"""命令行入口包。

tuan 主程序入口 (pyproject [project.scripts] tuan = "tuan_cli.cli:main")。
除透传 parser.main 外, 额外拦截 `tuan --desktop` 子命令:
任意目录一键启动桌面端 (claude-desktop-app 壳), 免 cd 免记忆路径。
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

from .parser import main as _parser_main

__all__ = ["main"]

# 更名前的旧命令名 —— **已彻底废弃**, 不再是入口点 (见 pyproject [project.scripts])。
# 保留此常量仅为兜底: 若机器上残留旧版安装的启动器 (shim 仍指向本模块),
# 直接明确报错并非零退出, 而不是静默当作 tuan 运行。
LEGACY_COMMAND_NAME = "qxt"
CURRENT_COMMAND_NAME = "tuan"


def _reject_legacy_command_name() -> None:
    """若以已废弃的旧命令名启动, 明确报错并退出 (兜底旧 shim)。

    正常安装下不会触发 —— `qxt` 已从 [project.scripts] 移除。
    """
    try:
        prog = os.path.basename(sys.argv[0] or "").lower()
    except Exception:  # noqa: BLE001
        return
    if prog.endswith(".exe"):
        prog = prog[:-4]
    if prog == LEGACY_COMMAND_NAME:
        sys.stderr.write(
            f"[{CURRENT_COMMAND_NAME}] 错误: 命令 `{LEGACY_COMMAND_NAME}` 已废弃, 不再可用。\n"
            f"       请改用 `{CURRENT_COMMAND_NAME}` (例如 `{CURRENT_COMMAND_NAME} models`)。\n"
            f"       若仍能调用到本命令, 说明装的是旧版本: 执行 "
            f"`pip install -U tuan-cli` 后旧启动器会被移除。\n"
        )
        raise SystemExit(2)


def main(argv: list | None = None) -> int:
    _reject_legacy_command_name()
    args = list(argv if argv is not None else sys.argv[1:])
    if args and args[0] == "--desktop":
        return _run_desktop(args[1:])
    # 工作目录: 默认尊重用户启动时的当前目录 (CWD), 不跳转 (2026-10-18 修正,
    # 修复「无论进入什么目录都强制转 D:\DeliveryOptimization\Tuan-Workspace」)。
    # 显式 --workspace / TUAN_WORKSPACE / agent.workspace 时用指定目录;
    # TUAN_AUTO_WORKSPACE=1 可恢复旧行为 (自动进入内置独立工作区)。见 paths.py。
    _enter_default_workspace(args)
    return _parser_main()


def _enter_default_workspace(args: list) -> None:
    """主入口钩子: 创建并进入默认工作目录 (失败不阻断启动)。"""
    try:
        from ..paths import maybe_enter_default_workspace

        maybe_enter_default_workspace(args)
    except Exception:  # noqa: BLE001 - 位置选择不可阻塞启动
        pass


def _run_desktop(args: list) -> int:
    """tuan --desktop [--install|--check|--help] —— 一键启动桌面端。

    定位项目根下的 scripts/tuan_desktop.py 启动器 (独立进程内动态加载,
    避免 scripts/ 未声明为包导致的导入问题), 并把后续参数原样透传。
    """
    root = Path(__file__).resolve().parent.parent.parent
    launcher = root / "scripts" / "tuan_desktop.py"
    if not launcher.exists():
        print(f"[青小团] 未找到桌面端启动器: {launcher}")
        return 1
    spec = importlib.util.spec_from_file_location("tuan_desktop_launcher", launcher)
    if spec is None or spec.loader is None:
        print(f"[青小团] 无法加载桌面端启动器: {launcher}")
        return 1
    mod = importlib.util.module_from_spec(spec)
    sys.modules["tuan_desktop_launcher"] = mod
    spec.loader.exec_module(mod)
    saved = sys.argv
    sys.argv = ["tuan_desktop"] + args
    try:
        return int(mod.main() or 0)
    finally:
        sys.argv = saved
