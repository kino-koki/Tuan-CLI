"""测试: qxt upgrade 自动更新。

覆盖:
- 版本号比较 (零填充数字段)
- --check 仅检查不安装
- --yes 直接调用 pip 升级
- --version 指定版本 (跳过 PyPI)
- 网络失败优雅降级
"""

from __future__ import annotations

import urllib.error
from types import SimpleNamespace
from unittest import mock

from qingxiaotuan import __version__
from qingxiaotuan.cli import cmd_upgrade


# ----------------------------------------------------------------- 版本比较

def test_compare_versions():
    assert cmd_upgrade.compare_versions("0.2.017", "0.2.017") == 0
    assert cmd_upgrade.compare_versions("0.2.017", "0.2.018") == -1
    assert cmd_upgrade.compare_versions("0.2.018", "0.2.017") == 1
    assert cmd_upgrade.compare_versions("0.2.9", "0.2.10") == -1
    assert cmd_upgrade.compare_versions("0.3.0", "0.2.99") == 1
    # 自身版本不大于 latest
    assert cmd_upgrade.compare_versions(__version__, __version__) == 0


# ----------------------------------------------------------------- --check 不安装

def test_check_mode_does_not_install():
    args = SimpleNamespace(check=True, yes=False, version=None)
    with mock.patch.object(cmd_upgrade, "fetch_latest", return_value=("9.9.9", "测试版")), \
         mock.patch.object(cmd_upgrade.subprocess, "run") as run:
        rc = cmd_upgrade.cmd_upgrade(args)
    assert rc == 0
    run.assert_not_called()  # --check 不安装


def test_already_latest_returns_zero():
    args = SimpleNamespace(check=False, yes=False, version=None)
    with mock.patch.object(cmd_upgrade, "fetch_latest", return_value=(__version__, "")), \
         mock.patch.object(cmd_upgrade.subprocess, "run") as run:
        rc = cmd_upgrade.cmd_upgrade(args)
    assert rc == 0
    run.assert_not_called()


# ----------------------------------------------------------------- 实际升级

def test_yes_upgrade_invokes_pip():
    args = SimpleNamespace(check=False, yes=True, version=None)
    fake = mock.Mock(returncode=0, stdout="Successfully installed", stderr="")
    with mock.patch.object(cmd_upgrade, "fetch_latest", return_value=("9.9.9", "新版")), \
         mock.patch.object(cmd_upgrade.subprocess, "run", return_value=fake) as run:
        rc = cmd_upgrade.cmd_upgrade(args)
    assert rc == 0
    run.assert_called_once()
    cmd = run.call_args[0][0]
    assert "pip" in cmd
    assert "--upgrade" in cmd
    assert "qingxiaotuan==9.9.9" in cmd


def test_version_skips_pypi_and_installs():
    args = SimpleNamespace(check=False, yes=True, version="0.2.018")
    fake = mock.Mock(returncode=0, stdout="ok", stderr="")
    with mock.patch.object(cmd_upgrade, "fetch_latest") as fetch, \
         mock.patch.object(cmd_upgrade.subprocess, "run", return_value=fake) as run:
        rc = cmd_upgrade.cmd_upgrade(args)
    assert rc == 0
    fetch.assert_not_called()  # 指定版本不查 PyPI
    cmd = run.call_args[0][0]
    assert "qingxiaotuan==0.2.018" in cmd


# ----------------------------------------------------------------- 网络失败

def test_network_failure_degrades_gracefully():
    args = SimpleNamespace(check=False, yes=True, version=None)
    with mock.patch.object(cmd_upgrade, "fetch_latest",
                           side_effect=urllib.error.URLError("boom")):
        rc = cmd_upgrade.cmd_upgrade(args)
    assert rc == 1  # 优雅返回错误码, 不抛异常


def test_pip_failure_propagates_returncode():
    args = SimpleNamespace(check=False, yes=True, version=None)
    fake = mock.Mock(returncode=1, stdout="", stderr="pip failed")
    with mock.patch.object(cmd_upgrade, "fetch_latest", return_value=("9.9.9", "")), \
         mock.patch.object(cmd_upgrade.subprocess, "run", return_value=fake):
        rc = cmd_upgrade.cmd_upgrade(args)
    assert rc == 1
