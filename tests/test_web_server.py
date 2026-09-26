# -*- coding: utf-8 -*-
"""Web 工作台端到端测试 (标准库 HTTP + SSE, 假 agent 工厂)。"""
import json
import threading
import time
import urllib.request

import pytest

from qingxiaotuan.web import server as ws_mod
from qingxiaotuan.web.server import WebServer


class _FakeAgent:
    def __init__(self):
        self.messages = []

    def run(self, user_input, stream=True, on_token=None, on_tool=None,
            on_tool_result=None, on_reason=None, on_error=None):
        for ch in "你好，这是流式回复":
            if on_token:
                on_token(ch)
        if on_tool:
            on_tool("read_file", '{"path": "src/main.py"}')
        if on_tool_result:
            on_tool_result("read_file", "def main(): pass")
        return "你好，这是流式回复"

    def cancel(self):
        pass


@pytest.fixture()
def server(tmp_path):
    ws_mod._SESSIONS.clear()
    srv = WebServer(kernel=None, workspace=str(tmp_path), port=0)
    srv.set_agent_factory(_FakeAgent)
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


def _get(url, expect_error=False):
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            return r.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        if expect_error:
            return e.read().decode("utf-8")
        raise


def _post(url, body, expect_error=False):
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if expect_error:
            return json.loads(e.read().decode("utf-8"))
        raise


def _delete(url, expect_error=False):
    req = urllib.request.Request(url, method="DELETE")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if expect_error:
            return json.loads(e.read().decode("utf-8"))
        raise


def _post_sse(url, body):
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8")


def _sse_payloads(sse):
    out = []
    for chunk in sse.split("\n\n"):
        ev, data = "", ""
        for line in chunk.splitlines():
            if line.startswith("event:"):
                ev = line[6:].strip()
            elif line.startswith("data:"):
                data = line[5:].strip()
        if data:
            out.append((ev, json.loads(data)))
    return out


def _url(server, path):
    return f"http://127.0.0.1:{server.port}{path}"


def _new_session(server):
    sse = _post_sse(_url(server, "/api/chat"), {"message": "hi"})
    events = _sse_payloads(sse)
    return [d["id"] for ev, d in events if ev == "session"][0]


def test_frontend_html(server):
    html = _get(_url(server, "/"))
    assert "<title>青小团 · Web 工作台</title>" in html
    assert "stream-cursor" in html
    assert "renderMd" in html  # markdown 渲染器
    assert "safety" in html    # 安全徽章


def test_info(server):
    info = json.loads(_get(_url(server, "/api/info")))
    assert info["ok"]
    assert "security" in info  # 安全状态字段


def test_chat_sse_flow(server):
    sse = _post_sse(_url(server, "/api/chat"), {"message": "hi"})
    events = _sse_payloads(sse)
    kinds = {ev for ev, _ in events}
    assert {"session", "delta", "tool", "tool_result", "done"} <= kinds
    delta = "".join(d for ev, d in events if ev == "delta")
    assert delta == "你好，这是流式回复"


def test_history_and_sessions(server):
    sid = _new_session(server)
    hist = json.loads(_get(_url(server, f"/api/history?session={sid}")))
    assert hist["ok"]
    assert [m["role"] for m in hist["messages"]] == ["user", "assistant"]
    sessions = json.loads(_get(_url(server, "/api/sessions")))
    assert any(s["id"] == sid for s in sessions["sessions"])


def test_clear_session(server):
    sid = _new_session(server)
    r = _post(_url(server, "/api/sessions/clear"), {"session": sid})
    assert r["ok"]
    hist = json.loads(_get(_url(server, f"/api/history?session={sid}")))
    assert hist["messages"] == []


def test_rename_session(server):
    sid = _new_session(server)
    r = _post(_url(server, "/api/sessions/rename"), {"session": sid, "title": "新标题"})
    assert r["ok"] and r["title"] == "新标题"
    sessions = json.loads(_get(_url(server, "/api/sessions")))
    hit = [s for s in sessions["sessions"] if s["id"] == sid][0]
    assert hit["title"] == "新标题"


