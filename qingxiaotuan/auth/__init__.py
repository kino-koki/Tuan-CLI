# -*- coding: utf-8 -*-
"""账户登录体系 —— GitHub / Apple / DeepSeek 网页 三种登录, 离线不登录照常可用。

对外 API::
    from qingxiaotuan.auth import AuthStore, get_provider, list_providers, \
        AuthError, ProviderNotConfigured

    store = AuthStore()                      # ~/.qingxiaotuan/auth.json
    provider = get_provider("github")        # 已注册的提供方
    result = provider.login()                # 浏览器授权, 写入 store
    provider.logout()                        # 登出
    provider.status()                        # 当前登录态 (不含原始令牌)
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
from .deepseek import DeepSeekWebProvider

# 注册内置提供方 (顺序即 `qxt login` 默认展示顺序)
register(GitHubOAuthProvider)
register(AppleSignInProvider)
register(DeepSeekWebProvider)

__all__ = [
    "AuthStore",
    "AuthProvider",
    "AuthResult",
    "AuthError",
    "ProviderNotConfigured",
    "get_provider",
    "list_providers",
]
