"""fastindex 命令 —— 持久化快速文件索引只读体检 (第 116 个独特功能)。

context/fast_index.py 的 FastFileIndex 把会话内的符号/导入/首行索引增量落盘到
``<workspace>/.tuan/fastindex/index.json`` (entries 按 relpath → {lang,size,loc,
symbols[],head}), 供上下文检索快速定位文件。它本质是一个**加速缓存**: 会话
内自动 build, 跨进程复用。但用户此前没有任何只读面能看到: 索引里收录了
多少文件、各语言分布、总 LOC、符号总量、最大的文件、以及最近 build 的指纹
(哪些文件变更会被重扫)。本命令补上独立只读体检面 (纯只读: json.load +
统计, 不构造 FastFileIndex —— 其 __init__ 会 _load, 且 build 会 mkdir/_save,
避免任何写副作用)。

差异化价值: 该索引是 Claude Code 没有的持久化增量索引, 且此前纯内部缓存;
本命令把它变成可被任何进程审计的持久事实 (覆盖率/语言分布/符号密度)。

  tuan fastindex [--workspace DIR] [--json]          # 索引体检
  tuan fastindex files [--workspace DIR] [--limit N] [--json]  # 按符号数/体积排名
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from ._ui_singleton import console
from .parser import _register_command


def _resolve_workspace(raw: Optional[str]) -> Path:
    if raw:
        return Path(raw).expanduser().resolve()
    env = os.environ.get("TUAN_WORKSPACE")
    if env:
        return Path(env).expanduser().resolve()
    return Path.cwd().resolve()


def _index_path(workspace: Path) -> Path:
    return workspace / ".tuan" / "fastindex" / "index.json"


def _load(path: Path) -> Optional[Dict[str, Any]]:
    """读取索引 (纯只读); 缺失/损坏返回 None。"""
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if isinstance(data, dict) and isinstance(data.get("entries"), dict):
        return data
    return None


def _entries(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    out = [e for e in data.get("entries", {}).values() if isinstance(e, dict)]
    return out


def cmd_fastindex(args: Any) -> int:
    """持久化快速文件索引只读体检 (第 116 个独特功能, 纯只读)。"""
    sub = getattr(args, "fastindex_cmd", None) or "stats"
    json_mode = bool(getattr(args, "json", False))
    workspace = _resolve_workspace(getattr(args, "workspace", None))
    path = _index_path(workspace)
    data = _load(path)
    entries = _entries(data) if data else []

    # 语言分布
    by_lang: Dict[str, int] = {}
    total_loc = 0
    total_symbols = 0
    total_bytes = 0
    for e in entries:
        lang = str(e.get("lang", "other"))
        by_lang[lang] = by_lang.get(lang, 0) + 1
        total_loc += int(e.get("loc", 0) or 0)
        total_symbols += len(e.get("symbols", []) or [])
        total_bytes += int(e.get("size", 0) or 0)

    stats: Dict[str, Any] = {
        "version": data.get("version") if data else None,
        "file_count": len(entries),
        "total_loc": total_loc,
        "total_symbols": total_symbols,
        "total_bytes": total_bytes,
        "by_lang": by_lang,
        "max_symbols_file": _max_by(entries, lambda e: len(e.get("symbols", []) or [])),
        "max_size_file": _max_by(entries, lambda e: float(int(e.get("size", 0) or 0))),
    }

    if sub == "files":
        limit = int(getattr(args, "limit", 0) or 0)
        ranked = sorted(entries,
                        key=lambda e: len(e.get("symbols", []) or []), reverse=True)
        if limit:
            ranked = ranked[:limit]
        if json_mode:
            print(json.dumps({"workspace": str(workspace),
                              "index_file": str(path),
                              "initialized": path.is_file(),
                              "items": [{
                                  "relpath": e.get("relpath"),
                                  "lang": e.get("lang"),
                                  "loc": e.get("loc"),
                                  "size": e.get("size"),
                                  "symbols": len(e.get("symbols", []) or []),
                                  "head": str(e.get("head", ""))[:60],
                              } for e in ranked]},
                             ensure_ascii=False, indent=2))
            return 0
        console.print(f"[bold]=== 索引文件排名 (按符号数) · {path} ===[/bold]\n")
        if not ranked:
            console.print("  [dim](索引未初始化或为空)[/dim]")
            return 0
        for e in ranked:
            console.print(f"  [bold]{e.get('relpath', '?')}[/bold]")
            console.print(f"      {len(e.get('symbols', []) or [])} 符号 · "
                          f"{int(e.get('loc', 0) or 0)} LOC · "
                          f"{int(e.get('size', 0) or 0)/1024:.1f} KB · "
                          f"{e.get('lang')}")
        return 0

    # 默认 stats
    if json_mode:
        print(json.dumps({"workspace": str(workspace),
                          "index_file": str(path),
                          "initialized": path.is_file(),
                          **stats}, ensure_ascii=False, indent=2))
        return 0
    console.print(f"[bold]=== 快速文件索引 · {path} ===[/bold]\n")
    if not path.is_file():
        console.print("  [dim]索引未初始化 (会话运行自动 build 后建立; "
                      "用 `tuan codedev retrieve` 也可手动生成)[/dim]")
        return 0
    console.print(f"  版本: {stats['version']}")
    console.print(f"  文件: {stats['file_count']}")
    console.print(f"  总 LOC: {stats['total_loc']:,} · 总符号: {stats['total_symbols']:,}")
    console.print(f"  占用: {stats['total_bytes']/1024:.1f} KB\n")
    console.print("  语言分布:")
    for lang, n in sorted(by_lang.items(), key=lambda kv: -kv[1]):
        console.print(f"    {lang}: {n}")
    mx = stats["max_symbols_file"]
    ms = stats["max_size_file"]
    console.print("\n  最大符号数: "
                  f"[bold]{mx['relpath']}[/bold] ({mx['value']} 符号)")
    console.print("  最大体积: "
                  f"[bold]{ms['relpath']}[/bold] ({ms['value']/1024:.1f} KB)")
    return 0


def _max_by(entries: List[Dict[str, Any]], key: "Callable[[Dict[str, Any]], float]") -> Dict[str, Any]:
    best: Optional[Dict[str, Any]] = None
    for e in entries:
        v = key(e)
        if best is None or v > float(best["value"]):
            best = {"relpath": e.get("relpath", "?"), "value": v}
    return best if best else {"relpath": "-", "value": 0.0}


_register_command("cmd_fastindex", ".cmd_fastindex")
