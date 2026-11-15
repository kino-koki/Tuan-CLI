"""cmd_verify 测试 —— 验证工具发现与反思诊断 CLI。"""
from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from types import SimpleNamespace
from typing import Any, List, Optional

import pytest

from tuan_cli.cli import cmd_verify as P


# ---------------------------------------------------------------- fakes

@dataclass
class FakeVerResult:
    name: str
    passed: bool
    exit_code: int = 0
    output: str = ""
    duration: float = 0.0
    error_summary: str = ""


class FakeDecision(Enum):
    CONTINUE = "continue"
    FIX = "fix"
    DEGRADE = "degrade"
    ASK_USER = "ask_user"


@dataclass
class FakeReflection:
    decision: Any
    diagnosis: str = ""
    suggested_fix: str = ""
    failure_count: int = 1
    degraded_task: Optional[str] = None
    summary: str = ""
    verifications: List[Any] = None

    def __post_init__(self):
        if self.verifications is None:
            self.verifications = []


class FakeVerifier:
    def __init__(self, ws):
        self.ws = ws
        self._tools = ["pytest", "ruff"]

    def detect_available(self):
        return list(self._tools)

    def run_verification(self, tool):
        ok = tool == "pytest"
        return FakeVerResult(name=tool, passed=ok, exit_code=0 if ok else 1,
                             duration=1.2, error_summary="" if ok else "boom")

    def run_all(self, tools: Optional[List[str]] = None):
        targets = tools or self._tools
        return [self.run_verification(t) for t in targets]


class FakeReflector:
    def __init__(self, ws):
        self.ws = ws
        self.last_reflect_args = None

    def reflect(self, task, last_output=""):
        self.last_reflect_args = (task, last_output)
        return FakeReflection(
            decision=FakeDecision.FIX,
            diagnosis="编译失败",
            suggested_fix="检查语法",
            failure_count=1,
            verifications=[FakeVerResult("pytest", False, 1, error_summary="boom")],
        )

    def build_reflection_prompt(self, task, result, last_output):
        return f"REFLECT::{task}::" + (result.diagnosis or "")


def _args(**kw):
    base = dict(verify_cmd=None, json=False, workspace=None, cwd=None,
                tool=None, tools=None, task=None, last_output=None, prompt=False)
    base.update(kw)
    return SimpleNamespace(**base)


@pytest.fixture(autouse=True)
def _patch(monkeypatch):
    monkeypatch.setattr("tuan_cli.core.reflector.Verifier", FakeVerifier)
    monkeypatch.setattr("tuan_cli.core.reflector.Reflector", FakeReflector)


# ---------------------------------------------------------------- 纯函数

class TestHelpers:
    def test_workspace_explicit(self, tmp_path):
        a = _args(workspace=str(tmp_path))
        assert P._workspace(a) == str(tmp_path.resolve())

    def test_workspace_cwd_fallback(self):
        a = _args(cwd=".")
        assert P._workspace(a) != ""

    def test_workspace_default_cwd(self):
        import os
        assert P._workspace(_args()) == os.getcwd()

    def test_verification_dict(self):
        v = FakeVerResult("pytest", True, 0, "ok out", 0.5)
        d = P._verification_dict(v)
        assert d["name"] == "pytest"
        assert d["passed"] is True
        assert d["exit_code"] == 0
        assert d["output"] == "ok out"
        assert d["duration_sec"] == 0.5


# ---------------------------------------------------------------- detect

class TestDetect:
    def test_detect_text(self, capsys):
        rc = P.cmd_verify(_args(verify_cmd="detect"))
        assert rc == 0
        out = capsys.readouterr().out
        assert "可用验证工具" in out
        assert "pytest" in out

    def test_detect_json(self, capsys):
        rc = P.cmd_verify(_args(verify_cmd="detect", json=True))
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert data["count"] == 2
        assert "pytest" in data["available"]

    def test_detect_empty(self, capsys, monkeypatch):
        class EmptyVerifier(FakeVerifier):
            def detect_available(self):
                return []
        monkeypatch.setattr("tuan_cli.core.reflector.Verifier", EmptyVerifier)
        rc = P.cmd_verify(_args(verify_cmd="detect"))
        assert rc == 0
        assert "未检测到" in capsys.readouterr().out

    def test_default_detect(self, capsys):
        rc = P.cmd_verify(_args())
        assert rc == 0
        assert "可用验证工具" in capsys.readouterr().out


