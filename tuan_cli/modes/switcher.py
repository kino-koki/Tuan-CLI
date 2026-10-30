"""五模式切换状态机 —— R1–R7 切换规则。

纯函数 check_transition 可独立测试；switch_mode 执行切换 + 发事件 + 落审计。

规则表（§3.4）：
    R1  chat → 任意：需用户显式切换，禁止自动升级权限
    R2  collaboration → lingma/gantong：只提示，不自动切
    R3  gantong/lingma → boundless：必须风险披露 + 二次确认（force=False 时拒绝）
    R4  boundless → 任意：随时降级，同会话内立即收紧
    R5  任意 → chat：允许，立即收回除"对话 + 记忆沙箱 + TTS"外的一切能力
    R6  boundless 在非桌面白名单平台：直接拒绝，不给确认机会
    R7  mode.locked=True：除 boundless→降级外一律拒绝
"""

from __future__ import annotations

import time
from typing import Any, Optional, Tuple

from .registry import (
    DESKTOP_PLATFORMS,
    MODE_REGISTRY,
    MODE_NAMES,
    get_mode_meta,
    level_order,
    resolve_mode_id,
)


def _is_downgrade(src_id: str, dst_id: str) -> bool:
    """判断目标模式是否为降级（权限等级降低）。"""
    src_level = MODE_REGISTRY[src_id]["level"]
    dst_level = MODE_REGISTRY[dst_id]["level"]
    return level_order(dst_level) < level_order(src_level)


def check_transition(
    src: str,
    dst: str,
    *,
    platform: str = "desktop",
    locked: bool = False,
    force: bool = False,
) -> Tuple[bool, str]:
    """检查模式切换是否允许。返回 (allowed, reason)。

    参数:
        src: 当前模式 ID（支持别名）。
        dst: 目标模式 ID（支持别名）。
        platform: 当前平台标识。
        locked: mode.locked 配置值。
        force: 是否强制切换（跳过二次确认）。

    返回:
        (allowed, reason) 二元组。
    """
    # ---- 解析别名 ----
    src_id = resolve_mode_id(src)
    dst_id = resolve_mode_id(dst)

    # ---- 无变化 → 直接放行 ----
    if src_id == dst_id:
        return (True, "模式未变化")

    # ---- R6: boundless 在非桌面白名单平台直接拒绝 ----
    if dst_id == "boundless" and platform.lower() not in DESKTOP_PLATFORMS:
        return (
            False,
            f"[R6] 无界模式仅允许在桌面平台启用，当前平台: {platform!r}。"
            f"无界为 YOLO 同级高权限模式，移动端/Web 端物理禁用。",
        )

    # ---- R7: mode.locked=True 除 boundless→降级外一律拒绝 ----
    if locked:
        if src_id == "boundless" and _is_downgrade(src_id, dst_id):
            # boundless → 降级 豁免锁定
            return (True, f"[R7] 模式已锁定，但无界→降级({MODE_NAMES.get(dst_id, dst_id)}) 始终允许。")
        return (
            False,
            f"[R7] 模式已锁定（mode.locked=True），除无界→降级外所有切换均被拒绝。"
            f"请先解除锁定（tuan config set mode.locked false）。",
        )

    # ---- R1-ext: chat → boundless (L0→L4 跨级跳升) 需 force 确认 ----
    if src_id == "chat" and dst_id == "boundless" and not force:
        return (
            False,
            "[R1] 闲聊 → 无界 属于跨级跳升 (L0→L4)，必须使用 --force 确认执行。",
        )

    # ---- R3: gantong/lingma → boundless 必须二次确认 ----
    if src_id in ("gantong", "lingma") and dst_id == "boundless":
        if not force:
            return (
                False,
                f"[R3] {MODE_NAMES.get(src_id, src_id)} → 无界 属于跨级升级，"
                f"必须风险披露 + 二次确认。请使用 --force 参数确认执行。",
            )
        return (
            True,
            f"[R3] {MODE_NAMES.get(src_id, src_id)} → 无界 已确认执行（force=True）。",
        )

    # ---- R2: collaboration → lingma/gantong 只提示，不自动切 ----
    if src_id == "collaboration" and dst_id in ("lingma", "gantong"):
        if not force:
            return (
                False,
                f"[R2] 协同 → {MODE_NAMES.get(dst_id, dst_id)} 需要用户确认后切换，"
                f"系统不会自动切换。请使用 --force 参数确认执行。",
            )
        return (
            True,
            f"[R2] 协同 → {MODE_NAMES.get(dst_id, dst_id)} 已确认执行（force=True）。",
        )

    # ---- R1: chat → 任意（非 chat 目标）用户显式切换 ----
    if src_id == "chat" and dst_id != "chat":
        return (
            True,
            f"[R1] 闲聊 → {MODE_NAMES.get(dst_id, dst_id)} 用户显式切换，已授权。"
            f"注意：禁止系统自动升级权限，仅允许用户手动触发。",
        )

    # ---- R4: boundless → 任意（降级）随时允许 ----
    if src_id == "boundless":
        return (
            True,
            f"[R4] 无界 → {MODE_NAMES.get(dst_id, dst_id)} 降级，权限立即收紧。",
        )

    # ---- R5: 任意 → chat 允许，立即收回能力 ----
    if dst_id == "chat":
        return (
            True,
            f"[R5] {MODE_NAMES.get(src_id, src_id)} → 闲聊 允许，"
            f"立即收回除对话 + 记忆沙箱 + TTS 外的一切能力。",
        )

    # ---- 其他组合（如 collaboration→boundless, gantong→collaboration 等）----
    return (True, f"模式切换: {MODE_NAMES.get(src_id, src_id)} → {MODE_NAMES.get(dst_id, dst_id)}，已允许。")


