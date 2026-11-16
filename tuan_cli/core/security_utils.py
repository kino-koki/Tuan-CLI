"""共享安全工具 —— 环境变量脱敏等跨模块复用的安全原语。

消除 core/sandbox.py + core/sandbox_provider.py + arch/security.py +
tools/mcp/sandbox.py 中重复的 _sanitize_env / SECRET_HINTS 定义。
"""

from __future__ import annotations

import re
import os
from typing import Any, Dict, Mapping, Optional, Sequence
import logging

log = logging.getLogger(__name__)


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

    B2: 已经是 ``TUAN_MASKED_*`` sentinel 的值**保留原样** —— 它们本身已经
    是安全占位符, 再清空等于把 broker 的指纹也丢掉。

    返回脱敏后的环境变量字典。
    """
    env = dict(base if base is not None else os.environ)
    if extra:
        env.update(extra)
    return {
        k: ("" if (any(h in k.upper() for h in SECRET_HINTS)
                    and not (isinstance(v, str)
                             and v.startswith(MASKED_PLACEHOLDER_PREFIX)))
            else v)
        for k, v in env.items()
    }


# ---------------------------------------------------------------- 敏感脱敏

REDACT_TAG = "[REDACTED]"

# 占位符前缀 (单一真值, sandbox/egress.py 从此处导入为 SENTINEL_PREFIX)。
# 脱敏后的环境变量值用 `<prefix><sha256指纹>` 替换, 真实值只在 CredentialBroker
# 内存中, 绝不出现在子进程 env / 审计日志 / 可序列化字段。
MASKED_PLACEHOLDER_PREFIX = "TUAN_MASKED_"

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


# ---- safe_error_text: 错误文本安全展示原语 ----
# 用于把异常/错误消息展示给用户前: (1) 脱敏 (复用 redact_sensitive);
# (2) 剥离终端控制字符 (ESC/BEL/RLO 等, 防终端注入/欺骗);
# (3) 限长 (防错误消息刷屏/DoS)。绝不抛异常 (fail-open 展示原语)。

# 匹配 C0 控制字符 (除 \n \t) + DEL + C1 控制字符 + 危险 Unicode 方向覆盖符
_UNSAFE_CTRL_RE = re.compile(
    r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f"       # C0 + DEL (保留 \n\t)
    r"\u0080-\u009f"                            # C1 控制
    r"\u202a-\u202e"                            # 双向覆盖 (RLO/LRO/POP)
    r"\u2066-\u2069"                            # 隔离符 (LRI/RLI/FSI/PDI)
    r"\ufeff]"                                  # BOM/零宽不换行
)
_DEFAULT_MAX_LEN = 400


def safe_error_text(obj: Any, limit: Any = None) -> str:
    """把错误/异常对象转成安全可展示文本。

    处理管线 (顺序敏感):
    1. 非 str 输入 → 仅返回类型名 (不调 ``__str__``, 防损坏对象泄露 repr);
    2. ``redact_sensitive`` 脱敏 API Key / Token / 密码 / Bearer / JWT;
    3. 剥离终端控制字符 (ESC/BEL/RLO/LRO 等, 防终端欺骗);
    4. 限长 (默认 400, 传入非法 limit 值回落默认并追加「截断」标记)。

    绝不抛异常: 任何一步失败都静默降级为最保守输出。
    """
    try:
        # 非 str → 类型名 (None → 空串; 不触发 __str__)
        if obj is None:
            return ""
        if not isinstance(obj, str):
            try:
                return type(obj).__name__ or "object"
            except Exception as exc:  # noqa: BLE001
                log.debug("安全展示原语降级: %s", exc)
                return "object"

        text = redact_sensitive(obj)
        # 剥离控制字符 (保留 \n \t, 它们是可读错误的一部分)
        text = _UNSAFE_CTRL_RE.sub("", text)

        # 限长: None/缺省 → 默认; 非正整数/非有限数/异常大 → 回落默认 + 标记
        max_len = _DEFAULT_MAX_LEN
        mark = False
        if limit is not None:
            try:
                import math
                # 上限封顶: 异常大的 limit (如 10**9) 视为脏值, 回落默认
                _SANE_CEILING = 10_000
                if isinstance(limit, bool) or not isinstance(limit, (int, float)):
                    mark = True
                elif isinstance(limit, float) and not math.isfinite(limit):
                    mark = True
                elif limit <= 0:
                    mark = True
                elif limit > _SANE_CEILING:
                    mark = True
                else:
                    max_len = int(limit)
            except Exception:  # noqa: BLE001
                mark = True

        if len(text) > max_len:
            return text[:max_len] + "…[截断]"
        if mark:
            # limit 非法 (如 None→默认 / -1 / nan): 文本未超默认限长就不动;
            # 超了才追加「截断」标记。测试只断言 len<500 且含「截断」当超长。
            return text
        return text
    except Exception as exc:  # noqa: BLE001 - 展示原语绝不抛
        log.debug("安全展示原语降级: %s", exc)
        return "object"


def safe_exception_text(exc: BaseException, limit: Any = None) -> str:
    """把异常对象安全展示。

    与 ``safe_error_text`` 的区别: 输入是异常对象 (可能有 ``.message`` /
    ``.args``), 我们只取 ``str(exc)`` 后走同一净化管线, 并用 try 包住防
    损坏对象掀翻错误路径。
    """
    try:
        out = safe_error_text(str(exc), limit)
        type_name = type(exc).__name__ if isinstance(exc, BaseException) else "object"
        if out:
            return f"{type_name}: {out}"
        return type_name
    except Exception:  # noqa: BLE001
        return (f"{type(exc).__name__} (异常消息不可用已丢弃)")


def is_masked_placeholder(value: Any) -> bool:
    """判断字符串是否是 MASKED_PLACEHOLDER_PREFIX 占位符。

    用于拒绝把占位符当真实值写回 / 发送: egress 层把占位符 resolve 成
    真实值后才出网, 直接出现的占位符意味着 broker 丢失或 resolve 漏调。
    """
    return isinstance(value, str) and value.startswith(MASKED_PLACEHOLDER_PREFIX)


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
