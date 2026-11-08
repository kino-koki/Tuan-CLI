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

运行时闭环 (深度轮 2, 见 ``SLOGAN_MAPPING.md`` §11): 静态表对应上了,
TUI 留痕却丢了 ``entry_id``、错误被 ``except Exception`` 静默吞掉、
全局日志跨实例互串、审计与分发各有一处 O(n²)/O(n) 热路径。
现在留痕可反查、错误必留痕、按 ``owner`` 分域加 ``RLock``、
``_BY_ID``/``_BY_TEXT`` O(1) 索引、构建时缓存净化审计、
``rng``/``now`` 注入可确定性回放。``SloganEntry.events`` 补齐共享
事件的归属。``audit()`` 共 11 项不变量。

深度轮 3 再补: ``_BY_CLEAN`` (净化后索引) + 运行时 miss fail-closed
计数、净化撞车检测、owner 桶 LRU 上界与 ``release_owner()``、
错误双层留痕 ``record_error()``、``_MAX_WINDOWS`` 按真实 key 空间算。
``audit()`` 现在还校验三份索引全等与零运行时 miss。

深度轮 4: 连续 miss 自愈 (累计证据/日志不丢)、``close()`` 封存
``session.exit``、LRU 读刷新、日志字段净化、信息项与 fatal 分离、
分发与索引共用单一渲染出口。

深度轮 5 再补: ``owner`` 全链路归一 (D4 漏掉的 public 入参)、
LRU **被动淘汰**留脱敏痕迹 (D4 只覆盖了显式 ``close()``)、
``sanitize_log_field`` 的 ``limit`` 严格类型校验。

深度轮 6 再补: 淘汰痕与 decision 共用注入时钟 (可回放)、
``EvictionRecord.reason_counts`` 让桶内错误信号不再被
``last_reason`` 掩盖、``norm_owner`` 口径按实测精确化、
``sanitize_log_field`` 改为先清理后截断。

