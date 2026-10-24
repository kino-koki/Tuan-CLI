#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""为 Tuan-App「社区二创档」批量生成立绘资源。

产出（每模型 5 张 x 3 套目录 = 195 张 + 署名清单）
---------------------------------------------------
  Tuan-App/src/assets/avatars-community/<model>/01..05.png      480x640 浅底
  Tuan-App/src/assets/avatars-community-dark/<model>/01..05.png 480x640 黑底
  Tuan-App/src/assets/avatars-community-thumb/<model>/01..05.png 128x128
  Tuan-App/src/assets/avatar-credits.json                       署名清单

设计原则
--------
1. **一个模型 = 一个形象**：发型 + 配色由模型唯一确定；5 张变体只有
   动作 / 表情 / 视线不同，不能画成五个不同角色。
2. **黑底版只换底色**：同一张主体层分别合成到浅底与黑底上，主体不重画、
   不改色 —— 明暗主题切换时是"同一张画的两种底色"，不留突兀。
3. **署名随包**：生成占位形象时写入 avatar-credits.json；用 --import 导入
   用户自备的已授权二创立绘时保留用户已填的署名，--check 会拦住"已换成
   外部立绘但 artist 为空"的情况，避免无署名外部素材随包分发。

用法
----
  python scripts/build_avatar_variants.py                 # 全量重生成
  python scripts/build_avatar_variants.py --models kimi claude
  python scripts/build_avatar_variants.py --check         # 只校验，不写盘
  python scripts/build_avatar_variants.py --import DIR    # 导入自备授权立绘
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

# ---------------------------------------------------------------- 路径

REPO = Path(__file__).resolve().parent.parent
ASSETS = REPO / "Tuan-App" / "src" / "assets"
CREDITS_MANIFEST = ASSETS / "avatar-credits.json"
DIR_LIGHT = "avatars-community"
DIR_DARK = "avatars-community-dark"
DIR_THUMB = "avatars-community-thumb"

W, H = 480, 640          # 立绘尺寸
THUMB = 128              # 缩略图尺寸
VARIANTS = 5             # 每个模型 5 张
BG_LIGHT = (244, 242, 236)   # 与 index.css 的 --tuan-art-bg 浅色值一致
BG_DARK = (33, 31, 27)       # 与 index.css 的 --tuan-art-bg 深色值一致

# ---------------------------------------------------------- 厂商品牌色
# (primary, secondary) —— primary 用于头发与强调，secondary 用于衣服。
BRAND_COLORS = {
    "deepseek": ("#4D6BFE", "#9FB4FF"),
    "claude": ("#D97757", "#F0A883"),
    "gpt": ("#10A37F", "#5FD3AE"),
    "qwen": ("#615CED", "#B7B3FB"),
    "kimi": ("#00D4FF", "#7BE8FF"),
    "glm": ("#4568DC", "#9AB0F5"),
    "doubao": ("#F07C42", "#FFC199"),
    "gemini": ("#4285F4", "#A8C7FA"),
    "grok": ("#0F0F0F", "#8A8A8A"),
    "mistral": ("#FF7000", "#FFB27A"),
    "minimax": ("#C2185B", "#F06292"),
    "hunyuan": ("#0052D9", "#6FA8FF"),
    "perplexity": ("#20B8CD", "#7DE0E8"),
}

# 每个模型固定一种发型，保证"同一家永远长一个样子"
HAIR_OF = {
    "deepseek": "long",
    "claude": "side",
    "gpt": "bob",
    "qwen": "long",
    "kimi": "twin",
    "glm": "side",
    "doubao": "bob",
    "gemini": "long",
    "grok": "bob",
    "mistral": "twin",
    "minimax": "bun",
    "hunyuan": "twin",
    "perplexity": "side",
}

# 形象名字（与 mascot.ts 的 ROSTER 对齐）
MODEL_NAMES = {
    "deepseek": "DeepSeek",
    "claude": "Claude",
    "gpt": "GPT",
    "qwen": "通义千问",
    "kimi": "Kimi",
    "glm": "GLM",
    "doubao": "豆包",
    "gemini": "Gemini",
    "grok": "Grok",
    "mistral": "Mistral",
    "minimax": "MiniMax",
    "hunyuan": "混元",
    "perplexity": "Perplexity",
}

