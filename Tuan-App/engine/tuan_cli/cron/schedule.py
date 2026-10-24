"""轻量 5 字段 cron 表达式解析与匹配 (零第三方依赖)。

背景: 旧版定时任务只有 ``interval_minutes`` (每隔 N 分钟), 无法表达
"每个工作日 09:00" / "每周一 08:30" 这类真实排期。本模块补齐标准 5 字段
cron 语义, 与 Claude Code ``/schedule`` 对齐, 但不引入 croniter 等依赖
(项目版本冻结, 不新增第三方包)。

格式 (5 字段, 空格分隔)::

    分 时 日 月 周
    0  9  *  *  1-5     # 每工作日 09:00

字段取值:
    分        0-59
    时        0-23
    日        1-31   (day-of-month)
    月        1-12
    周        0-6    (0=周日, 7 也按周日处理)

语法 (每个字段):
    ``*``       任意值
    ``a-b``     闭区间
    ``a/b``     从 a 开始的步长 (``*/15`` = 每 15)
    ``a,b,c``   列表
    ``?``       与 ``*`` 等价 (day-of-month / day-of-week 场景, 习惯写法)
    可组合: ``1-30/5``, ``9,12,18``

day-of-month 与 day-of-week 的组合遵循标准 cron 语义:
两者都被"限定"(非 ``*``)时, 命中条件为 **OR** (满足其一即当天命中);
否则要求两个字段都命中。
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from typing import FrozenSet, List, Optional, Tuple

# 字段名与取值范围 (min, max)
_FIELD_RANGES: Tuple[Tuple[str, int, int], ...] = (
    ("minute", 0, 59),
    ("hour", 0, 23),
    ("dom", 1, 31),
    ("month", 1, 12),
    ("dow", 0, 6),
)


class CronParseError(ValueError):
    """cron 表达式无法解析/非法。"""


@dataclass(frozen=True)
class CronSchedule:
    """一个已校验的 cron 表达式, 可判断某分钟是否命中、计算最近一次触发时刻。"""

    raw: str
    minutes: FrozenSet[int]
    hours: FrozenSet[int]
    doms: FrozenSet[int]
    months: FrozenSet[int]
    dows: FrozenSet[int]
    dom_restricted: bool
    dow_restricted: bool

    # ------------------------------------------------------------ 匹配

    def matches(self, when: _dt.datetime) -> bool:
        """``when`` 所在的分钟是否命中本排期 (秒/微秒忽略)。"""
        if when.minute not in self.minutes:
            return False
        if when.hour not in self.hours:
            return False
        if when.month not in self.months:
            return False
        # Python: Monday=0 .. Sunday=6; cron: Sunday=0 .. Saturday=6
        py_dow = when.weekday()  # Mon=0..Sun=6
        cron_dow = (py_dow + 1) % 7  # -> Sun=0..Sat=6
        day_ok = when.day in self.doms
        dow_ok = cron_dow in self.dows
        if self.dom_restricted and self.dow_restricted:
            # 两者都被限定: 标准 cron 取 OR
            return day_ok or dow_ok
        return day_ok and dow_ok

    def last_fire(self, now: _dt.datetime, *, max_backtrack_minutes: int = 366 * 24 * 60) -> Optional[_dt.datetime]:
        """返回 ``<= now`` 的最近一次命中分钟 (截断到分钟)。

        找不到 (例如该月永远不命中) 返回 None。最多向前回溯
        ``max_backtrack_minutes`` 分钟, 防止病态表达式死循环。
        """
        cur = now.replace(second=0, microsecond=0)
        for _ in range(max_backtrack_minutes):
            if self.matches(cur):
                return cur
            cur -= _dt.timedelta(minutes=1)
        return None


# ------------------------------------------------------------ 字段解析

def _parse_field(token: str, lo: int, hi: int, field_name: str) -> Tuple[FrozenSet[int], bool]:
    """解析单个 cron 字段, 返回 (命中值集合, 是否被"限定"即非全量 *)."""
    token = token.strip()
    if not token:
        raise CronParseError(f"{field_name} 字段为空")

    # ? 视为 * (dom/dow 习惯写法)
    if token == "?":
        token = "*"

    restricted = token != "*"
    values: set[int] = set()

    for part in token.split(","):
        part = part.strip()
        if not part:
            raise CronParseError(f"{field_name} 字段含空列表项: {token!r}")

        step = 1
        base = part
        if "/" in part:
            base, step_s = part.split("/", 1)
            try:
                step = int(step_s)
            except ValueError as exc:
                raise CronParseError(f"{field_name} 步长非法: {part!r}") from exc
            if step <= 0:
                raise CronParseError(f"{field_name} 步长必须为正整数: {part!r}")

        if base == "*" or base == "":
            start, end = lo, hi
        elif "-" in base:
            a, b = base.split("-", 1)
            try:
                start, end = int(a), int(b)
            except ValueError as exc:
                raise CronParseError(f"{field_name} 区间非法: {base!r}") from exc
        else:
            # 单值; 与步长组合时, 如 "5/15" 表示从 5 开始每 15
            try:
                start = int(base)
            except ValueError as exc:
                raise CronParseError(f"{field_name} 无法识别: {part!r}") from exc
            end = hi if "/" in part else start

        if start < lo or end > hi or start > end:
            raise CronParseError(
                f"{field_name} 越界: {part!r} (合法范围 {lo}-{hi})"
            )
        values.update(range(start, end + 1, step))

    if not values:
        raise CronParseError(f"{field_name} 未产生任何命中值: {token!r}")
    return frozenset(values), restricted


def parse(expr: str) -> CronSchedule:
    """解析并校验 cron 表达式, 返回 ``CronSchedule``。非法时抛 ``CronParseError``。"""
    parts = (expr or "").split()
    if len(parts) != 5:
        raise CronParseError(
            f"cron 表达式必须是 5 段 (分 时 日 月 周), 实际 {len(parts)} 段: {expr!r}"
        )

    mins = _parse_field(parts[0], 0, 59, "minute")
    hours = _parse_field(parts[1], 0, 23, "hour")
    doms = _parse_field(parts[2], 1, 31, "day-of-month")
    months = _parse_field(parts[3], 1, 12, "month")

    # dow: 7 归一化为 0 (周日)
    raw_dow = parts[4].replace("7", "0")
    dows = _parse_field(raw_dow, 0, 6, "day-of-week")

    return CronSchedule(
        raw=expr.strip(),
        minutes=mins[0],
        hours=hours[0],
        doms=doms[0],
        months=months[0],
        dows=dows[0],
        dom_restricted=doms[1],
        dow_restricted=dows[1],
    )


def is_valid(expr: str) -> bool:
    """快速判断表达式是否合法 (不抛异常)。"""
    try:
        parse(expr)
        return True
    except CronParseError:
        return False
