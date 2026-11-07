"""第 12 轮：core_app 组 9 个模块的对齐回归。

每个测试类对应一个上游模块。重点是**安全契约**而非渲染细节：
脱敏、审批冲突、跨会话失效、双生命周期忙状态、既有安全接线保护。
"""
from __future__ import annotations

import os

import pytest

from tuan_cli.tui import corekit
from tuan_cli.tui.corekit import app as ck_app
from tuan_cli.tui.corekit import app_backtrack as bt
from tuan_cli.tui.corekit import app_command as cmd
from tuan_cli.tui.corekit import app_event as ev
from tuan_cli.tui.corekit import app_event_sender as sender
from tuan_cli.tui.corekit import app_info as info
from tuan_cli.tui.corekit import chatwidget as cw
from tuan_cli.tui.corekit import cli as ck_cli
from tuan_cli.tui.corekit import resize_reflow_cap as cap


# ---------------------------------------------------------------- app_command
class TestAppCommand:
    def test_redacted_never_leaks(self):
        r = cmd.RealtimeOfferSdp("ICE-ufrag:SECRET-CREDENTIAL")
        assert repr(r) == "<redacted>"
        assert str(r) == "<redacted>"
        assert f"{r}" == "<redacted>"
        assert r.serialize() == "<redacted>"
        assert r.to_dict() == "<redacted>"
        assert "SECRET" not in str([r]) and "SECRET" not in str({"k": r})

    def test_reveal_is_only_exit_and_counted(self):
        r = cmd.RealtimeSpeechText("private words")
        assert r.reveal_count == 0
        assert r.reveal() == "private words"
        assert r.reveal_count == 1
        assert str(r) == "<redacted>"

    def test_command_recording_redacts(self):
        c = cmd.AppCommand(cmd.CommandKind.USER_TURN, {
            "offer": cmd.RealtimeOfferSdp("ICE-SECRET"),
            "speech": cmd.RealtimeSpeechText("SECRET-SPOKEN"),
        })
        j = c.to_json()
        assert "ICE-SECRET" not in j and "SECRET-SPOKEN" not in j
        assert j.count("<redacted>") == 2

    def test_user_verification_proof_not_serialized(self):
        r = cmd.UserVerificationResponse(
            cmd.UserVerificationResponseKind.ACCEPT,
            proof=cmd.RealtimeOfferSdp("PROOF-VALUE"))
        assert "PROOF-VALUE" not in str(r.to_dict())
        assert r.wire_proof() == "PROOF-VALUE"

    def test_constructors(self):
        assert cmd.AppCommand.interrupt().kind is cmd.CommandKind.INTERRUPT
        assert cmd.AppCommand.compact().is_review() is False
        assert cmd.AppCommand.review("diff").is_review() is True
        assert cmd.AppCommand.run_user_shell_command("ls").payload["command"] == "ls"
        a = cmd.AppCommand.exec_approval("id1", "allow", turn_id="t1")
        assert a.payload == {"id": "id1", "turn_id": "t1", "decision": "allow"}

    def test_user_turn_defaults_approvals_reviewer_none(self):
        c = cmd.AppCommand.user_turn(
            turn_trigger="enter",
            cloud_submission=cmd.CloudSubmissionIntent.START_OR_STEER,
            client_user_message_id="m1", items=[], cwd="/w",
            approval_policy="on-request", model="local")
        assert c.payload["approvals_reviewer"] is None
        assert c.payload["cloud_submission"] == "start_or_steer"

    def test_realtime_variants_are_contract_only(self):
        c = cmd.AppCommand(cmd.CommandKind.REALTIME_CONVERSATION_START)
        assert c.is_implemented() is False


