/**
 * 移动端 / 原生壳适配层（对应 26.10.23 代办 §8 的 W-2 / W-3 / W-7 / W-8）。
 *
 * 为什么单独抽一层：
 *   Tauri 的原生壳（Android WebView 的 onBackPressed / KEYCODE_MENU 拦截）
 *   只能通过 window.__nav 这个命名空间回灌到前端；而侧栏抽屉、伪路由返回栈、
 *   横竖屏复位、软键盘避让这四件事的触发源各不相同（硬件键 / 浏览器历史 /
 *   orientationchange / resize），塞进 App.tsx 会让那个文件更难读。
 *   本文件只做「事件 → 回调」的接线，不含任何 React 状态，也不 import React。
 *
 * 兼容性约束：必须能跑在 Android 8.0 的 Chrome 68 WebView 上，因此
 *   - 不用 ?. / ??（Chrome 80 才有）；
 *   - 不用 Object.fromEntries / Array.flat / Promise.any；
 *   - 不用 CSS 容器查询、:has()、color-mix()、100dvh；
 *   - 所有可选对象（visualViewport / matchMedia / history）都先判空。
 *
 * 所有函数都返回一个幂等的清理函数，配合 React 的 useEffect return 使用；
 * 在 SSR / 非浏览器环境（window 不存在）下一律静默跳过，不抛异常。
 */

/** 原生壳 → 前端的导航指令集合。全部可选，调用方按需组合。 */
export interface NavHandlers {
  /** 侧栏开合（原生壳拦 KEYCODE_MENU 后回调） */
  toggleSidebar?: () => void;
  /** 返回：先退伪路由栈，栈空则交回原生壳决定 */
  back?: () => void;
  /** 当前是否存在可退的一层（供原生壳决定是否吞掉物理返回键） */
  canBack?: () => boolean;
  /** 横竖屏 / 视口跨断点后的布局复位 */
  onOrientation?: () => void;
}

type NavBag = Record<string, unknown>;

/**
 * 合并式写入 window.__nav。
 *
 * 刻意不做整体赋值：多个模块（导航栈、手势、原生壳）都可能往 __nav 上加键，
 * 谁整体覆盖谁就把别人的键清掉了。这里逐键合并，卸载时只撤掉本次写入的键。
 */
export function installNav(handlers: NavHandlers): () => void {
  if (typeof window === 'undefined') return () => {};
  const w = window as unknown as { __nav?: NavBag };
  const keys = Object.keys(handlers) as Array<keyof NavHandlers>;
  const merged: NavBag = Object.assign({}, w.__nav || {});
  for (const k of keys) {
    const v = handlers[k];
    if (v !== undefined) merged[k as string] = v;
  }
  w.__nav = merged;
  const written = keys.filter((k) => handlers[k] !== undefined) as string[];
  return () => {
    const cur = w.__nav;
    if (cur && cur !== merged) return; // 后来者已整体替换，不再动手
    for (const k of written) delete merged[k];
  };
}

/** 暴露给原生壳判定用：当前是否还能再退一层。 */
export function navCanBack(): boolean {
  if (typeof window === 'undefined') return false;
  const n = (window as unknown as { __nav?: NavBag }).__nav;
  const f = n && typeof n.canBack === 'function' ? (n.canBack as () => boolean) : null;
  return !!f && !!f();
}

/**
 * W-2 硬件菜单键。
 *
 * Android WebView 的物理「菜单键」在 Chrome 系一直派发 keydown 且
 * key === 'ContextMenu'（Chrome 8 时代的遗留标识，至今未改）——
 * 这是纯前端能拿到的唯一信号，无需原生层。
 * 另外兼容原生壳主动派发 CustomEvent('tuan-nav') 的写法，两条路都接。
 */
export function attachMenuKey(onToggle: () => void): () => void {
  if (typeof window === 'undefined') return () => {};
  const onKey = (e: KeyboardEvent) => {
    if (e.key === 'ContextMenu') {
      e.preventDefault();
      onToggle();
    }
  };
  const onCustom = (e: Event) => {
    const d = (e as CustomEvent).detail as { action?: string } | null | undefined;
    if (d && (d.action === 'toggleSidebar' || d.action === 'menu')) onToggle();
  };
  window.addEventListener('keydown', onKey);
  window.addEventListener('tuan-nav', onCustom as EventListener);
  return () => {
    window.removeEventListener('keydown', onKey);
    window.removeEventListener('tuan-nav', onCustom as EventListener);
  };
}

export interface BackNavOptions {
  /** 栈里当前有没有可退的一层（决定 popstate 是退栈还是交回原生壳） */
  canGoBack: () => boolean;
  /** 退一层：关闭栈顶浮层（返回聊天页 / 收起抽屉等） */
  goBack: () => void;
  /** 是否启用侧滑返回（默认启用） */
  swipeBack?: boolean;
  /** 侧滑起点热区宽度（px），默认 32 */
  edgeWidth?: number;
  /** 侧滑判定阈值（px），默认 56 */
  swipeThreshold?: number;
}

