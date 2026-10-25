/**
 * 会话管理支撑层（T-3 会话管理 / T-6 离线体验分片）。
 *
 * 设计要点：
 *  - 与引擎侧 Web 服务的 /api/sessions 系列路由对接（见 tuan_cli/web/server.py）：
 *    列表 GET /api/sessions、历史 GET /api/history、删除 DELETE /api/sessions?session=
 *    清空单会话消息 POST /api/sessions/clear。
 *  - 引擎未启动时（桌面引擎缺失、Android 无 Python 引擎、纯网页预览）一切降级为
 *    「静默失败 + 本地 localStorage 数据」，绝不向上抛错——会话界面在任何环境都可用。
 *  - 离线缓存：每次成功拉取引擎会话列表后写 localStorage，断网时界面仍可展示最近列表。
 *  - selectSession(id)：供「启动与命令面板」分片的桌面通知点击回调跳转会话——
 *    这里只做防御性导出（window 事件 + localStorage 记录），通知侧自行监听或调用。
 *  - 导出：Conversation → Markdown / JSON 纯文本，浏览器 Blob 下载，不依赖任何后端。
 */
import type { Conversation, ChatMessage } from '../types';
import { TTS_ENGINE_URL } from './tts';

/** localStorage 键：引擎会话列表的离线缓存 */
const KEY_CACHE = 'tuan.sessions.cache';
/** localStorage 键：最近被选中（点击/通知跳转）的会话 id */
const KEY_LAST_SELECTED = 'tuan.sessions.lastSelected';
/** localStorage 键：每条会话的模式标签侧映射（由后续分片在发送落盘时写入；本层只读） */
const KEY_MODE_MAP = 'tuan.convModeMap';

/** window 事件名：请求跳转到指定会话（通知点击等外部入口用） */
export const EVENT_SELECT_SESSION = 'tuan:select-session';

/** window 事件名：会话列表已被外部（下拉刷新）拉取过，组件可重读本地缓存 */
export const EVENT_SESSIONS_REFRESHED = 'tuan:sessions-refreshed';

/** 引擎侧会话列表项的最小形态（与 server.py GET /api/sessions 的返回对齐，字段做防御取值） */
export interface EngineSessionMeta {
  id: string;
  title: string;
  /** 创建时间（秒级时间戳，server.py 只回 created） */
  created?: number;
  /** 消息条数 */
  messageCount?: number;
  /** 由哪条会话 fork 而来 */
  forkedFrom?: string;
}

/** 安全读取 localStorage 中的 JSON */
function readJson<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : fallback;
  } catch {
    return fallback;
  }
}

function writeJson(key: string, value: unknown): void {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    /* 存储满/隐私模式下静默失败 */
  }
}

/** 当前是否有网络（navigator.onLine 不可用时一律按在线处理，避免误判） */
export function isAppOnline(): boolean {
  return typeof navigator === 'undefined' ? true : !!navigator.onLine;
}

/** 订阅在线状态变化；返回取消订阅函数。SSR/非浏览器环境静默跳过。 */
export function onOnlineStatusChange(cb: (online: boolean) => void): () => void {
  if (typeof window === 'undefined') return () => {};
  const on = () => cb(true);
  const off = () => cb(false);
  window.addEventListener('online', on);
  window.addEventListener('offline', off);
  return () => {
    window.removeEventListener('online', on);
    window.removeEventListener('offline', off);
  };
}

/** 读取离线缓存的引擎会话列表（断网时界面展示用） */
export function getCachedEngineSessions(): EngineSessionMeta[] {
  return readJson<EngineSessionMeta[]>(KEY_CACHE, []);
}

/** 写入离线缓存 */
function saveCachedEngineSessions(list: EngineSessionMeta[]): void {
  writeJson(KEY_CACHE, list);
}

/**
 * 拉取引擎侧会话列表。
 * 失败/离线时返回空数组（调用方应回落到本地 localStorage 会话数据），不抛异常。
 */