# ---------------------------------------------------------------- app_event
class TestAppEvent:
    def test_catalog_counts(self):
        c = ev.event_catalog()
        assert c["exit_modes"] == 3
        assert c["feedback_categories"] == 5
        assert c["running_task_actions"] == 3

    def test_enums(self):
        assert ev.ExitMode.IMMEDIATE.value == "Immediate"
        assert ev.FeedbackCategory.SAFETY_CHECK.value == "SafetyCheck"
        assert ev.RunningTaskExitAction.RUN_IN_BACKGROUND.value == "RunInBackground"
        assert ev.SideStartMode.NEW.value == "New"

    def test_codex_op_is_not_double_logged(self):
        e = ev.AppEvent.codex_op(cmd.AppCommand.interrupt())
        assert e.is_loggable_inbound() is False

    def test_unknown_event_not_logged(self):
        """本地化增强：未知事件（可能带敏感字段）不进会话日志。"""
        assert ev.AppEvent("SomeNewServerEvent").is_loggable_inbound() is False

    def test_local_event_is_logged(self):
        assert ev.AppEvent("ClearUi").is_loggable_inbound() is True

    def test_voice_allowlist(self):
        assert ev.AppEvent("RefreshRateLimits").is_voice_allowed() is True
        assert ev.AppEvent("ClearUi").is_voice_allowed() is False
        c = cmd.AppCommand(cmd.CommandKind.REALTIME_CONVERSATION_SPEECH)
        assert ev.AppEvent.codex_op(c).is_voice_allowed() is True

    def test_transcript_copy_closed(self):
        e = ev.AppEvent.transcript_copy_closed()
        assert e.name == ev.TRANSCRIPT_COPY_CLOSED
        assert e.is_loggable_inbound() is True

    def test_validate_thread_op_rejects_missing_id(self):
        for tid in (None, "", "   "):
            e = ev.AppEvent.submit_thread_op(tid, cmd.AppCommand.interrupt())
            assert "thread_id" in (ev.validate_thread_op(e) or "")
        assert ev.validate_thread_op(
            ev.AppEvent.submit_thread_op("t1", cmd.AppCommand.interrupt())) is None

    def test_to_dict_uses_command_redaction(self):
        e = ev.AppEvent.codex_op(cmd.AppCommand(
            cmd.CommandKind.USER_TURN,
            {"sdp": cmd.RealtimeOfferSdp("SECRET")}))
        assert "SECRET" not in str(e.to_dict())


# ---------------------------------------------------------------- sender
class TestAppEventSender:
    def test_capacity_matches_app_constant(self):
        assert sender.DEFAULT_QUEUE_CAPACITY == ck_app.THREAD_EVENT_CHANNEL_CAPACITY == 32768

    def test_send_and_inbound_log(self):
        s = sender.AppEventSender()
        assert s.send(ev.AppEvent("ClearUi")) is True
        st = s.stats()
        assert st["queued"] == 1 and st["inbound_logged"] == 1
        assert len(s.inbound_log()) == 1

    def test_ops_not_double_logged(self):
        s = sender.AppEventSender()
        s.send(ev.AppEvent.codex_op(cmd.AppCommand.interrupt()))
        assert s.stats()["inbound_logged"] == 0

    def test_voice_only_drops_before_logging(self):
        """上游顺序：白名单丢弃在日志之前，被丢事件不进 inbound 日志。"""
        s = sender.AppEventSender()
        s.set_voice_only(True)
        assert s.send(ev.AppEvent("ClearUi")) is False
        st = s.stats()
        assert st["dropped_voice"] == 1
        assert st["inbound_logged"] == 0
        assert s.send(ev.AppEvent("RefreshRateLimits")) is True

    def test_invalid_thread_op_rejected(self):
        s = sender.AppEventSender()
        assert s.send(ev.AppEvent.submit_thread_op(
            "", cmd.AppCommand.interrupt())) is False
        assert s.stats()["dropped_invalid"] == 1

    def test_sink_error_is_swallowed_and_logged(self):
        logs = []
        def bad(_):
            raise RuntimeError("channel closed")
        s = sender.AppEventSender(sink=bad,
                                  logger=lambda lv, m: logs.append((lv, m)))
        assert s.send(ev.AppEvent("ClearUi")) is False
        assert s.stats()["send_errors"] == 1
        assert logs and logs[0][0] == "error"

    def test_bounded_queue_rejects_when_full(self):
        s = sender.AppEventSender(capacity=2)
        assert s.send(ev.AppEvent("ClearUi")) is True
        assert s.send(ev.AppEvent("NewSession")) is True
        assert s.send(ev.AppEvent("ClearUi")) is False
        assert s.stats()["dropped_full"] == 1
        assert len(s.drain()) == 2

    def test_convenience_methods(self):
        s = sender.AppEventSender()
        assert s.interrupt() and s.compact() and s.set_thread_name("n")
        assert s.review("diff") and s.run_user_shell_command("ls")
        assert s.exec_approval("t1", "i1", "allow") is True
        assert s.patch_approval("t1", "p1", "deny") is True
        assert s.request_permissions_response("t1", "r1", {"ok": True}) is True
        assert s.user_input_answer("t1", "u1", {"a": 1}) is True
        assert s.resolve_elicitation("t1", "srv", "q1", "accept") is True
        assert s.resolve_user_verification("t1", "srv", "q1", {"ok": 1}) is True
        assert s.stats()["queued"] == 11


