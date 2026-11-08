"""把青小团既有实现适配成本模块的 ``agent_provider`` 接口（DIP 桥）。

目标：让 ``tuan_cli/acp/cmd_acp.py`` 等既有入口可复用本 ``kernel.acp`` 子系统，
而不必把既有 ACP server 推倒重来。

适配来源（按可用性）：
- 首选 ``tuan_cli.core.agent.Agent``：其 ``run(prompt, stream, on_token, on_tool,
  on_tool_result, on_error)`` 是同步 + 回调式；本桥在 executor 里跑它，把回调推入
  asyncio.Queue，再包成异步事件源（见 :class:`KernelAcpBridge.prompt`）。
- 兼容 ``tuan_cli.acp.server.AcpServer``：若调用方已持有其实例，可用
  :func:`from_existing_acp_server` 包成 ``agent_provider``（精简桥，懒加载 + 降级）。

所有重量级导入均惰性进行，保证 ``import tuan_cli.runtime.acp`` 不触发内核/provider 依赖。
"""

from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator, Callable, Dict, List, Optional

from .events_map import acp_tool_call_id

#: 单次权限请求等待客户端决策的上限 (秒)。超时不阻塞整个会话 ——
#: 超时即视为拒绝 (fail-closed)，否则 IDE 用户不点"允许"就能把 agent 卡死。
_PERMISSION_TIMEOUT_S = 300.0


