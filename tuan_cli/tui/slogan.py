"""运行时标语域: 标语分发、阶段判定、trace/封存快照。

本模块由 tui.py 的 QxtTUI 拆分而来, 方法体逐行原样迁移 (无逻辑改动)。
模块级常量/工具/小类集中在 `tuan_cli.tui.common`, 由 `from .common import *`
注入到本模块命名空间, 因此方法体内对模块级名字的引用保持不变。
"""

from __future__ import annotations

from .common import *  # noqa: F401,F403

from ..ui.slogans import mapping  # noqa: F401  (tui.py 顶部同名 import)


class SloganMixin:
    """运行时标语域: 标语分发、阶段判定、trace/封存快照。"""

    # ---- 跨 mixin 共享实例属性/方法 (纯声明, 运行期不赋值) ----
    _lang: Any
    _last_event_ms: Any
    _phase: str
    _phase_since: float
    _slogan_errors: Any
    _slogan_lock: Any
    _slogan_log: Any
    _slogan_owner: str
    _slogan_sealed: Tuple[Dict[str, Any], ...]

    def _phase_of_context(self, context: Optional[str]) -> str:
            """事件上下文 → RuntimeSloganEngine 真实阶段 (驱动 stall 诊断)。"""
            return {
                "startup": "booting",
                "thinking": "waiting_model",
                "streaming": "streaming",
                "explore": "running_tool",
            }.get(context or "", "idle")

    def _slogan_dispatch(self, event: str, *,
                             strict: bool = False,
                             at_ms: Optional[int] = None
                             ) -> Optional["mapping.SloganDecision"]:
            """单一事件驱动入口 (真实接线, 不走静态示例)。

            成功返回 decision 并写 TUI 留痕 + 全局 owner 桶 (pick_for_event 内部做);
            安全事件返回空文案 decision (reason=security-notice); 未绑事件在非严格
            模式返回 None 并在两层各留 error 痕 (映射层 record_error + TUI 计数),
            严格模式向上抛 UnboundSloganEvent。
            """
            try:
                d = mapping.pick_for_event(event, lang=self._lang,
                                           owner=self._slogan_owner)
            except mapping.UnboundSloganEvent as exc_val:
                # 两层都留痕 —— 严格模式也要先记再抛; event 用 record_error
                # 返回的净化后 decision.event (与映射层保持一致的安全串)。
                try:
                    err_d = mapping.record_error(event, "unbound-event",
                                                 owner=self._slogan_owner)
                    safe_event = err_d.event
                except Exception:  # noqa: BLE001
                    safe_event = mapping.norm_owner(event)
                with self._slogan_lock:
                    self._slogan_errors.append(
                        (self._last_event_ms, safe_event, "error:unbound-event"))
                if strict:
                    raise
                return None
            with self._slogan_lock:
                self._slogan_log.append((event, d.context, d.reason, d.origin,
                                         d.entry_id, d.owner, d.at_ms))
                if len(self._slogan_log) > 64:
                    del self._slogan_log[:len(self._slogan_log) - 64]
            self._last_event_ms = d.at_ms
            if d.context is not None:
                self._phase = self._phase_of_context(d.context)
                self._phase_since = time.monotonic()
            return d

    def slogan_for(self, event: str, *, strict: bool = False) -> str:
            """事件 → 净化后标语文案。安全/未绑/出错返回空串 (靠 trace 区分)。"""
            d = self._slogan_dispatch(event, strict=strict)
            return d.text if d is not None else ""

    def slogan_trace(self) -> List[Dict[str, Any]]:
            """本实例运行时留痕快照 (每行 dict: event/context/reason/.../at_ms)。"""
            keys = ("event", "context", "reason", "origin", "entry_id",
                    "owner", "at_ms")
            return [dict(zip(keys, row)) for row in self._slogan_log]

    def slogan_owner(self) -> str:
            """本实例的日志桶 owner (多 TUI 实例不互串)。"""
            return self._slogan_owner

    def slogan_errors(self) -> Tuple[Tuple[str, str, str], ...]:
            """本实例记录到的错误痕 (event, entry_id, reason)。"""
            return tuple((ev, "", r) for (_at, ev, r) in self._slogan_errors)

    def slogan_closed_trace(self) -> Tuple[Dict[str, Any], ...]:
            """close() 时从全局桶封存的决策快照 (含 session.exit, 供审计回放)。"""
            with self._slogan_lock:
                sealed = tuple(self._slogan_sealed)
            out = []
            for d in sealed:
                out.append({
                    "event": d.event, "context": d.context, "reason": d.reason,
                    "origin": d.origin, "entry_id": d.entry_id,
                    "owner": d.owner, "at_ms": d.at_ms,
                })
            return tuple(out)

    def _release_slogan_owner(self) -> None:
            """close() 路径专用: 取走 owner 桶 (不记被动淘汰) 并在锁内封存快照。"""
            mapping.take_owner_log(self._slogan_owner)
            keys = ("event", "context", "reason", "origin", "entry_id",
                    "owner", "at_ms")
            with self._slogan_lock:
                self._slogan_sealed = tuple(
                    dict(zip(keys, row)) for row in self._slogan_log)

    # ------------------------------------------------------------ B3 XVI 生命周期接线

    def liveness(self):
            """运行时活性快照 (调试/doctor 用), 透传 runtime_slogans 引擎。"""
            engine = getattr(self, "_slogans", None)
            return engine.liveness() if engine is not None else None

    def _slogan_stream_started(self) -> None:
            """流式开始/分片: 节流 1s; 同时推进映射桶与引擎阶段/活性。"""
            now = time.monotonic()
            if now - getattr(self, "_slogan_last_stream_at", 0.0) < 1.0:
                return
            self._slogan_last_stream_at = now
            self._slogan_dispatch("model.streaming")
            engine = getattr(self, "_slogans", None)
            if engine is not None:
                engine.note_activity("streaming")

    def _slogan_tool_started(self, name: str = "") -> None:
            """工具开始: 阶段切到 running_tool (detail 只留工具名)。"""
            self._slogan_dispatch("tool.exploring")
            engine = getattr(self, "_slogans", None)
            if engine is not None:
                engine.note_activity("running_tool", detail=name)

    def _slogan_tool_ended(self) -> None:
            """工具结束: 只刷新活性证据 (kind=tool_end), 不改阶段。"""
            engine = getattr(self, "_slogans", None)
            if engine is not None:
                engine.note_progress(kind="tool_end")

    def _slogan_stream_ended(self) -> None:
            """流式收尾: 只刷新活性证据 (kind=stream_end), 阶段保持 streaming。"""
            engine = getattr(self, "_slogans", None)
            if engine is not None:
                engine.note_progress(kind="stream_end")

    def _slogan_turn_completed(self) -> None:
            """回合完成: 记 turn_completed 证据 (供跨回合回放)。"""
            engine = getattr(self, "_slogans", None)
            if engine is not None:
                engine.note_progress(kind="turn_completed")
