# -*- coding: utf-8 -*-
"""阶段 12 —— 多语言叙事 TTS (narration_tts) 测试。

覆盖: 确定性合成 WAV / 参数非法 fail-closed / 引擎自动探测兜底 /
流水线旁白轨并入 compose audio (混音链路)。
"""
from __future__ import annotations

import wave

from tuan_cli.web.narration_tts import synth_wav, synthesize_narration


def _wav_info(path: str):
    with wave.open(path, "rb") as w:
        return {
            "channels": w.getnchannels(),
            "width": w.getsampwidth(),
            "rate": w.getframerate(),
            "frames": w.getnframes(),
            "duration": w.getnframes() / w.getframerate(),
        }


def test_synth_wav_produces_valid_pcm16(tmp_path):
    """内置合成器输出合法 PCM16 单声道 WAV, 时长>0。"""
    out = tmp_path / "nar.wav"
    res = synth_wav("你好世界", str(out), lang="zh")
    assert out.exists()
    assert out.stat().st_size > 0
    assert res["engine"] == "synth_wav"
    assert res["duration"] > 0
    info = _wav_info(str(out))
    assert info["channels"] == 1
    assert info["width"] == 2
    assert info["rate"] == 22050
    assert info["frames"] > 0


def test_synth_wav_deterministic(tmp_path):
    """同文本同参数 → 同字节 (frame-stable / 可回归)。"""
    a = tmp_path / "a.wav"
    b = tmp_path / "b.wav"
    synth_wav("同一个旁白", str(a), lang="zh")
    synth_wav("同一个旁白", str(b), lang="zh")
    assert a.read_bytes() == b.read_bytes()


def test_synth_wav_language_tokens_differ(tmp_path):
    """中文逐字 / 英文逐词 → 时长不同 (语言感知)。"""
    za = tmp_path / "za.wav"
    en = tmp_path / "en.wav"
    synth_wav("hello world", str(za), lang="zh")
    synth_wav("hello world", str(en), lang="en")
    assert _wav_info(str(za))["duration"] != _wav_info(str(en))["duration"]


def test_synth_wav_empty_text_fail_closed(tmp_path):
    """空文本 → fail-closed ValueError。"""
    try:
        synth_wav("   ", str(tmp_path / "x.wav"))
        assert False, "应抛 ValueError"
    except ValueError as exc:
        assert "为空" in str(exc)


def test_synthesize_narration_forced_synth(tmp_path):
    """engine='synth' 强制内置合成器 (不探测外部引擎)。"""
    out = tmp_path / "forced.wav"
    res = synthesize_narration("测试旁白", str(out), engine="synth", lang="zh")
    assert res["engine"] == "synth_wav"
    assert out.exists()


def test_synthesize_narration_auto_fallback(tmp_path):
    """engine='auto' 探测外部引擎失败时兜底内置合成器 (绝不静默失败)。"""
    out = tmp_path / "auto.wav"
    res = synthesize_narration("自动兜底", str(out), engine="auto", lang="zh")
    assert res["engine"] in ("synth_wav", "edge-tts", "pyttsx3")
    assert out.exists()


def test_pipeline_narration_audio_merged_into_compose(tmp_path):
    """旁白音频轨被并入 compose 产物的 project_json.audio (混音链路)。"""
    from tuan_cli.web.video_pipeline import VideoPipeline
    import os

    audio_holder = {}
    nar_wav = tmp_path / "nar.wav"

    def fake_tts(text, voice, ctx):
        audio_holder["text"] = text
        synth_wav(text, str(nar_wav), lang="zh")
        return {"path": str(nar_wav), "duration": 0.2}

    def fake_executor(stage, prompt, ctx):
        if stage == "research":
            return {"keywords": ["ai"], "angles": [], "competitors": []}
        if stage == "script":
            return {"hook": "H", "scenes": []}
        if stage == "scene":
            return {"layout": "16:9", "palette": "dark", "motion": "slide"}
        if stage == "gate":
            return {"approved": True, "notes": "ok"}
        if stage == "narration":
            return {"voice": "zh", "text": "旁白音频"}
        if stage == "music":
            return {"bpm": 120, "mood": "up", "track": "b.mp3"}
        if stage == "compose":
            return {"project_json": {
                "width": 128, "height": 72, "fps": 5, "duration": 0.4,
                "nodes": [{"type": "bg", "start": 0, "end": 0.4,
                           "props": {"type": "solid"}}],
            }}
        raise AssertionError(f"未预期阶段 {stage}")

    pipe = VideoPipeline()
    out = pipe.run("x", executor=fake_executor, tts=fake_tts,
                   renderer=lambda pj, path: {"out_path": path, "frames": 1})
    pj = out["stages"]["compose"]["project_json"]
    assert isinstance(pj["audio"], list) and len(pj["audio"]) >= 1
    assert audio_holder["text"] == "旁白音频"
    assert "audio" in out["stages"]["narration"]
