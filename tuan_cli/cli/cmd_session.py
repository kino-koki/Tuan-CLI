"""`tuan session` —— 会话管理 (拆分自 cmd_services.py)。"""

from __future__ import annotations
from ..paths import default_workspace

import datetime
import json
import os
import time
from pathlib import Path
from typing import Any, List

from ..config import home_dir
from ..i18n import t
from ._ui_singleton import console
from ..ui.format import Table


# ---- app 链惰性加载: 仅 resume 真正恢复会话时才构建内核 ----
def build_kernel(*a: Any, **k: Any) -> Any:
    from ..app import build_kernel as _f
    return _f(*a, **k)


def create_agent(*a: Any, **k: Any) -> Any:
    from ..app import create_agent as _f
    return _f(*a, **k)


def seed_builtin_skills(*a: Any, **k: Any) -> Any:
    from ..app import seed_builtin_skills as _f
    return _f(*a, **k)


def _format_session_time(mtime: float, now: float) -> str:
    """会话时间: 近期显示相对时间, 更早显示绝对时间。"""
    delta = now - mtime
    if delta < 60:
        return "刚刚"
    if delta < 3600:
        return f"{int(delta // 60)} 分钟前"
    if delta < 86400:
        return f"{int(delta // 3600)} 小时前"
    if delta < 7 * 86400:
        return f"{int(delta // 86400)} 天前"
    return datetime.datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")


def _count_session_messages(path: Path) -> int:
    """统计会话中的消息条数。"""
    n = 0
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if rec.get("type") in ("user", "assistant", "tool"):
                    n += 1
    except OSError:
        pass
    return n


def _resolve_session_target(files: List[Path], target: str) -> List[Path]:
    """把会话目标解析为文件列表。"""
    if target == "all":
        return list(files)
    if target.isdigit():
        idx = int(target) - 1
        return [files[idx]] if 0 <= idx < len(files) else []
    return [f for f in files if f.stem.startswith(target)]


def _print_tree(res: Any, roots: List[str]) -> None:
    """用缩进打印会话分叉树 (以多个根开始, 每层缩进子分支)。"""
    by_id = {s["session_id"]: s for s in res.list_sessions()}

    def _label(sid: Any) -> str:
        info = by_id.get(sid, {})
        title = (info.get("title") or "(无标题)")
        mark = "*" if info.get("forked") else ""
        tail = []
        if info.get("branch_point"):
            tail.append(f"@{info['branch_point']}")
        return f"{sid}{mark}  {title}" + ("  [分支点" + " ".join(tail) + "]" if tail else "")

    seen: set = set()

    def _walk(sid: Any, depth: int) -> None:
        if sid in seen:
            print(f"{'  ' * depth}· {sid}  (环/重复, 已截断)")
            return
        seen.add(sid)
        prefix = "  " * depth
        print(f"{prefix}{'└─' if depth else '● '} {_label(sid)}")
        for child in by_id.values():
            if child.get("forked") and child.get("parent") == sid:
                _walk(child["session_id"], depth + 1)

    for rid in roots:
        _walk(rid, 0)


