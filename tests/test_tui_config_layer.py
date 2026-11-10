"""第 13 轮：config_models + misc 组 5 个模块的对齐回归。

重点不是渲染细节，而是三条真实修正与两处几何一致性：
链式 replace 二次替换、发现失败冒充空列表、--add-dir 静默丢弃、
choice_at / choice_rows 同源、TabStrip.hit / render 同源。
"""
from __future__ import annotations

import pytest

from tuan_cli.tui import configkit
from tuan_cli.tui.configkit import additional_dirs as ad
from tuan_cli.tui.configkit import collaboration_modes as cm
from tuan_cli.tui.configkit import model_migration as mm
from tuan_cli.tui.configkit import sidebar_chooser as sc
from tuan_cli.tui.configkit import sidebar_tab_strip as st


# ---------------------------------------------------------------- additional_dirs
class TestAdditionalDirs:
    def test_warning_template_verbatim(self):
        assert ad.WARNING_TEMPLATE_EN == (
            "Ignoring --add-dir ({joined_paths}) because the effective "
            "permissions do not allow additional writable roots. Switch to "
            "workspace-write or danger-full-access to allow them.")
        assert ad.constants()["early_return_branches"] == 4

    def test_format_warning_joins_with_comma(self):
        w = ad.format_warning(["relative", "/abs"], zh=False)
        assert w == (
            "Ignoring --add-dir (relative, /abs) because the effective "
            "permissions do not allow additional writable roots. Switch to "
            "workspace-write or danger-full-access to allow them.")

    @pytest.mark.parametrize("profile", [
        ad.PermissionProfileView.workspace_write(),
        ad.PermissionProfileView.disabled(),
        ad.PermissionProfileView.external(),
        ad.PermissionProfileView(
            no_fs_sandbox_policy=False, has_full_disk_write_access=True),
    ])
    def test_four_early_returns(self, profile):
        assert ad.add_dir_warning_message(
            ["/tmp/extra"], profile, "/tmp/project") is None

    def test_empty_dirs_returns_none(self):
        assert ad.add_dir_warning_message(
            [], ad.PermissionProfileView.read_only(), "/tmp/project") is None

    def test_warns_for_read_only(self):
        w = ad.add_dir_warning_message(
            ["/tmp/extra"], ad.PermissionProfileView.read_only(),
            "/tmp/project", zh=False)
        assert w is not None and "Ignoring --add-dir (/tmp/extra)" in w

    def test_warns_when_can_write_elsewhere_but_not_cwd(self):
        w = ad.add_dir_warning_message(
            ["/tmp/extra"], ad.PermissionProfileView.managed_restricted(),
            "/tmp/project")
        assert w is not None and "已忽略" in w

    def test_decide_ignores_and_enforce_rejects(self):
        d = ad.decide_add_dirs(
            ["/tmp/extra"], ad.PermissionProfileView.read_only(),
            "/tmp/project")
        assert d.ignored is True
        assert d.reason == "permissions_do_not_allow"
        assert d.warning and d.actionable_hint
        assert d.effective_dirs == []
        e = ad.enforce(d)
        assert e["allowed"] is False and e["effective_dirs"] == []

    def test_decide_allows_when_cwd_writable(self):
        d = ad.decide_add_dirs(
            ["/tmp/extra"], ad.PermissionProfileView.workspace_write(),
            "/tmp/project")
        assert d.ignored is False
        assert ad.enforce(d)["effective_dirs"] == ["/tmp/extra"]

    def test_no_dirs(self):
        d = ad.decide_add_dirs(
            [], ad.PermissionProfileView.read_only(), "/tmp/project")
        assert d.ignored is False and d.reason == "no_additional_dirs"

    @pytest.mark.parametrize("bad", ["../escape", "a/../b", "", "x\x00y",
                                     "x\x07y", "x\x1b]8;;evil"])
    def test_path_validation_rejects(self, bad):
        d = ad.decide_add_dirs(
            [bad], ad.PermissionProfileView.workspace_write(), "/tmp/project")
        assert d.ignored is True
        assert d.reason == "invalid_paths"
        assert d.path_problems

    def test_add_dir_outside_cwd_is_not_rejected(self):
        """add-dir 的本意就是加工作区外的可写根，不能把'在 cwd 外'当错误。"""
        d = ad.decide_add_dirs(
            ["/elsewhere/extra"],
            ad.PermissionProfileView.workspace_write(), "/tmp/project")
        assert d.ignored is False

    def test_relative_path_ok(self):
        d = ad.decide_add_dirs(
            ["extra"], ad.PermissionProfileView.workspace_write(),
            "/tmp/project")
        assert d.ignored is False

    def test_warning_zh_localization(self):
        w = ad.add_dir_warning_message(
            ["/tmp/extra"], ad.PermissionProfileView.read_only(),
            "/tmp/project", zh=True)
        assert "已忽略" in w and "workspace-write" in w

    def test_to_dict_is_auditable(self):
        d = ad.decide_add_dirs(
            ["/tmp/extra"], ad.PermissionProfileView.read_only(),
            "/tmp/project")
        dd = d.to_dict()
        assert dd["ignored"] is True and dd["effective_dirs"] == []
        assert "warning" in dd and "actionable_hint" in dd


