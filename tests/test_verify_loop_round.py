"""verify_loop 数据类 / run_check / verify_once / 缓存清理 单元测试。

覆盖 `core/verify_loop.py` 中未被 test_verify_infer / test_verify_loop_wiring
触及的部分: VerifyConfig 解析、CheckResult / VerifyRound / VerifyReport 行为、
run_check 的分支 (成功/失败/拦截/超时/异常)、verify_once 编排、clear_tool_cache。
"""
from __future__ import annotations

import subprocess
import time
from pathlib import Path

import pytest

from tuan_cli.core import verify_loop as vl
from tuan_cli.core.verify_loop import (
    CheckResult,
    VerifyConfig,
    VerifyReport,
    VerifyRound,
    clear_tool_cache,
    run_check,
    verify_once,
)


# ------------------------------------------------------------------ VerifyConfig

def test_verify_config_defaults():
    cfg = VerifyConfig()
    assert cfg.enabled is True
    assert cfg.auto is True
    assert cfg.max_heal_rounds == vl.MAX_HEAL_ROUNDS
    assert cfg.test_cmd == "" and cfg.typecheck_cmd == "" and cfg.lint_cmd == ""


def test_verify_config_from_dict_full():
    cfg = VerifyConfig.from_dict({
        "verify": {
            "enabled": False,
            "auto": False,
            "max_heal_rounds": 7,
            "checks": {"test": "pytest -q", "typecheck": "mypy .", "lint": "ruff check ."},
        }
    })
    assert cfg.enabled is False
    assert cfg.auto is False
    assert cfg.max_heal_rounds == 7
    assert cfg.test_cmd == "pytest -q"
    assert cfg.typecheck_cmd == "mypy ."
    assert cfg.lint_cmd == "ruff check ."


def test_verify_config_from_dict_partial():
    cfg = VerifyConfig.from_dict({"verify": {"checks": {"test": "go test ./..."}}})
    assert cfg.enabled is True  # 默认
    assert cfg.test_cmd == "go test ./..."
    assert cfg.typecheck_cmd == ""  # 缺失留空


def test_verify_config_from_dict_empty():
    cfg = VerifyConfig.from_dict({})
    assert cfg.enabled is True
    assert cfg.test_cmd == ""


# ------------------------------------------------------------------ CheckResult / VerifyRound / VerifyReport

def test_check_result_fields():
    r = CheckResult(name="test", cmd="pytest -q", passed=True,
                    output="1 passed", returncode=0, elapsed=0.3)
    assert r.name == "test"
    assert r.cmd == "pytest -q"
    assert r.passed is True
    assert r.output == "1 passed"
    assert r.returncode == 0
    assert r.elapsed == 0.3


def test_verify_round_all_passed_and_failures():
    rnd = VerifyRound(round_num=1, checks=[
        CheckResult("test", "pytest", True, "ok", 0),
        CheckResult("lint", "ruff", False, "E501", 1),
    ])
    assert rnd.all_passed is False
    assert [c.name for c in rnd.failures] == ["lint"]


def test_verify_round_all_passed_true_when_empty():
    # 空 checks 视为全部通过 (all([]) == True)
    assert VerifyRound(round_num=1).all_passed is True


def test_verify_round_summary_contains_fail_tail():
    rnd = VerifyRound(round_num=1, checks=[
        CheckResult("test", "pytest", False, "line1\nline2\nERROR boom", 1),
    ])
    s = rnd.summary()
    assert "[FAIL] test: pytest" in s
    assert "ERROR boom" in s  # 失败输出尾部被带出


def test_verify_round_summary_pass():
    rnd = VerifyRound(round_num=1, checks=[
        CheckResult("test", "pytest", True, "ok", 0),
    ])
    s = rnd.summary()
    assert "[PASS] test: pytest" in s
    assert "ERROR" not in s


def test_verify_report_summary_healed_and_gave_up():
    r = VerifyReport(rounds=[VerifyRound(1, [CheckResult("t", "p", True, "", 0)])],
                     healed=True, gave_up=False)
    s = r.summary()
    assert "验证闭环: 1 轮" in s
    assert "自修复成功" in s

    r2 = VerifyReport(rounds=[VerifyRound(1, [CheckResult("t", "p", False, "err", 1)])],
                      gave_up=True)
    assert "已达修复上限" in r2.summary()

    r3 = VerifyReport(rounds=[VerifyRound(1, [CheckResult("t", "p", True, "", 0)])])
    assert "首轮即全部通过" in r3.summary()


def test_verify_report_total_rounds():
    r = VerifyReport(rounds=[VerifyRound(1), VerifyRound(2)])
    assert r.total_rounds == 2


