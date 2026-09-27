"""`qxt ecosystem` —— 生态互操作总入口。

把青小团变成 Agent 生态的互操作枢纽: 一条命令完成
Claude Code / Hermes Agent 资产的双向搬运、MCP 暴露与委派。

    qxt ecosystem scan                    探测本机 Claude Code / Hermes 及其资产
    qxt ecosystem status                  连接状态 + 资产计数 + 开关
    qxt ecosystem import skills|memory|agents|context|mcp|all [--from claude|hermes|all] [--force]
    qxt ecosystem export skills|agents|memory [--to claude|hermes|all]
    qxt ecosystem link [--apply]          把 qxt 注册为 Claude Code 的 MCP server (写 .mcp.json)
                                           并给出 Hermes 的接入命令 (--apply 同时写入 hermes config)
    qxt ecosystem serve [--allow-dangerous]  以 MCP stdio server 运行, 供外部 Agent 挂载
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import TYPE_CHECKING, List, Optional

from ..config import Config
from ._ui_singleton import console
from ..ui.format import Table

if TYPE_CHECKING:
    from ..ecosystem.detect import EcosystemProbe

_IMPORT_KINDS = ("skills", "memory", "agents", "context", "mcp", "all")
_EXPORT_KINDS = ("skills", "agents", "memory")
_SOURCES = ("claude", "hermes", "all")


def _cfg(args) -> Config:
    return Config(profile=getattr(args, "profile", "default"),
                  patch_file=getattr(args, "patch", None))


def _probe(args, config: Optional[Config] = None) -> "EcosystemProbe":
    from ..ecosystem.detect import EcosystemProbe

    cfg = config or _cfg(args)
    workspace = getattr(args, "workspace", None)
    return EcosystemProbe.probe(workspace)


def _hint(ok: bool) -> str:
    return "✓" if ok else "✗"


# ---------------------------------------------------------------- scan / status

def _cmd_scan(args) -> int:
    from ..ecosystem.detect import render_probe

    probe = _probe(args)
    console.print(render_probe(probe))
    console.print("")
    console.print("资产盘点 (未安装或未配置的项目显示 0):")
    table = Table(title="Ecosystem Assets")
    table.add_column("生态")
    table.add_column("技能")
    table.add_column("Agents")
    table.add_column("命令")
    table.add_column("记忆")
    table.add_column("SOUL")
    table.add_column("MCP servers")
    for name, summary in probe.summarize().items():
        d = summary.to_dict()
        table.add_row(name, str(d["skills"]), str(d["agents"]), str(d["commands"]),
                      str(d["memories"]), "有" if d["soul"] else "-", str(d["mcp_servers"]))
    console.print(table)
    console.print("提示: `qxt ecosystem import all` 把双方资产并入青小团; `qxt ecosystem link` 反向挂载。")
    return 0


def _cmd_status(args) -> int:
    from ..ecosystem.detect import EcosystemProbe

    config = _cfg(args)
    probe = EcosystemProbe.probe(
        getattr(args, "workspace", None),
        hermes_home=config.get("ecosystem.hermes.home") or None,
    )
    table = Table(title="Ecosystem Status")
    table.add_column("项")
    table.add_column("状态")
    table.add_column("说明")
    table.add_row("Claude Code CLI", _hint(bool(probe.claude_cli)),
                  probe.claude_cli or "未安装 (claude 不在 PATH)")
    table.add_row("Claude Code 目录", _hint(probe.claude_home is not None),
                  str(probe.claude_home) if probe.claude_home else "未找到 ~/.claude")
    table.add_row("Hermes CLI", _hint(bool(probe.hermes_cli)),
                  probe.hermes_cli or "未安装 (hermes 不在 PATH)")
    table.add_row("Hermes 主目录", _hint(probe.hermes_home is not None),
                  str(probe.hermes_home) if probe.hermes_home else "未找到 ~/.hermes")
    table.add_row("导入 Claude 技能", "开" if config.get("ecosystem.claude_code.enabled", True) else "关",
                  "会话自动发现 .claude/skills")
    table.add_row("导入 Hermes 技能", "开" if config.get("ecosystem.hermes.enabled", True) else "关",
                  "会话自动发现 ~/.hermes/skills")
    table.add_row("MCP 危险工具", "开" if config.get("ecosystem.mcp.allow_dangerous_tools", False) else "关",
                  "run_shell 是否对外部 MCP 暴露 (默认关, fail-closed)")
    console.print(table)
    return 0


# ---------------------------------------------------------------- import

def _cmd_import(args) -> int:
    from ..ecosystem.detect import EcosystemProbe

    kind = args.kind
    src = getattr(args, "ecosystem_from", "all")
    config = _cfg(args)
    probe = EcosystemProbe.probe(
        getattr(args, "workspace", None),
        hermes_home=config.get("ecosystem.hermes.home") or None,
    )
    workspace = getattr(args, "workspace", None)
    sources = _sources_tuple(src)

    total = 0
    if kind in ("skills", "all"):
        n = _import_skills(config, probe, sources)
        console.print(f"技能导入: {n} 个")
        total += n
    if kind in ("memory", "all"):
        n = _import_memory(args, config, probe, sources)
        console.print(f"记忆导入: {n} 条")
        total += n
    if kind in ("agents", "all"):
        n = _import_agents(args, config, probe, sources)
        console.print(f"Agent 导入: {n} 个")
        total += n
    if kind in ("context", "all"):
        n = _import_context(args, config, probe, sources)
        console.print(f"上下文/人格导入: {n} 项")
        total += n
    if kind in ("mcp", "all"):
        n = _import_mcp(args, config, probe, sources)
        console.print(f"MCP server 导入: {n} 个")
        total += n
    console.print(f"合计导入 {total} 项。反向挂载: `qxt ecosystem link`。")
    return 0


def _sources_tuple(src: str) -> tuple:
    if src == "claude":
        return ("claude_code",)
    if src == "hermes":
        return ("hermes",)
    return ("claude_code", "hermes")


def _import_skills(config, probe, sources: tuple) -> int:
    from ..ecosystem.skills_bridge import import_skills
    from ..skills.manager import SkillManager

    manager = SkillManager(config.home, config=config)
    result = import_skills(manager, probe, sources=sources)
    for e in result.errors:
        console.print(f"  [技能] 失败: {e}")
    for s in result.skipped:
        console.print(f"  [技能] 跳过: {s}")
    return len(result.imported)


def _import_memory(args, config, probe, sources: tuple) -> int:
    from ..ecosystem.memory_bridge import import_hermes_memory
    from ..memory.store import MemoryStore

    if "hermes" not in sources:
        return 0
    store = MemoryStore(config.home)
    hermes_dirs = probe.hermes_memories_dirs
    result = import_hermes_memory(
        store, hermes_dirs,
        force_soul=getattr(args, "force", False),
        hermes_home=probe.hermes_home,
        qxt_home=config.home,
    )
    for e in result.errors:
        console.print(f"  [记忆] 失败: {e}")
    return len(result.memory_added) + len(result.user_added)


def _import_agents(args, config, probe, sources: tuple) -> int:
    from ..ecosystem.agents_bridge import import_claude_agents

    if "claude_code" not in sources:
        return 0
    result = import_claude_agents(
        probe.claude_agents_dirs, config.home / "agents",
        overwrite=getattr(args, "force", False),
    )
    for e in result.errors:
        console.print(f"  [Agent] 失败: {e}")
    return len(result.imported)


def _import_context(args, config, probe, sources: tuple) -> int:
    """导入上下文/人格: Hermes SOUL.md → qxt SOUL.md (存在且未 force 时跳过)。"""
    from ..ecosystem.memory_bridge import import_hermes_memory
    from ..memory.store import MemoryStore

    if "hermes" not in sources:
        return 0
    store = MemoryStore(config.home)
    result = import_hermes_memory(
        store, [], force_soul=getattr(args, "force", False),
        hermes_home=probe.hermes_home, qxt_home=config.home,
    )
    if result.soul_copied:
        console.print("  [SOUL] 已导入 Hermes SOUL.md → qxt SOUL.md")
    elif result.soul_error:
        console.print(f"  [SOUL] {result.soul_error}")
    return 1 if result.soul_copied else 0


def _import_mcp(args, config, probe, sources: tuple) -> int:
    from ..ecosystem.mcp_import import (
        import_mcp_servers, parse_claude_mcp_json, parse_hermes_config,
    )

    servers = []
    if "claude_code" in sources and probe.workspace is not None:
        servers += parse_claude_mcp_json(probe.workspace / ".mcp.json")
    if "hermes" in sources and probe.hermes_home is not None:
        servers += parse_hermes_config(probe.hermes_home / "config.yaml")
    result = import_mcp_servers(
        config, servers, overwrite=getattr(args, "force", False),
    )
    for e in result.errors:
        console.print(f"  [MCP] 失败: {e}")
    for s in result.skipped:
        console.print(f"  [MCP] 跳过: {s}")
    return len(result.imported)


# ---------------------------------------------------------------- export

def _cmd_export(args) -> int:
    from ..ecosystem.detect import EcosystemProbe

    kind = args.kind
    dest = getattr(args, "ecosystem_to", "all")
    config = _cfg(args)
    probe = EcosystemProbe.probe(
        getattr(args, "workspace", None),
        hermes_home=config.get("ecosystem.hermes.home") or None,
    )
    total = 0
    if kind == "skills":
        targets = _export_skill_targets(probe, dest)
        for name, d in targets:
            from ..ecosystem.skills_bridge import export_skills
            from ..skills.manager import SkillManager

            manager = SkillManager(config.home, config=config)
            result = export_skills(manager, d)
            console.print(f"技能导出 → {name}: {len(result.imported)} 个 ({d})")
            for e in result.errors:
                console.print(f"  [技能] 失败: {e}")
            total += len(result.imported)
    elif kind == "agents":
        total = _export_agents(config, probe, dest)
        console.print(f"Agent 导出: {total} 个")
    elif kind == "memory":
        total = _export_memory(config, probe, dest)
        console.print(f"记忆导出: {total} 个文件")
    console.print(f"合计导出 {total} 项。导入: `qxt ecosystem import all`。")
    return 0


def _export_skill_targets(probe, dest: str) -> List[tuple]:
    targets: List[tuple] = []
    if dest in ("claude", "all") and probe.workspace is not None:
        targets.append(("claude", probe.workspace / ".claude" / "skills"))
    if dest in ("hermes", "all") and probe.hermes_home is not None:
        targets.append(("hermes", probe.hermes_home / "skills"))
    return targets


def _export_agents(config, probe, dest: str) -> int:
    from ..ecosystem.agents_bridge import export_to_claude

    if dest not in ("claude", "all") or probe.workspace is None:
        return 0
    result = export_to_claude(config.home / "agents", probe.workspace / ".claude" / "agents")
    for e in result.errors:
        console.print(f"  [Agent] 失败: {e}")
    return len(result.exported)


def _export_memory(config, probe, dest: str) -> int:
    from ..ecosystem.memory_bridge import export_to_hermes
    from ..memory.store import MemoryStore

    if dest not in ("hermes", "all") or probe.hermes_home is None:
        return 0
    store = MemoryStore(config.home)
    result = export_to_hermes(store, probe.hermes_home)
    for e in result.errors:
        console.print(f"  [记忆] 失败: {e}")
    if result.memory_over:
        console.print(f"  [记忆] 警告: MEMORY.md 超出 Hermes 上限 {result.memory_chars} chars")
    if result.user_over:
        console.print(f"  [记忆] 警告: USER.md 超出 Hermes 上限 {result.user_chars} chars")
    return 2 if result.target else 0


# ---------------------------------------------------------------- link / serve

def _qxt_command() -> List[str]:
    """定位 qxt 可执行命令 (优先 PATH 里的 qxt, 否则当前解释器 -m 根包)。"""
    exe = shutil.which("qxt")
    if exe:
        return [exe]
    return [sys.executable, "-m", "qingxiaotuan"]


def _cmd_link(args) -> int:
    from ..ecosystem.mcp_import import export_to_hermes_config

    config = _cfg(args)
    workspace = getattr(args, "workspace", None)
    cmd = _qxt_command()
    server_entry = {"name": "qxt", "command": cmd[0], "args": [*cmd[1:], "ecosystem", "serve"]}

    # ---- Claude Code: 写项目 .mcp.json ----
    if workspace:
        from ..ecosystem.mcp_import import export_to_claude_mcp_json

        dest = Path(workspace) / ".mcp.json"
        result = export_to_claude_mcp_json(
            [server_entry], dest, include_env=False,
        )
        if result.errors:
            console.print(f"[Claude] 写入 {dest} 失败: {result.errors[0]}")
        else:
            console.print(f"[Claude] 已写入 {dest} —— Claude Code 会话将自动挂载 qxt 工具:")
            console.print(f"         命令: {server_entry['command']} {' '.join(server_entry['args'])}")
    else:
        console.print("[Claude] 未指定工作区 (--workspace), 跳过 .mcp.json。可手动运行:")
        console.print(f"         claude mcp add qxt -- {cmd[0]} {' '.join(cmd[1:])} ecosystem serve")

    # ---- Hermes: 打印接入命令 / --apply 时写入 config.yaml ----
    # 与 EcosystemProbe 一致的解析链: 配置 → $HERMES_HOME → ~/.hermes。
    hermes_home = config.get("ecosystem.hermes.home") or None
    if hermes_home is None and os.environ.get("HERMES_HOME"):
        hermes_home = os.environ["HERMES_HOME"]
    if hermes_home is None:
        default_home = Path.home() / ".hermes"
        if default_home.exists():
            hermes_home = str(default_home)
    if hermes_home:
        hermes_config = Path(hermes_home) / "config.yaml"
        if getattr(args, "apply", False):
            result = export_to_hermes_config([server_entry], hermes_config)
            if result.errors:
                console.print(f"[Hermes] 写入失败: {result.errors[0]}")
            else:
                console.print(f"[Hermes] 已写入 {hermes_config}")
        else:
            console.print("[Hermes] 接入命令 (加 --apply 可自动写入):")
            console.print(f"         hermes config set mcp.servers.qxt.command {server_entry['command']}")
            console.print(f"         hermes config set mcp.servers.qxt.args '[\"ecosystem\",\"serve\"]'")
    else:
        console.print("[Hermes] 未检测到 ~/.hermes (可设 ecosystem.hermes.home)。")
    return 0


def _cmd_serve(args) -> int:
    from ..ecosystem.mcp_server import serve_stdio

    config = _cfg(args)
    workspace = getattr(args, "workspace", None)
    return serve_stdio(
        config.home,
        workspace=workspace,
        config=config,
    )


def cmd_ecosystem(args) -> int:
    """qxt ecosystem 分发器。"""
    action = getattr(args, "ecosystem_cmd", "scan")
    if action == "scan":
        return _cmd_scan(args)
    if action == "status":
        return _cmd_status(args)
    if action == "import":
        return _cmd_import(args)
    if action == "export":
        return _cmd_export(args)
    if action == "link":
        return _cmd_link(args)
    if action == "serve":
        return _cmd_serve(args)
    console.print(f"未知子命令: {action} (可用: scan/status/import/export/link/serve)")
    return 1
