# -*- coding: utf-8 -*-
"""ffmpeg / ffprobe 进程包装 —— tuan-watch 的外部依赖探测与安全调用。

设计要点 (自研实现, 理念对标 claude-video 的"依赖自举"):
  * ffmpeg/ffprobe/yt-dlp 全部为**可选**依赖: 缺失时给出明确的能力报告,
    绝不静默假装成功 (fail-closed);
  * Windows 下一律 CREATE_NO_WINDOW, 避免弹出黑色控制台;
  * 所有子进程调用都有超时, 超时即杀, 不挂死 Agent 循环。
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from typing import Any, Optional

_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000) if sys.platform == "win32" else 0


def _run(cmd: list, timeout: float = 60.0) -> tuple:
    """执行外部命令, 返回 (returncode, stdout, stderr)。超时/找不到可执行 → (-1, '', 原因)。"""
    try:
        proc = subprocess.run(
            cmd, capture_output=True, timeout=timeout,
            creationflags=_CREATE_NO_WINDOW,
        )
        return (proc.returncode,
                proc.stdout.decode(errors="replace"),
                proc.stderr.decode(errors="replace"))
    except subprocess.TimeoutExpired:
        return (-1, "", f"timeout after {timeout}s")
    except FileNotFoundError:
        return (-1, "", f"executable not found: {cmd[0]}")
    except OSError as exc:
        return (-1, "", str(exc))


def which(name: str) -> Optional[str]:
    """定位可执行文件; 找不到返回 None。"""
    return shutil.which(name)


def ffmpeg_available() -> bool:
    return which("ffmpeg") is not None


def ffprobe_available() -> bool:
    return which("ffprobe") is not None


def ytdlp_available() -> bool:
    return which("yt-dlp") is not None


def ffprobe_json(path: str, timeout: float = 30.0) -> Optional[dict]:
    """ffprobe 元数据 → dict; 失败返回 None (调用方 fail-closed 上报)。"""
    if not ffprobe_available():
        return None
    rc, out, _err = _run([
        "ffprobe", "-v", "error", "-print_format", "json",
        "-show_format", "-show_streams", str(path),
    ], timeout=timeout)
    if rc != 0 or not out.strip():
        return None
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def ffmpeg_run(args: list, timeout: float = 120.0) -> tuple:
    """执行一条 ffmpeg 命令 (自动带 -nostdin 防止吞输入), 返回 (rc, stderr)。"""
    cmd = ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", *args]
    rc, _out, err = _run(cmd, timeout=timeout)
    return rc, err


def capability_report() -> dict:
    """能力自检: 供 /watch 与 doctor 输出, 缺什么依赖一目了然。"""
    return {
        "ffmpeg": ffmpeg_available(),
        "ffprobe": ffprobe_available(),
        "yt_dlp": ytdlp_available(),
        "whisper": _whisper_flavor(),
    }


def _whisper_flavor() -> str:
    """探测可用的 Whisper 后端: faster-whisper > openai-whisper > 无。"""
    try:
        import faster_whisper  # noqa: F401
        return "faster-whisper"
    except Exception:  # noqa: BLE001
        pass
    try:
        import whisper  # noqa: F401
        return "openai-whisper"
    except Exception:  # noqa: BLE001
        return ""


__all__ = [
    "ffmpeg_available", "ffprobe_available", "ytdlp_available",
    "ffprobe_json", "ffmpeg_run", "capability_report", "which",
]
