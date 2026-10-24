"""ACP 权限接线回归测试（IDE 场景的 fail-closed 静默拒绝修复）。

背景 —— 为什么这是 P0:
    ACP 进程的 stdin 是管道（非 tty）。`tools/base.py` 的 ``ctx.confirm`` 若为
    None，`core/whitelist.py` 的无回调分支会**fail-closed 拒绝所有高危命令**
    （写文件/ 跑 shell / 删文件……）。而 ``KernelAcpBridge`` 此前
    ``create_agent(kernel, workspace)`` 没传 ``confirm=``，
    ``session/request_permission`` 这个写得很完整的反向 RPC 一次都不会触发。

    用户侧表现：在 IDE 里跑 agent，高危操作全部"莫名失败"，既看不到授权弹窗，
    也看不到拒绝原因 —— 看起来像工具坏了，而不是像权限被拒。

    修复：bridge 惰性建agent 时接上 confirm=，经反向 RPC 把授权请求转给 IDE
    客户端（``AcpInteractionBridge.handle_approval`` 从死代码转为活代码）。

本文件覆盖:
    - confirm 回调在有连接时能拿到客户端的真实决策（批准 / 拒绝 / 取消）
    - 跨线程桥接：回调跑在 executor 线程，RPC 在事件循环线程（真实路径）
    - fail-closed：无连接 / 事件循环已关/ RPC 失败 一律拒绝，绝不静默放行
    - bridge 把自身作为 conn 绑给 provider（server 侧接线）
"""
import asyncio
import threading

import pytest

from tuan_cli.runtime.acp.bridge import KernelAcpBridge


class _FakeConn:
    """最小 AcpConn：记录 request_permission 调用并按预设返回。

    注意响应的**嵌套信封**：`_parse_response` 读的是 ``resp["outcome"]["outcome"]``
    与 ``resp["outcome"]["optionId"]`` —— 因为 `request_permission` 在协议里是
    JSON-RPC 响应，真正的 result 段被包在 ``result/outcome`` 下。这里必须复刻
    真实结构，否则测的是"扁平响应"这条不存在的路径。
    """

    def __init__(self, option_id="approve_once", raise_exc=None, outcome="selected"):
        self.option_id = option_id
        self.raise_exc = raise_exc
        self.outcome = outcome
        self.calls = []

    async def request_permission(self, *, session_id, options, tool_call):
        self.calls.append({
            "session_id": session_id,
            "options": options,
            "tool_call": tool_call,
        })
        if self.raise_exc is not None:
            raise self.raise_exc
        return {"outcome": {"outcome": self.outcome, "optionId": self.option_id}}

    async def session_update(self, notification):
        pass


def _run_callback(bridge, confirm, prompt="执行危险命令"):
    """在**另一个线程**里调confirm（复刻 agent.run 走 executor 的真实情形）。"""
    box = {}

    def target():
        try:
            box["value"] = confirm(prompt)
        except Exception as exc:  # noqa: BLE001
            box["error"] = exc

    th = threading.Thread(target=target)
    th.start()
    th.join(timeout=10)
    return box


def _drive(conn, prompt="执行危险命令"):
    """完整真实路径：主线程持有 loop，confirm 在工作线程同步调用并阻塞等决策。"""
    async def scenario():
        bridge = KernelAcpBridge(workspace=".")
        bridge.bind_conn(conn, "sess-1")
        bridge._loop = asyncio.get_running_loop()
        confirm = bridge._make_confirm()
        assert confirm is not None
        box = await asyncio.get_running_loop().run_in_executor(
            None, _run_callback, bridge, confirm, prompt
        )
        assert "error" not in box, box.get("error")
        return box["value"]

    return asyncio.run(scenario())


# ============================================================ 跨线程真路径


def test_confirm_approved_reaches_client_decision():
    """客户端点"允许一次" -> confirm 返回 True，且请求真到达了 conn。"""
    conn = _FakeConn(option_id="approve_once")
    assert _drive(conn) is True
    assert len(conn.calls) == 1, "反向 RPC 必须真的发出"
    sent = conn.calls[0]
    assert sent["session_id"] == "sess-1"
    assert sent["options"], "必须带候选选项给客户端渲染"
    opt_ids = {o.get("optionId") for o in sent["options"]}
    assert "approve_once" in opt_ids


def test_confirm_rejected_when_client_declines():
    assert _drive(_FakeConn(option_id="reject_once")) is False