PLACEHOLDER_NOTE = (
    "本项目原创占位形象（程序化绘制，无第三方美术素材）。"
    "分发含外部二创立绘的版本前，请用 --import 导入已授权图片并补全署名。"
)


# ---------------------------------------------------------------- 颜色工具

def hex2rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[1:4], 16), int(h[4:6], 16)


def rgb2hex(rgb: tuple[int, int, int]) -> str:
    return "#{:02X}{:02X}{:02X}".format(*[max(0, min(255, int(c))) for c in rgb])


def lighten(rgb: tuple[int, int, int], ratio: float) -> tuple[int, int, int]:
    """朝白色插值，ratio=0.3 表示混入 30% 白。"""
    return tuple(int(c + (255 - c) * ratio) for c in rgb)  # type: ignore[return-value]


def darken(rgb: tuple[int, int, int], ratio: float) -> tuple[int, int, int]:
    return tuple(int(c * (1 - ratio)) for c in rgb)  # type: ignore[return-value]


def with_alpha(rgb: tuple[int, int, int], alpha: int) -> tuple[int, int, int, int]:
    return (rgb[0], rgb[1], rgb[2], max(0, min(255, alpha)))


# ---------------------------------------------------------------- 绘制
# chibi 角色立绘：头大身小、大眼睛、有明确的头发 / 衣服 / 四肢与姿态。
#
# 上一版是"圆角矩形小机器人"——没有头发、衣服、手脚，5 张变体只差一点点
# 旋转和视线，观感是图标而不是立绘。这一版按角色立绘重画：
#   后层头发 → 腿 → 脖颈 → 衣服 → 头（脸）→ 五官 → 刘海 → 手臂
# 5 张变体是 5 个完全不同的动作（挥手 / 思考 / 鞠躬 / 欢呼 / 盘腿坐），
# 而不是同一姿势的轻微旋转。

SS = 2                    # 超采样倍数：先 2x 画再缩小，边缘才不锯齿
SKIN = (255, 224, 200)
INK = (58, 50, 66)        # 描边 / 眉眼
CHEEK = (255, 164, 170)
WHITE = (255, 255, 255)

# 缩略图裁切框：覆盖头顶（含丸子头，按最大构图缩放后仍不裁掉刘海）到下颌
THUMB_BOX = (54, 38, 334, 318)


def _s(v: float) -> float:
    """逻辑坐标 → 超采样坐标。"""
    return v * SS


def _lw(v: float) -> int:
    """线宽（已放大）。"""
    return max(1, int(round(v * SS)))


class C:
    """画布包装：调用方写 480x640 逻辑坐标，内部按 SS 倍放大绘制。"""

    def __init__(self, img: Image.Image) -> None:
        self.d = ImageDraw.Draw(img, "RGBA")

    def e(self, box, fill=None, outline=None, w=0):
        self.d.ellipse(
            [_s(v) for v in box], fill=fill, outline=outline,
            width=_lw(w) if w else 0,
        )

    def rr(self, box, r, fill=None, outline=None, w=0):
        self.d.rounded_rectangle(
            [_s(v) for v in box], radius=_s(r),
            fill=fill, outline=outline, width=_lw(w) if w else 0,
        )

    def ln(self, pts, fill, w=3.0):
        self.d.line(
            [(_s(x), _s(y)) for x, y in pts],
            fill=fill, width=_lw(w), joint="curve",
        )

    def poly(self, pts, fill=None, outline=None):
        self.d.polygon([(_s(x), _s(y)) for x, y in pts], fill=fill, outline=outline)


# ---------------------------------------------------------- 五官 / 头发

def _eye(c: C, x: float, y: float, pdx: float, pdy: float, closed: bool) -> None:
    """动漫风眼睛：白底 + 深色虹膜（随视线偏移）+ 高光。closed 画成眯眯眼。"""
    ew, eh = 19, 25
    if closed:
        c.d.arc([_s(x - ew), _s(y - eh + 6), _s(x + ew), _s(y + eh - 6)],
                start=205, end=335, fill=INK, width=_lw(4))
        return
    c.e([x - ew, y - eh, x + ew, y + eh], fill=WHITE, outline=INK, w=3)
    ix, iy = x + pdx, y + pdy
    c.e([ix - 11, iy - 17, ix + 11, iy + 17], fill=(44, 38, 54))
    c.e([ix - 7, iy - 12, ix + 1, iy - 4], fill=WHITE)
    c.e([ix + 2, iy + 6, ix + 7, iy + 11], fill=(255, 255, 255, 190))


