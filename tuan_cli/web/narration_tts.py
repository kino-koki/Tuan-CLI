# -*- coding: utf-8 -*-
"""多语言叙事 TTS —— 生成旁白音频轨, 供视频流水线混音。

对齐最新开源卖点 (OpenMontage narration 阶段 → 真实音频轨): 把旁白文本
合成 WAV 音频。**纯 stdlib, 零外部依赖**, 确定性 (同文本同参数 → 同字节),
保证帧稳定/可回归测试。

引擎优先级 (``engine="auto"``):
  1. ``edge-tts`` (若有, 需网络) —— 高质量多语言神经网络 TTS
  2. ``pyttsx3`` (若有, Windows SAPI 本地) —— 系统语音
  3. 内置确定性 WAV 合成器 ``synth_wav`` (始终可用, 兜底)

``synth_wav`` 用音节脉冲 + 音高轮廓逼近"说话感" (辅音爆点/元音持续),
不依赖任何音频设备或模型; 输出合法 WAV (PCM16 单声道), 可被 ffmpeg amix
直接混入 mp4。所有路径 fail-closed: 参数非法/写入失败 → ValueError。
"""

from __future__ import annotations

import math
import struct
import wave
from pathlib import Path
from typing import Any, Dict, Optional

import hashlib

import logging
log = logging.getLogger(__name__)

_SAMPLE_RATE = 22050
_AMPLITUDE = 0.45  # 峰幅 (避免削波)


def synth_wav(text: str, out_path: str, *,
              rate: int = _SAMPLE_RATE, base_freq: float = 220.0,
              lang: str = "zh") -> Dict[str, Any]:
    """确定性合成旁白 WAV (stdlib 兜底引擎)。

    把文本切成"音节单元" (按语言: 中文按字/英文按词), 每个音节生成一段
    辅音爆点 (噪声衰减) + 元音持续 (基频 + 泛音), 音节间加停顿。同输入
    恒同输出 (纯函数于 text/lang/base_freq/rate)。

    返回 ``{"path","duration","samples","engine"}``。
    """
    text = (text or "").strip()
    if not text:
        raise ValueError("旁白文本为空, 无法合成 (fail-closed)")
    rate = max(8000, min(48000, int(rate)))
    base_freq = max(60.0, min(800.0, float(base_freq)))

    units = _tokenize_units(text, lang)
    if not units:
        raise ValueError("无法从文本切分音节单元 (fail-closed)")

    # 确定性种子: 由文本+参数派生, 保证同输入同输出
    seed_bytes = f"{text}|{lang}|{base_freq}|{rate}".encode("utf-8")
    seed = int.from_bytes(hashlib.sha256(seed_bytes).digest()[:4], "big")

    samples: list[float] = []
    rng_state = seed & 0xFFFF
    for i, unit in enumerate(units):
        # 音高轮廓: 每单元起始频率略有变化 (确定性伪随机)
        rng_state = (rng_state * 1103515245 + 12345) & 0x7FFFFFFF
        unit_freq = base_freq * (1.0 + ((rng_state % 41) - 20) / 200.0)
        # 音节时长: 元音 0.12-0.22s, 辅音 0.02-0.05s
        vowel_sec = 0.10 + ((rng_state % 23) / 230.0)
        consonant_sec = 0.02 + ((rng_state % 7) / 350.0)
        # 辅音爆点 (噪声衰减)
        n_cons = int(consonant_sec * rate)
        for k in range(n_cons):
            rng_state = (rng_state * 1103515245 + 12345) & 0x7FFFFFFF
            noise = ((rng_state / 0x7FFFFFFF) * 2 - 1)
            env = 1.0 - (k / max(1, n_cons))
            samples.append(noise * env * 0.35)
        # 元音持续 (基频 + 2 次泛音)
        n_vowel = int(vowel_sec * rate)
        for k in range(n_vowel):
            ph = 2 * math.pi * unit_freq * (k / rate)
            env = min(1.0, k / (rate * 0.02)) * min(1.0, (n_vowel - k) / (rate * 0.03))
            s = (math.sin(ph) * 0.7 + math.sin(2 * ph) * 0.22
                 + math.sin(3 * ph) * 0.08) * env
            samples.append(s)
        # 音节间停顿 40ms
        pause = int(0.04 * rate)
        samples.extend([0.0] * pause)
        # 每 8 个音节加一个稍长句读停顿
        if (i + 1) % 8 == 0:
            samples.extend([0.0] * int(0.12 * rate))

    duration = len(samples) / rate
    _write_wav_pcm16(samples, out_path, rate)
    return {
        "path": str(Path(out_path).resolve()),
        "duration": round(duration, 3),
        "samples": len(samples),
        "engine": "synth_wav",
        "lang": lang,
    }