深度轮 7 再补: OSC/CSI 允许 ``ESC+`` 引导 (补齐上一轮 ESC_RUN
覆盖缺口)、注入时钟严格类型校验 (脏值回落真实时钟, 不抛异常/不放大)、
``owner`` 有界摘要 (不再整串 sha1)、淘汰**累计**证据
``evicted_total`` (与 ``_INDEX_MISSES`` 连续/累计双层口径对齐)。
"""

from __future__ import annotations

import hashlib
import math
import threading
import time
from collections import Counter, OrderedDict, deque
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
    "verbs_for_phase", "entry_for", "entry_for_text", "entry_for_clean",
    "dispatch_log", "reset_dispatch_log", "release_owner", "take_owner_log",
    "record_error", "reset_runtime_counters", "acknowledge_runtime_misses",
    "dispatch_log_stats", "evicted_owner_log", "evicted_total",
    "norm_owner", "registry", "index_stats",
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
    #: 能触发该上下文的**全部**事件 (含主事件)。上一轮只记主事件,
    #: 导致 `model.streaming` 触发的标语反查出来显示 `model.waiting` ——
    #: 共享映射在运行时产生归属歧义。
    events: Tuple[str, ...] = ()

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
            events = tuple(sorted(ev for ev, b in EVENT_BINDINGS.items()
                                  if b.context == ctx))
            for i, pe in enumerate(picker.pool_entries(ctx, lang)):
                out.append(SloganEntry(
                    id=f"{lang}:{ctx}:{i:03d}:{_sha8(pe.text)}",
                    lang=lang, context=ctx, event=event,
                    index=i, text=pe.text, origin=pe.origin,
                    events=events,
                ))
    return tuple(out)


_REGISTRY: Optional[Tuple[SloganEntry, ...]] = None
_BY_ID: Dict[str, SloganEntry] = {}
_BY_TEXT: Dict[Tuple[str, str, str], SloganEntry] = {}   # 原始文案反查 (兼容 API)
_BY_CLEAN: Dict[Tuple[str, str, str], SloganEntry] = {}  # 净化后文案反查 (运行时分发用)
_CLEAN_COLLISIONS: Tuple[str, ...] = ()                 # 净化后文案撞车的注册项 (fatal)
_CLIPPED_IDS: Tuple[str, ...] = ()                     # 文案经净化后与原文不同 (信息项, 非 fatal)
_UNRENDERABLE_IDS: Tuple[str, ...] = ()                # 净化后为空 / 仍超宽 (fatal)
_INDEX_MISSES: int = 0                                  # 累计：历史 miss 证据，永不自动清零
_UNRESOLVED_MISSES: int = 0                             # 自最近一次成功反查以来的**连续** miss
_registry_lock = threading.RLock()


def _ensure_index_locked() -> None:
    """调用方必须持 ``_registry_lock``。一次性建三个 O(1) 索引 +
    一次性净化审计 / 三类词条判定。

    深度轮 4 修的口径冲突：上一轮把「文案需要净化」一律记进
    ``clipped`` 并让 ``audit().ok`` 失败。但净化后索引 (``_BY_CLEAN``)
    建成后，**需要净化的词条其实能正确反查** —— 实测注入一条含 ZWSP
    的词条：``reason='ok'`` / ``entry_id`` 正确，而 ``audit().ok=False``。
    现在三者分开：

    - ``_CLIPPED_IDS``   文案经净化后与原文不同 → **信息项**，不致命；
    - ``_UNRENDERABLE_IDS`` 净化后为空 / 仍超宽 → **fatal**（无法渲染）；
    - ``_CLEAN_COLLISIONS`` 两条不同词条净化后相同 → **fatal**（无法区分）。

    索引 key 用与分发**完全相同**的 ``sanitize_verb`` 出口计算，
    不再有分发侧二次按码点截断造成的簇边界破坏（深度轮 4 的 F）。
    """
    global _REGISTRY, _CLIPPED_IDS, _UNRENDERABLE_IDS, _CLEAN_COLLISIONS
    if _REGISTRY is not None:
        return
    reg = build_registry()
    san = _sanitizer()
    clipped: list[str] = []
    unrenderable: list[str] = []
    collisions: list[str] = []
    for e in reg:
        _BY_ID[e.id] = e
        _BY_TEXT.setdefault((e.lang, e.context, e.text), e)
        if san is None:
            continue
        sanitize_verb, display_cols, max_cols = san
        clean = sanitize_verb(e.text)
        if clean != e.text:
            clipped.append(e.id)
        if not clean or display_cols(clean) > max_cols:
            unrenderable.append(e.id)
        ckey = (e.lang, e.context, clean)
        prev = _BY_CLEAN.get(ckey)
        if prev is not None and prev.id != e.id:
            collisions.append(e.id)
        else:
            _BY_CLEAN[ckey] = e
    _CLIPPED_IDS = tuple(sorted(clipped))
    _UNRENDERABLE_IDS = tuple(sorted(unrenderable))
    _CLEAN_COLLISIONS = tuple(sorted(collisions))
    _REGISTRY = reg


def registry() -> Tuple[SloganEntry, ...]:
    """全量注册表 (惰性、加锁幂等构建)。

    上一轮这里是无锁裸全局: 两个线程首次同时进入会各建一份 1695 条
    注册表, 且 ``entry_for`` 与构建过程并发时可能读到半初始化状态。
    """
    with _registry_lock:
        _ensure_index_locked()
        assert _REGISTRY is not None
        return _REGISTRY


def entry_for(slogan_id: str) -> Optional[SloganEntry]:
    """按稳定 id 反查一条标语及其触发事件 (**O(1)**)。

    上一轮是 ``for e in registry(): ...`` 线性扫 1695 条。
    """
    with _registry_lock:
        _ensure_index_locked()
        return _BY_ID.get(slogan_id)


def entry_for_text(lang: str, context: str, text: str) -> Optional[SloganEntry]:
    """按 (语种, 上下文, 文案) 反查注册项 (**O(1)**)。

    分发链路拿到的就是净化后的文案, 用这个索引直接反查 ``entry_id``,
    不再每次线性扫全表 (实测 2000 次分发 58.9 ms -> 见验证日志)。
    """
    with _registry_lock:
        _ensure_index_locked()
        return _BY_TEXT.get((lang, context, text))



def entry_for_clean(lang: str, context: str, clean_text: str) -> Optional[SloganEntry]:
    """按 (语种, 上下文, **净化后**文案) 反查注册项 (O(1))。

    分发链路拿到的是 ``sanitize_verb()`` 的输出, 必须查净化后索引;
    查原始索引在词条需要净化时会静默 miss (实测复现)。
    """
    with _registry_lock:
        _ensure_index_locked()
        return _BY_CLEAN.get((lang, context, clean_text))

def index_stats() -> Dict[str, int]:
    """索引规模自检, 供 ``audit()`` 与独立验证脚本核验。"""
    with _registry_lock:
        _ensure_index_locked()
        return {"registry": len(_REGISTRY or ()),
                "by_id": len(_BY_ID), "by_text": len(_BY_TEXT),
                "by_clean": len(_BY_CLEAN),
                "clipped_cached": len(_CLIPPED_IDS),
                "unrenderable": len(_UNRENDERABLE_IDS),
                "clean_collisions": len(_CLEAN_COLLISIONS),
                "index_misses": _INDEX_MISSES,
                "unresolved_misses": _UNRESOLVED_MISSES}


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
    index_consistent: bool = False
    clean_collisions: Tuple[str, ...] = ()   # 净化后文案撞车 -> 无法区分是哪条 (fatal)
    runtime_index_misses: int = 0            # 累计历史 miss 证据 (信息项, 不影响 ok)
    unresolved_misses: int = 0               # 连续未处置 miss (fatal)
    sanitized_slogans: Tuple[str, ...] = () # 文案需净化但能正确反查 (信息项, 非 fatal)
    unrenderable_slogans: Tuple[str, ...] = ()  # 净化后为空/仍超宽 (fatal)
    dispatch_stats: Dict[str, int] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        """「每个标语都要对应的」的硬判据 —— 不是文档自述, 是运行时计算。"""
        return not any((
            self.orphan_slogans, self.events_without_pool,
            self.contexts_without_event, self.events_without_context,
            self.locale_gaps, self.empty_pools, self.duplicate_ids,
            self.unsafe_bindings, self.phase_gaps,
        )) and self.sanitizer_shared and self.index_consistent \
            and not self.clean_collisions \
            and not self.unrenderable_slogans \
            and self.unresolved_misses == 0

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
            "index_consistent": self.index_consistent,
            "clean_collisions": len(self.clean_collisions),
            "runtime_index_misses": self.runtime_index_misses,
            "unresolved_misses": self.unresolved_misses,
            "sanitized_slogans": len(self.sanitized_slogans),
            "unrenderable_slogans": len(self.unrenderable_slogans),
            "dispatch_stats": dict(self.dispatch_stats),
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
    """运行时全量核验不变量。

    ``ok`` 看的是**当前**健康度：fatal 项（孤儿、缺口、重复 id、
    不安全绑定、净化撞车、无法渲染词条、连续未处置 miss、
    sanitizer 未共享、索引不一致）任一非零即 False。
    ``clipped_slogans`` / ``runtime_index_misses`` 是**历史信息项**，
    保留证据但不参与判定 —— 深度轮 4 实测修好了这一点。
    """
    reg = registry()
    # 上一轮 ``ids.count(i)`` 对 1695 条是 O(n^2)=287 万次比较,
    # 实测单次 audit() 38.4 ms / 20 次 763.7 ms。Counter 是 O(n)。
    dup = tuple(sorted(i for i, n in Counter(e.id for e in reg).items()
                       if n > 1))

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

    # 三类词条判定在 ``_ensure_index_locked()`` 构建索引时算一次并缓存。
    # 深度轮 4: ``clipped`` 降为**信息项**（净化后索引让需净化的词条
    # 仍可正确反查）, 真正 fatal 的是 ``unrenderable``。
    with _registry_lock:
        _ensure_index_locked()
        clipped = list(_CLIPPED_IDS)
        unrenderable = list(_UNRENDERABLE_IDS)

    idx = index_stats()
    # 深度轮 4: 不再要求 ``clipped_cached == 0``（净化后索引让需净化
    # 的词条仍可正确反查），也不再看累计 ``index_misses``（一次已修复的
    # 历史错误不该让健康状态永久报不健康）。改看**连续**未处置 miss 与
    # 真正无法渲染的词条。三份索引仍必须与注册表全等。
    index_ok = (
        idx["by_id"] == idx["by_text"] == idx["by_clean"]
        == idx["registry"] == len(reg)
        and idx["unrenderable"] == 0
        and idx["clean_collisions"] == 0
        and idx["unresolved_misses"] == 0
        and all(e.events and e.event in e.events for e in reg)
    )

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
        index_consistent=index_ok,
        clean_collisions=_CLEAN_COLLISIONS,
        runtime_index_misses=idx["index_misses"],
        unresolved_misses=idx["unresolved_misses"],
        sanitized_slogans=_CLIPPED_IDS,
        unrenderable_slogans=_UNRENDERABLE_IDS,
        dispatch_stats=dispatch_log_stats(),
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
    owner: str = ""               # 会话/实例作用域, 避免多 TUI 实例日志互串


#: 按 owner 分桶。上一轮是**全局裸 list 单例**: 两个 TUI 实例的日志
#: 混在一起, ``reset_dispatch_log()`` 会清掉另一个实例的记录 (实测复现)。
#: 空 owner 保留为兼容桶, 无参 ``dispatch_log()`` 仍返回全量。
#:
#: 深度轮 3: 上一轮只限制了**每桶长度** (64), 没限制**桶数量** ——
#: 实测 2000 个会话各分发一次就留下 2000 个桶, 长期运行的 REPL /
#: 测试集会无限累积。现在用 LRU OrderedDict + 桶数上限; ``close()``
#: 还会显式释放自己的 owner。
#: 深度轮 7: 注入时钟的合法范围。``now`` 是秒，``at_ms`` 是毫秒；
#: 超过上界（天文数字）会让 ``int(v*1000)`` 放大成超大整数。
_MAX_NOW_S = 1e12
_MAX_AT_MS = 1e15

#: ``owner`` 参与摘要的最大码点数；超过则用「头 + 长 + 尾」有界摘要，
#: 不再对整串做 UTF-8 编码 + sha1（实测 1 MiB ≈ 12.7 ms 且无上界）。
OWNER_SCAN_CAP = 4096


def _coerce_ms(value: object, *, is_seconds: bool) -> Optional[int]:
    """把注入时钟收敛成合法非负 ``int`` 毫秒；脏值返回 ``None``。

    深度轮 7 实测复现（public API 一路裸奔）:

    - ``pick_for_event(now=float('nan'))`` → ``ValueError``
    - ``now=float('inf')`` → ``OverflowError``
    - ``now='1000'`` → ``lambda: now`` 返回字符串，``'1000'*1000``
      被 ``int()`` 解析成 4000 位天文数字（内存/CPU 放大）；
    - ``record_error(at_ms='1000')`` 直接把**字符串**存进
      ``SloganDecision.at_ms``，类型契约被破坏；``True`` 被当成 1。

    与 ``runtime_slogans.load_config`` / ``_clean._coerce_log_limit``
    的严格类型口径对齐：拒绝 bool / 非数值 / 非有限 / 负值 / 超上界，
    脏值一律返回 ``None``，由调用方回落真实单调时钟。
    **绝不抛异常、绝不产生非 int、绝不放大**。
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    cap = _MAX_NOW_S if is_seconds else _MAX_AT_MS
    if value < 0 or value > cap:
        return None
    return int(value * 1000) if is_seconds else int(value)


