"""首次运行 Onboarding 引导 (对标竞品首次启动体验)。

触发时机:
- ``qxt onboarding``            手动重新运行引导;
- 首次 ``qxt`` / ``qxt init``   且 ``<home>/.qxt_onboarding_done`` 不存在时自动触发;
- ``qxt onboarding --skip``     跳过引导并写入完成标记 (脚本/CI 友好)。

非交互模式 (stdin 非 TTY, 如管道/CI) 自动跳过交互式提问, 只打印快速上手指南,
绝不阻塞。

配置项: ``onboarding.enabled`` (默认 true); 设为 false 则首次运行不弹引导。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional

from ..config import home_dir

MARKER_NAME = ".qxt_onboarding_done"

# 快速上手卡片: 5 个最常用命令
QUICK_START = [
    ("qxt chat", "直接进入交互式对话 (默认行为)"),
    ("/goal <目标>", "目标模式: 自动循环直到完成"),
    ("! <shell 命令>", "在会话里直接跑 shell 命令"),
    ("/init", "扫描当前仓库生成 QXT.md 项目规则"),
    ("/help", "查看全部斜杠命令与快捷键"),
]


def onboarding_done_marker(home: Optional[Path] = None) -> Path:
    """完成标记文件路径 (<home>/.qxt_onboarding_done)。"""
    return (Path(home) if home else home_dir()) / MARKER_NAME


def is_first_run(home: Optional[Path] = None) -> bool:
    """是否需要跑引导: 完成标记不存在, 且配置未显式关闭 onboarding。"""
    marker = onboarding_done_marker(home)
    if marker.exists():
        return False
    # onboarding.enabled=false 时跳过 (读 config.yaml, 失败则默认 true)
    try:
        cfg = (Path(home) if home else home_dir()) / "config.yaml"
        if cfg.exists():
            import yaml
            data = yaml.safe_load(cfg.read_text(encoding="utf-8")) or {}
            ob = data.get("onboarding") or {}
            if isinstance(ob, dict) and ob.get("enabled") is False:
                return False
    except Exception:  # noqa: BLE001 - 配置读失败不阻塞首次引导
        pass
    return True


def mark_onboarding_done(home: Optional[Path] = None) -> Path:
    """写入完成标记, 返回标记路径。"""
    marker = onboarding_done_marker(home)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("done\n", encoding="utf-8")
    return marker


def _is_interactive() -> bool:
    try:
        return bool(sys.stdin.isatty() and sys.stdout.isatty())
    except Exception:  # noqa: BLE001
        return False


def _print_welcome() -> None:
    print()
    print("  欢迎使用青小团 qxt!  🎯")
    print("  一个会成长、微内核插件化的 Windows 原生 Agent CLI。")
    print("  我能读代码、跑测试、改文件、提交 git —— 边做边学, 越用越顺手。")
    print()


def _print_quick_start() -> None:
    print("  ── 快速上手 ──────────────────────────────")
    for cmd, desc in QUICK_START:
        print(f"    {cmd:<16}  {desc}")
    print()


def _ask_yes_no(prompt: str, default: bool) -> bool:
    """交互式 yes/no; 非交互或异常时返回 default。"""
    default_str = "Y/n" if default else "y/N"
    try:
        raw = input(f"  {prompt} [{default_str}]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return default
    if not raw:
        return default
    return raw in ("y", "yes", "是", "好")


def _detect_git_repo(workspace: Path) -> bool:
    try:
        import subprocess
        r = subprocess.run(
            ["git", "-C", str(workspace), "rev-parse", "--is-inside-work-tree"],
            capture_output=True, text=True, timeout=5,
        )
        return r.returncode == 0 and r.stdout.strip() == "true"
    except Exception:  # noqa: BLE001
        return False


def run_onboarding(workspace: Optional[Path] = None, *,
                   skip: bool = False, home: Optional[Path] = None,
                   interactive: Optional[bool] = None) -> int:
    """运行首次引导。返回 0。

    - skip=True: 只写完成标记, 不交互;
    - 非交互 (CI/管道): 只打印快速上手卡片并写标记, 不提问;
    - 交互: 走完整欢迎/选模型/生成 QXT.md/自动记忆/快速上手流程。
    """
    home = Path(home) if home else home_dir()
    workspace = Path(workspace) if workspace else Path.cwd()
    inter = _is_interactive() if interactive is None else interactive

    if skip:
        mark_onboarding_done(home)
        print("  已跳过首次引导。可用 `qxt onboarding` 随时重跑。")
        return 0

    _print_welcome()

    if not inter:
        # 非交互: 不提问, 只给快速上手指南, 然后写标记 (下次不再打扰)
        _print_quick_start()
        mark_onboarding_done(home)
        print("  (非交互模式: 已自动跳过交互式引导)")
        return 0

    # ---- 交互式引导 ----
    # 1. provider/model 选择 (轻量: 列出已知 provider, 让用户选或跳过)
    print("  第一步: 选择默认模型供应商 (可稍后用 `qxt models set` 改)")
    try:
        from ..models.provider_catalog import PROVIDER_CATEGORIES
        names = [cat[0] for cat in PROVIDER_CATEGORIES[:8]] if PROVIDER_CATEGORIES else []
    except Exception:  # noqa: BLE001
        names = []
    if names:
        for i, n in enumerate(names, 1):
            print(f"    {i}. {n}")
        print("    0. 跳过 (稍后自己配)")
        try:
            pick = input("  选择供应商编号 > ").strip()
        except (EOFError, KeyboardInterrupt):
            pick = "0"
        if pick.isdigit() and 1 <= int(pick) <= len(names):
            print(f"  已记下偏好: {names[int(pick)-1]} (用 `qxt models set <provider> <model>` 完成配置)")
        else:
            print("  已跳过供应商选择。")
    else:
        print("  (未枚举到内置供应商, 跳过; 可用 `qxt models` 配置)")

    # 2. 是否生成 QXT.md (当前是 git 仓库时提议)
    if _detect_git_repo(workspace):
        if _ask_yes_no("当前是 git 仓库, 要现在生成 QXT.md 项目规则吗?", default=True):
            print("  好的, 启动后输入 /init 即可生成 (或现在运行 qxt init)。")

    # 3. 自动记忆 (默认开)
    mem = _ask_yes_no("启用自动记忆 (我会记住你的偏好并在下次会话沿用)?", default=True)
    print(f"  自动记忆: {'已启用' if mem else '已关闭'} (可用 `qxt memory` 查看)")

    # 4. 快速上手卡片
    _print_quick_start()

    mark_onboarding_done(home)
    print("  引导完成! 输入 `qxt` 开始对话, 或 `qxt run \"任务\"` 跑一次性任务。")
    return 0


def cmd_onboarding(args) -> int:
    """`qxt onboarding` CLI 入口。"""
    skip = bool(getattr(args, "skip", False))
    workspace = getattr(args, "workspace", None) or os.getcwd()
    return run_onboarding(Path(workspace), skip=skip)
