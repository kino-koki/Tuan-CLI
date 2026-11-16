"""remote 命令 —— 远程控制会话可观测性 (第 91 个独特功能)。

暴露 :mod:`tuan_cli.core.remote_control` 的只读状态面 + 主动通知:
- **配对会话清单**: 从 <home>/remote_sessions.json 装载的远程配对会话,
  含连接状态 / 设备 / 推送开关 / 确认标记;
- **会话详情**: 单会话的活跃状态、token 过期、requires_confirmation;
- **主动通知**: 推送一条测试通知 (模拟"模型决策/需确认"事件)。

差异化价值: Claude Code 的 Remote Control 是黑箱, 用户无法从命令行
查询「当前有哪些远程配对会话、各自连接状态如何、是否需用户确认」。
本命令把 RemoteControl 的持久化会话状态开放为可查询 (纯只读),
并支持发送测试通知验证推送通道。

  tuan remote status [--json]            # 全部远程配对会话
  tuan remote status <sid> [--json]      # 单会话详情
  tuan remote notify <标题> [--body B]   # 主动推送测试通知
  tuan remote clear <sid>                # 移除过期/失效会话记录 (只清理盘上残留)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from ._ui_singleton import console
from .parser import _register_command

import logging
log = logging.getLogger(__name__)


def _get_rc() -> Any:
    from ..core.remote_control import RemoteControl
    from ..config.loader import home_dir

    rc = RemoteControl(Path(home_dir()))
    # 装载持久化会话 (__init__ 不自动加载, 独立查询需显式读盘)
    try:
        rc._load_sessions()
    except Exception as exc:  # noqa: BLE001
        log.warning("_get_rc(): 非致命异常已忽略(设计内降级, 不改控制流): %s", exc)
        pass
    return rc


def cmd_remote(args: Any) -> int:
    """remote 主入口: 远程控制会话可观测 (纯只读查询 + 主动通知)。"""
    sub = getattr(args, "remote_cmd", None) or "status"
    json_mode = bool(getattr(args, "json", False))
    rc = _get_rc()

    if sub == "status":
        sid = str(getattr(args, "session", "") or "").strip()
        if sid:
            st = rc.get_session(sid)
            if st is None:
                console.print(f"[red]未找到远程会话: {sid}[/red]")
                return 1
            if json_mode:
                print(json.dumps(st, ensure_ascii=False, indent=2))
                return 0
            console.print(f"[bold]远程会话 {sid}[/bold]")
            conn = "已连接" if st.get("connected") else "未连接"
            console.print(f"  连接: [{'green' if st.get('connected') else 'yellow'}]{conn}[/] "
                          f"· 设备: [cyan]{st.get('device_name') or '未绑定'}[/cyan] "
                          f"[dim]({st.get('device_type') or '-'})[/dim]")
            console.print(f"  推送: {st.get('push_enabled')} "
                          f"· 已确认: {st.get('confirmed')}")
            if st.get("requires_confirmation"):
                console.print(f"  需用户确认: [yellow]{st.get('requires_confirmation')}[/yellow]")
            if st.get("connected_at"):
                console.print(f"  连接时间: {st.get('connected_at')}")
            return 0

        sessions: List[Dict[str, Any]] = rc.list_sessions()
        if json_mode:
            print(json.dumps({
                "count": len(sessions),
                "sessions": sessions,
            }, ensure_ascii=False, indent=2))
            return 0
        if not sessions:
            console.print("[green]✓ 无远程配对会话[/green] "
                          "([dim]<home>/remote_sessions.json[/dim])")
            console.print("[dim]提示: 用 tuan remote notify <标题> 测试推送通道[/dim]")
            return 0
        console.print(f"[bold]远程控制会话 ({len(sessions)} 个)[/bold]\n")
        for s in sessions:
            conn = "[green]已连接[/green]" if s.get("connected") else "[yellow]未连接[/yellow]"
            conf = " · [cyan]已确认[/cyan]" if s.get("confirmed") else ""
            console.print(f"  [yellow]{str(s.get('session_id'))[:12]}[/yellow]  "
                          f"{conn}{conf}  "
                          f"[dim]{s.get('device_name') or '未绑定设备'}[/dim]  "
                          f"[dim]推送={s.get('push_enabled')}[/dim]")
        console.print("\n[dim]详情: tuan remote status <sid> · "
                      "通知: tuan remote notify <标题>[/dim]")
        return 0

    if sub == "notify":
        title = str(getattr(args, "title", "") or "").strip()
        if not title:
            console.print("[red]缺少通知标题[/red] (用法: tuan remote notify <标题>)")
            return 1
        body = str(getattr(args, "body", "") or "")
        from ..core.remote_control import notify
        ok = notify(title, body or "远程控制测试通知", kind="info")
        if json_mode:
            print(json.dumps({"sent": ok, "title": title, "body": body},
                             ensure_ascii=False, indent=2))
            return 0
        if ok:
            console.print(f"[green]✓ 已发送通知: {title}[/green]")
        else:
            console.print(f"[yellow]通知发送失败 (推送通道未就绪): {title}[/yellow]")
        return 0

    if sub == "clear":
        sid = str(getattr(args, "session", "") or "").strip()
        if not sid:
            console.print("[red]缺少会话 ID[/red] (用法: tuan remote clear <sid>)")
            return 1
        removed = rc._sessions.pop(sid, None)
        if removed is not None:
            rc._save_sessions()
            if json_mode:
                print(json.dumps({"removed": True, "session_id": sid},
                                 ensure_ascii=False, indent=2))
                return 0
            console.print(f"[green]✓ 已移除会话 {sid}[/green]")
            return 0
        if json_mode:
            print(json.dumps({"removed": False, "session_id": sid},
                             ensure_ascii=False, indent=2))
            return 0
        console.print(f"[yellow]会话不存在或已清理: {sid}[/yellow]")
        return 0

    console.print(f"[red]未知 remote 子命令: {sub}[/red]")
    return 1


_register_command("cmd_remote", ".cmd_remote")
