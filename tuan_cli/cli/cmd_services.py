"""服务管理 CLI 命令: MCP / Cron / Hooks / Memory / Skill / Plugin / Session / Usercmd。

拆分自 commands.py。本文件保留 plugin / skill / memory 与所有旧导入路径,
MCP / Cron / Hooks / Session / Usercmd 已拆至 cmd_mcp_cli / cmd_cron /
cmd_hooks / cmd_session / cmd_usercmd。
"""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

from ..config import Config
from ..memory import MemoryStore
from ..skills import SkillManager
from ._ui_singleton import console


def build_kernel(*a: Any, **k: Any) -> Any:
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


def __getattr__(name: str) -> Any:
    mapping = _SUBMODULES.get(name)
    if mapping is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    mod = importlib.import_module(mapping[0], __package__)
    return getattr(mod, mapping[1])


# ===================================================================== cmd_plugin


def _get_plugin_manager(config: Any = None) -> Any:
    """惰性构建 PluginManager (基于 ~/.tuan/plugins)。"""
    from ..skills.plugin_sdk import PluginManager

    home = None
    if config is not None:
        try:
            home = config.home
        except Exception:  # noqa: BLE001
            home = None
    if home is None:
        from ..paths import get_home  # 保守尝试

        home = Path(get_home())  # type: ignore[misc]
    return PluginManager(Path(home) / "plugins")


def cmd_plugin(args: Any) -> int:
    """插件管理 (兼容 DSH 0.2+)。

    子命令:
      tuan plugin list                  列出已安装插件
      tuan plugin install <path>        从本地目录安装
      tuan plugin uninstall <name>      卸载
      tuan plugin enable <name>         启用
      tuan plugin disable <name>        禁用
      tuan plugin info <name>           查看详情
    """
    plugin_cmd = getattr(args, "plugin_cmd", None) or "list"
    config = Config(
        profile=getattr(args, "profile", "default"),
        patch_file=getattr(args, "patch", None),
    )

    try:
        manager = _get_plugin_manager(config)
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]插件管理器初始化失败:[/red] {exc}")
        return 1

    if plugin_cmd == "list":
        return _plugin_cmd_list(manager)

    if plugin_cmd == "install":
        source = getattr(args, "path", "")
        name = getattr(args, "name", None)
        if not source:
            console.print("[red]缺少插件源目录路径[/red]")
            return 1
        try:
            info = manager.install_from_directory(Path(source).expanduser(), name=name)
        except Exception as exc:  # noqa: BLE001
            console.print(f"[red]安装失败:[/red] {exc}")
            return 1
        console.print(
            f"[green]已安装[/green] {info.manifest.name} v{info.manifest.version} "
            f"({info.path})"
        )
        return 0

    if plugin_cmd == "uninstall":
        name = getattr(args, "name", "")
        if manager.uninstall(name):
            console.print(f"[green]已卸载[/green] {name}")
            return 0
        console.print(f"[yellow]未找到插件[/yellow] {name}")
        return 1

    if plugin_cmd == "enable":
        name = getattr(args, "name", "")
        if manager.enable(name):
            console.print(f"[green]已启用[/green] {name}")
            return 0
        console.print(f"[yellow]未找到插件[/yellow] {name}")
        return 1

    if plugin_cmd == "disable":
        name = getattr(args, "name", "")
        if manager.disable(name):
            console.print(f"[yellow]已禁用[/yellow] {name}")
            return 0
        console.print(f"[red]未找到插件[/red] {name}")
        return 1

    if plugin_cmd == "info":
        name = getattr(args, "name", "")
        return _plugin_cmd_info(manager, name)

    console.print(f"[red]未知子命令[/red] plugin {plugin_cmd}")
    return 1


