"""B1：Claude Code v2.1.319 全模块超越计划的基线与第一步落地回归。

两条线并行：
  - A 线 ``tuan tui parity``（Codex TUI 对齐，前 13 轮已完成 155/165）；
  - B 线本文件（超 Claude Code，本轮建立 14 域 99 模块基线 + B1 落地）。

重点不是"文档写了很多"，而是：
  1. 99 个模块的状态、证据、领先理由、轮次**可机器核验**；
  2. 六个超越维度的**运行时探针**真调现有代码；
  3. ``hooks/manager.py`` 两个 fail-open 侧门被修并有回归覆盖；
  4. 既有 6 条安全接线仍完好。
"""
from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

from tuan_cli import parity_claude as pc
from tuan_cli.hooks.manager import (
    DEFAULT_ON_FAILURE, ON_FAILURE_POLICIES, HookManager,
)
from tuan_cli.parity_claude import catalog, evidence, matrix, superiority


# ================================================================ 基线与目录
class TestBaseline:
    def test_version_locked_to_latest(self):
        assert catalog.CC_VERSION == "2.1.319"
        assert catalog.CC_DATE == "2026-11-06"
        assert catalog.CC_TAG_TIMESTAMP == "2026-11-06T17:04:01Z"
        assert catalog.CC_PRODUCT == "Claude Code"

    def test_sources_include_official_and_third_party(self):
        kinds = {x["kind"] for x in catalog.SOURCES}
        assert kinds == {"official", "third_party"}
        assert all(x["url"].startswith("https://") for x in catalog.SOURCES)
        assert all(x["note"] for x in catalog.SOURCES)
        assert len(catalog.SOURCES) == 8

    def test_domains_and_modules(self):
        c = catalog.constants()
        assert len(c["domains"]) == 14
        assert c["total_modules"] == 99
        assert len(c["statuses"]) == 5
        assert len(c["superiority_dimensions"]) == 6
        assert c["waves"][:2] == ["A14", "A15"]

    def test_module_names_unique(self):
        names = [m.name for m in catalog.MODULES]
        assert len(names) == len(set(names))

    def test_every_module_in_a_known_domain(self):
        for m in catalog.MODULES:
            assert m.domain in catalog.DOMAINS
            assert m.status in catalog.STATUSES
            assert m.cc_ref and m.note

    def test_status_counts_are_derived(self):
        s = pc.claude_parity_report()["matrix"]
        assert sum(s["by_status"].values()) == 99
        # B2 落地后同步到新基线（**不是放宽**）：4 个 B2 模块从 gap 变为
        # 2 aligned + 2 partial，证据路径与运行时探针全部真实存在。
        # 派生一致性仍要求总和 99 且与 catalog 逐项对应。
        assert s["by_status"] == {
            "ahead": 10, "aligned": 45, "partial": 10,
            "gap": 26, "not_applicable": 8}

    def test_domain_counts_sum(self):
        s = pc.claude_parity_report()["matrix"]
        assert sum(d["total"] for d in s["domain_counts"].values()) == 99

    def test_waves_cover_a_and_b_lines(self):
        waves = [w["wave"] for w in catalog.WAVES]
        assert waves == ["A14", "A15", "B1", "B2", "B3", "B4", "B5",
                         "B6", "B7", "B8", "B9", "B10"]
        assert all(w["target"] and w["note"] for w in catalog.WAVES)


# ================================================================ 证据与状态定义
class TestEvidence:
    def test_all_evidence_paths_exist(self):
        assert evidence.verify_evidence() == []

    def test_not_applicable_modules_have_reason_not_ahead(self):
        for m in catalog.MODULES:
            if m.status == catalog.STATUS_NA:
                assert not m.ahead_reason
                assert not m.wave
                assert "不适用" in m.note or "不实现" in m.note

    def test_ahead_modules_have_reason_and_dimension(self):
        for m in catalog.MODULES:
            if m.status == catalog.STATUS_AHEAD:
                assert m.ahead_reason
                assert m.ahead_dim in catalog.SUPERIORITY_DIMENSIONS
                assert m.evidence

    def test_non_ahead_modules_cannot_claim_ahead(self):
        for m in catalog.MODULES:
            if m.status != catalog.STATUS_AHEAD:
                assert not m.ahead_reason and not m.ahead_dim

    def test_every_gap_has_a_wave(self):
        waves = {w["wave"] for w in catalog.WAVES}
        for m in catalog.MODULES:
            if m.status == catalog.STATUS_GAP:
                assert m.wave in waves
                assert m.wave.startswith("B")

    def test_gap_queue_matches_status(self):
        s = pc.claude_parity_report()["matrix"]
        assert len(s["gap_queue"]) == s["gaps"] == s["by_status"]["gap"]
        waves = {g["wave"] for g in s["gap_queue"]}
        assert "B2" in waves and "B3" in waves and "B10" in waves

    def test_wave_load_references_every_gap(self):
        load = evidence.wave_load()
        for d, mod, wave in evidence.gaps():
            assert mod in load[wave]

    def test_evidence_report_counts(self):
        r = evidence.evidence_report()
        assert r["total_modules"] == 99
        assert r["problems"] == []
        assert r["by_status"]["not_applicable"]["modules"] == 8

    def test_readme_count_includes_english(self):
        names = evidence.readme_languages()
        assert "README.md" in names
        assert len(names) == 10


