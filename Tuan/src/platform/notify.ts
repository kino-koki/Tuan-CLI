import { store } from '../store/config';

/**
 * 桌面通知助手（T-5.1）。
 *
 * 覆盖三类 Agent 事件：回复完成（含摘要）/ 执行失败（含错误信息）/
 * 等待安全闸门确认。只做前端展示层——Rust 侧无独立通知通道，
 * 这里直接封装 Web Notification API。
 *
 * 降级策略（任一条件命中即静默，绝不抛错阻塞主流程）：
 *  1. 设置开关缺失或关闭：notifyEnabled / notifySound / doNotDisturb
 *     由「设置与外观」分片在 store/config.ts 提供；此处防御读取，
 *     缺失时默认「通知开启、提示音开启、免打扰关闭」；
 *  2. 当前窗口可见（document.visibilityState !== 'hidden'）：
 *     用户正盯着屏幕，不再弹窗打扰；
 *  3. 浏览器 / WebView 不支持 Notification，或用户已拒绝授权：
 *     静默忽略，不重复请求。
 *
 * 点击跳转：App.tsx 启动时通过 registerNotifyOpener 注册「打开指定会话」
 * 回调；通知点击时先 window.focus() 再触发回调。回调失败不阻塞。
 */

/** 设置读取结果（全部防御默认值） */
interface NotifySettings {
  /** 总开关（默认开启） */
  enabled: boolean;
  /** 提示音（默认开启；映射为 Notification silent 取反） */
  sound: boolean;
  /** 免打扰（默认关闭；开启时一律不弹） */
  dnd: boolean;
}

/** 通知点击跳转回调：参数为会话 id */
type NotifyOpener = (convId: string) => void;

let opener: NotifyOpener | null = null;

/** 注册通知点击跳转回调（App 启动时调一次，内部用最新的 openConv 逻辑） */
export function registerNotifyOpener(fn: NotifyOpener): void {
  opener = fn;
}

/**
 * 防御读取设置：「设置与外观」分片尚未接入 store 时全部回落默认值，
 * 不因为对方 API 缺席而打断启动流程。
 */
function readSettings(): NotifySettings {
  try {
    const s = store as unknown as Record<string, unknown>;
    const call = (key: string, fallback: boolean): boolean => {
      const fn = s[key];
      if (typeof fn === 'function') {
        try {
          return !!fn.call(store);
        } catch {
          return fallback;
        }
      }
      return fallback;
    };
    return {
      enabled: call('notifyEnabled', true),
      sound: call('notifySound', true),
      dnd: call('doNotDisturb', false),
    };
  } catch {
    return { enabled: true, sound: true, dnd: false };
  }
}

/** 页面是否切到后台（前台可见时不打扰） */
function pageHidden(): boolean {
  try {
    return typeof document !== 'undefined' && document.visibilityState === 'hidden';
  } catch {
    return false;
  }
}

/** 底层推送：所有前置条件不满足时静默返回，任何异常都不外抛 */
function push(title: string, body: string, convId: string): void {
  try {
    const cfg = readSettings();
    if (!cfg.enabled || cfg.dnd || !pageHidden()) return;
    if (typeof Notification === 'undefined') return;

    const show = () => {
      try {
        const n = new Notification(title, {
          body,
          // tag 去重：同一会话的新通知顶替旧通知，不堆通知中心
          tag: `tuan-${convId}`,
          silent: !cfg.sound,
        });
        n.onclick = () => {
          try {
            window.focus();
            opener?.(convId);
          } catch {
            /* 跳转失败不阻塞 */
          }
          n.close();
        };
      } catch {
        /* WebView 构造器不可用时静默降级 */
      }
    };

    const perm = Notification.permission;
    if (perm === 'granted') {
      show();
    } else if (perm !== 'denied' && typeof Notification.requestPermission === 'function') {
      // 尚未询问过：趁本次事件异步请求一次；用户拒绝后不再重复打扰
      Notification.requestPermission()
        .then((p) => {
          if (p === 'granted') show();
        })
        .catch(() => {});
    }
  } catch {
    /* 总兜底：通知永远不能影响对话主流程 */
  }
}

/** 摘要截断：通知正文不宜过长，保留前 120 个字符 */
function summarize(text: string): string {
  const t = (text || '').trim();
  if (!t) return '本轮回复已完成。';
  return t.length > 120 ? `${t.slice(0, 120)}…` : t;
}

/** Agent 回复完成通知（含摘要） */
export function notifyAgentDone(convId: string, summary: string): void {
  push('青小团 · 回复完成', summarize(summary), convId);
}

/** Agent 执行失败通知（含错误信息） */
export function notifyAgentError(convId: string, message: string): void {
  const m = (message || '').trim();
  push('青小团 · 执行出错', m ? `错误：${m.length > 160 ? `${m.slice(0, 160)}…` : m}` : '执行过程中发生未知错误。', convId);
}

/** Agent 等待安全闸门确认通知 */
export function notifyAgentApproval(convId: string, prompt: string): void {
  const p = (prompt || '').trim();
  push('青小团 · 需要你确认', p ? `安全审批：${p.length > 160 ? `${p.slice(0, 160)}…` : p}` : '引擎正在等待安全闸门审批。', convId);
}
