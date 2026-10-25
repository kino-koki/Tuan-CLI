import { useEffect, useRef, useState } from 'react';
import BrandMark from './BrandMark';
import { CrawlerSpinner, OnboardCheck, OnboardProgress, OnboardShell } from './OnboardKit';

export interface BootEngineStatus {
  ok: boolean;
  reason: string;
  python: string;
  app_version?: string;
  engine_version?: string;
  engine_root?: string;
}

interface Props {
  /** 启动时的真实引擎自检结果；null = 尚未返回 */
  engineStatus: BootEngineStatus | null;
  /** 序列完成（或用户跳过）时调用 */
  onDone: () => void;
}

/** 引擎状态的中文口径（就绪 / 降级 / 检测中）。 */
function engineLine(s: BootEngineStatus | null): { text: string; tone: 'ok' | 'warn' | 'wait' } {
  if (!s) return { text: '检测中', tone: 'wait' };
  if (s.ok) return { text: '就绪', tone: 'ok' };
  if (/android/i.test(s.reason)) return { text: '移动端直连模式', tone: 'warn' };
  return { text: '未启用 · 降级模式', tone: 'warn' };
}

/**
 * 启动加载序列。
 *
 * 设计语言与 EngineSetupPage 共用 OnboardKit（Claude 桌面端口径）：
 * 同底、同卡、同打勾、同菊花、同进度条——是主界面"开机一刻"的延伸，
 * 不是另一个产品。与上一版的区别：**不做任何表演**——
 * 没有呼吸光晕、没有标识浮动、没有弹跳勾选，全场只有一次
 * 「淡入 + 6px 微下沉」，然后如实逐项打勾。
 *
 * - 视觉：品牌标识安静出场（与 ChatView 空态同一枚 BrandMark）；
 * - 节奏：清单逐项落入、打勾小缩放淡入、3px 细进度条；
 * - 诚实：第三行「本地引擎」反映真实 check_engine 结果——
 *   就绪 / 未启用（降级）/ 检测中，不表演假进度；
 * - 退出：全部就绪后 0.4s 自动淡出；任意点击或按键立即跳过；
 *   prefers-reduced-motion 下直接放行，不做任何表演。
 */
export default function BootScreen({ engineStatus, onDone }: Props) {
  const [elapsed, setElapsed] = useState(0);
  const [leaving, setLeaving] = useState(false);
  const doneRef = useRef(false);

  const finish = () => {
    if (doneRef.current) return;
    doneRef.current = true;
    setLeaving(true);
    window.setTimeout(onDone, 240);
  };

  // 时间推进：清单按固定节奏逐项点亮
  useEffect(() => {
    if (window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      onDone();
      return;
    }
    const t0 = Date.now();
    const timer = window.setInterval(() => setElapsed(Date.now() - t0), 120);
    return () => window.clearInterval(timer);
  }, [onDone]);

  // 跳过：任意点击 / 按键
  useEffect(() => {
    const onKey = () => finish();
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  const rows = [
    { key: 'shell', label: '界面外壳', at: 260 },
    { key: 'data', label: '本地数据与偏好', at: 620 },
    { key: 'engine', label: '本地引擎', at: 980 },
    { key: 'ready', label: '准备就绪', at: 1500 },
  ];
  // 引擎行要等真实自检返回（最多等到 1.4s，之后按结果落笔）
  const engineArrived = engineStatus !== null || elapsed >= 1400;
  const stateOf = (r: { key: string; at: number }): 'wait' | 'done' => {
    if (r.key === 'engine') return engineArrived && elapsed >= r.at ? 'done' : 'wait';
    return elapsed >= r.at ? 'done' : 'wait';
  };
  const allDone = engineArrived && elapsed >= 1500;

  // 全部就绪 → 短暂停留后自动淡出
  useEffect(() => {
    if (!allDone) return;
    const t = window.setTimeout(finish, 420);
    return () => window.clearTimeout(t);
  }, [allDone]);

  const doneCount = rows.filter((r) => stateOf(r) === 'done').length;
  const pct = Math.round((doneCount / rows.length) * 100);
  const eng = engineLine(engineStatus);

  return (
    <div
      className={`boot-screen fixed inset-0 z-[100] flex flex-col items-center justify-center bg-tuan-main select-none ${leaving ? 'boot-screen-out' : ''}`}
      onClick={finish}
      role="status"
      aria-label="正在启动"
    >
      <div className="onboard-shell flex flex-col items-center justify-center">
        {/* 品牌标识：安静出场——无光晕、无浮动（与 ChatView 空态同一枚 BrandMark） */}
        <div className="onboard-in mb-8">
          <BrandMark size="lg" />
        </div>

        {/* 启动清单：与安装向导同款卡片（.tuan-card：白底 + 发丝边 + 16px 圆角） */}
        <div className="onboard-in tuan-card w-[320px] max-w-full px-5 py-4" style={{ animationDelay: '0.08s' }}>
          <div className="space-y-2.5">
            {rows.map((r) => {
              const st = stateOf(r);
              return (
                <div key={r.key} className="flex h-7 items-center">
                  <span className="flex h-4 w-4 flex-none items-center justify-center">
                    {st === 'done' ? (
                      <OnboardCheck />
                    ) : (
                      <CrawlerSpinner className="!h-[14px] !w-[14px]" />
                    )}
                  </span>
                  <span
                    className={`ml-3 text-[13.5px] transition-colors ${
                      st === 'done' ? 'text-tuan-text' : 'text-tuan-textSecondary'
                    }`}
                  >
                    {r.label}
                  </span>
                  {r.key === 'engine' && (
                    <span
                      className={`ml-auto text-[12px] ${
                        eng.tone === 'ok' ? 'text-tuan-accentSoft' : 'text-tuan-textSecondary'
                      }`}
                    >
                      {eng.text}
                    </span>
                  )}
                </div>
              );
            })}
          </div>
          <div className="mt-4 border-t border-tuan-border pt-3">
            <OnboardProgress pct={pct} label={false} />
            <div className="mt-2 flex items-center justify-between">
              <span className="text-[11.5px] text-tuan-textSecondary tabular-nums">{pct}%</span>
              <span className="text-[11.5px] text-tuan-textSecondary">点击任意处跳过</span>
            </div>
          </div>
        </div>

        {engineStatus?.app_version && (
          <div className="onboard-in mt-6 text-[11px] text-tuan-textSecondary" style={{ animationDelay: '0.16s' }}>
            Tuan-Chat v{engineStatus.app_version}
          </div>
        )}
      </div>
    </div>
  );
}
