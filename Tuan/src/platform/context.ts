/**
 * 上下文预算仪表 (Context Budget Gauge) —— 模块 3。
 *
 * 从引擎 /api/context 拉取当前会话的 token 占用估算, 对照 model.context_window
 * 渲染为状态栏的「预算进度条」。命中 70% / 90% 阈值分别变黄/变红,
 * 100% 标为「溢出」—— 提醒用户及时 /compact, 避免无声截断。
 *
 * 引擎侧口径（est.）: 混合中英文按 ~3 字符/token 估算, 前端明确标注为估算值。
 */
import { TTS_ENGINE_URL } from './tts';

export interface ContextGauge {
  /** 上下文窗口上限（token） */
  window: number;
  /** 当前会话估算 token（est.） */
  estTokens: number;
  /** 占比 0~1 */
  ratio: number;
}

const _ctxCache: { url: string; data: ContextGauge | null } = { url: '', data: null };

async function _rawContext(): Promise<{ window: number; sessions: { id: string; est_tokens: number }[] } | null> {
  try {
    const res = await fetch(`${TTS_ENGINE_URL}/api/context`, { cache: 'no-store' });
    if (!res.ok) return null;
    const j = (await res.json()) as {
      ok?: boolean;
      window?: number;
      sessions?: { id: string; est_tokens: number }[];
    };
    if (!j.ok) return null;
    return { window: j.window ?? 128000, sessions: j.sessions ?? [] };
  } catch {
    return null;
  }
}

/** 拉取上下文预算仪表数据。convId 缺省时用「全部会话合计」。 */
export async function fetchContextGauge(convId?: string): Promise<ContextGauge | null> {
  const raw = await _rawContext();
  if (!raw) return null;
  let est = 0;
  if (convId) {
    const s = raw.sessions.find((x) => x.id === convId);
    est = s ? s.est_tokens : 0;
  } else {
    est = raw.sessions.reduce((a, s) => a + s.est_tokens, 0);
  }
  const window = Math.max(raw.window, 1);
  const gauge: ContextGauge = {
    window,
    estTokens: est,
    ratio: Math.min(est / window, 2), // 上限 200%, 超出也只显示到 200%
  };
  _ctxCache.url = `${TTS_ENGINE_URL}/api/context`;
  _ctxCache.data = gauge;
  return gauge;
}

/** 引擎最近一次预算数据（供瞬时渲染, 不额外 fetch） */
export function cachedContextGauge(): ContextGauge | null {
  return _ctxCache.data;
}

export function gaugeColor(ratio: number): string {
  if (ratio >= 0.9) return 'var(--tuan-danger)';
  if (ratio >= 0.7) return 'var(--tuan-accent-soft)';
  return 'var(--tuan-ok)';
}

export function gaugeLabel(ratio: number): string {
  const pct = Math.round(ratio * 100);
  if (ratio >= 1) return `ctx ${pct}% 溢出`;
  return `ctx ${pct}%`;
}