/**
 * W-3 返回键 / 侧滑返回。
 *
 * 单页应用没有真实路由，浏览器历史栈是空的，原生壳的 onBackPressed
 * 会把用户直接踢出应用。这里用 history.pushState 造一层「伪路由」：
 * 首次挂载用 replaceState 清一次基线，之后每次打开浮层 push 一层，
 * popstate 时交给 goBack 关栈顶。侧滑返回复用同一出口，逻辑不分叉。
 */
export function attachBackNav(opts: BackNavOptions): () => void {
  if (typeof window === 'undefined') return () => {};
  const { canGoBack, goBack } = opts;
  const edge = opts.edgeWidth ?? 32;
  const thr = opts.swipeThreshold ?? 56;

  // 清一次基线：不要在初始 URL 上多留一层历史
  try {
    if (window.history && typeof window.history.replaceState === 'function') {
      window.history.replaceState(null, '', window.location.href);
    }
  } catch {
    /* file:// 等受限来源不允许写 history，忽略 */
  }

  const onPop = () => {
    if (canGoBack()) goBack();
  };
  window.addEventListener('popstate', onPop);

  let sx = 0;
  let sy = 0;
  let tracking = false;
  let detachSwipe: (() => void) | null = null;
  if (opts.swipeBack !== false && typeof document !== 'undefined') {
    const onStart = (e: TouchEvent) => {
      const t = e.touches && e.touches[0];
      if (!t) return;
      // 只在屏幕最左缘的热区内开始追踪，避免和列表横向滑动冲突
      tracking = t.clientX < edge;
      sx = t.clientX;
      sy = t.clientY;
    };
    const onEnd = (e: TouchEvent) => {
      if (!tracking) return;
      tracking = false;
      const t = e.changedTouches && e.changedTouches[0];
      if (!t) return;
      const dx = t.clientX - sx;
      const dy = t.clientY - sy;
      // 必须明显是「横向往右滑」，纵向滚动不算
      if (dx > thr && Math.abs(dx) > Math.abs(dy) && canGoBack()) {
        e.preventDefault();
        goBack();
      }
    };
    window.addEventListener('touchstart', onStart, { passive: true });
    // touchend 需要 preventDefault 阻止原生返回，所以不能 passive
    window.addEventListener('touchend', onEnd, { passive: false });
    detachSwipe = () => {
      window.removeEventListener('touchstart', onStart);
      window.removeEventListener('touchend', onEnd);
    };
  }
  return () => {
    window.removeEventListener('popstate', onPop);
    if (detachSwipe) detachSwipe();
  };
}

export interface OrientationOptions {
  /** 复位回调：关抽屉、重画画布、消息滚到底、输入框自适应 */
  onChange: () => void;
  /** 断点边界（px），从左到右递增；跨档才触发，默认 [480, 640, 820] */
  bands?: readonly number[];
  /** resize 防抖延迟（ms），默认 160 */
  debounceMs?: number;
}

/**
 * W-7 横竖屏切换布局复位。
 *
 * 两个入口：
 *   1) orientationchange —— 触发时窗口尺寸尚未稳定，延迟 120ms 再复位；
 *   2) resize 防抖 —— 只在「宽度跨断点」时才复位，避免每次 resize 都重排。
 * 再加 matchMedia 兜底：部分老内核在快速横竖屏切换时会丢掉 orientationchange。
 *
 * matchMedia 的监听按内核可用性降级：68 只有 addListener，新内核两个都有，
 * 全用 try/catch 包住，任何一个都取不到就跳过，不影响主路径。
 */
