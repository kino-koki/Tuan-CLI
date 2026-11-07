"""与 Codex ``tui/src/sidebar_tab_strip.rs`` 对齐的标签条几何与命中测试。

上游模块头（契约原文）：

    "Draw sidebar tabs and hit-test the same visible cells. When space runs
    out, keep the selected tab visible and reserve the add button at the
    right edge."

逐值/逐分支对齐 ``TabStrip::targets()``（**几何常量一个都不能改**）：

    width     = area.width.saturating_sub(1)
    plus      = min(width, 3)
    available = width - plus
    height    = min(area.height, 1)
    tab_width = min(available, self.tab_width)
    count     = available / tab_width          // 0 时 unwrap_or_default -> 0
    first     = (selected_index + 1) - count   // 保证选中 tab 可见
    tabs      = ids[first .. first+count]
    add_rect  = Rect(area.x + available, area.y, plus, height)

  - ``TabState``：Absent / Active / Inactive（三态）；
  - ``selected_index()``：``ids.iter().position(|id| Some(id) == selected)``；
  - ``hit()``：**add 区域优先判定**，然后逐个 tab rect 找第一个包含点；
    ``TabTarget::Add`` 恒在最右侧保留（哪怕空间不够也要留住 + 按钮）；
  - ``render()``：当 ``add_state == Absent`` 且 id == selected 时用
    ``selected_state``，其余一律 ``Absent``；``" + "`` 用 ``add_state``；
  - ``style()`` 三态映射（Active 选中样式去下划线 / Inactive 活动 tab
    样式 / Absent 次要文本样式）。

**安全相关**：``hit()`` 必须与 ``render()`` 用**同一份** ``targets()``
几何，否则会出现「点到的和看到的不一致」——这类偏差在带权限的侧栏
里会让用户误开另一个会话。本模块让二者共用同一个函数，并把 rect 的
``contains`` 做成可测契约。

本地化修改（如实列出）：
  - ratatui ``Rect`` / ``Buffer`` / ``Position`` -> 纯 Python dataclass，
    渲染返回**字符串标签序列 + rect 列表**（不引入 ratatui）；
  - `tab_width == 0` 时上游靠 ``checked_div().unwrap_or_default()`` 得 0；
    这里显式返回空 targets，避免除零，语义一致；
  - 中文标签（英文原文 ``" + "`` 保留），样式用 token 字符串代替
    ratatui ``Style``；
  - 新增 ``render_plan()`` 可观测：返回每次渲染的 (label, rect, state)，
    供 ``hit_test_matches_render()`` 自检；
  - 本地化增强：``hit()`` 对负坐标 / 越界点显式返回 None（上游 rect
    天然不含，Python 里做成可测）。

许可：Apache-2.0（NOTICE 第 13 条）。无 Rust 源码逐字复制。
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Dict, Generic, List, Optional, Tuple, TypeVar

PLUS_WIDTH = 3          # min(width, 3)
RIGHT_RESERVE = 1       # area.width.saturating_sub(1)
ADD_LABEL = " + "
TAB_HEIGHT = 1          # area.height.min(1)

Id = TypeVar("Id")


class TabState(str, Enum):
    ABSENT = "Absent"
    ACTIVE = "Active"
    INACTIVE = "Inactive"


class TabTargetKind(str, Enum):
    TAB = "Tab"
    ADD = "Add"


@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    width: int
    height: int

    @property
    def right(self) -> int:
        return self.x + self.width

    @property
    def bottom(self) -> int:
        return self.y + self.height

    def contains(self, px: int, py: int) -> bool:
        """半开区间 [x, x+w) × [y, y+h)；负尺寸一律不含。"""
        return (self.width > 0 and self.height > 0
                and self.x <= px < self.right
                and self.y <= py < self.bottom)

    def to_dict(self) -> Dict[str, int]:
        return {"x": self.x, "y": self.y,
                "width": self.width, "height": self.height}


@dataclass(frozen=True)
class TabTarget(Generic[Id]):
    kind: TabTargetKind
    id: Optional[Id] = None
    index: Optional[int] = None


@dataclass(frozen=True)
class TabStrip(Generic[Id]):
    """对齐 ``TabStrip<'a, Id>`` 三字段。"""

    ids: Tuple[Id, ...]
    selected: Optional[Id] = None
    tab_width: int = 0

    def selected_index(self) -> Optional[int]:
        """对齐 ``position(|id| Some(*id) == self.selected)``。"""
        if self.selected is None:
            return None
        for i, ident in enumerate(self.ids):
            if ident == self.selected:
                return i
        return None

    def targets(self, area: Rect) -> Tuple[List[Tuple[int, Id, Rect]], Rect]:
        """逐值对齐上游几何；**render 与 hit 共用这一份**。"""
        width = max(0, area.width - RIGHT_RESERVE)
        plus = min(width, PLUS_WIDTH)
        available = width - plus
        height = min(area.height, TAB_HEIGHT)
        tab_width = min(available, self.tab_width)
        # 上游 checked_div(tab_width).unwrap_or_default()：tab_width=0 -> 0
        count = available // tab_width if tab_width > 0 else 0
        sel = self.selected_index()
        first = (sel + 1 - count) if sel is not None else 0
        first = max(0, first)
        tabs: List[Tuple[int, Id, Rect]] = []
        for index in range(first, min(first + count, len(self.ids))):
            x = area.x + (index - first) * tab_width
            tabs.append((index, self.ids[index],
                         Rect(x, area.y, tab_width, height)))
        add = Rect(area.x + available, area.y, plus, height)
        return tabs, add

    def hit(self, area: Rect, px: int, py: int) -> Optional[TabTarget[Id]]:
        """**add 优先**，然后按序找第一个包含点的 tab。"""
        tabs, add = self.targets(area)
        if add.contains(px, py):
            return TabTarget(TabTargetKind.ADD)
        for index, ident, rect in tabs:
            if rect.contains(px, py):
                return TabTarget(TabTargetKind.TAB, ident, index)
        return None

    def render_plan(
        self, area: Rect, add_state: TabState,
        selected_state: TabState,
        label: Callable[[int, Id], str],
    ) -> List[Dict[str, Any]]:
        """本地化：返回渲染计划（供 hit/render 一致性自检）。"""
        tabs, add = self.targets(area)
        plan: List[Dict[str, Any]] = []
        for index, ident, rect in tabs:
            state = (selected_state
                     if add_state is TabState.ABSENT
                     and ident == self.selected
                     else TabState.ABSENT)
            plan.append({"kind": "tab", "index": index, "id": ident,
                         "label": label(index, ident),
                         "state": state.value, "rect": rect.to_dict()})
        plan.append({"kind": "add", "label": ADD_LABEL,
                     "state": add_state.value, "rect": add.to_dict()})
        return plan

    def render(self, area: Rect, add_state: TabState,
               selected_state: TabState,
               label: Callable[[int, Id], str]) -> List[Dict[str, Any]]:
        """对齐 ``render()``：样式三态映射 + `" + "` 用 add_state。"""
        return self.render_plan(area, add_state, selected_state, label)

    def hit_test_matches_render(
        self, area: Rect, add_state: TabState,
        selected_state: TabState,
        label: Callable[[int, Id], str],
    ) -> List[str]:
        """本地化增强：逐格核对「点到的 == 看到的」，返回问题列表。"""
        problems: List[str] = []
        plan = self.render_plan(area, add_state, selected_state, label)
        for entry in plan:
            r = entry["rect"]
            cx, cy = r["x"], r["y"]
            if r["width"] == 0 or r["height"] == 0:
                continue
            target = self.hit(area, cx, cy)
            if target is None:
                problems.append(f"渲染格 {entry['kind']} 无法命中 ({cx},{cy})")
                continue
            if entry["kind"] == "add":
                if target.kind is not TabTargetKind.ADD:
                    problems.append("add 格命中了非 add 目标")
            elif target.kind is not TabTargetKind.TAB or target.id != entry["id"]:
                problems.append(
                    f"tab {entry['index']} 命中错位: {target}")
        return problems


def style_token(state: TabState) -> str:
    """对齐上游三态样式映射（本地化为 token 字符串）。"""
    return {
        TabState.ACTIVE: "selection/no-underline",
        TabState.INACTIVE: "active-tab",
        TabState.ABSENT: "secondary-text",
    }[state]


def constants() -> Dict[str, Any]:
    return {"plus_width": PLUS_WIDTH, "right_reserve": RIGHT_RESERVE,
            "add_label": ADD_LABEL, "tab_height": TAB_HEIGHT,
            "states": [s.value for s in TabState]}