def cmd_session(args: Any) -> int:
    session_cmd = getattr(args, "session_cmd", None)
    sessions_dir = home_dir() / "sessions"
    if not sessions_dir.exists():
        console.print("没有会话记录")
        return 0
    files = sorted(sessions_dir.glob("*.jsonl"), key=lambda f: f.stat().st_mtime, reverse=True)

    if session_cmd == "list":
        from ..memory.sessions import SessionStore
        limit = getattr(args, "limit", None)
        show_all = getattr(args, "all", False)
        sessions = files if show_all else files[:int(limit) if limit else 10]
        if not sessions:
            console.print("没有会话记录")
            return 0
        table = Table(title="历史会话")
        table.add_column("#", justify="right")
        table.add_column("时间", justify="left")
        table.add_column("标题", justify="left")
        table.add_column("消息", justify="right")
        table.add_column("大小", justify="right")
        table.add_column("会话ID", justify="left")
        now = time.time()
        for i, f in enumerate(sessions, 1):
            title = SessionStore.peek_title(f) or "(无标题)"
            size_kb = f.stat().st_size / 1024
            table.add_row(
                str(i),
                _format_session_time(f.stat().st_mtime, now),
                title,
                str(_count_session_messages(f)),
                f"{size_kb:.0f}KB" if size_kb >= 1 else f"{f.stat().st_size}B",
                f.stem,
            )
        console.print(table)
        console.print("使用 tuan session resume <编号|会话ID> 恢复会话")
        return 0

    if session_cmd == "resume":
        target = getattr(args, "target", None) or "latest"
        from .cmd_chat import _resume_session, _apply_mode_override, _run_chat_repl
        try:
            kernel = build_kernel()
        except Exception as exc:
            console.print(f"启动失败: {exc}")
            return 1
        config = kernel.require("config")
        workspace = getattr(args, "workspace", None) or default_workspace()
        agent = create_agent(kernel, workspace)
        seed_builtin_skills(kernel)
        loaded = _resume_session(agent, target)
        if loaded is None:
            return 1
        console.print(f"{t('chat.resumed', path=loaded, count=len(agent.messages))}")
        mode = _apply_mode_override(kernel, getattr(args, "mode", None),
                                    yes=getattr(args, "yolo", False))
        # Auto 模式 (对标 Claude Code): 内部标记, 由 ToolExecutor 经分类器按风险分级决策。
        if mode == "auto":
            agent.ctx.auto_mode = True
        effort = config.get("agent.effort", "high")
        rc: int = _run_chat_repl(agent, config, workspace, mode, effort)
        return rc

    if session_cmd == "delete":
        target = getattr(args, "target", None) or "1"
        if target == "latest":
            target = "1"
        if not files:
            console.print("没有会话记录")
            return 0
        targets = _resolve_session_target(files, target)
        if not targets:
            console.print(f"未找到匹配的会话: {target}")
            return 1
        if not getattr(args, "yes", False):
            total_size = sum(f.stat().st_size for f in targets)
            names = ", ".join(f.stem for f in targets[:5])
            if len(targets) > 5:
                names += f" …(共 {len(targets)} 个)"
            try:
                ans = input(
                    f"  确认删除 {len(targets)} 个会话 ({names})? "
                    f"(共 {total_size / 1024:.0f}KB) [y/N] "
                ).strip().lower()
            except (EOFError, KeyboardInterrupt):
                ans = ""
            if ans != "y":
                console.print("已取消")
                return 0
        for f in targets:
            try:
                f.unlink()
            except OSError as exc:
                console.print(f"删除失败 {f.name}: {exc}")
                return 1
        console.print(f"已删除 {len(targets)} 个会话")
        return 0

    if session_cmd == "export":
        target = getattr(args, "target", None) or "1"
        output = getattr(args, "output", None)
        targets = _resolve_session_target(files, target)
        if not targets:
            console.print(f"未找到匹配的会话: {target}")
            return 1
        src = targets[0]
        if output:
            out_path = Path(output).expanduser()
            want_zip = str(out_path).endswith(".zip")
            if out_path.is_dir():
                out_path = out_path / (src.stem + (".zip" if want_zip else ".jsonl"))
            if want_zip:
                from .cmd_session_export import export_session_zip
                out_path = export_session_zip(src, out_path)
                console.print(f"已导出会话 zip: {out_path}")
            else:
                import shutil
                shutil.copy2(src, out_path)
                console.print(f"已导出到: {out_path}")
        else:
            # 输出到 stdout
            try:
                content = src.read_text(encoding="utf-8")
                print(content)
            except OSError as exc:
                console.print(f"读取失败: {exc}")
                return 1
        return 0

    if session_cmd == "clean":
        # 清理过期会话 (默认 30 天前)
        max_age_days = getattr(args, "older_than", 30)
        cutoff = time.time() - max_age_days * 86400
        old_files = [f for f in files if f.stat().st_mtime < cutoff]
        if not old_files:
            console.print(f"没有超过 {max_age_days} 天的会话")
            return 0
        total_size = sum(f.stat().st_size for f in old_files)
        if not getattr(args, "yes", False):
            try:
                ans = input(
                    f"  将清理 {len(old_files)} 个过期会话 "
                    f"(>{max_age_days}天, 共 {total_size / 1024:.0f}KB)? [y/N] "
                ).strip().lower()
            except (EOFError, KeyboardInterrupt):
                ans = ""
            if ans != "y":
                console.print("已取消")
                return 0
        for f in old_files:
            try:
                f.unlink()
            except OSError:
                pass
        console.print(f"已清理 {len(old_files)} 个过期会话 (释放 {total_size / 1024:.0f}KB)")
        return 0

    if session_cmd == "stats":
        if not files:
            console.print("没有会话记录")
            return 0
        total_size = sum(f.stat().st_size for f in files)
        total_msgs = sum(_count_session_messages(f) for f in files)
        ages = [(time.time() - f.stat().st_mtime) / 86400 for f in files]
        oldest = max(ages) if ages else 0
        newest = min(ages) if ages else 0
        console.print(f"会话统计")
        console.print(f"  总数: {len(files)} 个会话")
        console.print(f"  总大小: {total_size / 1024:.0f}KB ({total_size / 1024 / 1024:.1f}MB)")
        console.print(f"  总消息: {total_msgs} 条")
        console.print(f"  最旧: {oldest:.0f} 天前")
        console.print(f"  最新: {newest:.0f} 天前")
        # 按月统计
        month_counts: dict[str, int] = {}
        for f in files:
            import datetime as _dt
            month = _dt.datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m")
            month_counts[month] = month_counts.get(month, 0) + 1
        if month_counts:
            console.print(f"  月度分布:")
            for month in sorted(month_counts)[-6:]:
                bar = "#" * min(month_counts[month], 30)
                console.print(f"    {month}: {month_counts[month]:3d} {bar}")
        return 0

    # --- 跨会话 / 分叉 (迭代 3) ---
    if session_cmd in ("fork", "tree", "ref"):
        from ..core.cross_session import CrossSessionResolver
        from ..memory.sessions import SessionStore as _SS

        if session_cmd == "fork":
            target = getattr(args, "target", None) or "1"
            targets = _resolve_session_target(files, target)
            if not targets:
                console.print(f"未找到匹配的会话: {target}")
                return 1
            src = targets[0]
            store = _SS(sessions_dir)
            store.dir = sessions_dir
            store.file = src
            child = store.fork(at_message=getattr(args, "at_message", None),
                               note=getattr(args, "note", None) or "")
            b = child.branch_info()
            console.print(f"已分叉会话 {src.stem} -> {child.session_id}")
            console.print(f"  父会话: {b.get('parent')}  分支点: {b.get('branch_point') or '整份'}"
                          + (f"  备注: {b.get('note')}" if b.get("note") else ""))
            console.print("可在其它对话用 @session:<id> 引用这个分支")
            return 0

        res = CrossSessionResolver(home=home_dir())

        if session_cmd == "tree":
            root = getattr(args, "root", None)
            if root:
                targets = _resolve_session_target(files, root)
                if not targets:
                    console.print(f"未找到匹配的会话: {root}")
                    return 1
                root_id = targets[0].stem
            else:
                _sess_dir = res._sessions_dir()
                roots = [p.stem for p in _sess_dir.glob("*.jsonl")
                         if ((_SS.read_meta(p) or {}).get("kind") != "fork")]
                if not roots:
                    roots = [files[0].stem] if files else []
                _print_tree(res, roots)
                return 0
            _print_tree(res, [root_id])
            return 0

        if session_cmd == "ref":
            text = " ".join(getattr(args, "text", []))
            out = res.inject(text)
            if out == text:
                console.print("(文本中没有可解析的 @session / @# 引用)")
                return 0
            print(out)
            return 0

    # --- 回放 / 轨迹 (原顶级 tuan replay / tuan trajectory, 已并入 session) ---
    if session_cmd == "replay":
        from ..core.replay import list_sessions, load_trajectory, render_replay

        if getattr(args, "list", False) or not getattr(args, "session", None):
            rows = list_sessions()
            if not rows:
                console.print("没有历史会话。先跑一次 `tuan` 或 `tuan run` 即可生成。")
                return 0
            console.print(f"{'#':>3}  {'时间':<20}  {'事件':>5}  标题")
            for i, r in enumerate(rows, 1):
                console.print(
                    f"{i:>3}  {r['mtime_str']:<20}  {r['events']:>5}  标题: {r['title'][:48]}"
                )
            return 0
        sid = args.session
        if getattr(args, "json", False):
            traj = load_trajectory(sid)
            if traj is None:
                console.print(f"[错误] 找不到会话: {sid}")
                return 1
            print(traj.to_json())
            return 0
        text = render_replay(sid)
        if getattr(args, "export", None):
            # 注意: 本函数作用域内 out 已被推断为 str (render 分支), 此处
            # 不能复用同名变量存 Path, 否则 mypy 报 incompatible types。
            p = Path(args.export)
            p.write_text(text, encoding="utf-8")
            console.print(f"已导出回放: {p}")
        else:
            print(text)
        return 0

    if session_cmd == "trajectory":
        from ..core.replay import load_trajectory

        sub = getattr(args, "traj_cmd", None)
        if sub in ("analyze", "timeline", "fork", "snapshots"):
            # 转发给专项 handler (原先静默降级为 show, 属错误行为)
            return _session_traj_dispatch(sub, args)
        if sub == "export":
            traj = load_trajectory(args.session)
            if traj is None:
                console.print(f"[错误] 找不到会话: {args.session}")
                return 1
            out = traj.to_json() if args.format == "json" else traj.to_markdown()
            if args.out:
                p = Path(args.out)
                p.write_text(out, encoding="utf-8")
                console.print(f"已导出 Trajectory: {p}")
            else:
                print(out)
            return 0
        # 默认 / show: 指标 + 摘要
        traj = load_trajectory(args.session)
        if traj is None:
            console.print(f"[错误] 找不到会话: {args.session}")
            return 1
        print(json.dumps(traj.metrics(), ensure_ascii=False, indent=2))
        print("─" * 50)
        print(traj.summary())
        return 0

    # --- trajectory 子命令 (analyze/timeline/fork/snapshots 曾静默降级为 show) ---
    if session_cmd == "trajectory":
        sub = getattr(args, "traj_cmd", None)
        if sub == "analyze":
            return _session_traj_analyze(args)
        if sub == "timeline":
            return _session_traj_timeline(args)
        if sub == "fork":
            return _session_traj_fork(args)
        if sub == "snapshots":
            return _session_traj_snapshots(args)

    # --- 跨会话差异对比 ---
    if session_cmd == "compare":
        return _session_compare(args)

    # --- 跨会话指标聚合趋势 ---
    if session_cmd == "trend":
        return _session_trend(args)

    # --- 事件溯源查询/统计 ---
    if session_cmd == "events":
        return _session_events(args)

    # --- WireStore 上下文记录流只读体检 ---
    if session_cmd == "wire":
        return _session_wire(args, files)

    # --- EventSourcer API 化查询 ---
    if session_cmd == "query":
        return _session_query(args, files)

    # --- EventSourcer 内存态分叉/回放 ---
    if session_cmd == "sourcer":
        return _session_sourcer(args, files)

    # --- 无 LLM 结构化摘要提取预览 ---
    if session_cmd == "digest":
        return _session_digest(args, files)

    console.print("用法: tuan session "
                  "list|resume|delete|export|clean|stats|fork|tree|ref|replay|trajectory|"
                  "compare|trend|events|wire|query|sourcer|digest")
    return 0


