"""与 Codex ``tui/src/custom_terminal.rs`` 对齐的终端双缓冲与差分绘制。

**许可特别说明**：该文件上游明确标注「derived from ``ratatui::Terminal``」，
采用 **MIT**（Copyright 2016-2022 Florian Dehau / 2023-2025 The Ratatui
Developers）。其许可全文已在 ``THIRD_PARTY_LICENSES/Codex-NOTICE.txt``
（上游 NOTICE）与 ``NOTICE`` 第 9/11 条。本模块只实现**算法契约**，
无 Rust 源码逐字复制。

对齐的核心契约（逐条取自上游）：
  - 两个 buffer（previous / current）在每帧结束时 diff，只输出必要更新；
  - ``diff_buffers`` 扫描每行找 ``last_nonblank_column``：非空 glyph、
    与行尾 bg 不同、带 modifier、或 ``AlwaysUpdate`` 的格子都算「有意义」；
    多宽字符把区域延伸到完整显示宽度；之后的行尾用**一条** ``ClearToEnd``
    清掉，而不是逐个空格 Put（性能关键）；
  - ``AlwaysUpdate`` 的空白格必须留在可绘制前缀里，否则尾部过滤会丢掉
    显式要求的重绘；
  - 尾部相等时，若前一帧有宽字符跨过 clear 边界，仍必须 ClearToEnd；
  - viewport invalidation 会标记旧格子，使带外写入强制不相等；
  - ``flush_updates`` 把最后一个 Put 的坐标记为 ``last_known_cursor_pos``；
  - ``Drop`` 恢复光标样式并显示被隐藏的光标；
  - 同步帧（BSU/ESU）包裹多次写，避免中间光标移动闪屏。

本地化修改（如实列出）：
  - crossterm / ratatui ``Backend`` -> 可注入的 Python ``TerminalBackend``
    协议（便于确定性测试，不依赖 PTY）；
  - 字符位置用字符索引而非字节偏移；CJK/emoji 宽度用 ``display_width``
    本地实现（本地化增强，第 10 轮 ``width`` 模块已做）；
  - ``CellWidth`` 用整数 1/2 表示；``ForcedWidth`` 只保留语义标记；
  - 图片放置 / kitty / sixel **不实现**（OpenAI 专属渲染，属
    ``not_applicable``），但 ``Frame.image_placements`` 字段保留为空列表，
    不谎称支持。

许可：MIT（ratatui 派生）+ Apache-2.0（Codex 包装）。见 NOTICE 第 11 条。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple


# ---------------------------------------------------------------- 宽度
def display_width(ch: str) -> int:
    """东亚宽/全角 -> 2，组合/控制 -> 0，其余 -> 1（UAX #11 近似）。"""
    if not ch:
        return 0
    cp = ord(ch[0])
    if cp == 0 or cp < 32 or 0x7F <= cp < 0xA0:
        return 0
    import unicodedata
    if unicodedata.combining(ch[0]) or unicodedata.category(ch[0]) in ("Mn", "Me"):
        return 0
    if (0x1100 <= cp <= 0x115F or 0x2329 <= cp <= 0x232A
            or 0x2E80 <= cp <= 0xA4CF or 0xAC00 <= cp <= 0xD7A3
            or 0xF900 <= cp <= 0xFAFF or 0xFE10 <= cp <= 0xFE19
            or 0xFE30 <= cp <= 0xFE6F or 0xFF00 <= cp <= 0xFF60
            or 0xFFE0 <= cp <= 0xFFE6 or 0x1F300 <= cp <= 0x1FAFF
            or 0x20000 <= cp <= 0x3FFFD):
        return 2
    return 1


# ---------------------------------------------------------------- 单元格
class CellDiffOption(str, Enum):
    """对齐 ratatui ``CellDiffOption``。"""

    NONE = "none"
    SKIP = "skip"
    ALWAYS_UPDATE = "always_update"
    FORCED_WIDTH = "forced_width"


