# -*- coding: utf-8 -*-
"""video_render 工具插件 —— Agent 工具面上的"生成视频"入口。

自研视频渲染能力 (claude-video + MotionHarness 融合) 的工具面暴露:
  * video_render: 从文本 prompt 或自定义 nodes 组合渲染短视频 (1280x720 / 30fps /
    默认 5s), 走 code_anim_render (Pillow 逐帧 + ffmpeg 管道编码), 写到用户工作区。
    依赖: ffmpeg (PATH 或 TUAN_FFMPEG) + Pillow。

    两种用法:
      (a) 简单: 传 prompt → 自动生成 [bg + title] 基础运动图形;
      (b) 高级: 传 nodes 数组 → 自由组合 code / particles / kinetic / transition /
          camera / path_motion 等丰富节点 (MotionHarness 运动图形核心能力)。

    支持的节点类型 (code_anim_render._KNOWN_NODE_TYPES):
      背景: bg (渐变/grid/纯色)
      文本: title (slide/zoom/wipe) / subtitle / kinetic (逐字弹跳/旋转)
      代码: code (语法高亮, 支持 python/js/ts 等)
      动效: transition / particles / beat
      补全: shape_morph / camera / path_motion / hand_drawn
      数据: dataflow / box
      图形: shape (line/poly/bezier/circle/spiral)

安全要点:
  * out_path 走 write_boundary 校验 (防穿越 / 覆盖任意文件) —— 与 write 工具同款;
  * long_running=True (渲染可达分钟级), 走 heartbeat 保活;
  * 参数校验在 validate_project 层做 fail-closed (拒绝 >4K / >3600s / >200k 帧 /
    >500 节点)。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from ..core.kernel import Kernel, Plugin
from .base import Tool, ToolContext, string_prop

log = logging.getLogger(__name__)


def _write_boundary(workspace: Path, path: Path) -> bool:
    """轻量 write_boundary: path 必须落在 workspace 内 (防穿越)。"""
    try:
        path.resolve().relative_to(workspace.resolve())
        return True
    except (OSError, ValueError):
        return False


def _build_nodes(prompt: str, duration: float, nodes_json: str) -> tuple[list[dict[str, Any]], str]:
    """构造 nodes 数组; 返回 (nodes, error)。error 非 None 表示 nodes_json 解析失败。

    nodes_json 为空 → 自动生成 [bg + title] 简单运动图形;
    nodes_json 非空 → 解析 JSON 数组 (LLM 自由组合), 失败返回错误。
    """
    if not nodes_json.strip():
        # 简单模式: 背景 + 标题
        return [
            {"type": "bg", "start": 0.0, "end": float(duration),
             "color": "#10121a", "color2": "#1a1d2e"},
            {"type": "title", "start": 0.1, "end": max(duration - 0.2, 0.3),
             "text": prompt[:80], "color": "#e8eaf0", "size": 56},
        ], ""
    try:
        parsed = json.loads(nodes_json)
    except json.JSONDecodeError as exc:
        return [], f"nodes_json 解析失败: {exc}"
    if not isinstance(parsed, list):
        return [], "nodes_json 必须是数组"
    return parsed, ""


def video_render(ctx: ToolContext, prompt: str = "", out_path: str = "",
                 width: int = 1280, height: int = 720,
                 fps: int = 30, duration: float = 5.0,
                 nodes_json: str = "") -> str:
    """渲染短视频 (自研 ffmpeg 后端)。prompt 简单模式 / nodes_json 高级模式。

    返回写入路径或错误。prompt 或 nodes_json 至少提供一个。
    """
    from ..web import code_anim_render as car

    if not prompt.strip() and not nodes_json.strip():
        return "[video_render] 缺少 prompt 或 nodes_json (至少提供一个)"

    if not car._pillow_available():
        return ("[video_render] Pillow 未安装 —— 请执行 `pip install 'tuan-cli[video]'` "
                "(或 `pip install Pillow imageio-ffmpeg`)")

    workspace = Path(ctx.workspace or ".").resolve()

    # 确定输出路径 (默认写到 workspace/video-<ts>.mp4)
    import time
    if not out_path.strip():
        out_path = f"video-{int(time.time())}.mp4"
    out = (workspace / out_path).resolve()
    if not _write_boundary(workspace, out):
        return f"[video_render] out_path 越界: 必须在工作区 {workspace} 内"
    out.parent.mkdir(parents=True, exist_ok=True)

    # 构造 nodes (prompt 简单模式 / nodes_json 高级模式)
    nodes, err = _build_nodes(prompt, duration, nodes_json)
    if err:
        return f"[video_render] {err}"

    # 构造 project_json (纯 JSON, code_anim_render 消费)
    project: dict[str, Any] = {
        "width": int(width),
        "height": int(height),
        "fps": int(fps),
        "duration": float(duration),
        "prompt": prompt,
        "nodes": nodes,
    }
    err = car.validate_project(project)
    if err:
        return f"[video_render] project 校验失败: {err}"

    if not car.ffmpeg_available():
        return ("[video_render] ffmpeg 不可用 —— 请安装 ffmpeg 并加入 PATH "
                "(或设置 TUAN_FFMPEG 环境变量)")

    node_types = [n.get("type", "?") for n in nodes if isinstance(n, dict)]
    ctx.heartbeat("video_render",
                  f"渲染 {duration}s @ {fps}fps ({width}x{height}, {len(nodes)} 节点: "
                  f"{','.join(node_types[:5])}{'...' if len(nodes) > 5 else ''})...")
    try:
        result = car.render_video(project, str(out), workspace=str(workspace))
        frames = result.get("frames", "?")
        elapsed = result.get("elapsed", 0)
        size_kb = result.get("size_bytes", 0) / 1024
        return (f"[video_render] 完成: {out.name} "
                f"({frames} 帧, {elapsed:.1f}s, {size_kb:.0f} KB)")
    except Exception as exc:  # noqa: BLE001
        log.warning("video_render 失败: %s", exc)
        return f"[video_render] 渲染失败: {exc}"


class VideoRenderPlugin(Plugin):
    name = "tools.video_render"
    requires = ["tool_registry"]

    def activate(self, kernel: Kernel) -> None:
        config = kernel.get("config")
        if config and not config.get("tools.video_render.enabled", True):
            return
        registry = kernel.require("tool_registry")
        registry.register(Tool(
            name="video_render",
            description=(
                "渲染短视频 (自研 ffmpeg 后端, claude-video + MotionHarness 融合)。"
                "两种用法: (1) 简单模式传 prompt → 自动生成背景+标题运动图形; "
                "(2) 高级模式传 nodes_json (JSON 数组) → 自由组合 code/particles/"
                "kinetic/transition/camera/path_motion 等丰富节点。默认 1280x720 / 30fps / 5s。"
                "输出写到工作区。依赖 ffmpeg + Pillow。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "prompt": string_prop("内容描述 (简单模式, 用作标题文本; 与 nodes_json 二选一)"),
                    "nodes_json": string_prop(
                        "节点数组 JSON (高级模式, 自由组合运动图形; 与 prompt 二选一)。"
                        "示例: [{\"type\":\"bg\",\"start\":0,\"end\":5,\"color\":\"#10121a\"},"
                        "{\"type\":\"title\",\"start\":0.2,\"end\":4.8,\"text\":\"Hello\","
                        "\"anim\":\"slide\"},{\"type\":\"code\",\"start\":1,\"end\":5,"
                        "\"code\":\"print('hi')\",\"language\":\"python\"}]"
                    ),
                    "out_path": string_prop("输出 mp4 文件名 (可选, 默认 video-<ts>.mp4)"),
                    "width": {"type": "integer", "description": "视频宽度 (默认 1280, 上限 7680)"},
                    "height": {"type": "integer", "description": "视频高度 (默认 720, 上限 7680)"},
                    "fps": {"type": "integer", "description": "帧率 (默认 30, 上限 240)"},
                    "duration": {"type": "number", "description": "时长秒数 (默认 5.0, 上限 3600)"},
                },
                "required": [],
            },
            handler=video_render, group="media", long_running=True,
        ))


__all__ = ["VideoRenderPlugin", "video_render"]