# ---------------------------------------------------------------- collaboration_modes
class TestCollaborationModes:
    def _catalog(self):
        return [
            cm.CollaborationModeMask(name="default",
                                     mode=cm.ModeKind.DEFAULT,
                                     model="local-a"),
            cm.CollaborationModeMask(name="plan", mode=cm.ModeKind.PLAN,
                                     model="local-b"),
            cm.CollaborationModeMask(name="hidden",
                                     mode=cm.ModeKind.HIDDEN,
                                     model="local-c"),
            cm.CollaborationModeMask(name="no-mode", mode=None),
        ]

    def test_constants(self):
        c = cm.constants()
        assert c["timeout_secs"] == 2
        assert c["request_prefix"] == "collaboration-mode-list-"
        assert c["mask_fields"] == [
            "name", "mode", "model", "reasoning_effort",
            "developer_instructions"]
        assert len(c["discovery_statuses"]) == 5

    def test_filtered_presets_only_tui_visible(self):
        masks = cm.filtered_presets(self._catalog())
        assert [m.name for m in masks] == ["default", "plan"]

    def test_default_mask_prefers_default(self):
        assert cm.default_mask(self._catalog()).name == "default"

    def test_default_mask_falls_back_to_first(self):
        cat = [cm.CollaborationModeMask(name="plan", mode=cm.ModeKind.PLAN)]
        assert cm.default_mask(cat).name == "plan"

    def test_default_mask_empty(self):
        assert cm.default_mask([]) is None

    def test_mask_for_kind_rejects_invisible(self):
        assert cm.mask_for_kind(self._catalog(), cm.ModeKind.HIDDEN) is None

    def test_mask_for_kind(self):
        assert cm.default_mode_mask(self._catalog()).name == "default"
        assert cm.plan_mask(self._catalog()).name == "plan"

    def test_next_mask_cycles(self):
        cat = self._catalog()
        presets = cm.filtered_presets(cat)
        assert cm.next_mask(cat, presets[0]).name == "plan"
        assert cm.next_mask(cat, presets[1]).name == "default"

    def test_next_mask_unknown_current_starts_at_zero(self):
        cat = self._catalog()
        other = cm.CollaborationModeMask(name="x", mode=cm.ModeKind.HIDDEN)
        assert cm.next_mask(cat, other).name == "default"
        assert cm.next_mask(cat, None).name == "default"

    def test_next_mask_empty(self):
        assert cm.next_mask([], None) is None

    def test_mask_from_wire_clears_developer_instructions(self):
        m, problems = cm.CollaborationModeMask(), []
        m = cm.mask_from_wire({
            "name": "plan", "mode": "Plan", "model": "m1",
            "reasoning_effort": "high",
            "developer_instructions": "SHOULD-BE-CLEARED"}, problems)
        assert problems == []
        assert m.developer_instructions is None
        assert m.prompts_omitted is True
        assert m.mode is cm.ModeKind.PLAN

    def test_mask_from_wire_rejects_unknown_field(self):
        problems = []
        cm.mask_from_wire({"name": "x", "server_secret": "S"}, problems)
        assert any("未知字段" in p for p in problems)

    @pytest.mark.parametrize("bad", ["x\x07y", "x\x1b]8;;evil", "a" * 600])
    def test_mask_from_wire_rejects_unsafe_string(self, bad):
        problems = []
        cm.mask_from_wire({"name": bad}, problems)
        assert problems

    def test_discover_ok(self):
        r = cm.discover(requester=lambda rid, p: {
            "data": [{"name": "default", "mode": "Default"}]})
        assert r.status is cm.DiscoveryStatus.OK
        assert r.usable and len(r.masks) == 1
        assert r.request_id.startswith(cm.DISCOVERY_REQUEST_PREFIX)

    def test_discover_empty_is_distinct_from_unavailable(self):
        r = cm.discover(requester=lambda rid, p: {"data": []})
        assert r.status is cm.DiscoveryStatus.EMPTY and r.usable

    def test_discover_failure_is_unavailable_not_empty(self):
        """本轮修正：上游把失败压成空 Vec，这里必须可区分。"""
        def boom(_rid, _p):
            raise RuntimeError("network down")
        r = cm.discover(requester=boom)
        assert r.status is cm.DiscoveryStatus.UNAVAILABLE
        assert r.usable is False and r.warning

    def test_discover_timeout(self):
        def slow(_rid, _p):
            raise TimeoutError()
        r = cm.discover(requester=slow)
        assert r.status is cm.DiscoveryStatus.TIMEOUT
        assert r.usable is False

    def test_discover_no_requester(self):
        r = cm.discover()
        assert r.status is cm.DiscoveryStatus.UNAVAILABLE

    def test_discover_protocol_error(self):
        r = cm.discover(requester=lambda rid, p: {"nope": 1})
        assert r.status is cm.DiscoveryStatus.PROTOCOL_ERROR

    def test_discover_clock_timeout(self):
        ticks = iter([0.0, 5.0])
        r = cm.discover(requester=lambda rid, p: {"data": []},
                        timeout_secs=2, clock=lambda: next(ticks))
        assert r.status is cm.DiscoveryStatus.TIMEOUT

    def test_to_dict(self):
        r = cm.discover(requester=lambda rid, p: {"data": []})
        d = r.to_dict()
        assert d["status"] == "empty" and d["usable"] is True


