import { useEffect, useRef, useState } from 'react';
import { Check } from 'lucide-react';
import BrandMark from './BrandMark';

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
 * 启动加载序列（豆包 × CodeX 风格）。
 *
 * - 视觉：品牌标识呼吸柔光 + 轻浮动（豆包的温暖感）；
 * - 节奏：CodeX 式清单逐项落入、打勾弹跳、细进度条；
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
    window.setTimeout(onDone, 320);
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
      {/* 品牌标识 + 呼吸柔光 */}
      <div className="relative w-[128px] h-[128px] mb-10 flex items-center justify-center">
        <div className="boot-halo" />
        <BrandMark size="xl" className="boot-float relative" />
      </div>

      {/* 清单 */}
      <div className="w-[260px] space-y-3">
        {rows.map((r, i) => {
          const st = stateOf(r);
          return (
            <div
              key={r.key}
              className="boot-item-in flex items-center gap-3"
              style={{ animationDelay: `${i * 0.12}s` }}
            >
              <span className="w-4 h-4 flex items-center justify-center flex-none">
                {st === 'done' ? (
                  <span className="boot-check-pop w-4 h-4 rounded-full bg-tuan-ok flex items-center justify-center">
                    <Check size={11} className="text-white" strokeWidth={3} />
                  </span>
                ) : (
                  <span className="boot-spinner" />
                )}
              </span>
              <span className={`text-[13.5px] ${st === 'done' ? 'text-tuan-text' : 'text-tuan-textSecondary'}`}>
                {r.label}
              </span>
              {r.key === 'engine' && (
                <span
                  className={`ml-auto text-[12px] ${
                    eng.tone === 'ok' ? 'text-tuan-ok' : eng.tone === 'warn' ? 'text-tuan-textSecondary' : 'text-tuan-textSecondary'
                  }`}
                >
                  {eng.text}
                </span>
              )}
            </div>
          );
        })}
      </div>

      {/* 细进度条 */}
      <div className="w-[260px] mt-8">
        <div className="h-[3px] rounded-full bg-tuan-border overflow-hidden">
          <div
            className="h-full rounded-full bg-tuan-accent transition-all duration-300 ease-out"
            style={{ width: `${pct}%` }}
          />
        </div>
        <div className="flex items-center justify-between mt-2">
          <span className="text-[11.5px] text-tuan-textSecondary tabular-nums">{pct}%</span>
          <span className="text-[11.5px] text-tuan-textSecondary">点击任意处跳过</span>
        </div>
      </div>

      {engineStatus?.app_version && (
        <div className="absolute bottom-6 text-[11px] text-tuan-textSecondary">
          Tuan-Chat v{engineStatus.app_version}
        </div>
      )}
    </div>
  );
}
