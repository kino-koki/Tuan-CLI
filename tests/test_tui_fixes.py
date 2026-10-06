# -*- coding: utf-8 -*-
"""TUI 修复回归测试: UI 桥接 / /web 横幅 / slash 补全 meta。"""
from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from qingxiaotuan.ui.tui_bridge import TuiUI  # noqa: E402


# ---------------------------------------------------------------- TUI UI 桥接
class _FakeTui:
    def __init__(self):
        self.logs = []

    def append_log(self, text, cls=None):
        self.logs.append((text, cls))

    def confirm(self, prompt, *, expected=None, position=None):
        return True


class TestTuiBridge:
    def test_info_success_error_forwarded(self):
        tui = _FakeTui()
        b = TuiUI(tui)
        b.info("hello")
        b.success("done")
        b.error("boom")
        assert tui.logs[0][0] == "hello"
        assert tui.logs[1][0].startswith("  ✓")
        assert tui.logs[2][0].startswith("  ✗")

    def test_answer_md_forwarded(self):
        tui = _FakeTui()
        b = TuiUI(tui)
        b.answer_md("## 标题\n正文")
        assert tui.logs[0][0] == "## 标题\n正文"

    def test_confirm_delegates_to_tui(self):
        b = TuiUI(_FakeTui())
        assert b.confirm("确认?") is True

    def test_attach_ui_replaces_singleton(self):
        from qingxiaotuan.cli import _ui_singleton
        from qingxiaotuan.cli.cmd_chat import _prepare_agent  # noqa: F401 确保可导入

        class FakeQxtTUI:
            def __init__(self):
                self.called = False

            def attach_ui(self):
                self.called = True

        # 直接测 QxtTUI.attach_ui 存在且可调用 (不启动全屏)
        from qingxiaotuan.tui.tui import QxtTUI
        assert hasattr(QxtTUI, "attach_ui")
        assert hasattr(QxtTUI, "__init__")
        # 单例替换路径: attach_ui 内部会把 _ui_singleton._ui 换成 TuiUI
        import inspect
        src = inspect.getsource(QxtTUI.attach_ui)
        assert "_ui_singleton._ui = TuiUI(self)" in src


# ---------------------------------------------------------------- /web 横幅
class TestWebBanner:
    def test_serve_forever_accepts_banner(self):
        from qingxiaotuan.web.server import WebServer
        import inspect
        sig = inspect.signature(WebServer.serve_forever)
        assert "banner" in sig.parameters

    def test_banner_called_not_print(self, tmp_path, monkeypatch):
        """serve_forever(banner=...) 时横幅走回调, 不打 stdout。"""
        from qingxiaotuan.app import build_kernel
        from qingxiaotuan.web.server import WebServer

        kernel = build_kernel()
        srv = WebServer(kernel, str(tmp_path), port=0)
        calls = []
        captured = io.StringIO()
        monkeypatch.setattr(sys, "stdout", captured)
        # 直接调 serve_forever 会阻塞; 用 httpd 已绑定后抛异常退出验证 banner 先行
        def _banner(url, ws, mdl):
            calls.append((url, ws, mdl))
            raise KeyboardInterrupt

        with pytest.raises(KeyboardInterrupt):
            srv.serve_forever(banner=_banner)
        assert len(calls) == 1
        assert calls[0][1] == str(tmp_path)
        # banner 模式不打印启动横幅
        assert "Web 工作台已启动" not in captured.getvalue()


