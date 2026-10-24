#!/usr/bin/env python
"""
make_dark_bg_avatars.py

为 Tuan-App/dist/assets 下的「*-白色背景.jpg」立绘生成对应的「*-黑色背景.jpg」版本。
只替换背景像素；主体颜色/位置/构图/分辨率与原图完全一致。

算法概要：
  1. 从图像四边采样种子点（候选：低局部边缘强度 + 灰度值高于阈值）。
  2. 用 PIL floodfill（带 per-channel 容差）从每个种子点做连通域填充，
     再与"候选掩膜"取交集，得到精确的背景像素掩膜。
  3. 对掩膜做 1-2 px 的高斯模糊以得到柔和过渡带，再做 alpha 混合：
       output = original * (1 - alpha) + black * alpha
  4. 以 JPEG quality=95 / subsampling=0（4:4:4）写出，尺寸与原图一致。

幂等：重复运行时自动跳过已存在的「*-黑色背景.jpg」。

文件边界：只写
  Tuan-App/dist/assets/*.jpg
  _shots/avatar-bg-check.png
不触碰任何 .ts/.tsx/.css / dist/index.html / dist/data / dist/icons / 备份目录。
"""

import os
import sys
import glob
import shutil
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

# ─────────────────────────── 配置 ───────────────────────────
ASSETS_DIR  = r'F:\Tuan-CLI\Tuan-App\dist\assets'
SHOTS_DIR   = r'F:\Tuan-CLI\_shots'
CHECK_IMAGE = os.path.join(SHOTS_DIR, 'avatar-bg-check.png')

BG_TOLERANCE       = 20    # floodfill per-channel RGB 容差
FLAT_THRESH        = 15    # 局部边缘强度 < 此值视为"平坦"
MIN_BG_BRIGHTNESS  = 100   # 灰度 > 此值才认为是背景（排除深色主体）
BLACK_RGB          = (0, 0, 0)
SOFTEN_RADIUS      = 1.0   # 掩膜高斯模糊半径（≈ 1-2 px 过渡带）
JPEG_QUALITY       = 95
JPEG_SUBSAMPLING   = 0     # 4:4:4
MIN_REGION_PIXELS  = 50    # floodfill 区域最小像素数，过滤噪点
SEED_STEP          = 8     # 边缘种子采样步长（像素）

RENAME_MAP = {
    'GPT-白色背景_1792584425908edit.jpg': 'GPT-白色背景.jpg',
}

# ─────────────────────────── 核心算法 ───────────────────────────

def local_edge_strength(gray, radius=2):
    """用 |pixel - box_blur(pixel)| 近似局部边缘强度。"""
    img = Image.fromarray(gray.astype(np.uint8))
    blurred = np.asarray(img.filter(ImageFilter.BoxBlur(radius))).astype(np.float32)
    return np.abs(gray.astype(np.float32) - blurred)


def find_bg_mask(arr):
    """
    通过"边缘种子 + floodfill + 平坦/亮度过滤"找出背景像素掩膜。
    arr: uint8 RGB numpy 数组 (H, W, 3)
    返回: bool 掩膜 (H, W)
    """
    h, w = arr.shape[:2]
    gray = (0.299 * arr[:, :, 0].astype(np.float32)
            + 0.587 * arr[:, :, 1].astype(np.float32)
            + 0.114 * arr[:, :, 2].astype(np.float32))
    edge = local_edge_strength(gray, radius=2)

    # 候选背景：平坦且明亮
    candidate = (edge < FLAT_THRESH) & (gray > MIN_BG_BRIGHTNESS)

    bg_mask = np.zeros((h, w), dtype=bool)

    # 从四条边采样种子
    seeds = []
    for x in range(0, w, SEED_STEP):
        if candidate[0, x]:    seeds.append((x, 0))
        if candidate[h - 1, x]: seeds.append((x, h - 1))
    for y in range(0, h, SEED_STEP):
        if candidate[y, 0]:     seeds.append((0, y))
        if candidate[y, w - 1]: seeds.append((w - 1, y))

    MARKER = (255, 0, 255)  # 洋红，与源图像素冲突概率极低
    for (x, y) in seeds:
        if bg_mask[y, x]:
            continue
        work_img = Image.fromarray(arr)
        ImageDraw.floodfill(work_img, (x, y), MARKER, thresh=BG_TOLERANCE)
        work_arr = np.asarray(work_img)
        marker_mask = (work_arr[:, :, 0] == 255) & \
                      (work_arr[:, :, 1] == 0) & \
                      (work_arr[:, :, 2] == 255)
        region = marker_mask & candidate
        if region.sum() >= MIN_REGION_PIXELS:
            bg_mask |= region
        del work_img, work_arr, marker_mask, region

    return bg_mask


