"""ecosystem agent 工具 —— 把 tuan_cli/ecosystem 互操作子系统暴露给 Agent。

青小团定位为 Agent 生态的互操作枢纽: 本工具让 Agent 在会话内直接探测、导入、
导出本机 Claude Code (~/.claude、项目 .claude、.mcp.json) 与 Hermes Agent
(~/.hermes、$HERMES_HOME) 积累的资产 (技能 / agents / 记忆 / SOUL)。

四个操作 (op):
- scan           只读探测双方安装与资产盘点 (不写任何文件, 默认操作)
- status         简要状态行 (生态是否在场 + tuan 导出目录)
- import_assets  把对方生态资产导入 tuan (写入 tuan 自己的 <TUAN_HOME> 目录;
                 这是对 tuan 主目录的显式变更, 由 op 名明示)
- export_assets  把 tuan 资产导出给对方生态 (写入 .claude / ~/.hermes, 同为显式变更)

link / serve (MCP server 生命周期) 不在 Agent 工具范围内, 走 `tuan ecosystem` CLI。
实现上复用 cmd_ecosystem 调用的同一批桥接函数 (skills_bridge / agents_bridge /
memory_bridge), 保证工具与 CLI 行为一致。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, List, Optional, Tuple

from ..core.kernel import Kernel, Plugin
from ..tools.base import Tool, ToolContext, string_prop

log = logging.getLogger(__name__)

_VALID_OPS = ("scan", "status", "import_assets", "export_assets")
_VALID_SCOPES = ("all", "skills", "agents", "memory")
_VALID_TARGETS = ("claude", "hermes", "all")


# ================================================================ 探测辅助

def _cfg_of(ctx: ToolContext) -> Optional[Any]:
    """从工具上下文取内核配置服务 (缺失时返回 None, 不抛异常)。"""
    kernel = getattr(ctx, "kernel", None)
    if kernel is None:
        return None
    try:
        return kernel.get("config")
    except Exception as exc:  # noqa: BLE001 - 配置服务不可用时按无配置降级
        log.debug("ecosystem_tool._cfg_of(): 非致命异常已忽略(设计内降级, 不改控制流): %s", exc)
        return None


def _make_probe(
    ctx: ToolContext,
    claude_home: Optional[str] = None,
    hermes_home: Optional[str] = None,
) -> Any:
    """构建 EcosystemProbe (与 cmd_ecosystem 同一探测入口)。

    路径注入优先级: 显式参数 > 配置 ecosystem.hermes.home > 环境变量/默认位置。
    测试经 claude_home/hermes_home 参数注入 tmp 目录, 实现完全离线。
    """
    from ..ecosystem.detect import EcosystemProbe

    cfg = _cfg_of(ctx)
    hh = hermes_home or None
    if not hh and cfg is not None:
        try:
            hh = cfg.get("ecosystem.hermes.home") or None
        except Exception as exc:  # noqa: BLE001 - 配置损坏时按默认探测
            log.debug("ecosystem_tool._make_probe(): 非致命异常已忽略(设计内降级, 不改控制流): %s", exc)
            hh = None
    workspace = getattr(ctx, "workspace", "") or None
    return EcosystemProbe.probe(
        workspace,
        claude_home=claude_home or None,
        hermes_home=hh,
    )


def _sources_tuple(target: str) -> Tuple[str, ...]:
    """目标生态 → 桥接层 sources 元组 (与 cmd_ecosystem._sources_tuple 一致)。"""
    if target == "claude":
        return ("claude_code",)
    if target == "hermes":
        return ("hermes",)
    return ("claude_code", "hermes")


def _export_skill_targets(probe: Any, target: str) -> List[Tuple[str, Any]]:
    """技能导出目标列表 (与 cmd_ecosystem._export_skill_targets 一致)。"""
    targets: List[Tuple[str, Any]] = []
    if target in ("claude", "all") and probe.workspace is not None:
        targets.append(("claude", probe.workspace / ".claude" / "skills"))
    if target in ("hermes", "all") and probe.hermes_home is not None:
        targets.append(("hermes", probe.hermes_home / "skills"))
    return targets


def _fmt_errors(lines: List[str], errors: List[str], tag: str) -> None:
    for e in errors:
        lines.append(f"  [{tag}] 失败: {e}")


# ================================================================ op: scan

def _op_scan(
    ctx: ToolContext, claude_home: Optional[str] = None,
    hermes_home: Optional[str] = None, **_: Any,
) -> str:
    """只读探测: 双方 CLI / 主目录 / 资产计数 (绝不写文件)。"""
    probe = _make_probe(ctx, claude_home, hermes_home)
    s = probe.summarize()
    c, h = s["claude_code"], s["hermes"]

    lines: List[str] = ["【生态扫描】只读探测, 未修改任何文件"]

    lines.append("Claude Code (Anthropic):")
    lines.append(f"  CLI: {probe.claude_cli + (f' ({probe.claude_version})' if probe.claude_version else '') if probe.claude_cli else '未安装 (claude 不在 PATH)'}")
    lines.append(f"  用户目录: {probe.claude_home if probe.claude_home else '未找到 ~/.claude'}")
    lines.append(f"  项目目录: {probe.claude_project if probe.claude_project else '无 (<workspace>/.claude)'}")
    lines.append(
        f"  资产: 技能 {c.skills} | agents {c.agents} | 命令 {c.commands}"
        f" | MCP servers {c.mcp_servers} | 插件 {c.plugins}"
    )

    lines.append("Hermes Agent (Nous Research):")
    lines.append(f"  CLI: {probe.hermes_cli + (f' ({probe.hermes_version})' if probe.hermes_version else '') if probe.hermes_cli else '未安装 (hermes 不在 PATH)'}")
    lines.append(f"  主目录: {probe.hermes_home if probe.hermes_home else '未找到 ~/.hermes'}")
    if probe.hermes_profiles:
        names = ", ".join(p.name for p in probe.hermes_profiles[:8])
        lines.append(f"  profiles: {names}")
    lines.append(
        f"  资产: 技能 {h.skills} | 记忆文件 {h.memories}"
        f" | SOUL {'有' if h.soul else '无'} | MCP servers {h.mcp_servers}"
    )
    lines.append("提示: import_assets 把双方资产并入 tuan; export_assets 反向导出。")
    return "\n".join(lines)


# ================================================================ op: status

def _op_status(
    ctx: ToolContext, claude_home: Optional[str] = None,
    hermes_home: Optional[str] = None, **_: Any,
) -> str:
    """简要状态: 生态是否在场 + tuan 自己的导入/导出目录。"""
    probe = _make_probe(ctx, claude_home, hermes_home)
    cfg = _cfg_of(ctx)
    home = getattr(cfg, "home", None)

    claude_present = bool(probe.claude_cli or probe.claude_home or probe.claude_project)
    hermes_present = bool(probe.hermes_cli or probe.hermes_home)

    lines: List[str] = ["【生态状态】"]
    lines.append(
        f"Claude Code: {'已检测到' if claude_present else '未检测到'}"
        f" (CLI: {'有' if probe.claude_cli else '无'};"
        f" 目录: {probe.claude_home if probe.claude_home else '无'})"
    )
    lines.append(
        f"Hermes: {'已检测到' if hermes_present else '未检测到'}"
        f" (CLI: {'有' if probe.hermes_cli else '无'};"
        f" 目录: {probe.hermes_home if probe.hermes_home else '无'})"
    )
    if home is not None:
        lines.append(
            f"tuan 导出目录: 技能 {Path(home) / 'skills'} | agents {Path(home) / 'agents'}"
            f" | 记忆 {Path(home) / 'memories'}"
        )
    if cfg is not None:
        try:
            cc_on = bool(cfg.get("ecosystem.claude_code.enabled", True))
            h_on = bool(cfg.get("ecosystem.hermes.enabled", True))
            lines.append(f"自动发现开关: claude_code={'开' if cc_on else '关'} | hermes={'开' if h_on else '关'}")
        except Exception as exc:  # noqa: BLE001 - 开关读取失败不影响状态主输出
            log.debug("ecosystem_tool._op_status(): 非致命异常已忽略(设计内降级, 不改控制流): %s", exc)
    return "\n".join(lines)


# ================================================================ op: import_assets

def _op_import_assets(
    ctx: ToolContext, scope: str = "all", target: str = "all",
    claude_home: Optional[str] = None, hermes_home: Optional[str] = None, **_: Any,
) -> str:
    """把 Claude Code / Hermes 资产导入 tuan (写 tuan 自己的 <TUAN_HOME> 目录)。"""
    if scope not in _VALID_SCOPES:
        return f"[ecosystem] 未知 scope: {scope!r} (可用: {'/'.join(_VALID_SCOPES)})"
    if target not in _VALID_TARGETS:
        return f"[ecosystem] 未知 target: {target!r} (可用: {'/'.join(_VALID_TARGETS)})"

    cfg = _cfg_of(ctx)
    if cfg is None or getattr(cfg, "home", None) is None:
        return "[ecosystem] 内核缺少 config 服务 (无 tuan 主目录), 无法执行导入。"

    probe = _make_probe(ctx, claude_home, hermes_home)
    sources = _sources_tuple(target)
    total = 0
    lines: List[str] = [f"【生态导入】scope={scope} target={target}"]

    if scope in ("skills", "all"):
        from ..ecosystem.skills_bridge import import_skills
        from ..skills.manager import SkillManager

        manager = SkillManager(cfg.home, config=cfg)
        result = import_skills(manager, probe, sources=sources)
        total += len(result.imported)
        names = ", ".join(result.imported) if result.imported else "无"
        lines.append(f"技能导入: {len(result.imported)} 个 ({names})")
        _fmt_errors(lines, result.errors, "技能")

    if scope in ("memory", "all"):
        from ..ecosystem.memory_bridge import import_hermes_memory
        from ..memory.store import MemoryStore

        if "hermes" in sources:
            store = MemoryStore(cfg.home)
            mem_result = import_hermes_memory(
                store, probe.hermes_memories_dirs,
                hermes_home=probe.hermes_home, tuan_home=cfg.home,
            )
            n = len(mem_result.memory_added) + len(mem_result.user_added)
            total += n
            extra = "; SOUL.md 已复制" if mem_result.soul_copied else ""
            lines.append(f"记忆导入: {n} 条{extra}")
            if mem_result.soul_error:
                lines.append(f"  [SOUL] {mem_result.soul_error}")
            _fmt_errors(lines, mem_result.errors, "记忆")
        else:
            lines.append("记忆导入: 跳过 (仅 Hermes 提供记忆目录约定)")

    if scope in ("agents", "all"):
        from ..ecosystem.agents_bridge import import_claude_agents

        if "claude_code" in sources:
            agent_result = import_claude_agents(probe.claude_agents_dirs, cfg.home / "agents")
            total += len(agent_result.imported)
            names = ", ".join(agent_result.imported) if agent_result.imported else "无"
            lines.append(f"Agent 导入: {len(agent_result.imported)} 个 ({names})")
            _fmt_errors(lines, agent_result.errors, "Agent")
        else:
            lines.append("Agent 导入: 跳过 (仅 Claude Code 提供 agents 目录约定)")

    lines.append(f"合计导入 {total} 项 → {cfg.home}")
    return "\n".join(lines)


# ================================================================ op: export_assets

def _op_export_assets(
    ctx: ToolContext, scope: str = "all", target: str = "all",
    claude_home: Optional[str] = None, hermes_home: Optional[str] = None, **_: Any,
) -> str:
    """把 tuan 资产导出给 Claude Code / Hermes (写对方生态目录)。"""
    if scope not in _VALID_SCOPES:
        return f"[ecosystem] 未知 scope: {scope!r} (可用: {'/'.join(_VALID_SCOPES)})"
    if target not in _VALID_TARGETS:
        return f"[ecosystem] 未知 target: {target!r} (可用: {'/'.join(_VALID_TARGETS)})"

    cfg = _cfg_of(ctx)
    if cfg is None or getattr(cfg, "home", None) is None:
        return "[ecosystem] 内核缺少 config 服务 (无 tuan 主目录), 无法执行导出。"

    probe = _make_probe(ctx, claude_home, hermes_home)
    total = 0
    lines: List[str] = [f"【生态导出】scope={scope} target={target}"]

    if scope in ("skills", "all"):
        from ..ecosystem.skills_bridge import export_skills
        from ..skills.manager import SkillManager

        targets = _export_skill_targets(probe, target)
        if not targets:
            lines.append("技能导出: 无可用目标 (claude 需要工作区, hermes 需要 ~/.hermes)")
        manager = SkillManager(cfg.home, config=cfg)
        for name, dest in targets:
            result = export_skills(manager, dest)
            total += len(result.imported)
            lines.append(f"技能导出 → {name}: {len(result.imported)} 个 ({dest})")
            _fmt_errors(lines, result.errors, "技能")

    if scope in ("agents", "all"):
        if target in ("claude", "all") and probe.workspace is not None:
            from ..ecosystem.agents_bridge import export_to_claude

            dest = probe.workspace / ".claude" / "agents"
            agent_result = export_to_claude(cfg.home / "agents", dest)
            total += len(agent_result.exported)
            lines.append(f"Agent 导出 → claude: {len(agent_result.exported)} 个 ({dest})")
            _fmt_errors(lines, agent_result.errors, "Agent")
        else:
            lines.append("Agent 导出: 跳过 (仅支持 claude 目标, 且需要工作区)")

    if scope in ("memory", "all"):
        if target in ("hermes", "all") and probe.hermes_home is not None:
            from ..ecosystem.memory_bridge import export_to_hermes
            from ..memory.store import MemoryStore

            store = MemoryStore(cfg.home)
            memexp_result = export_to_hermes(store, probe.hermes_home)
            total += 2 if memexp_result.target else 0
            lines.append(f"记忆导出 → hermes: {memexp_result.target or '未写入'}")
            if memexp_result.memory_over:
                lines.append(f"  [记忆] 警告: MEMORY.md 超出 Hermes 上限 {memexp_result.memory_chars} chars")
            if memexp_result.user_over:
                lines.append(f"  [记忆] 警告: USER.md 超出 Hermes 上限 {memexp_result.user_chars} chars")
            _fmt_errors(lines, memexp_result.errors, "记忆")
        else:
            lines.append("记忆导出: 跳过 (仅支持 hermes 目标, 且需要 ~/.hermes)")

    lines.append(f"合计导出 {total} 项")
    return "\n".join(lines)


# ================================================================ 分发入口

def _eco_handler(ctx: ToolContext, op: str = "scan", **kw: Any) -> str:
    """ecosystem 工具入口: 按 op 分发; 任何异常降级为 '[ecosystem] ...' 文本。"""
    try:
        if op == "scan":
            return _op_scan(ctx, **kw)
        if op == "status":
            return _op_status(ctx, **kw)
        if op == "import_assets":
            return _op_import_assets(ctx, **kw)
        if op == "export_assets":
            return _op_export_assets(ctx, **kw)
        return (f"[ecosystem] 未知 op: {op!r} "
                f"(可用: {'/'.join(_VALID_OPS)}; link/serve 请用 tuan ecosystem CLI)")
    except Exception as exc:  # noqa: BLE001 - 工具层兜底, 不向 Agent 循环抛原始异常
        log.warning("ecosystem 工具 op=%s 执行失败: %s", op, exc)
        return f"[ecosystem] {op} 执行失败: {type(exc).__name__}: {exc}"


# ================================================================ 插件注册

class EcosystemToolPlugin(Plugin):
    """把 ecosystem 互操作子系统注册为名为 ``ecosystem`` 的 Agent 工具。"""

    name = "tools.ecosystem"
    provides: List[str] = []
    requires = ["tool_registry"]

    def activate(self, kernel: Kernel) -> None:
        config = kernel.get("config")
        if config and not config.get("tools.ecosystem.enabled", True):
            return

        registry = kernel.require("tool_registry")
        registry.register(Tool(
            name="ecosystem",
            description=(
                "生态互操作枢纽: 探测/导入/导出本机 Claude Code 与 Hermes Agent 的资产"
                " (技能/agents/记忆/SOUL)。op=scan 只读盘点 (默认); op=status 简要状态;"
                " op=import_assets 把对方资产复制进 tuan (会写 tuan 的主目录);"
                " op=export_assets 把 tuan 资产导出到对方目录 (会写 .claude / ~/.hermes)。"
                " scope: all|skills|agents|memory; target: claude|hermes|all。"
                " link/serve 请改用 tuan ecosystem CLI。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "op": {
                        "type": "string",
                        "enum": list(_VALID_OPS),
                        "description": (
                            "操作: scan=只读探测(默认); status=简要状态; "
                            "import_assets=导入对方资产到 tuan; export_assets=导出 tuan 资产给对方"
                        ),
                    },
                    "scope": {
                        "type": "string",
                        "enum": list(_VALID_SCOPES),
                        "description": "资产范围 (import/export 用): all|skills|agents|memory, 默认 all",
                    },
                    "target": {
                        "type": "string",
                        "enum": list(_VALID_TARGETS),
                        "description": "目标生态 (import/export 用): claude|hermes|all, 默认 all",
                    },
                    "claude_home": string_prop("覆盖 Claude Code 主目录 (默认 ~/.claude; 测试/自定义环境用)"),
                    "hermes_home": string_prop("覆盖 Hermes 主目录 (默认 $HERMES_HOME 或 ~/.hermes)"),
                },
                "required": [],
            },
            handler=_eco_handler,
            group="tools",
        ))