# ---------------------------------------------------------------- app_info
class TestAppInfo:
    def test_field_counts(self):
        assert info.field_counts() == {
            "app_info": 15, "branding": 6, "metadata": 11,
            "review": 1, "screenshot": 3}

    def test_explicit_conversion(self):
        wire = {
            "id": "a1", "name": "demo", "labels": ["x"],
            "install_url": "https://example.com/install",
            "branding": {"category": "dev", "website": "https://example.com"},
            "app_metadata": {"version": "1.0", "review": {"status": "ok"},
                             "screenshots": [{"url": "https://e.com/s.png"}]},
        }
        d = info.app_info_from_api(wire)
        assert isinstance(d, info.AppInfo)
        assert d.branding.category == "dev"
        assert d.app_metadata.review.status == "ok"
        assert d.app_metadata.screenshots[0].url == "https://e.com/s.png"
        assert d.labels == ["x"]

    def test_unknown_wire_field_rejected(self):
        problems = info.validate_api_app_info(
            {"id": "x", "server_secret": "SECRET"})
        assert any("未知字段" in p for p in problems)
        d = info.app_info_from_api({"id": "x", "server_secret": "SECRET"})
        assert not hasattr(d, "server_secret")

    def test_unsafe_url_rejected(self):
        for bad in ("javascript:alert(1)", "file:///etc/passwd",
                    "https://exa\x07mple.com", "https://exa\x1b]8;;evil.com"):
            problems = info.validate_api_app_info({"install_url": bad})
            assert problems, bad

    def test_nested_unknown_field_detected(self):
        problems = info.validate_api_app_info(
            {"app_metadata": {"version": "1", "internal_token": "T"}})
        assert any("app_metadata" in p and "未知字段" in p for p in problems)


# ---------------------------------------------------------------- cli
class TestCli:
    def test_constants(self):
        assert "ask-for-approval" in ck_cli.PUBLIC_FLAGS
        assert "resume_session_id" in ck_cli.INTERNAL_SKIP_ARGS
        assert len(ck_cli.CONFLICT_RULES) == 2

    def test_bypass_conflicts_with_approval_policy(self):
        c, problems = ck_cli.parse_args(
            ["--yolo", "--ask-for-approval", "on-request"])
        assert not c.is_safe_to_start()
        assert any("绕过" in p for p in problems)

    def test_auto_review_conflicts_with_approval_policy(self):
        c, problems = ck_cli.parse_args(
            ["--auto-review", "--ask-for-approval", "on-request"])
        assert not c.is_safe_to_start()
        assert any("auto_review" in p for p in problems)

    def test_two_bypass_switches_also_rejected(self):
        c, problems = ck_cli.parse_args(["--yolo", "--auto-review"])
        assert not c.is_safe_to_start()

    def test_safe_combination(self):
        c, problems = ck_cli.parse_args(
            ["--strict-config", "--ask-for-approval", "on-request", "hello"])
        assert problems == [] and c.is_safe_to_start()
        assert c.prompt == "hello" and c.strict_config is True

    def test_unknown_flag_not_silently_ignored(self):
        _, problems = ck_cli.parse_args(["--evil-flag"])
        assert any("未识别" in p for p in problems)

    def test_internal_args_never_public(self):
        c = ck_cli.Cli(prompt="x")
        public = c.to_public_flags()
        assert not (set(public) & ck_cli.INTERNAL_SKIP_ARGS)
        assert public["prompt"] == "x"

    def test_defaults(self):
        c = ck_cli.Cli()
        assert c.strict_config is False and c.web_search is False
        assert c.no_alt_screen is False and c.no_daemon is False
        assert c.approval_policy is None

    def test_missing_value(self):
        _, problems = ck_cli.parse_args(["--ask-for-approval"])
        assert any("缺少取值" in p for p in problems)


