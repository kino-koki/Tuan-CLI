"""kernel.acp：鉴权握手 + session/fork 接入建 + loop 错误处理器 before/after 排序。

自研实现测试 —— 覆盖本轮「自己开发还需要的功能」新增项：
- AcpServer 内部鉴权（authenticate / logout / 受保护方法门禁）
- session/fork 优先接 agent_provider.fork_session
- AgentLoopService 错误恢复处理器的 before/after 稳定排序
- SseMcpClient 的 endpoint 事件发现
"""

from __future__ import annotations

import asyncio
import json

from qingxiaotuan.runtime.acp.server import (
    AUTH_REQUIRED,
    AcpServer,
    AUTH_TYPE_INTERNAL,
)
from qingxiaotuan.runtime.acp import (
    AUTHENTICATE,
    INITIALIZE,
    SESSION_NEW,
    SESSION_FORK,
    SESSION_PROMPT,
)
from qingxiaotuan.runtime.mcp.client_sse import SseMcpClient


class _ListWriter:
    def __init__(self):
        self.lines = []

    def write(self, s):
        self.lines.append(s)

    def flush(self):
        pass


def _make_server(secret=None, provider=None):
    return AcpServer(
        agent_provider=provider or (lambda confirm: None),
        agent_info={"name": "t", "version": "1"},
        workspace=".",
        auth_secret=secret,
    )


# ----------------------------------------------------------------- ACP 鉴权

def test_no_secret_backward_compat_authenticated():
    server = _make_server(secret=None)
    assert server._is_authenticated() is True


def test_authenticate_internal_secret_ok():
    server = _make_server(secret="s3cr3t")
    result = __import__("asyncio").run(server._h_authenticate(
        {"type": AUTH_TYPE_INTERNAL, "metadata": {"secret": "s3cr3t"}}
    ))
    assert result["authenticated"] is True
    assert server._is_authenticated() is True


def test_authenticate_wrong_secret_fails():
    server = _make_server(secret="s3cr3t")
    result = __import__("asyncio").run(server._h_authenticate(
        {"type": AUTH_TYPE_INTERNAL, "metadata": {"secret": "nope"}}
    ))
    assert result["authenticated"] is False
    assert result["error"]["type"] == "invalid_credentials"
    assert server._is_authenticated() is False


def test_logout_resets_authenticated():
    server = _make_server(secret="s3cr3t")
    __import__("asyncio").run(server._h_authenticate(
        {"type": "internal", "metadata": {"secret": "s3cr3t"}}
    ))
    assert server._authenticated is True
    __import__("asyncio").run(server._h_logout({}))
    assert server._authenticated is False


def _gate_new_session(server) -> int:
    """驱动一次 session/new 请求，返回响应帧里的 error code（无则 None）。"""
    writer = _ListWriter()
    server._writer = writer
    frame = {"jsonrpc": "2.0", "id": 7, "method": SESSION_NEW, "params": {"cwd": "."}}
    __import__("asyncio").run(server._handle_request(frame))
    resp = json.loads(writer.lines[-1])
    err = resp.get("error")
    return err["code"] if err else None


def test_protected_method_requires_auth():
    server = _make_server(secret="s3cr3t")
    assert _gate_new_session(server) == AUTH_REQUIRED


def test_protected_method_allowed_after_auth():
    server = _make_server(secret="s3cr3t")
    __import__("asyncio").run(server._h_authenticate(
        {"type": "internal", "metadata": {"secret": "s3cr3t"}}
    ))
    assert _gate_new_session(server) is None  # 成功（无 error）


def test_initialize_advertises_internal_auth_when_secret():
    server = _make_server(secret="s3cr3t")
    result = __import__("asyncio").run(server._h_initialize({"protocolVersion": 1}))
    types = [m.get("type") for m in result["authMethods"]]
    assert "internal" in types


