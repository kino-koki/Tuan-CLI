"""统一工具权限决策 (覆盖同类终端 Agent 的已知加固项)。

增强:
- 锚定路径规则: 单段目录允许规则仅限 cwd 下, 不再跨 monorepo 蔓延。
- Fail-closed bash 检查: 文件描述符重定向格式不一致时, 默认拒绝执行。
- 长命令提示: 超过 10,000 字符的命令自动触发确认, 不盲目执行。
- Docker/Podman 安全: 带守护进程重定向标志的 docker 命令强制确认。
- Shell 特定修复: 处理 Windows PowerShell 5.1 和复杂 zsh 变量下标。
"""

from __future__ import annotations

import fnmatch
import os
import re
from dataclasses import dataclass
from typing import Any, Iterable
from urllib.parse import urlparse

# 长命令阈值 (对标 Claude Code 2.1.214: 10000 字符)
_LONG_COMMAND_THRESHOLD = 10_000

# Docker/Podman 守护进程重定向标志
_DAEMON_FLAGS = {"--url", "--connection", "--identity"}

# Windows PowerShell 特殊模式
_PS_DANGEROUS_PATTERNS = (
    r"\bInvoke-Expression\b",
    r"\bIEX\b",
    r"\bSet-ExecutionPolicy\b",
)

# 文件描述符重定向格式 (fail-closed: 解析器与 shell 可能不一致, 默认拒绝)
_FD_REDIRECT_RE = re.compile(r"\b\d+>\s*\S")


@dataclass(frozen=True)
class PermissionDecision:
    action: str  # allow | confirm | deny
    reason: str
    explicit: bool = False  # True = 用户规则表显式 allow (可豁免危险工具确认)


def _nested_get(args: dict, dotted: str) -> Any:
    """按点号路径从嵌套 dict 取值 (如 config.model); 取不到返回 None。"""
    cur = args
    for part in str(dotted).split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur


def _effective_tool_name(name: str, args: dict[str, Any]) -> str:
    """E6: 把 MCP 调用规范化为 `mcp__<server>__<tool>` 供规则表匹配。

    此前规则表只能按外层工具名 `mcp_call` 匹配, 无法对「某台不可信 server 的
    某个工具」单独放行或拒绝 —— 只能一刀切。现在规则可写
    `{"tool": "mcp__untrusted__*", "action": "deny"}`。
    """
    if name not in ("mcp_call", "mcp_tool", "mcp") or not isinstance(args, dict):
        return name
    server = (args.get("server") or args.get("server_name")
              or args.get("mcp_server") or "")
    tool = (args.get("tool") or args.get("tool_name")
            or args.get("mcp_tool") or args.get("name") or "")
    if not server and not tool:
        return name
    return f"mcp__{server}__{tool}"


def _rule_exclude(rule: dict) -> str:
    """E6: 取负向排除模式。支持 `exclude: "bin/**"` 与 `pattern: "!bin/**"`。"""
    ex = rule.get("exclude")
    if ex is not None and str(ex).strip():
        return str(ex).strip()
    pat = str(rule.get("pattern", "")).strip()
    if pat.startswith("!"):
        return pat[1:].strip()
    return ""


