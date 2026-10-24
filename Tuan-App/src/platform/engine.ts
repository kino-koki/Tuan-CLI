import { invoke, Channel, isTauri } from '@tauri-apps/api/core';
import type { ChatChunk, ChatMessage, Provider } from '../types';

/**
 * 通信层：
 * - Tauri 桌面端（Windows / macOS）：请求在 Rust 侧用 reqwest 发出，绕开 WebView 的
 *   CORS 限制，SSE 分片经 Channel 回传，这是能真正调出模型的主路径。
 * - Android：不内置本地 Python 引擎，engine_chat_stream 不可用；
 *   改走 chat_stream（纯协议直连），同样经 Rust 发出以绕开 WebView CORS 限制。
 * - 纯网页预览：无 Tauri 时回退到浏览器 fetch（仅用于本地开发预览）。
 * 支持 OpenAI 兼容（/chat/completions）与 Anthropic（/v1/messages）两种协议。
 */

/**
 * 是否运行在 Android。
 *
 * Tauri 的 isTauri() 在安卓同样返回 true，无法区分平台；而安卓端没有本地
 * Python 引擎，若误走引擎桥会导致聊天必然失败，故需按 UA 判定。
 */
export function isAndroid(): boolean {
  if (typeof navigator === 'undefined') return false;
  return /android/i.test(navigator.userAgent);
}

/** 安卓端没有本地引擎，聊天与探测都走 Rust 直连协议而非引擎桥。 */
function needsDirectProtocol(): boolean {
  return isAndroid();
}

/**
 * 引擎可用性状态缓存。
 *
 * 应用启动时由 App.tsx 调用 check_engine 命令初始化；
 * 引擎不可用时 engineChat 自动降级到 tauriStream（直连协议），
 * 保证用户至少能用纯对话模式，而不是看到"需要引擎"的报错。
 */
let engineAvailable: boolean | null = null; // null = 未检查

export function setEngineAvailable(v: boolean): void {
  engineAvailable = v;
}

export function getEngineAvailable(): boolean | null {
  return engineAvailable;
}

/** 引擎不可用时是否应该降级到直连协议。 */
function shouldFallback(): boolean {
  return engineAvailable === false;
}

/** Tauri 主路径：调用 Rust chat_stream，按 Channel 消息异步产出分片。 */
async function* tauriStream(
  provider: Provider,
  model: string,
  history: ChatMessage[],
  signal?: AbortSignal,
): AsyncGenerator<ChatChunk> {
  const chan = new Channel<ChatChunk>();
  const queue: ChatChunk[] = [];
  let wake: (() => void) | null = null;
  let finished = false;
  chan.onmessage = (msg: ChatChunk) => {
    queue.push(msg);
    wake?.();
  };

  invoke<void>('chat_stream', {
    provider,
    model,
    history: history.map((m) => ({ role: m.role, content: m.content })),
    channel: chan,
  })
    .then(() => {
      finished = true;
      wake?.();
    })
    .catch((e) => {
      queue.push({ type: 'error', error: String(e?.message ?? e ?? '调用失败') });
      finished = true;
      wake?.();
    });

  signal?.addEventListener('abort', () => {
    finished = true;
    wake?.();
  });

  for (;;) {
    while (queue.length) {
      const item = queue.shift()!;
      yield item;
      if (item.type === 'done' || item.type === 'error') return;
    }
    if (finished) return;
    await new Promise<'wait'>((r) => {
      wake = () => r('wait');
      setTimeout(() => r('wait'), 500);
    });
    wake = null;
  }
}

/* ---------- 网页预览兜底（直连，受 CORS 限制，仅开发用） ---------- */

const HEADER_TIMEOUT_MS = 20_000;

function friendly(e: unknown): string {
  if (e instanceof DOMException && e.name === 'AbortError') return '已停止生成或响应超时，请检查网络与接口地址';
  if (e instanceof TypeError) return '连接被拦截或失败（CORS/网络），请在应用内使用原生通道';
  if (e instanceof Error) return `连接失败：${e.message}`;
  return '请求失败，请稍后重试';
}

