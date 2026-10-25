"""CLI 友好错误体系 (C-2) —— 五类错误 + 固定中文模板。

与 ``core/error_handler.py`` 的关系:
- ``error_handler`` 负责「把任意第三方异常分类成 FriendlyError」(既有, 已被测试覆盖);
- 本模块定义 **业务侧可主动抛出** 的五类异常, 以及契约要求的固定模板文案,
  并提供 :func:`template_for` 供 error_handler 合并取用 (不改动其现有分类逻辑,
  只替换/增强文案, 保证既有测试不回归)。

五类错误 (契约 C-2.1):
- ProviderError  通用供应商调用失败
- AuthError      API Key 无效 / 未配置
- NetworkError   网络不通 / 端点不可达
- ConfigError    配置缺失 / 格式错误
- ModelError     模型名不存在 / 无可用模型
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional


class TuanCliError(Exception):
    """所有 CLI 业务错误的根类 (可直接被顶层兜底捕获)。"""

    kind: str = "generic"

    def __init__(self, message: str = "", *, detail: str = "") -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail


class ProviderError(TuanCliError):
    """供应商调用失败 (非认证/非网络的通用错误, 如 5xx、响应格式异常)。"""

    kind = "provider"


class AuthError(TuanCliError):
    """API Key 缺失 / 无效 / 已过期。"""

    kind = "auth"


class NetworkError(TuanCliError):
    """无法连接到模型服务 (离线 / DNS / 代理)。"""

    kind = "network"


class ConfigError(TuanCliError):
    """配置缺失 / 格式错误 / 字段非法。"""

    kind = "config"


class ModelError(TuanCliError):
    """指定模型不存在或当前环境无可用模型。"""

    kind = "model"


@dataclass
class FriendlyTemplate:
    """单类错误的友好模板: 描述 + 原因 + 建议 + 可执行命令。"""

    title: str            # 一句话标题 (❌ 后的第一行)
    reason: str          # 原因解释
    suggestion: str      # 可执行建议 (含具体命令)
    kind: str = "generic"

    def render(self, detail: str = "") -> str:
        """渲染为用户可读的多行提示。"""
        lines = [
            f"❌ {self.title}",
            f"   原因: {self.reason}",
            f"   建议: {self.suggestion}",
        ]
        if detail:
            lines.append(f"   详情: {detail}")
        return "\n".join(lines)


# ------------------------------------------------------------------ 契约固定文案
# C-2.3 / C-2.4 / C-2.5 逐字采用契约措辞, 不要意译改写。

TEMPLATES: Dict[str, FriendlyTemplate] = {
    "auth": FriendlyTemplate(
        title="API Key 无效或已过期",
        reason="模型服务端拒绝了本次认证请求。",
        suggestion="您的 API Key 可能已过期或无效。请运行 tuan setup 重新配置。",
        kind="auth",
    ),
    "network": FriendlyTemplate(
        title="无法连接到模型服务",
        reason="请求在限定时间内未能到达模型服务端点。",
        suggestion="无法连接到模型服务。请检查网络连接，或运行 tuan models local 查看本地模型。",
        kind="network",
    ),
    "model": FriendlyTemplate(
        title="模型不存在",
        reason="当前选择的模型名在供应商目录中找不到。",
        suggestion="模型 {model} 不存在。运行 tuan models 查看可用模型列表。",
        kind="model",
    ),
    "provider": FriendlyTemplate(
        title="模型服务调用失败",
        reason="供应商返回了非预期的错误 (服务端异常或响应格式异常)。",
        suggestion="可稍后重试; 若持续失败, 运行 tuan doctor 诊断, 或用 tuan models 切换其它供应商。",
        kind="provider",
    ),
    "config": FriendlyTemplate(
        title="配置有误",
        reason="配置缺失或格式不正确, 程序无法按预期启动。",
        suggestion="请运行 tuan doctor 自动定位并修复配置问题; 或运行 tuan setup 重新初始化。",
        kind="config",
    ),
}


def template_for(kind: str, **fields: Any) -> FriendlyTemplate:
    """按错误类型取模板; 用 ``fields`` (如 model="gpt-xxx") 填充占位符。

    未知 kind 回退到 provider 通用模板。
    """
    tmpl = TEMPLATES.get(kind, TEMPLATES["provider"])
    if fields:
        # 对 suggestion 里的 {xxx} 占位符做安全填充 (缺字段时原样保留)
        suggestion = tmpl.suggestion.format(**{k: v for k, v in fields.items() if isinstance(v, str)})
        title = tmpl.title
        if kind == "model" and "model" in fields:
            title = f"模型 {fields['model']} 不存在"
        return FriendlyTemplate(title=title, reason=tmpl.reason,
                                suggestion=suggestion, kind=tmpl.kind)
    return tmpl


def friendly_for(exc: Exception) -> Optional[FriendlyTemplate]:
    """把本模块定义的业务异常映射为友好模板; 其它异常返回 None。

    供 error_handler 在外部分类之上叠加业务模板 (优先采用固定文案)。
    """
    if isinstance(exc, TuanCliError):
        fields: Dict[str, Any] = {}
        if isinstance(exc, ModelError):
            # ModelError 的 message 通常就是模型名
            fields["model"] = exc.message or "(未指定)"
        return template_for(exc.kind, **fields)
    return None
