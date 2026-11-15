"""cmd_harden tests -- environment hardening diagnostics CLI."""
from __future__ import annotations

import pathlib
from types import SimpleNamespace

import pytest

from tuan_cli.cli import cmd_harden as P


def _args(**kw):
    base = dict(harden_cmd=None, format=None, out=None, push=None,
                from_=None, command=None, egress_cidr=None, one_way=False,
                verify=False)
    base.update(kw)
    return SimpleNamespace(**base)


# ---------------------------------------------------------------- resolve_bus_log

class TestResolveBusLog:
    def test_returns_path(self):
        p = P._resolve_bus_log()
        assert isinstance(p, pathlib.Path)

    def test_expected_name(self):
        p = P._resolve_bus_log()
        assert p.name in ("security-audit.jsonl", "security_events.jsonl")
        assert p.suffix == ".jsonl"


# ---------------------------------------------------------------- dispatch

class TestDispatch:
    def test_default_status(self, capsys):
        rc = P.cmd_harden(_args())
        assert rc == 0
        assert "加密后端" in capsys.readouterr().out

    def test_unknown_sub(self, capsys):
        rc = P.cmd_harden(_args(harden_cmd="nope"))
        assert rc == 1
        assert "用法" in capsys.readouterr().err


# ---------------------------------------------------------------- subcommands

class TestSubcommands:
    def test_status_ok(self, capsys):
        rc = P.cmd_harden(_args(harden_cmd="status"))
        assert rc == 0
        assert "加密后端" in capsys.readouterr().out

    def test_crypto_provider(self, capsys):
        rc = P.cmd_harden(_args(harden_cmd="crypto-provider"))
        assert rc == 0
        assert "可用密码学后端" in capsys.readouterr().out

    def test_sbom(self, capsys):
        rc = P.cmd_harden(_args(harden_cmd="sbom"))
        assert rc == 0
        assert "SBOM" in capsys.readouterr().out

    def test_repro_lock(self, capsys):
        rc = P.cmd_harden(_args(harden_cmd="repro-lock"))
        assert rc == 0
        assert "可复现锁" in capsys.readouterr().out

    def test_network_check_missing_command(self, capsys):
        rc = P.cmd_harden(_args(harden_cmd="network-check"))
        assert rc == 1
        assert "请通过" in capsys.readouterr().err

    def test_audit_export_missing_source(self, capsys):
        rc = P.cmd_harden(_args(harden_cmd="audit-export",
                                 from_=str(pathlib.Path("/nonexistent"))))
        assert rc == 1
        assert "未找到" in capsys.readouterr().err