# =====================================================================
# session 组补充 handler (修复死子命令: 有 argparse 入口、无分发实现)
# =====================================================================

def _resolve_session_path(files: List[Path], target: str) -> Any:
    """解析会话目标 (编号/ID/前缀/latest) 为单个文件, 找不到返回 None。"""
    if target == "latest":
        return files[0] if files else None
    if target.isdigit():
        idx = int(target) - 1
        return files[idx] if 0 <= idx < len(files) else None
    for f in files:
        if f.stem.startswith(target):
            return f
    return None


class _EventStoreAdapter:
    """EventSourcer 的单参 append(dict) 契约适配器。

    真实 SessionStore.append(event_type, payload) 是双参, 而 EventSourcer
    依赖单参 append(dict) (ContextEventLog 兼容契约)。适配器把 to_dict()
    (含 type 字段) 拆成 (event_type, 其余 payload), 并透传 read_all/session_id。
    """

    def __init__(self, store: Any) -> None:
        self._store = store
        self.session_id = getattr(store, "session_id", "")

    def append(self, d: dict) -> None:
        d = dict(d)
        ev_type = d.pop("type", "event")
        self._store.append(ev_type, d)

    def read_all(self) -> list:
        rows: list = self._store.read_all()
        return rows


def _session_compare(args: Any) -> int:
    """跨会话差异对比 (CrossSessionResolver.compare)。"""
    from ..core.cross_session import CrossSessionResolver
    res = CrossSessionResolver(home=home_dir())
    result = res.compare(args.session_a, args.session_b)
    if getattr(args, "json", False):
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0
    ma, mb = result["meta_a"], result["meta_b"]
    print(f"跨会话差异对比: {result['session_a']}  vs  {result['session_b']}")
    print(f"  会话A 事件总数: {result['events_a'].get('total', 0)}"
          f"  标题: {ma.get('title') or '(无标题)'}")
    print(f"  会话B 事件总数: {result['events_b'].get('total', 0)}"
          f"  标题: {mb.get('title') or '(无标题)'}")
    diff = result["event_count_diff"]
    print(f"  事件数差: {diff:+d}  (A相对B{'多' if diff >= 0 else '少'})")
    if result["tool_diff"]:
        print("  工具使用差异 (仅非零):")
        for k, v in sorted(result["tool_diff"].items(), key=lambda kv: abs(kv[1]), reverse=True):
            print(f"    {k}: {v:+d}")
    return 0


