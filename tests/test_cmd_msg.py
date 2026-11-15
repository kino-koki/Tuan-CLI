"""``tuan msg`` CLI 的单元测试 (cmd_msg.py)。

跨会话消息总线可观测性 + 归档巡查。覆盖:
1. _get_bus: 构造 MessageBus(带 home)
2. cmd_msg agents: 空清单 / 有清单 / JSON
3. cmd_msg inbox: 缺 sid / 空 / 有消息 / keep / JSON
4. cmd_msg send: 缺字段 / 成功 / 失败 / JSON
5. cmd_msg cleanup: 正常 / JSON
6. 未知子命令
7. _cmd_msg_archive: 未初始化 / 有归档 / JSON
8. _fmt_ts: 正常 / 异常

通过 monkeypatch 打桩 _get_bus 返回 fake MessageBus。
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from tuan_cli.cli import cmd_msg as P


def _args(**kw) -> SimpleNamespace:
    base = dict(msg_cmd=None, json=False, session=None, keep=False,
                from_sid=None, to_sid=None, content=None, limit=0)
    base.update(kw)
    return SimpleNamespace(**base)


class _FakeBus:
    def __init__(self, agents=None, inbox=None, sent_id="m1", cleaned=2):
        self._agents = agents or []
        self._inbox = inbox or []
        self._sent_id = sent_id
        self._cleaned = cleaned

    def list_agents(self):
        return self._agents

    def receive(self, sid, mark_read=True):
        return self._inbox

    def send(self, from_sid, to_sid, content):
        return self._sent_id

    def cleanup(self):
        return self._cleaned


class _FakeMsg:
    def __init__(self, id="m1", from_session="s1", content="hello", ts=1000.0,
                 read=False):
        self.id = id
        self.from_session = from_session
        self.content = content
        self.ts = ts
        self.read = read


def _patch_bus(monkeypatch, **kw) -> None:
    monkeypatch.setattr(P, "_get_bus", lambda: _FakeBus(**kw))


# ============================================================ _get_bus


class TestGetBus:
    def test_construction(self, monkeypatch, tmp_path) -> None:
        import tuan_cli.config.loader as L
        monkeypatch.setattr(L, "home_dir", lambda: tmp_path)  # Path 对象
        rc = P._get_bus()
        assert rc is not None


# ============================================================ agents 子命令


class TestAgents:
    def test_empty(self, monkeypatch, capsys) -> None:
        _patch_bus(monkeypatch, agents=[])
        monkeypatch.setattr(P.console, "print", lambda *a, **k: None)
        rc = P.cmd_msg(_args(msg_cmd="agents"))
        assert rc == 0

    def test_with_agents(self, monkeypatch) -> None:
        _patch_bus(monkeypatch, agents=[
            {"session_id": "sess1234", "pid": 4321, "uptime": 90,
             "meta": {"model": "gpt-4", "workspace": "/tmp/x"}},
        ])
        printed = []
        monkeypatch.setattr(P.console, "print",
                            lambda msg, *a, **k: printed.append(str(msg)))
        rc = P.cmd_msg(_args(msg_cmd="agents"))
        assert rc == 0
        text = "\n".join(printed)
        assert "活跃会话" in text
        assert "gpt-4" in text

    def test_json_output(self, monkeypatch, capsys) -> None:
        _patch_bus(monkeypatch, agents=[
            {"session_id": "s1", "pid": 1, "uptime": 60, "meta": {}},
        ])
        monkeypatch.setattr(P.console, "print", lambda *a, **k: None)
        rc = P.cmd_msg(_args(msg_cmd="agents", json=True))
        data = json.loads(capsys.readouterr().out)
        assert rc == 0
        assert data["count"] == 1


# ============================================================ inbox 子命令


class TestInbox:
    def test_missing_sid(self, monkeypatch) -> None:
        _patch_bus(monkeypatch)
        printed = []
        monkeypatch.setattr(P.console, "print",
                            lambda msg, *a, **k: printed.append(str(msg)))
        rc = P.cmd_msg(_args(msg_cmd="inbox", session=""))
        assert rc == 1
        assert any("缺少会话 ID" in p for p in printed)

    def test_empty(self, monkeypatch) -> None:
        _patch_bus(monkeypatch, inbox=[])
        monkeypatch.setattr(P.console, "print", lambda *a, **k: None)
        rc = P.cmd_msg(_args(msg_cmd="inbox", session="s1"))
        assert rc == 0

    def test_with_messages(self, monkeypatch) -> None:
        _patch_bus(monkeypatch, inbox=[_FakeMsg(content="测试消息")])
        printed = []
        monkeypatch.setattr(P.console, "print",
                            lambda msg, *a, **k: printed.append(str(msg)))
        rc = P.cmd_msg(_args(msg_cmd="inbox", session="s1"))
        assert rc == 0
        text = "\n".join(printed)
        assert "未读" in text
        assert "测试消息" in text

    def test_keep_flag(self, monkeypatch) -> None:
        _patch_bus(monkeypatch, inbox=[_FakeMsg()])
        printed = []
        monkeypatch.setattr(P.console, "print",
                            lambda msg, *a, **k: printed.append(str(msg)))
        rc = P.cmd_msg(_args(msg_cmd="inbox", session="s1", keep=True))
        assert rc == 0

    def test_json_output(self, monkeypatch, capsys) -> None:
        _patch_bus(monkeypatch, inbox=[_FakeMsg(content="hello")])
        monkeypatch.setattr(P.console, "print", lambda *a, **k: None)
        rc = P.cmd_msg(_args(msg_cmd="inbox", session="s1", json=True))
        data = json.loads(capsys.readouterr().out)
        assert rc == 0
        assert data["count"] == 1
        assert data["messages"][0]["content"] == "hello"


# ============================================================ send 子命令


class TestSend:
    def test_missing_fields(self, monkeypatch) -> None:
        _patch_bus(monkeypatch)
        printed = []
        monkeypatch.setattr(P.console, "print",
                            lambda msg, *a, **k: printed.append(str(msg)))
        rc = P.cmd_msg(_args(msg_cmd="send", from_sid="", to_sid="t", content="x"))
        assert rc == 1
        assert any("用法" in p for p in printed)

    def test_success(self, monkeypatch) -> None:
        _patch_bus(monkeypatch, sent_id="m99")
        printed = []
        monkeypatch.setattr(P.console, "print",
                            lambda msg, *a, **k: printed.append(str(msg)))
        rc = P.cmd_msg(_args(msg_cmd="send", from_sid="a", to_sid="b", content="x"))
        assert rc == 0
        assert any("已发送" in p for p in printed)

    def test_failure(self, monkeypatch) -> None:
        _patch_bus(monkeypatch, sent_id=None)
        printed = []
        monkeypatch.setattr(P.console, "print",
                            lambda msg, *a, **k: printed.append(str(msg)))
        rc = P.cmd_msg(_args(msg_cmd="send", from_sid="a", to_sid="b", content="x"))
        assert rc == 0
        assert any("发送失败" in p for p in printed)

    def test_json_output(self, monkeypatch, capsys) -> None:
        _patch_bus(monkeypatch, sent_id="m5")
        monkeypatch.setattr(P.console, "print", lambda *a, **k: None)
        rc = P.cmd_msg(_args(msg_cmd="send", from_sid="a", to_sid="b",
                            content="x", json=True))
        data = json.loads(capsys.readouterr().out)
        assert rc == 0
        assert data["sent"] is True
        assert data["id"] == "m5"


# ============================================================ cleanup 子命令


class TestCleanup:
    def test_normal(self, monkeypatch) -> None:
        _patch_bus(monkeypatch, cleaned=3)
        printed = []
        monkeypatch.setattr(P.console, "print",
                            lambda msg, *a, **k: printed.append(str(msg)))
        rc = P.cmd_msg(_args(msg_cmd="cleanup"))
        assert rc == 0
        assert any("已清理 3" in p for p in printed)

    def test_json_output(self, monkeypatch, capsys) -> None:
        _patch_bus(monkeypatch, cleaned=5)
        monkeypatch.setattr(P.console, "print", lambda *a, **k: None)
        rc = P.cmd_msg(_args(msg_cmd="cleanup", json=True))
        data = json.loads(capsys.readouterr().out)
        assert rc == 0
        assert data["cleaned_sessions"] == 5


# ============================================================ 未知子命令


class TestUnknown:
    def test_unknown(self, monkeypatch) -> None:
        _patch_bus(monkeypatch)
        printed = []
        monkeypatch.setattr(P.console, "print",
                            lambda msg, *a, **k: printed.append(str(msg)))
        rc = P.cmd_msg(_args(msg_cmd="bogus"))
        assert rc == 1
        assert any("未知" in p for p in printed)


# ============================================================ archive 子命令


class TestArchive:
    def test_uninitialized(self, monkeypatch, tmp_path, capsys) -> None:
        monkeypatch.setattr(P, "_get_bus", lambda: None)
        import tuan_cli.config.loader as L
        monkeypatch.setattr(L, "home_dir", lambda: str(tmp_path))
        rc = P.cmd_msg(_args(msg_cmd="archive"))
        out = capsys.readouterr().out
        assert rc == 0
        assert "未初始化" in out

    def test_uninitialized_json(self, monkeypatch, tmp_path, capsys) -> None:
        monkeypatch.setattr(P, "_get_bus", lambda: None)
        import tuan_cli.config.loader as L
        monkeypatch.setattr(L, "home_dir", lambda: str(tmp_path))
        rc = P.cmd_msg(_args(msg_cmd="archive", json=True))
        data = json.loads(capsys.readouterr().out)
        assert rc == 0
        assert data["initialized"] is False

    def test_with_archive(self, monkeypatch, tmp_path, capsys) -> None:
        import tuan_cli.config.loader as L
        monkeypatch.setattr(L, "home_dir", lambda: str(tmp_path))
        archive = tmp_path / "messaging"
        archive.mkdir()
        (archive / "_registry.json").write_text(
            json.dumps({"sess1": {"name": "主会话", "working_dir": "/tmp/ws"}}),
            encoding="utf-8-sig")
        (archive / "sess1.jsonl").write_text(
            json.dumps({"id": "m1", "content": "hi", "read": False}, ensure_ascii=False) + "\n",
            encoding="utf-8-sig")
        rc = P.cmd_msg(_args(msg_cmd="archive", json=True))
        data = json.loads(capsys.readouterr().out)
        assert rc == 0
        assert data["initialized"] is True
        assert data["queue_count"] == 1
        assert data["queues"][0]["session_id"] == "sess1"
        assert data["queues"][0]["total"] == 1


# ============================================================ _fmt_ts


class TestFmtTs:
    def test_valid(self) -> None:
        s = P._fmt_ts(0.0)
        assert s != "-"

    def test_invalid(self) -> None:
        assert P._fmt_ts("not-a-number") == "-"
