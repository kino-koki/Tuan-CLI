/**
 * MOSS-TTS-Nano 本地语音合成前端模块。
 *
 * 引擎 web 服务（127.0.0.1:8137，与 src-tauri/engine_chat.rs 的 ENGINE_PORT 一致）
 * 已内置 /api/tts/* 路由（见 engine/tuan_cli/web/tts_service.py）。WebView 直接
 * fetch 该服务：
 * - 合成：POST /api/tts/synthesize（服务端已放开 CORS）；
 * - 音频：GET /tts_audio/<name>.wav；
 * - 引擎未启动 / 依赖缺失 / 合成失败时全部优雅降级（speak 返回 false，不抛错）。
 */
import { store } from '../store/config';
import { isAndroid } from './engine';
import { invoke, isTauri } from '@tauri-apps/api/core';

export const TTS_ENGINE_URL = 'http://127.0.0.1:8137';

/** 引擎 i18n 的 10 种语言（与 engine/tuan_cli/i18n/locales 一致） */
export const TTS_LANGUAGES: { code: string; label: string }[] = [
  { code: 'zh_CN', label: '简体中文' },
  { code: 'zh_TW', label: '繁體中文' },
  { code: 'en', label: 'English' },
  { code: 'ja', label: '日本語' },
  { code: 'ko', label: '한국어' },
  { code: 'es', label: 'Español' },
  { code: 'fr', label: 'Français' },
  { code: 'de', label: 'Deutsch' },
  { code: 'pt_BR', label: 'Português (Brasil)' },
  { code: 'ru', label: 'Русский' },
];

/** Tuan 语言 code → Android Locale 字符串（系统原生 TTS 用） */
const ANDROID_LOCALES: Record<string, string> = {
  zh_CN: 'zh-CN',
  zh_TW: 'zh-TW',
  en: 'en-US',
  ja: 'ja-JP',
  ko: 'ko-KR',
  es: 'es-ES',
  fr: 'fr-FR',
  de: 'de-DE',
  pt_BR: 'pt-BR',
  ru: 'ru-RU',
};

/**
 * Android 无 PyTorch → 无法运行本地 MOSS-TTS。走系统原生 TextToSpeech：
 * 优先 Tauri 原生桥（src-tauri/plugins/tuan-tts，Rust 命令 tts_speak），
 * 桥未接入时回退 WebView speechSynthesis；都不行则静默返回 false。
 */
async function speakAndroid(text: string, language: string): Promise<boolean> {
  const locale = ANDROID_LOCALES[language] ?? 'zh-CN';
  try {
    if (isTauri()) {
      await invoke('tts_speak', { text, lang: locale });
      return true;
    }
  } catch {
    /* 原生桥未接入则继续回退 */
  }
  try {
    if (typeof window !== 'undefined' && window.speechSynthesis && typeof window.speechSynthesis.speak === 'function') {
      const u = new SpeechSynthesisUtterance(text);
      u.lang = locale;
      window.speechSynthesis.speak(u);
      return true;
    }
  } catch {
    /* 忽略 */
  }
  return false;
}

/** 服务端不可达时的音色静态回退清单（与 tts_service.VOICES 保持一致） */
export const TTS_VOICE_FALLBACK: { key: string; label: string }[] = [
  { key: 'zh_1', label: '中文·官方女声' },
  { key: 'zh_3', label: '中文·京味闲聊（活力，默认）' },
  { key: 'zh_4', label: '中文·台湾腔' },
  { key: 'zh_6', label: '中文·深夜温柔' },
  { key: 'zh_10', label: '中文·讲坛' },
  { key: 'zh_11', label: '中文·与自己同行' },
  { key: 'zh_male', label: '中文·男声（官方 Bitter Lesson 音色）' },
  { key: 'en_2', label: '英语·The Bitter Lesson（男声）' },
  { key: 'en_3', label: '英语·A Gentle Reminder' },
  { key: 'en_4', label: '英语·新闻（10 语言通用音色）' },
  { key: 'en_6', label: '英语·官方 Welcome' },
  { key: 'en_7', label: '英语·You Are Not Alone Tonight' },
  { key: 'en_8', label: '英语·The Quiet Motion' },
  { key: 'jp_2', label: '日语·新闻' },
];

export interface TtsStatus {
  ok: boolean;
  model_loaded: boolean;
  load_error: string | null;
  busy: boolean;
  synth_count: number;
  last_duration_s: number | null;
  cache_size?: number;
  voices: string[];
  voice_labels: Record<string, string>;
  custom_voices?: { key: string; label: string }[];
  languages: string[];
  lang_presets: Record<string, string>;
  default_voice: string;
}

export async function ttsStatus(): Promise<TtsStatus | null> {
  try {
    const resp = await fetch(`${TTS_ENGINE_URL}/api/tts/status`, {
      signal: AbortSignal.timeout(3000),
    });
    if (!resp.ok) return null;
    return (await resp.json()) as TtsStatus;
  } catch {
    return null;
  }
}

