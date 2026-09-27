"""服务管理 CLI 命令: MCP / Cron / Hooks / Memory / Skill / Plugin / Session / Usercmd。

拆分自 commands.py。本文件保留 plugin / skill / memory 与所有旧导入路径,
MCP / Cron / Hooks / Session / Usercmd 已拆至 cmd_mcp_cli / cmd_cron /
cmd_hooks / cmd_session / cmd_usercmd。
"""

from __future__ import annotations

import importlib

from ..config import Config
from ..memory import MemoryStore
from ..skills import SkillManager
from ._ui_singleton import console


def build_kernel(*a, **k):
    """惰性构建内核: 仅 plugin 命令等真正需要完整内核时才加载 app 链。"""
    from ..app import build_kernel as _f
    return _f(*a, **k)

# ---- 拆分出去的子命令: 惰性 re-export (PEP 562)。
# 避免访问任一子命令时连带加载 cron/mcp/hooks/session/usercmd 全家桶
# (cron 包会拖入 core/tools 全链, ~400ms)。 ----
_SUBMODULES = {
    "cmd_cron": (".cmd_cron", "cmd_cron"),
    "_cron_pid_file": (".cmd_cron", "_cron_pid_file"),
    "_cron_daemon_alive": (".cmd_cron", "_cron_daemon_alive"),
    "_cron_spawn_daemon": (".cmd_cron", "_cron_spawn_daemon"),
    "cmd_hooks": (".cmd_hooks", "cmd_hooks"),
    "_hooks_list": (".cmd_hooks", "_hooks_list"),
    "_hooks_test": (".cmd_hooks", "_hooks_test"),
    "_cmd_hooks": (".cmd_hooks", "_cmd_hooks"),
    "cmd_mcp": (".cmd_mcp_cli", "cmd_mcp"),
    "_mcp_build_kernel": (".cmd_mcp_cli", "_mcp_build_kernel"),
    "_mcp_list": (".cmd_mcp_cli", "_mcp_list"),
    "_mcp_tools": (".cmd_mcp_cli", "_mcp_tools"),
    "_mcp_call": (".cmd_mcp_cli", "_mcp_call"),
    "_mcp_add": (".cmd_mcp_cli", "_mcp_add"),
    "_mcp_test": (".cmd_mcp_cli", "_mcp_test"),
    "_mcp_audit": (".cmd_mcp_cli", "_mcp_audit"),
    "_mcp_security": (".cmd_mcp_cli", "_mcp_security"),
    "cmd_session": (".cmd_session", "cmd_session"),
    "_format_session_time": (".cmd_session", "_format_session_time"),
    "_count_session_messages": (".cmd_session", "_count_session_messages"),
    "_resolve_session_target": (".cmd_session", "_resolve_session_target"),
    "cmd_usercmd": (".cmd_usercmd", "cmd_usercmd"),
}


def __getattr__(name: str):
    mapping = _SUBMODULES.get(name)
    if mapping is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    mod = importlib.import_module(mapping[0], __package__)
    return getattr(mod, mapping[1])


# ===================================================================== cmd_plugin

def cmd_plugin(args) -> int:
    """插件管理。"""
    try:
        kernel = build_kernel()
    except Exception as exc:
        console.print(f"启动失败: {exc}")
        return 1
    console.print("插件列表")
    for name, plugin in kernel.plugins.items():
        provides = ", ".join(plugin.provides) if plugin.provides else "-"
        console.print(f"  {name:<30s} provides: {provides}")
    console.print("\n服务列表")
    for svc in kernel.services.services:
        console.print(f"  {svc}")
    return 0


# ===================================================================== cmd_skill

