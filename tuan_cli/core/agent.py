"""Agent 主循环 —— ReAct: think -> tool -> observe -> think ... 直到完成。

融合点:
- Harness: 循环本身也是一个挂在插件容器上的组件, 每个 step 都发出内核事件
  并写入 append-only 会话事件流 (可审计、可回放)。
- Hermes: 每隔 skill_nudge_interval 个 turn, 循环会"自我提醒"反思 —
  这次的方法值不值得蒸馏成技能? 这就是自进化闭环的触发器。
- Claude Code: 大上下文机制 —— 系统提示里钉一份代码库地图, 长会话里按
  优先级智能压缩旧历史 (ContextManager), 关键信息不丢。

重构说明 (v0.3):
- 模型路由 → core/model_router.py (AgentModelRouter)
- 韧性组件 → core/resilience.py (AgentResilience)
- 可观测性 → core/observability.py (AgentObservability)
- Agent 本体只保留 ReAct 循环 + 组合委托
"""

from __future__ import annotations

import inspect
import logging
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Set, cast

from ..config import Config
from ..context.manager import ContextManager, estimate_messages
from .kernel import Kernel
from .model_router import AgentModelRouter
from .resilience import AgentResilience
from .observability import AgentObservability
from .prompts import build_system_prompt, build_task_context
from .prompt_tier import (COMPACT, FULL, PromptBudget, budget_for_tier,
                          resolve_prompt_budget, resolve_soul_tier)
from .tool_executor import ToolExecutor
from .auto_route import AutoRouter, RouteSession, tool_messages_of_turn
from .agent_helpers import (
    SKILL_NUDGE, summarize_messages, should_nudge,
    detect_verify_write_tools, ChunkFlusher,
)
from .loop_provider import LoopProvider, ReActLoop
from .agent_loop_fusion import (
    classify_transient,
    resolve_max_iterations,
    retry_step,
)
from .agent_goal import GoalMixin
from .agent_vision import VisionMixin
from .agent_compat import CompatMixin
from .agent_hooks import HooksMixin
from ..tools.base import ToolContext
from ..vision import build_user_content
from ..vision.blocks import ImageRef

log = logging.getLogger(__name__)