def test_confirm_cancelled_when_client_cancels():
    """客户端选"取消"（outcome=cancelled）必须视为拒绝。"""
    conn = _FakeConn(outcome="cancelled", option_id=None)
    assert _drive(conn) is False


def test_approve_for_session_also_true():
    assert _drive(_FakeConn(option_id="approve_always")) is True


# ============================================================ fail-closed


def test_no_conn_means_no_confirm_callback():
    """没有连接时不提供 confirm —— 调用方会 fail-closed 拒绝，而不是放行。"""
    bridge = KernelAcpBridge(workspace=".")
    assert bridge._make_confirm() is None


def test_closed_loop_rejects():
    """事件循环已关闭 -> 拒绝, 不得抛异常影响工具执行。"""

    class _ClosedLoop:
        """is_closed() 为真的替身（真loop 不能在运行中 close）。"""

        def is_closed(self):
            return True

    bridge = KernelAcpBridge(workspace=".")
    bridge.bind_conn(_FakeConn(), "s")
    bridge._loop = _ClosedLoop()
    confirm = bridge._make_confirm()
    assert confirm("危险操作") is False, "loop 不可用时必须 fail-closed"


def test_missing_loop_rejects():
    """还没跑过 prompt（_loop 为 None）-> 拒绝而非崩溃。"""
    bridge = KernelAcpBridge(workspace=".")
    bridge.bind_conn(_FakeConn(), "s")
    confirm = bridge._make_confirm()
    assert bridge._loop is None
    assert confirm("危险操作") is False


def test_rpc_failure_rejects():
    """RPC 抛异常 -> 拒绝（拒绝比放行更安全）。"""
    assert _drive(_FakeConn(raise_exc=RuntimeError("客户端断开"))) is False


def test_unknown_option_id_rejects():
    """未知 optionId -> 拒绝（防御性, 不能误批准）。"""
    assert _drive(_FakeConn(option_id="some-unknown-garbage")) is False


# ============================================================ 接线完整性


def test_prompt_records_loop_and_session():
    """prompt() 必须先记录事件循环与会话 id —— 权限回调要用它们。"""
    bridge = KernelAcpBridge(workspace=".")

    class _FakeAgent:
        def run(self, prompt, stream=False, on_token=None, on_tool=None,
                on_tool_result=None, on_error=None):
            if on_token:
                on_token("ok")
            if on_error:
                on_error(None)
            return "done"

        def cancel(self):
            pass

    bridge._agent = _FakeAgent()

    async def scenario():
        events = []
        async for ev in bridge.prompt("sess-42", "hi", None):
            events.append(ev)
        return events

    captured = {}

    async def scenario():
        # 在 loop 还活着时取状态（asyncio.run 结束后 loop 会被关闭）
        async for _ev in bridge.prompt("sess-42", "hi", None):
            pass
        captured["sid"] = bridge._session_id
        captured["loop"] = bridge._loop

    asyncio.run(scenario())
    assert captured["sid"] == "sess-42"
    assert captured["loop"] is not None


def test_server_binds_itself_as_conn():
    """AcpServer 构造时应把自己(AcpConn)绑给 provider。"""
    from tuan_cli.runtime.acp.server import AcpServer

    bridge = KernelAcpBridge(workspace=".")
    server = AcpServer(bridge, agent_info={"name": "t", "version": "0"})
    assert bridge._conn is server, "server 必须把自身作为 conn 绑给 bridge"


def test_handle_approval_no_longer_dead_code():
    """回归守卫: AcpInteractionBridge 必须被 bridge 真正调用。

    此前 handle_approval 是死代码（实现完整、导出完整、调用者0 个），
    导致 IDE 里权限请求从不发出。这里直接验证"真的走过了 handle_approval"：
    打桩它，驱动一次 confirm，断言被打桩函数被调用过。
    """
    import tuan_cli.runtime.acp.interaction_bridge as ib

    called = []
    original = ib.AcpInteractionBridge.handle_approval

    async def spy(self, req):
        called.append(req)
        return await original(self, req)

    ib.AcpInteractionBridge.handle_approval = spy
    try:
        assert _drive(_FakeConn(option_id="approve_once")) is True
    finally:
        ib.AcpInteractionBridge.handle_approval = original

    assert called, "bridge 必须经 AcpInteractionBridge.handle_approval 转发"
    req = called[0]
    # 它吃的是 dict 形态的 ApprovalRequest
    for key in ("approval_id", "session_id", "tool_call_id", "tool_name",
                "action", "tool_input_display"):
        assert key in req, f"缺字段 {key}"