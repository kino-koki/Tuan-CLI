"""标语取词器 — 按上下文取一条, 带避重与频率节制。

三条纪律 (来自标语库设计稿, 实现时保留):

1. **按上下文取, 不全局随机** —— 出错时飘出 "Let's see what's here." 会让人出戏。
2. **避重** —— 每个 (语种, 上下文) 维护滑动窗口, 取到重复就重抽;
   窗口大小随池大小自适应 (小池不会把自己锁死)。
3. **频率节制** —— 长任务里 spinner 换文案的间隔不应短于 ``MIN_INTERVAL_S``;
   注意 ``mascot.MOON_INTERVAL_MS`` 是 120ms (8fps) 的动画帧,
   **文案绝不能跟着它换**, 否则两行字会抽风。

深度轮修补 (全部先实测复现, 见 ``SLOGAN_MAPPING.md`` §1):

- **并发**: ``_windows`` 原是模块级裸 dict, ``SloganPicker._last`` 也是裸
  dict; UI / 模型 / 工具 / 动画多线程同时取词时是复合读写。与
  ``runtime_slogans`` 深度轮 D1 同类问题, 现在全部在 ``RLock`` 内线性化。
- **LRU**: 旧清理是 ``pop(next(iter(_windows)))`` (FIFO), 与 docstring
  「清理最久未用」不符; 且池大小一变就把整个窗口**重建**, 避重历史丢失。
  改 ``OrderedDict`` + ``move_to_end``, 尺寸变化时保留已有历史。
- **小池**: ``_choose`` 对 1~2 条池仍白抽 12 次, 现在直接短路。
- **严格模式**: 旧 ``pick("totally.unknown")`` 静默飘出一句
  ``"Here."`` —— 一条没有任何对应事件的标语被渲染。新增
  ``pick_strict()`` 抛 ``UnknownSloganContext``; 生产接线一律走
  ``mapping.pick_for_event()``, 不再静默回落。
- **可测**: ``SloganPicker`` 注入 ``clock``, 校验 ``min_interval`` 必须是
  有限非负数 (旧版 ``-1`` / ``NaN`` / ``Inf`` 全被接受, ``Inf`` 会让
  spinner 永远不换词)。
- **补池**: 合并 ``extra_locales`` (8 语种 × 6 场景) 与
  ``locales.patches`` (空组), 让每个 (语种, 上下文) 都有本语种词条。
- **可回放**: ``_choose`` 支持 ``rng`` 注入; 注入时用一次性局部避重
  窗口, 避免全局隐藏状态让「相同输入」得到不同结果 (实测第二次分发
  的 ``choice`` 调用从 1 变成 13)。生产路径 ``rng=None`` 完全不变。
- **窗口容量**: ``_MAX_WINDOWS`` 按真实 key 空间计算 (384), 不再是
  固定 64 —— 实测 64 会让 320 个 key 互相驱逐, 避重失效。

用法::

    from tuan_cli.ui.slogans import pick, for_state, SloganPicker
    from tuan_cli.ui.slogans.mapping import pick_for_event

    pick_for_event("tool.exploring")        # 生产接线: 严格, 事件驱动
    pick("thinking", lang="ja")            # 兼容旧调用
    p = SloganPicker(min_interval=5.0, clock=fake_clock)
    p.pick("thinking")                     # 5 秒内不换词
"""

from __future__ import annotations

import math
import random
import threading
import time
from collections import OrderedDict, deque
from dataclasses import dataclass
from typing import Deque, Dict, Optional, Tuple

from . import extra, extra_locales, universal
from .locales import LANGUAGES, groups, normalize, patches

__all__ = [
    "CONTEXTS", "EXTRA_CONTEXTS", "STATE_MAP", "MIN_INTERVAL_S",
    "PoolEntry", "pick", "pick_strict", "pick_local_first", "for_state",
    "pool", "pool_entries", "resolve_lang", "SloganPicker", "languages",
    "UnknownSloganContext",
]


class UnknownSloganContext(ValueError):
    """上下文不在标语注册表里 —— 严格模式下绝不静默兜底。"""


# 主体上下文 + 扩展场景
CONTEXTS: Tuple[str, ...] = universal.CONTEXTS
EXTRA_CONTEXTS: Tuple[str, ...] = extra.CONTEXTS
ALL_CONTEXTS: Tuple[str, ...] = CONTEXTS + EXTRA_CONTEXTS

# mascot.py 的 5 态 -> 标语上下文
#   IDLE/THINKING/WORKING/ALERT/DONE
# 注: ALERT 映射为 guard, 但**安全拦截的结构化输出不要替换成标语** ——
#     那会把告警降维成俏皮话; guard 只用于非拦截的谨慎提示。
#     mapping.SECURITY_EVENTS 把这条纪律做成了 fail-closed 契约。
STATE_MAP: Dict[str, str] = {
    "idle": "idle",
    "thinking": "thinking",
    "working": "explore",
    "alert": "guard",
    "done": "done",
}

