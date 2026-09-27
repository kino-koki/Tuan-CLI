"""命令精简 (2026-09-27) 回归测试。

验证保守精简后的 CLI 表面:
- 已删/合并的 12 个顶级命令不再出现在 parser 中 (parse_args 报 invalid choice);
- 新的合并入口可正常解析 (session replay/trajectory, dev codedev, doctor --compact, undo --impact);
- 保留的核心命令仍可解析。
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from qingxiaotuan.cli.parser import build_parser, _rewrite_dev_codedev


def _parse(*argv):
    return build_parser().parse_args(list(argv))


# 已删除的顶级命令: 必须报 argparse 错误 (exit 2)
DELETED = [
    "arch", "ext", "others", "code-edit", "impact", "mode",
    "open", "replay", "trajectory", "compact", "bench", "codedev",
]


@pytest.mark.parametrize("cmd", DELETED)
def test_deleted_commands_rejected(cmd):
    with pytest.raises(SystemExit) as e:
        _parse(cmd)
    assert e.value.code == 2


@pytest.mark.parametrize("cmd", [
    "acp", "web", "run", "agent", "bg", "setup", "doctor", "onboarding",
    "commands", "models", "config", "plugin", "skill", "memory", "cron",
    "mcp", "hooks", "undo", "improve", "session", "usercmd", "agents",
    "rewind", "project", "chat", "worktree", "safe", "gh", "tutorial",
    "harden", "migrate", "network", "net", "help", "upgrade", "permissions",
])
def test_kept_commands_present(cmd):
    # 这些命令必须仍注册在 parser 中 (用 --help 触发 SystemExit 0, 而非 invalid choice 2)
    try:
        _parse(cmd, "--help")
    except SystemExit as e:
        code = e.code if isinstance(e.code, int) else 0
        assert code == 0, f"{cmd} 退出码 {code} (应为 0=help, 而非 2=invalid choice)"


# ---- 合并后的新入口 ----

def test_session_replay_parses():
    args = _parse("session", "replay", "abc", "--json")
    assert args.session_cmd == "replay"
    assert args.func == "cmd_session"
    assert args.session == "abc"
    assert args.json is True


def test_session_trajectory_show_parses():
    args = _parse("session", "trajectory", "show", "abc")
    assert args.session_cmd == "trajectory"
    assert args.traj_cmd == "show"
    assert args.func == "cmd_session"


def test_session_trajectory_export_parses():
    args = _parse("session", "trajectory", "export", "abc", "--format", "json", "--out", "x.md")
    assert args.traj_cmd == "export"
    assert args.format == "json"


def test_doctor_compact_parses():
    args = _parse("doctor", "--compact")
    assert args.func == "cmd_doctor"
    assert args.compact is True


def test_undo_impact_flag():
    args = _parse("undo", "--impact")
    assert args.func == "cmd_undo"
    assert args.impact is True


def test_dev_codedev_rewrite_helper():
    assert _rewrite_dev_codedev(["dev", "codedev", "demo"]) == ["__dev_codedev", "demo"]
    assert _rewrite_dev_codedev(["dev", "codedev", "retrieve", "task", "--root", "."]) == [
        "__dev_codedev", "retrieve", "task", "--root", ".",
    ]
    # 普通 dev 任务不受影响
    assert _rewrite_dev_codedev(["dev", "build the thing"]) == ["dev", "build the thing"]


def test_dev_codedev_hidden_parser_parses():
    args = _parse("__dev_codedev", "demo")
    assert args.func == "cmd_codedev"
    assert args.codedev_cmd == "demo"
    args = _parse("__dev_codedev", "retrieve", "do x", "--root", ".", "--top-k", "4")
    assert args.codedev_cmd == "retrieve"
    assert args.task == "do x"
    assert args.top_k == 4


def test_dev_task_still_parses():
    args = _parse("dev", "build the thing")
    assert args.func == "cmd_dev"
    assert args.task == "build the thing"
