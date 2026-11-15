"""`tuan telemetry` —— 遥测可观测性 (第 44 个独特功能)。

Claude Code 的 Telemetry 是「黑盒上传云端」: 你既看不到 span 树, 也无法在
本地查询/导出。Tuan-CLI 的 TelemetryCollector (core/telemetry.py) 是本地纯
Python 实现, 本命令把这份遥测变成**可查询、可导出、跨进程可见**的第一方视图:

    tuan telemetry stats                 # 本进程内存统计 + 磁盘导出文件盘点
    tuan telemetry spans  [--n 20]       # 最近 N 条 span (内存 + 磁盘)
    tuan telemetry export [--path F]     # 导出为 JSONL (默认 ~/.tuan/telemetry/)
    tuan telemetry export --json         # 机器可读 (CI / SIEM 消费)

差异化价值:
- 本地优先: 遥测不离开机器, 全部落在 ~/.tuan/telemetry/ (纯 JSONL, 零依赖)。
- 跨进程可观测: 独立 CLI 进程看不到别的进程的内存态, 但能读磁盘已导出的
  JSONL —— 本命令把「磁盘导出」也纳入统计/查询, 让长时间运行的 agent
  (自动导出阈值 500 span) 的遥测仍然可见。
- 可导出: --path 指定落盘位置, 供外部 SIEM / 成本归因消费。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List

from ..config import home_dir
from ..ui.plain_console import console


def _scan_exported(home: Path) -> List[Dict[str, Any]]:
    """盘点 ~/.tuan/telemetry/ 下已导出的 JSONL 文件 (跨进程可见的遥测)。

    返回每份文件的 {file, size, spans, first_ts, last_ts}; 跳过坏文件。
    """
    telemetry_dir = Path(home) / "telemetry"
    out: List[Dict[str, Any]] = []
    if not telemetry_dir.is_dir():
        return out
    for jl in sorted(telemetry_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime):
        try:
            size = jl.stat().st_size
            spans = 0
            first_ts = None
            last_ts = None
            with jl.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except Exception:  # noqa: BLE001 - 坏行跳过
                        continue
                    spans += 1
                    ts = rec.get("start_time")
                    if isinstance(ts, (int, float)):
                        first_ts = ts if first_ts is None else first_ts
                        last_ts = ts
            out.append({
                "file": jl.name,
                "size_bytes": size,
                "spans": spans,
                "first_ts": first_ts,
                "last_ts": last_ts,
            })
        except OSError:
            continue
    return out


def _load_exported_spans(home: Path, limit: int) -> List[Dict[str, Any]]:
    """从磁盘导出的 JSONL 读取最近 limit 条 span (跨进程可见)。

    按文件 mtime 升序读取所有导出文件, 保留尾部 limit 条 (最新的在后)。
    """
    telemetry_dir = Path(home) / "telemetry"
    if not telemetry_dir.is_dir():
        return []
    all_spans: List[Dict[str, Any]] = []
    for jl in sorted(telemetry_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime):
        try:
            with jl.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except Exception:  # noqa: BLE001
                        continue
                    if isinstance(rec, dict):
                        all_spans.append(rec)
        except OSError:
            continue
    return all_spans[-limit:] if limit > 0 else all_spans


def _cmd_telemetry_stats(args: Any, home: Path, json_mode: bool) -> int:
    """telemetry stats: 本进程内存统计 + 磁盘导出盘点。"""
    from ..core.telemetry import TelemetryCollector

    tc = TelemetryCollector(home)
    stats = tc.get_stats()
    exported = _scan_exported(home)
    total_exported = sum(e["spans"] for e in exported)

    if json_mode:
        sys.stdout.write(json.dumps({
            "memory": stats,
            "exported_files": exported,
            "exported_total_spans": total_exported,
        }, ensure_ascii=False, indent=2) + "\n")
        return 0

    console.print("[bold]遥测统计[/bold] (本进程 + 磁盘导出)")
    console.print(
        f"  span: {stats['total_spans']}  trace: {stats['total_traces']}  "
        f"错误: {stats['total_errors']} (error_rate {stats['error_rate']}%)"
    )
    console.print(
        f"  token: {stats['total_tokens']}  工具调用: {stats['total_tool_calls']}  "
        f"活跃 span: {stats['active_spans']}"
    )
    console.print(
        f"  平均延迟: 工具 {stats['avg_tool_latency_ms']}ms / 模型 {stats['avg_model_latency_ms']}ms"
    )
    if not stats["total_spans"] and not total_exported:
        console.print("\n[dim]本进程无 span (CLI 独立进程), 磁盘也无导出文件。[/dim]")
        console.print("[dim]提示: 运行 `tuan chat` 产生遥测; 长时间 agent 会话达 500 span 自动导出。[/dim]")
        return 0
    if exported:
        console.print(f"\n[bold]磁盘已导出 {len(exported)} 份文件, 共 {total_exported} 条 span:[/bold]")
        for e in exported:
            console.print(
                f"  {e['file']}  ({e['size_bytes']} B, {e['spans']} 条)"
            )
    return 0


def _cmd_telemetry_spans(args: Any, home: Path, json_mode: bool) -> int:
    """telemetry spans: 最近 N 条 span (内存优先, 回退磁盘)。"""
    from ..core.telemetry import TelemetryCollector

    n = int(getattr(args, "n", 20) or 20)
    tc = TelemetryCollector(home)
    spans = tc.get_recent_spans(n)
    source = "内存"
    if not spans:
        spans = _load_exported_spans(home, n)
        source = "磁盘导出"

    if json_mode:
        sys.stdout.write(json.dumps({
            "source": source,
            "count": len(spans),
            "spans": spans,
        }, ensure_ascii=False, indent=2) + "\n")
        return 0

    if not spans:
        console.print("[dim]无 span (内存与磁盘导出均为空)。运行 `tuan chat` 产生遥测。[/dim]")
        return 0
    console.print(f"[bold]最近 {len(spans)} 条 span[/bold] (来源: {source})\n")
    for s in spans:
        name = s.get("name", "?")
        status = s.get("status", "?")
        dur = s.get("duration_ms", 0.0)
        color = {"ok": "green", "error": "red", "cancelled": "yellow"}.get(status, "dim")
        span_id = str(s.get("span_id", ""))[:8]
        console.print(
            f"  [{color}]{status:>8}[/{color}]  {name:<28} "
            f"{float(dur):>8.1f}ms  {span_id}"
        )
    console.print("\n提示: tuan telemetry export --path <file> 导出完整 JSONL")
    return 0


def _cmd_telemetry_export(args: Any, home: Path, json_mode: bool) -> int:
    """telemetry export: 导出全部 span 为 JSONL (默认 ~/.tuan/telemetry/)。"""
    from ..core.telemetry import TelemetryCollector

    tc = TelemetryCollector(home)
    path_arg = getattr(args, "path", None)
    export_path = Path(path_arg) if path_arg else None
    count = tc.export_jsonl(export_path)
    out_path = export_path or (Path(home) / "telemetry" / f"spans_{int(__import__('time').time())}.jsonl")

    if json_mode:
        sys.stdout.write(json.dumps({
            "exported": count,
            "path": str(out_path),
        }, ensure_ascii=False, indent=2) + "\n")
        return 0

    if count == 0:
        console.print("[dim]无可导出的 span (本进程内存为空)。[/dim]")
        console.print("[dim]提示: 跨进程已导出的文件在 ~/.tuan/telemetry/ 可查。[/dim]")
        return 0
    console.print(f"已导出 {count} 条 span → {out_path}")
    return 0


def _cmd_telemetry_otlp(args: Any, home: Path, json_mode: bool) -> int:
    """telemetry otlp: OTLP 导出/自动导出判断/清空 (第 64 个独特功能)。

    暴露 export_to_otlp / auto_export / should_auto_export / clear:
    - 默认: 判断是否应自动导出 (span 数 >= 阈值 500) + 自动导出落盘数;
    - --endpoint <url>: 把 span 转 OTLP 事件投递给指定 HTTP 接收端
      (尽力而为, 失败静默降级, 不阻断);
    - --clear: 清空本进程遥测缓冲 (长时间会话防泄漏的运维入口)。

    差异化: Claude Code 遥测只能上传其私有云端; Tuan-CLI 可投递到任意
    OTLP 兼容后端 (如自建 Jaeger/OTel Collector), 遥测数据归用户所有。
    """
    from ..core.telemetry import TelemetryCollector

    tc = TelemetryCollector(home)
    endpoint = getattr(args, "endpoint", None)
    do_clear = bool(getattr(args, "clear", False))

    if do_clear:
        tc.clear()
        if json_mode:
            sys.stdout.write(json.dumps({"cleared": True},
                                        ensure_ascii=False, indent=2) + "\n")
            return 0
        console.print("[green]✓ 已清空本进程遥测缓冲[/green]")
        console.print("  [dim](长时间 agent 会话后清空, 防内存/磁盘无限增长)[/dim]")
        return 0

    if endpoint:
        # 尽力而为投递 OTLP 事件到指定后端
        import asyncio

        class _HttpTransport:
            def __init__(self, url: str) -> None:
                self.url = url

            async def send(self, events: List[Any]) -> None:
                import urllib.request
                payload = {
                    "resourceSpans": [{
                        "scopeSpans": [{
                            "spans": [{
                                "name": e.event,
                                "startTimeUnixNano": int(float(e.timestamp or 0) * 1e9),
                                "endTimeUnixNano": int(float(e.timestamp or 0) * 1e9),
                                "attributes": [
                                    {"key": k,
                                     "value": {"stringValue": str(v)}}
                                    for k, v in (e.properties or {}).items()
                                ],
                            } for e in events],
                        }],
                    }],
                }
                req = urllib.request.Request(
                    self.url, data=json.dumps(payload).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                await asyncio.to_thread(urllib.request.urlopen, req, timeout=5.0)

        transport = _HttpTransport(endpoint)
        n = tc.export_to_otlp(transport)
        if json_mode:
            sys.stdout.write(json.dumps({
                "exported_events": n,
                "endpoint": endpoint,
            }, ensure_ascii=False, indent=2) + "\n")
            return 0
        console.print(f"[green]✓ OTLP 投递完成[/green] {n} 个事件 → {endpoint}")
        console.print("  [dim](尽力而为: 失败静默降级, 不阻断主流程)[/dim]")
        return 0

    # 默认: 自动导出判断 + 落盘
    should = tc.should_auto_export()
    auto_n = tc.auto_export()
    stats = tc.get_stats()
    if json_mode:
        sys.stdout.write(json.dumps({
            "should_auto_export": should,
            "auto_exported": auto_n,
            "threshold": TelemetryCollector._AUTO_EXPORT_THRESHOLD,
            "total_spans": stats.get("total_spans", 0),
        }, ensure_ascii=False, indent=2) + "\n")
        return 0

    console.print("[bold]OTLP 自动导出检查[/bold]")
    console.print(
        f"  当前 span: {stats.get('total_spans', 0)}  "
        f"(阈值 {TelemetryCollector._AUTO_EXPORT_THRESHOLD})"
    )
    if should:
        console.print(f"  [yellow]⚠ 已达阈值, 应自动导出[/yellow] (本次落盘 {auto_n} 条)")
        console.print("  [dim]提示: --endpoint <url> 投递 OTLP 后端; --clear 清空缓冲[/dim]")
    else:
        console.print("  [green]✓ 未达阈值, 无需自动导出[/green]")
    console.print("\n[dim]提示: --endpoint <url> 把 span 投递 OTLP 兼容后端 "
                  "(如自建 Jaeger/OTel Collector)[/dim]")
    return 0


def cmd_telemetry(args: Any) -> int:
    """`tuan telemetry` 入口: 遥测可观测性 (stats/spans/export/otlp)。"""
    home = Path(home_dir())
    sub = getattr(args, "telemetry_cmd", None) or "stats"
    json_mode = bool(getattr(args, "json", False))

    if sub == "spans":
        return _cmd_telemetry_spans(args, home, json_mode)
    if sub == "export":
        return _cmd_telemetry_export(args, home, json_mode)
    if sub == "otlp":
        return _cmd_telemetry_otlp(args, home, json_mode)
    # 默认 stats
    return _cmd_telemetry_stats(args, home, json_mode)


# 注册本模块的命令函数到全局注册表
from .parser import _register_command  # noqa: E402

_register_command("cmd_telemetry", ".cmd_telemetry")
