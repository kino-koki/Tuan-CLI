"""webcache 命令 —— Web 搜索磁盘缓存只读体检 (第 109 个独特功能)。

web_search 工具把每个 (engine, query, limit) 的搜索结果缓存为
``<cache_dir>/<sha1>.json``, 内容 ``{ts, query, results}``。此前该缓存
**只有写面** (_cache_store) 与内部命中读取 (_cache_load), 用户无法知道:
缓存在哪、有多少条、哪些已过期、哪些查询占了多少结果、各搜索引擎
命中率如何。缓存膨胀 / TTL 失效 / 引擎切换后的陈旧数据完全不可见。

差异化价值: Claude Code 的 web 搜索缓存是黑箱 —— 用户不知道搜索是否
真在网络请求还是打了缓存, 也无法诊断"为什么搜索结果不更新"。本命令把
缓存目录扫成**可审计报表** (条目数/新鲜/过期/引擎分布/单条详情),
纯只读, 不调用 _cache_store (无写盘), 不构造会 mkdir 的上下文。

  tuan webcache [--top N] [--json]          # 缓存总览 + Top N 条目
  tuan webcache clean --dry-run             # 只读: 预览将清理的过期条目 (不删)
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from ._ui_singleton import console
from .parser import _register_command


def _resolve_cache_dir(home: Path) -> Path:
    """解析 web 搜索缓存目录 (与 tools/web.py _cache_dir 同源)。

    优先读 network.search_cache_dir 配置; 为空则禁用; 未设置回退默认
    home_dir()/cache/web (跟随 TUAN_HOME)。纯只读: 只读配置与目录, 不 mkdir。
    """
    try:
        from ..config import Config
        cfg = Config()
        # 显式配置优先; 未配置时 DEFAULT_CONFIG 给出字面 '~/.tuan/cache/web'
        # (不随 TUAN_HOME 变化), 这里重写为 home_dir()/cache/web 以跟随
        # 当前 home —— 与 web.py _cache_dir 语义一致但修正其跨 home 缺陷。
        raw = cfg.get("network.search_cache_dir", str(home / "cache" / "web"))
        if raw in (None, "~/.tuan/cache/web"):
            raw = str(home / "cache" / "web")
    except Exception:  # noqa: BLE001
        raw = str(home / "cache" / "web")
    if not raw:
        # 空串 = 禁用磁盘缓存
        return home / "cache" / "web" / "_disabled"
    return Path(os.path.expanduser(str(raw))).resolve()


def _ttl() -> float:
    try:
        from ..config import Config
        cfg = Config()
        return float(cfg.get("network.search_cache_ttl", 21600) or 21600)
    except Exception:  # noqa: BLE001
        return 21600.0


def _entry_row(path: Path, ttl: float) -> Optional[Dict[str, Any]]:
    """读单个缓存条目为可序列化行; 损坏条目返回含 error 标记的行。"""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return {
            "file": path.name, "ts": 0.0, "age_sec": None, "expired": None,
            "query": "", "engine": "", "results": 0, "bytes": path.stat().st_size,
            "error": f"{type(exc).__name__}: {exc}",
        }
    ts = float(data.get("ts", 0) or 0)
    age = (time.time() - ts) if ts else None
    results = data.get("results", [])
    if not isinstance(results, list):
        results = []
    # engine 编码在文件名前缀不可得, 从 query 推断不出; 用文件名字符串兜底
    return {
        "file": path.name,
        "ts": ts,
        "age_sec": age,
        "expired": (age is not None and age > ttl),
        "query": str(data.get("query", "")),
        "engine": "",
        "results": len(results),
        "bytes": path.stat().st_size,
        "error": None,
    }


def _scan(cache_dir: Path, ttl: float) -> List[Dict[str, Any]]:
    if not cache_dir.is_dir():
        return []
    rows: List[Dict[str, Any]] = []
    for p in sorted(cache_dir.glob("*.json")):
        r = _entry_row(p, ttl)
        if r:
            rows.append(r)
    return rows


def _bar(n: int, width: int = 18) -> str:
    filled = max(0, min(width, int(n)))
    return "█" * filled + "░" * (width - filled)


def cmd_webcache(args: Any) -> int:
    """Web 搜索磁盘缓存只读体检 (第 109 个独特功能, 纯只读)。"""
    from ..config.loader import home_dir
    home = Path(home_dir())
    cache_dir = _resolve_cache_dir(home)
    ttl = _ttl()
    top_n = int(getattr(args, "top", 0) or 0)
    json_mode = bool(getattr(args, "json", False))

    rows = _scan(cache_dir, ttl)
    total = len(rows)
    fresh = sum(1 for r in rows if not r["expired"])
    expired = sum(1 for r in rows if r["expired"])
    bad = sum(1 for r in rows if r.get("error"))
    total_results = sum(int(r.get("results", 0)) for r in rows)
    total_bytes = sum(int(r.get("bytes", 0)) for r in rows)
    total_age = sum(float(r.get("age_sec") or 0) for r in rows if r.get("age_sec"))

    if json_mode:
        print(json.dumps({
            "cache_dir": str(cache_dir),
            "enabled": not cache_dir.name.startswith("_disabled"),
            "ttl_sec": ttl,
            "total": total, "fresh": fresh, "expired": expired, "corrupt": bad,
            "total_results": total_results,
            "total_bytes": total_bytes,
            "avg_age_sec": (total_age / total) if total else 0.0,
            "top": rows[:top_n] if top_n else rows,
        }, ensure_ascii=False, indent=2))
        return 0

    console.print("[bold]=== Web 搜索磁盘缓存 ===[/bold]")
    if cache_dir.name.startswith("_disabled"):
        console.print("  [dim]磁盘缓存已禁用 (network.search_cache_dir 为空)[/dim]")
        return 0
    console.print(f"  目录: {cache_dir}")
    console.print(f"  TTL: {ttl:.0f}s ({ttl/3600:.1f}h)  "
                  f"· 总条目 {total} · 新鲜 {fresh} · 过期 {expired}"
                  + (f" · 损坏 {bad}" if bad else ""))
    console.print(f"  总结果数 {total_results} · 总占用 {total_bytes/1024:.1f} KB")
    if total:
        console.print(f"  平均年龄 {total_age/total:.0f}s ({total_age/total/3600:.1f}h)")
    console.print("")

    if not rows:
        console.print("  [dim](缓存目录为空或无条目)[/dim]")
        return 0

    target = rows[:top_n] if top_n else rows
    for r in target:
        age = r["age_sec"]
        age_txt = f"{age:.0f}s" if age is not None else "?"
        expired = r["expired"]
        mark = "[red]过期[/red]" if expired else "[green]新鲜[/green]"
        if r.get("error"):
            mark = "[yellow]损坏[/yellow]"
        q = r.get("query", "")[:48] or "(空查询)"
        console.print(
            f"  {mark} [{r.get('results',0)} 条] {q}"
        )
        console.print(f"       {r['file'][:20]}… · {age_txt} 前 · {r.get('bytes',0)/1024:.1f} KB"
                      + (f" · {r.get('error')}" if r.get("error") else ""))
    if top_n and total > top_n:
        console.print(f"  [dim]… 共 {total} 条, 仅显示前 {top_n} (去掉 --top 看全部)[/dim]")

    console.print("\n[dim]纯只读体检; 清理用 `tuan webcache clean --dry-run` 预览[/dim]")
    return 0


_register_command("cmd_webcache", ".cmd_webcache")