def test_delete_session(server):
    sid = _new_session(server)
    r = _delete(_url(server, f"/api/sessions?session={sid}"))
    assert r["ok"]
    sessions = json.loads(_get(_url(server, "/api/sessions")))
    assert all(s["id"] != sid for s in sessions["sessions"])


def test_persistence_roundtrip(server, tmp_path):
    """会话持久化: 聊天后磁盘有快照, 新 server 实例可加载 (重启不丢)。"""
    sid = _new_session(server)
    disk = tmp_path / ".qxt" / "web_sessions.json"
    assert disk.exists(), "会话应落盘"
    data = json.loads(disk.read_text(encoding="utf-8"))
    assert sid in data
    assert data[sid]["messages"][-1]["role"] == "assistant"
    # 新实例 (模拟重启) 加载历史
    ws_mod._SESSIONS.clear()
    srv2 = WebServer(kernel=None, workspace=str(tmp_path), port=0)
    t2 = threading.Thread(target=srv2.serve_forever, daemon=True)
    t2.start()
    for _ in range(50):
        if srv2._httpd is not None:
            break
        time.sleep(0.05)
    try:
        assert srv2.load_sessions() >= 1
        hist = json.loads(_get(f"http://127.0.0.1:{srv2.port}/api/history?session={sid}"))
        assert hist["ok"] and len(hist["messages"]) == 2
    finally:
        if srv2._httpd is not None:
            try:
                srv2._httpd.shutdown()
            except Exception:  # noqa: BLE001
                pass
            srv2._httpd.server_close()
        ws_mod._SESSIONS.clear()


def test_frontend_features(server):
    """测试前端新功能: 主题切换、搜索框、导出按钮、文件上传。"""
    html = _get(_url(server, "/"))
    # 主题切换
    assert 'data-theme' in html
    assert 'btn-theme' in html
    assert 'localStorage' in html  # 主题持久化
    # 会话搜索
    assert 'searchbox' in html
    assert 'filterSessions' in html
    # 导出按钮
    assert 'btn-export' in html
    assert 'exportMarkdown' in html
    # 键盘快捷键
    assert 'ctrlKey' in html
    assert 'exportMarkdown' in html
    # 文件上传
    assert 'upload-btn' in html
    assert 'file-input' in html
    assert 'dragover' in html  # 拖拽上传
    assert 'dataUrl' in html  # 图片预览
    assert 'lightbox' in html  # 灯箱查看


def test_sessions_sorted_by_created(server):
    """会话列表按创建时间倒序排列。"""
    # 创建多个会话
    for msg in ["first", "second", "third"]:
        _new_session(server)
    sessions = json.loads(_get(_url(server, "/api/sessions")))
    ids = [s["id"] for s in sessions["sessions"]]
    # 最新创建的应该在前面 (因为有 created 字段)
    assert len(ids) >= 3
    # 检查 created 字段存在且递减
    created = [s["created"] for s in sessions["sessions"]]
    for i in range(len(created) - 1):
        assert created[i] >= created[i + 1]


def test_empty_session_validation(server):
    """空消息和空标题应被拒绝。"""
    # 空消息
    r = _post(_url(server, "/api/chat"), {"message": ""}, expect_error=True)
    assert r["ok"] is False
    # 空标题
    r = _post(_url(server, "/api/sessions/rename"), {"session": "x", "title": "  "}, expect_error=True)
    assert r["ok"] is False


def test_missing_session_operations(server):
    """对不存在的会话操作应返回 404。"""
    r = json.loads(_get(_url(server, "/api/history?session=nonexistent"), expect_error=True))
    assert r["ok"] is False
    r = _post(_url(server, "/api/sessions/clear"), {"session": "nonexistent"}, expect_error=True)
    assert r["ok"] is False
    r = _post(_url(server, "/api/sessions/rename"), {"session": "nonexistent", "title": "test"}, expect_error=True)
    assert r["ok"] is False
    r = _delete(_url(server, "/api/sessions?session=nonexistent"), expect_error=True)
    assert r["ok"] is False