export type TtsSynthResult =
  | { ok: true; audio_name: string }
  | { ok: false; error: string };

export async function ttsSynthesize(
  text: string,
  voice?: string,
  language?: string,
): Promise<TtsSynthResult> {
  try {
    const resp = await fetch(`${TTS_ENGINE_URL}/api/tts/synthesize`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        text,
        voice: voice || undefined,
        language: language || undefined,
      }),
      signal: AbortSignal.timeout(300_000),
    });
    const data: unknown = await resp.json().catch(() => ({}));
    const d = data as { ok?: boolean; audio_name?: string; error?: string };
    return d?.ok && d.audio_name
      ? { ok: true, audio_name: d.audio_name }
      : { ok: false, error: d?.error ?? `HTTP ${resp.status}` };
  } catch (e) {
    return { ok: false, error: String(e) };
  }
}

export function ttsAudioUrl(audioName: string): string {
  return `${TTS_ENGINE_URL}/tts_audio/${encodeURIComponent(audioName)}`;
}

/** 文件 → base64（不含 data: 前缀），用于上传注册专属音色 */
export function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const dataUrl = String(reader.result ?? '');
      const idx = dataUrl.indexOf(',');
      resolve(idx >= 0 ? dataUrl.slice(idx + 1) : dataUrl);
    };
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
}

export type TtsRegisterResult =
  | { ok: true; key: string }
  | { ok: false; error: string };

/**
 * 注册专属音色：上传一段用户自有/有权使用的音频（自己录的即可），
 * 经 voice_clone 生成专属音色。真人明星音色不支持爬取克隆。
 */
export async function ttsRegisterVoice(
  name: string,
  file: File,
): Promise<TtsRegisterResult> {
  try {
    const audio_b64 = await fileToBase64(file);
    const resp = await fetch(`${TTS_ENGINE_URL}/api/tts/register_voice`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, audio_b64 }),
      signal: AbortSignal.timeout(120_000),
    });
    const data: unknown = await resp.json().catch(() => ({}));
    const d = data as { ok?: boolean; key?: string; error?: string };
    return d?.ok && d.key
      ? { ok: true, key: d.key }
      : { ok: false, error: d?.error ?? `HTTP ${resp.status}` };
  } catch (e) {
    return { ok: false, error: String(e) };
  }
}

/* ---------- 单一播放器（同一时刻只播一段语音） ---------- */

let currentAudio: HTMLAudioElement | null = null;
let speakingKey = '';
let speakingMsgId = '';

export function stopSpeech(): void {
  if (currentAudio) {
    currentAudio.pause();
    currentAudio = null;
  }
  speakingKey = '';
  speakingMsgId = '';
  if (isAndroid()) {
    if (isTauri()) {
      invoke('tts_stop').catch(() => {});
    }
    try {
      if (typeof window !== 'undefined' && window.speechSynthesis) {
        window.speechSynthesis.cancel();
      }
    } catch {
      /* 忽略 */
    }
  }
}

export function isSpeaking(): boolean {
  return currentAudio != null;
}

export function speakingId(): string {
  return speakingMsgId;
}

/**
 * 合成并播放。onEnd 在播放结束 / 失败 / 被新语音打断时回调（用于复位按钮态）。
 * 引擎不可用或合成失败时静默返回 false。
 */
export async function speak(
  text: string,
  voice?: string,
  language?: string,
  msgId = '',
  onEnd?: () => void,
): Promise<boolean> {
  stopSpeech();
  const t = (text || '').trim();
  if (!t) return false;
  // Android：无 PyTorch，走系统原生 TTS（音色参数忽略，语言映射到系统 Locale）
  if (isAndroid()) {
    const ok = await speakAndroid(t, language ?? store.ttsLanguage());
    if (!ok && onEnd) onEnd();
    return ok;
  }
  const res = await ttsSynthesize(t, voice, language);
  if (!res.ok) return false;
  try {
    const audio = new Audio(ttsAudioUrl(res.audio_name));
    currentAudio = audio;
    speakingKey = t;
    speakingMsgId = msgId;
    const finish = () => {
      if (currentAudio === audio) {
        currentAudio = null;
        speakingKey = '';
        speakingMsgId = '';
      }
      onEnd?.();
    };
    audio.onended = finish;
    audio.onerror = finish;
    await audio.play();
    return true;
  } catch {
    if (currentAudio) currentAudio = null;
    speakingKey = '';
    speakingMsgId = '';
    return false;
  }
}

/** 按当前设置朗读一段文本（App 自动播报 / 设置页试听共用）。 */
export async function speakWithSettings(
  text: string,
  msgId = '',
  onEnd?: () => void,
): Promise<boolean> {
  if (!store.ttsEnabled()) return false;
  return speak(text, store.ttsVoice(), store.ttsLanguage(), msgId, onEnd);
}
