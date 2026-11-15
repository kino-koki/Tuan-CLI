"""OAuth flow constants, ported from ``constants.ts``.

Node-side env overrides are resolved through ``os.environ`` so the module stays
loadable without a ``process`` global.
"""

from __future__ import annotations

import os

DEFAULT_KIMI_CODE_OAUTH_HOST = "https://auth.kimi.com"


def _env_override(*keys: str) -> str | None:
    for key in keys:
        value = os.environ.get(key)
        if value:
            return value
    return None


KIMI_CODE_FLOW_CONFIG = {
    "name": "kimi-code",
    "oauth_host": _env_override("KIMI_CODE_OAUTH_HOST", "KIMI_OAUTH_HOST")
    or DEFAULT_KIMI_CODE_OAUTH_HOST,
    "client_id": "17e5f671-d194-4dfb-9706-5516cb48c098",
}

# ------------------------------------------------------------------ GitHub 设备流
# GitHub 设备流 (RFC 8628) 需要一个已注册的 OAuth App 的 client_id。
# 这里放一个**明显的占位符** client_id, 可通过环境变量 TUAN_GITHUB_CLIENT_ID
# 覆盖 —— 这样既不会把真实密钥提交进仓库, 又允许部署方不改代码即可用真号登录。
# 未配置 TUAN_GITHUB_CLIENT_ID 时占位符会让 GitHub 返回 401/invalid_client,
# Web 层据此识别为 "尚未配置 GitHub 登录"。
GITHUB_DEVICE_FLOW_CONFIG = {
    "name": "github",
    "device_code_url": "https://github.com/login/device/code",
    "token_url": "https://github.com/login/oauth/access_token",
    "client_id": _env_override("TUAN_GITHUB_CLIENT_ID") or "Ov23li00000000000000",
}


__all__ = [
    "DEFAULT_KIMI_CODE_OAUTH_HOST",
    "KIMI_CODE_FLOW_CONFIG",
    "GITHUB_DEVICE_FLOW_CONFIG",
]
