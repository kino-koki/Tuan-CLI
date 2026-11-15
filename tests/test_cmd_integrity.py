"""cmd_integrity 测试 —— 文件完整性可观测性 CLI (纯只读)。"""
from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any, List

import pytest

from tuan_cli.cli import cmd_integrity as P
from tuan_cli.core.file_integrity import IntegrityChange


# ---------------------------------------------------------------- fakes

class _FakeMonitor:
    def __init__(self, changes: List[IntegrityChange]):
        self._changes = changes

    def get_changes(self, *, severity=None, change_type=None,
                    path_pattern=None, last_n=100):
        results = list(self._changes)
        if severity:
            results = [c for c in results if c.severity == severity]
        if change_type:
            results = [c for c in results if c.change_type == change_type]
        if path_pattern:
            import fnmatch
            results = [c for c in results if fnmatch.fnmatch(c.path, path_pattern)]
        return results[-last_n:]

    def stats(self):
        by_type: dict = {}
        by_sev: dict = {}
        for c in self._changes:
            by_type[c.change_type] = by_type.get(c.change_type, 0) + 1
            by_sev[c.severity] = by_sev.get(c.severity, 0) + 1
        return {"total_changes": len(self._changes),
                "by_type": by_type, "by_severity": by_sev}

    def export_report(self, last_n=50):
        return f"# 报告\n\n总变更: {len(self._changes)}\n"


def _chg(path="soul.md", ct="modified", sev="high", ts=1700000000.0):
    return IntegrityChange(
        path=path, change_type=ct,
        old_sha256="a" * 8, new_sha256="b" * 8,
        severity=sev, detected_at=ts, details="details-of-change",
    )


def _args(**kw):
    base = dict(integrity_cmd=None, home=None, json=False, last=None,
                severity=None, change_type=None, path_pattern=None)
    base.update(kw)
    return SimpleNamespace(**base)


@pytest.fixture(autouse=True)
def _patch_monitor(monkeypatch):
    holder: dict = {"monitor": _FakeMonitor([_chg()])}
    monkeypatch.setattr(P, "_get_monitor", lambda home_raw: holder["monitor"])
    return holder


# ---------------------------------------------------------------- 纯函数

class TestHelpers:
    def test_fmt_time(self):
        out = P._fmt_time(1700000000.0)
        assert isinstance(out, str) and len(out) >= 19

    def test_fmt_time_bad(self):
        # time.localtime 对 str 会抛错, 走 except 分支
        assert P._fmt_time("bad") == "-"

    def test_sev_color(self):
        assert P._sev_color("high") == "red"
        assert P._sev_color("critical") == "red"
        assert P._sev_color("medium") == "yellow"
        assert P._sev_color("low") == "dim"
        assert P._sev_color("unknown") == "dim"

    def test_change_dict(self):
        c = _chg()
        d = P._change_dict(c)
        assert d["path"] == "soul.md"
        assert d["change_type"] == "modified"
        assert d["severity"] == "high"
        assert d["old_sha256"] == "a" * 8
        assert "time" in d and "detected_at" in d

    def test_get_monitor_exists(self):
        # 占位: 验证 _get_monitor 可调用 (autouse fixture 已把它替换掉)
        assert callable(P._get_monitor)


# ---------------------------------------------------------------- overview

class TestOverview:
    def test_text_overview(self, capsys):
        rc = P.cmd_integrity(_args())
        assert rc == 0
        out = capsys.readouterr().out
        assert "文件完整性监控" in out
        assert "总变更数: 1" in out

    def test_json_overview(self, capsys):
        rc = P.cmd_integrity(_args(json=True))
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert data["stats"]["total_changes"] == 1
        assert len(data["recent"]) == 1

    def test_overview_empty(self, capsys, _patch_monitor):
        _patch_monitor["monitor"] = _FakeMonitor([])
        rc = P.cmd_integrity(_args())
        assert rc == 0
        out = capsys.readouterr().out
        assert "暂无变更记录" in out


# ---------------------------------------------------------------- changes

class TestChanges:
    def test_changes_text(self, capsys):
        rc = P.cmd_integrity(_args(integrity_cmd="changes"))
        assert rc == 0
        out = capsys.readouterr().out
        assert "变更历史" in out
        assert "modified" in out

    def test_changes_json(self, capsys):
        rc = P.cmd_integrity(_args(integrity_cmd="changes", json=True))
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert isinstance(data, list) and len(data) == 1
        assert data[0]["path"] == "soul.md"

    def test_changes_empty(self, capsys, _patch_monitor):
        _patch_monitor["monitor"] = _FakeMonitor([])
        rc = P.cmd_integrity(_args(integrity_cmd="changes"))
        assert rc == 0
        assert "暂无变更记录" in capsys.readouterr().out

    def test_changes_filter_severity(self, capsys, _patch_monitor):
        _patch_monitor["monitor"] = _FakeMonitor([
            _chg(path="a", sev="high"),
            _chg(path="b", sev="low"),
        ])
        rc = P.cmd_integrity(_args(integrity_cmd="changes", json=True, severity="high"))
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert len(data) == 1 and data[0]["path"] == "a"


# ---------------------------------------------------------------- stats

class TestStats:
    def test_text_stats(self, capsys):
        rc = P.cmd_integrity(_args(integrity_cmd="stats"))
        assert rc == 0
        out = capsys.readouterr().out
        assert "变更统计" in out
        assert "总变更数: 1" in out

    def test_json_stats(self, capsys):
        rc = P.cmd_integrity(_args(integrity_cmd="stats", json=True))
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert data["total_changes"] == 1
        assert data["by_type"]["modified"] == 1


# ---------------------------------------------------------------- report

class TestReport:
    def test_report(self, capsys):
        rc = P.cmd_integrity(_args(integrity_cmd="report"))
        assert rc == 0
        out = capsys.readouterr().out
        assert "# 报告" in out


# ---------------------------------------------------------------- 未知子命令

class TestUnknown:
    def test_unknown_sub(self, capsys):
        rc = P.cmd_integrity(_args(integrity_cmd="nope"))
        assert rc == 1
        out = capsys.readouterr().out
        assert "未知子命令" in out

    def test_default_overview(self, capsys):
        # integrity_cmd=None 走 overview
        rc = P.cmd_integrity(_args(integrity_cmd=None))
        assert rc == 0
        assert "文件完整性监控" in capsys.readouterr().out

    def test_status_alias(self, capsys):
        rc = P.cmd_integrity(_args(integrity_cmd="status"))
        assert rc == 0
        assert "文件完整性监控" in capsys.readouterr().out