# spinner 文案最短更换间隔 (秒)
MIN_INTERVAL_S: float = 5.0

# 同时挂着的状态位上限 (语种 × 上下文), 超出则清理最久未用。
#
# 深度轮 3 实测: 固定 64 **小于真实 key 空间**, 避重形同虚设 ——
# 10 语种 x 16 上下文 x 2 种窗口 (本地池 / 兼容池) = 320 个 key。
# 遍历一轮后起始 key 的窗口被驱逐 3/3 次, 下一次取词可能立刻重复上一条。
# 所以上限按实际词池维度算, 而不是拍一个魔数; 仍有上界, 不会无界增长。
_MAX_WINDOWS: int = (
    len(LANGUAGES) * (len(universal.CONTEXTS) + len(extra.CONTEXTS)) * 2 + 64
)  # = 10 * 16 * 2 + 64 = 384

_windows: "OrderedDict[Tuple[str, str], Deque[str]]" = OrderedDict()
_windows_lock = threading.RLock()

# 兜底: 池异常为空时也不返回空串 (仅兼容路径使用)
_FALLBACK: Dict[str, str] = {
    "startup": "Ready.",
    "thinking": "Thinking…",
    "error": "That didn't land.",
    "undo": "Back to before.",
    "done": "Done.",
    "explore": "Looking.",
    "idle": "Here.",
    "together": "Together.",
    "guard": "Careful here.",
    "signoff": "Until next time.",
    "model.switch": "Switched.",
    "budget.warn": "Watch the meter.",
    "bg.start": "Running in the background.",
    "bg.progress": "Still going.",
    "pairing": "Connected.",
    "memory.write": "Noted.",
}

# locales 语言代码 -> 模块名 (patches 按模块名索引)
try:
    from .locales import _MODULES as _MODULE_NAMES  # noqa: PLC0415
except Exception:  # noqa: BLE001
    _MODULE_NAMES = {}


# ------------------------------------------------------------------ 池构建

@dataclass(frozen=True)
class PoolEntry:
    """一条候选词 + 它的来源。

    ``origin`` 让 ``mapping.audit()`` 能区分「本语种词条」与「英文兜底」,
    而不是靠猜。``is_local`` 对英文语种把通用英文池也算本地 (同为英文)。
    """
    text: str
    origin: str                 # locale | locale-patch | locale-extra | universal | extra-universal

    @property
    def is_local(self) -> bool:
        return self.origin in ("locale", "locale-patch", "locale-extra")


def _dedup(items: Tuple[str, ...]) -> Tuple[str, ...]:
    """保序去重, 去掉空串。"""
    return tuple(dict.fromkeys(i for i in items if i))


def pool_entries(ctx: str, lang: Optional[str] = None) -> Tuple[PoolEntry, ...]:
    """构建 (语种, 上下文) 的候选池, 每条带来源标注。

    规则:
      * 扩展场景 -> 本语种扩展池 (extra + extra_locales) + 通用英文扩展池;
      * 主体场景 -> 本语种本地池 (+ patches) 非空则独占 / 为空则通用英文池;
      * English  -> 本地池与通用池**合并** (同为英文)。
    """
    resolved = resolve_lang(lang)
    out: list[PoolEntry] = []

    if ctx in EXTRA_CONTEXTS:
        loc = list(extra.LOCALES.get(resolved, {}).get(ctx, ()))
        loc += list(extra_locales.LOCALES.get(resolved, {}).get(ctx, ()))
        gen = list(extra.GROUPS.get(ctx, ()))
        if resolved == "en":
            pairs = [(s, "extra-universal") for s in gen] + \
                    [(s, "locale-extra") for s in loc]
        else:
            pairs = [(s, "locale-extra") for s in loc] + \
                    [(s, "extra-universal") for s in gen]
    else:
        mod = _MODULE_NAMES.get(resolved, "")
        loc = list(groups(resolved).get(ctx, ()))
        loc += list(patches.PATCHES.get(mod, {}).get(ctx, ()))
        gen = list(universal.GROUPS.get(ctx, ()))
        if resolved == "en":
            pairs = [(s, "locale") for s in loc] + \
                    [(s, "universal") for s in gen]
        elif loc:
            pairs = [(s, "locale") for s in loc]
        else:
            pairs = [(s, "universal") for s in gen]

    seen = set()
    for text, origin in pairs:
        if not text or text in seen:
            continue
        # 3 条超长内置文案会被净化出口截成半句; 在这里换成语义完整的
        # 短版并标注来源, 保证**每条**进池的标语都能完整渲染。
        if text in patches.REPLACEMENTS:
            text = patches.REPLACEMENTS[text]
            origin = "locale-patch"
        if text in seen:
            continue
        seen.add(text)
        # patches 里的词条要单独标出来, 便于审计「补池生效」
        if origin == "locale" and mod and text in patches.PATCHES.get(mod, {}).get(ctx, ()):
            origin = "locale-patch"
        out.append(PoolEntry(text, origin))
    return tuple(out)