# ================================================================ 六维探针
class TestSuperiorityProbes:
    def test_probe_count_matches_dimensions(self):
        assert len(superiority.PROBES) == 6
        assert set(superiority.PROBES) == set(catalog.SUPERIORITY_DIMENSIONS)

    def test_all_six_probes_pass(self):
        results = superiority.probe_all()
        for dim, r in results.items():
            assert r.ok, f"{dim}: {r.detail}"
            assert r.checks

    def test_verified_ahead_equals_declared(self):
        r = pc.claude_parity_report()
        assert r["matrix"]["ahead_verified"] == r["matrix"]["ahead_declared"] == 10
        assert r["matrix"]["dimensions_unverified"] == []
        assert not r["matrix"]["ahead_unverified_by_dim"]

    def test_probes_are_read_only(self):
        """探针不得在仓库内留下文件（临时目录之外）。"""
        before = {p.name for p in evidence.REPO_ROOT.glob("*.json")}
        superiority.probe_all()
        after = {p.name for p in evidence.REPO_ROOT.glob("*.json")}
        assert before == after

    def test_hook_failure_probe_uses_a_missing_binary(self):
        r = superiority._probe_fail_closed_default()
        assert r.ok
        assert "spawn 失败" in " ".join(r.checks)

    def test_verifiable_parity_probe_reports_pending(self):
        r = superiority._probe_verifiable_parity()
        assert r.ok
        assert "165" in " ".join(r.checks)


# ================================================================ 矩阵与判据
class TestMatrix:
    def test_validate_clean(self):
        assert pc.claude_parity_validate() == []

    def test_fully_superior_is_false_and_honest(self):
        m = pc.claude_parity_report()["matrix"]
        assert m["fully_superior"] is False
        c = m["superiority_criteria"]
        assert c["gaps_zero"] is False
        assert c["all_probes_ok"] is True
        assert c["every_dimension_has_ahead"] is True
        assert c["all_b_waves_done"] is False
        assert c["external_adaptive_red_team"] is False
        assert m["b_waves_done"] == ["B1"]

    def test_security_wiring_still_intact(self):
        w = pc.claude_parity_report()["matrix"]["security_wiring"]
        assert w["intact"] is True
        assert len(w["checks"]) == 6
        assert w["problems"] == []

    def test_report_shape(self):
        r = pc.claude_parity_report()
        assert r["validate"] == []
        assert len(r["sources"]) == 8
        assert r["baseline"]["total_modules"] == 99
        assert len(r["probes"]) == 6
        assert len(r["waves"]) == 12

    def test_ahead_by_dimension_all_six(self):
        d = evidence.ahead_by_dimension()
        assert set(d) == set(catalog.SUPERIORITY_DIMENSIONS)
        assert all(v for v in d.values())


# ================================================================ B1 落地：hooks fail-closed
def _cfg(hooks=None, **extra):
    cfg = {"hooks": {"enabled": True, "audit_log": False, **(hooks or {})}}
    cfg["hooks"].update(extra)
    return cfg


def _failing_hook(**over):
    return {"type": "command", "matcher": "*",
            "command": ["/definitely/missing/tuan-parity-binary"],
            "timeout": 1.0, **over}