# ---------------------------------------------------------------- model_migration
class TestModelMigration:
    def test_constants(self):
        c = mm.constants()
        assert c["outcomes"] == ["Accepted", "Rejected", "Exit"]
        assert c["menu_options"] == ["TryNewModel", "UseExistingModel"]
        assert c["labels_en"] == ["Try new model", "Use existing model"]
        assert c["heading_en"] == (
            "Codex just got an upgrade. Introducing {display}.")

    def test_labels_zh_localization(self):
        assert mm.MigrationMenuOption.TRY_NEW_MODEL.label() == "试用新模型"
        assert mm.MigrationMenuOption.USE_EXISTING_MODEL.label(
            zh=False) == "Use existing model"

    def test_fill_markdown_single_pass(self):
        """本轮修正：链式 replace 的二次替换缺陷。"""
        tpl = "从 {model_from} 迁移到 {model_to}"
        cur, tgt = "old-{model_to}-x", "NEW"
        out = mm.fill_migration_markdown(tpl, cur, tgt)
        assert out == "从 old-{model_to}-x 迁移到 NEW"
        assert "old-NEW-x" not in out

    def test_fill_markdown_unknown_placeholder_preserved(self):
        out = mm.fill_migration_markdown(
            "{model_from} -> {model_to} / {unknown}", "A", "B")
        assert out == "A -> B / {unknown}"

    def test_copy_markdown_branch(self):
        c = mm.migration_copy_for_models(
            "old", "new", target_display_name="New",
            migration_markdown="**{model_from}** => {model_to}",
            can_opt_out=True)
        assert c.markdown == "**old** => new"
        assert c.heading == [] and c.content == []

    def test_copy_default_branch(self):
        c = mm.migration_copy_for_models(
            "old", "new", target_display_name="New Model", zh=False)
        assert c.heading == [
            "Codex just got an upgrade. Introducing New Model."]
        assert c.content[0] == (
            "We recommend switching from old to new.")
        assert "better performance and reliability" in c.content[2]
        assert not any("You can continue" in x for x in c.content)
        assert c.can_opt_out is False

    def test_copy_with_custom_description_and_link(self):
        c = mm.migration_copy_for_models(
            "old", "new", target_display_name="New",
            target_description="Custom desc", model_link="https://e.com",
            can_opt_out=True, zh=False)
        assert "Custom desc" in c.content[2]
        assert "https://e.com" in c.content[2]
        assert "You can continue using old if you prefer." in c.content

    def test_copy_custom_migration_copy_skips_recommendation(self):
        c = mm.migration_copy_for_models(
            "old", "new", target_display_name="New",
            migration_copy="Server supplied copy", zh=False)
        assert "We recommend switching" not in "".join(c.content)
        assert "Server supplied copy" in c.content

    def test_ctrl_exit_combo(self):
        assert mm.is_ctrl_exit_combo(frozenset({"CONTROL"}), "c") is True
        assert mm.is_ctrl_exit_combo(frozenset({"CONTROL"}), "d") is True
        assert mm.is_ctrl_exit_combo(frozenset({"CONTROL"}), "x") is False
        assert mm.is_ctrl_exit_combo(frozenset(), "c") is False

    def test_mandatory_esc_accepts(self):
        """上游既有键盘策略：强制迁移 Esc 也接受（如实保留，非 fail-closed）。"""
        s = mm.ModelMigrationScreen(mm.ModelMigrationCopy(can_opt_out=False))
        s.handle_key("Esc")
        assert s.is_done()
        assert s.outcome_value() is mm.ModelMigrationOutcome.ACCEPTED
        assert "强制迁移" in s.policy_note()

    def test_mandatory_enter_accepts(self):
        s = mm.ModelMigrationScreen(mm.ModelMigrationCopy(can_opt_out=False))
        s.handle_key("Enter")
        assert s.outcome_value() is mm.ModelMigrationOutcome.ACCEPTED

    def test_mandatory_ctrl_c_exits(self):
        s = mm.ModelMigrationScreen(mm.ModelMigrationCopy(can_opt_out=False))
        s.handle_key("c", frozenset({"CONTROL"}))
        assert s.outcome_value() is mm.ModelMigrationOutcome.EXIT

    def test_optional_menu_keys(self):
        s = mm.ModelMigrationScreen(mm.ModelMigrationCopy(can_opt_out=True))
        s.handle_key("j")
        assert s.highlighted_option is mm.MigrationMenuOption.USE_EXISTING_MODEL
        s2 = mm.ModelMigrationScreen(mm.ModelMigrationCopy(can_opt_out=True))
        s2.handle_menu_key("2")
        assert s2.outcome_value() is mm.ModelMigrationOutcome.REJECTED
        s3 = mm.ModelMigrationScreen(mm.ModelMigrationCopy(can_opt_out=True))
        s3.handle_menu_key("1")
        assert s3.outcome_value() is mm.ModelMigrationOutcome.ACCEPTED

    def test_optional_esc_confirms_highlight_not_cancel(self):
        s = mm.ModelMigrationScreen(mm.ModelMigrationCopy(can_opt_out=True))
        s.handle_key("j")       # highlight UseExistingModel
        s.handle_key("Esc")     # 上游：确认当前选中，不是取消
        assert s.outcome_value() is mm.ModelMigrationOutcome.REJECTED
        assert "不是取消" in s.policy_note()

    def test_release_key_ignored(self):
        s = mm.ModelMigrationScreen(mm.ModelMigrationCopy(can_opt_out=False))
        s.handle_key("Enter", kind="Release")
        assert not s.is_done()

    def test_event_stream_end_defaults_to_accept(self):
        out = mm.run_model_migration_prompt(
            mm.ModelMigrationCopy(can_opt_out=False), events=[])
        assert out is mm.ModelMigrationOutcome.ACCEPTED

    def test_event_sequence(self):
        out = mm.run_model_migration_prompt(
            mm.ModelMigrationCopy(can_opt_out=True),
            events=[("2", frozenset(), "Press")])
        assert out is mm.ModelMigrationOutcome.REJECTED

    def test_alt_screen_guard_restores_on_exception(self):
        calls = []
        class FakeTui:
            def enter_alt_screen(self):
                calls.append("enter")
            def leave_alt_screen(self):
                calls.append("leave")
                raise RuntimeError("restore failed")  # 异常也必须走完
        g = mm.AltScreenGuard(FakeTui())
        with g:
            assert calls == ["enter"]
        assert calls == ["enter", "leave"]
        assert g.entered is False

    def test_audit_trail(self):
        s = mm.ModelMigrationScreen(mm.ModelMigrationCopy(can_opt_out=True))
        s.handle_key("j"); s.handle_key("2")
        assert any(e["event"] == "highlight" for e in s.audit_trail)
        assert s.audit_trail[-1]["outcome"] == "Rejected"