def _mouth(c: C, x: float, y: float, kind: str) -> None:
    if kind == "smile":
        c.d.arc([_s(x - 24), _s(y - 14), _s(x + 24), _s(y + 18)],
                start=25, end=155, fill=INK, width=_lw(5))
    elif kind == "open":
        c.e([x - 18, y - 10, x + 18, y + 13], fill=(196, 78, 86), outline=INK, w=3)
        c.e([x - 13, y + 2, x + 13, y + 12], fill=WHITE)
    elif kind == "o":
        c.e([x - 9, y - 9, x + 9, y + 9], outline=INK, w=4)
    elif kind == "closed":
        c.d.arc([_s(x - 16), _s(y - 8), _s(x + 16), _s(y + 10)],
                start=30, end=150, fill=INK, width=_lw(4))
    else:  # flat
        c.ln([(x - 16, y), (x + 16, y)], INK, w=4)


def _face(c: C, hx: float, hy: float, gaze: tuple[float, float], closed: bool, mouth: str) -> None:
    """眉毛 + 眼睛 + 腮红 + 鼻子 + 嘴。"""
    gx, gy = gaze
    for sd in (-1, 1):
        bx = hx + sd * 42 + gx * 0.5
        by = hy - 30 + gy * 0.4
        c.ln([(bx - 17, by + 3), (bx + 17, by - 2)], INK, w=5)
    _eye(c, hx - 42, hy - 2, gx, gy, closed)
    _eye(c, hx + 42, hy - 2, gx, gy, closed)
    for sd in (-1, 1):
        c.e([hx + sd * 58 - 19, hy + 26, hx + sd * 58 + 19, hy + 42],
            fill=with_alpha(CHEEK, 150))
    c.e([hx - 3, hy + 16, hx + 5, hy + 22], fill=(240, 198, 174))
    _mouth(c, hx, hy + 44, mouth)


def _hair_back(c: C, style: str, p, p_dark, hx: float, hy: float) -> None:
    """后层头发：画在脸后面（长发 / 双马尾的垂坠部分）。"""
    if style == "long":
        c.rr([hx - 118, hy - 108, hx + 118, hy + 132], 74, fill=p, outline=p_dark, w=4)
    elif style == "twin":
        c.rr([hx - 118, hy - 108, hx + 118, hy + 26], 70, fill=p, outline=p_dark, w=4)
        c.rr([hx - 156, hy - 34, hx - 94, hy + 150], 28, fill=p, outline=p_dark, w=4)
        c.rr([hx + 94, hy - 34, hx + 156, hy + 150], 28, fill=p, outline=p_dark, w=4)
    else:  # bob / side / bun 的后层较短
        c.rr([hx - 118, hy - 108, hx + 118, hy + 40], 68, fill=p, outline=p_dark, w=4)


_BANGS = (
    (0 - 92, 8), (0 - 52, -58), (0 - 16, 14),
    (0 + 20, -60), (0 + 58, 10), (0 + 92, -30), (0 + 96, 14),
)


def _hair_front(c: C, style: str, p, p_dark, p_light, hx: float, hy: float) -> None:
    """前层头发：头顶 + 锯齿刘海，画在脸前面。"""
    hi = lighten(p, 0.20)
    if style == "bun":
        c.rr([hx - 112, hy - 112, hx + 112, hy + 4], 76, fill=p, outline=p_dark, w=4)
        c.e([hx - 32, hy - 158, hx + 32, hy - 90], fill=p, outline=p_dark, w=4)
        c.rr([hx - 14, hy - 96, hx + 14, hy - 72], 8, fill=p_light, outline=p_dark, w=3)
    elif style == "side":
        c.rr([hx - 112, hy - 114, hx + 112, hy + 6], 76, fill=p, outline=p_dark, w=4)
        c.poly([(hx - 110, hy - 72), (hx + 70, hy - 118), (hx + 116, hy - 28),
                (hx + 94, hy + 14), (hx - 44, hy - 34), (hx - 104, hy + 6)], fill=hi)
        return
    else:
        c.rr([hx - 114, hy - 112, hx + 114, hy + 2], 78, fill=p, outline=p_dark, w=4)
    c.poly([(hx + dx, hy + dy) for dx, dy in _BANGS], fill=hi)
    if style == "twin":
        for sd in (-1, 1):
            c.rr([hx + sd * 150 - 30, hy - 22, hx + sd * 150 + 30, hy + 2],
                 12, fill=p_light, outline=p_dark, w=3)


