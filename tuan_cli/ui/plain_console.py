"""纯文本 console —— 剥离所有 Rich 高亮标记, 输出无颜色/无加粗的纯文本。

所有面向用户的 CLI 输出统一走这里的 `console`, 保证全终端无高亮字体。

rich 只在真正用到 console 时才导入 (~100ms): `config get` 等轻量命令
import 本模块不付 rich 代价, `console` 首次 print 时才加载。
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from rich.console import Console

    _render_console: Console
    render_plain: Callable[[Any], str]
    PlainConsole: type[Console]
    console: Console

# 仅匹配合法的 Rich 样式标记 (颜色名/属性/hex 色), 不误伤类型注解或内容前缀
# (如 Optional[...]、[web_fetch] 等)。
_STYLE_TOKENS = (
    "bold|dim|italic|underline|blink|reverse|strike|conceal|"
    "black|red|green|yellow|blue|magenta|cyan|white|grey|gray|"
    "bright_black|bright_red|bright_green|bright_yellow|bright_blue|"
    "bright_magenta|bright_cyan|bright_white"
)
_MARKUP_RE = re.compile(
    r"\[/\]|\[/?(?:%s|#[0-9a-fA-F]{3,8})(?: (?:%s|#[0-9a-fA-F]{3,8}))*\]"
    % (_STYLE_TOKENS, _STYLE_TOKENS)
)
_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def strip_markup(text: str) -> str:
    """剥离字符串中的 Rich 样式标记, 保留其余文本。"""
    return _MARKUP_RE.sub("", text)


def strip_ansi(text: str) -> str:
    """剥离所有 ANSI 转义序列, 输出纯文本。"""
    return _ANSI_RE.sub("", text)


# ---- 以下符号依赖 rich, 惰性加载 (PEP 562 模块 __getattr__) ----
_LAZY_RICH = ("_render_console", "render_plain", "PlainConsole", "console")
_rich_loaded = False


def _ensure_rich() -> None:
    """首次访问 rich 依赖符号时才导入 rich 并构建 console 单例。"""
    global _rich_loaded, _render_console, render_plain, PlainConsole, console
    if _rich_loaded:
        return
    from rich.console import Console

    # 无颜色渲染器: 把 Markdown/Table 等 renderable 转成纯文本字符串。
    _render_console = Console(no_color=True, force_terminal=False, highlight=False)

    def render_plain(obj: Any) -> str:
        """把任意 Rich renderable 渲染为纯文本 (无颜色/无加粗/无 ANSI)。"""
        with _render_console.capture() as cap:
            _render_console.print(obj)
        return strip_ansi(cap.get())

    class PlainConsole(Console):
        """打印时自动剥离 Rich 标记并禁用语法高亮的 Console, 输出纯文本。"""

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            kwargs.setdefault("highlight", False)
            # 记录调用方是否显式指定了输出流: 显式指定 (如测试传 file=buf) 时
            # 必须尊重该流; 只有走默认 sys.stdout 时才允许打印前同步为当前 stdout。
            self._explicit_file = "file" in kwargs or bool(args)
            super().__init__(*args, **kwargs)

        def _sync_file(self) -> None:
            """Rich Console 构造时固化了当时的 ``sys.stdout``。

            测试 (pytest capsys / monkeypatch) 或调用方可能替换 ``sys.stdout``,
            若仍写旧流会丢失输出。每次打印前把输出目标同步为当前 ``sys.stdout``,
            保证 CLI 输出始终落在调用方期望的流上 (含重定向/捕获)。

            仅当调用方**未显式指定**输出流时同步; 显式传 ``file=`` (如单元测试
            注入 ``StringIO``) 必须原样尊重, 不能被覆盖成 ``sys.stdout``。
            """
            if self._explicit_file:
                return
            import sys

            if self._file is not sys.stdout:
                self._file = sys.stdout

        def print(self, *objects: Any, **kwargs: Any) -> Any:
            self._sync_file()
            plain = tuple(
                strip_markup(o) if isinstance(o, str) else render_plain(o) for o in objects
            )
            kwargs["markup"] = False
            return super().print(*plain, **kwargs)

    PlainConsole.__module__ = __name__
    console = PlainConsole()
    _rich_loaded = True


def __getattr__(name: str) -> Any:
    if name in _LAZY_RICH:
        _ensure_rich()
        return globals()[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
