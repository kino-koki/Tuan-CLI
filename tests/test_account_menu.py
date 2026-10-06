# -*- coding: utf-8 -*-
"""TUI / REPL 的 /account 账户登录菜单测试 (离线/GitHub/Apple/DeepSeek)。"""
from __future__ import annotations

import sys
from typing import Any, Dict, List, Optional

import pytest

from qingxiaotuan.cli.cmd_slash import _cmd_account

_PROVIDERS = [
    {
        "name": "github",
        "display_name": "GitHub",
        "description": "GitHub OAuth 登录 (浏览器授权)",
    },
    {
        "name": "apple",
        "display_name": "Apple 账户",
        "description": "Sign in with Apple",
    },
    {
        "name": "deepseek",
        "display_name": "DeepSeek (官方 API)",
        "description": "DeepSeek 官方 API Key (sk- 开头; 官方渠道, 无封号风险)",
    },
]


class FakeProvider:
    display_name = "GitHub"

    def __init__(self, name: str) -> None:
        self.display_name = {"github": "GitHub", "apple": "Apple 账户", "deepseek": "DeepSeek (官方 API)"}[name]

    def login(self):
        from qingxiaotuan.auth import AuthResult

        return AuthResult(provider="github", login="octocat", display_name=self.display_name,
                          extra={"note": "ok"})


class EmptyStore:
    def get(self, provider: str) -> Optional[dict]:
        return None


class TTYStore(EmptyStore):
    """模拟已登录 deepseek 的登录态。"""

    def get(self, provider: str) -> Optional[dict]:
        if provider == "deepseek":
            return {"token": "x", "login": "user@deepseek"}
        return None


def _ok_result() -> Any:
    from qingxiaotuan.auth import AuthResult

    return AuthResult(provider="github", login="octocat", display_name="GitHub", extra={"note": "ok"})


def _patch_env(monkeypatch, store: Any = None) -> None:
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("qingxiaotuan.auth.AuthStore", store or EmptyStore)  # 类, 由菜单 AuthStore() 实例化
    monkeypatch.setattr("qingxiaotuan.auth.list_providers", lambda: _PROVIDERS)

    def _get(name: str):
        return FakeProvider(name)

    monkeypatch.setattr("qingxiaotuan.auth.get_provider", _get)
    monkeypatch.setattr("qingxiaotuan.auth.ProviderNotConfigured", type("PNC", (Exception,), {}))
    monkeypatch.setattr("qingxiaotuan.auth.AuthError", type("AE", (Exception,), {}))


def _login_spy(monkeypatch, called: List[str]):
    """登录时记录 display_name 并返回正常结果。"""
    monkeypatch.setattr(
        FakeProvider,
        "login",
        lambda self: (called.append(self.display_name), _ok_result())[1],
    )


def test_account_menu_offline(monkeypatch, capsys) -> None:
    """选择 1 (离线): 不触发任何登录, 保持离线。"""
    _patch_env(monkeypatch)
    called: List[str] = []
    _login_spy(monkeypatch, called)
    monkeypatch.setattr("builtins.input", lambda _: "1")
    assert _cmd_account(None, None, "") is True
    assert called == []


def test_account_menu_github_login(monkeypatch, capsys) -> None:
    """选择 2 (GitHub): 调用 provider.login() 完成登录。"""
    _patch_env(monkeypatch)
    called: List[str] = []
    _login_spy(monkeypatch, called)
    monkeypatch.setattr("builtins.input", lambda _: "2")
    assert _cmd_account(None, None, "") is True
    assert called == ["GitHub"]


def test_account_menu_by_name(monkeypatch, capsys) -> None:
    """输入提供方名称 (deepseek) 同样生效。"""
    _patch_env(monkeypatch)
    called: List[str] = []
    _login_spy(monkeypatch, called)
    monkeypatch.setattr("builtins.input", lambda _: "deepseek")
    assert _cmd_account(None, None, "") is True
    assert called == ["DeepSeek (官方 API)"]


def test_account_menu_shows_logged_state(monkeypatch, capsys) -> None:
    """菜单展示当前登录态: 已登录的 deepseek 显示 [已登录]。"""
    _patch_env(monkeypatch, store=TTYStore)  # 传类, AuthStore() 时实例化
    monkeypatch.setattr("builtins.input", lambda _: "")
    _cmd_account(None, None, "")
    out = capsys.readouterr().out
    assert "离线" in out
    assert "GitHub" in out
    assert "Apple 账户" in out
    assert "DeepSeek" in out
    assert "已登录" in out
    assert "user@deepseek" in out


def test_account_menu_cancel(monkeypatch, capsys) -> None:
    """回车取消: 保持当前状态。"""
    _patch_env(monkeypatch)
    called: List[str] = []
    _login_spy(monkeypatch, called)
    monkeypatch.setattr("builtins.input", lambda _: "")
    assert _cmd_account(None, None, "") is True
    assert called == []


def test_account_menu_invalid(monkeypatch, capsys) -> None:
    """无效输入: 提示且不触发登录。"""
    _patch_env(monkeypatch)
    called: List[str] = []
    _login_spy(monkeypatch, called)
    monkeypatch.setattr("builtins.input", lambda _: "99")
    assert _cmd_account(None, None, "") is True
    assert called == []


def test_account_menu_non_tty(monkeypatch, capsys) -> None:
    """非交互终端: 提示改用 qxt login, 不阻塞。"""
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr("builtins.input", lambda _: "2")
    assert _cmd_account(None, None, "") is True
    out = capsys.readouterr().out
    assert "qxt login" in out


def test_account_menu_login_failure(monkeypatch, capsys) -> None:
    """登录抛 AuthError: 报告失败且不崩溃。"""
    _patch_env(monkeypatch)

    def _boom(self):
        from qingxiaotuan.auth import AuthError

        raise AuthError("授权失败")

    monkeypatch.setattr(FakeProvider, "login", _boom)
    monkeypatch.setattr("builtins.input", lambda _: "2")
    assert _cmd_account(None, None, "") is True
    out = capsys.readouterr().out
    assert "登录失败" in out
