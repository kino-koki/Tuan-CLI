"""cmd_gh tests -- GitHub CLI passthrough (help/usage/dispatch + pure helpers)."""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any, List

import pytest

from tuan_cli.cli import cmd_gh as P
from tuan_cli.cli.cmd_gh import (_pop_flag, _pop_option, _pop_positional,
                                  _looks_like_auth_failure)


# ---------------------------------------------------------------- parse helpers

class TestParseHelpers:
    def test_pop_flag_present(self):
        argv = ["--json", "foo"]
        assert _pop_flag(argv, "json") is True
        assert argv == ["foo"]

    def test_pop_flag_short(self):
        argv = ["-q", "bar"]
        assert _pop_flag(argv, "q") is True
        assert argv == ["bar"]

    def test_pop_flag_absent(self):
        argv = ["a", "b"]
        assert _pop_flag(argv, "json") is False
        assert argv == ["a", "b"]

    def test_pop_flag_equals(self):
        argv = ["--key=1"]
        assert _pop_flag(argv, "key") is True
        assert argv == []

    def test_pop_option_long(self):
        argv = ["--limit", "5", "x"]
        assert _pop_option(argv, "limit") == "5"
        assert argv == ["x"]

    def test_pop_option_equals(self):
        argv = ["--mode=repo"]
        assert _pop_option(argv, "mode") == "repo"
        assert argv == []

    def test_pop_option_default(self):
        argv = ["a"]
        assert _pop_option(argv, "mode", default="code") == "code"

    def test_pop_positional(self):
        argv = ["hello", "--flag", "world", "-x"]
        pos = _pop_positional(argv)
        assert pos == ["hello", "world"]
        assert argv == ["--flag", "-x"]


# ---------------------------------------------------------------- auth failure detection

class TestAuthFailure:
    def test_not_logged_in(self):
        assert _looks_like_auth_failure("You are not logged in") is True

    def test_unauthorized(self):
        assert _looks_like_auth_failure("HTTP 401 unauthorized") is True

    def test_gh_auth_login_hint(self):
        assert _looks_like_auth_failure("please run 'gh auth login'") is True

    def test_normal_error(self):
        assert _looks_like_auth_failure("repository not found") is False

    def test_empty(self):
        assert _looks_like_auth_failure("") is False


# ---------------------------------------------------------------- dispatch

class TestDispatch:
    def test_no_args_shows_usage(self, capsys):
        rc = P.cmd_gh(SimpleNamespace(gh_args=[], rest=False))
        assert rc == 0
        assert "用法" in capsys.readouterr().out

    def test_help_flag(self, capsys):
        rc = P.cmd_gh(SimpleNamespace(gh_args=["--help"], rest=False))
        assert rc == 0
        assert "用法" in capsys.readouterr().out

    def test_h_flag(self, capsys):
        rc = P.cmd_gh(SimpleNamespace(gh_args=["-h"], rest=False))
        assert rc == 0
        assert "用法" in capsys.readouterr().out

    def test_policy_show(self, capsys, monkeypatch):
        monkeypatch.setattr(P, "load_policy",
                            lambda: SimpleNamespace(guard_extra=[], allow_extra=[],
                                                     verbose_guarded=False))
        rc = P.cmd_gh(SimpleNamespace(gh_args=["policy", "show"], rest=False))
        assert rc == 0
        out = capsys.readouterr().out
        assert "安全策略" in out

    def test_policy_no_sub(self, capsys, monkeypatch):
        monkeypatch.setattr(P, "load_policy",
                            lambda: SimpleNamespace(guard_extra=[], allow_extra=[],
                                                     verbose_guarded=False))
        rc = P.cmd_gh(SimpleNamespace(gh_args=["policy"], rest=False))
        assert rc == 0
        assert "安全策略" in capsys.readouterr().out
