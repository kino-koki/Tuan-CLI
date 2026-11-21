# -*- coding: utf-8 -*-
"""OpenMontage 式流水线驱动 —— ModelGateway 串联 9 阶段自动化成片。

对齐最新开源卖点 OpenMontage (agentic 视频流水线): 一条 `brief` 进入,
按 9 阶段顺序驱动多模型网关, 每阶段产出结构化中间态, 最后调用
``code_anim_render`` 渲染 mp4。

阶段 (9):
  brief     归一化输入 brief
  research  调研 → {keywords, angles, competitors}
  script    脚本 → {hook, scenes[]}
  scene     分镜/视觉 → {layout, palette, motion}
  gate      质量闸门 → {approved, notes}   (未通过 → fail-closed 抛错)
  narration 旁白 → {voice, text}
  music     音乐 → {bpm, mood, track}
  compose   合成 → {project_json}          (renderable 项目)
  render    渲染 → {rendered, out_path, frames}

设计要点:
  * 每阶段经 ``gw.call_intent(intent, prompt, json_schema=...)`` 得到结构化输出,
    解析失败/未知意图/未配置 → 抛错 (fail-closed, 绝不静默)。
  * ``run`` 的 LLM 调用经可注入 ``executor`` (默认用网关), 便于无网测试。
  * ``render`` 阶段仅 ffmpeg 可用才真正出片; 否则返回 ``rendered: False`` 带原因
    (能力缺失, 明确上报而非假成功)。
"""

from __future__ import annotations

import hashlib
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from ..runtime.gateway import ModelGateway

# 阶段顺序 (intent 名)
STAGE_NAMES: List[str] = [
    "brief", "research", "script", "scene", "gate",
    "narration", "music", "compose", "render",
]


@dataclass
class PipelineContext:
    """流水线累积上下文: brief + 各阶段产物。"""

    brief: str = ""
    stages: Dict[str, Any] = field(default_factory=dict)

    def get(self, stage: str, key: str, default: Any = None) -> Any:
        s = self.stages.get(stage)
        if isinstance(s, dict):
            return s.get(key, default)
        return default


