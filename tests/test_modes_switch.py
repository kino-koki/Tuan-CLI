"""测试: 五模式切换规则 R1–R7 + 别名 + 锁定 + 平台 + 持久化 + 事件。"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from tuan_cli.modes.registry import (
    MODE_ALIASES,
    MODE_IDS,
    MODE_NAMES,
    get_mode_meta,
    resolve_mode_id,
)
from tuan_cli.modes.switcher import check_transition, current_mode, switch_mode
from tuan_cli.modes.policy import get_mode_policy, ModePolicy


# =====================================================================
# 注册表基础测试
# =====================================================================


def test_mode_ids_complete():
    assert MODE_IDS == ("gantong", "lingma", "chat", "boundless", "collaboration")


def test_mode_names_complete():
    assert MODE_NAMES == {
        "gantong": "感通",
        "lingma": "灵码",
        "chat": "闲聊",
        "boundless": "无界",
        "collaboration": "协同",
    }


def test_alias_resolution():
    """旧三档别名应映射到新模式 ID。"""
    assert resolve_mode_id("standard") == "collaboration"
    assert resolve_mode_id("yolo") == "boundless"
    assert resolve_mode_id("plan") == "chat"


def test_alias_resolve_via_get_mode_meta():
    """get_mode_meta 应支持别名解析。"""
    meta = get_mode_meta("standard")
    assert meta["id"] == "collaboration"
    assert meta["name"] == "协同"

    meta = get_mode_meta("yolo")
    assert meta["id"] == "boundless"
    assert meta["name"] == "无界"

    meta = get_mode_meta("plan")
    assert meta["id"] == "chat"
    assert meta["name"] == "闲聊"


def test_invalid_mode_rejected():
    """非法模式 ID 应抛 ValueError。"""
    with pytest.raises(ValueError, match="未知模式"):
        resolve_mode_id("turbo")
    with pytest.raises(ValueError):
        get_mode_meta("invalid")


def test_mode_meta_fields():
    """每个模式元数据应包含必要字段。"""
    for mid in MODE_IDS:
        meta = get_mode_meta(mid)
        assert meta["id"] == mid
        assert "name" in meta
        assert "level" in meta
        assert "risk" in meta
        assert "description" in meta
        assert "loop" in meta
        assert "capabilities" in meta
        assert "shell" in meta["capabilities"]
        assert "mcp" in meta["capabilities"]
        assert "network" in meta["capabilities"]


# =====================================================================
# check_transition — R1: chat → 任意
# =====================================================================


def test_r1_chat_to_any_allowed():
    """R1: chat → L2/L3 模式允许（用户显式切换，无跨级跳升）。"""
    for dst in ("collaboration", "gantong", "lingma"):
        allowed, reason = check_transition("chat", dst)
        assert allowed, f"chat → {dst} 应被允许，实际: {reason}"


def test_r1_chat_to_boundless_requires_force():
    """R1-ext: chat → boundless (L0→L4 跨级跳升) 需 force 确认。"""
    allowed, reason = check_transition("chat", "boundless", force=False)
    assert not allowed
    assert "R1" in reason
    allowed, reason = check_transition("chat", "boundless", force=True)
    assert allowed
    assert "R1" in reason


def test_r1_chat_to_same_noop():
    """chat → chat 是无操作。"""
    allowed, reason = check_transition("chat", "chat")
    assert allowed
    assert "未变化" in reason


# =====================================================================
# check_transition — R2: collaboration → lingma/gantong
# =====================================================================


def test_r2_collab_to_lingma_no_force_rejected():
    """R2: collaboration → lingma 不带 force 应拒绝。"""
    allowed, reason = check_transition("collaboration", "lingma", force=False)
    assert not allowed
    assert "R2" in reason


def test_r2_collab_to_lingma_force_allowed():
    """R2: collaboration → lingma 带 force 应允许。"""
    allowed, reason = check_transition("collaboration", "lingma", force=True)
    assert allowed
    assert "R2" in reason


def test_r2_collab_to_gantong_no_force_rejected():
    """R2: collaboration → gantong 不带 force 应拒绝。"""
    allowed, reason = check_transition("collaboration", "gantong", force=False)
    assert not allowed


def test_r2_collab_to_chat_not_affected():
    """R2 不影响 collaboration → chat（由 R5 处理）。"""
    allowed, reason = check_transition("collaboration", "chat", force=False)
    assert allowed
    assert "R5" in reason


# =====================================================================
# check_transition — R3: gantong/lingma → boundless
# =====================================================================


def test_r3_gantong_to_boundless_no_force_rejected():
    """R3: gantong → boundless 不带 force 应拒绝。"""
    allowed, reason = check_transition("gantong", "boundless", force=False)
    assert not allowed
    assert "R3" in reason


def test_r3_lingma_to_boundless_no_force_rejected():
    """R3: lingma → boundless 不带 force 应拒绝。"""
    allowed, reason = check_transition("lingma", "boundless", force=False)
    assert not allowed
    assert "R3" in reason


def test_r3_gantong_to_boundless_force_allowed():
    """R3: gantong → boundless 带 force 应允许。"""
    allowed, reason = check_transition("gantong", "boundless", force=True)
    assert allowed
    assert "R3" in reason


def test_r3_lingma_to_boundless_force_allowed():
    """R3: lingma → boundless 带 force 应允许。"""
    allowed, reason = check_transition("lingma", "boundless", force=True)
    assert allowed


# =====================================================================
# check_transition — R4: boundless → 任意
# =====================================================================


def test_r4_boundless_downgrade_allowed():
    """R4: boundless → 任意模式（降级）随时允许。"""
    for dst in ("chat", "collaboration", "gantong", "lingma"):
        allowed, reason = check_transition("boundless", dst, force=False)
        assert allowed, f"boundless → {dst} 应被允许，实际: {reason}"
        assert "R4" in reason


def test_r4_boundless_to_chat_r5_applies():
    """boundless → chat 同时满足 R4 和 R5，R4 优先（降级语义）。"""
    allowed, reason = check_transition("boundless", "chat")
    assert allowed
    # R4 先命中（boundless → 任意）
    assert "R4" in reason


# =====================================================================
# check_transition — R5: 任意 → chat
# =====================================================================


def test_r5_any_to_chat_allowed():
    """R5: 任意 → chat 允许。"""
    for src in ("collaboration", "gantong", "lingma"):
        allowed, reason = check_transition(src, "chat", force=False)
        assert allowed, f"{src} → chat 应被允许，实际: {reason}"
        assert "R5" in reason


def test_r5_chat_to_chat_noop():
    """chat → chat 无变化。"""
    allowed, reason = check_transition("chat", "chat")
    assert allowed
    assert "未变化" in reason


# =====================================================================
# check_transition — R6: boundless 在非桌面白名单平台
# =====================================================================


def test_r6_boundless_on_android_rejected():
    """R6: boundless 在 Android 上直接拒绝。"""
    allowed, reason = check_transition("chat", "boundless", platform="android")
    assert not allowed
    assert "R6" in reason
    assert "android" in reason.lower()


def test_r6_boundless_on_ios_rejected():
    """R6: boundless 在 iOS 上直接拒绝。"""
    allowed, reason = check_transition("collaboration", "boundless", platform="ios")
    assert not allowed
    assert "R6" in reason


def test_r6_boundless_on_web_rejected():
    """R6: boundless 在 Web 上直接拒绝。"""
    allowed, reason = check_transition("chat", "boundless", platform="web")
    assert not allowed
    assert "R6" in reason


def test_r6_boundless_on_desktop_allowed():
    """R6: boundless 在桌面平台允许。"""
    for platform in ("desktop", "windows", "mac", "linux"):
        allowed, _ = check_transition("chat", "boundless", platform=platform, force=True)
        assert allowed, f"boundless 在 {platform} 上应被允许"


def test_r6_boundless_force_cannot_override_platform():
    """R6: 即使 force=True 也无法在非桌面平台切换到 boundless。"""
    allowed, reason = check_transition(
        "chat", "boundless", platform="android", force=True
    )
    assert not allowed
    assert "R6" in reason


def test_r6_r6_applies_before_r7():
    """R6 平台拦截应在 R7 锁定之前检查。"""
    allowed, reason = check_transition(
        "chat", "boundless", platform="android", locked=True
    )
    assert not allowed
    # R6 应先命中（平台拦截优先级高于锁定）
    assert "R6" in reason


# =====================================================================
# check_transition — R7: mode.locked=True
# =====================================================================


def test_r7_locked_blocks_normal_switch():
    """R7: locked=True 时普通切换应拒绝。"""
    allowed, reason = check_transition("chat", "collaboration", locked=True)
    assert not allowed
    assert "R7" in reason


def test_r7_locked_blocks_all_except_boundless_downgrade():
    """R7: locked=True 时除 boundless→降级外一律拒绝。"""
    # collaboration → gantong: 拒绝
    allowed, _ = check_transition("collaboration", "gantong", locked=True)
    assert not allowed

    # gantong → boundless: 拒绝（不是降级）
    allowed, _ = check_transition("gantong", "boundless", locked=True, force=True)
    assert not allowed

    # boundless → chat: 允许（降级豁免）
    allowed, reason = check_transition("boundless", "chat", locked=True)
    assert allowed
    assert "R7" in reason

    # boundless → collaboration: 允许（降级豁免）
    allowed, _ = check_transition("boundless", "collaboration", locked=True)
    assert allowed


def test_r7_locked_with_not_force():
    """R7: locked=True 时 force 也不能覆盖（除非 boundless 降级）。"""
    allowed, reason = check_transition(
        "chat", "collaboration", locked=True, force=True
    )
    assert not allowed
    assert "R7" in reason


def test_r7_not_locked_allows_switch():
    """locked=False 时正常切换不受 R7 影响。"""
    allowed, _ = check_transition("chat", "collaboration", locked=False)
    assert allowed


# =====================================================================
# 别名映射在 check_transition 中的表现
# =====================================================================


def test_alias_in_check_transition():
    """check_transition 应支持别名。"""
    # standard → boundless (collaboration → boundless)
    allowed, reason = check_transition("standard", "yolo", force=True)
    assert allowed

    # plan → gantong (chat → gantong)
    allowed, _ = check_transition("plan", "gantong")
    assert allowed


def test_alias_self_transition():
    """别名指向相同模式时无变化。"""
    allowed, reason = check_transition("standard", "collaboration")
    assert allowed
    assert "未变化" in reason


# =====================================================================
# 规则优先级测试
# =====================================================================


def test_r6_before_r7_before_r3():
    """R6（平台）> R7（锁定）> R3（跨级）的优先级。"""
    # Android + locked + force: R6 先拦截
    allowed, reason = check_transition(
        "gantong", "boundless", platform="android", locked=True, force=True
    )
    assert not allowed
    assert "R6" in reason

    # Linux + locked + force: R7 先拦截（locked 阻止非 boundless 降级切换）
    # 但 gantong → boundless 不是 boundless 降级，所以 R7 拦截
    allowed, reason = check_transition(
        "gantong", "boundless", platform="linux", locked=True, force=True
    )
    assert not allowed
    assert "R7" in reason

    # Linux + not locked + no force: R3 拦截（需要 force）
    allowed, reason = check_transition(
        "gantong", "boundless", platform="linux", locked=False, force=False
    )
    assert not allowed
    assert "R3" in reason


def test_r5_before_r3_when_chat_to_chat_via_alias():
    """别名解析后 src == dst 时直接返回无变化。"""
    # plan (chat) → chat (chat): 无变化
    allowed, reason = check_transition("plan", "chat")
    assert allowed
    assert "未变化" in reason


# =====================================================================
# switch_mode — 持久化测试
# =====================================================================


def test_switch_mode_persists_current_mode(tuan_home):
    """switch_mode 应写入 mode.current 配置。"""
    # 先切换到 collaboration
    ok, reason = switch_mode("collaboration", force=True)
    assert ok
    # 验证持久化
    from tuan_cli.config import Config
    cfg = Config()
    mode_data = cfg.get("mode", {}) or {}
    assert mode_data.get("current") == "collaboration"


def test_current_mode_reads_config(tuan_home):
    """current_mode 应从配置读取当前模式。"""
    # 默认 chat
    assert current_mode() == "chat"
    # 切换后读取
    ok, _ = switch_mode("collaboration", force=True)
    assert ok
    assert current_mode() == "collaboration"
    # 切换到 boundless (需要 force)
    ok, _ = switch_mode("boundless", force=True)
    assert ok
    assert current_mode() == "boundless"


def test_current_mode_resolves_alias(tuan_home):
    """current_mode 应解析别名。"""
    # 设置 mode.default = "standard" (历史字段), 同时清除 mode.current 以触发回退
    from tuan_cli.config import Config
    cfg = Config()
    cfg.set_user("mode.current", None)  # 清除新字段，让 mode.default 生效
    cfg.set_user("mode.default", "standard")
    assert current_mode() == "collaboration"


def test_switch_mode_rejects_invalid_target():
    """非法目标模式应抛 ValueError。"""
    with pytest.raises(ValueError):
        switch_mode("invalid_mode")


def test_switch_mode_rejects_when_locked(tuan_home):
    """locked 配置时 switch_mode 应拒绝非降级切换。"""
    from tuan_cli.config import Config
    cfg = Config()
    cfg.set_user("mode.locked", True)

    # 先切到 chat
    ok, _ = switch_mode("chat", force=True)
    assert ok

    # 锁定后切换到 collaboration 应拒绝
    ok, reason = switch_mode("collaboration", force=True)
    assert not ok
    assert "R7" in reason


def test_switch_mode_downgrade_from_boundless_when_locked(tuan_home):
    """locked 配置时 boundless → 降级 应允许。"""
    from tuan_cli.config import Config
    cfg = Config()

    # 先切换到 boundless (需要 force)
    ok, _ = switch_mode("boundless", force=True)
    assert ok

    # 锁定
    cfg.set_user("mode.locked", True)

    # boundless → chat 应允许（降级豁免）
    ok, reason = switch_mode("chat", force=True)
    assert ok
    assert "R7" in reason


# =====================================================================
# switch_mode — 事件发射测试
# =====================================================================


def test_switch_mode_emits_event(tuan_home):
    """switch_mode 应通过 kernel 发射 mode.changed 事件。"""
    kernel = MagicMock()
    kernel.get.return_value = None  # audit_store

    ok, reason = switch_mode("collaboration", force=True, kernel=kernel)
    assert ok

    # 验证事件发射
    assert kernel.emit.called
    call_args = kernel.emit.call_args
    assert call_args[0][0] == "mode.changed"
    payload = call_args[0][1]
    assert payload["from"] == "chat"
    assert payload["to"] == "collaboration"
    assert "ts" in payload


def test_switch_mode_emits_reject_no_event(tuan_home):
    """switch_mode 拒绝时不应发射事件。"""
    kernel = MagicMock()
    kernel.get.return_value = None

    ok, reason = switch_mode("boundless", force=False, kernel=kernel)
    assert not ok
    assert not kernel.emit.called


def test_switch_mode_logs_audit(tuan_home):
    """switch_mode 应写入审计日志。"""
    kernel = MagicMock()
    audit_store = MagicMock()
    kernel.get.return_value = audit_store

    ok, _ = switch_mode("collaboration", force=True, kernel=kernel)
    assert ok

    # 验证审计日志
    assert audit_store.log.called
    call_args = audit_store.log.call_args
    assert call_args[0][0] == "mode_switch"
    payload = call_args[0][1]
    assert payload["from"] == "chat"
    assert payload["to"] == "collaboration"


def test_switch_mode_audit_failure_no_crash(tuan_home):
    """审计日志失败不应导致 switch_mode 崩溃。"""
    kernel = MagicMock()
    audit_store = MagicMock()
    audit_store.log.side_effect = RuntimeError("审计写入失败")
    kernel.get.return_value = audit_store

    # 不应抛异常
    ok, reason = switch_mode("collaboration", force=True, kernel=kernel)
    assert ok


def test_switch_mode_event_failure_no_crash(tuan_home):
    """事件发射失败不应导致 switch_mode 崩溃。"""
    kernel = MagicMock()
    kernel.emit.side_effect = RuntimeError("事件发射失败")
    kernel.get.return_value = None

    ok, reason = switch_mode("collaboration", force=True, kernel=kernel)
    assert ok


# =====================================================================
# 综合场景测试
# =====================================================================


def test_full_switch_flow(tuan_home):
    """完整切换流程：chat → collaboration → lingma → boundless → chat。"""
    # chat → collaboration (R1)
    ok, _ = switch_mode("collaboration", force=True)
    assert ok
    assert current_mode() == "collaboration"

    # collaboration → lingma (R2, needs force)
    ok, _ = switch_mode("lingma", force=True)
    assert ok
    assert current_mode() == "lingma"

    # lingma → boundless (R3, needs force)
    ok, _ = switch_mode("boundless", force=True)
    assert ok
    assert current_mode() == "boundless"

    # boundless → chat (R4 downgrade)
    ok, _ = switch_mode("chat", force=False)
    assert ok
    assert current_mode() == "chat"


def test_switch_with_alias(tuan_home):
    """通过别名切换模式。"""
    # plan (chat) → standard (collaboration)
    ok, _ = switch_mode("standard", force=True)
    assert ok
    assert current_mode() == "collaboration"

    # standard → yolo (boundless)
    ok, _ = switch_mode("yolo", force=True)
    assert ok
    assert current_mode() == "boundless"

    # yolo → plan (chat)
    ok, _ = switch_mode("plan", force=False)
    assert ok
    assert current_mode() == "chat"


def test_platform_switch_rejection(tuan_home):
    """非桌面平台切换到 boundless 应被拒绝。"""
    ok, reason = switch_mode("boundless", platform="android", force=True)
    assert not ok
    assert "R6" in reason


def test_boundless_downgrade_always_allowed():
    """boundless → 任意模式始终允许（即使 locked）。"""
    for dst in ("chat", "collaboration", "gantong", "lingma"):
        allowed, _ = check_transition("boundless", dst, locked=True, force=False)
        assert allowed, f"boundless → {dst} 应允许降级"