def _session_trend(args: Any) -> int:
    """跨会话指标聚合趋势 (逐会话 Trajectory.metrics 横向对比)。"""
    from ..core.replay import list_sessions, load_trajectory
    rows = list_sessions()
    if not rows:
        console.print("没有历史会话")
        return 0
    limit = getattr(args, "limit", 10)
    rows = rows[:limit]
    sort = getattr(args, "sort", "time")
    series = []
    for r in rows:
        traj = load_trajectory(r["session_id"])
        if traj is None:
            continue
        m = traj.metrics()
        series.append({
            "session_id": r["session_id"],
            "mtime": r["mtime"],
            "title": r.get("title") or "(无标题)",
            "steps": m["steps"],
            "user_turns": m["user_turns"],
            "tool_calls": m["tool_calls"],
            "tool_ok": m["tool_ok"],
            "tool_failed": m["tool_failed"],
            "tool_success_rate": m["tool_success_rate"],
            "tool_time_ms": m["tool_time_ms"],
            "total_tokens": m["total_tokens"],
            "total_cost_usd": m["total_cost_usd"],
        })
    if sort == "success":
        series.sort(key=lambda s: (s["tool_success_rate"] is None, -(s["tool_success_rate"] or 0)))
    elif sort == "cost":
        series.sort(key=lambda s: -s["total_cost_usd"])
    elif sort == "tokens":
        series.sort(key=lambda s: -s["total_tokens"])
    else:
        series.sort(key=lambda s: s["mtime"], reverse=True)
    if getattr(args, "json", False):
        print(json.dumps(series, ensure_ascii=False, indent=2, default=str))
        return 0
    print(f"跨会话指标趋势 (最近 {len(series)} 个会话, 排序: {sort})")
    print(f"{'会话ID':<22} {'步骤':>4} {'工具':>4} {'成功率':>7} {'Token':>9} {'花费$':>8}  标题")
    for s in series:
        rate = f"{s['tool_success_rate'] * 100:.0f}%" if s["tool_success_rate"] is not None else "—"
        print(f"{s['session_id']:<22} {s['steps']:>4} {s['tool_calls']:>4} "
              f"{rate:>7} {s['total_tokens']:>9} {s['total_cost_usd']:>8.4f}  {s['title']}")
    return 0


