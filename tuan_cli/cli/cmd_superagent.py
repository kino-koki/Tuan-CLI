"""superagent 命令 —— Super-Agent 持久化状态只读审计 (第 102 个独特功能)。

把 DeepSeek 双层架构 Super-Agent 的**落盘状态** (state.json + outbox.json,
由 superagent.store.StateStore 管理) 暴露为跨进程只读报表。`/superagent
status` 只读聚合 stats() 与面板, 从不直接展示原始工单/订阅/WAL 队列;
本命令补齐这个缺口 —— 用户可以审计「故障后可恢复的待办工单全貌」、
「订阅映射」、「先记录后执行 (Write-Ahead) 队列积压」与「持久化观察上下文」。

差异化价值: Claude Code 的待办/后台任务各自黑箱, 用户对「跨进程重启后
哪些工单未完成、哪些订阅仍挂着、WAL 队列积压多少」没有只读入口, 也无法
在不启动引擎的情况下审计持久状态。本命令只读 StateStore 的只读方法,
不触发任何 save/enqueue/dequeue/register 等写操作, 也不启动引擎。

纯只读: 未初始化 (无 state.json) 时不构造 StateStore, 避免其 __init__ 的
目录创建副作用; 只用 all_tickets/get_ticket/pending_tickets/outbox/
subscriptions/load_context/stats。

  tuan superagent [--home H] [--json]                     # 概览: 统计 + 最近工单
  tuan superagent tickets [--status X] [--limit N] [--home H] [--json]
  tuan superagent ticket <ticket_id> [--home H] [--json]
  tuan superagent pending [--home H] [--json]             # 中断/未完成 (可恢复)
  tuan superagent outbox [--home H] [--json]              # WAL 先记录后执行队列
  tuan superagent subscriptions [--home H] [--json]       # 订阅映射
  tuan superagent context [--home H] [--json]             # 持久化观察上下文
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
    """打开 StateStore; 未初始化 (无 state.json) 时返回 None。

    不构造 StateStore 以避免其 __init__ 的目录创建副作用, 保证纯只读。
    """
    if not (home / "superagent" / "state.json").exists():
        return None
    from ..superagent.store import StateStore
    return StateStore(home=home)


def _fmt_ts(ts: float) -> str:
    if not ts:
        return "-"
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))


def _ticket_row(t: Any) -> Dict[str, Any]:
    """把 Ticket 对象转成可 JSON 序列化的行 (纯读取, 无副作用)。"""
    return {
        "ticket_id": getattr(t, "ticket_id", ""),
        "title": (getattr(t, "title", "") or "")[:60],
        "status": getattr(getattr(t, "status", None), "value", "?"),
        "authorization": getattr(t, "authorization", ""),
        "worker_id": getattr(t, "worker_id", ""),
        "created_at": getattr(t, "created_at", 0.0),
        "updated_at": getattr(t, "updated_at", 0.0),
        "progress": (getattr(t, "progress", "") or "")[:120],
        "error": (getattr(t, "error", "") or "")[:80],
    }


def _print_rows(rows: List[Dict[str, Any]], title: str) -> None:
    console.print(f"[bold]{title} ({len(rows)} 项)[/bold]\n")
    if not rows:
        console.print("  [dim](空)[/dim]")
        return
    for r in rows:
        console.print(
            f"  {r.get('ticket_id','?'):<20} "
            f"[{r.get('status','?'):<10}] "
            f"{_fmt_ts(r.get('created_at',0))}  {r.get('title','')}"
        )
        if r.get("error"):
            console.print(f"         [red]err: {r['error']}[/red]")


# ---------------------------------------------------------------- 子命令

def _cmd_overview(args: Any, store: Any) -> int:
    json_mode = bool(getattr(args, "json", False))
    if store is None:
        if json_mode:
            print(json.dumps({"initialized": False, "stats": {}}, ensure_ascii=False, indent=2))
            return 0
        console.print("[dim]Super-Agent 持久状态未初始化 (尚无 state.json; "
                      "启动引擎后自动建立)[/dim]")
        return 0

    stats = store.stats()
    if json_mode:
        print(json.dumps({"initialized": True, "stats": stats},
                         ensure_ascii=False, indent=2))
        return 0

    console.print(f"[bold]=== Super-Agent 持久状态 · {_get_home(getattr(args,'home',None))} ===[/bold]\n")
    console.print(f"  工单 {stats['tickets']} · 线程 {stats['threads']} · "
                  f"订阅 {stats['subscriptions']} · 上下文 {stats['context']} · "
                  f"WAL 队列 {stats['outbox']} · 可恢复 {stats['recoverable']}")

    pend = [t for t in store.all_tickets()
            if getattr(getattr(t, "status", None), "value", "") in
            ("pending", "running", "retrying", "blocked")]
    recent = sorted(pend, key=lambda t: getattr(t, "created_at", 0.0), reverse=True)[:5]
    if recent:
        console.print("\n[bold]未完成工单 (按创建时间取最近 5 个)[/bold]")
        for t in recent:
            console.print(f"  {t.ticket_id:<20} [{t.status.value:<10}] {t.title[:50]}")
    else:
        console.print("\n[dim]无未完成工单[/dim]")
    return 0


def _cmd_tickets(args: Any, store: Any) -> int:
    json_mode = bool(getattr(args, "json", False))
    status_f = getattr(args, "status", None)
    limit = int(getattr(args, "limit", 50) or 50)
    if store is None:
        if json_mode:
            print(json.dumps({"initialized": False, "tickets": []}, ensure_ascii=False, indent=2))
            return 0
        console.print("[dim]Super-Agent 持久状态未初始化[/dim]")
        return 0

    rows = [_ticket_row(t) for t in store.all_tickets()]
    if status_f:
        rows = [r for r in rows if r["status"] == status_f]
    rows = sorted(rows, key=lambda r: r["created_at"], reverse=True)[:limit]

    if json_mode:
        print(json.dumps({"initialized": True, "tickets": rows},
                         ensure_ascii=False, indent=2))
        return 0
    _print_rows(rows, "全部工单" + (f" (status={status_f})" if status_f else ""))
    return 0


def _cmd_ticket(args: Any, store: Any) -> int:
    json_mode = bool(getattr(args, "json", False))
    tid = getattr(args, "ticket_id", "")
    if not tid:
        console.print("[red]用法: tuan superagent ticket <ticket_id>[/red]")
        return 1
    if store is None:
        if json_mode:
            print(json.dumps({"initialized": False, "found": False}, ensure_ascii=False, indent=2))
            return 0
        console.print("[dim]Super-Agent 持久状态未初始化[/dim]")
        return 0

    t = store.get_ticket(tid)
    if t is None:
        if json_mode:
            print(json.dumps({"initialized": True, "found": False, "ticket_id": tid},
                             ensure_ascii=False, indent=2))
            return 0
        console.print(f"[red]工单不存在: {tid}[/red]")
        return 1

    if json_mode:
        print(json.dumps({"initialized": True, "found": True, "ticket": t.to_dict()},
                         ensure_ascii=False, indent=2))
        return 0

    console.print(f"[bold]工单 · {t.ticket_id}[/bold]\n")
    console.print(f"  标题: {t.title}")
    console.print(f"  状态: {t.status.value}  (授权 {t.authorization}, worker {t.worker_id or '-'})")
    console.print(f"  创建: {_fmt_ts(t.created_at)} · 更新: {_fmt_ts(t.updated_at)}")
    if t.started_at:
        console.print(f"  开始: {_fmt_ts(t.started_at)}")
    if t.finished_at:
        console.print(f"  完成: {_fmt_ts(t.finished_at)}")
    if t.progress:
        console.print(f"  进度: {t.progress[:120]}")
    if t.error:
        console.print(f"  [red]错误: {t.error[:120]}[/red]")
    if t.result:
        console.print(f"  结果: {t.result[:80]}")
    if t.workdir:
        console.print(f"  目录: {t.workdir}")
    return 0


def _cmd_pending(args: Any, store: Any) -> int:
    json_mode = bool(getattr(args, "json", False))
    if store is None:
        if json_mode:
            print(json.dumps({"initialized": False, "pending": []}, ensure_ascii=False, indent=2))
            return 0
        console.print("[dim]Super-Agent 持久状态未初始化[/dim]")
        return 0

    rows = [_ticket_row(t) for t in store.pending_tickets()]
    if json_mode:
        print(json.dumps({"initialized": True, "pending": rows},
                         ensure_ascii=False, indent=2))
        return 0
    _print_rows(rows, "中断/未完成工单 (可恢复)")
    return 0


def _cmd_outbox(args: Any, store: Any) -> int:
    json_mode = bool(getattr(args, "json", False))
    if store is None:
        if json_mode:
            print(json.dumps({"initialized": False, "outbox": []}, ensure_ascii=False, indent=2))
            return 0
        console.print("[dim]Super-Agent 持久状态未初始化[/dim]")
        return 0

    items = store.outbox()
    if json_mode:
        print(json.dumps({"initialized": True, "outbox": items},
                         ensure_ascii=False, indent=2))
        return 0
    console.print(f"[bold]WAL 先记录后执行队列 ({len(items)} 项)[/bold]\n")
    if not items:
        console.print("  [dim](空, 无积压)[/dim]")
        return 0
    for o in items:
        op_id = o.get("id", "?")
        op_type = o.get("type", o.get("op", "?"))
        ts = o.get("ts", o.get("created_at", 0.0))
        console.print(f"  {str(op_id)[:20]:<20} {str(op_type)[:20]} {_fmt_ts(float(ts or 0))}")
    return 0


def _cmd_subscriptions(args: Any, store: Any) -> int:
    json_mode = bool(getattr(args, "json", False))
    if store is None:
        if json_mode:
            print(json.dumps({"initialized": False, "subscriptions": {}}, ensure_ascii=False, indent=2))
            return 0
        console.print("[dim]Super-Agent 持久状态未初始化[/dim]")
        return 0

    subs = store.subscriptions()
    if json_mode:
        print(json.dumps({"initialized": True, "subscriptions": subs},
                         ensure_ascii=False, indent=2))
        return 0
    console.print(f"[bold]订阅映射 (thread → worker, {len(subs)} 条)[/bold]\n")
    if not subs:
        console.print("  [dim](空)[/dim]")
        return 0
    for tid, wid in subs.items():
        console.print(f"  {tid:<20} → {wid}")
    return 0


def _cmd_context(args: Any, store: Any) -> int:
    json_mode = bool(getattr(args, "json", False))
    if store is None:
        if json_mode:
            print(json.dumps({"initialized": False, "context": []}, ensure_ascii=False, indent=2))
            return 0
        console.print("[dim]Super-Agent 持久状态未初始化[/dim]")
        return 0

    ctx = store.load_context()
    if json_mode:
        print(json.dumps({"initialized": True, "context": ctx},
                         ensure_ascii=False, indent=2))
        return 0
    console.print(f"[bold]持久化观察上下文 ({len(ctx)} 条)[/bold]\n")
    if not ctx:
        console.print("  [dim](空)[/dim]")
        return 0
    for c in ctx:
        src = c.get("source", c.get("channel", "?"))
        ts = c.get("ts", c.get("created_at", 0.0))
        content = c.get("content", c.get("summary", ""))
        console.print(f"  [{_fmt_ts(float(ts or 0))}] {str(src)[:16]:<16} {str(content)[:70]}")
    return 0


# ---------------------------------------------------------------- 入口

def cmd_superagent(args: Any) -> int:
    """Super-Agent 持久化状态只读审计 (第 102 个独特功能, 纯只读)。"""
    try:
        home = _get_home(getattr(args, "home", None))
        store = _open_store(home)
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]状态读取失败: {exc}[/red]")
        return 1

    sub = getattr(args, "superagent_cmd", None) or "overview"
    if sub == "tickets":
        return _cmd_tickets(args, store)
    elif sub == "ticket":
        return _cmd_ticket(args, store)
    elif sub == "pending":
        return _cmd_pending(args, store)
    elif sub == "outbox":
        return _cmd_outbox(args, store)
    elif sub == "subscriptions":
        return _cmd_subscriptions(args, store)
    elif sub == "context":
        return _cmd_context(args, store)
    elif sub in ("overview", ""):
        return _cmd_overview(args, store)
    else:
        console.print(f"[red]未知子命令: {sub}[/red]")
        console.print("可用: overview / tickets / ticket <id> / pending / outbox / subscriptions / context")
        return 1


_register_command("cmd_superagent", ".cmd_superagent")
