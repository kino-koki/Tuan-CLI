"""Agent 的单轮执行 mixin (取消 / 重试 / 续做提示 / 工具执行 / 校验循环)。"""

from __future__ import annotations

from ..vision import build_user_content
from .agent_helpers import SKILL_NUDGE, summarize_messages, should_nudge, detect_verify_write_tools, ChunkFlusher
from .auto_route import AutoRouter, RouteSession, tool_messages_of_turn
from .prompts import build_system_prompt, build_task_context
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Set, cast
import logging
import threading
import time

if TYPE_CHECKING:
    from ..config import Config
    from ..tools.base import ToolContext
    from ..vision.blocks import ImageRef
    from .kernel import Kernel
    from .observability import AgentObservability
    from .tool_executor import ToolExecutor

log = logging.getLogger("tuan_cli.core.agent")


class AgentTurnMixin:
    # ---- 跨 mixin 共享实例状态 (纯声明, 运行期不赋值; 由 Agent.__init__ 初始化) ----
    config: "Config"
    kernel: "Kernel"
    workspace: str
    messages: List[Dict[str, Any]]
    model: Any
    ctx: "ToolContext"
    session: Any
    turn_count: int
    exclude_tools: Set[str]
    pending_images: List["ImageRef"]
    _cancel_event: threading.Event
    _last_user_input: str
    _system_prompt: str
    _tool_executor: "ToolExecutor"
    _obs: "AgentObservability"

    # ---- 由兄弟 mixin 提供的方法 ----
    _schemas: Callable[[], Any]
    _accumulate_usage: Callable[[Any], None]
    _session_append: Callable[..., None]
    _run_prompt_submit_hooks: Callable[[str], str]
    _maybe_route_model: Callable[..., None]
    _resolve_cross_refs: Callable[[str], str]
    _notify_hook: Callable[..., None]
    _auto_memory_extract: Callable[..., None]

    @property
    def _nudge_interval(self) -> int:
        return int(self.config.get("agent.skill_nudge_interval", 3))


    def _should_nudge(self) -> bool:
        return should_nudge(self.turn_count, self._nudge_interval)


    def _nudge_round(self, on_token: Any = None, on_reason: Any = None, on_error: Any = None) -> None:
        """任务推进数轮后自我提醒: 本次方法是否值得蒸馏成技能。

        模型若决定蒸馏, 会返回 skill_save 工具调用, 这里执行之; 若回复空内容
        表示无需蒸馏, 直接结束。nudge 是单轮收尾, 不再继续循环。
        """
        self.messages.append({"role": "user", "content": SKILL_NUDGE})
        try:
            result = self._chat_with_retry(
                self.messages,
                tools=self._schemas(),
                stream=False,
                on_token=on_token,
                on_reason=on_reason,
            )
        except Exception as exc:  # noqa: BLE001
            if on_error:
                on_error(str(exc))
            return
        if result is None:
            return
        usage = getattr(result, "usage", None)
        if usage:
            self._accumulate_usage(usage)
        msg_dict = self._parse_assistant_message(result)
        self.messages.append(msg_dict)
        self._session_append("assistant", message=msg_dict)
        tool_calls = msg_dict.get("tool_calls", [])
        if tool_calls:
            self._tool_executor.execute_batch(
                tool_calls, self.ctx,
                exclude_tools=self.exclude_tools,
            )


    def cancel(self) -> None:
        """请求在当前模型调用或工具步骤结束后停止当前任务。"""
        self._cancel_event.set()


    def clear_cancel(self) -> None:
        """清除取消请求，准备执行下一项任务。"""
        self._cancel_event.clear()


    def _chat_with_retry(self, messages: Any, tools: Any, stream: Any, on_token: Any, on_reason: Any, label: Any = "模型") -> Any:
        """带超时/重试/熔断的模型调用 —— 委托给 AgentResilience + AgentObservability。

        测试可能用 Agent.__new__ 绕过 __init__, 此时 _resilience 不存在,
        回退到使用 self.retry_policy / self._rate_limiter 直连 (保持旧行为)。
        """
        # 正常路径: 委托给韧性组件
        resilience = getattr(self, '_resilience', None)
        obs = getattr(self, '_obs', None)

        started_at = time.monotonic()
        span = obs.start_span("model.chat", attributes={"label": label}) if obs is not None else None

        try:
            if resilience is not None:
                result = resilience.chat_with_retry(
                    self.model, messages, tools, stream, on_token, on_reason, label,
                )
            else:
                # Agent.__new__ 回退: 使用直接设置的 retry_policy / _rate_limiter
                retry_policy = getattr(self, 'retry_policy', None)
                rate_limiter = getattr(self, '_rate_limiter', None)
                def _direct_call() -> Any:
                    if rate_limiter is not None:
                        rate_limiter.acquire()
                    try:
                        return self.model.chat(
                            messages, tools=tools, stream=stream,
                            on_token=on_token, on_reason=on_reason,
                        )
                    finally:
                        if rate_limiter is not None:
                            rate_limiter.release()
                if retry_policy is not None:
                    result = retry_policy.call(_direct_call, label=label)
                else:
                    result = _direct_call()
        except Exception as exc:  # noqa: BLE001
            if obs is not None and span is not None:
                obs.finish_span(span.span_id, status="error")
                obs.add_span_event(span, "model.error", {"error": str(exc)})
            raise
        if obs is not None and span is not None:
            elapsed_ms = (time.monotonic() - started_at) * 1000
            obs.finish_span(span.span_id, status="ok")
            usage = getattr(result, "usage", None) if result is not None else None
            tokens = 0
            if usage:
                pt = usage.get("prompt_tokens") if isinstance(usage, dict) else getattr(usage, "prompt_tokens", 0)
                ct = usage.get("completion_tokens") if isinstance(usage, dict) else getattr(usage, "completion_tokens", 0)
                tokens = int(pt or 0) + int(ct or 0)
            breaker = None
            if resilience is not None:
                breaker = resilience._circuit_breaker
            if breaker is not None and breaker.enabled:
                obs.add_span_event(span, "circuit_breaker", {"state": breaker.state})
            obs.record_model_call(elapsed_ms, tokens, success=True)
        return result


    def _execute_tools(
        self,
        tool_calls: List[Dict[str, Any]],
        on_tool: Optional[Callable[[str, str], None]] = None,
        on_tool_result: Optional[Callable[[str, str], None]] = None,
    ) -> None:
        """执行一批工具调用 —— 委托给 ToolExecutor (core/tool_executor.py)。

        同时把工具调用/结果以规范事件 (tool_call / tool_call_update) 落盘到会话流,
        供 Trajectory 重建与 replay 回放 (CLI 与 ACP/IDE 会话统一同一事件流)。
        """
        _counter = {"n": 0}

        def _ont(name: str, args: str) -> None:
            _counter["n"] += 1
            tid = f"t{_counter['n']}"
            self._session_append("tool_call", name=name, arguments=args, toolCallId=tid)
            if on_tool:
                on_tool(name, args)

        def _ontr(name: str, result: str) -> None:
            self._session_append(
                "tool_call_update", name=name, status="completed", result=result,
                toolCallId=f"t{_counter['n']}",
            )
            if on_tool_result:
                on_tool_result(name, result)

        self._tool_executor.execute_batch(
            tool_calls, self.ctx,
            exclude_tools=self.exclude_tools,
            on_tool=_ont,
            on_tool_result=_ontr,
        )


    # ------------------------------------------------------------ 编码验证闭环 (verify_loop)
    def _run_verify_loop(
        self,
        tool_calls: List[Dict[str, Any]],
        on_token: Optional[Callable[[str], None]] = None,
    ) -> None:
        """写工具执行后触发验证闭环 (core/verify_loop), 失败把错误喂回模型自修复。

        设计见 verify_loop.py: Agent 每次修改文件后自动跑 pytest/mypy/ruff, 失败则把
        错误信息作为一条 user 消息注入, 下一轮 while 循环里模型据此自我修复。最多
        max_heal_rounds 轮 (实际由调用方 max_iterations 兜底)。

        仅当 config.verify.enabled 且 verify.auto 为真时生效; 默认配置未配置 verify,
        故不影响既有运行行为 (避免无测试/无 mypy/ruff 的项目被误报刷屏)。
        """
        cfg = self.config.get("verify", {})
        if not isinstance(cfg, dict) or not cfg.get("enabled") or not cfg.get("auto", True):
            return
        if not detect_verify_write_tools(tool_calls):
            return
        try:
            from ..core.verify_loop import (
                MAX_HEAL_ROUNDS, VerifyConfig, verify_once,
            )
            checks = cfg.get("checks", {}) or {}
            vcfg = VerifyConfig(
                enabled=True,
                auto=True,
                max_heal_rounds=int(cfg.get("max_heal_rounds", MAX_HEAL_ROUNDS)),
                test_cmd=str(checks.get("test", "") or ""),
                typecheck_cmd=str(checks.get("typecheck", "") or ""),
                lint_cmd=str(checks.get("lint", "") or ""),
            )
            rnd = verify_once(
                self.workspace, vcfg,
                kernel=getattr(self, "kernel", None),
                confirm=getattr(getattr(self, "ctx", None), "confirm", None),
            )
        except Exception as exc:  # noqa: BLE001 - 验证基础设施异常不应阻断主流程
            log.debug("验证闭环执行失败 (已跳过): %s", exc)
            return
        if rnd.all_passed:
            if on_token:
                on_token("\n[验证闭环] 测试/类型检查/lint 全部通过 ✓\n")
            self._session_append("verify.passed", round=rnd.round_num)
            return
        # 有失败: 把错误摘要喂回模型, 触发自修复 (下一轮决策将看到此上下文)
        summary = rnd.summary()
        note = (
            "\n[验证闭环] 以下检查未通过, 请分析并修复后继续;\n"
            "修复后再次写入文件将重新触发验证:\n" + summary
        )
        if on_token:
            on_token(note)
        self.messages.append({"role": "user", "content": note})
        self._session_append("verify.failed", summary=summary)


    # 续跑判定线索 (小写匹配)
    _CONTINUE_CUES = ("接下来", "然后", "还需要", "下一步", "让我", "我将", "正在",
                      "准备", "待办", "尚未", "还没",
                      "next", "let me", "i'll", "i will", "going to", "then i",
                      "need to", "going to")


    @classmethod
    def _looks_unfinished(cls, text: str) -> bool:
        """判断一段纯文本回复是否**明确表达"还要继续"**。

        刻意保守: 只在文本含明确的"继续"线索 (接下来 / 然后 / 还需要 / 让我 /
        next / let me…) 时才判为未完成。**不做"没有完成词就当未完成"的兜底猜测** ——
        那会把「文件已写好」「被拒绝了」这类正常收尾也误判, 造成无意义的续跑往返
        甚至把 Mock 脚本跑穿。宁可靠模型自己确认, 也不靠猜。
        """
        t = (text or "").strip().lower()
        if not t:
            return False
        return any(c in t for c in cls._CONTINUE_CUES)


    @staticmethod
    def _parse_assistant_message(result: Any) -> Dict[str, Any]:
        """把模型响应 (ModelResponse / dict / str) 转成标准 assistant 消息字典。

        统一入口: _nudge_round、_run_react_inline、LoopProvider 都需要此逻辑,
        消除 3 处重复的 isinstance 判定链。
        """
        if hasattr(result, "content"):
            return {
                "role": "assistant",
                "content": result.content or "",
                # OpenAI 兼容规范: 每个 tool_call 必须含 type="function", 否则严格端点
                # (如 SenseNova) 在回传历史时以 400 拒绝 (invalid tool_call type)。
                # 此前缺失该字段 —— 属核心序列化缺陷, 与供应商无关。
                "tool_calls": [
                    {"id": tc.id, "type": "function",
                     "function": {"name": tc.name, "arguments": tc.arguments}}
                    for tc in (result.tool_calls or [])
                ],
            }
        if isinstance(result, dict):
            message = result.get("message", result)
            return (
                message
                if isinstance(message, dict)
                else {"role": "assistant", "content": str(message)}
            )
        return {"role": "assistant", "content": str(result)}


    def _prepare_run(
        self,
        user_input: str,
        session_id: Optional[str],
        on_token: Optional[Callable[[str], None]],
    ) -> tuple:
        """运行前共享初始化: 会话旋转、生命周期事件、token 落盘包装、trace、
        系统提示注入、hook 上下文、模型路由、用户消息构建。

        Returns:
            (on_token_wrapped, run_trace, raw_on_token)
        """
        # A4 事件溯源: 会话旋转 + 生命周期事件
        if session_id and self.session is not None and hasattr(self.session, "rotate"):
            try:
                self.session.rotate(session_id, meta={"task": (user_input or "")[:200]})
            except Exception:  # noqa: BLE001
                pass
        self._session_append("session.update", status="initialized")
        self._session_append("task.update", status="running")

        # 包装 on_token: 增量落盘 (分片合并 —— 逐 delta 同步写盘会拖慢流式输出,
        # 见 ChunkFlusher; 上一轮未冲完的先冲掉, 防跨轮串块)
        raw_on_token = on_token
        prev_flusher = getattr(self, "_chunk_flusher", None)
        if prev_flusher is not None:
            prev_flusher.flush()
        flusher = ChunkFlusher(
            lambda text: self._session_append("agent_message_chunk", text=text)
        )
        self._chunk_flusher = flusher

        def _wrapped_on_token(delta: str) -> None:
            if delta:
                flusher.add(delta)
            if raw_on_token:
                raw_on_token(delta)
        on_token = _wrapped_on_token

        # 可观测性 trace
        run_trace = self._obs.start_trace("agent.run")
        if run_trace:
            self._tool_executor._trace_id = run_trace

        # 系统提示 + 任务上下文
        if not self.messages:
            self.messages.append({"role": "system", "content": self._system_prompt})

        hook_ctx = self._run_prompt_submit_hooks(user_input)
        self._maybe_route_model(user_input)
        self._route_session = RouteSession()

        task_ctx = build_task_context(
            task_hint=user_input,
            memory_store=self.kernel.get("memory_store") if self.config.get("memory.auto_inject", True) else None,
            skill_manager=self.kernel.get("skill_manager") if self.config.get("skills.auto_inject", True) else None,
        )
        prefix = "\n\n".join(x for x in (task_ctx, hook_ctx) if x)
        _expanded_input = self._resolve_cross_refs(user_input)
        user_msg: Dict[str, Any] = {
            "role": "user",
            "content": (prefix + "\n\n" + _expanded_input) if prefix else _expanded_input,
        }
        if self.pending_images:
            vision = getattr(self.model.capabilities, "vision", False)
            provider = getattr(self.model, "name", "openai")
            user_msg["content"] = build_user_content(
                user_msg["content"], self.pending_images, vision, provider
            )
            self.pending_images = []
        self.messages.append(user_msg)
        self._session_append("user", message=user_msg)
        self._last_user_input = _expanded_input

        return on_token, run_trace, raw_on_token


    def _teardown_run(
        self,
        answer: str,
        run_trace: Any,
        raw_on_token: Optional[Callable[[str], None]],
        on_error: Optional[Callable[[str], None]],
        nudge: bool = True,
    ) -> str:
        """运行后共享收尾: hooks 通知、技能蒸馏、trace 关闭、会话状态落盘。"""
        # 输出净化 (零 emoji 硬规则兜底): 提示词已要求不输出 emoji, 但提示词是
        # 请求而非保证。这里在**所有运行路径的公共收尾**做一次确定性清理, 保证
        # 落盘会话 / 历史回看 / 导出 Markdown 里都不含 emoji —— HTML/PPT 场景下
        # emoji 会渲染成豆腐方框, 属产物缺陷。放在 hooks/记忆提取**之前**, 让
        # 下游看到的就是净化后的文本。
        if answer:
            from .output_sanitize import strip_emoji
            answer, _removed = strip_emoji(answer)
        # 流式分片合并落盘的收尾: 把不满阈值的尾部一次冲完, 保证 JSONL 完整
        flusher = getattr(self, "_chunk_flusher", None)
        if flusher is not None:
            flusher.flush()
        if answer and not answer.startswith("[模型错误]") and not self._cancel_event.is_set():
            self._notify_hook("Stop", {"reason": "stop", "answer": answer[:1000]})
            self._auto_memory_extract(answer)
        if nudge and self._should_nudge():
            self._nudge_round(on_token=raw_on_token, on_reason=None, on_error=on_error)
        if run_trace:
            self._obs.finish_trace(run_trace)

        _failed = bool(answer) and answer.startswith("[模型错误]")
        self._session_append("task.update", status="failed" if _failed else "completed")
        self._session_append("session.update", status="done")
        return answer