def _fallback_ms() -> int:
    """真实单调时钟毫秒（脏注入的 fail-closed 回落）。"""
    return int(time.monotonic() * 1000)


_dispatch_log: "OrderedDict[str, list[SloganDecision]]" = OrderedDict()
_DISPATCH_CAP = 64
_MAX_OWNERS = 128
_dispatch_lock = threading.RLock()

#: 深度轮 5: LRU **被动淘汰**的记录。D4 只给显式 ``close()`` 封存了
#: 快照, 但 ``_record()`` 里的 ``popitem(last=False)`` 仍会静默丢掉整桶
#: (实测: 含 ``turn.completed`` 的 s-0 被第 129 个会话挤掉, 查不到也
#: 没有任何痕迹)。现在淘汰本身留一条有界记录 —— 不复活决策内容
#: (那会让 128 桶上界形同虚设), 但「谁、丢了几条、最后一条是什么」
#: 可查, 证据丢失至少**可见**。
_EVICT_CAP = 64
_EVICTED: "deque[EvictionRecord]" = deque(maxlen=_EVICT_CAP)
#: 深度轮 7: **累计**被动淘汰次数（进程生命周期内）。``_EVICTED`` 只
#: 保留最近 64 次，运维答不出「总共发生过多少次淘汰」。与
#: ``_INDEX_MISSES`` 的「连续 / 累计」双层口径对齐：累计值是信息项，
#: 永不自动清零、不参与 ``audit().ok``；只有显式 ``reset_dispatch_log()``
#: 全清（测试隔离）才归零。
_EVICT_TOTAL = 0


