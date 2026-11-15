"""专家团编排器 (TeamLead) 测试 —— 调度外部 CLI agent 组成开发团。

全部用 mock 适配器, 不依赖本机真实安装 claude/codex 等。
"""

from __future__ import annotations

import asyncio

import pytest

from tuan_cli.agents.base import AgentAdapter, AgentEvent, AgentInfo, EventType
from tuan_cli.core.team_lead import (
    DevRole,
    TeamLead,
    default_roles,
    make_team_lead,
)


# ============================================================ mock 适配器


class MockAdapter(AgentAdapter):
    """可控的 mock 外部 agent (按 preset 决定输出/失败)。"""

    def __init__(self, aid: str, output: str = "ok-output", fail: bool = False,
                 empty: bool = False):
        self.id = aid
        self.display_name = aid
        self._output = output
        self._fail = fail
        self._empty = empty
        self.calls: list = []

    async def detect(self) -> AgentInfo:
        return AgentInfo(id=self.id, name=self.display_name, healthy=True, score=100)

    async def run(self, task):
        self.calls.append(task)
        if self._fail:
            yield AgentEvent(kind=EventType.ERROR, data={"message": "boom"})
            yield AgentEvent(kind=EventType.DONE, data={"status": "error"})
            return
        if self._empty:
            yield AgentEvent(kind=EventType.DONE, data={"status": "ok"})
            return
        yield AgentEvent(kind=EventType.TEXT, data={"text": self._output})
        yield AgentEvent(kind=EventType.DONE, data={"status": "ok"})


@pytest.fixture()
def healthy_env(monkeypatch):
    """注入全部 9 家健康 mock agent 到全局 ADAPTERS (v0.4.2: 扩充后 9 家)。

    每家输出不同的文本, 便于断言路由与结果聚合。
    """
    from tuan_cli.agents.adapters import ADAPTERS

    output_by_id = {
        "claude-code": "ARCH", "codex": "IMPL", "kimi-code": "REVIEW",
        "hermes": "HERMES", "deepseek-harness": "DSH",
        "gemini": "GEMINI", "aider": "AIDER", "qwen-code": "QWEN", "doubao": "DOUBAO",
    }
    mocks = {aid: MockAdapter(aid, out) for aid, out in output_by_id.items()}
    for aid, m in mocks.items():
        monkeypatch.setitem(ADAPTERS, aid, m)
    return mocks


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


# ============================================================ 角色/分配


def test_default_roles_cover_dev_loop():
    roles = default_roles()
    keys = {r.key for r in roles}
    assert {"architect", "implementer", "reviewer", "tester"} <= keys


def test_assign_role_prefers_preferred(healthy_env):
    lead = make_team_lead()
    _run(lead.discover())
    arch = next(r for r in lead.roles if r.key == "architect")
    assert lead.assign_role(arch) == "claude-code"


def test_assign_role_degrades_when_preferred_missing(monkeypatch, healthy_env):
    from tuan_cli.agents.adapters import ADAPTERS
    # 移除首选 + 次选 (claude-code, codex), 架构师应降级到第三偏好 gemini
    monkeypatch.delitem(ADAPTERS, "claude-code", raising=False)
    monkeypatch.delitem(ADAPTERS, "codex", raising=False)
    lead = make_team_lead()
    _run(lead.discover())
    arch = next(r for r in lead.roles if r.key == "architect")
    assert lead.assign_role(arch) == "gemini"


def test_assign_role_none_when_no_healthy(monkeypatch, healthy_env):
    from tuan_cli.agents.adapters import ADAPTERS
    for aid in list(healthy_env.keys()):
        monkeypatch.delitem(ADAPTERS, aid, raising=False)
    lead = make_team_lead()
    _run(lead.discover())
    arch = next(r for r in lead.roles if r.key == "architect")
    assert lead.assign_role(arch) is None


def test_plan_maps_all_roles(healthy_env):
    lead = make_team_lead()
    _run(lead.discover())
    plan = lead.plan()
    assert set(plan.keys()) == {r.key for r in lead.roles}
    all_ids = set(healthy_env.keys())  # fixture 注入的 9 家
    assert all(v in all_ids for v in plan.values())


# ============================================================ 派发


def test_run_aggregates_ok(healthy_env):
    lead = make_team_lead(roles=[DevRole("a", "A", "do a", preferred=["claude-code"]),
                                 DevRole("b", "B", "do b", preferred=["codex"])])
    rep = _run(lead.run("构建 X"))
    assert rep.total == 2 and rep.ok == 2 and rep.failed == 0
    by_role = {r.role: r for r in rep.roles}
    assert by_role["a"].text == "ARCH"
    assert by_role["a"].agent_id == "claude-code"
    assert by_role["b"].text == "IMPL"


def test_run_injects_goal_into_prompt(healthy_env):
    mocks = healthy_env
    lead = make_team_lead(roles=[DevRole("a", "A", "PREAMBLE", preferred=["claude-code"])])
    _run(lead.run("MY_GOAL"))
    sent = mocks["claude-code"].calls[0]
    assert "PREAMBLE" in sent.prompt
    assert "MY_GOAL" in sent.prompt


def test_run_parallel_all_roles(healthy_env):
    lead = make_team_lead()  # 默认 4 角色
    rep = _run(lead.run("全流程"))
    assert rep.total == 4
    # 全部角色都被分配到健康 agent
    assert all(r.status in {"ok"} for r in rep.roles)


