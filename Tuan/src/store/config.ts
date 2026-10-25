import type { Conversation, Provider } from '../types';
import { DEFAULT_MODE, isModeId, type ModeId } from '../platform/modes';

const KEY_PROVIDERS = 'tuan.providers';
const KEY_CONVERSATIONS = 'tuan.conversations';
const KEY_PROJECTS = 'tuan.projects';
const KEY_THEME = 'tuan.theme';
const KEY_AGENT_MODE = 'tuan.agentMode';
const KEY_MODE = 'tuan.mode';
const KEY_PROVIDER_ID = 'tuan.providerId';
const KEY_MODEL = 'tuan.model';
/** 引擎安装向导是否已被用户明确跳过（持久化：跳过就不再每次启动弹） */
const KEY_ENGINE_SETUP_DISMISSED = 'tuan.engineSetupDismissed';
/** 本地 TTS 语音播报开关（MOSS-TTS-Nano，引擎内置 /api/tts） */
const KEY_TTS_ENABLED = 'tuan.tts.enabled';
const KEY_TTS_VOICE = 'tuan.tts.voice';
const KEY_TTS_LANGUAGE = 'tuan.tts.language';
/** 语音协警: 关键事件 (授权/完成/出错) 本地语音提醒 (默认关) */
const KEY_VOICE_COPILOT = 'tuan.voiceCopilot.enabled';
/** 侧栏折叠偏好（桌面人体工学：跨会话保持用户布局选择） */
const KEY_SIDEBAR_COLLAPSED = 'tuan.sidebarCollapsed';

// ===== T-7 主题与外观系统持久化键 =====
/** 明暗三态：dark 暗色（默认）/ light 亮色 / system 跟随系统 */
const KEY_THEME_MODE = 'tuan.themeMode';
/** 强调色四选一：blue 蓝（默认）/ green 绿 / orange 橙 / purple 紫 */
const KEY_ACCENT = 'tuan.accent';
/** 主题色板：default 标准 / green 护眼绿 */
const KEY_PALETTE = 'tuan.palette';
/** 字体三档：sm 小 / md 中（默认）/ lg 大 */
const KEY_FONT_SIZE = 'tuan.fontSize';
/** 代码块是否使用等宽字体（默认开） */
const KEY_CODE_MONO = 'tuan.codeMono';
/** ASCII 吉祥物三款：tuan 青小团 / moon 望月团 / dots 点阵团 */
const KEY_MASCOT = 'tuan.mascot';
// ===== T-2.3 安全组 =====
/** 安全等级：strict 严格 / standard 标准（默认）/ loose 宽松 */
const KEY_SECURITY_LEVEL = 'tuan.securityLevel';
// ===== T-2.4 / T-5.4 通知组 =====
/** 桌面通知总开关（platform/notify.ts 消费） */
const KEY_NOTIFY_ENABLED = 'tuan.notify.enabled';
/** 通知提示音开关（platform/notify.ts 消费） */
const KEY_NOTIFY_SOUND = 'tuan.notify.sound';
/** 免打扰时段是否启用 */
const KEY_DND_ENABLED = 'tuan.notify.dndEnabled';
/** 免打扰开始 / 结束时刻（24h 制 HH:mm，如 22:00 / 08:00） */
const KEY_DND_START = 'tuan.notify.dndStart';
const KEY_DND_END = 'tuan.notify.dndEnd';
/** 上下文预算告警阈值（百分比，默认 80） */
const KEY_BUDGET_THRESHOLD = 'tuan.budgetThreshold';
// ===== T-2.2 模型组 =====
/** 采样温度（0~2，默认 0.7） */
const KEY_TEMPERATURE = 'tuan.temperature';
// ===== T-2.5 实验组（仅预研展示） =====
/** TTS 试听开关 */
const KEY_LAB_TTS_PREVIEW = 'tuan.lab.ttsPreview';
/** 离线模式开关（预研） */
const KEY_OFFLINE_MODE = 'tuan.lab.offline';
// ===== T-1.4 引导完成存储 =====
/** 引导是否完成。沿用 OnboardingWizard 的原始字符串约定 '1'，
 *  与 App.tsx / OnboardingWizard 现有读取逻辑保持二进制兼容。 */
const KEY_ONBOARDING_DONE = 'tuan.onboardingDone';

function read<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : fallback;
  } catch {
    return fallback;
  }
}

function write<T>(key: string, value: T) {
  localStorage.setItem(key, JSON.stringify(value));
}