def _session_events(args: Any) -> int:
    """事件溯源: 查询/统计 (类型/单条事件)。"""
    from ..core.trajectory_replay import TrajectoryReplay
    session = getattr(args, "session", None)
    if not session:
        console.print("需要指定会话: tuan session events <会话ID|前缀>")
        return 2
    replay = TrajectoryReplay(session_dir=home_dir() / "sessions")
    seq = getattr(args, "seq", None)
    if seq is not None:
        events = replay.replay(session)
        for ev in events:
            if ev.seq == seq:
                if getattr(args, "json", False):
                    print(json.dumps(ev.to_dict(), ensure_ascii=False, indent=2, default=str))
                else:
                    print(f"[#{ev.seq}] {ev.event_type}  {ev.status}  "
                          f"工具={ev.tool_name or '-'}  来源={ev.source or '-'}")
                    print(f"  {json.dumps(ev.payload, ensure_ascii=False, default=str)[:500]}")
                return 0
        console.print(f"未找到序号 {seq} 的事件")
        return 1
    events = replay.replay(session, filter_type=getattr(args, "kind", None))
    limit = getattr(args, "limit", 30)
    if getattr(args, "json", False):
        print(json.dumps([ev.to_dict() for ev in events[-limit:]],
                         ensure_ascii=False, indent=2, default=str))
        return 0
    print(f"会话 {session} 事件列表 (共 {len(events)} 条, 显示最后 {min(limit, len(events))} 条)")
    for ev in events[-limit:]:
        print(f"  [#{ev.seq}] {ev.event_type:<12} {ev.status:<8} "
              f"工具={ev.tool_name or '-'}  来源={ev.source or '-'}")
    return 0


