"""技能工具插件: Hermes 自进化闭环的执行端 —— 蒸馏 / 查阅 / registry 安装管理。

registry 管理域工具 (与 tuan skills 子命令同源, 复用同一 registry 客户端与
用户级技能目录): skill_install (安装) / skill_remove (删除) / skill_update (更新)。
"""

from __future__ import annotations

from types import SimpleNamespace

from ..core.kernel import Kernel, Plugin
from .base import Tool, ToolContext, string_prop


def skill_save(ctx: ToolContext, name: str, description: str, body: str) -> str:
    manager = ctx.kernel.require("skill_manager")
    skill = manager.save(name, description, body)
    return f"技能已保存: {skill.name} -> {skill.path} (累计使用 {skill.use_count} 次)"


def skill_list(ctx: ToolContext) -> str:
    manager = ctx.kernel.require("skill_manager")
    skills = manager.list_all()
    if not skills:
        return "还没有任何技能。完成一个可复用的任务后, 用 skill_save 蒸馏一个吧。"
    return "\n".join(f"- {s.name} (使用 {s.use_count} 次): {s.description}" for s in skills)


def skill_read(ctx: ToolContext, name: str) -> str:
    manager = ctx.kernel.require("skill_manager")
    slug = name.lower().replace(" ", "-")
    skill = manager.load(slug)
    if not skill:
        return f"[错误] 技能不存在: {name}。可用 skill_list 查看全部技能。"
    return f"# {skill.name}\n{skill.description}\n\n{skill.body}"


def _skill_args(name: str) -> SimpleNamespace:
    """构造 cmd_skills 子命令处理器所需的最小 args (与 CLI 同一入口)。"""
    return SimpleNamespace(name=str(name or "").strip())


def skill_install(ctx: ToolContext, name: str, source: str = "") -> str:
    """从远程 registry (Tuan-Skills) 安装技能到用户级技能目录 ~/.tuan/skills/<name>/。

    复用 tuan skills install 的同一链路 (_install_one → registry.install)。
    source 可选: 显式给出仓库内路径 (如 skills/<name>) 时跳过清单查询直接安装。
    """
    name = str(name or "").strip()
    if not name:
        return "[skill] 请指定要安装的技能名 (name)。"
    from ..cli.cmd_skills import _install_one, _user_skills_dir

    src = str(source or "").strip()
    if src:
        # 显式 source: 跳过 registry 清单查询, 按给定仓库内路径走同一 install 后端
        from ..ecosystem import registry

        entry = registry.RegistryEntry(
            name=name, version="0.0.1", path=src, kind="skill",
        )
        if registry.install(entry, _user_skills_dir()):
            return f"技能 {name} 已从 {src} 安装到 {_user_skills_dir() / name}。"
        return f"[skill] 技能 {name} 安装失败 (source={src})。请检查网络/registry 后重试。"
    code = _install_one(_skill_args(name))
    if code == 0:
        return f"技能 {name} 安装完成 → {_user_skills_dir() / name}。"
    return f"[skill] 技能 {name} 安装失败 (exit={code})。请检查网络/registry 后重试。"


def skill_remove(ctx: ToolContext, name: str) -> str:
    """删除用户级已安装技能 ~/.tuan/skills/<name>/ (复用 tuan skills remove 同一链路)。"""
    name = str(name or "").strip()
    if not name:
        return "[skill] 请指定要删除的技能名 (name)。"
    from ..cli.cmd_skills import _remove_one

    code = _remove_one(_skill_args(name))
    if code == 0:
        return f"技能 {name} 已从用户级技能目录删除。"
    return f"[skill] 删除技能 {name} 失败 (exit={code})。该技能可能不在 ~/.tuan/skills/ 下。"


def skill_update(ctx: ToolContext, name: str = "") -> str:
    """更新 (重新拉取远程最新) 已安装技能: 传 name 更新单个, 留空或 'all' 刷新全部用户级技能。

    复用 tuan skills update 的同一链路 (_update_one: 删旧目录 → 重新 install)。
    """
    from ..cli.cmd_skills import _update_one, _user_skills_dir

    name = str(name or "").strip()
    if name and name.lower() != "all":
        targets = [name]
    else:
        root = _user_skills_dir()
        targets = (sorted(d.name for d in root.iterdir() if d.is_dir())
                   if root.is_dir() else [])
    if not targets:
        return "[skill] 没有可更新的技能: 用户级技能目录为空 (可先 skill_install 安装)。"
    ok: list[str] = []
    failed: list[str] = []
    for n in targets:
        code = _update_one(_skill_args(n))
        (ok if code == 0 else failed).append(n)
    parts = []
    if ok:
        parts.append(f"已更新 {len(ok)} 个技能: {', '.join(ok)}")
    if failed:
        parts.append(f"[skill] 更新失败 {len(failed)} 个: {', '.join(failed)}")
    return "; ".join(parts)


class SkillToolPlugin(Plugin):
    name = "tools.skills"
    requires = ["tool_registry", "skill_manager"]

    def activate(self, kernel: Kernel) -> None:
        registry = kernel.require("tool_registry")
        registry.register(Tool(
            name="skill_save",
            description="把验证有效的方法蒸馏为可复用技能 (同名即改进)",
            parameters={
                "type": "object",
                "properties": {
                    "name": string_prop("技能名"),
                    "description": string_prop("何时使用, 一句话"),
                    "body": string_prop("步骤/命令/注意 (Markdown)"),
                },
                "required": ["name", "description", "body"],
            },
            handler=skill_save, group="skills", dangerous=True,
        ))
        registry.register(Tool(
            name="skill_list",
            description="列出全部技能",
            parameters={"type": "object", "properties": {}, "required": []},
            handler=skill_list, group="skills", read_only=True,
        ))
        registry.register(Tool(
            name="skill_read",
            description="阅读技能完整内容",
            parameters={
                "type": "object",
                "properties": {"name": string_prop("技能名")},
                "required": ["name"],
            },
            handler=skill_read, group="skills", read_only=True,
        ))
        registry.register(Tool(
            name="skill_install",
            description="从远程 registry (Tuan-Skills) 安装一个技能到用户级目录",
            parameters={
                "type": "object",
                "properties": {
                    "name": string_prop("技能名 (Tuan-Skills registry 里的 name)"),
                    "source": string_prop("可选: 显式仓库内路径 (如 skills/<name>), "
                                          "跳过清单查询直接安装"),
                },
                "required": ["name"],
            },
            handler=skill_install, group="skills", dangerous=True,
        ))
        registry.register(Tool(
            name="skill_remove",
            description="删除用户级已安装技能 (~/.tuan/skills/<name>/)",
            parameters={
                "type": "object",
                "properties": {"name": string_prop("技能名")},
                "required": ["name"],
            },
            handler=skill_remove, group="skills", dangerous=True,
        ))
        registry.register(Tool(
            name="skill_update",
            description="更新 (重新拉取) 已安装技能: 传 name 更新单个, "
                        "留空或 'all' 刷新全部用户级技能",
            parameters={
                "type": "object",
                "properties": {"name": string_prop("技能名; 留空或 'all' 表示全部")},
                "required": [],
            },
            handler=skill_update, group="skills", dangerous=True,
        ))
