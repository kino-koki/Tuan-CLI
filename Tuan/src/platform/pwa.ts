/**
 * PWA 支持层（T-6.3）。
 *
 * 职责：
 *  1. 注册 /sw.js（vite 会把 public/sw.js 原样复制到 dist 根目录）；
 *  2. 拦截浏览器 beforeinstallprompt，把事件缓存起来，供界面（侧栏用户菜单）
 *     主动触发「安装到桌面/主屏幕」；
 *  3. 提供 install 状态订阅：界面用它决定是否显示「安装应用」按钮。
 *
 * 全部逻辑防御性降级：不支持 Service Worker / 已安装 / 用户拒绝安装时都静默，
 * 不影响主流程。
 */

/** beforeinstallprompt 事件的最小形态（TS DOM 库无此类型，手动声明） */
interface BeforeInstallPromptEvent extends Event {
  prompt: () => Promise<void>;
  userChoice: Promise<{ outcome: 'accepted' | 'dismissed' }>;
}

let deferredPrompt: BeforeInstallPromptEvent | null = null;
/** 是否已安装（display-mode: standalone 即视为已安装，不再显示安装入口） */
let installed = false;
type InstallListener = (canInstall: boolean) => void;
const listeners = new Set<InstallListener>();

function emit(): void {
  const can = !installed && !!deferredPrompt;
  for (const cb of listeners) {
    try {
      cb(can);
    } catch {
      /* 单个订阅者异常不影响其它 */
    }
  }
}

/** 是否当前可展示安装入口（未安装且已捕获到 beforeinstallprompt） */
export function canInstallPwa(): boolean {
  return !installed && !!deferredPrompt;
}

/** 订阅安装可用性变化；返回取消订阅函数 */
export function onInstallPromptAvailable(cb: InstallListener): () => void {
  listeners.add(cb);
  // 订阅时立即推一次当前状态，避免界面错过初始化前的事件
  try {
    cb(canInstallPwa());
  } catch {
    /* 忽略 */
  }
  return () => listeners.delete(cb);
}

/** 触发系统安装弹窗；用户接受返回 true，拒绝/失败返回 false */
export async function promptInstall(): Promise<boolean> {
  if (!deferredPrompt) return false;
  try {
    await deferredPrompt.prompt();
    const choice = await deferredPrompt.userChoice;
    if (choice.outcome === 'accepted') {
      installed = true;
      deferredPrompt = null;
      emit();
      return true;
    }
    return false;
  } catch {
    return false;
  }
}

/** 初始化：注册 Service Worker + 安装提示拦截。main.tsx 启动时调用一次。 */
export function initPwa(): void {
  if (typeof window === 'undefined' || typeof navigator === 'undefined') return;

  // 已以 standalone 模式打开（已安装）：不显示安装入口
  try {
    const displayMode = (window.matchMedia?.('(display-mode: standalone)')?.matches) ?? false;
    if (displayMode) installed = true;
  } catch {
    /* 老内核无 matchMedia，按未安装处理 */
  }

  // 拦截 beforeinstallprompt：必须 preventDefault 才能留住事件
  window.addEventListener('beforeinstallprompt', (e) => {
    try {
      e.preventDefault();
      deferredPrompt = e as BeforeInstallPromptEvent;
      emit();
    } catch {
      /* 忽略 */
    }
  });

  // 安装完成后不再提示
  window.addEventListener('appinstalled', () => {
    installed = true;
    deferredPrompt = null;
    emit();
  });

  // 注册 Service Worker（仅在 https 或 localhost 下浏览器才会放行，失败静默）
  if ('serviceWorker' in navigator) {
    window.addEventListener('load', () => {
      navigator.serviceWorker.register('/sw.js').catch(() => {
        /* 离线/缓存不影响主功能 */
      });
    });
  }
}
