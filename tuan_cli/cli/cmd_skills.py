"""tuan skills —— 从 Tuan-Skills / Tuan-Craft 远程 registry 管理技能与组件。

子命令:
  tuan skills list            列出远程 registry 可用的全部 skill
  tuan skills installed       列出本地已安装的 skill (用户级 + 项目级 + builtin)
  tuan skills install <name>  从远程安装一个 skill 到 ~/.tuan/skills/<name>/
  tuan skills update <name>   更新已安装 skill (重新拉远程最新)
  tuan skills pull            一次性 pull registry 全部 skill 到本地
  tuan skills remove <name>   删除已安装 skill (只删用户级副本)
  tuan skills seed            把 builtin/ 里的内置 skill 播种到用户级目录
  tuan skills cache           清除 registry 本地缓存

  tuan craft list             列出 Tuan-Craft 组件工坊
  tuan craft install <name>   安装 craft 组件到 ~/.tuan/craft/<name>/

registry 协议见 ecosystem/registry.py。
"""

from __future__ import annotations

import shutil
from pathlib import Path

from .parser import _register_command  # noqa: E402
from ..ui.plain_console import console  # noqa: E402
from ..ecosystem import registry  # noqa: E402


def _user_skills_dir() -> Path:
    return Path.home() / ".tuan" / "skills"


def _user_craft_dir() -> Path:
    return Path.home() / ".tuan" / "craft"


def _find_skill_manager():
    """惰性 import, 避免 CLI 启动时加载重模块。"""
    try:
        from ..skills.manager import SkillManager
        from ..core import config as _cfg

        kernel_cfg = _cfg.ConfigManager.load()
        return SkillManager(kernel_cfg)
    except Exception:  # noqa: BLE001
        return None


def _builtin_dir() -> Path:
    """返回打包后 builtin skills 目录 (用 __file__ 向上两级定位 tuan_cli/resources)。"""
    here = Path(__file__).resolve()
    # tuan_cli/cli/cmd_skills.py → tuan_cli/resources/skills/builtin/
    return here.parent.parent / "resources" / "skills" / "builtin"


# --- 子命令处理器 ---

def _list_remote(args) -> int:
    entries = registry.list_skills()
    if not entries:
        console.print("[yellow]远程 registry 暂时不可用 (网络或仓库未初始化)[/]")
        console.print("等 Tuan-Skills 仓库上传 registry.json 后, `tuan skills list` 会显示全部条目")
        return 0
    console.print(f"[bold]Tuan-Skills 可用条目 ({len(entries)}):[/]")
    for e in entries:
        desc = (e.description or "")[:60]
        tags = f"  [{','.join(e.tags)}]" if e.tags else ""
        console.print(f"  {e.name:<22} v{e.version:<8} {desc}{tags}")
    return 0


def _install_one(args) -> int:
    name = getattr(args, "name", "")
    if not name:
        console.print("[red]缺少 skill 名称: tuan skills install <name>[/]")
        return 2
    entries = registry.list_skills()
    target = next((e for e in entries if e.name == name), None)
    if not target:
        console.print(f"[yellow]registry 里没找到 '{name}' — 尝试按惯例路径 skills/{name} 拉取[/]")
        target = registry.RegistryEntry(
            name=name, version="0.0.1", path=f"skills/{name}", kind="skill",
        )
    dest_root = _user_skills_dir()
    console.print(f"安装 [bold]{target.name}[/] v{target.version} → {dest_root}")
    if registry.install(target, dest_root):
        console.print(f"[green]✓[/] {target.name} 安装完成")
        return 0
    console.print("[red]✗ 安装失败 (git sparse-checkout 和 zip 回退都没成功)[/]")
    console.print("检查: 1) git 可用  2) 网络可达 github.com  3) 目标 skill 存在于 Tuan-Skills/skills/<name>/")
    return 1


def _update_one(args) -> int:
    name = getattr(args, "name", "")
    if not name:
        console.print("[red]缺少 skill 名称[/]")
        return 2
    dest = _user_skills_dir() / name
    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)
    return _install_one(args)


def _remove_one(args) -> int:
    name = getattr(args, "name", "")
    if not name:
        console.print("[red]缺少 skill 名称[/]")
        return 2
    dest = _user_skills_dir() / name
    if not dest.exists():
        console.print(f"[red]{name} 不在 ~/.tuan/skills/[/]")
        return 1
    shutil.rmtree(dest, ignore_errors=True)
    console.print(f"[green]✓[/] 已删除 {name}")
    return 0


def _pull_all(args) -> int:
    entries = registry.list_skills()
    if not entries:
        console.print("[yellow]远程 registry 暂时不可用[/]")
        return 1
    dest_root = _user_skills_dir()
    console.print(f"一次性 pull [bold]{len(entries)}[/] 个 skill → {dest_root}")
    ok_n, fail_n, skip_n = 0, 0, 0
    for e in entries:
        dest = dest_root / e.name
        if dest.exists():
            skip_n += 1
            console.print(f"  - skip {e.name} (已存在, 用 --force 覆盖)")
            continue
        if registry.install(e, dest_root):
            ok_n += 1
            console.print(f"  [green]✓[/] {e.name}")
        else:
            fail_n += 1
            console.print(f"  [red]✗[/] {e.name}")
    console.print(f"完成: [green]成功 {ok_n}[/], [yellow]跳过 {skip_n}[/], [red]失败 {fail_n}[/]")
    return 0 if fail_n == 0 else 1


