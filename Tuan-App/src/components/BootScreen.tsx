import { useEffect, useRef, useState } from 'react';
import BrandMark from './BrandMark';
import { BrailleSpinner, OnboardCheck, OnboardProgress, OnboardShell, TermWindow } from './OnboardKit';

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

/** 底部状态栏的引擎口径（CodeX status bar 的英文等宽风格）。 */
function engineFoot(tone: 'ok' | 'warn' | 'wait'): string {
  if (tone === 'ok') return 'engine: ready';
  if (tone === 'warn') return 'engine: degraded';
  return 'engine: checking';
}

/**
 * 启动加载序列（CodeX 式 TUI 启动终端）。
 *
 * 结构照抄 OpenAI Codex 的启动界面：一扇终端窗口（三点窗饰 + 等宽
 * 标题栏），窗内是 `>_` 标识行 + meta 行（engine / mode）、逐项点亮
 * 的启动清单（左 braille 旋转 → 陶土橘打勾，右为实时状态）、3px 细
 * 进度条；窗口底部是 CodeX TUI 同位的单行状态栏。
 *
 * 动效（豆包 × CodeX，应用户要求完整保留）：品牌标识呼吸柔光
 * （boot-halo）+ 轻浮动（boot-float）；清单逐行落入（boot-item-in）、
 * 打勾弹跳（boot-check-pop）、等待态 braille 旋转符。
 *
 * 诚实：第三行「本地引擎」反映真实 check_engine 结果——就绪 / 未启用
 * （降级）/ 检测中，不表演假进度；退出：全部就绪后 0.4s 自动淡出，
 * 任意点击或按键立即跳过；prefers-reduced-motion 下直接放行。
 */
export default function BootScreen({ engineStatus, onDone }: Props) {
  const [elapsed, setElapsed] = useState(0);
  const [leaving, setLeaving] = useState(false);
  const doneRef = useRef(false);

  const finish = () => {
    if (doneRef.current) return;
    doneRef.current = true;
    setLeaving(true);
    window.setTimeout(onDone, 350);
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
  const appVersion = engineStatus?.app_version;
  const engineVersion = engineStatus?.engine_version;

  return (
    <div
      className={`boot-screen fixed inset-0 z-[100] flex flex-col items-center justify-center bg-tuan-main select-none ${leaving ? 'boot-screen-out' : ''}`}
      onClick={finish}
      role="status"
      aria-label="正在启动"
    >
      <div className="onboard-shell flex flex-col items-center justify-center">
        {/* 品牌标识 + 呼吸柔光 + 轻浮动（豆包式温暖感） */}
        <div className="boot-item-in relative mb-10 flex h-[128px] w-[128px] items-center justify-center">
          <div className="boot-halo" />
          <BrandMark size="xl" className="boot-float relative" />
        </div>

        {/* 启动终端（CodeX 式 TUI 窗口） */}
        <TermWindow
          className="boot-item-in w-[440px] max-w-full"
          title="tuan-chat — bootstrap"
          right={appVersion ? `v${appVersion}` : undefined}
          footer={
            <>
              <span>{engineFoot(eng.tone)}</span>
              <span>{pct}% · click to skip</span>
            </>
          }
        >
          {/* `>_` 标识行 + meta 行（CodeX TUI header block） */}
          <div className="boot-item-in flex items-center gap-2" style={{ animationDelay: '0.1s' }}>
            <span className="term-prompt">&gt;_</span>
            <span className="tuan-mono text-[13px] font-medium text-tuan-text">青小团 Tuan-Chat</span>
          </div>
          <div className="tuan-mono term-meta boot-item-in" style={{ animationDelay: '0.15s' }}>
            <span className="term-meta-key">engine:</span> tuan-cli {engineVersion ? `v${engineVersion}` : 'v0.3.1'} · 58 providers
          </div>
          <div className="tuan-mono term-meta boot-item-in" style={{ animationDelay: '0.19s' }}>
            <span className="term-meta-key">mode:</span> local-first · sandboxed
          </div>

          {/* 启动清单（CodeX transcript 行：状态符 · 标签 · 右状态） */}
          <div className="mt-4 space-y-2">
            {rows.map((r, i) => {
              const st = stateOf(r);
              return (
                <div
                  key={r.key}
                  className="boot-item-in flex h-6 items-center"
                  style={{ animationDelay: `${0.23 + i * 0.12}s` }}
                >
                  <span className="flex h-4 w-4 flex-none items-center justify-center">
                    {st === 'done' ? (
                      <OnboardCheck />
                    ) : (
                      <BrailleSpinner className="text-tuan-accentSoft" />
                    )}
                  </span>
                  <span
                    className={`ml-2.5 text-[13px] transition-colors ${
                      st === 'done' ? 'text-tuan-text' : 'text-tuan-textSecondary'
                    }`}
                  >
                    {r.label}
                  </span>
                  {r.key === 'engine' && (
                    <span
                      className={`tuan-mono ml-auto text-[11.5px] ${
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

          {/* 细进度条 */}
          <div className="mt-4">
            <OnboardProgress pct={pct} label={false} />
          </div>
        </TermWindow>

        <div className="boot-item-in tuan-mono mt-5 text-[11px] text-tuan-textSecondary" style={{ animationDelay: '0.7s' }}>
          {appVersion ? `Tuan-Chat v${appVersion} · ` : ''}Model + Harness = Agent
        </div>
      </div>
    </div>
  );
}
