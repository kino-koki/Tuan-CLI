# -*- coding: utf-8 -*-
"""video_render 工具测试 (自研 ffmpeg 渲染, claude-video + MotionHarness 融合)。

覆盖:
  * 插件注册: schema 暴露 video_render, 参数正确
  * prompt 生成 project_json (nodes 含 bg + title)
  * out_path 默认写到 workspace/video-<ts>.mp4
  * out_path 越界 (.. 或绝对路径) → 拒绝
  * validate_project 失败 (超大分辨率/时长) → 返回错误
  * ffmpeg 不可用 → fail-closed 报错
  * 正常渲染路径 (monkeypatch render_video)
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from tuan_cli.core.kernel import Kernel
from tuan_cli.tools.base import ToolContext
from tuan_cli.tools.video_render_tool import VideoRenderPlugin, video_render


# ---------------------------------------------------------------------------
# 插件注册
# ---------------------------------------------------------------------------

class _FakeRegistry:
    def __init__(self) -> None:
        self.tools: dict[str, Any] = {}

    def register(self, tool: Any) -> None:
        self.tools[tool.name] = tool


class _FakeKernel:
    def __init__(self, config: dict | None = None) -> None:
        self._registry = _FakeRegistry()
        self._config = config or {}

    def get(self, key: str) -> Any:
        return self._config

    def require(self, key: str) -> _FakeRegistry:
        assert key == "tool_registry"
        return self._registry


def test_plugin_registers_video_render():
    kernel = _FakeKernel()
    VideoRenderPlugin().activate(kernel)  # type: ignore[arg-type]
    assert "video_render" in kernel._registry.tools
    tool = kernel._registry.tools["video_render"]
    assert tool.name == "video_render"
    assert tool.group == "media"
    assert tool.long_running is True
    assert tool.parameters["required"] == ["prompt"]
    assert "prompt" in tool.parameters["properties"]
    assert "out_path" in tool.parameters["properties"]


def test_plugin_disabled_via_config():
    kernel = _FakeKernel({"tools.video_render.enabled": False})
    VideoRenderPlugin().activate(kernel)  # type: ignore[arg-type]
    assert "video_render" not in kernel._registry.tools


# ---------------------------------------------------------------------------
# out_path 边界
# ---------------------------------------------------------------------------

def test_out_path_default_writes_to_workspace(tmp_path):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    ctx = ToolContext(workspace=str(workspace))
    ctx.heartbeat = lambda *a, **k: None  # type: ignore[method-assign]

    # monkeypatch ffmpeg 可用性 + render_video
    from tuan_cli.web import code_anim_render as car
    orig_ffmpeg, orig_render = car.ffmpeg_available, car.render_video
    car.ffmpeg_available = lambda: True
    captured = {}

    def _fake_render(project, out, **kwargs):
        captured["out"] = out
        captured["project"] = project
        return {"out_path": out, "frames": 150, "elapsed": 0.1, "size_bytes": 1024}
    car.render_video = _fake_render
    try:
        result = video_render(ctx, "测试标题")
    finally:
        car.ffmpeg_available, car.render_video = orig_ffmpeg, orig_render

    assert "[video_render] 完成" in result
    assert "测试标题" in captured["project"]["nodes"][1]["text"]
    assert captured["project"]["width"] == 1280
    assert captured["project"]["fps"] == 30
    assert captured["project"]["duration"] == 5.0
    out_file = Path(captured["out"])
    assert out_file.exists() is False  # fake 不真写
    assert out_file.parent == workspace.resolve()


def test_out_path_traversal_rejected(tmp_path):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    ctx = ToolContext(workspace=str(workspace))
    result = video_render(ctx, "prompt", out_path="../../escape.mp4")
    assert "越界" in result


def test_out_path_absolute_outside_rejected(tmp_path):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    outside = tmp_path / "outside.mp4"
    ctx = ToolContext(workspace=str(workspace))
    result = video_render(ctx, "prompt", out_path=str(outside))
    assert "越界" in result


# ---------------------------------------------------------------------------
# validate_project fail-closed
# ---------------------------------------------------------------------------

def test_validate_rejects_oversized_resolution(tmp_path):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    ctx = ToolContext(workspace=str(workspace))
    result = video_render(ctx, "prompt", width=9999, height=720)
    assert "校验失败" in result


def test_validate_rejects_oversized_duration(tmp_path):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    ctx = ToolContext(workspace=str(workspace))
    result = video_render(ctx, "prompt", duration=4000)
    assert "校验失败" in result


# ---------------------------------------------------------------------------
# ffmpeg 不可用
# ---------------------------------------------------------------------------

def test_ffmpeg_unavailable(tmp_path, monkeypatch):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    ctx = ToolContext(workspace=str(workspace))
    from tuan_cli.web import code_anim_render as car
    monkeypatch.setattr(car, "ffmpeg_available", lambda: False)
    result = video_render(ctx, "prompt")
    assert "ffmpeg 不可用" in result


# ---------------------------------------------------------------------------
# 渲染失败
# ---------------------------------------------------------------------------

def test_render_exception(tmp_path, monkeypatch):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    ctx = ToolContext(workspace=str(workspace))
    ctx.heartbeat = lambda *a, **k: None  # type: ignore[method-assign]
    from tuan_cli.web import code_anim_render as car
    monkeypatch.setattr(car, "ffmpeg_available", lambda: True)
    monkeypatch.setattr(car, "render_video", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    result = video_render(ctx, "prompt")
    assert "渲染失败" in result
    assert "boom" in result
