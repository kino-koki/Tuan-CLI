"""统一命令守卫 —— 供 verify / reflect / code_edit 等非 run_shell 执行路径共用。

这些路径没有完整 ToolContext（无白名单 / trust_level / yolo 语义），但同样是
「模型影响下执行的命令」，若直接 subprocess 就绕过了统一安全层。本守卫收敛
确定性最强的三层滤网，与 tools/shell.py 的 _pre_exec_guard 同源但不依赖 ctx：

1) 硬红线   —— 文件系统/OS 级毁灭操作，永不自动执行（fail-closed，YOLO 不可绕）；
2) 网络出口 —— NetworkGuard 权威判定：deny 拒绝；confirm 且无确认通道 → 拒绝；
3) 审计     —— 拦截/放行事件统一写入 SecurityEventBus（与 shell 护栏同一条审计流）。

fail-closed：任一环节异常 → 拒绝，绝不静默放行（与 SECURITY.md 设计原则一致）。
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable, Optional

log = logging.getLogger(__name__)


def guard_command(
    command: str,
    *,
    kernel: Any = None,
    confirm: Optional[Callable[[str], bool]] = None,
    home: Optional[str] = None,
) -> Optional[str]:
    """判定命令是否可执行。

    Returns:
        None = 放行；str = 拦截原因文本（调用方直接呈现给上层/模型）。
    """
    cmd = str(command or "")
    if not cmd.strip():
        return None

    # 1) 硬红线：与 shell 护栏 step1 同源，永不自动执行
    try:
        from ..ext.safety_engine import is_hard_redline
        if is_hard_redline(cmd):
            _emit("security.command.blocked", cmd,
                  {"reason": "hard_redline", "severity": "critical"})
            return f"[已拦截] 命中致命操作红线, 禁止自动执行: {cmd}"
    except Exception as exc:  # noqa: BLE001
        log.error("命令守卫: 硬红线判定异常, fail-closed 拒绝: %s", exc)
        return f"[已拦截] 安全引擎不可用, 安全降级拒绝: {cmd}"

    # 2) 网络出口门控（外泄 / 远程执行 / 敏感域名）
    try:
        from ..core.network_guard import get_network_guard
        decision = get_network_guard().check(cmd)
        if decision.action == "deny":
            reasons = "; ".join((getattr(decision, "reasons", None) or [])[:5])
            domains = ", ".join(getattr(decision, "detected_domains", None) or []) or "(无)"
            _emit("security.command.blocked", cmd,
                  {"reason": "network_guard", "severity": "high"})
            return (f"[已拦截] 网络出口门控: {cmd}\n"
                    f"原因: {reasons}\n检测到的域名: {domains}")
        if decision.action == "confirm":
            if confirm is None:
                _emit("security.command.blocked", cmd,
                      {"reason": "network_guard_no_channel", "severity": "high"})
                return f"[已拦截] 网络出口门控: 无确认通道, 拒绝网络操作: {cmd}"
            try:
                if not confirm(f"⚠️ 网络出口门控检测到中风险操作:\n{cmd}\n确认执行? (仅本次生效)"):
                    return f"[已拦截] 用户拒绝网络操作: {cmd}"
            except Exception as exc:  # noqa: BLE001
                log.error("命令守卫: 网络确认通道异常, fail-closed 拒绝: %s", exc)
                return f"[已拦截] 网络确认通道异常, 安全降级拒绝: {cmd}"
    except Exception as exc:  # noqa: BLE001
        log.error("命令守卫: 网络门控异常, fail-closed 拒绝: %s", exc)
        return f"[已拦截] 网络出口门控不可用, 安全降级拒绝: {cmd}"

    _emit("security.command.allowed", cmd, {"severity": "info"})
    return None


def _emit(event_type: str, command: str, payload: dict) -> None:
    """审计事件（尽力而为，失败不反作用于裁决）。"""
    try:
        from ..core.security_bus import SecurityEvent, get_security_bus
        get_security_bus().emit(SecurityEvent(
            event_type=event_type,
            timestamp=time.time(),
            payload={"command": command[:300], **payload},
            source="command_guard",
            severity=payload.get("severity", "info"),
        ))
    except Exception:  # noqa: BLE001
        pass
