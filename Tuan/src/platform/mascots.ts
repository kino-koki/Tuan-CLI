/**
 * 青小团吉祥物 — 前端 ASCII 三款（只读参考 tuan_cli/ui/mascot.py）。
 *
 * 设计对齐 TUI：终端吉祥物采用 block art logo + 月相 spinner，
 * 不使用 ASCII 脸。这里提供三款可在设置面板预览与切换的静态变体：
 *  - tuan 青小团：原版 block art logo
 *  - moon 望月团：月相 spinner 取景
 *  - dots 点阵团：Braille 点阵 spinner 取景
 *
 * 仅负责展示与持久化（store.mascot），渲染方为设置面板的预览卡片。
 */

import type { MascotId } from '../store/config';

export interface MascotSpec {
  id: MascotId;
  /** 中文名 */
  name: string;
  /** 两行 ASCII / 字符画，设置面板 <pre> 内等宽渲染 */
  lines: [string, string];
  /** 一句话说明 */
  desc: string;
}

/** 三款吉祥物清单；顺序即设置面板卡片顺序 */
export const MASCOTS: readonly MascotSpec[] = [
  {
    id: 'tuan',
    name: '青小团',
    // 与 tuan_cli/ui/mascot.py 的 block art logo 一致：
    // ▐█▛█▛█▌ / ▐█████▌，配月相状态图标
    lines: ['▐█▛█▛█▌  🌑', '▐█████▌  ●'],
    desc: '原版 block art logo，终端 TUI 同款',
  },
  {
    id: 'moon',
    name: '望月团',
    // 取月相 spinner（🌑🌒🌓🌔🌕…）前三帧组成一行
    lines: ['🌑 🌒 🌓', '🌔 🌕 🌖'],
    desc: '月相渐盈，安静跟随任务状态',
  },
  {
    id: 'dots',
    name: '点阵团',
    // 取 Braille spinner（⠋⠙⠹⠸⠼⠴）前两帧
    lines: ['⠋ ⠙ ⠹', '⠸ ⠼ ⠴'],
    desc: 'Braille 点阵，极客备用风',
  },
];

/** 按 ID 取吉祥物定义；未知值回落青小团，不抛异常 */
export function getMascot(id: string): MascotSpec {
  return MASCOTS.find((m) => m.id === id) ?? MASCOTS[0];
}
