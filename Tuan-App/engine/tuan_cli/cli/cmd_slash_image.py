"""斜杠命令 —— 多模态图片管理域 (/image /images /clear-images)。

拆分自 cmd_slash.py: 承载图片挂接、待发送图片列表、以及 AI 图片生成。
"""

from __future__ import annotations

from ._ui_singleton import ui


def _cmd_image(agent, head: str, arg: str) -> None:
    """/image /images /clear-images /image generate: 多模态图片管理 + AI 生成。"""
    if head == "/images":
        if not getattr(agent, "pending_images", None):
            ui.info("当前没有待发送的图片。")
            return
        for i, ref in enumerate(agent.pending_images, 1):
            loc = ref.path or ref.url or "<data>"
            ui.success(f"{i}. {loc} ({ref.byte_size() // 1024}KB, {ref.media_type})")
        return
    if head == "/clear-images":
        n = agent.clear_pending_images()
        ui.info(f"已清除 {n} 张待发送图片。")
        return
    # /image generate <描述> — AI 图片生成
    if arg and arg.strip().lower().startswith("generate"):
        _cmd_image_generate(agent, arg.strip()[len("generate"):].strip())
        return
    # /image list — 已生成图片列表
    if arg and arg.strip().lower() == "list":
        from ..tools.image_gen import list_generated
        workspace = getattr(getattr(agent, "ctx", None), "workspace", ".") or "."
        ui.info(list_generated(workspace))
        return
    if not arg:
        ui.info("用法:")
        ui.info("  /image <本地路径 | http(s) URL>       挂接图片随下轮发送")
        ui.info("  /image generate <描述>                 AI 生成图片")
        ui.info("  /image list                           已生成图片列表")
        ui.info("  /images                              查看待发送图片")
        ui.info("  /clear-images                        清除待发送图片")
        return
    try:
        msg = agent.attach_image(arg.strip())
        ui.success(msg)
    except Exception as exc:  # noqa: BLE001
        ui.error(f"挂接图片失败: {exc}")


def _cmd_image_generate(agent, arg: str) -> None:
    """/image generate <描述> — AI 图片生成。"""
    if not arg:
        ui.info("用法: /image generate <图片描述>")
        ui.info("示例: /image generate 一只穿着太空服的猫在月球上跳跃")
        ui.info("选项: --provider openai|stability --size 1024x1024 --quality hd")
        return
    # 解析简单参数
    provider = "auto"
    size = "1024x1024"
    quality = "standard"
    parts = arg.split(" --")
    prompt_parts = []
    for part in parts:
        if part.startswith("provider "):
            provider = part.split(" ", 1)[1].strip()
        elif part.startswith("size "):
            size = part.split(" ", 1)[1].strip()
        elif part.startswith("quality "):
            quality = part.split(" ", 1)[1].strip()
        else:
            prompt_parts.append(part)
    prompt = " ".join(prompt_parts).strip()
    if not prompt:
        ui.info("请输入图片描述。")
        return
    workspace = getattr(getattr(agent, "ctx", None), "workspace", ".") or "."
    ui.info(f"[AI 绘图] 正在生成: {prompt[:60]}{'...' if len(prompt) > 60 else ''}")
    try:
        from ..tools.image_gen import generate_image
        from ..tools.base import ToolContext
        kernel = getattr(agent, "kernel", None)
        ctx = ToolContext(
            kernel=kernel,
            workspace=workspace,
            on_progress=lambda name, msg: ui.info(f"  {msg}"),
        )
        result = generate_image(ctx, prompt, provider=provider, size=size, quality=quality)
        if result.startswith("[image_gen] 生成失败") or result.startswith("[image_gen] 未检测到"):
            ui.error(result)
        else:
            ui.success(result)
            # 自动挂接生成的图片, 方便视觉模型查看
            import re
            m = re.search(r"已保存: (.+)$", result, re.MULTILINE)
            if m:
                try:
                    agent.attach_image(m.group(1).strip())
                    ui.info("(已自动挂接, 视觉模型下轮可查看)")
                except Exception:  # noqa: BLE001
                    pass
    except Exception as exc:  # noqa: BLE001
        ui.error(f"图片生成失败: {exc}")
