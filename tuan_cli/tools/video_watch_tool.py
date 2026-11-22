# -*- coding: utf-8 -*-
"""video_watch 工具插件 —— Agent 工具面上的"看视频"入口。

tuan-watch 能力 (claude-video 理念自研) 的工具面暴露:
  * video_watch: 观看本地/URL 视频, 返回转写 + 关键帧 + 元数据摘要。
    只写 .tuan/watch/ 观看包缓存, 不改用户工作区状态, Plan 模式放行。
"""

from __future__ import annotations

from typing import Any

from ..core.kernel import Kernel, Plugin
from .base import Tool, ToolContext, string_prop

import logging
log = logging.getLogger(__name__)


def video_watch(ctx: ToolContext, source: str, question: str = "",
                detail: str = "balanced", start: float = 0.0,
                end: float = 0.0, no_dedup: bool = False) -> str:
    """观看视频: 字幕优先转写 + 帧预算抽帧 (去重), 返回观看包摘要。"""
    from ..videowatch import summarize, watch_video

    kwargs: dict = {}
    if detail:
        kwargs["detail"] = detail
    if start:
        kwargs["start"] = float(start)
    if end:
        kwargs["end"] = float(end)
    if no_dedup:
        kwargs["no_dedup"] = True
    if question:
        kwargs["question"] = question
    result = watch_video(
        source, workspace=ctx.workspace or ".", **kwargs,
    )
    return summarize(result)


class VideoWatchPlugin(Plugin):
    name = "tools.video_watch"
    requires = ["tool_registry"]

    def activate(self, kernel: Kernel) -> None:
        config = kernel.get("config")
        if config and not config.get("tools.video_watch.enabled", True):
            return
        registry = kernel.require("tool_registry")
        registry.register(Tool(
            name="video_watch",
            description=(
                "观看视频 (本地文件或 URL): 提取字幕/转写文本 + 按档位抽关键帧"
                "(自动去重), 返回带时间戳的观看摘要。可选依赖 ffmpeg/yt-dlp/whisper。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "source": string_prop("视频本地路径或 URL"),
                    "question": string_prop("观看时重点回答的问题 (可选)"),
                    "detail": {
                        "type": "string",
                        "enum": ["transcript", "swift", "balanced", "deep"],
                        "description": "观看档位: transcript 只看字幕 / swift 24帧 / balanced 48帧 / deep 96帧",
                    },
                    "start": {"type": "number", "description": "起始秒 (可选, 只看片段)"},
                    "end": {"type": "number", "description": "结束秒 (可选, 只看片段)"},
                    "no_dedup": {"type": "boolean", "description": "关闭帧去重 (默认开启)"},
                },
                "required": ["source"],
            },
            handler=video_watch, group="media", read_only=True,
        ))


__all__ = ["VideoWatchPlugin", "video_watch"]
