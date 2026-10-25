"""MCP server 配置解析。

无 transport 时按 ``command`` -> stdio / ``url`` -> http 自动补全。
校验由 :mod:`tuan_cli._config_model` 完成 —— 纯 stdlib 实现, 不依赖 pydantic。

旧实现同时存在两条分支: 有 pydantic 时返回校验过的模型实例, 没有时返回裸 dict。
下游 ``getattr(config, "headers")`` / ``getattr(config, "bearerTokenEnvVar")`` 在
dict 形状下取不到值, 会导致远程 MCP server 的自定义请求头与 bearer token 静默丢失。
现在无论是否安装 pydantic, 返回的都是同一个 :class:`ConfigModel`, 两种读法都成立。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from ..._config_model import (
    ConfigModel,
    McpServerConfig,
    ValidationError,
    validate_server_config,
)
from .errors import McpStartupError

DEFAULT_STARTUP_TIMEOUT_MS = 30_000
DEFAULT_TOOL_TIMEOUT_MS = 2_147_483_647  # 对应 MAX_MCP_TIMEOUT_MS，实际交给客户端默认


def _cfg_get(config: Any, key: str, default: Any = None) -> Any:
    """统一读取配置字段: 同时兼容 dict 与 :class:`ConfigModel`。"""
    if isinstance(config, dict):
        return config.get(key, default)
    return getattr(config, key, default)


def _init_data(args: tuple, kwargs: Dict[str, Any]) -> Dict[str, Any]:
    """把 ``Cls(data)`` / ``Cls(**fields)`` / ``Cls(data, **overrides)`` 归一为 dict。"""
    data: Dict[str, Any] = {}
    if len(args) == 1 and isinstance(args[0], (dict, ConfigModel)):
        src = args[0]
        data.update(src.model_dump() if isinstance(src, ConfigModel) else dict(src))
    data.update(kwargs)
    return data


class McpServerStdioConfig(ConfigModel):
    """stdio 传输配置 (构造即校验)。"""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        data = _init_data(args, kwargs)
        data.setdefault("transport", "stdio")
        super().__init__(validate_server_config(data).model_dump())


class McpServerHttpConfig(ConfigModel):
    """HTTP (Streamable HTTP) 传输配置 (构造即校验)。"""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        data = _init_data(args, kwargs)
        data.setdefault("transport", "http")
        super().__init__(validate_server_config(data).model_dump())


class McpServerSseConfig(ConfigModel):
    """SSE 传输配置 (构造即校验)。"""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        data = _init_data(args, kwargs)
        data.setdefault("transport", "sse")
        super().__init__(validate_server_config(data).model_dump())


def resolve_config(raw: Any) -> Any:
    """补全 transport 并校验为 :class:`ConfigModel`。

    - 已带 ``transport``：直接校验。
    - 否则按 ``command`` -> stdio / ``url`` -> http 推断。
    """
    if not isinstance(raw, dict):
        raise McpStartupError(f"MCP server config 必须是对象，收到 {type(raw).__name__}")
    try:
        return validate_server_config(raw)
    except ValidationError as exc:
        raise McpStartupError(str(exc)) from exc


def load_mcp_config(path_or_dict: Any) -> Dict[str, Any]:
    """解析 ``{mcpServers: {...}}``（或扁平 ``{name: config}``）为 ``name -> ConfigModel``。

    接受：
    - dict：直接当作配置（含顶层 ``mcpServers`` 则取其内部）。
    - str / Path：JSON 文件路径。
    """
    if isinstance(path_or_dict, (str, Path)):
        with open(path_or_dict, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    elif isinstance(path_or_dict, dict):
        data = path_or_dict
    else:
        raise TypeError("load_mcp_config 接受 dict 或文件路径")

    if not isinstance(data, dict):
        raise McpStartupError("MCP 配置根必须是对象")
    servers = data.get("mcpServers", data)
    if not isinstance(servers, dict):
        raise McpStartupError("MCP servers 必须是对象")

    out: Dict[str, Any] = {}
    for name, cfg in servers.items():
        out[name] = resolve_config(cfg)
    return out


def merge_mcp_configs(*configs: Dict[str, Any]) -> Dict[str, Any]:
    """多层配置合并（后者覆盖前者，简化为单层合并）。"""
    merged: Dict[str, Any] = {}
    for cfg in configs:
        if not cfg:
            continue
        merged.update(cfg)
    return merged


def compute_enabled_names(
    tools: List[Any],
    enabled_tools: Optional[List[str]] = None,
    disabled_tools: Optional[List[str]] = None,
) -> set:
    """根据 enabled/disabled 过滤，返回实际启用的工具名集合。"""
    names = [t.name if hasattr(t, "name") else t for t in tools]
    enabled = set(names)
    if enabled_tools is not None:
        ef = set(enabled_tools)
        enabled = {n for n in names if n in ef}
    if disabled_tools is not None:
        df = set(disabled_tools)
        enabled = {n for n in enabled if n not in df}
    return enabled


def is_remote_config(config: Any) -> bool:
    return _cfg_get(config, "transport") in ("http", "sse")


def build_remote_headers(config: Any, env_lookup: Optional[Callable[[str], str]] = None) -> Optional[Dict[str, str]]:
    """构造远程（http/sse）请求头，注入 bearer token。"""
    env_lookup = env_lookup or (lambda n: os.environ.get(n) or "")
    headers: Dict[str, str] = dict(_cfg_get(config, "headers") or {})
    token_env = _cfg_get(config, "bearerTokenEnvVar")
    if token_env is not None:
        token = env_lookup(token_env)
        if not token:
            raise McpStartupError(
                f"MCP {_cfg_get(config, 'transport', 'remote')} bearer token 环境变量 "
                f"'{token_env}' 未设置或为空"
            )
        headers = {k: v for k, v in headers.items() if k.lower() != "authorization"}
        headers["Authorization"] = f"Bearer {token}"
    return headers or None
