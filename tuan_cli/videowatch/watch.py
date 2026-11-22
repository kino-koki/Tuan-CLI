# -*- coding: utf-8 -*-
"""tuan-watch 编排器 —— 给 Agent 一双"看视频的眼睛" (claude-video 理念自研)。

一条 ``watch_video()`` 串起: 源解析 (本地/URL) → 元数据 → 字幕优先转写 →
帧预算抽帧 (去重) → 观看包 (watch pack) 落盘。全程 fail-closed:
依赖缺失/源不可用都如实上报, 绝不静默假成功。
"""
from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

from ._ff import capability_report, ytdlp_available
from .frames import extract_frames, normalize_tier, plan_timestamps
from .probe import probe_video
from .transcript import build_transcript

_MAX_DOWNLOAD_BYTES = 300 * 1024 * 1024  # URL 直下上限 300MB (yt-dlp 不受限)
_TRANSCRIPT_EXCERPT_SEGMENTS = 60        # 工具输出里最多内联的转写条数


# ---------------------------------------------------------------- 源解析

def _is_url(source: str) -> bool:
    try:
        return urllib.parse.urlparse(source).scheme in ("http", "https")
    except ValueError:
        return False


def _download_direct(url: str, dest: Path) -> None:
    """直链媒体下载 (urllib, 带 UA 与大小上限)。失败抛 ValueError。"""
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (tuan-watch)"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            total = 0
            with open(dest, "wb") as f:
                while True:
                    chunk = resp.read(1024 * 256)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > _MAX_DOWNLOAD_BYTES:
                        raise ValueError(f"直链下载超过 {_MAX_DOWNLOAD_BYTES // (1024*1024)}MB 上限")
                    f.write(chunk)
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"直链下载失败: {exc}") from exc


def resolve_source(source: str, workdir: Path) -> Dict[str, Any]:
    """把 本地路径 / 视频URL 归一化为本地文件。

    返回 {path, cleanup: Callable, origin}。URL 优先 yt-dlp (数百站点),
    未安装则尝试直链下载; 都不行 → 明确报错 (含安装提示)。
    """
    src = source.strip()
    if not src:
        raise ValueError("源为空")
    if not _is_url(src):
        p = Path(src)
        if not p.exists():
            raise ValueError(f"本地文件不存在: {src}")
        if p.is_dir():
            raise ValueError(f"目标是目录, 需要视频文件: {src}")
        return {"path": str(p), "cleanup": None, "origin": "local"}

    tmpdir = Path(tempfile.mkdtemp(prefix="tuan_watch_"))
    if ytdlp_available():
        out_tpl = str(tmpdir / "video.%(ext)s")
        from ._ff import _run
        rc, _out, err = _run([
            "yt-dlp", "--no-playlist", "-o", out_tpl, "--no-progress", src,
        ], timeout=600)
        files = [f for f in tmpdir.iterdir() if f.is_file()] if tmpdir.is_dir() else []
        if rc == 0 and files:
            fpath = max(files, key=lambda f: f.stat().st_size)
            return {"path": str(fpath), "cleanup": lambda: shutil.rmtree(tmpdir, ignore_errors=True),
                    "origin": "yt-dlp"}
        raise ValueError(
            f"yt-dlp 下载失败: {err[-300:] or '未知错误'}")

    # 无 yt-dlp: 尝试直链
    dest = tmpdir / "video.mp4"
    try:
        _download_direct(src, dest)
    except ValueError:
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise ValueError(
            "URL 下载失败: 未安装 yt-dlp (pip install yt-dlp 可支持数百视频站点), "
            "且该地址不是可直接下载的媒体直链")
    return {"path": str(dest), "cleanup": lambda: shutil.rmtree(tmpdir, ignore_errors=True),
            "origin": "direct"}


# ---------------------------------------------------------------- 主入口