def synthesize_narration(text: str, out_path: str, *,
                         voice: str = "", lang: str = "zh",
                         engine: str = "auto") -> Dict[str, Any]:
    """合成旁白音频轨, 自动探测外部 TTS 引擎, 兜底 synth_wav。

    ``engine``:
      * ``"auto"`` 按 edge-tts → pyttsx3 → synth_wav 顺序探测。
      * ``"synth"`` 强制内置合成器 (测试用)。
      * 其他值若探测失败 → 回退内置合成器 (绝不静默失败)。
    """
    if engine != "synth":
        for name, fn in (("edge-tts", _try_edge_tts), ("pyttsx3", _try_pyttsx3)):
            if engine != "auto" and engine != name:
                continue
            try:
                res = fn(text, out_path, voice=voice, lang=lang)
                if res:
                    return res
            except Exception as exc:  # noqa: BLE001 - 外部引擎失败回退
                log.debug("synthesize_narration(): 非致命异常已忽略(设计内降级, 不改控制流): %s", exc)
                continue
    return synth_wav(text, out_path, lang=lang)


def _try_edge_tts(text: str, out_path: str, *,
                  voice: str, lang: str) -> Optional[Dict[str, Any]]:
    """edge-tts 神经网络 TTS (需网络); 不可用返回 None。"""
    try:
        import asyncio
        import edge_tts
    except Exception as exc:  # noqa: BLE001
        log.debug("_try_edge_tts(): 非致命异常已忽略(设计内降级, 不改控制流): %s", exc)
        return None
    try:
        voice_id = voice or (f"{lang}-CN-XiaoxiaoNeural" if lang == "zh"
                             else f"{lang}-US-AnaNeural")
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            loop.run_until_complete(_edge_save(edge_tts, text, voice_id, out_path))
        finally:
            loop.close()
        dur = _wav_duration(out_path)
        return {"path": str(Path(out_path).resolve()), "duration": dur,
                "samples": int(dur * _SAMPLE_RATE), "engine": "edge-tts",
                "lang": lang}
    except Exception as exc:  # noqa: BLE001
        log.debug("_try_edge_tts(): 非致命异常已忽略(设计内降级, 不改控制流): %s", exc)
        return None


async def _edge_save(edge_tts: Any, text: str, voice_id: str,
                     out_path: str) -> None:
    tts = edge_tts.Communicate(text, voice_id)
    await tts.save(out_path)


def _try_pyttsx3(text: str, out_path: str, *,
                 voice: str, lang: str) -> Optional[Dict[str, Any]]:
    """pyttsx3 本地 SAPI TTS (Windows); 不可用返回 None。"""
    try:
        import pyttsx3
    except Exception as exc:  # noqa: BLE001
        log.debug("_try_pyttsx3(): 非致命异常已忽略(设计内降级, 不改控制流): %s", exc)
        return None
    try:
        eng = pyttsx3.init()
        if voice:
            for v in eng.getProperty("voices"):
                if voice.lower() in (v.id or "").lower():
                    eng.setProperty("voice", v.id)
                    break
        eng.save_to_file(text, out_path)
        eng.runAndWait()
        dur = _wav_duration(out_path)
        return {"path": str(Path(out_path).resolve()), "duration": dur,
                "samples": int(dur * _SAMPLE_RATE), "engine": "pyttsx3",
                "lang": lang}
    except Exception as exc:  # noqa: BLE001
        log.debug("_try_pyttsx3(): 非致命异常已忽略(设计内降级, 不改控制流): %s", exc)
        return None


# ---------------------------------------------------------------------------
# 内部工具
# ---------------------------------------------------------------------------

def _tokenize_units(text: str, lang: str) -> list[str]:
    """按语言把文本切成音节单元: 中文逐字, 其他逐词。"""
    units: list[str] = []
    if lang.startswith("zh"):
        for ch in text:
            if ch.strip() and not ch.isspace():
                units.append(ch)
    else:
        for word in text.replace("\n", " ").split():
            if word.strip():
                units.append(word)
    return units


def _write_wav_pcm16(samples: list[float], out_path: str, rate: int) -> None:
    """写合法 PCM16 单声道 WAV (原子: 先写临时文件再替换)。"""
    p = Path(out_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp.wav")
    try:
        with wave.open(str(tmp), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(rate)
            frames = bytearray()
            for s in samples:
                v = max(-1.0, min(1.0, s * _AMPLITUDE))
                frames.extend(struct.pack("<h", int(v * 32767)))
            w.writeframes(bytes(frames))
        tmp.replace(p)
    except Exception:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
        raise


def _wav_duration(path: str) -> float:
    try:
        with wave.open(path, "rb") as w:
            return round(w.getnframes() / w.getframerate(), 3)
    except Exception as exc:  # noqa: BLE001
        log.debug("_wav_duration(): 非致命异常已忽略(设计内降级, 不改控制流): %s", exc)
        return 0.0


__all__ = ["synth_wav", "synthesize_narration"]
