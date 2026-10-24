#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 Android APK 图标与桌面 exe 图标统一。

用法
----
    python scripts/sync_android_icons.py                 # 用 icons/icon.png 重建全部 mipmap
    python scripts/sync_android_icons.py --source PATH   # 指定其它源图
    python scripts/sync_android_icons.py --check         # 只校验，不写文件
    python scripts/sync_android_icons.py --gen-dir DIR   # 额外同步到打包产物目录

问题背景
--------
桌面 exe 用的是 ``src-tauri/icons/icon.png``（单一 512×512 主视觉），而 Android 侧
历史上是两套：各密度一张完整图标 ``ic_launcher.png``（48/72/96/144/192），外加一套
``ic_launcher_foreground.png`` 供 Android 8+ 自适应图标使用。这两套是分别生成的，
内容不一致，导致手机上看到的图标和桌面版不是一个。

做法：以桌面 ``icon.png`` 为唯一来源，按 Android 官方密度规格重新产出，并统一
自适应图标的背景色：

  mdpi      48   48  / 前景 108
  hdpi      72   72  / 前景 162
  xhdpi     96   96  / 前景 216
  xxhdpi   144  144  / 前景 324
  xxxhdpi  192  192  / 前景 432

  ic_launcher.png          完整图标，用于 Android 7 及以下与通知 / 分享图标
  ic_launcher_round.png    圆形蒙版版，用于支持 roundIcon 的启动器
  ic_launcher_foreground.png  自适应图标前景（1.5x 画布，主体缩到 66% 安全区）

自适应图标的画布是标准图标的 1.5 倍，主体必须落在中心 66% 安全区内，否则会被
圆形 / 水滴形蒙版裁掉。这里先把桌面图标缩放到 66% 再居中放大，主体形状完全不变，
因此手机上和桌面上看到的还是同一个标志。

依赖：Pillow。
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from PIL import Image, ImageDraw

REPO = Path(__file__).resolve().parent.parent
ICONS = REPO / "Tuan-App" / "src-tauri" / "icons"
ANDROID = ICONS / "android"
DEFAULT_SOURCE = ICONS / "icon.png"
ADAPTIVE_XML = ANDROID / "mipmap-anydpi-v26" / "ic_launcher.xml"

# 密度 -> (完整图标边长, 自适应前景画布边长)
DENSITIES = [
    ("mdpi", 48, 108),
    ("hdpi", 72, 162),
    ("xhdpi", 96, 216),
    ("xxhdpi", 144, 324),
    ("xxxhdpi", 192, 432),
]

# 自适应图标安全区占比：主体只占画布 66%，保证任何蒙版（圆/水滴/方块）都不裁边
SAFE_RATIO = 0.66

ADAPTIVE_XML_TEXT = """<?xml version="1.0" encoding="utf-8"?>
<adaptive-icon xmlns:android="http://schemas.android.com/apk/res/android">
  <background android:drawable="@color/ic_launcher_background"/>
  <foreground android:drawable="@mipmap/ic_launcher_foreground"/>
</adaptive-icon>
"""


def adaptive_background_color(src: Image.Image) -> str:
    """从源图四角采样一个不透明的平均色，作为自适应图标的背景。

    桌面图标多为浅色 / 品牌色底；若直接沿用旧的 #FFFFFF，深色标志在手机桌面
    上会出现一圈白边。这里取四角像素的中位数，跳过透明像素。
    """
    rgb = src.convert("RGBA")
    w, h = rgb.size
    corners = [
        rgb.getpixel((0, 0)),
        rgb.getpixel((w - 1, 0)),
        rgb.getpixel((0, h - 1)),
        rgb.getpixel((w - 1, h - 1)),
    ]
    opaque = [tuple(c[:3]) for c in corners if len(c) > 3 and c[3] > 16]
    if not opaque:
        return "#FFFFFF"
    vals = [c for px in opaque for c in px]
    n = len(vals) // 3
    return "#{:02X}{:02X}{:02X}".format(
        int(sum(vals[0::3]) / n), int(sum(vals[1::3]) / n), int(sum(vals[2::3]) / n)
    )


def fit_into(size: int, bg: tuple[int, ...] = (255, 255, 255, 255)) -> Image.Image:
    return Image.new("RGBA", (size, size), bg)


def make_full(src: Image.Image, size: int) -> Image.Image:
    """完整图标：等比缩放 + 透明底居中（不填色，避免和桌面图标底色不一致）。"""
    im = src.convert("RGBA").resize((size, size), Image.LANCZOS)
    return im


def make_round(src: Image.Image, size: int) -> Image.Image:
    """圆形蒙版版：先按完整图标缩放，再套圆形遮罩。"""
    im = src.convert("RGBA").resize((size, size), Image.LANCZOS)
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse([0, 0, size - 1, size - 1], fill=255)
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(im, (0, 0), mask)
    return out