@dataclass
class Cell:
    symbol: str = " "
    bg: str = "reset"
    fg: str = "reset"
    modifier: frozenset = field(default_factory=frozenset)
    diff_option: CellDiffOption = CellDiffOption.NONE
    skip: bool = False
    forced_width: int = 0

    def cell_width(self) -> int:
        """对齐上游：零宽符号按 1 处理；ForcedWidth 优先。"""
        if self.diff_option is CellDiffOption.FORCED_WIDTH and self.forced_width:
            return max(1, self.forced_width)
        return max(1, display_width(self.symbol))

    def set_diff_option(self, option: CellDiffOption,
                        width: int = 0) -> "Cell":
        self.diff_option = option
        if option is CellDiffOption.FORCED_WIDTH:
            self.forced_width = width
        return self


@dataclass(frozen=True)
class Rect:
    x: int = 0
    y: int = 0
    width: int = 0
    height: int = 0

    def bottom(self) -> int:
        return self.y + self.height

    def right(self) -> int:
        return self.x + self.width

    def contains(self, pos: Tuple[int, int]) -> bool:
        px, py = pos
        return self.x <= px < self.right() and self.y <= py < self.bottom()


class Buffer:
    """最小 ratatui ``Buffer`` 等价物（矩形 content + pos_of）。"""

    def __init__(self, area: Rect):
        self.area = area
        self.content: List[Cell] = [Cell() for _ in range(area.width * area.height)]

    def resize(self, area: Rect) -> None:
        self.area = area
        self.content = [Cell() for _ in range(area.width * area.height)]

    def pos_of(self, index: int) -> Tuple[int, int]:
        w = self.area.width or 1
        return (self.area.x + index % w, self.area.y + index // w)

    def get(self, x: int, y: int) -> Cell:
        return self.content[(y - self.area.y) * self.area.width + (x - self.area.x)]

    def set(self, x: int, y: int, cell: Cell) -> None:
        self.content[(y - self.area.y) * self.area.width + (x - self.area.x)] = cell


# ---------------------------------------------------------------- 绘制命令
class DrawCommand:
    pass


@dataclass
class Put(DrawCommand):
    x: int
    y: int
    cell: Cell

    def is_put(self) -> bool:
        return True


@dataclass
class ClearToEnd(DrawCommand):
    x: int
    y: int
    bg: str

    def is_put(self) -> bool:
        return False


# ---------------------------------------------------------------- OSC 8
def osc8_hyperlink_parts(symbol: str) -> Optional[Tuple[str, str]]:
    """逐分支对齐上游 ``osc8_hyperlink_parts``。

    ``ESC]8;;<dest>BEL<visible>ESC]8;;BEL`` -> (dest, visible)；
    空 destination 返回 None（安全：不允许无目标的链接）。
    """
    prefix = "\x1b]8;;"
    if not symbol.startswith(prefix):
        return None
    content = symbol[len(prefix):]
    dest_end = content.find("\x07")
    if dest_end < 0:
        return None
    destination = content[:dest_end]
    if not destination:
        return None
    suffix = "\x1b]8;;\x07"
    visible_part = content[dest_end + 1:]
    if not visible_part.endswith(suffix):
        return None
    return destination, visible_part[:-len(suffix)]


# ---------------------------------------------------------------- diff
def diff_buffers(a: Buffer, b: Buffer) -> List[DrawCommand]:
    """对齐上游 ``diff_buffers``（含全部四个边界条件）。

    返回 ``Put`` / ``ClearToEnd`` 序列。刻意保持与上游相同的扫描顺序，
    便于逐条回归：行尾优化、AlwaysUpdate 保留、宽字符跨界、带外写入
    强制失效。
    """
    if a.area != b.area:
        # 本地化：尺寸变化时整屏重绘（上游由 resize 先同步两个 buffer）
        updates: List[DrawCommand] = []
        for y in range(b.area.height):
            for x in range(b.area.width):
                c = b.get(b.area.x + x, b.area.y + y)
                updates.append(Put(b.area.x + x, b.area.y + y, c))
        return updates

    updates = []
    w = a.area.width
    h = a.area.height
    for y in range(h):
        row_start = y * w
        row_end = row_start + w
        previous_row = a.content[row_start:row_end]
        row = b.content[row_start:row_end]
        bg = row[-1].bg if row else "reset"

        last_nonblank_column = 0
        column = 0
        while column < len(row):
            cell = row[column]
            width = cell.cell_width()
            if (cell.symbol != " " or cell.bg != bg or cell.modifier
                    or cell.diff_option is CellDiffOption.ALWAYS_UPDATE):
                last_nonblank_column = column + (width - 1 if width > 1 else 0)
            column += max(1, width)

        clear_start = last_nonblank_column + 1
        if clear_start < len(row):
            tail_changed = previous_row[clear_start:] != row[clear_start:]
            wide_char_overlaps_tail = False
            for col in range(clear_start - 1, -1, -1):
                c = previous_row[col]
                if c.symbol != " " or c.cell_width() > 1:
                    wide_char_overlaps_tail = (
                        col + c.cell_width() > clear_start)
                    break
            if tail_changed or wide_char_overlaps_tail:
                x, py = a.pos_of(row_start + clear_start)
                updates.append(ClearToEnd(x, py, bg))

        # 逐格比较，Skip 语义对齐上游
        for col, (prev, cur) in enumerate(zip(previous_row, row)):
            is_skip = (cur.diff_option is CellDiffOption.SKIP
                       or (cur.skip and cur.diff_option is CellDiffOption.NONE))
            if is_skip:
                continue
            if prev != cur or cur.diff_option is CellDiffOption.ALWAYS_UPDATE \
                    or cur.diff_option is CellDiffOption.FORCED_WIDTH:
                x, py = a.pos_of(row_start + col)
                updates.append(Put(x, py, cur))
    return updates


# ---------------------------------------------------------------- backend
class TerminalBackend:
    """可注入后端协议（本地化替代 crossterm）。"""

    def __init__(self, size: Tuple[int, int] = (80, 24)):
        self._size = size
        self.writes: List[str] = []
        self.hidden_cursor = False
        self.cursor_style: Optional[str] = None
        self.synchronized_depth = 0

    def size(self) -> Tuple[int, int]:
        return self._size

    def write(self, data: str) -> None:
        self.writes.append(data)

    def hide_cursor(self) -> None:
        self.hidden_cursor = True

    def show_cursor(self) -> None:
        self.hidden_cursor = False

    def set_cursor_style(self, style: str) -> None:
        self.cursor_style = style

    def reset_cursor_style(self) -> None:
        self.cursor_style = None

    def begin_synchronized_update(self) -> None:
        self.synchronized_depth += 1
        self.write("\x1b[?2026h")

    def end_synchronized_update(self) -> None:
        self.synchronized_depth = max(0, self.synchronized_depth - 1)
        self.write("\x1b[?2026l")

    def flush(self) -> None:
        pass


# ---------------------------------------------------------------- Frame
@dataclass
class Frame:
    """对齐上游 ``Frame`` 的字段语义（图片放置保留为空，见模块头）。"""

    viewport_area: Rect
    buffer: Buffer
    cursor_position: Optional[Tuple[int, int]] = None
    cursor_style: Optional[str] = None
    image_placements: List[Any] = field(default_factory=list)

    def area(self) -> Rect:
        return self.viewport_area

    def buffer_mut(self) -> Buffer:
        return self.buffer

    def set_cursor_style(self, style: str) -> None:
        self.cursor_style = style


class Terminal:
    """对齐上游 ``Terminal<B>`` 的可观测子集。"""

    def __init__(self, backend: TerminalBackend):
        sw, sh = backend.size()
        self.backend = backend
        self.buffers = [Buffer(Rect(0, 0, sw, sh)),
                        Buffer(Rect(0, 0, sw, sh))]
        self.current = 0
        self.hidden_cursor = False
        self.last_cursor_style: Optional[str] = None
        self.viewport_area = Rect(0, 0, sw, sh)
        self.last_known_screen_size: Tuple[int, int] = (sw, sh)
        self.last_known_cursor_pos: Tuple[int, int] = (0, 0)
        self.visible_history_rows = 0
        self._frame_stats: List[Dict[str, int]] = []

    # ------------------------------------------------------------ 缓冲
    def current_buffer(self) -> Buffer:
        return self.buffers[self.current]

    def previous_buffer(self) -> Buffer:
        return self.buffers[1 - self.current]

    def current_buffer_mut(self) -> Buffer:
        return self.buffers[self.current]

    def previous_buffer_mut(self) -> Buffer:
        return self.buffers[1 - self.current]

    def swap_buffers(self) -> None:
        self.current = 1 - self.current

    # ------------------------------------------------------------ 尺寸
    def resize(self, screen_size: Tuple[int, int]) -> None:
        self.last_known_screen_size = screen_size

    def set_viewport_area(self, area: Rect) -> None:
        if self.viewport_area != area:
            self.invalidate_cursor_state()
        self.current_buffer_mut().resize(area)
        self.previous_buffer_mut().resize(area)
        self.viewport_area = area
        self.visible_history_rows = min(self.visible_history_rows, area.y)

    def invalidate_cursor_state(self) -> None:
        """对齐上游：viewport 变化后让光标状态失效，下次强制重绘。"""
        self.last_cursor_style = None

    def invalidate_viewport(self) -> None:
        """对齐上游：带外写入后标记旧格子 AlwaysUpdate，强制不等式。"""
        for c in self.previous_buffer_mut().content:
            c.set_diff_option(CellDiffOption.ALWAYS_UPDATE)

    # ------------------------------------------------------------ 绘制
    def flush_updates(self, updates: Sequence[DrawCommand]) -> None:
        last_put = next((u for u in reversed(updates) if isinstance(u, Put)), None)
        if last_put is not None:
            self.last_known_cursor_pos = (last_put.x, last_put.y)
        draw(self.backend, updates)

    def flush(self) -> None:
        self.flush_updates(diff_buffers(self.previous_buffer(),
                                        self.current_buffer()))

    def draw(self, render: Callable[[Frame], None]) -> Dict[str, int]:
        """一帧：同步更新包裹 -> render -> diff -> flush -> 恢复光标。"""
        area = Rect(0, 0, *self.backend.size())
        if self.viewport_area.width != area.width or \
                self.viewport_area.height != area.height:
            self.set_viewport_area(area)
        self.backend.begin_synchronized_update()
        try:
            frame = Frame(viewport_area=self.viewport_area,
                          buffer=self.current_buffer_mut())
            render(frame)
            updates = diff_buffers(self.previous_buffer(),
                                   self.current_buffer())
            if updates and not self.hidden_cursor:
                self.backend.hide_cursor()
                self.hidden_cursor = True
            self.flush_updates(updates)
            if frame.cursor_style and frame.cursor_style != self.last_cursor_style:
                self.backend.set_cursor_style(frame.cursor_style)
                self.last_cursor_style = frame.cursor_style
            self.swap_buffers()
            self._frame_stats.append({
                "puts": sum(1 for u in updates if isinstance(u, Put)),
                "clears": sum(1 for u in updates if isinstance(u, ClearToEnd)),
            })
            return self._frame_stats[-1]
        finally:
            self.backend.end_synchronized_update()
            self.backend.flush()

    # ------------------------------------------------------------ Drop
    def close(self) -> None:
        """对齐上游 ``Drop``：恢复光标样式并显示被隐藏的光标。"""
        self.backend.reset_cursor_style()
        if self.hidden_cursor:
            self.backend.show_cursor()
            self.hidden_cursor = False

    def __enter__(self) -> "Terminal":
        return self

    def __exit__(self, *exc) -> bool:
        self.close()
        return False


def draw(backend: TerminalBackend, commands: Iterable[DrawCommand]) -> None:
    """把差分命令写成终端字节（本地化：用可注入后端的字符串序列）。"""
    for cmd in commands:
        if isinstance(cmd, Put):
            backend.write(f"\x1b[{cmd.y + 1};{cmd.x + 1}H{cmd.cell.symbol}")
        elif isinstance(cmd, ClearToEnd):
            backend.write(f"\x1b[{cmd.y + 1};{cmd.x + 1}H\x1b[K")
