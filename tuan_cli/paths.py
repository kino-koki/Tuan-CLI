"""默认工作目录解析 —— 尊重当前目录, 显式指定优先 (2026-10-18 行为修正)。

历史行为与问题
--------------
旧设计: Agent 未显式指定工作目录时, 强制 ``os.chdir`` 进入内置 D 盘独立目录
(``D:\\DeliveryOptimization\\Tuan-Workspace``) —— 无论用户从哪个目录启动, 都被
弹到同一个固定目录。这带来强烈的「目录劫持」体感: 用户 ``cd`` 到自己的项目里
敲 ``tuan``, 落地却是一个陌生目录, 相对路径/子进程/文件操作全部落空。

现行行为 (修复后)
----------------
**默认尊重用户启动时的当前目录 (CWD)** —— 不 chdir、不创建、不跳转。
Agent 就在用户所在的目录里干活, 与 ``cd`` 的直觉一致。

解析顺序 (高 → 低)
----------------
1. 命令行 ``--workspace`` 显式传入 (调用方直接传参, 不经本模块)
2. 环境变量 ``TUAN_WORKSPACE`` (一次性覆盖, 适合脚本/CI)
3. 配置 ``agent.workspace`` (``~/.tuan/config.yaml`` 或 settings.json, 非空即采信)
4. **当前工作目录 (CWD)** —— 新默认, 取代旧的内置 D 盘候选链

显式值 (env/config) 会尽力创建目录 (用户自己的目录由用户负责, 但帮一次忙);
CWD 兜底什么都不做。

opt-in 旧行为
------------
``TUAN_AUTO_WORKSPACE=1``: 恢复「未显式指定时自动进入独立工作区」
(首次自动创建 + chdir)。适合确实需要「无论从哪启动都落同一个隔离工作区」
的场景 (安全隔离诉求), 默认关闭。工作区位于 ``~\\Tuan-Workspace``
(用户主目录下, 跨机器可移植, 不依赖任何固定盘符)。

``TUAN_FORCE_WORKSPACE=1``: 绝对强制 —— 忽略 env/CLI/config 的显式指定,
一律进入 ``TUAN_WORKSPACE`` 指向的目录 (未设则用内置默认)。

回退语义: 任何一层失败都**不静默**——记日志并继续向下回退, 保证任何环境下
Agent 都能启动 (fail-open 仅限位置选择, 安全闸门不受影响)。
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import List, Optional, Tuple

log = logging.getLogger(__name__)

#: 工作目录目录名 (opt-in 自动工作区模式下使用)。
WORKSPACE_DIR_NAME = "Tuan-Workspace"

#: opt-in 自动工作区的首选: 用户主目录下的独立工作区 (跨机器可移植)。
#: 仅 ``TUAN_AUTO_WORKSPACE=1`` / ``TUAN_FORCE_WORKSPACE=1`` 时才会用到。
#: 历史上曾硬编码 ``D:\\DeliveryOptimization\\Tuan-Workspace`` —— 换台设备或
#: 没有 D 盘的机器上, 该路径不可用, 是「目录写死」的典型问题; 现改为
#: ``~\\Tuan-Workspace`` (Windows) / ``~/.tuan/workspace`` 同源位置, 与
#: 配置/会话目录一致, 任何有用户主目录的机器都能落地。
DEFAULT_WORKSPACE_DIR = Path.home() / WORKSPACE_DIR_NAME

#: 环境变量覆盖入口。
WORKSPACE_ENV_VAR = "TUAN_WORKSPACE"

#: opt-in 开关: 置 1 后恢复旧行为 (未显式指定时自动进入独立工作区)。
AUTO_WORKSPACE_ENV_VAR = "TUAN_AUTO_WORKSPACE"

#: 兼容旧版的逃生开关 (默认已不跳转, 此变量现为恒真无操作, 保留防脚本报错)。
NO_AUTO_CHDIR_ENV_VAR = "TUAN_NO_AUTO_CHDIR"

#: 「绝对强制工作目录」开关: 置 1 后忽略 env/CLI/config 的显式指定,
#: 无论从哪个目录启动都进入同一个工作区。
FORCE_WORKSPACE_ENV_VAR = "TUAN_FORCE_WORKSPACE"

# 进程级缓存: 配置读取涉及文件 I/O, 而本函数在 CLI 各命令入口被高频调用。
# 同一进程内配置不会变 (--patch 层由调用方显式传参, 不走本缓存)。
_cached: Optional[str] = None


def _from_env() -> Optional[str]:
    """环境变量 TUAN_WORKSPACE (非空采信)。"""
    val = os.environ.get(WORKSPACE_ENV_VAR, "").strip()
    return val or None


def _from_config() -> Optional[str]:
    """配置 agent.workspace (非空采信)。

    依次读两个配置层 (后者是文档记载的主配置):
    1. ManagedSettings (settings.json 级联: 组织/用户/项目/环境变量);
    2. Config (~/.tuan/config.yaml 的 agent.workspace)。

    读取失败 (配置损坏/环境异常) 时返回 None, 由调用方继续向下回退——
    位置选择永不应成为启动阻塞项。
    """
    try:
        from .config.loader import home_dir
        from .config.managed import ManagedSettings

        val = ManagedSettings(home_dir()).get("agent.workspace", "")
        val = str(val or "").strip()
        if val:
            return val
    except Exception as exc:  # noqa: BLE001 - 位置解析不可阻塞启动
        log.debug("default_workspace: settings.json 读取失败, 尝试 config.yaml: %s", exc)
    try:
        from .config.loader import Config, home_dir

        val = Config(home_dir()).get("agent.workspace", "")
        val = str(val or "").strip()
        return val or None
    except Exception as exc:  # noqa: BLE001 - 位置解析不可阻塞启动
        log.debug("default_workspace: 配置读取失败, 回退当前目录: %s", exc)
        return None


def _ensure_dir(path: Path) -> Optional[Path]:
    """尽力创建目录; 失败返回 None (调用方回退 CWD)。"""
    try:
        path.mkdir(parents=True, exist_ok=True)
        return path if path.is_dir() else None
    except OSError as exc:
        log.debug("default_workspace: 无法创建工作目录 %s (%s), 回退当前目录", path, exc)
        return None


def _fallback_candidates() -> List[Path]:
    """opt-in 自动工作区候选链: 首选不可用时的回退 (按序尝试)。

    首选 (``~\\Tuan-Workspace``, 跨机器可移植) 不可写时, 退到 tuan 自己的
    home (``~/.tuan/workspace``, 与配置/会话同源)。位置选择永不应成为启动
    阻塞项: 若全部失败, 调用方回退 CWD。
    """
    out: List[Path] = []
    try:
        from .config.loader import home_dir

        out.append(Path(home_dir()) / "workspace")
    except Exception as exc:  # noqa: BLE001
        log.debug("default_workspace: home 目录解析失败 (%s), 回退 CWD", exc)
    return out


def _builtin_candidates() -> List[Path]:
    """完整内置候选链 (仅 opt-in 自动工作区模式使用): 首选 + 回退。"""
    return [DEFAULT_WORKSPACE_DIR, *_fallback_candidates()]


def _resolve_explicit() -> Optional[str]:
    """显式指定 (env > config); 顺手创建目录, 创建失败也返回原路径 (调用方回退)。"""
    resolved = _from_env() or _from_config()
    if not resolved:
        return None
    candidate = Path(resolved).expanduser()
    made = _ensure_dir(candidate)
    return str((made or candidate).resolve()) if made else str(candidate)


def default_workspace() -> str:
    """返回 Agent 默认工作目录 (绝对路径字符串)。

    解析顺序: ``TUAN_WORKSPACE`` 环境变量 > 配置 ``agent.workspace`` >
    **当前工作目录 (CWD)**。

    2026-10-18 起默认尊重 CWD: 用户在哪启动就在哪干活, 不再强制跳转
    ``D:\\DeliveryOptimization\\Tuan-Workspace``。旧行为可用
    ``TUAN_AUTO_WORKSPACE=1`` 显式打开 (见模块 docstring)。
    """
    global _cached
    if _cached is not None:
        return _cached

    resolved = _resolve_explicit()
    if resolved:
        _cached = resolved
        return _cached

    # 新默认: 尊重用户启动时的当前目录 (绝对化, 避免后续 chdir 语义漂移)
    _cached = os.path.abspath(os.getcwd())
    return _cached


def auto_workspace() -> str:
    """opt-in 旧行为的工作目录解析: env > config > 内置独立工作区 > CWD。

    仅 ``TUAN_AUTO_WORKSPACE=1`` / ``TUAN_FORCE_WORKSPACE=1`` 时使用:
    未显式指定时进入内置独立工作区 (首次自动创建), 与仓库/系统/用户目录隔离。
    首选位置为 ``~\\Tuan-Workspace`` (跨机器可移植); 不可写时退到
    ``~/.tuan/workspace`` (与配置/会话同源); 全部失败则回退 CWD。
    """
    resolved = _resolve_explicit()
    if resolved:
        return resolved
    for candidate in _builtin_candidates():
        made = _ensure_dir(candidate)
        if made is not None:
            return str(made.resolve())
    # 候选全部不可用: 回退 CWD (保底可启动)
    return os.path.abspath(os.getcwd())


def workspace_source() -> Tuple[str, str]:
    """返回 ``(工作目录绝对路径, 来源标签)`` —— 供 ``tuan workspace`` 展示。

    来源标签: ``env`` | ``config`` | ``cwd`` | ``default (内置独立工作区)``。
    """
    if _from_env():
        return default_workspace(), "env (TUAN_WORKSPACE)"
    if _from_config():
        return default_workspace(), "config (agent.workspace)"
    path = default_workspace()
    # opt-in/强制模式下若进了内置独立工作区, 标注出来 (默认模式下不会发生)
    try:
        if os.path.normcase(path) == os.path.normcase(str(DEFAULT_WORKSPACE_DIR.resolve())):
            return path, "default (内置独立工作区, TUAN_AUTO_WORKSPACE=1)"
    except OSError:
        if path == str(DEFAULT_WORKSPACE_DIR):
            return path, "default (内置独立工作区, TUAN_AUTO_WORKSPACE=1)"
    return path, "cwd (当前目录)"


def ensure_default_workspace() -> str:
    """确保默认工作目录存在 (幂等), 返回其绝对路径。

    现行语义: 显式指定的目录会顺手创建; CWD 兜底原样返回 (无需创建)。
    """
    return default_workspace()


def workspace_explicitly_set(argv: Optional[List[str]] = None) -> Optional[str]:
    """检测用户是否**显式**指定了工作目录; 是则返回来源标签, 否则 None。

    显式来源: ``TUAN_WORKSPACE`` 环境变量 / ``--workspace`` 命令行参数 /
    ``agent.workspace`` 配置。三者任一即视为显式。

    注意: argv 检测是保守的包含匹配 —— 任务自由文本里恰好出现 ``--workspace``
    字样也会被判为「显式」。方向安全: 漏判只是多用一次 CWD, 乱判才会改变用户预期。
    """
    if _from_env():
        return "env"
    if argv:
        for token in argv:
            if token == "--workspace" or token.startswith("--workspace="):
                return "cli"
    if _from_config():
        return "config"
    return None


def _auto_workspace_opted_in() -> bool:
    """``TUAN_AUTO_WORKSPACE=1``: 用户显式选择旧行为 (自动进入内置独立工作区)。"""
    return os.environ.get(AUTO_WORKSPACE_ENV_VAR, "").strip() not in ("", "0", "false", "False")


def maybe_enter_default_workspace(argv: Optional[List[str]] = None) -> Optional[str]:
    """按需进入默认工作目录。

    现行默认 (2026-10-18 起): **不跳转** —— 尊重用户启动时的当前目录, 直接
    返回 None。只有以下两种情况才会 chdir:
    1. ``TUAN_AUTO_WORKSPACE=1`` (opt-in 旧行为): 未显式指定时进入内置独立工作区;
    2. ``TUAN_FORCE_WORKSPACE=1``: 绝对强制, 忽略显式指定一律进同一工作区。

    任何异常都不阻断启动 (位置选择永不应成为启动阻塞项)。
    """
    forced = os.environ.get(FORCE_WORKSPACE_ENV_VAR, "").strip() not in ("", "0", "false", "False")
    opted_in = _auto_workspace_opted_in()
    if not forced and not opted_in:
        # 默认: 尊重 CWD, 不跳转不创建
        return None
    try:
        tokens = list(sys.argv[1:]) if argv is None else list(argv)
        if not forced and workspace_explicitly_set(tokens):
            return None
        # opt-in / 强制模式: 用内置候选链 (env > config > D 盘独立目录 > CWD)
        target = auto_workspace()
        current = os.getcwd()
        if os.path.normcase(target) != os.path.normcase(current):
            os.chdir(target)
        return target
    except Exception as exc:  # noqa: BLE001 - 位置选择不可阻塞启动
        log.warning("maybe_enter_default_workspace: 进入工作目录失败 (%s), 保持当前目录", exc)
        return None


def reset_workspace_cache() -> None:
    """清空进程级缓存 (仅供测试/配置热重载使用)。"""
    global _cached
    _cached = None