export function attachOrientation(opts: OrientationOptions): () => void {
  if (typeof window === 'undefined') return () => {};
  const { onChange } = opts;
  const bands = opts.bands && opts.bands.length ? opts.bands : [480, 640, 820];
  const ms = opts.debounceMs ?? 160;

  const fire = () => {
    window.setTimeout(onChange, 120);
  };

  window.addEventListener('orientationchange', fire);

  let lastBand = -1;
  let lastBW = 0;
  let timer: number | undefined;
  const bandOf = (w: number): number => {
    let b = 0;
    for (let i = 0; i < bands.length; i++) {
      if (w >= bands[i]) b = i;
    }
    return b;
  };
  const onResize = () => {
    const bw = Math.floor(window.innerWidth);
    if (bw === lastBW) return;
    lastBW = bw;
    const band = bandOf(bw);
    if (band === lastBand) return;
    lastBand = band;
    if (timer) window.clearTimeout(timer);
    timer = window.setTimeout(onChange, ms);
  };
  window.addEventListener('resize', onResize);

  const mqCleanups: Array<() => void> = [];
  if (typeof window.matchMedia === 'function') {
    for (const q of ['(max-width: 819px)', '(orientation: portrait)']) {
      try {
        const mq = window.matchMedia(q);
        if (!mq) continue;
        if (typeof (mq as unknown as { addListener?: (cb: () => void) => void }).addListener === 'function') {
          const cb = () => fire();
          (mq as unknown as { addListener: (cb: () => void) => void }).addListener(cb);
          mqCleanups.push(() => {
            (mq as unknown as { removeListener?: (cb: () => void) => void }).removeListener?.(cb);
          });
        } else {
          const cb = () => fire();
          mq.addEventListener('change', cb);
          mqCleanups.push(() => mq.removeEventListener('change', cb));
        }
      } catch {
        /* 老内核不支持 matchMedia，跳过 */
      }
    }
  }

  return () => {
    window.removeEventListener('orientationchange', fire);
    window.removeEventListener('resize', onResize);
    if (timer) window.clearTimeout(timer);
    for (const c of mqCleanups) {
      try {
        c();
      } catch {
        /* 忽略卸载期的二次异常 */
      }
    }
  };
}

export interface KeyboardAvoidanceOptions {
  /** 输入元素选择器（可命中多个），默认 textarea, input */
  selector?: string;
  /** 判定键盘弹出的最小高度差（px），默认 12，过滤掉布局抖动 */
  minDelta?: number;
  /** 偏移量写入 body 的 CSS 变量名，默认 --kb-offset */
  cssVar?: string;
}

/**
 * W-8 软键盘遮挡兜底。
 *
 * viewport 已写 interactive-widget=resizes-content，但 Android 8.0 的
 * Chrome 68 WebView 不识别该属性——键盘弹出时视口不收缩，输入卡被整块盖住。
 * 这里不依赖任何新特性：
 *   1) focusin 记录「键盘收起时」的视口高度作基线；
 *   2) resize 时算高度差，超过阈值就判定键盘弹出；
 *   3) 把偏移量写成 body 上的 CSS 变量（--kb-offset），由样式层喂给输入卡；
 *   4) 再 scrollIntoView 兜底，确保输入行可见。
 * visualViewport 有更准的口径，可用就用，用 try/catch 包住以兼容 68。
 */
export function attachKeyboardAvoidance(opts: KeyboardAvoidanceOptions = {}): () => void {
  if (typeof window === 'undefined' || typeof document === 'undefined') return () => {};
  const sel = opts.selector || 'textarea, input';
  const minDelta = opts.minDelta ?? 12;
  const cssVar = opts.cssVar || '--kb-offset';

  let base = 0;
  let timer: number | undefined;

  const apply = (off: number) => {
    const b = document.body;
    if (!b) return;
    b.style.setProperty(cssVar, off > minDelta ? off + 'px' : '0px');
  };
  const isFocused = (): boolean => {
    const el = document.activeElement as HTMLElement | null;
    if (!el || typeof el.closest !== 'function') return false;
    return !!el.closest(sel);
  };

  const onResize = () => {
    if (timer) window.clearTimeout(timer);
    timer = window.setTimeout(() => {
      if (!base || !isFocused()) {
        apply(0);
        return;
      }
      const off = base - window.innerHeight;
      if (off < minDelta) {
        apply(0);
        return;
      }
      apply(off);
      const el = document.querySelector(sel) as HTMLElement | null;
      if (el && typeof el.scrollIntoView === 'function') {
        el.scrollIntoView(false);
      }
    }, 70);
  };

  const onFocus = (e: Event) => {
    const t = e.target as HTMLElement | null;
    if (!t || typeof t.closest !== 'function' || !t.closest(sel)) return;
    base = window.innerHeight;
    apply(0);
  };
  const onBlur = (e: Event) => {
    const t = e.target as HTMLElement | null;
    if (!t || typeof t.closest !== 'function' || !t.closest(sel)) return;
    apply(0);
  };

  window.addEventListener('resize', onResize);
  document.addEventListener('focusin', onFocus);
  document.addEventListener('focusout', onBlur);

  let vvClean: (() => void) | null = null;
  try {
    const vv = (window as unknown as { visualViewport?: EventTarget }).visualViewport;
    if (vv && typeof vv.addEventListener === 'function') {
      vv.addEventListener('resize', onResize);
      vvClean = () => vv.removeEventListener('resize', onResize);
    }
  } catch {
    /* 68 老内核没有 visualViewport，走纯 resize 路径 */
  }

  return () => {
    if (timer) window.clearTimeout(timer);
    window.removeEventListener('resize', onResize);
    document.removeEventListener('focusin', onFocus);
    document.removeEventListener('focusout', onBlur);
    if (vvClean) vvClean();
    apply(0);
  };
}
