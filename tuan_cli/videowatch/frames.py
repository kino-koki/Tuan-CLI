# -*- coding: utf-8 -*-
"""帧预算 + 抽帧 + 去重 —— tuan-watch 的 token 成本闸门。

设计要点 (自研实现, 理念对标 claude-video 的帧预算/帧去重):
  * 档位预算: 视频越长, 单位时长抽帧越少, 且有硬上限 —— 防止长视频烧爆上下文;
  * 帧去重: 每帧缩成 16x16 灰度图, 与**上一张被保留帧**比较平均亮度差
    (非相邻帧两两比较), 低于阈值判为近重复丢弃 —— 能捕捉缓慢渐变,
    静态画面不重复烧 token;
  * ffmpeg 缺失 → 明确报错, 不假成功。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from ._ff import ffmpeg_run


# 档位: (每秒抽帧率, 最少帧数, 最大帧数)
# transcript 档 = 0 帧 (只看字幕, 不抽帧)。
TIERS: Dict[str, Dict[str, float]] = {
    "transcript": {"rate": 0.0, "min": 0, "cap": 0},
    "swift":      {"rate": 0.25, "min": 6, "cap": 24},
    "balanced":   {"rate": 0.5, "min": 8, "cap": 48},
    "deep":       {"rate": 1.0, "min": 12, "cap": 96},
}

DEFAULT_TIER = "balanced"
DEDUP_THRESHOLD = 2.0   # 16x16 灰度平均亮度差 (0-255), 低于此值判近重复
THUMB_SIZE = 16         # 去重缩略图边长
FRAME_WIDTH = 640       # 输出帧等比缩放宽度


def normalize_tier(detail: Optional[str]) -> str:
    d = (detail or DEFAULT_TIER).strip().lower()
    return d if d in TIERS else DEFAULT_TIER


def plan_timestamps(duration: float, tier: str,
                    start: Optional[float] = None,
                    end: Optional[float] = None,
                    max_frames: Optional[int] = None) -> List[float]:
    """按档位预算规划采样时间点 (均匀布点, 含段首不含段尾)。

    duration<=0 或 transcript 档 → 空列表。
    """
    t = TIERS[tier]
    if duration <= 0 or t["cap"] <= 0:
        return []
    s = max(0.0, float(start) if start is not None else 0.0)
    e = min(duration, float(end) if end is not None else duration)
    if e <= s:
        return []
    span = e - s
    n = int(span * t["rate"])
    n = max(n, int(t["min"]))
    n = min(n, int(t["cap"]))
    if max_frames is not None and max_frames > 0:
        n = min(n, int(max_frames))
    if n <= 0:
        return []
    # 均匀布点: t_i = s + span * i / n (i=0..n-1), 避开段尾越界
    return [round(s + span * i / n, 3) for i in range(n)]


def _gray16(jpg_path: Path, timeout: float = 30.0) -> Optional[bytes]:
    """把单帧 JPEG 缩成 16x16 灰度原始字节 (16*16=256B), 供去重比较。

    优先 PIL (省一次进程); 无 PIL 用 ffmpeg。失败 → None (该帧不参与去重)。
    """
    try:
        from PIL import Image  # type: ignore
        with Image.open(jpg_path) as im:
            g = im.convert("L").resize((THUMB_SIZE, THUMB_SIZE))
            return g.tobytes()
    except Exception:  # noqa: BLE001 - 回退 ffmpeg
        pass
    import subprocess as _sp
    from ._ff import _CREATE_NO_WINDOW
    try:
        proc = _sp.run(
            ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
             "-i", str(jpg_path), "-vf", f"scale={THUMB_SIZE}:{THUMB_SIZE}",
             "-pix_fmt", "gray", "-f", "rawvideo", "-"],
            capture_output=True, timeout=timeout, creationflags=_CREATE_NO_WINDOW,
        )
    except Exception:  # noqa: BLE001 - 进程失败该帧不参与去重
        return None
    raw = proc.stdout or b""
    if proc.returncode != 0 or len(raw) < THUMB_SIZE * THUMB_SIZE:
        return None
    return raw[: THUMB_SIZE * THUMB_SIZE]


def mean_abs_diff(a: Optional[bytes], b: Optional[bytes]) -> Optional[float]:
    """两张 16x16 灰度图的平均绝对差 (0-255)。任一缺失 → None。"""
    if a is None or b is None or len(a) != len(b) or len(a) == 0:
        return None
    total = sum(abs(x - y) for x, y in zip(a, b))
    return total / len(a)


def extract_frames(video_path: str, timestamps: List[float], out_dir: Path,
                   dedup: bool = True, width: int = FRAME_WIDTH) -> Dict[str, Any]:
    """按时间点抽帧 (JPEG), 可选去重。返回 {frames: [{t, path, kept}], dropped}。

    单帧失败跳过并计数, 不中断整批 (长视频部分时间点 seek 失败是常态)。
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    frames: List[Dict[str, Any]] = []
    last_thumb: Optional[bytes] = None
    dropped = 0
    failed = 0
    for i, t in enumerate(timestamps):
        jpg = out_dir / f"frame_{i:04d}_{t:.2f}s.jpg"
        rc, _err = ffmpeg_run([
            "-ss", f"{t:.3f}", "-i", str(video_path),
            "-frames:v", "1", "-vf", f"scale={width}:-2", "-q:v", "3",
            "-y", str(jpg),
        ], timeout=60)
        if rc != 0 or not jpg.exists():
            failed += 1
            continue
        thumb = _gray16(jpg) if dedup else None
        if dedup and last_thumb is not None:
            diff = mean_abs_diff(thumb, last_thumb)
            if diff is not None and diff < DEDUP_THRESHOLD:
                dropped += 1
                try:
                    jpg.unlink()
                except OSError:
                    pass
                continue
        if thumb is not None:
            last_thumb = thumb
        frames.append({"t": t, "path": str(jpg), "kept": True})
    return {"frames": frames, "dropped": dropped, "failed": failed}


__all__ = [
    "TIERS", "DEFAULT_TIER", "DEDUP_THRESHOLD", "normalize_tier",
    "plan_timestamps", "extract_frames", "mean_abs_diff",
]
