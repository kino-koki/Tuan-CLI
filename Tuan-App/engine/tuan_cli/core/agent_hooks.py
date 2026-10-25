"""Agent 用户级 Hooks 与 Auto Memory 触发 —— 从 agent.py 提取的独立职责。

承载三类"生命周期副作用", 全部异常隔离、绝不阻断主循环:
- 用户级 HookManager 的通知事件 (Stop / SubagentStop / PreCompact);
- UserPromptSubmit hook (向本回合注入附加上下文);
- Auto Memory 后台抽取 (复用 MemoryStore + 规则启发式, 不调额外 LLM)。

用法:
    class Agent(HooksMixin, ...):
        pass
"""

from __future__ import annotations

import logging
from typing import Any, Dict

log = logging.getLogger(__name__)


class HooksMixin:
    """用户级 Hooks 分发 + Auto Memory 触发。

    依赖宿主 Agent 提供: `ctx`(含 hooks)、`kernel`、`_last_user_input`。
    """

    # 由 Agent.__init__ 注入; 类型标注仅为 IDE/类型检查提示
    kernel: Any

    def _hooks(self):
        """取用户级 HookManager (create_agent 时注入到 agent.ctx.hooks), 无则 None。"""
        ctx = getattr(self, "ctx", None)
        return getattr(ctx, "hooks", None) if ctx is not None else None

    def _notify_hook(self, event: str, payload: Dict[str, Any]) -> None:
        """触发通知类 hook (Stop/SubagentStop/PreCompact), 异常隔离、不阻断主流程。"""
        hooks = self._hooks()
        if hooks is None or not hooks.enabled_for(event):
            return
        try:
            hooks.run_notify(event, payload)
        except Exception as exc:  # noqa: BLE001
            log.debug("hook %s 执行失败: %s", event, exc)

    def _auto_memory_extract(self, answer: str = "") -> None:
        """Auto Memory: 后台线程从本轮用户消息抽取偏好/反馈/项目决策/参考事实。

        复用 MemoryStore + 规则启发式 (不调额外 LLM); 配置 memory.auto_extract=false
        时整体关闭。异常隔离, 绝不影响主循环。
        """
        try:
            from ..memory.auto_extractor import build_extractor
            extractor = build_extractor(self.kernel)
            if extractor is None:
                return
            user_text = getattr(self, "_last_user_input", "") or ""
            if not user_text.strip():
                return
            extractor.process_turn_async(user_text, answer or "", kernel=self.kernel)
        except Exception as exc:  # noqa: BLE001
            log.debug("Auto Memory 触发失败 (已忽略): %s", exc)

    def _run_prompt_submit_hooks(self, prompt: str) -> str:
        """UserPromptSubmit hook: 返回注入本回合的附加上下文 (无则空串)。"""
        hooks = self._hooks()
        if hooks is None or not hooks.enabled_for("UserPromptSubmit"):
            return ""
        try:
            return hooks.run_user_prompt_submit(prompt) or ""
        except Exception as exc:  # noqa: BLE001
            log.debug("UserPromptSubmit hook 执行失败: %s", exc)
            return ""
