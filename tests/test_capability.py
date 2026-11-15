"""AgentCapability 统一门面测试 —— v0.4.2「一个 Agent 体验所有 Agent 能力」。

覆盖: 注册/启停/模式装配/受限能力 fail-closed/invoke/来源分组。
"""

from __future__ import annotations

import pytest

from tuan_cli.core.capability import (
    AgentCapability,
    CapabilityRegistry,
    builtin_capabilities,
    make_capability_registry,
)


# ---------------------------------------------------------------- 注册/查询


def test_builtin_capabilities_nonempty():
    caps = builtin_capabilities()
    assert len(caps) >= 10
    names = {c.name for c in caps}
    # goal 点名的各家理念都要有
    assert "spec_driven" in names  # Kiro
    assert "autonomous_coding" in names  # Codebuff
    assert "agent_steering" in names  # Windsurf
    assert "codebase_indexing" in names  # Cursor
    assert "team_group" in names  # Tuan v0.4.2


def test_register_and_get():
    reg = CapabilityRegistry()
    reg.register(AgentCapability(name="x", description="X"))
    assert reg.get("x").description == "X"
    assert reg.count() == 1


def test_register_duplicate_overwrites():
    reg = CapabilityRegistry()
    reg.register(AgentCapability(name="x", description="v1"))
    reg.register(AgentCapability(name="x", description="v2"))
    assert reg.get("x").description == "v2"
    assert reg.count() == 1


def test_get_unknown_returns_none():
    reg = CapabilityRegistry()
    assert reg.get("nope") is None


def test_unregister():
    reg = CapabilityRegistry()
    reg.register(AgentCapability(name="x", description="X"))
    assert reg.unregister("x") is True
    assert reg.unregister("x") is False
    assert reg.count() == 0


# ---------------------------------------------------------------- 启停


def test_enable_disable():
    reg = CapabilityRegistry()
    reg.register(AgentCapability(name="x", description="X", enabled=True))
    assert reg.is_enabled("x") is True
    reg.disable("x")
    assert reg.is_enabled("x") is False
    reg.enable("x")
    assert reg.is_enabled("x") is True


def test_enable_unknown_raises():
    reg = CapabilityRegistry()
    with pytest.raises(KeyError):
        reg.enable("nope")


# ---------------------------------------------------------------- 模式装配


def test_set_mode_restricted_shuts_high_risk():
    reg = make_capability_registry(mode="standard")
    assert reg.is_enabled("autonomous_coding") is True
    r = reg.set_mode("restricted")
    assert r["mode"] == "restricted"
    assert reg.is_enabled("autonomous_coding") is False
    assert reg.is_enabled("background_agents") is False
    assert reg.is_enabled("swarm_planner") is False
    # 普通能力不受影响
    assert reg.is_enabled("memory") is True


def test_set_mode_full_restores():
    reg = make_capability_registry(mode="restricted")
    assert reg.is_enabled("autonomous_coding") is False
    reg.set_mode("full")
    # 非受限能力恢复, 受限能力保持关闭 (需显式 force 开启)
    assert reg.is_enabled("memory") is True
    assert reg.is_enabled("autonomous_coding") is False


def test_force_enable_restricted():
    reg = make_capability_registry(mode="restricted")
    assert reg.enable("autonomous_coding", force=True) is True
    assert reg.is_enabled("autonomous_coding") is True
    # 非 force 在受限模式保持关闭
    reg.disable("autonomous_coding")
    assert reg.enable("autonomous_coding", force=False) is False


# ---------------------------------------------------------------- invoke


def test_invoke_enabled_handler():
    reg = CapabilityRegistry()
    reg.register(AgentCapability(
        name="calc", description="C", handler=lambda p: p.get("a", 0) + 1))
    assert reg.invoke("calc", {"a": 41}) == 42


def test_invoke_disabled_fails():
    reg = CapabilityRegistry()
    reg.register(AgentCapability(name="x", description="X",
                                 handler=lambda p: "ok", enabled=False))
    with pytest.raises(RuntimeError, match="未启用"):
        reg.invoke("x")


def test_invoke_no_handler_fails():
    reg = CapabilityRegistry()
    reg.register(AgentCapability(name="x", description="X"))  # handler=None
    with pytest.raises(RuntimeError, match="无运行时入口"):
        reg.invoke("x")


def test_invoke_unknown_raises():
    reg = CapabilityRegistry()
    with pytest.raises(KeyError):
        reg.invoke("nope")


# ---------------------------------------------------------------- 导出/来源


def test_list_hides_handler():
    reg = CapabilityRegistry()
    reg.register(AgentCapability(name="x", description="X", handler=lambda p: p))
    items = reg.list()
    assert len(items) == 1
    assert "handler" not in items[0]
    assert items[0]["name"] == "x"


def test_by_source_groups():
    reg = make_capability_registry()
    groups = reg.by_source()
    assert "Kiro" in groups
    assert "spec_driven" in groups["Kiro"]
    assert "Codebuff" in groups
    # Tuan 自己的能力
    assert any("team_group" in v for v in groups.get("Tuan v0.4.2", []))


def test_make_registry_counts():
    reg = make_capability_registry()
    assert reg.count() == reg.count_enabled()  # 标准模式全开
    assert reg.mode == "standard"
