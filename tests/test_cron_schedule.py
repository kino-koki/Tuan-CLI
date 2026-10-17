"""Cron 表达式排期测试 —— schedule 解析/匹配 + store cron 到期判定 + CLI --cron。

设计要点:
- 全部在 tmp_path 临时 home 下操作, 不触碰真实用户目录;
- 不启动常驻 daemon (cron daemon 类测试不真起进程), 只测 store/runner/CLI 离线路径;
- cron 排期的"到期"用可控时间点断言, 不依赖墙钟真实流逝。
"""
from __future__ import annotations

import datetime as dt

import pytest

from tuan_cli.cron.schedule import (
    CronParseError,
    is_valid,
    parse,
)


# ------------------------------------------------------------ 解析与校验

def test_parse_valid_common_expressions():
    for expr in ["0 9 * * 1-5", "*/15 * * * *", "30 8 1 * *",
                 "0 0 1,15 * *", "0 12 * * 0", "0 9 * * 1-5"]:
        assert is_valid(expr), f"应合法: {expr}"


def test_parse_wrong_field_count_rejected():
    with pytest.raises(CronParseError):
        parse("0 9 * *")          # 4 段
    with pytest.raises(CronParseError):
        parse("0 9 * * 1 5")      # 6 段
    assert is_valid("") is False


def test_parse_out_of_range_rejected():
    with pytest.raises(CronParseError):
        parse("60 * * * *")       # 分越界
    with pytest.raises(CronParseError):
        parse("* 25 * * *")       # 时越界
    with pytest.raises(CronParseError):
        parse("0 9 32 * *")       # 日越界
    with pytest.raises(CronParseError):
        parse("0 9 * 13 *")       # 月越界
    with pytest.raises(CronParseError):
        parse("0 9 * * 8")        # 周越界 (7 归一化为 0, 但 8 非法)


def test_parse_bad_step_rejected():
    with pytest.raises(CronParseError):
        parse("*/0 * * * *")      # 步长为 0
    with pytest.raises(CronParseError):
        parse("*/abc * * * *")    # 步长非数字


def test_dow_7_normalized_to_sunday():
    # 7 应等价于周日 (0)
    s = parse("0 9 * * 7")
    # 2026-10-04 是周日
    assert s.matches(dt.datetime(2026, 10, 4, 9, 0)) is True
    assert s.matches(dt.datetime(2026, 10, 5, 9, 0)) is False  # 周一


# ------------------------------------------------------------ 匹配语义

def test_workday_nine_oclock():
    s = parse("0 9 * * 1-5")
    # 2026-10-06 周二 09:00 命中
    assert s.matches(dt.datetime(2026, 10, 6, 9, 0)) is True
    # 同一分钟但 09:30 不命中 (分字段=0)
    assert s.matches(dt.datetime(2026, 10, 6, 9, 30)) is False
    # 2026-10-10 周六 09:00 不命中
    assert s.matches(dt.datetime(2026, 10, 10, 9, 0)) is False
    # 2026-10-11 周日 09:00 不命中
    assert s.matches(dt.datetime(2026, 10, 11, 9, 0)) is False


def test_step_every_15_minutes():
    s = parse("*/15 * * * *")
    assert s.matches(dt.datetime(2026, 10, 6, 9, 0)) is True
    assert s.matches(dt.datetime(2026, 10, 6, 9, 15)) is True
    assert s.matches(dt.datetime(2026, 10, 6, 9, 30)) is True
    assert s.matches(dt.datetime(2026, 10, 6, 9, 7)) is False


def test_day_of_month_list():
    s = parse("0 0 1,15 * *")
    assert s.matches(dt.datetime(2026, 10, 1, 0, 0)) is True
    assert s.matches(dt.datetime(2026, 10, 15, 0, 0)) is True
    assert s.matches(dt.datetime(2026, 10, 16, 0, 0)) is False


def test_dom_dow_or_semantics():
    # 标准 cron: dom 与 dow 都被限定(非 *)时取 OR。
    # 每月 1 号 或 周一 命中。
    s = parse("0 9 1 * 1")
    # 2026-10-05 是周一 (非 1 号) -> dow 命中
    assert s.matches(dt.datetime(2026, 10, 5, 9, 0)) is True
    # 2026-10-01 是周四 (1 号) -> dom 命中
    assert s.matches(dt.datetime(2026, 10, 1, 9, 0)) is True
    # 2026-10-06 周二, 非 1 号 -> 都不命中
    assert s.matches(dt.datetime(2026, 10, 6, 9, 0)) is False


def test_last_fire_recent_minute():
    s = parse("0 9 * * 1-5")
    # 2026-10-06 (周二) 10:00 之前最近一次命中是当天 09:00
    fired = s.last_fire(dt.datetime(2026, 10, 6, 10, 0))
    assert fired == dt.datetime(2026, 10, 6, 9, 0)


# ------------------------------------------------------------ store 集成 (cron 到期判定)

from tuan_cli.cron.store import CronStore  # noqa: E402


def test_store_add_with_schedule_persists(tmp_path):
    store = CronStore(tmp_path)
    job = store.add("工作日日报", "写日报", interval_minutes=60, schedule="0 9 * * 1-5")
    assert job["schedule"] == "0 9 * * 1-5"
    # 持久化: 新实例读同一文件仍在 (模拟进程重启)
    store2 = CronStore(tmp_path)
    jobs = store2.list()
    assert len(jobs) == 1
    assert jobs[0]["schedule"] == "0 9 * * 1-5"


