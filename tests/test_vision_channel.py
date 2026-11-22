"""多模态回传通道端到端回归: read_file(图片) → ToolResult.images → 工具消息内容块。

此前 ToolResult.images 通道已声明但无任何工具填充, 工具消息组装也不消费。
本文件验证: 图片文件经 read_file 读取后, images 进入 ToolResult; 且
ToolExecutor._tool_msg_content 按模型视觉能力把结果转成 文本块+图片块。
"""

import base64
from pathlib import Path

import pytest

from tuan_cli.app import build_kernel
from tuan_cli.core.agent import Agent
from tuan_cli.core.tool_executor import ToolExecutor

# 1x1 红色像素 PNG
_PNG_B64 = ("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ"
            "AAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")


@pytest.fixture()
def img_ctx(tmp_path, tuan_home):
    kernel = build_kernel()
    config = kernel.require("config")
    agent = Agent(kernel=kernel, config=config, workspace=str(tmp_path),
                  confirm=lambda _p: True)
    img = tmp_path / "pixel.png"
    img.write_bytes(base64.b64decode(_PNG_B64))
    return kernel, agent, img


def test_read_file_image_returns_toolresult_with_images(img_ctx):
    kernel, agent, img = img_ctx
    reg = kernel.require("tool_registry")
    res = reg.get("read_file").handler(agent.ctx, path=str(img))
    # handler 直接返回结构化结果, 携带图片富通道
    assert getattr(res, "images", None), "read_file 未填充 images 通道"
    assert res.images[0].media_type == "image/png"
    assert res.status == "ok"
    # 经 registry.dispatch_result 透传后 images 仍在 (不被二次包装丢掉)
    import json as _json
    out = reg.dispatch_result("read_file", _json.dumps({"path": str(img)}), agent.ctx)
    assert getattr(out, "images", None)


def test_tool_msg_content_builds_image_blocks_for_vision_model(img_ctx):
    kernel, agent, img = img_ctx
    reg = kernel.require("tool_registry")
    import json as _json
    res = reg.dispatch_result("read_file", _json.dumps({"path": str(img)}), agent.ctx)
    ex = ToolExecutor(
        registry=reg,
        vision_ctx_fn=lambda: (True, "openai"),   # 视觉模型
    )
    content = ex._tool_msg_content(res)
    assert isinstance(content, list), "视觉模型下应转换为内容块列表"
    types = [b.get("type") for b in content]
    assert "text" in types and "image_url" in types


def test_tool_msg_content_degrades_for_text_only_model(img_ctx):
    kernel, agent, img = img_ctx
    reg = kernel.require("tool_registry")
    import json as _json
    res = reg.dispatch_result("read_file", _json.dumps({"path": str(img)}), agent.ctx)
    ex = ToolExecutor(
        registry=reg,
        vision_ctx_fn=lambda: (False, "openai"),  # 纯文本模型
    )
    content = ex._tool_msg_content(res)
    assert isinstance(content, str), "无视觉能力时应降级为纯文本"
    assert "不支持视觉" in content or "图片" in content


def test_read_file_text_still_plain_string(img_ctx):
    kernel, agent, img = img_ctx
    txt = img.parent / "note.txt"
    txt.write_text("你好", encoding="utf-8")
    reg = kernel.require("tool_registry")
    res = reg.get("read_file").handler(agent.ctx, path=str(txt))
    assert isinstance(res, str) and "你好" in res
