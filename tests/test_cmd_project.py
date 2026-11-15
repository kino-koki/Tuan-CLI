"""cmd_project tests -- project layer CLI (init/info/list)."""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from tuan_cli.cli import cmd_project as P


@pytest.fixture(autouse=True)
def _patch_paths(monkeypatch, tmp_path):
    monkeypatch.setattr("tuan_cli.cli.cmd_project.default_workspace",
                        lambda: str(tmp_path))


def _args(**kw):
    base = dict(project_cmd=None, workspace=None, profile="default",
                patch=None, force=False)
    base.update(kw)
    return SimpleNamespace(**base)


# ---------------------------------------------------------------- init

class TestInit:
    def test_init_creates_structure(self, capsys, tmp_path):
        rc = P.cmd_project(_args(project_cmd="init"))
        assert rc == 0
        out = capsys.readouterr().out
        assert "已初始化项目" in out
        # .tuan 目录应存在
        assert (tmp_path / ".tuan").is_dir()

    def test_init_idempotent(self, capsys, tmp_path):
        P.cmd_project(_args(project_cmd="init"))
        rc = P.cmd_project(_args(project_cmd="init"))
        assert rc == 0  # 第二次幂等, 不报错

    def test_init_default_when_no_sub(self, capsys, tmp_path):
        # project_cmd=None 默认走 info
        rc = P.cmd_project(_args())
        assert rc == 0


# ---------------------------------------------------------------- info

class TestInfo:
    def test_info_uninitialized(self, capsys, tmp_path):
        rc = P.cmd_project(_args(project_cmd="info"))
        assert rc == 0
        out = capsys.readouterr().out
        assert "尚未初始化" in out

    def test_info_after_init(self, capsys, tmp_path):
        P.cmd_project(_args(project_cmd="init"))
        capsys.readouterr()
        rc = P.cmd_project(_args(project_cmd="info"))
        assert rc == 0
        out = capsys.readouterr().out
        assert "项目 ID" in out
        assert "路径" in out


# ---------------------------------------------------------------- list

class TestList:
    def test_list_empty(self, capsys, tmp_path):
        rc = P.cmd_project(_args(project_cmd="list"))
        assert rc == 0
        assert "尚未登记" in capsys.readouterr().out

    def test_list_after_init(self, capsys, tmp_path):
        P.cmd_project(_args(project_cmd="init"))
        capsys.readouterr()
        rc = P.cmd_project(_args(project_cmd="list"))
        assert rc == 0
        out = capsys.readouterr().out
        assert "已知项目" in out


# ---------------------------------------------------------------- usage

class TestUsage:
    def test_unknown_sub_returns_2(self, capsys):
        rc = P.cmd_project(_args(project_cmd="nope"))
        assert rc == 2
        assert "用法" in capsys.readouterr().out
