"""阶段 A 测试: 反思性自我进化闭环 (evaluator / regression_gate / evolution_loop)。"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tuan_cli.self_improve.evaluator import Evaluator, EvaluationResult  # noqa: E402
from tuan_cli.self_improve.regression_gate import RegressionGate  # noqa: E402
from tuan_cli.self_improve.evolution_loop import (  # noqa: E402
    EvolutionCandidate,
    EvolutionLedger,
    EvolutionLoop,
    EvolutionRecord,
)


# ------------------------------------------------------------------ Evaluator
class TestEvaluator:
    def test_full_pass_scores_high(self):
        ev = Evaluator()
        r = ev.evaluate("T1", {"ok": True, "tests_run": 5, "tests_passed": 5,
                               "files_touched": 3, "elapsed": 1.0, "notes": ["a"]})
        # correctness=100, performance=98.3, style=85, completeness 渐进 (68)
        assert r.total_score >= 85
        assert r.passed is True
        assert r.dims["correctness"] == 100.0

    def test_failure_is_penalized(self):
        ev = Evaluator()
        r = ev.evaluate("T2", {"ok": False, "error": "boom"})
        assert r.total_score < 60
        assert r.passed is False
        assert any("boom" in n for n in r.notes)

    def test_missing_tests_not_assumed_success(self):
        ev = Evaluator()
        ok = ev.evaluate("T3", {"ok": True})
        fail = ev.evaluate("T4", {"ok": False})
        assert ok.total_score > fail.total_score
        assert ok.dims["correctness"] == 80.0  # 无测试信息不虚高

    def test_custom_dims_and_weight_normalization(self):
        def coverage(a):
            return 100.0 if a.get("covered") else 0.0

        ev = Evaluator(extend_dims={"coverage": coverage}, extend_weights={"coverage": 0.2})
        assert "coverage" in ev.dims
        assert abs(sum(ev.weights.values()) - 1.0) < 1e-6
        r = ev.evaluate("T5", {"ok": True, "covered": True, "tests_run": 1, "tests_passed": 1})
        assert r.dims["coverage"] == 100.0

    def test_to_from_dict_roundtrip(self):
        ev = Evaluator()
        r = ev.evaluate("T6", {"ok": True, "tests_run": 2, "tests_passed": 2})
        d = r.to_dict()
        r2 = EvaluationResult.from_dict(d)
        assert r2.total_score == r.total_score
        assert r2.dims == r.dims


# --------------------------------------------------------- RegressionGate
class TestRegressionGate:
    def test_accepts_net_improvement(self):
        score = {"ok": True, "tests_run": 1, "tests_passed": 0}
        gate = RegressionGate(run_task=lambda t: dict(score), tasks=["T"])

        def better():
            score["tests_passed"] = 1

        verdict = gate.evaluate({"apply": better, "rollback": lambda: None})
        assert verdict.accepted is True
        assert verdict.delta > 0

    def test_rejects_lower_score(self):
        score = {"ok": True, "tests_run": 1, "tests_passed": 1}
        gate = RegressionGate(run_task=lambda t: dict(score), tasks=["T"])

        def worse():
            score["tests_passed"] = 0

        verdict = gate.evaluate({"apply": worse, "rollback": lambda: None})
        assert verdict.accepted is False
        assert verdict.delta < 0

    def test_rejects_critical_dim_regression(self):
        # correctness 是红线; 完整性上升但正确性下降 => 拒绝
        score = {"ok": True, "tests_run": 2, "tests_passed": 2, "files_touched": 1}
        gate = RegressionGate(run_task=lambda t: dict(score), tasks=["T"])

        def regress_correctness():
            score["tests_passed"] = 1   # 正确性 50
            score["files_touched"] = 5  # 完整性更高

        verdict = gate.evaluate({"apply": regress_correctness, "rollback": lambda: None})
        assert verdict.accepted is False
        assert "correctness" in verdict.rejected_dims

    def test_apply_failure_is_conservative_reject(self):
        gate = RegressionGate(run_task=lambda t: {"ok": True, "tests_run": 1,
                                                  "tests_passed": 1}, tasks=["T"])

        def failing_apply():
            raise RuntimeError("apply boom")

        verdict = gate.evaluate({"apply": failing_apply, "rollback": lambda: None})
        assert verdict.accepted is False
        assert "apply failed" in verdict.reason

    def test_empty_tasks_rejected(self):
        gate = RegressionGate(run_task=lambda t: {}, tasks=[])
        verdict = gate.evaluate({"apply": lambda: None, "rollback": lambda: None})
        assert verdict.accepted is False

    def test_rollback_called_after_apply(self):
        calls = []
        score = {"ok": True, "tests_run": 1, "tests_passed": 0}
        gate = RegressionGate(run_task=lambda t: dict(score), tasks=["T"])

        def better():
            score["tests_passed"] = 1
            calls.append("apply")

        def rollback():
            score["tests_passed"] = 0
            calls.append("rollback")

        gate.evaluate({"apply": better, "rollback": rollback})
        assert calls == ["apply", "rollback"]  # 对比后必回滚 (由循环决定是否重应用)


# ------------------------------------------------------------- EvolutionLoop
class TestEvolutionLoop:
    def test_iterate_accepts_good_candidate_and_logs(self, tmp_path):
        ledger = tmp_path / "evo.jsonl"
        score = {"ok": True, "tests_run": 1, "tests_passed": 0}
        loop = EvolutionLoop(run_task=lambda t: dict(score), tasks=["T"], ledger_path=str(ledger))

        def gen(experiences):
            return [EvolutionCandidate(
                id="c1", summary="提升正确性", origin="manual",
                apply=lambda: score.update(tests_passed=1),
                rollback=lambda: score.update(tests_passed=0))]

        records = loop.iterate(gen)
        assert len(records) == 1
        assert records[0].accepted is True
        assert records[0].delta > 0
        # 账本已落盘且可回放
        loaded = EvolutionLedger(str(ledger)).load()
        assert len(loaded) == 1
        assert loaded[0]["accepted"] is True

    def test_iterate_rejects_bad_candidate_and_rolls_back(self, tmp_path):
        ledger = tmp_path / "evo.jsonl"
        score = {"ok": True, "tests_run": 1, "tests_passed": 1}
        loop = EvolutionLoop(run_task=lambda t: dict(score), tasks=["T"], ledger_path=str(ledger))

        def gen(experiences):
            return [EvolutionCandidate(
                id="c2", summary="劣化", origin="manual",
                apply=lambda: score.update(tests_passed=0),
                rollback=lambda: score.update(tests_passed=1))]

        records = loop.iterate(gen)
        assert records[0].accepted is False
        assert records[0].delta < 0
        # 拒绝后已回滚, 状态恢复
        assert score["tests_passed"] == 1
        loaded = EvolutionLedger(str(ledger)).load()
        assert loaded[0]["accepted"] is False

    def test_ledger_append_only_does_not_overwrite(self, tmp_path):
        ledger = tmp_path / "evo.jsonl"
        l = EvolutionLedger(str(ledger))
        l.append(EvolutionRecord("c1", "a", "manual", True, 80, 90, 10, "ok", ts=1))
        l.append(EvolutionRecord("c2", "b", "manual", False, 90, 70, -20, "bad", ts=2))
        loaded = l.load()
        assert len(loaded) == 2
        assert loaded[0]["candidate_id"] == "c1"
        assert loaded[1]["candidate_id"] == "c2"

    def test_report_empty(self, tmp_path):
        loop = EvolutionLoop(run_task=lambda t: {}, tasks=["T"],
                             ledger_path=str(tmp_path / "e.jsonl"))
        assert "为空" in loop.report()
