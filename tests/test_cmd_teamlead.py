"""``tuan teamlead`` CLI 入口的单元测试 —— 用 mock agent 不依赖 PATH。

覆盖三件事:
1. ``status`` / ``plan`` / ``run`` 三个子命令分发 (cmd_teamlead)。
2. 空机 / 单机 / 多机 三种发现结果下的分配计划正确性 (缺位 vs 降级)。
3. ``run`` 并行聚合报告 (ok/failed/missing/empty 状态收敛)。

所有测试都不依赖真实 CLI 在 PATH, 通过 monkeypatch 伪造 ``_adapters``。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, AsyncIterator, Dict, List

import pytest

from tuan_cli.agents.base import AgentEvent, EventType, TaskRequest
from tuan_cli.core.team_lead import (
    DevRole, RoleReport, TeamLead, TeamReport,
    default_roles, make_team_lead,
)


# ============================================================ 测试基建


@dataclass
class FakeAgentInfo:
    """伪造的 AgentInfo (与 agents.base.AgentInfo 字段对齐)。"""

    id: str
    name: str
    healthy: bool = True
    version: str = ""
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {"id": self.id, "name": self.name, "healthy": self.healthy,
                "version": self.version, "reason": self.reason}


class FakeAdapter:
    """伪造的 AgentAdapter —— 返回预设的文本/事件序列。"""

    def __init__(self, agent_id: str, *,
                 text: str = "ok", events: int = 1,
                 fail: bool = False, empty: bool = False) -> None:
        self._id = agent_id
        self._text = text
        self._events = events
        self._fail = fail
        self._empty = empty

    async def run(self, task: TaskRequest) -> AsyncIterator[AgentEvent]:
        if self._fail:
            yield AgentEvent(kind=EventType.ERROR, data={"message": "boom"})
            yield AgentEvent(kind=EventType.DONE, data={"status": "error"})
            return
        if not self._empty:
            yield AgentEvent(kind=EventType.TEXT, data={"text": self._text})
        yield AgentEvent(kind=EventType.DONE, data={"status": "ok"})


def _make_lead_with(agents: Dict[str, FakeAdapter], *,
                    healthy: List[str] = None) -> TeamLead:
    """构造一个用假 adapters 的 TeamLead, _health 预填好。"""
    lead = TeamLead()
    lead._adapters = agents
    if healthy is None:
        healthy = list(agents.keys())
    lead._health = {aid: FakeAgentInfo(id=aid, name=aid, healthy=(aid in healthy))
                    for aid in list(agents.keys()) + [x for x in healthy if x not in agents]}
    return lead


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


# ============================================================ 默认角色


class TestDefaultRoles:
    """default_roles() 覆盖典型开发闭环。"""

    def test_has_four_roles(self) -> None:
        roles = default_roles()
        assert len(roles) == 4

    def test_role_keys(self) -> None:
        keys = {r.key for r in default_roles()}
        assert keys == {"architect", "implementer", "reviewer", "tester"}

    def test_each_role_has_preferred(self) -> None:
        for r in default_roles():
            assert isinstance(r.preferred, list)
            assert len(r.preferred) > 0
            assert isinstance(r.instruction, str) and r.instruction.strip()


# ============================================================ 发现


class TestDiscovery:
    """discover() 探测 PATH 并缓存。"""

    def test_discover_populates_health(self) -> None:
        lead = TeamLead()

        async def fake_discover() -> List[FakeAgentInfo]:
            return [FakeAgentInfo("claude-code", "Claude"),
                    FakeAgentInfo("codex", "Codex", healthy=False, reason="not found")]

        import tuan_cli.agents.discovery as d
        import tuan_cli.core.team_lead as tl
        orig = d.discover_agents
        try:
            d.discover_agents = fake_discover  # monkeypatch at source
            # 因为 team_lead 内部是 ``from ..agents.discovery import discover_agents``
            # 在调用时才导入, 所以 patch 该模块的属性就够:
            import tuan_cli.agents.discovery  # noqa
            asyncio.new_event_loop().run_until_complete(lead.discover())
        finally:
            d.discover_agents = orig
        assert "claude-code" in lead._health
        assert "codex" in lead._health
        assert lead._health["claude-code"].healthy is True
        assert lead._health["codex"].healthy is False

    def test_healthy_agents_returns_only_healthy(self) -> None:
        lead = _make_lead_with(
            {"a": FakeAdapter("a"), "b": FakeAdapter("b")},
            healthy=["a"],
        )
        assert lead.healthy_agents() == ["a"]


# ============================================================ 角色分配


class TestAssignRole:
    """assign_role 优先 preferred → 任意健康 → None。"""

    def test_preferred_first(self) -> None:
        lead = _make_lead_with({"a": FakeAdapter("a"), "b": FakeAdapter("b")})
        role = DevRole("r", "R", "inst", preferred=["b"])
        assert lead.assign_role(role) == "b"

    def test_fallback_to_any_healthy(self) -> None:
        lead = _make_lead_with({"x": FakeAdapter("x")})
        role = DevRole("r", "R", "inst", preferred=["nonexistent"])
        assert lead.assign_role(role) == "x"

    def test_no_healthy_returns_none(self) -> None:
        lead = _make_lead_with({"x": FakeAdapter("x")}, healthy=[])
        role = DevRole("r", "R", "inst", preferred=["x"])
        assert lead.assign_role(role) is None

    def test_plan_covers_all_roles(self) -> None:
        lead = _make_lead_with({"codex": FakeAdapter("codex")})
        plan = lead.plan()
        assert set(plan.keys()) == {r.key for r in lead.roles}
        assert plan["architect"] == "codex"  # 降级到唯一健康 agent
        assert plan["implementer"] == "codex"


# ============================================================ 并行派发


class TestRunRoles:
    """run() 并行聚合 + 状态收敛。"""

    def test_run_ok_status(self) -> None:
        lead = _make_lead_with({"codex": FakeAdapter("codex", text="hello")})
        report = _run(lead.run("做一件事"))
        assert isinstance(report, TeamReport)
        assert report.total == 4
        assert report.ok == 4
        assert report.failed == 0
        assert report.missing == 0
        for r in report.roles:
            assert r.status == "ok"
            assert r.text == "hello"
            assert r.agent_id == "codex"

    def test_run_missing_when_no_healthy(self) -> None:
        lead = _make_lead_with({"codex": FakeAdapter("codex")}, healthy=[])
        report = _run(lead.run("做一件事"))
        assert report.ok == 0
        assert report.missing == 4
        for r in report.roles:
            assert r.status == "missing"
            assert "PATH" in r.error

    def test_run_failed_status(self) -> None:
        lead = _make_lead_with({"codex": FakeAdapter("codex", fail=True)})
        report = _run(lead.run("做一件事"))
        assert report.failed == 4
        for r in report.roles:
            assert r.status == "failed"
            assert "boom" in r.error

    def test_run_empty_status(self) -> None:
        lead = _make_lead_with({"codex": FakeAdapter("codex", empty=True)})
        report = _run(lead.run("做一件事"))
        assert report.ok == 0
        # 空输出不是 ok 也不是 failed, 而是 empty (避免假成功)
        for r in report.roles:
            assert r.status == "empty"
            assert "无文本输出" in r.error

    def test_run_roles_filter(self) -> None:
        lead = _make_lead_with({"codex": FakeAdapter("codex", text="x")})
        report = _run(lead.run("目标", roles=["architect"]))
        assert report.total == 1
        assert report.roles[0].role == "architect"

    def test_run_to_dict_roundtrip(self) -> None:
        lead = _make_lead_with({"codex": FakeAdapter("codex", text="y")})
        report = _run(lead.run("goal"))
        d = report.to_dict()
        assert d["goal"] == "goal"
        assert d["total"] == 4 and d["ok"] == 4
        assert len(d["roles"]) == 4
        assert all(r["agent_id"] == "codex" for r in d["roles"])


# ============================================================ 工厂


class TestFactories:
    """make_team_lead / make_audited_team_lead。"""

    def test_make_team_lead_defaults(self) -> None:
        lead = make_team_lead()
        assert isinstance(lead, TeamLead)
        assert len(lead.roles) == 4

    def test_make_team_lead_custom_roles(self) -> None:
        role = DevRole("only", "Only", "inst")
        lead = make_team_lead([role])
        assert lead.roles == [role]

    def test_make_team_lead_timeout(self) -> None:
        lead = make_team_lead(timeout_sec=42)
        assert lead.timeout_sec == 42
