"""cmd_upgrade tests -- auto-update version comparison + install cmd."""
from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from tuan_cli.cli import cmd_upgrade as P


# ---------------------------------------------------------------- compare_versions

class TestCompareVersions:
    def test_equal(self):
        assert P.compare_versions("1.0.0", "1.0.0") == 0

    def test_less(self):
        assert P.compare_versions("1.0.0", "1.0.1") == -1

    def test_greater(self):
        assert P.compare_versions("1.1.0", "1.0.0") == 1

    def test_zero_padded(self):
        # 0.2.017 == 0.2.17
        assert P.compare_versions("0.2.017", "0.2.17") == 0

    def test_different_lengths(self):
        assert P.compare_versions("1.0", "1.0.0") == 0
        assert P.compare_versions("1.0", "1.0.1") == -1

    def test_empty_string(self):
        assert P.compare_versions("", "0.0.1") == -1


# ---------------------------------------------------------------- pip install cmd

class TestPipInstallCmd:
    def test_with_version(self):
        cmd = P._pip_install_cmd("1.2.3")
        assert "pip" in cmd
        assert "install" in cmd
        assert "--upgrade" in cmd
        assert "tuan-cli==1.2.3" in cmd

    def test_without_version(self):
        cmd = P._pip_install_cmd("")
        assert "tuan-cli" in cmd
        # no pinning
        assert "tuan-cli==" not in " ".join(cmd)

    def test_uses_current_interpreter(self):
        cmd = P._pip_install_cmd("1.0.0")
        assert cmd[0] == sys.executable


# ---------------------------------------------------------------- dispatch (mocked network)

class TestUpgradeDispatch:
    def test_already_latest(self, capsys, monkeypatch):
        monkeypatch.setattr(P, "fetch_latest", lambda timeout=10.0: ("0.0.1", "desc"))
        rc = P.cmd_upgrade(SimpleNamespace(version=None, check=False, yes=True))
        assert rc == 0
        assert "已是最新" in capsys.readouterr().out

    def test_network_error(self, capsys, monkeypatch):
        def _fail(*a, **kw):
            import urllib.error
            raise urllib.error.URLError("no network")
        monkeypatch.setattr(P, "fetch_latest", _fail)
        rc = P.cmd_upgrade(SimpleNamespace(version=None, check=False, yes=True))
        assert rc == 1
        out = capsys.readouterr().out
        assert "网络不可达" in out

    def test_check_mode(self, capsys, monkeypatch):
        monkeypatch.setattr(P, "fetch_latest",
                            lambda timeout=10.0: ("99.0.0", "desc"))
        rc = P.cmd_upgrade(SimpleNamespace(version=None, check=True, yes=True))
        assert rc == 0
        out = capsys.readouterr().out
        assert "发现新版本" in out
        assert "--check" in out