# ---------------------------------------------------------- 身体 / 四肢

def _body(c: C, p, sec, p_dark, p_light, y: float) -> None:
    """上衣（secondary）+ 领口 + 胸前徽章 + 下摆。"""
    c.rr([170, y, 310, y + 128], 32, fill=sec, outline=INK, w=4)
    for sd in (-1, 1):
        c.rr([240 + sd * 70 - 26, y - 2, 240 + sd * 70 + 26, y + 26],
             14, fill=sec, outline=INK, w=3)
    c.poly([(216, y), (264, y), (240, y + 40)], fill=SKIN, outline=INK)
    c.e([226, y + 56, 254, y + 84], fill=p, outline=INK, w=3)
    c.rr([236, y + 64, 244, y + 76], 3, fill=p_light)
    c.ln([(176, y + 116), (304, y + 116)], p_dark, w=4)


def _legs(c: C, p, apart: bool) -> None:
    """站姿双腿 + 鞋。"""
    dx = 13 if apart else 0
    for sd in (-1, 1):
        cx = 240 + sd * (24 + dx)
        c.rr([cx - 17, 418, cx + 17, 548], 16, fill=SKIN, outline=INK, w=3)
        c.rr([cx - 26, 540, cx + 20, 566], 13, fill=p, outline=INK, w=3)


def _arm(c: C, pts, sec, p_dark) -> None:
    """手臂：袖子两段 + 袖口 + 手。pts = (肩, 肘, 手)。"""
    (sx, sy), (ex, ey), (hx, hy) = pts
    c.ln([(sx, sy), (ex, ey)], sec, w=27)
    c.ln([(ex, ey), (hx, hy)], sec, w=24)
    c.e([sx - 13, sy - 13, sx + 13, sy + 13], fill=sec)
    c.e([ex - 15, ey - 15, ex + 15, ey + 15], fill=sec, outline=p_dark, w=3)
    c.e([hx - 16, hy - 16, hx + 16, hy + 16], fill=SKIN, outline=INK, w=3)


# ---------------------------------------------------------- 姿态表
# 5 张变体 = 5 个不同动作。右臂 / 左臂各自给 (肩, 肘, 手) 三点。
# None 表示走专门的坐姿布局（比例与站姿不同，无法共用坐标）。

POSES = [
    # 01 挥手 —— 右手高举过头挥动，左手自然下垂；标准构图
    dict(arm_r=((302, 318), (346, 254), (368, 190)),
         arm_l=((178, 318), (164, 380), (170, 424)),
         mouth="smile", gaze=(3, 0), closed=False, apart=False,
         scale=1.00, rot=0.0),
    # 02 思考 —— 右手托腮、视线朝左上、"o" 型嘴；大幅拉近成大头特写
    dict(arm_r=((302, 318), (342, 296), (286, 240)),
         arm_l=((178, 318), (166, 382), (174, 426)),
         mouth="o", gaze=(-8, -9), closed=False, apart=False,
         scale=1.24, rot=3.0),
    # 03 鞠躬 —— 双手垂在两侧偏外，闭眼微笑；整体前倾、略微缩小
    dict(arm_r=((302, 318), (330, 392), (336, 448)),
         arm_l=((178, 318), (150, 392), (144, 448)),
         mouth="closed", gaze=(0, 0), closed=True, apart=False,
         scale=0.95, rot=9.0),
    # 04 欢呼 —— 双手高举成 V 字，双脚分开，张嘴；略放大
    dict(arm_r=((302, 318), (338, 250), (358, 188)),
         arm_l=((178, 318), (142, 250), (122, 188)),
         mouth="open", gaze=(0, 0), closed=False, apart=True,
         scale=1.05, rot=0.0),
    # 05 盘腿坐 —— 单独布局
    None,
]


