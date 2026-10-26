"""标语取词器 — 按上下文取一条, 带避重与频率节制。

三条纪律 (来自标语库设计稿, 实现时保留):

1. **按上下文取, 不全局随机** —— 出错时飘出 "Let's see what's here." 会让人出戏。
2. **避重** —— 每个 (语种, 上下文) 维护滑动窗口, 取到重复就重抽;
   窗口大小随池大小自适应 (小池不会把自己锁死)。
3. **频率节制** —— 长任务里 spinner 换文案的间隔不应短于 ``MIN_INTERVAL_S``;
   注意 ``mascot.MOON_INTERVAL_MS`` 是 120ms (8fps) 的动画帧,
   **文案绝不能跟着它换**, 否则两行字会抽风。

语言无关性: English 的本地池与通用池同为英文, 两者**合并**取用;
其余语种优先使用本地池 (保持语种性格), 本地池为空才回落通用英文池。

用法::

    from tuan_cli.ui.slogans import pick, for_state, SloganPicker

    pick("thinking")                 # 用当前界面语言
    pick("bg.progress", lang="ja")   # 指定语种
    for_state("THINKING")            # 按 mascot 状态取
    p = SloganPicker(min_interval=5.0)
    p.pick("thinking")               # 5 秒内不换词
"""

from __future__ import annotations

import random
import time
from collections import deque
from typing import Deque, Dict, Optional, Tuple

from . import extra, universal
from .locales import LANGUAGES, groups, normalize

__all__ = [
    "CONTEXTS", "EXTRA_CONTEXTS", "STATE_MAP", "MIN_INTERVAL_S",
    "pick", "for_state", "pool", "SloganPicker",
]

# 主体上下文 + 扩展场景
CONTEXTS: Tuple[str, ...] = universal.CONTEXTS
EXTRA_CONTEXTS: Tuple[str, ...] = extra.CONTEXTS

# mascot.py 的 5 态 -> 标语上下文
#   IDLE/THINKING/WORKING/ALERT/DONE
# 注: ALERT 映射为 guard, 但**安全拦截的结构化输出不要替换成标语** ——
#     那会把告警降维成俏皮话; guard 只用于非拦截的谨慎提示。
STATE_MAP: Dict[str, str] = {
    "idle": "idle",
    "thinking": "thinking",
    "working": "explore",
    "alert": "guard",
    "done": "done",
}

# spinner 文案最短更换间隔 (秒)
MIN_INTERVAL_S: float = 5.0

# 同时挂着的状态位上限 (语种 × 上下文), 超出则清理最久未用
_MAX_WINDOWS: int = 64

_windows: Dict[Tuple[str, str], Deque[str]] = {}

# 兜底: 池异常为空时也不返回空串
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


# ------------------------------------------------------------------ 池构建

def _dedup(items: Tuple[str, ...]) -> Tuple[str, ...]:
    """保序去重, 去掉空串。"""
    return tuple(dict.fromkeys(i for i in items if i))


def pool(ctx: str, lang: Optional[str] = None) -> Tuple[str, ...]:
    """构建 (语种, 上下文) 的候选池。

    规则:
      * 扩展场景 -> 本语种扩展池 + 通用英文扩展池;
      * 主体场景 -> 本语种本地池 (非空则独占) / 为空则通用英文池;
      * English -> 本地池与通用池**合并** (同为英文)。
    """
    lang = _resolve_lang(lang)
    if ctx in EXTRA_CONTEXTS:
        loc = tuple(extra.LOCALES.get(lang, {}).get(ctx, ()))
        gen = tuple(extra.GROUPS.get(ctx, ()))
        return _dedup(gen + loc if lang == "en" else loc + gen)
    loc = tuple(groups(lang).get(ctx, ()))
    gen = tuple(universal.GROUPS.get(ctx, ()))
    if lang == "en":
        return _dedup(loc + gen)
    return loc if loc else gen


def _resolve_lang(lang: Optional[str]) -> str:
    """未指定语种时跟随当前界面语言 (懒导入, 避免启动期耦合)。"""
    if lang:
        return normalize(lang) or "en"
    try:
        from tuan_cli.i18n import get_language  # noqa: PLC0415

        return normalize(get_language()) or "en"
    except Exception:  # noqa: BLE001
        return "en"


# ------------------------------------------------------------------ 避重

def _window(key: Tuple[str, str], size: int) -> Deque[str]:
    size = max(4, min(20, size // 2))
    win = _windows.get(key)
    if win is None or win.maxlen != size:
        if len(_windows) >= _MAX_WINDOWS:
            _windows.pop(next(iter(_windows)), None)
        win = deque(maxlen=size)
        _windows[key] = win
    return win


def _choose(items: Tuple[str, ...], key: Tuple[str, str]) -> str:
    """随机取一条并尽量避开滑动窗口; 池太小时允许重复 (不阻塞)。"""
    win = _window(key, len(items))
    for _ in range(12):
        s = random.choice(items)
        if s not in win:
            win.append(s)
            return s
    s = random.choice(items)
    win.append(s)
    return s


# ------------------------------------------------------------------ 对外 API

def pick(ctx: str, lang: Optional[str] = None) -> str:
    """按上下文取一条标语 (纯随机 + 避重, 不管时间间隔)。

    ``ctx`` 可为主体场景 (``thinking`` / ``undo`` …) 或扩展场景
    (``bg.progress`` / ``model.switch`` …), 亦可用 ``extra.EVENT_MAP``
    里的事件名 (如 ``remote.pair``)。未知上下文回落 ``idle``。
    """
    ctx = extra.EVENT_MAP.get(ctx, ctx)
    resolved = _resolve_lang(lang)
    items = pool(ctx, resolved)
    if not items:
        return _FALLBACK.get(ctx) or _FALLBACK["idle"]
    return _choose(items, (resolved, ctx))


def for_state(state: str, lang: Optional[str] = None) -> str:
    """按 ``mascot`` 状态取一条 (IDLE / THINKING / WORKING / ALERT / DONE)。"""
    ctx = STATE_MAP.get(str(state).lower(), "idle")
    return pick(ctx, lang)


class SloganPicker:
    """带频率节制的取词器 (长任务 spinner 用这个, 不要直接用 ``pick``)。

    :param lang: 固定语种; 为 None 时每次跟随当前界面语言。
    :param min_interval: 同一上下文两次换词的最小间隔 (秒), 默认 5.0。
    """

    def __init__(self, lang: Optional[str] = None, min_interval: float = MIN_INTERVAL_S) -> None:
        self.lang = normalize(lang) if lang else None
        self.min_interval = float(min_interval)
        self._last: Dict[Tuple[str, str], Tuple[str, float]] = {}

    def pick(self, ctx: str, lang: Optional[str] = None) -> str:
        """取词; 距上次换词不足 ``min_interval`` 时复用上一条。"""
        ctx = extra.EVENT_MAP.get(ctx, ctx)
        resolved = self.lang or _resolve_lang(lang)
        key = (resolved, ctx)
        hit = self._last.get(key)
        now = time.monotonic()
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
        self._last.clear()


def languages() -> Tuple[str, ...]:
    """支持的语种清单。"""
    return LANGUAGES