def _plugin_cmd_list(manager: Any) -> int:
    """列出已安装插件 (含版本、状态、兼容性)。"""
    plugins = manager.list_plugins()
    if not plugins:
        console.print(
            f"没有插件 (目录: {manager.plugins_dir})\n"
            "用 `tuan plugin install <path>` 安装"
        )
        return 0

    dsh_version = manager.check_dsh_version()
    if dsh_version:
        console.print(f"[dim]DSH 版本: {dsh_version}[/dim]")
    else:
        console.print(
            "[dim]DSH 未检测到 — 跳过 min_dsh_version 检查 "
            "(可写入 ~/.tuan/dsh_version 或安装 dsh 命令)[/dim]"
        )
    console.print(f"{'名称':<28} {'版本':<10} {'状态':<8} {'格式':<8} 描述")
    for info in plugins:
        status = "[green]启用[/green]" if info.enabled else "[dim]禁用[/dim]"
        fmt = info.manifest.format
        desc = (info.manifest.description or "")[:40]
        console.print(
            f"{info.manifest.name:<28} {info.manifest.version:<10} "
            f"{status:<8} {fmt:<8} {desc}"
        )
    return 0


def _plugin_cmd_info(manager: Any, name: str) -> int:
    """显示插件完整信息。"""
    info = manager.get_plugin(name)
    if info is None:
        console.print(f"[red]未找到插件[/red] {name}")
        return 1

    m = info.manifest
    console.print(f"[bold]{m.name}[/bold] v{m.version}   "
                  f"{'[green]启用[/green]' if info.enabled else '[dim]禁用[/dim]'}")
    if m.description:
        console.print(f"  描述: {m.description}")
    if m.author:
        console.print(f"  作者: {m.author}")
    if m.license:
        console.print(f"  许可: {m.license}")
    if m.repository:
        console.print(f"  仓库: {m.repository}")
    console.print(f"  路径: {info.path}")
    console.print(f"  格式: {m.format}")

    if m.skills:
        console.print(f"\n[bold]技能 ({len(m.skills)})[/bold]")
        for s in m.skills:
            auto = " (auto)" if s.get("auto_invoke") else ""
            console.print(f"  - {m.name}:{s.get('name', '?')}{auto}  "
                          f"{s.get('description', '')}")

    if m.hooks:
        console.print("\n[bold]Hooks[/bold]")
        for hook_name, hook_cmd in m.hooks.items():
            console.print(f"  {hook_name:<10} {hook_cmd}")

    if m.dependencies:
        console.print("\n[bold]依赖[/bold]")
        for dep_name, dep_ver in m.dependencies.items():
            console.print(f"  {dep_name}: {dep_ver}")

    if m.compatibility:
        console.print("\n[bold]兼容性[/bold]")
        for k, v in m.compatibility.items():
            console.print(f"  {k}: {v}")
        dsh_version = manager.check_dsh_version()
        ok, reason = m.validate_dsh_compat(dsh_version)
        if not ok:
            console.print(f"  [red]DSH 兼容性: 不满足[/red] ({reason})")
        elif reason:
            console.print(f"  [yellow]DSH 兼容性:[/yellow] {reason}")
        else:
            console.print("  [green]DSH 兼容性: 满足[/green]")
    return 0


# ===================================================================== cmd_skill


def cmd_skill(args: Any) -> int:
    """技能管理: list/show/import/audit/consolidate/lint。"""
    skill_cmd = getattr(args, "skill_cmd", None)
    config = Config(
        profile=getattr(args, "profile", "default"),
        patch_file=getattr(args, "patch", None),
    )
    workspace = getattr(args, "cwd", None) or getattr(args, "workspace", None)
    manager = SkillManager(
        config.home, workspace=Path(workspace) if workspace else None, config=config
    )

    if skill_cmd == "list":
        skills = manager.list_all()
        if not skills:
            console.print("没有技能")
        else:
            console.print(f"{'名称':<28} {'来源':<8} {'次数':<5} 描述")
            for s in skills:
                console.print(
                    f"{s.ui_name:<28} {s.origin:<8} {s.use_count:<5} "
                    f"{(s.short_description or s.description)[:40]}"
                )
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
            console.print(
                f"  {r.slug:<24} {r.origin:<8} use={r.use_count:<3} "
                f"闲置{r.days_idle:.0f}天{tag}"
            )
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
            console.print(
                f"  相似度 {pr.score}: 保留 `{pr.keeper.slug}` "
                f"← 并入 `{pr.loser.slug}` ({writable})"
            )
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


def cmd_memory(args: Any) -> int:
    """记忆管理。"""
    memory_cmd = getattr(args, "memory_cmd", None)
    config = Config(
        profile=getattr(args, "profile", "default"),
        patch_file=getattr(args, "patch", None),
    )
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
