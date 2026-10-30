"""帮助系统: 分类帮助 / 单命令详情 / 快捷键 / `tuan commands` JSON 输出。

对标竞品帮助系统:
- ``/help``            分类列出所有斜杠命令 (对话管理 / 代码 / 技能 / 系统 / 边界);
- ``/help <command>``  显示某命令的详细用法 / 示例 / 参数;
- ``/help keyboard``    显示 TUI 快捷键列表;
- ``tuan commands``      以 JSON 输出全部命令及元数据 (供 IDE / 外部工具消费);
- ``tuan help``         与 ``tuan --help`` 等效 (沿用 argparse)。

命令元数据单一来源: ``tuan_cli.cli.cmd_slash._CMD_META``, 避免多处维护漂移。
"""

from __future__ import annotations

import json
import sys
from typing import Any, Dict, List, Optional


# ------------------------------------------------------------------ 分类
# 四层边界: 对话管理 / 代码与工程 / 技能与记忆 / 系统与权限

CATEGORIZED_HELP: "Dict[str, List[str]]" = {
    "对话管理": [
        "/help", "/clear", "/compact", "/context", "/usage", "/cost", "/budget",
        "/resume", "/export", "/import", "/checkpoint", "/rewind", "/handoff",
        "/more", "/exit", "/quit",
    ],
    "代码与工程": [
        "/diff", "/undo", "/impact", "/log", "/verify", "/code", "/worktree",
        "/workflow", "/gh-borrow", "/web",
    ],
    "技能与记忆": [
        "/skills", "/memory", "/commands", "/subagent", "/swarm", "/route",
    ],
    "系统与权限": [
        "/model", "/provider", "/effort", "/mode", "/plan",
        "/permissions", "/sandbox", "/offline", "/audit", "/status", "/stats",
        "/hooks", "/mcp", "/mcp-tools", "/image", "/images", "/clear-images",
        "/init", "/goal", "/blast",
    ],
}

# 单命令详细用法 (用法 / 参数 / 示例); 未收录的回退一句话描述。
_DETAIL: Dict[str, Dict[str, str]] = {
    "/help": {
        "usage": "/help [命令名] | /help keyboard",
        "params": "命令名: 如 /help diff; keyboard: 显示 TUI 快捷键",
        "example": "/help diff\n/help keyboard",
    },
    "/diff": {
        "usage": "/diff [文件] | /diff --full",
        "params": "文件: 只看该文件改动; --full: 显示完整 diff (而非摘要)",
        "example": "/diff\n/diff src/foo.py\n/diff --full",
    },
    "/undo": {
        "usage": "/undo [N | <文件> | all | --safe]",
        "params": "N: 回退 N 步; <文件>: 只回退该文件; all: 全部; --safe: 仅回退安全操作",
        "example": "/undo\n/undo 2\n/undo README.md",
    },
    "/goal": {
        "usage": "/goal <目标描述>",
        "params": "目标: 自然语言目标, tuan 自动循环直到完成",
        "example": "/goal 给所有路由加上鉴权",
    },
    "/init": {
        "usage": "/init",
        "params": "无参数; 扫描当前工作区生成 TUAN.md 项目规则",
        "example": "/init",
    },
    "/compact": {
        "usage": "/compact",
        "params": "无参数; 折叠旧历史, 释放上下文窗口",
        "example": "/compact",
    },
    "/clear": {
        "usage": "/clear",
        "params": "无参数; 清空当前对话上下文 (不影响磁盘会话)",
        "example": "/clear",
    },
    "/model": {
        "usage": "/model [switch <provider> <model>]",
        "params": "无参: 查看当前; switch: 热切换模型 (不写盘)",
        "example": "/model\n/model switch deepseek deepseek-chat",
    },
    "/usage": {
        "usage": "/usage",
        "params": "无参数; 显示本次会话 token 用量",
        "example": "/usage",
    },
}