def _session_wire(args: Any, files: List[Path]) -> int:
    """WireStore 上下文记录流只读体检 (类型分布/时间跨度/协议版本)。"""
    from ..runtime.session.wire import WireStore
    session = getattr(args, "session", None)
    if not session:
        # 默认取最近一个会话
        if not files:
            console.print("没有会话记录")
            return 0
        session = files[0].stem
    sessions_dir = home_dir() / "sessions"
    wire_path = sessions_dir / f"{session}.wire.jsonl"
    store = WireStore(wire_path)
    if not store.exists():
        console.print(f"[wire] 没有上下文记录流: {wire_path}")
        return 0
    records = list(store.read_journal())
    from collections import Counter
    by_type: Counter = Counter()
    timestamps: list = []
    protocol = "?"
    for rec in records:
        by_type[rec.get("type", "unknown")] += 1
        ts = rec.get("time")
        if isinstance(ts, (int, float)):
            timestamps.append(ts)
        if rec.get("protocol_version"):
            protocol = rec["protocol_version"]
    span = ""
    if len(timestamps) >= 2:
        span = f"{ (max(timestamps) - min(timestamps)) / 1000:.1f}s"
    if getattr(args, "json", False):
        print(json.dumps({
            "session": session, "records": len(records),
            "by_type": dict(by_type), "protocol_version": protocol,
            "span_ms": (max(timestamps) - min(timestamps)) if len(timestamps) >= 2 else 0,
        }, ensure_ascii=False, indent=2, default=str))
        return 0
    print(f"[wire] 上下文记录流体检: {session}")
    print(f"  - 记录总数   : {len(records)}")
    print(f"  - 协议版本   : {protocol}")
    print(f"  - 类型分布   : {dict(sorted(by_type.items()))}")
    if span:
        print(f"  - 时间跨度   : {span}")
    return 0


def _session_query(args: Any, files: List[Path]) -> int:
    """EventSourcer API 化查询 (类型/时间窗/序号/标签多维过滤)。"""
    from ..core.event_sourcer import EventSourcer
    from ..memory.sessions import SessionStore
    session = getattr(args, "session", None)
    if not session:
        console.print("需要指定会话: tuan session query <会话ID|前缀>")
        return 2
    sessions_dir = home_dir() / "sessions"
    path = _resolve_session_path(files, session)
    if path is None:
        console.print(f"未找到会话: {session}")
        return 1
    store = SessionStore(home_dir())
    store.dir = sessions_dir
    store.file = path
    store.session_id = path.stem
    sourcer = EventSourcer(session_store=store)
    tag = getattr(args, "tag", None)
    events = sourcer.query(
        kind=getattr(args, "kind", None),
        since=getattr(args, "since", None),
        until=getattr(args, "until", None),
        since_seq=getattr(args, "since_seq", 0),
        until_seq=getattr(args, "until_seq", 0),
        tags=[tag] if tag else None,
        limit=getattr(args, "limit", 1000),
    )
    if getattr(args, "count", False):
        print(f"{len(events)}")
        return 0
    if getattr(args, "json", False):
        print(json.dumps([ev.to_dict() for ev in events],
                         ensure_ascii=False, indent=2, default=str))
        return 0
    print(f"会话 {path.stem} 查询命中 {len(events)} 条事件")
    for ev in events:
        print(f"  [#{ev.seq}] {ev.kind:<12} {ev.semantics:<8} "
              f"tags={','.join(ev.tags) or '-'}  {json.dumps(ev.payload, ensure_ascii=False, default=str)[:160]}")
    return 0


