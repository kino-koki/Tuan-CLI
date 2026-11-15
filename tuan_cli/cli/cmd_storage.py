"""storage 命令 —— 持久化数据占用可观测性 (第 100 个独特功能)。

只读扫描 <home>/.tuan 下各子系统的磁盘占用: 会话 / 检查点 / 快照 / 审计 /
完整性监控 / 后台作业 / 日志 / 缓存 / 协作黑板 / 记忆 / 遥测等, 按体积
降序列出, 并可下钻到单个子目录 (递归列出最大的文件)。

差异化价值: Claude Code 只把数据存在 ~/.claude 下, 用户对「哪些子系统
吃了多少磁盘」没有可查询入口, 也没有「最大文件在哪」的定位能力。本命令
把 Tuan-CLI 的持久化层 (20+ 个子系统) 的磁盘占用暴露为只读报表, 运维可
据此做清理决策 (如 sessions/ 膨胀、checkpoints/ 积压)。

纯只读: 只用 os.walk / Path.iterdir 统计, 不写任何文件。

  tuan storage [--home H] [--json]             # 各子系统占用概览
  tuan storage top [--n N] [--home H] [--json] # 全局最大的 N 个文件
  tuan storage tree <子系统> [--home H]        # 下钻: 子系统内最大文件
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ._ui_singleton import console
from .parser import _register_command


# ---------------------------------------------------------------- 辅助

def _get_home(home_raw: Optional[str]) -> Path:
    if home_raw:
        return Path(home_raw).expanduser().resolve()
    from ..config.loader import home_dir
    return Path(home_dir())


def _fmt_size(n: int) -> str:
    value = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            if unit == "B":
                return f"{int(value)} B"
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"


def _dir_size(d: Path) -> Tuple[int, int]:
    """返回 (总字节, 文件数)。跳过损坏的符号链接。"""
    total = 0
    count = 0
    for root, dirs, files in os.walk(d):
        for f in files:
            try:
                fp = Path(root) / f
                if fp.is_symlink():
                    continue
                total += fp.stat().st_size
                count += 1
            except OSError:
                continue
    return total, count


def _subsystem_scan(home: Path) -> List[Dict[str, Any]]:
    """扫 .tuan 下每个子系统目录, 返回占用列表。"""
    rows: List[Dict[str, Any]] = []
    if not home.is_dir():
        return rows
    for child in sorted(home.iterdir()):
        if not child.is_dir():
            continue
        size, count = _dir_size(child)
        rows.append({
            "subsystem": child.name,
            "bytes": size,
            "files": count,
            "human": _fmt_size(size),
        })
    rows.sort(key=lambda r: r["bytes"], reverse=True)
    return rows


# ---------------------------------------------------------------- 子命令

def _cmd_storage_overview(args: Any) -> int:
    """子系统占用概览。"""
    try:
        home = _get_home(getattr(args, "home", None))
        rows = _subsystem_scan(home)
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]存储扫描失败: {exc}[/red]")
        return 1

    total_bytes = sum(r["bytes"] for r in rows)
    total_files = sum(r["files"] for r in rows)

    if getattr(args, "json", False):
        print(json.dumps({
            "home": str(home),
            "total_bytes": total_bytes,
            "total_files": total_files,
            "subsystems": rows,
        }, ensure_ascii=False, indent=2))
        return 0

    if not rows:
        console.print(f"[dim]{home} 不存在或无子系统目录[/dim]")
        return 0

    console.print(f"[bold]Tuan 持久化占用 · {home}[/bold]\n")
    console.print(f"  总计: {_fmt_size(total_bytes)} / {total_files} 个文件 "
                  f"({len(rows)} 个子系统)\n")
    for r in rows:
        if r["bytes"] == 0:
            continue
        bar_len = max(1, int(40 * r["bytes"] / max(total_bytes, 1)))
        console.print(f"  {r['subsystem']:<16} {r['human']:>9} "
                      f"[{'#' * bar_len}] ({r['files']} 文件)")
    console.print("\n[dim]子命令: top (全局最大文件) / tree <子系统> (下钻)[/dim]")
    return 0


def _cmd_storage_top(args: Any) -> int:
    """全局最大的 N 个文件。"""
    try:
        home = _get_home(getattr(args, "home", None))
        n = int(getattr(args, "n", 20) or 20)
        rows: List[Dict[str, Any]] = []
        for root, dirs, files in os.walk(home):
            for f in files:
                try:
                    fp = Path(root) / f
                    if fp.is_symlink():
                        continue
                    st = fp.stat()
                    rel = str(fp.relative_to(home))
                    rows.append({
                        "path": rel, "bytes": st.st_size,
                        "human": _fmt_size(st.st_size),
                    })
                except OSError:
                    continue
        rows.sort(key=lambda r: r["bytes"], reverse=True)
        rows = rows[:n]
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]扫描失败: {exc}[/red]")
        return 1

    if getattr(args, "json", False):
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return 0

    if not rows:
        console.print(f"[dim]{home} 不存在或为空[/dim]")
        return 0
    console.print(f"[bold]全局最大的 {len(rows)} 个文件[/bold]\n")
    for r in rows:
        console.print(f"  {r['human']:>9}  {r['path']}")
    return 0


def _cmd_storage_tree(args: Any) -> int:
    """下钻: 子系统内最大的文件。"""
    subsystem = getattr(args, "subsystem", None)
    if not subsystem:
        console.print("[red]用法: tuan storage tree <子系统>[/red]")
        return 1
    try:
        home = _get_home(getattr(args, "home", None))
        target = home / subsystem
        if not target.is_dir():
            console.print(f"[red]子系统不存在: {subsystem}[/red]")
            return 1
        size, count = _dir_size(target)
        rows: List[Dict[str, Any]] = []
        for root, dirs, files in os.walk(target):
            for f in files:
                try:
                    fp = Path(root) / f
                    if fp.is_symlink():
                        continue
                    st = fp.stat()
                    rows.append({
                        "path": str(fp.relative_to(target)),
                        "bytes": st.st_size,
                        "human": _fmt_size(st.st_size),
                    })
                except OSError:
                    continue
        rows.sort(key=lambda r: r["bytes"], reverse=True)
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]下钻失败: {exc}[/red]")
        return 1

    console.print(f"[bold]{subsystem}/ · 共 {_fmt_size(size)} / {count} 个文件[/bold]\n")
    if not rows:
        console.print("[dim]空目录[/dim]")
        return 0
    for r in rows[:30]:
        console.print(f"  {r['human']:>9}  {r['path']}")
    if len(rows) > 30:
        console.print(f"  [dim]... 另有 {len(rows) - 30} 个文件[/dim]")
    return 0


# ---------------------------------------------------------------- 分发入口

def cmd_storage(args: Any) -> int:
    """持久化数据占用可观测性总入口 (第 100 个独特功能, 纯只读)。"""
    sub = getattr(args, "storage_cmd", None) or "overview"

    if sub == "top":
        return _cmd_storage_top(args)
    elif sub == "tree":
        return _cmd_storage_tree(args)
    elif sub in ("overview", ""):
        return _cmd_storage_overview(args)
    else:
        console.print(f"[red]未知子命令: {sub}[/red]")
        console.print("可用: overview / top / tree")
        return 1


_register_command("cmd_storage", ".cmd_storage")
