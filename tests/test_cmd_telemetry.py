"""cmd_telemetry tests -- telemetry observability CLI."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, List

import pytest

from tuan_cli.cli import cmd_telemetry as P


@pytest.fixture(autouse=True)
def _patch(monkeypatch, tmp_path):
    monkeypatch.setattr("tuan_cli.cli.cmd_telemetry.home_dir", lambda: tmp_path)
    return tmp_path


def _args(**kw):
    base = dict(telemetry_cmd=None, json=False, n=20, path=None,
                endpoint=None, clear=False)
    base.update(kw)
    return SimpleNamespace(**base)


def _write_span(home: Path, spans: List[dict], fname: str = "spans_test.jsonl"):
    d = home / "telemetry"
    d.mkdir(parents=True, exist_ok=True)
    p = d / fname
    p.write_text("\n".join(json.dumps(s) for s in spans), encoding="utf-8")
    return p


def _span(name="tool_call", status="ok", ts=1700000000.0):
    return {"name": name, "status": status, "duration_ms": 10.0,
            "span_id": "abc12345", "start_time": ts}


# ---------------------------------------------------------------- helpers

class TestHelpers:
    def test_scan_exported_empty(self, tmp_path):
        assert P._scan_exported(tmp_path) == []

    def test_scan_exported_files(self, tmp_path):
        _write_span(tmp_path, [_span(), _span(ts=1700000100.0)])
        out = P._scan_exported(tmp_path)
        assert len(out) == 1
        assert out[0]["spans"] == 2
        assert out[0]["size_bytes"] > 0

    def test_scan_exported_skips_bad(self, tmp_path):
        d = tmp_path / "telemetry"
        d.mkdir()
        (d / "bad.jsonl").write_text("not json\n", encoding="utf-8")
        (d / "good.jsonl").write_text(json.dumps(_span()) + "\n", encoding="utf-8")
        out = P._scan_exported(tmp_path)
        assert len(out) == 2  # both files, but bad has 0 spans
        bad = next(e for e in out if e["file"] == "bad.jsonl")
        assert bad["spans"] == 0

    def test_load_exported_spans_empty(self, tmp_path):
        assert P._load_exported_spans(tmp_path, 10) == []

    def test_load_exported_spans_limit(self, tmp_path):
        _write_span(tmp_path, [_span(ts=i * 100.0) for i in range(10)])
        spans = P._load_exported_spans(tmp_path, 3)
        assert len(spans) == 3
        # should be the last 3 (highest ts)
        assert spans[-1]["start_time"] == 900.0


# ---------------------------------------------------------------- stats

class TestStats:
    def test_stats_text_empty(self, capsys, tmp_path, monkeypatch):
        class FakeTC:
            _AUTO_EXPORT_THRESHOLD = 500
            def __init__(self, home):
                pass
            def get_stats(self):
                return {"total_spans": 0, "total_traces": 0, "total_errors": 0,
                        "error_rate": 0.0, "total_tokens": 0, "total_tool_calls": 0,
                        "active_spans": 0, "avg_tool_latency_ms": 0.0,
                        "avg_model_latency_ms": 0.0}
        monkeypatch.setattr("tuan_cli.core.telemetry.TelemetryCollector", FakeTC)
        rc = P.cmd_telemetry(_args(telemetry_cmd="stats"))
        assert rc == 0
        out = capsys.readouterr().out
        assert "遥测统计" in out
        assert "本进程无 span" in out

    def test_stats_json(self, capsys, tmp_path, monkeypatch):
        _write_span(tmp_path, [_span(), _span()])
        class FakeTC:
            _AUTO_EXPORT_THRESHOLD = 500
            def __init__(self, home):
                pass
            def get_stats(self):
                return {"total_spans": 0, "total_traces": 0, "total_errors": 0,
                        "error_rate": 0.0, "total_tokens": 0, "total_tool_calls": 0,
                        "active_spans": 0, "avg_tool_latency_ms": 0.0,
                        "avg_model_latency_ms": 0.0}
        monkeypatch.setattr("tuan_cli.core.telemetry.TelemetryCollector", FakeTC)
        rc = P.cmd_telemetry(_args(telemetry_cmd="stats", json=True))
        assert rc == 0
        d = json.loads(capsys.readouterr().out)
        assert "memory" in d
        assert "exported_total_spans" in d
        assert d["exported_total_spans"] == 2


# ---------------------------------------------------------------- spans

class TestSpans:
    def test_spans_from_disk(self, capsys, tmp_path, monkeypatch):
        _write_span(tmp_path, [_span(), _span(status="error")])
        class FakeTC:
            _AUTO_EXPORT_THRESHOLD = 500
            def __init__(self, home):
                pass
            def get_stats(self):
                return {}
            def get_recent_spans(self, n):
                return []
        monkeypatch.setattr("tuan_cli.core.telemetry.TelemetryCollector", FakeTC)
        rc = P.cmd_telemetry(_args(telemetry_cmd="spans"))
        assert rc == 0
        out = capsys.readouterr().out
        assert "span" in out
        assert "tool_call" in out

    def test_spans_json(self, capsys, tmp_path, monkeypatch):
        _write_span(tmp_path, [_span()])
        class FakeTC:
            _AUTO_EXPORT_THRESHOLD = 500
            def __init__(self, home):
                pass
            def get_stats(self):
                return {}
            def get_recent_spans(self, n):
                return []
        monkeypatch.setattr("tuan_cli.core.telemetry.TelemetryCollector", FakeTC)
        rc = P.cmd_telemetry(_args(telemetry_cmd="spans", json=True))
        assert rc == 0
        d = json.loads(capsys.readouterr().out)
        assert d["count"] == 1
        assert d["source"] == "磁盘导出"


# ---------------------------------------------------------------- export

class TestExport:
    def test_export_empty(self, capsys, tmp_path, monkeypatch):
        class FakeTC:
            _AUTO_EXPORT_THRESHOLD = 500
            def __init__(self, home):
                pass
            def get_stats(self):
                return {}
            def export_jsonl(self, path):
                return 0
        monkeypatch.setattr("tuan_cli.core.telemetry.TelemetryCollector", FakeTC)
        rc = P.cmd_telemetry(_args(telemetry_cmd="export"))
        assert rc == 0
        assert "无可导出" in capsys.readouterr().out

    def test_export_json(self, capsys, tmp_path, monkeypatch):
        class FakeTC:
            _AUTO_EXPORT_THRESHOLD = 500
            def __init__(self, home):
                pass
            def get_stats(self):
                return {}
            def export_jsonl(self, path):
                return 42
        monkeypatch.setattr("tuan_cli.core.telemetry.TelemetryCollector", FakeTC)
        rc = P.cmd_telemetry(_args(telemetry_cmd="export", json=True))
        assert rc == 0
        d = json.loads(capsys.readouterr().out)
        assert d["exported"] == 42


# ---------------------------------------------------------------- otlp

class TestOtlp:
    def test_otlp_default(self, capsys, tmp_path, monkeypatch):
        class FakeTC:
            _AUTO_EXPORT_THRESHOLD = 500
            def __init__(self, home):
                pass
            def get_stats(self):
                return {"total_spans": 100}
            def should_auto_export(self):
                return False
            def auto_export(self):
                return 0
        monkeypatch.setattr("tuan_cli.core.telemetry.TelemetryCollector", FakeTC)
        rc = P.cmd_telemetry(_args(telemetry_cmd="otlp"))
        assert rc == 0
        out = capsys.readouterr().out
        assert "OTLP" in out
        assert "未达阈值" in out

    def test_otlp_clear(self, capsys, tmp_path, monkeypatch):
        class FakeTC:
            _AUTO_EXPORT_THRESHOLD = 500
            def __init__(self, home):
                pass
            def clear(self):
                pass
        monkeypatch.setattr("tuan_cli.core.telemetry.TelemetryCollector", FakeTC)
        rc = P.cmd_telemetry(_args(telemetry_cmd="otlp", clear=True))
        assert rc == 0
        assert "已清空" in capsys.readouterr().out

    def test_otlp_clear_json(self, capsys, tmp_path, monkeypatch):
        class FakeTC:
            _AUTO_EXPORT_THRESHOLD = 500
            def __init__(self, home):
                pass
            def clear(self):
                pass
        monkeypatch.setattr("tuan_cli.core.telemetry.TelemetryCollector", FakeTC)
        rc = P.cmd_telemetry(_args(telemetry_cmd="otlp", clear=True, json=True))
        assert rc == 0
        d = json.loads(capsys.readouterr().out)
        assert d["cleared"] is True
