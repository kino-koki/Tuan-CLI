"""本轮深度修复：把「出网 + 凭据」准备层收成**所有执行分支共用的单一出口**。

**实测缺口（先复现再修，全部量过）**

上一轮（B2 收尾）把逐命令域名强绑定接到了 ``_execute_backend`` 的
**local 分支**。但 ``_execute_backend`` 还有三条分支，实测逐条核对：

===============  ============  ============  ============  ================
分支              EgressGuard   claim 检查    代理 env      last_egress
                  (凭据脱敏)                   注入          可观测
===============  ============  ============  ============  ================
local            有            有（裁决层）  有            有
landlock/docker  无            只传元数据    无            无
/ seatbelt
jobobject        无            无            无            无
(syscall)
copy_diff_apply  随下游        随下游        随下游        随下游
===============  ============  ============  ============  ================

也就是说：**安全等级更高的强后端路径，反而完全没有上一轮刚补的防护**。
更具体的三处：

1. ``SandboxProfile.allowed_domains`` 在整个 ``sandbox_provider.py`` 里
   **只出现 1 次**（就是 dataclass 字段定义），没有任何后端消费它。
   上一轮文档写「只是元数据」属实，但没说**因此 strict claim 在强后端下
   完全失效** —— 把缺口当成边界写，口径偏乐观。
2. ``_run_provider`` 调 ``provider.run(...)`` 不传 ``env``，走的是
   ``sanitize_env``（把敏感键置空串），**不是** EgressGuard 的
   sentinel + ``CredentialBroker`` 注入链路。
3. **最严重**：``_run_syscall`` 调 ``run_syscall_sandboxed``，该函数
   **根本没有 env 参数**，所有 ``Popen`` / ``run_with_tree_kill`` /
   ``os.execvp`` 一律继承父进程完整环境 —— Windows Job Object / Linux
   seccomp 路径上，真实密钥原样进入子进程，连置空都没有。

本模块提供 :func:`plan_egress`：给定裁决、后端、策略、基础环境，产出
一份 :class:`EgressPlan`，由 ``SandboxManager`` 在**所有分支之前**统一
调用。核心是两条可执行契约：

- **凭据**：任何后端都拿 ``plan.env``（EgressGuard 脱敏 / sentinel）。
  强后端不再继承父进程裸环境。
- **逐命令域名**：若 ``claim.strict`` 且 ``claim.source == "tool_args"``
  （真正逐命令声明，而非全局白名单回落），则**必须**有出网代理能力；
  强后端没有域名级过滤、且 netns / seatbelt 隔离下宿主机回环代理不可达，
  默认 **fail-closed 拒绝**，不假装强绑定生效。

``source`` 这个字段是上一轮 ``claim_from_args`` 刻意标注、但当时没被
消费的：它在这里第一次真正决定行为。全局白名单回落（``global_policy``）
沿用既有文本层语义，不因本轮改动让配了全局白名单 + 强后端的部署
突然全部拒绝 —— 精确区分，不大范围破坏既有行为。

**刻意不宣称**：本模块不提供域名级 OS 过滤（那不存在），也不把代理
塞进 netns 隔离的强后端（连不上）。做不到就拒绝，这是本轮的全部立场。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional

from .egress import EgressGuard
from .egress_allowlist import NetworkClaim, claim_from_verdict

# 有 OS 级网络隔离、但**没有域名级过滤**能力的后端。
STRONG_BACKENDS = frozenset({
    "landlock", "bwrap", "docker", "seatbelt", "jobobject", "syscall",
    "sandbox-exec", "windows-job-object",
})
# 本地裸跑后端：唯一能可靠连到宿主机回环代理的路径。
LOCAL_BACKENDS = frozenset({"local", "", "auto", "fallback", "none"})

MODE_NONE = "none"                       # 无 strict claim，不涉出网强绑定
MODE_TEXT_ONLY = "text_only"             # 文本层强绑定（可绕过，undetectable 标记）
MODE_PROXY = "proxy"                     # 出网路径强绑定（本地回环代理）
MODE_DENY = "deny"                       # EgressGuard 本身拒绝
MODE_UNPROVABLE = "deny_unprovable"      # 强后端无法证明逐命令域名合规
MODE_DEGRADED = "text_only_degraded"     # 显式降级逃生口，harden status 告警

DEFAULT_STRONG_POLICY = "deny"           # deny | metadata_only
STRONG_POLICY_KEY = "strict_claim_strong_backend"


@dataclass
class EgressPlan:
    """一次执行的统一出网/凭据计划。``env`` 可变：代理启动后由 manager 注入。"""

    mode: str
    backend: str
    reason: str
    claim: NetworkClaim
    env: Dict[str, str] = field(default_factory=dict)
    wants_proxy: bool = False
    proxy_url: str = ""
    guard_audit: Dict[str, Any] = field(default_factory=dict)
    degraded: bool = False
    # EgressGuard 创建的凭据代理对象；代理转发时需要它来还原 sentinel。
    # 只在进程内内存，绝不进 to_audit_dict()。
    broker: Any = None

    @property
    def allowed(self) -> bool:
        return self.mode not in (MODE_DENY, MODE_UNPROVABLE)

    @property
    def enforcement(self) -> str:
        """给 ``last_egress`` / 审计用的稳定字符串，绝不写「已强隔离」这类谎话。"""
        return {
            MODE_NONE: "none",
            MODE_TEXT_ONLY: "text-layer-only",
            MODE_PROXY: "egress-proxy-host-validation",
            MODE_DENY: "guard-denied",
            MODE_UNPROVABLE: "refused-unprovable-domain-compliance",
            MODE_DEGRADED: "text-layer-only-explicit-downgrade",
        }[self.mode]

    def to_audit_dict(self) -> Dict[str, Any]:
        return {
            # ``allowed`` 是 B2 首轮 EgressDecision.to_audit_dict() 的既有
            # 可观测契约（test_b2_boundaries / 运维脚本都读它）。统一出口
            # 必须保留，否则「闸门锁紧了，监控却看不到 allowed=false」。
            "allowed": self.allowed,
            "mode": self.mode,
            "enforcement": self.enforcement,
            "backend": self.backend,
            "reason": self.reason,
            "claim": self.claim.to_dict(),
            "proxy_enabled": self.wants_proxy,
            "degraded": self.degraded,
            "guard": dict(self.guard_audit),
        }


def _resource(policy: Any) -> Dict[str, Any]:
    r = policy.get("resource", {}) if isinstance(policy, Mapping) else {}
    return r if isinstance(r, dict) else {}


def plan_egress(verdict: Any, backend: str, policy: Any,
                base_env: Mapping[str, str]) -> EgressPlan:
    """为一次执行生成统一计划。纯决策，不启动任何东西。

    ``base_env`` 显式传入（通常是 ``os.environ``），便于测试与回放；
    不偷偷读全局环境。异常一律收敛成 :data:`MODE_UNPROVABLE` 而非放行。
    """
    normalized_backend = (backend or "").strip().lower()
    claim = claim_from_verdict(verdict)
    res = _resource(policy)
    proxy_switch = res.get("egress_proxy_enabled", False) is True

    try:
        decision = EgressGuard.from_policy(policy).prepare(
            verdict, normalized_backend, dict(base_env))
    except Exception as exc:  # noqa: BLE001 - 闸门异常必须闭合
        return EgressPlan(
            MODE_UNPROVABLE, normalized_backend,
            f"EgressGuard 异常 fail-closed: {type(exc).__name__}",
            claim, env={}, guard_audit={"error": type(exc).__name__})

    env = dict(decision.env)
    audit = decision.to_audit_dict()
    if not decision.allowed:
        return EgressPlan(MODE_DENY, normalized_backend, decision.reason,
                          claim, env=env, guard_audit=audit,
                          broker=decision.broker)

    if not claim.strict:
        return EgressPlan(MODE_NONE, normalized_backend,
                          "无逐命令域名声明, 不涉强绑定", claim,
                          env=env, guard_audit=audit)

    is_per_command = claim.source == "tool_args"
    is_strong = normalized_backend in STRONG_BACKENDS
    is_local = normalized_backend in LOCAL_BACKENDS

    # 真正逐命令声明 + 本地后端 + 代理开启 → 出网路径强绑定（上一轮已实现）
    if is_per_command and is_local and proxy_switch:
        return EgressPlan(MODE_PROXY, normalized_backend,
                          "逐命令域名声明, 由本地回环代理在主机层强绑定",
                          claim, env=env, wants_proxy=True, guard_audit=audit,
                          broker=decision.broker)

    # 真正逐命令声明 + 强后端 → 默认拒绝；显式降级才放行并留痕
    if is_per_command and is_strong:
        strong_mode = res.get(STRONG_POLICY_KEY, DEFAULT_STRONG_POLICY)
        if strong_mode == "metadata_only":
            return EgressPlan(
                MODE_DEGRADED, normalized_backend,
                "显式降级: 强后端无域名级过滤, 逐命令声明仅作元数据/文本层",
                claim, env=env, guard_audit=audit, degraded=True)
        return EgressPlan(
            MODE_UNPROVABLE, normalized_backend,
            "强后端无域名级过滤且回环代理在 netns/seatbelt 隔离下不可达, "
            "无法证明逐命令出网合规 (可配 "
            "sandbox.resource.strict_claim_strong_backend=metadata_only 显式降级)",
            claim, env=env, guard_audit=audit)

    # 其余：全局白名单回落 / 本地但代理未开启 → 沿用既有文本层语义。
    # 上一轮已如实标注 undetectable 是标记不是证明，这里不重复放宽也不假装更强。
    return EgressPlan(
        MODE_TEXT_ONLY, normalized_backend,
        "文本层强绑定 (source=%s, 代理未启用或非本地后端); "
        "undetectable 仅标记不证明" % claim.source,
        claim, env=env, guard_audit=audit)


def plan_is_consistent_with_verdict(plan: EgressPlan, verdict: Any) -> bool:
    """派生一致性校验：plan 的 claim 必须真的来自传入 verdict。

    防止有人改了状态定义或绕开 ``claim_from_verdict`` 造成「审计说一套、
    执行做一套」—— 前几轮反复抓的就是这类撕裂。
    """
    return plan.claim.to_dict() == claim_from_verdict(verdict).to_dict()
