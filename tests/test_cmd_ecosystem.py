"""``tuan ecosystem`` CLI 的单元测试 (cmd_ecosystem.py)。

生态互操作。覆盖:
1. _hint: ok/fail
2. _sources_tuple: claude/hermes/all
3. _export_skill_targets: 全路径
4. _tuan_command: 返回 [python, -m, tuan_cli]
5. _cmd_scan: 正常渲染
6. _cmd_status: 正常渲染
7. _cmd_import: skills/memory/agents/context/mcp/all
8. _cmd_export: skills/agents/memory
9. _cmd_link: workspace/hermes 路径
10. _cmd_serve: 委派 serve_stdio
11. cmd_ecosystem: 未知子命令
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from tuan_cli.cli import cmd_ecosystem as P


def _args(**kw) -> SimpleNamespace:
    base = dict(ecosystem_cmd=None, kind="skills", profile="default",
                patch=None, workspace=None, ecosystem_from="all",
                ecosystem_to="all", force=False, apply=False,
                allow_dangerous=False)
    base.update(kw)
    return SimpleNamespace(**base)


class _FakeSummary:
    def __init__(self):
        self.d = {
            "skills": 3, "agents": 2, "commands": 5, "memories": 1,
            "soul": True, "mcp_servers": 0,
        }

    def to_dict(self):
        return dict(self.d)


class _FakeProbe:
    def __init__(self, **kw):
        self.workspace = kw.get("workspace", Path("/tmp/ws"))
        self.claude_home = kw.get("claude_home", Path("/tmp/.claude"))
        self.hermes_home = kw.get("hermes_home", Path("/tmp/.hermes"))
        self.claude_cli = kw.get("claude_cli", "/usr/bin/claude")
        self.hermes_cli = kw.get("hermes_cli", "/usr/bin/hermes")
        self.claude_agents_dirs = []
        self.hermes_memories_dirs = []
        self.summaries = {"claude_code": _FakeSummary(),
                          "hermes": _FakeSummary()}

    def summarize(self):
        return self.summaries


def _patch_probe(monkeypatch, **kw) -> None:
    probe = _FakeProbe(**kw)
    monkeypatch.setattr(P, "_probe", lambda args, config=None: probe)
    monkeypatch.setattr("tuan_cli.ecosystem.detect.EcosystemProbe.probe",
                        classmethod(lambda cls, ws, hermes_home=None: probe))
    return probe


# ============================================================ _hint


class TestHint:
    def test_ok(self):
        assert P._hint(True) == "✓"

    def test_fail(self):
        assert P._hint(False) == "✗"


# ============================================================ _sources_tuple


class TestSourcesTuple:
    def test_claude(self):
        assert P._sources_tuple("claude") == ("claude_code",)

    def test_hermes(self):
        assert P._sources_tuple("hermes") == ("hermes",)

    def test_all(self):
        assert P._sources_tuple("all") == ("claude_code", "hermes")


# ============================================================ _export_skill_targets


class TestExportSkillTargets:
    def test_claude_all(self):
        probe = _FakeProbe()
        targets = P._export_skill_targets(probe, "claude")
        assert len(targets) == 1
        assert targets[0][0] == "claude"

    def test_hermes_all(self):
        probe = _FakeProbe()
        targets = P._export_skill_targets(probe, "hermes")
        assert len(targets) == 1
        assert targets[0][0] == "hermes"

    def test_all_both(self):
        probe = _FakeProbe()
        targets = P._export_skill_targets(probe, "all")
        assert len(targets) == 2

    def test_no_workspace(self):
        probe = _FakeProbe(workspace=None)
        targets = P._export_skill_targets(probe, "claude")
        assert targets == []


# ============================================================ _tuan_command


class TestTuanCommand:
    def test_returns_python_module(self):
        cmd = P._tuan_command()
        assert cmd == [sys.executable, "-m", "tuan_cli"]


# ============================================================ _cmd_scan


class TestCmdScan:
    def test_normal(self, monkeypatch):
        _patch_probe(monkeypatch)
        monkeypatch.setattr("tuan_cli.ecosystem.detect.render_probe",
                            lambda probe: "probe render")
        monkeypatch.setattr(P.console, "print", lambda *a, **k: None)
        rc = P._cmd_scan(_args())
        assert rc == 0


# ============================================================ _cmd_status


class TestCmdStatus:
    def test_normal(self, monkeypatch):
        _patch_probe(monkeypatch)
        monkeypatch.setattr(P.console, "print", lambda *a, **k: None)
        rc = P._cmd_status(_args())
        assert rc == 0


# ============================================================ _cmd_import


class TestCmdImport:
    def test_skills(self, monkeypatch):
        _patch_probe(monkeypatch)
        monkeypatch.setattr(P, "_import_skills", lambda *a, **k: 3)
        monkeypatch.setattr(P.console, "print", lambda *a, **k: None)
        rc = P._cmd_import(_args(kind="skills"))
        assert rc == 0

    def test_memory_hermes_only(self, monkeypatch):
        _patch_probe(monkeypatch)
        monkeypatch.setattr(P, "_import_memory", lambda *a, **k: 5)
        monkeypatch.setattr(P.console, "print", lambda *a, **k: None)
        rc = P._cmd_import(_args(kind="memory", ecosystem_from="hermes"))
        assert rc == 0

    def test_memory_skip_claude(self, monkeypatch):
        _patch_probe(monkeypatch)
        monkeypatch.setattr(P.console, "print", lambda *a, **k: None)
        rc = P._cmd_import(_args(kind="memory", ecosystem_from="claude"))
        assert rc == 0

    def test_agents_claude_only(self, monkeypatch):
        _patch_probe(monkeypatch)
        monkeypatch.setattr(P, "_import_agents", lambda *a, **k: 2)
        monkeypatch.setattr(P.console, "print", lambda *a, **k: None)
        rc = P._cmd_import(_args(kind="agents", ecosystem_from="claude"))
        assert rc == 0

    def test_agents_skip_hermes(self, monkeypatch):
        _patch_probe(monkeypatch)
        monkeypatch.setattr(P.console, "print", lambda *a, **k: None)
        rc = P._cmd_import(_args(kind="agents", ecosystem_from="hermes"))
        assert rc == 0

    def test_context(self, monkeypatch):
        _patch_probe(monkeypatch)
        monkeypatch.setattr(P, "_import_context", lambda *a, **k: 1)
        monkeypatch.setattr(P.console, "print", lambda *a, **k: None)
        rc = P._cmd_import(_args(kind="context", ecosystem_from="hermes"))
        assert rc == 0

    def test_mcp(self, monkeypatch):
        _patch_probe(monkeypatch)
        monkeypatch.setattr(P, "_import_mcp", lambda *a, **k: 1)
        monkeypatch.setattr(P.console, "print", lambda *a, **k: None)
        rc = P._cmd_import(_args(kind="mcp"))
        assert rc == 0

    def test_all(self, monkeypatch):
        _patch_probe(monkeypatch)
        monkeypatch.setattr(P, "_import_skills", lambda *a, **k: 1)
        monkeypatch.setattr(P, "_import_memory", lambda *a, **k: 2)
        monkeypatch.setattr(P, "_import_agents", lambda *a, **k: 3)
        monkeypatch.setattr(P, "_import_context", lambda *a, **k: 4)
        monkeypatch.setattr(P, "_import_mcp", lambda *a, **k: 5)
        monkeypatch.setattr(P.console, "print", lambda *a, **k: None)
        rc = P._cmd_import(_args(kind="all"))
        assert rc == 0


# ============================================================ _cmd_export


class TestCmdExport:
    def test_skills(self, monkeypatch):
        _patch_probe(monkeypatch)
        monkeypatch.setattr(P, "_export_skill_targets",
                            lambda probe, dest: [("claude", Path("/tmp/x"))])
        monkeypatch.setattr(P.console, "print", lambda *a, **k: None)
        monkeypatch.setitem(sys.modules, "tuan_cli.ecosystem.skills_bridge",
                            SimpleNamespace(
                                export_skills=lambda m, d: SimpleNamespace(
                                    imported=[1, 2], errors=[])))
        monkeypatch.setitem(sys.modules, "tuan_cli.skills.manager",
                            SimpleNamespace(SkillManager=lambda *a, **k: None))
        rc = P._cmd_export(_args(kind="skills", ecosystem_to="claude"))
        assert rc == 0

    def test_agents(self, monkeypatch):
        _patch_probe(monkeypatch)
        monkeypatch.setattr(P, "_export_agents", lambda *a, **k: 2)
        monkeypatch.setattr(P.console, "print", lambda *a, **k: None)
        rc = P._cmd_export(_args(kind="agents"))
        assert rc == 0

    def test_memory(self, monkeypatch):
        _patch_probe(monkeypatch)
        monkeypatch.setattr(P, "_export_memory", lambda *a, **k: 1)
        monkeypatch.setattr(P.console, "print", lambda *a, **k: None)
        rc = P._cmd_export(_args(kind="memory"))
        assert rc == 0


# ============================================================ _cmd_link


class TestCmdLink:
    def test_with_workspace(self, monkeypatch, tmp_path):
        import tuan_cli.config.loader as L
        monkeypatch.setattr(L, "Config", lambda **k: SimpleNamespace(
            home=tmp_path, get=lambda *a, **k: None))
        monkeypatch.setattr(P.console, "print", lambda *a, **k: None)
        monkeypatch.setattr("tuan_cli.ecosystem.mcp_import.export_to_claude_mcp_json",
                            lambda *a, **k: SimpleNamespace(errors=[]))
        rc = P._cmd_link(_args(workspace=str(tmp_path)))
        assert rc == 0

    def test_no_workspace(self, monkeypatch, tmp_path):
        import tuan_cli.config.loader as L
        monkeypatch.setattr(L, "Config", lambda **k: SimpleNamespace(
            home=tmp_path, get=lambda *a, **k: None))
        monkeypatch.setattr(P.console, "print", lambda *a, **k: None)
        rc = P._cmd_link(_args(workspace=None))
        assert rc == 0


# ============================================================ _cmd_serve


class TestCmdServe:
    def test_delegates(self, monkeypatch):
        import tuan_cli.config.loader as L
        monkeypatch.setattr(L, "Config", lambda **k: SimpleNamespace(
            home=Path("/tmp/h")))
        monkeypatch.setattr("tuan_cli.ecosystem.mcp_server.serve_stdio",
                            lambda *a, **k: 0)
        rc = P._cmd_serve(_args())
        assert rc == 0


# ============================================================ cmd_ecosystem 入口


class TestCmdEcosystem:
    def test_default_scan(self, monkeypatch):
        _patch_probe(monkeypatch)
        monkeypatch.setattr("tuan_cli.ecosystem.detect.render_probe",
                            lambda probe: "render")
        monkeypatch.setattr(P.console, "print", lambda *a, **k: None)
        rc = P.cmd_ecosystem(_args())
        assert rc == 0

    def test_scan(self, monkeypatch):
        _patch_probe(monkeypatch)
        monkeypatch.setattr("tuan_cli.ecosystem.detect.render_probe",
                            lambda probe: "render")
        monkeypatch.setattr(P.console, "print", lambda *a, **k: None)
        rc = P.cmd_ecosystem(_args(ecosystem_cmd="scan"))
        assert rc == 0

    def test_status(self, monkeypatch):
        _patch_probe(monkeypatch)
        monkeypatch.setattr(P.console, "print", lambda *a, **k: None)
        rc = P.cmd_ecosystem(_args(ecosystem_cmd="status"))
        assert rc == 0

    def test_import(self, monkeypatch):
        _patch_probe(monkeypatch)
        monkeypatch.setattr(P, "_import_skills", lambda *a, **k: 1)
        monkeypatch.setattr(P.console, "print", lambda *a, **k: None)
        rc = P.cmd_ecosystem(_args(ecosystem_cmd="import", kind="skills"))
        assert rc == 0

    def test_export(self, monkeypatch):
        _patch_probe(monkeypatch)
        monkeypatch.setattr(P, "_export_agents", lambda *a, **k: 1)
        monkeypatch.setattr(P.console, "print", lambda *a, **k: None)
        rc = P.cmd_ecosystem(_args(ecosystem_cmd="export", kind="agents"))
        assert rc == 0

    def test_link(self, monkeypatch, tmp_path):
        import tuan_cli.config.loader as L
        monkeypatch.setattr(L, "Config", lambda **k: SimpleNamespace(
            home=tmp_path, get=lambda *a, **k: None))
        monkeypatch.setattr("tuan_cli.ecosystem.mcp_import.export_to_claude_mcp_json",
                            lambda *a, **k: SimpleNamespace(errors=[]))
        monkeypatch.setattr(P.console, "print", lambda *a, **k: None)
        rc = P.cmd_ecosystem(_args(ecosystem_cmd="link"))
        assert rc == 0

    def test_unknown(self, monkeypatch):
        printed = []
        monkeypatch.setattr(P.console, "print",
                            lambda msg, *a, **k: printed.append(str(msg)))
        rc = P.cmd_ecosystem(_args(ecosystem_cmd="bogus"))
        assert rc == 1
        assert any("未知" in p for p in printed)
