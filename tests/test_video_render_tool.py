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

import json
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
    assert tool.parameters["required"] == []  # prompt/nodes_json 二选一, 均非必填
    assert "prompt" in tool.parameters["properties"]
    assert "nodes_json" in tool.parameters["properties"]
    assert "out_path" in tool.parameters["properties"]


def test_plugin_disabled_via_config():
    kernel = _FakeKernel({"tools.video_render.enabled": False})
    VideoRenderPlugin().activate(kernel)  # type: ignore[arg-type]
    assert "video_render" not in kernel._registry.tools


def test_prompt_or_nodes_required(tmp_path):
    """prompt 和 nodes_json 都缺 → 报错 (fail-closed)。"""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    ctx = ToolContext(kernel=None, workspace=str(workspace))
    result = video_render(ctx)
    assert "缺少 prompt 或 nodes_json" in result


def test_nodes_json_invalid_json(tmp_path):
    """nodes_json 非法 JSON → 解析错误。"""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    ctx = ToolContext(kernel=None, workspace=str(workspace))
    result = video_render(ctx, nodes_json="not json")
    assert "解析失败" in result


def test_nodes_json_not_array(tmp_path):
    """nodes_json 是对象而非数组 → 报错。"""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    ctx = ToolContext(kernel=None, workspace=str(workspace))
    result = video_render(ctx, nodes_json='{"type":"bg"}')
    assert "必须是数组" in result


def test_nodes_json_advanced_mode(tmp_path):
    """nodes_json 高级模式: 传 nodes 数组 (含 code + particles) 渲染。"""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    ctx = ToolContext(kernel=None, workspace=str(workspace))
    ctx.heartbeat = lambda *a, **k: None  # type: ignore[method-assign]

    nodes_json = json.dumps([
        {"type": "bg", "start": 0.0, "end": 3.0, "color": "#10121a"},
        {"type": "title", "start": 0.2, "end": 2.8, "text": "Advanced", "anim": "slide"},
        {"type": "code", "start": 1.0, "end": 3.0,
         "code": "print('hi')", "language": "python"},
        {"type": "particles", "start": 0.0, "end": 3.0, "count": 50},
    ])
    from tuan_cli.web import code_anim_render as car
    orig_ffmpeg, orig_render = car.ffmpeg_available, car.render_video
    car.ffmpeg_available = lambda: True
    captured = {}

    def _fake_render(project, out, **kwargs):
        captured["project"] = project
        return {"out_path": out, "frames": 90, "elapsed": 0.1, "size_bytes": 2048}
    car.render_video = _fake_render
    try:
        result = video_render(ctx, nodes_json=nodes_json, duration=3.0)
    finally:
        car.ffmpeg_available, car.render_video = orig_ffmpeg, orig_render

    assert "[video_render] 完成" in result
    assert len(captured["project"]["nodes"]) == 4
    node_types = [n["type"] for n in captured["project"]["nodes"]]
    assert node_types == ["bg", "title", "code", "particles"]


# ---------------------------------------------------------------------------
# out_path 边界
# ---------------------------------------------------------------------------

def test_out_path_default_writes_to_workspace(tmp_path):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    ctx = ToolContext(kernel=None, workspace=str(workspace))
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
    ctx = ToolContext(kernel=None, workspace=str(workspace))
    result = video_render(ctx, "prompt", out_path="../../escape.mp4")
    assert "越界" in result


def test_out_path_absolute_outside_rejected(tmp_path):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    outside = tmp_path / "outside.mp4"
    ctx = ToolContext(kernel=None, workspace=str(workspace))
    result = video_render(ctx, "prompt", out_path=str(outside))
    assert "越界" in result


# ---------------------------------------------------------------------------
# validate_project fail-closed
# ---------------------------------------------------------------------------

def test_validate_rejects_oversized_resolution(tmp_path):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    ctx = ToolContext(kernel=None, workspace=str(workspace))
    result = video_render(ctx, "prompt", width=9999, height=720)
    assert "校验失败" in result


def test_validate_rejects_oversized_duration(tmp_path):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    ctx = ToolContext(kernel=None, workspace=str(workspace))
    result = video_render(ctx, "prompt", duration=4000)
    assert "校验失败" in result


# ---------------------------------------------------------------------------
# ffmpeg 不可用
# ---------------------------------------------------------------------------

def test_ffmpeg_unavailable(tmp_path, monkeypatch):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    ctx = ToolContext(kernel=None, workspace=str(workspace))
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
    ctx = ToolContext(kernel=None, workspace=str(workspace))
    ctx.heartbeat = lambda *a, **k: None  # type: ignore[method-assign]
    from tuan_cli.web import code_anim_render as car
    monkeypatch.setattr(car, "ffmpeg_available", lambda: True)
    monkeypatch.setattr(car, "render_video", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    result = video_render(ctx, "prompt")
    assert "渲染失败" in result
    assert "boom" in result
