# -*- coding: utf-8 -*-
"""DeepSeek 网页账号登录提供方 (会话令牌注入, 无需 API Key)。

背景: 视频/社区方案 (如 DSH-webtokens) 把「已登录的 DeepSeek 网页」作为模型后端,
不产生 API 调用费用, 使用网页账号额度。本项目以「会话令牌注入」的轻量方式支持:

流程:
1. 打开浏览器, 用户登录 chat.deepseek.com (若未登录);
2. 从浏览器开发者工具 (Application → Cookies → chat.deepseek.com) 复制
   会话访问令牌 (auth token / cookie 串);
3. 粘贴到终端 (或预先写入 auth-config.toml [deepseek] session_token);
4. 令牌保存到 AuthStore, 之后模型层可按需接入 deepseek-web 供应商。

说明:
- 本模块只负责登录态 (令牌) 的管理与验证; 模型调用层见 models 的
  deepseek-web 适配 (标注为实验性, 依赖网页接口, 网页改版可能失效)。
- 令牌属高敏感凭据, 妥善保管; 失效后在网页端退出登录或换令牌即可。
- 离线不登录是默认路径: 不做 DeepSeek 登录时, 本地/API 模型照常可用。
"""
from __future__ import annotations

import getpass
import time
import webbrowser
from typing import Any, Dict, Optional

from .base import AuthError, AuthProvider, AuthResult

_WEB_HOME = "https://chat.deepseek.com"
_TOKEN_HINT = (
    "在浏览器登录 chat.deepseek.com 后:\n"
    "  1) 打开开发者工具 (F12) → Application → Cookies → chat.deepseek.com;\n"
    "  2) 复制会话认证令牌 (auth token 或完整 cookie 串);\n"
    "  3) 粘贴到下方输入框 (粘贴不会回显)。"
)


class DeepSeekWebProvider(AuthProvider):
    """DeepSeek 网页账号登录 (会话令牌)。"""

    name = "deepseek"
    display_name = "DeepSeek (网页)"
    description = "DeepSeek 网页账号登录 (会话令牌, 无需 API Key, 用网页额度)"

    @staticmethod
    def _env_map() -> Dict[str, str]:
        return {
            "QXT_DEEPSEEK_SESSION_TOKEN": "session_token",
            "QXT_DEEPSEEK_LOGIN": "login",
        }

    # ------------------------------------------------------------- 交互 (可注入测试)
    def _ask_token(self, prompt: str) -> str:
        return getpass.getpass(prompt)

    # ------------------------------------------------------------- 登录
    def login(self) -> AuthResult:
        creds = self.credentials()
        token = (creds.get("session_token") or "").strip()

        if not token:
            try:
                webbrowser.open(_WEB_HOME)
            except Exception:
                pass
            print(_TOKEN_HINT)
            token = self._ask_token("DeepSeek 网页会话令牌: ").strip()
            if not token:
                raise AuthError("未输入会话令牌, 登录已取消。")

        login_hint = (creds.get("login") or "").strip() or "deepseek-web"
        self.store.set(
            "deepseek",
            {
                "token": token,
                "login": login_hint,
                "display_name": login_hint,
                "avatar_url": "",
                "expires_at": None,  # 网页会话有效期由 DeepSeek 网页端决定
            },
        )
        return AuthResult(
            provider="deepseek",
            login=login_hint,
            display_name=login_hint,
            extra={"note": "会话令牌已保存; 模型调用走 deepseek-web 适配 (实验性)。"},
        )
