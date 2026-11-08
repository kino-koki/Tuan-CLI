"""共享安全工具 —— 环境变量脱敏等跨模块复用的安全原语。

消除 core/sandbox.py + core/sandbox_provider.py + arch/security.py +
tools/mcp/sandbox.py 中重复的 _sanitize_env / SECRET_HINTS 定义。
"""

from __future__ import annotations

import re
import os
from typing import Any, Dict, Mapping, Optional, Sequence


# 出网凭据脱敏占位符前缀。与 sandbox/egress.py::SENTINEL_PREFIX 同值；
# 放在共享原语层避免 core -> sandbox 的反向导入（循环），并有回归断言
# 两边常量恒等。占位符**不是**真实密钥，脱敏链路上必须原样保留，
# 否则下游出网代理拿不到可用于 inject_headers() 还原的标记。
MASKED_PLACEHOLDER_PREFIX: str = "tuan-egress-sentinel-v1:"


def is_masked_placeholder(value: Any) -> bool:
    """判断一个环境变量值是否已是脱敏占位符（而非真实凭据）。"""
    return (isinstance(value, str)
            and value.startswith(MASKED_PLACEHOLDER_PREFIX))


# 敏感环境变量名片段 (统一来源, 所有沙箱/安全模块从此处导入)
SECRET_HINTS: tuple = (
    "API_KEY", "SECRET", "TOKEN", "PASSWORD", "PASSWD", "PRIVATE_KEY",
    "ACCESS_KEY", "CREDENTIAL", "AUTH",
    # 项目前缀
    "TUAN_",
    # 主流 Provider
    "OPENAI", "ANTHROPIC", "DEEPSEEK", "MOONSHOT", "DASHSCOPE",
    "ZHIPU", "GROQ", "SILICONFLOW",
    # 云平台
    "AWS_", "GCP", "AZURE", "DATABASE_URL",
)


def sanitize_env(
    base: Optional[Dict[str, str]] = None,
    extra: Optional[Dict[str, str]] = None,
) -> Dict[str, str]:
    """拷贝并抹除敏感环境变量, 防止密钥泄漏到沙箱子进程。

    - base: 源环境 (None = os.environ)
    - extra: 额外注入的非敏感变量 (不会被抹除)

    返回脱敏后的环境变量字典。
    """
    env = dict(base if base is not None else os.environ)
    if extra:
        env.update(extra)
    return {
        k: ("" if any(h in k.upper() for h in SECRET_HINTS) else v)
        for k, v in env.items()
    }


# ---------------------------------------------------------------- 敏感脱敏

REDACT_TAG = "[REDACTED]"

# 配置/结构化字段名: 命中即视为敏感, dump/get 时遮蔽
_SENSITIVE_KEY_MARKERS: tuple = (
    "api_key", "apikey", "api_secret", "secret", "token", "password",
    "passwd", "credential", "private_key", "access_key", "client_secret",
    "bearer", "jwt", "refresh_token", "authorization", "auth_token",
)
# 把非字母数字分隔符归一为 |, 再按词边界匹配, 避免 "token" 撞上 "tokens"/"token_usage"
_SEP_RE = re.compile(r"[^a-z0-9]+")
_MARKER_RE = tuple(
    re.compile(rf"(?:^|\|){re.escape(_SEP_RE.sub('|', m).strip('|'))}(?:$|\|)")
    for m in _SENSITIVE_KEY_MARKERS
)


def is_sensitive_key(key: str) -> bool:
    """判断配置字段名是否属于敏感(密钥类)字段, 用于 dump/get 遮蔽。

    api_key / access-key / client.secret 等均按词边界命中; `budget_tokens` 这类
    "计数 token" 不会误判为敏感。
    """
    norm = _SEP_RE.sub("|", (key or "").lower())
    return any(rx.search(norm) for rx in _MARKER_RE)


def mask_sensitive_dict(data: Any) -> Any:
    """递归遮蔽 dict/list 中敏感字段的值, 其它字段原样返回 (供 `config dump` 使用)。"""
    if isinstance(data, Mapping):
        out: Dict[Any, Any] = {}
        for k, v in data.items():
            out[k] = REDACT_TAG if is_sensitive_key(str(k)) else mask_sensitive_dict(v)
        return out
    if isinstance(data, list):
        return [mask_sensitive_dict(x) for x in data]
    return data


