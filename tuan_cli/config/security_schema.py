"""E8: 安全相关配置的强校验 (schema + fail-closed 可观测性)。

为什么单独一个模块:
`config/validate.py` 只校验模型 / agent / context 等数值与枚举, 完全不覆盖
`sandbox` / `permissions` —— 而这两段恰恰决定「安全流水线是否生效」。
最危险的不是配错值, 是**静默配错**: `PermissionPolicy.match_rule()` 对非 dict
规则 / 未知 action 一律 `continue` 跳过, `sandbox.enabled=false` 直接短路整条
滤网 (见 tests/test_sandbox_system.py::test_disabled_shortcircuits)。写错一个键,
看起来规则还在, 实际已经不设防。

本模块把这类「静默失效」变成 `tuan config validate` 的显式错误, 并在
`tuan harden status` 里输出, 让降级项可见。校验只读配置、不联网、不打印密钥。
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

_BACKENDS = ("auto", "local", "docker", "landlock", "seatbelt",
             "jobobject", "token-acl")
_THRESHOLDS = ("low", "medium", "high", "critical")
_ACTIONS = ("allow", "deny", "ask")
_RULE_KEYS = {"tool", "pattern", "action", "param", "value", "exclude"}
_RULE_STR_KEYS = ("tool", "pattern", "param", "value", "exclude")


def _bool_field(errors: List[str], section: str, val: Any, *,
                dangerous_when_false: str | None = None) -> None:
    if val is None:
        return
    if not isinstance(val, bool):
        errors.append(f"类型错误: {section} 应为 bool, 实际为 {type(val).__name__}")
        return
    if dangerous_when_false and val is False:
        errors.append(f"安全降级: {section}=false ({dangerous_when_false})")


def _str_list(errors: List[str], section: str, val: Any) -> None:
    if val is None:
        return
    if not isinstance(val, (list, tuple)):
        errors.append(f"类型错误: {section} 应为字符串列表, 实际为 {type(val).__name__}")
        return
    bad = [i for i, x in enumerate(val) if not isinstance(x, str)]
    if bad:
        errors.append(f"类型错误: {section} 含非字符串元素 (索引 {bad[:5]})")


def _validate_rules(errors: List[str], warnings: List[str], rules: Any) -> None:
    if rules is None:
        return
    if not isinstance(rules, (list, tuple)):
        errors.append(
            f"类型错误: permissions.rules 应为规则列表, 实际为 {type(rules).__name__} "
            f"(整表将被静默忽略)")
        return
    for i, rule in enumerate(rules):
        tag = f"permissions.rules[{i}]"
        if not isinstance(rule, dict):
            errors.append(f"{tag} 不是 dict, 该规则会被静默跳过")
            continue
        action = rule.get("action")
        if action is None:
            errors.append(f"{tag} 缺少 action, 该规则会被静默跳过")
        elif str(action).strip().lower() not in _ACTIONS:
            errors.append(
                f"{tag}.action={action!r} 非法 (应为 {_ACTIONS}), 该规则会被静默跳过")
        for key in _RULE_STR_KEYS:
            if key in rule and rule[key] is not None and not isinstance(rule[key], str):
                errors.append(f"{tag}.{key} 应为字符串, 实际为 {type(rule[key]).__name__}")
        unknown = set(rule) - _RULE_KEYS
        if unknown:
            warnings.append(
                f"{tag} 含未知键 {sorted(unknown)} —— 拼写错误会让规则不生效")
        pat = str(rule.get("pattern", "")).strip()
        if pat.startswith("!") and not pat[1:].strip():
            errors.append(f"{tag}.pattern='!' 空排除模式, 该规则语义异常")
        # deny 规则带 exclude 不生效 (见 PermissionPolicy.match_rule), 明确提示避免误解
        if "exclude" in rule and str(rule.get("action", "")).strip().lower() == "deny":
            warnings.append(
                f"{tag} 是 deny 规则, exclude 会被忽略 (fail-closed, 拒绝规则不允许被放宽)")


def validate_security_config(config: Any) -> Tuple[List[str], List[str]]:
    """校验 sandbox / permissions / 安全相关开关。

    返回 (errors, warnings)。**缺失字段不报错** —— 由 DEFAULT_CONFIG 兜底;
    只有显式写出且类型/取值非法、或显式关闭关键防线时才报。
    """
    errors: List[str] = []
    warnings: List[str] = []

    def get(key: str) -> Any:
        try:
            return config.get(key)
        except Exception:  # noqa: BLE001
            return None

    sb = get("sandbox")
    if sb is not None and not isinstance(sb, dict):
        errors.append(f"类型错误: sandbox 应为配置字典, 实际为 {type(sb).__name__}")
        sb = None
    if isinstance(sb, dict):
        _bool_field(errors, "sandbox.enabled", sb.get("enabled"),
                    dangerous_when_false="4 层沙箱滤网整体短路, 所有工具裸执行")
        _bool_field(errors, "sandbox.enforce_required", sb.get("enforce_required"),
                    dangerous_when_false="无强隔离后端时静默降级为裸执行")
        _bool_field(errors, "sandbox.deny_unknown_shell", sb.get("deny_unknown_shell"))
        backend = sb.get("backend")
        if backend is not None and (not isinstance(backend, str) or backend not in _BACKENDS):
            errors.append(f"非法枚举: sandbox.backend={backend!r} 不在 {_BACKENDS} 中")
        _str_list(errors, "sandbox.allowed_domains", sb.get("allowed_domains"))
        res = sb.get("resource")
        if res is not None and not isinstance(res, dict):
            errors.append(f"类型错误: sandbox.resource 应为配置字典, 实际为 {type(res).__name__}")
            res = None
        if isinstance(res, dict):
            _bool_field(errors, "sandbox.resource.deny_network_by_default",
                        res.get("deny_network_by_default"))
            if res.get("deny_network_by_default") is False:
                warnings.append(
                    "sandbox.resource.deny_network_by_default=false (出厂默认值; "
                    "生产/托管部署建议开启, 见 SECURITY_BASELINE.md §3.2)")
            # B2: 子进程出网边界的两个开关。显式关闭必须作为安全降级可见，
            # 不能静默回到「禁网裁决裸跑 / 真实凭据进子进程」的旧行为。
            _bool_field(errors, "sandbox.resource.egress_credential_masking",
                        res.get("egress_credential_masking"),
                        dangerous_when_false="父进程真实凭据原样进入子进程")
            _bool_field(errors, "sandbox.resource.egress_block_local_when_denied",
                        res.get("egress_block_local_when_denied"),
                        dangerous_when_false="local 后端收到禁网裁决仍会裸跑")
            # B2 收尾: 出网代理默认关。开启是真行为变更（改写子进程代理环境变量），
            # 必须可见；但「关闭」不是安全降级，因为逐命令 claim 的裁决层强绑定
            # 始终生效，代理只是把强制点从文本层搬到出网路径上。
            _bool_field(errors, "sandbox.resource.egress_proxy_enabled",
                        res.get("egress_proxy_enabled"))
            if res.get("egress_proxy_enabled") is True:
                warnings.append(
                    "行为变更: sandbox.resource.egress_proxy_enabled=true 使"
                    "带逐命令 allowed_domains 的子进程出网改写 HTTP_PROXY/"
                    "HTTPS_PROXY 并经过本地回环代理做主机校验与凭据注入")
            for key in ("max_memory_mb", "max_timeout"):
                val = res.get(key)
                if val is None:
                    continue
                if not isinstance(val, int) or isinstance(val, bool) or val < 0:
                    errors.append(f"取值非法: sandbox.resource.{key}={val!r} 应为 >=0 的整数")
            # E3: Job Object 配额。写错范围时执行层会抛 ValueError 并降级为裸跑,
            # 必须在配置校验阶段就拦住, 否则运行时才发现"隔离没生效"。
            for key, lo, hi in (("cpu_rate_pct", 1, 100),
                                ("active_process_limit", 1, 1024)):
                val = res.get(key)
                if val is None:
                    continue
                if not isinstance(val, int) or isinstance(val, bool) or not (lo <= val <= hi):
                    errors.append(
                        f"取值非法: sandbox.resource.{key}={val!r} 应在 {lo}..{hi} 之间")
            kt = res.get("kill_timeout_seconds")
            if kt is not None:
                if not isinstance(kt, (int, float)) or isinstance(kt, bool) \
                        or not (0.5 <= kt <= 60.0):
                    errors.append(
                        f"取值非法: sandbox.resource.kill_timeout_seconds={kt!r} 应在 0.5..60 之间")
            if res.get("max_memory_mb") not in (None, 0):
                mm = res["max_memory_mb"]
                if isinstance(mm, int) and not isinstance(mm, bool) and not (16 <= mm <= 65536):
                    errors.append(
                        f"取值非法: sandbox.resource.max_memory_mb={mm} 应在 16..65536 (或 0=不限)")
            thr = res.get("isolate_copy_threshold")
            if thr is not None and thr not in _THRESHOLDS:
                errors.append(
                    f"非法枚举: sandbox.resource.isolate_copy_threshold={thr!r} "
                    f"不在 {_THRESHOLDS} 中")

    # B2 / 超 Claude Code v2.1.319: permissions.denyInsteadOfPrompting。
    # 默认关闭；开启是显式行为变更（需审批的调用改为拒绝并继续 turn）。
    _bool_field(errors, "permissions.denyInsteadOfPrompting",
                get("permissions.denyInsteadOfPrompting"))
    if get("permissions.denyInsteadOfPrompting") is True:
        warnings.append(
            "行为变更: permissions.denyInsteadOfPrompting=true 使无人值守的"
            "需确认调用直接拒绝并继续 turn (不再挂起等待输入)")
    dip_scope = get("permissions.denyInsteadOfPromptingScope")
    if dip_scope is not None and (
            not isinstance(dip_scope, str)
            or dip_scope.strip().lower() not in (
                "no_confirm_channel", "all_confirmations")):
        errors.append(
            f"非法枚举: permissions.denyInsteadOfPromptingScope={dip_scope!r} "
            f"(应为 no_confirm_channel / all_confirmations)")

    _validate_rules(errors, warnings, get("permissions.rules"))
    _str_list(errors, "permissions.shell.deny_patterns", get("permissions.shell.deny_patterns"))
    _str_list(errors, "permissions.network.allow_domains",
              get("permissions.network.allow_domains"))
    _str_list(errors, "mode.yolo_require_confirm", get("mode.yolo_require_confirm"))

    net = get("security.network")
    if net is not None and not isinstance(net, dict):
        errors.append(f"类型错误: security.network 应为配置字典, 实际为 {type(net).__name__}")

    # E1: 显式关闭 MCP 信任分级是重大降级, 必须可见 (不是静默的逃生口)。
    mcp = get("mcp")
    if mcp is not None and not isinstance(mcp, dict):
        errors.append(f"类型错误: mcp 应为配置字典, 实际为 {type(mcp).__name__}")
        mcp = None
    if isinstance(mcp, dict):
        pol = mcp.get("policy")
        if pol is not None and not isinstance(pol, dict):
            errors.append(f"类型错误: mcp.policy 应为配置字典, 实际为 {type(pol).__name__}")
            pol = None
        if isinstance(pol, dict):
            _bool_field(errors, "mcp.policy.enabled", pol.get("enabled"),
                        dangerous_when_false="MCP 信任分级整体关闭, 未登记 server 将由外层一刀切放行")

    # B1 / 超 Claude Code v2.1.319: hook 故障策略决定「闸门坏了是关门还是
    # 开门」。HookManager 对未知值会回退最严格档 block，所以这里必须在
    # 配置阶段就拦住拼写错误；显式 allow 是逃生口，必须作为安全降级可见。
    hk = get("hooks")
    if hk is not None and not isinstance(hk, dict):
        errors.append(f"类型错误: hooks 应为配置字典, 实际为 {type(hk).__name__}")
    elif isinstance(hk, dict):
        of = hk.get("on_failure")
        if of is not None:
            if not isinstance(of, str) or of.strip().lower() not in (
                    "block", "ask", "allow"):
                errors.append(
                    f"非法枚举: hooks.on_failure={of!r} 不在 "
                    f"('block', 'ask', 'allow') 中 (HookManager 会回退 block, "
                    f"但拼写错误不应静默)")
            elif of.strip().lower() == "allow":
                warnings.append(
                    "安全降级: hooks.on_failure=allow 使 hook 故障静默放行; "
                    "CC 的 onFailure:'block' 需逐条显式配置, 本项目默认闭合")
        for evt in ("PreToolUse", "PostToolUse"):
            specs = hk.get(evt)
            if specs is None:
                continue
            if not isinstance(specs, (list, tuple)):
                errors.append(
                    f"类型错误: hooks.{evt} 应为 hook 列表, 实际为 "
                    f"{type(specs).__name__}")
                continue
            for i, spec in enumerate(specs):
                if not isinstance(spec, dict):
                    errors.append(f"hooks.{evt}[{i}] 不是 dict, 该 hook 会被跳过")
                    continue
                p_of = spec.get("on_failure")
                if p_of is not None and (
                        not isinstance(p_of, str)
                        or p_of.strip().lower() not in ("block", "ask", "allow")):
                    errors.append(
                        f"非法枚举: hooks.{evt}[{i}].on_failure={p_of!r} "
                        f"(应为 block / ask / allow)")

    return errors, warnings
