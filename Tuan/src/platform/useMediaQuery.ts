import { useEffect, useState } from 'react';

/**
 * 响应式查询 hook。
 * 用途：桌面端（宽窗口）用 Claude 桌面式下拉弹层，窄屏回落原生 <select>
 * （安卓低端 WebView 上原生控件更稳，且不占布局空间）。
 */
export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(
    () =>
      typeof window !== 'undefined' &&
      typeof window.matchMedia === 'function' &&
      window.matchMedia(query).matches,
  );

  useEffect(() => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return;
    const mql = window.matchMedia(query);
    const onChange = () => setMatches(mql.matches);
    onChange();
    // Safari < 14 只有老 API，两者都接一下保证兼容
    if (typeof mql.addEventListener === 'function') {
      mql.addEventListener('change', onChange);
      return () => mql.removeEventListener('change', onChange);
    }
    mql.addListener(onChange);
    return () => mql.removeListener(onChange);
  }, [query]);

  return matches;
}