class VideoPipeline:
    """OpenMontage 式 9 阶段视频流水线 (ModelGateway 驱动)。"""

    def __init__(self, gw: Optional[ModelGateway] = None,
                 stages: Optional[List[str]] = None) -> None:
        self.gw = gw or ModelGateway()
        self.stages = list(stages or STAGE_NAMES)

    def run(self, brief: str, *,
            executor: Optional[Callable[[str, str, PipelineContext],
                                        Dict[str, Any]]] = None,
            renderer: Optional[Callable[[Dict[str, Any], str],
                                        Dict[str, Any]]] = None,
            out_path: str = "pipeline_out.mp4",
            tts: Optional[Callable[[str, str, PipelineContext],
                                   Dict[str, Any]]] = None) -> Dict[str, Any]:
        """执行流水线, 返回 {brief, stages: {stage: result}, rendered}。

        任一段失败 → 抛 ValueError (fail-closed)。

        ``tts``: 可选旁白音频轨合成器, 签名
        ``(text, voice, ctx) -> {"path","duration"}``; 默认内置
        :func:`narration_tts.synthesize_narration` (自动探测外部引擎,
        兜底确定性 WAV)。若 TTS 成功, 产物写入 compose 阶段
        ``project_json.audio``, 供 render 阶段混音。
        """
        ctx = PipelineContext(brief=brief)
        exec_fn = executor or self._default_executor
        tts_fn = tts or self._default_tts
        for stage in self.stages:
            if stage not in STAGE_NAMES:
                raise ValueError(f"未知流水线阶段 {stage!r} (fail-closed)")
            # brief: 归一化步骤, 不进模型 (prompt 即 brief); render: 特殊渲染
            if stage == "brief":
                result = {"normalized": brief.strip(), "length": len(brief.strip())}
            elif stage == "render":
                result = self._stage_render(ctx, renderer, out_path)
            else:
                prompt = self._stage_prompt(stage, ctx)
                result = exec_fn(stage, prompt, ctx)
                if stage == "gate":
                    if not result.get("approved"):
                        raise ValueError(
                            f"质量闸门未通过 (fail-closed): {result.get('notes', '')}")
                if stage == "narration":
                    self._attach_narration_audio(result, ctx, tts_fn)
            ctx.stages[stage] = result
        # narration 在 compose 之前执行: 循环结束后把旁白音频轨并入 compose 产物
        self._merge_narration_audio(ctx)
        rendered = ctx.stages.get("render", {})
        return {
            "brief": brief,
            "stages": ctx.stages,
            "rendered": bool(rendered.get("rendered")),
            "out_path": rendered.get("out_path"),
            "frames": rendered.get("frames"),
        }

    # --- 默认 TTS: narration_tts.synthesize_narration (fail-closed 兜底) ---

    def _default_tts(self, text: str, voice: str,
                     ctx: PipelineContext) -> Dict[str, Any]:
        from . import narration_tts
        # 默认 TTS 无调用方传入输出路径: 按 text+voice 派生确定性临时路径
        # (同输入同文件, 与 narration_tts 确定性合成的语义一致)。
        digest = hashlib.sha1(f"{text}|{voice}".encode("utf-8"), usedforsecurity=False).hexdigest()[:16]
        out_path = str(Path(tempfile.gettempdir()) / f"tuan_narration_{digest}.wav")
        return narration_tts.synthesize_narration(text, out_path, voice=voice)

    def _attach_narration_audio(self, narration: Dict[str, Any], ctx: PipelineContext,
                                tts_fn: Callable[[str, str, PipelineContext],
                                                 Dict[str, Any]]) -> None:
        """旁白文本 → 音频轨, 暂存在 narration 阶段 (待 compose 后合并)。

        TTS 失败只记 ``narration.tts_error`` (不中断流水线, 成片仍可出);
        但若音频轨产出, 必须合法才能混音 (render 阶段 fail-closed 校验)。
        """
        text = narration.get("text")
        voice = narration.get("voice") or ""
        if not isinstance(text, str) or not text.strip():
            return
        try:
            audio = tts_fn(text, voice, ctx)
        except Exception as exc:  # noqa: BLE001
            narration["tts_error"] = str(exc)
            return
        if not isinstance(audio, dict) or not audio.get("path"):
            narration["tts_error"] = "TTS 未产出合法音频轨"
            return
        narration["audio"] = audio

    def _merge_narration_audio(self, ctx: PipelineContext) -> None:
        """把 narration 阶段的音频轨并入 compose 产物的 project_json.audio。"""
        narration = ctx.stages.get("narration")
        audio = narration.get("audio") if isinstance(narration, dict) else None
        if not isinstance(audio, dict) or not audio.get("path"):
            return
        compose = ctx.stages.get("compose")
        pj = compose.get("project_json") if isinstance(compose, dict) else None
        if not isinstance(pj, dict):
            return
        existing = pj.get("audio")
        track = {"path": audio["path"],
                 "start": audio.get("start", 0.0),
                 "volume": audio.get("volume", 0.9),
                 "loop": False}
        if existing is None:
            pj["audio"] = [track]
        elif isinstance(existing, list):
            existing.append(track)
        elif isinstance(existing, str):
            pj["audio"] = [{"path": existing, "start": 0.0,
                            "volume": 0.9, "loop": False}, track]

    # --- 默认执行器: 经网关 call_intent (fail-closed) ---

    def _default_executor(self, stage: str, prompt: str,
                          ctx: PipelineContext) -> Dict[str, Any]:
        schema = _STAGE_SCHEMAS.get(stage)
        return self.gw.call_intent(stage, prompt, json_schema=schema)

    # --- 阶段 prompt 构建 ---

    def _stage_prompt(self, stage: str, ctx: PipelineContext) -> str:
        b = ctx.brief
        if stage == "research":
            return (f"针对以下创作 brief 做深度调研, 输出关键词/切入角度/竞品。"
                    f"\nbrief: {b}")
        if stage == "script":
            kw = ctx.get("research", "keywords", "")
            return (f"基于调研 {kw} 写一段 30s 产品/主题视频脚本, 输出 hook 与场景列表。"
                    f"\nbrief: {b}")
        if stage == "scene":
            return (f"为脚本设计视觉分镜: 布局/配色/运动方式。"
                    f"\n脚本: {ctx.get('script', 'hook', '')}\nbrief: {b}")
        if stage == "gate":
            return (f"对以下成片方案做质量闸门评审, 返回 approved(bool) 与 notes。"
                    f"\n脚本: {ctx.get('script', 'hook', '')}"
                    f"\n视觉: {ctx.get('scene', 'motion', '')}")
        if stage == "narration":
            return (f"为脚本写旁白配音文本。\n脚本: {ctx.get('script', 'hook', '')}")
        if stage == "music":
            return (f"为脚本选 BGM 基调: bpm/mood/track。\n脚本: {ctx.get('script', 'hook', '')}")
        if stage == "compose":
            return (f"把脚本/分镜/音乐合成可渲染 project_json (width/height/fps/"
                    f"duration/nodes/audio)。仅输出 JSON。\n"
                    f"脚本: {ctx.get('script', 'hook', '')}"
                    f"\n视觉: {ctx.get('scene', 'layout', '')}"
                    f"\n音乐: {ctx.get('music', 'track', '')}")
        return f"brief: {b}"

    # --- render 阶段: 用 code_anim_render 出片 ---

    def _stage_render(self, ctx: PipelineContext,
                      renderer: Optional[Callable[[Dict[str, Any], str],
                                                  Dict[str, Any]]],
                      out_path: str) -> Dict[str, Any]:
        pj = ctx.get("compose", "project_json")
        if not isinstance(pj, dict):
            raise ValueError("compose 阶段未产出合法 project_json (fail-closed)")
        from . import code_anim_render as car
        if not car.ffmpeg_available():
            return {"rendered": False, "reason": "ffmpeg 不可用",
                    "project_json": pj}
        fn = renderer or car.render_video
        result = fn(pj, out_path)
        if isinstance(result, dict):
            return {"rendered": True, **result}
        return {"rendered": True, "out_path": out_path}


