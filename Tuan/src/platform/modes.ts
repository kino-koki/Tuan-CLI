/**
 * 五模式定义：纯数据 + 类型层，不引 React。
 * 模式 ID 与中文名强制约定，旧版命名已废弃，禁止在任何位置复用。
 */

export type ModeId = 'gantong' | 'lingma' | 'chat' | 'boundless' | 'collaboration';

export interface ModeSpec {
  id: ModeId;
  /** 中文名 */
  name: string;
  /** 一句话定位（≤ 20 字），用于卡片副标题 */
  tagline: string;
  /** 设置页用的详细说明（1-2 句），需明示权限边界 */
  desc: string;
  /** 权限分级：L0 无工具 / L2 文档 / L3 工程 / L4 全能 */
  level: 'L0' | 'L2' | 'L3' | 'L4';
  /** 风险等级 */
  risk: '低' | '中' | '高' | '极高';
  /** UI 短标签，用于 chip */
  badge: string;
}

export const MODES: readonly ModeSpec[] = [
  {
    id: 'chat',
    name: '闲聊',
    tagline: '轻量对话，纯文本',
    desc: '仅走纯对话通道，不执行工具、不访问文件。适合日常问答、头脑风暴与轻松聊天；需要操作请切换到其它模式。',
    level: 'L0',
    risk: '低',
    badge: '对话',
  },
  {
    id: 'collaboration',
    name: '协同',
    tagline: '文档表格，办公协作',
    desc: '面向文档、表格与协作场景，可读写本地 Office 文件并做批注；仅访问用户明确授权的项目目录，不触碰系统路径。',
    level: 'L2',
    risk: '中',
    badge: '协作',
  },
  {
    id: 'lingma',
    name: '灵码',
    tagline: '代码开发，工程操作',
    desc: '以工程操作为主：读写代码、跑测试、执行开发工具。默认工作范围限在当前项目目录内，跨目录改动会先弹确认。',
    level: 'L3',
    risk: '高',
    badge: '开发',
  },
  {
    id: 'gantong',
    name: '感通',
    tagline: '创意工坊，多模态创作',
    desc: '调用多模态与 MCP 工具做图文创作、素材检索与合成；生成类内容需在项目目录内落盘，跨域抓取需用户确认。',
    level: 'L3',
    risk: '高',
    badge: '多模态',
  },
  {
    id: 'boundless',
    name: '无界',
    tagline: '高权限自由，桌面端可用',
    desc: '无界并非没有限制：权限放开但仍需安全闸门，不可逆操作（删除、覆盖、执行脚本）会先弹确认；Android 端不可用。',
    level: 'L4',
    risk: '极高',
    badge: '自由',
  },
];

export const MODE_IDS: readonly ModeId[] = MODES.map((m) => m.id);

export const DEFAULT_MODE: ModeId = 'chat';

/** 类型守卫：判断任意值是否为合法的模式 ID。 */
export function isModeId(v: unknown): v is ModeId {
  return typeof v === 'string' && (MODE_IDS as readonly string[]).includes(v);
}

/** 按 ID 取模式定义；未知值回落 DEFAULT_MODE，不抛异常。 */
export function getMode(id: ModeId): ModeSpec {
  return MODES.find((m) => m.id === id) ?? MODES[0];
}

/** 安全取值：任意输入一律回落到有效模式定义。 */
export function getModeSafe(v: unknown): ModeSpec {
  return isModeId(v) ? getMode(v) : getMode(DEFAULT_MODE);
}

/**
 * 平台切换规则（对应设计规格 §6）：
 *  - `boundless`（无界，L4 高权限）在 Android 端物理禁用，不给确认机会；
 *  - 切换到 `boundless` 需要先做风险披露 + 二次确认；
 *  - `boundless` 降级到任意其它模式随时允许。
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
  if (id === 'boundless' && isAndroid() && BOUNDLESS_BLOCKED_PLATFORMS.has('android')) {
    return '「无界」为桌面端功能，当前安卓端不可用';
  }
  return '';
}

/** 切换到目标模式前是否必须二次确认（无界需风险披露）。 */
export function needsConfirmSwitch(from: ModeId, to: ModeId): boolean {
  return to === 'boundless' && from !== 'boundless';
}
