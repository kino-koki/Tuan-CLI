"""标语 ↔ 真实运行时事件的**一一对应表**与全量注册表。

本模块回答一个问题：**每条标语到底由哪个真实事件触发？**

原库的真实状态 (实测复现, 见 ``SLOGAN_MAPPING.md`` §1):

- 860 条标语躺在仓库根目录 ``slogans/``, 而 docstring 全写
  ``from tuan_cli.ui.slogans import ...`` —— 这个路径当时**不存在**;
- 全仓 13 处「接入」全是 docstring 示例文本, **真实 import 一行都没有**;
- ``pick("totally.unknown", lang="zh-CN")`` 静默返回 ``"Here."`` ——
  一条没有任何对应事件的标语被随机飘到界面上;
- ``pick("bg.progress", lang="ja")`` 返回英文 ``"Still at it."`` ——
  8 个语种的 6 个扩展场景 (48 个组合) 全无本地词条。

三条硬约束 (延续 ``runtime_slogans`` 深度轮):

1. **双向完备**: 每个上下文有唯一事件, 每个事件有唯一上下文;
   每条标语的注册表项都带 ``event``; 不存在孤儿标语、不存在无标语事件。
2. **严格分发**: ``pick_for_event`` 对未知事件抛异常, 绝不静默回落
   ``idle`` 飘一句无关的俏皮话。
3. **安全告警不降级**: ``SECURITY_EVENTS`` 显式无标语。用户库设计稿
   原文「不要动: 安全拦截的结构化告警 (那是降级, 不是优化)」在这里
   变成可执行的 fail-closed 契约, 而不是一句注释。

另外把 ``runtime_slogans`` 的 5 个 PHASE 也纳入同一张表
(``PHASE_EVENTS``), 使「活性引擎的阶段」与「标语库的上下文」不是两套
互相不知道对方存在的系统。
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from typing import Dict, FrozenSet, Optional, Tuple

from . import picker, universal, extra, extra_locales
from .picker import UnknownSloganContext
from .locales import LANGUAGES

__all__ = [
    "EventBinding", "SloganEntry", "AuditReport", "SloganDecision",
    "UnboundSloganEvent", "UnknownSloganContext",
    "EVENT_BINDINGS", "SECURITY_EVENTS", "CONTEXT_EVENTS", "PHASE_EVENTS",
    "ALL_CONTEXTS", "build_registry", "audit", "pick_for_event",
    "verbs_for_phase", "entry_for", "dispatch_log", "reset_dispatch_log",
]


class UnboundSloganEvent(ValueError):
    """事件没有绑定任何标语上下文 —— 严格模式下绝不静默兜底。"""


# ------------------------------------------------------------------ 事件绑定

@dataclass(frozen=True)
class EventBinding:
    """一个真实运行时事件 → 一个标语上下文。

    ``allow_slogan=False`` 表示这是安全/裁决类事件: 它的输出必须是
    结构化告警, **绝不**被随机标语替换或稀释。
    """
    event: str
    context: Optional[str]
    note: str
    allow_slogan: bool = True


def _b(event: str, context: str, note: str) -> EventBinding:
    return EventBinding(event, context, note, True)


#: 18 个真实事件 → 16 个上下文。多对一是**显式共享**, 不是遗漏:
#: ``model.streaming`` 与 ``model.waiting`` 同属 "结果还没交付",
#: ``turn.retry`` 与 ``undo.applied`` 同属 "重来一次"。
EVENT_BINDINGS: Dict[str, EventBinding] = {
    b.event: b for b in (
        _b("session.start",       "startup",        "会话启动 / 欢迎横幅就绪"),
        _b("model.waiting",      "thinking",       "已提交, 等模型首个 token"),
        _b("model.streaming",    "thinking",       "流式分片到达 (结果仍未交付, 与 waiting 共享)",
           ),
        _b("turn.error",         "error",          "回合内可恢复错误"),
        _b("undo.applied",       "undo",           "撤销生效"),
        _b("turn.completed",     "done",           "回合完成 / 分隔线"),
        _b("tool.exploring",     "explore",        "工具在探索文件与代码"),
        _b("session.idle",       "idle",           "空闲位 / 等待输入"),
        _b("user.collab",        "together",       "协作提示 (非裁决)"),
        _b("guard.notice",       "guard",          "非拦截的谨慎提示"),
        _b("session.exit",       "signoff",        "退出 / 收工"),
        _b("model.switched",     "model.switch",   "切换模型或供应商完成"),
        _b("budget.warning",     "budget.warn",    "接近上下文 / 费用预算上限"),
        _b("background.started", "bg.start",       "后台 / 长任务派发"),
        _b("background.progress", "bg.progress",   "后台任务进行中 (>30s)"),
        _b("remote.paired",      "pairing",        "手机扫码 / 远端配对成功"),
        _b("memory.written",     "memory.write",   "自动写入记忆"),
        _b("turn.retry",         "undo",           "回炉重试 (与 undo 共享 '重来一次')"),
    )
}

#: 这些事件**没有标语**。结构化安全告警不得被俏皮话降级。
SECURITY_EVENTS: FrozenSet[str] = frozenset({
    "security.blocked", "security.redline", "permission.denied",
    "confirm.required", "sandbox.degraded", "hook.failed",
})

#: 反向唯一映射: 每个上下文只有一个主事件 (共享事件不改写主事件)。
CONTEXT_EVENTS: Dict[str, str] = {
    "startup": "session.start",
    "thinking": "model.waiting",
    "error": "turn.error",
    "undo": "undo.applied",
    "done": "turn.completed",
    "explore": "tool.exploring",
    "idle": "session.idle",
    "together": "user.collab",
    "guard": "guard.notice",
    "signoff": "session.exit",
    "model.switch": "model.switched",
    "budget.warn": "budget.warning",
    "bg.start": "background.started",
    "bg.progress": "background.progress",
    "pairing": "remote.paired",
    "memory.write": "memory.written",
}

#: ``runtime_slogans.RuntimeSloganEngine`` 的 5 个阶段 → 各自独立事件。
#: 这使活性引擎与标语库共用同一张对应表, 不是两套互不知情的系统。
PHASE_EVENTS: Dict[str, str] = {
    "booting": "session.start",
    "waiting_model": "model.waiting",
    "streaming": "model.streaming",
    "running_tool": "tool.exploring",
    "retrying": "turn.retry",
}

ALL_CONTEXTS: Tuple[str, ...] = tuple(universal.CONTEXTS) + tuple(extra.CONTEXTS)


# ------------------------------------------------------------------ 注册表

@dataclass(frozen=True)
class SloganEntry:
    """一条标语的注册项 —— 「每个标语都要对应的」的落点。

    ``id`` 是稳定的 ``lang:context:index:sha8``, 可用于审计回放;
    ``event`` 由 ``CONTEXT_EVENTS`` 反查, 保证每条标语都能回答
    「我由哪个真实事件触发」。
    """
    id: str
    lang: str
    context: str
    event: str
    index: int
    text: str
    origin: str                 # locale | locale-patch | locale-extra | universal | extra-universal

    @property
    def is_localized(self) -> bool:
        return self.origin in ("locale", "locale-patch", "locale-extra")


def _sha8(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:8]


def build_registry() -> Tuple[SloganEntry, ...]:
    """遍历 10 语种 × 16 上下文的所有候选词条, 生成全量注册表。

    词条来源由 ``picker.pool_entries()`` 标注, 不靠猜测。英文通用池
    作为所有语种的兜底仍然登记 (origin=universal/extra-universal),
    但 ``audit()`` 会单独报告「某语种某场景**没有本语种词条**」的组合 ——
    那才是「没对应上」, 有兜底不等于对应上了。
    """
    out: list[SloganEntry] = []
    for lang in LANGUAGES:
        for ctx in ALL_CONTEXTS:
            event = CONTEXT_EVENTS.get(ctx, "")
            for i, pe in enumerate(picker.pool_entries(ctx, lang)):
                out.append(SloganEntry(
                    id=f"{lang}:{ctx}:{i:03d}:{_sha8(pe.text)}",
                    lang=lang, context=ctx, event=event,
                    index=i, text=pe.text, origin=pe.origin,
                ))
    return tuple(out)


_REGISTRY: Optional[Tuple[SloganEntry, ...]] = None


def registry() -> Tuple[SloganEntry, ...]:
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = build_registry()
    return _REGISTRY


def entry_for(slogan_id: str) -> Optional[SloganEntry]:
    """按稳定 id 反查一条标语及其触发事件。"""
    for e in registry():
        if e.id == slogan_id:
            return e
    return None


# ------------------------------------------------------------------ 审计

@dataclass(frozen=True)
class AuditReport:
    total_slogans: int
    total_events: int
    total_contexts: int
    total_languages: int
    orphan_slogans: Tuple[str, ...] = ()
    events_without_pool: Tuple[str, ...] = ()
    contexts_without_event: Tuple[str, ...] = ()
    events_without_context: Tuple[str, ...] = ()
    locale_gaps: Tuple[str, ...] = ()        # "lang:ctx" 无本语种词条
    empty_pools: Tuple[str, ...] = ()
    duplicate_ids: Tuple[str, ...] = ()
    unsafe_bindings: Tuple[str, ...] = ()
    phase_gaps: Tuple[str, ...] = ()
    thin_pools: Tuple[str, ...] = ()         # 本语种词条 <3 (如实披露, 不算失败)
    clipped_slogans: Tuple[str, ...] = ()    # 过不了统一净化出口 / 超宽的词条
    sanitizer_source: str = "unavailable"
    sanitizer_shared: bool = False

    @property
    def ok(self) -> bool:
        """「每个标语都要对应的」的硬判据 —— 不是文档自述, 是运行时计算。"""
        return not any((
            self.orphan_slogans, self.events_without_pool,
            self.contexts_without_event, self.events_without_context,
            self.locale_gaps, self.empty_pools, self.duplicate_ids,
            self.unsafe_bindings, self.phase_gaps, self.clipped_slogans,
        )) and self.sanitizer_shared

    def as_dict(self) -> Dict[str, object]:
        return {
            "ok": self.ok,
            "total_slogans": self.total_slogans,
            "total_events": self.total_events,
            "total_contexts": self.total_contexts,
            "total_languages": self.total_languages,
            "orphan_slogans": len(self.orphan_slogans),
            "events_without_pool": len(self.events_without_pool),
            "contexts_without_event": len(self.contexts_without_event),
            "events_without_context": len(self.events_without_context),
            "locale_gaps": len(self.locale_gaps),
            "empty_pools": len(self.empty_pools),
            "duplicate_ids": len(self.duplicate_ids),
            "unsafe_bindings": len(self.unsafe_bindings),
            "phase_gaps": len(self.phase_gaps),
            "thin_pools": len(self.thin_pools),
            "sanitizer_source": self.sanitizer_source,
            "sanitizer_shared": self.sanitizer_shared,
        }


def _sanitizer():
    """复用 ``_clean`` 的唯一净化出口 (纯 stdlib, 永远可用)。

    前两轮 ``runtime_slogans`` 的净化层已抽到本包的 ``_clean``,
    活性引擎只是 re-export 同一批函数对象 —— 新标语库与它共用
    **同一份实现**, 不产生第三套宽度/净化真值。
    ``audit().sanitizer_shared`` 会断言这一点。
    """
    from . import _clean  # noqa: PLC0415

    return _clean.sanitize_verb, _clean.display_cols, _clean._MAX_VERB_COLS


def audit() -> AuditReport:
    """运行时全量核验九项不变量。任何一项非零, ``ok`` 就是 False。"""
    reg = registry()
    ids = [e.id for e in reg]
    dup = tuple(sorted({i for i in ids if ids.count(i) > 1}))

    valid_events = set(EVENT_BINDINGS) | set(SECURITY_EVENTS)
    orphan = tuple(sorted(e.id for e in reg
                          if not e.event or e.event not in valid_events))

    ctx_no_event = tuple(sorted(c for c in ALL_CONTEXTS
                                if c not in CONTEXT_EVENTS))
    ev_no_ctx = tuple(sorted(e for e, b in EVENT_BINDINGS.items()
                             if b.context not in ALL_CONTEXTS))

    # 每个事件在其绑定的上下文里至少有一个语种的非空池
    ev_no_pool = []
    for ev, b in EVENT_BINDINGS.items():
        if not b.context:
            continue
        if not any(picker.pool_entries(b.context, lang) for lang in LANGUAGES):
            ev_no_pool.append(ev)

    # 每个 (语种, 上下文) 至少有 1 条本语种词条, 且池非空
    gaps, empties, thin = [], [], []
    for lang in LANGUAGES:
        for ctx in ALL_CONTEXTS:
            entries = picker.pool_entries(ctx, lang)
            key = f"{lang}:{ctx}"
            if not entries:
                empties.append(key)
            # 英文语种的通用英文池同为英文, 按本语种口径计算
            if lang == "en":
                local_n = len(entries)
            else:
                local_n = sum(1 for e in entries if e.is_local)
            if local_n == 0:
                gaps.append(key)
            elif local_n < 3:
                thin.append(f"{key}={local_n}")

    # 安全事件绝不能被绑上标语
    unsafe = tuple(sorted(e for e in SECURITY_EVENTS
                          if e in EVENT_BINDINGS and EVENT_BINDINGS[e].allow_slogan))

    phase_gaps = tuple(sorted(ph for ph, ev in PHASE_EVENTS.items()
                              if ev not in EVENT_BINDINGS))

    # 每条标语都必须能**完整**通过唯一净化出口 (不被截成半句、不带不可见字符)
    clipped = []
    _san = _sanitizer()
    if _san:
        sanitize_verb, display_cols, max_cols = _san
        for e in reg:
            if (sanitize_verb(e.text) != e.text
                    or display_cols(e.text) > max_cols):
                clipped.append(e.id)

    s = _sanitizer()
    src = "ui.slogans._clean.sanitize_verb" if s else "unavailable"
    shared = False
    if s:
        try:
            from tuan_cli.tui import runtime_slogans as _rs  # noqa: PLC0415
            shared = _rs.sanitize_verb is s[0]
            src = "ui.slogans._clean (shared with runtime_slogans)" if shared else src
        except Exception:  # noqa: BLE001 - tui 依赖缺失时如实报告未共享
            pass

    return AuditReport(
        total_slogans=len(reg),
        total_events=len(EVENT_BINDINGS),
        total_contexts=len(ALL_CONTEXTS),
        total_languages=len(LANGUAGES),
        orphan_slogans=orphan,
        events_without_pool=tuple(sorted(ev_no_pool)),
        contexts_without_event=ctx_no_event,
        events_without_context=ev_no_ctx,
        locale_gaps=tuple(sorted(gaps)),
        empty_pools=tuple(sorted(empties)),
        duplicate_ids=dup,
        unsafe_bindings=unsafe,
        phase_gaps=phase_gaps,
        thin_pools=tuple(sorted(thin)),
        clipped_slogans=tuple(sorted(clipped)),
        sanitizer_source=src,
        sanitizer_shared=shared,
    )


# ------------------------------------------------------------------ 分发

@dataclass(frozen=True)
class SloganDecision:
    """一次事件分发的结果 (可审计、可回放、脱敏)。"""
    event: str
    context: Optional[str]
    lang: str
    text: str
    reason: str                    # ok | security-notice | sanitizer-unavailable | rejected
    at_ms: int = 0
    entry_id: str = ""
    origin: str = ""              # locale | universal-fallback | fallback-hardcoded


_dispatch_log: list[SloganDecision] = []
_DISPATCH_CAP = 64


def dispatch_log() -> Tuple[SloganDecision, ...]:
    return tuple(_dispatch_log)


def reset_dispatch_log() -> None:
    _dispatch_log.clear()


def _record(d: SloganDecision) -> None:
    _dispatch_log.append(d)
    if len(_dispatch_log) > _DISPATCH_CAP:
        del _dispatch_log[:-_DISPATCH_CAP]


def pick_for_event(event: str, lang: Optional[str] = None, *,
                   now: Optional[float] = None) -> SloganDecision:
    """**唯一**对外的事件驱动取词入口。

    - 未知事件 → 抛 ``UnboundSloganEvent``, 绝不静默回落 ``idle``;
    - 安全事件 → 返回空文案 + ``security-notice`` (结构化告警不降级);
    - 净化出口不可用 → fail-closed 返回空, 不渲染未净化文案;
    - 正常事件 → 走 ``picker.pick_strict``, 再过统一净化/列宽出口。
    """
    at = int((time.monotonic() if now is None else now) * 1000)
    resolved = picker.resolve_lang(lang)

    if event in SECURITY_EVENTS:
        d = SloganDecision(event, None, resolved, "", "security-notice", at, "", "")
        _record(d)
        return d
    binding = EVENT_BINDINGS.get(event)
    if binding is None or binding.context is None:
        raise UnboundSloganEvent(
            f"事件 {event!r} 没有绑定标语上下文；未知事件不得静默回落 idle")

    s = _sanitizer()
    if s is None:
        d = SloganDecision(event, binding.context, resolved, "",
                           "sanitizer-unavailable", at, "", "")
        _record(d)
        return d
    sanitize_verb, display_cols, max_cols = s

    raw, origin = picker.pick_local_first(binding.context, resolved)
    text = sanitize_verb(raw)
    if not text or display_cols(text) > max_cols:
        text = sanitize_verb(text)[:max_cols] if text else ""
        if not text:
            d = SloganDecision(event, binding.context, resolved, "",
                               "rejected", at, "", origin)
            _record(d)
            return d

    # 反查注册项, 让每次渲染都能回答「这条标语对应哪个事件」
    eid = ""
    for e in registry():
        if e.lang == resolved and e.context == binding.context and e.text == text:
            eid = e.id
            break
    d = SloganDecision(event, binding.context, resolved, text, "ok", at, eid, origin)
    _record(d)
    return d


def verbs_for_phase(phase: str, lang: Optional[str] = None) -> Tuple[str, ...]:
    """把活性引擎的 PHASE 映射到本标语库的候选池 (供 TUI 可选使用)。

    **刻意不改写** ``runtime_slogans._pool()``: 那个引擎的事件驱动、
    活性判定、并发不变量已经过多轮验证, 换词池会破坏既有 139 例回归。
    这里只提供一座桥, 让两套系统「互相知道对方」, 由调用方决定是否采用。
    """
    ev = PHASE_EVENTS.get(phase)
    if not ev:
        return ()
    b = EVENT_BINDINGS.get(ev)
    if not b or not b.context:
        return ()
    resolved = picker.resolve_lang(lang)
    s = _sanitizer()
    if s is None:
        return ()
    sanitize_verb, _, _ = s
    out = []
    for pe in picker.pool_entries(b.context, resolved):
        clean = sanitize_verb(pe.text)
        if clean:
            out.append(clean)
    return tuple(dict.fromkeys(out))