def pool(ctx: str, lang: Optional[str] = None) -> Tuple[str, ...]:
    """候选文案 (兼容旧 API, 不带来源)。"""
    return tuple(e.text for e in pool_entries(ctx, lang))


def resolve_lang(lang: Optional[str] = None) -> str:
    """未指定语种时跟随当前界面语言 (懒导入, 避免启动期耦合)。"""
    if lang:
        return normalize(lang) or "en"
    try:
        from tuan_cli.i18n import get_language  # noqa: PLC0415

        return normalize(get_language()) or "en"
    except Exception:  # noqa: BLE001
        return "en"


# 兼容旧私有名
_resolve_lang = resolve_lang


# ------------------------------------------------------------------ 避重

def _window_locked(key: Tuple[str, str], size: int) -> Deque[str]:
    """调用方必须持 ``_windows_lock``。

    LRU: 每次访问 ``move_to_end``; 超限时 ``popitem(last=False)`` 淘汰
    **最久未用** (旧实现是 FIFO, 与 docstring 不符)。
    尺寸变化时保留已有历史, 不再整个重建窗口。
    """
    win = _windows.get(key)
    if win is None:
        if len(_windows) >= _MAX_WINDOWS:
            _windows.popitem(last=False)
        win = deque(maxlen=size)
        _windows[key] = win
    else:
        _windows.move_to_end(key)
        if win.maxlen != size:
            preserved = deque(list(win), maxlen=size)
            _windows[key] = preserved
            win = preserved
    return win


