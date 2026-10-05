# -*- coding: utf-8 -*-
"""Apple 登录提供方 (Sign in with Apple, 授权码流 + 本机回调)。

流程:
1. 校验凭证: team_id / client_id (Service ID) / key_id / private_key 必须配置;
2. 用 .p8 私钥生成 ES256 签名 client_secret (JWT);
3. 启动本机回调, 打开浏览器到 Apple 授权页;
4. 回调拿到 code, 交换 id_token / access_token;
5. 解析 id_token 取 sub/email, 写入 AuthStore。

凭证 (环境变量 QXT_APPLE_* 优先, 或 <QXT_HOME>/auth-config.toml [apple]):
    team_id / client_id / key_id / private_key_path / redirect_uri

注册指引 (README「登录与凭证」):
    Apple Developer → Certificates, Identifiers & Profiles:
    1. Identifiers → Services IDs: 新建, 开启 Sign in with Apple;
    2. Keys → 新建 Sign in with Apple Key (启用 Service ID), 下载 .p8;
    3. 该 Service ID 的 Sign in with Apple 配置中填回调
       http://127.0.0.1:8765/callback。
"""
from __future__ import annotations

import base64
import json
import time
import webbrowser
from typing import Any, Dict, Optional
from urllib.parse import urlencode

import httpx

from .base import AuthError, AuthProvider, AuthResult, ProviderNotConfigured
from .callback import DEFAULT_CALLBACK_PORT, LocalCallbackServer

_AUTHORIZE_URL = "https://appleid.apple.com/auth/authorize"
_TOKEN_URL = "https://appleid.apple.com/auth/token"
_AUDIENCE = "https://appleid.apple.com"


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _decode_jwt_payload(token: str) -> Dict[str, Any]:
    """解析 JWT 的 payload 段 (id_token), 不做签名校验 (令牌来自 Apple 直连响应)。"""
    try:
        payload_b64 = token.split(".")[1]
        pad = "=" * (-len(payload_b64) % 4)
        raw = base64.urlsafe_b64decode(payload_b64 + pad)
        claims: Dict[str, Any] = json.loads(raw)
        return claims
    except Exception as exc:
        raise AuthError(f"解析 Apple id_token 失败: {exc}") from exc


def _make_client_secret(
    team_id: str, client_id: str, key_id: str, private_key_pem: bytes
) -> str:
    """用 .p8 私钥生成 Sign in with Apple 的 client_secret (ES256 JWT)。"""
    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
    except ImportError:
        raise AuthError(
            "Apple 登录需要 cryptography 库生成 client_secret, 请安装: "
            "pip install \"qingxiaotuan[crypto]\" (或 pip install cryptography)"
        ) from None

    now = int(time.time())
    header = {"alg": "ES256", "kid": key_id}
    payload = {
        "iss": team_id,
        "iat": now,
        "exp": now + 60 * 60 * 24 * 180,  # Apple 上限 6 个月
        "aud": _AUDIENCE,
        "sub": client_id,
    }
    h_b64 = _b64url(json.dumps(header, separators=(",", ":")).encode())
    p_b64 = _b64url(json.dumps(payload, separators=(",", ":")).encode())
    signing_input = f"{h_b64}.{p_b64}".encode("ascii")

    try:
        key = serialization.load_pem_private_key(private_key_pem, password=None)
        assert isinstance(key, ec.EllipticCurvePrivateKey)
        der_sig = key.sign(signing_input, ec.ECDSA(hashes.SHA256()))
        r, s = decode_dss_signature(der_sig)
        raw_sig = r.to_bytes(32, "big") + s.to_bytes(32, "big")
    except Exception as exc:
        raise AuthError(f"生成 Apple client_secret 失败 (私钥无效?): {exc}") from exc
    return f"{signing_input.decode('ascii')}.{_b64url(raw_sig)}"


