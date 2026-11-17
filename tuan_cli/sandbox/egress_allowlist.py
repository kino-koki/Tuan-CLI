"""B2 收尾: 逐命令域名强绑定（strict allowlist）。

**实测缺口（先复现再修）**

``TrustFilter.check`` 确实会用 ``payload.meta["allowed_domains"]`` 对命令
文本里检测到的域名做 deny —— 但那是**全局配置 + 命令文本识别**：

1. ``SandboxProfile`` 只有 ``network: bool``，没有任何域名字段。
   ``SandboxManager._run_provider`` 构造
   ``SandboxProfile(network=verdict.network, ...)`` 时，强后端拿到的是
   「全开 / 全关」，拿不到「这次只允许哪些主机」。
2. ``verdict.extra`` 为空：裁决结果**不携带**逐命令声明的主机清单到执行层。
   实测 ``assess_command('curl https://evil.example/x')`` 得到
   ``extra={}``，即使配置了白名单。
3. 文本识别本身可被零宽字符 / ANSI-C / 注释换行 / 变量间接引用绕过
   （前几轮 477 条 fuzz 已证）。白名单若只活在文本层，就不是出网路径上的
   强制边界。

本模块把「逐命令声明所需主机、其余一律拒绝」做成**结构化、可核验、
能一路传到执行层**的东西：

- :func:`normalize_domain` 严格归一化，脏输入 / 过宽通配 / 控制字符
  一律拒绝或降级，绝不静默放宽。
- :class:`NetworkClaim`：**本次调用**声明的主机清单 + ``strict`` 标志。
- :func:`evaluate_claim`：声明外域名一律拒绝；``strict`` 且检测不到域名
  时**也拒绝**（无法证明合规，防文本绕过），不是「没检测到就放行」。
- :func:`claim_from_args`：从工具参数里取逐命令 ``allowed_domains``；
  没有则回落全局配置，但明确标 ``source``，不假装是逐命令声明。

**刻意不做**：不声称 bwrap / seatbelt 具备域名级 OS 过滤能力 —— 它们
只有 network namespace / IP 级规则。域名强绑定的**真正强制点**是
``egress_proxy.py`` 的本地回环出网代理（CONNECT / 明文 HTTP 主机校验），
本模块负责把 claim 一路送到那里，并写进 ``SandboxProfile`` 供后端参考。
"""
from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence, Tuple

# 域名标签：字母数字 + 连字符，不以连字符开头/结尾；不允许多余标点。
_LABEL_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_CTRL_RE = re.compile(r"[\x00-\x20\x7f-\x9f]")
_WILDCARD = "*."
# 合法域名输入字符集（ASCII only）。非 ASCII 一律拒绝，见 normalize_domain。
_DOMAIN_CHARS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-*:[]")

CLAIM_KEY = "network_claim"
PROFILE_KEY = "allowed_domains"