def test_store_rejects_bad_schedule(tmp_path):
    store = CronStore(tmp_path)
    with pytest.raises(CronParseError):
        store.add("坏任务", "x", interval_minutes=60, schedule="99 * * * *")
    # 坏数据不应写盘
    assert store.list() == []


def test_store_due_uses_cron_when_schedule_present(tmp_path):
    """cron 任务的到期由"最近命中分钟 > last_run"决定, 与固定间隔无关。"""
    store = CronStore(tmp_path)
    # 一个 09:00 触发的任务, interval 给 60 但 schedule 优先
    job = store.add("日报", "写日报", interval_minutes=60, schedule="0 9 * * 1-5")

    # 把 last_run 拨到昨天 (2026-10-05) 09:00, "现在"是 2026-10-06 10:00
    # 今天 09:00 的命中 > last_run -> 应到期
    import time as _t
    last_run = dt.datetime(2026, 10, 5, 9, 0).timestamp()
    jobs = store._read()
    for j in jobs:
        if j["id"] == job["id"]:
            j["last_run"] = last_run
    store._write(jobs)

    # 用 monkeypatch 固定 time.time 到 2026-10-06 10:00
    import tuan_cli.cron.store as store_mod
    real_time = store_mod.time.time
    store_mod.time.time = lambda: dt.datetime(2026, 10, 6, 10, 0).timestamp()
    try:
        due = store.due()
        assert any(j["id"] == job["id"] for j in due), "cron 任务在今天 09:00 命中后应到期"
    finally:
        store_mod.time.time = real_time


def test_store_cron_not_due_when_already_run(tmp_path):
    """last_run 已是今天 09:00 -> 今天不再到期。"""
    store = CronStore(tmp_path)
    job = store.add("日报", "写日报", interval_minutes=60, schedule="0 9 * * 1-5")
    import tuan_cli.cron.store as store_mod
    last_run = dt.datetime(2026, 10, 6, 9, 0).timestamp()
    jobs = store._read()
    for j in jobs:
        if j["id"] == job["id"]:
            j["last_run"] = last_run
    store._write(jobs)
    real_time = store_mod.time.time
    store_mod.time.time = lambda: dt.datetime(2026, 10, 6, 10, 0).timestamp()
    try:
        due = store.due()
        assert all(j["id"] != job["id"] for j in due), "今天 09:00 已跑过, 不应再到期"
    finally:
        store_mod.time.time = real_time


def test_store_malformed_schedule_skipped_not_crash(tmp_path):
    """jobs.json 里手工塞一条非法 cron 表达式, due() 应跳过而非崩溃。"""
    store = CronStore(tmp_path)
    good = store.add("正常", "p", interval_minutes=60)
    malformed = [
        {"id": good["id"], "name": "正常", "prompt": "p",
         "interval_minutes": 60, "last_run": 0, "enabled": True},
        {"id": "bad-cron", "name": "坏cron", "prompt": "p",
         "interval_minutes": 60, "last_run": 0, "enabled": True,
         "schedule": "99 malformed !!!"},
    ]
    store._write(malformed)
    due = store.due()  # 不应抛
    ids = [j["id"] for j in due]
    assert good["id"] in ids
    assert "bad-cron" not in ids


# ------------------------------------------------------------ CLI --cron

from tuan_cli.cli.commands import cmd_cron  # noqa: E402
from tuan_cli.cli.parser import build_parser  # noqa: E402


def _run_cron(tmp_path, argv, monkeypatch):
    parser = build_parser()
    args = parser.parse_args(["cron"] + argv)
    monkeypatch.setenv("TUAN_HOME", str(tmp_path))
    return cmd_cron(args)


def test_cmd_cron_add_with_cron(tmp_path, monkeypatch):
    rc = _run_cron(tmp_path, ["add", "工作日日报", "写日报", "--cron", "0 9 * * 1-5"], monkeypatch)
    assert rc == 0
    store = CronStore(tmp_path)
    jobs = store.list()
    assert len(jobs) == 1
    assert jobs[0]["schedule"] == "0 9 * * 1-5"


def test_cmd_cron_add_bad_cron_returns_error(tmp_path, monkeypatch):
    rc = _run_cron(tmp_path, ["add", "坏", "p", "--cron", "99 * * * *"], monkeypatch)
    assert rc != 0
    store = CronStore(tmp_path)
    assert store.list() == []


def test_cmd_cron_list_shows_cron(tmp_path, monkeypatch, capsys):
    _run_cron(tmp_path, ["add", "日报", "p", "--cron", "30 8 * * 1-5"], monkeypatch)
    rc = _run_cron(tmp_path, ["list"], monkeypatch)
    assert rc == 0
    captured = capsys.readouterr()
    assert "30 8 * * 1-5" in captured.out


def test_cmd_cron_edit_to_cron(tmp_path, monkeypatch):
    _run_cron(tmp_path, ["add", "任务A", "p", "--interval", "30"], monkeypatch)
    store = CronStore(tmp_path)
    jid = store.list()[0]["id"]
    rc = _run_cron(tmp_path, ["edit", jid, "--cron", "0 18 * * 1-5"], monkeypatch)
    assert rc == 0
    job = store.get(jid)
    assert job["schedule"] == "0 18 * * 1-5"


def test_cmd_cron_edit_bad_cron(tmp_path, monkeypatch):
    _run_cron(tmp_path, ["add", "任务A", "p", "--interval", "30"], monkeypatch)
    store = CronStore(tmp_path)
    jid = store.list()[0]["id"]
    rc = _run_cron(tmp_path, ["edit", jid, "--cron", "bad expr"], monkeypatch)
    assert rc != 0
    # 原任务未被改坏
    assert store.get(jid).get("schedule") is None