@dataclass(frozen=True)
class EvictionRecord:
    """一次 LRU 被动淘汰的痕迹 (脱敏: 不含文案、不含 entry_id)。

    深度轮 6: ``at_ms`` 改走 ``_record`` 的注入时钟 (与
    ``SloganDecision.at_ms`` 同源, 可确定性回放); 新增
    ``reason_counts`` —— 旧版只记 ``last_reason``, 实测桶内
    ``ok / error:boom / ok`` 淘汰后只剩 ``last_reason='ok'``,
    运维完全看不出被丢弃的会话曾出错。摘要按 reason 字符串计数并
    排序 (确定性), reason 本身是内部常量或已净化的 ``error:kd``,
    不含文案与 entry_id。
    """
    owner: str
    dropped: int
    last_reason: str
    at_ms: int
    reason_counts: Tuple[Tuple[str, int], ...] = ()


#: ``owner`` 零改动的上限（码点）。超过即归一定长指纹, 保证桶 key 有界。
OWNER_LIMIT = 64
#: 深度轮 7: 摘要输入上界（见 ``OWNER_SCAN_CAP`` 声明处）。


def norm_owner(raw: object) -> str:
    """把 public API 的 ``owner`` 归一成可安全进日志/桶 key 的字符串。

    深度轮 5 实测: ``owner`` 是 ``pick_for_event`` / ``record_error``
    的公开入参, 旧实现**全程未净化** —— 注入 5033 码点含 OSC 8 超链接
    与 U+202E RLO 的串后, ``SloganDecision.owner``、桶 key、
    ``slogan_trace()`` 输出全部原样带控制字符。D4 净化了
    event/kind/context, 偏偏漏了这一路。

    两条约束:
    * **干净且 ≤ ``OWNER_LIMIT`` 码点零改动** —— ``sanitize_log_field``
      返回原串时原样返回, 所以既有 ``owner='s-0'`` / ``tui:%x``
      全部不变, 查询侧用同一个函数即可对上。深度轮 6 实测:
      65 码点以上的**纯 ASCII 干净串**也会被归一成指纹 (实测
      ``'a'*64`` 原样、``'a'*65`` → ``owner:<fp16>``)。旧 docstring
      写「干净输入零改动」不精确, 已按实测修正; 功能无变化
      (写入/查询仍命中同一 key), 只是口径如实。
    * **脏串归一定长指纹 key** —— ``owner:<sha1(raw)[:16]>`` 只有 22
      码点, 干净且远小于 limit, 因此 ``norm_owner(norm_owner(x)) ==
      norm_owner(x)`` **严格幂等**。这点是实测逼出来的: 初版把净化后
      的 65 码点文案 + 8 位指纹拼成 74 码点, 二次归一又会被 64 码点
      上限截断并**重新算指纹**, 结果 ``_record`` 存的 key 与查询侧
      算出的 key 对不上 (实测 ``dispatch_log(evil)` 返回 0)。
      代价是脏 owner 原串不进日志 —— 这正是净化的目的。
    """
    if not isinstance(raw, str) or not raw:
        return ""
    from . import _clean  # noqa: PLC0415
    clean = _clean.sanitize_log_field(raw, OWNER_LIMIT)
    if clean == raw:
        return raw                     # 干净输入零改动, 严格幂等
    # 深度轮 7: 旧版对**整串**做 UTF-8 编码 + sha1, 无输入上界
    # (实测 1 MiB ≈ 12.7 ms, 每次写入/查询都付一次)。超过
    # ``OWNER_SCAN_CAP`` 改用「头 2048 + 长度 + 尾 2048」有界摘要:
    #   * 摘要本身 O(4096) 码点; 整体还含 ``sanitize_log_field`` 的
    #     ``_SCAN_CAP=65536`` **固定**扫描上限, 因此与输入长度无关
    #     (实测 64KiB→8MiB 均 ~12–14 ms), 但不等于「只扫 4096」;
    #   * 包含尾部, 实测仅尾部不同的两个 100k 串仍不撞车;
    #   * 长度参与, 不同长度不会撞。
    # 如实边界: 共享前 2048、后 2048 且总长相同、仅**中间**不同的
    # 两个超长串会撞到同一 key —— 这是有界摘要的固有碰撞面,
    # 不宣称「任意两个不同串绝不撞」。输出仍是 22 码点干净串,
    # ``norm_owner`` 严格幂等。
    if len(raw) > OWNER_SCAN_CAP:
        seed = (str(len(raw)) + ":" + raw[:2048] + ":" +
                raw[-2048:]).encode("utf-8", "replace")
    else:
        seed = raw.encode("utf-8", "replace")
    fp = hashlib.sha1(seed).hexdigest()[:16]
    return f"owner:{fp}"


