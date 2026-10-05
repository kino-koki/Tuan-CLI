# -*- coding: utf-8 -*-
"""GitHub OAuth 登录提供方 (授权码流 + PKCE + 本机回调)。

流程:
1. 校验凭证: client_id 必须已配置 (GitHub OAuth App);
2. 生成 PKCE code_verifier/code_challenge;
3. 启动本机回调服务器, 打开浏览器到 GitHub 授权页;
4. 回调拿到 code, 交换 access_token (支持 client_secret 或纯 PKCE);
5. 查询用户信息, 写入 AuthStore。

凭证 (环境变量 QXT_GITHUB_* 优先, 或 <QXT_HOME>/auth-config.toml [github]):
    client_id / client_secret / redirect_uri

注册指引 (README「登录与凭证」):
    GitHub → Settings → Developer settings → OAuth Apps → New OAuth App
    Homepage URL 任意;  Authorization callback URL 填
    http://127.0.0.1:8765/callback   (与 redirect_uri 一致, 端口可改)
"""
from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
import webbrowser
from typing import Any, Dict, Optional

import httpx

from .base import AuthError, AuthProvider, AuthResult, ProviderNotConfigured
from .callback import DEFAULT_CALLBACK_PORT, LocalCallbackServer
from .store import AuthStore

_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
_TOKEN_URL = "https://github.com/login/oauth/access_token"
_API_USER_URL = "https://api.github.com/user"
_SCOPE = "read:user user:email"


def _s256(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


class GitHubOAuthProvider(AuthProvider):
    """GitHub OAuth (PKCE) 登录。"""

    name = "github"
    display_name = "GitHub"
    description = "GitHub OAuth 登录 (授权码流 + PKCE, 浏览器授权)"

    @staticmethod
    def _env_map() -> Dict[str, str]:
        return {
            "QXT_GITHUB_CLIENT_ID": "client_id",
            "QXT_GITHUB_CLIENT_SECRET": "client_secret",
            "QXT_GITHUB_REDIRECT_URI": "redirect_uri",
        }

    # ------------------------------------------------------------- 工具
    def _configured(self) -> bool:
        return bool(self.credentials().get("client_id"))

    def _redirect_uri(self, port: int = DEFAULT_CALLBACK_PORT) -> str:
        creds = self.credentials()
        return creds.get("redirect_uri") or f"http://127.0.0.1:{port}/callback"

    @staticmethod
    def _post_json(url: str, data: Dict[str, Any], headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        try:
            resp = httpx.post(
                url,
                data=data,
                headers=headers or {},
                timeout=30,
                follow_redirects=True,
            )
        except httpx.HTTPError as exc:
            raise AuthError(f"请求 GitHub 失败: {exc}") from exc
        try:
            payload: Dict[str, Any] = resp.json()
            return payload
        except ValueError:
            raise AuthError(f"GitHub 返回异常: {resp.status_code} {resp.text[:200]}") from None

    # ------------------------------------------------------------- 登录
    def login(self) -> AuthResult:
        creds = self.credentials()
        client_id = creds.get("client_id")
        if not client_id:
            raise ProviderNotConfigured(
                "GitHub 尚未配置 OAuth App 凭证。\n"
                "1) GitHub → Settings → Developer settings → OAuth Apps → New OAuth App;\n"
                "2) Authorization callback URL 填 http://127.0.0.1:8765/callback;\n"
                "3) 将 client_id (与可选 client_secret) 写入 <QXT_HOME>/auth-config.toml "
                "或环境变量 QXT_GITHUB_CLIENT_ID / QXT_GITHUB_CLIENT_SECRET。"
            )

        verifier = secrets.token_urlsafe(48)
        challenge = _s256(verifier)

        with LocalCallbackServer() as cb:
            authorize_params = {
                "client_id": client_id,
                "redirect_uri": self._redirect_uri(cb.port),
                "response_type": "code",
                "scope": _SCOPE,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            }
            from urllib.parse import urlencode

            url = f"{_AUTHORIZE_URL}?{urlencode(authorize_params)}"
            try:
                opened = webbrowser.open(url)
            except Exception:
                opened = False
            if not opened:
                raise AuthError(f"无法自动打开浏览器, 请手动访问:\n{url}")
            code = cb.wait()

        token_data: Dict[str, Any] = {
            "client_id": client_id,
            "code": code,
            "redirect_uri": self._redirect_uri(),
            "code_verifier": verifier,
        }
        if creds.get("client_secret"):
            token_data["client_secret"] = creds["client_secret"]
        tok = self._post_json(
            _TOKEN_URL, token_data, headers={"Accept": "application/json"}
        )
        access_token = tok.get("access_token")
        if not access_token:
            raise AuthError(f"换取令牌失败: {tok.get('error_description', tok)}")

        user = self._get_user(access_token)
        scope = tok.get("scope", "")
        self.store.set(
            "github",
            {
                "token": access_token,
                "token_type": tok.get("token_type", "bearer"),
                "scope": scope,
                "login": user.get("login", ""),
                "display_name": user.get("name") or user.get("login", ""),
                "avatar_url": user.get("avatar_url", ""),
                "id": str(user.get("id", "")),
                "email": user.get("email", ""),
                "expires_at": None,  # GitHub access_token 不过期 (可 revoke)
            },
        )
        return AuthResult(
            provider="github",
            login=user.get("login", ""),
            display_name=user.get("name") or "",
            avatar_url=user.get("avatar_url", ""),
            extra={"id": str(user.get("id", "")), "scope": scope},
        )

    def _get_user(self, access_token: str) -> Dict[str, Any]:
        try:
            resp = httpx.get(
                _API_USER_URL,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
                timeout=30,
            )
        except httpx.HTTPError as exc:
            raise AuthError(f"查询 GitHub 用户失败: {exc}") from exc
        if resp.status_code != 200:
            raise AuthError(f"查询 GitHub 用户失败: {resp.status_code} {resp.text[:200]}")
        payload: Dict[str, Any] = resp.json()
        return payload

    # 测试注入点
    _http_client = None