def watch_video(source: str, workspace: str = ".",
                detail: Optional[str] = None,
                start: Optional[float] = None,
                end: Optional[float] = None,
                no_dedup: bool = False,
                question: Optional[str] = None,
                max_frames: Optional[int] = None,
                allow_whisper: bool = True) -> Dict[str, Any]:
    """观看一个视频, 返回结构化"观看包"。

    返回 dict: {source, origin, meta, detail, transcript: {source, segments, tried},
                frames: [{t, path, kept}], dropped, failed, pack_dir, caps, notes[]}
    任一硬失败 (源不可用/无 ffmpeg) → raise ValueError (fail-closed)。
    """
    tier = normalize_tier(detail)
    caps = capability_report()
    if not caps["ffprobe"]:
        raise ValueError("ffprobe 不可用: 请安装 ffmpeg 并加入 PATH (winget install ffmpeg)")

    resolved = resolve_source(source, Path(tempfile.gettempdir()))
    vpath = resolved["path"]
    cleanup = resolved["cleanup"]
    notes: List[str] = []
    try:
        meta = probe_video(vpath)
        if meta.get("error"):
            raise ValueError(f"元数据探测失败: {meta['error']}")

        # 观看包目录: <workspace>/.tuan/watch/<digest>/
        digest = hashlib.sha1(
            f"{source}|{tier}|{start}|{end}|{no_dedup}".encode("utf-8"),
            usedforsecurity=False).hexdigest()[:12]
        pack_dir = Path(workspace) / ".tuan" / "watch" / digest
        pack_dir.mkdir(parents=True, exist_ok=True)

        # 1) 字幕优先
        tr = build_transcript(vpath, pack_dir, meta=meta, allow_whisper=allow_whisper)
        if tr["source"] == "none":
            notes.append("无字幕且无转写; " + "; ".join(tr.get("tried", [])))

        # 2) 抽帧 (transcript 档 = 0 帧; 但若无字幕则自动升档兜底)
        eff_tier = tier
        if tier == "transcript" and tr["source"] == "none":
            eff_tier = "swift"
            notes.append("transcript 档无字幕可用, 自动降级为 swift 抽帧")
        ts = plan_timestamps(float(meta["duration"] or 0.0), eff_tier,
                             start=start, end=end, max_frames=max_frames)
        fr: Dict[str, Any] = {"frames": [], "dropped": 0, "failed": 0}
        if ts:
            if not caps["ffmpeg"]:
                notes.append("ffmpeg 不可用, 跳过抽帧 (转写仍有效)")
            else:
                fr = extract_frames(vpath, ts, pack_dir, dedup=not no_dedup)

        result: Dict[str, Any] = {
            "source": source,
            "origin": resolved["origin"],
            "detail": tier,
            "effective_detail": eff_tier,
            "meta": meta,
            "transcript": {"source": tr["source"], "segments": tr["segments"],
                           "tried": tr.get("tried", [])},
            "frames": fr["frames"],
            "dropped": fr["dropped"],
            "failed": fr["failed"],
            "pack_dir": str(pack_dir),
            "caps": caps,
            "notes": notes,
            "question": question,
        }
        # 观看包清单落盘 (帧文件已是持久产物, 清单供复看/二次提问)
        try:
            (pack_dir / "pack.json").write_text(json.dumps(
                {**result, "frames": fr["frames"]}, ensure_ascii=False, indent=2,
                default=str), encoding="utf-8")
        except OSError as exc:  # noqa: BLE001 - 清单写失败不影响返回
            notes.append(f"pack.json 写入失败: {exc}")
        return result
    finally:
        if cleanup:
            cleanup()


# ---------------------------------------------------------------- 摘要

def summarize(result: Dict[str, Any], max_segments: int = _TRANSCRIPT_EXCERPT_SEGMENTS) -> str:
    """把观看包渲染成模型/用户都易读的文本摘要 (工具输出用)。"""
    meta = result.get("meta") or {}
    lines: List[str] = []
    dur = meta.get("duration")
    dur_s = f"{int(dur // 60)}:{int(dur % 60):02d}" if isinstance(dur, (int, float)) else "?"
    lines.append(f"视频: {result.get('source')}  ({dur_s}, "
                 f"{meta.get('width') or '?'}x{meta.get('height') or '?'}@{meta.get('fps') or '?'}fps, "
                 f"来源: {result.get('origin')})")
    if result.get("question"):
        lines.append(f"观看问题: {result['question']}")
    tr = result.get("transcript") or {}
    segs = tr.get("segments") or []
    if segs:
        lines.append(f"转写 ({tr.get('source')}, 共 {len(segs)} 段):")
        for s in segs[:max_segments]:
            st = s.get("start", 0.0)
            mm, ss = int(st // 60), int(st % 60)
            lines.append(f"  [{mm}:{ss:02d}] {s.get('text', '')}")
        if len(segs) > max_segments:
            lines.append(f"  ...(其余 {len(segs) - max_segments} 段见 {result.get('pack_dir')}/pack.json)")
    else:
        lines.append("转写: 无")
    frames = result.get("frames") or []
    if frames:
        lines.append(f"关键帧 {len(frames)} 张 (档位 {result.get('effective_detail')}"
                     f"{', 去重丢弃 ' + str(result['dropped']) + ' 张' if result.get('dropped') else ''}"
                     f"{', 抽帧失败 ' + str(result['failed']) + ' 个时间点' if result.get('failed') else ''}):")
        for f in frames[:12]:
            lines.append(f"  t={f['t']:.2f}s  {f['path']}")
        if len(frames) > 12:
            lines.append(f"  ...(其余 {len(frames) - 12} 帧在 {result.get('pack_dir')} 内)")
    else:
        lines.append("关键帧: 无 (transcript 档或 ffmpeg 不可用)")
    for n in result.get("notes") or []:
        lines.append(f"注: {n}")
    if result.get("pack_dir"):
        lines.append(f"观看包: {result['pack_dir']}")
    return "\n".join(lines)


__all__ = ["watch_video", "summarize", "resolve_source"]