def dispatch_log(owner: Optional[str] = None) -> Tuple[SloganDecision, ...]:
    """快照 (加锁, 不返回内部可变对象)。

    ``owner=None`` -> 全量 (兼容旧调用); 指定 owner -> 只看该会话。
    全量在桶数有上界后也可控 (<= ``_MAX_OWNERS * _DISPATCH_CAP``)。
    """
    key = norm_owner(owner) if owner is not None else None
    with _dispatch_lock:
        if key is not None:
            bucket = _dispatch_log.get(key, ())
            if key in _dispatch_log:
                # 深度轮 4: 读也算「最近使用」。上一轮只有写入刷新 LRU,
                # 实测高频只读的活跃会话被当成最久未用而淘汰 —— LRU
                # 名不副实。无参全量读**不**刷新，否则一次全量读会把
                # 所有桶都刷成最近使用，淘汰策略直接失效。
                _dispatch_log.move_to_end(key)
            return tuple(bucket)
        return tuple(d for bucket in _dispatch_log.values() for d in bucket)


def reset_dispatch_log(owner: Optional[str] = None) -> None:
    """``owner=None`` 清全部 (兼容旧调用); 指定 owner 只清该会话。

    全清时连 ``_EVICTED`` 一起清 (测试隔离需要); 指定 owner 属于显式
    释放而非被动淘汰, 不写淘汰痕、也不清已有淘汰痕。
    """
    key = norm_owner(owner) if owner is not None else None
    global _EVICT_TOTAL
    with _dispatch_lock:
        if key is None:
            _dispatch_log.clear()
            _EVICTED.clear()
            _EVICT_TOTAL = 0
        else:
            _dispatch_log.pop(key, None)


