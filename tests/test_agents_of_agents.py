"""Agent-of-Agents 调度层测试。

覆盖:
- 事件模型 (EventType / AgentEvent / TaskRequest / AgentInfo)
- 5 家适配器注册闭合 + build_command
- router: 显式指定 / auto 打分排序 / 不健康跳过 / 无可用
- discovery: 并行探测返回 5 家

不依赖本机真实安装哪些代理: detect() 在测试里被 monkeypatch 为可控的 healthy 状态。
"""
from __future__ import annotations

import asyncio

import pytest

from tuan_cli.agents.adapters import ADAPTERS
from tuan_cli.agents.base import AgentAdapter, AgentEvent, AgentInfo, EventType, TaskRequest
from tuan_cli.agents.discovery import discover_agents
from tuan_cli.agents.router import REGISTRATION_PRIORITY, route

EXPECTED_ADAPTERS = ("claude-code", "codex", "hermes", "deepseek-harness", "kimi-code")


# ---------------------------------------------------------------------------
# 事件模型
# ---------------------------------------------------------------------------
def test_event_type_protocol_values():
    assert EventType.TEXT.value == "text"
    assert EventType.TOOL_CALL.value == "tool_call"
    assert EventType.APPROVAL.value == "approval"
    assert EventType.STDERR.value == "stderr"
    assert EventType.ERROR.value == "error"
    assert EventType.DONE.value == "done"
    assert EventType.META.value == "meta"


def test_agent_event_to_dict():
    ev = AgentEvent(kind=EventType.TEXT, data={"text": "hi"}, seq=1, task_id="t1")
    d = ev.to_dict()
    assert d["type"] == "event"
    assert d["kind"] == "text"
    assert d["data"] == {"text": "hi"}
    assert d["seq"] == 1
    assert d["task_id"] == "t1"


def test_task_request_defaults():
    t = TaskRequest(id="x", prompt="p")
    assert t.agent == "auto"
    assert t.mode == "chat"
    assert t.stream is True
    assert t.auto_approve_low_risk is True
    assert t.timeout_sec == 600


def test_agent_info_to_dict_omits_reason_when_none():
    info = AgentInfo(id="c", name="Claude", healthy=True, version="1.0")
    d = info.to_dict()
    assert d["healthy"] is True
    assert d["version"] == "1.0"
    assert "reason" not in d

    sick = AgentInfo(id="c", name="Claude", healthy=False, reason="missing")
    assert sick.to_dict()["reason"] == "missing"


# ---------------------------------------------------------------------------
# 适配器注册与命令构建
# ---------------------------------------------------------------------------
def test_five_adapters_registered():
    for aid in EXPECTED_ADAPTERS:
        assert aid in ADAPTERS, f"adapter {aid} 未注册"
    # 注册顺序固定, 供 UI 稳定渲染
    assert list(ADAPTERS.keys()) == list(EXPECTED_ADAPTERS)


def test_build_command_claude():
    a = ADAPTERS["claude-code"]
    cmd = asyncio.run(a.build_command(TaskRequest(id="t", prompt="do it")))
    assert cmd == ["claude", "-p", "do it"]


def test_build_command_all_adapters():
    assert asyncio.run(ADAPTERS["codex"].build_command(TaskRequest(id="t", prompt="p"))) == ["codex", "exec", "p"]
    assert asyncio.run(ADAPTERS["deepseek-harness"].build_command(TaskRequest(id="t", prompt="p"))) == ["dsh", "--prompt", "p"]
    assert asyncio.run(ADAPTERS["kimi-code"].build_command(TaskRequest(id="t", prompt="p"))) == ["kimi-code", "--prompt", "p"]
    assert asyncio.run(ADAPTERS["hermes"].build_command(TaskRequest(id="t", prompt="p"))) == ["hermes", "run", "p"]


def test_all_adapters_subclass_base_and_are_configured():
    # 不变式: 每个注册适配器都是 AgentAdapter 子类, 且 id / command / weights 都填好
    for inst in ADAPTERS.values():
        assert isinstance(inst, AgentAdapter)
        assert inst.id
        assert inst.command
        assert inst.weights
        # weights 必须是 mode -> int 映射
        assert all(isinstance(v, int) for v in inst.weights.values())


# ---------------------------------------------------------------------------
# router / discovery (monkeypatch detect, 不依赖本机真实安装)
# ---------------------------------------------------------------------------
@pytest.fixture
def healthy_agents(monkeypatch):
    for inst in ADAPTERS.values():
        aid = inst.id

        async def _fake_detect(aid=aid):
            return AgentInfo(id=aid, name=aid, healthy=True, version="1.0")

        monkeypatch.setattr(inst, "detect", _fake_detect)
    yield


def test_route_explicit_not_found():
    a, err = asyncio.run(route(TaskRequest(id="t", prompt="p", agent="ghost")))
    assert a is None
    assert "AGENT_NOT_FOUND" in (err or "")


def test_route_explicit_healthy(healthy_agents):
    a, err = asyncio.run(route(TaskRequest(id="t", prompt="p", agent="claude-code")))
    assert err is None
    assert a is not None
    assert a.id == "claude-code"


def test_route_explicit_unhealthy(monkeypatch):
    inst = ADAPTERS["claude-code"]

    async def _bad():
        return AgentInfo(id="claude-code", name="Claude", healthy=False, reason="missing")

    monkeypatch.setattr(inst, "detect", _bad)
    a, err = asyncio.run(route(TaskRequest(id="t", prompt="p", agent="claude-code")))
    assert a is None
    assert "AGENT_UNHEALTHY" in (err or "")


def test_route_auto_picks_highest_weight(healthy_agents):
    # lingma 模式: codex weights=5 最高 -> 应选 codex
    a, err = asyncio.run(route(TaskRequest(id="t", prompt="p", mode="lingma")))
    assert err is None
    assert a is not None
    assert a.id == "codex"


def test_route_auto_chat_prefers_claude(healthy_agents):
    # chat 模式: claude-code weights=5 最高且在优先级最前
    a, err = asyncio.run(route(TaskRequest(id="t", prompt="p", mode="chat")))
    assert err is None
    assert a.id == "claude-code"


def test_route_auto_no_available(monkeypatch):
    for inst in ADAPTERS.values():
        async def _bad():
            return AgentInfo(id=inst.id, name=inst.display_name, healthy=False)

        monkeypatch.setattr(inst, "detect", _bad)
    a, err = asyncio.run(route(TaskRequest(id="t", prompt="p")))
    assert a is None
    assert "NO_AGENT_AVAILABLE" in (err or "")


def test_discover_agents_returns_all(healthy_agents):
    infos = asyncio.run(discover_agents())
    assert len(infos) == len(EXPECTED_ADAPTERS)
    assert all(i.healthy for i in infos)


def test_registration_priority_covers_all():
    for aid in EXPECTED_ADAPTERS:
        assert aid in REGISTRATION_PRIORITY