// ===== 外观相关类型 =====
/** 明暗三态 */
export type ThemeMode = 'dark' | 'light' | 'system';
/** 强调色四选一 */
export type AccentId = 'blue' | 'green' | 'orange' | 'purple';
/** 主题色板 */
export type PaletteId = 'default' | 'green';
/** 字体三档 */
export type FontSizeId = 'sm' | 'md' | 'lg';
/** 吉祥物三款 */
export type MascotId = 'tuan' | 'moon' | 'dots';
/** 安全等级三档 */
export type SecurityLevel = 'strict' | 'standard' | 'loose';

function isThemeMode(v: unknown): v is ThemeMode {
  return v === 'dark' || v === 'light' || v === 'system';
}
function isAccentId(v: unknown): v is AccentId {
  return v === 'blue' || v === 'green' || v === 'orange' || v === 'purple';
}
function isPaletteId(v: unknown): v is PaletteId {
  return v === 'default' || v === 'green';
}
function isFontSizeId(v: unknown): v is FontSizeId {
  return v === 'sm' || v === 'md' || v === 'lg';
}
function isMascotId(v: unknown): v is MascotId {
  return v === 'tuan' || v === 'moon' || v === 'dots';
}
function isSecurityLevel(v: unknown): v is SecurityLevel {
  return v === 'strict' || v === 'standard' || v === 'loose';
}

