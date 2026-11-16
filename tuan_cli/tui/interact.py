"""交互域: 键位绑定、剪贴板、Enter 提交、鼠标滚轮、确认/询问按键侧。

本模块由 tui.py 的 QxtTUI 拆分而来, 方法体逐行原样迁移 (无逻辑改动)。
模块级常量/工具/小类集中在 `tuan_cli.tui.common`, 由 `from .common import *`
注入到本模块命名空间, 因此方法体内对模块级名字的引用保持不变。
"""

from __future__ import annotations

from .common import *  # noqa: F401,F403

import logging
log = logging.getLogger(__name__)



class InteractMixin:
    """交互域: 键位绑定、剪贴板、Enter 提交、鼠标滚轮、确认/询问按键侧。"""

    # ---- 跨 mixin 共享实例属性/方法 (纯声明, 运行期不赋值) ----
    _MOUSE_WHEEL_LINES: Any
    _accept_slash: Callable[..., Any]
    _ask_free: bool
    _ask_index: Any
    _ask_pending: Any
    _boot_error: Any
    _booting: Any
    _busy: Any
    _cancel_requested: Any
    _close_session_picker: Callable[..., Any]
    _close_slash_menu: Callable[..., Any]
    _close_task_browser: Callable[..., Any]
    _commands: Any
    _confirm_pending: Any
    _follow: Any
    _help_open: Any
    _input: Any
    _last_assistant_text: Any
    _last_user_text: Any
    _mcp_visible: Any
    _moon_suppressed: Any
    _on_input_changed: Callable[..., Any]
    _open_session_picker: Callable[..., Any]
    _open_task_browser: Callable[..., Any]
    _push_history: Callable[..., Any]
    _record_slash_usage: Callable[..., Any]
    _request_exit: Callable[..., Any]
    _resolve_ask: Callable[..., Any]
    _resolve_confirm: Callable[..., Any]
    _resolve_trust: Callable[..., Any]
    _run_submit: Any
    _scroll_log: Callable[..., Any]
    _scroll_to_bottom: Callable[..., Any]
    _scroll_to_top: Callable[..., Any]
    _session_picker_open: Callable[..., Any]
    _slash_items: Any
    _slash_move: Callable[..., Any]
    _slash_open: Any
    _sp_accept: Callable[..., Any]
    _sp_move: Callable[..., Any]
    _sp_panel: Any
    _sp_toggle_scope: Callable[..., Any]
    _streaming: Any
    _task_browser_open: Callable[..., Any]
    _tb_accept: Callable[..., Any]
    _tb_move: Callable[..., Any]
    _tb_panel: Any
    _tb_stop: Callable[..., Any]
    _tb_toggle_filter: Callable[..., Any]
    _toast: Any
    _toast_until: Any
    _toggle_help: Callable[..., Any]
    _tool_detail: Any
    _trust_index: Any
    _trust_pending: Any
    _turn_started: Any
    _turn_tool_lines: List[str]
    _view_top: Any
    _viewport_rows: Callable[..., Any]
    append_log: Callable[..., Any]
    on_command: Optional[Callable[[str], Optional[str]]]
    toggle_audit: Callable[..., Any]
    toggle_diff: Callable[..., Any]
    toggle_mcp_status: Callable[..., Any]

    def _set_clipboard(self, event: Any, text: str, label: str) -> None:
            """写系统剪贴板并给用户一条可感知的状态提示。

            prompt_toolkit 的 ``app.clipboard.set_text`` 在 Windows 上经
            ``WindowsClipboard`` 走 win32 剪贴板; 在无剪贴板的伪终端/测试环境,
            ``InMemoryClipboard`` 兜底, 状态提示会标注已复制而非报错。
            """
            text = text.rstrip("\n")
            if not text:
                return
            try:
                event.app.clipboard.set_text(text)
                # 状态行提示: 临时写入 _status_toast, 由 _status_hud 优先展示
                self._toast = f"已复制{label} ({len(text)} 字符)"
                self._toast_until = time.monotonic() + 2.0
            except Exception as exc:  # noqa: BLE001
                self._toast = f"复制失败: {exc}"
                self._toast_until = time.monotonic() + 2.0
            event.app.invalidate()

    def _copy_last_answer(self, event: Any) -> None:
            self._set_clipboard(event, self._last_assistant_text, "助手回复")

    def _copy_last_user(self, event: Any) -> None:
            self._set_clipboard(event, self._last_user_text, "输入")

    def _build_keys(self) -> "KeyBindings":
            kb = KeyBindings()

            @kb.add("c-c")
            def _(event: Any) -> None:
                self._request_exit(event)

            @kb.add("c-q")
            def _(event: Any) -> None:
                self._request_exit(event)

            @kb.add("enter")
            def _(event: Any) -> None:
                self._handle_enter(event)

            @kb.add("c-o")
            def _(event: Any) -> None:
                self.toggle_audit()

            # ---- 命令面板 (OpenCode ctrl+p): 打开 "/" 命令面板 ----
            # OpenCode 用 ctrl+p 唤起命令面板; 我们复用 Claude Code 同款 "/" 面板,
            # ctrl+p 等价于在输入框预填 "/" 并弹出面板 (空前缀列出全部命令)。
            @kb.add("c-p")
            def _(event: Any) -> None:
                if self._booting or self._boot_error or self._trust_pending:
                    return
                # 打开 "/" 面板: 若输入框为空则预填 "/", 否则保持原文本触发过滤
                try:
                    if not self._input.text:
                        self._input.text = "/"
                    self._slash_open = True
                    self._on_input_changed()
                    event.app.invalidate()
                except Exception as exc:  # noqa: BLE001 - 输入框未就绪 (极早期启动)
                    log.warning("InteractMixin._(): 非致命异常已忽略(设计内降级, 不改控制流): %s", exc)
                    pass

            # ---- 复制文本 (不能复制很难受) ----
            # F6: 复制最后一条助手回复到系统剪贴板; F7: 复制最后一条用户输入。
            # prompt_toolkit 的剪贴板是 Application 级, 用 app.clipboard.set_text
            # 写系统剪贴板 (Windows 下自动走 win32/msvcrt)。
            @kb.add("f6")
            def _(event: Any) -> None:
                self._copy_last_answer(event)

            @kb.add("f7")
            def _(event: Any) -> None:
                self._copy_last_user(event)

            # ---- 对话区回卷 (Claude Code 同款): 整屏翻页 / 逐行 / 到顶到底 ----
            # (不用 Ctrl+U/Ctrl+D: 会被输入框的编辑键抢占, 见 TextArea buffer 绑定)
            @kb.add("pageup")
            def _(event: Any) -> None:
                self._scroll_log(-self._viewport_rows())
                event.app.invalidate()

            @kb.add("pagedown")
            def _(event: Any) -> None:
                self._scroll_log(self._viewport_rows())
                event.app.invalidate()

            # Shift+PgUp/PgDn: 逐行微调 (整屏翻页有时太粗, 尤其快到顶/底时)
            @kb.add("s-pageup")
            def _(event: Any) -> None:
                self._scroll_log(-1)
                event.app.invalidate()

            @kb.add("s-pagedown")
            def _(event: Any) -> None:
                self._scroll_log(1)
                event.app.invalidate()

            # Ctrl+↑/↓: 同样逐行翻 (终端不总把 Shift+PgUp 传对时的等价键)
            @kb.add("c-up")
            def _(event: Any) -> None:
                self._scroll_log(-1)
                event.app.invalidate()

            @kb.add("c-down")
            def _(event: Any) -> None:
                self._scroll_log(1)
                event.app.invalidate()

            @kb.add("home")
            def _(event: Any) -> None:
                self._scroll_to_top()
                event.app.invalidate()

            @kb.add("end")
            def _(event: Any) -> None:
                self._scroll_to_bottom()
                event.app.invalidate()

            # ---- 鼠标滚轮: 回看对话历史 (Claude Code 同款) ----
            # prompt_toolkit 把鼠标事件送进按键系统, 分两条通道 (见
            # prompt_toolkit/key_binding/bindings/mouse.py):
            #   - `Keys.Vt100MouseEvent`: VT100/xterm/SGR 序列 (终端上报
            #     `ESC [ < 64 ; col ; row M` 等), conpty 走这条;
            #   - `Keys.WindowsMouseEvent`: Windows 原生控制台鼠标事件。
            # 两条都要接, 且**只能靠 event.data 的 event_type 区分滚轮与点击** ——
            # 滚轮不是独立键名 (`<scroll-up>` 在本版本 pt 里解析不出来)。
            # Shift+方向键也一并接: 部分终端把滚轮降级报成它。
            @kb.add(Keys.Vt100MouseEvent)
            @kb.add(Keys.WindowsMouseEvent)
            def _(event: Any) -> None:
                data = getattr(event, "data", None)
                etype = getattr(data, "event_type", None)
                name = getattr(etype, "name", "") or str(etype)
                # Shift 修饰: 交回终端/默认绑定 —— 让 Shift+拖选走**终端原生复制**,
                # Shift+滚轮走终端原生滚动。prompt_toolkit 已把 VT100/SGR 序列里的
                # modifier (Shift) 解析进 data.modifiers (见 mouse_events.MouseEvent)。
                modifiers: frozenset = getattr(data, "modifiers", frozenset()) or frozenset()
                if any(getattr(m, "name", "") == "SHIFT" for m in modifiers):
                    return  # 不消费
                if name == "SCROLL_UP":
                    self._mouse_wheel(event, up=True)
                    return
                if name == "SCROLL_DOWN":
                    self._mouse_wheel(event, up=False)
                    return
                # 点击/移动: 不消费, 交回默认 (终端自己做选中复制)

            @kb.add("s-up")
            def _(event: Any) -> None:
                self._mouse_wheel(event, up=True)

            @kb.add("s-down")
            def _(event: Any) -> None:
                self._mouse_wheel(event, up=False)

            # ---- "/" 命令面板: Tab 确认填入, ↑↓ 游走菜单 (关闭时回退默认行为), Esc 关闭 ----
            @kb.add("c-i")  # Tab
            def _(event: Any) -> None:
                if self._slash_open and self._slash_items:
                    self._accept_slash(event)
                    return
                b = event.current_buffer
                if b.complete_state:  # 兼容旧补全路径 (外部直接驱动 buffer 的场景)
                    b.complete_next()
                else:
                    b.start_completion(select_first=True)

            @kb.add("down")
            def _(event: Any) -> None:
                if self._sp_panel:
                    self._sp_move(1)
                    return
                if self._tb_panel:
                    self._tb_move(1)
                    return
                if self._ask_pending:
                    self._ask_move(1)
                    event.app.invalidate()
                    return
                if self._trust_pending:
                    self._trust_index = 1
                    event.app.invalidate()
                    return
                if self._slash_open and self._slash_items:
                    self._slash_move(1)
                    event.app.invalidate()
                    return
                b = event.current_buffer
                if b.complete_state:
                    b.complete_next()
                else:
                    # 面板关闭: 交还默认行为 (↑↓ 历史导航 / 光标移动)。
                    # 早先这里"匹配却不代理"吞掉了按键, 导致历史导航失效。
                    b.auto_down(count=event.arg or 1)

            @kb.add("up")
            def _(event: Any) -> None:
                if self._sp_panel:
                    self._sp_move(-1)
                    return
                if self._tb_panel:
                    self._tb_move(-1)
                    return
                if self._ask_pending:
                    self._ask_move(-1)
                    event.app.invalidate()
                    return
                if self._trust_pending:
                    self._trust_index = 0
                    event.app.invalidate()
                    return
                if self._slash_open and self._slash_items:
                    self._slash_move(-1)
                    event.app.invalidate()
                    return
                b = event.current_buffer
                if b.complete_state:
                    b.complete_previous()
                else:
                    # 同 down: 面板关闭时交还默认行为, 修复 ↑ 历史导航被吞。
                    b.auto_up(count=event.arg or 1)

            @kb.add("c-d")
            def _(event: Any) -> None:
                """Ctrl+D 开合右侧 diff 实时面板 (Claude Code 同款)。"""
                self.toggle_diff()
                event.app.invalidate()

            # ---- Kimi 移植: Ctrl+R 会话选择器 / Ctrl+T 后台任务浏览器 / F2 MCP 状态 ----
            @kb.add("c-r")
            def _(event: Any) -> None:
                """Ctrl+R: 打开会话选择器 (Kimi Code 同款, 浏览/恢复会话)。"""
                if not self._session_picker_open():
                    self._open_session_picker()
                event.app.invalidate()

            @kb.add("c-t")
            def _(event: Any) -> None:
                """Ctrl+T: 打开后台任务浏览器 (Kimi Code 同款, 查看/停止任务)。"""
                if not self._task_browser_open():
                    self._open_task_browser()
                event.app.invalidate()

            @kb.add("f2")
            def _(event: Any) -> None:
                """F2: 开合 MCP 服务器状态面板。

                注意: prompt_toolkit 中 ``Keys.Enter == Keys.ControlM`` (都是 ``c-m``),
                而 codex (crossterm) 里 Enter 与 Ctrl+M 是不同键。若绑定 ``c-m``,
                合并注册表 ``matches[-1]`` 会选中最后注册的 ``c-m``, 导致回车被
                MCP 面板开关劫持、提交/信任确认卡死。因此改用 F2 (codex 无该键位,
                且与现有绑定无冲突)。
                """
                self.toggle_mcp_status()
                event.app.invalidate()

            # ---- 面板内单键: 会话选择器 Ctrl+A 切范围 / 任务浏览器 A 切过滤、X 停止 ----
            @kb.add("c-a")
            def _(event: Any) -> None:
                if self._sp_panel:
                    self._sp_toggle_scope()
                    return
                # 面板关闭: 交还默认 (Ctrl+A = 光标到行首), 避免输入框编辑行为被吞
                b = event.current_buffer
                b.beginning_of_line()

            @kb.add("a")
            def _(event: Any) -> None:
                if self._tb_panel:
                    self._tb_toggle_filter()
                    return

            @kb.add("x")
            def _(event: Any) -> None:
                if self._tb_panel:
                    self._tb_stop()
                    return

            @kb.add("escape")
            def _(event: Any) -> None:
                # Esc 逐层关闭: 面板 > 审计 > diff > "/" 命令面板
                if self._sp_panel:
                    self._close_session_picker()
                    event.app.invalidate()
                    return
                if self._tb_panel:
                    self._close_task_browser()
                    event.app.invalidate()
                    return
                if getattr(self, "_mcp_visible", False):
                    self.toggle_mcp_status()
                    event.app.invalidate()
                    return
                if self._slash_open:
                    self._close_slash_menu()
                    event.app.invalidate()
                    return
                if self._help_open:
                    self._toggle_help()
                    event.app.invalidate()
                    return

            # Codex 同款 "?": 空输入时开合快捷键帮助浮层 (shortcut_overlay.rs)。
            # 只在输入框为空且非 busy/streaming/面板态时响应 —— "?" 本身仍是可输入字符,
            # 不能劫持用户正想打问号的消息。
            @kb.add("?")
            def _(event: Any) -> None:
                if (self._help_open
                        or (not self._busy and not self._streaming
                            and not self._slash_open and not self._commands
                            and not self._sp_panel and not self._tb_panel
                            and not self._mcp_visible
                            and not self._input.text.strip())):
                    self._toggle_help()
                    event.app.invalidate()

            return kb

    def _handle_enter(self, event: Any) -> None:
            # 模型提问态优先级最高: 模型在等用户拍板, 输入框此刻就是选项答复通道
            # (↑↓ 已由键位路由到 _ask_move; Enter 取高亮项 / 编号 / 自由文本)。
            # 必须排在 slash 面板与 trust 之前, 否则提问会被当成普通输入吞掉。
            if self._ask_pending:
                self._resolve_ask(self._input.text)
                self._input.buffer.reset()
                event.app.invalidate()
                return
            # Kimi 面板确认: 会话选择器 Enter=恢复, 任务浏览器 Enter=看输出
            if self._sp_panel:
                self._sp_accept()
                event.app.invalidate()
                return
            if self._tb_panel:
                self._tb_accept()
                event.app.invalidate()
                return
            # "/" 命令面板展开: Enter 确认高亮项 (填入输入框, 不直接执行 —— 与
            # Claude Code 一致, 填好后可继续输参数或再按回车执行)
            if self._slash_open and self._slash_items:
                self._accept_slash(event)
                return
            text = self._input.text.strip()
            # 信任确认态: 优先按 y/n 解析; 若用户直接输入了别的内容, 说明他就是要用这个
            # 工作区 —— 自动记为信任, 并把这句当作正常消息继续往下走。
            # (此前非 y/n 输入只提示"无效"并停在确认态: 用户不按 y/n 就永远进不了对话,
            #  表现即"TUI 没有输入框 / 输入没反应"。
            #  **必须排在空输入 guard 之前**: 否则空输入按 Enter 会在 `if not text: return`
            #   处提前退出, 永远到不了这里 —— 默认高亮项 (信任) 无法用回车确认, 信任卡
            #   就此卡死 (用户"完全进不去")。空回车 = 按当前 ↑↓ 高亮项确认。)
            if self._trust_pending:
                # ① 用户直接输入了明确的 y/n/1/2/是/否/信任/只读 → 按文本解析
                if text and self._resolve_trust(text):
                    self._input.buffer.reset()
                    event.app.invalidate()
                    return
                # ② 否则按当前 ↑↓ 高亮项确认 (默认高亮=信任, 空回车也能进工作区);
                #    既修复"对话框没有选项"的渲染缺失, 也修复"不按 y/n 就永远卡在确认态"。
                self._resolve_trust("y" if self._trust_index == 0 else "n")
                self._input.buffer.reset()
                event.app.invalidate()
                return
            # 命令确认态: 同样只接受 y/n (或确认码)。必须排在 _busy 判断之前 ——
            # 确认期间 _busy=True (防止用户又提交一轮对话), 但输入框此刻正是答复通道。
            # 空回车按"未答复"处理 (不误放行), 不提前 return —— 交给 _resolve_confirm 判无效。
            if self._confirm_pending:
                self._resolve_confirm(text)
                self._input.buffer.reset()
                event.app.invalidate()
                return
            if not text:
                return
            if self._booting or self._boot_error:
                self.append_log(t("tui.booting_wait"))
                return
            if self._busy:
                self.append_log(t("tui.busy_wait"))
                return

            self._push_history(text)
            self._input.buffer.reset()
            self._busy = True
            self._turn_started = time.monotonic()
            self._cancel_requested.clear()
            self._moon_suppressed = False  # 新一轮回合, 思考月亮恢复可用
            # 新一轮: 重置工具折叠缓冲, 并回到自动跟随底部 (让最新回复可见)
            self._turn_tool_lines = []
            self._tool_detail = False
            self._follow = True
            self._view_top = 0

            # 命令: 支持 `/cmd` 与 Kimi 同款 `+/cmd` (归一化后统一走 on_command)
            cmd = None
            if text.startswith("/"):
                cmd = text
            elif text.startswith("+/"):
                cmd = "/" + text[2:]
            if cmd and self.on_command:
                self._record_slash_usage(cmd)  # C-3.5: 记录最近使用, 下次 "/" 优先
                result = self.on_command(cmd)
                if result:
                    self.append_log(result)
                self._busy = False
                event.app.invalidate()
                return

            self.append_log(f"{USER_MESSAGE_BULLET}{text}")
            self._last_user_text = text  # 供复制
            threading.Thread(
                target=self._run_submit, args=(text,),
                name="tuan-submit", daemon=True,
            ).start()

    def _ask_move(self, delta: int) -> None:
            """↑↓ 移动选项高亮 (无选项时忽略)。"""
            pending = self._ask_pending
            if not pending:
                return
            opts = pending.get("options") or []
            if not opts:
                return
            n = len(opts)
            self._ask_free = False
            self._ask_index = max(0, min(n - 1, self._ask_index + delta))

    def _wheel_owner(self) -> bool:
            """当前是否有交互卡片占用"上下"语义 —— 有则滚轮让位给卡片。

            模型提问 (ask_user)、首次信任确认、"/" 命令面板这三种状态下,
            ↑↓ 是"在选项之间移动", 不是"翻历史"。若滚轮此时也拿去翻页,
            用户会看到选项列表却在滚动一个静止的画面 —— 表现为"能看不能选"。
            """
            return bool(self._ask_pending or self._trust_pending
                        or self._confirm_pending
                        or (self._slash_open and self._slash_items))

    def _mouse_wheel(self, event: Any, up: bool) -> None:
            """滚轮事件入口: 按终端行上下平移对话区视口。

            `up=True` 向历史方向 (内容下移), `up=False` 回到最新。
            """
            if self._wheel_owner():
                # 卡片态: 滚轮与 ↑↓ 键同义 —— 在选项之间移动高亮。
                delta = -1 if up else 1
                if self._ask_pending:
                    self._ask_move(delta)
                elif self._trust_pending:
                    # 信任卡是两项 radiolist (0=信任 / 1=只读); 与 ↑↓ 键行为一致:
                    # up 直接回 0、down 直接到 1 (而不是循环切换)。
                    self._trust_index = 0 if up else 1
                elif self._slash_open and self._slash_items:
                    self._slash_move(delta)
                try:
                    event.app.invalidate()
                except Exception as exc:  # noqa: BLE001 - 无 app 时忽略
                    log.warning("InteractMixin._mouse_wheel(): 非致命异常已忽略(设计内降级, 不改控制流): %s", exc)
                    pass
                return
            # 一格滚轮 = _MOUSE_WHEEL_LINES 终端行, 快速滑动才能翻整屏
            self._scroll_log(-self._MOUSE_WHEEL_LINES if up else self._MOUSE_WHEEL_LINES)
            try:
                event.app.invalidate()
            except Exception as exc:  # noqa: BLE001 - 无 app 时忽略
                log.warning("InteractMixin._mouse_wheel(): 非致命异常已忽略(设计内降级, 不改控制流): %s", exc)
                pass
