"""斜杠命令 —— 账户与密钥域 (/provider /login /account)。

拆分自 cmd_slash.py:
- /provider /login  管理 API Key (持久化到 ~/.qingxiaotuan/.env);
- /account          管理第三方账户登录态 (GitHub / Apple / DeepSeek 网页)。
"""

from __future__ import annotations

import os

from ..i18n import t
from ._ui_singleton import ui


def _cmd_provider(agent, config, head: str, arg: str) -> None:
    """`/provider` 与 `/login` (别名): 查看/设置/清除当前 API Key 与供应商。

    用法:
        /provider [show]            查看当前供应商 / 模型 / 密钥环境变量
        /provider set <ENV> <KEY>   把 API Key 持久化到 ~/.qingxiaotuan/.env
        /provider clear [ENV]       删除某供应商密钥 (默认当前供应商), 保留原文件其余内容
        /login <KEY>                为当前供应商的 api_key_env 保存密钥
    """
    from ..config import normalize_api_key, persist_api_key, remove_api_key

    provider = config.get("model.provider", "?")
    model = config.get("model.model", "?")
    env_name = config.get("model.api_key_env", "DEEPSEEK_API_KEY")
    low = (arg or "").strip()
    action, rest = (low.split(None, 1) + [""])[:2] if low else ("", "")

    if low in ("show", "status", ""):
        ui.info(f"  provider: {provider}")
        ui.info(f"  model: {model}")
        ui.info(f"  api_key_env: {env_name} ({'已配置' if os.environ.get(env_name) else '未配置'})")
        if not os.environ.get(env_name):
            ui.info(t("slash.provider_usage", env=env_name))
        return

    if action == "set":
        kv = (rest or "").split(None, 1)
        if len(kv) < 2:
            ui.info(t("slash.provider_usage", env=env_name))
            return
        env, key = kv[0], kv[1]
    elif action == "clear":
        # /provider clear [ENV]: 删除该 env 的密钥 (默认当前供应商), 幂等且不影响其他密钥
        env = rest or env_name
        try:
            remove_api_key(env)
        finally:
            os.environ.pop(env, None)
        ui.success(t("slash.provider_cleared", env=env))
        return
    else:
        # /login <KEY>: 未显式给 env 名时取当前 provider 的 api_key_env
        env, key = env_name, arg.strip()

    key = normalize_api_key(key)
    if not key:
        ui.info(t("slash.provider_usage", env=env_name))
        return
    try:
        persist_api_key(env, key)
    except ValueError:
        ui.error(t("slash.provider_invalid_env", env=env))
        return
    os.environ[env] = key
    ui.success(t("slash.provider_set_done", env=env))

