"""msg 命令 —— 跨会话消息总线可观测性 (第 92 个独特功能)。

暴露 :mod:`tuan_cli.core.message_bus` 的文件级消息总线:
- **活跃会话/代理**: 从 <home>/messages/sessions/*.json 心跳注册表扫描
  存活会话 (心跳 2 分钟内), 含 pid/uptime/元信息 (模型/工作区);
- **收件箱**: 某会话的未读/待处理消息 (TTL 5 分钟内, 默认标记已读),
  消息内容/来源/时间戳;
- **主动发送**: 向某会话 inbox 写入一条测试消息 (验证消息通道);
- **清理**: 移除死会话与过期消息的注册文件。

差异化价值: Claude Code 的 SendMessage/ListAgents 只在会话内黑箱可用,
用户无法从命令行独立查询"有哪些活跃会话/代理、各自 uptime/元信息"
或"某会话的未读消息"。本命令把文件级消息总线开放为可查询 (纯只读),
并支持主动发送测试消息验证通道。

  tuan msg agents [--json]                # 活跃会话/代理清单
  tuan msg inbox <sid> [--keep] [--json]  # 读取某会话未读消息 (默认标记已读)
  tuan msg send <from> <to> <内容>        # 主动发送测试消息
  tuan msg cleanup [--json]               # 清理死会话/过期消息
"""

from __future__ import annotations

import datetime
import json
from typing import Any, Dict, List

from ._ui_singleton import console
from .parser import _register_command


def _get_bus() -> Any:
    from ..core.message_bus import MessageBus
    from ..config.loader import home_dir

    return MessageBus(home_dir())


def cmd_msg(args: Any) -> int:
    """msg 主入口: 跨会话消息总线可观测 (纯只读查询 + 主动发送)。"""
    sub = getattr(args, "msg_cmd", None) or "agents"
    json_mode = bool(getattr(args, "json", False))

    # archive: 纯只读巡查弃用归档, 不构造 MessageBus (其 __init__ 会 mkdir)
    if sub == "archive":
        return _cmd_msg_archive(args, json_mode)

    bus = _get_bus()

    if sub == "agents":
        agents: List[Dict[str, Any]] = bus.list_agents()
        if json_mode:
            print(json.dumps({
                "count": len(agents),
                "agents": agents,
            }, ensure_ascii=False, indent=2))
            return 0
        if not agents:
            console.print("[green]✓ 无活跃会话[/green] "
                          "([dim]<home>/messages/sessions/[/dim])")
            return 0
        console.print(f"[bold]活跃会话/代理 ({len(agents)} 个)[/bold]\n")
        for a in agents:
            meta = a.get("meta", {})
            model = meta.get("model", "") if isinstance(meta, dict) else ""
            ws = meta.get("workspace", "") if isinstance(meta, dict) else ""
            uptime_s = a.get("uptime", 0)
            uptime = f"{uptime_s // 60}m{uptime_s % 60}s" if uptime_s < 3600 \
                else f"{uptime_s // 3600}h"
            console.print(f"  [yellow]{a.get('session_id', '')[:14]}[/yellow]  "
                          f"[cyan]pid={a.get('pid')}[/cyan]  "
                          f"[dim]uptime={uptime}[/dim]")
            if model:
                console.print(f"      [dim]模型: {model}[/dim]")
            if ws:
                console.print(f"      [dim]工作区: {ws}[/dim]")
        console.print("\n[dim]详情: tuan msg inbox <sid> · 发送: tuan msg send <from> <to> <内容>[/dim]")
        return 0

    if sub == "inbox":
        sid = str(getattr(args, "session", "") or "").strip()
        if not sid:
            console.print("[red]缺少会话 ID[/red] (用法: tuan msg inbox <sid>)")
            return 1
        keep = bool(getattr(args, "keep", False))
        msgs = bus.receive(sid, mark_read=not keep)
        if json_mode:
            print(json.dumps({
                "session_id": sid,
                "count": len(msgs),
                "messages": [{
                    "id": m.id,
                    "from": m.from_session,
                    "content": m.content,
                    "ts": m.ts,
                    "read": m.read,
                } for m in msgs],
            }, ensure_ascii=False, indent=2))
            return 0
        if not msgs:
            console.print(f"[green]✓ 会话 {sid} 无未读消息[/green]")
            return 0
        console.print(f"[bold]会话 {sid} 收件箱 ({len(msgs)} 条未读)[/bold]\n")
        for m in msgs:
            console.print(f"  [dim]@{m.id}[/dim] [cyan]{m.from_session or '(外部)'}[/cyan] → {sid}")
            console.print(f"      {m.content[:80]}")
        if not keep:
            console.print("\n[dim]已标记已读 (用 --keep 保留)[/dim]")
        return 0

    if sub == "send":
        from_sid = str(getattr(args, "from_sid", "") or "").strip()
        to_sid = str(getattr(args, "to_sid", "") or "").strip()
        content = str(getattr(args, "content", "") or "").strip()
        if not from_sid or not to_sid or not content:
            console.print("[red]用法: tuan msg send <from> <to> <内容>[/red]")
            return 1
        msg_id = bus.send(from_sid, to_sid, content)
        if json_mode:
            print(json.dumps({
                "sent": bool(msg_id), "id": msg_id,
                "from": from_sid, "to": to_sid,
            }, ensure_ascii=False, indent=2))
            return 0
        if msg_id:
            console.print(f"[green]✓ 已发送 {from_sid} → {to_sid} (id={msg_id})[/green]")
        else:
            console.print(f"[yellow]发送失败: {from_sid} → {to_sid}[/yellow]")
        return 0

    if sub == "cleanup":
        cleaned = bus.cleanup()
        if json_mode:
            print(json.dumps({"cleaned_sessions": cleaned},
                             ensure_ascii=False, indent=2))
            return 0
        console.print(f"[green]✓ 已清理 {cleaned} 个死会话[/green]")
        return 0

    console.print(f"[red]未知 msg 子命令: {sub}[/red]")
    return 1


