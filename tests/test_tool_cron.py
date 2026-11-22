"""cron 工具真实接入回归测试。

此前 cron 只有 CLI 入口 (cmd_cron.py), Agent 工具面缺失。
本文件验证 `cron` 工具经 builtin_tool_plugins() 注册后, Agent 可以
真实管理 (add/list/remove/toggle/status) 与触发 (run_due) 定时任务,
且底层走的是真 CronStore / run_due_jobs 链路。
"""

from pathlib import Path

import pytest

from tuan_cli.app import build_kernel
from tuan_cli.core.agent import Agent


def _make_ctx(tmp_path):
    kernel = build_kernel()
    config = kernel.require("config")
    agent = Agent(kernel=kernel, config=config, workspace=str(tmp_path),
                  confirm=lambda _p: True)
    return kernel, agent


# ------------------------------------------------------------------ 注册

def test_cron_tool_registered(tuan_home):
    kernel = build_kernel()
    names = {t.name for t in kernel.require("tool_registry").tools}
    assert "cron" in names, "cron 工具未接入 Agent 工具面"


# ------------------------------------------------------------------ add/list

def test_cron_add_and_list_roundtrip(tmp_path, tuan_home):
    kernel, agent = _make_ctx(tmp_path)
    reg = kernel.require("tool_registry")
    cron = reg.get("cron").handler
    out = cron(agent.ctx, op="add", name="日报",
               prompt="汇总今日进展", schedule="0 9 * * 1-5")
    assert "已创建" in out
    listing = cron(agent.ctx, op="list")
    assert "日报" in listing and "0 9 * * 1-5" in listing
    # 落盘验证: 真实 CronStore 文件存在且含该任务
    jobs_file = Path(kernel.require("config").home) / "cron" / "jobs.json"
    assert jobs_file.exists()
    data = jobs_file.read_text(encoding="utf-8")
    assert "日报" in data and "汇总今日进展" in data


def test_cron_add_interval_and_missing_prompt(tmp_path, tuan_home):
    kernel, agent = _make_ctx(tmp_path)
    cron = kernel.require("tool_registry").get("cron").handler
    out = cron(agent.ctx, op="add", name="巡检", prompt="检查服务",
               interval_minutes=30)
    assert "已创建" in out
    # 缺 prompt 拒绝
    out2 = cron(agent.ctx, op="add", name="坏任务")
    assert "prompt" in out2  # 缺 prompt 的明确提示


def test_cron_add_invalid_schedule_rejected(tmp_path, tuan_home):
    kernel, agent = _make_ctx(tmp_path)
    cron = kernel.require("tool_registry").get("cron").handler
    out = cron(agent.ctx, op="add", name="坏表达式",
               prompt="x", schedule="99 99 * * *")
    assert "新增失败" in out
    # 非法表达式不得落盘
    assert cron(agent.ctx, op="list").startswith("当前没有定时任务")


# ------------------------------------------------------------------ toggle/remove

def test_cron_toggle_and_remove(tmp_path, tuan_home):
    kernel, agent = _make_ctx(tmp_path)
    reg = kernel.require("tool_registry")
    cron = reg.get("cron").handler
    cron(agent.ctx, op="add", name="任务A", prompt="p", interval_minutes=10)
    job_id = reg.get("cron_store").list()[0]["id"] if reg.get("cron_store") else None
    if job_id is None:
        # kernel 未提供 cron_store 服务时, 直接从 jobs.json 读 id
        jobs_file = Path(kernel.require("config").home) / "cron" / "jobs.json"
        job_id = __import__("json").loads(jobs_file.read_text(encoding="utf-8"))[0]["id"]

    out = cron(agent.ctx, op="toggle", job_id=job_id, enabled=False)
    assert "停用" in out
    out2 = cron(agent.ctx, op="toggle", job_id=job_id)
    assert "启用" in out2  # 缺省取反
    out3 = cron(agent.ctx, op="remove", job_id=job_id)
    assert "已删除" in out3
    assert cron(agent.ctx, op="remove", job_id=job_id).startswith("[cron] 未找到")
    assert cron(agent.ctx, op="toggle", job_id=job_id).startswith("[cron] 未找到")


# ------------------------------------------------------------------ run_due/status

def test_cron_run_due_empty_and_status(tmp_path, tuan_home):
    kernel, agent = _make_ctx(tmp_path)
    cron = kernel.require("tool_registry").get("cron").handler
    out = cron(agent.ctx, op="run_due")
    assert "没有到期" in out
    status = cron(agent.ctx, op="status")
    assert "共 0 个" in status and "jobs.json" in status
    # 未知 op
    assert "未知 op" in cron(agent.ctx, op="nope")