def _list_installed(args) -> int:
    mgr = _find_skill_manager()
    if not mgr:
        console.print("[red]SkillManager 初始化失败[/]")
        return 1
    try:
        skills = mgr.list_all()
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]读取技能库失败: {exc}[/]")
        return 1
    if not skills:
        console.print("[yellow]本地还没有任何 skill[/]")
        return 0
    console.print(f"[bold]已安装 skill ({len(skills)}):[/]")
    for s in skills:
        origin = getattr(s, "origin", "builtin")
        ver = getattr(s, "version", "") or ""
        console.print(f"  {s.name:<22} [{origin}]  {ver:<8}  {getattr(s, 'path', '')}")
    return 0


def _clear_cache(_args) -> int:
    registry.clear_cache()
    console.print("[green]✓[/] 已清除 registry 缓存, 下次 list 会重新拉取")
    return 0


def _seed_builtin(_args) -> int:
    """把 builtin/ 里的内置 skill 播种到用户级 ~/.tuan/skills/。

    这是「去预制化」的第一步: 首次启动后, 用户运行一次 seed,
    builtin 目录就只作为 fallback 保留, 后续更新统一走 registry。
    """
    builtin = _builtin_dir()
    dest = _user_skills_dir()
    if not builtin.is_dir():
        console.print(f"[yellow]builtin 目录不存在 ({builtin}) — 可能是开发环境[/]")
        return 0
    dest.mkdir(parents=True, exist_ok=True)
    skills = [d for d in builtin.iterdir() if d.is_dir() and (d / "SKILL.md").exists()]
    if not skills:
        console.print("[yellow]builtin 目录里没有可播种的 skill[/]")
        return 0
    console.print(f"播种 [bold]{len(skills)}[/] 个 builtin skill → {dest}")
    ok_n, skip_n = 0, 0
    for s in skills:
        target = dest / s.name
        if target.exists():
            skip_n += 1
            console.print(f"  - skip {s.name} (已存在)")
            continue
        shutil.copytree(s, target)
        ok_n += 1
        console.print(f"  [green]✓[/] {s.name}")
    console.print(f"完成: [green]播种 {ok_n}[/], [yellow]跳过 {skip_n}[/]")
    return 0


def _craft_list(_args) -> int:
    entries = registry.list_craft()
    if not entries:
        console.print("[yellow]Tuan-Craft 暂时不可用 (仓库未初始化 registry)[/]")
        return 0
    console.print(f"[bold]Tuan-Craft 组件工坊 ({len(entries)}):[/]")
    for e in entries:
        desc = (e.description or "")[:60]
        console.print(f"  {e.name:<22} v{e.version:<8} {desc}")
    return 0


def _craft_install(args) -> int:
    name = getattr(args, "name", "")
    if not name:
        console.print("[red]缺少组件名[/]")
        return 2
    entries = registry.list_craft()
    target = next((e for e in entries if e.name == name), None)
    if not target:
        target = registry.RegistryEntry(
            name=name, version="0.0.1", path=f"components/{name}", kind="craft",
        )
    dest_root = _user_craft_dir()
    console.print(f"安装 [bold]craft.{target.name}[/] → {dest_root}")
    if registry.install(target, dest_root):
        console.print(f"[green]✓[/] craft.{target.name} 安装完成")
        return 0
    console.print(f"[red]✗ craft.{target.name} 安装失败[/]")
    return 1


# --- 主入口 ---

_ACTIONS = {
    "list": _list_remote,
    "installed": _list_installed,
    "install": _install_one,
    "update": _update_one,
    "remove": _remove_one,
    "pull": _pull_all,
    "cache": _clear_cache,
    "seed": _seed_builtin,
    "craft-list": _craft_list,
    "craft-install": _craft_install,
}


def cmd_skills(args) -> int:
    act = getattr(args, "skills_action", None) or "list"
    craft_mode = act in ("craft-list", "craft-install")
    if act in ("list", "installed", "install") and bool(getattr(args, "craft_mode", False)):
        craft_mode = True

    if craft_mode:
        if act in ("craft-list", "list"):
            handler = _craft_list
        elif act in ("craft-install", "install"):
            handler = _craft_install
        else:
            _print_help()
            return 2
    else:
        handler = _ACTIONS.get(act)
        if handler is None:
            console.print(f"[red]未知子命令: skills {act}[/]")
            _print_help()
            return 2
    return int(handler(args) or 0)


def _print_help() -> None:
    console.print("""用法:
  tuan skills list              列出远程 registry 可用 skill
  tuan skills installed         列出本地已安装 skill
  tuan skills install <name>    安装一个 skill
  tuan skills update <name>     更新已安装 skill
  tuan skills remove <name>     删除已安装 skill (用户级)
  tuan skills pull              一次性 pull registry 全部 skill
  tuan skills seed              把 builtin/ 内置 skill 播种到用户级目录
  tuan skills cache             清除 registry 本地缓存
  tuan skills craft-list        列出 Tuan-Craft 组件
  tuan skills craft-install <name>  安装 craft 组件

  tuan craft list               等价于 tuan skills craft-list
  tuan craft install <name>     等价于 tuan skills craft-install""")


# ---------------------------------------------------------------------------
# 注册

_register_command("cmd_skills", ".cmd_skills")