def test_run_failure_isolated(monkeypatch, healthy_env):
    from tuan_cli.agents.adapters import ADAPTERS
    # 让 codex 失败, 其它仍成功
    ADAPTERS["codex"] = MockAdapter("codex", fail=True)
    lead = make_team_lead(roles=[DevRole("a", "A", "x", preferred=["claude-code"]),
                                 DevRole("b", "B", "y", preferred=["codex"])])
    rep = _run(lead.run("g"))
    by_role = {r.role: r for r in rep.roles}
    assert by_role["a"].status == "ok"
    assert by_role["b"].status == "failed"
    assert "boom" in by_role["b"].error
    assert rep.ok == 1 and rep.failed == 1


def test_run_empty_output_flagged(monkeypatch, healthy_env):
    from tuan_cli.agents.adapters import ADAPTERS
    ADAPTERS["codex"] = MockAdapter("codex", empty=True)
    lead = make_team_lead(roles=[DevRole("b", "B", "y", preferred=["codex"])])
    rep = _run(lead.run("g"))
    assert rep.roles[0].status == "empty"
    assert rep.failed == 0 and rep.ok == 0


def test_run_missing_when_no_healthy(monkeypatch, healthy_env):
    from tuan_cli.agents.adapters import ADAPTERS
    for aid in list(healthy_env.keys()):
        monkeypatch.delitem(ADAPTERS, aid, raising=False)
    lead = make_team_lead(roles=[DevRole("a", "A", "x")])
    rep = _run(lead.run("g"))
    assert rep.roles[0].status == "missing"
    assert rep.missing == 1


def test_run_empty_roles_rejected(healthy_env):
    # role filter 匹配不到任何角色时, run() 应拒绝
    lead = make_team_lead()
    with pytest.raises(ValueError, match="角色"):
        _run(lead.run("g", roles=["nonexistent-role"]))


def test_run_role_filter(healthy_env):
    lead = make_team_lead()
    rep = _run(lead.run("g", roles=["architect"]))
    assert rep.total == 1
    assert rep.roles[0].role == "architect"


def test_report_to_dict_shape(healthy_env):
    lead = make_team_lead(roles=[DevRole("a", "A", "x", preferred=["claude-code"])])
    rep = _run(lead.run("g"))
    d = rep.to_dict()
    assert d["goal"] == "g"
    assert d["total"] == 1 and d["ok"] == 1
    assert d["roles"][0]["agent_id"] == "claude-code"
    assert "text" in d["roles"][0]


# ============================================================ 团组审计集成


def test_audited_team_lead_writes_audit(healthy_env, tmp_path):
    """带团组 store 的专家团应把派发/结果写进 team_audit.jsonl。"""
    from tuan_cli.core.team_group import TeamGroupStore
    from tuan_cli.core.team_lead import make_audited_team_lead

    store = TeamGroupStore(tmp_path / ".tuan" / "team_group.json")
    store.create_group("g", "alice", owner_name="Alice")
    lead = make_audited_team_lead(
        store, roles=[DevRole("a", "A", "x", preferred=["claude-code"])])
    rep = _run(lead.run("审计目标", actor="alice"))
    assert rep.ok == 1
    audit = store.read_audit(limit=10)
    actions = [a["action"] for a in audit]
    assert "expert_dispatch" in actions
    assert "expert_report" in actions


def test_audited_team_lead_none_store_noop(healthy_env):
    """store=None 时优雅降级为纯 TeamLead (不写审计, 不抛异常)。"""
    from tuan_cli.core.team_lead import make_audited_team_lead

    lead = make_audited_team_lead(None, roles=[DevRole("a", "A", "x", preferred=["codex"])])
    rep = _run(lead.run("g"))
    assert rep.ok == 1


def test_audited_team_lead_delegates_plan(healthy_env, tmp_path):
    """AuditedTeamLead.plan/discover 应代理给内部 lead。"""
    from tuan_cli.core.team_lead import make_audited_team_lead

    lead = make_audited_team_lead(None)
    _run(lead.discover())
    plan = lead.plan()
    assert set(plan.keys()) == {r.key for r in lead.lead.roles}


# ============================================================ CLI 入口


def test_cli_teamlead_registered():
    """tuan teamlead 命令应被注册到命令表。"""
    from tuan_cli.cli.parser import _COMMAND_REGISTRY, _auto_register
    _auto_register()
    assert _COMMAND_REGISTRY.get("cmd_teamlead") == ".cmd_teamlead"


def test_cli_teamlead_status_no_agents(monkeypatch, tmp_path, capsys):
    """无外部 agent 时, teamlead status --json 应返回 1 (exit code) 并列出 agent。"""
    import types
    from tuan_cli.cli.cmd_teamlead import cmd_teamlead

    # 清空健康探测 (本机可能装了, 但我们强制空表, 走 not-found 分支)
    import tuan_cli.agents.adapters as A

    class _Noop(AgentAdapter):
        id = "noop"
        display_name = "Noop"

        async def detect(self):
            return AgentInfo(id="noop", name="Noop", healthy=False, reason="not found in PATH")

        async def run(self, task):
            yield AgentEvent(kind=EventType.DONE, data={"status": "ok"})

    monkeypatch.setitem(A.ADAPTERS, "claude-code", _Noop())
    monkeypatch.setitem(A.ADAPTERS, "codex", _Noop())
    args = types.SimpleNamespace(teamlead_cmd="status", json=True)
    rc = cmd_teamlead(args)
    out = capsys.readouterr().out
    assert "healthy" in out and "false" in out
    assert rc == 1  # 在线为 0 → exit 1
