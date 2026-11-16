"""面板/浏览器域: 审计/Diff/MCP 面板开关、会话选择器、任务浏览器、帮助覆盖层。

本模块由 tui.py 的 QxtTUI 拆分而来, 方法体逐行原样迁移 (无逻辑改动)。
模块级常量/工具/小类集中在 `tuan_cli.tui.common`, 由 `from .common import *`
注入到本模块命名空间, 因此方法体内对模块级名字的引用保持不变。
"""

from __future__ import annotations

from .common import *  # noqa: F401,F403

import logging
log = logging.getLogger(__name__)



class PanelsMixin:
    """面板/浏览器域: 审计/Diff/MCP 面板开关、会话选择器、任务浏览器、帮助覆盖层。"""

    # ---- 跨 mixin 共享实例属性/方法 (纯声明, 运行期不赋值) ----
    _HELP_GROUPS: Any
    _app: Any
    _audit_log: Any
    _audit_visible: Any
    _clip_dw: Callable[[str, int], str]
    _diff_cache: List[Tuple[str, str]]
    _diff_error: Any
    _diff_fetched_at: Any
    _diff_panel_available: Callable[..., Any]
    _diff_panel_width: Callable[..., Any]
    _diff_summary: Any
    _diff_visible: Any
    _help_open: Any
    _mcp_servers: List[Any]
    _mcp_visible: Any
    _render_sp_rows: Callable[..., Any]
    _render_tb_rows: Callable[..., Any]
    _sp_panel: Any
    _tb_panel: Any
    _terminal_cols: Callable[..., Any]
    _tool_detail: Any
    append_log: Callable[..., Any]
    audit: Callable[..., Any]
    on_command: Optional[Callable[[str], Optional[str]]]

    def toggle_audit(self) -> None:
            """Ctrl+O 切换"see"折叠: 收起/展开工具调用详情 + 审计面板 (思考过程)。

            折叠态在对话区只显示一行 "see N tool calls", 展开态逐条展示每步调用;
            审计面板同步显示完整思考过程与工具记录。类似 Claude/TraeWork 的折叠观察窗。
            """
            self._audit_visible = not self._audit_visible
            self._tool_detail = self._audit_visible
            if self._app and self._app.is_running:
                self._app.invalidate()

    def toggle_diff(self) -> None:
            """Ctrl+D 开合 diff 面板。"""
            if not self._diff_visible and not self._diff_panel_available():
                self._audit_log.append((
                    "class:textdim",
                    t("tui.diff_too_narrow", width=self._terminal_cols()),
                ))
                if self._app and self._app.is_running:
                    self._app.invalidate()
                return
            self._diff_visible = not self._diff_visible
            if self._diff_visible:
                self._diff_fetched_at = 0.0        # 立刻刷新一次
            if self._app and self._app.is_running:
                self._app.invalidate()

    def _fetch_diff(self) -> None:
            """同步取一次工作区 diff 并切好颜色。

            只在面板可见时调用; 由 `_render_diff_panel` 按 1.5s 节流触发, 所以这里的
            开销最多是"每秒不到一次 fork git"。
            """
            import os
            import subprocess

            self._diff_fetched_at = time.monotonic()
            try:
                ws = getattr(self, "_workspace", None) or os.getcwd()
                # 显式检测是否在 git 仓库根: git 会沿父目录向上找 .git, 若工作区是
                # 某仓库内的子目录 (如 E:\Tuan-CLI\.pytest-tmp\...), `git diff` 会误判
                # 为仓库并返回父仓库的真实 diff。用 --show-toplevel 拿到仓库根绝对路径,
                # 只有工作区本身就是仓库根 (resolve 后相等) 才视为仓库; 否则直接报错,
                # 保证「非仓库应给出可读提示」而非误读上层仓库。
                ws_resolved = os.path.abspath(ws)
                probe = subprocess.run(  # noqa: S603 - 固定参数, 无用户输入拼接
                    ["git", "rev-parse", "--show-toplevel"], cwd=ws,
                    capture_output=True, text=True, timeout=10, errors="replace",
                )
                top = (probe.stdout or "").strip()
                if probe.returncode != 0 or not top or \
                        os.path.abspath(top) != ws_resolved:
                    self._diff_error = (probe.stderr or "").strip()[:200] or t("tui.diff_not_repo")
                    self._diff_cache = []
                    self._diff_summary = ""
                    return
                proc = subprocess.run(  # noqa: S603 - 固定参数, 无用户输入拼接
                    ["git", "diff", "--no-color"], cwd=ws,
                    capture_output=True, text=True, timeout=10, errors="replace",
                )
            except FileNotFoundError:
                self._diff_error = t("tui.diff_no_git")
                self._diff_cache = []
                self._diff_summary = ""
                return
            except subprocess.TimeoutExpired:
                self._diff_error = t("tui.diff_timeout")
                self._diff_cache = []
                self._diff_summary = ""
                return
            except Exception as exc:  # noqa: BLE001 - 面板失败不能影响主界面
                self._diff_error = t("tui.diff_failed", error=exc)
                self._diff_cache = []
                self._diff_summary = ""
                return

            if proc.returncode != 0 and not proc.stdout:
                self._diff_error = (proc.stderr or "").strip()[:200] or t("tui.diff_not_repo")
                self._diff_cache = []
                self._diff_summary = ""
                return

            self._diff_error = ""
            files = added = removed = 0
            rows: List[Tuple[str, str]] = []
            width = self._diff_panel_width()

            def cut(raw: str) -> str:
                """按**显示宽度**截断到面板宽度。

                旧实现用 `raw[:width]` 按字符数截断, 对中文/emoji 完全失效 ——
                一个汉字占 2 列, 一行 60 字的中文注释实际要120 列, 而面板
                `wrap_lines=False`, 超宽内容会直接顶破布局 (右侧面板压到终端右边界
                之外, 表现为"溢出/错位")。
                """
                return self._clip_dw(raw, max(1, width))

            for raw in (proc.stdout or "").splitlines():
                if raw.startswith("diff --git"):
                    files += 1
                    rows.append(("class:primary", cut(raw)))
                    continue
                if raw.startswith(("+++", "---")):
                    rows.append(("class:textdim", cut(raw)))
                    continue
                if raw.startswith("@@"):
                    rows.append(("class:accent", cut(raw)))
                    continue
                if raw.startswith("+"):
                    added += 1
                    rows.append(("class:diffadd", cut(raw)))
                    continue
                if raw.startswith("-"):
                    removed += 1
                    rows.append(("class:diffdel", cut(raw)))
                    continue
                if raw.startswith(("index ", "new file", "deleted file", "similarity ")):
                    rows.append(("class:textdim", cut(raw)))
                    continue
                rows.append(("class:text", cut(raw)))

            self._diff_summary = (
                t("tui.diff_summary", files=files, added=added, removed=removed)
                if files else t("tui.diff_clean")
            )
            self._diff_cache = rows

    def _session_picker_open(self) -> bool:
            """会话选择器是否正在展开。"""
            return bool(getattr(self, "_sp_panel", None))

    def _task_browser_open(self) -> bool:
            """任务浏览器是否正在展开。"""
            return bool(getattr(self, "_tb_panel", None))

    def _open_session_picker(self) -> None:
            """Ctrl+R: 打开会话选择器面板 (Kimi 同款: ↑↓ 选会话, Ctrl+A 切范围, Enter 恢复)。

            面板渲染在对话区底部 (输入框上方), 与 slash 菜单 / 信任卡片同层。
            选择后调用 `_resume_session(session_id)` (由 cmd_chat 通过 on_command 路由)。
            """
            try:
                from .kimi_modules import (
                    SessionEntry, SessionPickerModel, collect_sessions,
                    format_session_choice, _EMPTY_SESSION_ID,
                )
            except Exception as exc:  # noqa: BLE001
                self._audit_log.append(("class:error", f"[Kimi 会话选择器] 加载失败: {exc}"))
                if self._app and self._app.is_running:
                    self._app.invalidate()
                return
            sessions = collect_sessions()
            model = SessionPickerModel(sessions)
            model.current_dir = getattr(self, "workspace", os.getcwd())
            model.refresh()
            self._sp_panel = {
                "model": model,
                "rows": [],
                "open": True,
            }
            self._render_sp_rows()
            if self._app and self._app.is_running:
                self._app.invalidate()

    def _sp_move(self, delta: int) -> None:
            model = self._sp_panel["model"]
            model.move(delta)
            self._render_sp_rows()
            if self._app and self._app.is_running:
                self._app.invalidate()

    def _sp_toggle_scope(self) -> None:
            model = self._sp_panel["model"]
            model.toggle_scope()
            self._render_sp_rows()
            if self._app and self._app.is_running:
                self._app.invalidate()

    def _sp_accept(self) -> bool:
            """确认选中会话; 返回是否消费了按键 (有选中项才算)。"""
            model = self._sp_panel["model"]
            sel = model.selected
            if sel is None:
                return False
            self._close_session_picker()
            self.append_log(f"[会话] 恢复 {sel.session_id} ({sel.work_dir})")
            self.audit("info", f"会话选择: {sel.session_id}")
            # 交给命令路由 (cmd_chat.command_in_tui 的 /session resume 语义)
            try:
                if self.on_command:
                    self.on_command(f"/session resume {sel.session_id}")
            except Exception as exc:  # noqa: BLE001
                self.append_log(f"[会话] 恢复失败: {exc}")
            return True

    def _close_session_picker(self) -> None:
            self._sp_panel = None
            if self._app and self._app.is_running:
                self._app.invalidate()

    def _open_task_browser(self) -> None:
            """Ctrl+T: 打开后台任务浏览器 (Kimi 同款: ↑↓ 选任务, A 切过滤, Enter 看输出, X 停止)。"""
            try:
                from .kimi_modules import TaskBrowserModel, collect_tasks
            except Exception as exc:  # noqa: BLE001
                self._audit_log.append(("class:error", f"[Kimi 任务浏览器] 加载失败: {exc}"))
                if self._app and self._app.is_running:
                    self._app.invalidate()
                return
            tasks = collect_tasks()
            model = TaskBrowserModel(tasks)
            self._tb_panel = {"model": model, "rows": [], "open": True}
            self._render_tb_rows()
            if self._app and self._app.is_running:
                self._app.invalidate()

    def _tb_move(self, delta: int) -> None:
            model = self._tb_panel["model"]
            model.move(delta)
            self._render_tb_rows()
            if self._app and self._app.is_running:
                self._app.invalidate()

    def _tb_toggle_filter(self) -> None:
            model = self._tb_panel["model"]
            model.toggle_filter()
            self._render_tb_rows()
            if self._app and self._app.is_running:
                self._app.invalidate()

    def _tb_stop(self) -> bool:
            """停止选中的后台任务 (Kimi 同款 X); 返回是否消费按键。"""
            model = self._tb_panel["model"]
            sel = model.selected
            if sel is None:
                return False
            try:
                from ..core.background_store import kill_process_tree
                if sel.pid:
                    kill_process_tree(sel.pid)
                    model.flash_message(f"已发送停止信号给 {sel.task_id}")
                else:
                    model.flash_message(f"任务 {sel.task_id} 无运行进程")
            except Exception as exc:  # noqa: BLE001
                model.flash_message(f"停止失败: {exc}")
            # 刷新任务列表
            try:
                from .kimi_modules import collect_tasks
                model.all_tasks = collect_tasks()
            except Exception as exc:  # noqa: BLE001
                log.warning("PanelsMixin._tb_stop(): 非致命异常已忽略(设计内降级, 不改控制流): %s", exc)
                pass
            model.refresh()
            self._render_tb_rows()
            if self._app and self._app.is_running:
                self._app.invalidate()
            return True

    def _tb_accept(self) -> bool:
            """查看选中任务输出; 返回是否消费按键。"""
            model = self._tb_panel["model"]
            sel = model.selected
            if sel is None:
                return False
            self._close_task_browser()
            self.append_log(f"[任务] {sel.task_id} · {sel.status} · 输出:\n{sel.result or '(无输出)'}")
            self.audit("info", f"任务浏览: {sel.task_id} [{sel.status}]")
            return True

    def _close_task_browser(self) -> None:
            self._tb_panel = None
            if self._app and self._app.is_running:
                self._app.invalidate()

    def toggle_mcp_status(self) -> None:
            """F2: 开合 MCP 服务器状态面板。"""
            self._mcp_visible = not getattr(self, "_mcp_visible", False)
            if self._mcp_visible:
                try:
                    from .kimi_modules import collect_mcp_servers
                    self._mcp_servers = collect_mcp_servers()
                except Exception:  # noqa: BLE001
                    self._mcp_servers = []
            if self._app and self._app.is_running:
                self._app.invalidate()

    def _help_overlay_rows(self) -> int:
            """快捷键浮层高度 (布局期 callable 求值): 内容行数 + 空行 + 底部提示行。"""
            rows = 1 + len(self._HELP_GROUPS[0][1])  # 标题 + 最长组 (Compose)
            return max(1, rows + 3)

    def _toggle_help(self) -> None:
            """开合 "?" 快捷键帮助浮层。"""
            self._help_open = not self._help_open
            if self._app and self._app.is_running:
                try:
                    self._app.invalidate()
                except Exception as exc:  # noqa: BLE001
                    log.warning("PanelsMixin._toggle_help(): 非致命异常已忽略(设计内降级, 不改控制流): %s", exc)
                    pass