def make_dark_bg(src_path, dst_path):
    """
    读取 src_path，生成深色背景版本保存到 dst_path。
    返回 report dict。
    """
    img = Image.open(src_path)
    arr = np.asarray(img)  # uint8
    h, w = arr.shape[:2]

    # 1. 找背景掩膜
    bg_mask = find_bg_mask(arr)
    bg_pixels = int(bg_mask.sum())
    if bg_pixels == 0:
        raise RuntimeError(f'{os.path.basename(src_path)}: 未找到背景像素')

    # 2. 掩膜柔化 → alpha
    mask_img = Image.fromarray((bg_mask * 255).astype(np.uint8))
    soft_mask = np.asarray(
        mask_img.filter(ImageFilter.GaussianBlur(SOFTEN_RADIUS))
    ).astype(np.float32) / 255.0
    soft_mask = np.clip(soft_mask, 0.0, 1.0)

    # 3. 混合
    black = np.array(BLACK_RGB, dtype=np.float32)
    out = arr.astype(np.float32) * (1.0 - soft_mask[:, :, None]) \
          + black * soft_mask[:, :, None]
    out = out.clip(0, 255).astype(np.uint8)

    # 4. 写出 JPEG
    Image.fromarray(out).save(
        dst_path,
        quality=JPEG_QUALITY,
        subsampling=JPEG_SUBSAMPLING,
        optimize=True,
    )

    # 5. 量化指标
    diff = np.abs(out.astype(np.int16) - arr.astype(np.int16))
    max_diff_per_px = diff.max(axis=2)
    subject_mask = ~bg_mask
    subject_modified = int(((subject_mask) & (max_diff_per_px > 2)).sum())
    if subject_mask.sum() > 0:
        subject_diff_mean = float(diff[subject_mask].mean())
    else:
        subject_diff_mean = 0.0
    bg_diff_mean = float(diff[bg_mask].mean()) if bg_pixels > 0 else 0.0

    return {
        'size':           f'{w}x{h}',
        'bg_pixels':      bg_pixels,
        'bg_frac':        bg_pixels / (h * w),
        'subject_modified': subject_modified,
        'subject_diff_mean': subject_diff_mean,
        'bg_diff_mean':   bg_diff_mean,
        'soften_radius':  SOFTEN_RADIUS,
        'out_size_kb':    os.path.getsize(dst_path) // 1024,
    }


# ─────────────────────────── 校验拼图 ───────────────────────────

