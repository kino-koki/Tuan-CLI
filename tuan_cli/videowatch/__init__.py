# -*- coding: utf-8 -*-
"""tuan-watch —— 给 Agent 一双"看视频的眼睛" (claude-video 理念, 完全自研)。

能力链: 源解析 (本地/yt-dlp/直链) → ffprobe 元数据 → 字幕优先转写
(sidecar → 内嵌轨 → Whisper) → 帧预算抽帧 (16x16 灰度去重) → 观看包落盘。

公开 API:
    watch_video(...)  执行观看, 返回结构化结果 (fail-closed)
    summarize(...)    渲染为可读摘要
    capability_report() 依赖自检
"""
from ._ff import capability_report
from .watch import summarize, watch_video

__all__ = ["watch_video", "summarize", "capability_report"]