function openaiStream(
  provider: Provider,
  model: string,
  history: ChatMessage[],
  signal?: AbortSignal,
): AsyncGenerator<ChatChunk> {
  return (async function* () {
    const base = provider.baseUrl.replace(/\/+$/, '');
    const ctrl = new AbortController();
    const onAbort = () => ctrl.abort();
    signal?.addEventListener('abort', onAbort);
    const timer = setTimeout(() => ctrl.abort(), HEADER_TIMEOUT_MS);
    try {
      const resp = await fetch(`${base}/chat/completions`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${provider.apiKey}` },
        signal: ctrl.signal,
        body: JSON.stringify({ model, messages: history.map((m) => ({ role: m.role, content: m.content })), stream: true }),
      });
      clearTimeout(timer);
      if (!resp.ok || !resp.body) {
        yield { type: 'error', error: `接口返回 ${resp.status}，请检查地址、密钥与模型` };
        return;
      }
      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buf = '';
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        const lines = buf.split('\n');
        buf = lines.pop() ?? '';
        for (const line of lines) {
          const s = line.trim();
          if (!s.startsWith('data:')) continue;
          const payload = s.slice(5).trim();
          if (payload === '[DONE]') { yield { type: 'done' }; return; }
          try {
            const json = JSON.parse(payload);
            const delta = json?.choices?.[0]?.delta?.content;
            if (delta) yield { type: 'text', text: delta };
          } catch { /* 分片不完整 */ }
        }
      }
      yield { type: 'done' };
    } catch (e) {
      yield { type: 'error', error: friendly(e) };
    } finally {
      clearTimeout(timer);
      signal?.removeEventListener('abort', onAbort);
    }
  })();
}

function anthropicStream(
  provider: Provider,
  model: string,
  history: ChatMessage[],
  signal?: AbortSignal,
): AsyncGenerator<ChatChunk> {
  return (async function* () {
    const base = provider.baseUrl.replace(/\/+$/, '');
    const system = history.filter((m) => m.role === 'system').map((m) => m.content).join('\n');
    const messages = history.filter((m) => m.role !== 'system')
      .map((m) => ({ role: m.role === 'assistant' ? 'assistant' : 'user', content: m.content }));
    const ctrl = new AbortController();
    const onAbort = () => ctrl.abort();
    signal?.addEventListener('abort', onAbort);
    const timer = setTimeout(() => ctrl.abort(), HEADER_TIMEOUT_MS);
    try {
      const resp = await fetch(`${base}/v1/messages`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'x-api-key': provider.apiKey, 'anthropic-version': '2023-06-01' },
        signal: ctrl.signal,
        body: JSON.stringify({ model, max_tokens: 4096, system: system || undefined, messages, stream: true }),
      });
      clearTimeout(timer);
      if (!resp.ok || !resp.body) {
        yield { type: 'error', error: `接口返回 ${resp.status}，请检查地址、密钥与模型` };
        return;
      }
      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buf = '';
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        const lines = buf.split('\n');
        buf = lines.pop() ?? '';
        for (const line of lines) {
          const s = line.trim();
          if (!s.startsWith('data:')) continue;
          try {
            const json = JSON.parse(s.slice(5).trim());
            const text = json?.delta?.text;
            if (text) yield { type: 'text', text };
            if (json?.type === 'message_stop') { yield { type: 'done' }; return; }
          } catch { /* 分片不完整 */ }
        }
      }
      yield { type: 'done' };
    } catch (e) {
      yield { type: 'error', error: friendly(e) };
    } finally {
      clearTimeout(timer);
      signal?.removeEventListener('abort', onAbort);
    }
  })();
}

export async function* streamChat(
  provider: Provider,
  model: string,
  history: ChatMessage[],
  signal?: AbortSignal,
): AsyncGenerator<ChatChunk> {
  if (isTauri()) {
    yield* tauriStream(provider, model, history, signal);
    return;
  }
  yield* provider.format === 'anthropic'
    ? anthropicStream(provider, model, history, signal)
    : openaiStream(provider, model, history, signal);
}

/**
 * 引擎聊天流：Tauri 内走 Rust 引擎桥（engine_chat_stream）——引擎自带完整
 * 系统提示词（prompt_tier / SOUL_FULL 分层）、工具调用、安全闸门与会话持久化，
 * 与 TUI 完全对齐；SSE 事件 reason/tool/tool_result 一并回传。
 * 网页预览无引擎桥时降级为直连（仅开发用）。
 */
async function* engineStream(
  provider: Provider,
  model: string,
  message: string,
  session: string,
  signal?: AbortSignal,
): AsyncGenerator<ChatChunk> {
  const chan = new Channel<ChatChunk>();
  const queue: ChatChunk[] = [];
  let wake: (() => void) | null = null;
  let finished = false;
  chan.onmessage = (msg: ChatChunk) => {
    queue.push(msg);
    wake?.();
  };

  invoke<void>('engine_chat_stream', { provider, model, message, session, channel: chan })
    .then(() => {
      finished = true;
      wake?.();
    })
    .catch((e) => {
      queue.push({ type: 'error', error: String(e?.message ?? e ?? '引擎调用失败') });
      finished = true;
      wake?.();
    });

  const onAbort = () => {
    finished = true;
    wake?.();
    // 前端停止 → 引擎取消当前轮生成（对标 TUI Ctrl+C）
    invoke('engine_stop').catch(() => {});
  };
  signal?.addEventListener('abort', onAbort);

  for (;;) {
    while (queue.length) {
      const item = queue.shift()!;
      yield item;
      if (item.type === 'done' || item.type === 'error') return;
    }
    if (finished) return;
    await new Promise<'wait'>((r) => {
      wake = () => r('wait');
      setTimeout(() => r('wait'), 500);
    });
    wake = null;
  }
}

/**
 * Android轻量 Agent 流：走 Rust 侧 agent_chat_stream。
 * 由 Rust 复刻引擎的工具调用循环（联网抓取 / 搜索 / 计算 / 笔记），
 * 手机没有本地 Python 引擎，能力边界由系统提示词明确约束。
 */
async function* agentStream(
  provider: Provider,
  model: string,
  history: ChatMessage[],
  signal?: AbortSignal,
  enableTools = true,
): AsyncGenerator<ChatChunk> {
  const chan = new Channel<ChatChunk>();
  const queue: ChatChunk[] = [];
  let wake: (() => void) | null = null;
  let finished = false;
  chan.onmessage = (msg: ChatChunk) => {
    queue.push(msg);
    wake?.();
  };

  invoke<void>('agent_chat_stream', {
    provider,
    model,
    history: history.map((m) => ({ role: m.role, content: m.content })),
    enableTools,
    channel: chan,
  })
    .then(() => {
      finished = true;
      wake?.();
    })
    .catch((e) => {
      queue.push({ type: 'error', error: String(e?.message ?? e ?? 'Agent 调用失败') });
      finished = true;
      wake?.();
    });

  const onAbort = () => {
    finished = true;
    wake?.();
  };
  signal?.addEventListener('abort', onAbort);

  for (;;) {
    while (queue.length) {
      const item = queue.shift()!;
      yield item;
      if (item.type === 'done' || item.type === 'error') return;
    }
    if (finished) return;
    await new Promise<'wait'>((r) => {
      wake = () => r('wait');
      setTimeout(() => r('wait'), 500);
    });
    wake = null;
  }
}

/**
 * 聊天总入口。
 * 桌面端走引擎桥（完整系统提示词、工具调用、会话持久化）；
 * 引擎不可用时自动降级到直连协议（纯对话模式，无工具调用）；
 * Android 走 Rust 轻量 Agent；网页预览走浏览器 fetch。
 */
export async function* engineChat(
  provider: Provider,
  model: string,
  message: string,
  session: string,
  signal?: AbortSignal,
  history: ChatMessage[] = [],
  opts?: { agentMode?: boolean },
): AsyncGenerator<ChatChunk> {
  if (!isTauri()) {
    yield* streamChat(provider, model, [{ id: '', role: 'user', content: message, ts: Date.now() }], signal);
    return;
  }
  const turn: ChatMessage = { id: '', role: 'user', content: message, ts: Date.now() };
  if (needsDirectProtocol()) {
    if (opts?.agentMode === false) {
      // 关闭 Agent 能力时退化为纯对话
      yield* tauriStream(provider, model, [...history, turn], signal);
      return;
    }
    yield* agentStream(provider, model, [...history, turn], signal, true);
    return;
  }
  // 桌面端：引擎不可用时降级到直连协议，保证用户能用纯对话
  if (shouldFallback()) {
    yield* tauriStream(provider, model, [...history, turn], signal);
    return;
  }
  yield* engineStream(provider, model, message, session, signal);
}

/** 探测模型列表：Tauri 走 Rust，网页兜底直连，15 秒超时。 */
export async function probeModels(provider: Provider, timeoutMs = 15_000): Promise<string[]> {
  if (isTauri()) {
    try {
      return await invoke<string[]>('probe_models', { provider });
    } catch {
      return [];
    }
  }
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    if (provider.format === 'anthropic') return [];
    const base = provider.baseUrl.replace(/\/+$/, '');
    const resp = await fetch(`${base}/models`, {
      headers: { Authorization: `Bearer ${provider.apiKey}` },
      signal: ctrl.signal,
    });
    if (!resp.ok) return [];
    const data = await resp.json();
    const list: unknown[] = data?.data ?? [];
    return list.map((m) => String((m as { id?: string })?.id ?? '')).filter(Boolean);
  } catch {
    return [];
  } finally {
    clearTimeout(t);
  }
}