# 常见明文密钥赋值:  KEY=value / key: value / --key=value / Key=value
_KEY_VALUE_RE = re.compile(
    r"(?i)(api[_-]?key|apikey|api[_-]?secret|secret|token|password|passwd|"
    r"credential|client[_-]?secret|refresh[_-]?token|access[_-]?key|"
    r"private[_-]?key|authorization|bearer)\s*[:=]\s*([^\s,;\"']{6,})"
)
# 独立的长敏感 token
_BEARER_RE = re.compile(r"(?i)\b(Bearer|Basic|Bearer type)\s+[A-Za-z0-9._~+/=]{12,}")
_SK_RE = re.compile(r"\bsk-[A-Za-z0-9\-_]{12,}")
_JWT_RE = re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}")
# 单行环境变量赋值:  DEEPSEEK_API_KEY=sk-xxx  (直接置于行首, 用词边界防误伤)
_ENV_LINE_RE = re.compile(
    r"(?im)^\s*([A-Z0-9_]*(?:API_KEY|APISECRET|SECRET|TOKEN|PASSWORD|PASSWD|"
    r"CREDENTIAL|ACCESS_KEY|PRIVATE_KEY|AUTH)[A-Z0-9_]*)\s*=\s*(\S+)\s*$"
)


def redact_sensitive(
    text: Any,
    extra_secrets: Sequence[str] = (),
) -> str:
    """统一敏感内容脱敏: 抹掉文本中的 API Key / Token / 密码 / Bearer / 密钥环境变量取值。

    用于审计日志、安全事件、MCP 审计与导出链路, 防止真实密钥落盘或回显。
    extra_secrets: 额外传入的确切密钥串, 会做整串替换。
    幂等且绝不抛异常 (任何输入都安全处理)。
    """
    if not text:
        return "" if text is None else str(text)
    if not isinstance(text, str):
        text = str(text)
    out: str = text

    for s in extra_secrets:
        if isinstance(s, str) and s and len(s) >= 8:
            out = out.replace(s, REDACT_TAG)

    # 只有文本包含疑似长 token 时才走正则, 减少对普通文本的处理开销
    if not re.search(r"[A-Za-z0-9_\-./+]{8,}", out):
        return out

    out = _ENV_LINE_RE.sub(lambda m: f"{m.group(1)}={REDACT_TAG}", out)
    out = _BEARER_RE.sub(r"\1 " + REDACT_TAG, out)
    out = _SK_RE.sub("sk-" + REDACT_TAG, out)
    out = _JWT_RE.sub(REDACT_TAG, out)
    out = _KEY_VALUE_RE.sub(REDACT_TAG, out)
    return out


def redact_nested(data: Any) -> Any:
    """递归对所有字符串值做敏感脱敏, 结构保持不变 (供审计 context/features、事件 payload 使用)。"""
    if isinstance(data, Mapping):
        return {k: redact_nested(v) for k, v in data.items()}
    if isinstance(data, list):
        return [redact_nested(x) for x in data]
    if isinstance(data, tuple):
        return tuple(redact_nested(x) for x in data)
    if isinstance(data, str):
        return redact_sensitive(data)
    return data


# ---------------------------------------------------------------- 错误文本净化

# 终端可解释的控制字符 / bidi / 零宽 / 私用区 / 未分配码点。
# 用途与 UI 标语的净化层不同：这里**不做** grapheme 簇或显示宽度判定，
# 只保证「执行层异常消息被回显到终端时不会被解释成转义序列、也不会
# 用 RLO 重排欺骗用户」，因此不构成第三套宽度真值。
_ERROR_CTRL_RE = re.compile(
    r"[\x00-\x1f\x7f-\x9f\u200b-\u200f\u202a-\u202e\u2060-\u206f\ufeff\ue000-\uf8ff]"
)


def safe_error_text(text: Any, limit: int = 400) -> str:
    """把执行层异常消息安全地变成可回显文本（绝不抛异常）。

    实测缺口：``_execute_backend`` / ``_run_provider`` /
    ``_execute_copy_diff_apply`` 的 ``except`` 分支直接把 ``str(exc)``
    放进 ``SandboxExecResult.error``，而 ``tools/shell.py`` 在
    ``returncode < 0`` 时原样回显 ``[错误] {res.error}``。异常消息可能
    来自工具参数、路径或命令文本，于是 ``GITHUB_TOKEN=ghp_...`` 这类
    真实凭据会原样回显；OSC 8 超链接与 RLO 也会进终端。

    处理顺序：非 str 只取类型名（不 ``str()`` 未知对象，避免 repr 泄露）
    -> 剥离控制字符 -> ``redact_sensitive`` 遮蔽密钥 -> 限长。
    ``limit`` 脏值一律回落默认，不抛异常。
    """
    if text is None:
        return ""
    if not isinstance(text, str):
        text = type(text).__name__
    try:
        out = _ERROR_CTRL_RE.sub("", text)
        out = redact_sensitive(out)
        cap = limit if isinstance(limit, int) and not isinstance(limit, bool) \
            and 0 < limit <= 4096 else 400
        if len(out) > cap:
            out = out[:cap] + f"…[截断 {len(out) - cap} 字符]"
        return out
    except Exception:  # noqa: BLE001 - 净化自身绝不能让错误路径再抛
        return "[错误文本净化失败, 原文已丢弃]"
