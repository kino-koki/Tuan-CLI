"""青小团 TUI —— 渲染域: 对话/头部/底栏/面板/斜杠菜单/确认卡/markdown。

本模块由原 4812 行单文件 tui.py 拆分而来, 方法体逐行原样迁移 (无逻辑改动)。
模块级常量/工具/小类集中在 `tuan_cli.tui.common`, 由 `from .common import *`
注入到本模块命名空间, 因此方法体内对模块级名字的引用保持不变。
"""

from __future__ import annotations

from .common import *  # noqa: F401,F403

import logging
log = logging.getLogger(__name__)


class RenderMixin:
    """渲染域: 对话/头部/底栏/面板/斜杠菜单/确认卡/markdown。"""

    # ---- 跨 mixin 共享实例属性 (纯声明, 运行期不赋值) ----
    # 这些属性由 StateMixin.__init__ / QxtTUI 在运行时初始化; 同一实例的状态被
    # 拆到多个 mixin 后, 类型检查器无法看到兄弟类的赋值, 故在此显式声明。
    workspace: str
    _agent: Any
    _app: Optional[Any]
    _ask_index: int
    _ask_pending: Optional[Dict[str, Any]]
    _audit_log: List[Tuple[str, str]]
    _audit_visible: bool
    _boot_error: Optional[str]
    _booting: bool
    _busy: bool
    _command_meta: Dict[str, str]
    _commands: List[str]
    _confirm_pending: Optional[Dict[str, Any]]
    _ctx_budget: Optional[int]
    _ctx_tokens: Optional[int]
    _diff_cache: List[Tuple[str, str]]
    _diff_error: str
    _diff_fetched_at: float
    _diff_summary: str
    _diff_visible: bool
    _events: List[Any]
    _history_dirty: bool
    _history_screen: Optional[List[List[Tuple[str, str]]]]
    _history_width: int
    _mode: str
    _model_label: str
    _moon_suppressed: bool
    _no_key: bool
    _no_key_env: str
    _offline_cache: Optional[bool]
    _offline_ts: float
    _plan_mode: bool
    _reason_full: str
    _running: List[str]
    _sl_next: float
    _sl_text: str
    _sl_thread: Optional[Any]
    _slash_index: int
    _slash_items: List[str]
    _slash_metas: List[str]
    _slash_open: bool
    _slash_scroll: int
    _sp_panel: Optional[Dict[str, Any]]
    _stream_buf: str
    _streaming: bool
    _tb_panel: Optional[Dict[str, Any]]
    _toast: str
    _toast_until: float
    _tool_detail: bool
    _tool_start_times: dict
    _trust_index: int
    _trust_pending: Optional[Dict[str, Any]]
    _turn_started: float
    _turn_tool_lines: List[str]

    # ---- 由布局/状态 mixin 与主类提供的方法 (本 mixin 只调用) ----
    _box_width: Callable[[], int]
    _clip_dw: Callable[[str, int], str]
    _clip_parts: Callable[[List[Tuple[str, str]]], List[Tuple[str, str]]]
    _clip_parts_upto: Callable[..., List[Tuple[str, str]]]
    _diff_panel_width: Callable[[], int]
    _elapsed_since_turn: Callable[[], str]
    _fetch_diff: Callable[[], None]
    _fit: Callable[[str], str]
    _format_home_dir: Callable[[str], str]
    _git_branch: Callable[[], str]
    _log_width: Callable[[], int]
    _scroll_state: Callable[[], Tuple[bool, int, int, int]]
    _term_width: Callable[[], int]
    _viewport_slice: Callable[
        [List[List[Tuple[str, str]]]], List[List[Tuple[str, str]]]]
    _wrap_dw: Callable[[str, int], List[str]]

    def _statusline_segment(self) -> str:
        """自定义底栏片段 (/statusline <命令>): 后台执行 + 15s 缓存。

        渲染线程只读取缓存字符串; 到点后在守护线程里跑命令 (3s 超时),
        因此慢命令/坏命令都不会卡住界面 (管道清理问题也隔离在该线程内)。
        """
        try:
            from ..ui import prefs as _prefs
            cmd = _prefs.statusline_command()
        except Exception as exc:  # noqa: BLE001 - 偏好不可用时不显示自定义段
            log.debug("RenderMixin._statusline_segment(): 非致命异常已忽略(设计内降级, 不改控制流): %s", exc)
            return ""
        if not cmd:
            self._sl_text = ""
            return ""
        now = time.monotonic()
        th = self._sl_thread
        if th is not None and th.is_alive():
            return self._sl_text
        if now >= self._sl_next:
            self._sl_next = now + 15.0

            def _run() -> None:
                try:
                    import subprocess
                    proc = subprocess.run(
                        cmd, shell=True, capture_output=True, text=True,
                        encoding="utf-8", errors="replace",
                        stdin=subprocess.DEVNULL, timeout=3,
                    )
                    text = (proc.stdout or "").strip()
                    self._sl_text = " ".join(text.split())[:120]
                except Exception:  # noqa: BLE001 - 命令失败/超时 → 不显示
                    self._sl_text = ""
                if self._app is not None:
                    try:
                        self._app.invalidate()
                    except Exception as exc:  # noqa: BLE001 - 应用已退出
                        log.warning("RenderMixin._statusline_segment(): 非致命异常已忽略(设计内降级, 不改控制流): %s", exc)
                        pass

            self._sl_thread = threading.Thread(
                target=_run, name="tuan-statusline", daemon=True)
            self._sl_thread.start()
        return self._sl_text

    def _render_diff_panel(self) -> Any:
        """右侧 diff 面板内容 (对标 Claude Code /diff 的并排实时面板)。

        该面板的 Window 是 `wrap_lines=False` (diff 需要保持原始行、不折行),
        因此**每一行都必须在渲染出口按显示宽度硬裁** —— 与对话区不同, 这里
        一旦超宽就是真的顶破布局 (面板溢出终端右边界 / 把整屏挤错位)。
        """
        if not self._diff_visible:
            return []
        # 节流刷新: 面板开着时模型连续改文件, 每个重绘帧都 fork git 会拖慢 TUI。
        if time.monotonic() - self._diff_fetched_at > 1.5:
            self._fetch_diff()

        width = max(1, self._diff_panel_width())

        def row(cls: str, text: str) -> Tuple[str, str]:
            return (cls, self._clip_dw(text, width))

        out: List[Tuple[str, str]] = []
        out.append(row("class:primary", t("tui.diff_title")))
        if self._diff_error:
            out.append(("", "\n"))
            out.append(row("class:textdim", self._diff_error))
            return out

        out.append(row("class:textdim", f" {self._diff_summary}"))
        out.append(("", "\n"))
        out.append(row("class:textdim", "  " + t("tui.diff_hint")))
        out.append(("", "\n"))
        if not self._diff_cache:
            out.append(row("class:textdim", "  " + t("tui.diff_clean")))
            return out

        for i, (cls, seg) in enumerate(self._diff_cache):
            if i:
                out.append(("", "\n"))
            # 双重保险: _fetch_diff 已按显示宽度裁过, 这里再裁一次以覆盖
            # 外部直接写入 _diff_cache 的路径 (测试/未来功能)。
            out.append(row(cls, seg))
        return out

    def _render_sp_rows(self) -> None:
        """构建会话选择器面板的富文本行 (style, text)。"""
        from .kimi_modules import format_session_choice, _EMPTY_SESSION_ID
        assert self._sp_panel is not None
        model = self._sp_panel["model"]
        rows: List[Tuple[str, str]] = []
        rows.append(("class:primary", " 会话选择器"))
        rows.append(("class:textdim",
                     f"  范围: {'全部目录' if model.scope == 'all' else '当前目录'} · "
                     f"↑↓选择 · Enter恢复 · Ctrl+A切范围 · Esc关闭"))
        if not model.filtered:
            rows.append(("class:textdim", "  (无会话; Ctrl+A 切换范围查看全部)"))
        for i, s in enumerate(model.filtered):
            mark = "▶" if i == model.selected_index else " "
            cls = "class:primary" if i == model.selected_index else "class:text"
            rows.append((cls, f" {mark} {format_session_choice(s)}"))
        self._sp_panel["rows"] = rows

    def _render_tb_rows(self) -> None:
        assert self._tb_panel is not None
        from .kimi_modules import format_task_choice
        model = self._tb_panel["model"]
        rows: List[Tuple[str, str]] = []
        rows.append(("class:primary", " 后台任务"))
        rows.append(("class:textdim",
                     f"  过滤: {'进行中' if model.filter_mode == 'active' else '全部'} · "
                     f"↑↓选择 · A切过滤 · X停止 · Esc关闭"))
        msg = model.message_live()
        if msg:
            rows.append(("class:warning", f"  {msg}"))
        if not model.filtered:
            rows.append(("class:textdim", "  (无后台任务)"))
        for i, v in enumerate(model.filtered):
            mark = "▶" if i == model.selected_index else " "
            cls = "class:primary" if i == model.selected_index else "class:text"
            rows.append((cls, f" {mark} {format_task_choice(v)}"))
        self._tb_panel["rows"] = rows

    def _render_mcp_panel(self) -> Any:
        """MCP 状态面板渲染 (对话区上方 / 复用 audit 面板区域)。"""
        if not getattr(self, "_mcp_visible", False):
            return []
        try:
            from .kimi_modules import render_mcp_panel
            servers = getattr(self, "_mcp_servers", [])
            rows = render_mcp_panel(servers)
        except Exception:  # noqa: BLE001
            rows = [("class:textdim", "  MCP 状态不可用")]
        out: List[Tuple[str, str]] = [("class:primary", " MCP 服务器状态")]
        for cls, seg in rows:
            out.append(("", "\n"))
            out.append((cls, seg))
        out.append(("", "\n"))
        out.append(("class:textdim", "  Esc 关闭"))
        return out

    def _render_audit(self) -> Any:
        """审计面板内容: 顶部标题 + 思考全文 + 审计日志 (kimi 折叠思考)。

        面板是 `wrap_lines=True`, 正文长文本会软换行 (正常)。但标题与
        "Ctrl+O 收起" 提示拼在同一行, i18n 变长 (德/俄语) 或窄终端下会超宽,
        这里按显示宽度裁剪以免首行被折成两行、标题与正文错位。

        复用同一区域承载 Kimi 移植面板 (Ctrl+R 会话 / Ctrl+T 任务 / F2 MCP):
        它们打开时优先渲染, 否则回落审计内容。
        """
        # ---- Kimi 面板优先级最高 (会话选择器 > 任务浏览器 > MCP) ----
        sp = getattr(self, "_sp_panel", None)
        if sp:
            return sp.get("rows", [])
        tb = getattr(self, "_tb_panel", None)
        if tb:
            return tb.get("rows", [])
        if getattr(self, "_mcp_visible", False):
            return self._render_mcp_panel()
        width = max(8, self._log_width())
        head = self._clip_dw(t("tui.audit_title"), width)
        if not self._audit_visible:
            return [("class:primary", head)]
        hint = self._clip_dw("Ctrl+O", width - _disp_width(head) - 2)
        line: List[Tuple[str, str]] = [("class:primary", head)]
        if hint:
            line.append(("class:textdim", "  " + hint))
        out: List[List[Tuple[str, str]]] = [line]
        # 进行中的思考 (实时)
        if self._reason_full:
            out.append([("class:textdim", self._reason_full)])
        for cls, text in self._audit_log[-40:]:
            out.append([(cls, text)])
        if len(out) == 1:
            out.append([("class:textdim", t("tui.audit_empty"))])
        flat: List[Tuple[str, str]] = []
        for i, r in enumerate(out):
            for cls, seg in r:
                flat.append((cls, seg))
            if i < len(out) - 1:
                flat.append(("", "\n"))
        return flat

    def _render_slash_menu(self) -> Any:
        """"/" 命令面板: 高亮行 + 命令名 + 描述 (+ 溢出时滚动提示行)。

        每行按终端显示宽度裁剪 (CJK 宽字符感知), 防止超宽描述顶破布局。
        """
        items = self._slash_items
        if not items:
            return []
        width = self._term_width()
        visible = min(len(items), _SLASH_MAX_VISIBLE)
        start = self._slash_scroll
        if self._slash_index >= start + visible:
            start = self._slash_index - visible + 1
        elif self._slash_index < start:
            start = self._slash_index
        window = range(start, min(start + visible, len(items)))
        rows: List[List[Tuple[str, str]]] = []
        # C-3.6: 高亮标记按 Windows 终端能力降级 (legacy ConHost 退回 ASCII),
        # 非 Windows / VT 已开 / 测试环境保持 ▶ (既有观感与回归断言不变)。
        from .win_compat import menu_glyph
        sel_mark = menu_glyph("select")
        for i in window:
            cmd = items[i]
            sel = (i == self._slash_index)
            mark = f"{sel_mark} " if sel else "  "
            # C-3.3: 描述优先取平行参数帮助表 (子命令/标志/模型候选的预览文本),
            # 缺省回退命令元数据 (既有行为)。
            desc = ""
            if i < len(self._slash_metas):
                desc = self._slash_metas[i]
            if not desc:
                desc = self._command_meta.get(cmd) or t("tui.cmd_meta")
            # 该面板 wrap_lines=False, 故**整行**必须 ≤ width: 命令名、分隔空格、
            # 描述三者按顺序瓜分预算。旧实现只裁描述、且分隔符恒为2 列,
            # 在12~16 列的极窄终端下 "  /provider  " 这类行仍会算出 13 列。
            head = self._clip_dw(f"{mark}{cmd}", width)
            gap_room = max(0, width - _disp_width(head))
            gap = " " * min(2, gap_room)
            rest = gap_room - _disp_width(gap)
            desc = self._clip_dw(desc, rest) if rest > 0 else ""
            sel_cls = "class:slashsel" if sel else ""
            rows.append([
                (sel_cls or "class:slashcmd", head),
                (sel_cls, gap),
                (sel_cls or "class:slashdesc", desc),
            ])
        if len(items) > _SLASH_MAX_VISIBLE:
            hidden = len(items) - visible
            hint = t("tui.slash_more", n=hidden, pos=f"{self._slash_index + 1}/{len(items)}")
            # C-3.4: 溢出时帮助并入滚动提示行 (不加高面板, 保持 9 行封顶契约)
            rows.append([("class:slashhint", self._clip_dw(f"{hint}  · ? 帮助", width))])
        else:
            # C-3.4: 无溢出时面板底部固定帮助行 (_slash_menu_rows 已多留 1 行)
            rows.append([("class:slashhint",
                          self._clip_dw("? 帮助 — ↑↓ 选择 · Enter 填入 · Esc 关闭", width))])
        out: List[Tuple[str, str]] = []
        for r_i, row in enumerate(rows):
            for cls, seg in row:
                out.append((cls, seg))
            if r_i < len(rows) - 1:
                out.append(("", "\n"))
        return out


    # ============================================================ "?" 快捷键帮助浮层
    # 移植自 codex-rs/tui/src/bottom_pane/shortcut_overlay.rs: 标题 "Keyboard shortcuts",
    # 三栏 Compose / Session / Transcript (open first), 底部 "/keymap customize" 提示,
    # 关闭提示 "? / esc close"。快捷键标签按 Windows 平台规范 (ctrl+t / pgup / pgdn / enter)。
    _HELP_GROUPS: List[Tuple[str, List[Tuple[str, str]]]] = [
        ("Compose", [
            ("/", "Commands"),
            ("@", "Mention files"),
            ("!", "Shell command"),
            ("shift+enter", "New line"),
            ("ctrl+v", "Paste image"),
            ("ctrl+g", "External editor"),
            ("ctrl+r", "Search history"),
            ("esc", "Edit last message"),
        ]),
        ("Session", [
            ("tab", "Send message"),
            ("alt+shift+tab", "Change mode"),
            ("alt+,", "Less reasoning"),
            ("alt+.", "More reasoning"),
            ("alt+left / alt+right", "Subagents (empty prompt)"),
            ("f4", "Inspect activity"),
            ("ctrl+c", "Quit"),
        ]),
        ("Transcript (open first)", [
            ("ctrl+t", "Open transcript"),
            ("f3", "Find text"),
            ("pgup / pgdn", "Scroll"),
            ("ctrl+space", "Start selection"),
            ("ctrl+home / ctrl+end", "Top / latest"),
            ("alt+shift+, / alt+shift+.", "Top / latest"),
        ]),
    ]

    def _render_help_overlay(self) -> Any:
        """Codex 同款 "Keyboard shortcuts" 三栏帮助浮层。

        复刻 shortcut_help.rs 的 group_lines 布局: 宽度够就三栏并排, 不够
        两栏 (Session+Transcript 同栏), 再不够单栏堆叠。键名 accent 蓝加粗,
        动作普通文字; key 列左对齐, 动作缩进 key_width + 2 列; 栏间 4 列 gap。
        整行按累积显示宽度裁剪, 防止窄屏下溢出。
        """
        width = self._term_width()

        # 每个 group 先转成 ["标题行", (key, action)...] 的 (style, text) 列表。
        # 保留原始 key/action (无 "  " 前缀), 前缀在渲染时按栏宽精确补齐。
        group_cols: List[List[List[Tuple[str, str]]]] = []
        for gtitle, entries in self._HELP_GROUPS:
            col: List[List[Tuple[str, str]]] = [
                [("class:textstrong", gtitle)]
            ]
            for key, action in entries:
                col.append([
                    ("class:primary", key),
                    ("class:textdim", action),
                ])
            group_cols.append(col)

        def _col_width(col: List[List[Tuple[str, str]]]) -> int:
            """一栏的渲染宽度 = max(标题宽, max(key_w + 2 + action_w))。"""
            title_w = _disp_width(col[0][0][1])
            body = max(
                (_disp_width(r[0][1]) + 2 + _disp_width(r[1][1]) for r in col[1:]),
                default=0,
            )
            return max(title_w, body)

        def _render_col(
            col: List[List[Tuple[str, str]]], col_w: int,
        ) -> List[List[Tuple[str, str]]]:
            """把一栏渲染成 (style, text) 行; key 列左对齐, 标题不缩进。"""
            key_w = max(
                (_disp_width(r[0][1]) for r in col[1:]), default=0,
            )
            out: List[List[Tuple[str, str]]] = []
            for r_i, row in enumerate(col):
                if len(row) == 1:  # 标题行
                    out.append([(row[0][0], row[0][1])])
                else:
                    pad = " " * (key_w - _disp_width(row[0][1]) + 2)
                    out.append([
                        (row[0][0], row[0][1]),
                        (row[1][0], pad + row[1][1]),
                    ])
            return out

        gap = 4
        widths = [_col_width(c) for c in group_cols]

        # 选择布局: 三栏 / 两栏 (Session+Transcript 同栏) / 单栏堆叠。
        if sum(widths) + gap * 2 <= width:
            layout_cols = group_cols
            layout_widths = widths
            # 每栏渲染后按本栏宽补齐 (栏间加 gap)。
            max_rows = max(len(c) for c in layout_cols)
            rows: List[List[Tuple[str, str]]] = []
            for r_i in range(max_rows):
                row: List[Tuple[str, str]] = []
                for ci, col in enumerate(layout_cols):
                    rendered = _render_col(col, layout_widths[ci])
                    if r_i < len(rendered):
                        row.extend(rendered[r_i])
                    if ci < len(layout_cols) - 1:
                        row.append(("", " " * gap))
                rows.append(row)
        else:
            # 两栏: 左 Compose, 右 Session + 空行 + Transcript。
            right: List[List[Tuple[str, str]]] = (
                list(group_cols[1]) + [[("", "")]] + list(group_cols[2])
            )
            two = [group_cols[0], right]
            two_w = [
                max(widths[0], 0),
                max(widths[1], widths[2]),
            ]
            max_rows = max(len(two[0]), len(two[1]))
            rows = []
            for r_i in range(max_rows):
                row = []
                for ci, col in enumerate(two):
                    rendered = _render_col(col, two_w[ci])
                    if r_i < len(rendered):
                        row.extend(rendered[r_i])
                    if ci < len(two) - 1:
                        row.append(("", " " * gap))
                rows.append(row)

        # 组装最终输出: 标题 + 空行 + 栏行 + 尾部空行 + "/keymap customize" + 空行 + close。
        out_lines: List[List[Tuple[str, str]]] = [
            [("class:textstrong", "  Keyboard shortcuts")],
            [("", "")],
        ]
        out_lines.extend(rows)
        out_lines.append([("", "")])
        out_lines.append([
            ("class:primary", "  /keymap"),
            ("class:textdim", " customize"),
        ])
        out_lines.append([("", "")])
        out_lines.append([("class:textdim", "  ? / esc close")])

        # 扁平化为 FormattedTextControl 的 fragments, 每行按宽度裁剪。
        out: List[Tuple[str, str]] = []
        for r_i, row in enumerate(out_lines):
            # 整行累积宽度裁剪, 防止某栏超宽撑破全屏。
            used = 0
            for cls, seg in row:
                if not seg:
                    continue
                w = _disp_width(seg)
                if used + w > width:
                    seg = self._clip_dw(seg, max(0, width - used))
                out.append((cls, seg))
                used += _disp_width(seg)
            if r_i < len(out_lines) - 1:
                out.append(("", "\n"))
        return out

    def _render_boot_error(self) -> List[Tuple[str, str]]:
        """启动失败态: 简短错误行 (对齐 codex startup_error, 无粒子盒子/进度条)。

        旧实现 `_render_boot` 把粒子徽记盒 + 进度条画在错误信息上面, 与 Codex
        启动观感脱节; 现在启动即渲染对话界面, 只在**构建内核失败**时展示这一屏。
        """
        out: List[Tuple[str, str]] = []
        budget = max(4, self._box_width() - 2)

        def emit(cls: str, text: str) -> None:
            out.append((cls, self._clip_dw(text, budget) + "\n"))

        emit("class:error", f"  ✗ {self._boot_error}")
        emit("class:textdim", f"  {t('tui.exit_ctrl_c')}")
        return out

    def _mode_badge(self) -> Tuple[str, str]:
        """底部状态栏模式徽标 (fragment 对)。

        展示名: 五模式用中文名 (感通/灵码/闲聊/无界/协同), plan 只读态用 "plan"。
        颜色按等级映射: chat→dim, collaboration→warning, gantong/lingma→primary,
        boundless→error (原 yolo 的红), plan→magenta (codex footer.rs:164)。
        """
        mode = self._mode or "standard"
        # plan 是只读规划态, 独立于五模式, 用 codex 的 magenta。
        if mode == "plan":
            return ("class:plan", "plan")
        # 徽标文本: 优先中文名, 未知 ID 回退原文 (绝不让渲染帧抛错)。
        try:
            from ..modes.registry import MODE_NAMES
            label = MODE_NAMES.get(mode, mode)
        except Exception:
            label = mode
        # 颜色按等级 (含历史别名回退): 未知一律 warning, 保守不炸。
        try:
            from ..modes.registry import MODE_LEVELS
            level = MODE_LEVELS.get(mode, "")
        except Exception:
            level = ""
        if level == "L4":          # boundless: 原 yolo 红
            cls = "class:error"
        elif level in ("L3", "L2"):  # gantong/lingma/collaboration: 蓝
            cls = "class:primary"
        elif level == "L0":        # chat: dim
            cls = "class:textdim"
        else:
            cls = "class:warning"
        return (cls, label)

    def _context_string(self) -> str:
        """底部上下文占用: context: X% (est/budget)。"""
        est = self._ctx_tokens or 0
        bud = self._ctx_budget or 0
        pct = min(100.0, est / bud * 100.0) if bud > 0 else 0.0
        self._context_pct = pct

        def _fmt(n: int) -> str:
            if n >= 1_000_000:
                return f"{n / 1_000_000:.0f}M"
            if n >= 1_000:
                return f"{n / 1_000:.1f}k"
            return str(n)

        return f"context: {pct:.0f}% ({_fmt(est)}/{_fmt(bud)})"

    def _completion_footer_text(self) -> str:
        """codex `FinalMessageSeparator` 同款完成分隔线文案。

        对齐 separators.rs::label(): 回合结束时显示 ``Worked for {elapsed}``,
        其中 elapsed 按 codex 规则格式化 —— <1s→"<1s", <60s→"{s}s",
        <3600→"{m}m {s}s", 否则 "{h}h {m}m {s}s" (仅保留非零单位)。
        末尾附完成时刻 HH:MM (24h), 与 " • " 连接。
        """
        if not self._turn_started:
            return ""
        s = max(0, int(time.monotonic() - self._turn_started))
        if s <= 0:
            elapsed = "<1s"
        elif s < 60:
            elapsed = f"{s}s"
        else:
            h, rem = divmod(s, 3600)
            m, sec = divmod(rem, 60)
            parts = []
            if h:
                parts.append(f"{h}h")
            if m or h:
                parts.append(f"{m}m")
            parts.append(f"{sec}s")
            elapsed = " ".join(parts)
        label = f"Worked for {elapsed}"
        try:
            label += f" · {time.strftime('%H:%M', time.localtime())}"
        except Exception as exc:  # noqa: BLE001 - 时钟失败绝不影响完成分隔线
            log.warning("RenderMixin._completion_footer_text(): 非致命异常已忽略(设计内降级, 不改控制流): %s", exc)
            pass
        return label

    def _working_status_line(self) -> List[Tuple[str, str]]:
        """codex 忙碌状态行: `Working (Ns · esc to interrupt)` (无 hint 时 `Working (Ns)`)。

        对齐 status_indicator_widget.rs: activity_indicator + summary_shimmer("Working")
        + " " + "({pretty_elapsed} • {interrupt} to interrupt)".dim()。
        """
        parts: List[Tuple[str, str]] = [("class:textdim", "• ")]
        parts.append(("class:textstrong", "Working"))
        elapsed = self._elapsed_since_turn()
        parts.append(("class:textdim", f" ({elapsed} • esc to interrupt)"))
        return parts

    def _working_status_text(self) -> str:
        """footer 用纯文本忙碌状态 (与 _working_status_line 同文案, 无样式)。"""
        return f"Working ({self._elapsed_since_turn()} • esc to interrupt)"

    def _context_left_hint(self) -> str:
        """Codex 同款 "X% context left" (底栏右端 context 提示)。

        对齐 codex-rs/tui/src/bottom_pane/footer.rs 的 ``context_window_line()``:
        有预算时显示**剩余**百分比 (``100 - 已用%``, clamp 到 0..100);
        无预算 (模型窗口未知) 回落 ``100% context left`` —— 即 Codex 空态快照
        ``empty.snap`` 的初始渲染。
        """
        est = self._ctx_tokens or 0
        bud = self._ctx_budget or 0
        if bud > 0:
            used_pct = min(100.0, est / bud * 100.0)
            remaining = max(0.0, 100.0 - used_pct)
            return f"{int(round(remaining))}% context left"
        return "100% context left"


    # ============================================================ 渲染: 对话区

    # ============================================================ Markdown 渲染 (代码语法高亮)
    # pygments token 类别 -> 暗色主题十六进制前景 (GitHub Dark 风, 与品牌蓝协调)
    _CODE_TOKEN_COLORS: Dict[str, str] = {
        "Keyword": "#FF7B72",
        "Keyword.Constant": "#79C0FF",
        "Name.Function": "#D2A8FF",
        "Name.Class": "#FFA657",
        "Name.Builtin": "#79C0FF",
        "Name.Decorator": "#D2A8FF",
        "Name.Namespace": "#C9D1D9",
        "String": "#A5D6FF",
        "String.Doc": "#A5D6FF",
        "String.Escape": "#FFA657",
        "Number": "#79C0FF",
        "Comment": "#7D8590",
        "Operator": "#FF7B72",
        "Punctuation": "#C9D1D9",
        "Literal": "#A5D6FF",
        "Generic.Deleted": "#FFA198",
        "Generic.Inserted": "#7EE787",
        "Generic.Strong": "#C9D1D9 bold",
        "Generic.Emph": "#C9D1D9 italic",
        "Text": "#C9D1D9",
    }

    _CODE_DEFAULT = "#C9D1D9"

    def _color_for_token(self, ttype: Any) -> str:
        """pygments token 类型 -> 十六进制前景色 (从具体到通用逐级回退)。"""
        for t in ttype.split():
            parts = str(t).split(".")
            key = ".".join(parts[1:]) if len(parts) > 1 else parts[0]
            if key in self._CODE_TOKEN_COLORS:
                return self._CODE_TOKEN_COLORS[key]
        return self._CODE_DEFAULT

    def _highlight_code(self, code: str, lang: str) -> List[List[Tuple[str, str]]]:
        """按语言做 pygments 语法着色, 返回逐逻辑行的 (颜色, 文本) 段列表。

        每段仅前景着色 (不铺背景), 以区别于正文; 每行即一个逻辑行, 供对话区
        软换行高度估算; 无法识别的语言回落纯文本。
        """
        from pygments.lexers import get_lexer_by_name
        from pygments.token import Token as _PToken
        code = code.rstrip("\n")
        try:
            lexer = get_lexer_by_name((lang or "text").lower(), stripnl=False)
            tokens = list(lexer.get_tokens(code))
        except Exception:
            tokens = [(_PToken.Text, code)]
        lines: List[List[Tuple[str, str]]] = []
        cur: List[Tuple[str, str]] = []
        for ttype, value in tokens:
            color = self._color_for_token(ttype)
            for idx, piece in enumerate(value.split("\n")):
                if idx > 0:
                    lines.append(cur)
                    cur = []
                if piece:
                    cur.append((color, piece))
        if cur:
            lines.append(cur)
        if not lines:
            lines.append([("", "")])
        return [ln if ln else [("", "")] for ln in lines]

    def _render_markdown_message(self, text: str) -> List[List[Tuple[str, str]]]:
        """把助手消息按 Markdown 渲染: 代码块语法高亮 + 语言标签, 其余纯文本。

        首行带 ● 状态符 (若事件已带则复用, 避免双 bullet); 正文延续行缩进 2 格;
        代码块以 `› lang` 标签引导、块内不缩进、结束补空行分隔。返回逻辑行列表。
        """
        import re
        fence_re = re.compile(r"^\s*```(\w*)\s*$")
        text = str(text)
        if text.startswith(STATUS_BULLET):
            text = text[len(STATUS_BULLET):]
        lines = text.lstrip("\n").split("\n")
        out: List[List[Tuple[str, str]]] = []
        first = True

        def push(segs: List[Tuple[str, str]], indent: bool = False) -> None:
            nonlocal first
            if first:
                if not (segs and segs[0][1].startswith(STATUS_BULLET)):
                    segs = [("class:textdim", STATUS_BULLET)] + segs
                first = False
            elif indent and segs[0][1]:
                # 空行不加缩进: 否则每行空行都带两个尾随空格, 既在终端里看不见,
                # 又会被选中复制出去, 还让 diff 里凭空多出空白字符。
                segs = [("class:text", "  ")] + segs
            out.append(segs)

        i, n = 0, len(lines)
        while i < n:
            raw = lines[i]
            m = fence_re.match(raw)
            if m:
                lang = m.group(1) or ""
                code: List[str] = []
                i += 1
                while i < n and not lines[i].strip().startswith("```"):
                    code.append(lines[i])
                    i += 1
                i += 1  # 跳过结束围栏 (若存在)
                push([("class:textdim", f"› {lang}" if lang else "› code")])
                for cl in self._highlight_code("\n".join(code), lang):
                    out.append(cl)
                # 代码块后补一行空行做视觉分隔; 但若后面没有内容 (收尾的代码块),
                # 或已经是空行, 就别再补 —— 否则空行会与块分隔叠加成两行。
                if i < n and not (i < n and not lines[i].strip()):
                    push([("", "")])
            else:
                push([("class:text", raw)], indent=True)
                i += 1
        return out

    def _msg_to_lines(self, role: str, text: str,
                      width: Optional[int] = None) -> List[List[Tuple[str, str]]]:
        # 用户消息: Codex CLI 风格 —— 左对齐浅灰半透明底 (history_prompt_style 近似),
        # "›" 前缀 **dim** (codex messages.rs:266 `"› ".bold().dim()`), 正文 **accent**
        # (user_message_element_style 把 fg 设成 accent)。快照佐证: user_prompt_has_a_
        # background...snap 中 x=0 `›` 是 BOLD|DIM、x=2 正文是 NONE(accent)。无 emoji;
        # 助手消息走 Markdown 渲染。
        if role == "user":
            bullet = USER_MESSAGE_BULLET
            userbg = f"class:text bg:{USER_MESSAGE_BG}"
            bcls = "class:textdim"        # 前缀 › : dim (codex "› ".bold().dim())
            ccls = f"class:primary bg:{USER_MESSAGE_BG}"  # 正文: accent + 浅灰底
            cont = f"class:text bg:{USER_MESSAGE_BG}"
        else:
            # log/助手: 直接走 Markdown (代码块语法高亮), 不再逐行纯文本。
            # 统一灰色底层: 助手消息与用户消息刷同一种灰底 (用户选择"全部统一灰色",
            # 消除"一块灰一块不灰"的割裂感)。
            rows = self._render_markdown_message(text)
            return [self._with_user_bg(row) for row in rows]
        # 事件可能已带 bullet 前缀 (写入时角色标记), 渲染时防重复叠加 (修复双 ✨)。
        raw = str(text).lstrip("\n")
        if raw.startswith(bullet):
            raw = raw[len(bullet):]
        # codex wrap_width = width - (LIVE_PREFIX_COLS + 1) = width - 3:
        # 左侧 2 列留给 "› " 前缀, 右侧再留 1 列 margin, 用户消息不贴右缘。
        wrap_w = max(1, (width or self._log_width()) - 3)
        lines: List[str] = []
        for ln in raw.split("\n"):
            lines.extend(self._wrap_dw(ln, wrap_w) or [""])
        out: List[List[Tuple[str, str]]] = []
        for i, ln in enumerate(lines):
            if i == 0:
                seg: List[Tuple[str, str]] = []
                if bullet:
                    seg.append((bcls, bullet))
                if ln:
                    seg.append((ccls, ln))
                out.append(seg)
            else:
                out.append([(cont, "  " + ln)])
        return out

    def _with_user_bg(self, row: List[Tuple[str, str]]) -> List[Tuple[str, str]]:
        """给一行 fragment 统一补灰底 (class 后追加 ``bg:USER_MESSAGE_BG``)。

        ``_render_markdown_message`` 返回的 fragment class 可能是 ``class:text``、
        ``class:code_xxx`` 或空串 ``""``。空 class 直接拼接会得到 ``" bg:..."``
        (前导空格, prompt_toolkit 可能报错), 所以空 class 单独构造。
        """
        bg = f" bg:{USER_MESSAGE_BG}"
        out: List[Tuple[str, str]] = []
        for cls, seg in row:
            if cls:
                out.append((cls + bg, seg))
            else:
                out.append((bg.lstrip(), seg))
        return out

    def _colored_lines(self, cls: str, text: str) -> List[List[Tuple[str, str]]]:
        out: List[List[Tuple[str, str]]] = []
        for ln in str(text).split("\n"):
            out.append([(cls, ln)] if ln else [("", ln)])
        return out

    def _scrolled_lines(self, logic_only: bool = False) -> List[List[Tuple[str, str]]]:
        """构建对话区**完整**内容 (段落行列表) —— 不做视口裁剪。

        裁剪由 `_viewport_slice` 负责 (本方法始终返回全量历史, 滚动位置
        `_view_top` 单独记录)。`logic_only` 参数为兼容旧调用保留, 已无差别。

        - 工具完成记录默认折叠为一行 "see N tool calls", Ctrl+O 展开逐条;
        - 返回的 list 每项是一行 (list[ (cls,text) ])。
        """
        # 信任确认态优先: 未知目录首次访问时整屏显示确认卡片 (不显示对话区)
        if self._trust_pending:
            return _split_flat_lines(self._render_trust_confirm())

        # 启动失败态: 整屏只显示简短错误行 (不再有粒子加载屏盒子)。
        if self._boot_error:
            return _split_flat_lines(self._render_boot_error())

        # 历史部分走缓存: 只有 `_events` 真的变化 (append/trim) 或对话区宽度变化
        # 时才全量重建, 否则复用。流式期间 `_events` 不变, 这一大段 O(n) 渲染
        # (含逐行 `_display_width`) 不再每帧重跑 —— 这是卡顿的主因。
        #
        # 重要: `_build_history_screen` 返回的是**缓存 list 对象**, 绝不能直接
        # extend 动态卡片 (工具行/流式/确认卡/提问卡)。否则每调用一次就把这些
        # 动态卡片追加进缓存, 行数逐帧累积 (116→126→136...), 虚拟视口总高不断
        # 膨胀, 表现为"提问卡片态滚轮翻历史"(top 随每次重渲染漂移) 与内存泄漏。
        # 这里浅拷贝缓存后再追加动态内容, 缓存本身保持只含 `_events` 的纯历史。
        screen = list(self._build_history_screen())

        # 本轮工具调用: 折叠成一行摘要 (see N), 展开时逐条; 始终镜像进审计面板
        if self._turn_tool_lines:
            if self._tool_detail:
                # codex exec_cell/render.rs: 工具详情首行前缀 "  └ ", 续行 "    " (dim)。
                # 前缀占 4 显示列, 内容须截到 log_width-4, 保证整行不超一屏宽。
                detail_w = max(4, self._log_width() - 4)
                for ln in self._turn_tool_lines:
                    detail_lines = self._clip_dw(ln, detail_w).split("\n")
                    for i, dl in enumerate(detail_lines):
                        prefix = "  └ " if i == 0 else "    "
                        screen.append([("class:textdim", prefix + dl)])
            else:
                n = len(self._turn_tool_lines)
                screen.append([("class:primary", self._fit(
                    f"▸ see {n} tool calls (Ctrl+O)"))])

        # 流式
        if self._streaming and self._stream_buf:
            screen.append([("class:text", self._fit(
                STATUS_BULLET + self._stream_buf.lstrip(chr(10))))])
        elif self._busy and not self._running and not self._streaming and not self._moon_suppressed:
            # codex 忙碌状态行 "Working (Ns · esc to interrupt)" (替代旧月亮行)
            screen.append(self._working_status_line())
        # 在途工具
        for name in self._running:
            elapsed = self._tool_start_times.get(name)
            elapsed_str = f" ({time.monotonic() - elapsed:.1f}s)" if elapsed else ""
            screen.append([("class:textdim", self._fit(
                t("tui.tool_run", name=name, time=elapsed_str)))])

        if not screen:
            screen.append([("class:textdim", t("tui.ready_empty"))])

        # 命令确认卡片: 追加在对话区底部 (输入框上方)。放在这里而不是输入框里,
        # 是修复"确认框撑破输入框边框"的关键 —— 它现在是内容, 不是输入提示。
        if self._confirm_pending:
            screen.extend(_split_flat_lines(self._render_confirm_card()))
        # 模型提问卡片: 同样追加在对话区底部 (输入框上方), 跟随虚拟视口切片。
        # 优先级高于确认卡 —— 提问是模型在等用户拍板, 必须先于一切被看见。
        if self._ask_pending:
            screen.extend(_split_flat_lines(self._render_ask_card()))

        return screen

    def _build_history_screen(self) -> List[List[Tuple[str, str]]]:
        """把 `_events` 渲染成历史逻辑行, 结果缓存供 `_scrolled_lines` 复用。

        性能关键: 流式输出时每帧都会调用 `_scrolled_lines`, 而 `_events` 里的
        历史 (含每条用户/助手消息) 在流式期间**不变**。旧实现对全部历史逐帧
        重新 `_msg_to_lines` + 逐行 `_display_width`, 2000+ 行时每帧多花数十毫秒,
        直接表现为卡顿。这里仅在 dirty 或宽度变化时重建。
        """
        log_w = self._log_width()
        if (not self._history_dirty
                and self._history_screen is not None
                and self._history_width == log_w):
            return self._history_screen

        screen: List[List[Tuple[str, str]]] = []
        prev_role = ""
        for ev in self._events:
            if isinstance(ev, tuple):
                screen.extend(self._colored_lines(ev[0], ev[1]))
            elif isinstance(ev, list):
                screen.append(ev)
            else:
                role = "user" if ev.startswith(USER_MESSAGE_BULLET) else "log"
                # 块间空行分隔, 但**对标 Claude Code 的紧凑排版**做两处收敛:
                # 1. 提问与其回答之间不空行 —— 一次问答是一个整体, 空行会把它拆成
                #    两个视觉区块, 是"行距偏松"的最大来源;
                # 2. 连续空行去重 —— 代码块尾部已补过空行, 块分隔再补一次就变成
                #    两行空白, 累积起来把对话撑得又长又散。
                if screen and screen[-1] and not (prev_role == "user" and role == "log"):
                    screen.append([])
                screen.extend(self._msg_to_lines(role, ev, width=log_w))
                prev_role = role

        self._history_screen = screen
        self._history_width = log_w
        self._history_dirty = False
        return screen

    def _render_conversation(self) -> Any:
        """扁平化**当前视口**的对话内容供 FormattedTextControl 渲染 (行间加 \\n)。

        这里返回的不是整段历史, 而是按 `_view_top` 切好的一屏 —— 这正是"能真正
        回看上面记录"的关键: 内容再长也只渲染可见的那几行, 翻页即改切片起点。
        """
        screen = self._viewport_slice(self._scrolled_lines())
        if not screen:
            return [("class:textdim", t("tui.ready_empty"))]
        flat: List[Tuple[str, str]] = []
        for i, line in enumerate(screen):
            for cls, seg in line:
                flat.append((cls, seg))
            if i < len(screen) - 1:
                flat.append(("", "\n"))
        return flat

    def _render_header(self) -> Any:
        """顶部状态 HUD: 实时状态(启动转圈/思考月亮/就绪勾) + 模式 + 模型。"""
        parts: List[Tuple[str, str]] = []
        # 复制/操作反馈 toast: 优先于常规状态展示 (2 秒后自动消失)
        if self._toast and time.monotonic() < self._toast_until:
            return self._clip_parts([("class:text", " " + self._toast)])
        if self._trust_pending:
            parts.append(("class:warning", f"? {t('tui.trust_title')}"))
            return self._clip_parts(parts)
        if self._ask_pending:
            parts.append(("class:warning", f"? {t('tui.ask_title')}"))
            return self._clip_parts(parts)
        if self._confirm_pending:
            parts.append(("class:warning", f"? {t('tui.confirm_title')}"))
            return self._clip_parts(parts)
        if self._busy or self._running or self._streaming:
            # codex 状态行: "• Working (Ns • esc to interrupt)" (替代旧月亮 + Processing)
            parts.extend(self._working_status_line())
        else:
            parts.append(("class:success", f"{SUCCESS_MARK} {t('fs.ready')}"))
        if self._plan_mode:
            parts.append(("class:plan", f"  [{t('tui.plan_badge')}]"))
        if self._model_label:
            parts.append(("class:text", f"  {self._model_label}"))
        # header 也是 height=1 的单行控件: 长模型名 (provider/model 很长) 会顶破
        # 顶部一行, 必须按显示宽度硬裁。
        return self._clip_parts(parts)

    def _render_footer(self) -> Any:
        """单行底部状态栏 (Codex CLI 两端布局)。

        左端: `? for shortcuts` (空闲) 或 `mode · model · status · dir · branch`;
        右端: `X% context left` (secondary dim)。中间以空格隔开。
        语义色对齐 Codex status_line_style: model→cyan/primary、dir→green、
        branch→magenta、separator 用 " · "。
        """
        # 信任确认期: 底栏只显示确认提示 (不展示模型/状态/目录; 超宽裁剪防溢出)
        if self._trust_pending:
            return self._clip_parts([("class:warning", " " + t("tui.trust_footer"))])
        # 模型提问期: 底栏让位给选项提示 (↑↓ 选择 · Enter 确认)
        if self._ask_pending:
            opts = (self._ask_pending or {}).get("options") or []
            hint = t("tui.ask_opt_hint") if opts else t("tui.ask_free_hint")
            return self._clip_parts([("class:warning", " " + hint)])
        # 命令确认期: 同上, 底栏让位给确认提示
        if self._confirm_pending:
            return self._clip_parts([("class:warning", " " + t("tui.confirm_footer"))])

        left: List[Tuple[str, str]] = []

        # Codex footer 整行从第 2 列开始 (FOOTER_INDENT_COLS=2, footer.rs:255)。
        left.append(("", "  "))

        # Codex 同款 "? for shortcuts": 空闲且无命令面板时, 左端显示快捷键提示。
        # codex key_hint_style() 对键标签用 加粗前景 (深底 Reset+bold, key_hint.rs:284),
        # 非 dim; " for shortcuts" 用 secondary。因此 `?` 用 textstrong (加粗亮白)。
        if (not self._busy and not self._streaming and not self._slash_open
                and not self._commands):
            left.append(("class:textstrong", "?"))
            left.append(("class:textdim", " for shortcuts"))
        else:
            # 模式徽标 (五模式 ID + plan 只读态) —— codex 对 Plan mode 用 magenta。
            left.append(self._mode_badge())

            # C-5.2 离线横幅: 消费 CLI 核心分片新建的 core/network_check.is_offline()。
            # 该模块由并行分片提供; 未落地时 try/import 静默降级, 横幅不激活也不报错,
            # 待联调。探测结果缓存 30s (footer 随动画高频重绘, 不能每帧探网络)。
            _is_offline: Optional[Callable[..., bool]] = None
            try:
                from ..core.network_check import is_offline as _is_offline_impl
                _is_offline = _is_offline_impl
            except Exception as exc:  # noqa: BLE001 - network_check 尚未就绪: 横幅暂不激活
                log.warning("RenderMixin._render_footer(): 非致命异常已忽略(设计内降级, 不改控制流): %s", exc)
                pass
            if _is_offline is not None:
                try:
                    now = time.monotonic()
                    if now - self._offline_ts > 30.0:
                        self._offline_cache = bool(_is_offline())
                        self._offline_ts = now
                    if self._offline_cache:
                        offline_label = self._model_label or "ollama/qwen2.5:7b"
                        left.append(("class:warning",
                                     f"  ⚠ 离线模式 — 已切换至本地模型 {offline_label}"))
                except Exception as exc:  # noqa: BLE001 - 探测异常不阻断底栏渲染
                    log.warning("RenderMixin._render_footer(): 非致命异常已忽略(设计内降级, 不改控制流): %s", exc)
                    pass

            # Kimi 同款命令行提示: 仅当启用了命令补全且空闲时展示, 保持简短
            if self._commands and not self._busy and not self._streaming:
                left.append(("class:textdim", f"  {t('tui.cmd_hint')}"))

            # 模型名 (去 provider 前缀, 语义色 cyan) + 状态
            model = self._model_label or "default"
            if "/" in model:
                model = model.rsplit("/", 1)[-1]
            if self._no_key and not self._booting:
                status = t("tui.no_key_hint", env=self._no_key_env or "API Key")
                status_cls = "class:warning"
            elif self._booting:
                status = t("tui.boot_starting")
                status_cls = "class:textdim"
            elif self._busy or self._streaming:
                # codex 同款: "Working (Ns · esc to interrupt)" 而非简单 "Thinking…"
                status = self._working_status_text()
                status_cls = "class:text"
            elif self._running:
                tool = self._running[-1] if self._running else ""
                status = tool if tool else t("fs.ready")
                status_cls = "class:accent"
            else:
                status = t("fs.ready")
                status_cls = "class:success"
            left.append(("class:primary", f" {model}"))
            left.append((status_cls, f" {status}"))

            # 工作目录 (语义色 green)
            cwd = os.path.basename(os.path.normpath(self.workspace)) or self.workspace
            left.append(("class:success", f" · {cwd}"))

            # git 分支 (语义色 magenta / shell)
            git_branch = self._git_branch()
            if git_branch:
                left.append(("class:shellmode", f" · {git_branch.replace(' ', '')}"))

            # Super-Agent 活动提示: 绑定引擎有存活 Worker 或待人工处理项时,
            # 在底栏左端追加轻量徽标 (让"后台自主任务"对用户可见, 而非隐藏)。
            try:
                sa = getattr(self._agent, "_superagent", None)
                if sa is not None and sa.is_running():
                    seg = self._superagent_footer_seg(sa)
                    if seg:
                        left.extend(seg)
            except Exception as exc:  # noqa: BLE001 - Super-Agent 提示绝不阻断底栏渲染
                log.warning("RenderMixin._render_footer(): 非致命异常已忽略(设计内降级, 不改控制流): %s", exc)
                pass

        # 回卷位置指示: 一旦用户上翻离开底部就高亮提示 (Claude Code 同款),
        left.extend(self._scroll_indicator())

        # 右端: Codex 同款 "X% context left" (secondary dim)。
        # 预算靠模型名猜不可靠, 用 token 计数估算百分比 (无真实预算则显示 100%)。
        context_right = self._context_left_hint()
        context_w = _disp_width(context_right)
        width = self._term_width()
        # 两端布局: 右端 context 提示固定贴右缘, 左端裁剪到剩余宽度。
        # 窄屏下若连左端 + context 都放不下, 丢弃 context (保留左端更有信息量)。
        if context_w + 2 > width:  # context 本身都超宽: 只显示左端
            return self._clip_parts(left)
        # 左端裁剪预算 = 宽度 - context - 最小 1 列间隙。
        left_budget = max(0, width - context_w - 1)
        parts = self._clip_parts_upto(left, left_budget)
        used = sum(_disp_width(seg) for _c, seg in parts)
        gap = max(1, width - used - context_w - 1)
        parts.append(("", " " * gap))
        parts.append(("class:textdim", context_right))
        return parts

    def _learner_footer_seg(self) -> str:
        """安全学习器校准徽标 (仅当在线更新 > 0 时显示)。

        只读一次磁盘 (结果缓存在实例上), 不随动画帧反复访问 home 目录;
        任何异常都静默降级为空串 —— 底栏渲染不能被安全层 I/O 拖垮。
        """
        if not hasattr(self, "_lr_updates"):
            n = 0
            try:
                from pathlib import Path

                from ..config.loader import home_dir
                from ..core.security_learner import SecurityLearner
                n = int(SecurityLearner(home=Path(home_dir())).state.updates)
            except Exception:  # noqa: BLE001 - 学习器不可用则不显示
                n = 0
            self._lr_updates = n
        return f" · 学习校准 {self._lr_updates}" if self._lr_updates > 0 else ""

    def _scroll_indicator(self) -> List[Tuple[str, str]]:
        """底栏回卷指示片段 (未上翻时返回空)。

        上翻后显示 `↑ 已上翻 42/411 行 · End 回底` —— 让用户明确知道自己不在
        底部, 以及怎么回去 (否则"看不到最新回复"很像界面卡死)。
        """
        try:
            scrolled, top, total, vp = self._scroll_state()
        except Exception as exc:  # noqa: BLE001 - 指示器绝不阻断底栏渲染
            log.debug("RenderMixin._scroll_indicator(): 非致命异常已忽略(设计内降级, 不改控制流): %s", exc)
            return []
        if not scrolled or total <= vp:
            return []
        # OpenCode 克制配色: 位置用 accent 蓝 (非警示黄), 回底提示用更弱灰。
        return [("class:accent", f"  ↑ {top + 1}/{total}"),
                ("class:textmuted", f" {t('tui.scroll_back_hint')}")]

    def _superagent_footer_seg(self, sa: Any) -> List[Tuple[str, str]]:
        """Super-Agent 底栏徽标片段 (有存活 Worker 或待人工处理时显示)。

        轻量单次查询 (避免每帧重算): 返回空列表表示无活动, 底栏保持纯净。
        """
        try:
            active = sa.workers.active_count() if sa.workers else 0
            needs = len(sa.panel.needs_human()) if sa.panel else 0
        except Exception as exc:  # noqa: BLE001
            log.debug("RenderMixin._superagent_footer_seg(): 非致命异常已忽略(设计内降级, 不改控制流): %s", exc)
            return []
        seg: List[Tuple[str, str]] = []
        # OpenCode 风格: 后台自主任务徽标用独立青绿 (roleagent), 与用户蓝/助手灰区分。
        # 活跃 Worker 用青绿, 待人工处理用 warning (需动作) —— 颜色即优先级提示。
        if active:
            seg.append(("class:roleagent", f" · SA:{active}"))
        if needs:
            seg.append(("class:warning", f" · SA!{needs}"))
        return seg

    def _box_row(self, segs: List[Tuple[str, str]], inner: int,
                 pad: str = "  ") -> List[Tuple[str, str]]:
        """把一段 (cls, text) 拼成带左右边框的一行, 右侧对齐竖线。

        内容总宽超过可用宽度时从第一段起按显示宽度截断 (补省略号),
        防止窄屏下长标题/说明/选项行撑破右边框。供信任确认卡片、命令
        确认卡片与模型提问卡片共用, 保证几类卡片排版完全一致。

        可用宽度按 `pad` 的**实际**显示宽度推导 (旧实现硬编码 `-2`, 一旦
        调用方传不同 pad 就会算错; 且 `inner` 很小时结果为负, 补空格数
        变正数后整行仍超宽)。
        """
        pad_w = _disp_width(pad)
        avail = max(0, inner - pad_w)      # 左右边框各占 1 列, 已由 inner 排除
        body_w = sum(_disp_width(s) for _, s in segs)
        if body_w > avail:
            clipped: List[Tuple[str, str]] = []
            rest = avail
            for cls, s in segs:
                w = _disp_width(s)
                if w <= rest:
                    clipped.append((cls, s))
                    rest -= w
                    continue
                if rest > 0:
                    clipped.append((cls, self._clip_dw(s, rest)))
                rest = 0
                break
            segs = clipped
            body_w = sum(_disp_width(s) for _, s in segs)
        line: List[Tuple[str, str]] = [("class:primary", "│")]
        line.append(("", pad))
        line.extend(segs)
        line.append(("", " " * max(0, avail - body_w)))
        line.append(("class:primary", "│"))
        return line

    def _menu_blank(self, width: int) -> List[Tuple[str, str]]:
        """codex `render_menu_surface` 同款整行背景填充 (上下 inset V=1 的留白行)。"""
        bg = f"bg:{USER_MESSAGE_BG}"
        return [(bg, " " * max(0, width))]

    def _menu_row(self, segs: List[Tuple[str, str]], width: int,
                  inset_h: int = 2) -> List[Tuple[str, str]]:
        """codex `render_menu_surface` 同款**无边框背景块**内容行。

        对齐 selection_popup_common.rs: 整块只刷 ``user_message_style`` 背景
        (``Block::default().style(...)``, 无 border), 内容区 inset H=2 (左右各
        2 格), 因此没有 ``│``/``╭`` 边框字符 —— 选项弹窗是悬浮背景块而非盒子。

        内容总宽超过 ``width - inset_h*2`` 时逐段累计裁剪 (与 ``_box_row`` 同规则)。
        """
        bg = f"bg:{USER_MESSAGE_BG}"
        pad = " " * inset_h
        avail = max(1, width - inset_h * 2)
        body_w = sum(_disp_width(s) for _, s in segs)
        if body_w > avail:
            clipped: List[Tuple[str, str]] = []
            rest = avail
            for cls, s in segs:
                w = _disp_width(s)
                if w <= rest:
                    clipped.append((cls, s))
                    rest -= w
                    continue
                if rest > 0:
                    clipped.append((cls, self._clip_dw(s, rest)))
                break
            segs = clipped
            body_w = sum(_disp_width(s) for _, s in segs)
        line: List[Tuple[str, str]] = [(bg, pad)]
        for cls, s in segs:
            # 内容片段统一继承背景色, 否则中间露出对话区底色, 背景块不连续。
            if bg not in (cls or ""):
                cls = f"{cls} {bg}" if cls else f"class:text {bg}"
            line.append((cls, s))
        line.append((bg, " " * max(0, avail - body_w)))
        return line

    def _render_trust_confirm(self) -> List[Tuple[str, str]]:
        """codex 无边框背景块风格信任确认卡 (对齐 render_menu_surface)。

        codex approval/elicitation 弹窗是整块 ``user_message_style`` 背景 (无
        ``╭─╮`` 边框), 内容 inset V=1 / H=2, 选项前缀 ``› N. ``。这里改为同款
        悬浮背景块, 不再画圆角边框。
        """
        pending = self._trust_pending or {}
        ws = str(pending.get("workspace", ""))
        width = max(8, self._box_width())
        clip_dw = self._clip_dw

        def row(segs: List[Tuple[str, str]]) -> List[Tuple[str, str]]:
            return self._menu_row(segs, width)

        out: List[Tuple[str, str]] = []
        out += self._menu_blank(width)                      # 顶部 inset V=1
        out.append(("", "\n"))
        out += row([("class:warning", t("tui.trust_title"))])
        out.append(("", "\n"))
        out += row([("class:boxsub", t("tui.trust_folder") + ": "),
                    ("class:text", clip_dw(ws, max(1, width - 4 - _disp_width(t("tui.trust_folder") + ": "))))])
        out.append(("", "\n"))
        for ln in t("tui.trust_desc").split("\n"):
            out += row([("class:textdim", ln)])
            out.append(("", "\n"))
        out += row([("class:success", t("tui.trust_opt"))])
        out.append(("", "\n"))
        # 选项列表 (↑↓ 选择 · Enter 确认; 也可直接输入 1/2 或 y/n):
        # 此前这两行选项被遗漏渲染, 导致对话框"有标题没选项、完全无法进入工作区"。
        # 选项前缀对齐 codex list_selection_view: 选中 "› N. ", 未选中 "  N. " (编号加 ".")。
        for _i, (_label, _desc) in enumerate((
            (t("tui.trust_opt_trust"), t("tui.trust_opt_trust_desc")),
            (t("tui.trust_opt_distrust"), t("tui.trust_opt_distrust_desc")),
        )):
            _sel = self._trust_index == _i
            _mark = "› " if _sel else "  "
            out += row([("class:accent" if _sel else "class:textdim",
                         f"{_mark}{_i + 1}. {_label}")])
            out.append(("", "\n"))
            out += row([("class:textdim", "   " + clip_dw(_desc, max(1, width - 4)))])
            out.append(("", "\n"))
        out += self._menu_blank(width)                      # 底部 inset V=1
        out.append(("", "\n"))
        # footer 提示: codex 弹窗 footer 缩进 2 格、弱化色 (accept_cancel_hint_line)。
        out.append(("class:textdim", "  " + clip_dw(t("tui.trust_prompt"), max(1, width - 4)) + "\n"))
        return out

    def _render_confirm_card(self) -> List[Tuple[str, str]]:
        """codex 无边框背景块风格命令确认卡 (对齐 render_menu_surface)。

        取代旧的 run_in_terminal 方案: 旧方案把提示 print 到输入框所在光标位置,
        长命令直接撑破输入框边框, 且"确认"在语义上变成了输入框内容 —— 既不美观
        也不该出现在那儿。现在卡片渲染在对话区底部, 输入框只负责收 y/n。
        """
        pending = self._confirm_pending or {}
        width = max(8, self._box_width())
        clip_dw = self._clip_dw

        def row(segs: List[Tuple[str, str]]) -> List[Tuple[str, str]]:
            return self._menu_row(segs, width)

        out: List[Tuple[str, str]] = []
        out += self._menu_blank(width)                      # 顶部 inset V=1
        out.append(("", "\n"))
        out += row([("class:warning", t("tui.confirm_title"))])
        out.append(("", "\n"))
        # 命令正文逐行铺开; 超宽行折行而非截断, 保证命令尾部可见
        for ln in str(pending.get("prompt", "")).split("\n"):
            for seg in self._wrap_dw(ln, max(1, width - 4)):
                out += row([("class:text", seg)])
                out.append(("", "\n"))
        expected = pending.get("expected")
        if expected is not None:
            out += row([("class:boxsub", t("tui.confirm_code_hint", code=expected))])
            out.append(("", "\n"))
        out += row([("class:success", t("tui.confirm_opt"))])
        out.append(("", "\n"))
        out += self._menu_blank(width)                      # 底部 inset V=1
        out.append(("", "\n"))
        out.append(("class:textdim", "  " + clip_dw(t("tui.confirm_prompt"), max(1, width - 4)) + "\n"))
        return out

    def _render_ask_card(self) -> List[Tuple[str, str]]:
        """codex 无边框背景块风格模型提问卡 (对齐 render_menu_surface)。

        渲染在对话区底部 (与确认卡片同位), 因此天然进入虚拟视口切片 —— 长问题
        自动折行、超长选项按显示宽度裁剪, 不会再把输入框/边框顶破。
        """
        pending = self._ask_pending or {}
        width = max(8, self._box_width())
        clip_dw = self._clip_dw
        opts: List[str] = list(pending.get("options") or [])
        sel = max(0, min(len(opts) - 1, self._ask_index)) if opts else -1

        def row(segs: List[Tuple[str, str]]) -> List[Tuple[str, str]]:
            return self._menu_row(segs, width)

        out: List[Tuple[str, str]] = []
        out += self._menu_blank(width)                      # 顶部 inset V=1
        out.append(("", "\n"))
        out += row([("class:warning", "? " + clip_dw(t("tui.ask_title"), max(1, width - 4)))])
        out.append(("", "\n"))
        # 问题正文: 逐行折行铺开, 保证长问题不溢出卡片
        for ln in str(pending.get("question", "")).split("\n"):
            for seg in self._wrap_dw(ln, max(1, width - 4)):
                out += row([("class:text", seg)])
                out.append(("", "\n"))
        # 选项: 高亮项加 › 前缀 + 反显, 未选项缩进对齐 (对齐 codex list_selection_view)
        if opts:
            out.append(("", "\n"))
            for i, o in enumerate(opts):
                marker = "› " if i == sel else "  "
                cls = "class:success" if i == sel else "class:text"
                out += row([(cls, marker + clip_dw(f"{i + 1}. {o}", max(1, width - 4)))])
                out.append(("", "\n"))
            out += row([("class:textdim",
                         clip_dw(t("tui.ask_opt_hint"), max(1, width - 4)))])
            out.append(("", "\n"))
        else:
            out += row([("class:textdim",
                         clip_dw(t("tui.ask_free_hint"), max(1, width - 4)))])
            out.append(("", "\n"))
        out += self._menu_blank(width)                      # 底部 inset V=1
        return out

    def _show_welcome(self) -> None:
        """就绪后展示 codex 同款会话头 (SessionHeaderHistoryCell::display_lines)。

        精确对齐 codex-rs/tui/src/history_cell/session.rs 的 display_lines:
            空行
              >_ Tuan-CLI (vX)   ← accent ">_ " 前缀 + bold 标题 + dim (vX)
                 ~/path/to/dir   ← 5 空格缩进 + dim 目录 (relativize_to_home)
        无任何 ╭─╮ 欢迎盒 (codex 就绪态顶部只有会话头, 那是用户看到的"残留"
        来源 —— 旧实现把品牌盒画在会话头之前, 观感与 codex 不一致)。

        这两行是固定文本, 不经过 _scrolled_lines 的 _fit, 必须按对话区宽裁剪,
        否则窄屏 (≤44 列) 下 `  >_ Tuan-CLI (v0.3.3)` / 长目录行会超宽溢出。
        注意用 _box_width() (真实 App 列宽) 而非 _log_width() (有 max(20,..) 下限),
        否则 16/12 列终端仍会按 20 列预算裁, 结果还是超宽。
        """
        cwd = os.path.abspath(self.workspace)
        log_w = max(8, self._box_width())
        cwd_disp = self._format_home_dir(cwd)
        self._events.append([("", " ")])  # 顶部空行 (2 空格视觉留白)
        title_segs = [
            ("class:primary", "  >_ "),   # accent >_ 前缀 (2 空格缩进)
            ("class:textstrong", "Tuan-CLI"),
            ("class:textdim", f" ({VERSION})"),
        ]
        # 逐段累计裁剪 (与 _box_row 同规则): 段累计超预算即裁当前段并丢弃后续段。
        clip_title: List[Tuple[str, str]] = []
        rest = log_w
        for cls, s in title_segs:
            w = _disp_width(s)
            if w <= rest:
                clip_title.append((cls, s))
                rest -= w
                continue
            if rest > 0:
                clip_title.append((cls, self._clip_dw(s, rest)))
            break
        self._events.append(clip_title)
        self._events.append([
            ("class:textdim", self._clip_dw("     " + cwd_disp, log_w)),
        ])
        # 会话头后留一个空行, 与 codex 首轮消息间距一致 (对话区不再被盒子压顶)。
        self._events.append([])