# ---------------------------------------------------------------- sidebar_tab_strip
class TestSidebarTabStrip:
    def test_constants(self):
        c = st.constants()
        assert (c["plus_width"], c["right_reserve"], c["add_label"]) == \
            (3, 1, " + ")
        assert c["states"] == ["Absent", "Active", "Inactive"]

    def test_rect_contains_half_open(self):
        r = st.Rect(0, 0, 10, 1)
        assert r.contains(0, 0) and r.contains(9, 0)
        assert not r.contains(10, 0) and not r.contains(-1, 0)
        assert not r.contains(0, 1)

    def test_targets_geometry(self):
        ts = st.TabStrip(ids=("a", "b", "c"), selected="b", tab_width=11)
        tabs, add = ts.targets(st.Rect(0, 0, 40, 1))
        # width=39, plus=3, available=36, tab_width=11, count=3
        assert len(tabs) == 3
        assert add.to_dict() == {"x": 36, "y": 0, "width": 3, "height": 1}
        assert [t[2].x for t in tabs] == [0, 11, 22]

    def test_add_button_kept_when_narrow(self):
        ts = st.TabStrip(ids=("a", "b", "c"), selected="c", tab_width=11)
        tabs, add = ts.targets(st.Rect(0, 0, 6, 1))
        # width=5, plus=3, available=2, tab_width=2, count=1
        assert len(tabs) == 1
        assert add.width == 3 and add.x == 2

    def test_selected_tab_stays_visible_when_space_runs_out(self):
        ids = tuple(f"s{i}" for i in range(20))
        ts = st.TabStrip(ids=ids, selected="s18", tab_width=11)
        tabs, _ = ts.targets(st.Rect(0, 0, 40, 1))
        assert len(tabs) == 3
        assert any(t[1] == "s18" for t in tabs), "选中 tab 必须仍可见"

    def test_tab_width_zero_does_not_crash(self):
        ts = st.TabStrip(ids=("a",), tab_width=0)
        tabs, add = ts.targets(st.Rect(0, 0, 40, 1))
        assert tabs == [] and add.width == 3

    def test_hit_add_takes_priority(self):
        ts = st.TabStrip(ids=("a", "b"), selected="a", tab_width=11)
        _, add = ts.targets(st.Rect(0, 0, 40, 1))
        t = ts.hit(st.Rect(0, 0, 40, 1), add.x + 1, 0)
        assert t.kind is st.TabTargetKind.ADD

    def test_hit_tab(self):
        ts = st.TabStrip(ids=("a", "b", "c"), selected="a", tab_width=11)
        t = ts.hit(st.Rect(0, 0, 40, 1), 12, 0)
        assert t.kind is st.TabTargetKind.TAB and t.id == "b" and t.index == 1

    def test_hit_outside_returns_none(self):
        ts = st.TabStrip(ids=("a",), tab_width=11)
        assert ts.hit(st.Rect(0, 0, 40, 1), 100, 100) is None
        assert ts.hit(st.Rect(0, 0, 40, 1), -1, 0) is None

    def test_render_plan_states(self):
        ts = st.TabStrip(ids=("a", "b"), selected="b", tab_width=11)
        plan = ts.render_plan(st.Rect(0, 0, 40, 1),
                              st.TabState.ABSENT, st.TabState.ACTIVE,
                              lambda i, ident: f" T{i} ")
        assert plan[-1]["label"] == " + "
        assert plan[-1]["state"] == "Absent"
        assert plan[1]["state"] == "Active"   # selected
        assert plan[0]["state"] == "Absent"

    def test_render_plan_active_add_overrides_selected(self):
        ts = st.TabStrip(ids=("a",), selected="a", tab_width=11)
        plan = ts.render_plan(st.Rect(0, 0, 40, 1),
                              st.TabState.ACTIVE, st.TabState.ACTIVE,
                              lambda i, ident: " T ")
        assert plan[0]["state"] == "Absent"   # add_state != Absent
        assert plan[-1]["state"] == "Active"

    def test_style_tokens(self):
        assert st.style_token(st.TabState.ACTIVE) == "selection/no-underline"
        assert st.style_token(st.TabState.INACTIVE) == "active-tab"
        assert st.style_token(st.TabState.ABSENT) == "secondary-text"

    def test_hit_matches_render(self):
        ts = st.TabStrip(ids=("a", "b", "c"), selected="b", tab_width=11)
        assert ts.hit_test_matches_render(
            st.Rect(0, 0, 40, 1), st.TabState.ABSENT,
            st.TabState.ACTIVE, lambda i, ident: f" T{i} ") == []


