# -*- coding: utf-8 -*-
"""DeepSeek 官方 API 登录提供方 (API Key, 官方渠道)。

背景: 早期实现曾支持「网页会话令牌直连 chat.deepseek.com 私有接口」,
该方案绕过官方开放平台、依赖网页私有端点, 会触发 DeepSeek 平台风控
(账号被临时停用/禁言)。已整体移除, 不再提供任何网页令牌路径。

当前唯一受支持的 DeepSeek 接入方式为官方开放平台 API Key
(https://platform.deepseek.com 注册 → API Keys 创建, sk- 开头,
新账号附赠免费 token 额度, 无需信用卡)。

流程:
1. 提示用户前往 DeepSeek 开放平台创建 API Key (或从环境变量
   QXT_DEEPSEEK_API_KEY / 配置文件读取);
2. API Key 保存到 AuthStore (模型层经 provider=deepseek 官方端点
   https://api.deepseek.com 调用);
3. 离线不登录是默认路径: 不做 DeepSeek 登录时, 本地/其他 API 模型照常可用。

安全说明:
- API Key 属高敏感凭据, 妥善保管; 泄露风险与处理同 DEEPSEEK_API_KEY。
- 官方 API 与网页账号体系相互独立, 走官方 API 不产生网页账号风控风险。
"""
from __future__ import annotations

import getpass
import webbrowser
from typing import Any, Dict, Optional

from .base import AuthError, AuthProvider, AuthResult

_PLATFORM_HOME = "https://platform.deepseek.com"
_API_HINT = (
    "前往 DeepSeek 开放平台 (platform.deepseek.com) 注册并创建 API Key:\n"
    "  1) 登录开放平台 → API Keys → Create new API key;\n"
    "  2) 复制 sk- 开头的密钥 (仅创建时显示一次);\n"
    "  3) 粘贴到下方输入框 (粘贴不会回显)。\n"
    "模型调用将走官方端点 https://api.deepseek.com (OpenAI 兼容, 无风控风险)。"
)


class DeepSeekAPIProvider(AuthProvider):
    """DeepSeek 官方开放平台登录 (API Key)。"""

    name = "deepseek"
    display_name = "DeepSeek (官方 API)"
    description = "DeepSeek 官方 API Key (sk- 开头; 官方渠道, 无封号风险)"

    @staticmethod
    def _env_map() -> Dict[str, str]:
        return {
            "QXT_DEEPSEEK_API_KEY": "api_key",
            "QXT_DEEPSEEK_LOGIN": "login",
        }

    # ------------------------------------------------------------- 交互 (可注入测试)
    def _ask_api_key(self, prompt: str) -> str:
        return getpass.getpass(prompt)

    # ------------------------------------------------------------- 登录
    def login(self) -> AuthResult:
        creds = self.credentials()
        api_key = (creds.get("api_key") or "").strip()

        if not api_key:
            webbrowser.open(_PLATFORM_HOME)
            print(_API_HINT)
            api_key = self._ask_api_key("DeepSeek 官方 API Key: ").strip()
            if not api_key:
                raise AuthError("未输入 API Key, 登录已取消。")

        login_hint = (creds.get("login") or "").strip() or "deepseek-api"
        self.store.set(
            "deepseek",
            {
                "token": api_key,
                "login": login_hint,
                "display_name": login_hint,
                "avatar_url": "",
                "expires_at": None,  # API Key 无有效期概念, 由用户在开放平台管理
            },
        )
        return AuthResult(
            provider="deepseek",
            login=login_hint,
            display_name=login_hint,
            extra={
                "note": "官方 API Key 已保存; 模型调用走 provider=deepseek "
                        "(https://api.deepseek.com, OpenAI 兼容)。"
            },
        )
