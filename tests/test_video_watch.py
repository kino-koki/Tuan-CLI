"""tuan-watch (视频观看能力) 纯逻辑回归测试。

覆盖: 帧预算规划 / 帧去重灰度差 / SRT+VTT 解析 / 旁挂字幕发现 /
源解析 fail-closed / 摘要渲染 / 工具注册。不依赖 ffmpeg (外部进程链路
由 capability_report 门控, 真实抽帧属集成范畴)。
"""

from pathlib import Path

import pytest

from tuan_cli.videowatch.frames import (
    TIERS,
    mean_abs_diff,
    normalize_tier,
    plan_timestamps,
)
from tuan_cli.videowatch.transcript import (
    find_sidecar,
    parse_srt,
    parse_subtitle_text,
    parse_vtt,
)
from tuan_cli.videowatch.watch import resolve_source, summarize, watch_video


# ------------------------------------------------------------------ 帧预算

def test_plan_timestamps_balanced_basic():
    ts = plan_timestamps(60.0, "balanced")
    assert len(ts) == 30  # 60s * 0.5帧/s
    assert ts[0] == 0.0
    assert all(b > a for a, b in zip(ts, ts[1:])), "时间点必须严格递增"
    assert max(ts) < 60.0, "不得越过视频末尾"


def test_plan_timestamps_tier_caps():
    # 长视频: 各档封顶生效
    assert len(plan_timestamps(3600.0, "swift")) == TIERS["swift"]["cap"]
    assert len(plan_timestamps(3600.0, "balanced")) == TIERS["balanced"]["cap"]
    assert len(plan_timestamps(3600.0, "deep")) == TIERS["deep"]["cap"]
    # 短视频: 各档下限生效
    assert len(plan_timestamps(4.0, "swift")) == TIERS["swift"]["min"]
    assert len(plan_timestamps(4.0, "balanced")) == TIERS["balanced"]["min"]


def test_plan_timestamps_transcript_is_empty():
    assert plan_timestamps(120.0, "transcript") == []


def test_plan_timestamps_window_and_max_frames():
    ts = plan_timestamps(100.0, "deep", start=10.0, end=20.0, max_frames=3)
    assert len(ts) == 3
    assert ts[0] >= 10.0 and max(ts) < 20.0


def test_plan_timestamps_invalid_inputs():
    assert plan_timestamps(0.0, "balanced") == []
    assert plan_timestamps(-5.0, "balanced") == []
    assert plan_timestamps(10.0, "balanced", start=8.0, end=2.0) == []


def test_normalize_tier_fallback():
    assert normalize_tier("DEEP") == "deep"
    assert normalize_tier("不认识的档位") == "balanced"
    assert normalize_tier(None) == "balanced"


# ------------------------------------------------------------------ 去重灰度差

def test_mean_abs_diff_identical_and_different():
    a = bytes([128] * 256)
    assert mean_abs_diff(a, a) == 0.0
    b = bytes([148] * 256)
    assert abs(mean_abs_diff(a, b) - 20.0) < 1e-9
    assert mean_abs_diff(a, None) is None
    assert mean_abs_diff(a, b"short") is None


# ------------------------------------------------------------------ 字幕解析

SRT_SAMPLE = """1
00:00:01,000 --> 00:00:03,500
你好, 欢迎观看

2
00:00:04,000 --> 00:00:06,000
这是<b>第二句</b>字幕
"""

VTT_SAMPLE = """WEBVTT

00:00:01.000 --> 00:00:03.500
你好, 欢迎观看

00:00:04.000 --> 00:00:06.000
第二句
"""


def test_parse_srt_basic():
    segs = parse_srt(SRT_SAMPLE)
    assert len(segs) == 2
    assert segs[0]["start"] == 1.0
    assert segs[0]["end"] == 3.5
    assert segs[0]["text"] == "你好, 欢迎观看"
    assert segs[1]["text"] == "这是第二句字幕"  # 内联标签被剥掉, 文本保留


def test_parse_vtt_basic():
    segs = parse_vtt(VTT_SAMPLE)
    assert len(segs) == 2
    assert segs[0]["start"] == 1.0
    assert segs[1]["end"] == 6.0


def test_parse_subtitle_auto_detect():
    assert parse_subtitle_text(VTT_SAMPLE)[0]["start"] == 1.0
    assert parse_subtitle_text(SRT_SAMPLE, hint="x.srt")[0]["start"] == 1.0


def test_parse_srt_tolerates_garbage():
    assert parse_srt("完全不是字幕的文本") == []
    assert parse_srt("") == []


# ------------------------------------------------------------------ 旁挂字幕

def test_find_sidecar_exact_then_lang(tmp_path):
    vid = tmp_path / "movie.mp4"
    vid.write_bytes(b"fake")
    exact = tmp_path / "movie.srt"
    exact.write_text(SRT_SAMPLE, encoding="utf-8")
    assert find_sidecar(str(vid)) == exact

    exact.unlink()
    lang = tmp_path / "movie.zh.srt"
    lang.write_text(SRT_SAMPLE, encoding="utf-8")
    assert find_sidecar(str(vid)) == lang


def test_find_sidecar_none(tmp_path):
    vid = tmp_path / "movie.mp4"
    vid.write_bytes(b"fake")
    assert find_sidecar(str(vid)) is None


# ------------------------------------------------------------------ 源解析 / fail-closed

def test_resolve_source_missing_file_raises():
    with pytest.raises(ValueError):
        resolve_source("绝对不存在的文件_9x7.mp4", Path("."))


def test_resolve_source_directory_raises(tmp_path):
    with pytest.raises(ValueError):
        resolve_source(str(tmp_path), tmp_path)


def test_resolve_source_local_ok(tmp_path):
    vid = tmp_path / "clip.mp4"
    vid.write_bytes(b"fake")
    res = resolve_source(str(vid), tmp_path)
    assert res["origin"] == "local" and res["path"] == str(vid) and res["cleanup"] is None


def test_watch_video_bad_source_fail_closed(tmp_path):
    with pytest.raises(ValueError):
        watch_video("不存在_9x7.mp4", workspace=str(tmp_path))


# ------------------------------------------------------------------ 摘要

def test_summarize_renders_metadata_and_transcript():
    result = {
        "source": "clip.mp4",
        "origin": "local",
        "effective_detail": "balanced",
        "meta": {"duration": 75.0, "width": 1920, "height": 1080, "fps": 30.0},
        "transcript": {"source": "sidecar", "segments": [
            {"start": 1.0, "text": "第一句"},
            {"start": 65.0, "text": "第二句"},
        ], "tried": []},
        "frames": [{"t": 0.0, "path": "/tmp/f.jpg", "kept": True}],
        "dropped": 2,
        "failed": 0,
        "pack_dir": "/tmp/pack",
        "notes": [],
        "question": "讲了什么",
    }
    text = summarize(result)
    assert "clip.mp4" in text and "1:15" in text
    assert "[0:01] 第一句" in text
    assert "讲了什么" in text
    assert "去重丢弃 2 张" in text


# ------------------------------------------------------------------ 工具注册

def test_video_watch_tool_registered(tuan_home):
    from tuan_cli.app import build_kernel

    kernel = build_kernel()
    names = {t.name for t in kernel.require("tool_registry").tools}
    assert "video_watch" in names, "video_watch 工具未接入 Agent 工具面"


def test_reach_tools_registered(tuan_home):
    from tuan_cli.app import build_kernel

    kernel = build_kernel()
    names = {t.name for t in kernel.require("tool_registry").tools}
    assert "reach_fetch" in names and "reach_doctor" in names
