"""团队协作工具测试 —— 验证 4 个 team_* 工具真实挂接 CollaborationProtocol。"""

from __future__ import annotations

import urllib.error

import pytest

from tuan_cli.core.collaboration_protocol import (
    CollaborationProtocol,
    MessageType,
)
from tuan_cli.core.kernel import Kernel
from tuan_cli.tools.base import ToolContext, ToolRegistry
from tuan_cli.tools.team_tool import (
    TeamToolPlugin,
    build_team_list_members_tool,
    build_team_post_update_tool,
    build_team_read_updates_tool,
    build_team_share_note_tool,
)


# ------------------------------------------------------------------ fixtures


def _make_ctx(protocol: CollaborationProtocol) -> ToolContext:
    kernel = Kernel()
    kernel.provide("collaboration_protocol", protocol)
    return ToolContext(kernel=kernel, workspace=".")


@pytest.fixture()
def protocol() -> CollaborationProtocol:
    return CollaborationProtocol()


@pytest.fixture()
def ctx(protocol: CollaborationProtocol) -> ToolContext:
    return _make_ctx(protocol)


@pytest.fixture()
def registry() -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(build_team_share_note_tool())
    reg.register(build_team_post_update_tool())
    reg.register(build_team_read_updates_tool())
    reg.register(build_team_list_members_tool())
    return reg


# ------------------------------------------------------------------ team_share_note


def test_share_note_returns_version(protocol: CollaborationProtocol, ctx: ToolContext):
    out = build_team_share_note_tool().handler(ctx, key="doc:T1", note="会议纪要 v1")
    assert '已共享笔记 "doc:T1"' in out
    assert "v1" in out
    # 协议侧确实写入了
    assert protocol.read("doc:T1") == "会议纪要 v1"


def test_share_note_increments_version(protocol: CollaborationProtocol, ctx: ToolContext):
    tool = build_team_share_note_tool()
    tool.handler(ctx, key="doc:T1", note="v1")
    out = tool.handler(ctx, key="doc:T1", note="v2")
    assert "v2" in out
    assert protocol.read_version("doc:T1") == 2


def test_share_note_missing_key(ctx: ToolContext):
    out = build_team_share_note_tool().handler(ctx, key="", note="x")
    assert "[错误]" in out


# ------------------------------------------------------------------ team_post_update


def test_post_update_broadcast(protocol: CollaborationProtocol, ctx: ToolContext):
    out = build_team_post_update_tool().handler(
        ctx, sender="planner", update="开始分析阶段", priority="high",
    )
    assert "priority=high" in out
    assert "→ *" in out
    # 写入了 team:updates 键, msg_type=STATUS
    msgs = protocol.get_messages(msg_type=MessageType.STATUS)
    assert len(msgs) >= 1
    assert msgs[0].sender == "planner"


def test_post_update_directed_recipient(protocol: CollaborationProtocol, ctx: ToolContext):
    out = build_team_post_update_tool().handler(
        ctx, sender="planner", update="请评审",
        recipient="reviewer", priority="normal",
    )
    assert "→ reviewer" in out
    value = protocol.read("team:updates")
    assert "reviewer" in str(value)


def test_post_update_missing_sender(ctx: ToolContext):
    out = build_team_post_update_tool().handler(ctx, sender="", update="x")
    assert "[错误]" in out


# ------------------------------------------------------------------ team_read_updates


def test_read_updates_lists_messages(protocol: CollaborationProtocol, ctx: ToolContext):
    build_team_share_note_tool().handler(ctx, key="a", note="笔记甲")
    build_team_post_update_tool().handler(ctx, sender="alice", update="进展1")
    build_team_post_update_tool().handler(ctx, sender="bob", update="进展2")
    out = build_team_read_updates_tool().handler(ctx)
    assert "alice" in out and "bob" in out


def test_read_updates_filter_note(protocol: CollaborationProtocol, ctx: ToolContext):
    build_team_share_note_tool().handler(ctx, key="doc", note="文档内容")
    build_team_post_update_tool().handler(ctx, sender="alice", update="进度1")
    out = build_team_read_updates_tool().handler(ctx, msg_type="note")
    # 笔记以 ARTIFACT 类型入板; 更新以 STATUS 入板
    assert "doc" in out
    assert "文档内容" in out
    assert "进度1" not in out


def test_read_updates_filter_update(protocol: CollaborationProtocol, ctx: ToolContext):
    build_team_share_note_tool().handler(ctx, key="doc", note="文档内容")
    build_team_post_update_tool().handler(ctx, sender="alice", update="进度1")
    out = build_team_read_updates_tool().handler(ctx, msg_type="update")
    assert "进度1" in out
    assert "文档内容" not in out


def test_read_updates_single_key(protocol: CollaborationProtocol, ctx: ToolContext):
    build_team_share_note_tool().handler(ctx, key="target", note="特定键的值")
    build_team_share_note_tool().handler(ctx, key="other", note="另一个键的值")
    out = build_team_read_updates_tool().handler(ctx, key="target")
    assert "特定键的值" in out
    assert "另一个键的值" not in out


def test_read_updates_empty_board(protocol: CollaborationProtocol, ctx: ToolContext):
    out = build_team_read_updates_tool().handler(ctx)
    assert "暂无" in out