def release_owner(owner: str) -> int:
    """释放一个会话的日志桶 (TUI ``close()`` 调用)。

    :return: 被释放的决策条数, 供运维/验证核对。
    """
    key = norm_owner(owner)
    if not key:
        return 0
    with _dispatch_lock:
        bucket = _dispatch_log.pop(key, None)
        return len(bucket or ())


def dispatch_log_stats() -> Dict[str, int]:
    """日志规模自检: 桶数 / 决策总数 / 最大单桶长度。"""
    with _dispatch_lock:
        buckets = [len(b) for b in _dispatch_log.values()]
        return {"owners": len(_dispatch_log),
                "decisions": sum(buckets),
                "max_bucket": max(buckets, default=0),
                "cap_per_owner": _DISPATCH_CAP,
                "max_owners": _MAX_OWNERS,
                "evicted_recent": len(_EVICTED),
                "evicted_cap": _EVICT_CAP,
                "evicted_total": _EVICT_TOTAL}


def reset_runtime_counters(include_dispatch_log: bool = False) -> None:
    """清运行时计数 (测试隔离用), 不影响静态索引与词条。

    深度轮 4: 默认**不再清日志**。上一轮把「清计数」与「清全部
    运行时留痕」绑死，导致恢复 ``audit().ok`` 必须丢掉证据。
    需要连日志一起清时显式传 ``include_dispatch_log=True``。
    """
    global _INDEX_MISSES, _UNRESOLVED_MISSES
    with _registry_lock:
        _INDEX_MISSES = 0
        _UNRESOLVED_MISSES = 0
    if include_dispatch_log:
        reset_dispatch_log()


def take_owner_log(owner: str) -> Tuple[SloganDecision, ...]:
    """取走一个会话的完整日志快照并释放它的桶。

    与 ``release_owner()`` 只返回条数不同，这里把**含会话最后一条
    (``session.exit``)** 的决策都归还给调用方，供归档/审计。
    深度轮 4 实测：``close()`` 先记 ``session.exit`` 再
    ``release_owner()`` 删桶，全局日志永远看不到会话退出事件。
    """
    key = norm_owner(owner)
    if not key:
        return ()
    with _dispatch_lock:
        bucket = _dispatch_log.pop(key, None)
        return tuple(bucket or ())


def evicted_total() -> int:
    """进程生命周期内**累计**的 LRU 被动淘汰次数（信息项）。

    深度轮 7: ``_EVICTED`` 是 64 条有界环形缓冲，``evicted_recent``
    只回答「最近几条」；累计值回答「总共多少次」，且**不因缓冲滚动
    而丢失**。不参与 ``audit().ok``（淘汰是正常有界行为）。
    """
    with _dispatch_lock:
        return _EVICT_TOTAL


def evicted_owner_log() -> Tuple[EvictionRecord, ...]:
    """最近 ``_EVICT_CAP`` 次 LRU **被动淘汰**的痕迹 (快照、加锁)。

    深度轮 5: D4 的 ``slogan_closed_trace()`` 只覆盖显式 ``close()``;
    被 129 个会话挤掉的桶仍是黑洞。这里不复活决策内容, 只让
    「谁被淘汰 / 丢了几条 / 最后一条 reason」可见, 128 桶上界不变。
    ``dispatch_log_stats()['evicted_recent']`` 给聚合计数,
    ``audit().as_dict()['dispatch_stats']`` 也会带上。
    """
    with _dispatch_lock:
        return tuple(_EVICTED)


def acknowledge_runtime_misses() -> int:
    """把「连续未处置 miss」清零，**不动累计证据、不动任何日志**。

    深度轮 4 修的破坏性耦合：上一轮 ``audit().ok`` 依赖累计
    ``_INDEX_MISSES``，一次已修复的历史 miss 会让健康状态永久报
    不健康；而唯一恢复手段 ``reset_runtime_counters()`` 又强绑
    ``reset_dispatch_log()`` —— 想恢复审计就得丢掉全部运行时留痕。

    现在 ``ok`` 看的是**连续** miss（自最近一次成功反查以来），
    数据源恢复后一次成功分发即自动归零；本函数只是给运维一个
    显式确认入口，累计 ``_INDEX_MISSES`` 与日志都原样保留。
    """
    global _UNRESOLVED_MISSES
    with _registry_lock:
        n = _UNRESOLVED_MISSES
        _UNRESOLVED_MISSES = 0
        return n


