# -*- coding: utf-8 -*-
"""tuan-reach 路由与回退注册表。

fetch(target) 流程:
  1. route: 按 channel.match 选频道 (未命中 → web 兜底);
  2. 依次尝试该频道有序 backend 链, 首个成功即返回;
  3. 全部失败 → ok=False, attempts 留痕每个后端的失败原因。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from .base import Channel, ReachResult
from .channels import build_channels

_CHANNELS: Optional[List[Channel]] = None


def _channels() -> List[Channel]:
    global _CHANNELS
    if _CHANNELS is None:
        _CHANNELS = build_channels()
    return _CHANNELS


def list_channels() -> List[Dict[str, Any]]:
    """频道清单 (名称/描述/后端链), 供 /reach channels 与 doctor。"""
    return [{"name": c.name, "description": c.description,
             "backends": [b.name for b in c.backends]} for c in _channels()]


def route(target: str) -> Channel:
    """为目标选择频道: 首个 match 的频道; 都不中 → web 兜底。"""
    for c in _channels():
        if c.name != "web" and c.applies(target):
            return c
    return _channels()[-1]


def fetch(target: str, channel: Optional[str] = None) -> ReachResult:
    """统一读取入口: 路由 → 有序回退 → 留痕结果。"""
    target = (target or "").strip()
    if not target:
        return ReachResult(ok=False, text="", error="目标为空")
    ch: Optional[Channel] = None
    if channel:
        ch = next((c for c in _channels() if c.name == channel.lower()), None)
        if ch is None:
            known = ", ".join(c.name for c in _channels())
            return ReachResult(ok=False, text="", error=f"未知频道 {channel!r} (可用: {known})")
    else:
        ch = route(target)
    attempts: List[Dict[str, Any]] = []
    for backend in ch.backends:
        try:
            ok, text, meta = backend.fn(target)
        except Exception as exc:  # noqa: BLE001 - 单后端异常不炸能力层
            ok, text, meta = False, "", {"reason": f"{type(exc).__name__}: {exc}"}
        attempts.append({"channel": ch.name, "backend": backend.name, "ok": bool(ok),
                         "error": "" if ok else str(meta.get("reason", "失败"))})
        if ok:
            return ReachResult(ok=True, text=text, channel=ch.name,
                               backend=backend.name, meta=meta, attempts=attempts)
    return ReachResult(ok=False, text="", channel=ch.name, attempts=attempts,
                       error="所有后端均失败")


__all__ = ["fetch", "route", "list_channels"]
