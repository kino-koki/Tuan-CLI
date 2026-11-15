"""diff 命令 —— 操作账本驱动的字节级 diff 展示 (第 88 个独特功能)。

暴露 :mod:`tuan_cli.core.diff_view` 的能力:
- **最近编辑 diff**: 从操作账本 (.tuan/ledger) 取最近一次文件编辑,
  生成着色后的统一 diff (新增绿 / 删除红 / 头信息灰);
- **摘要统计**: 一次编辑的 (+新增, -删除) 行数与文件数;
- **账本回放**: 列出账本中全部 edit/write 记录, 按文件/工具过滤。

差异化价值: Claude Code 的 ``/diff`` 只在会话内交互式展示当前 diff,
无法从命令行**独立查询**"最后一次文件编辑的精确差异", 也无法回放
历史每次编辑的摘要。本命令把 diff_view 的静态渲染 + 账本回放能力
开放为独立的 CLI 查询面, 纯只读, 不依赖活动会话。

  tuan diff                        # 最近一次编辑的字节级 diff
  tuan diff --last N               # 最近 N 次编辑摘要
  tuan diff --file <path>          # 只看某文件的编辑
  tuan diff --stat                 # 只显示摘要统计 (+/- 行数)
  tuan diff --scope                # 影响半径统计 (涉及文件数/操作数/文件清单)
  tuan diff --json                 # 机器可读
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from ._ui_singleton import console
from .parser import _register_command


def _resolve_workspace() -> Path:
    from ..config import home_dir
    from ..paths import default_workspace

    ws = Path(default_workspace())
    if not (ws / ".tuan").exists():
        # 回退: 用配置里的 workspace 或当前目录
        home = Path(home_dir())
        cfg_ws = home / "config.json"
        try:
            import json as _json

            if cfg_ws.exists():
                data = _json.loads(cfg_ws.read_text(encoding="utf-8"))
                alt = data.get("workspace", "")
                if alt:
                    ws = Path(alt)
        except OSError:
            pass
    return ws


def _load_ledger_events(ws: Path) -> List[Dict[str, Any]]:
    """从工作区 .tuan/ledger 读取全部变更凭证。"""
    ledger = ws / ".tuan" / "ledger"
    if not ledger.exists():
        return []
    cand = ledger if ledger.is_file() else (ledger / "events.jsonl")
    if not cand.exists():
        return []
    events: List[Dict[str, Any]] = []
    try:
        for line in cand.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    except OSError:
        return []
    return events


def _summarize(events: List[Dict[str, Any]]) -> Dict[str, Any]:
    """聚合摘要: 按类型/文件统计。"""
    from ..core.diff_view import summarize_diff

    by_type: Dict[str, int] = {}
    by_file: Dict[str, Dict[str, int]] = {}
    added = removed = files = 0
    for ev in events:
        typ = str(ev.get("type") or "unknown")
        by_type[typ] = by_type.get(typ, 0) + 1
        path = str(ev.get("path") or ev.get("file") or "")
        old = ev.get("old")
        new = ev.get("new")
        if path and old is not None and new is not None:
            try:
                a, r, f = summarize_diff(
                    _render_plain_diff(old, new, Path(path).name))
                added += a
                removed += r
                files += f
            except Exception:  # noqa: BLE001
                pass
            bf = by_file.setdefault(path, {"edits": 0, "added": 0, "removed": 0})
            bf["edits"] += 1
    return {
        "events": len(events),
        "by_type": by_type,
        "by_file": by_file,
        "added": added,
        "removed": removed,
        "files": files,
    }


def _render_plain_diff(old: str, new: str, filename: str) -> str:
    """生成未上色的统一 diff (供 summarize 统计)。"""
    import difflib

    diff = difflib.unified_diff(
        old.splitlines(), new.splitlines(),
        fromfile=f"a/{filename}", tofile=f"b/{filename}", lineterm="",
    )
    return "\n".join(diff)


def _scope_stats(events: List[Dict[str, Any]]) -> Dict[str, Any]:
    """影响半径统计: 涉及文件数 / 操作数 / 文件清单 (第 94 个独特功能)。

    语义与 :meth:`core.ledger.MutationLedger.stats` 一致, 但基于
    **落盘变更凭证** (跨进程可用), 而非内存态 ``_records``。
    """
    files: set[str] = set()
    by_type: Dict[str, int] = {}
    by_file: Dict[str, int] = {}
    for ev in events:
        typ = str(ev.get("type") or "unknown")
        by_type[typ] = by_type.get(typ, 0) + 1
        # 兼容 targets 列表 / 单 path / file 字段
        targets = ev.get("targets")
        if isinstance(targets, list):
            for t in targets:
                f = str(t).strip().lstrip("./\\")
                if f:
                    files.add(f)
                    by_file[f] = by_file.get(f, 0) + 1
        else:
            p = str(ev.get("path") or ev.get("file") or "").strip().lstrip("./\\")
            if p:
                files.add(p)
                by_file[p] = by_file.get(p, 0) + 1
    return {
        "records": len(events),
        "files_touched": len(files),
        "files": sorted(files),
        "by_type": by_type,
        "by_file": by_file,
    }


def cmd_diff(args: Any) -> int:
    """diff 主入口: 从操作账本展示字节级 diff (纯只读)。"""
    ws = _resolve_workspace()
    events = _load_ledger_events(ws)
    json_mode = bool(getattr(args, "json", False))
    last_n = int(getattr(args, "last", 0) or 0)
    only_file = str(getattr(args, "file", "") or "").strip()
    stat_only = bool(getattr(args, "stat", False))
    scope_only = bool(getattr(args, "scope", False))

    # -- 影响半径统计 (第 94 个独特功能): 全部凭证, 不分编辑/非编辑 --
    if scope_only:
        scope = _scope_stats(events)
        if json_mode:
            print(json.dumps({
                "workspace": str(ws),
                "records": scope["records"],
                "files_touched": scope["files_touched"],
                "files": scope["files"],
                "by_type": scope["by_type"],
                "by_file": scope["by_file"],
            }, ensure_ascii=False, indent=2))
            return 0
        if not scope["records"]:
            console.print("[green]✓ 账本无记录[/green] "
                          f"([dim]{ws}/.tuan/ledger[/dim])")
            return 0
        console.print(f"[bold]影响半径统计 · {ws.name}[/bold]")
        console.print(f"  操作记录: [cyan]{scope['records']}[/cyan] 条 · "
                      f"涉及文件: [green]{scope['files_touched']}[/green] 个")
        console.print("\n[dim]按操作类型: " + ", ".join(
            f"{k}×{v}" for k, v in sorted(scope["by_type"].items(),
                                          key=lambda x: -x[1])) + "[/dim]")
        if scope["files"]:
            console.print("\n[bold]涉及文件:[/bold]")
            for f in scope["files"]:
                n = scope["by_file"].get(f, 1)
                console.print(f"  [dim]{f}[/dim] [cyan]×{n}[/cyan]")
        return 0

    # 只保留 edit/write/edit_file 类凭证
    edits = [e for e in events if str(e.get("type")) in ("edit", "write", "edit_file")]
    if only_file:
        edits = [e for e in edits
                 if str(e.get("path") or e.get("file") or "").endswith(only_file)]
    if last_n > 0:
        edits = edits[-last_n:]

    if json_mode:
        print(json.dumps({
            "workspace": str(ws),
            "ledger_events": len(events),
            "edits": [{
                "type": e.get("type"),
                "path": e.get("path") or e.get("file"),
                "tool": e.get("tool", ""),
                "ts": e.get("ts"),
            } for e in edits],
            "summary": _summarize(edits),
        }, ensure_ascii=False, indent=2))
        return 0

    if not edits:
        console.print("[green]✓ 账本无编辑记录[/green] "
                      f"([dim]{ws}/.tuan/ledger[/dim])")
        console.print("[dim]提示: 用 tuan rewind / tuan session 触发编辑后可见[/dim]")
        return 0

    # -- 只显示统计 --
    if stat_only:
        stats = _summarize(edits)
        console.print(f"[bold]账本编辑摘要 · {ws.name}[/bold]")
        console.print(f"  记录: {stats['events']} 条 · "
                      f"文件: {stats['files']} 个 · "
                      f"[green]+{stats['added']}[/green] / "
                      f"[red]-{stats['removed']}[/red]")
        console.print("\n[dim]按类型: " + ", ".join(
            f"{k}×{v}" for k, v in sorted(stats["by_type"].items(),
                                          key=lambda x: -x[1])) + "[/dim]")
        return 0

    # -- 显示最近一次编辑的完整 diff --
    last = edits[-1]
    path = str(last.get("path") or last.get("file") or "")
    old = last.get("old")
    new = last.get("new")
    if path and old is not None and new is not None:
        from ..core.diff_view import render_edit_diff

        colored = render_edit_diff(old, new, Path(path).name)
        if colored:
            added, removed, files = _summarize([last])["added"], _summarize([last])["removed"], 1
            console.print(f"[bold]最近编辑 · {path}[/bold]")
            console.print(f"[dim]类型: {last.get('type')} · "
                          f"工具: {last.get('tool') or '(ledger)'} · "
                          f"统计: +{added}/-{removed}[/dim]\n")
            print(colored)
            if len(edits) > 1:
                console.print(f"\n[dim]另有 {len(edits) - 1} 条编辑记录: "
                              f"tuan diff --last {len(edits)} --stat[/dim]")
            return 0

    # -- 无 old/new 的凭证: 只列摘要 --
    console.print(f"[bold]账本编辑记录 ({len(edits)} 条)[/bold]")
    for e in edits[-20:]:
        console.print(f"  [dim]{str(e.get('ts', ''))[:19]}[/dim] "
                      f"[cyan]{e.get('type')}[/cyan] "
                      f"{str(e.get('path') or e.get('file') or '')[:60]}")
    console.print("\n[dim]提示: 这些凭证无 old/new 快照, 仅列摘要; "
                  "用 --stat 看统计[/dim]")
    return 0


_register_command("cmd_diff", ".cmd_diff")
