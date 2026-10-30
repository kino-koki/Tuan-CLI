"""Subagent 真并行执行 + 结构化结果回传 证明测试 (能力1)。

审计核实结论: subagents.py 具备完整链路 —— SubAgentPool 用 ThreadPoolExecutor
并发派出隔离子 Agent、各自独立 messages、结果经 SubResult.to_block/aggregate
带来源标注回传主 Agent。但既有 test_subagents_bg 的并发用例用的是无延迟
EchoModel, 并未从时序上证明"真并行" (串行/并行跑起来一样快)。

本测试用时序断言证明真并行:
- N 个各自 sleep 的子任务, 在 max_workers>=N 时, 整批墙钟时间远小于串行总和;
- 结果顺序与输入一致 (回传顺序确定);
- aggregate 把每个子结果带来源标注聚合成结构化报告 (供主 Agent 消费)。
"""

from __future__ import annotations

import time

from tuan_cli.app import build_kernel
from tuan_cli.core.agent import Agent
from tuan_cli.core.subagents import SubAgentPool, SubResult, SubTask
from tuan_cli.models.base import ModelAdapter, ModelResponse


class SlowEchoModel(ModelAdapter):
    """每个子 Agent 模型调用都 sleep `delay` 秒, 再回声 prompt。

    每个子任务会跑至少一轮模型调用, 故 N 个任务真并行时墙钟≈单任务延迟;
    串行时≈N×延迟。据此区分真并行与假并发。
    """

    name = "slow_echo"

    def __init__(self, delay: float = 0.4):
        self.delay = delay

    def chat(self, messages, tools=None, stream=False, on_token=None, **kwargs):
        time.sleep(self.delay)
        last = ""
        for m in reversed(messages):
            if m.get("role") == "user" and m.get("content"):
                last = m["content"]
                break
        return ModelResponse(content=f"回声[{last}]")


def _pool(tmp_path, tuan_home, model, max_workers: int):
    kernel = build_kernel()
    config = kernel.require("config")
    kernel.unprovide("model_adapter")
    kernel.provide("model_adapter", model, owner="test")
    return SubAgentPool(
        kernel=kernel, config=config, workspace=str(tmp_path),
        max_workers=max_workers, default_timeout=30.0, isolation="thread",
    )


def test_subagents_run_truly_in_parallel(tmp_path, tuan_home):
    """3 个各 sleep 1.2s 的子任务, max_workers=3 → 墙钟应明显 < 串行 3.6s。

    注: 子 Agent 构建是 CPU 密集段, 受 GIL 限制无法真并行 (约 0.6s/任务);
    但 sleep 段 (time.sleep 释放 GIL) 可真并行。故用较大 delay 让睡眠主导,
    并行墙钟 ≈ 构建串行 + 单任务 sleep ≈ 1.8s, 仍远小于串行总和 3.6s。
    """
    pool = _pool(tmp_path, tuan_home, SlowEchoModel(delay=1.2), max_workers=3)
    tasks = [SubTask(task_id=f"P{i}", prompt=f"调研{i}") for i in range(3)]
    start = time.time()
    results = pool.dispatch(tasks, stream=False)
    elapsed = time.time() - start

    assert len(results) == 3
    assert all(r.ok for r in results)
    # 串行应约 3.6s; 真并行接近 构建串行 + 单任务 sleep (≈1.8s)。
    assert elapsed < 2.5, f"3×1.2s 真并行墙钟应 <2.5s, 实际 {elapsed:.2f}s (疑似串行)"


def test_subagent_results_structured_and_sourced(tmp_path, tuan_home):
    """结果结构化回传: 每个 SubResult 带 task_id/ok/output, aggregate 带来源标注。"""
    pool = _pool(tmp_path, tuan_home, SlowEchoModel(delay=0.01), max_workers=2)
    tasks = [SubTask(task_id="ALPHA", prompt="Alpha任务"),
             SubTask(task_id="BETA", prompt="Beta任务")]
    results = pool.dispatch(tasks, stream=False)

    # 顺序与输入一致
    assert [r.task_id for r in results] == ["ALPHA", "BETA"]
    # 每个结果结构化: 独立上下文隔离, 不串味
    by_id = {r.task_id: r for r in results}
    assert "Alpha任务" in by_id["ALPHA"].output
    assert "Beta任务" not in by_id["ALPHA"].output
    assert by_id["ALPHA"].elapsed >= 0

    # to_block / aggregate 产出带来源标注的报告 (主 Agent 直接消费)
    report = SubAgentPool.aggregate(results, title="并行调研汇总")
    assert "并行调研汇总" in report
    assert "ALPHA" in report and "BETA" in report
    assert "回声[" in report  # 带来源标注的子结果块


def test_subagent_failure_does_not_crash_parallel_batch(tmp_path, tuan_home):
    """并行批里一个子任务抛错, 其余仍正常完成 (失败隔离, 结果结构化带回错误)。"""
    kernel = build_kernel()
    config = kernel.require("config")

    class MixedModel(ModelAdapter):
        name = "mixed"
        def chat(self, messages, tools=None, stream=False, on_token=None, **kwargs):
            last = next((m["content"] for m in reversed(messages)
                         if m.get("role") == "user" and m.get("content")), "")
            if "炸掉" in last:
                raise RuntimeError("boom on purpose")
            return ModelResponse(content=f"完成[{last}]")

    kernel.unprovide("model_adapter")
    kernel.provide("model_adapter", MixedModel(), owner="test")
    pool = SubAgentPool(kernel=kernel, config=config, workspace=str(tmp_path),
                        max_workers=2, isolation="thread")
    results = pool.dispatch([SubTask(task_id="G", prompt="正常任务"),
                             SubTask(task_id="B", prompt="炸掉任务")], stream=False)
    by_id = {r.task_id: r for r in results}
    assert by_id["G"].ok is True and "完成" in by_id["G"].output
    assert by_id["B"].ok is False and "boom" in (by_id["B"].error or "")