# ---------------------------------------------------------------- slash 补全 meta
class TestSlashMeta:
    def test_slash_command_meta(self):
        from qingxiaotuan.cli.cmd_slash import slash_command_meta
        meta = slash_command_meta()
        assert meta.get("/web", "").startswith("启动本地 Web")
        assert meta.get("/help", "") == "显示帮助"
        assert len(meta) > 15

    def test_list_slash_commands_has_meta_keys(self):
        from qingxiaotuan.cli.cmd_slash import list_slash_commands, slash_command_meta
        names = list_slash_commands()
        meta = slash_command_meta()
        for n in names:
            assert n.startswith("/")
        # 常用命令必须有描述
        for key in ("/help", "/provider", "/web", "/code", "/commands", "/clear", "/exit"):
            assert key in meta, key

    def test_completer_uses_meta(self):
        from qingxiaotuan.tui.tui import _SlashCompleter

        c = _SlashCompleter(["/web", "/code"], {"/web": "启动 Web 工作台"})
        items = list(c.get_completions(_FakeDocument("/"), None))
        metas = {}
        for it in items:
            disp = it.display_text if hasattr(it, "display_text") else str(it.display)
            meta = it.display_meta_text if hasattr(it, "display_meta_text") else str(it.display_meta)
            metas[disp] = meta
        assert metas.get("/web") == "启动 Web 工作台"
        assert metas.get("/code", "")  # 未收录命令回退非空 meta


class _FakeDocument:
    def __init__(self, text):
        self.text_before_cursor = text

# ---------------------------------------------------------------- 输出溢出防护
class TestOverflowGuard:
    """TUI 规范化: 单条日志/流式缓冲/思考全文都有界, 防止巨文本挤爆渲染。"""

    def _tui(self):
        from qingxiaotuan.tui.tui import QxtTUI
        return QxtTUI(on_submit=lambda x: None)

    def test_append_log_truncates_long_text(self):
        tui = self._tui()
        tui.append_log("x" * 5000)
        ev = tui._events[-1]
        assert isinstance(ev, str)
        assert len(ev) < 2100
        assert "已截断" in ev

    def test_append_log_short_text_untouched(self):
        tui = self._tui()
        tui.append_log("ok")
        assert tui._events[-1] == "ok"

    def test_append_log_no_truncate_when_max_len_zero(self):
        tui = self._tui()
        tui.append_log("y" * 3000, max_len=0)
        assert len(tui._events[-1]) == 3000

    def test_append_log_tuple_cls_kept(self):
        tui = self._tui()
        tui.append_log("z" * 4000, cls="class:error")
        ev = tui._events[-1]
        assert ev[0] == "class:error"
        assert "已截断" in ev[1]

    def test_stream_assistant_flushes_overlong_buffer(self):
        tui = self._tui()
        tui.stream_assistant("a" * 30000)
        # 超过上限: 前段固化为日志, 剩余留在缓冲继续流式
        assert tui._stream_buf
        assert any("流式超长" in (e if isinstance(e, str) else e[1]) for e in tui._events)

    def test_stream_reason_caps_full_text(self):
        tui = self._tui()
        tui.stream_reason("r" * 40000)
        assert "已截断" in tui._reason_full
        assert len(tui._reason_full) < 31000

    def test_audit_truncates_long_text(self):
        tui = self._tui()
        tui.audit("class:warning", "w" * 5000)
        assert "已截断" in tui._audit_log[-1][1]

    def test_end_stream_uses_append_log(self):
        tui = self._tui()
        tui.stream_assistant("hello")
        tui.end_stream()
        assert tui._events[-1].startswith("● hello")


# ---------------------------------------------------------------- set_ready 接线
class TestSetReadyAttach:
    """set_ready 必须调用 attach_ui(): slash 命令输出进入渲染层而非直写 stdout。"""

    def test_set_ready_attaches_ui(self, monkeypatch):
        from qingxiaotuan.tui.tui import QxtTUI

        class _FakeCtx:
            confirm = None

        class _FakeAgent:
            plan_mode = False

            def __init__(self):
                self.ctx = _FakeCtx()

        class _FakeConfig:
            def get(self, key, default=None):
                return {"model.provider": "openai", "model.model": "gpt-4o"}.get(key, default)

            def api_key(self):
                return "sk-test"

        tui = QxtTUI(on_submit=lambda x: None)
        calls = []
        tui.attach_ui = lambda: calls.append(True)  # 实例级替换, 记录调用
        monkeypatch.setattr(tui, "_show_welcome", lambda: None)
        tui.set_ready(_FakeConfig(), _FakeAgent(), ".")
        assert calls == [True]
