"""cmd_trust tests -- workspace trust CLI (status/check/set/remove/cleanup/export/import)."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import pytest

from tuan_cli.cli import cmd_trust as P


# ---------------------------------------------------------------- fakes

@dataclass
class FakeRecord:
    path: str
    level: str = "trusted"
    project_name: str = ""
    fingerprint: str = "a" * 64
    last_used: float = 1700000000.0
    trust_count: int = 1
    decayed_at: Optional[float] = None
    decay_reason: str = ""


class FakeTrust:
    def __init__(self, records: Optional[List[FakeRecord]] = None):
        self._records = records or []

    def list_trusted(self):
        return list(self._records)

    def check_trust(self, path):
        for r in self._records:
            if r.path == path:
                return r.level
        return "unknown"

    def get_project_info(self, path):
        for r in self._records:
            if r.path == path:
                return {"fingerprint": r.fingerprint,
                        "last_used": str(r.last_used),
                        "decay_reason": r.decay_reason or None}
        return {"fingerprint": "-", "last_used": "-", "decay_reason": None}

    def set_trust(self, path, level, project_name=""):
        rec = FakeRecord(path=path, level=level, project_name=project_name)
        self._records.append(rec)
        return rec

    def remove(self, path):
        for i, r in enumerate(self._records):
            if r.path == path:
                self._records.pop(i)
                return True
        return False

    def cleanup(self):
        return 2

    def export_policy(self):
        return {"entries": [{"path": r.path, "level": r.level}
                            for r in self._records]}

    def import_policy(self, data, overwrite=False):
        return {"imported": 3, "skipped": 1, "invalid": 0}

    def check_for_decay(self, path):
        return None

    def apply_decay(self, path, reason):
        for r in self._records:
            if r.path == path:
                r.level = "limited"
                r.decayed_at = 1700000000.0
                r.decay_reason = reason
                return r
        return FakeRecord(path=path, level="limited")

    def update_last_used(self, path):
        pass


@pytest.fixture(autouse=True)
def _patch(monkeypatch, tmp_path):
    monkeypatch.setattr("tuan_cli.config.loader.home_dir", lambda: tmp_path)
    monkeypatch.setattr("tuan_cli.core.workspace_trust.WorkspaceTrust",
                        lambda home: FakeTrust())
    return tmp_path


def _args(**kw):
    base = dict(trust_cmd=None, path=None, level=None, name="",
                all=False, file=None, overwrite=False, json=False,
                force=False, touch=False)
    base.update(kw)
    return SimpleNamespace(**base)


# ---------------------------------------------------------------- helpers

class TestHelpers:
    def test_opt_str(self):
        assert P._opt_str(None) is None
        assert P._opt_str(123) == "123"
        assert P._opt_str("x") == "x"

    def test_render_level(self, capsys):
        P._render_level("trusted")
        out = capsys.readouterr().out
        assert "trusted" in out


# ---------------------------------------------------------------- dispatch

class TestDispatch:
    def test_default_status(self, capsys):
        rc = P.cmd_trust(_args())
        assert rc == 0
        out = capsys.readouterr().out
        assert "工作区信任" in out


# ---------------------------------------------------------------- status

class TestStatus:
    def test_status_empty(self, capsys):
        rc = P.cmd_trust(_args(trust_cmd="status"))
        assert rc == 0
        out = capsys.readouterr().out
        assert "暂无受信工作区" in out

    def test_status_with_records(self, capsys, monkeypatch):
        monkeypatch.setattr(
            "tuan_cli.core.workspace_trust.WorkspaceTrust",
            lambda home: FakeTrust([
                FakeRecord(path="/a", level="trusted"),
                FakeRecord(path="/b", level="limited"),
            ]))
        rc = P.cmd_trust(_args(trust_cmd="status", all=True))
        assert rc == 0
        out = capsys.readouterr().out
        assert "/a" in out and "/b" in out


# ---------------------------------------------------------------- check

class TestCheck:
    def test_check_missing_path(self, capsys):
        rc = P.cmd_trust(_args(trust_cmd="check"))
        assert rc == 1
        assert "用法" in capsys.readouterr().out

    def test_check_ok(self, capsys, tmp_path):
        monkeypatch_setattr = None
        p = tmp_path / "proj"
        p.mkdir()
        import tuan_cli.core.workspace_trust as wt
        wt.WorkspaceTrust = lambda home: FakeTrust([
            FakeRecord(path=str(p), level="trusted")])
        rc = P.cmd_trust(_args(trust_cmd="check", path=str(p)))
        assert rc == 0
        out = capsys.readouterr().out
        assert "trusted" in out


# ---------------------------------------------------------------- set

class TestSet:
    def test_set_missing_path(self, capsys):
        rc = P.cmd_trust(_args(trust_cmd="set"))
        assert rc == 1
        assert "用法" in capsys.readouterr().out

    def test_set_ok(self, capsys, tmp_path):
        import tuan_cli.core.workspace_trust as wt
        ft = FakeTrust()
        wt.WorkspaceTrust = lambda home: ft
        p = tmp_path / "proj"
        p.mkdir()
        rc = P.cmd_trust(_args(trust_cmd="set", path=str(p), level="trusted"))
        assert rc == 0
        assert "已标记" in capsys.readouterr().out


# ---------------------------------------------------------------- remove

class TestRemove:
    def test_remove_missing_path(self, capsys):
        rc = P.cmd_trust(_args(trust_cmd="remove"))
        assert rc == 1
        assert "用法" in capsys.readouterr().out

    def test_remove_ok(self, capsys, tmp_path):
        import tuan_cli.core.workspace_trust as wt
        p = tmp_path / "proj"
        wt.WorkspaceTrust = lambda home: FakeTrust([
            FakeRecord(path=str(p))])
        rc = P.cmd_trust(_args(trust_cmd="remove", path=str(p)))
        assert rc == 0
        assert "已移除" in capsys.readouterr().out


# ---------------------------------------------------------------- cleanup

class TestCleanup:
    def test_cleanup(self, capsys):
        rc = P.cmd_trust(_args(trust_cmd="cleanup"))
        assert rc == 0
        assert "已清理 2" in capsys.readouterr().out


# ---------------------------------------------------------------- matrix

class TestMatrix:
    def test_matrix_text(self, capsys):
        rc = P.cmd_trust(_args(trust_cmd="matrix"))
        assert rc == 0
        out = capsys.readouterr().out
        assert "动作矩阵" in out

    def test_matrix_json(self, capsys):
        rc = P.cmd_trust(_args(trust_cmd="matrix", json=True))
        assert rc == 0
        d = json.loads(capsys.readouterr().out)
        assert "levels" in d and "matrix" in d


# ---------------------------------------------------------------- audit

class TestAudit:
    def test_audit_empty(self, capsys):
        rc = P.cmd_trust(_args(trust_cmd="audit"))
        assert rc == 0
        assert "已记录工作区" in capsys.readouterr().out

    def test_audit_json(self, capsys, monkeypatch):
        monkeypatch.setattr(
            "tuan_cli.core.workspace_trust.WorkspaceTrust",
            lambda home: FakeTrust([
                FakeRecord(path="/a", level="trusted"),
                FakeRecord(path="/b", level="limited", decay_reason="指纹变化"),
            ]))
        rc = P.cmd_trust(_args(trust_cmd="audit", json=True))
        assert rc == 0
        d = json.loads(capsys.readouterr().out)
        assert d["total"] == 2
        assert d["decayed"] == 1


# ---------------------------------------------------------------- export/import

class TestExportImport:
    def test_export_stdout(self, tmp_path, monkeypatch):
        import io
        import sys as _sys
        p = tmp_path / "proj"
        monkeypatch.setattr(
            "tuan_cli.core.workspace_trust.WorkspaceTrust",
            lambda home: FakeTrust([FakeRecord(path=str(p))]))
        buf = io.StringIO()
        old = _sys.stdout
        _sys.stdout = buf
        try:
            rc = P.cmd_trust(_args(trust_cmd="export"))
        finally:
            _sys.stdout = old
        assert rc == 0
        d = json.loads(buf.getvalue())
        assert "entries" in d

    def test_export_file(self, capsys, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "tuan_cli.core.workspace_trust.WorkspaceTrust",
            lambda home: FakeTrust([FakeRecord(path="/a")]))
        out = tmp_path / "policy.json"
        rc = P.cmd_trust(_args(trust_cmd="export", file=str(out)))
        assert rc == 0
        assert out.exists()

    def test_import_missing_file(self, capsys):
        rc = P.cmd_trust(_args(trust_cmd="import"))
        assert rc == 1
        assert "用法" in capsys.readouterr().out

    def test_import_ok(self, capsys, tmp_path):
        f = tmp_path / "policy.json"
        f.write_text(json.dumps({"entries": []}), encoding="utf-8")
        rc = P.cmd_trust(_args(trust_cmd="import", file=str(f)))
        assert rc == 0
        assert "已导入" in capsys.readouterr().out
