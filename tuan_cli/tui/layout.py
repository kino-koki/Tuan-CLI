"""青小团 TUI —— 布局/几何域: 视口、滚动、行高、裁剪、盒子尺寸计算。

本模块由原 4812 行单文件 tui.py 拆分而来, 方法体逐行原样迁移 (无逻辑改动)。
模块级常量/工具/小类集中在 `tuan_cli.tui.common`, 由 `from .common import *`
注入到本模块命名空间, 因此方法体内对模块级名字的引用保持不变。
"""

from __future__ import annotations

from .common import *  # noqa: F401,F403


class LayoutMixin:
    """布局/几何域: 视口、滚动、行高、裁剪、盒子尺寸计算。"""

    # ---- 跨 mixin 共享实例属性 (纯声明, 运行期不赋值) ----
    # 由 StateMixin.__init__ 初始化; 声明在此仅供类型检查器解析。
    _app: Optional[Any]
    _diff_width: int
    _follow: bool
    _height_cache: Dict[Tuple[int, str], int]
    _log_window: Any
    _view_top: int

    # ---- 由渲染 mixin 与主类提供的方法 ----
    _scrolled_lines: Callable[..., List[List[Tuple[str, str]]]]
    _slash_menu_rows: Callable[[], int]

    # ---- Diff 实时面板 ----
    def _diff_panel_width(self) -> int:
        """面板宽度: 取终端宽度的 40%, 钳制在 [32, 64] 列。

        低于 ~90 列时不显示面板 (见 `_diff_panel_available`), 因为左右各留一半后
        对话区会被压到不可读。
        """
        if self._diff_width:
            return self._diff_width
        total = self._terminal_cols()
        w = int(total * 0.4)
        return max(32, min(64, w))

    def _diff_panel_available(self) -> bool:
        """终端太窄时不开面板, 避免把对话区压成一条缝。"""
        return self._terminal_cols() >= 90


    # ---- 对话区滚动 (自定义光标定位, Windows/conpty 下可靠) ----
    def _page_rows(self) -> int:
        """单次翻页的行数 = 可视区高度 (减输入框 3 行 + 底栏 1 行)。"""
        try:
            rows = self._app.output.get_size().rows if self._app else 0
        except Exception:
            rows = 0
        if rows <= 0:
            try:
                rows = shutil.get_terminal_size((80, 24)).lines
            except Exception:
                rows = 24
        return max(3, rows - 4)

    def _terminal_cols(self) -> int:
        """终端总列宽 (面板宽度/可用性判定用)。"""
        try:
            cols = self._app.output.get_size().columns if self._app else 0
        except Exception:
            cols = 0
        if cols <= 0:
            try:
                cols = shutil.get_terminal_size((80, 24)).columns
            except Exception:
                cols = 80
        return int(cols)

    def _log_width(self) -> int:
        """对话区可视列宽 (供软换行高度估算)。

        优先用 `_MeasuredWindow` 实测的宽度 —— 对话区实际宽度会被右侧 diff 面板
        (Ctrl+D) 吃掉一块, 用"终端列数-2"估算会偏大, 长消息折行数算少, 虚拟
        视口切片随之错位 (表现为回卷时露白/跳行)。首帧尚无实测值时退化为估算。
        """
        try:
            m = int(getattr(self._log_window, "measured_width", 0) or 0)
        except Exception:
            m = 0
        if m > 0:
            return m
        try:
            cols = self._app.output.get_size().columns if self._app else 0
        except Exception:
            cols = 0
        if cols <= 0:
            try:
                cols = shutil.get_terminal_size((80, 24)).columns
            except Exception:
                cols = 80
        return max(20, cols - 2)

    def _visible_log_rows(self) -> int:
        """对话区**理论上限**可视行数: 按当前布局从终端总行数里逐项扣减。

        为什么需要它: `_viewport_rows()` 信任 `_MeasuredWindow.measured_height`,
        而那个值是**上一帧** write_to_screen 时记下的。布局刚变化的帧 (Ctrl+O 展开
        审计面板 / 打开 "/" 命令面板 / 输入框长到多行 / 切换 diff 面板 / 终端改大小),
        实测值还是旧的"大高度", 于是 `_viewport_slice` 会切出比窗口**能显示的更多行**。
        多出来的行会让 prompt_toolkit 的 Window 触发它自己的内部滚动 —— 于是"我们的
        视口"和"Window 的滚动"两套机制打架, 表现就是上翻后内容被顶掉、翻不动。

        这里算出当前布局下的**上界**, 供 `_viewport_rows()` 做钳制。
        """
        try:
            rows = self._app.output.get_size().rows if self._app else 0
        except Exception:
            rows = 0
        if rows <= 0:
            try:
                rows = shutil.get_terminal_size((80, 24)).lines
            except Exception:
                rows = 24
        # 输入框边框 3 行 + 底栏 1 行
        budget = rows - 4
        # "/" 命令面板: 最多 _SLASH_MAX_VISIBLE 行 + 1 行边框
        if getattr(self, "_slash_open", False) and getattr(self, "_slash_items", None):
            try:
                budget -= int(self._slash_menu_rows()) + 1
            except Exception:
                budget -= _SLASH_MAX_VISIBLE + 1
        # 审计面板: 展开时约占 45% 高度 (与 _MeasuredWindow 里的说明一致)
        if getattr(self, "_audit_visible", False):
            budget = int(budget * 0.55)
        # 命令确认卡片 / 提问卡片按需占据底部若干行
        for attr in ("_confirm_pending", "_ask_pending"):
            if getattr(self, attr, None):
                budget -= 12
                break
        return max(3, budget)

    def _viewport_rows(self) -> int:
        """对话区视口高度 (终端行数) —— 实测值优先, 但**必须按当前布局钳制上界**。

        早期实现无条件相信实测高度, 布局变化的帧里它会过期, 导致切片超过窗口高度,
        进而触发 Window 的内部滚动, 把我们的视口顶掉 (见 `_visible_log_rows`)。
        """
        try:
            m = int(getattr(self._log_window, "measured_height", 0) or 0)
        except Exception:
            m = 0
        ceiling = self._visible_log_rows()
        if m > 0:
            # 实测值可能来自上一帧的旧布局; 取与当前布局上界的较小者。
            return max(3, min(m, ceiling))
        return ceiling

    def _line_heights(self, lines: List[List[Tuple[str, str]]]) -> List[int]:
        """每个逻辑行在 wrap_lines 下占的终端行数 (宽字符感知)。

        与 prompt_toolkit 的换行规则对齐: 按显示宽度断行; 空行/零宽占 1 行。
        视口偏移与切片都按**终端行**计量, 避免长消息 (无换行大段) 使逻辑行与
        终端行错位 → 中间内容永远够不到。

        性能: 历史 screen 由 `_build_history_screen` 缓存复用, 其行文本在流式期间
        不变。这里按 ``(width, text)`` 缓存高度, 命中即返回, 避免每帧对全部历史
        逐行 join + ``wcswidth`` (2000+ 行历史每帧数万次 C 调用)。
        """
        width = self._log_width()
        cache = self._height_cache
        heights: List[int] = []
        for line in lines:
            text = "".join(seg for _, seg in line)
            if not text:
                heights.append(1)
                continue
            key = (width, text)
            h = cache.get(key)
            if h is None:
                disp = _display_width(text)
                h = max(1, math.ceil(disp / width))
                # 有界缓存: 超限清空 (键是 (width,text), 内存占用与历史量级相当)
                if len(cache) > 20000:
                    cache.clear()
                cache[key] = h
            heights.append(h)
        return heights

    def _line_starts(self, heights: List[int]) -> List[int]:
        """每个逻辑行的起始终端行号 (前缀和) —— 视口切片的定位依据。"""
        starts: List[int] = []
        acc = 0
        for h in heights:
            starts.append(acc)
            acc += h
        return starts

    def _scroll_bounds(self, lines: List[List[Tuple[str, str]]]) -> Tuple[int, int, int]:
        """返回 (内容总终端行数, 视口高度, 视口顶端最大合法值)。"""
        total = sum(self._line_heights(lines))
        vp = self._viewport_rows()
        return total, vp, max(0, total - vp)

    def _resolve_view_top(self, max_top: int) -> int:
        """把 `_view_top` 钳到合法范围; follow 时钉在底部。"""
        if self._follow:
            self._view_top = max_top
        else:
            self._view_top = max(0, min(self._view_top, max_top))
        return self._view_top

    def _clip_line_rows(self, line: List[Tuple[str, str]], r0: int,
                        r1: int, width: int) -> List[Tuple[str, str]]:
        """取一个逻辑行里**显示行 [r0, r1)** 的部分 (视口顶/底切到半行时用)。

        按累计显示宽度判定每个字符落在哪个显示行 (`col // width`); 宽字符按其
        起始列归属, 与终端实际折行一致。整行命中时原样返回 (免拷贝)。
        """
        out: List[Tuple[str, str]] = []
        col = 0
        for cls, text in line:
            if not text:
                continue
            buf: List[str] = []
            for ch in text:
                if r0 <= (col // width) < r1:
                    buf.append(ch)
                col += max(0, _wcswidth(ch))
            if buf:
                out.append((cls, "".join(buf)))
        return out

    def _scroll_log(self, delta: int) -> None:
        """按 delta 终端行上/下滚动对话区 (正数向下)。

        单位是**终端行** (软换行后的可视行), 所以 PgUp/PgDn 正好一屏、
        Ctrl+↑/↓ 正好一行, 且能一路翻到最早的历史。滚到底自动恢复 follow
        (新内容继续跟随); 滚上去则停止跟随, 新内容不再把视图拽走。
        """
        try:
            lines = self._scrolled_lines(logic_only=True)
        except Exception:
            return
        if not lines:
            return
        _, _, max_top = self._scroll_bounds(lines)
        if self._follow:
            # 首次上翻: 先落到当前底部, 再叠加本次增量
            self._view_top = max_top
            self._follow = False
        self._view_top = max(0, min(self._view_top + delta, max_top))
        if self._view_top >= max_top:
            self._follow = True
            self._view_top = max_top

    def _scroll_to_top(self) -> None:
        """跳到最早的历史 (停止跟随)。"""
        self._view_top = 0
        self._follow = False

    def _scroll_to_bottom(self) -> None:
        """跳回最新内容并恢复跟随。"""
        self._follow = True
        self._view_top = 0   # 具体值在渲染时按 max_top 解析

    def _scroll_state(self) -> Tuple[bool, int, int, int]:
        """(是否已上翻, 视口顶端, 内容总行, 视口高) —— 供底栏显示位置指示。"""
        try:
            lines = self._scrolled_lines(logic_only=True)
        except Exception:
            return (False, 0, 0, self._viewport_rows())
        total, vp, max_top = self._scroll_bounds(lines)
        top = self._resolve_view_top(max_top)
        return (not self._follow, top, total, vp)

    def _current_line_count(self) -> int:
        """当前渲染内容的段落行数 (供滚动钳位)。"""
        try:
            lines = self._scrolled_lines(logic_only=True)
            return len(lines)
        except Exception:
            return 0


    # ============================================================ "/" 命令面板
    def _term_width(self) -> int:
        """终端真实列宽 (探测失败回退 shutil/80)。"""
        try:
            if self._app is not None:
                w = self._app.output.get_size().columns
                if w and w > 0:
                    return int(w)
        except Exception:
            pass
        try:
            return shutil.get_terminal_size((80, 24)).columns
        except Exception:
            return 80

    def _clip_parts(self, parts: List[Tuple[str, str]]) -> List[Tuple[str, str]]:
        """按终端显示宽度裁剪一行分段 (防文字溢出顶破全屏布局)。

        Window(height=1, wrap_lines=False) 自身不裁切内容: 超宽文本会被终端
        自行软换行, 把整行布局顶错位 (观感即"文字溢出/状态行跳行")。这里按
        列宽硬裁并补省略号, 与 prompt_toolkit 内部行为无关地保证单行控件不溢出。
        """
        width = self._term_width()
        out: List[Tuple[str, str]] = []
        used = 0
        for cls, seg in parts:
            if not seg:
                continue
            w = _disp_width(seg)
            if used + w <= width:
                out.append((cls, seg))
                used += w
                continue
            room = width - used
            if room > 0:
                out.append((cls, self._clip_dw(seg, room)))
            break
        return out

    def _clip_parts_upto(
        self, parts: List[Tuple[str, str]], budget: int,
    ) -> List[Tuple[str, str]]:
        """按**指定列预算**裁剪一行分段 (不依赖终端全宽)。

        与 `_clip_parts` 同逻辑, 但预算由调用方给出 —— 底栏两端布局需要给
        右端 context 提示预留空间, 左端只能占剩余列。
        """
        if budget <= 0:
            return []
        out: List[Tuple[str, str]] = []
        used = 0
        for cls, seg in parts:
            if not seg:
                continue
            w = _disp_width(seg)
            if used + w <= budget:
                out.append((cls, seg))
                used += w
                continue
            room = budget - used
            if room > 0:
                out.append((cls, self._clip_dw(seg, room)))
            break
        return out

    def _box_width(self) -> int:
        """盒子/输入框可用宽度 = 真实 App 列宽 (避免与 wrap_lines 的窗口宽度偏差导致错位/圆角外拐)。

        2026-10-18 修复文字溢出: 旧实现 ``max(44, w)`` 在窄终端 (<44 列) 下
        强制 44 宽, 盒子右边框被顶出屏幕, 对话区 (wrap_lines=True) 把超宽行
        软换行 → 右边框掉到下一行, 观感即"文字溢出/盒子错位"。现完全尊重
        真实宽度, 仅在探测失败时回退 shutil/80。
        """
        try:
            if self._app is not None:
                w = self._app.output.get_size().columns
                if w and w > 0:
                    return int(w)
        except Exception:
            pass
        try:
            return shutil.get_terminal_size((80, 24)).columns
        except Exception:
            return 80

    def _viewport_slice(self, screen: List[List[Tuple[str, str]]]) -> List[List[Tuple[str, str]]]:
        """把整段对话按当前视口切成**正好一屏**的行 (Claude Code 式虚拟滚动)。

        只返回终端行区间 [view_top, view_top+vp) 覆盖到的逻辑行; 首/尾逻辑行
        被切到半行时按显示行裁剪 (`_clip_line_rows`), 因此返回内容的实际高度
        恒等于视口高度 —— Window 无需再自行滚动, 上翻/下翻都是精确整屏位移。
        """
        if not screen:
            return screen
        total, vp, max_top = self._scroll_bounds(screen)
        top = self._resolve_view_top(max_top)
        if total <= vp:
            return screen                      # 内容不足一屏: 全部显示 (顶部对齐)
        width = self._log_width()
        heights = self._line_heights(screen)
        starts = self._line_starts(heights)
        bottom = top + vp
        out: List[List[Tuple[str, str]]] = []
        used = 0
        for i, line in enumerate(screen):
            s = starts[i]
            e = s + heights[i]
            if e <= top or s >= bottom:
                continue
            r0 = max(0, top - s)
            r1 = min(heights[i], bottom - s)
            # 防御: 估算高度与真实折行略有出入时, 宁可少给一行也不要超出视口
            if used + (r1 - r0) > vp:
                break
            out.append(line if (r0 == 0 and r1 >= heights[i])
                       else self._clip_line_rows(line, r0, r1, width))
            used += r1 - r0
        return out or screen[-1:]

    def _fit(self, s: str) -> str:
        """把一行文本裁到对话区可视宽度 (供流式/工具行等超长单行使用)。

        对话区是 `wrap_lines=True`, 长文本软换行本身没问题; 但流式缓冲、
        工具耗时行这类"本应是一行"的元素被折成多行会让人误以为内容重复或
        界面卡住, 故在构造时就裁到一屏宽。
        """
        return self._clip_dw(s, max(8, self._log_width()))

    def _clip_dw(self, s: str, n: int) -> str:
        if n <= 0:
            return ""
        if _disp_width(s) <= n:
            return s
        if n == 1:
            return "…"
        res = ""
        for ch in s:
            if _disp_width(res) + _disp_width(ch) > n - 1:  # 留 1 列给 "…"
                break
            res += ch
        return res + "…"

    def _box_budget(self) -> Tuple[int, int]:
        """卡片盒子宽度预算 = (总宽, 边框内侧宽度)。

        终端窄到连 3 列都不到时 (Windows conpty 窗口被拖到极窄会出现),
        直接返回 (4, 2) 之类的安全下限: 边框算式 `width-2` 为负会让
        `"─" * (width-2)` 变成空串、上下边框退化成 `╭╮`, 排版整体垮掉。
        """
        width = max(4, self._box_width())
        return width, max(2, width - 2)

    def _wrap_dw(self, text: str, width: int) -> List[str]:
        """按显示宽度把长文本切成多行 (CJK 宽字符按 2 列计)。

        确认卡片里的命令正文往往很长 —— 若只做单行截断, 用户看不到命令尾部
        (而那恰恰可能是 `rm -rf /` 之类的关键部分)。这里改为折行铺满卡片宽度,
        保证命令完整可读。
        """
        if width <= 0:
            return [text]
        out: List[str] = []
        cur = ""
        cw = 0
        for ch in text:
            try:
                w = max(0, _wcswidth(ch))
            except Exception:  # noqa: BLE001 - 极端字符宽度探测失败按 1 列
                w = 1
            if cw + w > width and cur:
                out.append(cur)
                cur = ""
                cw = 0
            cur += ch
            cw += w
        out.append(cur)
        return out or [""]

    def _format_home_dir(self, path: str) -> str:
        """codex `format_directory_inner` 同款目录展示: 相对 home 显示 `~/...`。

        对齐 session.rs::format_directory_inner —— 若目录位于用户 home 下,
        前缀 `~` + 分隔符 + 相对路径; 否则返回原绝对路径。
        """
        try:
            home = os.path.expanduser("~")
            norm = os.path.normpath(path)
            if os.path.normcase(norm) == os.path.normcase(home):
                return "~"
            home_prefix = home.rstrip(os.sep) + os.sep
            if os.path.normcase(norm).startswith(os.path.normcase(home_prefix)):
                rel = os.path.normpath(norm[len(home_prefix):])
                return "~" + os.sep + rel.replace(os.sep, "/")
        except Exception:  # noqa: BLE001 - 目录格式化失败回退原路径
            pass
        return path