def _session_sourcer(args: Any, files: List[Path]) -> int:
    """EventSourcer 内存态分叉/回放 API (fork/list/get/replay/resume)。"""
    from ..core.event_sourcer import EventSourcer
    from ..memory.sessions import SessionStore
    sub = getattr(args, "sourcer_cmd", None)
    session = getattr(args, "session", None)
    sessions_dir = home_dir() / "sessions"
    if not session and files:
        session = files[0].stem
    path = _resolve_session_path(files, session or "")
    if path is None:
        console.print(f"未找到会话: {session}")
        return 1
    store = SessionStore(home_dir())
    store.dir = sessions_dir
    store.file = path
    store.session_id = path.stem
    sourcer = EventSourcer(session_store=_EventStoreAdapter(store))
    js = getattr(args, "json", False)
    if sub == "fork":
        fork_id = sourcer.fork(at_seq=getattr(args, "at", 0),
                               reason=getattr(args, "reason", ""))
        if js:
            print(json.dumps({"fork_id": fork_id, "at_seq": args.at,
                              "reason": args.reason}, ensure_ascii=False))
        else:
            console.print(f"[sourcer] 已在序号 {args.at} 创建分叉锚点: {fork_id} (内存态, 不落盘)")
        return 0
    if sub == "list":
        forks = sourcer.list_forks()
        if js:
            print(json.dumps([f.to_dict() for f in forks], ensure_ascii=False, indent=2, default=str))
        else:
            print(f"[sourcer] {path.stem} 内存分叉点: {len(forks)} 个")
            for f in forks:
                print(f"  {f.fork_id}  @seq={f.at_seq}  原因={f.reason or '-'}")
        return 0
    if sub == "get":
        fp = sourcer.get_fork(args.fork_id)
        if fp is None:
            console.print(f"[sourcer] 未知分叉点: {args.fork_id}")
            return 1
        if js:
            print(json.dumps(fp.to_dict(), ensure_ascii=False, indent=2, default=str))
        else:
            print(f"[sourcer] {fp.fork_id}  source={fp.source_session} "
                  f"@seq={fp.at_seq}  原因={fp.reason or '-'}")
        return 0
    if sub == "replay":
        try:
            replayed = sourcer.replay(args.fork_id,
                                      to_seq=getattr(args, "to_seq", 0))
        except ValueError as exc:
            console.print(f"[sourcer] {exc}")
            return 1
        if js:
            print(json.dumps([ev.to_dict() for ev in replayed],
                             ensure_ascii=False, indent=2, default=str))
        else:
            print(f"[sourcer] 重放 {len(replayed)} 条事件 (分叉 {args.fork_id})")
            for ev in replayed:
                print(f"  [#{ev.seq}] {ev.kind}  {json.dumps(ev.payload, ensure_ascii=False, default=str)[:120]}")
        return 0
    if sub == "resume":
        try:
            messages = sourcer.resume_from(args.fork_id)
        except ValueError as exc:
            console.print(f"[sourcer] {exc}")
            return 1
        if js:
            print(json.dumps(messages, ensure_ascii=False, indent=2, default=str))
        else:
            print(f"[sourcer] 从分叉 {args.fork_id} 恢复 {len(messages)} 条消息")
            for m in messages:
                who = "用户" if m.get("role") == "user" else "青小团"
                print(f"  {who}: {str(m.get('content', ''))[:120]}")
        return 0
    console.print("用法: tuan session sourcer fork|list|get|replay|resume")
    return 2


def _session_digest(args: Any, files: List[Path]) -> int:
    """无 LLM 的结构化摘要提取预览 (上下文压缩会保留哪些关键信息)。"""
    from ..core.agent_helpers import summarize_messages
    from ..memory.sessions import SessionStore
    session = getattr(args, "session", None)
    if not session:
        console.print("需要指定会话: tuan session digest <会话ID|前缀>")
        return 2
    path = _resolve_session_path(files, session)
    if path is None:
        console.print(f"未找到会话: {session}")
        return 1
    messages = SessionStore.load_messages(path)
    tail = getattr(args, "tail", 0)
    if tail:
        messages = messages[-tail:]
    summary = summarize_messages(messages)
    if getattr(args, "json", False):
        print(json.dumps({"session": path.stem, "messages": len(messages),
                          "summary": summary}, ensure_ascii=False, indent=2))
        return 0
    print(f"[digest] 会话 {path.stem} 摘要预览 ({len(messages)} 条消息):")
    print(summary)
    return 0


