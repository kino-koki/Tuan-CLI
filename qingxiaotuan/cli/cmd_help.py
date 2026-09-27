"""帮助系统: 分类帮助 / 单命令详情 / 快捷键 / `qxt commands` JSON 输出。

对标竞品帮助系统:
- ``/help``            分类列出所有斜杠命令 (对话管理 / 代码 / 技能 / 系统 / 边界);
- ``/help <command>``  显示某命令的详细用法 / 示例 / 参数;
- ``/help keyboard``    显示 TUI 快捷键列表;
- ``qxt commands``      以 JSON 输出全部命令及元数据 (供 IDE / 外部工具消费);
- ``qxt help``         与 ``qxt --help`` 等效 (沿用 argparse)。

命令元数据单一来源: ``qingxiaotuan.cli.cmd_slash._CMD_META``, 避免多处维护漂移。
"""

from __future__ import annotations

import json
import sys
from typing import Dict, List, Optional


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
        "/model", "/provider", "/login", "/effort", "/mode", "/plan",
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
        "params": "目标: 自然语言目标, qxt 自动循环直到完成",
        "example": "/goal 给所有路由加上鉴权",
    },
    "/init": {
        "usage": "/init",
        "params": "无参数; 扫描当前工作区生成 QXT.md 项目规则",
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
    """生成分类帮助文本 (纯文本, 供 /help 与 qxt help 使用)。"""
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
    """聚合全部斜杠命令 + 分类 + 描述, 供 qxt commands / ACP IDE 消费。"""
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


def cmd_commands(args) -> int:
    """`qxt commands`: 以 JSON 输出全部斜杠命令元数据。"""
    payload = {
        "commands": all_commands_metadata(),
        "keyboard_shortcuts": [
            {"key": k, "action": d} for k, d in KEYBOARD_SHORTCUTS
        ],
    }
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    return 0
