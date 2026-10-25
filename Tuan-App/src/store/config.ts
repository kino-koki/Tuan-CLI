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
};

export function applyTheme(t: 'light' | 'dark') {
  document.documentElement.classList.toggle('dark', t === 'dark');
}

export function uid(): string {
  return Math.random().toString(36).slice(2, 10) + Date.now().toString(36);
}
