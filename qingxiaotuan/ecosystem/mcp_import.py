"""MCP 配置桥接层 —— Claude Code 的 ``.mcp.json`` / Hermes 的 ``config.yaml`` ↔ qxt。

「生态积累」里最值钱的一类资产是**别人已经配好的 MCP server**: Claude Code 项目里
的 ``.mcp.json``、Hermes ``config.yaml`` 的 ``mcp.servers`` 都声明了一批外部工具。
本层把它们导入 qxt 的 ``mcp.servers`` 配置 (合并去重), 或把 qxt 已配的 server
导出到对方的配置文件 —— 让每个生态配过的工具, 其他生态开箱即用。

安全: 只搬运声明 (name/command/args/env), 不搬运密钥 env 的明文值;
含 ``secret`` / ``token`` / ``key`` 的环境变量在导出时用占位符替代。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    import yaml
except ImportError:  # pragma: no cover - pyyaml 为核心依赖, 缺失时优雅降级
    yaml = None


@dataclass
class McpImportResult:
    imported: List[str] = field(default_factory=list)
    skipped: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    exported_path: str = ""


# ---------------------------------------------------------------- 解析

def parse_claude_mcp_json(path: Path) -> List[Dict[str, Any]]:
    """解析 Claude Code 项目 ``.mcp.json`` → server 声明列表。"""
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"解析 {path} 失败: {exc}") from exc
    servers = data.get("mcpServers", {}) if isinstance(data, dict) else {}
    if not isinstance(servers, dict):
        return []
    out = []
    for name, s in servers.items():
        if not isinstance(s, dict):
            continue
        out.append({
            "name": name,
            "command": s.get("command", ""),
            "args": list(s.get("args", []) or []),
            "env": dict(s.get("env", {}) or {}),
        })
    return out


def parse_hermes_config(path: Path) -> List[Dict[str, Any]]:
    """解析 Hermes ``config.yaml`` 的 ``mcp.servers`` → server 声明列表。

    Hermes 的 mcp.servers 形如 ``{name: {command, args, env, ...}}``;
    取不到时返回空列表, 不抛异常 (config 结构随版本演化, 尽力而为)。
    """
    if not path.exists() or yaml is None:
        return []
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001
        return []
    if not isinstance(data, dict):
        return []
    servers = (data.get("mcp") or {}).get("servers", {}) if isinstance(data.get("mcp"), dict) else {}
    if not isinstance(servers, dict):
        return []
    out = []
    for name, s in servers.items():
        if not isinstance(s, dict):
            continue
        out.append({
            "name": name,
            "command": s.get("command", ""),
            "args": list(s.get("args", []) or []),
            "env": dict(s.get("env", {}) or {}),
        })
    return out


def _existing_servers(qxt_servers: Any) -> Dict[str, Any]:
    if isinstance(qxt_servers, list):
        return {s.get("name", ""): s for s in qxt_servers if isinstance(s, dict)}
    if isinstance(qxt_servers, dict):
        return qxt_servers
    return {}


def import_mcp_servers(
    config_setter: Any,
    servers: List[Dict[str, Any]],
    *,
    overwrite: bool = False,
) -> McpImportResult:
    """把外部 server 声明并入 qxt 配置的 ``mcp.servers``。

    config_setter: 带 ``get`` 与 ``set`` (点号路径) 的 Config 实例。
    同名 server 且不 overwrite 时跳过; 无 command 的畸形声明跳过。
    """
    result = McpImportResult()
    if not servers:
        return result
    try:
        current = _existing_servers(config_setter.get("mcp.servers", []))
    except Exception as exc:  # noqa: BLE001
        result.errors.append(f"读取当前 mcp.servers: {exc}")
        current = {}
    merged = dict(current)
    for s in servers:
        name = s.get("name", "")
        if not name or not s.get("command"):
            result.skipped.append(name or "<unnamed>")
            continue
        if name in merged and not overwrite:
            result.skipped.append(name)
            continue
        merged[name] = s
        result.imported.append(name)
    try:
        config_setter.set("mcp.servers", list(merged.values()))
    except Exception as exc:  # noqa: BLE001
        result.errors.append(f"写入配置: {exc}")
    return result


# ---------------------------------------------------------------- 导出

def _sanitize_env(env: Dict[str, str]) -> Dict[str, str]:
    """把疑似密钥的 env 值替换为占位符 (不搬运密钥明文)。"""
    out = {}
    for k, v in (env or {}).items():
        low = k.lower()
        if any(flag in low for flag in ("secret", "token", "password", "api_key", "apikey", "key")):
            out[k] = "<redacted: 请手动填写>"
        else:
            out[k] = v
    return out


def export_to_claude_mcp_json(
    qxt_servers: Any,
    dest: Path,
    *,
    include_env: bool = False,
) -> McpImportResult:
    """把 qxt 的 ``mcp.servers`` 导出为 Claude Code 项目 ``.mcp.json``。"""
    result = McpImportResult()
    servers = {}
    for s in _existing_servers(qxt_servers).values():
        if not isinstance(s, dict) or not s.get("command"):
            continue
        entry: Dict[str, Any] = {"command": s["command"], "args": list(s.get("args", []) or [])}
        if include_env and s.get("env"):
            entry["env"] = _sanitize_env(s["env"])
        servers[s.get("name", "server")] = entry
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps({"mcpServers": servers}, ensure_ascii=False, indent=2) + "\n"
        from ..core import atomicio
        atomicio.atomic_write_text(dest, payload)
        result.exported_path = str(dest)
        result.imported = list(servers)
    except OSError as exc:
        result.errors.append(str(exc))
    return result


def export_to_hermes_config(
    qxt_servers: Any,
    hermes_config: Path,
) -> McpImportResult:
    """把 qxt 的 ``mcp.servers`` 合并进 Hermes ``config.yaml`` (保留其余配置)。

    在现有 ``mcp.servers`` 上按名合并; 无 yaml 时只给出写入目标路径不落盘。
    """
    result = McpImportResult()
    if yaml is None:
        result.errors.append("pyyaml 不可用, 无法合并 Hermes config.yaml")
        return result
    data: Dict[str, Any] = {}
    if hermes_config.exists():
        try:
            data = yaml.safe_load(hermes_config.read_text(encoding="utf-8")) or {}
        except Exception:  # noqa: BLE001
            data = {}
    if not isinstance(data, dict):
        data = {}
    mcp_cfg = data.get("mcp", {})
    if not isinstance(mcp_cfg, dict):
        mcp_cfg = {}
    servers = mcp_cfg.get("servers", {})
    if not isinstance(servers, dict):
        servers = {}
    for s in _existing_servers(qxt_servers).values():
        if not isinstance(s, dict) or not s.get("command"):
            continue
        name = s.get("name", "server")
        servers[name] = {
            "command": s["command"],
            "args": list(s.get("args", []) or []),
            "env": _sanitize_env(s.get("env", {}) or {}),
        }
    mcp_cfg["servers"] = servers
    data["mcp"] = mcp_cfg
    try:
        hermes_config.parent.mkdir(parents=True, exist_ok=True)
        from ..core import atomicio
        atomicio.atomic_write_text(hermes_config, yaml.safe_dump(data, allow_unicode=True, sort_keys=False))
        result.exported_path = str(hermes_config)
        result.imported = list(servers)
    except OSError as exc:
        result.errors.append(str(exc))
    return result


__all__ = [
    "McpImportResult",
    "parse_claude_mcp_json", "parse_hermes_config",
    "import_mcp_servers",
    "export_to_claude_mcp_json", "export_to_hermes_config",
]
