"""Agent 的会话与上下文 mixin (历史 / 用量与成本 / 压缩摘要 / 韧性状态)。"""

from __future__ import annotations

from ..context.manager import ContextManager, estimate_messages
from .agent_helpers import SKILL_NUDGE, summarize_messages, should_nudge, detect_verify_write_tools, ChunkFlusher
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Set, cast
import logging

if TYPE_CHECKING:
    from ..config import Config
    from .observability import AgentObservability
    from .resilience import AgentResilience

log = logging.getLogger("tuan_cli.core.agent")


class AgentSessionMixin:
    # ---- 跨 mixin 共享实例状态 (纯声明; 由 Agent.__init__ 初始化) ----
    config: "Config"
    session: Any
    turn_count: int
    context_manager: ContextManager
    _obs: "AgentObservability"
    _resilience: "AgentResilience"

    # ---- 由兄弟 mixin 提供的方法 ----
    _notify_hook: Callable[..., None]

    def load_history(self, messages: List[Dict[str, Any]],
                     system_prompt: Optional[str] = None) -> int:
        """C-4.6: 把历史消息完整装载进 agent 上下文 (恢复会话用)。

        - 自动把系统提示词拼在最前 (若历史里没有 system 消息);
        - 返回装载的消息条数 (供 CLI 打印「已恢复 N 条」)。

        替代散落在 cmd_chat 里的 `agent.messages = [system] + messages` 赋值,
        作为恢复上下文的唯一契约入口。
        """
        history = list(messages or [])
        if not history:
            return 0
        sys_prompt = system_prompt if system_prompt is not None else getattr(
            self, "_system_prompt", "")
        if history[0].get("role") != "system" and sys_prompt:
            history = [{"role": "system", "content": sys_prompt}] + history
        self.messages = history
        return len(history)


    def _session_append(self, event_type: str, **payload: Any) -> None:
        """把事件写入 append-only 会话流 (可审计、可回放)。"""
        if self.session is not None:
            try:
                self.session.append(event_type, payload)
            except Exception as exc:  # noqa: BLE001
                log.debug("会话事件写入失败 (%s): %s", event_type, exc)


    def _accumulate_usage(self, usage: Any) -> None:
        """累计模型用量 —— 委托给 AgentObservability。"""
        self._obs.accumulate_usage(usage, session_append=self._session_append,
                                   config=self.config, turn_count=self.turn_count)
        # 同步 total_usage 到 Agent 实例 (供外部读取)
        self.total_usage = self._obs.total_usage


    def _estimate_total_cost(self) -> float:
        """估算当前会话总花费 (USD) —— 委托给 AgentObservability。"""
        obs = getattr(self, '_obs', None)
        if obs is not None:
            return float(obs.estimate_total_cost())
        # Agent.__new__ / 鸭子类型对象 (测试或序列化重建) 可能没有 _obs:
        # 直接用 token 用量估算, 保持成本报告可用。
        from ..core.agent_helpers import estimate_total_cost as _etc
        return _etc(getattr(self, "config", None), getattr(self, "total_usage", {}) or {})


    def cache_hit_rate(self) -> Optional[float]:
        """DeepSeek 前缀缓存命中率 —— 委托给 AgentObservability。"""
        return self._obs.cache_hit_rate()


    def context_stats(self) -> Dict[str, Any]:
        """返回上下文统计: 预算、已用、压缩阈值等。"""
        budget = self.config.get("context.budget_tokens", 60000)
        estimated = estimate_messages(self.messages)
        return {
            "budget_tokens": budget,
            "estimated_tokens": estimated,
            "message_count": len(self.messages),
            "compact_trigger": self.config.get("context.compact_trigger", None),
        }


    def resilience_status(self) -> Dict[str, Any]:
        """返回韧性组件 (熔断/限流/重试) 的运行状态 —— 委托给 AgentResilience。"""
        return self._resilience.status()


    def _compress_if_needed(self) -> None:
        """压缩上下文 (如需要)。"""
        self.messages, _dropped = self.context_manager.compact_if_needed(
            self.messages
        )


    def compact(self) -> int:
        """手动压缩上下文 (对标 Claude Code /compact)。返回折叠的消息条数。"""
        # 用户级 Hooks: PreCompact (手动触发)
        self._notify_hook("PreCompact", {"trigger": "manual"})
        self.messages, dropped = self.context_manager.compact_force(self.messages)
        return dropped


    def _summarize(self, messages: List[Dict[str, Any]]) -> str:
        """从旧消息中提取结构化关键信息, 用于上下文压缩。"""
        return summarize_messages(messages)
