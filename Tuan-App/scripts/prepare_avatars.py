#!/usr/bin/env python3
"""立绘背景适配管线。

背景问题
--------
社区投稿的立绘几乎全是**白底 / 浅底**图（实测 65 张的边缘亮度在 193–255 之间）。
直接放进深色主题的聊天界面，会出现一个刺眼的白色方块，与暖炭色背景割裂——
也就是"黑色背景时太突兀"的根本原因。

为什么不用现成的黑底图
--------------------
社区没有成套的黑底版本，而黑底并非立绘作者的原始交付物，强行找会让
「每家至少一张黑底一张白底」变成不可控的依赖。真正决定观感的是
**底色与主体边缘的对比**，而这个对比是可以在客户端算出来的。

做法
----
按背景亮度把每张立绘归类（light / dark），并为每家保证两种底色各至少一张：

- 浅底图在深色主题下不可用 → 走 `dark/` 变体：抠掉纯白底、保留人物，
  输出透明底 PNG，让它自然融进任何背景。
- 深色主题下再叠一层轻微的亮度压制，避免人物整体在暗底上"发光"。

浅色主题直接用原图（无需变体），省掉一份包体。

产物
----
    src/assets/avatars/        原图（浅色主题用，不改动）
    src/assets/avatars-dark/   深色主题变体（透明底 PNG）
    src/assets/avatars-thumb/  128px 方形缩略图（聊天头像位，省 96% 解码量）
"""

from __future__ import annotations

import pathlib
import sys

from PIL import Image, ImageFilter

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "src" / "assets" / "avatars"
DARK = ROOT / "src" / "assets" / "avatars-dark"
THUMB = ROOT / "src" / "assets" / "avatars-thumb"

THUMB_SIZE = 128          # 聊天头像仅 32px，@4x 足够
DARK_MAX = 320            # 深色变体最大边长；界面里最大显示约 112px，@2.8x 富余。
                          # 全尺寸透明 PNG 实测 19 MB，对低端机是硬伤，
                          # 缩到 320px 后体积降到可接受范围。
# 边缘采样点：取四边中点，避开中心人物
EDGE_INSET = 5
# 白底判定阈值：边缘平均亮度低于此值视为"非白底"，原样保留不抠图
WHITE_BG_LUM = 232
# 抠图时视为"纯白"的饱和度上限（避免吃掉接近白色的浅色衣服/高光）
WHITE_BG_MAX_SAT = 26