def make_check_image(pairs, check_path):
    """
    每行一个模型：左侧白底、右侧黑底，宽度 160 px，带模型名标签。
    pairs: [(name, white_path, dark_path), ...]
    """
    tiles = []
    for name, white_path, dark_path in pairs:
        w_img = Image.open(white_path)
        d_img = Image.open(dark_path)
        target_w = 160
        scale = target_w / w_img.width
        new_h = int(round(w_img.height * scale))
        w_img = w_img.resize((target_w, new_h), Image.LANCZOS)
        d_img = d_img.resize((target_w, new_h), Image.LANCZOS)
        combined = Image.new('RGB', (target_w * 2 + 10, new_h), (55, 55, 55))
        combined.paste(w_img, (0, 0))
        combined.paste(d_img, (target_w + 10, 0))
        tiles.append((name, combined))

    label_w = 140
    row_gap = 10
    top_pad = 24
    tile_w = max(t[1].width for t in tiles)
    total_w = label_w + tile_w + 20
    total_h = top_pad + sum(t[1].height + row_gap for t in tiles)

    canvas = Image.new('RGB', (total_w, total_h), (28, 28, 28))
    draw = ImageDraw.Draw(canvas)

    try:
        font_name = ImageFont.truetype(r'C:\Windows\Fonts\arial.ttf', 16)
        font_tag  = ImageFont.truetype(r'C:\Windows\Fonts\arial.ttf', 11)
    except Exception:
        font_name = ImageFont.load_default()
        font_tag  = ImageFont.load_default()

    # 表头
    draw.text((label_w + 5, 5), 'WHITE BG', fill=(220, 220, 220), font=font_tag)
    draw.text((label_w + 160 + 5, 5), 'DARK BG', fill=(220, 220, 220), font=font_tag)
    draw.text((5, 5), 'MODEL', fill=(220, 220, 220), font=font_tag)

    y = top_pad
    for name, tile in tiles:
        draw.text((5, y + tile.height // 2 - 8), name,
                  fill=(255, 255, 255), font=font_name)
        canvas.paste(tile, (label_w + 5, y))
        y += tile.height + row_gap

    canvas.save(check_path)
    return check_path


# ─────────────────────────── 主流程 ───────────────────────────

def main():
    os.makedirs(SHOTS_DIR, exist_ok=True)

    print('=' * 72)
    print('make_dark_bg_avatars.py  —  为 awa 形象生成黑色背景版本')
    print('=' * 72)

    # ── Step 1: 规范化文件名 ──
    print('\n[Step 1] 规范化文件名 …')
    for old_name, new_name in RENAME_MAP.items():
        old_path = os.path.join(ASSETS_DIR, old_name)
        new_path = os.path.join(ASSETS_DIR, new_name)
        if os.path.exists(old_path) and not os.path.exists(new_path):
            shutil.move(old_path, new_path)
            print(f'  [rename] {old_name}  →  {new_name}')
        elif os.path.exists(old_path) and os.path.exists(new_path):
            print(f'  [skip] {new_name} 已存在，不覆盖；{old_name} 保留')
        elif not os.path.exists(old_path) and os.path.exists(new_path):
            print(f'  [ok] {new_name} 已就位（无需重命名）')
        else:
            print(f'  [warn] {old_name} 和 {new_name} 均不存在')

    # ── Step 2: 逐张生成深色背景 ──
    print('\n[Step 2] 生成黑色背景版本 …')
    pairs   = []
    reports = []

    white_files = sorted(glob.glob(os.path.join(ASSETS_DIR, '*-白色背景.jpg')))
    if not white_files:
        print('  [error] 未找到任何 *-白色背景.jpg')
        sys.exit(1)

    for src_path in white_files:
        base = os.path.basename(src_path)
        name = base.replace('白色背景', '').replace('.jpg', '')
        dst_name = base.replace('白色背景', '黑色背景')
        dst_path = os.path.join(ASSETS_DIR, dst_name)

        if os.path.exists(dst_path):
            print(f'  [skip] {dst_name} 已存在')
            pairs.append((name, src_path, dst_path))
            continue

        print(f'  [process] {name} …', end=' ', flush=True)
        try:
            report = make_dark_bg(src_path, dst_path)
        except Exception as e:
            print(f'FAILED: {e}')
            continue

        report['name'] = name
        reports.append(report)
        pairs.append((name, src_path, dst_path))
        print(f"bg={report['bg_frac'] * 100:5.1f}%  "
              f"mod_subj={report['subject_modified']:>5}  "
              f"subjΔ={report['subject_diff_mean']:.2f}  "
              f"bgΔ={report['bg_diff_mean']:.1f}  "
              f"→ {report['out_size_kb']} KB")

    # ── Step 3: 校验拼图 ──
    print('\n[Step 3] 生成校验拼图 …')
    if pairs:
        check_path = make_check_image(pairs, CHECK_IMAGE)
        print(f'  [ok] {check_path}  ({os.path.getsize(check_path) // 1024} KB)')

    # ── Step 4: 汇总表 ──
    print('\n[Step 4] 汇总报告')
    print('-' * 96)
    hdr = f'{"Model":<12} {"Size":<13} {"Bg Pixels":>10} {"Bg %":>7}  \
{"ModSubj":>8} {"SubjΔ":>8} {"BgΔ":>7} {"OutKB":>7}'
    print(hdr)
    print('-' * 96)
    for r in reports:
        print(f"{r['name']:<12} {r['size']:<13} {r['bg_pixels']:>10} "
              f"{r['bg_frac'] * 100:>6.1f}%  "
              f"{r['subject_modified']:>8} {r['subject_diff_mean']:>8.2f} "
              f"{r['bg_diff_mean']:>7.1f} {r['out_size_kb']:>7}")
    print('-' * 96)

    # ── 最终统计 ──
    all_jpg = glob.glob(os.path.join(ASSETS_DIR, '*.jpg'))
    white_cnt = len(glob.glob(os.path.join(ASSETS_DIR, '*-白色背景.jpg')))
    dark_cnt  = len(glob.glob(os.path.join(ASSETS_DIR, '*-黑色背景.jpg')))
    print(f'\n[统计] assets/*.jpg 共 {len(all_jpg)} 张  '
          f'(白底 {white_cnt}  +  黑底 {dark_cnt})')

    if reports:
        total_subj_mod = sum(r['subject_modified'] for r in reports)
        total_px = sum(int(r['size'].split('x')[1]) * int(r['size'].split('x')[0]) for r in reports)
        print(f'[量化] 全部 {len(reports)} 张：主体被误改像素 {total_subj_mod} / {total_px}'
              f' = {total_subj_mod / total_px * 100:.4f}%')
    print('\n[完成]')


if __name__ == '__main__':
    main()
