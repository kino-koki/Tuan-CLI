"""``tuan usercmd`` CLI 的单元测试 (cmd_usercmd.py)。

覆盖:
1. load_user_commands 返回空 -> 提示无命令
2. 返回用户级命令 (用户级标记)
3. 返回项目级命令 (含 .tuan 路径 -> 项目级标记)
4. 多条命令按名称排序
5. 启动失败 (build_kernel 抛异常) -> 返回 1

通过 monkeypatch 打桩 build_kernel / load_user_commands, 不依赖真实内核。
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from tuan_cli.cli import cmd_usercmd as P
from tuan_cli.cli.user_commands import UserCommand


def _args(workspace: str = "", profile: str = "default") -> SimpleNamespace:
    return SimpleNamespace(workspace=workspace, profile=profile)


def _uc(name: str, path: str = "/home/user/commands", hint: str = "") -> UserCommand:
    return UserCommand(
        name=name,
        description=f"desc of {name}",
        argument_hint=hint,
        body=f"body {name}",
        path=Path(path) / f"{name}.md",
    )


def _patch(monkeypatch, table=None, fail=False) -> None:
    """打桩 build_kernel / load_user_commands。"""
    if fail:
        def _boom(*a, **k):
            raise RuntimeError("kernel boom")
        monkeypatch.setattr(P, "build_kernel", _boom)
        return
    monkeypatch.setattr(P, "build_kernel", lambda *a, **k: SimpleNamespace(
        require=lambda name: SimpleNamespace()))
    monkeypatch.setattr(
        "tuan_cli.cli.user_commands.load_user_commands",
        lambda config, workspace: table or {},
    )


class TestUsercmd:
    def test_empty_table(self, monkeypatch, capsys) -> None:
        _patch(monkeypatch, table={})
        rc = P.cmd_usercmd(_args())
        out = capsys.readouterr().out
        assert rc == 0
        assert "没有自定义斜杠命令" in out

    def test_startup_failure_returns_1(self, monkeypatch, capsys) -> None:
        _patch(monkeypatch, fail=True)
        rc = P.cmd_usercmd(_args())
        out = capsys.readouterr().out
        assert rc == 1
        assert "启动失败" in out

    def test_user_level_source_label(self, monkeypatch, capsys) -> None:
        _patch(monkeypatch, table={
            "greet": _uc("greet", path="/home/user/.tuan-other"),
        })
        rc = P.cmd_usercmd(_args())
        out = capsys.readouterr().out
        assert rc == 0
        assert "/greet" in out
        assert "用户级" in out

    def test_project_level_source_label(self, monkeypatch, capsys) -> None:
        p = Path("/ws/.tuan/commands")
        _patch(monkeypatch, table={
            "deploy": _uc("deploy", path=str(p)),
        })
        rc = P.cmd_usercmd(_args())
        out = capsys.readouterr().out
        assert rc == 0
        assert "项目级" in out

    def test_sorted_by_name(self, monkeypatch, capsys) -> None:
        _patch(monkeypatch, table={
            "zeta": _uc("zeta"),
            "alpha": _uc("alpha"),
            "mid": _uc("mid"),
        })
        rc = P.cmd_usercmd(_args())
        out = capsys.readouterr().out
        assert rc == 0
        i_alpha = out.find("/alpha")
        i_mid = out.find("/mid")
        i_zeta = out.find("/zeta")
        assert 0 <= i_alpha < i_mid < i_zeta

    def test_argument_hint_or_dash(self, monkeypatch, capsys) -> None:
        _patch(monkeypatch, table={
            "with_hint": _uc("with_hint", hint="<arg>"),
            "no_hint": _uc("no_hint", hint=""),
        })
        rc = P.cmd_usercmd(_args())
        out = capsys.readouterr().out
        assert rc == 0
        assert "<arg>" in out
        assert "-" in out
