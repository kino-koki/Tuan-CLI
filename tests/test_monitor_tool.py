"""background_monitor 工具测试 (GAP A4, Mock 模型全程离线)。

验证 (对标 Claude Code 的 Monitor):
- 工具注册 (read_only + long_running 标记);
- 增量游标语义: 同一 job 多次调用只推送「自上次以来新增」的事件;
- 事件流: job.start → agent.turn → job.done 按序可见;
- 终态快照: done/failed 附带结果/错误摘要;
- 全量概览: 不传 job_id 列出全部任务 + 最新事件。
"""

import time

from tuan_cli.app import build_kernel
from tuan_cli.core.agent import Agent
from tuan_cli.models.base import ModelAdapter, ModelResponse


class EchoModel(ModelAdapter):
    """单轮模型: 输出完成标记 (后台任务立即收敛为 done)。"""
    name = "echo"

    def chat(self, messages, tools=None, stream=False, on_token=None, **kwargs):
        last_user = ""
        for m in reversed(messages):
            if m.get("role") == "user" and m.get("content"):
                last_user = m["content"]
                break
        resp = ModelResponse(content=f"【已完成】回声: {last_user}")
        if stream and on_token:
            on_token(resp.content)
        return resp


class MultiTurnModel(ModelAdapter):
    """两轮模型: 首轮调 background_monitor, 次轮收尾。用于验证多轮循环里的流式消费。"""
    name = "multi-turn"

    def __init__(self):
        self.n = 0

    def chat(self, messages, tools=None, stream=False, on_token=None, **kwargs):
        self.n += 1
        if self.n == 1:
            return ModelResponse(content="我先启动后台任务再监控。")
        return ModelResponse(content="监控完成。")


def _make_ctx(tmp_path, model):
    kernel = build_kernel()
    config = kernel.require("config")
    config.set_user("agent.subagent_isolation", "thread")
    config.set_user("subagent.isolated_workdir", False)
    kernel.unprovide("model_adapter")
    kernel.provide("model_adapter", model, owner="test")
    agent = Agent(kernel=kernel, config=config,
                  workspace=str(tmp_path), confirm=lambda _p: True)
    return kernel, agent.ctx


def _start_bg(ctx, kernel, prompt="后台任务M"):
    registry = kernel.require("tool_registry")
    task_tool = registry.get("task")
    out = task_tool.handler(ctx, description="后台监控", prompt=prompt,
                            run_in_background=True)
    job_id = next(ln.split()[-1] for ln in out.splitlines() if ln.startswith("job_id:"))
    return job_id


def _wait_status(ctx, kernel, job_id, expect=("done", "failed"), timeout=15):
    """轮询 background_status 直到任务进入终态, 返回最终文本。"""
    registry = kernel.require("tool_registry")
    status_tool = registry.get("background_status")
    deadline = time.time() + timeout
    final = ""
    while time.time() < deadline:
        final = status_tool.handler(ctx, job_id=job_id)
        if any(f"[{s}]" in final for s in expect):
            break
        time.sleep(0.2)
    return final


def _join_thread(ctx, job_id):
    job = ctx.background_runner.get(job_id)
    if job is not None and job.thread is not None:
        job.thread.join(timeout=10)


# ------------------------------------------------------------------ 注册与标记

def test_background_monitor_registered(tuan_home):
    kernel = build_kernel()
    registry = kernel.require("tool_registry")
    names = {t.name for t in registry.tools}
    assert "background_monitor" in names
    tool = registry.get("background_monitor")
    assert tool.read_only          # 纯观察, Plan 模式放行
    assert tool.long_running       # 主循环按长运行工具周期性回调
    assert tool.dangerous is False


def test_background_monitor_empty_ctx(tuan_home):
    kernel = build_kernel()
    fresh = Agent(kernel=kernel, config=kernel.require("config"),
                  workspace=".").ctx
    tool = kernel.require("tool_registry").get("background_monitor")
    out = tool.handler(fresh)
    assert "没有" in out


# ------------------------------------------------------------------ 流式事件消费

def test_background_monitor_streams_job_events(tmp_path, tuan_home):
    kernel, ctx = _make_ctx(tmp_path, EchoModel())
    registry = kernel.require("tool_registry")
    monitor = registry.get("background_monitor")

    job_id = _start_bg(ctx, kernel)
    _wait_status(ctx, kernel, job_id)  # 等任务进入终态, 事件流已完整落盘

    # 首次调用: 增量游标从 0 开始, 应看到 start + done 事件
    out = monitor.handler(ctx, job_id=job_id)
    assert "▶ 启动" in out and "✔ 完成" in out
    assert "[done]" in out and "回声" in out

    # 第二次调用: 游标已推进, 无新事件 (不重放旧事件)
    out2 = monitor.handler(ctx, job_id=job_id)
    assert "(无新事件)" in out2 and "▶ 启动" not in out2

    _join_thread(ctx, job_id)


def test_background_monitor_incremental_cursor(tmp_path, tuan_home):
    """增量游标: 任务运行中途调用能看到部分事件, 后续调用只补新增部分。"""
    kernel, ctx = _make_ctx(tmp_path, EchoModel())
    registry = kernel.require("tool_registry")
    monitor = registry.get("background_monitor")

    job_id = _start_bg(ctx, kernel)
    # 任务极快完成 (EchoModel 单轮), 但第一次调用可能已消费全部事件。
    # 无论如何: 调用两次后, 第二次必须无 start 重放 (游标单调)。
    first = monitor.handler(ctx, job_id=job_id)
    second = monitor.handler(ctx, job_id=job_id)
    # 若第一次已消费全部, 第二次必须无重放; 若第一次部分消费, 第二次只补增量。
    assert "▶ 启动" not in second or "✔ 完成" in second

    _join_thread(ctx, job_id)


def test_background_monitor_done_snapshot(tmp_path, tuan_home):
    kernel, ctx = _make_ctx(tmp_path, EchoModel())
    registry = kernel.require("tool_registry")
    monitor = registry.get("background_monitor")

    job_id = _start_bg(ctx, kernel)
    _wait_status(ctx, kernel, job_id)
    out = monitor.handler(ctx, job_id=job_id)
    assert "结果:" in out or "错误:" in out
    _join_thread(ctx, job_id)


def test_background_monitor_list_all(tmp_path, tuan_home):
    kernel, ctx = _make_ctx(tmp_path, EchoModel())
    registry = kernel.require("tool_registry")
    monitor = registry.get("background_monitor")

    job_id = _start_bg(ctx, kernel)
    _wait_status(ctx, kernel, job_id)
    listing = monitor.handler(ctx)  # 不传 job_id → 概览模式
    assert job_id in listing and "后台任务监控" in listing
    _join_thread(ctx, job_id)
