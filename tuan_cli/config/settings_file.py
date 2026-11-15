"""Claude Code 风格 settings.json 的加载与翻译 (对标 ``--settings``)。

Claude Code 的 ``--settings <file>`` 接受一份 JSON 设置文件, 常用字段:

    {
      "model": "claude-sonnet-4-5",
      "permissions": {
        "allow": ["Bash(git status)", "Read(./src/**)", "mcp__fs__read_file"],
        "deny":  ["Bash(rm -rf:*)"],
        "ask":   ["Bash(git push:*)"],
        "additionalDirectories": ["../shared"],
        "defaultMode": "plan"
      },
      "env": {"FOO": "bar"},
      "allowedTools": ["Read", "Grep"],
      "disallowedTools": ["WebFetch"]
    }

本模块把上述字段**翻译为本仓库既有结构**, 绝不静默丢弃安全相关配置:

- ``permissions.allow/deny/ask`` -> ``permissions.rules`` 规则表
  （``Bash(cmd:*)`` 前缀语义、``Read(./src/**)`` 路径 glob、``mcp__s__t`` 规范化名）；
- ``permissions.additionalDirectories`` -> 会话级额外可读目录；
- ``permissions.defaultMode`` -> 会话模式 (plan / auto / yolo)；
- ``model`` / ``env`` -> 一次性配置覆盖 (不写盘, 等价 ``--patch`` 层)；
- ``allowedTools`` / ``disallowedTools`` -> 会话级工具白/黑名单。

未知字段只告警不报错 (设置文件常含与本地 CLI 无关的键); 但 **无法翻译的
deny 条目必须报错** —— 丢掉一条拒绝规则等于悄悄放宽权限, 属 fail-open,
这是本模块唯一拒绝执行的情况。

许可: Apache-2.0。无第三方源码复制。
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

# Claude 工具名 -> 本仓库工具名
_TOOL_ALIASES: Dict[str, str] = {
    "bash": "run_shell",
    "shell": "run_shell",
    "read": "read_file",
    "edit": "edit_file",
    "multiedit": "edit_files",
    "multi_edit": "edit_files",
    "write": "write_file",
    "glob": "glob",
    "grep": "grep",
    "webfetch": "web_fetch",
    "websearch": "web_search",
    "notebookedit": "notebook_edit",
    "task": "task",
    "todowrite": "todo_write",
    "agent": "task",
}

# Claude defaultMode -> 本仓库会话模式
_MODE_MAP: Dict[str, Optional[str]] = {
    "default": None,
    "plan": "plan",
    "acceptEdits": "auto",
    "bypassPermissions": "yolo",
    "dontAsk": "yolo",
}

_ENTRY_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*\((.*)\)$")


@dataclass
class SettingsResult:
    """翻译结果。由调用方在会话启动时消费, 不落盘。"""

    config_patch: Dict[str, Any] = field(default_factory=dict)
    additional_directories: List[str] = field(default_factory=list)
    allowed_tools: List[str] = field(default_factory=list)
    disallowed_tools: List[str] = field(default_factory=list)
    mode: Optional[str] = None
    env: Dict[str, str] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)


def _norm_path(spec: str) -> str:
    spec = spec.strip()
    if spec.startswith("./"):
        spec = spec[2:]
    spec = spec.replace("\\", "/")
    return spec


def _path_patterns(spec: str) -> List[str]:
    """把 Claude 路径写法转成 fnmatch pattern, 同时覆盖相对/绝对/反斜杠。"""
    spec = _norm_path(spec)
    if not spec:
        return ["*"]
    spec = spec.replace("**", "*")
    if spec.startswith("/"):
        patterns = [spec]
    else:
        patterns = [spec, "*" + spec]
    # Windows 实参可能是反斜杠: 再加一组变体, 避免漏匹配
    patterns.append(spec.replace("/", "\\"))
    return patterns


def _translate_entry(entry: str, action: str) -> Optional[List[Dict[str, Any]]]:
    """单条 ``Tool(spec)`` 权限项 -> 若干本仓库规则 (None 表示不支持)。"""
    entry = str(entry).strip()
    if not entry:
        return None

    m = _ENTRY_RE.match(entry)
    if not m:
        low = entry.lower()
        if low.startswith("mcp__"):
            return [{"tool": "mcp_call", "pattern": low, "action": action}]
        tool = _TOOL_ALIASES.get(low)
        if tool is None:
            return None
        return [{"tool": tool, "action": action}]

    raw_tool, spec = m.group(1), m.group(2).strip()
    low = raw_tool.lower()

    # MCP 规范化名: mcp__server__tool -> mcp_call 的 effective 名
    if low.startswith("mcp__"):
        return [{"tool": "mcp_call", "pattern": low, "action": action}]

    tool = _TOOL_ALIASES.get(low)
    if tool is None:
        return None

    if tool == "run_shell":
        # Claude 的 "cmd:*" 是前缀匹配; 不带 ":*" 表示整条命令精确匹配
        if spec.endswith(":*"):
            prefix = spec[:-2].strip()
            return [{"tool": tool, "pattern": prefix + "*", "action": action}]
        return [{"tool": tool, "pattern": spec.lower(), "action": action}]

    if tool in ("read_file", "edit_file", "edit_files", "write_file",
                "notebook_edit"):
        return [{"tool": tool, "pattern": p.lower(), "action": action}
                for p in _path_patterns(spec)]

    if tool in ("glob", "grep"):
        return [{"tool": tool, "param": "pattern",
                 "value": _norm_path(spec).lower(), "action": action}]

    if tool == "web_fetch":
        # WebFetch(domain:example.com)
        domain = spec
        dm = re.match(r"^domain:(.+)$", spec, re.IGNORECASE)
        if dm:
            domain = dm.group(1)
        return [{"tool": tool, "param": "url",
                 "value": f"*{domain.lower()}*", "action": action}]

    if tool == "task":
        return [{"tool": tool, "param": "subagent_type",
                 "value": _norm_path(spec).lower(), "action": action}]

    # 其余工具: 有 spec 就用 pattern, 无 spec 就是整工具
    if spec:
        return [{"tool": tool, "pattern": spec.lower(), "action": action}]
    return [{"tool": tool, "action": action}]


def _as_str_list(value: Any) -> Optional[List[str]]:
    if value is None:
        return []
    if not isinstance(value, list):
        return None
    return [str(v) for v in value if str(v).strip()]


def load_settings(path: str) -> SettingsResult:
    """读取并翻译 settings.json；抛出 ValueError 供 CLI 直接展示。"""
    p = Path(path).expanduser()
    if not p.exists():
        raise ValueError(f"settings 文件不存在: {p}")
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"settings 文件无法解析: {exc}") from None
    if not isinstance(data, dict):
        raise ValueError("settings 文件顶层必须是 JSON 对象")

    res = SettingsResult()
    rules: List[Dict[str, Any]] = []

    for key in data:
        if key not in ("model", "permissions", "env", "allowedTools",
                       "disallowedTools", "hooks", "statusLine", "outputStyle"):
            res.warnings.append(f"忽略未支持的 settings 字段: {key}")

    model = data.get("model")
    if model is not None:
        if not isinstance(model, str) or not model.strip():
            raise ValueError("settings.model 必须是非空字符串")
        res.config_patch["model.model"] = model.strip()

    env = data.get("env")
    if env is not None:
        if not isinstance(env, dict):
            raise ValueError("settings.env 必须是对象")
        for k, v in env.items():
            if not isinstance(k, str) or not k:
                raise ValueError("settings.env 的键必须是非空字符串")
            res.env[k] = str(v)

    at = _as_str_list(data.get("allowedTools"))
    if at is None:
        raise ValueError("settings.allowedTools 必须是字符串数组")
    res.allowed_tools = at

    dt = _as_str_list(data.get("disallowedTools"))
    if dt is None:
        raise ValueError("settings.disallowedTools 必须是字符串数组")
    res.disallowed_tools = dt

    perms = data.get("permissions")
    if perms is not None:
        if not isinstance(perms, dict):
            raise ValueError("settings.permissions 必须是对象")
        for bucket, action in (("allow", "allow"), ("deny", "deny"),
                               ("ask", "ask")):
            items = _as_str_list(perms.get(bucket))
            if items is None:
                raise ValueError(f"settings.permissions.{bucket} 必须是字符串数组")
            for entry in items:
                translated = _translate_entry(entry, action)
                if translated is None:
                    if action == "deny":
                        # fail-closed: 无法翻译的拒绝规则绝不放行
                        raise ValueError(
                            f"无法翻译的 deny 规则: {entry!r}; "
                            "请改用本仓库支持的工具名或去掉该条")
                    res.warnings.append(
                        f"忽略无法翻译的 {action} 规则: {entry!r}")
                    continue
                rules.extend(translated)
        dirs = _as_str_list(perms.get("additionalDirectories"))
        if dirs is None:
            raise ValueError("settings.permissions.additionalDirectories 必须是字符串数组")
        res.additional_directories = dirs
        dm = perms.get("defaultMode")
        if dm is not None:
            if not isinstance(dm, str) or dm not in _MODE_MAP:
                raise ValueError(
                    f"settings.permissions.defaultMode 取值非法: {dm!r}; "
                    f"可选 {sorted(_MODE_MAP)}")
            res.mode = _MODE_MAP[dm]

    if rules:
        res.config_patch["permissions.rules"] = rules

    return res


def apply_env(env: Dict[str, str]) -> None:
    """把 settings.env 注入进程环境; 已存在的变量不覆盖 (不劫持用户环境)。"""
    for k, v in env.items():
        os.environ.setdefault(k, v)


def merge_rules(existing: Any, new_rules: List[Dict[str, Any]]) -> List[Any]:
    """把翻译出的规则追加到既有规则表末尾 (deny/ask/allow 优先级由决策层排序)。"""
    out: List[Any] = list(existing or ()) if isinstance(existing, (list, tuple)) else []
    out.extend(new_rules)
    return out


def split_tool_list(value: Optional[str]) -> List[str]:
    """解析逗号分隔工具列表 (与 ``--allowedTools`` 用法一致)。"""
    if not value:
        return []
    return [part.strip() for part in str(value).split(",") if part.strip()]


def normalize_tool_name(name: str) -> str:
    return _TOOL_ALIASES.get(str(name).strip().lower(), str(name).strip())


def tool_list(names: List[str]) -> List[str]:
    return [normalize_tool_name(n) for n in names]