def _record(d: SloganDecision, at_ms: Optional[int] = None) -> None:
    """写一条决策; ``at_ms`` 由调用方注入 (与 decision 同源时钟)。

    深度轮 6: 旧实现淘汰痕用 ``time.monotonic()``, 而
    ``pick_for_event(now=...)`` 的 decision 走注入时钟 —— 实测注入
    ``now=1000.0`` 时 ``decision.at_ms=1000000`` 但
    ``EvictionRecord.at_ms=76564``, 同一事件的两个时间戳来自两套
    时钟, 可回放性断了一半。现在统一。
    """
    key = norm_owner(d.owner)   # 幂等: 干净 owner 原样返回
    ms = None if at_ms is None else _coerce_ms(at_ms, is_seconds=False)
    stamp = _fallback_ms() if ms is None else ms
    with _dispatch_lock:
        bucket = _dispatch_log.get(key)
        if bucket is None:
            if len(_dispatch_log) >= _MAX_OWNERS:
                ev_owner, ev_bucket = _dispatch_log.popitem(last=False)
                # 淘汰不再静默: 记一条脱敏痕迹 (不含文案 / entry_id)。
                global _EVICT_TOTAL
                _EVICT_TOTAL += 1
                _EVICTED.append(EvictionRecord(
                    owner=ev_owner,
                    dropped=len(ev_bucket),
                    last_reason=(ev_bucket[-1].reason if ev_bucket else ""),
                    at_ms=stamp,
                    reason_counts=tuple(sorted(
                        Counter(x.reason for x in ev_bucket).items())),
                ))
            bucket = []
            _dispatch_log[key] = bucket
        else:
            _dispatch_log.move_to_end(key)
        bucket.append(d)
        if len(bucket) > _DISPATCH_CAP:
            del bucket[:-_DISPATCH_CAP]


def record_error(event: str, kind: str, *, owner: str = "",
                 at_ms: Optional[int] = None,
                 context: Optional[str] = None) -> SloganDecision:
    """把分发错误也写进**全局**日志。

    上一轮 TUI 的 ``_slogan_error()`` 只写实例自己的 ``_slogan_log``:
    实测拼错事件后 ``slogan_errors()`` 有 1 条, 而
    ``mapping.dispatch_log()`` 里错误相关 0 条 —— 只看全局日志的运维
    会完全漏掉。现在两层留痕一致。安全事件仍走 ``security-notice``,
    不与 ``error:*`` 混。
    """
    # 深度轮 7: 旧版把 ``at_ms`` 原样塞进 SloganDecision（实测
    # at_ms='1000' 存成字符串、True 存成 bool），类型契约被破坏。
    ms = None if at_ms is None else _coerce_ms(at_ms, is_seconds=False)
    at = _fallback_ms() if ms is None else ms
    # 深度轮 4: event / kind 是 public API 入参, 实测可注入 5030 码点
    # 含 OSC 8 超链接 + U+202E RLO 的串并原样写进日志。统一过
    # _clean.sanitize_log_field (与 UI 文案共用 _clean_once 清理核心)。
    from . import _clean  # noqa: PLC0415
    ev = _clean.sanitize_log_field(event)
    kd = _clean.sanitize_log_field(kind, 40)
    if not ev:
        ev, kd = "<invalid-event>", "invalid-field"
    if not kd:
        kd = "invalid-field"
    safe_ctx = (_clean.sanitize_log_field(context, 64)
                if context is not None else None)
    d = SloganDecision(ev, safe_ctx, "", "", "error:" + kd,
                       at, "", "", norm_owner(owner))
    _record(d, at)
    return d


