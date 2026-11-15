"""cmd_cron 单元测试 —— 定时任务管理 CLI。"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tuan_cli.cli import cmd_cron as P


# ============================================================ helpers


def _args(**kw) -> SimpleNamespace:
    base = dict(cron_cmd=None, id=None, name=None, prompt=None,
                interval=None, cron=None, output=None, check=60,
                detach=False, profile="default", patch=None)
    base.update(kw)
    return SimpleNamespace(**base)


def _fake_store(monkeypatch, tmp_path: Path, **overrides) -> SimpleNamespace:
    jobs: list = overrides.get("jobs", [])
    store = SimpleNamespace(
        add=lambda name, prompt, interval, schedule=None: dict(
            id="j1", name=name, prompt=prompt, interval_minutes=interval,
            schedule=schedule, enabled=True, last_run=None, output=None),
        list=lambda: jobs,
        get=lambda jid: next((j for j in jobs if j["id"] == jid), None),
        remove=lambda jid: next((j for j in jobs if j["id"] == jid), None) is not None,
        set_enabled=lambda jid, enabled: (lambda j: (j.update(enabled=enabled) or True) if j else False)(
            next((j for j in jobs if j["id"] == jid), None)),
        update=lambda jid, **fields: next(
            (j.update(**fields) for j in jobs if j["id"] == jid), None),
        due=lambda: [j for j in jobs if j.get("enabled")],
    )
    monkeypatch.setattr(P, "CronStore", lambda home: store)
    return store


@pytest.fixture(autouse=True)
def _patch_console(monkeypatch):
    monkeypatch.setattr(P.console, "print", lambda *a, **k: None)


@pytest.fixture
def _patch_cfg(monkeypatch, tmp_path):
    import tuan_cli.config.loader as L
    cfg = SimpleNamespace(home=tmp_path)
    monkeypatch.setattr(P, "Config", lambda **k: cfg)
    return cfg


# ============================================================ unknown


class TestCronUnknown:
    def test_unknown_returns_1(self, monkeypatch, tmp_path):
        _fake_store(monkeypatch, tmp_path)
        import tuan_cli.config.loader as L
        monkeypatch.setattr(P, "Config", lambda **k: SimpleNamespace(home=tmp_path))
        assert P.cmd_cron(_args(cron_cmd="bogus")) == 1


# ============================================================ add


class TestCronAdd:
    def test_add_interval(self, monkeypatch, tmp_path):
        _fake_store(monkeypatch, tmp_path)
        import tuan_cli.config.loader as L
        monkeypatch.setattr(P, "Config", lambda **k: SimpleNamespace(home=tmp_path))
        assert P.cmd_cron(_args(cron_cmd="add", name="x", prompt="y",
                                interval=30)) == 0

    def test_add_cron(self, monkeypatch, tmp_path):
        _fake_store(monkeypatch, tmp_path)
        import tuan_cli.config.loader as L
        monkeypatch.setattr(P, "Config", lambda **k: SimpleNamespace(home=tmp_path))
        assert P.cmd_cron(_args(cron_cmd="add", name="x", prompt="y",
                                interval=None, cron="0 9 * * 1-5")) == 0

    def test_add_cron_invalid(self, monkeypatch, tmp_path):
        import tuan_cli.config.loader as L
        monkeypatch.setattr(P, "Config", lambda **k: SimpleNamespace(home=tmp_path))

        from tuan_cli.cron.schedule import CronParseError as _CPE

        class FakeStore:
            def __init__(self, home):
                pass
            def add(self, name, prompt, interval, schedule=None):
                raise _CPE("bad")
        monkeypatch.setattr(P, "CronStore", FakeStore)
        assert P.cmd_cron(_args(cron_cmd="add", name="x", prompt="y",
                                interval=None, cron="not-a-cron")) == 2

    def test_add_with_output(self, monkeypatch, tmp_path):
        import tuan_cli.config.loader as L
        monkeypatch.setattr(P, "Config", lambda **k: SimpleNamespace(home=tmp_path))
        _job = dict(id="j1", name="x", prompt="y", interval_minutes=30,
                    schedule=None, enabled=True, last_run=None, output=None)
        class S:
            def add(self, name, prompt, interval, schedule=None):
                return dict(_job)
            def update(self, jid, **fields):
                _job.update(**fields)
            def get(self, jid):
                return dict(_job)
        monkeypatch.setattr(P, "CronStore", lambda home: S())
        assert P.cmd_cron(_args(cron_cmd="add", name="x", prompt="y",
                                interval=30, output=str(tmp_path / "out.log"))) == 0


# ============================================================ list


class TestCronList:
    def test_list_empty(self, monkeypatch, tmp_path):
        _fake_store(monkeypatch, tmp_path, jobs=[])
        import tuan_cli.config.loader as L
        monkeypatch.setattr(P, "Config", lambda **k: SimpleNamespace(home=tmp_path))
        assert P.cmd_cron(_args(cron_cmd="list")) == 0

    def test_list_with_jobs(self, monkeypatch, tmp_path):
        jobs = [dict(id="j1", name="backup", enabled=True, last_run=None,
                     interval_minutes=30, schedule=None)]
        _fake_store(monkeypatch, tmp_path, jobs=jobs)
        import tuan_cli.config.loader as L
        monkeypatch.setattr(P, "Config", lambda **k: SimpleNamespace(home=tmp_path))
        assert P.cmd_cron(_args(cron_cmd="list")) == 0

    def test_list_with_schedule(self, monkeypatch, tmp_path):
        import time
        jobs = [dict(id="j1", name="job", enabled=True,
                     last_run=time.time(), interval_minutes=60,
                     schedule="0 9 * * 1-5")]
        _fake_store(monkeypatch, tmp_path, jobs=jobs)
        import tuan_cli.config.loader as L
        monkeypatch.setattr(P, "Config", lambda **k: SimpleNamespace(home=tmp_path))
        assert P.cmd_cron(_args(cron_cmd="list")) == 0


# ============================================================ remove


class TestCronRemove:
    def test_remove_ok(self, monkeypatch, tmp_path):
        jobs = [dict(id="j1", name="x", enabled=True)]
        _fake_store(monkeypatch, tmp_path, jobs=jobs)
        import tuan_cli.config.loader as L
        monkeypatch.setattr(P, "Config", lambda **k: SimpleNamespace(home=tmp_path))
        assert P.cmd_cron(_args(cron_cmd="remove", id="j1")) == 0

    def test_remove_missing(self, monkeypatch, tmp_path):
        _fake_store(monkeypatch, tmp_path, jobs=[])
        import tuan_cli.config.loader as L
        monkeypatch.setattr(P, "Config", lambda **k: SimpleNamespace(home=tmp_path))
        assert P.cmd_cron(_args(cron_cmd="remove", id="nope")) == 1


# ============================================================ enable/disable


class TestCronEnableDisable:
    def test_enable(self, monkeypatch, tmp_path):
        jobs = [dict(id="j1", name="x", enabled=False)]
        _fake_store(monkeypatch, tmp_path, jobs=jobs)
        import tuan_cli.config.loader as L
        monkeypatch.setattr(P, "Config", lambda **k: SimpleNamespace(home=tmp_path))
        assert P.cmd_cron(_args(cron_cmd="enable", id="j1")) == 0

    def test_disable(self, monkeypatch, tmp_path):
        jobs = [dict(id="j1", name="x", enabled=True)]
        _fake_store(monkeypatch, tmp_path, jobs=jobs)
        import tuan_cli.config.loader as L
        monkeypatch.setattr(P, "Config", lambda **k: SimpleNamespace(home=tmp_path))
        assert P.cmd_cron(_args(cron_cmd="disable", id="j1")) == 0

    def test_enable_missing(self, monkeypatch, tmp_path):
        _fake_store(monkeypatch, tmp_path, jobs=[])
        import tuan_cli.config.loader as L
        monkeypatch.setattr(P, "Config", lambda **k: SimpleNamespace(home=tmp_path))
        assert P.cmd_cron(_args(cron_cmd="enable", id="nope")) == 1


# ============================================================ edit


class TestCronEdit:
    def test_edit_not_found(self, monkeypatch, tmp_path):
        _fake_store(monkeypatch, tmp_path, jobs=[])
        import tuan_cli.config.loader as L
        monkeypatch.setattr(P, "Config", lambda **k: SimpleNamespace(home=tmp_path))
        assert P.cmd_cron(_args(cron_cmd="edit", id="nope")) == 1

    def test_edit_no_fields(self, monkeypatch, tmp_path):
        jobs = [dict(id="j1", name="x", enabled=True)]
        _fake_store(monkeypatch, tmp_path, jobs=jobs)
        import tuan_cli.config.loader as L
        monkeypatch.setattr(P, "Config", lambda **k: SimpleNamespace(home=tmp_path))
        assert P.cmd_cron(_args(cron_cmd="edit", id="j1")) == 1

    def test_edit_interval(self, monkeypatch, tmp_path):
        jobs = [dict(id="j1", name="x", enabled=True, interval_minutes=30)]
        _fake_store(monkeypatch, tmp_path, jobs=jobs)
        import tuan_cli.config.loader as L
        monkeypatch.setattr(P, "Config", lambda **k: SimpleNamespace(home=tmp_path))
        assert P.cmd_cron(_args(cron_cmd="edit", id="j1", interval=60)) == 0

    def test_edit_prompt(self, monkeypatch, tmp_path):
        jobs = [dict(id="j1", name="x", enabled=True)]
        _fake_store(monkeypatch, tmp_path, jobs=jobs)
        import tuan_cli.config.loader as L
        monkeypatch.setattr(P, "Config", lambda **k: SimpleNamespace(home=tmp_path))
        assert P.cmd_cron(_args(cron_cmd="edit", id="j1", prompt="new")) == 0

    def test_edit_name(self, monkeypatch, tmp_path):
        jobs = [dict(id="j1", name="old", enabled=True)]
        _fake_store(monkeypatch, tmp_path, jobs=jobs)
        import tuan_cli.config.loader as L
        monkeypatch.setattr(P, "Config", lambda **k: SimpleNamespace(home=tmp_path))
        assert P.cmd_cron(_args(cron_cmd="edit", id="j1", name="new")) == 0

    def test_edit_cron_valid(self, monkeypatch, tmp_path):
        jobs = [dict(id="j1", name="x", enabled=True)]
        _fake_store(monkeypatch, tmp_path, jobs=jobs)
        import tuan_cli.config.loader as L
        monkeypatch.setattr(P, "Config", lambda **k: SimpleNamespace(home=tmp_path))
        assert P.cmd_cron(_args(cron_cmd="edit", id="j1", cron="0 9 * * 1-5")) == 0

    def test_edit_output(self, monkeypatch, tmp_path):
        jobs = [dict(id="j1", name="x", enabled=True)]
        _fake_store(monkeypatch, tmp_path, jobs=jobs)
        import tuan_cli.config.loader as L
        monkeypatch.setattr(P, "Config", lambda **k: SimpleNamespace(home=tmp_path))
        assert P.cmd_cron(_args(cron_cmd="edit", id="j1",
                                output=str(tmp_path / "log.txt"))) == 0


# ============================================================ status


class TestCronStatus:
    def test_status_no_daemon(self, monkeypatch, tmp_path):
        _fake_store(monkeypatch, tmp_path, jobs=[dict(id="j1", enabled=True)])
        import tuan_cli.config.loader as L
        monkeypatch.setattr(P, "Config", lambda **k: SimpleNamespace(home=tmp_path))
        monkeypatch.setattr(P, "_cron_daemon_alive", lambda cfg: False)
        assert P.cmd_cron(_args(cron_cmd="status")) == 0

    def test_status_daemon_alive(self, monkeypatch, tmp_path):
        _fake_store(monkeypatch, tmp_path, jobs=[])
        import tuan_cli.config.loader as L
        monkeypatch.setattr(P, "Config", lambda **k: SimpleNamespace(home=tmp_path))
        monkeypatch.setattr(P, "_cron_daemon_alive", lambda cfg: True)
        pid_file = tmp_path / "cron" / "daemon.pid"
        pid_file.parent.mkdir(parents=True, exist_ok=True)
        pid_file.write_text("12345", encoding="utf-8")
        assert P.cmd_cron(_args(cron_cmd="status")) == 0


# ============================================================ stop


class TestCronStop:
    def test_stop_no_pid_file(self, monkeypatch, tmp_path):
        import tuan_cli.config.loader as L
        monkeypatch.setattr(P, "Config", lambda **k: SimpleNamespace(home=tmp_path))
        assert P.cmd_cron(_args(cron_cmd="stop")) == 1

    def test_stop_with_pid(self, monkeypatch, tmp_path):
        import tuan_cli.config.loader as L
        monkeypatch.setattr(P, "Config", lambda **k: SimpleNamespace(home=tmp_path))
        pid_file = tmp_path / "cron" / "daemon.pid"
        pid_file.parent.mkdir(parents=True, exist_ok=True)
        pid_file.write_text("99999", encoding="utf-8")
        # taskkill will fail but we catch OSError
        assert P.cmd_cron(_args(cron_cmd="stop")) == 0
        assert not pid_file.exists()


# ============================================================ logs


class TestCronLogs:
    def test_logs_not_found(self, monkeypatch, tmp_path):
        _fake_store(monkeypatch, tmp_path, jobs=[])
        import tuan_cli.config.loader as L
        monkeypatch.setattr(P, "Config", lambda **k: SimpleNamespace(home=tmp_path))
        assert P.cmd_cron(_args(cron_cmd="logs", id="nope")) == 1

    def test_logs_no_sessions(self, monkeypatch, tmp_path):
        jobs = [dict(id="j1", name="x", enabled=True)]
        _fake_store(monkeypatch, tmp_path, jobs=jobs)
        import tuan_cli.config.loader as L
        monkeypatch.setattr(P, "Config", lambda **k: SimpleNamespace(home=tmp_path))
        assert P.cmd_cron(_args(cron_cmd="logs", id="j1")) == 0

    def test_logs_with_sessions(self, monkeypatch, tmp_path):
        jobs = [dict(id="j1", name="x", enabled=True)]
        _fake_store(monkeypatch, tmp_path, jobs=jobs)
        import tuan_cli.config.loader as L
        monkeypatch.setattr(P, "Config", lambda **k: SimpleNamespace(home=tmp_path))
        sess = tmp_path / "sessions"
        sess.mkdir()
        rec = dict(type="assistant", message=dict(content="hello"))
        (sess / "s1.jsonl").write_text(json.dumps(rec), encoding="utf-8")
        # inject job_id
        (sess / "s1.jsonl").write_text(
            json.dumps(dict(type="assistant", job_id="j1",
                            message=dict(content="hello"))), encoding="utf-8")
        assert P.cmd_cron(_args(cron_cmd="logs", id="j1")) == 0


# ============================================================ run/tick (kernel path)


class TestCronRunTick:
    def test_tick_kernel_fail(self, monkeypatch, tmp_path):
        import tuan_cli.config.loader as L
        monkeypatch.setattr(P, "Config", lambda **k: SimpleNamespace(home=tmp_path))
        monkeypatch.setattr(P, "build_kernel", lambda *a, **k: (_ for _ in ()).throw(
            RuntimeError("no kernel")))
        assert P.cmd_cron(_args(cron_cmd="tick")) == 1

    def test_run_kernel_fail(self, monkeypatch, tmp_path):
        import tuan_cli.config.loader as L
        monkeypatch.setattr(P, "Config", lambda **k: SimpleNamespace(home=tmp_path))
        monkeypatch.setattr(P, "build_kernel", lambda *a, **k: (_ for _ in ()).throw(
            RuntimeError("no kernel")))
        assert P.cmd_cron(_args(cron_cmd="run", id="j1")) == 1
