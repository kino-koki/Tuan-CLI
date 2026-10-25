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
from tuan_cli.agents.discovery import discover_agents, probe_agent, summarize
from tuan_cli.agents.router import REGISTRATION_PRIORITY, route, route_explain

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
    # hermes 实测口径 (v0.17.0): 单次查询走 `chat -q`
    assert asyncio.run(ADAPTERS["hermes"].build_command(TaskRequest(id="t", prompt="p"))) == ["hermes", "chat", "-q", "p"]


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


# ---------------------------------------------------------------------------
# 判定升级 (v0.3.2): 异步探测 + 健康分 (score) + verify 校验
# ---------------------------------------------------------------------------
def test_agent_info_score_default_and_to_dict():
    info = AgentInfo(id="c", name="Claude", healthy=True)
    assert info.score == 0  # 默认 0, 由 detect() 填充
    d = info.to_dict()
    assert d["score"] == 0
    scored = AgentInfo(id="c", name="Claude", healthy=True, score=100)
    assert scored.to_dict()["score"] == 100


def _stub_detect(monkeypatch, adapter_id, info):
    """把某个适配器的 detect() 换成返回固定 AgentInfo。"""
    monkeypatch.setattr(ADAPTERS[adapter_id], "detect", _async_return(info))


def _async_return(value):
    async def _inner():
        return value
    return _inner


def test_detect_not_found_scores_zero(monkeypatch):
    inst = ADAPTERS["codex"]
    monkeypatch.setattr("shutil.which", lambda cmd: None)
    info = asyncio.run(inst.detect())
    assert info.healthy is False
    assert info.score == 0
    assert "not found" in (info.reason or "")


def test_detect_verified_scores_100(monkeypatch):
    inst = ADAPTERS["claude-code"]
    monkeypatch.setattr("shutil.which", lambda cmd: "C:/fake/claude.exe")

    async def _probe(path):
        return "1.2.3 (Claude Code)", None

    monkeypatch.setattr(inst, "_probe_version", _probe)
    info = asyncio.run(inst.detect())
    assert info.healthy is True
    assert info.score == 100
    assert info.version == "1.2.3 (Claude Code)"


def test_detect_empty_version_scores_70(monkeypatch):
    inst = ADAPTERS["codex"]
    monkeypatch.setattr("shutil.which", lambda cmd: "C:/fake/codex.exe")

    async def _probe(path):
        return None, None  # 有命令, 无版本输出

    monkeypatch.setattr(inst, "_probe_version", _probe)
    info = asyncio.run(inst.detect())
    assert info.healthy is True
    assert info.score == 70
    assert info.version is None


def test_detect_probe_error_scores_70(monkeypatch):
    inst = ADAPTERS["kimi-code"]
    monkeypatch.setattr("shutil.which", lambda cmd: "C:/fake/kimi.exe")

    async def _probe(path):
        return None, "version probe timeout (5s)"

    monkeypatch.setattr(inst, "_probe_version", _probe)
    info = asyncio.run(inst.detect())
    assert info.healthy is True
    assert info.score == 70


def test_detect_verify_mismatch_scores_60_but_stays_healthy(monkeypatch):
    inst = ADAPTERS["hermes"]
    monkeypatch.setattr("shutil.which", lambda cmd: "C:/fake/hermes.exe")

    async def _probe(path):
        return "some-other-tool 2.0", None

    monkeypatch.setattr(inst, "_probe_version", _probe)
    info = asyncio.run(inst.detect())
    # 同名可疑: 不阻断路由 (healthy 仍为 True), 但降分 + 给出原因
    assert info.healthy is True
    assert info.score == 60
    assert "同名工具" in (info.reason or "")


def test_route_auto_health_score_breaks_weight_tie(monkeypatch):
    # chat 模式: deepseek-harness / hermes / kimi-code 权重同为 3;
    # claude-code (权重 5) 不健康被跳过 → 同权重按健康分决胜:
    # hermes 100 > deepseek 60 → 选 hermes; kimi-code 不健康不参与。
    _stub_detect(monkeypatch, "claude-code", AgentInfo(id="claude-code", name="cc", healthy=False, reason="missing"))
    _stub_detect(monkeypatch, "deepseek-harness", AgentInfo(id="deepseek-harness", name="dsh", healthy=True, score=60))
    _stub_detect(monkeypatch, "hermes", AgentInfo(id="hermes", name="hermes", healthy=True, score=100))
    _stub_detect(monkeypatch, "kimi-code", AgentInfo(id="kimi-code", name="kimi", healthy=False, reason="missing"))
    _stub_detect(monkeypatch, "codex", AgentInfo(id="codex", name="codex", healthy=True, score=100))
    a, err = asyncio.run(route(TaskRequest(id="t", prompt="p", mode="chat")))
    assert err is None
    assert a is not None
    assert a.id == "hermes"


