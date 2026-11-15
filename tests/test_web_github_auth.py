# -*- coding: utf-8 -*-
"""GitHub 设备流登录 (Web) 端到端测试 —— **全部 mock 网络传输**, 不访问真 github.com。"""
import json
import threading
import time
import urllib.request

import pytest

from tuan_cli.web import server as ws_mod
from tuan_cli.web.server import WebServer
from tuan_cli.web.web_sessions_auth import (
    WebAuthStore,
    build_set_cookie_header,
    parse_session_cookie,
    COOKIE_NAME,
)

# 假身份 + 假 token (模拟 GitHub 返回体, 绝不触发真实网络)
_FAKE_TOKEN = "gho_fake_token_123"
_FAKE_USER = {"login": "alice", "id": 42, "name": "Alice",
              "avatar_url": "https://avatars.githubusercontent.com/u/42"}


@pytest.fixture()
def server(tmp_path):
    ws_mod._SESSIONS.clear()
    srv = WebServer(kernel=None, workspace=str(tmp_path), port=0)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    for _ in range(50):
        if srv._httpd is not None:
            break
        time.sleep(0.05)
    yield srv
    if srv._httpd is not None:
        try:
            srv._httpd.shutdown()
        except Exception:  # noqa: BLE001
            pass
        srv._httpd.server_close()
    ws_mod._SESSIONS.clear()


def _post(url, body, headers=None):
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json",
                                          **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read().decode("utf-8")), dict(r.getheaders())
    except urllib.error.HTTPError as e:
        return json.loads(e.read().decode("utf-8")), dict(e.getheaders())


def _get(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read().decode("utf-8")), dict(r.getheaders())
    except urllib.error.HTTPError as e:
        return json.loads(e.read().decode("utf-8")), dict(e.getheaders())


# ================================================================ WebAuthStore 单元

def test_webauthstore_roundtrip_and_expiry(tmp_path):
    store = WebAuthStore(tmp_path / ".tuan" / "web_auth.json")
    sid = store.create_session(_FAKE_USER, _FAKE_TOKEN)
    ident = store.verify_session(sid)
    assert ident["login"] == "alice"
    assert ident["id"] == 42
    # 返回体不含 token
    assert "token" not in ident
    # token 可单独取
    assert store.get_token(sid) == _FAKE_TOKEN
    # 坏 session → None (fail-closed)
    assert store.verify_session("no-such-session") is None
    assert store.verify_session("") is None
    # 登出后失效
    store.delete_session(sid)
    assert store.verify_session(sid) is None


def test_webauthstore_persists_across_instances(tmp_path):
    f = tmp_path / ".tuan" / "web_auth.json"
    sid = WebAuthStore(f).create_session(_FAKE_USER, _FAKE_TOKEN)
    # 新实例从磁盘加载
    assert WebAuthStore(f).verify_session(sid)["login"] == "alice"


# ================================================================ Cookie 编解码

def test_set_cookie_flags():
    hdr = build_set_cookie_header("abc", secure=False)
    assert hdr.startswith(f"{COOKIE_NAME}=abc")
    assert "HttpOnly" in hdr and "SameSite=Lax" in hdr and "Path=/" in hdr
    assert "Secure" not in hdr  # http 不加
    secure_hdr = build_set_cookie_header("abc", secure=True)
    assert "Secure" in secure_hdr


def test_parse_session_cookie():
    assert parse_session_cookie("other=1; tuan_session=xyz") == "xyz"
    assert parse_session_cookie(None) is None
    assert parse_session_cookie("foo=bar") is None


# ================================================================ 端到端 (mock 传输)

def test_auth_status_unconfigured(server):
    """未配置 TUAN_GITHUB_CLIENT_ID → auth_optional:true。"""
    body, _ = _get(f"http://127.0.0.1:{server.port}/api/auth/status")
    assert body["authenticated"] is False
    assert body.get("auth_optional") is True