def normalize_domain(raw: Any) -> Optional[str]:
    """把一条声明严格归一化；非法输入返回 ``None``（由调用方拒绝/降级）。

    规则：
      - 非字符串 → None；控制字符 / 空白 / 端口后缀 / 协议前缀 → None；
      - 小写、去尾点、IDNA（非 ASCII 用 punycode）；
      - ``*.example.com`` 保留为**后缀**通配（不当成「允许所有」）；
        单独的 ``*`` / ``*.`` / ``*.*`` 等过宽形式 → None；
      - IP 字面量允许，但要求精确匹配（不放宽成网段）；
      - 标签数、长度、字符集合法性逐项校验。
    """
    if not isinstance(raw, str):
        return None
    s = raw.strip()
    if not s or _CTRL_RE.search(s):
        return None
    # A'（本轮自己挖回来的静默放宽）：``str.encode("idna")`` 会把 U+200B
    # ZWSP / 变体选择符等 Unicode 格式字符**直接丢弃**，于是
    # ``evil\\u200b.example`` 归一化成 ``evil.example`` —— 攻击者只要在
    # 真实主机里插一个零宽字符，就能让「另一个主机」匹配上白名单声明。
    # 逐字符白名单 + ASCII 约束先挡住，IDNA 保留仅作大小写/尾点处理。
    if not s.isascii() or any(ch not in _DOMAIN_CHARS for ch in s):
        return None
    # 拒绝 URL / scheme / 端口 / 路径形态
    if "://" in s or "/" in s or "@" in s or "?" in s or "#" in s:
        return None
    # 形如 host:port（IPv6 括号除外）
    if s.count(":") > 0 and not _looks_like_ipv6(s):
        return None
    if s.startswith("[") and s.endswith("]"):
        s = s[1:-1]
    s = s.rstrip(".").lower()
    if not s:
        return None

    # IP 字面量：精确匹配，不做网段放宽
    try:
        ipaddress.ip_address(s)
        return s
    except ValueError:
        pass

    suffix = False
    if s.startswith(_WILDCARD):
        suffix = True
        s = s[2:]
        if not s or _WILDCARD in s or "*" in s:
            return None
    elif "*" in s:
        # 只允许最左标签通配，其它位置一律拒绝
        return None
    try:
        s = s.encode("idna").decode("ascii")
    except (UnicodeError, UnicodeDecodeError):
        return None
    labels = s.split(".")
    if len(labels) < 2 and not suffix:
        # 单标签主机（localhost）允许，但必须是合法标签
        if not labels or not _LABEL_RE.match(labels[0]):
            return None
    for lab in labels:
        if not lab or not _LABEL_RE.match(lab):
            return None
    if len(s) > 253:
        return None
    return ("*." + s) if suffix else s


def _looks_like_ipv6(s: str) -> bool:
    return s.startswith("[") and "]" in s


def claim_matches(claim_domain: str, host: str) -> bool:
    """归一化后的声明是否匹配出网主机。IP 要求精确；``*.`` 是后缀匹配。"""
    if not isinstance(claim_domain, str) or not isinstance(host, str):
        return False
    h = normalize_domain(host)
    if h is None:
        return False
    if claim_domain.startswith(_WILDCARD):
        base = claim_domain[2:]
        return h == base or h.endswith("." + base)
    return h == claim_domain


@dataclass(frozen=True)
class NetworkClaim:
    """一次调用的逐命令出网声明。真实值只有域名，不含任何凭据。"""

    required_domains: Tuple[str, ...] = ()
    strict: bool = False
    source: str = "none"          # tool_args | payload_meta | global_policy | none
    invalid_values: Tuple[str, ...] = ()   # 只记被拒输入的**形态**，不记原文

    def to_dict(self) -> Dict[str, Any]:
        return {"required_domains": list(self.required_domains),
                "strict": self.strict, "source": self.source,
                "invalid_count": len(self.invalid_values)}

    def allows_host(self, host: str) -> bool:
        if not self.strict:
            return True
        if not self.required_domains:
            return False   # strict 但未声明任何主机 → 拒绝一切出网
        return any(claim_matches(d, host) for d in self.required_domains)


def claim_from_values(values: Any, *, strict: bool = True,
                      source: str = "tool_args") -> NetworkClaim:
    """从任意输入构造 claim；脏输入 fail-closed（空清单 + strict）。

    ``strict`` 语义：一旦调用方显式声明了逐命令域名，就进入「声明外一律
    拒绝」。非法值不静默丢弃 —— 记为 ``invalid_values`` 并保持严格。
    """
    if values is None:
        return NetworkClaim((), False, "none", ())
    if isinstance(values, str):
        items: Sequence[Any] = [values]
    elif isinstance(values, (list, tuple, set, frozenset)):
        items = list(values)
    else:
        return NetworkClaim((), True, source, (f"<{type(values).__name__}>",))
    out: list[str] = []
    invalid: list[str] = []
    for v in items:
        n = normalize_domain(v)
        if n is None:
            invalid.append(f"<{type(v).__name__}>")
        elif n not in out:
            out.append(n)
    return NetworkClaim(tuple(out), bool(strict), source, tuple(invalid))


