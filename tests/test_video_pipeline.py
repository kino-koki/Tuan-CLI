# -*- coding: utf-8 -*-
"""阶段 10 —— OpenMontage 式 9 阶段视频流水线测试 (VideoPipeline, 无网注入)。"""

from __future__ import annotations

from tuan_cli.web.video_pipeline import STAGE_NAMES, VideoPipeline


def _fake_executor(stage: str, prompt: str, ctx):
    """注入的假执行器: 按阶段返回结构化产物 (不触网)。"""
    if stage == "research":
        return {"keywords": ["ai", "video"], "angles": ["x"], "competitors": []}
    if stage == "script":
        return {"hook": "Hello", "scenes": [{"id": 1}]}
    if stage == "scene":
        return {"layout": "16:9", "palette": "dark", "motion": "slide"}
    if stage == "gate":
        return {"approved": True, "notes": "ok"}
    if stage == "narration":
        return {"voice": "zh", "text": "旁白"}
    if stage == "music":
        return {"bpm": 120, "mood": "upbeat", "track": "bgm.mp3"}
    if stage == "compose":
        return {"project_json": {
            "width": 128, "height": 72, "fps": 5, "duration": 0.4,
            "nodes": [{"type": "bg", "start": 0, "end": 0.4,
                       "props": {"type": "solid"}}],
        }}
    raise AssertionError(f"未预期阶段 {stage}")


def test_stage_names_full_set():
    """9 阶段完整且有序。"""
    assert STAGE_NAMES == [
        "brief", "research", "script", "scene", "gate",
        "narration", "music", "compose", "render",
    ]


def test_pipeline_success_with_fake_executor():
    """注入假执行器 + 假渲染器 → 全 9 阶段完成, rendered=True。"""
    pipe = VideoPipeline()
    out = pipe.run(
        "做一个 AI 视频",
        executor=_fake_executor,
        renderer=lambda pj, path: {"out_path": path, "frames": 2},
        out_path="demo.mp4",
    )
    assert out["brief"] == "做一个 AI 视频"
    assert set(out["stages"]) == set(STAGE_NAMES)
    assert out["rendered"] is True
    assert out["out_path"] == "demo.mp4"
    assert out["frames"] == 2


def test_pipeline_gate_rejected_fail_closed():
    """质量闸门未通过 → fail-closed 抛 ValueError, 不产出视频。"""
    def gate_fail(stage, prompt, ctx):
        if stage == "gate":
            return {"approved": False, "notes": "质量不达标"}
        return _fake_executor(stage, prompt, ctx)

    pipe = VideoPipeline()
    try:
        pipe.run("bad brief", executor=gate_fail,
                 renderer=lambda pj, path: {"out_path": path, "frames": 2})
        assert False, "应抛 ValueError"
    except ValueError as exc:
        assert "闸门" in str(exc)


def test_pipeline_unknown_stage_fail_closed():
    """含未知阶段 → fail-closed。"""
    pipe = VideoPipeline(stages=["research", "nope"])
    try:
        pipe.run("x", executor=_fake_executor)
        assert False, "应抛 ValueError"
    except ValueError as exc:
        assert "未知流水线阶段" in str(exc)


def test_pipeline_executor_error_propagates():
    """执行器抛错 → 原样传播 (fail-closed)。"""
    def boom(stage, prompt, ctx):
        raise ValueError("模型调用失败")

    pipe = VideoPipeline()
    try:
        pipe.run("x", executor=boom)
        assert False, "应抛 ValueError"
    except ValueError as exc:
        assert "模型调用失败" in str(exc)


def test_pipeline_compose_without_project_json_fail_closed():
    """compose 未产出 project_json → render 阶段 fail-closed。"""
    def no_pj(stage, prompt, ctx):
        if stage == "compose":
            return {"project_json": None}
        return _fake_executor(stage, prompt, ctx)

    pipe = VideoPipeline()
    try:
        pipe.run("x", executor=no_pj)
        assert False, "应抛 ValueError"
    except ValueError as exc:
        assert "project_json" in str(exc)


def test_pipeline_render_no_ffmpeg_reports_capability():
    """ffmpeg 不可用 → render 阶段返回 rendered=False + reason (明确上报, 非假成功)。"""
    import tuan_cli.web.code_anim_render as car
    if car.ffmpeg_available():
        # 环境有 ffmpeg, 此分支不触发; 改用注入 renderer 验证成功路径
        pipe = VideoPipeline()
        out = pipe.run("x", executor=_fake_executor,
                       renderer=lambda pj, path: {"out_path": path, "frames": 1})
        assert out["rendered"] is True
        return
    # 仅当 ffmpeg 缺失才走到这里
    pipe = VideoPipeline()
    out = pipe.run("x", executor=_fake_executor)
    assert out["rendered"] is False
    assert out["stages"]["render"]["reason"]