def _cmd_msg_archive(args: Any, json_mode: bool) -> int:
    """只读巡查弃用跨会话消息归档 (第 124 个独特功能)。

    core/messaging.py 已被 core.message_bus 取代 (弃用), 但其持久化的
    <home>/messaging/ 归档 —— ``_registry.json`` (会话注册表) 与
    ``<sid>.jsonl`` (每会话消息队列) —— 仍留在磁盘上, 且**只写不读**:
    生产代码已无任何读取方 (只有弃用模块自身与向后兼容测试引用),
    没有任何命令能列出"历史上曾注册过哪些会话、各自排了多少条遗留
    消息、是否已读"。对比 Claude Code: 它的跨会话消息无"历史归档"
    概念, 弃用遗留数据用户无从察觉。本命令补上只读面 (纯只读:
    glob + json.load, 不构造弃用 MessageBus —— 其 __init__ 会 mkdir)。
    """
    from pathlib import Path

    from ..config.loader import home_dir

    archive_dir = Path(home_dir()) / "messaging"

    if not archive_dir.is_dir():
        if json_mode:
            print(json.dumps({"archive_dir": str(archive_dir),
                              "initialized": False, "registry": {},
                              "queues": [], "count": 0},
                             ensure_ascii=False, indent=2))
            return 0
        console.print(f"[dim]消息归档未初始化: {archive_dir}[/dim]")
        return 0

    # --- 会话注册表 (_registry.json) ---
    registry: Dict[str, Any] = {}
    reg_malformed = 0
    reg_path = archive_dir / "_registry.json"
    if reg_path.is_file():
        try:
            data = json.loads(reg_path.read_text(encoding="utf-8-sig"))
            if isinstance(data, dict):
                registry = data
            else:
                reg_malformed += 1
        except (OSError, json.JSONDecodeError):
            reg_malformed += 1

    # --- 消息队列 (<sid>.jsonl) ---
    queues: List[Dict[str, Any]] = []
    q_malformed = 0
    for p in sorted(archive_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime,
                    reverse=True):
        sid = p.stem
        msgs: List[Dict[str, Any]] = []
        bad = 0
        try:
            for line in p.open("r", encoding="utf-8-sig"):
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    bad += 1
                    continue
                if not isinstance(rec, dict):
                    bad += 1
                    continue
                msgs.append(rec)
        except OSError:
            q_malformed += 1
            continue
        read_n = sum(1 for m in msgs if m.get("read"))
        queues.append({
            "session_id": sid,
            "total": len(msgs),
            "unread": len(msgs) - read_n,
            "bad_lines": bad,
            "mtime": p.stat().st_mtime,
            "messages": msgs,
        })

    limit = int(getattr(args, "limit", 0) or 0)
    shown_queues = queues[:limit] if limit and len(queues) > limit else queues

    if json_mode:
        print(json.dumps({
            "archive_dir": str(archive_dir),
            "initialized": True,
            "registry": registry,
            "registry_malformed": reg_malformed,
            "queue_count": len(queues),
            "queue_malformed": q_malformed,
            "total_messages": sum(q["total"] for q in queues),
            "queues": shown_queues,
        }, ensure_ascii=False, indent=2))
        return 0

    console.print(f"[bold]消息归档 · {archive_dir}[/bold]\n")
    console.print(f"  注册会话: {len(registry)} 个  "
                  f"(注册表坏文件 {reg_malformed})")
    console.print(f"  消息队列: {len(queues)} 个  "
                  f"(坏队列 {q_malformed}) · "
                  f"共 {sum(q['total'] for q in queues)} 条遗留消息\n")
    if not registry and not queues:
        console.print("  [dim](空)[/dim]")
        return 0

    if registry:
        console.print("  注册会话:")
        for sid, info in registry.items():
            name = info.get("name") or info.get("session_name") or ""
            ws = info.get("working_dir") or ""
            last = info.get("last_active") or info.get("last_active") or 0
            try:
                tstr = datetime.datetime.fromtimestamp(float(last)).strftime("%Y-%m-%d %H:%M:%S")
            except (TypeError, ValueError, OSError):
                tstr = "-"
            console.print(f"    [yellow]{sid}[/yellow]  {name}  "
                          f"[dim]最后活跃 {tstr}[/dim]"
                          + (f"  ws={ws}" if ws else ""))
        console.print("")

    if queues:
        console.print("  消息队列:")
        for q in shown_queues:
            tstr = _fmt_ts(q["mtime"])
            console.print(f"    [yellow]{q['session_id']}[/yellow]  "
                          f"{q['total']} 条 (未读 {q['unread']})  "
                          f"[dim]{tstr}[/dim]"
                          + (f"  [red]{q['bad_lines']} 坏行[/red]" if q["bad_lines"] else ""))
    return 0


def _fmt_ts(ts: float) -> str:
    try:
        return datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError, OSError):
        return "-"


_register_command("cmd_msg", ".cmd_msg")
