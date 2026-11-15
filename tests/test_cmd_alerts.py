"""``tuan alerts`` CLI 的单元测试 (cmd_alerts.py)。

持久化安全告警可观测性 (纯只读)。覆盖:
1. _get_logger: 显式 home / None 走 home_dir
2. _fmt_time: 正常 / 异常回落 "-"
3. _sev_color: 各级别映射
4. _filter_records: 按 severity / source / last_n
5. _record_dict: 字段标准化
6. list 子命令: 空记录 / 有记录 / JSON / 读取失败
7. stats 子命令: 空记录 / 有记录 / JSON
8. report 子命令: Markdown 报告 / 读取失败
9. 分发入口: 未知子命令 / 默认 list

通过 monkeypatch 打桩 _get_logger 返回 fake AlertLogger。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from tuan_cli.cli import cmd_alerts as P


def _args(**kw) -> SimpleNamespace:
    base = dict(alerts_cmd=None, home=None, json=False, severity=None,
                source=None, last=50)
    base.update(kw)
    return SimpleNamespace(**base)


class _FakeLogger:
    """假 AlertLogger: 返回预置记录列表。"""

    def __init__(self, records):
        self._records = records

    def read_recent(self, last_n=50):
        return self._records[:last_n]


def _rec(sev="high", title="告警", msg="消息", source="mcp", ts=1000.0,
         notified=False, details=None):
    return {"severity": sev, "title": title, "message": msg, "source": source,
            "timestamp": ts, "notified": notified, "details": details or {}}


def _patch_logger(monkeypatch, records) -> None:
    monkeypatch.setattr(P, "_get_logger", lambda home: _FakeLogger(records))


# ============================================================ _get_logger


class TestGetLogger:
    def test_explicit_home(self, monkeypatch) -> None:
        import tuan_cli.core.security_alert as SA

        captured = {}

        class _Fake:
            def __init__(self, home):
                captured["home"] = home

        monkeypatch.setattr(SA, "AlertLogger", _Fake)
        P._get_logger("/tmp/myhome")
        assert "myhome" in str(captured["home"])

    def test_default_home(self, monkeypatch) -> None:
        import tuan_cli.core.security_alert as SA
        import tuan_cli.config.loader as L

        monkeypatch.setattr(L, "home_dir", lambda: "/tmp/defhome")

        captured = {}

        class _Fake:
            def __init__(self, home):
                captured["home"] = home

        monkeypatch.setattr(SA, "AlertLogger", _Fake)
        P._get_logger(None)
        assert "defhome" in str(captured["home"])


# ============================================================ _fmt_time


class TestFmtTime:
    def test_valid_ts(self) -> None:
        s = P._fmt_time(0.0)
        assert s != "-"

    def test_invalid_ts(self) -> None:
        # None 走 localtime(None) 返回当前时间 (不抛), 非数字串才触发 ValueError -> "-"
        assert P._fmt_time("not-a-number") == "-"
        assert P._fmt_time(None) != "-"  # None 被当 "now"


# ============================================================ _sev_color


class TestSevColor:
    def test_known_severities(self) -> None:
        assert P._sev_color("critical") == "red"
        assert P._sev_color("high") == "red"
        assert P._sev_color("medium") == "yellow"

    def test_unknown_defaults_to_dim(self) -> None:
        assert P._sev_color("low") == "dim"
        assert P._sev_color("bogus") == "dim"


# ============================================================ _filter_records


class TestFilterRecords:
    def test_by_severity(self) -> None:
        records = [_rec(sev="high"), _rec(sev="low"), _rec(sev="high")]
        out = P._filter_records(records, "high", None, 100)
        assert len(out) == 2

    def test_by_source(self) -> None:
        records = [_rec(source="mcp"), _rec(source="fs"), _rec(source="mcp")]
        out = P._filter_records(records, None, "mcp", 100)
        assert len(out) == 2

    def test_last_n_truncates(self) -> None:
        records = [_rec(title=f"r{i}") for i in range(100)]
        out = P._filter_records(records, None, None, 10)
        assert len(out) == 10
        # 最后 10 条
        assert out[-1]["title"] == "r99"


# ============================================================ _record_dict


class TestRecordDict:
    def test_normalizes_fields(self) -> None:
        d = P._record_dict(_rec())
        assert d["severity"] == "high"
        assert d["title"] == "告警"
        assert d["source"] == "mcp"
        assert isinstance(d["notified"], bool)
        assert "time" in d

    def test_missing_fields_default(self) -> None:
        d = P._record_dict({})
        assert d["severity"] == "low"
        assert d["title"] == ""
        assert d["message"] == ""
        assert d["source"] == ""
        assert d["timestamp"] == 0.0
        assert d["notified"] is False


# ============================================================ list 子命令


class TestList:
    def test_empty(self, monkeypatch) -> None:
        _patch_logger(monkeypatch, [])
        monkeypatch.setattr(P.console, "print", lambda *a, **k: None)
        rc = P._cmd_alerts_list(_args())
        assert rc == 0

    def test_with_records(self, monkeypatch) -> None:
        _patch_logger(monkeypatch, [_rec(), _rec(sev="critical")])
        monkeypatch.setattr(P.console, "print", lambda *a, **k: None)
        rc = P._cmd_alerts_list(_args())
        assert rc == 0

    def test_json_output(self, monkeypatch, capsys) -> None:
        _patch_logger(monkeypatch, [_rec(sev="high"), _rec(sev="low")])
        rc = P._cmd_alerts_list(_args(json=True))
        import json
        data = json.loads(capsys.readouterr().out)
        assert rc == 0
        assert len(data) == 2
        assert data[0]["severity"] == "high"

    def test_read_failure(self, monkeypatch, capsys) -> None:
        def boom(home):
            raise RuntimeError("disk error")

        monkeypatch.setattr(P, "_get_logger", boom)
        monkeypatch.setattr(P.console, "print", lambda *a, **k: None)
        rc = P._cmd_alerts_list(_args())
        assert rc == 1


# ============================================================ stats 子命令


class TestStats:
    def test_empty(self, monkeypatch, capsys) -> None:
        _patch_logger(monkeypatch, [])
        rc = P._cmd_alerts_stats(_args(alerts_cmd="stats"))
        out = capsys.readouterr().out
        assert rc == 0
        assert "总告警数: 0" in out

    def test_by_severity(self, monkeypatch, capsys) -> None:
        _patch_logger(monkeypatch, [
            _rec(sev="high"), _rec(sev="high"), _rec(sev="low"),
        ])
        rc = P._cmd_alerts_stats(_args(alerts_cmd="stats"))
        out = capsys.readouterr().out
        assert rc == 0
        assert "总告警数: 3" in out
        assert "high" in out

    def test_json_output(self, monkeypatch, capsys) -> None:
        _patch_logger(monkeypatch, [
            _rec(sev="critical", source="mcp"), _rec(sev="high", source="fs"),
        ])
        rc = P._cmd_alerts_stats(_args(alerts_cmd="stats", json=True))
        import json
        data = json.loads(capsys.readouterr().out)
        assert rc == 0
        assert data["total"] == 2
        assert data["by_severity"]["critical"] == 1
        assert data["by_source"]["mcp"] == 1

    def test_read_failure(self, monkeypatch, capsys) -> None:
        monkeypatch.setattr(P, "_get_logger",
                            lambda home: (_ for _ in ()).throw(RuntimeError("x")))
        monkeypatch.setattr(P.console, "print", lambda *a, **k: None)
        rc = P._cmd_alerts_stats(_args(alerts_cmd="stats"))
        assert rc == 1


# ============================================================ report 子命令


class TestReport:
    def test_markdown_header(self, monkeypatch, capsys) -> None:
        _patch_logger(monkeypatch, [_rec(title="告警1")])
        rc = P._cmd_alerts_report(_args(alerts_cmd="report"))
        out = capsys.readouterr().out
        assert rc == 0
        assert "# 安全告警报告" in out
        assert "总告警数: 1" in out
        assert "告警1" in out

    def test_empty_report(self, monkeypatch, capsys) -> None:
        _patch_logger(monkeypatch, [])
        rc = P._cmd_alerts_report(_args(alerts_cmd="report"))
        out = capsys.readouterr().out
        assert rc == 0
        assert "总告警数: 0" in out

    def test_read_failure(self, monkeypatch, capsys) -> None:
        monkeypatch.setattr(P, "_get_logger",
                            lambda home: (_ for _ in ()).throw(RuntimeError("x")))
        monkeypatch.setattr(P.console, "print", lambda *a, **k: None)
        rc = P._cmd_alerts_report(_args(alerts_cmd="report"))
        assert rc == 1


# ============================================================ 分发入口


class TestDispatcher:
    def test_default_list(self, monkeypatch) -> None:
        _patch_logger(monkeypatch, [])
        monkeypatch.setattr(P.console, "print", lambda *a, **k: None)
        rc = P.cmd_alerts(_args())
        assert rc == 0

    def test_list_subcommand(self, monkeypatch) -> None:
        _patch_logger(monkeypatch, [])
        monkeypatch.setattr(P.console, "print", lambda *a, **k: None)
        rc = P.cmd_alerts(_args(alerts_cmd="list"))
        assert rc == 0

    def test_stats_subcommand(self, monkeypatch, capsys) -> None:
        _patch_logger(monkeypatch, [])
        rc = P.cmd_alerts(_args(alerts_cmd="stats"))
        assert rc == 0

    def test_report_subcommand(self, monkeypatch, capsys) -> None:
        _patch_logger(monkeypatch, [])
        rc = P.cmd_alerts(_args(alerts_cmd="report"))
        assert rc == 0

    def test_unknown_subcommand(self, monkeypatch, capsys) -> None:
        rc = P.cmd_alerts(_args(alerts_cmd="bogus"))
        out = capsys.readouterr().out
        assert rc == 1
        assert "未知子命令" in out
