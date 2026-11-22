# -*- coding: utf-8 -*-
"""字幕优先的转写链 —— tuan-watch 的"能不下载就不下载"理念落地。

优先级 (自研实现, 理念对标 claude-video 的 transcript-first):
  1. sidecar 字幕: 与视频同名的 .srt / .vtt 文件 (含 .<lang>.srt 变体);
  2. 内嵌字幕轨: ffmpeg -map 0:s:0 抽取第一条字幕流;
  3. Whisper 转写: 本地 faster-whisper / openai-whisper (可选依赖, 缺失则跳过);
  4. 都没有 → 如实报告 "无字幕无转写", 绝不编造。
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from ._ff import ffmpeg_run, _whisper_flavor


# ---------------------------------------------------------------- 解析

_TS_SRT = re.compile(r"(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})")
_TS_VTT = re.compile(r"(?:(\d{1,2}):)?(\d{1,2}):(\d{2})[.,](\d{1,3})")


def _to_seconds(h: str, m: str, s: str, ms: str) -> float:
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms.ljust(3, "0")) / 1000.0


def parse_srt(text: str) -> List[Dict[str, Any]]:
    """解析 SRT 字幕 → [{start, end, text}]。容错: 空块/坏时间戳跳过。"""
    segs: List[Dict[str, Any]] = []
    blocks = re.split(r"\r?\n\r?\n", text.strip())
    for block in blocks:
        lines = [ln for ln in block.splitlines() if ln.strip()]
        if len(lines) < 2:
            continue
        # 时间行: 可能带序号前缀 ("1\n00:00:01,000 --> ..."), 也可能直接是时间行
        tline = None
        body_start = 1
        for i, ln in enumerate(lines[:2]):
            if "-->" in ln:
                tline = ln
                body_start = i + 1
                break
        if not tline:
            continue
        m = re.match(r"\s*([^>]+?)\s*-->\s*(.+?)\s*$", tline)
        if not m:
            continue
        a, b = _TS_SRT.search(m.group(1)), _TS_SRT.search(m.group(2))
        if not a or not b:
            continue
        body = " ".join(ln.strip() for ln in lines[body_start:])
        body = re.sub(r"<[^>]+>", "", body).strip()  # 去内联标签
        if body:
            segs.append({"start": _to_seconds(*a.groups()), "end": _to_seconds(*b.groups()), "text": body})
    return segs


def parse_vtt(text: str) -> List[Dict[str, Any]]:
    """解析 WebVTT 字幕 → [{start, end, text}]。"""
    segs: List[Dict[str, Any]] = []
    blocks = re.split(r"\r?\n\r?\n", text.strip())
    for block in blocks:
        lines = [ln for ln in block.splitlines() if ln.strip()]
        if not lines:
            continue
        tline = next((ln for ln in lines if "-->" in ln), None)
        if not tline:
            continue
        m = re.match(r"\s*([^>]+?)\s*-->\s*(.+?)\s*$", tline)
        if not m:
            continue
        a, b = _TS_VTT.search(m.group(1)), _TS_VTT.search(m.group(2))
        if not a or not b:
            continue
        h = a.group(1) or "0"
        body_lines = lines[lines.index(tline) + 1:]
        body = " ".join(re.sub(r"<[^>]+>", "", ln).strip() for ln in body_lines).strip()
        if body:
            segs.append({"start": _to_seconds(h, a.group(2), a.group(3), a.group(4)),
                         "end": _to_seconds(b.group(1) or "0", b.group(2), b.group(3), b.group(4)),
                         "text": body})
    return segs


def parse_subtitle_text(text: str, hint: str = "") -> List[Dict[str, Any]]:
    """按内容/扩展名自动选择 SRT 或 VTT 解析器。"""
    if hint.lower().endswith(".vtt") or text.lstrip().startswith("WEBVTT"):
        return parse_vtt(text)
    return parse_srt(text)


# ---------------------------------------------------------------- 来源链

def find_sidecar(video_path: str) -> Optional[Path]:
    """查找与视频同目录的同名字幕文件 (stem.srt/.vtt 或 stem.*.srt/.vtt)。"""
    p = Path(video_path)
    if not p.parent.is_dir():
        return None
    candidates: List[Path] = []
    for child in sorted(p.parent.iterdir()):
        if not child.is_file() or child.suffix.lower() not in (".srt", ".vtt"):
            continue
        stem = child.stem.lower()
        if stem == p.stem.lower() or stem.startswith(p.stem.lower() + "."):
            candidates.append(child)
    # 优先精确同名, 其次任意语言变体
    for c in candidates:
        if c.stem.lower() == p.stem.lower():
            return c
    return candidates[0] if candidates else None


def _read_sidecar(video_path: str) -> Optional[Dict[str, Any]]:
    sc = find_sidecar(video_path)
    if sc is None:
        return None
    try:
        text = sc.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    segs = parse_subtitle_text(text, sc.suffix)
    if segs:
        return {"source": "sidecar", "file": str(sc), "segments": segs}
    return None


def _extract_embedded(video_path: str, workdir: Path) -> Optional[Dict[str, Any]]:
    """抽取第一条内嵌字幕流为 SRT。无字幕轨/无 ffmpeg → None。"""
    out = workdir / "embedded.srt"
    rc, _err = ffmpeg_run([
        "-i", str(video_path), "-map", "0:s:0", "-c:s", "srt", str(out),
    ], timeout=120)
    if rc != 0 or not out.exists():
        return None
    try:
        segs = parse_srt(out.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return None
    if segs:
        return {"source": "embedded", "file": str(out), "segments": segs}
    return None


def _extract_audio(video_path: str, workdir: Path) -> Optional[Path]:
    """抽取 16kHz 单声道音轨 (Whisper 标准输入)。"""
    wav = workdir / "audio16k.wav"
    rc, _err = ffmpeg_run([
        "-i", str(video_path), "-vn", "-ar", "16000", "-ac", "1",
        "-c:a", "pcm_s16le", str(wav),
    ], timeout=300)
    if rc != 0 or not wav.exists():
        return None
    return wav


def _whisper_transcribe(wav: Path) -> Optional[Dict[str, Any]]:
    """本地 Whisper 转写 (faster-whisper 优先)。不可用/失败 → None。"""
    flavor = _whisper_flavor()
    if not flavor:
        return None
    try:
        if flavor == "faster-whisper":
            from faster_whisper import WhisperModel
            model = WhisperModel("base", device="cpu", compute_type="int8")
            segments_iter, _info = model.transcribe(str(wav), vad_filter=True)
            segs = [{"start": float(s.start), "end": float(s.end),
                     "text": s.text.strip()} for s in segments_iter if s.text.strip()]
        else:
            import whisper
            model = whisper.load_model("base")
            result = model.transcribe(str(wav))
            segs = [{"start": float(s.get("start", 0.0)), "end": float(s.get("end", 0.0)),
                     "text": str(s.get("text", "")).strip()}
                    for s in result.get("segments", []) if str(s.get("text", "")).strip()]
        if segs:
            return {"source": f"whisper({flavor})", "file": str(wav), "segments": segs}
    except Exception:  # noqa: BLE001 - 转写失败不致命, 上层如实报告
        return None
    return None


def build_transcript(video_path: str, workdir: Path,
                     meta: Optional[Dict[str, Any]] = None,
                     allow_whisper: bool = True) -> Dict[str, Any]:
    """字幕优先转写链入口。返回 {source, file?, segments, tried}。

    tried 记录每一步是否尝试及失败原因, 供 /watch 输出可观测的能力链。
    """
    tried: List[str] = []
    hit = _read_sidecar(video_path)
    if hit:
        hit["tried"] = tried
        return hit
    tried.append("sidecar: 未找到同名字幕文件")

    n_subs = (meta or {}).get("subtitle_streams", 0)
    if n_subs:
        hit = _extract_embedded(video_path, workdir)
        if hit:
            hit["tried"] = tried
            return hit
        tried.append("embedded: 内嵌字幕抽取失败")
    else:
        tried.append("embedded: 无内嵌字幕轨")

    if allow_whisper:
        if (meta or {}).get("has_audio", True):
            wav = _extract_audio(video_path, workdir)
            if wav is not None:
                hit = _whisper_transcribe(wav)
                if hit:
                    hit["tried"] = tried
                    return hit
                tried.append(f"whisper: {_whisper_flavor() or '无可用后端'}")
            else:
                tried.append("whisper: 音轨抽取失败")
        else:
            tried.append("whisper: 视频无音轨")
    else:
        tried.append("whisper: 已禁用")
    return {"source": "none", "segments": [], "tried": tried}


__all__ = [
    "parse_srt", "parse_vtt", "parse_subtitle_text", "find_sidecar",
    "build_transcript",
]