export async function fetchEngineSessions(): Promise<EngineSessionMeta[]> {
  if (!isAppOnline()) return [];
  try {
    const resp = await fetch(`${TTS_ENGINE_URL}/api/sessions`, {
      method: 'GET',
      headers: { Accept: 'application/json' },
    });
    if (!resp.ok) return [];
    const data = (await resp.json()) as {
      ok?: boolean;
      sessions?: Array<Record<string, unknown>>;
    };
    if (!data || data.ok === false || !Array.isArray(data.sessions)) return [];
    const metas: EngineSessionMeta[] = data.sessions.map((s) => ({
      id: String(s.id ?? ''),
      title: String(s.title ?? '未命名会话'),
      created: typeof s.created === 'number' ? s.created : undefined,
      messageCount: typeof s.messages === 'number' ? s.messages : undefined,
      forkedFrom: s.forked_from ? String(s.forked_from) : undefined,
    })).filter((m) => !!m.id);
    saveCachedEngineSessions(metas);
    return metas;
  } catch {
    return [];
  }
}

/** 下拉刷新入口：拉取引擎列表并广播事件；返回本次拉到的会话元信息 */
export async function refreshSessionsFromEngine(): Promise<EngineSessionMeta[]> {
  const metas = await fetchEngineSessions();
  try {
    window.dispatchEvent(new CustomEvent(EVENT_SESSIONS_REFRESHED, { detail: { metas } }));
  } catch {
    /* 老内核无 CustomEvent.detail 也无所谓 */
  }
  return metas;
}

/** 删除引擎侧单条会话（DELETE /api/sessions?session=）；失败静默返回 false */
export async function deleteEngineSession(id: string): Promise<boolean> {
  if (!id || !isAppOnline()) return false;
  try {
    const resp = await fetch(`${TTS_ENGINE_URL}/api/sessions?session=${encodeURIComponent(id)}`, {
      method: 'DELETE',
    });
    return resp.ok;
  } catch {
    return false;
  }
}

/** 清空引擎侧单条会话的消息（POST /api/sessions/clear）；失败静默返回 false */
export async function clearEngineSessionMessages(id: string): Promise<boolean> {
  if (!id || !isAppOnline()) return false;
  try {
    const resp = await fetch(`${TTS_ENGINE_URL}/api/sessions/clear`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session: id }),
    });
    return resp.ok;
  } catch {
    return false;
  }
}

/**
 * 跳转到指定会话（防御性导出，供通知点击等外部入口调用）。
 * 实现：记录最近选中 id + 广播 window 事件；App 侧若已监听该事件即可完成切换，
 * 未监听时也不报错——选中记录可在下次启动时被读取。
 */
export function selectSession(id: string): void {
  if (!id) return;
  writeJson(KEY_LAST_SELECTED, id);
  try {
    window.dispatchEvent(new CustomEvent(EVENT_SELECT_SESSION, { detail: { id } }));
  } catch {
    /* 老内核降级 */
  }
}

/** 读取最近被选中的会话 id（无则空串） */
export function getLastSelectedSessionId(): string {
  return readJson<string>(KEY_LAST_SELECTED, '');
}

/** 订阅「请求跳转会话」事件；返回取消订阅函数 */
export function onSessionSelected(cb: (id: string) => void): () => void {
  if (typeof window === 'undefined') return () => {};
  const handler = (e: Event) => {
    const id = (e as CustomEvent<{ id?: string }>).detail?.id;
    if (id) cb(id);
  };
  window.addEventListener(EVENT_SELECT_SESSION, handler);
  return () => window.removeEventListener(EVENT_SELECT_SESSION, handler);
}

/**
 * 读取某条会话的模式标签（侧映射表，可能为空）。
 * 只读取：发送时落盘模式的动作由其它分片负责；这里有就显示，没有就不显示。
 */
export function getConvModeLabel(id: string): string | undefined {
  const map = readJson<Record<string, string>>(KEY_MODE_MAP, {});
  const v = map[id];
  return typeof v === 'string' && v ? v : undefined;
}