export const store = {
  providers(): Provider[] {
    return read<Provider[]>(KEY_PROVIDERS, []);
  },
  saveProviders(list: Provider[]) {
    write(KEY_PROVIDERS, list);
  },
  conversations(): Conversation[] {
    return read<Conversation[]>(KEY_CONVERSATIONS, []).sort(
      (a, b) => b.updatedAt - a.updatedAt,
    );
  },
  saveConversations(list: Conversation[]) {
    write(KEY_CONVERSATIONS, list);
  },
  projects<T>() {
    return read<T[]>(KEY_PROJECTS, []);
  },
  saveProjects<T>(list: T[]) {
    write(KEY_PROJECTS, list);
  },
  theme(): 'light' | 'dark' {
    return read<'light' | 'dark'>(KEY_THEME, 'light');
  },
  saveTheme(t: 'light' | 'dark') {
    write(KEY_THEME, t);
  },
  /** 安卓端轻量 Agent：开启后可联网搜索/抓取/算数；关闭则退化为纯对话。 */
  agentMode(): boolean {
    return read<boolean>(KEY_AGENT_MODE, true);
  },
  saveAgentMode(v: boolean) {
    write(KEY_AGENT_MODE, v);
  },
  /** 五模式：闲聊 / 协同 / 灵码 / 感通 / 无界。未知或缺失值一律回落 'chat'。 */
  mode(): ModeId {
    const v = read<string>(KEY_MODE, DEFAULT_MODE);
    return isModeId(v) ? v : DEFAULT_MODE;
  },
  saveMode(m: ModeId) {
    write(KEY_MODE, m);
  },
  providerId(): string {
    return read<string>(KEY_PROVIDER_ID, '');
  },
  saveProviderId(v: string) {
    write(KEY_PROVIDER_ID, v);
  },
  model(): string {
    return read<string>(KEY_MODEL, '');
  },
  saveModel(v: string) {
    write(KEY_MODEL, v);
  },
  /** 引擎安装向导跳过标记：true = 不再自动弹出（仍可从标题栏状态灯手动打开） */
  engineSetupDismissed(): boolean {
    return read<boolean>(KEY_ENGINE_SETUP_DISMISSED, false);
  },
  saveEngineSetupDismissed(v: boolean) {
    write(KEY_ENGINE_SETUP_DISMISSED, v);
  },
  /** 本地语音播报（默认开）：回复完成后自动朗读 */
  ttsEnabled(): boolean {
    return read<boolean>(KEY_TTS_ENABLED, true);
  },
  saveTtsEnabled(v: boolean) {
    write(KEY_TTS_ENABLED, v);
  },
  /** 音色 key（tts_service.VOICES；默认 zh_3 京味活力女声） */
  ttsVoice(): string {
    return read<string>(KEY_TTS_VOICE, 'zh_3');
  },
  saveTtsVoice(v: string) {
    write(KEY_TTS_VOICE, v);
  },
  /** 10 语言之一（默认 zh_CN），决定音色与文本语言 */
  ttsLanguage(): string {
    return read<string>(KEY_TTS_LANGUAGE, 'zh_CN');
  },
  saveTtsLanguage(v: string) {
    write(KEY_TTS_LANGUAGE, v);
  },
  /** 侧栏折叠偏好 */
  sidebarCollapsed(): boolean {
    return read<boolean>(KEY_SIDEBAR_COLLAPSED, false);
  },
  saveSidebarCollapsed(v: boolean) {
    write(KEY_SIDEBAR_COLLAPSED, v);
  },
  /** 语音协警开关 */
  voiceCopilotEnabled(): boolean {
    return read<boolean>(KEY_VOICE_COPILOT, false);
  },
  saveVoiceCopilot(v: boolean) {
    write(KEY_VOICE_COPILOT, v);
  },

  // ===== T-7.5 明暗三态（暗色默认；兼容旧版 tuan.theme 单键） =====
  themeMode(): ThemeMode {
    const v = read<string>(KEY_THEME_MODE, '');
    if (isThemeMode(v)) return v;
    // 旧版用户曾存过 light/dark 单键时沿用之，否则默认暗色
    const legacy = read<string>(KEY_THEME, '');
    return legacy === 'light' ? 'light' : 'dark';
  },
  saveThemeMode(m: ThemeMode) {
    write(KEY_THEME_MODE, m);
  },
  // ===== T-7.2 强调色四选一（蓝默认） =====
  accent(): AccentId {
    const v = read<string>(KEY_ACCENT, 'blue');
    return isAccentId(v) ? v : 'blue';
  },
  saveAccent(a: AccentId) {
    write(KEY_ACCENT, a);
  },
  // ===== T-7.1 主题色板（标准 / 护眼绿） =====
  palette(): PaletteId {
    const v = read<string>(KEY_PALETTE, 'default');
    return isPaletteId(v) ? v : 'default';
  },
  savePalette(p: PaletteId) {
    write(KEY_PALETTE, p);
  },
  // ===== T-7.3 / T-6.5 字体三档 =====
  fontSize(): FontSizeId {
    const v = read<string>(KEY_FONT_SIZE, 'md');
    return isFontSizeId(v) ? v : 'md';
  },
  saveFontSize(f: FontSizeId) {
    write(KEY_FONT_SIZE, f);
  },
  /** 代码块等宽字体开关（默认开） */
  codeMono(): boolean {
    return read<boolean>(KEY_CODE_MONO, true);
  },
  saveCodeMono(v: boolean) {
    write(KEY_CODE_MONO, v);
  },
  // ===== T-7.4 吉祥物三款 =====
  mascot(): MascotId {
    const v = read<string>(KEY_MASCOT, 'tuan');
    return isMascotId(v) ? v : 'tuan';
  },
  saveMascot(m: MascotId) {
    write(KEY_MASCOT, m);
  },
  // ===== T-2.3 安全等级 =====
  securityLevel(): SecurityLevel {
    const v = read<string>(KEY_SECURITY_LEVEL, 'standard');
    return isSecurityLevel(v) ? v : 'standard';
  },
  saveSecurityLevel(l: SecurityLevel) {
    write(KEY_SECURITY_LEVEL, l);
  },
  /** 严格安全模式是否禁用「无界」模式（确认策略） */
  yoloBlockedBySecurity(): boolean {
    return this.securityLevel() === 'strict';
  },
  // ===== T-2.4 / T-5.4 通知组 =====
  notifyEnabled(): boolean {
    return read<boolean>(KEY_NOTIFY_ENABLED, true);
  },
  saveNotifyEnabled(v: boolean) {
    write(KEY_NOTIFY_ENABLED, v);
  },
  notifySound(): boolean {
    return read<boolean>(KEY_NOTIFY_SOUND, true);
  },
  saveNotifySound(v: boolean) {
    write(KEY_NOTIFY_SOUND, v);
  },
  dndEnabled(): boolean {
    return read<boolean>(KEY_DND_ENABLED, false);
  },
  saveDndEnabled(v: boolean) {
    write(KEY_DND_ENABLED, v);
  },
  dndStart(): string {
    return read<string>(KEY_DND_START, '22:00');
  },
  saveDndStart(v: string) {
    write(KEY_DND_START, v);
  },
  dndEnd(): string {
    return read<string>(KEY_DND_END, '08:00');
  },
  saveDndEnd(v: string) {
    write(KEY_DND_END, v);
  },
  /** 上下文预算告警阈值（百分比，默认 80，夹在 50~100） */
  budgetThreshold(): number {
    const v = read<number>(KEY_BUDGET_THRESHOLD, 80);
    return Math.min(100, Math.max(50, Math.round(v)));
  },
  saveBudgetThreshold(n: number) {
    write(KEY_BUDGET_THRESHOLD, Math.min(100, Math.max(50, Math.round(n))));
  },
  // ===== T-2.2 模型组：采样温度 =====
  temperature(): number {
    const v = read<number>(KEY_TEMPERATURE, 0.7);
    return Math.min(2, Math.max(0, v));
  },
  saveTemperature(n: number) {
    write(KEY_TEMPERATURE, Math.min(2, Math.max(0, n)));
  },
  // ===== T-2.5 实验组（仅预研展示） =====
  labTtsPreview(): boolean {
    return read<boolean>(KEY_LAB_TTS_PREVIEW, true);
  },
  saveLabTtsPreview(v: boolean) {
    write(KEY_LAB_TTS_PREVIEW, v);
  },
  offlineMode(): boolean {
    return read<boolean>(KEY_OFFLINE_MODE, false);
  },
  saveOfflineMode(v: boolean) {
    write(KEY_OFFLINE_MODE, v);
  },
  // ===== T-1.4 引导完成存储 =====
  /** 引导是否完成：与 OnboardingWizard 写的原始字符串 '1' 兼容 */
  onboardingDone(): boolean {
    try {
      return localStorage.getItem(KEY_ONBOARDING_DONE) === '1';
    } catch {
      return false;
    }
  },
  /** 标记引导完成 / 未完成。done=true 写 '1'（不再弹）；done=false 清除标记。 */
  completeOnboarding(done = true) {
    try {
      if (done) localStorage.setItem(KEY_ONBOARDING_DONE, '1');
      else localStorage.removeItem(KEY_ONBOARDING_DONE);
    } catch {
      /* 隐私模式下写入失败静默忽略 */
    }
  },
};

