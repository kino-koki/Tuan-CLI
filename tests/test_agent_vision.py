"""Agent 多模态视觉处理 (core/agent_vision.py) 的专项测试。

VisionMixin 的三个方法:
- attach_image: 挂接图片, 调 encode_image_source, 追加 pending_images, 返回提示
- clear_pending_images: 清空缓冲返回数量
- _tool_content: 工具返回图片且模型支持视觉时构建多模态 content

用 mock 隔离 vision.encode_image_source / build_tool_content 与 ImageRef,
避免真实文件系统与图片编码依赖。
"""

from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from tuan_cli.core.agent_vision import VisionMixin


# ------------------------------------------------------------ 测试基类/夹具


class DummyAgent(VisionMixin):
    """最小 Agent: 只提供 VisionMixin 依赖的属性。"""

    def __init__(self, *, model=None, workspace="/tmp/ws", config=None):
        self.pending_images = []
        self.model = model if model is not None else SimpleNamespace(
            capabilities=SimpleNamespace(vision=False)
        )
        self.workspace = workspace
        self.config = config if config is not None else _default_config()


def _default_config():
    # 最小 config: 仅提供 .get (agent.vision_max_mb 可被覆盖)
    return SimpleNamespace(get=lambda key, default=None: default)


class FakeImageRef:
    """最小 ImageRef 替身: 提供 is_remote/byte_size/media_type/path。"""

    def __init__(self, *, remote=False, path="/tmp/a.png", size=1024, media="image/png"):
        self._remote = remote
        self.path = path
        self._size = size
        self.media_type = media

    def is_remote(self):
        return self._remote

    def byte_size(self):
        return self._size


# ------------------------------------------------------------ attach_image

class TestAttachImage:
    def test_local_image(self):
        """本地图片: 提示含路径/大小/类型, pending_images 追加。"""
        agent = DummyAgent()
        ref = FakeImageRef(path="/tmp/photo.png", size=2048, media="image/png")
        # encode_image_source 在方法内 from ..vision import, 故 patch tuan_cli.vision 上的属性
        with patch("tuan_cli.vision.encode_image_source", return_value=ref) as m:
            msg = agent.attach_image("/tmp/photo.png")
        m.assert_called_once_with("/tmp/photo.png", "/tmp/ws", 15 * 1024 * 1024)
        assert agent.pending_images == [ref]
        assert "已挂接图片" in msg
        assert "/tmp/photo.png" in msg
        assert "2KB" in msg
        assert "image/png" in msg

    def test_remote_image(self):
        """远程图片: 提示走远程文案, 不显示本地字节信息。"""
        agent = DummyAgent()
        ref = FakeImageRef(remote=True, path="https://x/y.png", size=0)
        with patch("tuan_cli.vision.encode_image_source", return_value=ref):
            msg = agent.attach_image("https://x/y.png")
        assert agent.pending_images == [ref]
        assert "已挂接远程图片" in msg
        assert "https://x/y.png" in msg

    def test_custom_max_mb(self):
        """vision_max_mb 可配置: 影响传给 encode_image_source 的字节上限。"""
        agent = DummyAgent(config=SimpleNamespace(
            get=lambda key, default=None: 3 if key == "agent.vision_max_mb" else default
        ))
        ref = FakeImageRef()
        with patch("tuan_cli.vision.encode_image_source", return_value=ref) as m:
            agent.attach_image("/tmp/x.png")
        m.assert_called_once_with("/tmp/x.png", "/tmp/ws", 3 * 1024 * 1024)

    def test_append_multiple(self):
        """多次挂接累积到 pending_images。"""
        agent = DummyAgent()
        refs = [FakeImageRef(path=f"/tmp/{i}.png") for i in range(3)]
        with patch("tuan_cli.vision.encode_image_source",
                   side_effect=refs) as m:
            for spec in ("/tmp/0.png", "/tmp/1.png", "/tmp/2.png"):
                agent.attach_image(spec)
        assert m.call_count == 3
        assert len(agent.pending_images) == 3


# ------------------------------------------------------------ clear_pending_images

class TestClearPendingImages:
    def test_clear_non_empty(self):
        """清空返回数量, pending_images 置空。"""
        agent = DummyAgent()
        agent.pending_images = [FakeImageRef(), FakeImageRef(), FakeImageRef()]
        n = agent.clear_pending_images()
        assert n == 3
        assert agent.pending_images == []

    def test_clear_empty(self):
        """空缓冲清空返回 0。"""
        agent = DummyAgent()
        assert agent.clear_pending_images() == 0


# ------------------------------------------------------------ _tool_content

class TestToolContent:
    def _make_result(self, images):
        from tuan_cli.tools.base import ToolResult
        return ToolResult(status="ok", content="工具输出", images=images)

    def test_images_and_vision_builds_content(self):
        """有图片 + 模型支持视觉: 调 build_tool_content 返回其值。"""
        agent = DummyAgent(model=SimpleNamespace(
            capabilities=SimpleNamespace(vision=True)
        ))
        img = FakeImageRef()
        result = self._make_result([img])
        blocks = [{"type": "text", "text": "工具输出"}]
        with patch("tuan_cli.vision.build_tool_content",
                   return_value=blocks) as m:
            out = agent._tool_content(result)
        m.assert_called_once_with(result.content, [img], True)
        assert out is blocks

    def test_images_no_vision_returns_original(self):
        """有图片但模型不支持视觉: 原样返回, 不调 build_tool_content。"""
        agent = DummyAgent(model=SimpleNamespace(
            capabilities=SimpleNamespace(vision=False)
        ))
        result = self._make_result([FakeImageRef()])
        with patch("tuan_cli.vision.build_tool_content") as m:
            out = agent._tool_content(result)
        m.assert_not_called()
        assert out is result

    def test_no_images_returns_original(self):
        """无图片 (即使视觉模型): 原样返回。"""
        agent = DummyAgent(model=SimpleNamespace(
            capabilities=SimpleNamespace(vision=True)
        ))
        result = self._make_result([])
        with patch("tuan_cli.vision.build_tool_content") as m:
            out = agent._tool_content(result)
        m.assert_not_called()
        assert out is result

    def test_non_tool_result_returns_original(self):
        """非 ToolResult (如纯字符串): 原样返回。"""
        agent = DummyAgent()
        with patch("tuan_cli.vision.build_tool_content") as m:
            out = agent._tool_content("just text")
        m.assert_not_called()
        assert out == "just text"

    def test_images_none_returns_original(self):
        """images 为 None: 原样返回。"""
        agent = DummyAgent(model=SimpleNamespace(
            capabilities=SimpleNamespace(vision=True)
        ))
        result = self._make_result(None)
        with patch("tuan_cli.vision.build_tool_content") as m:
            out = agent._tool_content(result)
        m.assert_not_called()
        assert out is result