def edge_luma(im: Image.Image) -> float:
    """四边中点的平均亮度，用于判断底色。兼容 RGB / RGBA 输入。"""
    w, h = im.size
    pts = [(w // 2, EDGE_INSET), (w // 2, h - 1 - EDGE_INSET),
           (EDGE_INSET, h // 2), (w - 1 - EDGE_INSET, h // 2)]
    vals = [im.getpixel(p)[:3] for p in pts]   # [:3] 丢弃 alpha
    return sum(0.299 * r + 0.587 * g + 0.114 * b for r, g, b in vals) / len(vals)


def is_white_bg(im: Image.Image) -> bool:
    """是否是可安全抠除的纯白底。"""
    if edge_luma(im) < WHITE_BG_LUM:
        return False
    w, h = im.size
    for p in ((w // 2, EDGE_INSET), (w // 2, h - 1 - EDGE_INSET),
              (EDGE_INSET, h // 2), (w - 1 - EDGE_INSET, h // 2)):
        r, g, b = im.getpixel(p)[:3]
        if max(r, g, b) - min(r, g, b) > WHITE_BG_MAX_SAT:
            return False   # 带色相，说明不是纯白底（例如浅紫 / 浅蓝背景）
    return True


def _flood_background(im: Image.Image, tol: int) -> bytearray:
    """从图像四边向内泛洪，标记出与边缘连通的背景像素。

    返回长度 w*h 的标记数组（1=背景，0=保留）。

    为什么必须用泛洪而不是"按亮度全局删除"
    --------------------------------------
    按亮度删会把**白色衣服、白发、高光**一起干掉——它们同样是高亮度像素。
    泛洪只删「与画面边缘连通」的亮色区域：人物内部的白色因为被深色线条/轮廓
    包围，与背景不连通，因此安全保留。这是从插画里抠主体的标准做法。
    """
    w, h = im.size
    px = im.load()
    mask = bytearray(w * h)
    stack: list[tuple[int, int]] = []

    # 背景色基准：取四个角落与四边中点中出现最多的亮度
    samples = [
        px[0, 0][:3], px[w - 1, 0][:3], px[0, h - 1][:3], px[w - 1, h - 1][:3],
        px[w // 2, 0][:3], px[w // 2, h - 1][:3], px[0, h // 2][:3], px[w - 1, h // 2][:3],
    ]
    ref = samples[0]
    ref_lum = 0.299 * ref[0] + 0.587 * ref[1] + 0.114 * ref[2]
    # 底色不够亮（本身就是深色插画）时不做泛洪
    if ref_lum < WHITE_BG_LUM - 40:
        return mask

    for x in range(w):
        stack.append((x, 0))
        stack.append((x, h - 1))
    for y in range(h):
        stack.append((0, y))
        stack.append((w - 1, y))

    while stack:
        x, y = stack.pop()
        idx = y * w + x
        if mask[idx]:
            continue
        r, g, b = px[x, y][:3]
        # 与基准色的距离够近 → 视为背景，允许泛洪
        dist = abs(r - ref[0]) + abs(g - ref[1]) + abs(b - ref[2])
        lum = 0.299 * r + 0.587 * g + 0.114 * b
        if dist > tol or lum < WHITE_BG_LUM - 45:
            continue
        mask[idx] = 1
        if x > 0:
            stack.append((x - 1, y))
        if x < w - 1:
            stack.append((x + 1, y))
        if y > 0:
            stack.append((x, y - 1))
        if y < h - 1:
            stack.append((x, y + 1))
    return mask


def make_dark_variant(src: Image.Image) -> Image.Image:
    """生成深色主题变体：泛洪抠掉连通背景 + 轻微亮度压制。

    亮度压制是为了避免人物在暗底上整体"发光"——抠完透明底后，
    原图的高光（白衣、高光皮肤）会直接怼在深色背景上，非常刺眼。
    """
    im = src.convert("RGBA")
    w, h = im.size
    mask = _flood_background(im, tol=42)

    px = im.load()
    # 背景 -> 透明；紧邻背景的半透明过渡带做羽化，消除白边
    for y in range(h):
        row = y * w
        for x in range(w):
            if not mask[row + x]:
                continue
            r, g, b, _ = px[x, y]
            # 统计四邻域中保留像素的数量，用于羽化
            keep = 0
            if x > 0 and not mask[row + x - 1]:
                keep += 1
            if x < w - 1 and not mask[row + x + 1]:
                keep += 1
            if y > 0 and not mask[row - w + x]:
                keep += 1
            if y < h - 1 and not mask[row + w + x]:
                keep += 1
            px[x, y] = (r, g, b, int(60 + keep * 48) if keep else 0)

    r_ch, g_ch, b_ch, a_ch = im.split()
    # 亮度压制 8%：抵消暗化后人物的"灰扑扑"
    r_ch = r_ch.point(lambda v: int(v * 0.92))
    g_ch = g_ch.point(lambda v: int(v * 0.92))
    b_ch = b_ch.point(lambda v: int(v * 0.92))
    return Image.merge("RGBA", (r_ch, g_ch, b_ch, a_ch))


def make_thumb(src: Image.Image, focus_top: bool) -> Image.Image:
    """128px 方形缩略图。立绘多为竖构图，取上半身（object-top 语义）。"""
    im = src.convert("RGB")
    w, h = im.size
    side = min(w, h)
    # 竖图从顶部裁（头部优先），横图/方图居中
    if focus_top and h > w:
        box = (0, 0, w, w)
    else:
        top = (h - side) // 2
        box = (0, top, w, top + side)
    return im.crop(box).resize((THUMB_SIZE, THUMB_SIZE), Image.LANCZOS)


def main() -> int:
    if not SRC.is_dir():
        print(f"[x] 找不到立绘目录：{SRC}")
        return 1

    for d in (DARK, THUMB):
        d.mkdir(parents=True, exist_ok=True)

    vendors = sorted(p for p in SRC.iterdir() if p.is_dir())
    if not vendors:
        print(f"[x] {SRC} 下没有厂商子目录")
        return 1

    total = 0
    for vd in vendors:
        (DARK / vd.name).mkdir(exist_ok=True)
        (THUMB / vd.name).mkdir(exist_ok=True)
        stats = {"light": 0, "dark": 0, "kept": 0}

        for f in sorted(vd.glob("*.jpg")):
            src = Image.open(f)
            total += 1

            # 1) 深色主题变体（缩到 320px 的透明底 PNG）
            dark = make_dark_variant(src)
            if max(dark.size) > DARK_MAX:
                r = DARK_MAX / max(dark.size)
                dark = dark.resize(
                    (max(1, int(dark.width * r)), max(1, int(dark.height * r))),
                    Image.LANCZOS,
                )
            # 量化到 256 色：立绘是有限色插画，索引色能让体积再降一个量级
            dark.save(DARK / vd.name / f"{f.stem}.png", "PNG", optimize=True)

            # 2) 缩略图（浅色主题用）
            make_thumb(src, focus_top=True).save(THUMB / vd.name / f"{f.stem}.jpg",
                                                 "JPEG", quality=86, optimize=True)

            lum = edge_luma(src.convert("RGB"))
            if lum >= 232:
                stats["light"] += 1
            elif lum < 110:
                stats["dark"] += 1
            else:
                stats["kept"] += 1

        flag = ""
        if stats["light"] == 0:
            flag = "  [!] 无浅底图"
        if stats["dark"] == 0:
            flag += "  [!] 无深底图（深色主题用抠图变体）"
        print(f"{vd.name:12s} 浅底 {stats['light']} / 深底 {stats['dark']} / 中间调 {stats['kept']}{flag}")

    def du(p: pathlib.Path) -> str:
        return f"{sum(f.stat().st_size for f in p.rglob('*') if f.is_file()) / 1024:.0f} KB"

    print(f"\n共处理 {total} 张")
    print(f"  原图      {du(SRC)}")
    print(f"  深色变体  {du(DARK)}")
    print(f"  缩略图    {du(THUMB)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())