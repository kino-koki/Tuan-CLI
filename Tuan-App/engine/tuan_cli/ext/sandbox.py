"""sandbox.py —— 分层执行域 (L0 宿主 / L1 进程沙箱 / L2 微 VM) 与决策引擎。

定位 (关键, 避免做成"又一个重功能"):
  - **不是**给每条命令都开沙箱 —— 低风险命令宿主直跑 (零开销);
  - **不是** Docker (要 daemon、攻击面大), **不是**完整 KVM (启动慢、占资源);
  - L1 = bubblewrap + 可选 Landlock/seccomp, 进程级隔离, 秒级、几乎无感;
  - L2 = gVisor runsc (用户态内核, 不需 KVM, Linux 通用), 内核级隔离;
  - L3 (完整 VM + 快照回滚) 预留, 处理不可信仓库/CI 红队场景。

分级触发 (由 risk_vector.RiskVector.composite() 驱动, 用户无感):
    0-2   L0 宿主直跑
    2-4   L0 宿主直跑 + 审计
    4-6   L1 (若可用) / 需确认
    6-8   L2 (若可用) / 需确认
    >=8   默认拒绝 (硬红线由安全引擎独立拦截, 不在此层)

可插拔后端: `available()` 探测运行时是否在 PATH; 不可用时**自动降级**
(L2 不可用 → L1 → L0 + 需确认), 绝不因为沙箱缺失而拒绝执行低风险命令。
开关: ``security.sandbox.enabled`` (默认 False, 由 `tuan setup` 向导开启)。
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, Dict, List, Optional


class SandboxTier(IntEnum):
    HOST = 0        # L0 宿主直跑
    L1_PROCESS = 1  # 进程级 (bwrap)
    L2_MICROVM = 2  # 微 VM (gVisor runsc)
    L3_FULL = 3     # 完整 VM + 快照 (预留)


# ---------------------------------------------------------------- 后端

class SandboxBackend:
    """沙箱后端抽象: 探测可用性, 并把命令包裹成隔离执行形式。"""
    name = "none"
    tier = SandboxTier.HOST

    def available(self) -> bool:
        return False

    def wrap(self, command: str, profile: "SandboxProfile") -> str:
        """返回包裹后的命令字符串 (在隔离域内执行 command)。"""
        return command

    def describe(self) -> str:
        return self.name


@dataclass
class SandboxProfile:
    """沙箱资源配置 (来自 security.sandbox 配置段)。"""
    cpu: int = 2
    memory_mb: int = 512
    pids: int = 200
    network: str = "deny"                       # deny | allowlist
    network_allow: List[str] = field(default_factory=list)
    readonly_paths: List[str] = field(default_factory=lambda: ["/usr", "/lib", "/bin", "/sbin"])
    forbidden_paths: List[str] = field(default_factory=lambda: ["~/.ssh", "~/.aws", "~/.config/gcloud"])
    idle_timeout: int = 30
    max_lifetime: int = 300

    @classmethod
    def from_config(cls, cfg: Any) -> "SandboxProfile":
        def g(key, default):
            try:
                v = cfg.get(f"security.sandbox.{key}", default)
                return default if v is None else v
            except Exception:  # noqa: BLE001
                return default
        return cls(
            cpu=int(g("cpu", 2)), memory_mb=int(g("memory_mb", 512)),
            pids=int(g("pids", 200)), network=str(g("network", "deny")),
            network_allow=list(g("network_allow", []) or []),
            readonly_paths=list(g("readonly_paths", ["/usr", "/lib", "/bin", "/sbin"]) or []),
            forbidden_paths=list(g("forbidden_paths", ["~/.ssh", "~/.aws", "~/.config/gcloud"]) or []),
            idle_timeout=int(g("idle_timeout", 30)), max_lifetime=int(g("max_lifetime", 300)),
        )


class BwrapBackend(SandboxBackend):
    """L1: bubblewrap —— 进程级隔离 (unshare pid/net), Linux 通用、秒级启动。"""
    name = "bwrap"
    tier = SandboxTier.L1_PROCESS

    def available(self) -> bool:
        return bool(shutil.which("bwrap"))

    def wrap(self, command: str, profile: SandboxProfile) -> str:
        ro = " ".join(f"--ro-bind {p} {p}" for p in profile.readonly_paths)
        net = "" if profile.network == "allowlist" else "--unshare-net"
        return (
            f"bwrap {ro} --tmpfs /tmp --dev /proc --unshare-pid {net} "
            f"--die-with-parent --new-session /bin/sh -c {command}"
        )


class RunscBackend(SandboxBackend):
    """L2: gVisor runsc —— 用户态内核, 强隔离, 不需要 KVM。"""
    name = "runsc"
    tier = SandboxTier.L2_MICROVM

    def available(self) -> bool:
        return bool(shutil.which("runsc"))

    def wrap(self, command: str, profile: SandboxProfile) -> str:
        net = "none" if profile.network == "deny" else "sandbox"
        return f"runsc --rootless --network={net} do /bin/sh -c {command}"


class NoopBackend(SandboxBackend):
    """无沙箱可用: 宿主直跑 (配合审批/审计, 绝不静默假装隔离了)。"""
    name = "host"
    tier = SandboxTier.HOST


_BACKENDS_BY_TIER: Dict[int, List[SandboxBackend]] = {
    SandboxTier.L1_PROCESS: [BwrapBackend()],
    SandboxTier.L2_MICROVM: [RunscBackend(), BwrapBackend()],  # L2 缺 runsc 时降级 L1
    SandboxTier.HOST: [NoopBackend()],
}


def pick_backend(tier: SandboxTier, profile: Optional[SandboxProfile] = None) -> SandboxBackend:
    """按档位挑一个**可用**的后端; 都不可用则降级返回宿主直跑。"""
    for b in _BACKENDS_BY_TIER.get(int(tier), [NoopBackend()]):
        if b.available():
            return b
    return NoopBackend()


def sandbox_status() -> Dict[str, Any]:
    """各后端可用性 (供 `tuan safe vm-status` 与 Web 面板展示)。"""
    return {
        "backends": [{"name": b.name, "tier": int(b.tier), "available": b.available()}
                     for b in (BwrapBackend(), RunscBackend())],
        "recommended": "L1(bwrap) 已就绪" if BwrapBackend().available() else
                       ("L2(gVisor) 已就绪" if RunscBackend().available() else
                        "未检测到可用沙箱运行时 (将回退审批模式)"),
    }


# ---------------------------------------------------------------- 决策引擎

@dataclass
class ExecutionDecision:
    tier: SandboxTier
    action: str                     # execute | execute_sandboxed | ask | deny
    reason: str
    backend: Optional[str] = None   # 实际选中的后端名 (None=宿主)


def decide_execution_tier(risk: Any, config: Any = None,
                          *, force_deny: bool = False) -> ExecutionDecision:
    """按风险向量决定执行域。

    risk: risk_vector.RiskVector (或任何有 composite()/level() 的对象)
    force_deny: 安全引擎判 hard redline 时置 True —— 沙箱也救不了, 直接拒绝。
    """
    profile = SandboxProfile.from_config(config)
    enabled = False
    if config is not None:
        try:
            enabled = bool(config.get("security.sandbox.enabled", False))
        except Exception:  # noqa: BLE001
            enabled = False
    score = float(risk.composite())

    if force_deny or score >= 8:
        return ExecutionDecision(SandboxTier.HOST, "deny",
                                 f"极高风险 (score={score}), 默认拒绝; 硬红线由安全引擎独立拦截")

    def _sandboxed(tier: SandboxTier, why: str) -> ExecutionDecision:
        if not enabled:
            return ExecutionDecision(SandboxTier.HOST, "ask",
                                     why + " (未启用隔离, 需人工确认)")
        b = pick_backend(tier, profile)
        if b.tier == SandboxTier.HOST:
            return ExecutionDecision(SandboxTier.HOST, "ask",
                                     why + " (无可用沙箱运行时, 需人工确认)")
        return ExecutionDecision(tier, "execute_sandboxed", why, backend=b.name)

    if score >= 6:
        return _sandboxed(SandboxTier.L2_MICROVM,
                          f"高风险 (score={score}), 自动路由到微 VM")
    if score >= 4:
        return _sandboxed(SandboxTier.L1_PROCESS,
                          f"中风险 (score={score}), 建议进程级沙箱")
    if enabled and pick_backend(SandboxTier.L1_PROCESS).available() and score >= 2:
        return ExecutionDecision(SandboxTier.L1_PROCESS, "execute_sandboxed",
                                 f"低风险 (score={score}), 沙箱可用则统一隔离")
    return ExecutionDecision(SandboxTier.HOST, "execute", f"安全 (score={score}), 宿主直跑")


__all__ = ["SandboxTier", "SandboxProfile", "SandboxBackend", "BwrapBackend",
           "RunscBackend", "NoopBackend", "pick_backend", "sandbox_status",
           "ExecutionDecision", "decide_execution_tier"]
