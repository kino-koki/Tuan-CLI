"""SandboxManager: 4 层滤网流水线的统一入口。

职责:
  - 按配置构建或复用一条 SandboxFilterChain (L0 意图 → L1 信任 → L2 资源 → L3 强隔离)
  - assess_tool / assess_command: 把工具或命令归一化成 Payload, 跑完整滤网, 返回裁决
  - execute_isolated: 当裁决要求隔离(isolate)时, 用选中的后端真正隔离执行
  - 全工具统一入口(在 ToolExecutor 层), 杜绝"绕道文件工具/run_tests 绕过 shell 护栏"的侧门

对 run_shell: Shell 内部已有完整的确认/红线链; 本层只做"是否需强隔离 + 隔离执行"的选路,
不重复它的确认 —— 因此 confirm 语义由调用方(Shell 或 ToolExecutor)按现有通道消费。
"""
from __future__ import annotations

import logging
import os
import subprocess
import time as _time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .verdict import Action, Payload, Verdict, SEV
from .filters import SandboxFilterChain, build_chain
from .backends import pick_backend
from .egress_allowlist import (
    claim_from_args, claim_from_verdict, claim_to_verdict_extra,
    evaluate_claim, profile_domains,
)
from .egress_proxy import EgressProxy
from .egress_plan import (
    MODE_DEGRADED, MODE_PROXY, MODE_UNPROVABLE, plan_egress,
    plan_is_consistent_with_verdict,
)

log = logging.getLogger(__name__)

DEFAULT_POLICY: Dict[str, Any] = {
    "enabled": True,
    "backend": "auto",                 # auto | local | docker | landlock | seatbelt | jobobject
    "enforce_required": True,          # 无强后端时 fail-closed 拒绝; 与 config/defaults.py 一致, 禁止静默降级裸执行
    "deny_unknown_shell": False,
    "resource": {
        "deny_network_by_default": False,
        "max_memory_mb": 0,
        "max_timeout": 0,
        "cpu_rate_pct": 50,
        "active_process_limit": 16,
        "kill_timeout_seconds": 5.0,
        "isolate_copy_threshold": "high",   # 高危以上走 copy-diff-apply
        # B2: 子进程出网边界。两项默认开是**修复实测 fail-open**，不是放宽：
        # local 后端禁网裁决以前会裸跑、父进程真实凭据以前原样进子进程。
        "egress_credential_masking": True,
        "egress_block_local_when_denied": True,
        "egress_proxy_enabled": False,
        # 本轮: 真正逐命令域名声明 + 强后端（无域名级过滤、回环代理不可达）
        # 默认拒绝执行，不假装强绑定生效。metadata_only 是显式降级逃生口，
        # harden status 会报安全降级。
        "strict_claim_strong_backend": "deny",
    },
}

# 工具名 → 方法类别 (供信任/计划模式滤网判断"只读")
_TOOL_METHOD = {
    "run_shell": "shell",
    "run_tests": "code", "git_status": "code", "git_diff": "code",
    "git_log": "code", "git_stash": "code", "codebase_map": "code",
    "write_file": "write", "edit_file": "write", "str_replace": "write",
    "delete_file": "write", "delete_dir": "write", "move_file": "write",
    "read_file": "read", "search_files": "read", "list_dir": "read", "glob": "read",
}

# 可执行/敏感文本字段 (从工具参数里抽出来喂意图滤网)
_EXEC_FIELDS = (
    "command", "code", "sql", "script", "query", "content", "text", "input", "url", "shell",
)


@dataclass
class SandboxExecResult:
    """隔离执行返回。enforced=False 表示实际回落到非隔离执行。"""

    stdout: str = ""
    stderr: str = ""
    returncode: int = 0
    ignored: bool = False        # 隔离执行不可用/被跳过 → 调用方维持原执行
    backend: str = ""
    enforced: bool = False
    error: str = ""
    # E7: copy-diff-apply 结果的可观测字段 (全部有默认值, 不破坏既有构造)
    workspace_mode: str = "direct"
    applied: bool = False
    applied_files: List[str] = field(default_factory=list)
    diff_preview: Optional[Dict[str, Any]] = None
    confirm_reason: str = ""

    def as_shell_text(self) -> str:
        parts = []
        if self.returncode == -1:
            parts.append("exit=-1 (被终止)")
        if self.stdout:
            parts.append(self.stdout.rstrip())
        if self.stderr:
            parts.append(self.stderr.rstrip())
        return "\n".join(parts)


