#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""shell=True 门禁 (Task G).

扫描 ``tuan_cli/**.py`` 里所有 ``shell=True`` / ``shell = True`` 调用点, 与
**显式白名单** 比对; 白名单外的新调用点直接 ``exit 1`` 并打印.

设计要点
--------
1. 纯 stdlib, **不 import 项目包** —— 保证 CI 无安装环境也能跑.
2. 白名单以 (相对路径, 内容锚点, 理由) 元组形式硬编码在本文件里,
   便于 review. 元组仍保留行号字段仅为**文档性提示** (写白名单时的定位线索),
   匹配时**不使用** —— 见下条.
3. 匹配**只按 (相对路径 + 内容锚点)**, 忽略行号. 这是本门禁的核心承诺:
   白名单可以安全地按行号漂动, 任何无关重构 (增删行 / 文件搬迁) 都不会
   导致门禁红. 若同一文件内同一锚点出现多次 (例如 plugin_sdk.py 的三处
   ``shell=True,``), 按多重集逐个消耗, 数量不匹配才算失配.
4. 白名单里未消耗的条目会给出 WARNING (说明条目已过期), 但不 fail; 只有
   **扫描出来但白名单里没有** 才 fail.

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
    # 注意: 第 2 个字段 (行号) 仅作文档提示, 匹配时忽略 (见模块 docstring 第 3 条)。
    # 匹配键 = (相对路径, 内容锚点)。锚点必须是该行 `shell=True` 附近的稳定子串。
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
    # tui/codexkit 与 web 模块的文档注释: 描述"永不 shell=True"的设计约束,
    # 属于对既有调用的反面声明, 不是自身调用点.
    ("tui/codexkit/stream_exec.py", 13, "命令用 `shell=True` 拼接", "COMMENT"),
    ("tui/codexkit/stream_exec.py", 288, "**永不** ``shell=True``", "COMMENT"),
    ("tui/codexkit/__init__.py", 31, "命令 ``shell=True`` 拼接", "COMMENT"),
    ("web/code_anim_render.py", 7, "永不 ``shell=True``", "COMMENT"),
    ("web/mh_runner.py", 5, "永不使用 ``shell=True``", "COMMENT"),
    # parity_claude/catalog.py: 差距分析文档里描述安全边界的长注释,
    # 提及 shell=True 是叙述性文字, 非调用点.
    ("parity_claude/catalog.py", 143, "MCP `run_shell` 是另一处 shell=True 入口", "COMMENT"),

    # ---------------------------------------
    # 真实调用点 (USER_INPUT / SHELL_META / PLUGIN_HOOK / SAFE_FALLBACK)
    # ---------------------------------------
    # 用户命令: `!`code` 语法预执行的 stdout, cmd 完全由用户在 prompt 里给出.
    ("cli/user_commands.py", 142, "shell=True, capture_output=True", "USER_INPUT"),
    # 教程演示命令的真实调用点: 优先 shlex, 命令含 shell 元字符时才回退 shell=True.
    ("cli/cmd_tutorial.py", 90, "r = subprocess.run(cmd, shell=True, timeout=120)", "SAFE_FALLBACK"),
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
    # (唯一真实调用点见下方 1092 行条目; 旧 607 行短锚点条目是同一调用点的
    # 行号漂移冗余, 已随锚点匹配改造删除 —— 607 行现无 shell=True。) 
    # tools/shell.py 主入口: LLM/用户提供的 shell 命令, 显式 shell 语义.
    # (唯一真实调用点见下方 738 行条目; 旧 690 行 docstring 条目已随
    # 锚点匹配改造移除 —— 690 行并无 shell=True, 是行号漂移残留。)
    # tools/code.py 的 run_tests/git_status: 命令由 LLM 生成, 允许组合.
    ("tools/code.py", 317, "command, shell=True", "USER_INPUT"),
    # MCP 沙箱本地执行: 命令由 MCP server 提供 (外部不可信), 必须 shell 语法.
    ("tools/mcp/sandbox.py", 229, "shell=True,", "USER_INPUT"),
    # MCP server 的 tuan_run 工具: 命令来自 MCP client (外部), 显式 shell.
    # (唯一真实调用点见下方 376 行条目; 旧 344 行短锚点条目是同一调用点的
    # 行号漂移冗余, 已删除 —— 344 行现无 shell=True。)
    # 沙箱管理器 local 后端: 命令来自被沙箱化的外部调用.
    # (唯一真实调用点见下方 449 行条目; 旧 280 行短锚点条目是同一调用点的
    # 行号漂移冗余, 已删除 —— 280 行现无 shell=True。)
    # 插件 SDK: hook_cmd / headersHelper.command 由插件 manifest 声明,
    # 视为外部用户输入 (插件作者).
    ("skills/plugin_sdk.py", 338, "shell=True,", "PLUGIN_HOOK"),
    ("skills/plugin_sdk.py", 364, "shell=True,", "PLUGIN_HOOK"),
    ("skills/plugin_sdk.py", 402, "shell=True,", "PLUGIN_HOOK"),
    # 0.4.4: _run_hook 的 docstring 里描述了 "直接 shell=True 执行" 的设计,
    # 是文字常量不是调用点 (真实调用点由上面三条 PLUGIN_HOOK 覆盖).
    ("skills/plugin_sdk.py", 532, "直接 shell=True 执行", "COMMENT"),
    # tui/render.py: /statusline 自定义命令来自用户配置, 渲染线程后台跑.
    ("tui/render.py", 117, "cmd, shell=True, capture_output=True", "USER_INPUT"),
    # web/handler.py & web/server.py: shell 命令来自 HTTP body, 经安全评估+审批.
    ("web/handler.py", 453, "command, shell=True, cwd=self._owner.workspace", "USER_INPUT"),
    ("web/server.py", 1092, "command, shell=True, cwd=self._owner.workspace,", "USER_INPUT"),
    # tools/shell.py 真实执行点 (normalize_shell_command 已 shlex 预解析).
    ("tools/shell.py", 738, "shell=True,", "USER_INPUT"),
    # sandbox/manager.py 真实执行点 (run_with_tree_kill 包 shell 复合命令).
    ("sandbox/manager.py", 449, "command, shell=True, cwd=cwd,", "USER_INPUT"),
    # ecosystem/mcp_server.py 真实执行点.
    ("ecosystem/mcp_server.py", 376, "command, shell=True, capture_output=True,", "USER_INPUT"),
    # 0.4.4 合并: _h_run_shell 的 docstring 描述 (文字常量, 非调用点).
    ("ecosystem/mcp_server.py", 676, "用 ``shell=True`` 执行", "COMMENT"),
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


def render_doc() -> str:
    """把白名单渲染成 markdown, 供 docs/shell_true_whitelist.md 公开说明。"""
    lines = [
        "# `shell=True` 白名单公开说明",
        "",
        "> 本文档由 `python scripts/check_shell_true.py --doc` 生成, 与 CI 门禁",
        "> (`scripts/check_shell_true.py`) 的 WHITELIST 表同源, 请勿手改;",
        "> 修改白名单后重新生成即可。",
        "",
        "门禁规则: `tuan_cli/**.py` 中任何 `shell=True` 调用点必须出现在下表",
        "(按 文件 + 内容锚点 匹配, 行号仅作文档提示)。白名单外的新调用点直接",
        "使 CI 失败。",
        "",
        f"当前白名单条目: {len(WHITELIST)} 条。",
        "",
        "| 文件 (相对 tuan_cli/) | 写入行号 | 锚点 | 必要性分类 |",
        "|---|---|---|---|",
    ]
    reason_desc = {
        "USER_INPUT": "命令由用户/LLM 直接提供, 无法安全转 list",
        "SHELL_META": "命令含 | & ; > < 等 shell 元字符, 需 shell 解释",
        "REGEX_CONST": "正则/错误消息字符串常量里的字样, 非真实调用点",
        "COMMENT": "注释中的文字描述, 非真实调用点",
        "PLUGIN_HOOK": "命令来自插件 manifest (插件作者 = 外部输入)",
        "SAFE_FALLBACK": "已 shlex 优先, 仅检测到 shell 元字符才回退 shell=True",
    }
    for rel, lineno, anchor, reason in WHITELIST:
        lines.append(f"| `{rel}` | {lineno} | `{anchor}` | {reason} — {reason_desc.get(reason, reason)} |")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    if "--doc" in sys.argv:
        print(render_doc())
        return 0
    hits = scan()
    # 按 (relpath, 锚点) 建立索引; 同一文件同一锚点可出现多次
    # (如 plugin_sdk.py 的三处 `shell=True,`), 因此按**条目索引**逐条消耗,
    # 而不是按 (relpath, 锚点) 键消耗 —— 否则同键第二条起全部误判为未授权。
    wl_by_key: dict[tuple[str, str], list[int]] = {}
    for idx, entry in enumerate(WHITELIST):
        wl_by_key.setdefault((entry[0], entry[2]), []).append(idx)

    unauthorized: list[tuple[str, int, str]] = []
    authorized: list[tuple[str, int, str, str]] = []
    consumed: set[int] = set()

    for rel, lineno, text in hits:
        # 锚点匹配: 找一条 (同 rel, 锚点是当前行子串) 的未消耗条目索引。
        # 同一文件内若多条锚点都命中 (如 web/server.py 的 `command, shell=True`
        # 是 `command, shell=True, cwd=...` 的前缀), 取**锚点最长**的那条 ——
        # 更具体的锚点优先, 避免前缀子串抢配导致具体锚点被误报为 stale。
        entry_idx = None
        best_anchor_len = -1
        for (file_key, anchor), bucket in wl_by_key.items():
            if file_key != rel:
                continue
            for idx in bucket:
                if idx in consumed:
                    continue
                if anchor and anchor in text and len(anchor) > best_anchor_len:
                    entry_idx = idx
                    best_anchor_len = len(anchor)
        if entry_idx is None:
            unauthorized.append((rel, lineno, text))
        else:
            consumed.add(entry_idx)
            authorized.append((rel, lineno, text, WHITELIST[entry_idx][3]))

    # 未消耗的白名单条目 (说明已过期, 不 fail, 只 warn)
    unused = [e for i, e in enumerate(WHITELIST) if i not in consumed]

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