def _apply_tf(img: Image.Image, scale: float = 1.0, rot: float = 0.0) -> Image.Image:
    """按画面中心做缩放 / 旋转（构图变化），主体形状不变。"""
    w, h = img.size
    cx, cy = w // 2, h // 2
    if scale != 1.0:
        s = scale
        img = img.transform(
            (w, h),
            Image.AFFINE,
            (1.0 / s, 0.0, cx * (1 - 1.0 / s), 0.0, 1.0 / s, cy * (1 - 1.0 / s)),
            resample=Image.BICUBIC,
        )
    if rot:
        img = img.rotate(rot, resample=Image.BICUBIC, center=(cx, cy))
    return img


def _pose_standing(c: C, p, sec, p_dark, p_light, hair_style: str, pose: dict) -> None:
    hx, hy = 240.0, 190.0
    _hair_back(c, hair_style, p, p_dark, hx, hy)
    _legs(c, p, apart=pose["apart"])
    c.rr([218, 264, 262, 306], 12, fill=SKIN, outline=INK, w=3)      # 脖颈
    _body(c, p, sec, p_dark, p_light, 300.0)
    c.e([hx - 104, hy - 94, hx + 104, hy + 94], fill=SKIN, outline=INK, w=4)
    for sd in (-1, 1):
        c.e([hx + sd * 104 - 15, hy - 18, hx + sd * 104 + 15, hy + 18],
            fill=SKIN, outline=INK, w=3)
    _face(c, hx, hy, pose["gaze"], pose["closed"], pose["mouth"])
    _hair_front(c, hair_style, p, p_dark, p_light, hx, hy)
    _arm(c, pose["arm_r"], sec, p_dark)
    _arm(c, pose["arm_l"], sec, p_dark)


def _pose_sit(c: C, p, sec, p_dark, p_light, hair_style: str) -> None:
    """盘腿 / 屈膝而坐：躯干下移，膝盖朝前上方，一手搭膝一手撑地。"""
    hx, hy = 240.0, 216.0
    _hair_back(c, hair_style, p, p_dark, hx, hy)
    for sd in (-1, 1):                                             # 屈膝双腿
        hipx = 240 + sd * 30
        kx, ky = 240 + sd * 50, 448
        fx, fy = 240 + sd * 36, 546
        c.ln([(hipx, 428), (kx, ky)], SKIN, w=36)
        c.ln([(kx, ky), (fx, fy)], SKIN, w=34)
        c.e([hipx - 18, 410, hipx + 18, 446], fill=SKIN)
        c.e([kx - 17, ky - 17, kx + 17, ky + 17], fill=SKIN, outline=INK, w=3)
        c.rr([fx - 28, fy - 12, fx + 18, fy + 20], 13, fill=p, outline=INK, w=3)
    c.rr([218, 290, 262, 332], 12, fill=SKIN, outline=INK, w=3)      # 脖颈
    _body(c, p, sec, p_dark, p_light, 326.0)
    c.e([hx - 104, hy - 94, hx + 104, hy + 94], fill=SKIN, outline=INK, w=4)
    for sd in (-1, 1):
        c.e([hx + sd * 104 - 15, hy - 18, hx + sd * 104 + 15, hy + 18],
            fill=SKIN, outline=INK, w=3)
    _face(c, hx, hy, (4, 0), False, "smile")
    _hair_front(c, hair_style, p, p_dark, p_light, hx, hy)
    _arm(c, ((302, 346), (332, 428), (322, 484)), sec, p_dark)      # 右手撑在身后
    _arm(c, ((178, 346), (166, 424), (200, 452)), sec, p_dark)      # 左手搭在膝上