class AppleSignInProvider(AuthProvider):
    """Sign in with Apple 登录。"""

    name = "apple"
    display_name = "Apple"
    description = "Apple 登录 (Sign in with Apple, 浏览器授权)"

    @staticmethod
    def _env_map() -> Dict[str, str]:
        return {
            "QXT_APPLE_TEAM_ID": "team_id",
            "QXT_APPLE_CLIENT_ID": "client_id",
            "QXT_APPLE_KEY_ID": "key_id",
            "QXT_APPLE_PRIVATE_KEY_PATH": "private_key_path",
            "QXT_APPLE_REDIRECT_URI": "redirect_uri",
        }

    # ------------------------------------------------------------- 工具
    def _configured(self) -> bool:
        creds = self.credentials()
        return bool(creds.get("team_id") and creds.get("client_id") and creds.get("key_id"))

    def _redirect_uri(self, port: int = DEFAULT_CALLBACK_PORT) -> str:
        creds = self.credentials()
        return creds.get("redirect_uri") or f"http://127.0.0.1:{port}/callback"

    def _load_private_key(self) -> bytes:
        creds = self.credentials()
        path = creds.get("private_key_path")
        if not path:
            raise ProviderNotConfigured(
                "Apple 登录缺少 private_key_path (下载的 AuthKey.p8 路径)。"
            )
        try:
            from pathlib import Path

            return Path(path).expanduser().read_bytes()
        except OSError as exc:
            raise AuthError(f"读取 Apple 私钥失败 ({path}): {exc}") from exc

    # ------------------------------------------------------------- 登录
    def login(self) -> AuthResult:
        creds = self.credentials()
        team_id = creds.get("team_id")
        client_id = creds.get("client_id")
        key_id = creds.get("key_id")
        if not (team_id and client_id and key_id):
            raise ProviderNotConfigured(
                "Apple 登录尚未配置凭证 (team_id / client_id / key_id)。\n"
                "在 Apple Developer 创建 Service ID + Sign in with Apple Key 后, "
                "将三项写入 <QXT_HOME>/auth-config.toml [apple] 或 QXT_APPLE_* 环境变量。"
            )

        client_secret = _make_client_secret(
            team_id, client_id, key_id, self._load_private_key()
        )

        with LocalCallbackServer() as cb:
            params = {
                "response_type": "code",
                "client_id": client_id,
                "redirect_uri": self._redirect_uri(cb.port),
                "scope": "name email",
                "response_mode": "query",
            }
            url = f"{_AUTHORIZE_URL}?{urlencode(params)}"
            try:
                opened = webbrowser.open(url)
            except Exception:
                opened = False
            if not opened:
                raise AuthError(f"无法自动打开浏览器, 请手动访问:\n{url}")
            code = cb.wait()

        try:
            resp = httpx.post(
                _TOKEN_URL,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "redirect_uri": self._redirect_uri(),
                },
                headers={"Accept": "application/json"},
                timeout=30,
            )
        except httpx.HTTPError as exc:
            raise AuthError(f"请求 Apple 令牌失败: {exc}") from exc
        if resp.status_code != 200:
            raise AuthError(f"Apple 令牌交换失败: {resp.status_code} {resp.text[:300]}")

        tok = resp.json()
        id_token = tok.get("id_token")
        if not id_token:
            raise AuthError(f"Apple 未返回 id_token: {tok}")
        claims = _decode_jwt_payload(id_token)
        sub = claims.get("sub", "")
        email = claims.get("email", "") or ""

        self.store.set(
            "apple",
            {
                "token": tok.get("access_token", ""),
                "refresh_token": tok.get("refresh_token", ""),
                "id_token": id_token,
                "token_type": tok.get("token_type", "bearer"),
                "expires_in": tok.get("expires_in"),
                "sub": sub,
                "email": email,
                "email_verified": bool(claims.get("email_verified")),
                "login": email or f"apple:{sub}",
                "display_name": email or sub,
                "avatar_url": "",
            },
        )
        return AuthResult(
            provider="apple",
            login=email or f"apple:{sub}",
            display_name=email or sub,
            extra={"sub": sub, "email": email},
        )
