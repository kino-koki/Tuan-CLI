"""B3: Subagent 层隔离测试 —— 独立工作目录、失败隔离、超时清理。"""

from __future__ import annotations

import time

from qingxiaotuan.app import build_kernel
from qingxiaotuan.core.subagents import (
    SubAgentPool,
    SubTask,
    cleanup_isolated_workdir,
    prepare_isolated_workdir,
)
from qingxiaotuan.models.base import ModelAdapter, ModelResponse


class EchoModel(ModelAdapter):
    name = "echo"

    def chat(self, messages, tools=None, stream=False, on_token=None, **kwargs):
        return ModelResponse(content="回声完成")


class BoomModel(ModelAdapter):
    name = "boom"

    def chat(self, messages, tools=None, stream=False, on_token=None, **kwargs):
        raise RuntimeError("子代理内部爆炸")


class SleepModel(ModelAdapter):
    name = "sleep"

    def chat(self, messages, tools=None, stream=False, on_token=None, **kwargs):
        time.sleep(3)
        return ModelResponse(content="慢")


def _kernel_with(model):
    kernel = build_kernel()
    kernel.unprovide("model_adapter")
    kernel.provide("model_adapter", model, owner="test")
    return kernel


# ------------------------------------------------------------ 工作目录工具

def test_prepare_isolated_workdir(tmp_path):
    wd = prepare_isolated_workdir(tmp_path, "task-1")
    assert wd.is_dir()
    assert wd == tmp_path / ".qxt" / "subagents" / "task-1"
    assert cleanup_isolated_workdir(wd) is True
    assert not wd.exists()


# ------------------------------------------------------------ Pool 默认值

def test_pool_defaults_read_config(tmp_path):
    kernel = _kernel_with(EchoModel())
    pool = SubAgentPool(kernel, kernel.require("config"), str(tmp_path),
                        isolation="thread", max_workers=1)
    assert pool.isolated_workdir is True
    assert pool.default_timeout == 300  # subagent.timeout 默认 300s


# ------------------------------------------------------------ 独立工作目录生效

def test_subagent_uses_isolated_workdir(tmp_path):
    kernel = _kernel_with(EchoModel())
    pool = SubAgentPool(kernel, kernel.require("config"), str(tmp_path),
                        isolation="thread", max_workers=1)
    results = pool.dispatch([SubTask(task_id="T1", prompt="打个招呼")])
    assert len(results) == 1
    assert results[0].ok is True
    # 独立工作目录已创建且登记
    wd = pool._task_workdirs["T1"]
    assert wd.is_dir()
    assert wd.name == "T1"
    # 状态追踪
    status = pool.task_status()
    assert status[0]["status"] == "done"
    assert status[0]["task_id"] == "T1"


# ------------------------------------------------------------ 失败隔离

def test_failure_isolation(tmp_path):
    kernel = _kernel_with(BoomModel())
    pool = SubAgentPool(kernel, kernel.require("config"), str(tmp_path),
                        isolation="thread", max_workers=1)
    results = pool.dispatch([
        SubTask(task_id="BAD", prompt="会炸"),
    ])
    assert results[0].ok is False
    assert results[0].error
    # 状态记录为 failed
    assert pool.task_status()[0]["status"] == "failed"


# ------------------------------------------------------------ 超时

def test_timeout_kills_and_marks(tmp_path):
    kernel = _kernel_with(SleepModel())
    pool = SubAgentPool(kernel, kernel.require("config"), str(tmp_path),
                        isolation="thread", max_workers=1, default_timeout=1.0)
    start = time.time()
    results = pool.dispatch([SubTask(task_id="SLOW", prompt="慢慢来")])
    elapsed = time.time() - start
    assert results[0].ok is False
    assert "超时" in (results[0].error or "")
    assert elapsed < 2.5  # 没有真的等满 3 秒
    assert pool.task_status()[0]["status"] == "timeout"
