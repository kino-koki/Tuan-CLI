#!/usr/bin/env python3
"""官方形象资产管线。

用途
----
用「各模型官方头像 / logo」替换原先 13×5 张画师同人立绘：
  - 官方资源无版权风险，且与各家产品 UI 实际呈现一致（ChatGPT / Claude 的
    聊天头像本来就是 logo，不是拟人角色）；
  - 国内站点可达的模型直接下载官方 PNG；官网不可达（OpenAI / Google /
    x.ai / Mistral / Perplexity 出网被墙）的用各家官方品牌色值程序生成头像。

产物（每模型 1 张，三套目录）
-----------------------------
    src/assets/avatars/<model>/01.png        主图 512×512 RGBA
    src/assets/avatars-dark/<model>/01.png   深色主题变体（透明底通用）
    src/assets/avatars-thumb/<model>/01.png  128×128 聊天头像位缩略图

不再调用 prepare_avatars.py：那套泛洪抠图逻辑是为「白底同人立绘」设计的，
官方 logo 本就是透明底 PNG，深浅主题通用，无需抠图。
"""

from __future__ import annotations

import pathlib
import shutil
import sys
from PIL import Image, ImageDraw, ImageFont

ROOT = pathlib.Path(__file__).resolve().parent.parent
ASSETS = ROOT / "src" / "assets"
PROBE = ASSETS / "_probe"
SRC = ASSETS / "avatars"
DARK = ASSETS / "avatars-dark"
THUMB = ASSETS / "avatars-thumb"

SIZE = 512          # 主图边长；界面最大显示约 112px，留足 @4x
THUMB_SIZE = 128

# 已有官方位图的模型：_probe 下的源文件名
OFFICIAL = {
    "doubao": "doubao-128.orig",
    "deepseek": "deepseek-fav.orig",
    "glm": "glm-fav.orig",
    "kimi": "kimi-fav.orig",
    "hunyuan": "hunyuan-fav.orig",
    "claude": "anthropic-fav.orig",
    "minimax": "hailuo-fav.orig",
}

# 官网不可达 / 仅有 SVG 的模型：官方品牌色 + 标识。
# 颜色取自各家公开品牌规范；grok 黑底在深色界面会融入背景，故深色变体加白描边。
BRANDED = {
    "qwen":      ("Q",  "#0042FF"),
    "gpt":       ("GPT", "#10A37F"),
    "gemini":    ("Gem", "#4285F4"),
    "grok":      ("Grok", "#1D1D1D"),
    "mistral":   ("M",  "#FF7000"),
    "perplexity": ("P",  "#20808D"),
}

ALL_MODELS = sorted(set(OFFICIAL) | set(BRANDED))


def font_for(text: str, target_h: int) -> ImageFont.FreeTypeFont:
    """按目标文字高度选字号；中文/英文都走系统字体回退链。"""
    candidates = [
        r"C:\Windows\Fonts\arialbd.ttf",
        r"C:\Windows\Fonts\arial.ttf",
        r"C:\Windows\Fonts\segoeui.ttf",
    ]
    for p in candidates:
        if pathlib.Path(p).exists():
            for size in range(target_h, 10, -4):
                try:
                    f = ImageFont.truetype(p, size)
                    if f.getbbox(text)[3] <= target_h:
                        return f
                except Exception:
                    continue
    return ImageFont.load_default()


def make_branded(text: str, color: str, dark: bool) -> Image.Image:
    """品牌色圆角方块 + 白色标识字。"""
    im = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([0, 0, SIZE - 1, SIZE - 1], radius=SIZE // 5, fill=color)

    # 深色主题下黑底（grok）会融入背景，加一圈白描边保证可见
    if dark and color.lower() in ("#1d1d1d", "#000000"):
        d.rounded_rectangle([3, 3, SIZE - 4, SIZE - 4], radius=SIZE // 5 - 3,
                            outline=(255, 255, 255, 235), width=8)

    f = font_for(text, int(SIZE * 0.42))
    bbox = d.textbbox((0, 0), text, font=f)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    d.text(((SIZE - tw) / 2 - bbox[0], (SIZE - th) / 2 - bbox[1]),
           text, font=f, fill=(255, 255, 255, 255))
    return im


def upscale(im: Image.Image) -> Image.Image:
    """统一放大到 512×512，居中留透明边，避免拉伸变形。"""
    im = im.convert("RGBA")
    w, h = im.size
    side = min(w, h)
    im = im.crop(((w - side) // 2, (h - side) // 2, (w - side) // 2 + side, (h - side) // 2 + side))
    return im.resize((SIZE, SIZE), Image.LANCZOS)


def main() -> int:
    if not PROBE.is_dir():
        print(f"[x] 找不到素材目录：{PROBE}")
        return 1

    for d in (SRC, DARK, THUMB):
        if d.exists():
            shutil.rmtree(d)
        for m in ALL_MODELS:
            (d / m).mkdir(parents=True, exist_ok=True)

    ok, fail = 0, []
    for model in ALL_MODELS:
        if model in OFFICIAL:
            src = PROBE / OFFICIAL[model]
            if not src.exists():
                fail.append(f"{model} 缺源文件 {OFFICIAL[model]}")
                continue
            im = upscale(Image.open(src))
        else:
            text, color = BRANDED[model]
            im = make_branded(text, color, dark=False)

        im.save(SRC / model / "01.png", "PNG", optimize=True)
        # 深色变体：官方透明底 logo 深浅通用；仅黑底品牌需要重绘加描边
        if model in BRANDED:
            text, color = BRANDED[model]
            make_branded(text, color, dark=True).save(DARK / model / "01.png", "PNG", optimize=True)
        else:
            im.save(DARK / model / "01.png", "PNG", optimize=True)
        im.resize((THUMB_SIZE, THUMB_SIZE), Image.LANCZOS).save(
            THUMB / model / "01.png", "PNG", optimize=True)
        ok += 1
        print(f"  {model:12s} {im.size[0]}x{im.size[1]}")

    def du(p: pathlib.Path) -> str:
        return f"{sum(f.stat().st_size for f in p.rglob('*') if f.is_file()) / 1024:.0f} KB"

    print(f"\n生成 {ok}/{len(ALL_MODELS)} 家官方形象")
    for f in fail:
        print(f"  [x] {f}")
    print(f"  原图      {du(SRC)}")
    print(f"  深色变体  {du(DARK)}")
    print(f"  缩略图    {du(THUMB)}")
    return 0 if not fail else 1


if __name__ == "__main__":
    sys.exit(main())