class Agent(GoalMixin, VisionMixin, CompatMixin, HooksMixin):
    def __init__(
        self,
        kernel: Kernel,
        config: Config,
        workspace: str,
        confirm: Optional[Callable[[str], bool]] = None,
        exclude_tools: tuple = (),
        indexer: Any = None,
        context_manager: Optional[ContextManager] = None,
        system_extra: str = "",
        user_mode: bool = False,
    ) -> None:
        self.kernel = kernel
        self.config = config
        self.workspace = workspace
        self.user_mode = user_mode  # 用户助手模式: USER_SOUL + 透明条款 + 排除 TUAN.md
        self.model = kernel.require("model_adapter")
        self.registry = kernel.require("tool_registry")
        self.session = kernel.get("session_store")
        self.messages: List[Dict[str, Any]] = []
        self.turn_count = 0
        self.total_usage = {"prompt_tokens": 0, "completion_tokens": 0}
        self._cancel_event = threading.Event()
        # 本轮用户原始输入 (供 Auto Memory 在 Stop 事件后分析, 不含系统前缀)
        self._last_user_input: str = ""
        self.exclude_tools: Set[str] = set(exclude_tools or ())
        # 子代理角色指令 (AgentType.system_extra): 追加到系统提示末尾 (空串则无感)
        self.system_extra = system_extra or ""
        self.yolo = config.is_yolo()
        self.plan_mode = False  # Plan Mode (对标 Claude Code: 只读模式, 不修改文件)
        # Goal 模式 (对标 Claude Code /goal): 设定完成条件, 循环直到满足
        self._goal: Optional[str] = None  # 目标描述 (None = 未启用 Goal)
        self._goal_check_prompt: Optional[str] = None  # 条件检查提示 (让快速模型判断是否满足)
        self.ctx = ToolContext(kernel=kernel, workspace=workspace, confirm=confirm, yolo=self.yolo)
        self.ctx.plan_mode = self.plan_mode
        # UI 句柄: ask_user 工具靠它把"模型提问"渲染进对话区卡片, 而不是
        # print()+input() 直接写 stdout (在全屏 TUI 下会冲垮布局且无法输入)。
        # 取 _ui_singleton.ui 惰性代理: TUI 启动后 attach_ui() 会把它指向
        # TuiUI, 普通 CLI/headless 下则是原 UI, 两者都实现了 ask_user 钩子或
        # 安全降级; 拿不到时留 None, 由工具自行走交互/降级分支。
        try:
            from ..cli._ui_singleton import ui as _shared_ui
            self.ctx.ui = _shared_ui
        except Exception:  # noqa: BLE001 - 取不到不影响其它工具
            self.ctx.ui = None
        # 同一列表对象: checkpoint 工具经 ctx.conversation 截断对话流 (rewind)
        self.ctx.conversation = self.messages
        # 反向引用: 让工具 handler 能同步 agent 级状态 (如 enter/exit_plan_mode 同步 plan_mode)
        self.ctx.agent = self
        # 多模态: 用户挂接的图片缓冲 (一次性, 随下一轮 user 消息发送后清空)
        self.pending_images: List[ImageRef] = []
        # 当前生效的工具集名 (Plan/YOLO/Standard), 供主循环取用对应工具清单
        self._tool_set: str = self._compute_tool_set()
        # 工具暴露档位 (minimal|standard|full): 控制传给模型的 tools 列表大小。
        # 来源 config tools.exposure (CLI --tools 已写回 config); auto 按模型能力解析。
        self.exposure: str = self._resolve_exposure()
        # --- 提取的组件 ---
        # 模型路由器 (core/model_router.py): 自动选择/切换模型
        self._router = AgentModelRouter(config, kernel)
        # 规划/执行 + 卡住升级的跨 turn 路由状态 (core/auto_route)
        self._auto = AutoRouter(self.config)
        self._route_session = RouteSession()
        # 韧性组件 (core/resilience.py): 重试/限流/熔断
        self._resilience = AgentResilience(config, kernel)
        # 可观测性组件 (core/observability.py): 遥测/用量/成本
        self._obs = AgentObservability(config, self.config.home)

        # 工具执行器 (从 Agent 拆出的独立组件)
        self._tool_executor = ToolExecutor(
            registry=self.registry,
            messages=self.messages,
            session_append=self._session_append,
            tool_content_fn=self._tool_content,
            telemetry=self._obs.telemetry,
            trace_id=self._obs.trace_id,
        )

        # 提示词分层 (待办4 已落地): 按当前模型上下文窗口定档, 小上下文模型收紧注入预算。
        # 稳定前缀档位 (_soul_tier): auto 下按窗口联动 —— >=128k 大上下文模型读
        # SOUL_FULL.md 完整提示词, <128k 小上下文模型只读 SOUL_COMPACT.md。
        # 解析失败一律回退 full 档 (== 历史行为), 绝不因分层逻辑把提示词打坏。
        self.prompt_tier, self.context_window, self.prompt_budget = self._resolve_prompt_tier()
        # 稳定前缀档位: 显式 compact/full 采信用户; auto 下按窗口联动
        # (大上下文读 SOUL_FULL.md, 小上下文读 SOUL_COMPACT.md)。
        self._soul_tier = self._resolve_soul_tier()

        # 大上下文: 把代码库地图钉进系统提示。
        # 索引构建 (os.walk + 逐文件 LOC 统计) 在大型仓库可达数秒, 同步做会卡死启动
        # (曾导致 `tuan run` 全程多等 4~5s, 即便缺 API Key 立即失败也要先走完扫描)。
        # 改为后台线程构建: 启动不阻塞; 交互会话中用户尚未发首条消息时构建完成,
        # 自动用「含地图」版本补建一次系统提示 (首轮开始前); 一次性 headless 任务则
        # 降级为不含地图, 功能无损 (地图仅为上下文增强, 且 find 工具仍可用)。
        self._codebase_map = ""
        self._turn_started = False
        self._index_thread: Optional[threading.Thread] = None
        self._indexer = (
            indexer if (indexer is not None and config.get("context.pin_codebase", True)) else None
        )
        if self._indexer is not None:
            self._index_thread = threading.Thread(
                target=self._build_codebase_map_bg, daemon=True, name="codebase-index"
            )
            self._index_thread.start()

        self._system_prompt = self._build_system(task_hint="")

        # 上下文优先级管理器
        if context_manager is not None:
            self.context_manager = context_manager
        else:
            self.context_manager = ContextManager(
                keep_recent=config.get("context.keep_recent", 14),
                budget_tokens=config.get("context.budget_tokens", 60000),
                compact_trigger=config.get("context.compact_trigger", None),
                strategy=config.get("context.compact_strategy", "smart"),
                summarize=self._summarize,
            )

        # 可插拔 Loop: 从 kernel 读取 LoopProvider, 无则用默认 ReAct
        self._loop_provider: LoopProvider = kernel.get("loop_provider") or ReActLoop()

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
            tier=self._soul_tier,
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

    # ------------------------------------------------------------ 会话事件流

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

    def _session_append(self, event_type: str, **payload: Any) -> None:
        """把事件写入 append-only 会话流 (可审计、可回放)。"""
        if self.session is not None:
            try:
                self.session.append(event_type, payload)
            except Exception as exc:  # noqa: BLE001
                log.debug("会话事件写入失败 (%s): %s", event_type, exc)

    # ------------------------------------------------------------ 用量统计

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
        return cast(Optional[float], self._obs.cache_hit_rate())

    # ------------------------------------------------------------ 技能蒸馏 (Hermes 闭环)

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

    # ------------------------------------------------------------ 主循环

    def cancel(self) -> None:
        """请求在当前模型调用或工具步骤结束后停止当前任务。"""
        self._cancel_event.set()

    def clear_cancel(self) -> None:
        """清除取消请求，准备执行下一项任务。"""
        self._cancel_event.clear()

    # ------------------------------------------------------------ Goal 模式

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

    # ------------------------------------------------------------ 自动模型路由

    def _maybe_route_model(self, task: str, override: int = 0, has_images: Optional[bool] = None) -> None:
        """按 router 配置自动选择/切换模型 —— 委托给 AgentModelRouter。"""
        self._router.maybe_route(task, override=override, has_images=has_images,
                                current_model=self.model, pending_images=self.pending_images)
        # 路由可能切换了模型, 同步到当前实例
        if self._router.last_route and self._router.last_route.get("switch"):
            self.model = self.kernel.require("model_adapter")

    # ------------------------------------------------------------ 工具执行 (委托 ToolExecutor)

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

    # ---- 向后兼容属性 (CompatMixin) 与用户级 Hooks (HooksMixin) 已提取 ----
    # 见 core/agent_compat.py 与 core/agent_hooks.py。

    # ------------------------------------------------------------ 主循环

    def effective_tool_set(self) -> str:
        """当前生效的工具集名 (plan/yolo/standard), 与 plan_mode/yolo 实时同步。

        主循环据此向模型提供对应模式的工具清单 —— Plan 只给只读工具,
        YOLO/Standard 给全量工具 (危险操作的批准策略由权限闸门控制)。
        """
        self._tool_set = self._compute_tool_set()
        return self._tool_set

    def _compute_tool_set(self) -> str:
        if self.plan_mode:
            return "plan"
        if self.yolo:
            return "yolo"
        return "standard"

    def _resolve_exposure(self) -> str:
        """解析工具暴露档位 (minimal|standard|full)。

        config ``tools.exposure`` 可为 minimal/standard/full/auto; auto 按当前模型
        名启发式解析 (弱模型 → minimal, 否则 standard)。解析失败一律回退 standard,
        绝不因配置异常把工具集降成空 (fail-safe)。
        """
        from ..tools.tiers import DEFAULT_EXPOSURE, resolve_exposure
        raw: Optional[str] = None
        model: str = ""
        try:
            raw = self.config.get("tools.exposure", None)
        except Exception:  # noqa: BLE001
            raw = None
        try:
            model = self.config.get("model.model", "") or ""
        except Exception:  # noqa: BLE001
            model = ""
        try:
            return resolve_exposure(raw, model)
        except Exception:  # noqa: BLE001
            return DEFAULT_EXPOSURE

    def _schemas(self) -> Any:
        """取传给模型的工具清单 (按 effective_tool_set + exposure 过滤)。

        对 registry.schemas 做接口兼容: 若它接受 tool_set / exclude_tools / exposure
        关键字 (真实 ToolRegistry / 测试双), 则透传; 否则极简 registry (仅接受无参调用)
        退化为裸调, 保证主循环总能拿到 schema 列表而不会因 TypeError 中断模型调用。
        详见 test_tool_set_wiring (要求透传 tool_set) 与 test_router/test_vision
        (极简 fake 只接受 schemas())。这确保主循环能正常进入模型轮并推进转台切换。
        """
        sch = getattr(self.registry, "schemas", None)
        if sch is None:
            return []
        try:
            sig = inspect.signature(sch)
        except (TypeError, ValueError):
            sig = None  # 无法反射签名 → 保守透传 (真实 registry 支持关键字)
        params = list(sig.parameters.values()) if sig is not None else []
        has_kw = sig is None or any(
            p.kind == inspect.Parameter.VAR_KEYWORD for p in params
        )
        # 用 getattr 兜底: _schemas 在模型调用热路径上, 属性缺失不应让整个模型轮
        # 崩溃成 "[模型错误] 'Agent' object has no attribute ..."。正常构造时
        # __init__ 已设置这两个属性; 这里的兜底覆盖子类覆写 __init__ 未调用 super、
        # 以及测试用 Agent.__new__ 绕过 __init__ 的场景。
        tool_set = getattr(self, "_tool_set", None) or self.effective_tool_set()
        if has_kw or any(p.name == "tool_set" for p in params):
            kwargs: Dict[str, Any] = {
                "tool_set": tool_set,
                "exclude_tools": getattr(self, "exclude_tools", set()),
            }
            # 仅当目标 schemas 支持 exposure 时透传 (兼容只认 tool_set 的旧双)
            if has_kw or any(p.name == "exposure" for p in params):
                kwargs["exposure"] = getattr(self, "exposure", None)
            return sch(**kwargs)
        # 极简 registry (如测试双 `def schemas(self)`) 不接受关键字 → 裸调
        return sch()

    # ---- 共享辅助: 消息解析 / 运行准备 / Goal / 收尾 ----

    # 续跑判定线索 (小写匹配)
    _CONTINUE_CUES = ("接下来", "然后", "还需要", "下一步", "让我", "我将", "正在",
                      "准备", "待办", "尚未", "还没",
                      "next", "let me", "i'll", "i will", "going to", "then i",
                      "need to", "going to")
    _DONE_CUES = ("完成", "已修", "已实现", "已创建", "已删除", "已更新", "已写入", "已写好", "已写",
                  "已保存", "已生成", "已添加", "已修复", "已运行", "任务完成", "全部完成",
                  "done", "completed", "finished", "fixed", "implemented",
                  "created", "deleted", "all set")

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

    def run(
        self,
        user_input: str,
        stream: bool = True,
        on_token: Optional[Callable[[str], None]] = None,
        on_tool: Optional[Callable[[str, str], None]] = None,
        on_reason: Optional[Callable[[str], None]] = None,
        on_tool_result: Optional[Callable[[str, str], None]] = None,
        on_error: Optional[Callable[[str], None]] = None,
        max_iterations: Optional[int] = None,
        session_id: Optional[str] = None,
    ) -> str:
        """运行一轮完整对话。

        可插拔 Loop: 若 kernel 中注册了 LoopProvider, 委托给它执行;
        否则使用内联 ReAct 循环 (向后兼容)。

        session_id: 若提供, 本轮写入独立的 SessionStore 文件 (便于 tuan replay 逐会话回放);
        否则复用进程级共享的 session_store。
        """
        # 首轮开始前: 等后台代码库索引 (最多 0.3s) 把地图补进系统提示。
        # 交互会话中用户思考/输入期间索引早已完成, 这里几乎不阻塞;
        # 超大仓库首条消息极快时地图可能缺席本轮 (降级, 非正确性)。
        self.await_codebase_index(timeout=0.3)
        self._turn_started = True
        self.clear_cancel()

        # ---- 可插拔 Loop: 有 LoopProvider 时委托执行 ----
        loop = getattr(self, '_loop_provider', None)
        if loop is not None:
            return self._run_with_loop(
                loop, user_input,
                stream=stream, on_token=on_token, on_tool=on_tool,
                on_reason=on_reason, on_tool_result=on_tool_result,
                on_error=on_error, max_iterations=max_iterations,
                session_id=session_id,
            )

        # ---- 无 LoopProvider: 内联 ReAct 循环 (向后兼容) ----
        return self._run_react_inline(
            user_input,
            stream=stream, on_token=on_token, on_tool=on_tool,
            on_reason=on_reason, on_tool_result=on_tool_result,
            on_error=on_error, max_iterations=max_iterations,
            session_id=session_id,
        )

    def _run_with_loop(
        self,
        loop: "LoopProvider",
        user_input: str,
        *,
        stream: bool = True,
        on_token: Optional[Callable[[str], None]] = None,
        on_tool: Optional[Callable[[str, str], None]] = None,
        on_reason: Optional[Callable[[str], None]] = None,
        on_tool_result: Optional[Callable[[str, str], None]] = None,
        on_error: Optional[Callable[[str], None]] = None,
        max_iterations: Optional[int] = None,
        session_id: Optional[str] = None,
    ) -> str:
        """使用 LoopProvider 执行对话, 保留 Agent 的 session/trace 仪式。"""
        on_token, run_trace, raw_on_token = self._prepare_run(
            user_input, session_id, on_token,
        )

        # 委托给 LoopProvider
        try:
            answer = loop.run_loop(
                self, user_input,
                stream=stream, on_token=on_token, on_tool=on_tool,
                on_reason=on_reason, on_tool_result=on_tool_result,
                on_error=on_error, max_iterations=max_iterations,
                session_id=session_id,
            )
        except Exception as exc:  # noqa: BLE001
            answer = f"[Loop 错误] {exc}"
            if on_error:
                on_error(str(exc))

        # Goal 模式 + 收尾
        self._handle_goal(answer, 0, max_iterations or 0, raw_on_token)
        return self._teardown_run(answer, run_trace, raw_on_token, on_error, nudge=False)

    def _run_react_inline(self, user_input: str, **kwargs: Any) -> str:
        """内联 ReAct 循环 (无 LoopProvider 时的向后兼容路径)。"""
        stream = kwargs.get("stream", True)
        on_token = kwargs.get("on_token")
        on_tool = kwargs.get("on_tool")
        on_reason = kwargs.get("on_reason")
        on_tool_result = kwargs.get("on_tool_result")
        on_error = kwargs.get("on_error")
        max_iterations = kwargs.get("max_iterations")
        session_id = kwargs.get("session_id")

        on_token, run_trace, raw_on_token = self._prepare_run(
            user_input, session_id, on_token,
        )

        max_iter = resolve_max_iterations(self.config, max_iterations)
        iteration = 0
        answer = ""
        # 续跑兜底计数 (防止"中途说句话就停"被无限续跑)
        self._continue_nudges = 0
        continue_nudge_max = int(self.config.get("fusion.continue_nudge_max", 3) or 0)

        while iteration < max_iter:
            if self._cancel_event.is_set():
                break
            budget = float(self.config.get("router.budget_limit", 0.0) or 0.0)
            if budget > 0:
                current_cost = self._estimate_total_cost()
                if current_cost >= budget:
                    if raw_on_token:
                        on_token(f"\n[预算已用尽] 已花费 ${current_cost:.4f} >= 上限 ${budget:.2f}, 自动停止。\n")
                    self._session_append("budget.exceeded", cost=current_cost, budget=budget)
                    break
            iteration += 1
            self.turn_count += 1

            if self._auto.enabled and (self._auto.plan_execute or self._auto.escalate):
                override = self._auto.decide_override(self._route_session)
                if override:
                    keep_vision = getattr(getattr(self.model, "capabilities", None), "vision", False)
                    self._maybe_route_model(user_input, override=override, has_images=keep_vision)

            if self.context_manager.needs_compact(self.messages):
                self._notify_hook("PreCompact", {"trigger": "auto"})
            self.messages, _dropped = self.context_manager.compact_if_needed(self.messages)

            try:
                result = self._chat_with_retry(
                    self.messages,
                    tools=self._schemas(),
                    stream=stream, on_token=on_token, on_reason=on_reason,
                )
            except Exception as exc:  # noqa: BLE001
                # 业务错误 (C-2: 缺 Key/配置损坏/模型不存在) 渲染固定模板给用户;
                # 其余异常保留原始信息。协议不变: answer 仍以 [模型错误] 开头
                # (后台 worker / 会话记录依赖该前缀)。
                from .errors import friendly_for
                tmpl = friendly_for(exc)
                if on_error:
                    on_error(tmpl.render() if tmpl else str(exc))
                else:
                    log.error("模型调用失败: %s", exc)
                err_msg = f"[模型错误] {exc}"
                answer = err_msg
                break

            if result is None:
                continue
            usage = getattr(result, "usage", None)
            if usage:
                self._accumulate_usage(usage)

            msg_dict = self._parse_assistant_message(result)
            self.messages.append(msg_dict)
            self._session_append("assistant", message=msg_dict)
            tool_calls = msg_dict.get("tool_calls", [])
            if not tool_calls:
                answer = msg_dict.get("content", "")
                # ---- 续跑兜底: 模型可能在任务中途"说了一句话就停" ----
                # 纯文本回复历来被当作最终答案直接 break; 但弱模型经常在多步任务的
                # 中途输出一段解释/计划文本而**不带工具调用**, 循环随即终止 ——
                # 表现即"Agent 干一会儿活就停下来, 任务还没干完"。
                # 此时若上下文显示刚才还在干工具活, 注入一条继续提示让模型自己
                # 判断"完成了就说 DONE, 否则接着干", 而不是替它下结论。
                had_tool_activity = any(
                    m.get("role") == "assistant" and m.get("tool_calls")
                    for m in self.messages[-8:]
                )
                awaiting = getattr(self, "_awaiting_done", False)
                # a) 文本明确表达"已完成" → 直接结束 (省一次往返)
                if not self._looks_unfinished(answer):
                    self._awaiting_done = False
                    break
                # b) 对我们 DONE 询问的回应且给出完成答复 → 结束
                if awaiting and ("done" in answer.lower()[:30]
                                 or any(c in answer for c in self._DONE_CUES)):
                    self._awaiting_done = False
                    break
                # c) 刚才在干工具活且还有续跑额度 → 注入询问, 让模型自己确认
                if had_tool_activity and self._continue_nudges < continue_nudge_max:
                    self._continue_nudges += 1
                    self._awaiting_done = True
                    self._session_append("continue_nudge", nudge=self._continue_nudges)
                    self.messages.append({"role": "user", "content": (
                        "若任务已经全部完成, 请回复 DONE 并简述结果; "
                        "否则不要停下来解释, 直接继续执行下一步。")})
                    continue
                self._awaiting_done = False
                break

            n_tool_msgs_before = len(self.messages)
            def _do_execute_tools(tc: Any = tool_calls) -> None:
                self._execute_tools(tc, on_tool=on_tool, on_tool_result=on_tool_result)
            retry_step(
                _do_execute_tools,
                is_transient=classify_transient,
            )
            self._run_verify_loop(tool_calls, on_token=on_token)
            self._auto.observe_turn(
                self._route_session,
                tool_messages_of_turn(self.messages, n_tool_msgs_before),
            )

        # Goal 模式
        self._handle_goal(answer, iteration, max_iter, raw_on_token)

        if not answer and iteration >= max_iter:
            if self._goal:
                answer = f"(达到最大迭代次数, Goal 未完成: {self._goal})"
            else:
                answer = "(达到最大迭代次数, 已停止。)"

        return self._teardown_run(answer, run_trace, raw_on_token, on_error)

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
        return cast(Dict[str, Any], self._resilience.status())

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
