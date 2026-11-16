"""作用域工具白名单 (对标 Claude Code 2.1.246 的 --allowedTools / scoped Bash)。

- 解析 Claude Code 的 allowedTools 语法:
    `Bash(npm test),Read,Edit,Write,Bash(pytest *.py)` 等。
- 支持作用域 Bash: 只放行匹配指定前缀/通配符子集的命令, 其余仍需确认。
  当命令以 * 结尾时, 视作前缀通配 (Claude Code 语义: `Bash(npm *)`);
  `Bash(*)` 放行全部 Bash。
- 语义:
    - 普通工具名 (Read/Edit/Write/...): 放行同名工具, 无需提示。
    - Bash(scope): 若命令作用域匹配, 放行该 Bash 调用。
- 安全约束: 本白名单只是"会话内免确认"的加分项, 优先级仍低于黑名单与硬红线;
  命中致命红线 (YOLO_REDLINE) 的命令无论是否在 allowedTools 中都不放行。
- 作用域只对本会话有效 (不写入磁盘白名单), 由 CLI 一次性注入。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class AllowedTools:
    """解析后的 allowedTools 规格。"""
    tools: set[str] = field(default_factory=set)          # 普通工具名
    bash_scopes: List[str] = field(default_factory=list)  # Bash 作用域 (glob/prefix)
    _bash_all: bool = False

    @classmethod
    def parse(cls, raw: Optional[str]) -> "AllowedTools":
        obj = cls()
        if not raw:
            return obj
        for piece in raw.split(","):
            piece = piece.strip()
            if not piece:
                continue
            # Bash(...) 作用域
            m = re.fullmatch(r"Bash\((.*)\)", piece)
            if m:
                scope = m.group(1).strip()
                obj.bash_scopes.append(scope)
                if not scope or scope == "*":
                    obj._bash_all = True
                continue
            # 普通工具名
            obj.tools.add(piece)
        return obj

    def allows_tool(self, tool_name: str) -> bool:
        return tool_name in self.tools

    def allows_bash(self, command: str) -> bool:
        """判断命令是否命中任一 Bash 作用域。"""
        if self._bash_all:
            return True
        cmd = command.strip()
        if not cmd:
            return False
        for scope in self.bash_scopes:
            if _scope_match(cmd, scope):
                return True
        return False

    def scopes_text(self) -> str:
        parts = []
        for t in sorted(self.tools):
            parts.append(t)
        for s in self.bash_scopes:
            parts.append(f"Bash({s})")
        return ", ".join(parts) or "(空)"


def _scope_match(command: str, scope: str) -> bool:
    """匹配命令与作用域: 前缀匹配 + * 通配。"""
    scope = scope.strip()
    if not scope:
        return False
    if "*" in scope:
        # 转 glob 到正则
        rx = _glob_to_regex(scope)
        return bool(re.search(rx, command, re.IGNORECASE))
    # 前缀匹配: `npm test` 放行 `npm test -- --watch`
    return command.lower().startswith(scope.lower()[:])


@dataclass
class DeniedTools:
    """解析后的 disallowedTools 规格 (对标 Claude Code --disallowedTools)。

    与 :class:`AllowedTools` 同一语法, 语义相反: 命中者**硬拒**, 优先级高于
    白名单/YOLO —— 用户显式声明"不许用"就该不许用。
    """
    tools: set[str] = field(default_factory=set)          # 普通工具名
    bash_scopes: List[str] = field(default_factory=list)  # Bash 作用域

    @classmethod
    def parse(cls, raw: Optional[str]) -> "DeniedTools":
        obj = cls()
        if not raw:
            return obj
        try:
            from ..config.settings_file import normalize_tool_name
        except Exception:  # noqa: BLE001 - 归一不可用时原样存储
            normalize_tool_name = lambda x: x  # type: ignore[assignment]
        for piece in raw.split(","):
            piece = piece.strip()
            if not piece:
                continue
            m = re.fullmatch(r"Bash\((.*)\)", piece)
            if m:
                scope = m.group(1).strip()
                if scope and scope != "*":
                    obj.bash_scopes.append(scope)
                else:
                    obj.bash_scopes.append("*")
                continue
            obj.tools.add(normalize_tool_name(piece))
        return obj

    def denies_tool(self, tool_name: str) -> bool:
        # 工具名归一 (read_file→Read, edit_file→Edit 等), 与 settings_file 对齐
        try:
            from ..config.settings_file import normalize_tool_name
            key = normalize_tool_name(tool_name)
        except Exception:  # noqa: BLE001 - 归一不可用时回退原始名
            key = str(tool_name).strip()
        return key in self.tools

    def denies_bash(self, command: str) -> bool:
        """判断命令是否命中任一禁用作用域。"""
        if "*" in self.bash_scopes:
            return True
        cmd = command.strip()
        if not cmd:
            return False
        return any(_scope_match(cmd, s) for s in self.bash_scopes)

    def scopes_text(self) -> str:
        parts = [t for t in sorted(self.tools)]
        parts += [f"Bash({s})" for s in self.bash_scopes]
        return ", ".join(parts) or "(空)"


def _glob_to_regex(pattern: str) -> str:
    import re as _re

    out = []
    for ch in pattern:
        if ch == "*":
            out.append(".*")
        elif ch == " ":
            out.append(r"\s+")
        elif ch == ":":
            # Claude Code 作用域分隔符: `Bash(git push:*)` 意为「git push 命令本身
            # 或其带参数调用」——冒号须匹配「行尾」或「参数前的空白」, 而非字面冒号。
            out.append(r"(?:$|\s+)")
        elif ch in ".^$+?()[]{}|\\-":
            out.append("\\" + ch)
        else:
            out.append(_re.escape(ch))
    return "".join(out)


def mode_tool_filter(tool_name: str, mode_id: str) -> bool:
    """按模式过滤工具调用。返回 True=允许, False=拒绝。

    逻辑:
    - 若模式白名单为空 (如 boundless on android), 拒绝所有工具 (fail-closed)。
    - 否则检查 tool_name 是否在白名单中。
    """
    from ..modes.policy import get_mode_policy
    policy = get_mode_policy(mode_id)
    allowlist = policy.tool_allowlist()
    if not allowlist:
        return False  # 无白名单=默认拒绝（fail-closed，如 boundless on android）
    return tool_name in allowlist
