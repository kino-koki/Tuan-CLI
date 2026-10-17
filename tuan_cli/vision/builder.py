"""builder: 把文本 + 图片按模型视觉能力, 构造发给模型的 content。

中间表示统一为 OpenAI 风格块 ({type: text|image_url})。Anthropic 适配器在
_convert_messages 里把 image_url 翻译为本地 image source 块, 因此这里不区分后端。

核心门控:
1. **视觉门控**: 模型不支持视觉时, 绝不发送任何图片字节, 仅把路径以文本注记送达,
   避免"静默失明" (模型以为收到图其实没有)。
2. **聚合预算**: 多图请求受「总量」约束 (字节 + 张数), 超限的图片降级为文本注记,
   保护上下文预算, 防止一次挂图把 token 预算打爆。
3. **损坏兜底**: 单张图片编码失败 (无 data 无 url) 时跳过该张, 不拖垮整轮请求。
"""

from __future__ import annotations

from typing import Any, List, Optional, Union

from .blocks import ImageRef

# 单次请求的图片聚合预算 (字节): 默认 20MB。超出的图片降级为文本注记。
DEFAULT_MAX_AGGREGATE_BYTES: int = 20 * 1024 * 1024

# 单次请求的图片数量上限: 超出的图片降级为文本注记。
DEFAULT_MAX_IMAGE_COUNT: int = 20

# 远程 URL 图片无法预知大小, 按 1MB 估算计入聚合预算 (防止无限堆 URL)。
_REMOTE_ESTIMATE_BYTES: int = 1024 * 1024


def _image_block(ref: ImageRef) -> dict:
    return {"type": "image_url", "image_url": {"url": ref.data_uri()}}


def _dropped_note(dropped: List[ImageRef], prefix: str = "") -> str:
    """超限/损坏图片的文本注记: 只记路径/来源, 不发送图片字节。"""
    if not dropped:
        return ""
    paths = ", ".join(r.path or r.url or "<data>" for r in dropped)
    return f"{prefix}以下图片未送达模型 (超出聚合预算或不可用), 仅记录来源: {paths}"


def _select_images(
    images: List[ImageRef],
    max_aggregate_bytes: int,
    max_image_count: int,
) -> tuple[List[ImageRef], List[ImageRef]]:
    """按聚合预算挑选可发送的图片: 返回 (送达, 降级)。

    规则: 按序累加字节 (远程 URL 按估算值计), 张数与字节任一超限即截断。
    """
    accepted: List[ImageRef] = []
    dropped: List[ImageRef] = []
    total = 0
    for ref in images:
        if len(accepted) >= max_image_count:
            dropped.append(ref)
            continue
        size = ref.byte_size()
        if size <= 0:
            size = _REMOTE_ESTIMATE_BYTES if ref.is_remote() else 0
        if total + size > max_aggregate_bytes:
            dropped.append(ref)
            continue
        total += size
        accepted.append(ref)
    return accepted, dropped


def build_user_content(
    text: str,
    images: List[ImageRef],
    vision_capable: bool,
    provider: str = "openai",
    max_aggregate_bytes: int = DEFAULT_MAX_AGGREGATE_BYTES,
    max_image_count: int = DEFAULT_MAX_IMAGE_COUNT,
) -> Union[str, List[dict]]:
    """构造一条 user 消息的 content。

    - 无图: 返回纯文本 str (保持与原管线兼容)。
    - 有图且支持视觉: 返回 [text 块, image_url 块, ...]; 超聚合预算的图片
      降级为文本注记块, 不会因多图打爆上下文预算。
    - 有图但不支持视觉: 降级为文本 + 路径注记 (图片不送达)。
    """
    if not images:
        return text
    if not vision_capable:
        paths = ", ".join(r.path or r.url or "<data>" for r in images)
        return (
            text
            + f"\n\n[注意: 当前模型不支持视觉, 以下图片未送达模型, 仅记录路径: {paths}]"
        )
    accepted, dropped = _select_images(images, max_aggregate_bytes, max_image_count)
    if not accepted:
        note = _dropped_note(images, "注意: 图片超出聚合预算, 均未送达模型。")
        return text + (f"\n\n[{note}]" if note else "")
    blocks: List[dict] = [{"type": "text", "text": text}]
    for ref in accepted:
        try:
            blocks.append(_image_block(ref))
        except (ValueError, TypeError):
            # 损坏引用 (无 data 无 url): 跳过该张, 不拖垮整轮请求
            dropped.append(ref)
    if dropped:
        note = _dropped_note(dropped, "注意:")
        if note:
            blocks.append({"type": "text", "text": note})
    return blocks


def build_tool_content(
    text: str,
    images: List[ImageRef],
    vision_capable: bool,
    max_aggregate_bytes: int = DEFAULT_MAX_AGGREGATE_BYTES,
    max_image_count: int = DEFAULT_MAX_IMAGE_COUNT,
) -> Union[str, List[dict]]:
    """构造工具结果消息的 content (工具返回图片时)。

    工具返回图片且模型支持视觉: 文本块 + 图片块 (同样受聚合预算约束);
    否则仅文本。
    """
    if not images or not vision_capable:
        return text
    accepted, dropped = _select_images(images, max_aggregate_bytes, max_image_count)
    blocks: List[dict] = [{"type": "text", "text": text}]
    for ref in accepted:
        try:
            blocks.append(_image_block(ref))
        except (ValueError, TypeError):
            dropped.append(ref)
    if dropped:
        note = _dropped_note(dropped, "注意:")
        if note:
            blocks.append({"type": "text", "text": note})
    return blocks