# TUI 快捷键 (供 /help keyboard)
KEYBOARD_SHORTCUTS: List[List[str]] = [
    ["Enter", "发送消息"],
    ["Esc+Enter", "换行 (多行输入)"],
    ["/ 或 +/", "弹出斜杠命令补全菜单"],
    ["Tab", "补全菜单内切换"],
    ["Ctrl+C", "中断当前生成"],
    ["Ctrl+D", "退出"],
]


def _meta() -> Dict[str, str]:
    """取命令一句话描述表 (惰性导入, 避免循环依赖)。"""
    from .cmd_slash import slash_command_meta
    return slash_command_meta()


def categorized_help_text() -> str:
    """生成分类帮助文本 (纯文本, 供 /help 与 tuan help 使用)。"""
    meta = _meta()
    lines = ["可用斜杠命令 (按分类):", ""]
    for cat, names in CATEGORIZED_HELP.items():
        lines.append(f"  ── {cat} ──")
        for name in names:
            desc = meta.get(name, "")
            lines.append(f"    {name:<14} {desc}")
        lines.append("")
    lines.append("提示: /help <命令名> 看详细用法; /help keyboard 看快捷键")
    return "\n".join(lines)


def help_for_command(name: str) -> str:
    """生成单个命令的详细帮助; 未知命令返回提示。"""
    name = name.strip()
    if not name.startswith("/"):
        name = "/" + name
    if name == "/keyboard":
        out = ["TUI 快捷键:"]
        for k, desc in KEYBOARD_SHORTCUTS:
            out.append(f"  {k:<16} {desc}")
        return "\n".join(out)
    meta = _meta()
    if name not in meta and name not in _DETAIL:
        return f"未知命令: {name} (输入 /help 查看全部命令)"
    out = [f"{name}  —  {meta.get(name, '')}"]
    detail = _DETAIL.get(name)
    if detail:
        out.append(f"  用法: {detail['usage']}")
        out.append(f"  参数: {detail['params']}")
        out.append(f"  示例: {detail['example']}")
    return "\n".join(out)


def all_commands_metadata() -> List[Dict[str, str]]:
    """聚合全部斜杠命令 + 分类 + 描述, 供 tuan commands / ACP IDE 消费。"""
    meta = _meta()
    cat_of: Dict[str, str] = {}
    for cat, names in CATEGORIZED_HELP.items():
        for n in names:
            cat_of[n] = cat
    result: List[Dict[str, str]] = []
    for name in sorted(meta.keys()):
        result.append({
            "name": name,
            "description": meta[name],
            "category": cat_of.get(name, "其他"),
        })
    return result


def cmd_commands(args: Any) -> int:
    """`tuan commands`: 以 JSON 输出全部斜杠命令元数据。"""
    payload = {
        "commands": all_commands_metadata(),
        "keyboard_shortcuts": [
            {"key": k, "action": d} for k, d in KEYBOARD_SHORTCUTS
        ],
    }
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    return 0


def cmd_help(args: Any) -> int:
    """`tuan help`：显示帮助（总览或特定子命令）。"""
    from ..ui.plain_console import console

    topic = getattr(args, "topic", None)

    if topic == "quickstart":
        _show_quickstart()
        return 0
    elif topic:
        # 显示特定子命令帮助：通过 parser 解析该子命令的 --help，避免 sys.argv 全局修改
        from .parser import build_parser
        parser = build_parser()
        try:
            parser.parse_args([topic, "--help"])
        except SystemExit as exc:
            return int(exc.code) if isinstance(exc.code, int) else 0
        return 2
    else:
        _show_overview()
        return 0