def current_mode() -> str:
    """读取当前模式 ID（从配置读取，支持别名解析）。"""
    from tuan_cli.config import Config

    cfg = Config()
    mode_data = cfg.get("mode", {}) or {}
    raw = mode_data.get("current") or mode_data.get("default") or "chat"
    meta = get_mode_meta(str(raw))
    return str(meta["id"])


def switch_mode(
    target: str,
    *,
    force: bool = False,
    platform: str = "desktop",
    kernel: Any = None,
) -> Tuple[bool, str]:
    """执行模式切换（含校验 + 持久化 + 事件 + 审计）。

    参数:
        target: 目标模式 ID 或别名。
        force: 强制切换（跳过 R2/R3 的二次确认）。
        platform: 当前平台标识。
        kernel: 可选的内核实例，用于事件发射和审计。为 None 时跳过事件/审计。

    返回:
        (success, reason) 二元组。
    """
    from tuan_cli.config import Config

    # ---- 解析目标模式 ----
    target_meta = get_mode_meta(target)
    target_id = target_meta["id"]

    # ---- 读取配置 ----
    cfg = Config()
    mode_data = cfg.get("mode", {}) or {}
    raw_current = mode_data.get("current") or mode_data.get("default") or "chat"
    src_id = get_mode_meta(str(raw_current))["id"]
    locked = bool(mode_data.get("locked", False))

    # ---- 校验切换规则 ----
    allowed, reason = check_transition(
        src_id, target_id, platform=platform, locked=locked, force=force
    )
    if not allowed:
        return (False, reason)

    # ---- 持久化切换 ----
    cfg.set_user("mode.current", target_id)

    # ---- 事件发射（best-effort） ----
    if kernel is not None:
        try:
            kernel.emit("mode.changed", {
                "from": src_id,
                "to": target_id,
                "reason": reason,
                "ts": time.time(),
                "force": force,
                "platform": platform,
            })
        except Exception:
            pass

    # ---- 审计日志（best-effort） ----
    if kernel is not None:
        try:
            store = kernel.get("audit_store")
            if store is not None:
                store.log("mode_switch", {
                    "from": src_id,
                    "to": target_id,
                    "reason": reason,
                    "force": force,
                    "platform": platform,
                })
        except Exception:
            pass

    return (True, reason)
