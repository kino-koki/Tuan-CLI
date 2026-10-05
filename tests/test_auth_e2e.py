# -*- coding: utf-8 -*-
"""三提供方登录的端到端状态机测试 (不依赖真实网络/浏览器)。

验证「理论上第三方服务器登录验证功能正常」:
- DeepSeek: 打开 chat.deepseek.com → 粘贴会话令牌 → 写入 AuthStore;
- GitHub:   授权 URL 生成 (PKCE) → 浏览器授权 → 回调 code → 令牌交换 → 用户查询 → 写入;
- Apple:    ES256 client_secret 生成 → 浏览器授权 → 回调 code → id_token 解析 → 写入。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import httpx
import pytest

from qingxiaotuan.auth.apple import AppleSignInProvider, _decode_jwt_payload, _make_client_secret
from qingxiaotuan.auth.deepseek import DeepSeekWebProvider
from qingxiaotuan.auth.github import GitHubOAuthProvider
from qingxiaotuan.auth.store import AuthStore

# ------------------------------------------------------------- 浏览器桩


class OpenedUrls:
    def __init__(self) -> None:
        self.urls: List[str] = []

    def open(self, url: str) -> bool:
        self.urls.append(url)
        return True


class FakeCallbackServer:
    """替换 LocalCallbackServer: 固定端口 + 直接返回预置 code。"""

    def __init__(self, code: str = "auth-code-123") -> None:
        self.code = code
        self.port = 8765

    def __enter__(self):
        return self

    def __exit__(self, *exc: Any) -> None:
        return None

    def wait(self) -> str:
        return self.code


# ------------------------------------------------------------- DeepSeek


def test_deepseek_login_opens_web_and_saves_token(tmp_path, monkeypatch) -> None:
    """实测链接: login 打开 chat.deepseek.com; 粘贴令牌后写入 AuthStore。"""
    opened = OpenedUrls()
    monkeypatch.setattr("qingxiaotuan.auth.deepseek.webbrowser.open", opened.open)
    store = AuthStore(home=tmp_path)
    provider = DeepSeekWebProvider(home=tmp_path, store=store)
    monkeypatch.setattr(provider, "_ask_token", lambda prompt: "ds-web-token-xyz")

    result = provider.login()

    assert opened.urls == ["https://chat.deepseek.com"]
    acc = store.get("deepseek")
    assert acc is not None
    assert acc["token"] == "ds-web-token-xyz"
    assert acc["login"] == "deepseek-web"
    assert result.provider == "deepseek"
    # auth.json 落盘可复读
    assert AuthStore(home=tmp_path).get("deepseek")["token"] == "ds-web-token-xyz"


def test_deepseek_login_uses_presaved_session_token(tmp_path, monkeypatch) -> None:
    """TOML 预写 session_token: 免交互直接登录, 不打开浏览器。"""
    opened = OpenedUrls()
    monkeypatch.setattr("qingxiaotuan.auth.deepseek.webbrowser.open", opened.open)
    cfg = tmp_path / "auth-config.toml"
    cfg.write_text('[deepseek]\nsession_token = "from-toml"\nlogin = "me@deepseek"\n', encoding="utf-8")
    store = AuthStore(home=tmp_path)
    provider = DeepSeekWebProvider(home=tmp_path, store=store)
    monkeypatch.setattr(provider, "_ask_token", lambda prompt: (_ for _ in ()).throw(AssertionError("不应询问")))

    result = provider.login()

    assert opened.urls == []
    assert store.get("deepseek")["token"] == "from-toml"
    assert store.get("deepseek")["login"] == "me@deepseek"
    assert result.login == "me@deepseek"


def test_deepseek_login_cancel(tmp_path, monkeypatch) -> None:
    """不输入令牌: 明确报错, 不写入登录态。"""
    monkeypatch.setattr("qingxiaotuan.auth.deepseek.webbrowser.open", lambda url: True)
    store = AuthStore(home=tmp_path)
    provider = DeepSeekWebProvider(home=tmp_path, store=store)
    monkeypatch.setattr(provider, "_ask_token", lambda prompt: "")

    from qingxiaotuan.auth.base import AuthError

    with pytest.raises(AuthError, match="登录已取消"):
        provider.login()
    assert store.get("deepseek") is None


# ------------------------------------------------------------- GitHub


def _github_env(monkeypatch) -> None:
    monkeypatch.setenv("QXT_GITHUB_CLIENT_ID", "gh-client-1")
    monkeypatch.setenv("QXT_GITHUB_CLIENT_SECRET", "gh-secret-1")
    monkeypatch.setenv("QXT_GITHUB_REDIRECT_URI", "http://127.0.0.1:8765/callback")


def test_github_login_full_flow(tmp_path, monkeypatch) -> None:
    """GitHub 全链路: PKCE 授权 URL → 回调 code → 令牌交换 → 用户查询 → 写入。"""
    _github_env(monkeypatch)
    opened = OpenedUrls()
    monkeypatch.setattr("qingxiaotuan.auth.github.webbrowser.open", opened.open)
    monkeypatch.setattr("qingxiaotuan.auth.github.LocalCallbackServer", FakeCallbackServer)
    store = AuthStore(home=tmp_path)
    provider = GitHubOAuthProvider(home=tmp_path, store=store)

    def _fake_post_json(url, data, headers=None):
        assert url == "https://github.com/login/oauth/access_token"
        assert data["code"] == "auth-code-123"
        assert data["client_id"] == "gh-client-1"
        assert data["code_verifier"]  # PKCE verifier 随请求回传
        return {
            "access_token": "gh-access-token",
            "token_type": "bearer",
            "scope": "read:user user:email",
        }

    monkeypatch.setattr(
        "qingxiaotuan.auth.github.GitHubOAuthProvider._post_json",
        staticmethod(_fake_post_json),
    )
    monkeypatch.setattr(
        "qingxiaotuan.auth.github.GitHubOAuthProvider._get_user",
        lambda self, tok: {
            "login": "octocat",
            "name": "Octo Cat",
            "avatar_url": "https://avatars.example/octo.png",
            "id": 12345,
            "email": "octo@example.com",
        },
    )

    result = provider.login()

    # 授权 URL: 包含 PKCE 挑战与回调
    assert len(opened.urls) == 1
    url = opened.urls[0]
    assert url.startswith("https://github.com/login/oauth/authorize?")
    assert "client_id=gh-client-1" in url
    assert "code_challenge=" in url and "code_challenge_method=S256" in url
    assert "scope=read%3Auser+user%3Aemail" in url or "user%3Aemail" in url
    assert "redirect_uri=http%3A%2F%2F127.0.0.1%3A8765%2Fcallback" in url

    acc = store.get("github")
    assert acc is not None
    assert acc["token"] == "gh-access-token"
    assert acc["login"] == "octocat"
    assert acc["scope"] == "read:user user:email"
    assert result.login == "octocat"


def test_github_login_not_configured(tmp_path) -> None:
    """未配置 client_id: ProviderNotConfigured, 不打开浏览器。"""
    from qingxiaotuan.auth.base import ProviderNotConfigured

    store = AuthStore(home=tmp_path)
    provider = GitHubOAuthProvider(home=tmp_path, store=store)
    with pytest.raises(ProviderNotConfigured, match="client_id"):
        provider.login()


# ------------------------------------------------------------- Apple


@pytest.fixture
def apple_key_file(tmp_path):
    """生成测试用 EC 私钥 (.p8 格式 PEM)。"""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    key = ec.generate_private_key(ec.SECP256R1())
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    p = tmp_path / "AuthKey_TESTKEY.p8"
    p.write_bytes(pem)
    return p


def _apple_env(monkeypatch, key_path) -> None:
    monkeypatch.setenv("QXT_APPLE_TEAM_ID", "TEAM123")
    monkeypatch.setenv("QXT_APPLE_CLIENT_ID", "com.example.cli")
    monkeypatch.setenv("QXT_APPLE_KEY_ID", "TESTKEY")
    monkeypatch.setenv("QXT_APPLE_PRIVATE_KEY_PATH", str(key_path))
    monkeypatch.setenv("QXT_APPLE_REDIRECT_URI", "http://127.0.0.1:8765/callback")


def test_apple_client_secret_es256(apple_key_file) -> None:
    """ES256 client_secret: 三段 JWT, payload 含 iss/aud/sub, 签名可解码。"""
    secret = _make_client_secret("TEAM123", "com.example.cli", "TESTKEY", apple_key_file.read_bytes())
    assert secret.count(".") == 2
    payload = _decode_jwt_payload(secret)
    assert payload["iss"] == "TEAM123"
    assert payload["aud"] == "https://appleid.apple.com"
    assert payload["sub"] == "com.example.cli"


def test_apple_login_full_flow(tmp_path, monkeypatch, apple_key_file) -> None:
    """Apple 全链路: client_secret → 授权 URL → 回调 → id_token 解析 → 写入。"""
    _apple_env(monkeypatch, apple_key_file)
    opened = OpenedUrls()
    monkeypatch.setattr("qingxiaotuan.auth.apple.webbrowser.open", opened.open)
    monkeypatch.setattr("qingxiaotuan.auth.apple.LocalCallbackServer", FakeCallbackServer)
    store = AuthStore(home=tmp_path)
    provider = AppleSignInProvider(home=tmp_path, store=store)

    def _fake_post(url, **kwargs):
        assert url == "https://appleid.apple.com/auth/token"
        assert kwargs["data"]["code"] == "auth-code-123"
        assert kwargs["data"]["client_secret"]  # ES256 JWT 已生成
        id_token = _make_fake_id_token("user-0001.abc", "alice@example.com")
        return httpx.Response(
            200,
            json={
                "access_token": "apple-access",
                "refresh_token": "apple-refresh",
                "id_token": id_token,
                "token_type": "bearer",
                "expires_in": 3600,
            },
        )

    monkeypatch.setattr("qingxiaotuan.auth.apple.httpx.post", _fake_post)

    result = provider.login()

    assert len(opened.urls) == 1
    url = opened.urls[0]
    assert url.startswith("https://appleid.apple.com/auth/authorize?")
    assert "client_id=com.example.cli" in url
    assert "response_type=code" in url
    assert "scope=name+email" in url

    acc = store.get("apple")
    assert acc is not None
    assert acc["sub"] == "user-0001.abc"
    assert acc["email"] == "alice@example.com"
    assert acc["login"] == "alice@example.com"
    assert acc["token"] == "apple-access"
    assert result.login == "alice@example.com"


def test_apple_login_not_configured(tmp_path) -> None:
    """未配置凭证: ProviderNotConfigured。"""
    from qingxiaotuan.auth.base import ProviderNotConfigured

    store = AuthStore(home=tmp_path)
    provider = AppleSignInProvider(home=tmp_path, store=store)
    with pytest.raises(ProviderNotConfigured, match="team_id"):
        provider.login()


def _make_fake_id_token(sub: str, email: str) -> str:
    """构造签名不校验的假 id_token (payload 含 sub/email)。"""
    import base64
    import json
    import time

    def b64(d: Dict[str, Any]) -> str:
        return base64.urlsafe_b64encode(json.dumps(d, separators=(",", ":")).encode()).rstrip(b"=").decode()

    header = b64({"alg": "RS256", "kid": "FAKE"})
    payload = b64(
        {
            "iss": "https://appleid.apple.com",
            "aud": "com.example.cli",
            "exp": int(time.time()) + 3600,
            "sub": sub,
            "email": email,
            "email_verified": True,
        }
    )
    return f"{header}.{payload}.fakesig"