class TestHookFailClosed:
    def test_default_policy_is_block(self):
        assert DEFAULT_ON_FAILURE == "block"
        assert ON_FAILURE_POLICIES == ("block", "ask", "allow")
        hm = HookManager(config=_cfg())
        assert hm.on_failure_policy() == "block"

    def test_spawn_failure_blocks_pre_tool_use(self):
        hm = HookManager(config=_cfg({"PreToolUse": [_failing_hook()]}))
        d = hm.run_pre("write_file", {"path": "x"})
        assert d.block is True
        assert d.failure_kind == "spawn_error"
        assert "fail-closed" in d.reason
        assert "spawn_error" in d.reason

    def test_failure_is_recorded_and_queryable(self):
        hm = HookManager(config=_cfg({"PreToolUse": [_failing_hook()]}))
        hm.run_pre("write_file", {})
        fs = hm.failures()
        assert len(fs) == 1
        assert fs[0]["kind"] == "spawn_error"
        assert fs[0]["event"] == "PreToolUse"
        assert fs[0]["hook_type"] == "command"
        assert fs[0]["uid"]
        assert fs[0]["ts"] > 0

    def test_clear_failures(self):
        hm = HookManager(config=_cfg({"PreToolUse": [_failing_hook()]}))
        hm.run_pre("write_file", {})
        assert hm.failures()
        hm.clear_failures()
        assert hm.failures() == []

    def test_global_allow_is_an_explicit_escape_hatch(self):
        hm = HookManager(config=_cfg(
            {"PreToolUse": [_failing_hook()], "on_failure": "allow"}))
        assert hm.on_failure_policy() == "allow"
        d = hm.run_pre("write_file", {})
        assert d.block is False
        assert hm.failures()  # 仍然留痕

    def test_per_hook_allow_overrides_global_block(self):
        hm = HookManager(config=_cfg(
            {"PreToolUse": [_failing_hook(on_failure="allow")]}))
        d = hm.run_pre("write_file", {})
        assert d.block is False
        assert hm.failures()

    def test_per_hook_block_overrides_global_allow(self):
        hm = HookManager(config=_cfg(
            {"PreToolUse": [_failing_hook(on_failure="block")],
             "on_failure": "allow"}))
        d = hm.run_pre("write_file", {})
        assert d.block is True

    def test_ask_policy_blocks_with_manual_hint(self):
        hm = HookManager(config=_cfg(
            {"PreToolUse": [_failing_hook()], "on_failure": "ask"}))
        d = hm.run_pre("write_file", {})
        assert d.block is True
        assert "需人工确认" in d.reason

    def test_unknown_global_policy_falls_back_to_block(self):
        hm = HookManager(config=_cfg(
            {"PreToolUse": [_failing_hook()], "on_failure": "sometimes"}))
        assert hm.on_failure_policy() == "block"

    def test_unknown_per_hook_policy_ignored_uses_global(self):
        hm = HookManager(config=_cfg(
            {"PreToolUse": [_failing_hook(on_failure="maybe")],
             "on_failure": "block"}))
        d = hm.run_pre("write_file", {})
        assert d.block is True
        assert "on_failure=block" in d.reason

    def test_blocking_default_true_makes_hook_block_effective(self):
        hook = {"type": "command", "matcher": "*",
                "command": [sys.executable, "-c",
                            "print('{\"block\": true, \"reason\": \"denied\"}')"],
                "timeout": 5.0}
        hm = HookManager(config=_cfg({"PreToolUse": [hook]}))
        d = hm.run_pre("write_file", {})
        assert d.block is True
        assert d.reason == "denied"
        assert d.failure_kind == ""

    def test_explicit_blocking_false_still_blocks_on_failure(self):
        """blocking 只管 hook 自身决策，不管执行失败的 fail-closed。"""
        hm = HookManager(config=_cfg(
            {"PreToolUse": [_failing_hook(blocking=False)]}))
        assert hm._specs[0].blocking is False
        d = hm.run_pre("write_file", {})
        assert d.block is True
        assert d.failure_kind == "spawn_error"

    def test_no_failure_does_not_leak_to_next_dispatch(self):
        """每次 _exec 清空最近失败，成功 hook 不被上一条失败污染。"""
        good = {"type": "command", "matcher": "*",
                "command": [sys.executable, "-c", "print('')"],
                "timeout": 5.0}
        hm = HookManager(config=_cfg(
            {"PreToolUse": [_failing_hook(on_failure="allow"), good]}))
        d = hm.run_pre("write_file", {})
        assert d.block is False
        assert len(hm.failures()) == 1

    def test_notify_events_record_failure_without_blocking_turn(self):
        hm = HookManager(config=_cfg({"Stop": [_failing_hook()]}))
        hm.run_notify("Stop", {"x": 1})   # 不抛
        assert hm.failures()[0]["event"] == "Stop"
        hm.run_post("write_file", {}, result=None)  # 无 Post hook，不抛

    def test_post_hook_failure_is_recorded_not_raised(self):
        hm = HookManager(config=_cfg({"PostToolUse": [_failing_hook()]}))
        hm.run_post("write_file", {}, result=None)
        assert hm.failures()[0]["event"] == "PostToolUse"

    def test_user_prompt_submit_failure_returns_empty_context(self):
        hm = HookManager(config=_cfg({"UserPromptSubmit": [_failing_hook()]}))
        assert hm.run_user_prompt_submit("hello") == ""
        assert hm.failures()

    def test_nonzero_rc_with_valid_decision_still_honors_decision(self):
        hook = {"type": "command", "matcher": "*",
                "command": [sys.executable, "-c",
                            "import sys; print('{\"block\": true, \"reason\": \"rc1\"}'); sys.exit(1)"],
                "timeout": 5.0}
        hm = HookManager(config=_cfg({"PreToolUse": [hook]}))
        d = hm.run_pre("write_file", {})
        assert d.block is True and d.reason == "rc1"
        assert any(f["kind"] == "nonzero_rc" for f in hm.failures())

    def test_timeout_blocks(self):
        hook = {"type": "command", "matcher": "*",
                "command": [sys.executable, "-c",
                            "import time; time.sleep(5)"],
                "timeout": 0.2}
        hm = HookManager(config=_cfg({"PreToolUse": [hook]}))
        d = hm.run_pre("write_file", {})
        assert d.block is True
        assert d.failure_kind == "timeout"

    def test_prompt_hook_without_kernel_is_a_failure_not_silent_skip(self):
        hook = {"type": "prompt", "matcher": "*", "prompt": "check {tool_name}"}
        hm = HookManager(config=_cfg({"PreToolUse": [hook]}))
        d = hm.run_pre("write_file", {})
        assert d.block is True
        assert d.failure_kind == "no_kernel"

    def test_subagent_hook_without_kernel_is_a_failure(self):
        hook = {"type": "subagent", "matcher": "*", "prompt": "inspect"}
        hm = HookManager(config=_cfg({"PreToolUse": [hook]}))
        d = hm.run_pre("write_file", {})
        assert d.block is True
        assert d.failure_kind == "no_kernel"

    def test_failure_log_is_bounded(self):
        hm = HookManager(config=_cfg({"PreToolUse": [_failing_hook()]}))
        hm._max_failures = 3
        for _ in range(6):
            hm.run_pre("write_file", {})
        assert len(hm.failures()) == 3


