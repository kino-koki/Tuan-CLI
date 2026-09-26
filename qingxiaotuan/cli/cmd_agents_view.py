"""Agent View —— 多会话管理面板 (对标 Claude Code claude agents)。

一屏展示所有会话状态 (rich 表格):
- 列: Session ID(短) / 类型(interactive|background) / 状态(running|waiting|done|failed)
      / 最后消息摘要(截断 40 字) / 创建时间 / 运行时长
- `--watch` 模式: 每 2 秒刷新一次 (类 top);
- `qxt agents kill <id>`: 终止后台会话 (写 job.cancel 事件 + 标记后台任务取消)。

兼容: 原有 `qxt agents list` / `qxt agents attach` 行为保持不变。
"""

from __future__ import annotations

import datetime
import json
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from rich.table import Table

from ..config import home_dir
from ..memory.sessions import SessionStore
from ._ui_singleton import ui, console


# ------------------------------------------------------------ 会话状态采集

def _get_session_status(path: Path) -> str:
    """判断会话状态: running / waiting / executing / done / failed / cancelled / unknown。"""
    meta = SessionStore.read_meta(path)
    if meta:
        kind = meta.get("kind", "")
        if kind == "background" or meta.get("task"):
            # 后台任务: 检查是否有最终状态
            try:
                with open(path, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                    for line in reversed(lines[-50:]):
                        try:
                            rec = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if rec.get("type") == "job.done":
                            return "done"
                        if rec.get("type") == "job.error":
                            return "failed"
                        if rec.get("type") == "job.cancel":
                            return "cancelled"
                return "running"  # 后台任务没有结束标记 = 仍在跑
            except OSError:
                return "unknown"

    # 交互式会话: 检查最后一条消息的类型
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()
            if not lines:
                return "empty"
            last_rec = json.loads(lines[-1])
            last_type = last_rec.get("type", "")
            if last_type == "assistant":
                return "done"
            if last_type == "user":
                return "waiting"
            if last_type in ("tool_call", "tool"):
                return "executing"
            if last_type == "job.cancel":
                return "cancelled"
    except (OSError, json.JSONDecodeError):
        pass
    return "unknown"


def _session_kind(path: Path) -> str:
    """会话类型: background / interactive。"""
    meta = SessionStore.read_meta(path)
    if meta:
        if meta.get("kind") == "background" or meta.get("task"):
            return "background"
        if meta.get("kind"):
            return str(meta["kind"])
    return "interactive"


def _created_at(path: Path) -> float:
    """会话创建时间: 优先 session.meta.started_at, 否则取文件 ctime。"""
    meta = SessionStore.read_meta(path)
    if meta and meta.get("started_at"):
        try:
            return float(meta["started_at"])
        except (TypeError, ValueError):
            pass
    try:
        return path.stat().st_ctime
    except OSError:
        return path.stat().st_mtime


def _last_summary(path: Path, max_chars: int = 40) -> str:
    """最后消息摘要 (截断 max_chars 字)。"""
    title = SessionStore.peek_title(path)
    if title:
        return title[:max_chars]
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        for line in reversed(lines[-20:]):
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("type") == "user":
                content = str(rec.get("message", {}).get("content", ""))
                if content:
                    return content.replace("\n", " ")[:max_chars]
            if rec.get("type") == "assistant":
                content = str(rec.get("message", {}).get("content", ""))
                if content:
                    return content.replace("\n", " ")[:max_chars]
    except OSError:
        pass
    return "(无摘要)"


def collect_sessions(sessions_dir: Path, limit: int = 100) -> List[Dict[str, Any]]:
    """采集全部会话行数据 (纯函数, 便于测试)。"""
    if not sessions_dir.exists():
        return []
    files = sorted(sessions_dir.glob("*.jsonl"),
                   key=lambda f: f.stat().st_mtime, reverse=True)[:limit]
    rows: List[Dict[str, Any]] = []
    now = time.time()
    for f in files:
        try:
            mtime = f.stat().st_mtime
            ctime = _created_at(f)
        except OSError:
            continue
        rows.append({
            "sid": f.stem,
            "short_id": f.stem[:12],
            "kind": _session_kind(f),
            "status": _get_session_status(f),
            "summary": _last_summary(f, 40),
            "created_at": ctime,
            "elapsed": now - ctime,
            "mtime": mtime,
            "path": f,
        })
    return rows


def _fmt_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{int(seconds)}s"
    if seconds < 3600:
        return f"{int(seconds // 60)}m"
    if seconds < 86400:
        return f"{int(seconds // 3600)}h"
    return f"{int(seconds // 86400)}d"


def render_table(rows: List[Dict[str, Any]]) -> Table:
    """把会话行渲染成 rich Table (纯渲染, 不打印)。"""
    table = Table(title="Agent View —— 会话面板", show_lines=False, expand=True)
    table.add_column("Session", style="cyan", no_wrap=True)
    table.add_column("类型", style="magenta")
    table.add_column("状态", style="green")
    table.add_column("最后消息", style="white", overflow="ellipsis", max_width=40)
    table.add_column("创建时间", style="dim")
    table.add_column("时长", style="yellow")
    status_style = {
        "running": "bold green", "executing": "bold green",
        "waiting": "yellow", "done": "dim",
        "failed": "bold red", "cancelled": "red",
        "unknown": "dim", "empty": "dim",
    }
    for r in rows:
        created = time.strftime("%m-%d %H:%M", time.localtime(r["created_at"]))
        table.add_row(
            r["short_id"],
            r["kind"],
            f"[{status_style.get(r['status'], 'white')}]{r['status']}[/]",
            r["summary"],
            created,
            _fmt_duration(r["elapsed"]),
        )
    return table


# ------------------------------------------------------------ watch 模式

def watch_loop(
    sessions_dir: Path,
    interval: float = 2.0,
    max_iterations: Optional[int] = None,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """top 风格刷新循环。max_iterations 仅供测试 (None = 无限, Ctrl-C 退出)。"""
    iteration = 0
    while True:
        console.clear()
        rows = collect_sessions(sessions_dir)
        console.print(f"Agent View (每 {interval:.0f}s 刷新 · 共 {len(rows)} 个会话 · Ctrl-C 退出)")
        if rows:
            console.print(render_table(rows))
        else:
            console.print("(没有会话记录)")
        iteration += 1
        if max_iterations is not None and iteration >= max_iterations:
            return
        try:
            sleep(interval)
        except KeyboardInterrupt:
            return


# ------------------------------------------------------------ kill

def kill_session(sessions_dir: Path, sid_prefix: str) -> Dict[str, Any]:
    """终止一个后台会话。返回结果 dict (纯函数, 便于测试)。

    做法: 按 id 前缀定位 jsonl, 追加一条 ``job.cancel`` 事件 (状态机即变为 cancelled);
    若该会话在 BackgroundStore 中有记录, 一并标记 cancelled。
    """
    sid_prefix = (sid_prefix or "").strip()
    if not sid_prefix:
        return {"ok": False, "error": "请提供会话 ID"}
    matches = sorted(sessions_dir.glob(f"{sid_prefix}*.jsonl"))
    if not matches:
        return {"ok": False, "error": f"未找到会话: {sid_prefix}"}
    path = matches[0]
    # 追加取消事件
    record = {"ts": time.time(), "type": "job.cancel", "by": "agents_kill"}
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    # 同步 BackgroundStore (best-effort, 找不到就算了)
    job_marked = False
    try:
        from ..core.background_store import BackgroundStore
        store = BackgroundStore(home_dir())
        try:
            store.update(path.stem, status="cancelled")
            job_marked = True
        except Exception:  # noqa: BLE001
            # 可能是交互式会话, 不在后台任务表里 —— 正常
            job_marked = False
    except Exception:  # noqa: BLE001
        pass
    return {
        "ok": True,
        "session_id": path.stem,
        "file": str(path),
        "job_store_updated": job_marked,
    }


# ------------------------------------------------------------ 命令入口

def cmd_agents_view(args) -> int:
    """Agent View 面板: rich 表格一屏展示所有会话状态。"""
    sessions_dir = home_dir() / "sessions"
    watch = bool(getattr(args, "watch", False))
    if watch:
        watch_loop(sessions_dir, interval=2.0)
        return 0

    rows = collect_sessions(sessions_dir)
    if not rows:
        console.print("没有会话记录")
        return 0
    console.print(render_table(rows))
    console.print("")
    console.print("用法:")
    console.print("  qxt agents view --watch     实时刷新 (类 top)")
    console.print("  qxt agents kill <id>        终止后台会话")
    console.print("  qxt session resume <id>     恢复会话")
    return 0


def cmd_agents_kill(args) -> int:
    """qxt agents kill <id> —— 终止后台会话。"""
    sessions_dir = home_dir() / "sessions"
    result = kill_session(sessions_dir, getattr(args, "session_id", ""))
    if not result.get("ok"):
        ui.error(result.get("error", "终止失败"))
        return 1
    ui.success(f"已终止会话: {result['session_id']}"
               + (" (后台任务表已同步)" if result.get("job_store_updated") else ""))
    return 0


def cmd_agents(args) -> int:
    """Agent 命令入口: view / list / kill / attach。"""
    sub = getattr(args, "agents_cmd", None)

    if sub is None or sub == "view":
        return cmd_agents_view(args)

    if sub == "list":
        sessions_dir = home_dir() / "sessions"
        rows = collect_sessions(sessions_dir, limit=20)
        if not rows:
            console.print("没有会话记录")
            return 0
        for i, r in enumerate(rows, 1):
            console.print(f"{i:2d}. [{r['status']:^10s}] {r['summary'][:50]:<50s} "
                          f"{_fmt_duration(r['elapsed']):>6s}")
        return 0

    if sub == "kill":
        return cmd_agents_kill(args)

    if sub == "attach":
        # attach 复用 session resume
        sid = getattr(args, "session_id", "") or ""
        if not sid:
            ui.error("用法: qxt agents attach <session_id>")
            return 1
        ui.info(f"请使用 `qxt session resume {sid}` 恢复并进入会话 {sid}")
        return 0

    console.print(f"未知子命令: {sub}")
    console.print("可用: view / list / kill / attach")
    return 1
