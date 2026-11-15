"""auditstore 命令 —— 内核全量审计事件归档只读查询 (第 107 个独特功能)。

把 audit.store.AuditStore 管理的**内核事件总线归档** (audit/audit.log
JSONL 一行一条, 超 20MB 轮转为 .1~.5) 暴露为跨进程只读查询。任何内核
事件 (模型/工具/权限/任务生命周期) 经脱敏后自动落盘; 现有 safe audit
读的是 security_auditor 的 AEAD 防篡改链, mcp audit 读的是 MCP 专用存储,
**均与此归档无关** —— 本归档此前无任何 CLI 查看面。

差异化价值: Claude Code 的审计日志是黑箱, 用户看不到「内核到底归档了
哪些事件、各类型分布、时间跨度」, 也无法在不启动 agent 的情况下按类型/
关键词/时间窗过滤全量事件。本命令只读 AuditStore 的只读方法
(query/recent/stats), 不触发 log() 写盘, 也不构造会 mkdir 的 __init__
(未初始化时返回空)。

纯只读: 未初始化 (无 audit.log) 时不构造 AuditStore, 避免其 __init__ 的
目录创建副作用; 只用 query/recent/stats。

  tuan auditstore [--home H] [--json]                 # 统计: 总量/类型分布/时间跨度
  tuan auditstore stats [--home H] [--json]           # 统计 (顶层默认)
  tuan auditstore recent [--limit N] [--type T] [--home H] [--json]
  tuan auditstore query [--type T] [--keyword K] [--since H] [--until H] [--limit N] [--home H] [--json]
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from ._ui_singleton import console
from .parser import _register_command


# ---------------------------------------------------------------- 辅助

def _get_home(home_raw: Optional[str]) -> Path:
    if home_raw:
        return Path(home_raw).expanduser().resolve()
    from ..config.loader import home_dir
    return Path(home_dir())


def _open_store(home: Path) -> Any:
    """打开 AuditStore; 未初始化 (无 audit.log) 时返回 None。

    不构造 AuditStore 以避免其 __init__ 的目录创建副作用, 保证纯只读。
    仅当存在 audit.log (或任一轮转文件) 时才构造。
    """
    adir = home / "audit"
    has_log = (adir / "audit.log").exists()
    if not has_log:
        # 容忍仅有轮转文件而无本体的情况
        for i in range(1, 6):
            if (adir / f"audit.log.{i}").exists():
                has_log = True
                break
    if not has_log:
        return None
    from ..audit.store import AuditStore
    return AuditStore(home=home)


def _fmt_ts(ts: float) -> str:
    if not ts:
        return "-"
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))


def _ev_row(ev: Any) -> Dict[str, Any]:
    """把 AuditEvent 转成可 JSON 序列化的行 (纯读取, 无副作用)。"""
    return {
        "seq": getattr(ev, "seq", 0),
        "ts": getattr(ev, "ts", 0.0),
        "iso": time.strftime(
            "%Y-%m-%dT%H:%M:%SZ", time.gmtime(getattr(ev, "ts", 0.0))
        ) if getattr(ev, "ts", 0.0) else None,
        "type": getattr(ev, "type", ""),
        "payload": getattr(ev, "payload", {}),
    }


def _print_events(rows: List[Dict[str, Any]], title: str, show_payload: bool = False) -> None:
    console.print(f"[bold]{title} ({len(rows)} 项)[/bold]\n")
    if not rows:
        console.print("  [dim](空)[/dim]")
        return
    for r in rows:
        console.print(
            f"  #{r.get('seq',0):<6} [{r.get('type','?'):<24}] {_fmt_ts(r.get('ts',0))}"
        )
        if show_payload and r.get("payload"):
            payload = r["payload"]
            if isinstance(payload, dict):
                text = json.dumps(payload, ensure_ascii=False, default=str)
            else:
                text = str(payload)
            console.print(f"          [dim]{text[:120]}[/dim]")


# ---------------------------------------------------------------- 子命令

def _cmd_stats(args: Any, store: Any) -> int:
    json_mode = bool(getattr(args, "json", False))
    if store is None:
        if json_mode:
            print(json.dumps({"initialized": False, "stats": {}}, ensure_ascii=False, indent=2))
            return 0
        console.print("[dim]内核审计归档未初始化 (尚无 audit.log; "
                      "内核事件发生后自动建立)[/dim]")
        return 0

    stats = store.stats()
    if json_mode:
        print(json.dumps({"initialized": True, "stats": stats},
                         ensure_ascii=False, indent=2))
        return 0

    console.print(f"[bold]=== 内核审计归档 · {_get_home(getattr(args,'home',None))} ===[/bold]\n")
    console.print(f"  总事件 {stats.get('total',0)} · 类型分布 {len(stats.get('by_type',{}))} 种 · "
                  f"内存缓冲 {stats.get('buffered',0)} · enabled {stats.get('enabled',True)}")
    console.print(f"  最早 {stats.get('oldest_iso','-')} · 最近 {stats.get('newest_iso','-')}")
    by_type = stats.get("by_type", {})
    if by_type:
        console.print("\n[bold]按类型分布 (Top 10)[/bold]")
        for t, c in sorted(by_type.items(), key=lambda kv: kv[1], reverse=True)[:10]:
            console.print(f"  {t:<28} {c}")
    return 0


def _cmd_recent(args: Any, store: Any) -> int:
    json_mode = bool(getattr(args, "json", False))
    limit = int(getattr(args, "limit", 20) or 20)
    type_f = getattr(args, "type", None)
    if store is None:
        if json_mode:
            print(json.dumps({"initialized": False, "events": []}, ensure_ascii=False, indent=2))
            return 0
        console.print("[dim]内核审计归档未初始化[/dim]")
        return 0

    types = (type_f,) if type_f else ()
    evs = store.recent(n=limit, types=types)
    rows = [_ev_row(e) for e in evs]
    if json_mode:
        print(json.dumps({"initialized": True, "events": rows},
                         ensure_ascii=False, indent=2))
        return 0
    _print_events(rows, "最近审计事件" + (f" (type={type_f})" if type_f else ""),
                  show_payload=True)
    return 0


def _cmd_query(args: Any, store: Any) -> int:
    json_mode = bool(getattr(args, "json", False))
    type_f = getattr(args, "type", None)
    keyword = getattr(args, "keyword", "") or ""
    since_h = getattr(args, "since", None)
    until_h = getattr(args, "until", None)
    limit = int(getattr(args, "limit", 50) or 50)
    if store is None:
        if json_mode:
            print(json.dumps({"initialized": False, "events": []}, ensure_ascii=False, indent=2))
            return 0
        console.print("[dim]内核审计归档未初始化[/dim]")
        return 0

    from ..audit.store import AuditQuery
    now = time.time()
    q = AuditQuery(
        types=(type_f,) if type_f else (),
        since=(now - float(since_h) * 3600.0) if since_h else None,
        until=(now - float(until_h) * 3600.0) if until_h else None,
        keyword=keyword,
        limit=limit,
    )
    evs = store.query(q)
    rows = [_ev_row(e) for e in evs]
    if json_mode:
        print(json.dumps({"initialized": True, "events": rows},
                         ensure_ascii=False, indent=2))
        return 0
    _print_events(rows, "审计查询结果", show_payload=True)
    return 0


# ---------------------------------------------------------------- 入口

def cmd_auditstore(args: Any) -> int:
    """内核全量审计事件归档只读查询 (第 107 个独特功能, 纯只读)。"""
    try:
        home = _get_home(getattr(args, "home", None))
        store = _open_store(home)
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]审计归档读取失败: {exc}[/red]")
        return 1

    sub = getattr(args, "auditstore_cmd", None) or "stats"
    if sub == "stats":
        return _cmd_stats(args, store)
    elif sub == "recent":
        return _cmd_recent(args, store)
    elif sub == "query":
        return _cmd_query(args, store)
    else:
        console.print(f"[red]未知子命令: {sub}[/red]")
        console.print("可用: stats / recent / query")
        return 1


_register_command("cmd_auditstore", ".cmd_auditstore")
