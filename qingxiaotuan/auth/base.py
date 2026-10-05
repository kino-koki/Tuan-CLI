# -*- coding: utf-8 -*-
"""AuthProvider 抽象基类、注册表与凭证读取。

第三方凭证 (OAuth client_id/secret 等) 属敏感信息, 统一从两个来源读取:
1. 环境变量 (优先级高)::
     QXT_GITHUB_CLIENT_ID / QXT_GITHUB_CLIENT_SECRET
     QXT_APPLE_TEAM_ID / QXT_APPLE_CLIENT_ID / QXT_APPLE_KEY_ID / QXT_APPLE_PRIVATE_KEY_PATH
     QXT_DEEPSEEK_SESSION_TOKEN
2. 配置文件 (默认 <QXT_HOME>/auth-config.toml)::
     [github]    client_id / client_secret / redirect_uri
     [apple]     team_id / client_id / key_id / private_key_path / redirect_uri
     [deepseek]  session_token

优先级: 环境变量 > TOML 文件。
"""
from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Type

from ..config.loader import home_dir
from .store import AuthStore

AUTH_CONFIG_FILE = "auth-config.toml"


class AuthError(Exception):
    """登录流程失败 (凭证缺失、网络错误、被拒绝等)。"""


class ProviderNotConfigured(AuthError):
    """该提供方未配置第三方凭证。"""


@dataclass
class AuthResult:
    """登录成功后的账户摘要 (不含原始令牌, 令牌由 provider 自行存入 store)。"""

    provider: str
    login: str  # 稳定用户名/邮箱/sub
    display_name: str = ""
    avatar_url: str = ""
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "provider": self.provider,
            "login": self.login,
            "display_name": self.display_name,
            "avatar_url": self.avatar_url,
            **self.extra,
        }


class AuthProvider(ABC):
    """第三方登录提供方基类。

    子类必须定义 name/display_name/description, 并实现 login()。
    每个 provider 实例绑定一个 AuthStore (可注入测试)。
    """

    name: str = ""
    display_name: str = ""
    description: str = ""

    def __init__(self, home: Optional[Path] = None, store: Optional[AuthStore] = None):
        self.home = Path(home) if home is not None else home_dir()
        self.store = store if store is not None else AuthStore(home=self.home)

    # ------------------------------------------------------------- 凭证
    def _credentials(self) -> Dict[str, str]:
        """读取该提供方的凭证 (环境变量优先, 其次 TOML)。"""
        creds: Dict[str, str] = {}
        # TOML 文件层
        cfg_path = self.home / AUTH_CONFIG_FILE
        if cfg_path.exists():
            try:
                import tomllib

                with open(cfg_path, "rb") as f:
                    cfg = tomllib.load(f)
                section = cfg.get(self.name) if isinstance(cfg, dict) else None
                if isinstance(section, dict):
                    for k, v in section.items():
                        if isinstance(v, str):
                            creds[k] = v
            except Exception:
                pass  # 配置文件损坏时静默降级到环境变量
        # 环境变量层 (覆盖)
        env_prefix = "QXT_" + self.name.upper()  # e.g. QXT_GITHUB
        for env_key, cfg_key in self._env_map().items():
            val = os.environ.get(env_key)
            if val:
                creds[cfg_key] = val
        return creds

    @staticmethod
    def _env_map() -> Dict[str, str]:
        """环境变量名 → 配置键名映射。子类可覆盖。"""
        return {}

    def credentials(self) -> Dict[str, str]:
        return self._credentials()

    # ------------------------------------------------------------- 协议
    @abstractmethod
    def login(self) -> AuthResult:
        """执行登录并写入 store; 失败抛 AuthError。"""

    def logout(self) -> bool:
        return self.store.remove(self.name)

    def status(self) -> Optional[dict]:
        acc = self.store.get(self.name)
        if not acc:
            return None
        # 对外隐藏原始令牌, 只暴露可展示字段
        return {
            "provider": self.name,
            "logged_in": True,
            "login": acc.get("login", ""),
            "display_name": acc.get("display_name", ""),
            "avatar_url": acc.get("avatar_url", ""),
            "scope": acc.get("scope", ""),
            "created_at": acc.get("created_at", ""),
            "updated_at": acc.get("updated_at", ""),
        }


# ------------------------------------------------------------- 注册表

PROVIDERS: Dict[str, Type[AuthProvider]] = {}


def register(provider_cls: Type[AuthProvider]) -> Type[AuthProvider]:
    name = provider_cls.name
    if not name:
        raise ValueError(f"{provider_cls.__name__} 必须定义 name")
    PROVIDERS[name] = provider_cls
    return provider_cls


def get_provider(name: str, home: Optional[Path] = None) -> AuthProvider:
    cls = PROVIDERS.get(name)
    if cls is None:
        raise AuthError(f"未知登录提供方: {name} (可用: {', '.join(PROVIDERS)})")
    return cls(home=home)


def list_providers() -> List[dict]:
    return [
        {"name": cls.name, "display_name": cls.display_name, "description": cls.description}
        for cls in PROVIDERS.values()
    ]


def load_credentials(name: str, home: Optional[Path] = None) -> Dict[str, str]:
    """便捷入口: 读取指定提供方的凭证。"""
    return get_provider(name, home=home).credentials()
