import type { Conversation, Provider } from '../types';
import { DEFAULT_MODE, isModeId, type ModeId } from '../platform/modes';

const KEY_PROVIDERS = 'tuan.providers';
const KEY_CONVERSATIONS = 'tuan.conversations';
const KEY_PROJECTS = 'tuan.projects';
const KEY_THEME = 'tuan.theme';
const KEY_AVATAR_MODE = 'tuan.avatarMode';
const KEY_AGENT_MODE = 'tuan.agentMode';
const KEY_MODE = 'tuan.mode';
const KEY_PROVIDER_ID = 'tuan.providerId';
const KEY_MODEL = 'tuan.model';

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
  /**
   * 助手形象档（历史兼容字段，已无 UI 入口）。
   *
   * 二次元立绘已成为唯一助手形象，不再有"官方星芒 vs 模型形象"的选择。
   * 返回类型收敛为 'anime' | 'default'：
   *  - 读取 localStorage 中的任何历史值（'default' / 'awa' / 'community'）
   *    一律归一为 'anime'。
   *  - 'default' 仅保留在类型联合中以便外部代码不报错，实际上函数永远返回 'anime'。
   *
   * 字段保留是为了兼容旧 localStorage 数据，避免升级时报错或丢数据。
   */
  avatarMode(): 'anime' | 'default' {
    // 读一次以确保 localStorage 被消费（历史值不再影响行为）
    read<string>(KEY_AVATAR_MODE, 'anime');
    return 'anime';
  },
  saveAvatarMode(m: 'anime' | 'default') {
    write(KEY_AVATAR_MODE, m);
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
};

export function applyTheme(t: 'light' | 'dark') {
  document.documentElement.classList.toggle('dark', t === 'dark');
}

export function uid(): string {
  return Math.random().toString(36).slice(2, 10) + Date.now().toString(36);
}
