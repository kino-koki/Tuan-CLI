# -*- coding: utf-8 -*-
"""账户登录体系 —— GitHub / Apple / DeepSeek 官方 API 三种登录, 离线不登录照常可用。

注意: DeepSeek 只支持官方开放平台 API Key (platform.deepseek.com)。
历史上存在过的「网页会话令牌直连 chat.deepseek.com 私有接口」方案会触发
平台风控 (账号临时停用), 已整体移除, 不再提供。
"""
from __future__ import annotations

from .base import (
    AuthError,
    AuthProvider,
    AuthResult,
    ProviderNotConfigured,
    get_provider,
    list_providers,
    register,
)
from .store import AuthStore
from .github import GitHubOAuthProvider
from .apple import AppleSignInProvider
from .deepseek import DeepSeekAPIProvider

# 注册内置提供方 (顺序即 `qxt login` 默认展示顺序)
register(GitHubOAuthProvider)
register(AppleSignInProvider)
register(DeepSeekAPIProvider)

__all__ = [
    "AuthStore",
    "AuthProvider",
    "AuthResult",
    "AuthError",
    "ProviderNotConfigured",
    "get_provider",
    "list_providers",
]
