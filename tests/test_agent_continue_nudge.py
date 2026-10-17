# -*- coding: utf-8 -*-
"""Agent 主循环"续跑兜底"测试: 模型中途纯文本停住时不得提前结束任务。

背景: 主循环历来把"无 tool_calls 的回复"直接当作最终答案 break。弱模型在多步
任务中途经常输出一段解释/计划文本而不带工具调用, 循环随即终止 —— 用户观感
"Agent 干一会儿活就停下来, 任务还没干完"。现在: 若上下文显示刚才还在干工具活,
注入一条继续提示让模型自己判断 (完成了说 DONE, 否则接着干), 上限
``fusion.continue_nudge_max`` (默认 3) 次, 防止无限续跑。
"""
import json

import pytest

from tuan_cli.app import build_kernel
from tuan_cli.core.agent import Agent
from tuan_cli.models.base import ModelAdapter, ModelResponse, ToolCall


class MockModel(ModelAdapter):
    name = "mock"

    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    def chat(self, messages, tools=None, stream=False, on_token=None, **kwargs):
        self.calls.append([dict(m) for m in messages])
        return self.script.pop(0)


def _build_agent(tmp_path, script):
    kernel = build_kernel()
    config = kernel.require("config")
    config.data["agent"]["skill_nudge_interval"] = 0   # 关闭 nudge, 纯测续跑
    kernel.unprovide("model_adapter")
    kernel.provide("model_adapter", MockModel(script), owner="test")
    return Agent(kernel=kernel, config=config, workspace=str(tmp_path),
                 confirm=lambda _p: True)


_WRITE = ModelResponse(tool_calls=[ToolCall(
    id="c1", name="write_file",
    arguments=json.dumps({"path": "out.txt", "content": "hello"}))])


def test_midtask_text_reply_triggers_continue_nudge(tmp_path, tuan_home):
    """工具活干到一半模型只说了句话 → 必须注入继续提示而不是直接结束。"""
    model_calls = []
    agent = _build_agent(tmp_path, [
        _WRITE,
        ModelResponse(content="让我再检查一下其他文件"),   # 中途停 (无工具调用)
        ModelResponse(content="任务已完成, out.txt 已写入"),
    ])
    orig_chat = type(agent.model).chat

    def spy(self, messages, **kw):
        model_calls.append(len(messages))
        return orig_chat(self, messages, **kw)

    type(agent.model).chat = spy
    try:
        answer = agent.run("写一个文件并检查")
    finally:
        type(agent.model).chat = orig_chat

    assert "已完成" in answer
    assert agent._continue_nudges == 1          # 注入过一次续跑
    assert len(agent.model.calls) == 3          # 工具轮 + 中途停轮 + 续跑轮


def test_legitimate_completion_does_not_nudge(tmp_path, tuan_home):
    """真正完成 (命中完成线索) 不得被续跑拖住。"""
    agent = _build_agent(tmp_path, [
        _WRITE,
        ModelResponse(content="任务已完成, out.txt 已写入"),
    ])
    answer = agent.run("写一个文件")
    assert "已完成" in answer
    assert agent._continue_nudges == 0
    assert len(agent.model.calls) == 2          # 无续跑注入


def test_continue_nudge_is_capped(tmp_path, tuan_home):
    """续跑有上限 (默认 3), 不会无限循环。"""
    stall = ModelResponse(content="让我继续看看")   # 永远"未完成"
    script = [_WRITE] + [stall] * 8
    agent = _build_agent(tmp_path, script)
    agent.run("写一个文件并一直检查")
    assert agent._continue_nudges == 3          # 达到上限即停
    assert len(agent.model.calls) == 1 + 1 + 3  # 工具轮 + 首次停 + 3 次续跑


def test_looks_unfinished_classification():
    """只有明确的"继续"线索才判为未完成; 正常收尾不得误判。"""
    assert Agent._looks_unfinished("让我先看看文件结构") is True
    assert Agent._looks_unfinished("接下来我需要修改配置") is True
    assert Agent._looks_unfinished("还需要安装依赖") is True
    assert Agent._looks_unfinished("I will now update the config") is True
    # 正常收尾 (无继续线索) 一律视为完成 —— 不得误判
    assert Agent._looks_unfinished("任务已完成, 已写入 out.txt") is False
    assert Agent._looks_unfinished("Done. All tests pass.") is False
    assert Agent._looks_unfinished("文件已写好") is False
    assert Agent._looks_unfinished("被拒绝了") is False
    assert Agent._looks_unfinished("") is False