/* ================= 导出工具 ================= */

/** 文件名清洗：去掉 Windows/macOS 不允许的字符 */
function safeFileName(name: string): string {
  return name.replace(/[\\/:*?"<>|]/g, '_').slice(0, 80) || '会话';
}

/** 浏览器触发文件下载 */
export function downloadText(filename: string, text: string, mime: string): void {
  try {
    const blob = new Blob([text], { type: `${mime};charset=utf-8` });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  } catch {
    /* 下载被浏览器拦截时静默失败 */
  }
}

function fmtTime(ts: number): string {
  try {
    return new Date(ts).toLocaleString('zh-CN');
  } catch {
    return String(ts);
  }
}

/** 单条会话 → Markdown 文本 */
export function conversationToMarkdown(conv: Conversation): string {
  const lines: string[] = [
    `# ${conv.title}`,
    '',
    `导出时间：${new Date().toLocaleString('zh-CN')}`,
    `消息数：${conv.messages.length}`,
    '',
    '---',
    '',
  ];
  for (const m of conv.messages) {
    const role = m.role === 'user' ? '我' : m.role === 'assistant' ? '助手' : '系统';
    lines.push(`**${role}**（${fmtTime(m.ts)}）`);
    lines.push('');
    lines.push(m.content || '');
    lines.push('');
    lines.push('---');
    lines.push('');
  }
  return lines.join('\n');
}

/** 单条会话 → JSON 文本（保留完整字段，便于日后导回） */
export function conversationToJson(conv: Conversation): string {
  const payload = {
    title: conv.title,
    exportedAt: new Date().toISOString(),
    messages: conv.messages.map((m: ChatMessage) => ({
      role: m.role,
      content: m.content,
      ts: m.ts,
      ...(m.model ? { model: m.model } : {}),
      ...(m.reasoning ? { reasoning: m.reasoning } : {}),
    })),
  };
  return JSON.stringify(payload, null, 2);
}

/** 导出单条会话为 Markdown 文件 */
export function exportConversationMarkdown(conv: Conversation): void {
  downloadText(`${safeFileName(conv.title)}.md`, conversationToMarkdown(conv), 'text/markdown');
}

/** 导出单条会话为 JSON 文件 */
export function exportConversationJson(conv: Conversation): void {
  downloadText(`${safeFileName(conv.title)}.json`, conversationToJson(conv), 'application/json');
}

/** 全部会话 → 合并 Markdown（按更新时间倒序，一条文件含全部） */
export function exportAllConversationsMarkdown(convs: Conversation[]): void {
  const sorted = [...convs].sort((a, b) => b.updatedAt - a.updatedAt);
  const parts: string[] = [
    `# Tuan 全部会话导出`,
    '',
    `导出时间：${new Date().toLocaleString('zh-CN')}`,
    `会话数：${sorted.length}`,
    '',
  ];
  for (const conv of sorted) {
    parts.push('');
    parts.push(conversationToMarkdown(conv));
    parts.push('');
    parts.push('# '.padEnd(40, '#'));
  }
  const stamp = new Date().toISOString().slice(0, 10);
  downloadText(`tuan-会话导出-${stamp}.md`, parts.join('\n'), 'text/markdown');
}

/** 全部会话 → JSON 数组文件 */
export function exportAllConversationsJson(convs: Conversation[]): void {
  const sorted = [...convs].sort((a, b) => b.updatedAt - a.updatedAt);
  const payload = {
    exportedAt: new Date().toISOString(),
    sessions: sorted.map((conv) => ({
      id: conv.id,
      title: conv.title,
      createdAt: conv.createdAt,
      updatedAt: conv.updatedAt,
      messages: conv.messages.map((m: ChatMessage) => ({
        role: m.role,
        content: m.content,
        ts: m.ts,
      })),
    })),
  };
  const stamp = new Date().toISOString().slice(0, 10);
  downloadText(`tuan-会话导出-${stamp}.json`, JSON.stringify(payload, null, 2), 'application/json');
}
