"""友好错误提示 (P1): 把常见异常转成中文 + 恢复建议。

设计:
- ``friendly_error(exc, context=None)`` -> ``FriendlyError`` (纯数据, 可测试);
- 输出格式::

      ❌ <错误标题>
         原因: <一句话原因>
         建议: <恢复动作>

- ``--verbose`` 时由调用方附加完整 traceback;
- 配置 ``ui.friendly_errors`` (默认 true) 关闭时, 调用方应回退原始异常;
- ``install_top_level_handler()`` 在 CLI 主入口 / REPL 里挂全局兜底, 确保用户
  永远看到可读提示而非一串 traceback。
"""

from __future__ import annotations

import errno
import sys
import traceback
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class FriendlyError:
    title: str
    reason: str
    suggestion: str
    kind: str = "generic"
    detail: str = ""

    def render(self, *, verbose: bool = False, tb: str = "") -> str:
        lines = [
            f"❌ {self.title}",
            f"   原因: {self.reason}",
            f"   建议: {self.suggestion}",
        ]
        if self.detail:
            lines.append(f"   详情: {self.detail}")
        if verbose and tb:
            lines.append("")
            lines.append("── 完整堆栈 (--verbose) ──")
            lines.append(tb.rstrip())
        return "\n".join(lines)


# ------------------------------------------------------------------ 分类规则

def _http_status_of(exc: Exception) -> Optional[int]:
    """从常见 HTTP 库异常里提取状态码 (openai/httpx/requests), 找不到返回 None。"""
    for attr in ("status_code", "code", "http_status"):
        v = getattr(exc, attr, None)
        if isinstance(v, int):
            return v
    resp = getattr(exc, "response", None)
    if resp is not None:
        v = getattr(resp, "status_code", None)
        if isinstance(v, int):
            return v
    return None


def _message(exc: Exception) -> str:
    return str(exc).strip() or exc.__class__.__name__


def friendly_error(exc: Exception, context: Optional[Dict[str, Any]] = None) -> FriendlyError:
    """把异常映射为友好的中文错误提示 + 恢复建议。"""
    context = context or {}
    msg = _message(exc)
    provider = context.get("provider", "当前 provider")
    ename = exc.__class__.__name__

    # ---- API 认证失败 401/403 ----
    status = _http_status_of(exc)
    looks_auth = status in (401, 403) or any(
        k in msg.lower() for k in ("api key", "apikey", "unauthorized",
                                   "invalid_api_key", "authentication", "401",
                                   "403", "forbidden"))
    if looks_auth:
        return FriendlyError(
            title="API Key 无效或已过期",
            reason=f"服务端拒绝了认证 (provider: {provider})。",
            suggestion="运行 `qxt config set provider.key <key>` 或 `qxt login <KEY>` 重新设置密钥。",
            kind="auth", detail=msg,
        )

    # ---- 超时 / 限流 429 ----
    looks_timeout = "timeout" in msg.lower() or "timed out" in msg.lower() or ename in ("Timeout", "TimeoutError", "ReadTimeout")
    looks_ratelimit = status == 429 or "rate limit" in msg.lower() or "429" in msg
    if looks_timeout or looks_ratelimit:
        if looks_ratelimit:
            return FriendlyError(
                title="请求被限流 (429)",
                reason=f"provider {provider} 返回了限流, 请稍后再试。",
                suggestion="降低并发、稍后重试, 或在 `qxt models` 里换一个更稳的供应商。",
                kind="rate_limit", detail=msg,
            )
        return FriendlyError(
            title="请求超时",
            reason=f"调用 provider {provider} 超时, 模型没有在限定时间内响应。",
            suggestion="可重试一次; 或降低上下文长度 / 用 `--effort low`; 检查代理网络。",
            kind="timeout", detail=msg,
        )

    # ---- 文件不存在 ----
    if isinstance(exc, FileNotFoundError):
        path = getattr(exc, "filename", None) or context.get("path", "?")
        return FriendlyError(
            title="文件不存在",
            reason=f"路径 {path} 不存在或已被移动。",
            suggestion="请检查路径拼写; 可用 glob 工具在工作区里搜索同名文件。",
            kind="not_found", detail=msg,
        )

    # ---- 权限拒绝 ----
    if isinstance(exc, PermissionError) or (isinstance(exc, OSError) and exc.errno == errno.EACCES):
        path = getattr(exc, "filename", None) or context.get("path", "该路径")
        return FriendlyError(
            title="权限不足",
            reason=f"没有权限访问 {path}。",
            suggestion="检查文件/目录权限; 写操作可在确认后用 --yolo 授权, 或用 --plan 只读模式先看。",
            kind="permission", detail=msg,
        )

    # ---- 网络不可达 ----
    looks_network = isinstance(exc, (ConnectionError,)) or any(
        k in msg.lower() for k in ("connection", "network is unreachable",
                                   "getaddrinfo failed", "ssl", "temporary failure",
                                   "nodename nor servname"))
    if looks_network:
        return FriendlyError(
            title="网络不可达",
            reason="无法连接到模型 API 或外网。",
            suggestion="检查代理 / VPN; 或使用本地模型 (`qxt models` 切 Ollama) 与 --offline 模式。",
            kind="network", detail=msg,
        )

    # ---- 配置语法错误 ----
    try:
        import yaml  # 延迟导入
        _is_yaml = isinstance(exc, yaml.YAMLError)
    except Exception:  # noqa: BLE001
        _is_yaml = ename in ("YAMLError", "MarkedYAMLError")
    if _is_yaml or "yaml" in ename.lower():
        return FriendlyError(
            title="配置文件语法错误",
            reason=f"config.yaml 解析失败: {msg.splitlines()[0] if msg else ''}",
            suggestion="用 `qxt doctor` 定位具体行; 对照 config.schema.json 修正缩进/字段。",
            kind="config", detail=msg,
        )

    # ---- 兜底 ----
    return FriendlyError(
        title=f"出错了: {ename}",
        reason=msg[:200] if msg else "未提供详细信息",
        suggestion="用 `--verbose` 查看完整堆栈; 或运行 `qxt doctor` 诊断环境。",
        kind="generic", detail=msg,
    )


# ------------------------------------------------------------------ 顶层兜底

def handle_exception(exc: Exception, *, verbose: bool = False,
                     enabled: bool = True, context: Optional[Dict[str, Any]] = None) -> int:
    """顶层异常兜底: 打印友好错误, 返回进程退出码 (1)。

    enabled=False (配置 ui.friendly_errors=false) 时, 原样抛出 traceback。
    """
    if not enabled:
        # 回退原始异常
        raise exc
    tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    fe = friendly_error(exc, context)
    sys.stderr.write(fe.render(verbose=verbose, tb=tb) + "\n")
    return 1


def install_top_level_handler() -> None:
    """在 CLI 主入口安装 sys.excepthook, 把未捕获异常转成友好提示。"""
    prev = sys.excepthook

    def _hook(exc_type, exc, tb):
        if issubclass(exc_type, (KeyboardInterrupt, SystemExit)):
            prev(exc_type, exc, tb)
            return
        try:
            verbose = getattr(sys, "_qxt_verbose", 0) >= 1
            enabled = getattr(sys, "_qxt_friendly_errors", True)
            handle_exception(exc, verbose=verbose, enabled=enabled)
        except Exception:  # noqa: BLE001 - 兜底不能再崩
            prev(exc_type, exc, tb)

    sys.excepthook = _hook
