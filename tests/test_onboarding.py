"""首次运行 Onboarding 引导测试 (tuan_cli/cli/cmd_onboarding.py)。"""

import sys
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tuan_cli.cli import cmd_onboarding
from tuan_cli.cli import commands


def test_first_run_detection(tmp_path, monkeypatch):
    """无标记文件 -> 首次运行; 写入标记后 -> 不再是首次。"""
    monkeypatch.setenv("TUAN_HOME", str(tmp_path / "home"))
    home = tmp_path / "home"
    assert cmd_onboarding.is_first_run(home) is True
    cmd_onboarding.mark_onboarding_done(home)
    assert cmd_onboarding.is_first_run(home) is False
    assert cmd_onboarding.onboarding_done_marker(home).exists()


def test_skip_writes_marker(tmp_path, monkeypatch, capsys):
    """--skip 写完成标记且不交互。"""
    monkeypatch.setenv("TUAN_HOME", str(tmp_path / "home"))
    home = tmp_path / "home"
    args = mock.Mock(workspace=str(tmp_path), skip=True)
    assert commands.cmd_onboarding(args) == 0
    assert cmd_onboarding.onboarding_done_marker(home).exists()
    assert "跳过" in capsys.readouterr().out


def test_non_interactive_auto_skips(tmp_path, monkeypatch, capsys):
    """非交互模式: 不提问, 打印快速上手, 写标记。"""
    monkeypatch.setenv("TUAN_HOME", str(tmp_path / "home"))
    home = tmp_path / "home"
    # interactive=False -> 走非交互分支
    rc = cmd_onboarding.run_onboarding(tmp_path, home=home, interactive=False)
    assert rc == 0
    out = capsys.readouterr().out
    # 快速上手卡片含关键命令
    assert "tuan setup" in out
    assert "tuan run" in out
    assert "/help" in out
    assert "/goal" in out
    # 已写标记, 下次不再打扰
    assert cmd_onboarding.onboarding_done_marker(home).exists()


def test_quick_start_card_has_key_commands(tmp_path, monkeypatch, capsys):
    """快速上手卡片从模型配置指向实际可用的入口命令。"""
    monkeypatch.setenv("TUAN_HOME", str(tmp_path / "home"))
    cmd_onboarding.run_onboarding(tmp_path, home=tmp_path / "home", interactive=False)
    out = capsys.readouterr().out
    for token in ("tuan setup", "tuan run", "/goal", "/help"):
        assert token in out, token


def test_interactive_welcome_and_mark(tmp_path, monkeypatch, capsys):
    """交互模式 (模拟输入): 走完整流程并写标记。

    tmp_path 可能位于任意 git 仓库内 (如仓库内 basetemp 时),
    _detect_git_repo 会因此额外输出项目规则提示。此处钉死 "非 git 仓库",
    让交互固定为是否启动模型配置向导一个提问。
    """
    monkeypatch.setenv("TUAN_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(cmd_onboarding, "_detect_git_repo", lambda ws: False)
    home = tmp_path / "home"
    inputs = iter(["n"])  # 跳过模型配置
    with mock.patch("builtins.input", side_effect=lambda *a: next(inputs)):
        rc = cmd_onboarding.run_onboarding(tmp_path, home=home, interactive=True)
    assert rc == 0
    out = capsys.readouterr().out
    assert "欢迎" in out
    assert "tuan setup" in out
    assert cmd_onboarding.onboarding_done_marker(home).exists()


def test_interactive_onboarding_runs_setup_when_requested(tmp_path, monkeypatch):
    """选择立即配置时调用真实 setup 向导，而不是只记录未持久化的供应商偏好。"""
    monkeypatch.setenv("TUAN_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(cmd_onboarding, "_detect_git_repo", lambda ws: False)
    setup_calls = []
    monkeypatch.setattr(
        "tuan_cli.cli.cmd_setup.cmd_setup",
        lambda args: setup_calls.append(args) or 0,
        raising=False,
    )
    with mock.patch("builtins.input", return_value="y"):
        rc = cmd_onboarding.run_onboarding(
            tmp_path, home=tmp_path / "home", interactive=True
        )
    assert rc == 0
    assert setup_calls == [None]


def test_setup_failure_does_not_mark_onboarding_done(tmp_path, monkeypatch):
    """设置向导失败时不把首次引导标为完成，便于用户重试。"""
    monkeypatch.setenv("TUAN_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(cmd_onboarding, "_detect_git_repo", lambda ws: False)
    monkeypatch.setattr(
        "tuan_cli.cli.cmd_setup.cmd_setup",
        lambda args: 1,
        raising=False,
    )
    with mock.patch("builtins.input", return_value="y"):
        rc = cmd_onboarding.run_onboarding(
            tmp_path, home=tmp_path / "home", interactive=True
        )
    assert rc == 1
    assert not cmd_onboarding.onboarding_done_marker(tmp_path / "home").exists()


def test_onboarding_disabled_config(tmp_path, monkeypatch):
    """onboarding.enabled=false 时不视为首次运行。"""
    monkeypatch.setenv("TUAN_HOME", str(tmp_path / "home"))
    home = tmp_path / "home"
    home.mkdir(parents=True)
    (home / "config.yaml").write_text(
        "onboarding:\n  enabled: false\n", encoding="utf-8"
    )
    assert cmd_onboarding.is_first_run(home) is False