def test_full_device_flow_success(server, monkeypatch):
    # 临时让 github_configured() = True (绕过占位符 client_id 检查)
    monkeypatch.setattr(WebServer, "github_configured", staticmethod(lambda: True))

    # 直接 patch server 里引用的传输层符号 (start/poll/identity), 绝不发真实网络请求。
    calls = {"n": 0}

    def fake_start(config):
        return type("DA", (), {
            "user_code": "ABCD-1234",
            "device_code": "dev-xyz",
            "verification_uri": "https://github.com/login/device",
            "verification_uri_complete": "https://github.com/login/device?user_code=ABCD-1234",
            "expires_in": 900,
            "interval": 5,
        })()

    def fake_poll_once(device_code, config):
        calls["n"] += 1
        if calls["n"] == 1:
            return {"status": "pending"}
        token = type("T", (), {"access_token": _FAKE_TOKEN})()
        return {"status": "ok", "token": token}

    def fake_identity(token, include_orgs=True):
        assert token == _FAKE_TOKEN
        return dict(_FAKE_USER)

    monkeypatch.setattr(ws_mod, "_gh_start_device_flow", fake_start)
    monkeypatch.setattr(ws_mod, "_gh_poll_once", fake_poll_once)
    monkeypatch.setattr(ws_mod, "_gh_fetch_identity", fake_identity)

    # 1) start
    start_body, _ = _post(f"http://127.0.0.1:{server.port}/api/auth/github/start", {})
    assert "device_auth" in start_body, f"unexpected start response: {start_body}"
    da = start_body["device_auth"]
    assert da["user_code"] == "ABCD-1234"
    assert da["verification_uri"] == "https://github.com/login/device"

    # 2) poll (第一次 pending, 第二次成功)
    p1, _ = _post(f"http://127.0.0.1:{server.port}/api/auth/github/poll",
                  {"device_code": "dev-xyz"})
    assert p1.get("pending") is True

    p2, headers = _post(f"http://127.0.0.1:{server.port}/api/auth/github/poll",
                        {"device_code": "dev-xyz"})
    assert p2["ok"] is True and p2["pending"] is False
    assert p2["login"] == "alice"
    # Cookie 已下发且 HttpOnly
    set_cookie = headers.get("Set-Cookie") or headers.get("set-cookie")
    assert set_cookie and COOKIE_NAME in set_cookie and "HttpOnly" in set_cookie
    cookie_val = parse_session_cookie(set_cookie)
    assert cookie_val

    # 3) /api/auth/status 带 Cookie → 已登录
    status_body, _ = _get(f"http://127.0.0.1:{server.port}/api/auth/status",
                          headers={"Cookie": f"{COOKIE_NAME}={cookie_val}"})
    assert status_body["authenticated"] is True
    assert status_body["login"] == "alice"
    assert "token" not in status_body  # token 不外泄

    # 4) logout 清除
    req = urllib.request.Request(
        f"http://127.0.0.1:{server.port}/api/auth/logout", data=b"{}",
        headers={"Content-Type": "application/json",
                 "Cookie": f"{COOKIE_NAME}={cookie_val}"}, method="POST")
    with urllib.request.urlopen(req, timeout=10) as r:
        r.read()
    status_after, _ = _get(f"http://127.0.0.1:{server.port}/api/auth/status",
                           headers={"Cookie": f"{COOKIE_NAME}={cookie_val}"})
    assert status_after["authenticated"] is False


def test_poll_missing_device_code(server, monkeypatch):
    monkeypatch.setattr(WebServer, "github_configured", staticmethod(lambda: True))
    body, _ = _post(f"http://127.0.0.1:{server.port}/api/auth/github/poll", {})
    assert body["ok"] is False


def test_start_unconfigured_returns_400(server):
    body, _ = _post(f"http://127.0.0.1:{server.port}/api/auth/github/start", {})
    assert body["ok"] is False
