"""TUI 与 Codex 对齐层回归（规格 / 键位 / 文案 / 矩阵 / CLI）。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tuan_cli.tui.parity import (
    upstream_spec as u, keymap as k, i18n as i, matrix as mx,
    parity_report, parity_validate,
)
from tuan_cli.ui.approval_overlay import (
    ApprovalDecision, ApprovalRequest, resolve_decision,
)


# ---------------------------------------------------------------- 规格事实
class TestUpstreamSpec:
    def test_scale_is_corrected(self):
        """口径更正：完整解压后是 1216 / 492414，不是上一轮的 567 / 247k。"""
        assert u.SCALE["top_level_modules"] == 165
        assert u.SCALE["rs_files"] == 1216
        assert u.SCALE["rs_lines"] == 492414
        assert u.SCALE["snapshot_files_skipped"] == 1491
        assert u.SCALE["license"] == "Apache-2.0"

    def test_module_tree_has_exactly_165(self):
        assert len(u.TOP_LEVEL_MODULES) == 165
        for key in ("keymap", "approval_events", "ui_consts", "bottom_pane",
                    "diff_render", "worktree_startup"):
            assert key in u.TOP_LEVEL_MODULES

    def test_groups_reference_only_real_modules(self):
        for group, mods in u.MODULE_GROUPS.items():
            for m in mods:
                assert m in u.TOP_LEVEL_MODULES, f"{group}: {m}"

    @pytest.mark.parametrize("name,value", [
        ("LIVE_PREFIX_COLS", 2), ("MAX_POPUP_ROWS", 8),
        ("MIN_LIST_WIDTH_FOR_SIDE", 40), ("SIDE_CONTENT_GAP", 2),
        ("MENU_SURFACE_HORIZONTAL_INSET", 4), ("MAX_KEY_CHORD_STROKES", 2),
    ])
    def test_layout_constants(self, name, value):
        assert u.LAYOUT_CONSTANTS[name] == value
        assert u.layout(name) == value

    def test_unknown_layout_raises(self):
        with pytest.raises(KeyError):
            u.layout("NO_SUCH_CONST")


class TestKeySpecNormalization:
    @pytest.mark.parametrize("raw,expected", [
        ("ctrl-a", "ctrl-a"),
        ("Control-A", "ctrl-a"),
        ("ALT-shift-Enter", "alt-shift-enter"),
        ("cmd-x", "super-x"),
        ("escape", "esc"),
        ("return", "enter"),
        ("pageup", "page-up"),
        ("pgdn", "page-down"),
        ("del", "delete"),
        ("ctrl-alt-shift-super-a", "ctrl-alt-shift-super-a"),
        ("f3", "f3"),
    ])
    def test_normalize(self, raw, expected):
        assert u.normalize_key_spec(raw) == expected

    def test_chord(self):
        assert u.normalize_key_spec("ctrl-x ctrl-s") == "ctrl-x ctrl-s"
        assert u.normalize_key_spec("leader c") == "leader c"

    def test_chord_too_long(self):
        with pytest.raises(u.KeySpecError):
            u.normalize_key_spec("a b c")

    def test_leader_requires_completion(self):
        with pytest.raises(u.KeySpecError):
            u.normalize_key_spec("leader")
        with pytest.raises(u.KeySpecError):
            u.normalize_key_spec("leader a b")

    def test_duplicate_modifier_rejected(self):
        with pytest.raises(u.KeySpecError):
            u.normalize_key_spec("ctrl-ctrl-a")

    def test_missing_key_rejected(self):
        with pytest.raises(u.KeySpecError):
            u.normalize_key_spec("ctrl-")
        with pytest.raises(u.KeySpecError):
            u.normalize_key_spec("")

    def test_modifier_after_key_rejected(self):
        with pytest.raises(u.KeySpecError):
            u.normalize_key_spec("a-ctrl")

    def test_unknown_key_rejected(self):
        with pytest.raises(u.KeySpecError):
            u.normalize_key_spec("ctrl-bogus")


# ---------------------------------------------------------------- 键位
class TestRuntimeKeymap:
    def test_defaults_are_conflict_free(self):
        km = k.RuntimeKeymap.defaults()
        assert km.validate_conflicts() == []
        cov = km.coverage()
        assert cov["contexts"] == 8
        assert cov["actions_with_binding"] > 70
        assert cov["conflicts"] == 0

    @pytest.mark.parametrize("ctx,action,expected", [
        ("app", "open_transcript", "ctrl-t"),
        ("app", "copy", "ctrl-o"),
        ("chat", "interrupt_turn", "esc"),
        ("composer", "submit", "enter"),
        ("composer", "history_search_previous", "ctrl-r"),
        ("approval", "approve", "y"),
        ("approval", "approve_for_session", "a"),
        ("approval", "approve_for_prefix", "p"),
        ("approval", "deny", "d"),
        ("approval", "decline", "esc"),
        ("approval", "cancel", "c"),
        ("list", "accept", "enter"),
        ("pager", "half_page_up", "ctrl-u"),
        ("agents", "stop", "x"),
    ])
    def test_primary_hint_matches_upstream(self, ctx, action, expected):
        assert k.RuntimeKeymap.defaults().primary_hint(ctx, action) == expected

    def test_resolve(self):
        km = k.RuntimeKeymap.defaults()
        assert km.resolve("approval", "y") == "approve"
        assert km.resolve("approval", "p") == "approve_for_prefix"
        assert km.resolve("pager", "ctrl-c") == "fixed.interrupt_or_quit"
        assert km.resolve("approval", "zzz") is None

    def test_context_override_precedence(self):
        km = k.RuntimeKeymap.from_config(
            {"composer": {"submit": ["ctrl-enter"]}})
        assert km.primary_hint("composer", "submit") == "ctrl-enter"
        assert km.primary_hint("list", "accept") == "enter"  # 未受影响

    def test_global_fallback(self):
        km = k.RuntimeKeymap.from_config(
            {"global": {"open_transcript": ["f9"]}})
        assert km.primary_hint("app", "open_transcript") == "f9"

    def test_explicit_unbind(self):
        km = k.RuntimeKeymap.from_config({"composer": {"submit": []}})
        assert km.bindings_for("composer", "submit") == ()
        assert km.primary_hint("composer", "submit") is None

    def test_null_also_unbinds(self):
        km = k.RuntimeKeymap.from_config({"composer": {"submit": None}})
        assert km.bindings_for("composer", "submit") == ()

    def test_fixed_key_cannot_be_rebound(self):
        with pytest.raises(k.KeymapConflict) as e:
            k.RuntimeKeymap.from_config({"chat": {"toggle_voice": "ctrl-c"}})
        assert "保留键" in str(e.value)

    def test_duplicate_in_same_context_conflicts(self):
        with pytest.raises(k.KeymapConflict) as e:
            k.RuntimeKeymap.from_config(
                {"chat": {"toggle_voice": "f8", "toggle_voice_mute": "f8"}})
        assert "同时绑定" in str(e.value)

    def test_same_key_in_different_contexts_ok(self):
        km = k.RuntimeKeymap.from_config(
            {"chat": {"toggle_voice": "f8"}, "app": {"open_warnings": "f8"}})
        assert km.validate_conflicts() == []

    def test_unknown_action_reported(self):
        with pytest.raises(k.KeymapConflict) as e:
            k.RuntimeKeymap.from_config({"composer": {"fly": "f1"}})
        assert "未知动作" in str(e.value)

    def test_unknown_context_reported(self):
        with pytest.raises(k.KeymapConflict) as e:
            k.RuntimeKeymap.from_config({"nope": {"submit": "f1"}})
        assert "未知 context" in str(e.value)

    def test_bad_binding_value_reported(self):
        with pytest.raises(k.KeymapConflict):
            k.RuntimeKeymap.from_config({"composer": {"submit": 123}})

    def test_localized_overrides_do_not_change_keys(self):
        """本地化只改文案/模型/路径，键位保持与上游完全相同。"""
        assert k.TUAN_KEYMAP_OVERRIDES == {}


# ---------------------------------------------------------------- 文案
class TestParityI18n:
    def test_en_and_zh_cn_are_complete(self):
        assert i.translated_count("en") == i.total_keys()
        assert i.translated_count("zh-CN") == i.total_keys()

    def test_ten_languages_available(self):
        assert len(i.available_languages()) == 10
        for lang in ("en", "zh-CN", "ja", "de", "pt-BR"):
            assert lang in i.available_languages()

    def test_localized_text_differs_from_english(self):
        assert i.pt("approval.approve", lang="en") == "Yes"
        assert i.pt("approval.approve", lang="zh-CN") == "确认，仅本次"

    def test_format_kwargs(self):
        assert i.pt("hint.transcript", lang="en", shortcut="Ctrl+T") == \
               "Ctrl+T to view transcript"
        assert "Ctrl+T" in i.pt("hint.transcript", lang="zh-CN", shortcut="Ctrl+T")

    def test_unknown_language_falls_back_to_english(self):
        assert i.pt("approval.cancel", lang="xx-XX") in (
            "Cancel", "中止")  # 项目默认 zh-CN 时可能命中中文

    def test_unknown_key_returns_key(self):
        assert i.pt("no.such.key", lang="en") == "no.such.key"

    def test_bad_format_kwargs_never_empty(self):
        assert i.pt("hint.transcript", lang="en", wrong="x")


# ---------------------------------------------------------------- 矩阵
class TestMatrix:
    def test_validate_clean(self):
        assert mx.validate() == []

    def test_status_covers_all_165(self):
        rows = mx.parity_status()
        assert len(rows) == 165
        assert {r.status for r in rows} <= set(mx._STATUSES)

    def test_summary_metrics(self):
        """第 12 轮基线（core_app 9 个转 aligned）：pending 24 -> 15。"""
        s = mx.summary()
        assert s["total_modules"] == 165
        assert s["pending"] == 15
        assert s["by_status"]["aligned"] == 30
        assert s["coverage_pct"] == 90.9
        assert s["aligned_pct"] == 52.7
        assert s["aligned_only_pct"] == 18.2
        assert s["fully_identical"] is False   # 如实：还没完全相同
        assert s["upstream_rs_files"] == 1216
        # 派生一致性：防止以后改状态定义凑数而测试没发现
        assert s["settled"] == sum(s["by_status"][k] for k in
                                   ("aligned", "localized", "not_applicable"))
        assert s["coverage_pct"] == round(s["settled"] * 100 / 165, 1)

    def test_aligned_items_have_notes(self):
        """每个 aligned 都必须能指向实现/测试，不能空标注。"""
        for r in mx.parity_status():
            if r.status == mx.ALIGNED:
                assert r.note.strip(), f"{r.module} 缺少落点说明"

    def test_gaps_are_pending_modules(self):
        gaps = mx.gaps()
        assert len(gaps) == mx.summary()["pending"]  # 派生，不硬编码
        pending = {r.module for r in mx.parity_status()
                   if r.status == mx.PENDING}
        assert {m for _, m in gaps} == pending

    def test_group_summary_totals(self):
        gs = mx.group_summary()
        assert gs and all(set(c) >= set(mx._STATUSES) for c in gs.values())

    def test_report_and_validate(self):
        r = parity_report()
        assert r["scale"]["rs_files"] == 1216
        assert r["matrix"]["total_modules"] == 165
        assert r["keymap"]["conflicts"] == 0
        assert parity_validate() == []


# ---------------------------------------------------------------- 审批键位对齐
class TestApprovalKeymapParity:
    def _req(self):
        return ApprovalRequest(kind="exec", title="t")

    @pytest.mark.parametrize("raw,decision", [
        ("y", ApprovalDecision.ONCE),
        ("a", ApprovalDecision.SESSION),
        ("p", ApprovalDecision.PREFIX),
        ("d", ApprovalDecision.DENY),
        ("n", ApprovalDecision.DECLINE),
        ("c", ApprovalDecision.ABORT),
    ])
    def test_codex_keys(self, raw, decision):
        assert resolve_decision(raw, self._req()) == decision

    def test_legacy_localized_aliases_still_work(self):
        """上一轮 Tuan 键位作为本地化兼容别名保留。"""
        assert resolve_decision("s", self._req()) == ApprovalDecision.SESSION
        assert resolve_decision("是", self._req()) == ApprovalDecision.ONCE
        assert resolve_decision("否", self._req()) == ApprovalDecision.DENY

    def test_esc_is_abort_localized_hardening(self):
        """本地化增强：Esc 仍为 ABORT（比上游 decline 更严格，文档如实标注）。"""
        assert resolve_decision("esc", self._req()) == ApprovalDecision.ABORT

    def test_prefix_is_a_grant(self):
        assert ApprovalDecision.PREFIX.granted
        assert not ApprovalDecision.DECLINE.granted

    def test_route_scope(self):
        from tuan_cli.ui.approval_overlay import route_decision
        req = ApprovalRequest(kind="exec", title="t")
        assert route_decision(req, ApprovalDecision.PREFIX)["scope"] == "prefix"
        assert route_decision(req, ApprovalDecision.SESSION)["scope"] == "session"
        assert route_decision(req, ApprovalDecision.DENY)["scope"] == "none"

    def test_default_options_use_codex_hints(self):
        req = self._req()
        hints = [o.hint for o in req.options]
        assert any(h.startswith("y") for h in hints)
        assert any(h.startswith("a") for h in hints)
        assert any(h.startswith("p") for h in hints)
        assert any(h.startswith("d") for h in hints)


# ---------------------------------------------------------------- CLI
class TestParityCLI:
    def test_human_report(self, capsys):
        from tuan_cli.cli.cmd_tui_parity import cmd_tui_parity
        args = type("A", (), {"report_json": False, "gaps": False})()
        assert cmd_tui_parity(args) == 0
        out = capsys.readouterr().out
        assert "1216" in out and "165" in out and "90.9%" in out
        assert "完全相同  : 否" in out

    def test_json_report(self, capsys):
        from tuan_cli.cli.cmd_tui_parity import cmd_tui_parity
        args = type("A", (), {"report_json": True, "gaps": True})()
        assert cmd_tui_parity(args) == 0
        data = json.loads(capsys.readouterr().out)
        assert data["matrix"]["total_modules"] == 165
        assert len(data["gaps"]) == 15
        assert data["validate"] == []

    def test_gaps_human(self, capsys):
        from tuan_cli.cli.cmd_tui_parity import cmd_tui_parity
        args = type("A", (), {"report_json": False, "gaps": True})()
        assert cmd_tui_parity(args) == 0
        assert "待对齐队列 (15)" in capsys.readouterr().out


# ---------------------------------------------------------------- 归属
class TestAttribution:
    def test_license_and_notice_verbatim(self):
        root = Path(__file__).resolve().parents[1]
        lic = (root / "THIRD_PARTY_LICENSES" / "Codex-LICENSE.txt").read_text()
        notice = (root / "NOTICE").read_text()
        assert "Apache License" in lic and "Version 2.0" in lic
        assert "openai/codex" in notice
        assert "1216" in notice and "492414" in notice  # 更正后的口径

    def test_parity_doc_exists(self):
        root = Path(__file__).resolve().parents[1]
        doc = (root / "TUI_PARITY.md").read_text()
        assert "1216" in doc and "492414" in doc
        assert "完全相同" in doc and "本地化" in doc