def test_route_explain_reports_candidates(monkeypatch):
    _stub_detect(monkeypatch, "claude-code", AgentInfo(id="claude-code", name="cc", healthy=True, score=100))
    _stub_detect(monkeypatch, "deepseek-harness", AgentInfo(id="deepseek-harness", name="dsh", healthy=False, reason="missing"))
    _stub_detect(monkeypatch, "hermes", AgentInfo(id="hermes", name="hermes", healthy=True, score=70))
    _stub_detect(monkeypatch, "kimi-code", AgentInfo(id="kimi-code", name="kimi", healthy=True, score=100))
    _stub_detect(monkeypatch, "codex", AgentInfo(id="codex", name="codex", healthy=True, score=100))
    ex = asyncio.run(route_explain(TaskRequest(id="t", prompt="p", mode="lingma")))
    assert ex["error"] is None
    assert ex["agent"] == "codex"  # lingma 权重 5 最高
    selected = [r for r in ex["candidates"] if r["selected"]]
    assert len(selected) == 1
    assert selected[0]["id"] == "codex"
    # 每家都有权重/分数/健康度三项打分明细
    assert all({"id", "weight", "score", "healthy"} <= set(r) for r in ex["candidates"])


def test_route_explain_explicit_not_found():
    ex = asyncio.run(route_explain(TaskRequest(id="t", prompt="p", agent="ghost")))
    assert ex["agent"] is None
    assert "AGENT_NOT_FOUND" in (ex["error"] or "")


def test_summarize_counts_online_and_verified():
    infos = [
        AgentInfo(id="a", name="A", healthy=True, score=100),
        AgentInfo(id="b", name="B", healthy=True, score=70),
        AgentInfo(id="c", name="C", healthy=False),
    ]
    s = summarize(infos)
    assert s["online"] == 2
    assert s["total"] == 3
    assert s["verified"] == 1
    assert s["line"] == "2/3 在线"


def test_probe_agent_unknown_id():
    info = asyncio.run(probe_agent("ghost"))
    assert info.healthy is False
    assert info.reason == "AGENT_NOT_FOUND"


# ---------------------------------------------------------------------------
# tuan dispatch 独立命令层 (cmd_dispatch)
# ---------------------------------------------------------------------------
def _dispatch_args(**kw):
    import argparse

    ns = argparse.Namespace(
        dispatch_cmd=kw.pop("dispatch_cmd", "status"),
        prompt=kw.pop("prompt", ""),
        agent=kw.pop("agent", None),
        mode=kw.pop("mode", None),
        cwd=None,
        timeout=600,
        format=kw.pop("format", "text"),
        agent_id=kw.pop("agent_id", None),
        host=None,
        port=None,
    )
    return ns


def test_cmd_dispatch_status_table(monkeypatch, capsys):
    from tuan_cli.cli.cmd_dispatch import cmd_dispatch

    infos = [
        AgentInfo(id="claude-code", name="Claude Code", healthy=True, score=100, version="1.0"),
        AgentInfo(id="codex", name="Codex", healthy=False, reason="not found in PATH"),
    ]

    async def _fake_collect(args):
        return infos

    monkeypatch.setattr("tuan_cli.cli.cmd_dispatch._collect", _fake_collect)
    rc = cmd_dispatch(_dispatch_args(dispatch_cmd="status"))
    out = capsys.readouterr().out
    assert rc == 0  # 有在线代理
    assert "Claude Code" in out and "已验证" in out
    assert "未安装" in out
    assert "在线 1/2" in out


def test_cmd_dispatch_status_all_offline_returns_1(monkeypatch, capsys):
    from tuan_cli.cli.cmd_dispatch import cmd_dispatch

    async def _fake_collect(args):
        return [AgentInfo(id="codex", name="Codex", healthy=False, reason="not found in PATH")]

    monkeypatch.setattr("tuan_cli.cli.cmd_dispatch._collect", _fake_collect)
    rc = cmd_dispatch(_dispatch_args(dispatch_cmd="status"))
    assert rc == 1
    assert "在线 0/1" in capsys.readouterr().out


def test_cmd_dispatch_route_dry_run(monkeypatch, capsys):
    from tuan_cli.cli.cmd_dispatch import cmd_dispatch

    _stub_detect(monkeypatch, "claude-code", AgentInfo(id="claude-code", name="Claude Code", healthy=True, score=100))
    for aid in ("deepseek-harness", "codex", "kimi-code", "hermes"):
        _stub_detect(monkeypatch, aid, AgentInfo(id=aid, name=aid, healthy=False, reason="missing"))
    rc = cmd_dispatch(_dispatch_args(dispatch_cmd="route", prompt="p", mode="chat"))
    out = capsys.readouterr().out
    assert rc == 0
    assert "将派给: claude-code" in out
    assert "← 选中" in out


def test_cmd_dispatch_unknown_action(capsys):
    from tuan_cli.cli.cmd_dispatch import cmd_dispatch

    rc = cmd_dispatch(_dispatch_args(dispatch_cmd="frobnicate"))
    assert rc == 1
    assert "未知子命令" in capsys.readouterr().out
