# -*- coding: utf-8 -*-
"""TUI UI 桥接 —— 让 slash 命令 / 后台线程的输出进入全屏 TUI 界面。

问题: cmd_slash 里所有 ui.info/ui.success 以及 WebServer.serve_forever 的
print() 都直接写 stdout。在 QxtTUI (prompt_toolkit 全屏 Application) 运行时,
这些输出绕过渲染层直接打进终端, 表现为"新输出挤爆 TUI 界面"。

解决: QxtTUI 启动后调用 attach_ui(), 把 _ui_singleton._ui 替换为本桥接实例。
桥接把所有 UI 方法转发为 QxtTUI.append_log() —— 由 TUI 渲染层安全绘制,
从任意线程调用都不会破坏界面 (append_log 内部只做 invalidate)。
"""
from __future__ import annotations

from typing import Any, Optional


class TuiUI:
    """把 REPL UI 接口转发到 QxtTUI 日志区的桥接实现。

    覆盖 _ui_singleton.ui 在 slash 命令路径中会用到的全部方法;
    未覆盖的方法 (状态条更新等) 由 cmd_chat 直接调用 tui, 不经 ui。
    """

    def __init__(self, tui: Any) -> None:
        self._tui = tui
        self._tokens = 0

    # ------------------------------------------------------------ 文本输出
    def info(self, text: str) -> None:
        self._tui.append_log(str(text), cls="class:textdim")

    def error(self, text: str) -> None:
        self._tui.append_log(f"  ✗ {text}", cls="class:error")

    def success(self, text: str) -> None:
        self._tui.append_log(f"  ✓ {text}", cls="class:success")

    def answer_md(self, text: str) -> None:
        # TUI 日志区按纯文本渲染; markdown 源码保留可读性, 不在此做二次渲染
        self._tui.append_log(str(text))

    def think_start(self) -> None:
        pass  # TUI 自带思考月亮动画

    def stream(self, token: str) -> None:
        pass  # TUI 流式渲染由 stream_assistant 负责

    def reason(self, text: str) -> None:
        self._tui.append_log(f"  ? {text}", cls="class:textdim")

    def tool_call(self, name: str, args: dict) -> None:
        self._tui.append_log(f"  tool {name} {str(args)[:120]}", cls="class:warning")

    def tool_result(self, name: str, result: str) -> None:
        failed = any(k in result for k in ("[错误]", "[已拒绝]", "Error", "error:", "Traceback", "失败"))
        icon = "✗" if failed else "✓"
        flat = (result or "").replace("\n", " ").strip()
        s = flat[:200] + ("…" if len(flat) > 200 else "")
        self._tui.append_log(f"  └─ {icon} {s}", cls="class:error" if failed else "class:textdim")

    def usage(self, usage: dict) -> None:
        pt = usage.get("prompt_tokens", 0)
        ct = usage.get("completion_tokens", 0)
        self._tui.append_log(f"  tokens: prompt {pt} / completion {ct}", cls="class:textdim")

    def show_more(self) -> None:
        pass

    # ------------------------------------------------------------ 状态/计数
    def add_tokens(self, n: int) -> None:
        self._tokens += max(0, int(n))

    def set_context_pct(self, pct: float, used: int = 0, budget: int = 0) -> None:
        pass  # TUI 底部 context 条由 tui.set_context_info 维护

    def context_bar(self, info: dict) -> None:
        pass

    def mascot_set(self, state: str) -> None:
        pass

    # ------------------------------------------------------------ 交互确认
    def confirm(self, prompt: str, *, expected: Optional[str] = None,
                position: Optional[int] = None) -> bool:
        """TUI 内确认: 挂起应用读一次性确认码 (与 QxtTUI.confirm 同路径)。"""
        try:
            result = self._tui.confirm(prompt, expected=expected, position=position)
            return bool(result)
        except Exception:  # noqa: BLE001
            from ..core.whitelist import interactive_confirm
            return bool(interactive_confirm(prompt, expected=expected, position=position))