# ------------------------------------------------------------------ team_list_members


def test_list_members_distinct_senders(protocol: CollaborationProtocol, ctx: ToolContext):
    build_team_share_note_tool().handler(ctx, key="a", note="x", sender="alice")
    build_team_share_note_tool().handler(ctx, key="b", note="y", sender="bob")
    build_team_share_note_tool().handler(ctx, key="c", note="z", sender="agent")
    out = build_team_list_members_tool().handler(ctx)
    assert "团队成员 (3)" in out
    assert "alice" in out and "bob" in out and "agent" in out


def test_list_members_excludes_system(protocol: CollaborationProtocol, ctx: ToolContext):
    protocol.write("sys:boot", "init", sender="__system__")
    build_team_share_note_tool().handler(ctx, key="a", note="x", sender="alice")
    out = build_team_list_members_tool().handler(ctx)
    assert "__system__" not in out
    assert "alice" in out


def test_list_members_empty(protocol: CollaborationProtocol, ctx: ToolContext):
    out = build_team_list_members_tool().handler(ctx)
    assert "暂无" in out


# ------------------------------------------------------------------ 插件注册


def test_team_tool_plugin_registers_all_four():
    kernel = Kernel()
    kernel.provide("tool_registry", ToolRegistry())
    plugin = TeamToolPlugin()
    plugin.activate(kernel)
    registry = kernel.require("tool_registry")
    for name in (
        "team_share_note", "team_list_members",
        "team_post_update", "team_read_updates",
    ):
        assert registry.get(name) is not None, f"工具 {name} 未注册"


def test_builtin_tool_plugins_includes_team():
    from tuan_cli.tools import builtin_tool_plugins
    plugins = builtin_tool_plugins()
    assert any(isinstance(p, TeamToolPlugin) for p in plugins)


# ------------------------------------------------------------------ HTTP 端点


def test_team_http_board_and_post(tmp_path):
    """团队黑板 HTTP 端点: 无 kernel → fail-closed; 有 kernel → board/post 往返。"""
    import json
    import threading
    import time
    import urllib.error
    import urllib.request
    from tuan_cli.web import server as ws_mod
    from tuan_cli.web.server import WebServer
    from tuan_cli.core.kernel import Kernel

    ws_mod._SESSIONS.clear()
    kernel = Kernel()
    kernel.provide("collaboration_protocol", CollaborationProtocol())
    srv = WebServer(kernel=kernel, workspace=str(tmp_path), port=0)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    for _ in range(50):
        if srv._httpd is not None:
            break
        time.sleep(0.05)
    try:
        base = f"http://127.0.0.1:{srv._httpd.server_port}"
        # 初始黑板为空
        with urllib.request.urlopen(base + "/api/team/board", timeout=10) as r:
            board = json.loads(r.read().decode("utf-8"))
        assert board["ok"] is True
        assert board["keys"] == {}
        assert board["messages"] == []
        # 发布一条
        req = urllib.request.Request(
            base + "/api/team/post",
            data=json.dumps({"key": "k1", "value": "hello", "msg_type": "status",
                             "recipient": "*"}).encode("utf-8"),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as r:
            post = json.loads(r.read().decode("utf-8"))
        assert post["ok"] is True
        # board 读回
        with urllib.request.urlopen(base + "/api/team/board", timeout=10) as r:
            board2 = json.loads(r.read().decode("utf-8"))
        assert board2["keys"].get("k1") == "hello"
        assert len(board2["messages"]) == 1
        assert board2["messages"][0]["msg_type"] == "status"
        # 缺 key → 400
        req2 = urllib.request.Request(
            base + "/api/team/post",
            data=json.dumps({"key": "", "value": "x"}).encode("utf-8"),
            headers={"Content-Type": "application/json"})
        try:
            urllib.request.urlopen(req2, timeout=10)
            assert False, "应返回 400"
        except urllib.error.HTTPError as e:
            assert e.code == 400
    finally:
        if srv._httpd is not None:
            srv._httpd.shutdown()
            srv._httpd.server_close()
        ws_mod._SESSIONS.clear()


def test_team_http_clear_requires_auth(tmp_path):
    """/api/team/clear 未登录 → 403 (fail-closed)。"""
    import json
    import threading
    import time
    import urllib.request
    from tuan_cli.web import server as ws_mod
    from tuan_cli.web.server import WebServer
    from tuan_cli.core.kernel import Kernel

    ws_mod._SESSIONS.clear()
    kernel = Kernel()
    kernel.provide("collaboration_protocol", CollaborationProtocol())
    srv = WebServer(kernel=kernel, workspace=str(tmp_path), port=0)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    for _ in range(50):
        if srv._httpd is not None:
            break
        time.sleep(0.05)
    try:
        base = f"http://127.0.0.1:{srv._httpd.server_port}"
        req = urllib.request.Request(base + "/api/team/clear",
                                     data=b"{}", method="POST",
                                     headers={"Content-Type": "application/json"})
        try:
            urllib.request.urlopen(req, timeout=10)
            assert False, "未登录应 403"
        except urllib.error.HTTPError as e:
            assert e.code == 403
    finally:
        if srv._httpd is not None:
            srv._httpd.shutdown()
            srv._httpd.server_close()
        ws_mod._SESSIONS.clear()