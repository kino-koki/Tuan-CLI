/**
 * 语音协警 (Voice Copilot) —— 模块 4。
 *
 * 在关键事件发生时用本地 TTS 播报一句短提示, 让用户不必盯着屏幕也能感知
 * agent 状态: 「需要授权」「回复完成」「出错了」。首创性: 多数 Agent 的 TTS
 * 只做"朗读回复", 把事件变成语音提醒的很少; 且完全本地、可一键关闭。
 *
 * 防噪策略:
 *  - 同类事件 1.5s 内合并 (例如连续两个工具事件只播一次);
 *  - 全局 800ms 节流, 避免工具风暴把 TTS 打爆;
 *  - 开关与 TTS 主开关双保险 (voiceCopilot 关闭或 ttsEnabled 关闭都不播)。
 */
import { store } from '../store/config';
import { speakWithSettings } from './tts';

export type CopilotEvent = 'approval' | 'done' | 'error';

const TEXT: Record<CopilotEvent, string> = {
  approval: '需要你的授权',
  done: '回复完成',
  error: '出错了',
};

let lastEventAt: Record<CopilotEvent, number> = {
  approval: 0,
  done: 0,
  error: 0,
};
let lastAnyAt = 0;

const SAME_EVENT_GAP = 1500; // 同类事件合并窗口 (ms)
const ANY_EVENT_GAP = 800; // 全局节流 (ms)

/** 通知一次关键事件 (自动防抖; 开关关闭时静默)。 */
export function notifyVoiceCopilot(ev: CopilotEvent): void {
  if (!store.voiceCopilotEnabled()) return;
  if (!store.ttsEnabled()) return;
  const now = Date.now();
  if (now - lastEventAt[ev] < SAME_EVENT_GAP) return;
  if (now - lastAnyAt < ANY_EVENT_GAP) return;
  lastEventAt[ev] = now;
  lastAnyAt = now;
  void speakWithSettings(TEXT[ev]);
}

/** 测试播报 (设置页试听用)。 */
export function previewVoiceCopilot(): void {
  if (!store.voiceCopilotEnabled() && !store.ttsEnabled()) return;
  void speakWithSettings('事件提醒已开启');
}