def _show_overview() -> None:
    """显示帮助总览（包含快速上手指南链接）。"""
    from ..ui.plain_console import console

    console.print("""
[bold]青小团 CLI (Tuan-CLI) 帮助总览[/bold]

[bold]快速开始：[/bold]
  • [cyan]tuan help quickstart[/cyan] - 查看快速上手指南（推荐新手）
  • [cyan]tuan setup[/cyan]        - 首次运行初始化向导
  • [cyan]tuan --version[/cyan]    - 查看当前版本

[bold]核心模式：[/bold]
  • [cyan]tuan[/cyan]            - 标准模式（需要确认）
  • [cyan]tuan --yolo[/cyan]     - Yolo 模式（自动批准）
  • [cyan]tuan --plan[/cyan]     - Plan 模式（只读规划）
  • [cyan]tuan --isolation[/cyan] - 进程级隔离模式

[bold]查看子命令帮助：[/bold]
  • [cyan]tuan help <子命令>[/cyan]  - 显示特定子命令帮助
  • [cyan]tuan help commands[/cyan]   - 查看所有斜杠命令
  • [cyan]tuan help quickstart[/cyan] - 查看快速上手指南（推荐新手）

[bold]环境诊断：[/bold]
  • [cyan]tuan doctor[/cyan] - 环境健康检查

[bold]更多资源：[/bold]
  • GitHub: https://github.com/kino-koki/Tuan-CLI
  • 文档: [cyan]https://github.com/kino-koki/Tuan-CLI#readme[/cyan]
    """)


def _show_quickstart() -> None:
    """显示快速上手指南（从 docs/QUICKSTART.md 读取）。"""
    from ..ui.plain_console import console
    from pathlib import Path
    import os

    # 多种路径解析策略，兼容源码树、pip 安装、冻结可执行文件等场景
    candidates = []
    # 1. 相对于当前模块文件（源码树: tuan_cli/cli/ -> 项目根 -> docs/）
    candidates.append(Path(__file__).resolve().parent.parent.parent / "docs" / "QUICKSTART.md")
    # 2. 相对于 CWD（用户从项目根运行）
    candidates.append(Path.cwd() / "docs" / "QUICKSTART.md")
    # 3. 相对于 package 安装位置
    try:
        import importlib.resources
        pkg = importlib.resources.files("tuan_cli")
        candidates.append(Path(str(pkg)) / "docs" / "QUICKSTART.md")
    except Exception:
        pass

    quickstart_path = None
    for p in candidates:
        if p.is_file():
            quickstart_path = p
            break

    if quickstart_path is None:
        console.print(f"[red]快速上手指南未找到[/red]")
        console.print("[yellow]请确保 docs/QUICKSTART.md 文件存在于项目根目录。[/yellow]")
        return

    try:
        content = quickstart_path.read_text(encoding="utf-8")

        # 简单的 Markdown 到 Console 的转换（只保留标题和粗体）
        lines = content.split("\n")

        # 提取标题和关键部分
        for line in lines:
            line = line.rstrip()
            if not line:
                continue

            # 标题
            if line.startswith("##"):
                level = line.count("#") - 1
                prefix = "  " * (level - 1) + ("[bold]" if level == 1 else "")
                suffix = "[/bold]" if level == 1 else ""
                console.print(f"{prefix}{line.strip('# ').strip()} {suffix}")
            # 粗体
            elif line.startswith("**") and line.endswith("**"):
                console.print(f"[bold]{line[2:-2]}[/bold]")
            # 命令代码块
            elif line.startswith("`"):
                code = line.strip("`")
                console.print(f"[dim]{code}[/dim]")
            # 列表项
            elif line.startswith("•"):
                console.print(f"[dim]  {line[1:].strip()}[/dim]")
            # 空行
            elif line == "":
                console.print("")
            # 其他（跳过）
            else:
                pass

        console.print("\n[bold][cyan]提示：[/cyan][/bold] 完整文档请查看 [cyan]docs/QUICKSTART.md[/cyan]")
    except Exception as e:
        console.print(f"[red]读取快速上手指南失败: {e}[/red]")
        console.print("[yellow]请手动查看 docs/QUICKSTART.md 文件。[/yellow]")


# 注册本模块的命令函数到全局注册表
from .parser import _register_command
_register_command("cmd_help", ".cmd_help")

