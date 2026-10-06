# -*- coding: utf-8 -*-
"""登录体系测试: 存储 / 提供方注册 / GitHub+Apple+DeepSeek 登录流程 (mock) / CLI。"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, Optional

import pytest

from qingxiaotuan.auth import (
    AuthError,
    AuthStore,
    ProviderNotConfigured,
    get_provider,
    list_providers,
)
from qingxiaotuan.auth import base as auth_base
from qingxiaotuan.auth import github as gh_mod
from qingxiaotuan.auth import apple as apple_mod
from qingxiaotuan.auth import deepseek as ds_mod
from qingxiaotuan.auth import callback as cb_mod


@pytest.fixture()
def store(tmp_path: Path) -> AuthStore:
    return AuthStore(home=tmp_path)


# ------------------------------------------------------------- 存储


def test_store_empty(store: AuthStore) -> None:
    assert store.load()["accounts"] == {}
    assert store.get("github") is None
    assert not store.is_logged_in("github")


def test_store_set_get_remove(store: AuthStore) -> None:
    store.set("github", {"token": "t1", "login": "kino-koki"})
    acc = store.get("github")
    assert acc is not None
    assert acc["token"] == "t1"
    assert acc["login"] == "kino-koki"
    assert "created_at" in acc and "updated_at" in acc
    assert store.is_logged_in("github")
    assert store.remove("github") is True
    assert store.remove("github") is False
    assert store.get("github") is None


def test_store_corrupt_file(tmp_path: Path) -> None:
    p = tmp_path / "auth.json"
    p.write_text("not-json{{", encoding="utf-8")
    store = AuthStore(home=tmp_path)
    assert store.load()["accounts"] == {}  # 损坏 → 空结构, 不抛异常


def test_store_clear(store: AuthStore) -> None:
    store.set("apple", {"token": "a"})
    store.set("github", {"token": "g"})
    assert len(store.list_accounts()) == 2
    store.clear()
    assert store.list_accounts() == {}


# ------------------------------------------------------------- 注册表


def test_providers_registered() -> None:
    names = {p["name"] for p in list_providers()}
    assert {"github", "apple", "deepseek"} <= names


def test_get_provider_unknown() -> None:
    with pytest.raises(AuthError):
        get_provider("nonexistent")


# ------------------------------------------------------------- 凭证读取


def test_credentials_env(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("QXT_GITHUB_CLIENT_ID", "env-id")
    provider = get_provider("github", home=tmp_path)
    assert provider.credentials()["client_id"] == "env-id"


def test_credentials_toml(tmp_path: Path) -> None:
    (tmp_path / "auth-config.toml").write_text(
        '[github]\nclient_id = "toml-id"\nclient_secret = "toml-secret"\n',
        encoding="utf-8",
    )
    provider = get_provider("github", home=tmp_path)
    creds = provider.credentials()
    assert creds["client_id"] == "toml-id"
    assert creds["client_secret"] == "toml-secret"


def test_credentials_env_overrides_toml(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / "auth-config.toml").write_text(
        '[github]\nclient_id = "toml-id"\n', encoding="utf-8"
    )
    monkeypatch.setenv("QXT_GITHUB_CLIENT_ID", "env-id")
    provider = get_provider("github", home=tmp_path)
    assert provider.credentials()["client_id"] == "env-id"


# ------------------------------------------------------------- GitHub OAuth (mock)


class _FakeCallback:
    """替代 LocalCallbackServer: 进入即返回, wait 直接给 code。"""

    def __init__(self, code: str = "fake-code", port: int = 8765) -> None:
        self.code = code
        self.port = port

    def __enter__(self) -> "_FakeCallback":
        return self

    def __exit__(self, *exc) -> None:
        pass

    @property
    def redirect_uri(self) -> str:
        return f"http://127.0.0.1:{self.port}/callback"

    def wait(self, timeout: Optional[float] = None) -> str:
        return self.code


def _mock_github_flow(monkeypatch, tmp_path: Path, user: Dict[str, Any]) -> Dict[str, Any]:
    """把 GitHub 登录的浏览器/回调/HTTP 全部打桩, 返回 httpx 收到的请求记录。"""
    (tmp_path / "auth-config.toml").write_text(
        '[github]\nclient_id = "test-id"\nclient_secret = "test-secret"\n',
        encoding="utf-8",
    )
    requests: Dict[str, Any] = {}

    monkeypatch.setattr(gh_mod.webbrowser, "open", lambda url: True)
    monkeypatch.setattr(gh_mod, "LocalCallbackServer", _FakeCallback)

    def _fake_post(url, data=None, headers=None, timeout=None, follow_redirects=None):
        requests["post_url"] = url
        requests["post_data"] = data
        assert url == "https://github.com/login/oauth/access_token"
        return _FakeResp({"access_token": "tok-123", "scope": "read:user", "token_type": "bearer"})

    def _fake_get(url, headers=None, timeout=None):
        requests["get_url"] = url
        requests["get_headers"] = headers
        assert url == "https://api.github.com/user"
        return _FakeResp(user)

    monkeypatch.setattr(gh_mod.httpx, "post", _fake_post)
    monkeypatch.setattr(gh_mod.httpx, "get", _fake_get)
    return requests


class _FakeResp:
    def __init__(self, payload: Dict[str, Any], status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def json(self) -> Dict[str, Any]:
        return self._payload

    @property
    def text(self) -> str:
        return json.dumps(self._payload)


def test_github_login_success(monkeypatch, tmp_path: Path) -> None:
    requests = _mock_github_flow(
        monkeypatch, tmp_path,
        {"login": "kino-koki", "name": "Kino", "avatar_url": "https://a/1", "id": 42, "email": "k@x.io"},
    )
    provider = get_provider("github", home=tmp_path)
    result = provider.login()

    assert result.provider == "github"
    assert result.login == "kino-koki"
    # 凭证里带 client_secret → 交换请求应包含它
    assert requests["post_data"]["client_secret"] == "test-secret"
    assert "code_verifier" in requests["post_data"]
    acc = provider.store.get("github")
    assert acc is not None
    assert acc["token"] == "tok-123"
    assert provider.status()["login"] == "kino-koki"
    # status 不应暴露原始令牌
    assert "token" not in provider.status()


def test_github_login_not_configured(tmp_path: Path) -> None:
    provider = get_provider("github", home=tmp_path)  # 无凭证
    with pytest.raises(ProviderNotConfigured):
        provider.login()


def test_github_login_token_error(monkeypatch, tmp_path: Path) -> None:
    _mock_github_flow(monkeypatch, tmp_path, {})

    def _fake_post(url, data=None, headers=None, timeout=None, follow_redirects=None):
        return _FakeResp({"error_description": "bad code"})

    monkeypatch.setattr(gh_mod.httpx, "post", _fake_post)
    provider = get_provider("github", home=tmp_path)
    with pytest.raises(AuthError, match="换取令牌失败"):
        provider.login()


def test_pkce_challenge_format() -> None:
    v = "a" * 43
    ch = gh_mod._s256(v)  # noqa: SLF001
    assert len(ch) == 43  # S256 base64url 无 padding, 长度恒 43


# ------------------------------------------------------------- Apple (mock)


def test_apple_client_secret_jwt() -> None:
    # 用 cryptography 生成测试私钥, 验证 JWT 结构
    pytest.importorskip("cryptography")
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    key = ec.generate_private_key(ec.SECP256R1())
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    secret = apple_mod._make_client_secret(  # noqa: SLF001
        "TEAM", "com.example.app", "KID", pem
    )
    parts = secret.split(".")
    assert len(parts) == 3
    import base64

    payload_b64 = parts[1]
    pad = "=" * (-len(payload_b64) % 4)
    claims = json.loads(base64.urlsafe_b64decode(payload_b64 + pad))
    assert claims["iss"] == "TEAM"
    assert claims["sub"] == "com.example.app"
    assert claims["aud"] == "https://appleid.apple.com"
    assert claims["exp"] > int(time.time())


def test_apple_login_success(monkeypatch, tmp_path: Path) -> None:
    pytest.importorskip("cryptography")
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    key = ec.generate_private_key(ec.SECP256R1())
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    key_path = tmp_path / "AuthKey.p8"
    key_path.write_bytes(pem)

    (tmp_path / "auth-config.toml").write_text(
        "[apple]\n"
        f'team_id = "TEAM"\nclient_id = "com.example.app"\nkey_id = "KID"\n'
        f'private_key_path = "{key_path.as_posix()}"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(apple_mod.webbrowser, "open", lambda url: True)
    monkeypatch.setattr(apple_mod, "LocalCallbackServer", _FakeCallback)

    id_token = (
        "eyJhbGciOiJFUzI1NiJ9."
        + apple_mod._b64url(  # noqa: SLF001
            json.dumps({"sub": "001234.abc", "email": "user@privaterelay.apple.com"}).encode()
        )
        + ".sig"
    )
    token_payload = {"id_token": id_token, "access_token": "at-1", "refresh_token": "rt-1"}

    def _fake_post(url, data=None, headers=None, timeout=None):
        assert url == "https://appleid.apple.com/auth/token"
        assert data["client_id"] == "com.example.app"
        assert data["grant_type"] == "authorization_code"
        assert data["client_secret"].count(".") == 2  # JWT
        return _FakeResp(token_payload)

    monkeypatch.setattr(apple_mod.httpx, "post", _fake_post)
    provider = get_provider("apple", home=tmp_path)
    result = provider.login()

    assert result.provider == "apple"
    assert "privaterelay.apple.com" in result.login
    acc = provider.store.get("apple")
    assert acc is not None
    assert acc["sub"] == "001234.abc"
    assert acc["refresh_token"] == "rt-1"


def test_apple_not_configured(tmp_path: Path) -> None:
    provider = get_provider("apple", home=tmp_path)
    with pytest.raises(ProviderNotConfigured):
        provider.login()


# ------------------------------------------------------------- DeepSeek 官方 API (mock)


def test_deepseek_login_paste_api_key(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(ds_mod.webbrowser, "open", lambda url: True)
    monkeypatch.setattr(
        ds_mod.DeepSeekAPIProvider, "_ask_api_key", lambda self, prompt: "sk-test-abc"
    )
    provider = get_provider("deepseek", home=tmp_path)
    result = provider.login()
    assert result.provider == "deepseek"
    acc = provider.store.get("deepseek")
    assert acc is not None
    assert acc["token"] == "sk-test-abc"
    assert provider.status()["login"] == "deepseek-api"


def test_deepseek_login_from_toml(tmp_path: Path) -> None:
    (tmp_path / "auth-config.toml").write_text(
        '[deepseek]\napi_key = "sk-pre-token"\nlogin = "me@deepseek"\n',
        encoding="utf-8",
    )
    provider = get_provider("deepseek", home=tmp_path)
    result = provider.login()
    assert result.login == "me@deepseek"
    assert provider.store.get("deepseek")["token"] == "sk-pre-token"


def test_deepseek_login_cancel(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(ds_mod.webbrowser, "open", lambda url: True)
    monkeypatch.setattr(ds_mod.DeepSeekAPIProvider, "_ask_api_key", lambda self, p: "")
    provider = get_provider("deepseek", home=tmp_path)
    with pytest.raises(AuthError, match="取消"):
        provider.login()


# ------------------------------------------------------------- CLI 逻辑


def test_cli_whoami(tmp_path: Path, capsys) -> None:
    from qingxiaotuan.cli import cmd_login

    class _A:
        pass

    args = _A()
    rc = cmd_login.cmd_whoami(args)
    assert rc == 0
    out = capsys.readouterr().out
    assert "未登录" in out


def test_cli_logout_all(monkeypatch, tmp_path: Path) -> None:
    from qingxiaotuan.cli import cmd_login

    store = AuthStore(home=tmp_path)
    store.set("github", {"token": "x", "login": "u"})
    store.set("apple", {"token": "y", "login": "v"})

    from qingxiaotuan.auth import store as store_mod

    monkeypatch.setattr(store_mod, "home_dir", lambda: tmp_path)

    class _A:
        provider: Optional[str] = None

    args = _A()
    rc = cmd_login.cmd_logout(args)
    assert rc == 0
    assert store.list_accounts() == {}


def test_cli_login_unknown_provider(tmp_path: Path, capsys) -> None:
    from qingxiaotuan.cli import cmd_login

    class _A:
        provider = "bogus"

    rc = cmd_login.cmd_login(_A())
    assert rc == 0
    out = capsys.readouterr().out
    assert "未知提供方" in out


def test_cli_login_not_configured(monkeypatch, tmp_path: Path, capsys) -> None:
    from qingxiaotuan.cli import cmd_login

    from qingxiaotuan.auth import base as base_mod

    monkeypatch.setattr(base_mod, "home_dir", lambda: tmp_path)

    class _A:
        provider = "github"

    rc = cmd_login.cmd_login(_A())
    assert rc == 1
    out = capsys.readouterr().out
    assert "未配置" in out


# ------------------------------------------------------------- /web 端点


def test_web_auth_status_and_logout(monkeypatch, tmp_path: Path) -> None:
    """/api/auth/status 汇总三提供方; /api/auth/logout 清除 (web 层)。"""
    import threading
    import urllib.request

    from qingxiaotuan.auth import store as store_mod
    from qingxiaotuan.auth import base as base_mod
    from qingxiaotuan.web.server import WebServer

    monkeypatch.setattr(store_mod, "home_dir", lambda: tmp_path)
    monkeypatch.setattr(base_mod, "home_dir", lambda: tmp_path)

    srv = WebServer(kernel=None, workspace=str(tmp_path), port=0)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    for _ in range(50):
        if srv._httpd is not None:
            break
        time.sleep(0.05)
    try:
        base = f"http://127.0.0.1:{srv.port}"

        # status: 三个提供方, 初始均未登录
        with urllib.request.urlopen(base + "/api/auth/status", timeout=10) as r:
            j = json.loads(r.read().decode("utf-8"))
        assert j["ok"] is True
        accs = j["accounts"]
        assert set(accs) == {"github", "apple", "deepseek"}
        for name in ("github", "apple", "deepseek"):
            assert accs[name]["logged_in"] is False

        # 未配置时登录 -> ok False + 指引
        req = urllib.request.Request(
            base + "/api/auth/login",
            data=json.dumps({"provider": "github"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=30) as r:
            j = json.loads(r.read().decode("utf-8"))
        assert j["ok"] is False
        assert "未配置" in j["error"]

        # 未知提供方
        req = urllib.request.Request(
            base + "/api/auth/login",
            data=json.dumps({"provider": "bogus"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            j = json.loads(r.read().decode("utf-8"))
        assert j["ok"] is False
        assert "未知提供方" in j["error"]

        # 预置一个登录态, 通过 /api/auth/logout 清除 (省略 provider = 全清)
        AuthStore(home=tmp_path).set("github", {"token": "t", "login": "u"})
        req = urllib.request.Request(
            base + "/api/auth/logout",
            data=json.dumps({"provider": "github"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            j = json.loads(r.read().decode("utf-8"))
        assert j["ok"] is True and j["removed"] is True

        AuthStore(home=tmp_path).set("apple", {"token": "y", "login": "v"})
        req = urllib.request.Request(
            base + "/api/auth/logout",
            data=json.dumps({}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            j = json.loads(r.read().decode("utf-8"))
        assert j["ok"] is True and j["removed"] is True
        assert AuthStore(home=tmp_path).list_accounts() == {}
    finally:
        if srv._httpd is not None:
            try:
                srv._httpd.shutdown()
            except Exception:  # noqa: BLE001
                pass
            srv._httpd.server_close()
