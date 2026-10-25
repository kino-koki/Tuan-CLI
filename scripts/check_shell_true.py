#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""shell=True 门禁 (Task G).

扫描 ``tuan_cli/**.py`` 里所有 ``shell=True`` / ``shell = True`` 调用点, 与
**显式白名单** 比对; 白名单外的新调用点直接 ``exit 1`` 并打印.

设计要点
--------
1. 纯 stdlib, **不 import 项目包** —— 保证 CI 无安装环境也能跑.
2. 白名单以 (相对路径, 行号, 内容锚点, 理由) 元组形式硬编码在本文件里,
   便于 review; 白名单**条目数 == 当前实测 25 处**, 覆盖当前全部匹配行
   (含注释里的 ``shell=True`` 文字常量 —— 例如 ``ext/ast_scan.py`` 的正则
   字符串常量在扫描用户的 ``shell=True``, 它不是真调用, 但会命中正则,
   所以也需要列入白名单).
3. 白名单里未匹配的条目会给出 WARNING (说明条目已过期), 但不 fail; 只有
   **扫描出来但白名单里没有** 才 fail. 这样白名单可以安全地按行号漂动,
   不会因为无关重构导致门禁红.

用法
----
  python scripts/check_shell_true.py              # 扫描 + 比对, 未授权调用点 exit 1

退出码
------
  0  全部匹配行都在白名单内
  1  至少有一个 ``shell=True`` 行不在白名单
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "tuan_cli"

# 与 grep ``shell\s*=\s*True`` 完全一致的匹配: 大小写敏感, 允许两侧空格.
SHELL_TRUE_RE = re.compile(r"shell\s*=\s*True\b")

SKIP_DIRS = {
    "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".hypothesis",
    "htmlcov", "coverage", ".venv", "venv", ".git", ".tox", ".nox",
}

# ---------------------------------------------------------------------------
# 白名单: (相对 tuan_cli/ 的路径, 行号, 内容锚点, 理由)
#   理由分类:
#     USER_INPUT  - 命令由用户/LLM 直接提供, 无法安全转 list.
#     SHELL_META  - 命令包含 | & ; > < 等 shell 元字符, 需 shell 解释.
#     REGEX_CONST - 字符串常量 (正则或错误消息) 里出现的 "shell=True" 字样,
#                   不是真实调用点, 但会命中正则, 需要白名单豁免.
#     COMMENT     - 代码注释中的文字描述, 不是真实调用点.
#     PLUGIN_HOOK - 命令来自插件 manifest, 视为外部用户输入.
#     SAFE_FALLBACK - 已做 shlex 优先, 只在检测到 shell 元字符时才回退 shell=True.
# ---------------------------------------------------------------------------
WHITELIST: list[tuple[str, int, str, str]] = [
    # ---------------------------------------
    # COMMENT / REGEX_CONST: 文字常量, 非真调用点
    # ---------------------------------------
    # 描述: 讲背景知识, 说明裸 shell=True 超时的问题.
    ("core/proc.py", 3, "`subprocess.run(cmd, shell=True", "COMMENT"),
    ("core/proc.py", 28, "直接用 `shell=True`", "COMMENT"),
    # 描述: 教程步骤里"什么时候才回退到 shell"的说明.
    ("cli/cmd_tutorial.py", 71, "回退到 shell=True", "COMMENT"),
    ("cli/cmd_tutorial.py", 79, "回退到 shell=True", "COMMENT"),
    # 描述: ast_scan 里说明"shell=True 检测"的注释和正则字符串常量,
    # 用于扫描**用户代码**里是否使用 shell=True, 不是自身调用.
    ("ext/ast_scan.py", 72, "shell=True 参数", "COMMENT"),
    ("ext/ast_scan.py", 76, "shell=True 或位置参数", "COMMENT"),
    ("ext/ast_scan.py", 184, "shell=True", "COMMENT"),
    ("ext/ast_scan.py", 193, "shell=True", "REGEX_CONST"),
    ("ext/ast_scan.py", 194, '"shell=True"', "REGEX_CONST"),
    # code_review 里的正则字符串, 用于扫描**用户代码**是否用了 shell=True.
    ("tools/code_review.py", 94, "shell\\s*=\\s*True", "REGEX_CONST"),

    # ---------------------------------------
    # 真实调用点 (USER_INPUT / SHELL_META / PLUGIN_HOOK / SAFE_FALLBACK)
    # ---------------------------------------
    # 用户命令: `!`code` 语法预执行的 stdout, cmd 完全由用户在 prompt 里给出.
    ("cli/user_commands.py", 142, "shell=True, capture_output=True", "USER_INPUT"),
    # 教程演示命令: 优先 shlex, 命令含 shell 元字符时才回退 shell=True.
    ("cli/cmd_tutorial.py", 89, "shell=True, timeout=120", "SAFE_FALLBACK"),
    # code_edit 验证循环: cmd 由 agent 生成的验证命令, 可能含管道/重定向.
    ("code_edit/verify_loop.py", 53, "shell=True, cwd=cwd", "USER_INPUT"),
    # core 验证循环: cmd 来自 agent/规划器, 可能是 shell 复合语句.
    ("core/verify_loop.py", 319, "shell=True, cwd=workspace", "USER_INPUT"),
    # Reflector 的内置验证命令字典里全是 "pytest -x -q 2>&1" 这类带重定向的
    # shell 语法字符串; 转 list 会丢掉 2>&1, 输出合并语义.
    ("core/reflector.py", 155, "shell=True, cwd=str(self.workspace)", "SHELL_META"),
    # 后台 shell 命令: 用户显式创建的 job 命令, 允许 pipe/redirect.
    ("core/background_shell.py", 269, "normalized, shell=True", "USER_INPUT"),
    # Web UI 的 shell 执行入口: 命令来自 HTTP body, 经安全评估 + 用户审批.
    ("web/server.py", 607, "command, shell=True", "USER_INPUT"),
    # tools/shell.py 主入口: LLM/用户提供的 shell 命令, 显式 shell 语义.
    ("tools/shell.py", 690, "shell=True,", "USER_INPUT"),
    # tools/code.py 的 run_tests/git_status: 命令由 LLM 生成, 允许组合.
    ("tools/code.py", 317, "command, shell=True", "USER_INPUT"),
    # MCP 沙箱本地执行: 命令由 MCP server 提供 (外部不可信), 必须 shell 语法.
    ("tools/mcp/sandbox.py", 229, "shell=True,", "USER_INPUT"),
    # MCP server 的 tuan_run 工具: 命令来自 MCP client (外部), 显式 shell.
    ("ecosystem/mcp_server.py", 344, "command, shell=True", "USER_INPUT"),
    # 沙箱管理器 local 后端: 命令来自被沙箱化的外部调用.
    ("sandbox/manager.py", 280, "command, shell=True", "USER_INPUT"),
    # 插件 SDK: hook_cmd / headersHelper.command 由插件 manifest 声明,
    # 视为外部用户输入 (插件作者).
    ("skills/plugin_sdk.py", 338, "shell=True,", "PLUGIN_HOOK"),
    ("skills/plugin_sdk.py", 364, "shell=True,", "PLUGIN_HOOK"),
    ("skills/plugin_sdk.py", 402, "shell=True,", "PLUGIN_HOOK"),
]


def _is_skip_dir(p: Path) -> bool:
    return any(part in SKIP_DIRS for part in p.parts)


def scan() -> list[tuple[str, int, str]]:
    """遍历 tuan_cli/, 返回所有 ``shell=True`` 行 (relpath, lineno, line_text)."""
    hits: list[tuple[str, int, str]] = []
    for p in SRC.rglob("*.py"):
        if _is_skip_dir(p.relative_to(SRC)):
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except OSError as exc:
            print(f"WARN: cannot read {p}: {exc}", file=sys.stderr)
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            if SHELL_TRUE_RE.search(line):
                rel = p.relative_to(SRC).as_posix()
                hits.append((rel, lineno, line.rstrip()))
    return hits


def main() -> int:
    hits = scan()
    # 建白名单索引: (relpath, lineno) -> entry
    wl_by_pos: dict[tuple[str, int], tuple[str, int, str, str]] = {}
    for entry in WHITELIST:
        wl_by_pos[(entry[0], entry[1])] = entry

    unauthorized: list[tuple[str, int, str]] = []
    authorized: list[tuple[str, int, str, str]] = []
    consumed: set[tuple[str, int]] = set()

    for rel, lineno, text in hits:
        key = (rel, lineno)
        entry = wl_by_pos.get(key)
        if entry is None:
            unauthorized.append((rel, lineno, text))
        else:
            consumed.add(key)
            # 校验锚点是否仍匹配当前行内容 (防止行内内容漂移而没更新白名单)
            anchor = entry[2]
            if anchor and anchor not in text:
                print(
                    f"WARN anchor drift: {rel}:{lineno}\n"
                    f"      whitelist anchor: {anchor!r}\n"
                    f"      actual line     : {text!r}",
                    file=sys.stderr,
                )
            authorized.append((rel, lineno, text, entry[3]))

    # 未匹配的白名单条目 (说明已过期, 不 fail, 只 warn)
    unused = [e for e in WHITELIST if (e[0], e[1]) not in consumed]

    print(f"shell=True gate: scanned {len(hits)} hit(s), "
          f"authorized {len(authorized)}, unauthorized {len(unauthorized)}, "
          f"unused whitelist {len(unused)}")

    if unauthorized:
        print("\n[FAIL] Unwhitelisted shell=True occurrences:")
        for rel, lineno, text in unauthorized:
            print(f"  {rel}:{lineno}  {text.strip()}")
        print(
            "\nAction: review each line. If the command is safe (pure internal "
            "constants, no user input), convert to a list argument and pass "
            "shell=False. Otherwise, add an entry to WHITELIST in "
            "scripts/check_shell_true.py with a reason (see classification "
            "comment at the top of that file)."
        )
        return 1

    if unused:
        print("\n[WARN] Whitelist entries no longer match any live line:")
        for rel, lineno, anchor, reason in unused:
            print(f"  {rel}:{lineno}  anchor={anchor!r}  reason={reason}")
        print("  (These are stale; prune them at your convenience — not fatal.)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
