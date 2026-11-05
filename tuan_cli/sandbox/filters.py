"""4 层沙箱滤网 + 编排链。

每一层都是独立滤网, 对一次执行请求(Payload)输出 Verdict, 只许"收紧"不许"放宽":
    L0 Intent  意图滤网   确定性识别致命红线 / 网络外泄 / 命令语言类别      (静态, 无副作用)
    L1 Trust   信任滤网   工作区信任分级 + 计划模式 + 域名白名单            (静态)
    L2 Resource 资源滤网   网络开关 / 内存/超时 / 工作区隔离模式选择         (元数据)
    L3 Hard    强隔离滤网  隔离后端自动选择(docker→bwrap→jobobject→local)  (执行策略, fail-closed)

对比单层"丢容器"方案的价值: L0/L1 不依赖任何内核/容器, 在命令进入任何运行时之前,
已把致命命令与越权写入判定为 deny —— 即便机器上没有 docker/bwrap/seccomp,
前两层滤网依然成立。L3 只是"锦上添花的真正隔离", 而 L2 决定该不该上这道锦上添花。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .verdict import Action, Payload, SEV, Verdict, deny, confirm, isolate

log = logging.getLogger(__name__)


# ----------------------------------------------------------------- 工具: 文本归并
def _all_benign(texts: List[str]) -> bool:
    """texts 里每个有意义的命令串都判为良性。"""
    try:
        from ..ext.safety_engine import is_benign_dev_command
    except Exception:  # pragma: no cover
        return False
    for t in texts:
        t = (t or "").strip()
        if not t:
            continue
        try:
            if not is_benign_dev_command(t):
                return False
        except Exception:  # noqa: BLE001 - 无法评估按非良性处理
            return False
    return True


def _scan_embedded_secrets(texts: List[str]) -> Optional[Verdict]:
    """扫描命令/写入文本里内嵌的高风险明文凭据 (AWS/GitHub/OpenAI key、PEM 私钥)。

    与 ``core.secret_scanner`` 共用同一份规则来源 (避免两套口径): 命中 high 级凭据 →
    CONFIRM (需人工确认, 附修复建议); 仅 medium 或无命中 → 放行。

    为什么是 CONFIRM 而非 DENY: 内嵌凭据不等于文件系统毁灭级红线 (rm -rf /),
    用户可能是在写测试 fixture/示例配置; 但把 live credential 写进工作区/带出门是
    真实泄露风险, 故至少要一次确认。redline/网络红线仍在此之前硬拒, 优先级更高。
    任何异常都吞掉 —— 密钥扫描是补充纵深, 绝不反噬既有裁决 (与审计总线同一原则)。
    """
    try:
        from ..core.secret_scanner import scan_text
    except Exception:  # pragma: no cover - secret_scanner 为标准库实现, 极少缺失
        return None
    findings: List[Any] = []
    for t in texts:
        t = (t or "").strip()
        if not t:
            continue
        try:
            findings.extend(scan_text(t))
        except Exception:  # noqa: BLE001 - 单段扫描失败不拖累其它段
            continue
    highs = [f for f in findings if getattr(f, "severity", "") == "high"]
    if not highs:
        return None
    descs = ", ".join(sorted({getattr(f, "description", "") for f in highs}))
    sugs = list(dict.fromkeys(
        getattr(f, "remediation", "") for f in highs if getattr(f, "remediation", "")
    ))
    return confirm(
        "intent",
        f"文本内嵌高风险明文凭据 ({descs}); 写入/外带会导致密钥泄露, 需确认",
        SEV["high"],
        sugs,
    )


# ================================================================ 高层意图判据 (报告 P1-2)
# L0 原本只消费 is_hard_redline —— 与命令引擎同源: 引擎认不出的载荷, L0 也认不出,
# 所谓「四层纵深」在这类载荷上退化为单层。这里补一个**独立于命令词法**的意图判据:
# 不看 token / 不看命令名, 只按「意图语义」直接扫描文本 —— 目标路径指向系统关键位置、
# 触碰身份/凭据文件、请求特权位。即使命令引擎因全新变形而失明, 高层语义仍兜得住。
#
# 设计约束: 必须**保守** —— 只命中「明确无疑」的高危意图, 避免把 chmod +x ./build
# / passwd 改自己密码 / usermod -aG docker 这类常规操作误杀。正则按纯文本语义匹配,
# 不依赖 _cmd_name / _normalize (异源), 也不依赖真实文件系统 (平台无关)。

import re as _re

# 身份/凭据/系统关键文件: 出现即意味着触碰认证或系统边界, 无论用什么命令写。
_SYS_IDENTITY_FILE_RE = _re.compile(
    r"/etc/(?:passwd|shadow|sudoers|gshadow)\b"
    r"|~?/\.ssh/authorized_keys\b"
    r"|/root/\.[a-zA-Z]+\b"
)

# 系统关键目录前缀 (写/移/删/卸载目标指向这里都是高危意图)。含根目录 `/` 与盘根。
# 只列「明确无疑」的系统关键位置, 不含 /tmp /home/data 这类常规工作目录 (防误杀)。
_SYS_CRITICAL_PATH_RE = _re.compile(
    r"/(?:etc|boot|dev|proc|sys|run|srv|opt|home|usr|var|bin|sbin|lib|lib64|root)(?:/|\s|$)"
    r"|(?:^|\s)/\s+(?=\S)"            # 根目录 `/` 后跟其它参数 (mv / /tmp/y · rm -rf / x)
    r"|(?:^|\s)/\s*$"                 # 根目录本身结尾 (umount / · rm -rf /)
    r"|[A-Za-z]:[\\/]{1,2}\s*$"       # Windows 盘根
)

# 特权位请求: chmod +s / +u+s / --setuid / setuid / setcap 特权 capability,
# 以及八进制 SUID/SGID (chmod 4755 / 2755 — 首位 2/4/6/7)。
_PRIVILEGE_BIT_RE = _re.compile(
    r"\bchmod\b[^\n]*(?:\+\s*[ugoa]*s\b|--setuid|--setgid|\s[0-7]*[2467][0-7]{3}\b)"
    r"|\bsetuid\b"
    r"|\bsetcap\b[^\n]*(?:cap_setuid|cap_setgid|cap_sys_admin)"
)

# root 账户接管: 改 root 密码 / 重复 uid=0 / 写 root 家目录 / 切到 root shell。
_ROOT_TAKEOVER_RE = _re.compile(
    r"\bpasswd\b[^\n]*\broot\b"
    r"|\b(?:useradd|usermod)\b[^\n]*\s-u\s*0\b"
    r"|\bchage\b[^\n]*\s-[dD]\s*0\b[^\n]*\broot\b"
    r"|\bsu\b[^\n]*(?:\s-|--login)?\s*root\b|\bsu\s*-\b"
    r"|\bsudo\b[^\n]*\s(?:su|bash|sh|zsh|ksh|dash|i)\b"
)

# 写意图动词: 触碰身份文件时必须伴随「写入」而非「读取」才构成逃逸。
# cat /etc/passwd (读) 不算, echo 'x' >> /etc/passwd (写) 才算 —— 防误杀。
_WRITE_VERB_RE = _re.compile(
    r">>|>\s|>\S"
    r"|\btee\b|\bcat\s*>"
    r"|\b(?:cp|mv|ln|truncate|chmod|chown|chpasswd)\b"
    r"|\b(?:sed|awk|perl)\b[^\n]*\s-i\b"
    r"|\bdd\b[^\n]*\bof\s*="
)


def _has_system_escape_intent(texts: List[str]) -> bool:
    """高层意图判据 (异源于命令词法): 身份文件写入 / 系统关键路径破坏 / 特权位 / root 接管。

    与 is_hard_redline 形成双判: 命令引擎按 token+旗标判定, 这里按语义意图判定。
    二者独立来源, 任一命中都足以在 L0 硬拒 (fail-closed 精神)。
    """
    for t in texts:
        t = (t or "").strip()
        if not t:
            continue
        # 报告 P2: 先剥离整行/行尾 shell 注释 —— `# 谨慎: rm -rf /` 是注释不是执行。
        # 不剥则注释里的 `rm -rf /` 会被下面意图判据误判为真实逃逸 (误杀)。
        try:
            from ..ext.safety_normalize import _strip_shell_comments
            t = _strip_shell_comments(t)
        except Exception:  # noqa: BLE001
            pass
        if not t.strip():
            continue
        # 1) 触碰身份/凭据文件 —— 必须伴随「写入」意图才算逃逸 (cat /etc/passwd 读不算)
        if _SYS_IDENTITY_FILE_RE.search(t) and _WRITE_VERB_RE.search(t):
            return True
        # 2) 特权位请求 (SUID/SGID/setuid/setcap)
        if _PRIVILEGE_BIT_RE.search(t):
            return True
        # 3) root 账户接管
        if _ROOT_TAKEOVER_RE.search(t):
            return True
        # 4) 向系统关键目录的写入/删除/移动 (mv /etc、rm -rf /dev、umount /boot ...)
        #    意图判据: 系统关键路径 + 破坏性动作。破坏性动作 = 具名破坏动词 (写/移/删/
        #    卸载/格式化) **或** 递归+强制旗标 (`-rf` / `-r -f` / `--recursive --force`)。
        #    后者让「命令名被参数展开/通配隐藏」的变形也能被语义兜住 (异源于命令词法)。
        if _SYS_CRITICAL_PATH_RE.search(t) and (
            _re.search(
                r"\b(?:rm|mv|dd|mkfs|wipefs|shred|blkdiscard|umount|chmod|chown|truncate)\b",
                t,
            )
            or _re.search(
                r"-(?:[rfR]{1,2}|recursive|force)\b", t
            )
        ):
            return True
    return False


def _has_network_request(texts: List[str]) -> bool:
    """任一命令串带网络获取/上传/传输/监听特征。"""
    try:
        from ..core.network_guard import get_network_guard
        guard = get_network_guard()
        for t in texts:
            t = (t or "").strip()
            if not t:
                continue
            dec = guard.check(t)
            if getattr(dec, "detected_domains", None) or getattr(dec, "risk_level", "") in ("high", "medium"):
                return True
    except Exception:  # pragma: no cover
        pass
    return False


# ================================================================ L0 意图滤网
class IntentFilter:
    """L0 意图滤网: 全静态、确定性最强、模型无关。

    职责:
      1) 命中致命红线 (文件系统/OS 级毁灭, 永不自动执行) → deny critical
      2) 命中数据外泄 / 远程执行 (curl|sh 等) → deny high
      3) 全部良性 (ls/git status/pytest/echo...) → allow (交后续信任滤网继续)
      4) 其它非良性 → 交 L1/L2 决定 (不在此越权 deny, 避免与 shell 既有确认链重复)
    """

    name = "intent"

    def check(self, payload: Payload) -> Optional[Verdict]:
        texts = payload.text or ([payload.command] if payload.command else [])
        if not texts:
            return None
        try:
            from ..ext.safety_engine import is_hard_redline
        except Exception:  # pragma: no cover
            is_hard_redline = None  # type: ignore[assignment]  # 导入失败时无红线检测

        critical = False
        if is_hard_redline is not None:
            for t in texts:
                if t.strip() and is_hard_redline(t):
                    critical = True
                    break
        if critical:
            return deny(self.name, "命中致命红线(文件系统/OS级毁灭操作), 永不自动执行",
                        SEV["critical"])

        # 报告 P1-2: 异源双判 —— L0 不再单依赖命令引擎 (is_hard_redline)。
        # 高层意图判据不看 token/命令名, 按语义扫描文本; 引擎因全新变形失明时仍兜底。
        if _has_system_escape_intent(texts):
            return deny(self.name,
                        "命中系统逃逸意图(身份文件写入/特权位/root接管/系统关键路径破坏), "
                        "永不自动执行", SEV["critical"])

        # V-10 补充: 读取 SSH 私钥 / 系统凭证 —— 不是毁灭操作但**凭证外泄**危害等同,
        # 需硬拒 (跟 is_hard_redline 同级)。不放进 is_hard_redline 本体是因为
        # SafetyEngine.score() 调 is_hard_redline 升 risk 到 critical 会拉 RiskVector
        # engine_floor=10 让 composite 超过 8.0, 破坏 test_risk_sandbox 预期
        # (SafetyEngine 判 high 即可, IntentFilter 独立做 DENY)。
        try:
            from ..ext.safety_redline import _CRED_READ_RE_HARD
            cred_read_hard = _CRED_READ_RE_HARD
        except Exception:
            cred_read_hard = None
        if cred_read_hard is not None:
            for t in texts:
                if t.strip() and cred_read_hard.search(t):
                    return deny(self.name,
                                "读取 SSH 私钥/系统凭证 —— 凭证外泄等同毁灭, 永不自动执行",
                                SEV["critical"])

        # 数据外泄 / 远程执行: 网络门控判定为 deny 的红线
        try:
            from ..core.network_guard import get_network_guard
            guard = get_network_guard()
            for t in texts:
                if not t.strip():
                    continue
                dec = guard.check(t)
                if getattr(dec, "action", "") == "deny":
                    return deny(self.name,
                                "; ".join(getattr(dec, "reasons", []) or ["命中网络外泄/远程执行红线"]),
                                SEV["high"])
        except Exception:  # pragma: no cover
            pass

        # 内嵌凭据 (与 secret_scanner 同口径): 文本里出现 high 级明文密钥 → 需确认。
        # 放在红线/网络硬拒之后: 致命命令仍优先硬拒, 凭据泄露退到确认级。
        secret_v = _scan_embedded_secrets(texts)
        if secret_v is not None:
            return secret_v

        if _all_benign(texts):
            return Verdict(Action.ALLOW, layer=self.name, severity=SEV["low"],
                           reason="命令为良性开发操作")

        # 非良性但未致命: 不在此 deny, 交给 trust 滤网按工作区信任裁决
        return None


# ================================================================ L1 信任滤网
class TrustFilter:
    """L1 信任滤网: 工作区信任分级(fail-closed) + 计划模式 + 域名白名单。

    trusted 工作区直接放行(用户显式信任); untrusted 一律 deny;
    unknown / limited 的非良性操作需确认 —— 这是"默认开启、trusted 放行"的落点。
    """

    name = "trust"

    def __init__(self, *, deny_unknown_shell: bool = False) -> None:
        self._deny_unknown_shell = deny_unknown_shell

    @staticmethod
    def _is_readonly_tool(payload: Payload) -> bool:
        read_only = ("read", "search", "list", "glob", "diff", "log", "status", "plan")
        return any(payload.method in (r,) or r in payload.tool_name for r in read_only)

    def check(self, payload: Payload) -> Optional[Verdict]:
        if not payload.any_text and self._is_readonly_tool(payload):
            # 只读工具无可执行内容: 直接放行, 不挑衅
            return None

        lvl = payload.trust_level
        if lvl in ("untrusted",):
            if payload.any_text:
                return deny(self.name, "工作区为 untrusted, 禁止执行命令/写入操作", SEV["high"])
        elif lvl in ("unknown",):
            if payload.any_text and not payload.yolo:
                return confirm(self.name, "工作区信任级别未知, 需用户确认后方可执行")
        elif lvl in ("limited",):
            if payload.any_text and not _all_benign_safe(payload) and not payload.yolo:
                return confirm(self.name, "工作区为 limited 信任, 非良性操作需确认", SEV["medium"])

        # 计划模式: 写类型工具必须拒绝
        if payload.plan_mode and not self._is_readonly_tool(payload):
            if payload.any_text:
                return deny(self.name, "计划模式已启用, 禁止执行写/修改操作", SEV["medium"])

        # 域名白名单 (配置提供): 含域名但不在白名单 → deny
        allowed = payload.meta.get("allowed_domains")
        if allowed:
            try:
                from ..core.network_guard import get_network_guard
                guard = get_network_guard()
                for domain in self._detected_domains(payload, guard):
                    if domain not in allowed:
                        return deny(self.name, f"域名不在白名单: {domain}", SEV["high"])
            except Exception:  # pragma: no cover
                pass
        return None

    @staticmethod
    def _detected_domains(payload: Payload, guard: Any) -> List[str]:
        out: List[str] = []
        for t in payload.text:
            if not t.strip():
                continue
            try:
                dec = guard.check(t)
                out.extend(getattr(dec, "detected_domains", None) or [])
            except Exception:  # pragma: no cover
                pass
        return list(dict.fromkeys(out))


def _all_benign_safe(payload: Payload) -> bool:
    texts = payload.text or ([payload.command] if payload.command else [])
    return _all_benign(texts)


# ================================================================ L2 资源滤网
_SEV_RANK = {SEV["none"]: 0, SEV["low"]: 1, SEV["medium"]: 2, SEV["high"]: 3, SEV["critical"]: 4}


class ResourceFilter:
    """L2 资源滤网: 网络开关 + 内存/超时 + 工作区隔离模式选择。

    不主动拒绝; 它把"该不该上 L3 强隔离"以及"隔离时用哪种工作区模式"决定下来,
    并把网络/资源边界写进 Verdict 供执行端消费。
    """

    name = "resource"

    def __init__(
        self,
        *,
        deny_network_by_default: bool = False,
        max_memory_mb: int = 0,
        max_timeout: float = 0.0,
        isolate_copy_threshold: str = "high",
    ) -> None:
        self._deny_net = deny_network_by_default
        self._mem = max_memory_mb
        self._timeout = max_timeout
        self._copy_threshold = isolate_copy_threshold

    def check(self, payload: Payload) -> Optional[Verdict]:
        if not payload.any_text:
            return None
        v = Verdict(layer=self.name)
        v.memory_mb = self._mem
        v.timeout = self._timeout

        sev = payload.meta.get("severity") or SEV["none"]
        # 高危可逆操作 → 副本→diff→apply; 低危 → 直接执行(限路径)
        if _SEV_RANK.get(sev, 0) >= _SEV_RANK.get(self._copy_threshold, 3):
            v.workspace_mode = "copy_diff_apply"
            v.isolate = True

        wants_net = _has_network_request(payload.text)
        if wants_net and self._deny_net:
            v.network = False
            v.isolate = True
            v.reason = "策略默认禁网, 含网络请求的命令改走无网隔离执行"
        return v


# ================================================================ L3 强隔离滤网
class HardIsolationFilter:
    """L3 强隔离滤网: 隔离后端自动选择 (docker→bwrap→jobobject→local)。

    - 只有当 L2/意图已 decide 需要隔离(isolate) 时才介入。
    - 后端自动探测可用性; enforced=True 且无可用强后端 → deny (fail-closed)。
    这才是"超越 CodeX 单容器方案"的关键: 强后端缺失时不静默降级到裸执行, 而是拒绝。
    """

    name = "hard"

    def __init__(self, *, prefer: str = "auto", enforce_require: bool = True) -> None:
        self._prefer = prefer
        self._enforce = enforce_require

    def check(self, verdict: Verdict, payload: Payload) -> Optional[Verdict]:
        if not verdict.isolate:
            return None  # 不需要强隔离, 不触发后端
        from .backends import pick_backend
        backend, available = pick_backend(prefer=self._prefer)
        # "强后端" = 具备 OS 级隔离的真实贡献者 (docker/bwrap/jobobject/seatbelt), local 不算
        strong = available and backend != "local"
        if self._enforce and not strong:
            return verdict.merged(
                deny(self.name,
                     f"需要强隔离执行, 但无可用强后端(仅回落到 {backend}): fail-closed 拒绝",
                     SEV["critical"])
            )
        return verdict.merged(
            Verdict(layer=self.name, backend=backend,
                    backend_available=strong, enforced=strong or self._enforce)
        )


# ================================================================ 编排链
@dataclass
class SandboxFilterChain:
    """4 层滤网流水线: 依序求值, 逐层收紧, 拒绝即短路。"""

    intent: IntentFilter = field(default_factory=IntentFilter)
    trust: TrustFilter = field(default_factory=TrustFilter)
    resource: ResourceFilter = field(default_factory=ResourceFilter)
    hard: HardIsolationFilter = field(default_factory=HardIsolationFilter)

    # 其它先进可插拔滤网 (如 ai 语义滤网 / 政策规则滤网), 默认空
    extras: List[Any] = field(default_factory=list)

    def _order(self) -> Any:
        yield self.intent
        yield self.trust
        yield from self.extras
        yield self.resource
        yield self.hard

    def evaluate(self, payload: Payload) -> Verdict:
        v = Verdict()
        for filt in self._order():
            if filt is self.hard:
                out = self.hard.check(v, payload)
            elif isinstance(filt, (ResourceFilter, TrustFilter, IntentFilter)):
                out = filt.check(payload)
            else:
                try:
                    out = filt.check(payload, v)
                except Exception:  # noqa: BLE001
                    out = deny("extras", "扩展滤网异常, fail-closed", SEV["high"])
            if out is not None:
                v = v.merged(out)
                if v.blocks:
                    break
        return v


def build_chain(policy: Optional[Dict[str, Any]] = None) -> SandboxFilterChain:
    """按配置构建 4 层滤网链。"""
    policy = policy or {}
    resource = policy.get("resource", {})
    return SandboxFilterChain(
        trust=TrustFilter(deny_unknown_shell=bool(policy.get("deny_unknown_shell", False))),
        resource=ResourceFilter(
            deny_network_by_default=bool(resource.get("deny_network_by_default", False)),
            max_memory_mb=int(resource.get("max_memory_mb", 0) or 0),
            max_timeout=float(resource.get("max_timeout", 0) or 0),
            isolate_copy_threshold=resource.get("isolate_copy_threshold", "high"),
        ),
        hard=HardIsolationFilter(
            prefer=policy.get("backend", "auto"),
            enforce_require=bool(policy.get("enforce_required", True)),
        ),
    )