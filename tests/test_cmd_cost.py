"""cmd_cost 单元测试 —— 成本/使用审计 CLI。"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from tuan_cli.cli import cmd_cost as P


# ============================================================ helpers


def _args(**kw) -> SimpleNamespace:
    base = dict(cost_cmd=None, last=20, top=5, json=False, days=14)
    base.update(kw)
    return SimpleNamespace(**base)


def _write_history(tmp_path: Path, rows: list) -> None:
    hist = tmp_path / "cost_history.jsonl"
    lines = [json.dumps(r, ensure_ascii=False) for r in rows]
    hist.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _route_row(**kw) -> dict:
    base = dict(kind="route", ts="2025-01-15T10:00:00", provider="openai",
                model="gpt-4", difficulty=5, local=False, offline=False,
                reason="high difficulty")
    base.update(kw)
    return base


def _usage_row(**kw) -> dict:
    base = dict(kind="usage", ts="2025-01-15T10:00:00", provider="openai",
                model="gpt-4", total_tokens=1500, est_cost_usd=0.003)
    base.update(kw)
    return base


@pytest.fixture(autouse=True)
def _patch_home(monkeypatch, tmp_path):
    import tuan_cli.config.loader as L
    monkeypatch.setattr(L, "home_dir", lambda: tmp_path)
    monkeypatch.setattr(P, "home_dir", lambda: tmp_path)
    monkeypatch.setattr(P.console, "print", lambda *a, **k: None)
    return tmp_path


# ============================================================ _load_history


class TestLoadHistory:
    def test_missing(self, tmp_path):
        assert P._load_history() == []

    def test_empty_lines(self, tmp_path):
        (tmp_path / "cost_history.jsonl").write_text("\n\n", encoding="utf-8")
        assert P._load_history() == []

    def test_valid_rows(self, tmp_path):
        _write_history(tmp_path, [_route_row(), _usage_row()])
        rows = P._load_history()
        assert len(rows) == 2
        assert rows[0]["kind"] == "route"
        assert rows[1]["kind"] == "usage"

    def test_malformed_skipped(self, tmp_path):
        (tmp_path / "cost_history.jsonl").write_text(
            "not json\n" + json.dumps(_route_row()) + "\n", encoding="utf-8")
        rows = P._load_history()
        assert len(rows) == 1


# ============================================================ cmd_cost dispatch


class TestCmdCostEmpty:
    def test_empty_returns_0(self):
        assert P.cmd_cost(_args()) == 0


class TestCmdCostReport:
    def test_default_report(self, tmp_path):
        _write_history(tmp_path, [_route_row(), _route_row(local=True)])
        assert P.cmd_cost(_args()) == 0

    def test_report_json(self, tmp_path, capsys):
        _write_history(tmp_path, [_route_row(), _usage_row()])
        assert P.cmd_cost(_args(json=True)) == 0
        data = json.loads(capsys.readouterr().out)
        assert data["total"] == 2
        assert data["route_decisions"] == 1
        assert data["usage_records"] == 1
        assert data["total_tokens"] == 1500
        assert "by_day" in data and "2025-01-15" in data["by_day"]
        assert "openai/gpt-4" in data["by_model"]

    def test_report_local_pct(self, tmp_path):
        _write_history(tmp_path, [_route_row(), _route_row(local=True), _route_row()])
        assert P.cmd_cost(_args()) == 0


class TestCmdCostLast:
    def test_last_text(self, tmp_path):
        _write_history(tmp_path, [_route_row(ts=f"2025-01-{i:02d}T00:00:00") for i in range(1, 6)])
        assert P.cmd_cost(_args(cost_cmd="last", last=3)) == 0

    def test_last_json(self, tmp_path, capsys):
        _write_history(tmp_path, [_route_row(), _route_row()])
        assert P.cmd_cost(_args(cost_cmd="last", json=True, last=1)) == 0
        data = json.loads(capsys.readouterr().out)
        assert len(data) == 1


class TestCmdCostTop:
    def test_top_text(self, tmp_path):
        _write_history(tmp_path, [_route_row(), _route_row(model="claude-3"), _route_row()])
        assert P.cmd_cost(_args(cost_cmd="top", top=2)) == 0

    def test_top_json(self, tmp_path, capsys):
        _write_history(tmp_path, [_route_row(), _route_row(model="claude-3")])
        assert P.cmd_cost(_args(cost_cmd="top", json=True)) == 0
        data = json.loads(capsys.readouterr().out)
        assert "openai/gpt-4" in data


class TestCmdCostJson:
    def test_raw_json(self, tmp_path, capsys):
        rows = [_route_row(), _usage_row()]
        _write_history(tmp_path, rows)
        assert P.cmd_cost(_args(cost_cmd="json")) == 0
        data = json.loads(capsys.readouterr().out)
        assert len(data) == 2


class TestCmdCostBudget:
    def test_no_budget(self, tmp_path):
        _write_history(tmp_path, [_route_row() for _ in range(5)])
        assert P.cmd_cost(_args(cost_cmd="budget")) == 0

    def test_budget_json(self, tmp_path, capsys, monkeypatch):
        import tuan_cli.config.loader as L
        router_dict = {"budget_limit": 10.0}
        monkeypatch.setattr(L, "Config", lambda **k: SimpleNamespace(
            get=lambda key, default=None: router_dict if key == "router" else default))
        _write_history(tmp_path, [_route_row() for _ in range(100)])
        assert P.cmd_cost(_args(cost_cmd="budget", json=True)) == 0
        data = json.loads(capsys.readouterr().out)
        assert data["budget_limit_usd"] == 10.0
        assert data["total_decisions"] == 100
        assert "forecast" in data
        assert "over_budget" in data

    def test_budget_over(self, tmp_path, monkeypatch):
        import tuan_cli.config.loader as L
        router_dict = {"budget_limit": 0.5}
        monkeypatch.setattr(L, "Config", lambda **k: SimpleNamespace(
            get=lambda key, default=None: router_dict if key == "router" else default))
        _write_history(tmp_path, [_route_row() for _ in range(100)])
        assert P.cmd_cost(_args(cost_cmd="budget")) == 0

    def test_budget_no_config(self, tmp_path, monkeypatch):
        import tuan_cli.config.loader as L
        monkeypatch.setattr(L, "Config", lambda **k: SimpleNamespace(
            get=lambda key, default=None: default))
        _write_history(tmp_path, [_route_row()])
        assert P.cmd_cost(_args(cost_cmd="budget")) == 0


class TestCmdCostTrend:
    def test_trend_text_empty(self, tmp_path):
        _write_history(tmp_path, [_route_row(ts="2020-01-01T00:00:00")])
        assert P.cmd_cost(_args(cost_cmd="trend", days=3)) == 0

    def test_trend_text_with_data(self, tmp_path):
        from datetime import datetime, timedelta
        today = datetime.now()
        rows = [_route_row(ts=(today - timedelta(days=i)).strftime("%Y-%m-%dT%H:%M:%S"))
                for i in range(3)]
        _write_history(tmp_path, rows)
        assert P.cmd_cost(_args(cost_cmd="trend", days=7)) == 0

    def test_trend_json(self, tmp_path, capsys):
        from datetime import datetime
        today = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        _write_history(tmp_path, [_route_row(ts=today), _usage_row(ts=today)])
        assert P.cmd_cost(_args(cost_cmd="trend", days=7, json=True)) == 0
        data = json.loads(capsys.readouterr().out)
        assert data["window_days"] == 7
        assert len(data["by_day"]) == 7
        assert data["max_decisions"] >= 1


class TestCmdCostEfficiency:
    def test_no_usage(self, tmp_path):
        _write_history(tmp_path, [_route_row()])
        assert P.cmd_cost(_args(cost_cmd="efficiency")) == 0

    def test_no_usage_json(self, tmp_path, capsys):
        _write_history(tmp_path, [_route_row()])
        assert P.cmd_cost(_args(cost_cmd="efficiency", json=True)) == 0
        data = json.loads(capsys.readouterr().out)
        assert data["usage_records"] == 0

    def test_efficiency_with_usage(self, tmp_path):
        _write_history(tmp_path, [
            _usage_row(provider="openai", model="gpt-4", total_tokens=1000, est_cost_usd=0.01),
            _usage_row(provider="deepseek", model="deepseek-v3", total_tokens=2000, est_cost_usd=0.002),
            _usage_row(provider="openai", model="gpt-4", total_tokens=500, est_cost_usd=0.005),
        ])
        assert P.cmd_cost(_args(cost_cmd="efficiency")) == 0

    def test_efficiency_json(self, tmp_path, capsys):
        _write_history(tmp_path, [
            _usage_row(provider="openai", model="gpt-4", total_tokens=1000, est_cost_usd=0.01),
        ])
        assert P.cmd_cost(_args(cost_cmd="efficiency", json=True)) == 0
        data = json.loads(capsys.readouterr().out)
        assert data["usage_records"] == 1
        row = data["rows"][0]
        assert row["key"] == "openai/gpt-4"
        assert row["total_tokens"] == 1000
        assert row["cost_per_1k"] is not None


class TestCmdCostUnknown:
    def test_unknown_defaults_to_report(self, tmp_path):
        _write_history(tmp_path, [_route_row()])
        assert P.cmd_cost(_args(cost_cmd="bogus")) == 0
