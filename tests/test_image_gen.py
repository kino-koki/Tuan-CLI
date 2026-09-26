# -*- coding: utf-8 -*-
"""AI 图片生成工具测试。"""
from __future__ import annotations

import base64
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from qingxiaotuan.tools.image_gen import (
    ImageGenPlugin,
    _ensure_gen_dir,
    _gen_filename,
    generate_image,
    list_generated,
)
from qingxiaotuan.tools.base import ToolContext


# ------------------------------------------------------------------ 工具函数

class TestEnsureGenDir:
    def test_creates_dir(self, tmp_path):
        d = _ensure_gen_dir(str(tmp_path))
        assert d.exists()
        assert d.name == "generated"

    def test_idempotent(self, tmp_path):
        d1 = _ensure_gen_dir(str(tmp_path))
        d2 = _ensure_gen_dir(str(tmp_path))
        assert d1 == d2


class TestGenFilename:
    def test_format(self):
        name = _gen_filename("test")
        assert name.startswith("test_")
        assert name.endswith(".png")
        # Format: test_YYYYMMDD_HHMMSS_randomhex.png
        body = name[len("test_"):-len(".png")]
        assert "_" in body  # has separator
        parts = body.split("_")
        assert len(parts) == 3  # date_time_random

    def test_unique(self):
        names = {_gen_filename() for _ in range(100)}
        assert len(names) == 100  # all unique


# ------------------------------------------------------------------ generate_image

class TestGenerateImage:
    def test_empty_prompt_returns_error(self, tmp_path):
        ctx = ToolContext(kernel=None, workspace=str(tmp_path))
        result = generate_image(ctx, "")
        assert "[image_gen]" in result
        assert "不能为空" in result

    def test_no_api_key_returns_hint(self, tmp_path):
        ctx = ToolContext(kernel=None, workspace=str(tmp_path))
        env_backup = os.environ.get("OPENAI_API_KEY")
        env_backup2 = os.environ.get("STABILITY_API_KEY")
        try:
            os.environ.pop("OPENAI_API_KEY", None)
            os.environ.pop("STABILITY_API_KEY", None)
            result = generate_image(ctx, "a cat", provider="auto")
            assert "OPENAI_API_KEY" in result or "STABILITY_API_KEY" in result
        finally:
            if env_backup:
                os.environ["OPENAI_API_KEY"] = env_backup
            if env_backup2:
                os.environ["STABILITY_API_KEY"] = env_backup2

    def test_unsupported_provider(self, tmp_path):
        ctx = ToolContext(kernel=None, workspace=str(tmp_path))
        result = generate_image(ctx, "a cat", provider="nonexistent")
        assert "不支持" in result

    @patch("qingxiaotuan.tools.image_gen._generate_dalle")
    def test_dalle_success_saves_file(self, mock_dalle, tmp_path):
        # Create a minimal valid PNG (1x1 pixel, red)
        png_bytes = (
            b"\x89PNG\r\n\x1a\n"  # PNG signature
            b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
            b"\x08\x02\x00\x00\x00\x90wS\xde"
            b"\x00\x00\x00\x0cIDATx"
            b"\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N"
            b"\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        mock_dalle.return_value = {
            "b64": base64.b64encode(png_bytes).decode(),
            "revised_prompt": "A cute cat",
        }
        ctx = ToolContext(kernel=None, workspace=str(tmp_path))
        os.environ["OPENAI_API_KEY"] = "test-key"
        try:
            result = generate_image(ctx, "a cute cat", provider="openai")
            assert "已生成并保存" in result
            assert "DALL-E" in result or "openai" in result
            # Check file exists
            gen_dir = tmp_path / ".qxt" / "generated"
            assert gen_dir.exists()
            pngs = list(gen_dir.glob("*.png"))
            assert len(pngs) == 1
        finally:
            os.environ.pop("OPENAI_API_KEY", None)

    @patch("qingxiaotuan.tools.image_gen._generate_dalle")
    def test_dalle_error_returns_message(self, mock_dalle, tmp_path):
        mock_dalle.return_value = {"error": "API rate limit exceeded"}
        ctx = ToolContext(kernel=None, workspace=str(tmp_path))
        os.environ["OPENAI_API_KEY"] = "test-key"
        try:
            result = generate_image(ctx, "a cat", provider="openai")
            assert "生成失败" in result
            assert "rate limit" in result
        finally:
            os.environ.pop("OPENAI_API_KEY", None)


# ------------------------------------------------------------------ list_generated

class TestListGenerated:
    def test_empty_dir(self, tmp_path):
        result = list_generated(str(tmp_path))
        assert "暂无" in result

    def test_lists_files(self, tmp_path):
        gen_dir = tmp_path / ".qxt" / "generated"
        gen_dir.mkdir(parents=True)
        (gen_dir / "img_001.png").write_bytes(b"\x89PNG fake")
        (gen_dir / "img_002.png").write_bytes(b"\x89PNG fake2")
        result = list_generated(str(tmp_path))
        assert "2 张" in result
        assert "img_001.png" in result
        assert "img_002.png" in result


# ------------------------------------------------------------------ Plugin 注册

class TestImageGenPlugin:
    def test_plugin_metadata(self):
        from qingxiaotuan.core.kernel import Plugin
        p = ImageGenPlugin()
        assert p.name == "tools.image_gen"
        assert isinstance(p, Plugin)
        assert p.version == "0.1.0"

    def test_register_tools(self):
        from qingxiaotuan.tools.base import ToolRegistry
        from qingxiaotuan.core.kernel import Kernel

        kernel = Kernel()
        registry = ToolRegistry()
        kernel.provide("tool_registry", registry)
        config = MagicMock()
        config.get.return_value = True
        kernel.provide("config", config)

        plugin = ImageGenPlugin()
        plugin.activate(kernel)

        assert registry.get("image_generate") is not None
        assert registry.get("image_list_generated") is not None

        tool = registry.get("image_generate")
        assert "prompt" in tool.parameters["properties"]
        assert tool.long_running is True

    def test_disabled_by_config(self):
        from qingxiaotuan.tools.base import ToolRegistry
        from qingxiaotuan.core.kernel import Kernel

        kernel = Kernel()
        registry = ToolRegistry()
        kernel.provide("tool_registry", registry)
        config = MagicMock()
        config.get.return_value = False
        kernel.provide("config", config)

        plugin = ImageGenPlugin()
        plugin.activate(kernel)

        assert registry.get("image_generate") is None
