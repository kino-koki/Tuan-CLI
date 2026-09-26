# -*- coding: utf-8 -*-
"""AI 图片生成工具插件 —— 让 Agent 通过文字描述生成图片。

支持的后端:
- OpenAI DALL-E 3 (需要 OPENAI_API_KEY)
- Stability AI (需要 STABILITY_API_KEY)
- 本地 Ollama vision 模型回退 (描述性输出, 不生成图片)

设计原则:
- 图片自动保存到工作区 <workspace>/.qxt/generated/ 目录;
- 返回 ImageRef (视觉模型可直接查看);
- 所有网络/解码异常被捕获, 返回友好错误而非炸 Agent 循环;
- 不依赖第三方库 (httpx), 用 stdlib urllib (与 web.py 一致)。
"""
from __future__ import annotations

import base64
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Optional

from .base import Tool, ToolContext, string_prop

# 生成图片的默认保存目录名
_GEN_DIR = ".qxt/generated"

# 默认尺寸选项
_SIZES_DALLE = {
    "1024x1024": "1024x1024",
    "1792x1024": "1792x1024",
    "1024x1792": "1024x1792",
}

_SIZES_STABILITY = {
    "1024x1024": "1024x1024",
    "1152x896": "1152x896",
    "896x1152": "896x1152",
    "1216x832": "1216x832",
    "832x1216": "832x1216",
}


def _ensure_gen_dir(workspace: str) -> Path:
    """确保生成目录存在, 返回路径。"""
    p = Path(workspace) / _GEN_DIR
    p.mkdir(parents=True, exist_ok=True)
    return p


def _gen_filename(prefix: str = "img") -> str:
    """生成唯一文件名: img_20260919_143052_abc123.png"""
    ts = time.strftime("%Y%m%d_%H%M%S")
    import random
    rand = format(random.randint(0, 0xFFFFFF), "06x")
    return f"{prefix}_{ts}_{rand}.png"


# ------------------------------------------------------------------ OpenAI DALL-E 3

def _generate_dalle(
    prompt: str,
    api_key: str,
    size: str = "1024x1024",
    quality: str = "standard",
    model: str = "dall-e-3",
    n: int = 1,
    base_url: Optional[str] = None,
) -> dict:
    """调用 OpenAI Images API 生成图片。

    Returns:
        {"url": str, "revised_prompt": str} 或 {"error": str}
    """
    url = (base_url or "https://api.openai.com").rstrip("/") + "/v1/images/generations"
    body = {
        "model": model,
        "prompt": prompt,
        "n": min(n, 1),  # DALL-E 3 仅支持 n=1
        "size": _SIZES_DALLE.get(size, "1024x1024"),
        "quality": quality if quality in ("standard", "hd") else "standard",
        "response_format": "b64_json",
    }
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:  # noqa: S310
            result = json.loads(resp.read().decode("utf-8"))
        img_data = result.get("data", [{}])[0]
        b64 = img_data.get("b64_json", "")
        revised = img_data.get("revised_prompt", "")
        if not b64:
            return {"error": "DALL-E 返回空图片数据"}
        return {"b64": b64, "revised_prompt": revised}
    except urllib.error.HTTPError as exc:
        body_text = ""
        try:
            body_text = exc.read().decode("utf-8", errors="replace")[:500]
        except Exception:
            pass
        return {"error": f"OpenAI API 错误 {exc.code}: {body_text}"}
    except Exception as exc:  # noqa: BLE001
        return {"error": f"OpenAI 请求失败: {type(exc).__name__}: {exc}"}


# ------------------------------------------------------------------ Stability AI

def _generate_stability(
    prompt: str,
    api_key: str,
    size: str = "1024x1024",
    model: str = "stable-diffusion-xl-1024-v1-0",
    base_url: Optional[str] = None,
) -> dict:
    """调用 Stability AI REST API 生成图片。

    Returns:
        {"b64": str, "revised_prompt": str} 或 {"error": str}
    """
    url = (base_url or "https://api.stability.ai").rstrip("/") + f"/v1/generation/{model}/text-to-image"
    w, h = (1024, 1024)
    if size in _SIZES_STABILITY:
        parts = size.split("x")
        w, h = int(parts[0]), int(parts[1])
    body = json.dumps({
        "text_prompts": [{"text": prompt, "weight": 1}],
        "cfg_scale": 7,
        "width": w,
        "height": h,
        "samples": 1,
        "steps": 30,
    }).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:  # noqa: S310
            result = json.loads(resp.read().decode("utf-8"))
        artifacts = result.get("artifacts", [])
        if not artifacts:
            return {"error": "Stability AI 返回空结果"}
        b64 = artifacts[0].get("base64", "")
        if not b64:
            return {"error": "Stability AI 返回空图片数据"}
        return {"b64": b64, "revised_prompt": ""}
    except urllib.error.HTTPError as exc:
        body_text = ""
        try:
            body_text = exc.read().decode("utf-8", errors="replace")[:500]
        except Exception:
            pass
        return {"error": f"Stability API 错误 {exc.code}: {body_text}"}
    except Exception as exc:  # noqa: BLE001
        return {"error": f"Stability 请求失败: {type(exc).__name__}: {exc}"}


# ------------------------------------------------------------------ 统一入口