# ---------------------------------------------------------------- sidebar_chooser
class TestSidebarChooser:
    def test_constants(self):
        c = sc.constants()
        assert c["wide_width"] == 58
        assert c["chat_tab"] == " Side chat " and c["chat_tab_width"] == 11
        assert c["resize_short_hint"] == "←/→ resize · Enter/Esc done"
        assert c["body_row_shrink"] == 3
        assert c["choice_start_offset"] == 4

    def test_body_row(self):
        assert sc.body_row(sc.Rect(5, 0, 80, 20), 3).to_dict() == {
            "x": 6, "y": 3, "width": 77, "height": 1}

    def test_resize_hint_short_when_narrow(self):
        text, short = sc.resize_hint("一段很长的提示" * 20, 10)
        assert short is True and text == sc.RESIZE_SHORT_HINT

    def test_resize_hint_full_when_wide(self):
        text, short = sc.resize_hint("short", 40)
        assert short is False and text == "short"

    def test_footer_fixed_three_hints(self):
        hints = sc.footer(zh=False)
        assert [(h.key, h.action) for h in hints] == [
            ("Enter", "open"), ("Esc", "back"), ("↑/↓", "move")]

    def test_footer_optional_hide_pane(self):
        class Keymap:
            def primary_hint(self, ctx, action):
                assert (ctx, action) == ("Global", "hide_pane")
                class H:
                    def display_label(self):
                        return "Ctrl+B"
                return H()
        hints = sc.footer(Keymap(), zh=False)
        assert hints[-1] == sc.FooterHint("Ctrl+B", "hide pane")

    def test_footer_no_hide_pane_when_absent(self):
        class Keymap:
            def primary_hint(self, ctx, action):
                return None
        assert len(sc.footer(Keymap())) == 3

    def test_chat_tabs_tab_width(self):
        ts = sc.chat_tabs(["a"], "a")
        assert ts.tab_width == len(sc.CHAT_TAB) == 11

    def test_tab_label_single_and_multiple(self):
        assert sc.tab_label(0, ["a"]) == " Side chat "
        assert sc.tab_label(1, ["a", "b"]) == " Side 2 "

    def test_choice_rows_wide_single_line(self):
        area = sc.Rect(0, 0, 80, 20)   # body width 77 >= 58
        height, rows = sc.choice_rows(area, 3, 1)
        assert height == 1 and list(rows) == [0, 1, 2]

    def test_choice_rows_narrow_two_lines(self):
        area = sc.Rect(0, 0, 40, 20)   # body width 37 < 58
        height, rows = sc.choice_rows(area, 3, 1)
        assert height == 2 and list(rows) == [0, 1, 2]

    def test_choice_rows_clamps_choice(self):
        area = sc.Rect(0, 0, 80, 20)
        _, rows = sc.choice_rows(area, 3, 999)
        assert list(rows) == [0, 1, 2]

    def test_choice_rows_keeps_selected_visible(self):
        area = sc.Rect(0, 0, 40, 8)   # visible = ceil(3/2) = 2
        _, rows = sc.choice_rows(area, 10, 8)
        assert 8 in list(rows)

    def test_choice_at_matches_rows(self):
        area = sc.Rect(0, 0, 80, 20)
        assert sc.choice_at(area, 3, 0, 4) == 0
        assert sc.choice_at(area, 3, 0, 5) == 1
        assert sc.choice_at(area, 3, 0, 6) == 2

    def test_choice_at_narrow_two_lines_same_option(self):
        area = sc.Rect(0, 0, 40, 20)
        assert sc.choice_at(area, 3, 0, 4) == 0
        assert sc.choice_at(area, 3, 0, 5) == 0  # detail 行仍属选项 0
        assert sc.choice_at(area, 3, 0, 6) == 1

    def test_choice_at_footer_and_out_of_range(self):
        area = sc.Rect(0, 0, 80, 20)
        assert sc.choice_at(area, 3, 0, 19) is None   # footer 行
        assert sc.choice_at(area, 3, 0, 3) is None     # 标题上方
        assert sc.choice_at(area, 3, 0, -1) is None
        assert sc.choice_at(area, 0, 0, 4) is None

    def test_choice_detail_new_side_chat_is_last(self):
        title, detail = sc.choice_detail(2, ["a", "b"], zh=False)
        assert title == "+ New side chat"
        assert detail == "Start from the main chat"

    def test_choice_detail_reopen(self):
        title, detail = sc.choice_detail(1, ["a", "b"], zh=False)
        assert title == "Side chat 2" and detail == "Reopen side chat"

    def test_paint_heading_and_new_side_chat(self):
        plan = sc.paint(True, sc.Rect(0, 0, 80, 20), ["a"], 0, zh=False)
        texts = [r["text"] for r in plan["rows"]]
        assert any("Open in sidebar" in t for t in texts)
        assert any("+ New side chat" in t for t in texts)
        assert plan["focused"] is True

    def test_paint_empty_area(self):
        plan = sc.paint(True, sc.Rect(0, 0, 0, 0), ["a"], 0)
        assert plan["rows"] == []

    def test_paint_resize_hint_uses_short_when_narrow(self):
        plan = sc.paint(True, sc.Rect(0, 0, 20, 20), ["a"], 0,
                        resize="一段很长很长的提示" * 10)
        assert plan["footer"][0]["short"] is True

    def test_paint_footer_fallback(self):
        plan = sc.paint(True, sc.Rect(0, 0, 80, 20), ["a"], 0, zh=False)
        assert plan["footer"][0]["text"] == "Enter/open"

    def test_hit_matches_render_wide(self):
        assert sc.hit_test_matches_render(
            sc.Rect(0, 0, 80, 20), ["s1", "s2"], 1) == []

    def test_hit_matches_render_narrow(self):
        assert sc.hit_test_matches_render(
            sc.Rect(0, 0, 40, 20), ["s1", "s2"], 0) == []

    def test_text_width_cjk(self):
        assert sc._text_width("abc") == 3
        assert sc._text_width("中文") == 4
        assert sc._text_width("a中b") == 4


# ---------------------------------------------------------------- package
class TestConfigkitPackage:
    def test_report(self):
        r = configkit.configkit_report()
        assert r["modules"] == 5
        assert r["upstream_groups"] == ["config_models", "misc"]

    def test_validate_clean(self):
        assert configkit.configkit_validate() == []

    def test_parity_includes_configkit(self):
        from tuan_cli.tui.parity import parity_report, parity_validate
        r = parity_report()
        assert r["configkit"]["modules"] == 5
        assert r["matrix"]["pending"] == 0
        assert r["matrix"]["by_status"]["aligned"] == 45
        assert r["matrix"]["coverage_pct"] == 100.0
        assert r["matrix"]["depth_verified"] == 10
        assert r["matrix"]["fully_identical"] is False
        assert r["corekit"]["security_wiring"]["intact"] is True
        assert parity_validate() == []

    def test_gaps_no_longer_contain_round13_modules(self):
        from tuan_cli.tui.parity import matrix
        gaps = {m for _, m in matrix.gaps()}
        for m in ("additional_dirs", "collaboration_modes",
                  "model_migration", "sidebar_chooser",
                  "sidebar_tab_strip"):
            assert m not in gaps
        assert len(gaps) == 0