def _draw_subject(model: str, index: int) -> Image.Image:
    """画出主体层（480x640 RGBA，透明底），含脚下阴影。"""
    primary = hex2rgb(BRAND_COLORS[model][0])
    secondary = hex2rgb(BRAND_COLORS[model][1])
    p_dark = darken(primary, 0.26)
    p_light = lighten(primary, 0.24)
    hair_style = HAIR_OF.get(model, "bob")

    big = Image.new("RGBA", (W * SS, H * SS), (0, 0, 0, 0))
    c = C(big)
    pose = POSES[max(0, min(VARIANTS - 1, index))]
    if pose is None:
        _pose_sit(c, primary, secondary, p_dark, p_light, hair_style)
        scale, rot = 1.0, 0.0
    else:
        _pose_standing(c, primary, secondary, p_dark, p_light, hair_style, pose)
        scale, rot = pose.get("scale", 1.0), pose.get("rot", 0.0)

    big = _apply_tf(big, scale=scale, rot=rot)
    layer = big.resize((W, H), Image.LANCZOS)

    # 脚下阴影（画在缩小后的图上，模糊半径才按最终分辨率生效）
    sh = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(sh).ellipse([150, 566, 330, 602], fill=(0, 0, 0, 58))
    layer.alpha_composite(sh.filter(ImageFilter.GaussianBlur(7)))
    return layer


def paint_bg(img: Image.Image, bg: tuple[int, int, int], dark_bg: bool) -> None:
    """铺底色 + 径向提亮 + 地面阴影带（画在主体之前，不会覆盖主体）。

    内部走 RGBA 合成后再转回 RGB，保证原地修改调用方持有的对象。
    """
    rgb = Image.new("RGBA", img.size, (bg[0], bg[1], bg[2], 255))
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay, "RGBA")
    od.ellipse(
        [img.width * 0.12, -img.height * 0.35, img.width * 0.88, img.height * 0.72],
        fill=(255, 255, 255, 14 if dark_bg else 26),
    )
    rgb.alpha_composite(overlay)
    band = Image.new("RGBA", img.size, (0, 0, 0, 0))
    bd = ImageDraw.Draw(band, "RGBA")
    bd.ellipse(
        [img.width * 0.18, img.height * 0.82, img.width * 0.82, img.height * 1.02],
        fill=(0, 0, 0, 34 if dark_bg else 20),
    )
    rgb.alpha_composite(band.filter(ImageFilter.GaussianBlur(14)))
    rgb_rgb = rgb.convert("RGB")
    img.paste(rgb_rgb)


def _compose(layer: Image.Image, dark_bg: bool) -> Image.Image:
    """把主体层合成到指定底色上，返回 RGB 立绘。"""
    bg = BG_DARK if dark_bg else BG_LIGHT
    out = Image.new("RGB", (W, H), bg)
    paint_bg(out, bg, dark_bg=dark_bg)
    out.paste(layer, (0, 0), layer)
    return out


def build_variants(model: str, index: int) -> tuple[Image.Image, Image.Image, Image.Image]:
    """返回 (浅色立绘, 黑底立绘, 缩略图)。"""
    layer = _draw_subject(model, index)
    light = _compose(layer, dark_bg=False)
    dark = _compose(layer, dark_bg=True)
    return light, dark, make_thumb(light)


def build_one(model: str, index: int) -> Image.Image:
    """生成一张 480x640 浅色底立绘（RGB）。"""
    return _compose(_draw_subject(model, index), dark_bg=False)


def derive_dark(light: Image.Image, model: str, index: int, layer: Image.Image | None = None) -> Image.Image:
    """由浅色版派生黑色底版本：只替换画布底色，主体原样保留。

    有生成层（layer）时直接按 alpha 合成 —— 主体内部逐像素与浅色版一致，
    只有半透明边缘随底色略微混合。
    没有生成层（--import 导入的现成图片）时退回颜色蒙版抠图。
    """
    out = Image.new("RGB", light.size, BG_DARK)
    paint_bg(out, BG_DARK, dark_bg=True)
    if layer is not None:
        tmp = Image.new("RGBA", light.size, (BG_DARK[0], BG_DARK[1], BG_DARK[2], 255))
        tmp.alpha_composite(layer)
        out.paste(tmp.convert("RGB"))
    else:
        out.paste(light, (0, 0), _subject_mask(light))
    return out


