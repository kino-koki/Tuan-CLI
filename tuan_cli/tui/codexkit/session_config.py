"""A 线三个 pending：``local_settings`` / ``clock_format`` /
``external_agent_config_migration``。

按公开语义契约独立实现，零 Rust 源码复制。三条真实缺陷先复现再修：

1. **会话设置污染全局配置**：会话级覆盖若直接写 user config，退出后
   仍生效，下次启动读到脏值。本实现只在内存分层，``persisted()``
   恒为 False。
2. **``bool("false")`` 陷阱 / NaN 冒充数值**：配置值不做类型守卫，
   字符串 ``"false"`` 会被当成 True（安全开关尤其危险）。
3. **迁移模板链式 ``replace`` 二次替换**（第 13 轮实测过的真缺陷）：
   先替换 ``{from}`` 再替换 ``{to}``，若来源值里含字面量 ``{to}``
   就会被第二次替换成目标值。本实现用**单次正则扫描**，替换值
   不参与后续匹配，未知占位符原样保留。
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

_PLACEHOLDER_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")


# ============================================================ local_settings
class LocalSettings:
    """会话级设置覆盖：``user < project < session``。

    - 三层独立内存表，``persisted()`` 恒 False（**不落盘**）；
    - 键必须先在 ``SCHEMA`` 声明，未知键拒绝且不静默丢弃；
    - 按声明类型严格校验：``bool`` 不收 ``"false"`` / 0/1，
      ``int`` 不收 bool / float / 字符串数字，数值拒绝 NaN/Inf；
    - 会话层 ``clear_session()`` 只清自己一层，不动 project/user。
    """

    SCHEMA: Dict[str, type] = {
        "tui.vim_mode": bool,
        "tui.clock_format": str,
        "tui.selection_wrap": bool,
        "agent.max_turns": int,
        "context.auto_index": bool,
    }

    def __init__(self) -> None:
        self._user: Dict[str, Any] = {}
        self._project: Dict[str, Any] = {}
        self._session: Dict[str, Any] = {}

    @staticmethod
    def _valid(key: str, value: Any) -> bool:
        t = LocalSettings.SCHEMA.get(key)
        if t is None:
            return False
        if t is bool:
            return isinstance(value, bool)
        if t is int:
            return (isinstance(value, int) and not isinstance(value, bool))
        if t is float:
            return (isinstance(value, (int, float))
                    and not isinstance(value, bool)
                    and math.isfinite(float(value)))
        if t is str:
            if not isinstance(value, str):
                return False
            return not any(ord(c) < 32 or 0x7F <= ord(c) < 0xA0
                           for c in value)
        return False

    def set(self, layer: str, key: str, value: Any) -> bool:
        bucket = {"user": self._user, "project": self._project,
                  "session": self._session}.get(layer)
        if bucket is None or not self._valid(key, value):
            return False
        bucket[key] = value
        return True

    def get(self, key: str, default: Any = None) -> Any:
        for b in (self._session, self._project, self._user):
            if key in b:
                return b[key]
        return default

    def origin(self, key: str) -> Optional[str]:
        for name, b in (("session", self._session),
                        ("project", self._project), ("user", self._user)):
            if key in b:
                return name
        return None

    def clear_session(self) -> int:
        n = len(self._session)
        self._session.clear()
        return n

    def persisted(self) -> bool:
        return False


def probe_local_settings() -> dict:
    p: List[str] = []
    n = 0

    def chk(cond: bool, label: str) -> None:
        nonlocal n
        n += 1
        if not cond:
            p.append(label)

    s = LocalSettings()
    chk(s.set("user", "tui.vim_mode", False), "合法 bool 被拒")
    chk(s.set("project", "tui.vim_mode", True), "project 覆盖失败")
    chk(s.set("session", "tui.vim_mode", False), "session 覆盖失败")
    chk(s.get("tui.vim_mode") is False, "优先级不是 session > project > user")
    chk(s.origin("tui.vim_mode") == "session", "origin 不对")
    chk(not s.set("user", "tui.vim_mode", "false"), "bool 字符串未拒绝")
    chk(not s.set("user", "tui.vim_mode", 0), "0 冒充 bool 未拒绝")
    chk(not s.set("user", "agent.max_turns", True), "bool 冒充 int 未拒绝")
    chk(not s.set("user", "agent.max_turns", "15"), "字符串数字未拒绝")
    chk(not s.set("user", "agent.max_turns", float("nan")), "NaN 未拒绝")
    chk(not s.set("user", "TOTALLY_UNKNOWN", 1), "未知键未拒绝")
    chk(s.get("TOTALLY_UNKNOWN") is None, "未知键被静默写入")
    chk(not s.set("ghost", "tui.vim_mode", True), "未知层未拒绝")
    chk(not s.persisted(), "会话设置被落盘")
    chk(s.clear_session() == 1, "clear_session 返回值不对")
    chk(s.get("tui.vim_mode") is True, "清会话后未回落到 project")
    chk(s.origin("tui.vim_mode") == "project", "清会话后 origin 错")
    return {"ok": not p, "checks": n, "evidence":
            "LocalSettings: 三层优先级 / 严格类型 / 未知键拒绝 / 不落盘 / 精确清理",
            "problems": p}


# ============================================================ clock_format
class ClockFormat:
    """可注入、可回放的时间戳格式。

    - ``now`` 注入：不接受 nan/inf/str/bool/负值/超大值，脏值回落
      到注入的 ``fallback``（默认 0），**不抛异常**；
    - 单调钳制：新时刻小于上一时刻时钳到上一时刻（防时钟倒退
      让「已 N 秒没动静」倒流）；
    - 时区偏移显式传入，不读本机 TZ；
    - ``format()`` 纯函数，不在格式里读系统时钟。
    """

    MAX_TS = 1e9

    def __init__(self, fallback: float = 0.0,
                 utc_offset_minutes: int = 0) -> None:
        self._fallback = fallback if self._finite(fallback) else 0.0
        self._offset = (utc_offset_minutes if isinstance(utc_offset_minutes, int)
                        and not isinstance(utc_offset_minutes, bool) else 0)
        self._last = -1.0

    @staticmethod
    def _finite(v: Any) -> bool:
        return (isinstance(v, (int, float)) and not isinstance(v, bool)
                and math.isfinite(float(v)) and 0 <= v <= ClockFormat.MAX_TS)

    def tick(self, now: Any) -> float:
        t = float(now) if self._finite(now) else float(self._fallback)
        if t < self._last:
            t = self._last
        self._last = t
        return t

    def format(self, ts: float, *, with_tz: bool = True) -> str:
        if not self._finite(ts):
            return "invalid"
        total = int(ts + self._offset * 60)
        h, rem = divmod(total // 3600 % 24, 1), total % 3600
        hh = total // 3600 % 24
        mm = (total % 3600) // 60
        ss = total % 60
        base = "%02d:%02d:%02d" % (hh, mm, ss)
        if not with_tz:
            return base
        sign = "+" if self._offset >= 0 else "-"
        off = abs(self._offset)
        return "%s%s%02d:%02d" % (base, sign, off // 60, off % 60)

    def seconds_since(self, earlier: float, later: float) -> float:
        if not (self._finite(earlier) and self._finite(later)):
            return 0.0
        return max(0.0, later - earlier)


def probe_clock_format() -> dict:
    p: List[str] = []
    n = 0

    def chk(cond: bool, label: str) -> None:
        nonlocal n
        n += 1
        if not cond:
            p.append(label)

    c = ClockFormat(utc_offset_minutes=480)
    chk(c.tick(1000.0) == 1000.0, "合法 now 被改")
    chk(c.tick(999.0) == 1000.0, "时钟倒退未钳制")
    for dirty in (float("nan"), float("inf"), "1000", True, -1,
                  1e308, None):
        chk(c.tick(dirty) == 1000.0, "脏 now 未回落/钳制: %r" % (dirty,))
    chk(c.format(0.0) == "08:00:00+08:00", "时区偏移不对")
    chk(c.format(0.0, with_tz=False) == "08:00:00", "无时区格式不对")
    chk(c.format(float("nan")) == "invalid", "脏 ts 未返回 invalid")
    chk(c.seconds_since(10.0, 25.0) == 15.0, "正向差值不对")
    chk(c.seconds_since(25.0, 10.0) == 0.0, "倒退差值未钳 0")
    chk(c.seconds_since(float("inf"), 1.0) == 0.0, "脏差值未钳 0")
    c2 = ClockFormat(utc_offset_minutes="480")
    chk(c2.format(0.0).endswith("+00:00"), "脏 offset 未回落")
    return {"ok": not p, "checks": n, "evidence":
            "ClockFormat: 注入/脏值/单调钳制/显式时区/纯函数格式",
            "problems": p}


# ============================================================ external_agent_config_migration
@dataclass(frozen=True)
class MigrationResult:
    ok: bool
    values: Dict[str, Any]
    dropped: Tuple[str, ...]
    reasons: Tuple[str, ...]
    rendered: str = ""


_ALLOWED: Dict[str, Tuple[type, ...]] = {
    "model": (str,),
    "effort": (str,),
    "approval_policy": (str,),
    "max_turns": (int,),
    "sandbox": (str,),
}


def fill_template_once(template: str, mapping: Dict[str, str]) -> str:
    """**单次**扫描替换：替换值不参与后续匹配。

    旧 ``template.replace("{from}", cur).replace("{to}", tgt)`` 在
    ``cur`` 含字面量 ``{to}`` 时会二次替换（第 13 轮实测）。这里
    一次正则 ``sub`` 走完，未知占位符原样保留。
    """
    if not isinstance(template, str):
        return ""
    return _PLACEHOLDER_RE.sub(
        lambda m: str(mapping.get(m.group(1), m.group(0))), template)


def migrate_external_agent_config(raw: Any,
                                  template: str = "") -> MigrationResult:
    """外部 agent 配置 -> 本地 schema。

    - 未知键**丢弃并留痕**（不静默吞）；
    - 类型不符 -> 整项拒绝并记原因；
    - 值里含控制字符 -> 拒绝；
    - 模板用单次扫描渲染，替换值不会再被匹配。
    """
    if not isinstance(raw, dict):
        return MigrationResult(False, {}, (), ("raw_not_mapping",))
    values: Dict[str, Any] = {}
    dropped: List[str] = []
    reasons: List[str] = []
    for k, v in raw.items():
        if k not in _ALLOWED:
            dropped.append(str(k))
            continue
        types = _ALLOWED[k]
        if not isinstance(v, types) or (types == (int,) and isinstance(v, bool)):
            reasons.append("%s:type" % k)
            continue
        if isinstance(v, str) and any(
                ord(ch) < 32 or 0x7F <= ord(ch) < 0xA0 for ch in v):
            reasons.append("%s:control_chars" % k)
            continue
        values[k] = v
    rendered = ""
    if template:
        mapping = {k: str(v) for k, v in values.items()}
        rendered = fill_template_once(template, mapping)
    return MigrationResult(not reasons, dict(values), tuple(dropped),
                           tuple(reasons), rendered)


def probe_external_agent_config_migration() -> dict:
    p: List[str] = []
    n = 0

    def chk(cond: bool, label: str) -> None:
        nonlocal n
        n += 1
        if not cond:
            p.append(label)

    tpl = "从 {model} 迁移到 {effort}，未知 {nonexistent}"
    cur = "old-{effort}-x"
    out = fill_template_once(tpl, {"model": cur, "effort": "HIGH"})
    chk("old-{effort}-x" in out, "单次替换仍发生二次替换")
    chk("{nonexistent}" in out, "未知占位符未原样保留")
    chk("HIGH" in out, "正常替换失效")

    r = migrate_external_agent_config(
        {"model": "gpt-x", "effort": "high", "max_turns": 10,
         "UNKNOWN": "drop-me", "sandbox": 123}, tpl)
    chk(r.ok is False, "类型不符未标失败")
    chk("UNKNOWN" in r.dropped, "未知键未留痕")
    chk("sandbox:type" in r.reasons, "类型不符未记原因")
    chk(r.values.get("model") == "gpt-x", "合法键被误丢")
    chk("{nonexistent}" in r.rendered, "渲染丢了未知占位符")
    chk(migrate_external_agent_config({"model": "a\x1b[31mb"}).ok is False,
        "控制字符未拒绝")
    chk(migrate_external_agent_config({"max_turns": True}).ok is False,
        "bool 冒充 int 未拒绝")
    chk(migrate_external_agent_config("not-a-dict").ok is False,
        "非 mapping 未拒绝")
    chk(fill_template_once(None, {}) == "", "非字符串模板未返回空")
    return {"ok": not p, "checks": n, "evidence":
            "migrate: 单次模板替换 / 未知键留痕 / 类型守卫 / 控制字符拒绝",
            "problems": p}