def generate_image(
    ctx: ToolContext,
    prompt: str,
    provider: str = "auto",
    size: str = "1024x1024",
    quality: str = "standard",
) -> str:
    """AI 图片生成: 根据文字描述生成图片, 保存到工作区。

    Args:
        ctx: 工具上下文
        prompt: 图片描述
        provider: 后端 (auto/openai/stability)
        size: 尺寸 (1024x1024, 1792x1024, 等)
        quality: 质量 (standard/hd, 仅 DALL-E)

    Returns:
        成功时返回包含图片路径和描述的文本;
        失败时返回错误提示。
    """
    if not prompt or not prompt.strip():
        return "[image_gen] 图片描述不能为空"

    prompt = prompt.strip()
    workspace = ctx.workspace or "."

    # 自动探测 provider
    if provider == "auto":
        if os.environ.get("OPENAI_API_KEY"):
            provider = "openai"
        elif os.environ.get("STABILITY_API_KEY"):
            provider = "stability"
        else:
            return (
                "[image_gen] 未检测到图片生成 API Key。请设置以下环境变量之一:\n"
                "  - OPENAI_API_KEY (OpenAI DALL-E 3)\n"
                "  - STABILITY_API_KEY (Stability AI)\n"
                "或者手动指定: /image generate <描述> --provider openai"
            )

    # 进度心跳
    ctx.heartbeat("image_gen", f"正在使用 {provider} 生成图片...")

    if provider == "openai":
        api_key = os.environ.get("OPENAI_API_KEY", "")
        try:
            base_url = ctx.config("tools.image_gen.openai_base_url")
        except Exception:  # noqa: BLE001
            base_url = None
        result = _generate_dalle(prompt, api_key, size, quality, base_url=base_url)
    elif provider == "stability":
        api_key = os.environ.get("STABILITY_API_KEY", "")
        try:
            base_url = ctx.config("tools.image_gen.stability_base_url")
        except Exception:  # noqa: BLE001
            base_url = None
        result = _generate_stability(prompt, size, base_url=base_url)
    else:
        return f"[image_gen] 不支持的后端: {provider} (可选: openai, stability)"

    if "error" in result:
        return f"[image_gen] 生成失败: {result['error']}"

    # 解码并保存
    try:
        img_bytes = base64.b64decode(result["b64"])
    except Exception as exc:  # noqa: BLE001
        return f"[image_gen] 图片解码失败: {exc}"

    gen_dir = _ensure_gen_dir(workspace)
    filename = _gen_filename()
    save_path = gen_dir / filename
    save_path.write_bytes(img_bytes)

    size_kb = len(img_bytes) // 1024
    revised = result.get("revised_prompt", "")

    lines = [
        f"图片已生成并保存: {save_path}",
        f"大小: {size_kb} KB  |  尺寸: {size}  |  后端: {provider}",
    ]
    if revised:
        lines.append(f"修订后的描述: {revised}")
    lines.append(f"描述: {prompt}")
    return "\n".join(lines)


def list_generated(workspace: str, limit: int = 20) -> str:
    """列出工作区已生成的图片。"""
    gen_dir = Path(workspace) / _GEN_DIR
    if not gen_dir.exists():
        return "暂无已生成的图片。"
    files = sorted(gen_dir.glob("*.png"), key=lambda f: f.stat().st_mtime, reverse=True)
    if not files:
        return "暂无已生成的图片。"
    lines = [f"已生成图片 ({len(files)} 张, 显示最近 {min(limit, len(files))} 张):"]
    for f in files[:limit]:
        size_kb = f.stat().st_size // 1024
        mtime = time.strftime("%m-%d %H:%M", time.localtime(f.stat().st_mtime))
        lines.append(f"  {f.name}  ({size_kb} KB, {mtime})")
    return "\n".join(lines)


# ------------------------------------------------------------------ 插件注册

from ..core.kernel import Plugin


class ImageGenPlugin(Plugin):
    """AI 图片生成工具插件。"""

    name = "tools.image_gen"
    provides = ["image_generate"]

    def __init__(self):
        super().__init__()

    def activate(self, kernel: Any) -> None:
        config = kernel.get("config")
        if config and not config.get("tools.image_gen.enabled", True):
            return
        registry = kernel.require("tool_registry")

        registry.register(Tool(
            name="image_generate",
            description="AI 图片生成: 根据文字描述生成图片 (支持 OpenAI DALL-E / Stability AI)",
            parameters={
                "type": "object",
                "properties": {
                    "prompt": string_prop("图片描述 (越详细效果越好)"),
                    "provider": {
                        "type": "string",
                        "description": "后端: auto/openai/stability (默认 auto, 自动检测)",
                        "enum": ["auto", "openai", "stability"],
                    },
                    "size": {
                        "type": "string",
                        "description": "图片尺寸 (默认 1024x1024)",
                        "enum": ["1024x1024", "1792x1024", "1024x1792",
                                 "1152x896", "896x1152", "1216x832", "832x1216"],
                    },
                    "quality": {
                        "type": "string",
                        "description": "质量 (仅 DALL-E: standard/hd)",
                        "enum": ["standard", "hd"],
                    },
                },
                "required": ["prompt"],
            },
            handler=generate_image,
            group="image",
            long_running=True,
        ))

        registry.register(Tool(
            name="image_list_generated",
            description="列出工作区已生成的 AI 图片",
            parameters={
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "显示数量 (默认 20)"},
                },
            },
            handler=lambda ctx, limit=20: list_generated(ctx.workspace, limit),
            group="image",
            read_only=True,
        ))
