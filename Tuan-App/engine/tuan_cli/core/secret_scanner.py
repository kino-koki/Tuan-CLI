"""密钥泄露扫描器 (Secret Scanner) —— 扫描项目文本/文件中的明文密钥并给修复建议。

背景: 旧安全栈里有两类能力, 但缺一个"扫描器":
- ``security_utils.redact_sensitive``: 把密钥 **遮蔽** 掉 (写审计日志时脱敏), 是被动脱敏;
- ``security_classifier``: 判断一条 **命令** 是否在访问敏感文件, 是命令级裁决。

官方 ``/security`` 还要求一项: 对目标项目做 **密钥泄露扫描** —— 把已经写进
源码/配置里的明文 API Key / 私钥揪出来, 按严重度分级并给出修复建议。本模块补齐
这块, 作为可独立测试的纯函数库, 结果可汇入安全事件总线 (审计留痕)。

扫描规则 (确定性正则, 不依赖网络/外部漏洞库):
- AWS Access Key ID (AKIA...);
- GitHub token (ghp_/gho_/ghs_/ghu_...);
- OpenAI / Anthropic 风格 sk-...;
- JWT (eyJ...);
- PEM 私钥块 (BEGIN ... PRIVATE KEY);
- 明文 key=value / key: value 赋值。

每个发现返回: 类型 / 所在行 / 严重度 / 修复建议。命中值本身只记录前后缀,
不把完整密钥写进结果 (避免二次泄露)。
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, List, Optional


# ------------------------------------------------------------ 规则定义

@dataclass(frozen=True)
class SecretRule:
    """一条密钥匹配规则。"""
    secret_type: str
    pattern: re.Pattern
    severity: str          # high / medium / low
    description: str
    remediation: str


def _p(regex: str) -> re.Pattern:
    return re.compile(regex)


_RULES: List[SecretRule] = [
    SecretRule(
        secret_type="aws_access_key",
        pattern=_p(r"\bAKIA[0-9A-Z]{16}\b"),
        severity="high",
        description="AWS Access Key ID",
        remediation="从 AWS IAM 禁用并轮换该 Access Key; 代码改用环境变量 "
                    "(AWS_ACCESS_KEY_ID), 并把该提交从 git 历史清除 (git filter-repo)。",
    ),
    SecretRule(
        secret_type="github_token",
        pattern=_p(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
        severity="high",
        description="GitHub Personal Access Token",
        remediation="立即到 GitHub Settings → Developer settings 撤销该 token, "
                    "改用 GitHub App / 短期 token; 移除历史中的明文。",
    ),
    SecretRule(
        secret_type="openai_style_key",
        pattern=_p(r"\bsk-[A-Za-z0-9\-_]{20,}\b"),
        severity="high",
        description="OpenAI/Anthropic 风格 API Key",
        remediation="到对应 Provider 控制台吊销该 key, 改走环境变量 "
                    "(OPENAI_API_KEY / ANTHROPIC_API_KEY), 不要提交进仓库。",
    ),
    SecretRule(
        secret_type="jwt",
        pattern=_p(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\b"),
        severity="medium",
        description="JSON Web Token (JWT)",
        remediation="JWT 通常应短时有效; 若为长期令牌请吊销, 改用受控签发流程。",
    ),
    SecretRule(
        secret_type="private_key_block",
        pattern=_p(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
        severity="high",
        description="PEM 私钥块",
        remediation="私钥绝不能入库; 立即从仓库删除并轮换对应证书/密钥, "
                    "把私钥放到 ~/.ssh 或密钥管理服务, 仓库只保留公钥。",
    ),
    SecretRule(
        secret_type="generic_api_key_assignment",
        pattern=_p(
            r"(?i)(api[_-]?key|api[_-]?secret|secret[_-]?key|access[_-]?key|"
            r"client[_-]?secret)\s*[:=]\s*[\"']?[A-Za-z0-9_\-]{16,}[\"']?"
        ),
        severity="medium",
        description="明文 API 密钥赋值",
        remediation="把硬编码密钥改为从环境变量/密钥管理读取, 并轮换已暴露的密钥。",
    ),
]


# ------------------------------------------------------------ 发现结果

@dataclass
class SecretFinding:
    """一条密钥泄露发现。"""
    secret_type: str
    description: str
    severity: str
    line: int
    # 命中值前后缀 (脱敏展示), 不记录完整密钥
    preview: str
    remediation: str
    path: str = ""

    def to_dict(self) -> dict:
        return {
            "secret_type": self.secret_type,
            "description": self.description,
            "severity": self.severity,
            "line": self.line,
            "preview": self.preview,
            "remediation": self.remediation,
            "path": self.path,
        }


def _mask_hit(text: str) -> str:
    """命中片段脱敏: 仅保留前 4 后 4 字符, 中间打码。"""
    text = text.strip()
    if len(text) <= 8:
        return text[:2] + "***"
    return f"{text[:4]}…{text[-4:]}"


def scan_text(content: str, *, path: str = "") -> List[SecretFinding]:
    """扫描一段文本, 返回命中的密钥发现 (按出现顺序)。绝不抛异常。"""
    findings: List[SecretFinding] = []
    if not content:
        return findings
    lines = content.splitlines()
    for rule in _RULES:
        for m in rule.pattern.finditer(content):
            line_no = content.count("\n", 0, m.start()) + 1
            hit = m.group(0)
            # 防御: 命中值不完整保留
            findings.append(SecretFinding(
                secret_type=rule.secret_type,
                description=rule.description,
                severity=rule.severity,
                line=line_no,
                preview=_mask_hit(hit),
                remediation=rule.remediation,
                path=path,
            ))
    # 按行号排序, 便于阅读
    findings.sort(key=lambda f: (f.line, f.secret_type))
    return findings


# 扫描目录时跳过的目录名 (避免扫描 .git / 依赖目录等噪声)
_DEFAULT_SKIP_DIRS = {
    ".git", ".hg", ".svn", "node_modules", "__pycache__", ".venv", "venv",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", "dist", "build", ".tuan",
}
# 单文件大小上限 (字节), 超过不扫, 避免读超大二进制文件
_MAX_FILE_BYTES = 1_000_000


def scan_file(file_path: Path) -> List[SecretFinding]:
    """扫描单个文件 (读取失败/过大/二进制则跳过)。"""
    try:
        p = Path(file_path)
        if not p.is_file():
            return []
        if p.stat().st_size > _MAX_FILE_BYTES:
            return []
        raw = p.read_bytes()
        # 粗判二进制: 含 NUL 字节则跳过
        if b"\x00" in raw:
            return []
        text = raw.decode("utf-8", errors="ignore")
    except OSError:
        return []
    return scan_text(text, path=str(p))


def scan_directory(
    root: Path,
    *,
    skip_dirs: Optional[Iterable[str]] = None,
    max_files: int = 2000,
) -> List[SecretFinding]:
    """递归扫描目录中的所有文本文件, 聚合发现。

    - 跳过 ``skip_dirs`` 指定的目录 (默认 ``_DEFAULT_SKIP_DIRS``);
    - 最多扫描 ``max_files`` 个文件, 防止对巨型仓库无限递归;
    - 任何单个文件失败都不影响整体扫描。
    """
    root = Path(root)
    if not root.exists():
        return []
    skip = set(_DEFAULT_SKIP_DIRS if skip_dirs is None else skip_dirs)
    findings: List[SecretFinding] = []
    scanned = 0
    for dirpath, dirnames, filenames in os.walk(root):
        # 原地剪枝: 不进入跳过目录
        dirnames[:] = [d for d in dirnames if d not in skip]
        for fn in filenames:
            if scanned >= max_files:
                return findings
            fp = Path(dirpath) / fn
            findings.extend(scan_file(fp))
            scanned += 1
    return findings


# ------------------------------------------------------------ 与安全总线集成

def emit_findings(bus, findings: List[SecretFinding]) -> int:
    """把高危发现汇入安全事件总线, 返回汇入条数 (bus 为 None 时返回 0)。

    用于审计留痕: 扫描出的密钥泄露事件可在 ``security_bus`` / 审计日志中追溯。
    """
    if bus is None or not findings:
        return 0
    from .security_bus import SecurityEvent
    n = 0
    for f in findings:
        if f.severity not in ("high", "medium"):
            continue
        try:
            bus.emit(SecurityEvent(
                event_type="security.secret.leak",
                timestamp=__import__("time").time(),
                payload={
                    "secret_type": f.secret_type,
                    "description": f.description,
                    "path": f.path,
                    "line": f.line,
                    "preview": f.preview,
                },
                source="secret_scanner",
                severity=f.severity,
            ))
            n += 1
        except Exception:  # noqa: BLE001  总线异常不能炸掉扫描
            continue
    return n


def summarize(findings: List[SecretFinding]) -> str:
    """生成人类可读的扫描报告 (CLI / TUI 输出用)。"""
    if not findings:
        return "✓ 未发现明文密钥泄露"
    by_sev: dict = {"high": [], "medium": [], "low": []}
    for f in findings:
        by_sev.setdefault(f.severity, []).append(f)
    lines = [f"发现 {len(findings)} 处疑似密钥泄露:"]
    for sev in ("high", "medium", "low"):
        group = by_sev.get(sev, [])
        if not group:
            continue
        lines.append(f"\n[{sev.upper()}] {len(group)} 处:")
        for f in group:
            loc = f.path or "(文本)"
            lines.append(f"  - {f.description} @ {loc}:{f.line}  ({f.preview})")
            lines.append(f"    建议: {f.remediation}")
    return "\n".join(lines)