def _subject_mask(img: Image.Image, tol: int = 26) -> Image.Image:
    """按"与四角背景色相异"生成主体蒙版（仅用于 --import 的现成图片）。

    不依赖具体品牌色：换色后仍可用。抗锯齿边缘用软阈值过渡，
    避免蒙版边界出现硬边白框。
    """
    rgb = img.convert("RGB")
    w, h = rgb.size
    corners = (
        rgb.getpixel((0, 0)), rgb.getpixel((w - 1, 0)),
        rgb.getpixel((0, h - 1)), rgb.getpixel((w - 1, h - 1)),
    )
    bg = tuple(int(round(sum(c[i] for c in corners) / len(corners))) for i in range(3))
    bg_only = Image.new("RGB", rgb.size, bg)
    # 逐通道绝对差再相加，得到 0..765 的总距离
    r = ImageChops.difference(rgb.getchannel(0), bg_only.getchannel(0))
    g = ImageChops.difference(rgb.getchannel(1), bg_only.getchannel(1))
    b = ImageChops.difference(rgb.getchannel(2), bg_only.getchannel(2))
    total = ImageChops.add(ImageChops.add(r, g), b, scale=1)
    # 软阈值：≤ low 透明，≥ high 不透明，中间线性过渡
    low, high = int(tol * 3 * 0.6), int(tol * 3)
    span = max(1, high - low)
    table = bytes(min(255, max(0, int(round((v - low) * 255.0 / span)))) for v in range(256))
    return total.point(table)


def make_thumb(light: Image.Image) -> Image.Image:
    """128x128 缩略图：按头顶为锚点裁正方形，保证小尺寸下脸部仍可见。"""
    crop = light.crop(THUMB_BOX).resize((THUMB, THUMB), Image.LANCZOS)
    return crop


def ensure_dirs() -> None:
    for name in (DIR_LIGHT, DIR_DARK, DIR_THUMB):
        (ASSETS / name).mkdir(parents=True, exist_ok=True)


def write_manifest(models: list[str]) -> None:
    """写署名清单；已存在的条目保留（不覆盖用户已填的署名）。"""
    existing = {}
    if CREDITS_MANIFEST.exists():
        try:
            existing = json.loads(CREDITS_MANIFEST.read_text("utf-8"))
        except Exception:
            existing = {}
    existing.setdefault("meta", {})
    existing["meta"].update(
        {
            "schemaVersion": 1,
            "note": (
                "形象署名清单。key 为模型 key；placeholder=true 表示该模型当前的"
                "立绘由 scripts/build_avatar_variants.py 程序化生成（本项目原创占位形象，"
                "不含第三方美术素材）。导入外部授权二创立绘后请把 placeholder 改为 false，"
                "并补齐 artist / source / license 字段。"
            ),
            "generator": "scripts/build_avatar_variants.py",
        }
    )
    entries = existing.setdefault("models", {})
    for m in models:
        e = entries.setdefault(m, {})
        if "placeholder" not in e:
            e["placeholder"] = True
        e.setdefault("name", MODEL_NAMES.get(m, m))
        e.setdefault("variants", VARIANTS)
        e.setdefault("artist", "Tuan-App 占位形象（原创，未使用第三方美术素材）")
        e.setdefault("source", "")
        e.setdefault("license", "原创，随本仓库 MIT 许可发布")
        e.setdefault("note", PLACEHOLDER_NOTE)
    CREDITS_MANIFEST.write_text(json.dumps(existing, ensure_ascii=False, indent=2) + "\n", "utf-8")