def test_initialize_no_internal_when_no_secret():
    server = _make_server(secret=None)
    result = __import__("asyncio").run(server._h_initialize({"protocolVersion": 1}))
    types = [m.get("type") for m in result["authMethods"]]
    assert "internal" not in types


# ----------------------------------------------------------------- session/fork

def test_fork_uses_provider_fork_session():
    calls = []

    class Provider:
        def fork_session(self, params):
            calls.append(params.get("sessionId"))
            return "forked-123"

    server = _make_server(provider=Provider())
    result = __import__("asyncio").run(
        server._h_session_fork({"sessionId": "src", "cwd": "."})
    )
    assert calls == ["src"]
    assert result["sessionId"] == "forked-123"
    assert "forked-123" in server._sessions


def test_fork_falls_back_to_new_when_missing():
    server = _make_server(provider=lambda confirm: None)
    result = __import__("asyncio").run(
        server._h_session_fork({"sessionId": "src", "cwd": "."})
    )
    assert result["sessionId"]


# ----------------------------------------------------------------- loop 排序

def _make_handler(handler_id, label):
    from qingxiaotuan.runtime.agent.loop import LoopErrorHandler

    async def handle(ctx):
        ctx.retry_order.append(label)

    async def noop(ctx):
        return None

    def match(ctx):
        return True

    h = LoopErrorHandler(handler_id, match, noop)
    h.label = label
    h.async_handle = handle
    return h


def _build_loop():
    from qingxiaotuan.runtime.agent.loop import AgentLoopService, ToolExecutor
    return AgentLoopService(
        provider=object(),
        system_prompt="",
        tools=[],
        history=[],
        tool_executor=ToolExecutor(),
    )


def test_error_handler_before_after_ordering():
    loop = _build_loop()
    h_a = _make_handler("a", "A")
    h_b = _make_handler("b", "B")
    h_c = _make_handler("c", "C")
    loop.register_loop_error_handler(h_a)
    loop.register_loop_error_handler(h_c)
    loop.register_loop_error_handler(h_b, {"before": ["c"], "after": ["a"]})
    # 约束：a->b->c
    ordered = loop._ordered_error_handlers()
    assert [h.label for h in ordered] == ["A", "B", "C"]


def test_error_handler_insertion_order_default():
    loop = _build_loop()
    h_a = _make_handler("a", "A")
    h_b = _make_handler("b", "B")
    h_c = _make_handler("c", "C")
    loop.register_loop_error_handler(h_c)
    loop.register_loop_error_handler(h_a)
    loop.register_loop_error_handler(h_b)
    ordered = loop._ordered_error_handlers()
    assert [h.id for h in ordered] == ["c", "a", "b"]


def test_error_handler_cycle_falls_back_to_insertion():
    loop = _build_loop()
    h_a = _make_handler("a", "A")
    h_b = _make_handler("b", "B")
    # a before b, b before a -> 环，兜底插入顺序
    loop.register_loop_error_handler(h_b, {"before": ["a"]})
    loop.register_loop_error_handler(h_a, {"before": ["b"]})
    ordered = loop._ordered_error_handlers()
    assert [h.id for h in ordered] == ["b", "a"]


# ----------------------------------------------------------------- SSE 端点发现

def test_sse_dispatch_endpoint_event():
    async def run():
        client = SseMcpClient({"url": "http://example.com/mcp"})
        loop = asyncio.get_event_loop()
        fut = loop.create_future()
        client._endpoint_fut = fut
        client._dispatch_sse_event("endpoint", '{"uri":"http://example.com/callback"}')
        assert await fut == "http://example.com/callback"

    asyncio.run(run())


def test_sse_dispatch_ignores_non_endpoint():
    async def run():
        client = SseMcpClient({"url": "http://example.com/mcp"})
        loop = asyncio.get_event_loop()
        fut = loop.create_future()
        client._endpoint_fut = fut
        client._dispatch_sse_event("", "some other data")
        assert fut.done() is False
        await client.close()

    asyncio.run(run())