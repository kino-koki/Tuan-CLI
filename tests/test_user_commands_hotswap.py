# -*- coding: utf-8 -*-
"""热插拔命令系统测试: Python 代码命令 + 运行期 enable/disable/reload。"""
from pathlib import Path

import pytest

from qingxiaotuan.cli import user_commands as uc


class _Cfg:
    def __init__(self, home: Path):
        self.home = home


def _write_cmd(d: Path, name: str, body: str) -> Path:
    p = d / f"{name}.py"
    p.write_text(body, encoding="utf-8")
    return p


@pytest.fixture()
def cmds(tmp_path):
    d = tmp_path / "commands"
    d.mkdir()
    _write_cmd(d, "greet", (
        "---\n"
        "description: 打招呼命令\n"
        "argument-hint: <名字>\n"
        "---\n"
        "import qingxiaotuan.cli.user_commands as _uc\n"
        "def run(args, agent, config, workspace):\n"
        "    _uc._ui_store.append(('greet', args, workspace))\n"
        "    return True\n"
    ))
    uc._ui_store = []  # type: ignore[attr-defined]
    cfg = _Cfg(tmp_path)
    table = uc.load_user_commands(cfg, "")
    return cfg, table, uc._ui_store  # type: ignore[attr-defined]


def test_py_command_parsed(cmds):
    cfg, table, _ = cmds
    assert "greet" in table
    c = table["greet"]
    assert c.is_py
    assert c.description == "打招呼命令"
    assert c.argument_hint == "<名字>"


def test_py_command_runs(cmds, tmp_path):
    cfg, table, store = cmds
    c = table["greet"]
    ok = uc._run_py_command(c, "张三", None, cfg, str(tmp_path))
    assert ok is True
    assert store == [("greet", "张三", str(tmp_path))]


def test_py_command_missing_run(tmp_path):
    """缺 run 函数的命令: 报错但不崩溃, 返回 True (视为已处理)。"""
    d = tmp_path / "commands"
    d.mkdir()
    _write_cmd(d, "broken", "x = 1\n")
    cfg = _Cfg(tmp_path)
    table = uc.load_user_commands(cfg, "")
    ok = uc._run_py_command(table["broken"], "", None, cfg, str(tmp_path))
    assert ok is True


def test_py_command_syntax_error(tmp_path):
    """语法错误的命令: 报错但不崩溃。"""
    d = tmp_path / "commands"
    d.mkdir()
    _write_cmd(d, "bad", "def run(:\n    return True\n")
    cfg = _Cfg(tmp_path)
    table = uc.load_user_commands(cfg, "")
    ok = uc._run_py_command(table["bad"], "", None, cfg, str(tmp_path))
    assert ok is True


def test_enable_disable(tmp_path):
    d = tmp_path / "commands"
    d.mkdir()
    _write_cmd(d, "ping", "def run(args, agent, config, workspace):\n    return True\n")
    cfg = _Cfg(tmp_path)
    assert uc.reload_user_commands(cfg, "") == 1
    items = uc.describe_commands()
    assert items[0]["enabled"] is True
    assert uc.set_command_enabled("ping", False) is False
    assert uc.set_command_enabled("ping", True) is True
    assert uc.set_command_enabled("ghost", True) is None
    uc.set_command_enabled("ping", False)
    items = uc.describe_commands()
    assert items[0]["enabled"] is False


def test_reload_picks_up_new_file(tmp_path):
    d = tmp_path / "commands"
    d.mkdir()
    cfg = _Cfg(tmp_path)
    assert uc.reload_user_commands(cfg, "") == 0
    _write_cmd(d, "later", "def run(args, agent, config, workspace):\n    return True\n")
    assert uc.reload_user_commands(cfg, "") == 1
    assert uc.describe_commands()[0]["name"] == "later"


def test_md_command_still_parsed(tmp_path):
    d = tmp_path / "commands"
    d.mkdir()
    md = d / "review.md"
    md.write_text("---\ndescription: 代码评审\n---\n请评审 $ARGUMENTS", encoding="utf-8")
    cfg = _Cfg(tmp_path)
    table = uc.load_user_commands(cfg, "")
    c = table["review"]
    assert not c.is_py
    assert c.body == "请评审 $ARGUMENTS"