def check_credits(models: list[str]) -> list[str]:
    """返回缺失署名的模型列表（用于 --check）。"""
    problems: list[str] = []
    if not CREDITS_MANIFEST.exists():
        return ["avatar-credits.json 不存在"]
    try:
        data = json.loads(CREDITS_MANIFEST.read_text("utf-8"))
    except Exception as e:
        return [f"avatar-credits.json 解析失败：{e}"]
    entries = data.get("models", {})
    for m in models:
        e = entries.get(m)
        if not e:
            problems.append(f"{m}: 无署名条目")
            continue
        if e.get("placeholder") is False and not (e.get("artist") or "").strip():
            problems.append(f"{m}: 已替换为外部立绘但 artist 为空")
        for variant_i in range(1, VARIANTS + 1):
            for d in (DIR_LIGHT, DIR_DARK, DIR_THUMB):
                p = ASSETS / d / m / f"{variant_i:02d}.png"
                if not p.exists():
                    problems.append(f"缺文件 {d}/{m}/{variant_i:02d}.png")
    return problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="生成 Tuan-App 社区二创档立绘资源")
    ap.add_argument("--models", nargs="*", default=None, help="只处理这些模型 key")
    ap.add_argument("--check", action="store_true", help="只校验资源与署名完整性")
    ap.add_argument("--import", dest="import_dir", default=None,
                    help="从目录导入用户自备的已授权立绘（<model>/01.png..05.png），重建深色版与缩略图")
    ap.add_argument("--jobs", type=int, default=4, help="并行度（仅 --import 时有效）")
    args = ap.parse_args(argv)

    models = args.models or list(BRAND_COLORS.keys())
    unknown = [m for m in models if m not in BRAND_COLORS]
    if unknown:
        print(f"[warn] 未知模型 key（将跳过品牌色定义）: {unknown}", file=sys.stderr)

    if args.check:
        problems = check_credits(models)
        if problems:
            print("署名 / 资源校验失败：")
            for p in problems:
                print(f"  - {p}")
            return 1
        print(f"校验通过：{len(models)} 个模型 x {VARIANTS} 张 x 3 套目录，署名齐全。")
        return 0

    ensure_dirs()
    if args.import_dir:
        src = Path(args.import_dir)
        if not src.is_dir():
            print(f"[error] 导入目录不存在：{src}", file=sys.stderr)
            return 2
        count = 0
        for m in models:
            mdir = src / m
            if not mdir.is_dir():
                print(f"[skip] {m}: 导入目录中无子目录")
                continue
            for i in range(VARIANTS):
                candidates = sorted(mdir.glob(f"{i+1:02d}.*")) or sorted(mdir.glob("*"))
                if i >= len(candidates):
                    print(f"[warn] {m}: 第 {i+1} 张缺失，回退到占位绘制")
                    light, dark, thumb = build_variants(m, i)
                else:
                    src_img = Image.open(candidates[i]).convert("RGB").resize((W, H), Image.LANCZOS)
                    light = _compose_full(src_img, dark_bg=False)
                    dark = derive_dark(light, m, i)   # 走颜色蒙版抠图
                    thumb = make_thumb(light)
                for d, img in ((DIR_LIGHT, light), (DIR_DARK, dark), (DIR_THUMB, thumb)):
                    out_dir = ASSETS / d / m
                    out_dir.mkdir(parents=True, exist_ok=True)
                    img.save(out_dir / f"{i+1:02d}.png", "PNG", optimize=True)
                count += 1
        write_manifest(models)
        print(f"导入完成：写入 {count} 组变体（浅色 / 黑底 / 缩略图）")
        return 0

    total = 0
    for m in models:
        if m not in BRAND_COLORS:
            continue
        for i in range(VARIANTS):
            light, dark, thumb = build_variants(m, i)
            for d, img in ((DIR_LIGHT, light), (DIR_DARK, dark), (DIR_THUMB, thumb)):
                out_dir = ASSETS / d / m
                out_dir.mkdir(parents=True, exist_ok=True)
                img.save(out_dir / f"{i+1:02d}.png", "PNG", optimize=True)
            total += 1
        print(f"[ok] {m}: {VARIANTS} 张 x 3 套目录")
    write_manifest(models)
    print(f"完成：{total} 个模型变体，共 {total * 3} 张图片 -> {ASSETS}")
    problems = check_credits(models)
    if problems:
        print("校验发现以下问题：")
        for p in problems:
            print(f"  - {p}")
    return 0


def _compose_full(rgb_img: Image.Image, dark_bg: bool) -> Image.Image:
    """导入路径：整幅现成图片覆盖到底色上（图片自带背景占满画面）。"""
    bg = BG_DARK if dark_bg else BG_LIGHT
    out = Image.new("RGB", (W, H), bg)
    paint_bg(out, bg, dark_bg=dark_bg)
    out.paste(rgb_img, (0, 0))
    return out


if __name__ == "__main__":
    raise SystemExit(main())