def make_foreground(src: Image.Image, canvas: int, bg: tuple[int, ...] = (255, 255, 255, 255)) -> Image.Image:
    """自适应图标前景：主体缩到 66% 安全区并居中。"""
    out = fit_into(canvas, bg)
    subject = int(round(canvas * SAFE_RATIO))
    inner = src.convert("RGBA").resize((subject, subject), Image.LANCZOS)
    off = (canvas - subject) // 2
    out.paste(inner, (off, off), inner)
    return out


def build_all(source: Path) -> tuple[list[Path], str]:
    src = Image.open(source)
    src.load()
    written: list[Path] = []
    bg_hex = adaptive_background_color(src)
    bg_rgb = tuple(int(bg_hex[i:i + 2], 16) for i in (1, 3, 5))

    for density, full_size, fg_size in DENSITIES:
        d = ANDROID / f"mipmap-{density}"
        d.mkdir(parents=True, exist_ok=True)
        for name, img in (
            ("ic_launcher.png", make_full(src, full_size)),
            ("ic_launcher_round.png", make_round(src, full_size)),
            ("ic_launcher_foreground.png", make_foreground(src, fg_size, bg_rgb + (255,))),
        ):
            p = d / name
            img.save(p, "PNG", optimize=True)
            written.append(p)

    (ANDROID / "mipmap-anydpi-v26").mkdir(parents=True, exist_ok=True)
    ADAPTIVE_XML.write_text(ADAPTIVE_XML_TEXT, "utf-8")
    written.append(ADAPTIVE_XML)

    values = ANDROID / "values"
    values.mkdir(parents=True, exist_ok=True)
    (values / "ic_launcher_background.xml").write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n<resources>\n'
        f'  <color name="ic_launcher_background">{bg_hex}</color>\n</resources>\n',
        "utf-8",
    )
    written.append(values / "ic_launcher_background.xml")
    return written, bg_hex


def mirror_to(gen_dir: Path) -> list[Path]:
    """把图标同步到打包产物目录，保证已生成的 Android 工程也是最新图标。"""
    target = gen_dir / "app" / "src" / "main" / "res"
    if not target.is_dir():
        return []
    written: list[Path] = []
    for density, _full, _fg in DENSITIES:
        dst = target / f"mipmap-{density}"
        dst.mkdir(parents=True, exist_ok=True)
        for name in ("ic_launcher.png", "ic_launcher_round.png", "ic_launcher_foreground.png"):
            shutil.copy2(ANDROID / f"mipmap-{density}" / name, dst / name)
            written.append(dst / name)
    dst = target / "mipmap-anydpi-v26"
    dst.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ADAPTIVE_XML, dst / "ic_launcher.xml")
    written.append(dst / "ic_launcher.xml")
    return written


def check(source: Path) -> list[str]:
    """校验源图与各密度产物的边长是否一致。"""
    problems: list[str] = []
    src = Image.open(source)
    src.load()
    for density, full_size, fg_size in DENSITIES:
        d = ANDROID / f"mipmap-{density}"
        for name, expect in (
            ("ic_launcher.png", full_size),
            ("ic_launcher_round.png", full_size),
            ("ic_launcher_foreground.png", fg_size),
        ):
            p = d / name
            if not p.exists():
                problems.append(f"缺失 {p.relative_to(ICONS)}")
                continue
            im = Image.open(p)
            if im.size != (expect, expect):
                problems.append(f"{p.relative_to(ICONS)} 边长 {im.size[0]} != 期望 {expect}")
    if not ADAPTIVE_XML.exists():
        problems.append(f"缺失 {ADAPTIVE_XML.relative_to(ICONS)}")
    return problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="统一 Android APK 图标与桌面 exe 图标")
    ap.add_argument("--source", type=Path, default=DEFAULT_SOURCE, help="源图标（默认 icons/icon.png）")
    ap.add_argument("--check", action="store_true", help="只校验不写文件")
    ap.add_argument("--gen-dir", type=Path, default=None,
                    help="额外同步到打包产物目录（默认探测 src-tauri/gen/android）")
    args = ap.parse_args(argv)

    src = args.source if args.source.is_absolute() else REPO / args.source
    if not src.is_file():
        print(f"[error] 源图标不存在：{src}", file=sys.stderr)
        return 2

    if args.check:
        problems = check(src)
        if problems:
            print("图标校验失败：")
            for p in problems:
                print(f"  - {p}")
            return 1
        print(f"校验通过：{len(DENSITIES)} 个密度 x 3 种图标，与 {src.name} 一致。")
        return 0

    written, bg_hex = build_all(src)
    print(f"已重建 {len(written)} 个文件，自适应背景色 {bg_hex}（取自 {src.name} 四角）")
    for p in written:
        print(f"  - {p.relative_to(REPO)}")

    gen = args.gen_dir or (REPO / "Tuan-App" / "src-tauri" / "gen" / "android")
    mirrored = mirror_to(gen)
    if mirrored:
        print(f"已同步 {len(mirrored)} 个文件到 {gen.relative_to(REPO)}")
    else:
        print(f"[skip] 未找到打包产物目录 {gen}，跳过同步")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
