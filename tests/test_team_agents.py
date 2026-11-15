"""团组 Agent-of-Agents 协调器 (TeamAgentCoordinator) 测试。"""

from __future__ import annotations

import time

import pytest

from tuan_cli.core.team_agents import (
    CoordinatorError,
    TeamAgentCoordinator,
    WorkerSpec,
    load_team_coordinator,
)
from tuan_cli.core.team_group import TeamGroupStore
from tuan_cli.core.team_security import TeamSecurityError, load_team_security

OWNER = "owner_alice"


@pytest.fixture()
def coord(tmp_path):
    store = TeamGroupStore(tmp_path / ".tuan" / "team_group.json")
    store.create_group("研发团组", OWNER, owner_name="Alice")
    store.register_provider_key("openai", "fp_openai", owner=OWNER)
    store.add_member("bob", actor=OWNER)
    grant = store.issue_grant("openai", "bob", days=30, owner=OWNER)
    sec = load_team_security(store)
    c = TeamAgentCoordinator(sec)
    return c, store, sec, grant["grant_id"]


def _echo_executor(spec, ctx):
    return f"echo:{spec.prompt}"


# ---------------------------------------------------------------- 基础派发


def test_dispatch_single_ok(coord):
    c, *_ = coord
    c.register_executor("echo", _echo_executor)
    rep = c.dispatch("goal", [WorkerSpec("w1", "echo", "hi")], actor=OWNER)
    assert rep.ok == 1 and rep.failed == 0
    assert rep.results[0].output == "echo:hi"
    assert rep.results[0].status == "ok"


def test_dispatch_parallel(coord):
    c, *_ = coord
    c.register_executor("echo", _echo_executor)
    workers = [WorkerSpec(f"w{i}", "echo", f"p{i}") for i in range(5)]
    rep = c.dispatch("parallel", workers, actor=OWNER)
    assert rep.total == 5 and rep.ok == 5
    outs = {r.output for r in rep.results}
    assert outs == {f"echo:p{i}" for i in range(5)}


def test_dispatch_empty_rejected(coord):
    c, *_ = coord
    with pytest.raises(CoordinatorError, match="worker"):
        c.dispatch("g", [], actor=OWNER)


def test_unregistered_capability_skipped(coord):
    c, *_ = coord
    rep = c.dispatch("g", [WorkerSpec("w1", "nope", "x")], actor=OWNER)
    assert rep.skipped == 1
    assert "未注册" in rep.results[0].error


def test_executor_exception_isolated(coord):
    c, *_ = coord

    def boom(spec, ctx):
        raise RuntimeError("kaboom")

    c.register_executor("boom", boom)
    c.register_executor("echo", _echo_executor)
    rep = c.dispatch("g", [
        WorkerSpec("w1", "boom", "x"),
        WorkerSpec("w2", "echo", "y"),
    ], actor=OWNER)
    assert rep.ok == 1 and rep.failed == 1
    statuses = {r.worker_id: r.status for r in rep.results}
    assert statuses["w1"] == "failed"
    assert statuses["w2"] == "ok"
    assert "kaboom" in next(r for r in rep.results if r.worker_id == "w1").error


# ---------------------------------------------------------------- 授权前置


def test_provider_worker_requires_grant_id(coord):
    c, *_ = coord
    c.register_executor("use", _echo_executor)
    rep = c.dispatch("g", [
        WorkerSpec("w1", "use", "x", provider="openai"),  # 缺 meta.grant_id
    ], actor=OWNER)
    assert rep.skipped == 1
    assert "授权失败" in rep.results[0].error


def test_provider_worker_with_valid_grant(coord):
    c, store, sec, gid = coord
    c.register_executor("use", _echo_executor)
    rep = c.dispatch("g", [
        WorkerSpec("w1", "use", "x", provider="openai",
                   meta={"grant_id": gid}, member="bob"),
    ], actor="bob")
    assert rep.ok == 1
    assert rep.results[0].output == "echo:x"
    assert rep.results[0].member == "bob"


def test_provider_worker_revoked_grant_skipped(coord):
    c, store, sec, gid = coord
    c.register_executor("use", _echo_executor)
    store.revoke_grant(gid, actor=OWNER)
    rep = c.dispatch("g", [
        WorkerSpec("w1", "use", "x", provider="openai", meta={"grant_id": gid}),
    ], actor="bob")
    assert rep.skipped == 1
    assert "授权失败" in rep.results[0].error


