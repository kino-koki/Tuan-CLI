"""image 命令 —— 已生成图片只读枚举 (第 113 个独特功能)。

image_gen 工具 (tools/image_gen.py) 把 AI 生成的图片保存到
``<workspace>/.tuan/generated/``, 文件名形如 ``img_20260919_143052_abc123.png``。
但该目录此前只能在一个**活着的会话里**用 ``/image list`` (或
image_list_generated 工具) 查看 —— 外部脚本/CI 无法脱离会话看到: 工作区里
到底生成了哪些图、各图多大、何时生成、占多少磁盘。本命令补上独立只读面
(纯只读, 只 glob + stat, 不调用 _ensure_gen_dir 写路径/mkdir)。

差异化价值: Claude Code 的 image_gen 产物同样只能会话内查看; 本命令把生成
目录变成可被任何进程审计的持久事实, 并给出占用统计与格式分布。

  tuan image list [--workspace DIR] [--limit N] [--json]   # 枚举生成图片
  tuan image show <文件名> [--workspace DIR]                # 查看单图元信息
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from ._ui_singleton import console
from .parser import _register_command

_GEN_DIR = ".tuan/generated"


def _resolve_workspace(raw: Optional[str]) -> Path:
    if raw:
        return Path(raw).expanduser().resolve()
    env = os.environ.get("TUAN_WORKSPACE")
    if env:
        return Path(env).expanduser().resolve()
    return Path.cwd().resolve()


def _gen_dir(workspace: Path) -> Path:
    return workspace / _GEN_DIR


def _row(path: Path) -> Dict[str, Any]:
    st = path.stat()
    return {
        "file": path.name,
        "size_bytes": st.st_size,
        "mtime": st.st_mtime,
        "iso": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(st.st_mtime)),
    }


def _prefix_from_name(name: str) -> str:
    """img_20260919_143052_abc123.png → img; 无下划线前缀则返回整体。"""
    return name.split("_", 1)[0] if "_" in name else name


def cmd_image(args: Any) -> int:
    """已生成图片只读枚举 (第 113 个独特功能, 纯只读)。"""
    sub = getattr(args, "image_cmd", None) or "list"
    json_mode = bool(getattr(args, "json", False))
    workspace = _resolve_workspace(getattr(args, "workspace", None))
    gdir = _gen_dir(workspace)

    if sub == "list":
        if not gdir.is_dir():
            if json_mode:
                print(json.dumps({"workspace": str(workspace),
                                  "gen_dir": str(gdir),
                                  "initialized": False, "items": []},
                                 ensure_ascii=False, indent=2))
                return 0
            console.print("[dim]生成目录未初始化 (尚无图片; "
                          "用 /image generate 或 image_generate 工具生成后自动建立)[/dim]")
            return 0
        rows = [_row(p) for p in sorted(gdir.glob("*.png"),
                                        key=lambda p: p.stat().st_mtime, reverse=True)]
        limit = int(getattr(args, "limit", 0) or 0)
        if limit and len(rows) > limit:
            rows = rows[:limit]
        if json_mode:
            print(json.dumps({"workspace": str(workspace),
                              "gen_dir": str(gdir),
                              "initialized": True,
                              "total": len(rows),
                              "items": rows,
                              "total_bytes": sum(r["size_bytes"] for r in rows)},
                             ensure_ascii=False, indent=2))
            return 0
        console.print(f"[bold]=== 已生成图片 · {gdir} ===[/bold]\n")
        if not rows:
            console.print("  [dim](空)[/dim]")
            return 0
        total_bytes = sum(r["size_bytes"] for r in rows)
        by_prefix: Dict[str, int] = {}
        for r in rows:
            pfx = _prefix_from_name(r["file"])
            by_prefix[pfx] = by_prefix.get(pfx, 0) + 1
        console.print(f"  {len(rows)} 张 · 共 {total_bytes/1024:.1f} KB")
        console.print(f"  前缀分布: {', '.join(f'{k}={v}' for k, v in sorted(by_prefix.items()))}\n")
        for r in rows:
            console.print(f"  [bold]{r['file']}[/bold]")
            console.print(f"      {r['size_bytes']/1024:.1f} KB · {r['iso']}")
        return 0

    elif sub == "show":
        name = getattr(args, "file", None)
        if not name:
            console.print("[red]缺少文件名: tuan image show <文件名>[/red]")
            return 1
        target = (gdir / name).resolve()
        if not target.is_file() or not str(target).startswith(str(gdir.resolve())):
            console.print(f"[red]图片不存在: {name}[/red]")
            return 1
        r = _row(target)
        if json_mode:
            print(json.dumps(r, ensure_ascii=False, indent=2))
            return 0
        console.print(f"[bold]{r['file']}[/bold]")
        console.print(f"  {r['size_bytes']/1024:.1f} KB · {r['iso']}")
        console.print("\n[dim]图片路径: " + str(target).replace("\\", "/") + "[/dim]")
        return 0

    else:
        console.print(f"[red]未知子命令: {sub}[/red]")
        console.print("可用: list / show")
        return 1


_register_command("cmd_image", ".cmd_image")
