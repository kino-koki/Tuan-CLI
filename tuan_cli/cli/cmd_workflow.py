"""workflow 命令 —— 动态并行工作流可观测性 (第 81 个独特功能)。

暴露 :mod:`tuan_cli.core.dynamic_workflow` 的 DynamicWorkflowEngine:
并行后台子代理编排的**只读/控制**可观测面 —— 列出工作流 / 查看状态 /
聚合结果 / 取消 / 重试失败。

差异化价值: Claude Code 的动态工作流编排是黑箱, 用户无法从命令行
查询「当前有哪些并行编排正在跑」「每步进度如何」「聚合结果是什么」。
本命令把这些状态暴露为可查询, 并支持取消/重试控制, 全程不触发
新的编排执行 (``auto_resume=False`` 避免 resume_all 续跑副作用)。
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

from ._ui_singleton import console
from .parser import _register_command


def _get_engine() -> Any:
    """取进程级共享引擎, 但不自动续跑 (纯查询/控制, 无 resume_all 副作用)。"""
    from ..config import home_dir
    from ..core.dynamic_workflow import get_engine

    return get_engine(home_dir(), auto_resume=False)


def _get_wf_id(args: Any) -> str:
    """从 args 解析工作流 ID (兼容 --id 与位置参数)。"""
    return str(getattr(args, "workflow_id", "") or "").strip()


def _cmd_workflow_list(args: Any, json_mode: bool) -> int:
    eng = _get_engine()
    wfs: List[Dict[str, Any]] = eng.list()
    if json_mode:
        print(json.dumps({"count": len(wfs), "workflows": wfs},
                         ensure_ascii=False, indent=2))
        return 0
    if not wfs:
        console.print("[green]✓ 无工作流记录[/green]")
        return 0
    console.print(f"[bold]动态并行工作流 ({len(wfs)} 个)[/bold]\n")
    for w in wfs:
        status = str(w.get("status") or "")
        color = {"done": "green", "running": "cyan",
                 "pending": "yellow", "failed": "red",
                 "cancelled": "dim"}.get(status, "white")
        console.print(f"  [yellow]{str(w.get('workflow_id', ''))[:8]}[/yellow]  "
                      f"[{color}]{status:^10s}[/{color}]  "
                      f"{str(w.get('name', ''))[:50]:<50s}  "
                      f"[dim]{w.get('n_steps', 0)} 步[/dim]")
    console.print("\n[dim]详情: tuan workflow status <id> · 结果: tuan workflow result <id>[/dim]")
    return 0


def _cmd_workflow_status(args: Any, json_mode: bool) -> int:
    eng = _get_engine()
    wf_id = _get_wf_id(args)
    if not wf_id:
        console.print("[red]缺少工作流 ID[/red] (用法: tuan workflow status <id>)")
        return 1
    try:
        st: Dict[str, Any] = eng.status(wf_id)
    except KeyError:
        console.print(f"[red]未找到工作流: {wf_id}[/red]")
        return 1
    if json_mode:
        print(json.dumps(st, ensure_ascii=False, indent=2))
        return 0
    console.print(f"[bold]{st.get('name', '')}[/bold] "
                  f"· [cyan]{st.get('workflow_id', '')[:8]}[/cyan] "
                  f"· 状态 [green]{st.get('status')}[/green] "
                  f"· {st.get('n_steps', 0)} 步 · 并行={st.get('parallel')}")
    for step in st.get("steps", []):
        icon = {"done": "✓", "running": "▶", "pending": "·",
                "failed": "✗", "cancelled": "⊘"}.get(step.get("status"), "?")
        console.print(f"  {icon} 步骤 {step.get('step') + 1} "
                      f"[{step.get('status')}]  "
                      f"{step.get('done_tasks')}/{step.get('n_tasks')} 任务")
    console.print("\n[dim]结果: tuan workflow result <id> · 取消: tuan workflow cancel <id>[/dim]")
    return 0


def _cmd_workflow_result(args: Any, json_mode: bool) -> int:
    eng = _get_engine()
    wf_id = _get_wf_id(args)
    if not wf_id:
        console.print("[red]缺少工作流 ID[/red] (用法: tuan workflow result <id>)")
        return 1
    try:
        res: Dict[str, Any] = eng.result(wf_id)
    except KeyError:
        console.print(f"[red]未找到工作流: {wf_id}[/red]")
        return 1
    if json_mode:
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0
    console.print(f"[bold]{res.get('name', '')}[/bold] · "
                  f"状态 [green]{res.get('status')}[/green] · "
                  f"完成 {res.get('ok_tasks')} 任务")
    console.print("")
    for line in str(res.get("summary", "")).split("\n"):
        console.print(line)
    return 0


def _cmd_workflow_cancel(args: Any, json_mode: bool) -> int:
    eng = _get_engine()
    wf_id = _get_wf_id(args)
    if not wf_id:
        console.print("[red]缺少工作流 ID[/red] (用法: tuan workflow cancel <id>)")
        return 1
    try:
        ok = eng.cancel(wf_id)
    except KeyError:
        console.print(f"[red]未找到工作流: {wf_id}[/red]")
        return 1
    if json_mode:
        print(json.dumps({"workflow_id": wf_id, "cancelled": ok},
                         ensure_ascii=False, indent=2))
        return 0
    if ok:
        console.print(f"[green]✓ 已取消工作流 {wf_id[:8]}[/green]")
    else:
        console.print(f"[yellow]无法取消 {wf_id[:8]} (已结束或不存在)[/yellow]")
    return 0


def _cmd_workflow_retry(args: Any, json_mode: bool) -> int:
    eng = _get_engine()
    wf_id = _get_wf_id(args)
    if not wf_id:
        console.print("[red]缺少工作流 ID[/red] (用法: tuan workflow retry <id>)")
        return 1
    try:
        ok = eng.retry_failed(wf_id)
    except KeyError:
        console.print(f"[red]未找到工作流: {wf_id}[/red]")
        return 1
    if json_mode:
        print(json.dumps({"workflow_id": wf_id, "retried": ok},
                         ensure_ascii=False, indent=2))
        return 0
    if ok:
        console.print(f"[green]✓ 已重跑失败任务 {wf_id[:8]}[/green]")
    else:
        console.print(f"[yellow]无失败任务可重跑 {wf_id[:8]} "
                      "(需处于 failed/done 且含失败任务)[/yellow]")
    return 0


def _cmd_workflow_archive(args: Any, json_mode: bool) -> int:
    """只读巡查已持久化工作流实例 (第 123 个独特功能)。

    WorkflowStore (core/dynamic_workflow.py) 把每个工作流实例原子落盘到
    ``<home>/background/workflows/<wf_id>.json`` (含 id/status/steps/任务/
    结果/时间戳), 供崩溃续跑与跨进程查询。但此前该归档**只写不读**:
    唯一的读是引擎内部 store.get(), 没有任何命令能列出磁盘上真正存在
    哪些工作流、各实例的状态/步数/起止时间。`tuan workflow list` 是
    **进程内**引擎视图 (可能未落盘/已清理), 不反映持久化事实。对比
    Claude Code: 它的并行编排状态是内存黑箱, 无「已持久化实例」只读巡查。
    本命令补上只读面 (纯只读: glob + json.load, 不构造 WorkflowStore ——
    其 __init__ 会 mkdir, 不触发 get_engine 的 auto_resume)。
    """
    from pathlib import Path

    from ..config import home_dir

    store_dir = Path(home_dir()) / "background" / "workflows"

    if not store_dir.is_dir():
        if json_mode:
            print(json.dumps({"store_dir": str(store_dir),
                              "initialized": False, "count": 0,
                              "workflows": []}, ensure_ascii=False, indent=2))
            return 0
        console.print(f"[dim]工作流归档未初始化: {store_dir}[/dim]")
        return 0

    wfs = []
    malformed = 0
    for p in sorted(store_dir.glob("*.json"), key=lambda p: p.stat().st_mtime,
                    reverse=True):
        try:
            # utf-8-sig: 容忍 UTF-8 BOM (某些编辑器/导出工具会加), 正常文件无影响
            data = json.loads(p.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            malformed += 1
            continue
        if not isinstance(data, dict):
            malformed += 1
            continue
        wfs.append(data)

    limit = int(getattr(args, "limit", 0) or 0)
    shown = wfs[:limit] if limit and len(wfs) > limit else wfs

    if json_mode:
        print(json.dumps({"store_dir": str(store_dir), "initialized": True,
                          "count": len(wfs), "malformed": malformed,
                          "workflows": shown}, ensure_ascii=False, indent=2))
        return 0

    console.print(f"[bold]工作流归档 · {store_dir}[/bold]\n")
    console.print(f"  磁盘上 {len(wfs)} 个工作流实例 (坏文件 {malformed})\n")
    if not wfs:
        console.print("  [dim](空)[/dim]")
        return 0
    for w in shown:
        wf_id = w.get("workflow_id") or w.get("id") or "?"
        status = w.get("status", "?")
        steps = w.get("steps", []) or []
        done = sum(1 for s in steps if s.get("status") == "done")
        created = w.get("created_at") or w.get("created") or ""
        updated = w.get("updated_at") or w.get("updated") or ""
        console.print(f"  [bold]{wf_id}[/bold] · {status} · 步 {done}/{len(steps)}")
        console.print(f"      创建: {created}  更新: {updated}")
        task_count = sum(len((s.get("tasks") or [])) for s in steps)
        console.print(f"      任务总数: {task_count}")
    return 0


def cmd_workflow(args: Any) -> int:
    """workflow 主入口: 分发到子命令 (纯只读/控制, 不触发新编排)。"""
    sub = getattr(args, "workflow_cmd", None) or "list"
    json_mode = bool(getattr(args, "json", False))
    if sub == "list":
        return _cmd_workflow_list(args, json_mode)
    if sub == "status":
        return _cmd_workflow_status(args, json_mode)
    if sub == "result":
        return _cmd_workflow_result(args, json_mode)
    if sub == "archive":
        return _cmd_workflow_archive(args, json_mode)
    if sub == "cancel":
        return _cmd_workflow_cancel(args, json_mode)
    if sub == "retry":
        return _cmd_workflow_retry(args, json_mode)
    console.print(f"[red]未知 workflow 子命令: {sub}[/red]")
    return 1


_register_command("cmd_workflow", ".cmd_workflow")