def _choose(items: Tuple[str, ...], key: Tuple[str, str], rng=None) -> str:
    """随机取一条并尽量避开滑动窗口; 池太小时允许重复 (不阻塞)。

    :param rng: 可注入随机源 (需有 ``choice`` 方法)。上一轮给
        ``SloganPicker`` 加了 ``clock`` 注入, 但分发链路的随机源仍是
        模块级 ``random`` —— 于是「刚才显示了哪条标语」无法确定性回放。
        本轮把 rng 贯通到 ``mapping.pick_for_event``。
    """
    if not items:
        return ""
    pick_one = rng.choice if rng is not None else random.choice
    if rng is not None:
        # 确定性回放要求「相同输入 -> 相同输出」。全局避重窗口是隐藏状态:
        # 实测两个独立 rng 依次分发时, 第二个因窗口里已有 items[0]
        # 被拒 12 次, choice 调用 1 -> 13, 回放失效。注入 rng 时用
        # 一次性局部窗口, 生产路径 (rng=None) 完全不变。
        win: Deque[str] = deque(maxlen=max(4, min(20, len(items) // 2)))
        return _choose_with(items, win, pick_one)
    with _windows_lock:
        win = _window_locked(key, max(4, min(20, len(items) // 2)))
        return _choose_with(items, win, pick_one)


def _choose_with(items: Tuple[str, ...], win: Deque[str], pick_one) -> str:
    """避重抽取的公共体, 使全局窗口与回放局部窗口共用同一语义。"""
    # 小池短路: 池 <= 窗口容量时不可能避开全部, 别白抽 12 次
    if len(items) <= 2:
        s = pick_one(items)
        win.append(s)
        return s
    for _ in range(12):
        s = pick_one(items)
        if s not in win:
            win.append(s)
            return s
    s = pick_one(items)
    win.append(s)
    return s


# ------------------------------------------------------------------ 对外 API

def pick_strict(ctx: str, lang: Optional[str] = None, rng=None) -> str:
    """严格取词: 未知上下文抛异常, **绝不静默回落 idle**。

    生产接线请走 ``mapping.pick_for_event(event)``; 它还会校验事件绑定、
    安全事件隔离与统一净化出口。
    """
    ctx = extra.EVENT_MAP.get(ctx, ctx)
    if ctx not in ALL_CONTEXTS:
        raise UnknownSloganContext(
            f"上下文 {ctx!r} 不在 16 个已绑定上下文中；不得回落到 idle 飘无关标语")
    resolved = resolve_lang(lang)
    items = pool(ctx, resolved)
    if not items:
        return _FALLBACK.get(ctx) or _FALLBACK["idle"]
    return _choose(items, (resolved, ctx), rng)


def pick(ctx: str, lang: Optional[str] = None, rng=None) -> str:
    """按上下文取一条标语 (兼容旧调用)。

    .. warning::
       未知上下文会回落到 ``_FALLBACK['idle']`` —— 这是**历史兼容行为**,
       不是生产接线。新代码一律用 ``mapping.pick_for_event()`` /
       ``pick_strict()``, 否则会出现「一条没有对应事件的标语被渲染」。
    """
    ctx = extra.EVENT_MAP.get(ctx, ctx)
    resolved = resolve_lang(lang)
    items = pool(ctx, resolved)
    if not items:
        return _FALLBACK.get(ctx) or _FALLBACK["idle"]
    return _choose(items, (resolved, ctx))


def pick_local_first(ctx: str, lang: Optional[str] = None,
                     rng=None) -> Tuple[str, str]:
    """事件分发专用: **优先本语种词条**, 英文通用池只作最后兜底。

    ``audit()`` 已保证每个 (语种, 上下文) 至少有一条本语种词条, 但普通
    ``pick()`` 是在「本语种 + 英文兜底」合并池里随机抽, 实测日语
    ``model.switched`` 仍会抽到 ``"Handed over."`` —— 对应表建好了,
    用户看到的却还是英文。这里把本地组单独成池并优先取, 返回值带上
    ``origin`` 供 ``SloganDecision`` 如实报告, 不假装本地化。

    对英文语种 (``lang == "en"``) 整个池都是英文, 直接标 ``locale``。
    """
    ctx = extra.EVENT_MAP.get(ctx, ctx)
    resolved = resolve_lang(lang)
    entries = pool_entries(ctx, resolved)
    if not entries:
        return _FALLBACK.get(ctx) or _FALLBACK["idle"], "fallback-hardcoded"
    if resolved == "en":
        return _choose(tuple(e.text for e in entries),
                       (resolved, ctx + ":local"), rng), "locale"
    local = tuple(e.text for e in entries if e.is_local)
    if not local:
        return _choose(tuple(e.text for e in entries),
                       (resolved, ctx), rng), "universal-fallback"
    # 独立窗口 key, 不与兼容路径 pick() 的避重历史串味
    return _choose(local, (resolved, ctx + ":local"), rng), "locale"


def for_state(state: str, lang: Optional[str] = None) -> str:
    """按 ``mascot`` 状态取一条 (IDLE / THINKING / WORKING / ALERT / DONE)。"""
    ctx = STATE_MAP.get(str(state).lower(), "idle")
    return pick(ctx, lang)


class SloganPicker:
    """带频率节制的取词器 (长任务 spinner 用这个, 不要直接用 ``pick``)。

    :param lang: 固定语种; 为 None 时每次跟随当前界面语言。
    :param min_interval: 同一上下文两次换词的最小间隔 (秒), 默认 5.0。
        必须是有限非负数 —— 旧版接受 ``Inf`` (spinner 永远不换词) 与
        ``NaN`` (每帧都换), 都是真实缺陷。
    :param clock: 可注入的单调时钟, 供确定性测试。
    """

    def __init__(self, lang: Optional[str] = None,
                 min_interval: float = MIN_INTERVAL_S,
                 *, clock=time.monotonic) -> None:
        if (isinstance(min_interval, bool)
                or not isinstance(min_interval, (int, float))):
            raise TypeError(f"min_interval 必须是数值, 得到 {min_interval!r}")
        interval = float(min_interval)
        if not math.isfinite(interval) or interval < 0:
            raise ValueError(f"min_interval 必须是有限非负数, 得到 {min_interval!r}")
        self.lang = normalize(lang) if lang else None
        self.min_interval = interval
        self._clock = clock
        self._lock = threading.RLock()
        self._last: Dict[Tuple[str, str], Tuple[str, float]] = {}

    def pick(self, ctx: str, lang: Optional[str] = None) -> str:
        """取词; 距上次换词不足 ``min_interval`` 时复用上一条。"""
        ctx = extra.EVENT_MAP.get(ctx, ctx)
        resolved = self.lang or resolve_lang(lang)
        key = (resolved, ctx)
        with self._lock:
            hit = self._last.get(key)
            now = self._clock()
            if hit and now - hit[1] < self.min_interval:
                return hit[0]
            text = pick(ctx, resolved)
            self._last[key] = (text, now)
            return text

    def for_state(self, state: str, lang: Optional[str] = None) -> str:
        """按 mascot 状态取词, 同样受 ``min_interval`` 约束。"""
        return self.pick(STATE_MAP.get(str(state).lower(), "idle"), lang)

    def reset(self) -> None:
        """清空换词计时 (例如新会话开始时)。"""
        with self._lock:
            self._last.clear()


def languages() -> Tuple[str, ...]:
    """支持的语种清单。"""
    return LANGUAGES
