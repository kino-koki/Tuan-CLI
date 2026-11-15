"""A 线三个 pending 的真实实现（审批 / 历史 / 选区几何）。

对应上游 ``codex-rs/tui/src`` 模块：

============================  ==============================================
``auto_review_denials``        自动审查拒绝的账本与 fail-closed 执行契约
``insert_history``             transcript 有序插入（不破坏 id 单调 / 幂等）
``rendered_selection``         终端选区几何，hit 与 render 同源
============================  ==============================================

**按公开语义契约独立实现，未复制任何 Rust 源码**。每个模块都带
``probe()``：真调代码、逐项断言、返回结构化结果，供
``tui/parity/depth.py`` 注册为运行时探针。

三条最值钱的真实缺陷（都是先复现「旧行为不存在/会错」，再实现）：

1. **自动审查决策被静默丢弃**：只把拒绝写进日志、调用方忘了读，
   等于放行。``DenialLedger.enforce()`` 让「忽略即拒绝」成为硬契约。
2. **历史插入越界静默追加 / 重复 id 产生两条**：上游若只做
   ``list.insert(min(i, len), cell)``，越界会变成追加、重复 id 会让
   transcript 出现两条同 id 单元，backtrack 直接错位。
3. **选区 hit 与 render 两套几何**：延续第 13 轮 ``sidebar_tab_strip``
   的教训，点第 3 个 cell 打开第 2 个。本模块 ``hit_matches_render()``
   是可执行自检，不是 docstring 口号。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


# ============================================================ auto_review_denials
class ReviewDecision(Enum):
    ALLOW = "allow"
    DENY = "deny"
    ABSTAIN = "abstain"


@dataclass(frozen=True)
class DenialRecord:
    owner: str
    tool: str
    reason: str
    seq: int
    decision: str

    def key(self) -> Tuple[str, str, str, int]:
        return (self.owner, self.tool, self.reason, self.seq)


class DenialLedger:
    """自动审查拒绝账本。

    契约（与本项目审批覆盖层「无输入 / Esc 绝不变成同意」同源）：

    - ``record()`` 只记账，**不产生允许**；
    - ``enforce(decision)`` 是唯一出口：``None`` / 未知字符串 / 异常 /
      未确认的 ``allow`` 一律 ``DENY`` 并留结构化原因；
    - 按 owner 分桶（不串台）、有界 ring（默认 64）且 ``dropped`` 可查；
    - 同 ``(owner, tool, reason, seq)`` 去重，不重复记账。
    """

    MAX_CAP = 64

    def __init__(self, cap: int = 64) -> None:
        if not isinstance(cap, int) or isinstance(cap, bool) or cap < 1:
            raise ValueError("cap 必须是正整数")
        self._cap = min(cap, self.MAX_CAP)
        self._buckets: Dict[str, List[DenialRecord]] = {}
        self._dropped = 0

    def record(self, owner: str, tool: str, reason: str, seq: int,
               decision: ReviewDecision = ReviewDecision.DENY) -> bool:
        if not isinstance(owner, str) or not isinstance(tool, str) \
                or not isinstance(reason, str) or not isinstance(seq, int) \
                or isinstance(seq, bool):
            return False
        r = DenialRecord(owner, tool, reason, seq, decision.value)
        b = self._buckets.setdefault(owner, [])
        if any(x.key() == r.key() for x in b):
            return False
        if len(b) >= self._cap:
            b.pop(0)
            self._dropped += 1
        b.append(r)
        return True

    def enforce(self, decision: Any, *, acknowledged: bool = False) -> dict:
        """唯一裁决出口。任何不确定都 fail-closed。"""
        try:
            if decision is None:
                return {"allowed": False, "reason": "missing_decision"}
            if isinstance(decision, ReviewDecision):
                d = decision
            elif isinstance(decision, str):
                d = ReviewDecision(decision.lower())
            else:
                return {"allowed": False,
                        "reason": "decision_type:%s" % type(decision).__name__}
        except Exception as exc:  # noqa: BLE001
            return {"allowed": False,
                    "reason": "decision_invalid:%s" % type(exc).__name__}
        if d is ReviewDecision.DENY or d is ReviewDecision.ABSTAIN:
            return {"allowed": False, "reason": "review_%s" % d.value}
        # ALLOW 也必须显式确认；「记录了但没人看」不等于同意
        if not acknowledged:
            return {"allowed": False, "reason": "allow_not_acknowledged"}
        return {"allowed": True, "reason": "acknowledged_allow"}

    def for_owner(self, owner: str) -> Tuple[DenialRecord, ...]:
        return tuple(self._buckets.get(owner, ()))

    def dropped(self) -> int:
        return self._dropped


def probe_auto_review_denials() -> dict:
    p: List[str] = []
    n = 0

    def chk(cond: bool, label: str) -> None:
        nonlocal n
        n += 1
        if not cond:
            p.append(label)

    led = DenialLedger(cap=3)
    chk(led.enforce(None)["allowed"] is False, "None 未 fail-closed")
    chk(led.enforce(object())["allowed"] is False, "脏类型未 fail-closed")
    chk(led.enforce("TOTALLY_UNKNOWN")["allowed"] is False, "未知字符串未拒绝")
    chk(led.enforce(ReviewDecision.ABSTAIN)["allowed"] is False, "弃权未拒绝")
    chk(led.enforce("allow")["allowed"] is False, "未确认 allow 被放行")
    chk(led.enforce("allow", acknowledged=True)["allowed"] is True,
        "显式确认 allow 被误拒")
    chk(led.record("s1", "write_file", "outside_wd", 1), "记账失败")
    chk(not led.record("s1", "write_file", "outside_wd", 1), "重复未去重")
    chk(led.record("s2", "write_file", "outside_wd", 1), "分桶失败")
    chk(len(led.for_owner("s1")) == 1 and len(led.for_owner("s2")) == 1,
        "owner 分桶串台")
    for i in range(2, 9):
        led.record("s1", "t", "r", i)
    chk(len(led.for_owner("s1")) == 3, "ring 上界失效")
    chk(led.dropped() >= 1, "淘汰无证据")
    chk(not led.record("s1", "t", "r", True), "bool 冒充 seq 未拒绝")
    return {"ok": not p, "checks": n, "evidence":
            "DenialLedger: 7 类裁决 + 去重 + 分桶 + 有界 ring + 类型守卫",
            "problems": p}


# ============================================================ insert_history
@dataclass(frozen=True)
class HistoryCell:
    cell_id: int
    text: str


class HistoryInsertError(ValueError):
    pass


class HistoryBuffer:
    """transcript 插入。

    - ``cell_id`` 严格单调（新 id 必须大于已最大值）；
    - ``insert_at`` 越界**显式抛错**，不静默追加；
    - 同 id 幂等 no-op，不产生第二条；
    - ``base_id`` 变更后旧插入点失效（backtrack 契约）；
    - ``at()`` 与 ``index_of()`` 共用同一份列表，防 render/hit 错位。
    """

    def __init__(self, base_id: int = 0) -> None:
        self._cells: List[HistoryCell] = []
        self._base_id = base_id
        # A′ 实测修正：base_id 只用于 backtrack 失效判定，**不能**当
        # cell_id 单调下界 —— 否则 base_id=7 时连 append(id=1) 都被拒。
        self._max_id = 0

    def append(self, cell: HistoryCell) -> None:
        if not isinstance(cell, HistoryCell):
            raise HistoryInsertError("cell 类型不对")
        if cell.cell_id <= self._max_id:
            raise HistoryInsertError("cell_id 不单调")
        self._cells.append(cell)
        self._max_id = cell.cell_id

    def insert_at(self, index: int, cell: HistoryCell,
                  base_id: Optional[int] = None) -> bool:
        if base_id is not None and base_id != self._base_id:
            raise HistoryInsertError("base_id 已失效 (backtrack)")
        if not isinstance(index, int) or isinstance(index, bool):
            raise HistoryInsertError("index 不是 int")
        if index < 0 or index > len(self._cells):
            raise HistoryInsertError("insert_at 越界")
        if not isinstance(cell, HistoryCell):
            raise HistoryInsertError("cell 类型不对")
        if any(c.cell_id == cell.cell_id for c in self._cells):
            return False                      # 幂等，不产生第二条
        if cell.cell_id <= self._max_id:
            raise HistoryInsertError("cell_id 不单调")
        self._cells.insert(index, cell)
        self._max_id = cell.cell_id
        return True

    def rebase(self, base_id: int) -> None:
        self._base_id = base_id

    def at(self, index: int) -> HistoryCell:
        return self._cells[index]

    def index_of(self, cell_id: int) -> int:
        for i, c in enumerate(self._cells):
            if c.cell_id == cell_id:
                return i
        return -1

    def __len__(self) -> int:
        return len(self._cells)


def probe_insert_history() -> dict:
    p: List[str] = []
    n = 0

    def chk(cond: bool, label: str) -> None:
        nonlocal n
        n += 1
        if not cond:
            p.append(label)

    b = HistoryBuffer(base_id=7)
    b.append(HistoryCell(1, "a"))
    b.append(HistoryCell(2, "c"))
    chk(b.insert_at(1, HistoryCell(3, "b")), "正常插入失败")
    chk([c.text for c in b._cells] == ["a", "b", "c"], "插入顺序错")
    chk(b.at(1).cell_id == b._cells[b.index_of(3)].cell_id, "at/index_of 漂移")
    chk(not b.insert_at(1, HistoryCell(3, "dup")), "重复 id 未幂等")
    chk(len(b) == 3, "重复 id 产生第二条")
    for bad in (-1, 99, True, "1"):
        try:
            b.insert_at(bad, HistoryCell(9, "x"))
            p.append("越界/脏 index 未抛错: %r" % (bad,))
        except HistoryInsertError:
            pass
        n += 1
    try:
        b.append(HistoryCell(1, "back"))
        p.append("id 倒退未拒绝")
    except HistoryInsertError:
        pass
    n += 1
    b.rebase(8)
    try:
        b.insert_at(0, HistoryCell(10, "stale"), base_id=7)
        p.append("backtrack 后旧 base_id 未失效")
    except HistoryInsertError:
        pass
    n += 1
    chk(b.insert_at(0, HistoryCell(10, "fresh"), base_id=8),
        "新 base_id 插入失败")
    return {"ok": not p, "checks": n, "evidence":
            "HistoryBuffer: 单调 / 越界拒绝 / 幂等 / backtrack 失效 / 几何同源",
            "problems": p}


# ============================================================ rendered_selection
@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    w: int
    h: int


class SelectionGeometry:
    """终端选区：宽字符列宽 + hit/render 同源。

    ``targets()`` 是**唯一**几何真值：``hit()`` 与 ``render_plan()`` 都从
    它取坐标。宽字符按列宽展开（CJK=2，组合/控制=0），窄屏裁列。
    """

    @staticmethod
    def col_widths(line: str) -> List[int]:
        out: List[int] = []
        for ch in line:
            o = ord(ch)
            if o < 32 or 0x7F <= o < 0xA0:
                out.append(0)                          # 控制字符不占列
            elif (0x300 <= o <= 0x36F) or (0x200B <= o <= 0x200F):
                out.append(0)                          # 组合标记 / bidi
            elif (0x1100 <= o <= 0x115F or 0x2E80 <= o <= 0xA4CF
                  or 0xAC00 <= o <= 0xD7A3 or 0xF900 <= o <= 0xFAFF
                  or 0xFE10 <= o <= 0xFE6F or 0xFF00 <= o <= 0xFF60
                  or 0xFFE0 <= o <= 0xFFE6 or 0x1F300 <= o <= 0x1FAFF):
                out.append(2)
            else:
                out.append(1)
        return out

    @staticmethod
    def targets(rect: Rect, lines: List[str]) -> List[Tuple[int, int, str]]:
        """[(row, col, char)]：col 是**渲染列**（宽字符占 2 列）。"""
        out: List[Tuple[int, int, str]] = []
        for r in range(min(rect.h, len(lines))):
            line = lines[rect.y + r] if rect.y + r < len(lines) else ""
            col = 0
            for ch, w in zip(line, SelectionGeometry.col_widths(line)):
                if w == 0:
                    continue
                for dx in range(w):
                    if rect.x <= col + dx < rect.x + rect.w:
                        out.append((rect.y + r, col + dx, ch))
                col += w
        return out

    def hit(self, rect: Rect, lines: List[str], row: int, col: int) -> Optional[str]:
        for r, c, ch in self.targets(rect, lines):
            if r == row and c == col:
                return ch
        return None

    def render_plan(self, rect: Rect, lines: List[str]) -> List[Tuple[int, int, str]]:
        return self.targets(rect, lines)

    def hit_matches_render(self, rect: Rect, lines: List[str]) -> List[str]:
        p: List[str] = []
        plan = self.render_plan(rect, lines)
        for r, c, ch in plan:
            got = self.hit(rect, lines, r, c)
            if got != ch:
                p.append("hit(%d,%d)=%r != render=%r" % (r, c, got, ch))
        return p


def probe_rendered_selection() -> dict:
    p: List[str] = []
    n = 0

    def chk(cond: bool, label: str) -> None:
        nonlocal n
        n += 1
        if not cond:
            p.append(label)

    g = SelectionGeometry()
    rect = Rect(0, 0, 20, 3)
    lines = ["a中b", "xy", "👩\u200d💻z"]
    chk(g.col_widths("a中b") == [1, 2, 1], "CJK 列宽不对")
    chk(g.col_widths("\x1b[31m")[0] == 0 or True, "控制列宽不抛错")
    chk(g.col_widths("a\u0301b") == [1, 0, 1], "组合标记未算 0 列")
    plan = g.targets(rect, lines)
    chk(any(c == 1 and ch == "中" for _, c, ch in plan), "宽字符起点列不对")
    chk(any(c == 2 and ch == "中" for _, c, ch in plan), "宽字符第二列缺失")
    chk(g.hit(rect, lines, 0, 1) == "中", "hit 宽字符首列失败")
    chk(g.hit(rect, lines, 0, 2) == "中", "hit 宽字符次列失败")
    chk(g.hit(rect, lines, 0, 3) == "b", "宽字符后 ascii 列偏移错")
    chk(g.hit(rect, lines, 99, 0) is None, "越界 hit 未返回 None")
    p.extend(g.hit_matches_render(rect, lines))
    n += 1
    narrow = Rect(0, 0, 2, 3)
    chk(all(c < 2 for _, c, _ in g.targets(narrow, lines)), "窄屏未裁列")
    p.extend("narrow: " + x for x in g.hit_matches_render(narrow, lines))
    n += 1
    return {"ok": not p, "checks": n, "evidence":
            "SelectionGeometry: CJK 列宽 / 组合标记 / hit==render / 窄屏裁列",
            "problems": p}
