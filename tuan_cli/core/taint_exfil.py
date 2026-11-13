"""污点追踪外泄检测器 (v0.4.0 新增安全防线)。

多路防御的第三条独立路径, 与规则引擎 (模式匹配) 和语义分类器 (特征加权)
**互补**: 本模块做**数据流分析** —— 追踪「敏感源」是否可能流向「外部汇」。

设计原则 (与既有安全栈一致):
- **fail-closed**: 任何分析异常都不放行, 保守返回 confirm。
- **只收紧不放行**: 本模块的 verdict 只会把 allow 升级为 confirm/deny,
  绝不降低其他路径的判决。
- **数据流而非关键词**: 即使命令不含已知危险关键词, 只要「敏感文件/变量」
  被重定向/管道/编码/网络发送到外部, 就判定外泄风险。

敏感源 (sources): 凭证 / 密钥 / 认证 / 环境 / 历史等。
外部汇 (sinks): 网络发送 / 编码外传 / 远程管道 / 剪贴板上传等。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional, Tuple

__all__ = [
    "ExfilVerdict",
    "detect_exfiltration",
    "has_taint_flow",
]

# ===== 敏感源 (taint sources) =====
# 凭证 / 密钥 / 认证文件 / 进程环境 / shell 历史 / 云凭据。
_SOURCES: Tuple[re.Pattern, ...] = (
    re.compile(r"\.ssh/", re.IGNORECASE),
    re.compile(r"\.aws/|aws_credentials|AWS_SECRET|AWS_ACCESS_KEY", re.IGNORECASE),
    re.compile(r"\.kube/config|\.docker/config\.json|\.netrc|\.git-credentials", re.IGNORECASE),
    re.compile(r"\.env\b|\.envrc|credentials\.json|secrets?\.(yaml|yml|json|env)", re.IGNORECASE),
    re.compile(r"/etc/(shadow|sudoers|ssh/)", re.IGNORECASE),
    re.compile(r"id_rsa|id_ed25519|id_dsa|\.pem\b|\.key\b|\.p12\b|keystore", re.IGNORECASE),
    re.compile(r"\bhistory\b|\.bash_history|\.zsh_history|\.python_history", re.IGNORECASE),
    re.compile(r"\$\{?(?:HOME|USER|PATH|SHELL|SSH_AUTH_SOCK|GITHUB_TOKEN|OPENAI_API_KEY|"
               r"ANTHROPIC_API_KEY|SLACK_TOKEN|DATABASE_URL|POSTGRES_PASSWORD)\b", re.IGNORECASE),
    re.compile(r"~/(?:\.ssh|\.aws|\.gnupg|\.kube|\.docker)/", re.IGNORECASE),
)

# ===== 外部汇 (taint sinks): 把数据送出本机的通道 =====
_SINKS_NET: Tuple[re.Pattern, ...] = (
    # 网络外发 (含把本地数据 POST/上传)
    re.compile(r"\b(?:curl|wget|nc|ncat|netcat|socat|telnet|ftp|sftp|scp|rsync|sync)\b", re.IGNORECASE),
    # ssh host 形式 (要求 ssh 后跟空格+主机名, 避免命中 ~/.ssh/ 文件路径)
    re.compile(r"\bssh\s+(?:-\S+\s+)*[\w@]", re.IGNORECASE),
    re.compile(r"https?://|ftp://|\b[\w.-]+\.(?:onion|to|xyz|ru|cn)\b"),
    # DNS 外泄通道 (把数据塞进子域)
    re.compile(r"\bdig\b|\bnslookup\b|\bhost\b|\bdrill\b"),
)

_SINKS_ENCODE: Tuple[re.Pattern, ...] = (
    # 编码外传 (把数据转成可外发的形式, 常与网络命令串联)
    re.compile(r"\bbase64\b|\bb64\b|\bxxd\b|\bhex\b|\brot13\b|\bgzip\b|\bzip\b|\btar\b", re.IGNORECASE),
    # 剪贴板 / 上传 / 远程粘贴
    re.compile(r"\bpbcopy\b|\bxclip\b|\bxsel\b|\bwl-copy\b|\bclip\.exe\b", re.IGNORECASE),
    # 远程 shell 反弹
    re.compile(r"/dev/tcp/|/dev/udp/|\bbash\s+-i\b.*>\s*&|mkfifo.*\|\s*(?:nc|bash)", re.IGNORECASE),
)

# 数据流出通道 (本地算子): 重定向 / 管道 / 命令替换 / tee / 拷贝移动。
# 重定向用 `(?!/dev/null\b)` 排除丢弃输出 —— `cat id_rsa > /dev/null` 不是外泄。
# 注意: 输入重定向 `< f` 只有在配对网络/编码汇时才算外发通道 (pbcopy < id_rsa),
# 单独 `< f` 不触发 (避免 `cat < README.md` 这类纯读被误判)。
_FLOW_REDIRECT = re.compile(r">\s*(?!/dev/null\b)[^\s|;&]", re.IGNORECASE)
_FLOW_PIPE = re.compile(r"\|", re.IGNORECASE)
_FLOW_CMD_SUB = re.compile(r"\$\(|`", re.IGNORECASE)
_FLOW_TEE = re.compile(r"\btee\b", re.IGNORECASE)
# 本地外泄通道: 把敏感文件搬到别处 (即使不到网络, 也可能是外泄前的落盘)
_FLOW_COPY = re.compile(r"\b(?:cp|mv|install|dd)\b", re.IGNORECASE)


def _has_local_flow(command: str) -> bool:
    """本地数据移动算子 (不含 `< input`, 那个只在配对 sink 时才计)。"""
    return bool(
        _FLOW_REDIRECT.search(command)
        or _FLOW_PIPE.search(command)
        or _FLOW_CMD_SUB.search(command)
        or _FLOW_TEE.search(command)
        or _FLOW_COPY.search(command)
    )


@dataclass
class ExfilVerdict:
    """外泄检测结果。action ∈ {"allow", "confirm", "deny"}。"""

    action: str
    severity: str
    reasons: Tuple[str, ...]
    sources: Tuple[str, ...] = ()
    sinks: Tuple[str, ...] = ()

    def blocks(self) -> bool:
        return self.action == "deny"

    def needs_confirm(self) -> bool:
        return self.action == "confirm"


def _find_sources(command: str) -> List[str]:
    hits: List[str] = []
    for pat in _SOURCES:
        m = pat.search(command)
        if m:
            hits.append(m.group(0))
    return hits


def _find_sinks(command: str) -> Tuple[List[str], List[str]]:
    net: List[str] = []
    encode: List[str] = []
    for pat in _SINKS_NET:
        m = pat.search(command)
        if m:
            net.append(m.group(0))
    for pat in _SINKS_ENCODE:
        m = pat.search(command)
        if m:
            encode.append(m.group(0))
    return net, encode


def has_taint_flow(command: str) -> Tuple[bool, List[str], List[str], List[str]]:
    """判断命令是否存在「敏感源 → 外部汇」的污点流。

    返回 (has_flow, sources, net_sinks, encode_sinks)。

    判定逻辑:
    - 敏感源 + 网络/编码汇 → 污点流 (网络汇本身即外发通道, 无需额外算子)
    - 敏感源 + 本地流出算子 (重定向/管道/tee/拷贝/cmd-sub) → 污点流
    - 敏感源 + `< file` + 网络/编码汇 → 污点流 (pbcopy < id_rsa)
    - 敏感源 + `< file` 单独出现, 无外发汇 → 不算 (纯读场景)
    - 敏感源单独出现 (如 `ls ~/.ssh/`) → 不算
    """
    sources = _find_sources(command)
    if not sources:
        return (False, [], [], [])
    net, encode = _find_sinks(command)
    local_flow = _has_local_flow(command)
    # 网络/编码汇本身即外发通道, 自动满足;
    # 本地拷贝/重定向/管道等算子作为补充外发通道。
    if sources and (net or encode or local_flow):
        return (True, sources, net, encode)
    return (False, sources, net, encode)


def detect_exfiltration(command: str) -> ExfilVerdict:
    """对外泄风险做 fail-closed 判定。

    - 敏感源 + 网络汇 + 流出通道 → deny (critical): 凭证外传几乎必然是攻击。
    - 敏感源 + 编码汇 + 流出通道 → confirm (high): 可能是正常打包, 但需人工确认。
    - 反弹 shell (dev/tcp 等) → deny (critical)。
    - 无污点流 / 分析异常 → allow (不收紧)。
    """
    try:
        has_flow, sources, net, encode = has_taint_flow(command)
        if not has_flow:
            # 反弹 shell 即使无敏感源也属高危 (含 nc -e / nc ... | sh 等变体)
            if re.search(
                r"/dev/tcp/|/dev/udp/|mkfifo.*\|\s*(?:nc|bash)|\bnc\s+-\w*e\b|\bncat\s+-\w*e\b",
                command, re.IGNORECASE,
            ):
                return ExfilVerdict(
                    action="deny", severity="critical",
                    reasons=("检测到反弹 shell (网络外联通道)",),
                )
            return ExfilVerdict(action="allow", severity="none", reasons=())

        detail = "、".join(list(dict.fromkeys(sources + net + encode))[:4])
        if net:
            return ExfilVerdict(
                action="deny", severity="critical",
                reasons=(f"污点追踪: 敏感数据经网络外发 ({detail}) —— 疑似凭证外泄",),
                sources=tuple(sources), sinks=tuple(net),
            )
        # 编码汇 / 拷贝汇: 可能是合法打包或本地备份, 但敏感源 + 外传通道需人工确认
        return ExfilVerdict(
            action="confirm", severity="high",
            reasons=(f"污点追踪: 敏感数据被编码/复制/外传 ({detail}) —— 需确认是否外泄",),
            sources=tuple(sources), sinks=tuple(encode),
        )
    except Exception:  # noqa: BLE001 - fail-closed
        return ExfilVerdict(
            action="confirm", severity="high",
            reasons=("污点追踪检测器异常, 保守要求人工确认",),
        )