def _session_traj_dispatch(sub: str, args: Any) -> int:
    """trajectory 子命令分发器 (analyze/timeline/fork/snapshots)。"""
    if sub == "analyze":
        return _session_traj_analyze(args)
    if sub == "timeline":
        return _session_traj_timeline(args)
    if sub == "fork":
        return _session_traj_fork(args)
    if sub == "snapshots":
        return _session_traj_snapshots(args)
    return _session_traj_analyze(args)


def _session_traj_analyze(args: Any) -> int:
    """轨迹分析: 工具延迟/状态/来源/安全事件统计。"""
    from ..core.trajectory_replay import TrajectoryReplay
    replay = TrajectoryReplay(session_dir=home_dir() / "sessions")
    stats = replay.analyze(args.session)
    if getattr(args, "json", False):
        print(json.dumps(stats.to_dict(), ensure_ascii=False, indent=2))
        return 0
    print(f"轨迹分析 · {args.session}")
    print(f"  - 总事件   : {stats.total_events}")
    print(f"  - 总耗时   : {stats.total_duration_ms / 1000:.1f}s")
    print(f"  - 类型分布 : {dict(sorted(stats.by_type.items()))}")
    if stats.by_tool:
        print(f"  - 工具分布 : {dict(sorted(stats.by_tool.items(), key=lambda kv: -kv[1]))}")
    if stats.by_status:
        print(f"  - 状态分布 : {dict(sorted(stats.by_status.items()))}")
    if stats.by_source:
        print(f"  - 来源分布 : {dict(sorted(stats.by_source.items(), key=lambda kv: -kv[1]))}")
    if stats.tool_latencies:
        avg = {k: sum(v) / len(v) for k, v in stats.tool_latencies.items()}
        print(f"  - 工具均延迟: " + ", ".join(f"{k}={v:.0f}ms" for k, v in sorted(avg.items())))
    print(f"  - 安全事件 : {stats.security_events}  拒绝: {stats.denied_events}  错误: {stats.error_events}")
    return 0


def _session_traj_timeline(args: Any) -> int:
    """导出事件时间线 (Markdown)。"""
    from ..core.trajectory_replay import TrajectoryReplay
    replay = TrajectoryReplay(session_dir=home_dir() / "sessions")
    text = replay.export_timeline(args.session, last_n=getattr(args, "limit", 50))
    if getattr(args, "json", False):
        events = replay.replay(args.session, last_n=getattr(args, "limit", 50))
        print(json.dumps([ev.to_dict() for ev in events], ensure_ascii=False, indent=2, default=str))
        return 0
    print(text)
    return 0


def _session_traj_fork(args: Any) -> int:
    """从断点分叉出新回放分支 (快照落盘)。"""
    from ..core.trajectory_replay import TrajectoryReplay
    replay = TrajectoryReplay(session_dir=home_dir() / "sessions")
    try:
        snap = replay.fork(args.session, at_seq=args.at, label=getattr(args, "label", ""))
    except ValueError as exc:
        console.print(f"[trajectory] {exc}")
        return 1
    if getattr(args, "json", False):
        print(json.dumps({
            "snapshot_id": f"{snap.session_id}_fork_{snap.fork_point}",
            "session_id": snap.session_id,
            "fork_point": snap.fork_point, "label": snap.label,
            "events": len(snap.events),
        }, ensure_ascii=False, indent=2, default=str))
    else:
        console.print(f"[trajectory] 已分叉 {snap.session_id} @seq={snap.fork_point} "
                      f"-> 快照 {snap.session_id}_fork_{snap.fork_point} ({len(snap.events)} 事件)")
    return 0


def _session_traj_snapshots(args: Any) -> int:
    """列出已保存的分叉快照。"""
    from ..core.trajectory_replay import TrajectoryReplay
    replay = TrajectoryReplay(session_dir=home_dir() / "sessions")
    snaps = replay.list_snapshots()
    if getattr(args, "json", False):
        print(json.dumps(snaps, ensure_ascii=False, indent=2, default=str))
    else:
        if not snaps:
            console.print("[trajectory] 没有已保存的快照")
            return 0
        print(f"[trajectory] 已保存 {len(snaps)} 个快照:")
        for s in snaps:
            print(f"  {s['id']}  {s['session_id']} @seq={s['fork_point']} "
                  f"({s['event_count']} 事件)  标签={s.get('label') or '-'}")
    return 0
