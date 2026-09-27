"""`qxt ecosystem` CLI 测试: 解析器注册 + link 写 .mcp.json + import 端到端。"""

from __future__ import annotations

import json
from pathlib import Path

from qingxiaotuan.cli.parser import build_parser


def _write(p: Path, text: str):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def test_parser_registers_ecosystem_subcommands():
    parser = build_parser()
    for argv in (
        ["ecosystem", "scan"],
        ["ecosystem", "status"],
        ["ecosystem", "import", "skills", "--from", "hermes"],
        ["ecosystem", "import", "all", "--force"],
        ["ecosystem", "export", "skills", "--to", "claude"],
        ["ecosystem", "link", "--apply"],
        ["ecosystem", "serve"],
    ):
        args = parser.parse_args(argv)
        assert args.cmd == "ecosystem"
        assert args.func == "cmd_ecosystem"


def test_parser_rejects_bad_kind():
    parser = build_parser()
    import pytest

    with pytest.raises(SystemExit):
        parser.parse_args(["ecosystem", "import", "bogus"])


def test_link_writes_claude_mcp_json(tmp_path: Path):
    from qingxiaotuan.cli.cmd_ecosystem import cmd_ecosystem
    from qingxiaotuan.cli.parser import build_parser as bp

    ws = tmp_path / "ws"
    ws.mkdir()
    parser = bp()
    # 全局参数 (--profile/--workspace) 必须位于子命令之前
    args = parser.parse_args(["--profile", "ecosystem_test", "--workspace", str(ws),
                              "ecosystem", "link"])
    assert cmd_ecosystem(args) == 0
    mcp_json = ws / ".mcp.json"
    assert mcp_json.exists()
    data = json.loads(mcp_json.read_text(encoding="utf-8"))
    assert "qxt" in data["mcpServers"]
    assert data["mcpServers"]["qxt"]["args"][:2] == ["ecosystem", "serve"]


def test_import_skills_e2e(tmp_path: Path, monkeypatch):
    from qingxiaotuan.cli.cmd_ecosystem import cmd_ecosystem
    from qingxiaotuan.cli.parser import build_parser as bp
    from qingxiaotuan.config import Config

    # 隔离 qxt home, 避免污染真实用户配置
    qxt_home = tmp_path / "qxt"
    hermes_home = tmp_path / "hermes"
    _write(hermes_home / "skills" / "from-hermes" / "SKILL.md",
           "---\nname: FromHermes\ndescription: 来自 Hermes 的技能\n---\n正文\n")
    monkeypatch.setenv("QXT_HOME", str(qxt_home))
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))

    parser = bp()
    args = parser.parse_args(["--profile", "ecosystem_test",
                              "ecosystem", "import", "skills", "--from", "hermes"])
    assert cmd_ecosystem(args) == 0
    from qingxiaotuan.skills.manager import SkillManager

    cfg = Config(profile="ecosystem_test", bare=False)
    mgr = SkillManager(cfg.home)
    slugs = [s.slug for s in mgr.list_all()]
    assert "from-hermes" in slugs
