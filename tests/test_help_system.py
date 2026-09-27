"""/help 增强与命令补全测试 (qingxiaotuan/cli/cmd_help.py)。"""

import json
import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from qingxiaotuan.cli import cmd_help
from qingxiaotuan.cli import commands


def test_categorized_help_groups_commands():
    """/help 分类输出含四大类, 且每类下列出命令。"""
    text = cmd_help.categorized_help_text()
    for cat in ("对话管理", "代码与工程", "技能与记忆", "系统与权限"):
        assert cat in text
    # 常用命令出现
    for n in ("/help", "/diff", "/skills", "/model"):
        assert n in text


def test_help_for_command_detail():
    """/help <command> 显示用法/参数/示例。"""
    out = cmd_help.help_for_command("diff")
    assert "用法" in out
    assert "示例" in out
    assert "/diff" in out


def test_help_for_keyboard():
    """/help keyboard 显示快捷键。"""
    out = cmd_help.help_for_command("keyboard")
    assert "Enter" in out
    assert "快捷键" in out


def test_help_unknown_command():
    out = cmd_help.help_for_command("/nonexistent")
    assert "未知命令" in out


def test_qxt_commands_json_output(capsys):
    """qxt commands 输出合法 JSON, 每个命令含 name/description。"""
    args = mock.Mock()
    assert commands.cmd_commands(args) == 0
    payload = json.loads(capsys.readouterr().out)
    assert "commands" in payload
    names = [c["name"] for c in payload["commands"]]
    assert "/help" in names
    # 每条都有 description
    for c in payload["commands"]:
        assert c["name"] and c["description"]


def test_acp_slash_commands_have_description():
    """ACP initialize 的 slash_commands 含 description 字段 (IDE 补全可展示)。"""
    from qingxiaotuan.cli.cmd_acp import _get_slash_commands
    cmds = _get_slash_commands()
    assert cmds, "ACP 斜杠命令不应为空"
    for c in cmds:
        assert "name" in c
        assert "description" in c
    # /help 应有描述
    help_cmd = next(c for c in cmds if c["name"] == "/help")
    assert help_cmd["description"]