# ================================================================ 配置校验
class TestSecuritySchemaHooks:
    def _v(self, cfg):
        from tuan_cli.config.security_schema import validate_security_config
        return validate_security_config(cfg)

    def test_unknown_global_policy_rejected(self):
        errors, _ = self._v({"hooks": {"on_failure": "sometimes"}})
        assert any("hooks.on_failure" in e for e in errors)

    def test_allow_reported_as_security_downgrade(self):
        errors, warnings = self._v({"hooks": {"on_failure": "allow"}})
        assert not errors
        assert any("安全降级" in w for w in warnings)

    def test_valid_policies_accepted(self):
        for policy in ("block", "ask", "allow"):
            errors, _ = self._v({"hooks": {"on_failure": policy}})
            assert not [e for e in errors if "on_failure" in e]

    def test_unknown_per_hook_policy_rejected(self):
        errors, _ = self._v({"hooks": {"PreToolUse": [
            {"command": ["echo"], "on_failure": "maybe"}]}})
        assert any("PreToolUse[0].on_failure" in e for e in errors)

    def test_non_dict_hooks_rejected(self):
        errors, _ = self._v({"hooks": "yes"})
        assert any("hooks 应为配置字典" in e for e in errors)

    def test_existing_checks_unchanged(self):
        assert self._v({"sandbox": "bad"})[0]
        assert self._v({"permissions.rules": [
            {"tool": "x", "action": "maybe"}]})[0]


# ================================================================ CLI
class TestCli:
    def _run(self, capsys, **kw):
        from tuan_cli.cli.cmd_claude_parity import cmd_claude_parity
        opts = {"report_json": False, "gaps": False, "probes": False}
        opts.update(kw)
        rc = cmd_claude_parity(types.SimpleNamespace(**opts))
        return rc, capsys.readouterr().out

    def test_text_output(self, capsys):
        rc, out = self._run(capsys, probes=True, gaps=True)
        assert rc == 0
        assert "[claude parity]" in out
        assert "2.1.319" in out and "2026-11-06" in out
        assert "14 个功能域" in out and "99 个模块" in out
        assert "OK" in out and "UNVERIFIED" not in out
        assert "既有链路完好" in out
        assert "完全超越  : 否" in out
        assert "下一轮 B2" in out
        assert "A 线并行" in out

    def test_report_json(self, capsys):
        rc, out = self._run(capsys, report_json=True)
        assert rc == 0
        data = json.loads(out)
        assert data["baseline"]["cc_version"] == "2.1.319"
        assert data["matrix"]["total_modules"] == 99
        assert data["validate"] == []
        assert len(data["probes"]) == 6

    def test_gaps_listing(self, capsys):
        _, out = self._run(capsys, gaps=True)
        assert "待补齐队列 (26)" in out   # B2 落地 4 项后
        assert "B2" in out and "os_sandbox" in out
