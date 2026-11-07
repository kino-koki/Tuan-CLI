"""与 Codex ``tui/src/sidebar_chooser.rs`` 对齐的侧栏选择器。

上游模块头（契约原文）：

    "The sidebar chooser belongs to its parent conversation and can remain
     open without taking input."

逐值/逐分支对齐：
  - ``WIDE_WIDTH = 58``；
  - ``body_row(area, y) = Rect(area.x+1, y, area.width-3, 1)``；
  - ``resize_hint(full, width)``：宽度够用原文，不够用短提示
    ``"←/→ resize · Enter/Esc done"``（**逐字保留**）；
  - ``footer()``：三项固定提示 ``Enter/open``、``Esc/back``、
    ``↑/↓/move``，再链式追加可选的 ``hide_pane``（来自
    ``RuntimeKeymap.primary_hint(Global, "hide_pane")``）；
  - ``CHAT_TAB = " Side chat "``，``chat_tabs()`` 的 ``tab_width``
    就是它的 ``len()``；
  - ``tab_strip()``：单 tab 时标签为 ``CHAT_TAB``，多 tab 时
    ``" Side {index+1} "``；
  - ``choice_rows(area, count, choice)``：
      ``height = 2 if body_row.width < WIDE_WIDTH else 1``
      ``visible = (area.height - 5).div_ceil(height)``
      ``start  = (choice + 1) - visible``
      ``rows   = start .. min(start+visible, count)``
  - ``choice_at(area, count, choice, y)``：
      ``y >= area.bottom()-1 -> None``
      ``offset = (y - area.y) - 4``
      ``rows.nth(offset / height)``
  - ``paint()``：``Clear`` 后空区域直接返回；focused 决定 chooser
    的 ``TabState::Active/Inactive``；标题 ``"Open in sidebar"``；
    选项数 ``ids.len() + 1``，最后一项是 ``"› + New side chat"`` /
    ``"Start from the main chat"``；窄屏每项两行、宽屏一行且用
    ``{title:<pad$}{detail}`` 右对齐 detail；footer 行优先用
    ``resize_hint``，否则用 ``footer()``。

**安全相关**：``choice_at`` 是**命中测试**，``choice_rows`` 是**渲染分页**。
二者必须用同一份 ``height/visible/start`` 计算，否则「点第 3 项却打开
第 2 项」。本模块让两者共用 ``choice_rows()``，并提供
``hit_test_matches_render()`` 自检。另：``count = ids.len()+1`` 里的
``+1`` 是「新建侧会话」入口，越界的 ``choice`` 会被钳制，绝不越界
索引到不存在的会话。

本地化修改（如实列出）：
  - ratatui ``Buffer`` / ``Widget`` / ``Clear`` -> 纯 Python 行列表，
    ``paint()`` 返回可测的渲染计划而非直接写终端；
  - 中文标签（英文原文常量全部保留供核销）：
    ``"Open in sidebar"`` / ``"+ New side chat"`` /
    ``"Start from the main chat"`` / ``"Reopen side chat"`` /
    ``"Side chat"``；10 语言由项目 i18n 提供；
  - ``div_ceil`` 用整数式 ``(a + b - 1) // b`` 显式实现；
  - 新增 ``FooterHint`` dataclass 与 ``footer_plan()``，让可选
    ``hide_pane`` 的链式追加可测；
  - 本地化增强：``choice_at`` 对负坐标、负 offset、空区域显式
    返回 None；``choice`` 钳制到 ``[0, count-1]``。

许可：Apache-2.0（NOTICE 第 13 条）。无 Rust 源码逐字复制。
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from .sidebar_tab_strip import Rect, TabState, TabStrip


def _text_width(text: str) -> int:
    """CJK 显示宽度近似（与第 11 轮 grapheme 近似同口径）。

    上游用 ratatui ``Line::width()``；本模块不引入 ratatui，按
    ``east_asian_width`` 的 W/F 记 2、其余记 1。**如实标注为近似**，
    不声称与 unicode-width 逐字节一致。
    """
    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
               for ch in text)


WIDE_WIDTH = 58
BODY_ROW_SHRINK = 3        # area.width.saturating_sub(3)
BODY_ROW_X_OFFSET = 1
CHOICE_START_OFFSET = 4    # body rows start at area.y + 4
FOOTER_FROM_BOTTOM = 1     # area.bottom() - 1

CHAT_TAB = " Side chat "
NEW_SIDE_CHAT_TITLE_EN = "+ New side chat"
NEW_SIDE_CHAT_DETAIL_EN = "Start from the main chat"
REOPEN_DETAIL_EN = "Reopen side chat"
SIDE_CHAT_TITLE_EN = "Side chat"
OPEN_IN_SIDEBAR_EN = "Open in sidebar"
RESIZE_SHORT_HINT = "←/→ resize · Enter/Esc done"  # 逐字对齐上游

OPEN_IN_SIDEBAR_ZH = "在侧栏中打开"
NEW_SIDE_CHAT_TITLE_ZH = "+ 新建侧边会话"
NEW_SIDE_CHAT_DETAIL_ZH = "从主会话开始"
REOPEN_DETAIL_ZH = "重新打开侧边会话"
SIDE_CHAT_TITLE_ZH = "侧边会话"

FIXED_FOOTER_HINTS: Tuple[Tuple[str, str], ...] = (
    ("Enter", "open"), ("Esc", "back"), ("↑/↓", "move"),
)
FIXED_FOOTER_HINTS_ZH: Tuple[str, ...] = ("打开", "返回", "移动")


@dataclass(frozen=True)
class FooterHint:
    key: str
    action: str


def body_row(area: Rect, y: int) -> Rect:
    """逐值对齐 ``Rect::new(area.x+1, y, area.width-3, 1)``。"""
    return Rect(area.x + BODY_ROW_X_OFFSET, y,
                max(0, area.width - BODY_ROW_SHRINK), 1)


def resize_hint(full: str, width: int, *, zh: bool = True) -> Tuple[str, bool]:
    """返回 ``(文本, 是否用了短提示)``；逐字对齐上游短提示。"""
    if _text_width(full) <= max(0, width):
        return full, False
    return RESIZE_SHORT_HINT, True


def footer(keymap: Optional[Any] = None, *,
           area: Optional[Rect] = None,
           zh: bool = True) -> List[FooterHint]:
    """对齐：三项固定提示 + 可选 ``hide_pane`` 链式追加。"""
    acts = FIXED_FOOTER_HINTS_ZH if zh else tuple(a for _, a in FIXED_FOOTER_HINTS)
    hints = [FooterHint(k, acts[i])
             for i, (k, _) in enumerate(FIXED_FOOTER_HINTS)]
    if keymap is not None:
        hide = None
        try:
            hide = keymap.primary_hint("Global", "hide_pane")
        except Exception:  # noqa: BLE001 - 对齐上游 Option::map
            hide = None
        if hide is not None:
            label = getattr(hide, "display_label", lambda: str(hide))()
            hints.append(FooterHint(str(label),
                                    "隐藏侧栏" if zh else "hide pane"))
    # area 仅用于对齐签名（body_row(area, area.y).width）
    if area is not None:
        _ = body_row(area, area.y).width
    return hints


def chat_tabs(ids: Sequence[Any], selected: Optional[Any]) -> TabStrip:
    """对齐 ``chat_tabs(ids, selected)``：``tab_width = len(CHAT_TAB)``。"""
    return TabStrip(ids=tuple(ids), selected=selected,
                    tab_width=len(CHAT_TAB))


def tab_label(index: int, ids: Sequence[Any], *, zh: bool = True) -> str:
    """单 tab -> ``CHAT_TAB``；多 tab -> ``" Side {i+1} "``。"""
    if len(ids) == 1:
        return CHAT_TAB
    return f" Side {index + 1} "


def _div_ceil(a: int, b: int) -> int:
    """对齐 Rust ``div_ceil``；b<=0 时返回 0（本地化保护）。"""
    if b <= 0:
        return 0
    return max(0, (a + b - 1) // b)


def choice_rows(area: Rect, count: int, choice: int
                ) -> Tuple[int, range]:
    """**渲染与命中测试共用的唯一分页计算**（逐值对齐上游）。"""
    height = 2 if body_row(area, area.y).width < WIDE_WIDTH else 1
    visible = _div_ceil(max(0, area.height - 5), height)
    # 本地化增强：choice 钳制，绝不越界索引到不存在的会话
    safe_choice = max(0, min(choice, max(0, count - 1)))
    start = max(0, (safe_choice + 1) - visible)
    return height, range(start, min(start + visible, count))


def choice_at(area: Rect, count: int, choice: int,
              y: int) -> Optional[int]:
    """对齐 ``choice_at``：footer 行不算选项，offset 从 ``area.y+4`` 起。"""
    if y >= area.bottom - FOOTER_FROM_BOTTOM:
        return None
    if y < area.y or count <= 0:
        return None
    height, rows = choice_rows(area, count, choice)
    offset = (y - area.y) - CHOICE_START_OFFSET
    if offset < 0:
        return None
    return list(rows)[offset // height] if offset // height < len(rows) else None


def choice_detail(index: int, ids: Sequence[Any], *,
                  zh: bool = True) -> Tuple[str, str]:
    """返回 ``(title, detail)``；最后一项是「新建侧边会话」。"""
    marker_at = None  # 由 paint 决定 '›' / ' '
    if index == len(ids):
        return ((NEW_SIDE_CHAT_TITLE_ZH if zh else NEW_SIDE_CHAT_TITLE_EN),
                (NEW_SIDE_CHAT_DETAIL_ZH if zh else NEW_SIDE_CHAT_DETAIL_EN))
    title = (SIDE_CHAT_TITLE_ZH if zh else SIDE_CHAT_TITLE_EN)
    if len(ids) != 1:
        title = f"{title} {index + 1}"
    return title, (REOPEN_DETAIL_ZH if zh else REOPEN_DETAIL_EN)


@dataclass
class PaintedRow:
    y: int
    text: str
    style: str
    kind: str = "choice"

    def to_dict(self) -> Dict[str, Any]:
        return {"y": self.y, "text": self.text,
                "style": self.style, "kind": self.kind}


def paint(focused: bool, area: Rect, ids: Sequence[Any],
          choice: int, *, keymap: Optional[Any] = None,
          resize: Optional[str] = None, zh: bool = True,
          ) -> Dict[str, Any]:
    """对齐 ``paint()``：返回可测的渲染计划而非直接写 ``Buffer``。"""
    plan: Dict[str, Any] = {"focused": focused, "area": area.to_dict(),
                            "rows": [], "footer": [], "truncated": False}
    if area.width <= 0 or area.height <= 0:
        return plan  # 对齐 Clear 后空区域直接返回
    chooser_state = (TabState.ACTIVE if focused else TabState.INACTIVE)
    style = "selection" if focused else "quiet-workspace"
    selected = ids[0] if len(ids) == 1 else None
    tabs = chat_tabs(ids, selected)
    plan["tab_strip"] = tabs.render(
        area, chooser_state, TabState.ABSENT,
        lambda i, _id: tab_label(i, ids, zh=zh))
    footer_y = area.bottom - 1
    row_width = body_row(area, area.y).width

    def add_row(y: int, text: str, row_style: str = "", kind: str = "choice"):
        if y < footer_y:
            plan["rows"].append(PaintedRow(y, text, row_style, kind))

    add_row(area.y + 2,
            OPEN_IN_SIDEBAR_ZH if zh else OPEN_IN_SIDEBAR_EN,
            "bold", "heading")
    count = len(ids) + 1
    height, rows = choice_rows(area, count, choice)
    for offset, index in enumerate(rows):
        marker = "›" if index == max(0, min(choice, count - 1)) else " "
        row_style = style if index == choice else ""
        title, detail = choice_detail(index, ids, zh=zh)
        y = area.y + CHOICE_START_OFFSET + offset * height
        if height == 1:
            # 对齐上游 format!("{title:<pad$}{detail}")：pad 按**显示宽度**
            # 计算（不用 Python 的字符数格式化，CJK 会错位）
            prefix = f"{marker} {title}"
            pad = max(0, row_width - 1 - _text_width(detail)
                      - _text_width(prefix))
            add_row(y, f"{prefix}{' ' * pad}{detail}", row_style)
        else:
            add_row(y, f"{marker} {title}", row_style)
            add_row(y + 1, f"    {detail}", row_style, "detail")
    if footer_y > area.y:
        if resize is not None:
            text, used_short = resize_hint(resize, row_width, zh=zh)
            plan["footer"] = [{"text": text, "short": used_short}]
        else:
            plan["footer"] = [{"text": f"{h.key}/{h.action}", "short": False}
                              for h in footer(keymap, area=area, zh=zh)]
    plan["rows"] = [r.to_dict() for r in plan["rows"]]
    return plan


def hit_test_matches_render(area: Rect, ids: Sequence[Any],
                            choice: int) -> List[str]:
    """本地化增强：逐行核对「点到的选项 == 渲染的选项」。"""
    problems: List[str] = []
    count = len(ids) + 1
    height, rows = choice_rows(area, count, choice)
    painted = paint(True, area, ids, choice)
    visible_ys = [r["y"] for r in painted["rows"]
                  if r["kind"] == "choice"]
    for offset, index in enumerate(rows):
        y = area.y + CHOICE_START_OFFSET + offset * height
        if y not in visible_ys:
            problems.append(f"选项 {index} 未被渲染 (y={y})")
            continue
        hit = choice_at(area, count, choice, y)
        if hit != index:
            problems.append(f"y={y} 渲染选项 {index}，命中 {hit}")
    return problems


def constants() -> Dict[str, Any]:
    return {"wide_width": WIDE_WIDTH, "chat_tab": CHAT_TAB,
            "chat_tab_width": len(CHAT_TAB),
            "resize_short_hint": RESIZE_SHORT_HINT,
            "body_row_shrink": BODY_ROW_SHRINK,
            "choice_start_offset": CHOICE_START_OFFSET,
            "fixed_footer_hints": [list(x) for x in FIXED_FOOTER_HINTS]}
