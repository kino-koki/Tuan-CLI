"""A 线续轮 XI：最后 10 个 pending 的真实实现 + 深度真实性判据。

核心立场（用户原话）：**「确保深度的真实复现，而非仅仅广度」**。
本回归集同时钉死两件事：

1. 10 个模块不是「写个 note 指向文件」，而是各有可执行的运行时探针，
   真调代码、逐项断言（合计 127 条断言，纯 stdlib 也能跑）。
2. 状态表清零**不等于**「完全相同」：``fully_identical`` 现在还要求
   ``depth_audit()["ok"]``，而对 102 个 aligned/localized 只验证了
   10 个 —— 如实 ``False``，``depth_missing`` 是下一轮工作队列。

B 线这一轮只做**只读深度基线**（``parity_claude/depth.py``），不改
任何判据 / 状态：实测 65 个非 gap 模块里 65 个有 evidence 路径与
note，但**模块级运行时探针 0 个**（六维聚合探针不等于模块级探针）。
26 个 gap 逐项证据进 ``gap_queue()``。``catalog.py`` 零改动，
``fully_superior`` 仍 False。

**A′（本轮自己写错自己抓回，全部实测复现）**：

- ``HistoryBuffer(base_id=7)`` 把 base_id 当 cell_id 单调下界，
  连 ``append(id=1)`` 都被拒 → base_id 只管 backtrack 失效判定。
- 流式净化只删 ESC 字节，留下 ``[31m`` 残片 → 先整段剥 CSI/OSC。
- 两条探针断言写反（净化分片应返回 True、拼接结果应含 CSI 残片
  被清后的文本）。
- ``sh -c x`` 不含 shell 元字符却等于间接启用解释器 → 加执行器黑名单。
- ``probe_clock_format`` 重复自增 checks → 计数失真。
- harness 的「不得依赖测试框架」源码扫描**扫到自己**（docstring /
  注释 / 扫描代码里的字面串，共 3 次同类误伤）→ 改措辞 + 拆分字面串。
- ``depth_audit()`` 不 import 实现包导致 10 个探针一个都没注册，
  ``depth_verified`` 假报 0 → 加幂等 ``_ensure_registry()``。
- B 线 ``gap_queue()`` 初版扫全仓 1300+ .py 耗时 18.8s → 改为只
  核销每个模块自己声明的 evidence 文件（352ms）。

**如实边界**：``fully_identical`` 仍 False；B 线 26 gap 一个未消、
``b_waves_done=["B1"]``、``external_adaptive_red_team=False``；
A 线 92 个既有 aligned/localized 仍无模块级探针（下一轮逐项补）；
``codexkit`` 不接 TUI 主循环、不替换任何既有运行时对象；纯 Python
独立实现，零 Rust 源码复制。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tuan_cli.tui import codexkit
from tuan_cli.tui.codexkit import (
    approval_history as AH, session_config as SC,
    stream_exec as SE, selftest as ST,
)
from tuan_cli.tui.parity import matrix as AM, depth as AD
from tuan_cli.parity_claude import matrix as BM, depth as BD, catalog as C


# ================================================== 10 个真实实现
class TestRealImplementations:
    def test_all_ten_probes_pass(self):
        for m in codexkit.MODULES:
            r = AD.run_probe(m)
            assert r.ok, (m, r.problems, r.evidence)
            assert r.checks >= 6, (m, r.checks)

    def test_pure_stdlib_selftest_is_green(self):
        r = ST.run_all_probes()
        assert r["ok"] and r["modules"] == 9 and r["passed"] == 9
        assert r["total_checks"] >= 120, r["total_checks"]

    def test_codexkit_validate_clean(self):
        assert codexkit.codexkit_validate() == []

    def test_denial_ledger_fail_closed(self):
        led = AH.DenialLedger()
        for d in (None, object(), "unknown", AH.ReviewDecision.ABSTAIN,
                  "allow"):
            assert led.enforce(d)["allowed"] is False, d
        assert led.enforce("allow", acknowledged=True)["allowed"] is True

    def test_history_buffer_rejects_out_of_range(self):
        b = AH.HistoryBuffer(base_id=7)
        b.append(AH.HistoryCell(1, "a"))
        with pytest.raises(AH.HistoryInsertError):
            b.insert_at(99, AH.HistoryCell(2, "b"))
        assert len(b) == 1

    def test_selection_hit_matches_render(self):
        g = AH.SelectionGeometry()
        assert g.hit_matches_render(AH.Rect(0, 0, 20, 3),
                                    ["a中b", "xy", "q"]) == []

    def test_local_settings_never_persists(self):
        s = SC.LocalSettings()
        assert s.set("user", "tui.vim_mode", True)
        assert not s.set("user", "tui.vim_mode", "false")
        assert s.persisted() is False

    def test_template_single_pass(self):
        out = SC.fill_template_once("从 {model} 到 {effort}",
                                    {"model": "old-{effort}-x",
                                     "effort": "HIGH"})
        assert "old-{effort}-x" in out and "HIGH" in out

    def test_stream_render_is_pure_read(self):
        s = SE.StreamAssembler()
        s.push(SE.Chunk(0, "a"))
        before = s.peek()
        for _ in range(5):
            s.render()
        assert s.peek() == before

    def test_agent_cannot_self_answer(self):
        a = SE.AsyncQuestionReply()
        a.register("q", "?")
        assert not a.answer_as_agent("q", "self")
        assert a.answer_for("q") is None
        assert "agent_self_answer" in a.rejections()

    def test_exec_command_rejects_indirect_shell(self):
        for argv in (["echo", "a;rm -rf /"], ["sh", "-c", "x"],
                     ["python3", "-c", "x"]):
            with pytest.raises(ValueError):
                SE.ExecCommand.build(argv)


# ================================================== A 线矩阵与深度判据
class TestALineMatrix:
    def test_pending_cleared(self):
        s = AM.summary()
        assert s["pending"] == 0
        assert s["all_modules_settled"] is True
        assert AM.gaps() == []
        assert AM.validate() == []

    def test_by_status(self):
        assert AM.summary()["by_status"] == {
            "aligned": 45, "localized": 57,
            "not_applicable": 63, "pending": 0}

    def test_fully_identical_still_false_depth_gate(self):
        """状态清零不等于完全相同 —— 深度判据把水分单独列出来。"""
        s = AM.summary()
        assert s["fully_identical"] is False
        assert s["depth_strict_ok"] is False
        assert s["depth_claimed"] == 102
        assert s["depth_verified"] == 10
        assert len(s["depth_missing"]) == 92

    def test_depth_audit_structure(self):
        a = AD.depth_audit()
        assert a["claimed"] == 102 and a["verified"] == 10
        assert a["coverage_pct"] == 9.8
        assert a["ok"] is False
        assert all(m in a["results"] for m in codexkit.MODULES)

    def test_new_modules_have_probes(self):
        d = AD.assert_depth_intact()
        assert d["checked"] == 10 and d["intact"] and d["problems"] == []

    def test_probe_registry_has_no_duplicates(self):
        assert len(AD.PROBE_REGISTRY) >= 13
        assert len(set(AD.PROBE_REGISTRY)) == len(AD.PROBE_REGISTRY)

    def test_depth_probe_never_caches(self):
        a, b = AD.run_probe("exec_command"), AD.run_probe("exec_command")
        assert a.ok and b.ok and a.checks == b.checks

    def test_wiring_intact_still_called(self):
        from tuan_cli.tui.corekit.app import assert_wiring_intact
        assert assert_wiring_intact().intact


# ================================================== B 线只读深度基线
class TestBLineBaseline:
    def test_module_depth_quantifies_water(self):
        r = BD.module_depth_audit()
        assert r["claimed"] == 65
        assert r["path_ok"] == 65 and r["note_present"] == 65
        assert r["probe_verified"] == 0
        assert r["runtime_verified_pct"] == 0.0

    def test_gap_queue_is_reproducible(self):
        q = BD.gap_queue()
        assert q["gaps"] == 26
        assert q["by_wave"] == {
            "B10": 5, "B2": 1, "B3": 2, "B4": 1, "B5": 1,
            "B6": 4, "B7": 8, "B8": 1, "B9": 3}
        for it in q["items"]:
            assert it["name"] and it["wave"].startswith("B")
            assert "symbol_hits_in_declared_evidence" in it

    def test_b_matrix_unchanged(self):
        s = BM.summary()
        assert s["by_status"] == {
            "ahead": 10, "aligned": 46, "partial": 9,
            "gap": 26, "not_applicable": 8}
        assert s["gaps"] == 26
        assert s["fully_superior"] is False
        assert s["b_waves_done"] == ["B1"]
        assert s["superiority_criteria"]["external_adaptive_red_team"] is False
        assert BM.validate() == []

    def test_b3_entries_still_gap(self):
        for name in ("hook_events_extended",
                     "hook_updated_input_validation"):
            m = next(x for x in C.MODULES if x.name == name)
            assert m.status == C.STATUS_GAP

    def test_catalog_unchanged_this_round(self):
        src = Path("tuan_cli/parity_claude/catalog.py").read_text(
            encoding="utf-8")
        assert "CC_VERSION" in src and "STATUS_GAP" in src


# ================================================== 源码级契约
class TestSourceContracts:
    def test_codexkit_has_no_rust_copy(self):
        d = Path("tuan_cli/tui/codexkit")
        files = sorted(p.name for p in d.glob("*.py"))
        assert files == ["__init__.py", "approval_history.py",
                         "selftest.py", "session_config.py",
                         "stream_exec.py"]
        for p in d.glob("*.py"):
            s = p.read_text(encoding="utf-8")
            assert "use ratatui" not in s and "crossterm::" not in s

    def test_matrix_fully_identical_uses_depth(self):
        s = Path("tuan_cli/tui/parity/matrix.py").read_text(
            encoding="utf-8")
        assert 'counts[PENDING] == 0 and audit["ok"]' in s
        assert "NEW_DEPTH_MODULES" in s

    def test_depth_gate_cannot_be_bypassed(self):
        """把某个探针临时改成失败，validate() 必须报错。"""
        old = AD.PROBE_REGISTRY["exec_command"]
        try:
            AD.PROBE_REGISTRY["exec_command"] = lambda: {
                "ok": False, "checks": 0, "evidence": "forced",
                "problems": ["forced_failure"]}
            problems = AM.validate()
            assert any("exec_command" in x for x in problems)
        finally:
            AD.PROBE_REGISTRY["exec_command"] = old
        assert AM.validate() == []