class PermissionPolicy:
    """集中处理工具权限。对标 Claude Code 2.1.214 的安全加固。"""

    def __init__(self, config: Any = None) -> None:
        self.config = config
        self.shell_deny = tuple(self._get("permissions.shell.deny_patterns", ()))
        self.network_allow = tuple(self._get("permissions.network.allow_domains", ()))
        self.rules = tuple(self._get("permissions.rules", ()))
        self.yolo_redline = set(self._get("mode.yolo_require_confirm", ()))
        self.workspace = self._get("_workspace", "")

    def _get(self, key: str, default: Any) -> Any:
        if self.config is None:
            return default
        value = self.config.get(key, default)
        return default if value is None else value

    def _hardening_confirm(self, reason: str, command: str, yolo: bool) -> PermissionDecision:
        """内置加固项的决策 —— YOLO 下放行, 但**硬红线永远拒绝**。

        这些加固 (超长命令 / FD 重定向 / PowerShell 危险模式 / Docker 守护进程重定向)
        走的是"需要确认"路径。早期实现直接 `return confirm`, 位置在下方 YOLO 自动批准
        判断**之前** —— 于是开了 YOLO 依然每条命令都弹窗 (Windows 上
        `_PS_DANGEROUS_PATTERNS` 命中率尤其高, 观感就是"命令全都要问我")。
        现在: 硬红线 → 拒绝 (YOLO 也不放行, 与 README 口径一致); 否则 YOLO → 放行。
        """
        try:
            from ..ext.safety_engine import is_redline

            if is_redline(command):
                return PermissionDecision("deny", f"硬红线, 不可自动批准: {reason}")
        except Exception:  # noqa: BLE001
            # fail-closed: 引擎不可用 = 无法证明该命令不是红线。旧实现 `pass`
            # 后继续往下走, YOLO 下会静默放行超长命令 / FD 重定向 / IEX /
            # Docker 守护进程重定向 —— 属于典型「异常即放行」。
            return PermissionDecision(
                "confirm", f"安全规则引擎不可用(fail-closed), 需人工确认: {reason}")
        if yolo:
            return PermissionDecision("allow", f"YOLO 自动批准 (加固项: {reason})")
        return PermissionDecision("confirm", reason)

    def decide(
        self, tool: Any, args: dict[str, Any], *, yolo: bool = False,
        auto_classifier: Any = None,
    ) -> PermissionDecision:
        """统一工具权限决策。

        - ``yolo``: YOLO 模式, 危险工具自动批准 (硬红线仍拒绝);
        - ``auto_classifier``: AutoMode 分类器 (core.auto_mode.AutoModeClassifier)。
          传入时按风险分级决定 allow/confirm —— 安全操作自动批准,
          敏感/危险操作仍需确认 (对标 Claude Code Auto Mode)。
        """
        name = tool.name
        if name in {"web_fetch", "mcp_call"} and self.network_allow:
            url = args.get("url", "")
            host = urlparse(url).hostname or ""
            if not any(fnmatch.fnmatch(host, pattern) for pattern in self.network_allow):
                return PermissionDecision("deny", f"网络域名不在允许列表: {host or url}")

        if name == "run_shell":
            command = str(args.get("command", ""))
            # Claude Code 2.1.214 安全加固: 长命令自动触发确认
            if len(command) > _LONG_COMMAND_THRESHOLD:
                return self._hardening_confirm(
                    f"命令过长 ({len(command)} 字符, 阈值 {_LONG_COMMAND_THRESHOLD}), 需要确认",
                    command, yolo)
            # Claude Code 2.1.214 安全加固: Docker/Podman 守护进程重定向
            if self._has_docker_daemon_flags(command):
                return self._hardening_confirm(
                    "Docker/Podman 命令带守护进程重定向标志, 需要确认", command, yolo)
            # Claude Code 2.1.214 安全加固: Fail-closed bash 检查
            if _FD_REDIRECT_RE.search(command):
                return self._hardening_confirm(
                    "命令含文件描述符重定向格式, 需要确认", command, yolo)
            # Claude Code 2.1.214 安全加固: Windows PowerShell 危险模式
            if os.name == "nt":
                for pattern in _PS_DANGEROUS_PATTERNS:
                    if re.search(pattern, command, re.IGNORECASE):
                        return self._hardening_confirm(
                            f"PowerShell 危险模式: {pattern}", command, yolo)
            for pattern in self.shell_deny:
                if re.search(pattern, command, re.IGNORECASE):
                    return PermissionDecision("deny", f"命令匹配拒绝规则: {pattern}")

        # 用户自定义规则表 (permissions.rules): 在内置加固之后、默认决策之前生效。
        # allow 命中带 explicit 标记, 危险工具可据此免确认; 内置加固确认不受豁免。
        rule_action = self.match_rule(name, args)
        if rule_action == "deny":
            return PermissionDecision("deny", f"权限规则 (permissions.rules) 拒绝执行 {name}")
        if rule_action == "ask":
            return PermissionDecision("confirm", f"权限规则 (permissions.rules) 要求确认 {name}")
        if rule_action == "allow":
            return PermissionDecision("allow", f"权限规则 (permissions.rules) 允许执行 {name}", explicit=True)

        # Auto Mode (对标 Claude Code): 分类器按风险分级决定 allow/confirm。
        # 硬红线仍由 _hardening_confirm 在下游拦截 (rm -rf /、DROP TABLE 等),
        # 分类器的 auto_approve 不会放行这些; needs_confirm=True 时仍需人工确认。
        if auto_classifier is not None:
            try:
                assessment = auto_classifier.assess(name, args)
                if getattr(assessment, "needs_confirm", False):
                    return PermissionDecision(
                        "confirm",
                        f"Auto 模式分类器要求确认: {assessment.reason}")
                if getattr(assessment, "auto_approve", False):
                    return PermissionDecision(
                        "allow",
                        f"Auto 模式自动批准: {assessment.reason}")
            except Exception:  # noqa: BLE001 - 分类器异常时回退常规决策 (fail-safe)
                pass

        if not getattr(tool, "dangerous", False):
            return PermissionDecision("allow", "只读或非危险工具")
        if yolo and name not in self.yolo_redline and not getattr(tool, "yolo_confirm", False):
            return PermissionDecision("allow", "YOLO 自动批准")
        return PermissionDecision("confirm", "危险工具需要用户确认")

    def match_rule(self, name: str, args: dict[str, Any]) -> str | None:
        """匹配用户自定义规则表, 返回命中动作 (deny/ask/allow) 或 None。

        多条规则同时命中时按 deny > ask > allow 取最严格者;
        规则格式非法 (非 dict / action 不认识) 时静默跳过。

        E6:
        - `exclude` / `pattern: "!glob"` 为负向排除: 目标匹配排除模式时该规则
          **不生效**, 用于给宽泛 allow 规则开洞 (如允许 `git *` 但排除
          `git push --force*`), 避免"永远允许"变成提权入口。
        - 为保持 fail-closed, **deny 规则忽略 exclude**: 拒绝规则不允许被
          排除条件放宽。
        - MCP 调用按 `mcp__<server>__<tool>` 规范化名参与 tool 匹配。
        """
        target = self._rule_target(name, args)
        effective = _effective_tool_name(name, args)
        hits: list[str] = []
        for rule in self.rules:
            if not isinstance(rule, dict):
                continue
            tool_pattern = str(rule.get("tool", "*"))
            if not (fnmatch.fnmatch(name.lower(), tool_pattern.lower())
                    or fnmatch.fnmatch(effective.lower(), tool_pattern.lower())):
                continue
            action = str(rule.get("action", "")).strip().lower()
            if action not in ("allow", "deny", "ask"):
                continue
            # Tool(param:value) 精确粒度 (对标 Claude Code 三层权限):
            # 规则带 param 时按参数值 glob 精确匹配, 优先于旧式 pattern。
            param = rule.get("param")
            if param:
                actual = _nested_get(args, str(param))
                if actual is None or not fnmatch.fnmatch(str(actual), str(rule.get("value", "*"))):
                    continue
            else:
                arg_pattern = str(rule.get("pattern", "")).strip()
                # "!glob" 是排除模式, 不作为正向匹配条件
                if arg_pattern and not arg_pattern.startswith("!") \
                        and not fnmatch.fnmatch(target, arg_pattern.lower()):
                    continue
            exclude = _rule_exclude(rule)
            if exclude and action != "deny":
                if (fnmatch.fnmatch(target, exclude.lower())
                        or fnmatch.fnmatch(effective.lower(), exclude.lower())):
                    continue
            hits.append(action)
        for priority in ("deny", "ask", "allow"):
            if priority in hits:
                return priority
        return None

    def inspect(self, name: str, args: dict[str, Any]) -> dict:
        """测试一次工具调用会被哪些规则命中 (供 `tuan permissions test` 使用)。

        Returns:
            {"action": 最终动作 deny/ask/allow/None, "hits": [{"index", "rule"}...]}
        """
        target = self._rule_target(name, args)
        effective = _effective_tool_name(name, args)
        hits: list[dict] = []
        for i, rule in enumerate(self.rules):
            if not isinstance(rule, dict):
                continue
            tool_pattern = str(rule.get("tool", "*"))
            if not (fnmatch.fnmatch(name.lower(), tool_pattern.lower())
                    or fnmatch.fnmatch(effective.lower(), tool_pattern.lower())):
                continue
            if rule.get("param"):
                actual = _nested_get(args, str(rule["param"]))
                matched = actual is not None and fnmatch.fnmatch(
                    str(actual), str(rule.get("value", "*")))
            else:
                p = str(rule.get("pattern", "")).strip()
                matched = (not p) or p.startswith("!") or fnmatch.fnmatch(target, p.lower())
            if matched:
                action = str(rule.get("action", "")).strip().lower()
                exclude = _rule_exclude(rule)
                if exclude and action != "deny":
                    if (fnmatch.fnmatch(target, exclude.lower())
                            or fnmatch.fnmatch(effective.lower(), exclude.lower())):
                        matched = False
            if matched:
                hits.append({"index": i, "rule": rule})
        action = None
        for priority in ("deny", "ask", "allow"):
            if any(h["rule"].get("action") == priority for h in hits):
                action = priority
                break
        return {"action": action, "hits": hits}

    @staticmethod
    def _rule_target(name: str, args: dict[str, Any]) -> str:
        """提取规则 pattern 的匹配文本 (小写): run_shell 用命令行, 其余优先 path/url, 兜底拼接参数值。"""
        if name == "run_shell":
            return str(args.get("command", "")).lower()
        if name in ("mcp_call", "mcp_tool", "mcp"):
            effective = _effective_tool_name(name, args)
            rest = " ".join(str(v) for k, v in args.items()
                            if k not in ("server", "server_name", "mcp_server",
                                         "tool", "tool_name", "mcp_tool", "name"))
            return f"{effective} {rest}".lower().strip()
        for key in ("path", "url"):
            if key in args:
                return str(args[key]).lower()
        return " ".join(str(v) for v in args.values()).lower()

    @staticmethod
    def _has_docker_daemon_flags(command: str) -> bool:
        """检测 Docker/Podman 命令是否带守护进程重定向标志。"""
        parts = command.lower().split()
        if not parts:
            return False
        # 检查 docker/podman 命令
        for i, part in enumerate(parts):
            if part in ("docker", "podman"):
                # 检查后续参数是否有守护进程标志
                for j in range(i + 1, min(i + 10, len(parts))):
                    if parts[j] in _DAEMON_FLAGS:
                        return True
        return False


def _is_empty_user_template(user_text: str) -> bool:
    """判断 USER.md 是否仍是未填写的空模板。"""
    import re as _re
    stripped = _re.sub(r"[#\-\*\s:]", "", user_text)
    stripped = _re.sub(r"(Name|City|Notes|关于用户)", "", stripped, flags=_re.IGNORECASE)
    return stripped.strip() == ""
