# -*- coding: utf-8 -*-
"""tuan-reach doctor —— 每频道健康自检 (对标 Agent-Reach 的可观测理念)。

对每个频道用轻量探测目标跑一遍**首个可用后端**链, 输出:
  频道 / 后端 / 结果 / 耗时 / 失败原因。网络不可达时如实报告, 不粉饰。
"""
from __future__ import annotations

import time
from typing import Any, Callable, Dict, List

from .base import Channel
from .channels import build_channels


def probe_channel(channel: Channel, timeout: float = 15.0) -> Dict[str, Any]:
    """探测单个频道: 依次尝试后端链, 返回首个成功或全部失败记录。"""
    target = channel.probe_target
    if not target:
        return {"channel": channel.name, "status": "skip",
                "note": "无轻量探测目标 (按需可达)", "backends": []}
    tried: List[Dict[str, Any]] = []
    for backend in channel.backends:
        t0 = time.perf_counter()
        try:
            ok, _text, meta = backend.fn(target)
        except Exception as exc:  # noqa: BLE001
            ok, _text, meta = False, "", {"reason": f"{type(exc).__name__}: {exc}"}
        ms = int((time.perf_counter() - t0) * 1000)
        tried.append({"backend": backend.name, "ok": bool(ok), "ms": ms,
                      "error": "" if ok else str(meta.get("reason", "失败"))})
        if ok:
            return {"channel": channel.name, "status": "ok",
                    "backend": backend.name, "ms": ms, "backends": tried}
    return {"channel": channel.name, "status": "fail", "backends": tried}


def doctor(prober: Callable[[Channel], Dict[str, Any]] = probe_channel) -> Dict[str, Any]:
    """全频道体检。prober 可注入 (测试用)。"""
    channels = build_channels()
    rows = [prober(c) for c in channels]
    ok_n = sum(1 for r in rows if r["status"] == "ok")
    return {"total": len(rows), "ok": ok_n, "fail": sum(1 for r in rows if r["status"] == "fail"),
            "skip": sum(1 for r in rows if r["status"] == "skip"), "channels": rows}


def render(report: Dict[str, Any]) -> str:
    """doctor 报告 → 文本 (CLI / 工具输出用)。"""
    skip_n = report.get("skip", 0)
    head = (f"tuan-reach 体检: {report['ok']} 可用 / {report['fail']} 失败"
            + (f" / {skip_n} 跳过" if skip_n else "")
            + f" (共 {report['total']} 频道)")
    lines = [head]
    for r in report["channels"]:
        mark = {"ok": "OK ", "fail": "FAIL", "skip": "SKIP"}.get(r["status"], "??")
        base = f"  [{mark}] {r['channel']}"
        if r["status"] == "ok":
            lines.append(f"{base}  经 {r.get('backend')} ({r.get('ms')}ms)")
        elif r["status"] == "skip":
            lines.append(f"{base}  {r.get('note', '')}")
        else:
            reasons = "; ".join(f"{b['backend']}: {b['error'] or '失败'}" for b in r.get("backends", []))
            lines.append(f"{base}  {reasons or '全部后端失败'}")
    return "\n".join(lines)


__all__ = ["doctor", "probe_channel", "render"]