# ------------------------------------------------------------------ run_check

def test_run_check_success(tmp_path, monkeypatch):
    monkeypatch.setattr("tuan_cli.core.command_guard.guard_command", lambda *a, **k: None)
    completed = subprocess.CompletedProcess(["pytest"], 0, stdout="1 passed", stderr="")
    monkeypatch.setattr("tuan_cli.core.proc.run_with_tree_kill",
                        lambda *a, **k: completed)
    res = run_check("test", "pytest -q", str(tmp_path))
    assert res.passed is True
    assert res.returncode == 0
    assert res.elapsed >= 0


def test_run_check_failure(tmp_path, monkeypatch):
    monkeypatch.setattr("tuan_cli.core.command_guard.guard_command", lambda *a, **k: None)
    completed = subprocess.CompletedProcess(["pytest"], 1, stdout="", stderr="boom")
    monkeypatch.setattr("tuan_cli.core.proc.run_with_tree_kill",
                        lambda *a, **k: completed)
    res = run_check("test", "pytest -q", str(tmp_path))
    assert res.passed is False
    assert res.returncode == 1
    assert "boom" in res.output


def test_run_check_blocked_by_guard(tmp_path, monkeypatch):
    """守卫拦截 (fail-closed): 不触碰 subprocess, 返回失败结果。"""
    monkeypatch.setattr("tuan_cli.core.command_guard.guard_command",
                        lambda *a, **k: "[已拦截] 危险命令")
    called = []
    monkeypatch.setattr("tuan_cli.core.proc.run_with_tree_kill",
                        lambda *a, **k: called.append(1))
    res = run_check("lint", "rm -rf /", str(tmp_path))
    assert res.passed is False
    assert res.returncode == -1
    assert "已拦截" in res.output
    assert called == []  # subprocess 未被调用


def test_run_check_guard_exception_treated_as_blocked(tmp_path, monkeypatch):
    monkeypatch.setattr("tuan_cli.core.command_guard.guard_command",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("guard broken")))
    res = run_check("test", "pytest", str(tmp_path))
    assert res.passed is False
    assert "已拦截" in res.output


def test_run_check_timeout(tmp_path, monkeypatch):
    monkeypatch.setattr("tuan_cli.core.command_guard.guard_command", lambda *a, **k: None)
    def _boom(*a, **k):
        raise subprocess.TimeoutExpired(["pytest"], 120)
    monkeypatch.setattr("tuan_cli.core.proc.run_with_tree_kill", _boom)
    res = run_check("test", "pytest -q", str(tmp_path), timeout=120)
    assert res.passed is False
    assert "超时" in res.output
    assert res.returncode == -1


def test_run_check_generic_error(tmp_path, monkeypatch):
    monkeypatch.setattr("tuan_cli.core.command_guard.guard_command", lambda *a, **k: None)
    def _boom(*a, **k):
        raise OSError("no such file")
    monkeypatch.setattr("tuan_cli.core.proc.run_with_tree_kill", _boom)
    res = run_check("test", "pytest", str(tmp_path))
    assert res.passed is False
    assert "OSError" in res.output
    assert res.returncode == -1


# ------------------------------------------------------------------ verify_once

def test_verify_once_runs_all_inferred(tmp_path, monkeypatch):
    """verify_once 编排: infer 出的每个命令都执行。"""
    monkeypatch.setattr("tuan_cli.core.command_guard.guard_command", lambda *a, **k: None)
    completed = subprocess.CompletedProcess(["x"], 0, stdout="ok", stderr="")
    monkeypatch.setattr("tuan_cli.core.proc.run_with_tree_kill",
                        lambda *a, **k: completed)
    monkeypatch.setattr(vl, "infer_check_commands",
                        lambda ws, cfg: {"test": "pytest -q", "lint": "ruff check ."})
    rnd = verify_once(str(tmp_path), VerifyConfig())
    assert rnd.round_num == 1
    assert [c.name for c in rnd.checks] == ["test", "lint"]
    assert rnd.all_passed is True


def test_verify_once_no_commands(tmp_path, monkeypatch):
    monkeypatch.setattr(vl, "infer_check_commands", lambda ws, cfg: {})
    rnd = verify_once(str(tmp_path), VerifyConfig())
    assert rnd.checks == []
    assert rnd.all_passed is True


# ------------------------------------------------------------------ 缓存清理

def test_clear_tool_cache(monkeypatch):
    vl._tool_cache["pytest"] = True
    assert vl._tool_cache.get("pytest") is True
    clear_tool_cache()
    assert "pytest" not in vl._tool_cache