def test_provider_worker_nonce_replay(coord):
    c, store, sec, gid = coord
    c.register_executor("use", _echo_executor)
    # 第一次通过 (消费 nonce)
    rep1 = c.dispatch("g", [
        WorkerSpec("w1", "use", "x", provider="openai",
                   meta={"grant_id": gid}, nonce="n-1"),
    ], actor="bob")
    assert rep1.ok == 1
    # 第二次重放同 nonce -> skipped
    rep2 = c.dispatch("g", [
        WorkerSpec("w2", "use", "x", provider="openai",
                   meta={"grant_id": gid}, nonce="n-1"),
    ], actor="bob")
    assert rep2.skipped == 1


def test_mixed_provider_and_plain(coord):
    c, store, sec, gid = coord
    c.register_executor("use", _echo_executor)
    c.register_executor("plain", _echo_executor)
    rep = c.dispatch("g", [
        WorkerSpec("w1", "plain", "a"),
        WorkerSpec("w2", "use", "b", provider="openai", meta={"grant_id": gid}),
        WorkerSpec("w3", "use", "c", provider="openai", meta={"grant_id": "gr_missing"}),
    ], actor="bob")
    assert rep.ok == 2 and rep.skipped == 1


# ---------------------------------------------------------------- 审计


def test_dispatch_writes_audit(coord):
    c, store, *_ = coord
    c.register_executor("echo", _echo_executor)
    c.dispatch("审计目标", [WorkerSpec("w1", "echo", "hi")], actor=OWNER)
    audit = store.read_audit(limit=10)
    actions = [a["action"] for a in audit]
    assert "coord_dispatch" in actions
    assert "coord_report" in actions


# ---------------------------------------------------------------- 工厂


def test_load_coordinator_with_registry(coord):
    c, store, sec, gid = coord
    from tuan_cli.core.capability import make_capability_registry

    reg = make_capability_registry()
    # 给一个能力挂 handler
    cap = reg.get("spec_driven")
    cap.handler = lambda payload: f"cap:{payload['prompt']}"
    coord2 = load_team_coordinator(sec, capability_registry=reg)
    assert "spec_driven" in coord2.registered_capabilities()
    rep = coord2.dispatch("g", [WorkerSpec("w1", "spec_driven", "hello")], actor=OWNER)
    assert rep.ok == 1
    assert rep.results[0].output == "cap:hello"


# ---------------------------------------------------------------- CLI 端到端


def test_cli_rotate_and_challenge(tmp_path, capsys):
    import types
    from tuan_cli.cli.cmd_team import _cmd_challenge, _cmd_rotate

    ws = tmp_path
    store = TeamGroupStore(ws / ".tuan" / "team_group.json")
    store.create_group("g", OWNER, owner_name="A")
    args = types.SimpleNamespace(workspace=str(ws), json=True, actor=OWNER, grace_days=7, ttl=60)
    rc = _cmd_rotate(args)
    assert rc == 0
    out = capsys.readouterr().out
    assert "resigned_grants" in out
    rc2 = _cmd_challenge(args)
    assert rc2 == 0
    assert "challenge_id" in capsys.readouterr().out


def test_cli_dispatch_end_to_end(tmp_path, capsys):
    import json as _json
    import types
    from tuan_cli.cli.cmd_team import _cmd_dispatch

    ws = tmp_path
    store = TeamGroupStore(ws / ".tuan" / "team_group.json")
    store.create_group("g", OWNER, owner_name="A")
    # CLI 内部 load_team_coordinator 未注册执行器 -> worker 标记 skipped
    plan = {
        "goal": "demo",
        "workers": [{"worker_id": "w1", "capability": "echo", "prompt": "hi"}],
    }
    plan_path = ws / "plan.json"
    plan_path.write_text(_json.dumps(plan), encoding="utf-8")
    args = types.SimpleNamespace(
        workspace=str(ws), json=True, actor=OWNER, plan=str(plan_path))
    rc = _cmd_dispatch(args)
    # skipped 不算失败, 退出 0
    assert rc == 0
    out = capsys.readouterr().out
    assert '"skipped": 1' in out
    assert "未注册能力执行器" in out
