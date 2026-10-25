/**
 * 三档权限模式定义：纯数据 + 类型层，不引 React。
 * 模式 ID 与中文名强制约定，旧版五模式命名已废弃，禁止在任何位置复用。
 *
 * 设计对齐 Claude Code / Cursor 的权限档位：
 *  - auto 标准（默认）：自动判断，常规操作直接执行，危险操作先确认；
 *  - plan 只读：只读与分析，不修改任何文件、不执行有副作用的命令；
 *  - yolo 无界：放开确认，自动化执行；仍需安全闸门兜底（不可逆操作弹确认）。
 */

export type ModeId = 'auto' | 'plan' | 'yolo';

export interface ModeSpec {
  id: ModeId;
  /** 中文名 */
  name: string;
  /** 一句话定位（≤ 20 字），用于卡片副标题 */
  tagline: string;
  /** 设置页用的详细说明（1-2 句），需明示权限边界 */
  desc: string;
  /** 权限分级：L0 无工具 / L1 只读 / L2 标准 / L4 全能 */
  level: 'L0' | 'L1' | 'L2' | 'L4';
  /** 风险等级 */
  risk: '低' | '中' | '高' | '极高';
  /** UI 短标签，用于 chip */
  badge: string;
}

export const MODES: readonly ModeSpec[] = [
  {
    id: 'auto',
    name: '标准',
    tagline: '自动判断，常规即执行',
    desc: '标准权限：常规操作（对话、读写项目文件、跑测试）直接执行，删除、覆盖、执行脚本等危险操作先弹确认。适合日常开发与办公。',
    level: 'L2',
    risk: '中',
    badge: '标准',
  },
  {
    id: 'plan',
    name: '只读',
    tagline: '只看不改，安全分析',
    desc: '只读权限：只做阅读、搜索、分析与方案规划，不修改任何文件、不执行有副作用的命令。适合评审、排查与需求梳理。',
    level: 'L1',
    risk: '低',
    badge: '只读',
  },
  {
    id: 'yolo',
    name: '无界',
    tagline: '放开确认，自动化执行',
    desc: '无界权限：放开大部分确认，任务自动化执行；不可逆操作（删除、覆盖、执行脚本）仍有安全闸门兜底。Android 端不可用。',
    level: 'L4',
    risk: '极高',
    badge: '无界',
  },
];

export const MODE_IDS: readonly ModeId[] = MODES.map((m) => m.id);

export const DEFAULT_MODE: ModeId = 'auto';

/** 类型守卫：判断任意值是否为合法的模式 ID。 */
export function isModeId(v: unknown): v is ModeId {
  return typeof v === 'string' && (MODE_IDS as readonly string[]).includes(v);
}

/** 按 ID 取模式定义；未知值回落 DEFAULT_MODE，不抛异常。 */
export function getMode(id: ModeId): ModeSpec {
  return MODES.find((m) => m.id === id) ?? MODES[0];
}

/** 安全取值：任意输入一律回落到有效模式定义（旧版五模式 ID 也回落 auto）。 */
export function getModeSafe(v: unknown): ModeSpec {
  return isModeId(v) ? getMode(v) : getMode(DEFAULT_MODE);
}

/**
 * 平台切换规则（对应设计规格 §6）：
 *  - `yolo`（无界，L4 高权限）在 Android 端物理禁用，不给确认机会；
 *  - 切换到 `yolo` 需要先做风险披露 + 二次确认；
 *  - `yolo` 降级到任意其它模式随时允许。
 */

/** 无界模式禁用的平台。 */
const BOUNDLESS_BLOCKED_PLATFORMS = new Set(['android']);

/** 是否安卓端（Webview / Tauri Android 通用启发式判定）。 */
export function isAndroid(): boolean {
  if (typeof navigator === 'undefined') return false;
  return /android/i.test(navigator.userAgent) || /android/i.test(navigator.platform ?? '');
}

/** 目标模式是否被当前平台禁用；返回禁用原因（空串表示可用）。 */
export function platformBlockReason(id: ModeId): string {
  if (id === 'yolo' && isAndroid() && BOUNDLESS_BLOCKED_PLATFORMS.has('android')) {
    return '「无界」为桌面端功能，当前安卓端不可用';
  }
  return '';
}

/** 切换到目标模式前是否必须二次确认（无界需风险披露）。 */
export function needsConfirmSwitch(from: ModeId, to: ModeId): boolean {
  return to === 'yolo' && from !== 'yolo';
}