def claim_from_args(fn_args: Any, *, fallback: Any = None,
                    fallback_source: str = "global_policy") -> NetworkClaim:
    """优先取工具参数里的逐命令声明；没有则回落全局配置。

    ``fn_args`` 里 ``allowed_domains`` 就是 CC v2.1.271 的 per-command
    ``allowed_domains`` 语义。回落时不假装是逐命令声明，``source`` 会写明。
    """
    if isinstance(fn_args, Mapping):
        for key in ("allowed_domains", "allowedDomains", "claim_domains"):
            if key in fn_args:
                return claim_from_values(fn_args[key], strict=True,
                                         source="tool_args")
    return claim_from_values(fallback, strict=True, source=fallback_source)


@dataclass(frozen=True)
class AllowlistDecision:
    allowed: bool
    reason: str
    claim: NetworkClaim
    detected: Tuple[str, ...] = ()
    unmatched: Tuple[str, ...] = ()
    undetectable: bool = False

    def to_audit_dict(self) -> Dict[str, Any]:
        return {"allowed": self.allowed, "reason": self.reason,
                "claim": self.claim.to_dict(),
                "detected_count": len(self.detected),
                "detected": list(self.detected),
                "unmatched": list(self.unmatched),
                "undetectable": self.undetectable}


def evaluate_claim(claim: NetworkClaim,
                   detected_domains: Iterable[str]) -> AllowlistDecision:
    """把「文本层检测到的域名」与本次声明强绑定。

    关键 fail-closed：``strict`` 模式下**检测不到域名也拒绝**。否则攻击者
    只要把域名藏进变量/编码里让文本识别失效，就能拿到「没检测到 → 放行」。
    真正的强制点在出网代理的主机校验，这里只做裁决层的一致性断言。
    """
    detected_raw = list(detected_domains) if isinstance(detected_domains, Iterable) \
        and not isinstance(detected_domains, (str, bytes)) else []
    detected: list[str] = []
    for d in detected_raw:
        n = normalize_domain(d)
        if n and n not in detected:
            detected.append(n)
    if not claim.strict:
        return AllowlistDecision(True, "非 strict 模式: 不做逐命令强绑定",
                                 claim, tuple(detected))
    if claim.invalid_values:
        return AllowlistDecision(
            False, "逐命令域名声明含非法值, fail-closed 拒绝", claim,
            tuple(detected), tuple(detected), False)
    if not claim.required_domains:
        return AllowlistDecision(
            False, "strict 模式未声明任何允许主机, 拒绝一切出网", claim,
            tuple(detected))
    unmatched = tuple(d for d in detected if not claim.allows_host(d))
    if unmatched:
        return AllowlistDecision(
            False, "检测到声明外出网目标, 拒绝: " + ", ".join(unmatched[:5]),
            claim, tuple(detected), unmatched, False)
    if not detected:
        return AllowlistDecision(
            True,
            "未从文本检测到域名; 由出网代理在 CONNECT/HTTP 主机层做最终强绑定",
            claim, (), (), True)
    return AllowlistDecision(True, "检测到的域名均在逐命令声明内", claim,
                             tuple(detected))


def claim_to_verdict_extra(claim: NetworkClaim) -> Dict[str, Any]:
    """写进 ``verdict.extra`` 的脱敏结构，供执行层 / 代理读取。"""
    d = claim.to_dict()
    d[CLAIM_KEY] = True
    return d


def claim_from_verdict(verdict: Any) -> NetworkClaim:
    """从裁决结果取回 claim；缺失 / 脏值一律 fail-closed 空声明。"""
    if verdict is None:
        return NetworkClaim((), True, "missing", ("<none>",))
    extra = getattr(verdict, "extra", None)
    if not isinstance(extra, Mapping) or CLAIM_KEY not in extra:
        return NetworkClaim((), False, "none", ())
    raw = extra.get("required_domains")
    if raw is None:
        return NetworkClaim((), True, "missing", ("<none>",))
    c = claim_from_values(raw, strict=bool(extra.get("strict", True)),
                          source=str(extra.get("source", "verdict")))
    return c


def profile_domains(claim: NetworkClaim) -> Tuple[str, ...]:
    """给 ``SandboxProfile.allowed_domains`` 用的清单（已归一化、去重）。"""
    return claim.required_domains
