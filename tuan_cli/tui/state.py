"""青小团 TUI —— 状态域: 生命周期、流式输出、日志、会话与信任确认状态机。

本模块由原 4812 行单文件 tui.py 拆分而来, 方法体逐行原样迁移 (无逻辑改动)。
模块级常量/工具/小类集中在 `tuan_cli.tui.common`, 由 `from .common import *`
注入到本模块命名空间, 因此方法体内对模块级名字的引用保持不变。
"""

from __future__ import annotations

from typing import cast

from .common import *  # noqa: F401,F403

import logging
log = logging.getLogger(__name__)


class StateMixin:
    """状态域: 生命周期、流式输出、日志、会话与信任确认状态机。"""

    # ---- 由渲染/布局 mixin 与主类提供的方法 (本 mixin 只调用) ----
    _animate: Callable[[], None]
    _apply_vim_mode: Callable[..., None]
    _build_keys: Callable[[], Any]
    _completion_footer_text: Callable[[], str]
    _diff_panel_available: Callable[[], bool]
    _diff_panel_width: Callable[[], int]
    _help_overlay_rows: Callable[[], int]
    _log_window: Any
    _on_input_changed: Callable[..., None]
    _on_vim_mode_changed: Callable[[bool], None]
    _render_audit: Callable[[], Any]
    _render_conversation: Callable[[], Any]
    _render_diff_panel: Callable[[], Any]
    _render_footer: Callable[[], Any]
    _render_help_overlay: Callable[[], Any]
    _render_slash_menu: Callable[[], Any]
    _show_welcome: Callable[[], None]
    _slash_menu_rows: Callable[[], int]
    _slogan_dispatch: Callable[..., Any]

    def __init__(
        self,
        on_submit: Callable[[str], Optional[str]],
        title: str = "青小团",
        workspace: str = ".",
        on_cancel: Optional[Callable[[], None]] = None,
        on_command: Optional[Callable[[str], Optional[str]]] = None,
        commands: Optional[List[str]] = None,
        command_meta: Optional[Dict[str, str]] = None,
        command_tiers: Optional[Dict[str, str]] = None,
    ) -> None:
        self.on_submit = on_submit
        self.on_cancel = on_cancel
        self.on_command = on_command
        self.title = title
        self.workspace = workspace
        # Kimi 同款 `+/命令` 补全词表: 传入则启用补全, 缺省 (兼容旧调用) 则不启用。
        self._commands: List[str] = list(commands or [])
        self._command_meta: Dict[str, str] = dict(command_meta or {})
        # 命令层级表 (命令 -> "core"|"expert"|"hidden"): 空前缀时仅展开核心层,
        # 前缀匹配时全量展开 (专家层命令按首字母可达)。缺省 None 保持旧行为。
        self._command_tiers: Dict[str, str] = dict(command_tiers or {})
        # "/" 命令面板状态 (Claude Code 同款: 输入 / 自动高亮列出全部命令,
        # ↑↓ 选择, Enter/Tab 确认填入, Esc 关闭)。取代 prompt_toolkit 自带
        # 补全菜单 —— 后者在输入框位于屏幕底部时下拉菜单无处渲染 (被底栏/
        # 屏幕边缘裁掉), 且无法做整行高亮。见 _on_input_changed / _render_slash_menu。
        self._slash_open = False            # 面板是否展开
        self._slash_items: List[str] = []   # 当前过滤后的命令列表
        self._slash_index = 0               # 高亮项索引
        self._slash_scroll = 0              # 滚动窗口起始索引
        self._slash_accepting = False       # 程序化写入文本时抑制联动 (防递归)
        self._slash_arg_mode = False        # 命令参数补全态 (/model <partial> 等)
        self._slash_arg_prefix = ""         # 参数补全时回填用的命令前缀 (如 "/model ")
        # C-3.3: 面板条目与描述平行表 (_slash_items 第 i 项的帮助文本),
        # 命令级缺省回退 command_meta, 子命令/参数级用 _SLASH_SUBCMDS 帮助。
        self._slash_metas: List[str] = []
        # C-3.5: slash 命令最近使用历史 (MRU, 最近 10 条; 仅会话内存态, 不落盘)
        self._slash_history: List[str] = []
        # C-5.2: 离线检测结果缓存 (footer 高频重绘, 30s 内不重复探测网络)
        self._offline_cache: Optional[bool] = None
        self._offline_ts: float = 0.0

        # 状态
        self._events: List[Any] = []
        # 性能: 历史 screen 缓存。`_scrolled_lines` 每帧都要把 `_events` 全量渲染成
        # 逻辑行并逐行算换行高度 (`_line_heights`), 流式期间每帧全量重算导致卡顿。
        # 只有 `_events` 真的变化 (append/trim) 时才重建缓存, 否则复用。
        self._history_dirty = True
        self._history_screen: Optional[List[List[Tuple[str, str]]]] = None
        self._history_heights: Optional[List[int]] = None
        self._history_width: int = 0
        # 行高缓存: `_line_heights` 按 ``(width, text)`` 缓存每个逻辑行的换行高度,
        # 历史 screen 复用期间每帧只做 dict 查找 (2000+ 行历史原本每帧数万次 C 调用)。
        self._height_cache: Dict[Tuple[int, str], int] = {}
        self._closed = False
        self._busy = False
        self._cancel_requested = threading.Event()
        # 回合开始单调时钟 (codex 状态行 "Working (Ns · esc to interrupt)" 的 elapsed 来源)
        self._turn_started = 0.0
        self._last_streamed_ts = 0.0  # 流式最后更新时间, 驱动 idle 检测

        # 模式: 标准五模式 ID (set_mode 统一解析; standard 别名 → collaboration)
        self._mode = "collaboration"
        self._plan_mode = False
        self._permission_mode = "default"
        self._no_key = False
        self._no_key_env = ""

        # Token / Context
        self._ctx_tokens: Optional[int] = None
        self._ctx_budget: Optional[int] = None
        self._context_pct: float = 0.0
        self._model_label = os.environ.get("TUAN_MODEL_LABEL", "")
        self._tools: List[str] = []

        # 启动引导 (loading) 状态: 旧实现用粒子徽记加载屏 (与 Codex 脱节), 已删除。
        # 现在启动即渲染对话界面 (会话头 + 空输入区, 对齐 codex startup_draft),
        # 内核在后台构建, 就绪后 set_ready 填充会话头。_boot_error 仅在启动失败时
        # 显示简短错误行。同一 Application / 事件循环, 杜绝双屏切换崩溃。
        self._booting = False
        self._boot_progress = 100
        self._boot_status = t("tui.boot_starting")
        self._boot_error: Optional[str] = None
        self._agent: Any = None
        # 首次访问未知目录的信任确认态 (Kimi/Claude Code 风格卡片):
        # 由 prompt_trust() 挂起, _resolve_trust() 消费后经 on_confirm 回调写回
        # workspace_trust.json; 确认前 set_ready 不被调用 (由 cmd_chat._boot 完成)。
        self._trust_pending: Optional[Dict[str, Any]] = None
        self._trust_index: int = 0  # 信任确认 radiolist 高亮项: 0=信任 / 1=不信任
        # 命令执行确认态 (Kimi 风格卡片): 由 confirm() 挂起 —— 工具线程阻塞在
        # threading.Event 上, 卡片渲染在对话区底部, 用户在输入框敲 y/n 后由
        # _resolve_confirm() 唤醒。取代旧的 run_in_terminal(print+input) 方案:
        # 后者把提示打到输入框位置, 长命令直接撑破边框且语义上属于"输入框内容"。
        self._confirm_pending: Optional[Dict[str, Any]] = None
        # 模型向用户提问态 (ask_user 工具): 与 confirm 同构 —— 工具线程阻塞在
        # Event 上, 卡片渲染在对话区底部, 用户 ↑↓ 选高亮 / Enter 确认 (也可直接
        # 敲编号或自由作答) 后由 _resolve_ask() 唤醒。
        # 此前 TUI 未实现该钩子, ask_user 直接 print()+input() 打到 stdout ——
        # 在全屏 TUI 里既冲垮布局 (溢出) 又无法正常输入 (选不了)。
        self._ask_pending: Optional[Dict[str, Any]] = None
        self._ask_index: int = 0       # 选项高亮项 (自由作答时为 -1 之外的语义, 见 _ask_move)
        self._ask_free: bool = False   # 用户是否已进入"自由作答"模式 (输入非编号文本)
        self._frame = 0
        self._moon_frame = 0

        # 流式 / 工具状态
        self._stream_buf = ""
        self._streaming = False
        self._streamed = False
        # 复制文本: 记录最后助手回复全文 / 最后用户输入 (F6 / Ctrl+Shift+C 复制)。
        self._last_assistant_text = ""
        self._last_user_text = ""
        self._toast = ""          # 状态行临时提示 (复制成功等), 2 秒后消失
        self._toast_until = 0.0
        self._running: List[str] = []
        self._tool_start_times: dict = {}
        # 抑制月亮: 流式收尾到回合真正结束之间, 不渲染"刚答完还转月亮"的鬼影。
        # 新一轮输入 / 新工具开始时清零, 保证多step回合里后续思考仍会显示。
        self._moon_suppressed = False

        # 审计面板 (kimi 折叠思考): 收集模型推理 + 重试/工具审计日志
        self._reason_buf: List[str] = []      # 本轮思考分片
        self._reason_full = ""                # 本轮累计思考全文
        self._audit_visible = False           # Ctrl+O 折叠面板开关
        self._audit_log: List[Tuple[str, str]] = []  # (cls, text) 审计行

        # Kimi 移植面板状态 (Ctrl+R 会话选择器 / Ctrl+T 任务浏览器 / F2 MCP):
        # 必须在此初始化, 否则 `_handle_enter`/键位路由在面板未打开时访问
        # `self._sp_panel` 会抛 AttributeError (测试在无 app 下直接调 _handle_enter)。
        self._sp_panel: Optional[Dict[str, Any]] = None    # 会话选择器面板
        self._tb_panel: Optional[Dict[str, Any]] = None    # 任务浏览器面板
        self._mcp_visible = False                          # MCP 状态面板开关
        self._mcp_servers: List[Any] = []                  # MCP 服务器缓存
        # Codex 同款 "?" 快捷键帮助浮层 (bottom_pane/shortcut_overlay.rs):
        # 空输入时按 "?" 打开三栏 Compose/Session/Transcript, "?" / esc 关闭。
        self._help_open = False

        # Diff 实时面板 (对标 Claude Code 的 /diff 并排实时面板): Ctrl+D 开合。
        # 面板在渲染时同步取一次工作区 diff, 但按 _diff_fetched_at 节流 (默认 1.5s),
        # 避免模型连续改文件时每个重绘帧都 fork 一个 git 进程。
        self._diff_visible = False
        self._diff_cache: List[Tuple[str, str]] = []   # 已渲染的 (cls, text) 行
        self._diff_summary = ""                        # 顶部统计行 (N files +A -B)
        self._diff_error = ""                          # 非 git 仓库 / git 缺失等
        self._diff_fetched_at = 0.0
        self._diff_width = 0                           # 0 = 运行时按终端宽度计算

        # 对话区滚动: **虚拟视口** (见 _render_conversation / _scroll_log)。
        # `_follow` 为 True 时视口钉在最新内容底部 (新内容自动跟随); 手动上翻后
        # 为 False, `_view_top` 记录视口顶端对应的终端行号, 新内容不再把视图拽走。
        # (早期实现用 FormattedTextControl.get_cursor_position 伪造"光标行"来驱动
        #  Window 滚动 —— prompt_toolkit 只会**最小幅度**滚动到该点可见, PgUp 根本
        #  翻不动一屏, 且逻辑行/终端行错位后中段内容永远够不到, 故改为真视口切片。)
        self._follow = True
        self._view_top = 0        # 视口顶端对应的终端行号 (整段内容里的偏移)
        # 工具调用折叠 (Claude/TraeWork 风格 "see"): 本轮工具完成记录先折叠成
        # 一行摘要, Ctrl+O 展开查看每步细节 (同时镜像进审计面板)。
        self._turn_tool_lines: List[str] = []
        self._tool_detail = False

        # prompt_toolkit
        self._app: Optional[Any] = None
        # 自定义底栏 (/statusline <命令>): 命令输出缓存与后台刷新线程。
        # 渲染每帧都会调用, 因此绝不能在渲染线程里同步跑子进程。
        self._sl_text = ""
        self._sl_thread: Optional[Any] = None
        self._sl_next = 0.0
        # vi 编辑模式 (/vim): Application.editing_mode 在构造时定型, 这里注册
        # 运行时偏好监听器, 使会话内 /vim on/off 能立即切换键位 (TextArea 的
        # 插入过滤器会让位给 vi 普通模式导航)。
        try:
            from ..ui import prefs as _prefs
            _prefs.add_listener(self._on_vim_mode_changed)
        except Exception as exc:  # noqa: BLE001 - 偏好模块异常时静默保持默认 emacs 键位
            log.warning("StateMixin.__init__(): 非致命异常已忽略(设计内降级, 不改控制流): %s", exc)
            pass
        # 对话区内容由 `_render_conversation` 自行按视口切片 (只返回当前可见的那些
        # 终端行), 因此**不注册** get_cursor_position —— 让它保持默认 Point(0,0):
        # 切片高度恰好等于窗口高度, Window 无需再自行滚动, 二者互不干扰。
        # (早期靠伪造 get_cursor_position 驱动 Window 滚动, 见 _follow 处注释。)
        self._log_control = FormattedTextControl(
            self._render_conversation,
            show_cursor=False,
        )
        self._footer_control = FormattedTextControl(self._render_footer)
        # Codex CLI 风格输入区: 无边框, 左 "›" 前缀 (bold primary, 2 列),
        # 空输入时显示 dim 灰 placeholder "Ask Codex to do anything"。
        # prompt_toolkit 3.0.53 无 placeholder 参数, 用 _PlaceholderProcessor 注入。
        self._input = TextArea(
            prompt=FormattedText([("class:primary", "› ")]),
            multiline=False,
            # 单行输入必须横向滚动: 若 wrap_lines=True 且 height=1, 中文/宽字符贴到
            # 右边界触发裁剪式软换行 → 最后列宽核算错一位, 高亮重绘(思考动画)把错位
            # 残影卷进输入栏, 表现为 IME 打字/粘贴/英文全变乱码。
            wrap_lines=False,
            scrollbar=False,
            height=1,
            history=InMemoryHistory(),
            # 空输入时显示 Codex 同款 placeholder "Ask Codex to do anything"。
            # cast: 无 prompt_toolkit 时 _PlaceholderProcessor 退化为占位类 (见
            # common.py), TextArea 只在有 pt 的路径上真正实例化, 运行期必为 Processor。
            input_processors=[cast("Processor", _PlaceholderProcessor())],
            # "/" 命令面板由 QxtTUI 自绘 (见 _render_slash_menu): 输入 "/" 即弹出,
            # ↑↓ 选择 · Enter/Tab 确认 · Esc 关闭。不走 prompt_toolkit 补全器 ——
            # 其下拉菜单位于输入框下方, 而本布局输入框贴屏幕底部, 菜单会被裁掉。
            completer=None,
            complete_while_typing=False,
        )
        # 输入文本变化 → 命令面板开合/过滤 (Claude Code 同款体验)
        try:
            self._input.buffer.on_text_changed += self._on_input_changed
        except Exception as exc:  # noqa: BLE001 - 测试桩/旧版 pt 无该事件时静默降级
            log.warning("StateMixin.__init__(): 非致命异常已忽略(设计内降级, 不改控制流): %s", exc)
            pass

        # 输入区: Codex 风格无边框 (仅 "› " 前缀 + 底部状态条), 直接占满底部。
        # 移除早期三层 ╭─╮ 细边框 —— Codex 输入区与消息区之间无绘制边框,
        # 仅靠 "›" 前缀与 placeholder 区分, 与开源 codex-rs/tui 视觉一致。
        self._input_frame = self._input

        # 对话区占满剩余空间: 自绘虚拟视口 (自己切片内容 + 自己算滚动), 不用
        # ScrollablePane (后者在 Windows/conpty 下碎滚动) 也不用伪造光标定位。
        # 用 _MeasuredWindow 记录真实高度, 供 _viewport_rows() 精确切片。
        self._log_window = _MeasuredWindow(
            self._log_control,
            wrap_lines=True,
            height=Dimension(min=1, weight=1),
        )
        conversation = self._log_window
        # 审计面板 (kimi 折叠思考): 默认隐藏, Ctrl+O 展开; 展开约占 45% 高度。
        # 复用同一区域显示 Kimi 移植面板 (Ctrl+R 会话 / Ctrl+T 任务 / F2 MCP)。
        self._audit_control = FormattedTextControl(self._render_audit)
        audit_wrap = ConditionalContainer(
            HSplit([
                Window(char="─" * 1, height=1, style="class:border"),
                Window(self._audit_control, wrap_lines=True, height=Dimension(min=3, weight=2)),
            ]),
            filter=Condition(lambda: (
                self._audit_visible
                or bool(getattr(self, "_sp_panel", None))
                or bool(getattr(self, "_tb_panel", None))
                or bool(getattr(self, "_mcp_visible", False))
            )),
        )
        # 就绪前 (booting / 启动失败) 隐藏输入框与底栏: 加载屏只显示盒子+进度条,
        # 避免"输入框空悬 + 底栏信息残缺"的杂乱观感; boot→ready 切换时强制
        # renderer.reset() 全量重绘, 杜绝 prompt_toolkit diff 残影 (旧帧的 boot
        # 状态/旧 footer 叠在新帧上, 观感"字符残留/双行状态栏")。
        _ready = Condition(lambda: not self._booting and not self._boot_error)
        # "/" 命令面板: 输入 "/" 即在输入框上方弹出 (Claude Code 同款位置),
        # 高度随条目数动态伸缩 (callable → prompt_toolkit 布局期求值), 最多 9 行。
        self._slash_control = FormattedTextControl(
            self._render_slash_menu, show_cursor=False, focusable=False,
        )
        slash_menu = ConditionalContainer(
            Window(
                self._slash_control,
                height=self._slash_menu_rows,
                style="class:slashbg",
                wrap_lines=False,
            ),
            filter=Condition(lambda: self._slash_open and bool(self._slash_items)),
        )
        # Codex 同款 "?" 快捷键帮助浮层: 覆盖输入区上方, 三栏 Compose/Session/
        # Transcript + 底部 "/keymap customize" 提示 (对齐 shortcut_overlay.rs)。
        self._help_control = FormattedTextControl(
            self._render_help_overlay, show_cursor=False, focusable=False,
        )
        help_overlay = ConditionalContainer(
            Window(
                self._help_control,
                height=self._help_overlay_rows,
                style="class:slashbg",
                wrap_lines=False,
            ),
            filter=Condition(lambda: self._help_open),
        )
        bottom = ConditionalContainer(
            HSplit([
                help_overlay,
                slash_menu,
                self._input_frame,
                Window(self._footer_control, height=1),
            ]),
            filter=_ready,
        )
        layout = Layout(
            HSplit([
                # 主体 (对话区 + 审计面板) 与右侧 diff 面板并排 (Claude Code /diff 同款)。
                # VSplit 而非手工拼字符: 让 prompt_toolkit 自己分配宽度, 避免在窄终端
                # 下把对话区压成一条缝。
                VSplit([
                    HSplit([
                        conversation,
                        # 审计面板: 仅当展开时占空间
                        audit_wrap,
                    ]),
                    ConditionalContainer(
                        HSplit([
                            Window(width=1, char="│", style="class:border"),
                            Window(
                                FormattedTextControl(
                                    self._render_diff_panel, show_cursor=False,
                                    focusable=False,
                                ),
                                width=lambda: self._diff_panel_width(),
                                wrap_lines=False,
                                style="class:slashbg",
                            ),
                        ]),
                        filter=Condition(
                            lambda: self._diff_visible and self._diff_panel_available()
                        ),
                    ),
                ]),
                bottom,
            ])
        )

        output = None
        try:
            is_test = bool(
                os.environ.get("PYTEST_CURRENT_TEST")
                or os.environ.get("PYTEST_VERSION")
                or os.environ.get("CI")
                or "pytest" in sys.modules
            )
            if is_test or not getattr(sys.stdout, "isatty", lambda: False)():
                output = DummyOutput()
            elif os.name == "nt":
                # Windows 原生体验 (Major #6): 真终端下先启用 VT 处理 + UTF-8 代码页,
                # 否则 prompt_toolkit 的 ANSI 颜色与 CJK 框线被 ConHost 渲染成乱码。
                from .win_compat import enable_virtual_terminal
                enable_virtual_terminal()
        except Exception as exc:
            log.warning("StateMixin.__init__(): 非致命异常已忽略(设计内降级, 不改控制流): %s", exc)
            pass

        # 鼠标滚轮回看历史 (Claude Code 同款)。开启后终端把滚轮上报为转义序列,
        # 代价是**鼠标左键拖选复制被终端截走**(选不中文字)。可用
        # TUAN_NO_MOUSE=1 临时关掉滚轮、恢复文本选择。
        mouse = not _env_flag("TUAN_NO_MOUSE")

        try:
            self._app = Application(
                layout=layout,
                key_bindings=self._build_keys(),
                style=STYLE,
                full_screen=True,
                mouse_support=mouse,
                output=output,
            )
        except Exception as exc:
            if type(exc).__name__ != "NoConsoleScreenBufferError":
                raise
            # DummyOutput 不上报鼠标, 但键位绑定仍保留滚轮处理 ——
            # 部分终端 (conpty 的部分模式) 由应用层注入 MouseEvent。
            self._app = Application(
                layout=layout,
                key_bindings=self._build_keys(),
                style=STYLE,
                full_screen=True,
                mouse_support=mouse,
                output=DummyOutput(),
            )

        # 应用 vi/emacs 编辑模式 (/vim): 布局与键位就绪后按运行时偏好定型。
        self._apply_vim_mode()

    def _request_exit(self, event: Any) -> None:
        """Ctrl-C / Ctrl-Q 退出: 先解冻挂起的确认 (按"拒绝"处理) 再退出应用。

        否则工具线程会一直阻塞在确认 Event 上 —— 线程的等待循环虽有应用退出
        兜底, 但显式解冻能让"用户取消"这一结果被正常回传与记录, 语义更干净。
        """
        self.cancel_confirm()
        self.cancel_ask()
        self._closed = True
        event.app.exit()

    def _push_history(self, text: str) -> None:
        """把输入写入输入框历史, 跳过与上一条完全相同的重复输入。

        配合 ↑/↓ 历史导航: 连发同一条命令/多轮同句式时不刷屏, 回看更干净。
        历史读写失败绝不影响发送主流程。
        """
        try:
            history = self._input.buffer.history
            if history is None:
                return
            try:
                entries = history.get_strings()
                if entries and entries[-1] == text:
                    return
            except Exception as exc:
                log.warning("StateMixin._push_history(): 非致命异常已忽略(设计内降级, 不改控制流): %s", exc)
                pass
            history.append_string(text)
        except Exception as exc:
            log.warning("StateMixin._push_history(): 非致命异常已忽略(设计内降级, 不改控制流): %s", exc)
            pass


    # ============================================================ 启动引导 (加载屏)
    def set_boot_progress(self, pct: int, status: str = "") -> None:
        self._boot_progress = min(100, max(0, int(pct)))
        if status:
            self._boot_status = status
        if self._app and self._app.is_running:
            self._app.invalidate()

    def attach_ui(self) -> None:
        """把 _ui_singleton.ui 替换为 TUI 桥接, 使 slash 命令 / 后台线程
        (如 /web 服务器) 的输出进入本界面, 不再直接打 stdout 挤爆全屏渲染。

        同时把 tuan 根 logger 的终端 handler 替换为 TUI 转发器 (模块级
        _TuiLogHandler): MCP / 内核等模块的 logging 输出不再裸写 stdout
        污染全屏界面, 而是以整齐的错误/警告/普通行进入对话区日志。

        记录原 _ui 供 detach_ui() 恢复 (测试隔离: QxtTUI 构造/就绪会污染
        全局 _ui_singleton._ui, 测试结束后需还原, 否则后续 CLI 测试的
        ui.info 会被导向 TUI 日志区而非 stdout)。
        """
        from ..cli import _ui_singleton
        from ..ui.tui_bridge import TuiUI

        # 仅首次 attach 时记录原值, 多次 attach (set_ready 幂等) 不覆盖已存原值
        if not hasattr(self, "_prev_ui"):
            self._prev_ui = getattr(_ui_singleton, "_ui", None)
        _ui_singleton._ui = TuiUI(self)
        try:
            import logging as _logging

            lg = _logging.getLogger("tuan")
            for h in list(lg.handlers):
                if isinstance(h, _logging.StreamHandler):
                    lg.removeHandler(h)
            # 幂等: 先移除旧转发器再挂新实例, 避免 attach_ui 被多次调用时重复输出
            for h in list(lg.handlers):
                if isinstance(h, _TuiLogHandler):
                    lg.removeHandler(h)
            lg.addHandler(_TuiLogHandler(self))

            # ---- 关键: 模块日志的桥接 ----
            # 各模块用 logging.getLogger(__name__) 取 logger, 名字是
            # "tuan_cli.core.xxx" —— **不是** "tuan" 的子级, 因此只挂 "tuan"
            # 会让全部模块日志绕过桥接、直接写 stdout, 出现在全屏界面下方
            # (观感"报错消息都在输入框里冒出来, 还一次好几条")。
            # 所以转发器要挂到根 logger 与 "tuan_cli" logger 上; 根上只留
            # WARNING+ (避免 httpx/openai 等三方库的 INFO 刷屏),
            # 根上写终端的 StreamHandler 一并移除 (文件 handler 保留)。
            root = _logging.getLogger()
            for h in list(root.handlers):
                if isinstance(h, _TuiLogHandler):
                    root.removeHandler(h)
                elif isinstance(h, _logging.StreamHandler):
                    stream = getattr(h, "stream", None)
                    if stream is getattr(sys, "__stdout__", None) or \
                            stream is getattr(sys, "__stderr__", None):
                        root.removeHandler(h)
            fwd = _TuiLogHandler(self)
            fwd.setLevel(_logging.WARNING)
            root.addHandler(fwd)
            mod_logger = _logging.getLogger("tuan_cli")
            for h in list(mod_logger.handlers):
                if isinstance(h, _TuiLogHandler):
                    mod_logger.removeHandler(h)
            mod_logger.addHandler(_TuiLogHandler(self))
            # 关闭向根传播: 否则 WARNING+ 会同时被 tuan_cli 与 root 两个转发器
            # 各渲染一次 (观感"一次发送好几条相同的报错")。
            mod_logger.propagate = False
        except Exception as exc:  # noqa: BLE001
            log.warning("StateMixin.attach_ui(): 非致命异常已忽略(设计内降级, 不改控制流): %s", exc)
            pass

    def detach_ui(self) -> None:
        """撤销 attach_ui 的全局副作用, 恢复被替换的 _ui_singleton._ui 与 logger。

        测试隔离用: QxtTUI 在测试中构造/就绪会替换全局 _ui_singleton._ui 为
        TuiUI, 若未还原, 后续 CLI 测试的 ``ui.info`` 会被导向 TUI 日志区而非
        stdout (capsys 捕获不到 → out 为空)。detach_ui 把 _ui 恢复为 attach 前的
        原值, 并移除本实例挂载的 _TuiLogHandler, 保证测试互不污染。
        """
        from ..cli import _ui_singleton
        import logging as _logging

        prev = getattr(self, "_prev_ui", None)
        if prev is None:
            _ui_singleton._ui = None
        else:
            _ui_singleton._ui = prev

        # 移除本实例的日志转发器 (根 / tuan / tuan_cli), 恢复原传播设置
        for name in ("", "tuan", "tuan_cli"):
            lg = _logging.getLogger(name)
            for h in list(lg.handlers):
                if isinstance(h, _TuiLogHandler):
                    lg.removeHandler(h)
            if name == "tuan_cli":
                lg.propagate = True


    # ============================================================ Super-Agent 绑定
    def _bind_superagent(self) -> None:
        """把 Super-Agent 引擎挂到主 Agent 并把后台任务事件推入对话区。

        融合点: TUI 就绪时即创建/绑定引擎 (与 /superagent 命令的 _get_engine
        复用同一单例), 让后台自主任务 (Router dispatch / Worker 汇报) 不再
        只显示为底栏徽标, 而是作为日志行进入对话区, 用户可见可追溯。

        引擎 start() 延迟到 /superagent start 或首次 ingest; 但 listener 立即
        注册, 保证事件从第一次起就可见。
        """
        try:
            agent = self._agent
            if agent is None:
                return
            eng = getattr(agent, "_superagent", None)
            if eng is None:
                from ..superagent import SuperAgent, WorkMode
                eng = SuperAgent(home="~/.tuan", agent=agent, work_mode=WorkMode.OBSERVE)
                setattr(agent, "_superagent", eng)

            # 幂等: 避免重复绑定 listener (set_ready 可能被多次调用)。
            if getattr(eng, "_tui_bound", False):
                return
            eng._tui_bound = True  # type: ignore[union-attr]

            def _on_sa_event(name: str, payload: Dict[str, Any]) -> None:
                """Router 事件 → 对话区日志行 (线程安全, 只做 invalidate)。

                OpenCode 风格角色徽章 ``@agent`` 作前缀 (CodeX 主体不变), 让后台
                自主任务在对话区里与用户/助手消息区分开, 可读性更高。
                徽章用独立青绿 ``roleagent`` 着色 (经 ``_append_agent_line``),
                正文沿用语义色 —— 徽章与正文不同色, 一眼可辨。
                """
                try:
                    if name == "dispatch":
                        title = payload.get("title", "")
                        wid = payload.get("worker_id", "")
                        self._append_agent_line(f"后台任务已开单 · {title}",
                                                cls="class:warning")
                    elif name == "ticket_update":
                        report = payload.get("report", {})
                        status = report.get("status", "")
                        progress = report.get("progress", "") or \
                            report.get("result", "") or report.get("error", "")
                        if status == "done":
                            # done = 结果已产出, 工单进入「待审阅」面板; 提示用 /superagent panel 验收
                            self._append_agent_line(
                                f"任务完成·待审阅 · {progress[:500]}",
                                cls="class:primary")
                        elif status == "accepted":
                            # 用户已验收: REVIEW → DONE (工单动作经 /superagent accept)
                            self._append_agent_line(
                                f"已验收 · {progress[:200]}",
                                cls="class:success")
                        elif status == "retrying":
                            self._append_agent_line(
                                f"已重试 · {progress[:200]}",
                                cls="class:warning")
                        elif status == "failed":
                            self._append_agent_line(f"任务失败 · {progress[:500]}",
                                                    cls="class:error")
                        elif status == "needs_input":
                            # 需要人: 面板里最醒目的交互点 —— 用 @agent 徽章 +
                            # 明确行动命令, 让用户一眼看到「现在有什么需要我」。
                            tid = payload.get("ticket_id", "")
                            self._append_agent_line(
                                f"需要你回答 · {progress[:300]}",
                                cls="class:warning")
                            if tid:
                                self._append_agent_line(
                                    f"  回答: /superagent reply {tid} <内容>",
                                    cls="class:textdim")
                        elif progress:
                            self._append_agent_line(f"进展 · {progress[:300]}",
                                                    cls="class:dim")
                except Exception as exc:  # noqa: BLE001 - 事件展示绝不阻断引擎
                    log.warning("StateMixin._bind_superagent(): 非致命异常已忽略(设计内降级, 不改控制流): %s", exc)
                    pass

            eng.router.add_listener(_on_sa_event)

            # 投机执行结果 → 对话区 (OpenCode 风格 @agent 徽章, 只展示有价值/失败)。
            def _on_spec_result(entry: Dict[str, Any]) -> None:
                try:
                    st = entry.get("status", "")
                    title = entry.get("title", "")
                    if st == "done":
                        result = entry.get("result", "") or ""
                        self._append_agent_line(
                            f"投机执行完成 · {title} · {result[:300]}",
                            cls="class:textdim")
                    elif st == "failed":
                        self._append_agent_line(
                            f"投机执行失败 · {title}",
                            cls="class:error")
                except Exception as exc:  # noqa: BLE001
                    log.warning("StateMixin._bind_superagent(): 非致命异常已忽略(设计内降级, 不改控制流): %s", exc)
                    pass

            eng._on_speculate_result = _on_spec_result
        except Exception as exc:  # noqa: BLE001 - Super-Agent 绑定失败不阻断 TUI 启动
            log.warning("StateMixin._bind_superagent(): 非致命异常已忽略(设计内降级, 不改控制流): %s", exc)
            pass

    def set_no_key(self, no_key: bool, env: str = "") -> None:
        """刷新"未配置 API Key"横幅状态 (配置密钥后立即清除, 无需重启会话)。"""
        self._no_key = bool(no_key)
        if env:
            self._no_key_env = env
        if self._app and self._app.is_running:
            self._app.invalidate()

    def set_ready(self, config: Any, agent: Any, workspace: str,
                  tools: Optional[List[str]] = None, no_key: bool = False,
                  no_key_env: str = "", mode: Optional[str] = None) -> None:
        """内核就绪: 从加载屏切换到对话界面。mode=standard/yolo/plan 驱动底部徽标。"""
        self._booting = False
        self._boot_error = None
        self._no_key = bool(no_key)
        self._no_key_env = no_key_env or ""
        self._agent = agent
        if tools:
            self.set_tools(list(tools))
        try:
            agent.ctx.confirm = self.confirm
        except Exception as exc:
            log.warning("StateMixin.set_ready(): 非致命异常已忽略(设计内降级, 不改控制流): %s", exc)
            pass
        if mode:
            # 显式传入的运行模式优先 (standard / yolo / plan)
            self.set_mode(mode)
        else:
            self.set_plan_mode(getattr(agent, "plan_mode", False))
        prov = config.get("model.provider", "") or ""
        mdl = config.get("model.model", "") or ""
        self._model_label = f"{prov}/{mdl}"
        # 初始化真实上下文占用条: 预算取模型真实上下文窗口 (fallback 到配置)
        self._ctx_budget = self._model_context_window(prov, mdl)
        self.set_context_info(0, self._ctx_budget)
        self._show_welcome()
        hint = t("tui.readonly_hint")
        if no_key:
            hint += " " + t("tui.no_key_hint")
        # 接线: 把 _ui_singleton.ui 替换为 TUI 桥接, 使 slash 命令 / 后台线程
        # 的输出进入渲染层 (append_log), 不再直接打 stdout 挤爆全屏界面。
        self.attach_ui()
        # Super-Agent 引擎绑定: 让 TUI 与 /superagent 命令复用同一引擎,
        # 并把 Router 的后台任务事件推入对话区 (而不仅是底栏徽标)。
        self._bind_superagent()
        # 只读提示作为普通日志行展示 (紧凑布局, 不单独占 hint 行)
        self.append_log(hint, cls="class:textdim")
        # 滚动键提示: 让用户知道可以回看历史 (否则长会话"无法回溯"的反馈会归因于产品)
        try:
            self.append_log(t("tui.scroll_hint"), cls="class:textdim")
        except Exception as exc:  # noqa: BLE001
            log.warning("StateMixin.set_ready(): 非致命异常已忽略(设计内降级, 不改控制流): %s", exc)
            pass
        self._reset_renderer()
        if self._app and self._app.is_running:
            self._app.invalidate()

    def _reset_renderer(self) -> None:
        """全量重绘: boot→ready / boot→error / trust→ready 切换时清掉上一帧。

        **必须先 erase() 再 reset()**: 只调 `reset()` 会丢弃 `_last_screen` 却
        **不擦掉屏幕上已有的内容**, 下一次渲染就把新帧直接画在旧帧下面 ——
        观感正是底栏/状态行"堆叠成两份"。`erase()` 会把光标移回起点并向下擦除,
        之后 `reset()` 才能从干净画布重绘。

        **两次调用都必须显式传 `leave_alternate_screen=False`** (修"输入框失去渲染"):
        `Renderer.reset()` 的默认值是 `leave_alternate_screen=True` —— 一旦漏传,
        它会执行 `output.quit_alternate_screen()` 把这个**全屏 TUI 踢出备用屏缓冲**,
        终端随即回退到进入 TUI 之前的主屏内容, 而 TUI 仍以为自己全屏绘制,
        于是输入框 (以及整幅界面) "失去渲染" —— 在 Windows conpty / Windows
        Terminal 上尤其明显。`erase()` 内部虽已用 `leave_alternate_screen=False`
        调过一次 `reset()`, 但紧跟着的裸 `reset()` 会用默认值再退出一次备用屏,
        这正是此前"输入框渲染丢失"的真凶。

        **线程安全** (同源问题): `set_ready`/`boot_error` 由 `_boot` **后台线程**
        调用 (见 cmd_chat), 而渲染循环跑在主线程。直接在后台线程操作 renderer
        会与主线程渲染竞争光标位置 / 输出写入, 造成同样的画面错乱。故把重置
        **投递到主事件循环** (`call_soon_threadsafe`) 执行; 应用尚未进入运行态
        (无 loop) 时退化为同步调用。
        """
        app = self._app
        if app is None:
            return

        def _do_reset() -> None:
            try:
                r = getattr(app, "renderer", None)
                if r is None:
                    return
                try:
                    r.erase(leave_alternate_screen=False)
                except Exception as exc:
                    log.warning("StateMixin._do_reset(): 非致命异常已忽略(设计内降级, 不改控制流): %s", exc)
                    pass
                if hasattr(r, "reset"):
                    try:
                        # 关键: 显式留在备用屏内, 避免 quit_alternate_screen()
                        r.reset(leave_alternate_screen=False)
                    except TypeError:  # 老版 pt 无该关键字
                        r.reset()
            except Exception as exc:
                log.warning("StateMixin._do_reset(): 非致命异常已忽略(设计内降级, 不改控制流): %s", exc)
                pass

        try:
            loop = getattr(app, "loop", None)
            if loop is not None and getattr(app, "is_running", False):
                loop.call_soon_threadsafe(_do_reset)
                return
        except Exception as exc:
            log.warning("StateMixin._reset_renderer(): 非致命异常已忽略(设计内降级, 不改控制流): %s", exc)
            pass
        _do_reset()

    def boot_error(self, message: str) -> None:
        """内核构建失败: 显示错误态 (不再静默闪退), 用户可读后 Ctrl-Q 退出。"""
        self._boot_error = str(message)
        self._booting = False
        self.append_log(f"{t('tui.boot_error_title')} {message}")
        self.append_log(t("tui.boot_error_hint"))
        self._reset_renderer()
        if self._app and self._app.is_running:
            self._app.invalidate()


    # ============================================================ 流式 / 工具
    def _throttled_invalidate(self, min_interval: float = 0.033) -> None:
        """限频刷新: 高频事件 (流式/审计) 每帧至多刷新一次 (~30fps), 减少闪烁与 CPU。

        低频事件 (begin_tool/end_tool) 仍即时刷新; 末态由 end_stream/submit finally
        兜底刷新, 不会因限频漏画最终画面。
        """
        if not (self._app and self._app.is_running):
            return
        now = time.monotonic()
        if now - getattr(self, "_last_invalidate", 0.0) >= min_interval:
            self._last_invalidate = now
            self._app.invalidate()

    def stream_assistant(self, delta: str) -> None:
        if not delta:
            return
        self._streaming = True
        self._streamed = True
        self._stream_buf += delta
        # 缓冲有界: 模型吐超长回复时把前段固化为日志, 避免内存/渲染无限膨胀
        if len(self._stream_buf) > _MAX_STREAM_BUF:
            head, self._stream_buf = self._stream_buf[:_MAX_STREAM_BUF], self._stream_buf[_MAX_STREAM_BUF:]
            self._events.append(f"{STATUS_BULLET}{head.lstrip(chr(10))}…[流式超长, 已分段]")
            self._history_dirty = True
            if len(self._events) > 5000:
                del self._events[: len(self._events) - 4000]
        # slogans: 流式开始/分片 -> 节流推进阶段与活性 (B3 XVI 接线)
        self._slogan_stream_started()
        self._throttled_invalidate()

    def stream_reason(self, delta: str) -> None:
        """接收模型推理分片, 累积成思考全文, 写入审计面板 (全文有界, 超长截断)。"""
        if not delta:
            return
        self._reason_buf.append(delta)
        self._reason_full += delta
        if len(self._reason_full) > _MAX_REASON_LEN:
            self._reason_full = self._reason_full[:_MAX_REASON_LEN] + "…[思考超长, 已截断]"
        self._throttled_invalidate()

    def audit(self, cls: str, text: str) -> None:
        """向审计面板追加一行日志 (类标志: textdim/accent/warning 等, 单条截断)。"""
        text = str(text)
        if len(text) > _MAX_LOG_LEN:
            text = text[:_MAX_LOG_LEN] + f"…[已截断 {len(text) - _MAX_LOG_LEN} 字符]"
        self._audit_log.append((cls, text))
        if len(self._audit_log) > 500:
            self._audit_log = self._audit_log[-500:]
        self._throttled_invalidate()

    def end_stream(self) -> None:
        if self._stream_buf:
            # 模型输出常以空行开头, 去掉前导换行, 否则 ● 指示符会单独成行、
            # 正文缩进到下一行 (消息头与正文不在同一行的 bug)。
            buf = self._stream_buf.lstrip("\n")
            if buf:
                self.append_log(f"{STATUS_BULLET}{buf}", max_len=_MAX_LOG_LEN * 4)
                self._last_assistant_text = buf  # 供 F6 / Ctrl+Shift+C 复制全文
            self._stream_buf = ""
        # 本轮思考收尾进审计面板: 折叠后首行是标题, 展开看全文
        if self._reason_full:
            self._audit_log.append(("class:primary", "▸ 思考 (本轮)"))
            self._audit_log.append(("class:textdim", self._reason_full))
            self._reason_buf = []
            self._reason_full = ""
        # slogans: 流式收尾 -> 活性证据 kind=stream_end, 阶段保持 streaming
        # (B3 XVI 接线)
        self._slogan_stream_ended()
        self._streaming = False
        # 流式收尾: 到回合结束前抑制月亮, 避免与刚落库的回复同屏出现鬼影。
        # 若回合不结束, 由随后 begin_tool 重启指示。
        self._moon_suppressed = True
        # 收尾刷新交给 _run_submit 的 finally (彼时 _busy 已清)。
        if not self._busy and self._app and self._app.is_running:
            self._app.invalidate()

    def begin_tool(self, name: str) -> None:
        self._running.append(name)
        self._busy = True
        self._moon_suppressed = False  # 新工具开始: 后续思考重新亮出指示
        self._tool_start_times[name] = time.monotonic()
        # slogans: 工具开始 -> 阶段切到 running_tool (B3 XVI 接线)
        self._slogan_tool_started(name)
        if self._app and self._app.is_running:
            self._app.invalidate()

    def end_tool(self, name: str, ok: bool = True) -> None:
        if name in self._running:
            self._running.remove(name)
        mark = SUCCESS_MARK if ok else FAILURE_MARK
        elapsed = self._tool_start_times.pop(name, None)
        elapsed_str = f" ({elapsed:.1f}s)" if elapsed is not None else ""
        label = t("tui.tool_done") if ok else t("tui.tool_failed")
        line = f"{mark}{name} {label}{elapsed_str}"
        # 工具完成记录进折叠缓冲 (see N tool calls), 并镜像进审计面板供 Ctrl+O 展开。
        self._turn_tool_lines.append(line)
        self._audit_log.append(("class:success" if ok else "class:error", line))
        if len(self._audit_log) > 500:
            self._audit_log = self._audit_log[-500:]
        # slogans: 工具结束 -> 活性证据 kind=tool_end (B3 XVI 接线)
        self._slogan_tool_ended()
        # _busy 由回合生命周期 (submit 开始置 True、finally 清) 统一掌管, 不在
        # 工具中途置 False, 否则多步回合会反复"掉指示/复现"造成月亮闪烁。
        if self._app and self._app.is_running:
            self._app.invalidate()

    def end_any_tool(self) -> None:
        if self._running:
            self.end_tool(self._running[0], ok=False)

    def set_model(self, label: str) -> None:
        self._model_label = str(label or "")
        if self._app and self._app.is_running:
            self._app.invalidate()

    def set_tools(self, tools: List[str]) -> None:
        self._tools = list(tools or [])

    def set_mode(self, mode: str) -> None:
        """设置运行模式, 底部状态栏徽标随之更新。

        接受旧三档别名 (standard / yolo / plan) 与五模式 ID (gantong / lingma /
        chat / boundless / collaboration), 统一经 modes.registry.resolve_mode_id
        解析为标准五模式 ID 后存 ``self._mode``。展示名 (徽标文本) 用中文名,
        徽标颜色按等级映射 (见 ``_mode_badge_style``)。

        兼容: plan 别名解析为 chat, 同时保持 ``_plan_mode`` 语义 (plan 是只读
        规划态, 独立于五模式, 徽标仍以 plan 呈现)。
        """
        raw = (mode or "standard").strip().lower()
        # plan 是只读规划态, 保留为独立徽标 (不并入五模式 ID)
        if raw == "plan":
            self._plan_mode = True
            self._mode = "plan"
        elif raw == "auto":
            # auto 是内部标记 (Claude Code Auto Mode), 按 standard 呈现, 不改变五模式。
            self._plan_mode = False
            self._mode = "standard"
        else:
            self._plan_mode = False
            try:
                from ..modes.registry import resolve_mode_id
                self._mode = resolve_mode_id(raw)   # 标准五模式 ID
            except Exception:
                # 未知/未初始化 (modes 不可用): 保守回退为 standard, 绝不抛给渲染帧。
                self._mode = "standard"
        if self._app and self._app.is_running:
            self._app.invalidate()

    def set_plan_mode(self, enabled: bool) -> None:
        self._plan_mode = bool(enabled)
        if enabled:
            self._mode = "plan"
        elif self._mode == "plan":
            self._mode = "standard"

    def set_context_info(self, estimated: int, budget: int) -> None:
        self._ctx_tokens = int(estimated)
        self._ctx_budget = int(budget) if budget else 0
        bud = self._ctx_budget
        # 关键: budget 为 0/未知时回落到 0%, 不得算出 300000% 之类荒谬值
        self._context_pct = (
            min(100.0, self._ctx_tokens / bud * 100.0) if bud is not None and bud > 0 else 0.0
        )
        if self._app and self._app.is_running:
            self._app.invalidate()

    def set_context_used(self, estimated: int) -> None:
        """刷新上下文已用 token, 保持分母 (模型上下文窗口) 不变。

        只在回合结束后更新已用量, 不改 budget, 从而避免分母在"模型窗口/配置预算"
        之间来回切换造成的百分比跳变 (此前肉眼观感随机)。
        """
        self._ctx_tokens = max(0, int(estimated))
        bud = self._ctx_budget
        self._context_pct = (
            min(100.0, self._ctx_tokens / bud * 100.0) if bud is not None and bud > 0 else 0.0
        )
        if self._app and self._app.is_running:
            self._app.invalidate()


    # 供应商级默认上下文窗口表已上移到 core.prompt_tier.PROVIDER_CONTEXT_WINDOWS
    # (单一真相源: 同一份规则同时驱动底栏分母与提示词分层定档)。本类不再维护副本,
    # 避免两处数字漂移。
    _PROVIDER_CONTEXT: Dict[str, int] = PROVIDER_CONTEXT_WINDOWS

    def _model_context_window(self, provider: str, model: str) -> int:
        """推断当前模型真实上下文窗口 (token), 驱动底栏 context 分母。

        尺寸后缀 / 长上下文家族的识别**委托给 core.prompt_tier.infer_context_window**
        (单一真相源), 本方法只在其之上叠加用户显式配置 ``model.context_window``
        (网关有自定义限额时以配置为准)。纯展示用途, 别拿它当硬性预算。
        """
        from ..core.prompt_tier import infer_context_window

        try:
            _app = self._app
            configured = _app.state.config.get("model.context_window") \
                if _app is not None else None
        except Exception:  # noqa: BLE001
            configured = None
        return infer_context_window(model=model, provider=provider, configured=configured)

    def _elapsed_since_turn(self) -> str:
        """codex `fmt_elapsed_compact` 同款: <60s→"{s}s", <3600→"{m}m {ss:02}s", 否则 "{h}h {mm:02}m {ss:02}s"."""
        if not self._turn_started:
            return "0s"
        s = max(0, int(time.monotonic() - self._turn_started))
        if s < 60:
            return f"{s}s"
        if s < 3600:
            return f"{s // 60}m {s % 60:02d}s"
        return f"{s // 3600}h {(s % 3600) // 60:02d}m {s % 60:02d}s"

    def append_log(self, text: str, cls: Optional[str] = None,
                   max_len: int = _MAX_LOG_LEN) -> None:
        """追加一条事件日志 (超长自动截断, 防巨文本挤爆渲染)。

        max_len=0 表示不截断; 默认 2000 字符, 超出后截断并标注省略字数。
        """
        text = str(text)
        if max_len and len(text) > max_len:
            text = text[:max_len] + f"…[已截断 {len(text) - max_len} 字符]"
        if cls:
            self._events.append((cls, text))
        else:
            self._events.append(text)
        self._history_dirty = True
        # 修剪: 超过 600 条才裁到 500 (避免每次 append 都做 O(n) 切片)
        if len(self._events) > 5000:
            del self._events[: len(self._events) - 4000]
        if self._app and self._app.is_running:
            self._app.invalidate()

    def _append_agent_line(self, text: str, cls: str = "class:textdim",
                           max_len: int = _MAX_LOG_LEN) -> None:
        """追加一条后台自主任务日志行: ``@agent`` 徽章用独立青绿 (roleagent)。

        OpenCode 风格角色徽章: 把 ``@agent`` 前缀与正文拆成两个 fragment, 徽章用
        青绿 ``roleagent`` 着色、正文沿用语义色 ``cls``。这样后台任务在对话区里
        一眼可辨 (青绿徽章 + 语义正文), 与用户蓝 / 助手灰消息真正区分开。
        """
        text = str(text)
        if max_len and len(text) > max_len:
            text = text[:max_len] + f"…[已截断 {len(text) - max_len} 字符]"
        # fragment 行: [徽章(roleagent), 正文(cls)] —— _build_history_screen 对
        # list 类型直接 append, 不做整行配色, 因此徽章/正文可各用各的颜色。
        self._events.append([
            ("class:roleagent", " @agent "),
            (cls, text),
        ])
        self._history_dirty = True
        if len(self._events) > 5000:
            del self._events[: len(self._events) - 4000]
        if self._app and self._app.is_running:
            self._app.invalidate()

    def append_usage_panel(self, usage: dict) -> None:
        """Kimi 风格用量配额面板 (F2 同款面板路由, 供 /usage 与 TuiUI.usage)。

        把本地会话 token 计数 + TUI 上下文状态映射成 Kimi usage.py 的配额条面板,
        渲染为 (cls, text) 行列表追加进 _events (复用 _colored_lines 的配色通道),
        并强制回到底部让面板可见。
        """
        try:
            from ..tui.kimi_modules import (
                build_usage_rows, render_usage_panel,
            )
            pt = int(usage.get("prompt_tokens", 0) or 0)
            ct = int(usage.get("completion_tokens", 0) or 0)
            budget = int(getattr(self, "_ctx_budget", 0) or 0)
            ctx_used = int(getattr(self, "_ctx_tokens", 0) or 0)
            rows = build_usage_rows(pt, ct, budget, ctx_used)
            panel = render_usage_panel(rows)
            # 把 rich Panel 渲染成纯文本行 (去 ANSI), 走 _colored_lines 配色。
            from rich.console import Console
            from io import StringIO
            buf = StringIO()
            Console(file=buf, force_terminal=False, color_system=None,
                    width=max(60, self._app.output.get_size().columns
                              if self._app else 80)).print(panel)
            text = buf.getvalue().rstrip("\n")
            self._events.append(("class:textdim", text))
            self._history_dirty = True
            self._follow = True
            if self._app and self._app.is_running:
                self._app.invalidate()
        except Exception:  # noqa: BLE001 - 面板失败绝不影响 Agent 循环
            self.append_log(
                f"  tokens: prompt {usage.get('prompt_tokens', 0)} "
                f"/ completion {usage.get('completion_tokens', 0)}",
                cls="class:textdim")

    def confirm(self, prompt: str, *, expected: Optional[str] = None,
                position: Optional[int] = None) -> bool:
        """安全确认: 卡片渲染在对话区, 输入框只收 y/n (Kimi 风格)。

        旧实现是 ``app.run_in_terminal(lambda: input(...))`` —— 它会把提示直接
        print 到当前光标位置 (也就是输入框那一行), 长命令于是撑破输入框边框,
        观感上"确认框长在输入框里", 语义上也把确认混成了输入内容。

        现改为挂起式卡片: 工具线程阻塞在 threading.Event 上, 主线程继续渲染
        对话区 (底部追加确认卡片), 用户在输入框敲 y/n 后由 _resolve_confirm()
        写回结果并唤醒工具线程。
        """
        from tuan_cli.core.whitelist import interactive_confirm

        app = self._app
        running = app is not None and getattr(app, "is_running", False)
        if not running:
            # headless / 应用未启动: 没有 UI 可挂卡片, 退回终端 input (保持旧行为)
            return interactive_confirm(prompt, expected=expected, position=position)
        assert app is not None  # running 为真即 app 非空

        done = threading.Event()
        pending: Dict[str, Any] = {
            "prompt": prompt,
            "expected": expected,
            "position": position,
            "event": done,
            "result": False,
        }
        self._confirm_pending = pending
        self._follow = True          # 确认卡片必须可见: 强制回到底部
        # 刻意不碰 _busy: 确认发生在工具执行过程中 (此时 _busy 已为 True), 若在
        # 这里置 True 再于返回前置 False, 会把"工具仍在运行"误清成"已就绪",
        # 顶部状态提前显示就绪勾。输入框已由 _handle_enter 的 confirm_pending
        # 分支独占为答复通道, 不需要借 _busy 拦截新提交。
        try:
            app.invalidate()
        except Exception as exc:  # noqa: BLE001
            log.warning("StateMixin.confirm(): 非致命异常已忽略(设计内降级, 不改控制流): %s", exc)
            pass

        # 阻塞等待用户应答。带 0.5s 心跳轮询是防死锁兜底: 若卡片被取消或应用
        # 已退出 (用户 Ctrl-Q), 不能让工具线程永远挂在这里。
        while not done.wait(timeout=0.5):
            if self._confirm_pending is not pending:
                break                       # 已被 _resolve_confirm 消费/替换
            if not getattr(app, "is_running", True):
                pending["result"] = False   # 应用退出 → 保守视为拒绝
                break
        return bool(pending.get("result", False))

    def _resolve_confirm(self, text: str) -> None:
        """解析命令确认输入并唤醒等待中的工具线程。

        - 无确认码时: y/yes/是 → 执行; n/no/否 → 取消;
        - 有确认码 (expected) 时: 必须精确键入该码才授权 (防误触放行高危命令)。
        """
        pending = self._confirm_pending
        if not pending:
            return
        raw = text.strip()
        choice = raw.lower()
        expected = pending.get("expected")
        if expected is not None:
            # 确认码模式: 必须精确键入, 否则一律视为拒绝 (不允许用 y 绕过)
            if raw.upper() == str(expected).upper():
                pending["result"] = True
                self.append_log(f"{SUCCESS_MARK} {t('tui.confirm_ok')}", cls="class:success")
            elif choice in ("n", "no", "2", "否", "取消", "cancel"):
                pending["result"] = False
                self.append_log(f"{FAILURE_MARK} {t('tui.confirm_no')}", cls="class:warning")
            else:
                self.append_log(t("tui.confirm_invalid_code", code=expected), cls="class:textdim")
                return
        elif choice in ("y", "yes", "1", "是", "执行", "ok"):
            pending["result"] = True
            self.append_log(f"{SUCCESS_MARK} {t('tui.confirm_ok')}", cls="class:success")
        elif choice in ("n", "no", "2", "否", "取消", "cancel"):
            pending["result"] = False
            self.append_log(f"{FAILURE_MARK} {t('tui.confirm_no')}", cls="class:warning")
        else:
            self.append_log(t("tui.confirm_invalid"), cls="class:textdim")
            return

        self._confirm_pending = None
        ev = pending.get("event")
        if ev is not None:
            ev.set()

    def cancel_confirm(self) -> None:
        """取消挂起中的确认 (退出/Ctrl-C 兜底), 一律按"拒绝"解冻工具线程。"""
        pending = self._confirm_pending
        if not pending:
            return
        self._confirm_pending = None
        pending["result"] = False
        ev = pending.get("event")
        if ev is not None:
            ev.set()


    # ============================================================ 模型提问 (ask_user)
    def ask_user(self, question: str, options: Optional[List[str]] = None) -> str:
        """模型提问 (ask_user 工具入口): 渲染可选择卡片, 阻塞到用户作答。

        供 `TuiUI.ask_user` 调用。取代工具里的 `print()+input()` —— 在全屏 TUI
        下那会把文本直接写进 prompt_toolkit 掌管的屏幕, 布局被冲垮 (用户报告的
        "溢出"), 且 `input()` 在备用屏/ raw 模式下拿不到按键 ("选不了")。

        交互: ↑↓ 移动高亮, Enter 确认; 也可直接敲编号 (1..N) 或任意文字
        (自由作答)。options 为空时退化为纯自由作答。
        """
        q = str(question or "").strip()
        opts = [str(o).strip() for o in (options or []) if str(o).strip()]

        app = self._app
        running = app is not None and getattr(app, "is_running", False)
        if not running:
            # headless / 应用未启动: 没有界面可挂卡片, 退回纯文本询问
            return _ask_user_plain(q, opts)
        assert app is not None  # running 为真即 app 非空

        done = threading.Event()
        pending: Dict[str, Any] = {
            "question": q,
            "options": opts,
            "event": done,
            "result": None,     # None = 未作答 (被取消)
        }
        self._ask_pending = pending
        self._ask_index = 0
        self._ask_free = False
        self._follow = True      # 提问卡片必须可见: 强制回到底部
        try:
            app.invalidate()
        except Exception as exc:  # noqa: BLE001
            log.warning("StateMixin.ask_user(): 非致命异常已忽略(设计内降级, 不改控制流): %s", exc)
            pass

        # 阻塞等待。0.5s 心跳轮询防死锁: 卡片被取消或应用退出时不能永远挂着。
        while not done.wait(timeout=0.5):
            if self._ask_pending is not pending:
                break
            if not getattr(app, "is_running", True):
                pending["result"] = None
                break
        return str(pending.get("result") or "")

    def _resolve_ask(self, text: str) -> None:
        """提交提问答案并唤醒等待中的工具线程。

        - 纯 ↑↓+Enter (输入框为空) → 取当前高亮项;
        - 敲了编号 (1..N) → 取对应项;
        - 其它任意文本 → 自由作答。
        """
        pending = self._ask_pending
        if not pending:
            return
        opts: List[str] = pending.get("options") or []
        raw = (text or "").strip()
        if not raw:
            # 空回车 = 确认当前高亮项 (无选项则视为跳过)
            ans = opts[self._ask_index] if opts else ""
        elif raw.isdigit() and opts and 1 <= int(raw) <= len(opts):
            ans = opts[int(raw) - 1]
        else:
            ans = raw
        pending["result"] = ans
        self._ask_pending = None
        self._ask_free = False
        try:
            self.append_log(f"{SUCCESS_MARK} {t('tui.ask_answer', answer=ans or t('tui.ask_skipped'))}",
                            cls="class:success")
        except Exception as exc:  # noqa: BLE001
            log.warning("StateMixin._resolve_ask(): 非致命异常已忽略(设计内降级, 不改控制流): %s", exc)
            pass
        ev = pending.get("event")
        if ev is not None:
            ev.set()

    def cancel_ask(self) -> None:
        """取消挂起中的提问 (退出/Ctrl-C 兜底), 按"未作答"解冻工具线程。"""
        pending = self._ask_pending
        if not pending:
            return
        self._ask_pending = None
        pending["result"] = None
        ev = pending.get("event")
        if ev is not None:
            ev.set()


    # ============================================================ 运行
    def _run_submit(self, text: str) -> None:
        try:
            result = self.on_submit(text)
            self.end_stream()
            if result and not self._streamed:
                self.append_log(result)
        except Exception as exc:
            self.append_log(f"[错误] {type(exc).__name__}: {exc}")
        finally:
            self._busy = False
            self._streamed = False
            self._streaming = False
            self._moon_suppressed = False
            self._running.clear()
            # slogans: 回合完成 -> 活性证据 kind=turn_completed (B3 XVI 接线)
            self._slogan_turn_completed()
            # codex `FinalMessageSeparator`: 回合结束注入完成分隔线
            # `  Worked for Xs · HH:MM` (缩进 2 空格, dim), 紧贴助手回复下方。
            footer = self._completion_footer_text()
            if footer:
                self._events.append(("class:textdim", "  " + footer))
                self._history_dirty = True
        if self._app and self._app.is_running:
            self._app.invalidate()

    def run(self) -> None:
        """启动 TUI: 默认处于加载态, 内核就绪后由 set_ready 切换。

        单一 Application / 事件循环: 不再有独立 Splash 全屏 App,
        因此不存在双屏 alt-screen 切换在 Windows Terminal(conpty) 下的崩溃。

        启动即把终端窗口/标签标题改为 "Tuan-CLI" (OSC 转义 + ConHost API
        双通道, 见 win_compat.set_terminal_title); 非 TTY / 失败静默跳过。

        若全屏模式在特殊终端下仍崩溃, 自动以内联模式 (full_screen=False,
        不抢占整屏/不走 alt-screen) 重试一次; 仍失败则抛给调用方回退 REPL。
        """
        # 窗口标题: "Windows powershell" 标签 → "Tuan-CLI" (启动即改, 退出不还原
        # —— 终端标题无标准查询接口, 竞品 TUI 同样留标题)。
        try:
            from .win_compat import set_terminal_title
            set_terminal_title(TERMINAL_TITLE)
        except Exception as exc:  # noqa: BLE001 - 标题设置绝不阻断启动
            log.warning("StateMixin.run(): 非致命异常已忽略(设计内降级, 不改控制流): %s", exc)
            pass
        animator = threading.Thread(target=self._animate, name="tuan-anim", daemon=True)
        animator.start()
        try:
            if self._app is not None:
                self._app.run()
        except BaseException:
            import traceback as _rt
            _rt.print_exc()
            # 全屏 alt-screen 在某些 conpty 配置下会崩溃 -> 退回内联模式重试
            if self._app is not None:
                try:
                    from prompt_toolkit import Application
                    self._app = Application(
                        layout=self._app.layout,
                        key_bindings=self._app.key_bindings,
                        style=STYLE,
                        full_screen=False,
                        # 内联模式是崩溃兜底路径, 鼠标上报在这里最可能加剧
                        # 不稳定 —— 保守关掉, 滚轮不可用但键盘 PgUp/PgDn 照常。
                        mouse_support=False,
                    )
                    self._app.run()
                    return
                except BaseException:
                    _rt.print_exc()
            raise
        finally:
            self._closed = True

    def _git_branch(self) -> str:
        """探测当前 git 分支 (带缓存, 避免每行渲染都调 git)。"""
        if not hasattr(self, "_git_branch_cache"):
            self._git_branch_cache = None
            self._git_branch_ts = 0.0
        now = time.monotonic()
        if now - self._git_branch_ts < 5.0 and self._git_branch_cache is not None:
            return self._git_branch_cache or ""
        try:
            import subprocess
            r = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=self.workspace, capture_output=True, text=True, timeout=1
            )
            if r.returncode == 0 and r.stdout.strip():
                branch = r.stdout.strip()
                # 探测是否有未提交改动
                r2 = subprocess.run(
                    ["git", "status", "--porcelain"],
                    cwd=self.workspace, capture_output=True, text=True, timeout=1
                )
                dirty = " [±]" if r2.stdout.strip() else ""
                self._git_branch_cache = branch + dirty
            else:
                self._git_branch_cache = ""
        except Exception:
            self._git_branch_cache = ""
        self._git_branch_ts = now
        return self._git_branch_cache or ""


    # ============================================================ 信任确认对话框
    # 首次访问未知目录时由 cmd_chat._boot 调用 prompt_trust(): 挂起确认卡片并
    # 等待用户输入 y/n, 结果经 on_confirm 回调写回 workspace_trust.json 后才 set_ready。
    # 此方法曾在一次 TUI 重写中被误删, 导致 cmd_chat 的 hasattr(tui, "prompt_trust")
    # 恒为 False、确认对话框"又没了" —— 现恢复并加回归测试 (tests/test_tui_fixes.py)。
    def _resolve_trust(self, text: str) -> bool:
        """解析信任确认输入: y/Y/yes → 信任 (trusted); n/N/no → 只读 (untrusted)。

        返回是否**消费**了这次输入 (True = 已按 y/n 处理; False = 不是 y/n,
        由调用方决定后续, 例如把这句当正常消息继续)。
        """
        pending = self._trust_pending or {}
        cb = pending.get("on_confirm")
        choice = text.strip().lower()
        if choice in ("y", "yes", "1", "是", "信任", "trust"):
            trusted = True
            self.append_log(f"{SUCCESS_MARK} {t('tui.trust_ok')} {pending.get('workspace', '')}",
                            cls="class:success")
        elif choice in ("n", "no", "2", "否", "只读", "readonly"):
            trusted = False
            self.append_log(f"{FAILURE_MARK} {t('tui.trust_no')} {pending.get('workspace', '')}",
                            cls="class:warning")
        else:
            return False
        self._trust_pending = None
        if callable(cb):
            try:
                cb(trusted)
            except Exception as exc:  # noqa: BLE001
                self.append_log(f"[信任确认回调] {type(exc).__name__}: {exc}", cls="class:error")
        return True

    def prompt_trust(self, workspace: str, project_name: str = "",
                     on_confirm: Optional[Callable[[bool], None]] = None) -> None:
        """首次访问未知目录: 显示 Kimi/Claude Code 风格信任确认卡片, 等待用户输入 y/n。

        确认后通过 on_confirm(trusted) 回调写回 workspace_trust.json 并继续就绪流程;
        在此之前 set_ready 不会被调用 (由 cmd_chat._boot 在回调里完成)。
        """
        self._trust_pending = {
            "workspace": workspace,
            "project_name": project_name,
            "on_confirm": on_confirm,
        }
        self._trust_index = 0  # 重置高亮到默认项 (信任)
        self._booting = False       # 退出加载态, 显示确认卡片 + 输入框
        self._boot_error = None
        if self._app and self._app.is_running:
            self._app.invalidate()

