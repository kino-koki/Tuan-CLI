# -*- coding: utf-8 -*-
"""tuan-reach 基础类型 —— channel / backend / 结果。

核心理念 (对标 Agent-Reach, 完全自研):
  * 能力层而非又一个工具: 统一路由, 读取交给各 channel 的 backend;
  * 每个 channel 是**有序 backend 列表** (主用 + 备胎), 某后端失效自动切换;
  * 一切尝试留痕 (attempts), 失败可观测。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

# backend 函数签名: (target) -> (ok, text, meta)
BackendFn = Callable[[str], Tuple[bool, str, Dict[str, Any]]]


@dataclass
class Backend:
    """一个具体的读取后端 (如 github-API、youtube-oembed)。"""
    name: str
    fn: BackendFn
    note: str = ""  # 一句话说明 (doctor 输出用)


@dataclass
class Channel:
    """一个平台频道: 匹配规则 + 有序后端回退链。"""
    name: str
    description: str
    match: Callable[[str], bool]
    backends: List[Backend]
    probe_target: str = ""  # doctor 用轻量探测目标; 空则用首个到达的请求

    def applies(self, target: str) -> bool:
        try:
            return bool(self.match(target))
        except Exception:  # noqa: BLE001
            return False


@dataclass
class ReachResult:
    """统一读取结果: ok + 文本 + 尝试留痕。"""
    ok: bool
    text: str
    channel: str = ""
    backend: str = ""
    meta: Dict[str, Any] = field(default_factory=dict)
    attempts: List[Dict[str, Any]] = field(default_factory=list)
    error: str = ""

    def summary(self) -> str:
        head = f"[{self.channel}/{self.backend}] " if self.channel else ""
        if self.ok:
            return f"{head}读取成功\n{self.text}"
        tries = "; ".join(
            f"{a.get('channel')}/{a.get('backend')}: {a.get('error', '失败')}"
            for a in self.attempts) or "无可用后端"
        return f"{head}读取失败 ({tries})"


__all__ = ["Backend", "Channel", "ReachResult", "BackendFn"]