export function applyTheme(t: 'light' | 'dark') {
  document.documentElement.classList.toggle('dark', t === 'dark');
}

/** 解析明暗三态为具体的 light/dark（system 走系统偏好） */
export function resolveThemeMode(mode: ThemeMode): 'light' | 'dark' {
  if (mode === 'system') {
    return typeof window !== 'undefined' &&
      window.matchMedia &&
      window.matchMedia('(prefers-color-scheme: dark)').matches
      ? 'dark'
      : 'light';
  }
  return mode;
}

/**
 * 一次性应用全部外观偏好到 <html>：
 *  - .dark 类按解析后的明暗切换
 *  - data-accent / data-palette / data-font / data-code 属性驱动 index.css 变量
 * App.tsx 无需改动即可生效。
 */
export function applyAppearance() {
  const root = document.documentElement;
  applyTheme(resolveThemeMode(store.themeMode()));
  root.dataset.accent = store.accent();
  root.dataset.palette = store.palette();
  root.dataset.font = store.fontSize();
  root.dataset.code = store.codeMono() ? 'mono' : 'ui';
}

// ===== T-1.4 引导「重新打开」订阅 =====
// SettingsPage 的「重新打开引导」按钮调用 requestOnboardingReopen()：
// 先清除完成标记（下次启动也会自动弹），再通知所有监听者立即打开引导向导。
// 消费侧（App.tsx，由启动与命令面板分片接线）通过 onOnboardingReopen 订阅。
const reopenListeners = new Set<() => void>();

/** 订阅「重新打开引导」请求，返回取消订阅函数 */
export function onOnboardingReopen(cb: () => void): () => void {
  reopenListeners.add(cb);
  return () => reopenListeners.delete(cb);
}

/** 请求立即重新打开引导：清除完成标记 + 通知监听者 + 派发 DOM CustomEvent */
export function requestOnboardingReopen(): void {
  store.completeOnboarding(false);
  for (const cb of reopenListeners) {
    try {
      cb();
    } catch {
      /* 单个监听者异常不影响其它 */
    }
  }
  try {
    window.dispatchEvent(new CustomEvent('tuan:open-onboarding'));
  } catch {
    /* 非浏览器环境忽略 */
  }
}

export function uid(): string {
  return Math.random().toString(36).slice(2, 10) + Date.now().toString(36);
}

// ===== 模块加载即应用持久化外观 =====
// config.ts 被 App.tsx 入口 import，此处执行副作用即可在首帧后统一主题，
// 无需改动 App.tsx；同时监听系统明暗偏好变化（themeMode=system 时实时跟随）。
if (typeof document !== 'undefined') {
  applyAppearance();
  if (typeof window !== 'undefined' && window.matchMedia) {
    const mq = window.matchMedia('(prefers-color-scheme: dark)');
    const onChange = () => {
      if (store.themeMode() === 'system') applyAppearance();
    };
    if (mq.addEventListener) mq.addEventListener('change', onChange);
    else if (mq.addListener) mq.addListener(onChange);
  }
}