# ---------------------------------------------------------------- resize cap
class TestResizeReflowCap:
    def test_constants(self):
        k = cap.constants()
        assert (k["vscode"], k["windows_terminal"], k["wezterm"],
                k["alacritty"]) == (1000, 9001, 3500, 10000)
        assert k["terminal_names"] == 15

    @pytest.mark.parametrize("name,expected", [
        (cap.TerminalName.VS_CODE, 1000),
        (cap.TerminalName.WINDOWS_TERMINAL, 9001),
        (cap.TerminalName.WEZTERM, 3500),
        (cap.TerminalName.ALACRITTY, 10000),
        (cap.TerminalName.GHOSTTY, 1000),
        (cap.TerminalName.UNKNOWN, 1000),
    ])
    def test_auto_caps(self, name, expected):
        assert cap.auto_resize_reflow_max_rows(name) == expected

    def test_vscode_probe_takes_priority(self):
        assert cap.auto_resize_reflow_max_rows(
            cap.TerminalName.WINDOWS_TERMINAL, True) == 1000

    def test_disabled_returns_none(self):
        assert cap.resize_reflow_max_rows_for(
            cap.TerminalResizeReflowConfig.disabled(),
            cap.TerminalName.VS_CODE) is None

    def test_explicit_limit_overrides_detection(self):
        assert cap.resize_reflow_max_rows_for(
            cap.TerminalResizeReflowConfig.limit(42),
            cap.TerminalName.ALACRITTY) == 42

    def test_limit_zero_is_disabled(self):
        assert cap.resize_reflow_max_rows_for(
            cap.TerminalResizeReflowConfig.limit(0),
            cap.TerminalName.VS_CODE) is None

    def test_illegal_limit_fails_closed(self):
        for n in (-1, 999999):
            assert cap.resize_reflow_max_rows_for(
                cap.TerminalResizeReflowConfig.limit(n),
                cap.TerminalName.VS_CODE) == cap.fallback_rows()

    def test_probe_injection(self):
        v, reason = cap.cap_for(
            cap.TerminalResizeReflowConfig.auto(),
            cap.TerminalName.WINDOWS_TERMINAL, True)
        assert v == 1000 and "VS Code" in reason
        assert cap.resize_reflow_max_rows(
            cap.TerminalResizeReflowConfig.auto(),
            terminal_probe=lambda: cap.TerminalName.WEZTERM,
            vscode_probe=lambda: False) == 3500