# 每阶段的结构化输出 schema (供 json_schema 透传)
_STAGE_SCHEMAS: Dict[str, Dict[str, Any]] = {
    "research": {
        "type": "object",
        "properties": {
            "keywords": {"type": "array", "items": {"type": "string"}},
            "angles": {"type": "array", "items": {"type": "string"}},
            "competitors": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["keywords"],
    },
    "script": {
        "type": "object",
        "properties": {
            "hook": {"type": "string"},
            "scenes": {"type": "array", "items": {"type": "object"}},
        },
        "required": ["hook"],
    },
    "scene": {
        "type": "object",
        "properties": {
            "layout": {"type": "string"},
            "palette": {"type": "string"},
            "motion": {"type": "string"},
        },
        "required": ["layout"],
    },
    "gate": {
        "type": "object",
        "properties": {
            "approved": {"type": "boolean"},
            "notes": {"type": "string"},
        },
        "required": ["approved"],
    },
    "narration": {
        "type": "object",
        "properties": {"voice": {"type": "string"}, "text": {"type": "string"}},
        "required": ["text"],
    },
    "music": {
        "type": "object",
        "properties": {
            "bpm": {"type": "integer"}, "mood": {"type": "string"},
            "track": {"type": "string"},
        },
        "required": ["bpm"],
    },
    "compose": {
        "type": "object",
        "properties": {"project_json": {"type": "object"}},
        "required": ["project_json"],
    },
}


__all__ = ["VideoPipeline", "PipelineContext", "STAGE_NAMES"]
