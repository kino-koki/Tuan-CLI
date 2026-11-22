# -*- coding: utf-8 -*-
"""reach 工具插件 —— Agent 工具面上的多平台读取入口。

tuan-reach 能力 (Agent-Reach 理念自研) 的工具面暴露:
  * reach_fetch : 按 channel→backend 回退链读取 URL/目标;
  * reach_doctor: 全频道健康自检。
纯只读, Plan 模式放行。
"""

from __future__ import annotations

from typing import Any

from ..core.kernel import Kernel, Plugin
from .base import Tool, ToolContext, string_prop

import logging
log = logging.getLogger(__name__)


def reach_fetch(ctx: ToolContext, target: str, channel: str = "") -> str:
    """经 tuan-reach 能力层读取 URL/目标 (自动路由频道与后端回退)。"""
    from ..reach import fetch

    res = fetch(target, channel=channel or None)
    return res.summary()


def reach_doctor(ctx: ToolContext) -> str:
    """tuan-reach 全频道健康自检。"""
    from ..reach import doctor, render

    return render(doctor())


def reach_channels(ctx: ToolContext) -> str:
    """列出 tuan-reach 频道与后端回退链。"""
    from ..reach import list_channels

    lines = ["tuan-reach 频道:"]
    for c in list_channels():
        lines.append(f"  {c['name']:10} {c['description']}  [{ ' -> '.join(c['backends']) }]")
    return "\n".join(lines)


class ReachPlugin(Plugin):
    name = "tools.reach"
    requires = ["tool_registry"]

    def activate(self, kernel: Kernel) -> None:
        config = kernel.get("config")
        if config and not config.get("tools.reach.enabled", True):
            return
        registry = kernel.require("tool_registry")
        registry.register(Tool(
            name="reach_fetch",
            description=(
                "多平台联网读取 (tuan-reach 能力层): 自动识别 GitHub/YouTube/B站/"
                "RSS/通用网页并走对应后端回退链, 返回结构化文本。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "target": string_prop("要读取的 URL 或目标"),
                    "channel": string_prop("强制指定频道 (可选): web/github/youtube/bilibili/rss"),
                },
                "required": ["target"],
            },
            handler=reach_fetch, group="web", read_only=True,
        ))
        registry.register(Tool(
            name="reach_doctor",
            description="tuan-reach 频道健康自检: 每个频道的后端可达性与失败原因。",
            parameters={"type": "object", "properties": {}},
            handler=reach_doctor, group="web", read_only=True,
        ))


__all__ = ["ReachPlugin", "reach_fetch", "reach_doctor", "reach_channels"]