# ---------------------------------------------------------------- app
class TestApp:
    def test_constants(self):
        c = ck_app.app_constants()
        assert c["thread_event_channel_capacity"] == 32768
        assert c["external_editor_hint"] == \
            "Save and close external editor to continue."
        assert set(c["exit_reasons"]) == \
            {"UserRequested", "TurnInterrupted", "Fatal"}

    def test_fatal_clears_other_fields(self):
        i = ck_app.AppExitInfo.fatal("boom")
        assert i.exit_reason is ck_app.ExitReason.FATAL
        assert i.thread_id is None and i.token_usage == {}
        assert i.fatal_message == "boom"

    def test_resumable_requires_nonempty_regular_file(self, tmp_path):
        empty = tmp_path / "empty.jsonl"
        empty.write_text("")
        assert ck_app.rollout_path_is_resumable(str(empty)) is False
        good = tmp_path / "good.jsonl"
        good.write_text('{"a":1}')
        assert ck_app.rollout_path_is_resumable(str(good)) is True
        assert ck_app.resumable_thread("t1", "n", str(good)) == {
            "thread_id": "t1", "thread_name": "n"}
        assert ck_app.resumable_thread("t1", "n", str(empty)) is None
        assert ck_app.resumable_thread(None, "n", str(good)) is None

    def test_request_exit(self):
        st = ck_app.AppState()
        i = st.request_exit(ck_app.ExitReason.FATAL, "crash")
        assert st.run_control is ck_app.AppRunControl.EXIT
        assert st.exit_info is i
        assert st.events[-1]["kind"] == "fatal"

    def test_existing_security_wiring_intact(self):
        """本轮硬约束：前 11 轮修好的 6 条接线一条都不能少。"""
        r = ck_app.assert_wiring_intact()
        assert r.intact is True
        assert len(r.checks) == 6
        assert all(r.checks.values())


# ---------------------------------------------------------------- backtrack
class TestBacktrack:
    def _state(self):
        s = bt.BacktrackState()
        s.start("thread-A", ["p1", "p2", "p3"])
        return s

    def test_constants(self):
        assert bt.NO_PREVIOUS_MESSAGE_TO_EDIT == "No previous message to edit."
        assert "侧会话" in bt.SIDE_EDIT_PREVIOUS_UNAVAILABLE_MESSAGE_ZH
        assert bt.NO_SELECTION == -1

    def test_six_step_state_machine(self):
        s = self._state()
        assert s.press_esc("thread-A") == "primed"
        assert s.primed is True and s.base_id == "thread-A"
        assert s.press_esc("thread-A") == "browsing"
        assert s.nth_user_message == 2  # 高亮最新用户消息
        assert s.move_selection(-1) == 1
        assert s.toggle_details() is False
        assert s.toggle_details() is True
        assert s.press_esc("thread-A") == "restored"
        assert s.nth_user_message == bt.NO_SELECTION

    def test_no_previous_message(self):
        s = bt.BacktrackState()
        s.start("t", [])
        s.press_esc("t")
        assert s.press_esc("t") == bt.NO_PREVIOUS_MESSAGE_TO_EDIT
        assert s.has_selection() is False

    def test_thread_change_invalidates_selection(self):
        """安全：线程变了，旧选择必须失效，绝不跨会话 revert。"""
        s = self._state()
        s.press_esc("thread-A"); s.press_esc("thread-A")
        assert s.has_selection() is True
        s.bind_thread("thread-B")
        assert s.has_selection() is False
        assert s.primed is False
        assert s.confirm_revert("thread-B") is None

    def test_confirm_revert_second_checks_thread(self):
        s = self._state()
        s.press_esc("thread-A"); s.press_esc("thread-A")
        req = s.confirm_revert("thread-A")
        assert isinstance(req, bt.RevertRequest)
        assert req.thread_id == "thread-A" and req.prompt == "p3"
        assert s.confirm_revert("thread-B") is None  # 二次校验

    def test_side_conversation_rejected(self):
        s = self._state()
        s.press_esc("thread-A"); s.press_esc("thread-A")
        assert s.confirm_revert("thread-A", side_conversation=True) is None

    def test_selection_clamped(self):
        s = self._state()
        s.press_esc("thread-A"); s.press_esc("thread-A")
        assert s.move_selection(-100) == 0
        assert s.move_selection(100) == 2

    def test_info_messages(self):
        s = bt.BacktrackState()
        assert "没有可编辑" in s.info_message()
        assert s.info_message(zh=False) == bt.NO_PREVIOUS_MESSAGE_TO_EDIT


