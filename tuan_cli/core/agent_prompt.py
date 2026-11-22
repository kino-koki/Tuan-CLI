"""Agent 的系统提示构建 mixin (提示分层 / 代码库地图 / 交叉引用)。"""

from __future__ import annotations

from .prompt_tier import COMPACT, FULL, PromptBudget, budget_for_tier, resolve_prompt_budget, resolve_soul_tier
from .prompts import build_system_prompt, build_task_context
from .intent_router import RouteDecision, route
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Set, cast
import logging
import threading

if TYPE_CHECKING:
    from ..config import Config
    from .kernel import Kernel

log = logging.getLogger("tuan_cli.core.agent")


class AgentPromptMixin:
    # ---- 跨 mixin 共享实例状态 (纯声明; 由 Agent.__init__ 初始化) ----
    config: "Config"
    kernel: "Kernel"
    workspace: str
    session: Any
    user_mode: bool
    system_extra: str
    prompt_tier: str
    prompt_budget: PromptBudget
    _soul_tier: str
    _indexer: Optional[Any]
    _index_thread: Optional[threading.Thread]
    _turn_started: bool
    _last_user_input: str
    #: 最近一轮意图路由决策 (见 core/intent_router.py); 仅当本轮有用户输入时非 None。
    #: 由 _effective_soul_tier 在每次 _build_system 期间刷新, 供日志/调试/后续按意图收紧工具集使用。
    _intent_route: Optional[RouteDecision]

    def _resolve_prompt_tier(self) -> Any:
        """解析提示词分层: 返回 (档位名, 推断窗口, 该档预算)。

        任何异常都回退 full 档 —— 分层是优化而非正确性前提, 打坏它不能影响会话。
        """
        try:
            tier, window, budget = resolve_prompt_budget(self.config)
        except Exception as exc:  # noqa: BLE001
            log.debug("提示词分层解析失败, 回退 full 档: %s", exc)
            return FULL, 0, budget_for_tier(FULL)
        log.debug("提示词分层: model=%s window=%d -> %s",
                  self.config.get("model.model", ""), window, tier)
        return tier, window, budget


    def _resolve_soul_tier(self) -> str:
        """稳定前缀的 SOUL 档位 —— 大上下文模型读 SOUL_FULL.md, 小上下文读 SOUL_COMPACT.md。

        - ``prompt.tier`` 显式 ``compact`` / ``full``: 采信用户选择 (历史行为)。
        - ``prompt.tier=auto`` (默认): 按解析出的预算档位联动 ——
          窗口 >= 128k (full 档, 即「大上下文模型」) → ``FULL``, 稳定前缀读
          SOUL_FULL.md 完整提示词 (自包含全部规范, 跳过其余附加段);
          窗口 < 128k (compact 档) → ``COMPACT``, 只读 SOUL_COMPACT.md
          小模型专属提示词 (自包含全部必要规范, 跳过其余附加段),
          否则 8k/32k 窗口会被稳定前缀本身挤爆。

        2026-10-18 修正: auto + full 档原先返回 ``""`` (SOUL.md + 规范段拼装,
        约 11K 字), 大上下文模型因此只拿到一份阉割版提示词。现按
        「128k 以上即大上下文模型, 读 SOUL_FULL.md」的口径统一 (用户需求)。
        异常一律回退 "" (默认拼装), 分层打坏不影响会话。
        """
        try:
            explicit = resolve_soul_tier(self.config)
            if explicit:
                return explicit
            # auto: 按上下文窗口联动 —— 大上下文读 SOUL_FULL.md, 小上下文读 SOUL_COMPACT.md
            if self.prompt_tier in (COMPACT, FULL):
                return str(self.prompt_tier)
            return ""
        except Exception as exc:  # noqa: BLE001
            log.debug("SOUL 档位解析失败, 回退默认拼装: %s", exc)
            return ""


    def _effective_prompt_limits(self) -> Any:
        """把用户配置值与当前分层预算取 min, 返回四元组注入预算。

        (skill_limit, memory_notes_max_lines, project_doc_max_bytes,
         long_memory_max_chars)

        full 档上限远高于默认值, 因此默认配置下本方法返回的值与历史完全一致。
        只管「注入多少」; 是否注入代码库地图由 context.pin_codebase 决定。
        """
        budget: PromptBudget = self.prompt_budget
        try:
            user_skill_limit = int(self.config.get("skills.inject_limit", 3))
        except Exception:  # noqa: BLE001
            user_skill_limit = 3
        try:
            user_notes_lines = int(self.config.get("memory.notes_max_lines", 200))
        except Exception:  # noqa: BLE001
            user_notes_lines = 200
        try:
            user_doc_bytes = int(self.config.get("prompt.project_doc_max_bytes", 32768))
        except Exception:  # noqa: BLE001
            user_doc_bytes = 32768
        return budget.apply_caps(
            skill_limit=user_skill_limit,
            memory_notes_max_lines=user_notes_lines,
            project_doc_max_bytes=user_doc_bytes,
            long_memory_max_chars=1500,
        )


    def _effective_soul_tier(self) -> str:
        """综合意图路由后的稳定前缀档位: 意图覆盖 > 既有 ``_soul_tier``。

        仅当本轮已有用户输入 (``_last_user_input`` 非空) 时才尝试意图路由;
        否则保持历史行为 (``_soul_tier`` 原值), 避免首帧/后台补建系统提示时
        基于空输入做分类。
        """
        try:
            user_input = (self._last_user_input or "").strip()
        except Exception:  # noqa: BLE001 - 属性未初始化时回退 (测试常 Agent.__new__ 绕过 __init__)
            return self._soul_tier
        if not user_input:
            return self._soul_tier
        try:
            decision = route(user_input, int(getattr(self, "context_window", 0) or 0))
        except Exception as exc:  # noqa: BLE001 - 路由打坏不影响会话
            log.debug("意图路由失败, 沿用既有 SOUL 档位: %s", exc)
            return self._soul_tier
        self._intent_route = decision
        override = decision.prompt_tier
        if not override:
            return self._soul_tier
        # 意图层档位映射: MINI 在当前架构下等价于 compact (SOUL_COMPACT.md),
        # COMPACT → compact, FULL → full。未识别字符串一律回退原档位 (fail-safe)。
        mapping = {"MINI": COMPACT, "COMPACT": COMPACT, "FULL": FULL}
        mapped = mapping.get(override.upper())
        if mapped is None:
            return self._soul_tier
        log.debug("意图路由覆盖 SOUL 档位: %s (intent=%s) -> %s",
                  self._soul_tier, decision.intent.value, mapped)
        return mapped

    def _build_system(self, task_hint: str = "") -> str:
        """组装「绝对稳定」的系统提示 (不含随任务变化的语义召回)。

        注入预算按提示词分层收紧 (见 _effective_prompt_limits)。
        """
        (skill_limit, notes_lines, doc_bytes, long_mem_chars) = (
            self._effective_prompt_limits()
        )
        prompt = build_system_prompt(
            home=self.config.home,
            workspace=self.workspace,
            memory_store=self.kernel.get("memory_store") if self.config.get("memory.auto_inject", True) else None,
            skill_manager=self.kernel.get("skill_manager") if self.config.get("skills.auto_inject", True) else None,
            skill_limit=skill_limit,
            codebase_map=self._codebase_map,
            reply_language=self.config.get("language", "") or "zh-CN",
            output_style=self.config.get("ui.output_style", "default"),
            cache_stable_prefix=self.config.get("prompt.cache_stable_prefix", True),
            memory_notes_enabled=self.config.get("memory.notes_enabled", True),
            memory_notes_max_lines=notes_lines,
            project_doc_max_bytes=doc_bytes,
            long_memory_max_chars=long_mem_chars,
            user_mode=self.user_mode,
            tier=self._effective_soul_tier(),
            config=self.config,
        )
        # 类型化子代理的角色指令 (task 工具的 AgentType.system_extra)
        if self.system_extra:
            prompt += "\n\n" + self.system_extra
        return prompt


    def _build_codebase_map_bg(self) -> None:
        """后台线程: 构建代码库地图, 完成后用「含地图」版本补建系统提示。

        仅在首轮尚未开始 (用户还在想/输入) 时补建 —— 交互会话中这段时间足够
        线程跑完, 地图照样钉进系统提示; 若首轮已启动 (headless 一次性任务), 则
        不补建, 避免并发改写正在使用的 _system_prompt。
        """
        try:
            if self._indexer is not None:
                self._codebase_map = self._indexer.build().map_text()
        except Exception as exc:  # noqa: BLE001
            log.debug("codebase 地图后台构建失败, 系统提示不含地图: %s", exc)
            self._codebase_map = ""
        if not self._turn_started:
            try:
                self._system_prompt = self._build_system(task_hint="")
            except Exception as exc:  # noqa: BLE001
                log.debug("含地图系统提示补建失败 (沿用基础版): %s", exc)


    def await_codebase_index(self, timeout: float = 0.0) -> None:
        """等待后台代码库索引完成 (最多 ``timeout`` 秒), 完成后用含地图版补建系统提示。

        首轮开始前调用: 交互会话中 init 与首条消息之间有用户输入间隔, 索引通常
        早已完成, 这里几乎不阻塞; 超大仓库首条消息极快时以 timeout 为上限,
        避免启动被拖慢。若首轮已启动 (``_turn_started``), 不再补建, 防止并发改写。
        """
        if self._index_thread is not None and self._index_thread.is_alive():
            self._index_thread.join(timeout=timeout)
        if self._codebase_map and not self._turn_started:
            try:
                self._system_prompt = self._build_system(task_hint="")
            except Exception as exc:  # noqa: BLE001
                log.debug("含地图系统提示补建失败 (沿用基础版): %s", exc)


    _CS_ENABLED = True  # 跨会话引用开关 (可用 config 关闭)


    def _resolve_cross_refs(self, text: str) -> str:
        """把用户输入里的 @session:<id> / @#<n> 引用展开为可读上下文 (只读注入)。

        解析失败不抛异常: 返回原文并用错误块提示。
        """
        if not self._CS_ENABLED:
            return text
        try:
            from .cross_session import CrossSessionResolver
            res = CrossSessionResolver(
                home=self.config.home,
                session_store=self.session,
            )
            return res.inject(text)
        except Exception as exc:  # noqa: BLE001
            log.debug("跨会话引用解析失败, 原样透传: %s", exc)
            return text