class KernelAcpBridge:
    """把青小团既有 ``Agent`` 适配为 ``agent_provider``（prompt/cancel/available_commands）。

    用法::

        bridge = KernelAcpBridge(make_agent=make_agent, workspace=".")
        server = AcpServer(bridge, agent_info=...)

    ``make_agent`` 为 0 参 callable，返回一个具备 ``run(...)`` 与 ``cancel()`` 的 AgentLike。
    若不传，桥会惰性 ``create_agent(kernel, workspace)``。

    **权限确认（``confirm=``）**:
        ACP 进程的 stdin 是管道（非 tty），`tools/base.py` 的``ctx.confirm`` 若为
        None，`core/whitelist.py` 会fail-closed 拒绝**所有**高危命令 —— 用户在 IDE 里
        看不到任何授权弹窗，只看到工具"莫名失败"。因此桥会把 confirm 回调接上，
        经`session/request_permission` 反向 RPC 把授权请求转给 IDE 客户端。
    """

    def __init__(
        self,
        make_agent: Optional[Callable[[], Any]] = None,
        *,
        kernel: Any = None,
        workspace: str = ".",
        conn: Any = None,
        session_id: str = "",
    ) -> None:
        self._make_agent = make_agent
        self._kernel = kernel
        self._workspace = workspace
        self._agent: Any = None
        self._turn_tool_ids: Dict[int, str] = {}
        self._mode: Any = None
        self._model: str = ""
        # 反向 RPC 出口：连接对象 + 当前会话 id。缺任一项时权限请求一律拒绝
        # （fail-closed），绝不"静默放行"。
        self._conn = conn
        self._session_id = session_id
        self._tool_call_seq = 0
        # 持有事件循环的线程引用 —— 权限回调跑在 executor 线程里，必须靠它把
        # 协程送回主循环（run_coroutine_threadsafe）。
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    # ----------------------------------------------------------- agent 惰性构建
    def _ensure_agent(self) -> Any:
        if self._agent is not None:
            return self._agent
        if self._make_agent is not None:
            self._agent = self._make_agent()
            return self._agent
        # 降级：惰性复用既有 app.create_agent
        from ..app import create_agent

        #必须传 confirm= —— 否则 ACP 进程 (stdin 非 tty) 里所有高危命令会被
        # whitelist 的 fail-closed 分支静默拒绝, 用户在 IDE 里看不到授权弹窗。
        self._agent = create_agent(
            self._kernel, self._workspace, confirm=self._make_confirm()
        )
        return self._agent

    # ----------------------------------------------------------- 权限确认桥
    def bind_conn(self, conn: Any, session_id: str) -> None:
        """绑定反向 RPC 连接（server 起来后调用），使权限请求能真正到达客户端。"""
        self._conn = conn
        if session_id:
            self._session_id = session_id

    def _make_confirm(self) -> Optional[Callable[[str], bool]]:
        """构造给 ``ToolContext.confirm`` 的同步回调。

        返回 None 表示"没有可用的授权通道"，调用方（whitelist）会fail-closed
        拒绝 —— 这是安全默认，不能因为"拿不到连接"就放行。
        """
        if self._conn is None:
            return None

        def _confirm(prompt: str) -> bool:
            # agent.run 在 executor 线程里跑, 而反向 RPC 是 asyncio —— 必须用
            # run_coroutine_threadsafe 把请求送回**持有事件循环的线程**再阻塞等决策。
            # 注意不能用 run_until_complete: 事件循环在主线程, 这里(工作线程)调用会抛
            # "This event loop is already running" 或根本没有 loop。
            loop = self._loop
            if loop is None or loop.is_closed():
                return False       # fail-closed: 拿不到授权通道就不放行
            try:
                fut = asyncio.run_coroutine_threadsafe(
                    self._request_permission(prompt), loop
                )
                return bool(fut.result(timeout=_PERMISSION_TIMEOUT_S))
            except Exception:  # noqa: BLE001 - 超时/取消/RPC 失败一律拒绝
                return False

        return _confirm

    async def _request_permission(self, prompt: str) -> bool:
        """经 ``session/request_permission`` 反向 RPC 向 IDE 客户端请求授权。"""
        from .interaction_bridge import AcpInteractionBridge

        self._tool_call_seq += 1
        tool_call_id = f"perm{self._tool_call_seq}"
        bridge = AcpInteractionBridge(self._conn, self._session_id)
        # handle_approval 吃的是 dict 形态的 ApprovalRequest（见
        # interaction_bridge 的纯映射函数签名），而非 dataclass。
        req = {
            "approval_id": tool_call_id,
            "session_id": self._session_id,
            "tool_call_id": tool_call_id,
            "tool_name": "permission",
            "action": prompt,
            "tool_input_display": {"prompt": prompt},
            "display": {"kind": "command"},
        }
        resp = await bridge.handle_approval(req)
        decision = str(getattr(resp, "decision", "") or "")
        return decision in ("approved", "allow", "allow_once", "approved_always")

    # ----------------------------------------------------------- 用户提问出口
    async def ask_user(self, question: str, options: List[str]) -> str:
        """``ask_user`` 的 ACP 实现：经 ``elicitation/create`` 向 IDE 用户提问。

        这是 TUI ``QxtTUI.ask_user`` 卡片在 IDE 侧的等价物 —— 上一轮只在 TUI
        宿主补了洞，非 TUI 宿主（ACP/IDE）仍然是空的，表现为"模型自问自答、
        用户全程看不到问题"。两个宿主共用 ``tools/session_tools.py`` 里的
        ``ctx.ui.ask_user`` 钩子契约，所以接线点唯一。

        返回用户选中的选项或输入的原文；无法交互时返回空串（调用方会转成
        "请基于现有信息继续并说明你的假设"）。
        """
        conn = self._conn
        loop = self._loop
        if conn is None or loop is None or loop.is_closed():
            return ""
        opts = [o for o in (options or []) if str(o).strip()]
        payload = [{"value": str(o), "label": str(o)} for o in opts]
        # B3 续轮: ACP 的 elicitation/create 反向 RPC 是 CC 语义上真正的
        # MCP elicitation 宿主。提问前派发 Elicitation（block = 取消，
        # 不代答）；拿到真实答案后派发 ElicitationResult（block = 作废）。
        from ...hooks.triggers import HookTrigger
        _trig = HookTrigger()
        _pre = _trig.elicitation(
            question=question, options=opts, source="acp_elicitation_create")
        if getattr(_pre, "block", False):
            return ""
        try:
            result = await conn.elicitation_create(
                session_id=self._session_id, message=question, options=payload
            )
        except Exception:  # noqa: BLE001 - 无法交互 -> 空串, 调用方降级
            return ""
        # 客户端回 {action: "accept", content: {"choice": "..."}} 或 cancel/decline
        if not isinstance(result, dict):
            return ""
        action = str(result.get("action") or "accept")
        if action not in ("accept", "acceptWithChanges"):
            return ""
        content = result.get("content")
        if not isinstance(content, dict):
            return ""
        for key in ("choice", "answer"):
            val = content.get(key)
            if isinstance(val, str) and val.strip():
                _res = _trig.elicitation_result(
                    answer=val.strip(), action=action, question=question,
                    source="acp_elicitation_create")
                if getattr(_res, "block", False):
                    return ""
                return val.strip()
        return ""

    def _make_ui_handle(self) -> Any:
        """给 ``ToolContext.ui`` 用的句柄 —— 只暴露 ``ask_user`` 一个能力。

        极简对象而不是整个 UI 类: ACP 侧只需要"能向用户提问"这一件事，
        而 REPL 的 ``UI`` 有 30+ 方法在管道环境下毫无意义。
        """
        bridge = self

        class _AcpUIHandle:
            def ask_user(self, question: str, options: List[str]) -> str:
                loop = bridge._loop
                if loop is None or loop.is_closed():
                    return ""
                fut = asyncio.run_coroutine_threadsafe(
                    bridge.ask_user(question, list(options or [])), loop
                )
                try:
                    return str(fut.result(timeout=_PERMISSION_TIMEOUT_S) or "")
                except Exception:  # noqa: BLE001
                    return ""

        return _AcpUIHandle()

    # ----------------------------------------------------------- agent_provider 接口
    async def prompt(
        self, session_id: str, input_text: str, signal: Any,
    ) -> AsyncIterator[Dict[str, Any]]:
        """驱动一次 prompt，产出引擎事件流（供 AcpSession 翻译）。"""
        # 先记住当前事件循环与会话 —— 必须在建 agent 之前, 权限回调要用。
        self._loop = asyncio.get_running_loop()
        if session_id:
            self._session_id = session_id
        agent = self._ensure_agent()
        turn_id = 1
        queue: "asyncio.Queue[Dict[str, Any]]" = asyncio.Queue()
        tool_ids: Dict[str, str] = {}

        def on_token(delta: str) -> None:
            queue.put_nowait({"type": "assistant.delta", "delta": delta or ""})

        def on_tool(name: str, args: str) -> None:
            raw_id = f"tc{len(tool_ids) + 1}"
            tool_ids[raw_id] = raw_id
            queue.put_nowait({
                "type": "tool.call.started", "turn_id": turn_id, "tool_call_id": raw_id,
                "name": name, "args": args,
            })

        def on_tool_result(name: str, result: str) -> None:
            raw_id = next(iter(tool_ids), "tc1")
            queue.put_nowait({
                "type": "tool.result", "turn_id": turn_id, "tool_call_id": raw_id,
                "output": result or "", "is_error": False,
            })

        def on_error(msg: str) -> None:
            queue.put_nowait({
                "type": "turn.ended", "reason": "failed",
                "error": {"code": "agent.error", "message": msg},
            })

        async def agen() -> AsyncIterator[Dict[str, Any]]:
            loop = asyncio.get_event_loop()
            run_fut = loop.run_in_executor(
                None,
                lambda: agent.run(
                    input_text, stream=True, on_token=on_token, on_tool=on_tool,
                    on_tool_result=on_tool_result, on_error=on_error,
                ),
            )
            done = False
            while not done:
                get_task = asyncio.ensure_future(queue.get())
                done_task, pending = await asyncio.wait(
                    {run_fut, get_task}, return_when=asyncio.FIRST_COMPLETED
                )
                if get_task in done_task:
                    item = get_task.result()
                    yield item
                    if item.get("type") == "turn.ended":
                        done = True
                else:
                    # agent 已结束：先吐完队列余量，再补一个正常 turn.ended
                    get_task.cancel()
                    while not queue.empty():
                        rem = queue.get_nowait()
                        yield rem
                        if rem.get("type") == "turn.ended":
                            done = True
                    if not done:
                        yield {"type": "turn.ended", "reason": "completed"}
                    done = True
            # 取 run 结果以吸收异常（不阻塞）
            try:
                await run_fut
            except Exception:
                pass

        async for ev in agen():
            yield ev

    def cancel(self, session_id: str, turn_id: int) -> None:
        agent = self._agent
        if agent is not None and hasattr(agent, "cancel"):
            try:
                agent.cancel()
            except Exception:
                pass

    def available_commands(self) -> List[Dict[str, Any]]:
        try:
            from ..cli.cmd_slash import list_slash_commands

            return [{"name": c.get("name", "")} for c in (list_slash_commands() or [])]
        except Exception:
            return []

    def list_sessions(self) -> List[str]:
        return []

    def new_session(self, params: Dict[str, Any]) -> str:
        import uuid

        return str(uuid.uuid4().hex)

    def set_mode(self, session_id: str, mode: Any) -> None:
        """接受 ACP 会话的 mode 偏好。

        桥接器把 ``prompt`` 直接委托给内核的 ``Agent``, 会话的运行模式由
        Agent 自身的策略驱动, 此处记录偏好但不强制透传, 保持单会话语义一致。
        幂等; 无效 mode 忽略。
        """
        self._mode = mode

    def set_model(self, session_id: str, model_id: str) -> None:
        """接受 ACP 会话的模型偏好。

        模型选择由内核 model_router 在 prompt 时解析, 邀请设置的 model_id 会
        被记录以支持将来按会话路由; 传入空串视为清除偏好。
        """
        self._model = model_id


def from_existing_acp_server(acp_server: Any) -> Any:
    """把既有 ``tuan_cli.acp.server.AcpServer`` 包成 agent_provider（精简桥）。

    既有 server 是线程式、按 stdin/stdout 驱动的完整 ACP server，与本项目单进程多 session
    模型不同；此处仅做最小兼容：作为 ``prompt`` 入口时降级为直接 new agent 运行。
    优先使用 KernelAcpBridge 以获得完整异步事件流。
    """
    make_agent = getattr(acp_server, "_agent_provider", None)
    if callable(make_agent):
        return KernelAcpBridge(make_agent=make_agent)
    return KernelAcpBridge()
