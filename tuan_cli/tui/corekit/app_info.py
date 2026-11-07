"""与 Codex ``tui/src/app_info.rs`` 对齐的 wire → domain 转换。

上游注释（契约原文）：

    "Converts the app-server wire type owned by `codex-app-server-protocol`
    into connector-domain app metadata owned by `codex-connectors`.
    The types stay separate so app-server protocol ownership does not leak
    into the connector domain crate. Because this crate owns neither type,
    Rust's orphan rules require an explicit conversion function instead of
    a `From` implementation."

逐字段对齐四个转换函数：``app_info_from_api``（15 字段）、
``app_branding_from_api``（6）、``app_metadata_from_api``（11）、
``app_review_from_api``（1）、``app_screenshot_from_api``（3）；
Option 字段用 ``map`` 递归转换，列表逐项 map。

本地化修改（如实列出）：
  - Rust struct/孤儿规则 -> Python ``dict -> dataclass``，仍然用**显式
    转换函数**（不用通用 ``from_dict``），保持「协议字段不泄漏进领域对象」
    这条边界；
  - **严格字段白名单**：wire 里出现的未知字段一律拒绝而不是透传
    （本地化安全增强）。上游是编译期类型，天然拒绝；Python 是动态
    dict，若不拦就会把服务端新增的敏感字段悄悄带进 UI/日志；
  - URL 字段做基本校验：只允许 http/https（本地化增强，防
    ``javascript:`` / ``file:`` 进 UI 链接渲染，与第 11 轮
    ``terminal_hyperlinks.web()`` 口径一致）；
  - 新增 ``validate_api_app_info()`` 返回全部问题而非抛异常。

许可：Apache-2.0（NOTICE 第 12 条）。无 Rust 源码逐字复制。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

# 逐字段对齐上游（15 / 6 / 11 / 1 / 3）
APP_INFO_FIELDS = (
    "id", "name", "description", "logo_url", "logo_url_dark",
    "icon_assets", "icon_dark_assets", "distribution_channel",
    "branding", "app_metadata", "labels", "install_url",
    "is_accessible", "is_enabled", "plugin_display_names",
)
BRANDING_FIELDS = (
    "category", "developer", "website", "privacy_policy",
    "terms_of_service", "is_discoverable_app",
)
METADATA_FIELDS = (
    "review", "categories", "sub_categories", "seo_description",
    "screenshots", "developer", "version", "version_id",
    "version_notes", "first_party_requires_install",
    "show_in_composer_when_unlinked",
)
REVIEW_FIELDS = ("status",)
SCREENSHOT_FIELDS = ("url", "file_id", "user_prompt")


def _safe_url(value: Any) -> bool:
    """本地化增强：URL 只允许 http/https，且不含控制字符。"""
    if value is None or value == "":
        return True
    if not isinstance(value, str):
        return False
    if any(ord(c) < 32 or c in ("\x07", "\x1b") for c in value):
        return False
    parsed = urlparse(value)
    return parsed.scheme.lower() in ("http", "https") and bool(parsed.netloc)


def _reject_unknown(src: Dict[str, Any], allowed: tuple,
                    label: str, problems: List[str]) -> None:
    """严格白名单：对齐 Rust 编译期类型的「未知字段即错误」。"""
    if not isinstance(src, dict):
        problems.append(f"{label} 不是 dict")
        return
    for k in src:
        if k not in allowed:
            problems.append(f"{label} 含未知字段 {k!r}（协议字段不得泄漏）")


@dataclass
class AppBranding:
    category: Optional[str] = None
    developer: Optional[str] = None
    website: Optional[str] = None
    privacy_policy: Optional[str] = None
    terms_of_service: Optional[str] = None
    is_discoverable_app: Optional[bool] = None


@dataclass
class AppReview:
    status: Optional[str] = None


@dataclass
class AppScreenshot:
    url: Optional[str] = None
    file_id: Optional[str] = None
    user_prompt: Optional[str] = None


@dataclass
class AppMetadata:
    review: Optional[AppReview] = None
    categories: List[str] = field(default_factory=list)
    sub_categories: List[str] = field(default_factory=list)
    seo_description: Optional[str] = None
    screenshots: Optional[List[AppScreenshot]] = None
    developer: Optional[str] = None
    version: Optional[str] = None
    version_id: Optional[str] = None
    version_notes: Optional[str] = None
    first_party_requires_install: Optional[bool] = None
    show_in_composer_when_unlinked: Optional[bool] = None


@dataclass
class AppInfo:
    """connector-domain 领域类型（对齐上游，不含任何 wire 专属字段）。"""

    id: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    logo_url: Optional[str] = None
    logo_url_dark: Optional[str] = None
    icon_assets: Any = None
    icon_dark_assets: Any = None
    distribution_channel: Optional[str] = None
    branding: Optional[AppBranding] = None
    app_metadata: Optional[AppMetadata] = None
    labels: List[str] = field(default_factory=list)
    install_url: Optional[str] = None
    is_accessible: Optional[bool] = None
    is_enabled: Optional[bool] = None
    plugin_display_names: List[str] = field(default_factory=list)


def app_branding_from_api(src: Dict[str, Any],
                          problems: Optional[List[str]] = None) -> AppBranding:
    """对齐上游 6 字段显式解构。"""
    problems = problems if problems is not None else []
    _reject_unknown(src, BRANDING_FIELDS, "branding", problems)
    for k in ("website", "privacy_policy", "terms_of_service"):
        if not _safe_url(src.get(k)):
            problems.append(f"branding.{k} 不是安全的 http(s) URL")
    return AppBranding(**{k: src.get(k) for k in BRANDING_FIELDS})


def app_review_from_api(src: Dict[str, Any],
                        problems: Optional[List[str]] = None) -> AppReview:
    problems = problems if problems is not None else []
    _reject_unknown(src, REVIEW_FIELDS, "review", problems)
    return AppReview(status=src.get("status"))


def app_screenshot_from_api(src: Dict[str, Any],
                            problems: Optional[List[str]] = None) -> AppScreenshot:
    problems = problems if problems is not None else []
    _reject_unknown(src, SCREENSHOT_FIELDS, "screenshot", problems)
    if not _safe_url(src.get("url")):
        problems.append("screenshot.url 不是安全的 http(s) URL")
    return AppScreenshot(**{k: src.get(k) for k in SCREENSHOT_FIELDS})


def app_metadata_from_api(src: Dict[str, Any],
                          problems: Optional[List[str]] = None) -> AppMetadata:
    """对齐上游 11 字段；``review`` / ``screenshots`` 用 map 逐项转换。"""
    problems = problems if problems is not None else []
    _reject_unknown(src, METADATA_FIELDS, "app_metadata", problems)
    review = src.get("review")
    shots = src.get("screenshots")
    return AppMetadata(
        review=app_review_from_api(review, problems) if review else None,
        categories=list(src.get("categories") or []),
        sub_categories=list(src.get("sub_categories") or []),
        seo_description=src.get("seo_description"),
        screenshots=[app_screenshot_from_api(s, problems) for s in shots]
        if shots is not None else None,
        developer=src.get("developer"),
        version=src.get("version"),
        version_id=src.get("version_id"),
        version_notes=src.get("version_notes"),
        first_party_requires_install=src.get("first_party_requires_install"),
        show_in_composer_when_unlinked=src.get("show_in_composer_when_unlinked"),
    )


def app_info_from_api(app: Dict[str, Any],
                      problems: Optional[List[str]] = None) -> AppInfo:
    """对齐上游显式转换函数（不用 ``From``，因为两边都不属于本模块）。

    严格返回**领域对象**；任何未知 wire 字段都不会出现在结果里。
    问题通过可选 ``problems`` 出参 / ``validate_api_app_info()`` 暴露，
    转换本身不抛异常（对齐上游「转换函数」而非校验器的职责）。
    """
    problems = problems if problems is not None else []
    _reject_unknown(app, APP_INFO_FIELDS, "app_info", problems)
    branding = app.get("branding")
    metadata = app.get("app_metadata")
    for k in ("logo_url", "logo_url_dark", "install_url"):
        if not _safe_url(app.get(k)):
            problems.append(f"app_info.{k} 不是安全的 http(s) URL")
    return AppInfo(
        id=app.get("id"), name=app.get("name"),
        description=app.get("description"),
        logo_url=app.get("logo_url"), logo_url_dark=app.get("logo_url_dark"),
        icon_assets=app.get("icon_assets"),
        icon_dark_assets=app.get("icon_dark_assets"),
        distribution_channel=app.get("distribution_channel"),
        branding=app_branding_from_api(branding, problems)
        if branding else None,
        app_metadata=app_metadata_from_api(metadata, problems)
        if metadata else None,
        labels=list(app.get("labels") or []),
        install_url=app.get("install_url"),
        is_accessible=app.get("is_accessible"),
        is_enabled=app.get("is_enabled"),
        plugin_display_names=list(app.get("plugin_display_names") or []),
    )


def validate_api_app_info(app: Dict[str, Any]) -> List[str]:
    """本地化增强：返回全部校验问题（未知字段 / 不安全 URL）。"""
    problems: List[str] = []
    app_info_from_api(app, problems)
    return problems


def field_counts() -> Dict[str, int]:
    """可观测：逐字段数量，供 parity 自检核销。"""
    return {
        "app_info": len(APP_INFO_FIELDS), "branding": len(BRANDING_FIELDS),
        "metadata": len(METADATA_FIELDS), "review": len(REVIEW_FIELDS),
        "screenshot": len(SCREENSHOT_FIELDS),
    }
