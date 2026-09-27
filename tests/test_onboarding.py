"""首次运行 Onboarding 引导测试 (qingxiaotuan/cli/cmd_onboarding.py)。"""

import sys
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from qingxiaotuan.cli import cmd_onboarding
from qingxiaotuan.cli import commands


def test_first_run_detection(tmp_path, monkeypatch):
    """无标记文件 -> 首次运行; 写入标记后 -> 不再是首次。"""
    monkeypatch.setenv("QXT_HOME", str(tmp_path / "home"))
    home = tmp_path / "home"
    assert cmd_onboarding.is_first_run(home) is True
    cmd_onboarding.mark_onboarding_done(home)
    assert cmd_onboarding.is_first_run(home) is False
    assert cmd_onboarding.onboarding_done_marker(home).exists()


def test_skip_writes_marker(tmp_path, monkeypatch, capsys):
    """--skip 写完成标记且不交互。"""
    monkeypatch.setenv("QXT_HOME", str(tmp_path / "home"))
    home = tmp_path / "home"
    args = mock.Mock(workspace=str(tmp_path), skip=True)
    assert commands.cmd_onboarding(args) == 0
    assert cmd_onboarding.onboarding_done_marker(home).exists()
    assert "跳过" in capsys.readouterr().out


def test_non_interactive_auto_skips(tmp_path, monkeypatch, capsys):
    """非交互模式: 不提问, 打印快速上手, 写标记。"""
    monkeypatch.setenv("QXT_HOME", str(tmp_path / "home"))
    home = tmp_path / "home"
    # interactive=False -> 走非交互分支
    rc = cmd_onboarding.run_onboarding(tmp_path, home=home, interactive=False)
    assert rc == 0
    out = capsys.readouterr().out
    # 快速上手卡片含关键命令
    assert "/help" in out
    assert "/goal" in out or "qxt chat" in out
    # 已写标记, 下次不再打扰
    assert cmd_onboarding.onboarding_done_marker(home).exists()


def test_quick_start_card_has_key_commands(tmp_path, monkeypatch, capsys):
    """快速上手卡片包含 5 个关键命令。"""
    monkeypatch.setenv("QXT_HOME", str(tmp_path / "home"))
    cmd_onboarding.run_onboarding(tmp_path, home=tmp_path / "home", interactive=False)
    out = capsys.readouterr().out
    for token in ("qxt chat", "/goal", "/init", "/help"):
        assert token in out, token


def test_interactive_welcome_and_mark(tmp_path, monkeypatch, capsys):
    """交互模式 (模拟输入): 走完整流程并写标记。"""
    monkeypatch.setenv("QXT_HOME", str(tmp_path / "home"))
    home = tmp_path / "home"
    inputs = iter(["0", "n"])  # 跳过供应商, 关闭自动记忆
    with mock.patch("builtins.input", side_effect=lambda *a: next(inputs)):
        rc = cmd_onboarding.run_onboarding(tmp_path, home=home, interactive=True)
    assert rc == 0
    out = capsys.readouterr().out
    assert "欢迎" in out
    assert cmd_onboarding.onboarding_done_marker(home).exists()


def test_onboarding_disabled_config(tmp_path, monkeypatch):
    """onboarding.enabled=false 时不视为首次运行。"""
    monkeypatch.setenv("QXT_HOME", str(tmp_path / "home"))
    home = tmp_path / "home"
    home.mkdir(parents=True)
    (home / "config.yaml").write_text("onboarding:\n  enabled: false\n", encoding="utf-8")
    assert cmd_onboarding.is_first_run(home) is False
