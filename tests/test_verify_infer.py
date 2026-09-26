"""verify_loop 命令自动推断测试 (M 级)。

覆盖:
- pytest 声明检测 (pytest.ini / [tool.pytest.ini_options] / tests/ 目录 / 仅有 pyproject 不推断);
- 工具不可用不硬上 (mypy/ruff/pytest 缺失 → 不推断对应检查);
- venv 感知 (项目 .venv 存在时用 venv 解释器);
- Go / Rust / TypeScript 推断;
- 配置显式覆盖优先于推断。
"""

from __future__ import annotations

import pytest

from qingxiaotuan.core import verify_loop as vl


def _cfg(**kw):
    return vl.VerifyConfig(enabled=True, auto=True, **kw)


# ---------------------------------------------------------------- pytest 声明检测


def test_pytest_inferred_when_ini_declared(tmp_path, monkeypatch):
    (tmp_path / "pytest.ini").write_text("[pytest]\n")
    monkeypatch.setattr(vl, "_py_available", lambda ws, mod: mod == "pytest")
    checks = vl.infer_check_commands(str(tmp_path), _cfg())
    assert checks["test"] == "python -m pytest -x -q --tb=short"


def test_pytest_inferred_from_pyproject_declaration(tmp_path, monkeypatch):
    (tmp_path / "pyproject.toml").write_text(
        "[tool.pytest.ini_options]\ntestpaths = ['tests']\n"
    )
    monkeypatch.setattr(vl, "_py_available", lambda ws, mod: True)
    checks = vl.infer_check_commands(str(tmp_path), _cfg())
    assert "test" in checks


def test_pytest_inferred_from_tests_dir(tmp_path, monkeypatch):
    (tmp_path / "tests").mkdir()
    monkeypatch.setattr(vl, "_py_available", lambda ws, mod: True)
    checks = vl.infer_check_commands(str(tmp_path), _cfg())
    assert "test" in checks


def test_pytest_not_inferred_without_declaration(tmp_path, monkeypatch):
    """仅有 pyproject.toml 但无 [tool.pytest.ini_options] → 不推断 (可能是 unittest 项目)。"""
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'\n")
    monkeypatch.setattr(vl, "_py_available", lambda ws, mod: True)
    checks = vl.infer_check_commands(str(tmp_path), _cfg())
    assert "test" not in checks


def test_pytest_not_inferred_when_unavailable(tmp_path, monkeypatch):
    """声明了 pytest 但工具不可用 → 不推断, 避免每轮 ModuleNotFoundError 空耗。"""
    (tmp_path / "pytest.ini").write_text("[pytest]\n")
    monkeypatch.setattr(vl, "_py_available", lambda ws, mod: False)
    checks = vl.infer_check_commands(str(tmp_path), _cfg())
    assert "test" not in checks


# ---------------------------------------------------------------- venv 感知


def test_venv_python_preferred(tmp_path, monkeypatch):
    venv = tmp_path / ".venv" / "Scripts"
    venv.mkdir(parents=True)
    (venv / "python.exe").write_text("")
    (tmp_path / "tests").mkdir()
    monkeypatch.setattr(vl, "_py_available", lambda ws, mod: True)
    checks = vl.infer_check_commands(str(tmp_path), _cfg())
    assert checks["test"].startswith(str(venv / "python.exe"))


def test_mypy_ruff_skip_when_unavailable(tmp_path, monkeypatch):
    (tmp_path / "tests").mkdir()
    monkeypatch.setattr(vl, "_py_available", lambda ws, mod: mod == "pytest")
    checks = vl.infer_check_commands(str(tmp_path), _cfg())
    assert "typecheck" not in checks
    assert "lint" not in checks


# ---------------------------------------------------------------- Go / Rust / TS


def test_go_inference(tmp_path, monkeypatch):
    (tmp_path / "go.mod").write_text("module example.com/x\n")
    monkeypatch.setattr(vl, "_tool_available", lambda t: t in ("go", "cargo", "npx"))
    checks = vl.infer_check_commands(str(tmp_path), _cfg())
    assert checks["test"] == "go test ./... -count=1"
    assert checks["typecheck"] == "go vet ./..."


def test_rust_inference(tmp_path, monkeypatch):
    (tmp_path / "Cargo.toml").write_text("[package]\nname = 'x'\n")
    monkeypatch.setattr(vl, "_tool_available", lambda t: t in ("go", "cargo", "npx"))
    checks = vl.infer_check_commands(str(tmp_path), _cfg())
    assert checks["test"] == "cargo test --quiet"
    assert checks["typecheck"] == "cargo check --quiet"


def test_typescript_typecheck_inferred(tmp_path, monkeypatch):
    (tmp_path / "package.json").write_text('{"scripts": {}}')
    (tmp_path / "tsconfig.json").write_text("{}")
    monkeypatch.setattr(vl, "_tool_available", lambda t: t in ("go", "cargo", "npx"))
    checks = vl.infer_check_commands(str(tmp_path), _cfg())
    assert checks["typecheck"] == "npx tsc --noEmit"


# ---------------------------------------------------------------- 配置优先


def test_config_overrides_inference(tmp_path, monkeypatch):
    monkeypatch.setattr(vl, "_py_available", lambda ws, mod: True)
    checks = vl.infer_check_commands(
        str(tmp_path), _cfg(test_cmd="custom-test", typecheck_cmd="custom-tc")
    )
    assert checks["test"] == "custom-test"
    assert checks["typecheck"] == "custom-tc"


def test_unknown_project_no_checks(tmp_path, monkeypatch):
    monkeypatch.setattr(vl, "_tool_available", lambda t: True)
    monkeypatch.setattr(vl, "_py_available", lambda ws, mod: True)
    checks = vl.infer_check_commands(str(tmp_path), _cfg())
    assert checks == {}