# ---------------------------------------------------------------- run

class TestRun:
    def test_run_pass(self, capsys):
        rc = P.cmd_verify(_args(verify_cmd="run", tool="pytest"))
        assert rc == 0
        out = capsys.readouterr().out
        assert "✓ pytest" in out

    def test_run_fail(self, capsys):
        rc = P.cmd_verify(_args(verify_cmd="run", tool="ruff"))
        assert rc == 1
        out = capsys.readouterr().out
        assert "✗ ruff" in out
        assert "boom" in out

    def test_run_json_pass(self, capsys):
        rc = P.cmd_verify(_args(verify_cmd="run", tool="pytest", json=True))
        assert rc == 0
        d = json.loads(capsys.readouterr().out)
        assert d["name"] == "pytest" and d["passed"] is True

    def test_run_missing_tool(self, capsys):
        rc = P.cmd_verify(_args(verify_cmd="run", tool=None))
        assert rc == 1
        assert "请指定" in capsys.readouterr().out


# ---------------------------------------------------------------- all

class TestAll:
    def test_all_text_all_pass(self, capsys, monkeypatch):
        class PassVerifier(FakeVerifier):
            def run_verification(self, tool):
                return FakeVerResult(tool, True, 0, duration=0.3)
        monkeypatch.setattr("tuan_cli.core.reflector.Verifier", PassVerifier)
        rc = P.cmd_verify(_args(verify_cmd="all"))
        assert rc == 0
        assert "2/2 通过" in capsys.readouterr().out

    def test_all_text_partial_fail(self, capsys):
        rc = P.cmd_verify(_args(verify_cmd="all"))
        assert rc == 1
        out = capsys.readouterr().out
        assert "1/2 通过" in out

    def test_all_json(self, capsys):
        rc = P.cmd_verify(_args(verify_cmd="all", json=True))
        assert rc == 1
        data = json.loads(capsys.readouterr().out)
        assert data["total"] == 2
        assert data["passed"] == 1
        assert data["failed"] == 1

    def test_all_with_tools_arg(self, capsys, monkeypatch):
        calls: list = []

        class SpyVerifier(FakeVerifier):
            def run_all(self, tools=None):
                calls.append(tools)
                return [FakeVerResult("pytest", True)]
        monkeypatch.setattr("tuan_cli.core.reflector.Verifier", SpyVerifier)
        rc = P.cmd_verify(_args(verify_cmd="all", tools="pytest,ruff", json=True))
        assert rc == 0
        assert calls[-1] == ["pytest", "ruff"]


# ---------------------------------------------------------------- reflect

class TestReflect:
    def test_reflect_text(self, capsys):
        rc = P.cmd_verify(_args(verify_cmd="reflect", task="修复 bug"))
        assert rc == 0
        out = capsys.readouterr().out
        assert "反思诊断" in out
        assert "fix" in out.lower()

    def test_reflect_json(self, capsys):
        rc = P.cmd_verify(_args(verify_cmd="reflect", task="t", json=True))
        assert rc == 0
        d = json.loads(capsys.readouterr().out)
        assert d["decision"] == "fix"
        assert d["diagnosis"] == "编译失败"

    def test_reflect_prompt_text(self, capsys):
        rc = P.cmd_verify(_args(verify_cmd="reflect", task="t", prompt=True))
        assert rc == 0
        out = capsys.readouterr().out
        assert "REFLECT::t::" in out

    def test_reflect_prompt_json(self, capsys):
        rc = P.cmd_verify(_args(verify_cmd="reflect", task="t", prompt=True, json=True))
        assert rc == 0
        d = json.loads(capsys.readouterr().out)
        assert d["task"] == "t"
        assert "REFLECT" in d["reflection_prompt"]

    def test_reflect_empty_task(self, capsys):
        rc = P.cmd_verify(_args(verify_cmd="reflect", task="   "))
        assert rc == 1
        assert "请提供任务" in capsys.readouterr().out