# ---------------------------------------------------------------- chatwidget
class TestChatWidget:
    def test_constants(self):
        c = cw.chatwidget_constants()
        assert c["default_model_display_name"] == "loading"
        assert c["default_status_line_items"] == [
            "model-with-reasoning", "current-dir", "thread-name"]
        assert c["ambient_pet_wrap_gap_columns"] == 2
        assert c["max_transcript_bytes"] == 1024
        assert c["max_replay_transcript_cells"] == 10

    def test_committed_plus_live_tail(self):
        w = cw.ChatWidget()
        w.commit_cell("cell-1")
        w.append_active("streaming")
        lines = w.overlay_lines()
        assert lines == ["cell-1", "streaming"]

    def test_live_tail_cache_reuse(self):
        w = cw.ChatWidget()
        w.append_active("a")
        w.live_tail(); w.live_tail()
        st = w.stats()
        assert st["tail_rebuilds"] == 1 and st["tail_reuses"] == 1
        w.append_active("b")
        w.live_tail()
        assert w.stats()["tail_rebuilds"] == 2

    def test_time_dependent_forces_refresh(self):
        w = cw.ChatWidget()
        w.append_active("x")
        w.live_tail()
        w.active_cell.time_dependent = True
        w.live_tail(); w.live_tail()
        assert w.stats()["tail_rebuilds"] == 3

    def test_dual_lifecycle_busy(self):
        """上游最值钱的一条：两个生命周期独立，busy 是派生状态。"""
        w = cw.ChatWidget()
        assert w.set_mcp_startup_status(cw.McpStartupStatus.STARTING) is True
        assert w.task_running is True and w.agent_turn_running is False
        assert w.set_agent_turn_running(True) is True
        assert w.set_mcp_startup_status(cw.McpStartupStatus.READY) is True
        assert w.task_running is True   # 回合仍在跑，不能误报空闲
        assert w.set_agent_turn_running(False) is False
        assert w.task_running is False

    def test_finish_active_cell(self):
        w = cw.ChatWidget()
        w.append_active("final")
        w.finish_active_cell()
        assert w.committed_cells == ["final"]
        assert w.active_cell.text == ""
        assert w.live_tail() == []

    def test_transcript_truncation_keeps_tail(self):
        w = cw.ChatWidget()
        text = "A" * 2000
        out = w.commit_cell(text)
        assert len(out.encode()) <= 1024
        assert out.endswith("A")
        assert w.stats()["transcript_truncations"] == 1

    def test_to_dict(self):
        d = cw.ChatWidget().to_dict()
        assert d["mcp_startup_status"] == "idle"
        assert d["task_running"] is False
        assert len(d["status_line_items"]) == 3


# ---------------------------------------------------------------- package
class TestCorekitPackage:
    def test_report(self):
        r = corekit.corekit_report()
        assert r["modules"] == 9
        assert r["upstream_group"] == "core_app"
        assert r["security_wiring"]["intact"] is True
        assert len(r["security_wiring"]["checks"]) == 6

    def test_validate_clean(self):
        assert corekit.corekit_validate() == []

    def test_parity_includes_corekit(self):
        from tuan_cli.tui.parity import parity_report, parity_validate
        r = parity_report()
        assert r["corekit"]["modules"] == 9
        assert r["matrix"]["pending"] == 15
        assert r["matrix"]["by_status"]["aligned"] == 30
        assert r["matrix"]["coverage_pct"] == 90.9
        assert r["matrix"]["fully_identical"] is False
        assert parity_validate() == []

    def test_gaps_no_longer_contain_core_app(self):
        from tuan_cli.tui.parity import matrix
        gaps = {m for _, m in matrix.gaps()}
        for m in ("app", "app_backtrack", "app_command", "app_event",
                  "app_event_sender", "app_info", "chatwidget", "cli",
                  "resize_reflow_cap"):
            assert m not in gaps
        assert len(gaps) == 15