def pick_for_event(event: str, lang: Optional[str] = None, *,
                   now: Optional[float] = None, rng=None,
                   owner: str = "") -> SloganDecision:
    """**唯一**对外的事件驱动取词入口。

    - 未知事件 → 抛 ``UnboundSloganEvent``, 绝不静默回落 ``idle``;
    - 安全事件 → 返回空文案 + ``security-notice`` (结构化告警不降级);
    - 净化出口不可用 → fail-closed 返回空, 不渲染未净化文案;
    - 正常事件 → ``picker.pick_local_first`` 本语种优先, 再过统一净化/列宽出口。

    本轮新增:
    :param rng: 可注入随机源, 让「刚才显示了哪条标语」可确定性回放;
    :param owner: 会话/实例作用域, 日志按 owner 分桶, 多 TUI 不互串;
    :param now: 可注入时钟 (原本已有, 现在贯穿到 ``at_ms`` 且可被
        ``clock`` 覆盖)。``entry_id`` 反查改走 O(1) 索引。

    深度轮 3: 反查改用 ``_BY_CLEAN`` (净化后文案), 未命中即
    fail-closed 返回 ``index-miss`` + 空文案并计数, 不再假装 "ok"。
    深度轮 4: 渲染与索引共用 ``sanitize_verb`` 单一出口 (去掉会破坏
    簇边界的二次按码点截断); miss 分「累计证据 / 连续未处置」两层,
    成功一次即自愈, 不再让一次已修复的历史错误永久污染 ``audit().ok``。
    """
    # 深度轮 7: 旧版 ``clock = lambda: now`` 直接把 public 入参参与
    # ``int(clock() * 1000)``。实测 now='1000' 产生 4000 位天文数字、
    # nan/inf 抛异常。严格收敛后脏值回落真实单调时钟。
    # 深度轮 7 自引入又抓回: ``_coerce_ms(...) or _fallback_ms()``
    # 会把**合法 0** 当成 falsy 回落真实时钟 (实测 now=0 -> 1e6 ms)。
    # 必须显式判 ``is None``。
    ms = None if now is None else _coerce_ms(now, is_seconds=True)
    at = _fallback_ms() if ms is None else ms
    resolved = picker.resolve_lang(lang)
    owner = norm_owner(owner)   # 深度轮 5: public 入参, 与查询侧同一归一

    if event in SECURITY_EVENTS:
        d = SloganDecision(event, None, resolved, "", "security-notice",
                           at, "", "", owner)
        _record(d, at)
        return d
    binding = EVENT_BINDINGS.get(event)
    if binding is None or binding.context is None:
        from . import _clean  # noqa: PLC0415
        # 异常消息也会进 traceback / 日志, 同样不能带控制字符或超长串。
        safe_ev = _clean.sanitize_log_field(event) or "<invalid-event>"
        raise UnboundSloganEvent(
            f"事件 {safe_ev!r} 没有绑定标语上下文；未知事件不得静默回落 idle")

    s = _sanitizer()
    if s is None:
        d = SloganDecision(event, binding.context, resolved, "",
                           "sanitizer-unavailable", at, "", "", owner)
        _record(d, at)
        return d
    sanitize_verb, display_cols, max_cols = s

    raw, origin = picker.pick_local_first(binding.context, resolved, rng)
    # 深度轮 4 (F): ``sanitize_verb`` 已是**唯一**出口 —— 它自己就在
    # grapheme 簇边界按 _MAX_VERB_COLS 截断并保证 display_cols <= max_cols。
    # 上一轮这里又补了一句「把 text 按码点切前 max_cols 个字符」：
    # 二次截断会切断簇、且让分发文案与 _BY_CLEAN 的
    # ``sanitize_verb(e.text)`` key 口径不一致，超长词条会静默 index-miss。
    # 现在分发与索引构建共用同一个函数、同一份结果。
    text = sanitize_verb(raw)
    if not text:
        d = SloganDecision(event, binding.context, resolved, "",
                           "rejected", at, "", origin, owner)
        _record(d, at)
        return d

    # O(1) 反查: 上一轮这里是逐条遍历全量注册表线性扫 1695 条,
    # 实测 2000 次分发 58.9 ms。现在按 (lang, context, **净化后** text)
    # 查 _BY_CLEAN —— 不能用原始文案索引, 词条需要净化时会静默 miss。
    entry = entry_for_clean(resolved, binding.context, text)
    if entry is None:
        # fail-closed: 显示一条**反查不到注册项**的标语, 等于把上一轮
        # 「每个标语都要对应的」重新打断。宁可不显示, 也不返回假的 "ok"。
        global _INDEX_MISSES, _UNRESOLVED_MISSES
        with _registry_lock:
            _INDEX_MISSES += 1          # 累计证据，永不自动清零
            _UNRESOLVED_MISSES += 1     # 连续 miss，成功一次即归零
        d = SloganDecision(event, binding.context, resolved, "",
                           "index-miss", at, "", origin, owner)
        _record(d, at)
        return d
    # 数据源恢复后一次成功反查即视为「当前健康」；历史累计证据保留。
    # ``global`` 已在上面的 miss 分支声明，此处不可重复声明。
    with _registry_lock:
        _UNRESOLVED_MISSES = 0
    d = SloganDecision(event, binding.context, resolved, text, "ok",
                       at, entry.id, origin, owner)
    _record(d, at)
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