def cmd_skill(args) -> int:
    """技能管理: list/show/import/audit/consolidate/lint。"""
    skill_cmd = getattr(args, "skill_cmd", None)
    config = Config(profile=getattr(args, "profile", "default"),
                    patch_file=getattr(args, "patch", None))
    workspace = getattr(args, "cwd", None) or getattr(args, "workspace", None)
    manager = SkillManager(config.home, workspace=Path(workspace) if workspace else None,
                           config=config)

    if skill_cmd == "list":
        skills = manager.list_all()
        if not skills:
            console.print("没有技能")
        else:
            console.print(f"{'名称':<28} {'来源':<8} {'次数':<5} 描述")
            for s in skills:
                console.print(f"{s.ui_name:<28} {s.origin:<8} {s.use_count:<5} "
                              f"{(s.short_description or s.description)[:40]}")
        return 0

    if skill_cmd == "show":
        name = getattr(args, "name", "")
        skill = manager.load(name)
        if skill:
            console.print(f"  名称: {skill.ui_name}")
            console.print(f"  slug: {skill.slug}  来源: {skill.origin}")
            console.print(f"  描述: {skill.description}")
            if skill.default_prompt:
                console.print(f"  默认提示: {skill.default_prompt}")
            console.print(f"\n{skill.body}")
        else:
            console.print(f"技能不存在: {name}")
        return 0

    if skill_cmd == "import":
        from pathlib import Path as _P
        src = _P(getattr(args, "path", "")).expanduser()
        skill = manager.import_skill(src)
        if skill:
            console.print(f"已导入技能: {skill.ui_name} → {skill.path}")
        else:
            console.print(f"导入失败 (未找到 SKILL.md): {src}")
            return 1
        return 0

    if skill_cmd == "audit":
        from ..skills.governance import audit
        rows = audit(manager)
        zombies = [r for r in rows if r.is_zombie]
        incomplete = [r for r in rows if r.incomplete]
        console.print(f"技能审计: 共 {len(rows)} 个技能")
        for r in rows:
            flags = []
            if r.is_zombie:
                flags.append("僵尸")
            if r.incomplete:
                flags.append("元数据不全")
            if not r.valid:
                flags.append("frontmatter非法")
            tag = f"  [{','.join(flags)}]" if flags else ""
            console.print(f"  {r.slug:<24} {r.origin:<8} use={r.use_count:<3} "
                          f"闲置{r.days_idle:.0f}天{tag}")
        console.print(f"\n僵尸技能 {len(zombies)} 个, 元数据不全 {len(incomplete)} 个")
        return 0

    if skill_cmd == "consolidate":
        from ..skills.governance import consolidate
        dry = not getattr(args, "apply", False)
        thr = float(getattr(args, "threshold", 0.7) or 0.7)
        proposals = consolidate(manager, dry_run=dry, threshold=thr)
        if not proposals:
            console.print("未发现相似技能对 (无需合并)")
            return 0
        mode = "dry-run (未改盘)" if dry else "已执行合并"
        console.print(f"相似技能合并提议 [{mode}]:")
        for pr in proposals:
            writable = "可写" if pr.writable else "只读(跳过删除)"
            console.print(f"  相似度 {pr.score}: 保留 `{pr.keeper.slug}` "
                          f"← 并入 `{pr.loser.slug}` ({writable})")
        return 0

    if skill_cmd == "lint":
        from ..skills.governance import lint
        name = getattr(args, "name", "")
        issues = lint(manager, name)
        if not issues:
            console.print(f"✓ 技能 `{name}` 通过检查")
        else:
            console.print(f"技能 `{name}` 发现 {len(issues)} 个问题:")
            for it in issues:
                console.print(f"  - {it}")
        return 0

    console.print(f"未知 skill 子命令: {skill_cmd}")
    return 1


# ===================================================================== cmd_memory

def cmd_memory(args) -> int:
    """记忆管理。"""
    memory_cmd = getattr(args, "memory_cmd", None)
    config = Config(profile=getattr(args, "profile", "default"),
                    patch_file=getattr(args, "patch", None))
    store = MemoryStore(config.home)
    if memory_cmd == "list":
        stats = store.get_stats() if hasattr(store, "get_stats") else {}
        console.print(f"  MEMORY.md 条目: {stats.get('memory_lines', 0)}")
        console.print(f"  USER.md 条目: {stats.get('user_lines', 0)}")
        console.print(f"  全文索引条目: {stats.get('fts_entries', 0)}")
        console.print(f"  标签条目: {stats.get('tag_entries', 0)}")
    elif memory_cmd == "search":
        query = getattr(args, "query", "")
        results = store.search(query) if hasattr(store, "search") else []
        for r in results[:10]:
            console.print(f"  {r}")
    return 0
