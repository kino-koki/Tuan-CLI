"""collab 命令 —— 多 Agent 协作协议黑板 (第 51 个独特功能)。

暴露 :mod:`tuan_cli.core.collaboration_protocol` 的 CollaborationProtocol:
升级版共享黑板, 支持结构化消息、定向路由、依赖声明、CAS 冲突检测、
版本控制、订阅通知与审计追溯。

差异化价值: Claude Code 无对应能力。这是多 Agent 协作的"通信中枢",
让用户能编排多个角色的 Agent 围绕共享黑板交换结果、声明依赖、
检测/解决冲突, 并对每次写入做审计追溯。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from ._ui_singleton import console
from .parser import _register_command


# ------------------------------------------------------------------ 内存协议实例 (跨进程持久化)

_BOARD_PATH: Optional[Path] = None


def _board_path() -> Path:
    """黑板持久化路径: ~/.tuan/collab/board.json (跨进程可见)。"""
    global _BOARD_PATH
    if _BOARD_PATH is None:
        from ..config import home_dir

        _BOARD_PATH = Path(home_dir()) / "collab" / "board.json"
    return _BOARD_PATH


def _get_protocol() -> Any:
    """获取 CollaborationProtocol, 从磁盘恢复 (跨进程共享黑板)。

    CLI 每次调用是独立进程, 黑板必须持久化才能跨命令共享。
    """
    from ..core.collaboration_protocol import CollaborationProtocol

    proto = CollaborationProtocol()
    path = _board_path()
    if path.exists():
        try:
            with path.open("r", encoding="utf-8") as fh:
                proto.load_state(json.load(fh))
        except (OSError, ValueError):
            pass  # 损坏的板子忽略, 从空黑板开始
    return proto


def _save_protocol(proto: Any) -> None:
    """把黑板状态落盘 (原子写)。"""
    path = _board_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(proto.to_state(), ensure_ascii=False),
                       encoding="utf-8")
        tmp.replace(path)
    except OSError as exc:
        console.print(f"[yellow]黑板落盘失败: {exc}[/yellow]")


# ------------------------------------------------------------------ 消息/冲突渲染

def _msg_brief(m: Any) -> Dict[str, Any]:
    return {
        "msg_id": m.msg_id,
        "msg_type": getattr(m.msg_type, "value", str(m.msg_type)),
        "sender": m.sender,
        "recipient": m.recipient,
        "key": m.key,
        "value": str(m.value)[:200],
        "priority": getattr(m.priority, "value", str(m.priority)),
        "depends_on": m.depends_on,
        "version": m.version,
        "timestamp": m.timestamp,
    }


def _print_msg(m: Any) -> None:
    msg_type = getattr(m.msg_type, "value", str(m.msg_type))
    priority = getattr(m.priority, "value", str(m.priority))
    color = {"error": "red", "conflict": "yellow", "feedback": "cyan",
             "status": "green"}.get(msg_type, "white")
    prio_tag = {"high": "[yellow]高[/yellow]", "urgent": "[red]急[/red]",
                "low": "[dim]低[/dim]", "normal": ""}.get(priority, "")
    console.print(
        f"  [bold]{m.msg_id}[/bold] [{color}]{msg_type}[/{color}] "
        f"[dim]{m.sender} → {m.recipient}[/dim] {m.key} {prio_tag}"
    )
    if m.depends_on:
        console.print(f"      [dim]依赖: {', '.join(m.depends_on)}[/dim]")
    val = str(m.value)[:200]
    if val:
        console.print(f"      [dim]{val}[/dim]")


def _print_conflict(c: Any) -> None:
    status = "[green]✓ 已解决[/green]" if c.resolved else "[yellow]⚠ 未解决[/yellow]"
    console.print(
        f"  [bold]{c.key}[/bold] {status}  "
        f"[dim]{c.sender_a} vs {c.sender_b}[/dim]"
    )
    if c.resolved:
        console.print(f"      [dim]→ {c.resolver}: {str(c.resolved_value)[:80]}[/dim]")


# ------------------------------------------------------------------ 子命令: 写黑板

def _cmd_collab_write(args: Any, json_mode: bool) -> int:
    proto = _get_protocol()
    try:
        from ..core.collaboration_protocol import MessageType, MessagePriority

        msg_type = MessageType(args.msg_type or "result")
        priority = MessagePriority(args.priority or "normal")
    except ValueError as exc:
        console.print(f"[red]消息类型/优先级非法: {exc}[/red]")
        return 1
    deps = [d.strip() for d in (args.depends_on or "").split(",") if d.strip()]
    msg = proto.write(
        key=args.key,
        value=args.value,
        sender=args.sender or "cli",
        msg_type=msg_type,
        priority=priority,
        depends_on=deps or None,
    )
    _save_protocol(proto)
    if json_mode:
        print(json.dumps(_msg_brief(msg), ensure_ascii=False, indent=2))
        return 0
    console.print(f"[green]✓ 已写入[/green] {msg.key} (v{msg.version})")
    console.print(f"  [dim]{msg.sender} → {msg.recipient}[/dim] "
                  f"[{getattr(msg.msg_type, 'value', msg.msg_type)}]")
    return 0


# ------------------------------------------------------------------ 子命令: 读黑板

def _cmd_collab_read(args: Any, json_mode: bool) -> int:
    proto = _get_protocol()
    value = proto.read(args.key, requester=args.requester or "cli")
    if json_mode:
        print(json.dumps({
            "key": args.key,
            "version": proto.read_version(args.key),
            "value": value,
        }, ensure_ascii=False, indent=2))
        return 0
    if value is None:
        console.print(f"[dim]{args.key} 尚无值 (用 collab write 写入)[/dim]")
        return 0
    console.print(f"[bold]{args.key}[/bold] (v{proto.read_version(args.key)})")
    console.print(str(value)[:2000])
    return 0


# ------------------------------------------------------------------ 子命令: CAS 写入

def _cmd_collab_cas(args: Any, json_mode: bool) -> int:
    proto = _get_protocol()
    ok = proto.compare_and_swap(
        args.key, int(args.version), args.value, sender=args.sender or "cli"
    )
    if ok:
        _save_protocol(proto)
    if json_mode:
        print(json.dumps({
            "ok": ok,
            "key": args.key,
            "expected_version": int(args.version),
            "current_version": proto.read_version(args.key),
            "value": args.value,
        }, ensure_ascii=False, indent=2))
        return 0
    if ok:
        console.print(f"[green]✓ CAS 成功[/green] {args.key} → v{proto.read_version(args.key)}")
    else:
        console.print(
            f"[yellow]✗ CAS 失败[/yellow] {args.key} 当前 v{proto.read_version(args.key)} "
            f"(期望 v{int(args.version)})"
        )
    return 0


# ------------------------------------------------------------------ 子命令: 冲突

def _cmd_collab_conflicts(args: Any, json_mode: bool) -> int:
    proto = _get_protocol()
    if getattr(args, "resolve", False):
        if not proto.resolve_conflict(int(args.idx), args.value, resolver=args.resolver or "cli"):
            console.print(f"[red]冲突索引非法: {args.idx}[/red]")
            return 1
        _save_protocol(proto)
        if json_mode:
            print(json.dumps({"resolved": True, "idx": int(args.idx),
                              "value": args.value}, ensure_ascii=False, indent=2))
            return 0
        console.print(f"[green]✓ 已解决冲突 #{args.idx}[/green]")
        return 0
    if getattr(args, "auto", False):
        n = proto.auto_resolve_conflicts(strategy=args.strategy or "last_write")
        if n > 0:
            _save_protocol(proto)
        if json_mode:
            print(json.dumps({"auto_resolved": n, "strategy": args.strategy},
                             ensure_ascii=False, indent=2))
            return 0
        console.print(f"[green]✓ 自动解决 {n} 个冲突[/green] (策略: {args.strategy})")
        return 0
    conflicts = proto.get_unresolved_conflicts()
    if json_mode:
        print(json.dumps({
            "unresolved": len(conflicts),
            "conflicts": [{
                "key": c.key, "sender_a": c.sender_a, "sender_b": c.sender_b,
                "resolved": c.resolved,
            } for c in conflicts],
        }, ensure_ascii=False, indent=2))
        return 0
    if not conflicts:
        console.print("[dim]无未解决冲突[/dim]")
        return 0
    console.print(f"[bold]未解决冲突[/bold] ({len(conflicts)} 个)")
    for c in conflicts:
        _print_conflict(c)
    console.print("\n[dim]解决: tuan collab conflicts --resolve <idx> --value <v>[/dim]")
    return 0


# ------------------------------------------------------------------ 子命令: 消息/统计

def _cmd_collab_messages(args: Any, json_mode: bool) -> int:
    proto = _get_protocol()
    sender = args.sender or None
    msg_type = args.msg_type or None
    msgs = proto.get_messages(
        sender=sender,
        msg_type=msg_type,
        limit=int(getattr(args, "limit", 20) or 20),
    )
    if json_mode:
        print(json.dumps({"count": len(msgs),
                          "messages": [_msg_brief(m) for m in msgs]},
                         ensure_ascii=False, indent=2))
        return 0
    if not msgs:
        console.print("[dim]无消息 (用 collab write 产生)[/dim]")
        return 0
    console.print(f"[bold]协作消息[/bold] ({len(msgs)} 条)")
    for m in msgs:
        _print_msg(m)
    return 0


def _cmd_collab_stats(args: Any, json_mode: bool) -> int:
    proto = _get_protocol()
    stats = proto.stats()
    if json_mode:
        print(json.dumps(stats, ensure_ascii=False, indent=2))
        return 0
    console.print("[bold]协作黑板统计[/bold]")
    console.print(f"  key 数: {stats['keys']}")
    console.print(f"  消息: {stats['messages']}")
    console.print(f"  冲突(总/未解决): {stats['conflicts_total']}/{stats['conflicts_unresolved']}")
    console.print(f"  订阅者: {stats['subscribers']}")
    return 0


# ------------------------------------------------------------------ 子命令: 清空

def _cmd_collab_clear(args: Any, json_mode: bool) -> int:
    proto = _get_protocol()
    proto.clear()
    _save_protocol(proto)
    if json_mode:
        print(json.dumps({"cleared": True}, ensure_ascii=False, indent=2))
        return 0
    console.print("[green]✓ 黑板已清空[/green]")
    return 0


# ------------------------------------------------------------------ 子命令: 演示

def _cmd_collab_demo(args: Any, json_mode: bool) -> int:
    """内置协作演示: 三个角色围绕黑板交换结果 + 制造一次冲突。"""
    proto = _get_protocol()
    proto.clear()
    from ..core.collaboration_protocol import MessageType, MessagePriority
    # Agent A (planner) 写计划
    proto.write("plan:overall", "先做架构设计, 再实现核心模块", sender="planner",
                msg_type=MessageType.ARTIFACT, priority=MessagePriority.HIGH)
    # Agent B (worker) 写实现
    proto.write("impl:T1", "实现了 Task 1 核心逻辑", sender="worker",
                msg_type=MessageType.RESULT, depends_on=["plan:overall"])
    # Agent C (reviewer) 反馈
    proto.write("review:T1", "实现符合预期, 建议补充边界测试", sender="reviewer",
                msg_type=MessageType.FEEDBACK, depends_on=["impl:T1"])
    # 制造冲突: 两个 Agent 对同一 key 写不同值
    proto.write("impl:T2", "方案 A: 快速实现", sender="worker")
    proto.write("impl:T2", "方案 B: 可扩展实现", sender="architect")
    _save_protocol(proto)

    stats = proto.stats()
    if json_mode:
        print(json.dumps({
            "demo": True,
            "stats": stats,
            "conflicts": [{
                "key": c.key, "sender_a": c.sender_a, "sender_b": c.sender_b,
            } for c in proto.get_unresolved_conflicts()],
        }, ensure_ascii=False, indent=2))
        return 0
    console.print("[bold]协作演示 · 三角色黑板[/bold]")
    console.print("  [cyan]planner[/cyan] → 计划")
    console.print("  [green]worker[/green] → 实现 (T1/T2)")
    console.print("  [magenta]reviewer[/magenta] → 反馈")
    console.print("  [yellow]architect[/yellow] → 与 worker 对 T2 写冲突")
    console.print(f"\n[dim]stats: {stats}[/dim]")
    console.print("[dim]查看: tuan collab conflicts / tuan collab messages[/dim]")
    return 0


# ------------------------------------------------------------------ 子命令: 黑板全量快照

def _cmd_collab_snapshot(args: Any, json_mode: bool) -> int:
    """黑板全量快照 (第 61 个独特功能: 多 Agent 黑板全量可读快照)。

    暴露 ``get_all()`` (全部 key/value) 与 ``context_block()`` (带冲突标注的
    可读快照文本)。read 只读单个 key; snapshot 一次取回整个黑板, 供
    编排者/审查者看到协作全貌 —— Claude Code 无跨 Agent 黑板, 更无全量快照。

      tuan collab snapshot            # 可读快照文本 (含冲突标注)
      tuan collab snapshot --raw      # 原始全量 dict (JSON)
      tuan collab snapshot --context  # 只输出 Agent 可消费的 context_block
    """
    proto = _get_protocol()
    all_data = proto.get_all()

    if bool(getattr(args, "context", False)):
        block = proto.context_block(requester="cli")
        print(block)
        return 0

    if bool(getattr(args, "raw", False)):
        print(json.dumps(all_data, ensure_ascii=False, indent=2))
        return 0

    if json_mode:
        print(json.dumps({
            "keys": list(all_data.keys()),
            "count": len(all_data),
            "data": {k: str(v)[:2000] for k, v in all_data.items()},
            "versions": {k: proto.read_version(k) for k in all_data},
        }, ensure_ascii=False, indent=2))
        return 0

    if not all_data:
        console.print("[dim]黑板为空 (用 collab write / collab demo 填充)[/dim]")
        return 0
    console.print(f"[bold]黑板全量快照[/bold] ({len(all_data)} 个 key)")
    for k, v in all_data.items():
        console.print(f"\n  [cyan]{k}[/cyan] (v{proto.read_version(k)})")
        console.print(f"    [dim]{str(v)[:2000]}[/dim]")
    unresolved = proto.get_unresolved_conflicts()
    if unresolved:
        console.print(f"\n  [yellow]⚠ {len(unresolved)} 个未解决冲突[/yellow]")
        for c in unresolved:
            console.print(f"    [dim]{c.key}: {c.sender_a} vs {c.sender_b}[/dim]")
    console.print("\n[dim]提示: --raw 原始 dict; --context 输出 Agent 可消费快照文本[/dim]")
    return 0


# ------------------------------------------------------------------ 分发

def cmd_collab(args: Any) -> int:
    """collab 主入口: 分发到子命令。"""
    sub = getattr(args, "collab_cmd", None) or "stats"
    json_mode = bool(getattr(args, "json", False))
    if sub == "write":
        return _cmd_collab_write(args, json_mode)
    if sub == "read":
        return _cmd_collab_read(args, json_mode)
    if sub == "cas":
        return _cmd_collab_cas(args, json_mode)
    if sub == "conflicts":
        return _cmd_collab_conflicts(args, json_mode)
    if sub == "messages":
        return _cmd_collab_messages(args, json_mode)
    if sub == "stats":
        return _cmd_collab_stats(args, json_mode)
    if sub == "clear":
        return _cmd_collab_clear(args, json_mode)
    if sub == "demo":
        return _cmd_collab_demo(args, json_mode)
    if sub == "snapshot":
        return _cmd_collab_snapshot(args, json_mode)
    console.print(f"[red]未知 collab 子命令: {sub}[/red]")
    return 1


_register_command("cmd_collab", ".cmd_collab")
