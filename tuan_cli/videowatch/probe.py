# -*- coding: utf-8 -*-
"""视频元数据探测 —— ffprobe 结构化读取 (时长/分辨率/帧率/音轨/字幕轨)。"""
from __future__ import annotations

from typing import Any, Dict, Optional

from ._ff import ffprobe_json


def probe_video(path: str) -> Dict[str, Any]:
    """探测视频元数据, 返回结构化 dict。

    失败 (无 ffprobe / 非媒体文件) 时返回 {"error": ...}, 调用方 fail-closed。
    """
    data: Optional[dict] = ffprobe_json(path)
    if data is None:
        return {"error": "ffprobe 不可用或无法解析该媒体文件"}

    fmt = data.get("format") or {}
    streams = data.get("streams") or []

    def _num(v: Any) -> Optional[float]:
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    duration = _num(fmt.get("duration"))
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    subs = [s for s in streams if s.get("codec_type") == "subtitle"]

    fps: Optional[float] = None
    if video:
        rate = str(video.get("avg_frame_rate") or video.get("r_frame_rate") or "")
        if "/" in rate:
            num, den = rate.split("/", 1)
            n, d = _num(num), _num(den)
            if n is not None and d not in (None, 0.0):
                fps = n / d

    meta: Dict[str, Any] = {
        "path": str(path),
        "duration": round(duration, 3) if duration is not None else None,
        "width": (video or {}).get("width"),
        "height": (video or {}).get("height"),
        "fps": round(fps, 3) if fps else None,
        "codec": (video or {}).get("codec_name"),
        "has_audio": audio is not None,
        "audio_codec": (audio or {}).get("codec_name"),
        "subtitle_streams": len(subs),
        "container": fmt.get("format_name"),
        "size_bytes": _num(fmt.get("size")),
    }
    if duration is None:
        meta["error"] = "无法读取时长 (文件损坏或不是视频)"
    return meta


__all__ = ["probe_video"]