class SandboxManager:
    """统一 4 层滤网入口。"""

    def __init__(self, policy: Optional[Dict[str, Any]] = None,
                 auditor: Any = None, bus: Any = None) -> None:
        self.policy = _merge_policy(policy or {})
        self.chain: SandboxFilterChain = build_chain(self.policy) if self.policy.get("enabled", True) else SandboxFilterChain()
        self._disabled = not self.policy.get("enabled", True)
        self._auditor = auditor       # SecurityAuditor (可选): 每条裁决直写审计
        self._bus = bus               # SecurityEventBus (可选): 沙箱事件汇入统一审计流
        # B2: 无人值守决策与出网边界的**脱敏**可观测状态。
        # 只存结构化结果 / 键名 / 计数，绝不存命令原文或凭据值。
        self._unattended_log: List[Dict[str, Any]] = []
        self._last_egress: Dict[str, Any] = {}
        self._last_allowlist: Dict[str, Any] = {}
        self._last_proxy_audit: List[Dict[str, Any]] = []

    # ------------------------------------------------------------ B2 可观测
    def _record_unattended(self, outcome: Any) -> None:
        """成对留痕：一次决策一条，脱敏、有界、不进异常路径。"""
        try:
            self._unattended_log.append(outcome.to_dict())
            if len(self._unattended_log) > 256:
                del self._unattended_log[:-256]
        except Exception:  # noqa: BLE001 - 审计失败绝不影响裁决
            pass

    def unattended_decisions(self) -> List[Dict[str, Any]]:
        return [dict(x) for x in self._unattended_log]

    @property
    def last_egress(self) -> Dict[str, Any]:
        return dict(self._last_egress)

    @property
    def last_allowlist(self) -> Dict[str, Any]:
        return dict(self._last_allowlist)

    @property
    def last_proxy_audit(self) -> List[Dict[str, Any]]:
        return [dict(x) for x in self._last_proxy_audit]

    def _detected_domains(self, payload: Any) -> List[str]:
        """复用 TrustFilter 的文本检测；异常一律上抛由调用方 fail-closed。"""
        from ..core.network_guard import get_network_guard
        from .filters import TrustFilter
        return TrustFilter._detected_domains(payload, get_network_guard())

    def _bind_network_claim(self, verdict: Any, payload: Any,
                            fn_args: Any = None) -> Any:
        """把逐命令域名声明写进 verdict.extra，并在裁决层做强绑定断言。

        B2 收尾实测缺口：verdict.extra 原本为空，执行层 / 强后端拿不到
        「这次只允许哪些主机」；SandboxProfile 也只有布尔 network。
        """
        from .verdict import deny
        claim = claim_from_args(
            fn_args, fallback=payload.meta.get("allowed_domains"),
            fallback_source="global_policy")
        try:
            detected = self._detected_domains(payload)
        except Exception as exc:  # noqa: BLE001 - 检测异常必须闭合
            detected = []
            self._last_allowlist = {"allowed": False,
                                    "reason": f"域名检测异常 fail-closed: {type(exc).__name__}"}
            return verdict.merged(deny(
                "egress_allowlist", self._last_allowlist["reason"], SEV["high"]))
        dec = evaluate_claim(claim, detected)
        verdict.extra.update(claim_to_verdict_extra(claim))
        verdict.extra["allowlist"] = dec.to_audit_dict()
        self._last_allowlist = dec.to_audit_dict()
        if not dec.allowed:
            return verdict.merged(deny("egress_allowlist", dec.reason, SEV["high"]))
        return verdict

    def _make_egress_proxy(self, plan: Any) -> Any:
        """只依据 ``plan.wants_proxy`` 构造代理 —— 单一真相，不重复判断。

        上一轮这里自己又判了一遍 ``egress_proxy_enabled + strict +
        required_domains``，与裁决层容易漂移。现在全部由
        :func:`plan_egress` 决定。
        """
        if not getattr(plan, "wants_proxy", False):
            return None
        return EgressProxy(plan.claim, plan.broker)

    def _unattended_policy(self, ctx: Any) -> Any:
        """从沙箱策略 + kernel 配置解析开关；配置不可用时保持默认关闭。"""
        from .unattended import UnattendedPolicy
        raw: Dict[str, Any] = dict(self.policy or {})
        try:
            kernel = getattr(ctx, "kernel", None)
            cfg = kernel.get("config") if kernel is not None else None
            if cfg is not None:
                for key in ("permissions.denyInsteadOfPrompting",
                            "permissions.denyInsteadOfPromptingScope"):
                    val = cfg.get(key)
                    if val is not None:
                        raw[key] = val
        except Exception:  # noqa: BLE001 - 配置通道异常不能掀掉裁决
            pass
        return UnattendedPolicy.from_mapping(raw)

    # ------------------------------------------------------------ 工具参数归一化
    @staticmethod
    def _method_for(fn_name: str) -> str:
        if fn_name.startswith("mcp__"):
            return "mcp"
        if fn_name.startswith("web_"):
            return "web"
        return _TOOL_METHOD.get(fn_name, "other")

    @staticmethod
    def _extract_text(fn_args: Any) -> List[str]:
        if isinstance(fn_args, str):
            try:
                import json as _json
                fn_args = _json.loads(fn_args) if fn_args.strip().startswith(("{", "[")) else {"command": fn_args}
            except Exception:
                fn_args = {"command": fn_args}
        if not isinstance(fn_args, dict):
            return []
        out: List[str] = []
        for key, val in fn_args.items():
            if key in _EXEC_FIELDS and isinstance(val, str) and val.strip():
                out.append(val)
        # 兜底: 任意字段里递归出现的整段可执行文本
        for val in fn_args.values():
            if isinstance(val, str) and val.strip().count("\n") >= 2:
                out.append(val)
        return list(dict.fromkeys(out))

    @staticmethod
    def _command_of(fn_args: Any) -> str:
        if isinstance(fn_args, dict):
            c = fn_args.get("command")
            return c if isinstance(c, str) else ""
        return ""

    # ------------------------------------------------------------ 审计闭环
    def _emit_audit(self, verdict: Verdict, payload: Payload) -> None:
        """把沙箱裁决汇入审计流 (仅当挂了 auditor / bus 时才落, 保证可移植/无副作用)。

        DENY 全量记录; CONFIRM / ISOLATE 仅在高危以上记一条 (避免噪音)。
        任何异常都吞掉 —— 审计是补充保障, 绝不反噬沙箱主流程。
        """
        if not (self._auditor is not None or self._bus is not None):
            return
        notable = verdict.blocks or verdict.severity in ("high", "critical")
        if not notable:
            return
        command = payload.command or (payload.text[0] if payload.text else "")
        command = (command or "")[:500]
        reasons = ([verdict.reason] if verdict.reason else []) + list(verdict.suggestions)
        context = {
            "layer": verdict.layer,
            "tool": payload.tool_name,
            "method": payload.method,
            "trust_level": payload.trust_level,
            "workspace_mode": verdict.workspace_mode,
            "backend": verdict.backend,
            "network": verdict.network,
            "plan_mode": payload.plan_mode,
        }
        try:
            if self._auditor is not None:
                self._auditor.record(
                    module="sandbox", action=verdict.action.value,
                    severity=verdict.severity, input_summary=command,
                    reasons=reasons, context=context,
                )
            if self._bus is not None:
                if verdict.blocks:
                    self._bus.emit_sandbox_blocked(
                        command, verdict.layer, verdict.reason,
                        severity=verdict.severity, suggestions=list(verdict.suggestions),
                    )
                else:
                    from ..core.security_bus import SecurityEvent, SecurityEventType
                    etype = (SecurityEventType.SANDBOX_ISOLATED if verdict.isolate
                             else SecurityEventType.SANDBOX_CONFIRMED)
                    self._bus.emit(SecurityEvent(
                        event_type=etype, timestamp=_time.time(),
                        payload={"command": command, "layer": verdict.layer,
                                 "reason": verdict.reason},
                        source="sandbox", severity=verdict.severity,
                    ))
        except Exception:  # noqa: BLE001 - 审计失败不影响主流程
            pass

    # ------------------------------------------------------------ 主评估
    def assess(self, payload: Payload) -> Verdict:
        if self._disabled:
            return Verdict()
        try:
            verdict = self.chain.evaluate(payload)
        except Exception as exc:  # noqa: BLE001 - 滤网自身故障必须 fail-closed
            log.error("沙箱滤网异常: %s", exc)
            verdict = Verdict(Action.DENY, layer="base", severity=SEV["critical"],
                              reason=f"沙箱评估内部故障, fail-closed ({type(exc).__name__})")
        self._emit_audit(verdict, payload)
        # 安全替代建议增强: 危险裁决未带建议时, 用命令感知引擎补齐
        if (verdict.blocks or verdict.action == Action.CONFIRM) and not verdict.suggestions:
            cmd = payload.command or (payload.text[0] if payload.text else "")
            if cmd:
                from ..harden.safe_alternatives import format_suggestions

                verdict.suggestions = format_suggestions(cmd)
        return verdict

    def assess_tool(self, fn_name: str, fn_args: Any, ctx: Any) -> Tuple[bool, str]:
        """全工具统一入口: 返回 (denied, block_msg)。供 ToolExecutor 调用。"""
        if self._disabled:
            return False, ""
        texts = self._extract_text(fn_args)
        command = self._command_of(fn_args)
        if not texts and not command:
            return False, ""
        payload = Payload(
            tool_name=fn_name,
            text=texts,
            command=command,
            method=self._method_for(fn_name),
            workspace=getattr(ctx, "workspace", ""),
            trust_level=getattr(ctx, "workspace_trust_level", getattr(ctx, "trust_level", None)),
            plan_mode=bool(getattr(ctx, "plan_mode", False)),
            yolo=bool(getattr(ctx, "yolo", False)),
            require_confirm=not getattr(ctx, "yolo", False),
            meta={
                "severity": getattr(ctx, "safety_severity", None),
                "allowed_domains": self._allowed_domains(ctx),
            },
        )
        verdict = self.assess(payload)
        verdict = self._bind_network_claim(verdict, payload, fn_args)
        if verdict.blocks:
            return True, verdict.describe()
        if verdict.action == Action.CONFIRM and not payload.yolo:
            confirm = getattr(ctx, "confirm", None)
            # B2: permissions.denyInsteadOfPrompting —— 无人值守时拒绝并继续
            # turn，不挂起等待。默认关闭，开启后 denied=True 仍是硬事实，
            # 「继续 turn」只写在 verdict.extra / 可查询审计里。
            from .unattended import UnattendedPolicy, resolve_confirm
            outcome = resolve_confirm(
                verdict, has_confirm_channel=confirm is not None,
                policy=self._unattended_policy(ctx))
            if outcome.applied:
                verdict.extra["unattended_deny"] = outcome.denied
                verdict.extra["continue_turn"] = outcome.continue_turn
                verdict.extra["suppressed_prompt"] = outcome.suppressed_prompt
                self._record_unattended(outcome)
                if outcome.denied:
                    return True, outcome.reason
            if confirm is None:
                return True, f"[沙箱信任滤网] 需要人工确认但没有确认通道: {verdict.reason}"
            try:
                if not confirm(f"[沙箱确认] {verdict.reason}\n请确认是否继续?"):
                    return True, f"[沙箱信任滤网] 用户拒绝: {verdict.reason}"
            except Exception:
                return True, f"[沙箱信任滤网] 确认通道异常, fail-closed: {verdict.reason}"
        return False, ""

    def assess_command(self, command: str, ctx: Any) -> Verdict:
        """对单条命令做完整滤网(供 run_shell 的隔离选路)。"""
        if self._disabled:
            return Verdict()
        payload = Payload(
            tool_name="run_shell",
            text=[command],
            command=command,
            method="shell",
            workspace=getattr(ctx, "workspace", ""),
            trust_level=getattr(ctx, "workspace_trust_level", getattr(ctx, "trust_level", None)),
            plan_mode=bool(getattr(ctx, "plan_mode", False)),
            yolo=bool(getattr(ctx, "yolo", False)),
            require_confirm=True,
            meta={"severity": getattr(ctx, "safety_severity", None),
                  "allowed_domains": self._allowed_domains(ctx)},
        )
        verdict = self.assess(payload)
        return self._bind_network_claim(verdict, payload)

    # ------------------------------------------------------------ 隔离执行
    def should_isolate(self, verdict: Verdict) -> bool:
        return verdict.isolate

    def execute_isolated(self, command: str, verdict: Verdict, ctx: Any,
                         timeout: float = 60.0) -> SandboxExecResult:
        """当裁决要求隔离时, 用选中后端真正执行命令。

        E7: 此前 ``verdict.workspace_mode == "copy_diff_apply"`` 只被 L2 滤网写入
        verdict、进审计 context, **执行层从未消费** —— 副本模式是纯文档特性,
        高危命令实际仍在真实工作区裸跑。现在按 workspace_mode 分派, 让高危命令
        真的在隔离副本里执行, 经过 diff 预览 + 用户确认后才写回。
        """
        if not verdict.isolate:
            return SandboxExecResult()
        cwd = getattr(ctx, "workspace", None) or "."
        if getattr(verdict, "workspace_mode", "direct") == "copy_diff_apply":
            return self._execute_copy_diff_apply(command, verdict, ctx, cwd, timeout)
        return self._execute_backend(command, verdict, cwd, timeout)

    def _execute_backend(self, command: str, verdict: Verdict, cwd: str,
                         timeout: float) -> SandboxExecResult:
        """按选中后端执行。**所有分支共用一个出网/凭据准备出口**。

        本轮实测缺口：上一轮只把 EgressGuard + 逐命令域名强绑定接到了
        local 分支；landlock/docker/seatbelt (``_run_provider``) 只把
        allowed_domains 当元数据传进去（后端根本不读），jobobject
        (``_run_syscall``) 连 env 参数都没有、子进程继承父进程全部真实
        环境变量。**安全等级更高的路径反而没有刚补的防护**。

        现在 ``plan_egress`` 在分支之前统一裁决，三条路径都拿 ``plan.env``
        （EgressGuard 脱敏 / sentinel），并统一写 ``last_egress``。
        """
        backend = verdict.backend or pick_backend("auto")[0]
        block_net = not verdict.network

        plan = plan_egress(verdict, backend, self.policy, os.environ)
        self._last_egress = plan.to_audit_dict()
        # 派生一致性：审计里的 claim 必须真的来自本次 verdict，
        # 不许「说一套做一套」（前几轮反复抓的撕裂类缺陷）。
        self._last_egress["claim_consistent"] = \
            plan_is_consistent_with_verdict(plan, verdict)
        if not plan.allowed:
            return SandboxExecResult(returncode=-1, backend=backend,
                                     enforced=False, error=plan.reason)

        # 代理只有本地后端能可靠连到（netns / seatbelt 隔离下宿主回环不可达）。
        # 生命周期 try/finally 覆盖所有分支：超时/异常也一定 stop()。
        proxy = None
        try:
            proxy = self._make_egress_proxy(plan)
            if proxy is not None:
                proxy.start()
                plan.env.update(proxy.env_overrides)
                self._last_egress["proxy_enabled"] = True
                self._last_egress["proxy_url"] = proxy.url
                self._last_egress["proxy_claim"] = plan.claim.to_dict()

            if backend in ("jobobject",) and os.name == "nt":
                return self._run_syscall(command, timeout, block_net, cwd,
                                         backend, env=plan.env)
            if backend in ("landlock", "docker", "seatbelt", "bwrap"):
                return self._run_provider(backend, command, cwd, timeout,
                                          block_net, verdict, env=plan.env)

            # local / 其它: 裸跑 (非 OS 级隔离), 交由上层 enforce 决定。
            from ..core.proc import run_with_tree_kill
            proc = run_with_tree_kill(
                command, shell=True, cwd=cwd,
                capture_output=True, text=True, timeout=timeout or 60.0,
                errors="replace", env=plan.env,
            )
            return SandboxExecResult(stdout=proc.stdout or "", stderr=proc.stderr or "",
                                     returncode=proc.returncode or 0,
                                     backend=backend, enforced=False)
        except subprocess.TimeoutExpired:
            return SandboxExecResult(returncode=-1, backend=backend,
                                     enforced=False, error="超时")
        except Exception as exc:
            return SandboxExecResult(returncode=-1, backend=backend,
                                     enforced=False, error=str(exc))
        finally:
            if proxy is not None:
                self._last_proxy_audit = proxy.audit()
                proxy.stop()

    def _execute_copy_diff_apply(self, command: str, verdict: Verdict, ctx: Any,
                                 cwd: str, timeout: float) -> SandboxExecResult:
        """副本 -> 执行 -> diff 预览 -> 确认 -> TOCTOU 复检 -> apply。"""
        from .isolation import isolate_workdir, confirm_apply, build_diff_preview

        wd = None
        try:
            wd = isolate_workdir(cwd)
            res = self._execute_backend(command, verdict, wd.path, timeout)
            res.workspace_mode = "copy_diff_apply"
            # 副本隔离本身已生效, 标记 enforced 让 shell.py 的路由返回结果文本,
            # 而不是回落 None 后又把命令在真实工作区跑一遍。
            verdict.enforced = True
            try:
                preview = build_diff_preview(wd)
            except Exception as exc:  # noqa: BLE001
                res.returncode = -1
                res.error = (f"生成变更预览失败 (fail-closed, 不写回): "
                             f"{type(exc).__name__}: {exc}")
                return res
            # E7-TUI: 统一走审批覆盖层 (借鉴 Codex TUI approval_overlay)。
            # 有 ctx.confirm 时把结构化卡片交给现有 TUI 挂起式确认通道;
            # 无通道时提供 headless 默认通道 (打印卡片 + 精确确认码 + stdin),
            # 不再"直接失败", 但同样要求显式决策, 不放松 fail-closed。
            from ..ui.approval_overlay import make_confirm_callable
            card_renderer, confirm_fn = make_confirm_callable(ctx)
            outcome = confirm_apply(wd, confirm_fn, card_renderer=card_renderer)
            res.diff_preview = outcome.preview.to_dict() if outcome.preview else preview.to_dict()
            res.applied = outcome.applied
            res.applied_files = list(outcome.files)
            res.confirm_reason = outcome.reason
            preview_text = (outcome.preview or preview).to_text()

            if not outcome.applied:
                res.returncode = -1
                # 拒绝时把预览一并放进 error, 因为 shell.py 在 returncode<0 时
                # 只展示 error —— 用户必须仍能看见"本来要改什么"。
                res.error = f"{outcome.reason}\n{preview_text}"
                return res
            # 执行本身失败也不写回, 但预览/确认已完成, 如实交回上层
            if res.returncode < 0:
                res.applied = False
                res.applied_files = []
                return res
            res.stdout = (res.stdout or "") + "\n" + preview_text + \
                         f"\n[E7] 用户已确认, 已写回 {len(outcome.files)} 个文件"
            return res
        except Exception as exc:  # noqa: BLE001
            return SandboxExecResult(
                returncode=-1, workspace_mode="copy_diff_apply", enforced=True,
                applied=False,
                error=f"副本隔离执行失败 (fail-closed, 未写回): {type(exc).__name__}: {exc}")
        finally:
            if wd is not None:
                wd.cleanup()

    def _run_syscall(self, command: str, timeout: float, block_net: bool,
                     cwd: str, backend: str,
                     env: Optional[Dict[str, str]] = None) -> SandboxExecResult:
        """调用 OS 原语执行, 并如实汇报是否真的拿到了强制隔离。

        E3: 旧实现把 ``enforced=True`` 写死 —— 只要 platform 层没抛异常,
        即使内部已降级为普通子进程 (libseccomp 缺失 / Job Object 挂不上),
        上层也会认为"已强隔离执行"并放行。现在以 ``SyscallResult.enforced``
        为准; ``enforce_required=True`` 时降级由 HardIsolationFilter 拒绝。
        """
        try:
            from ..arch.platform import run_syscall_sandboxed
            resource = self.policy.get("resource", {}) or {}
            res = run_syscall_sandboxed(
                ["cmd", "/c", command] if os.name == "nt" else ["/bin/sh", "-c", command],
                timeout=timeout or 30.0, block_network=block_net, cwd=cwd or None,
                memory_limit_mb=int(resource.get("max_memory_mb", 0) or 512),
                cpu_rate_pct=int(resource.get("cpu_rate_pct", 50) or 50),
                active_process_limit=int(resource.get("active_process_limit", 16) or 16),
                kill_timeout_seconds=float(resource.get("kill_timeout_seconds", 5.0) or 5.0),
                env=env,
            )
            note = res.degraded_reason or res.error or ("blocked" if res.blocked else "")
            return SandboxExecResult(stdout=res.stdout or "", stderr=res.stderr or "",
                                     returncode=res.returncode, backend=res.mechanism or backend,
                                     enforced=bool(res.enforced), error=note)
        except Exception as exc:
            return SandboxExecResult(returncode=-1, backend=backend,
                                     enforced=False, error=str(exc))

    @staticmethod
    def _run_provider(backend: str, command: str, cwd: str, timeout: float,
                      block_net: bool, verdict: Verdict,
                      env: Optional[Dict[str, str]] = None) -> SandboxExecResult:
        try:
            from ..core.sandbox_provider import SandboxProvider, SandboxProfile
            provider = SandboxProvider.create(backend)
            profile = SandboxProfile(
                network=verdict.network,
                max_memory_mb=verdict.memory_mb,
                allowed_domains=list(profile_domains(claim_from_verdict(verdict))))
            result = provider.run(["/bin/sh", "-c", command] if os.name != "nt" else ["cmd", "/c", command],
                                  workspace=cwd, profile=profile,
                                  env=env, timeout=timeout or 60.0)
            return SandboxExecResult(stdout=result.stdout, stderr=result.stderr,
                                     returncode=result.returncode,
                                     backend=backend, enforced=result.enforced,
                                     error=result.error)
        except Exception as exc:
            return SandboxExecResult(returncode=-1, backend=backend,
                                     enforced=False, error=str(exc))

    # ------------------------------------------------------------ 配置
    def _allowed_domains(self, ctx: Any) -> Optional[List[str]]:
        # 优先取沙箱策略自带白名单 (sandbox.allowed_domains), 保证无 kernel 也可用、可测;
        # 否则回落 kernel 配置 (permissions.network.allow_domains 优先, sandbox.allowed_domains 兜底)。
        p_ad = self.policy.get("allowed_domains")
        if p_ad:
            return list(p_ad)
        try:
            cfg = ctx.kernel.get("config")
            if cfg is not None:
                ad = cfg.get("permissions.network.allow_domains", [])
                if ad:
                    return list(ad)
                sd = cfg.get("sandbox.allowed_domains", [])
                if sd:
                    return list(sd)
        except Exception:  # pragma: no cover
            pass
        return None

    @classmethod
    def from_kernel(cls, kernel: Any) -> "SandboxManager":
        cfg = None
        auditor = None
        try:
            cfg = kernel.get("config")
        except Exception:  # pragma: no cover
            pass
        try:
            auditor = kernel.get("security_auditor")
        except Exception:  # pragma: no cover
            auditor = None
        policy = cfg.get("sandbox", {}) if cfg is not None else {}
        bus = None
        try:
            from ..core.security_bus import get_security_bus
            bus = get_security_bus()
        except Exception:  # pragma: no cover
            bus = None
        return cls(policy, auditor=auditor, bus=bus)


def _merge_policy(raw: Dict[str, Any]) -> Dict[str, Any]:
    merged = json_deep_merge(DEFAULT_POLICY, raw)
    return merged


def json_deep_merge(base: Dict[str, Any], over: Dict[str, Any]) -> Dict[str, Any]:
    import copy
    out = copy.deepcopy(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = json_deep_merge(out[k], v)
        else:
            out[k] = v
    return out