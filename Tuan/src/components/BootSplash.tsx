import BrandMark from './BrandMark';
import {
  BrailleSpinner,
  OnboardCheck,
  OnboardProgress,
  OnboardShell,
} from './OnboardKit';

/**
 * 冷启动闪屏（T-1.1 / T-1.3）。
 *
 * 流程：应用启动 → 本屏（Logo 呼吸光晕 + 版本行 + 引擎分阶段进度）→ 主界面。
 * 最小展示 1.5 秒由 App.tsx 门控保证，本组件只负责展示：
 *  - 标识位：菊花 Logo + 呼吸柔光（与 EngineSetupPage 同一枚 BrandMark）；
 *  - 版本行：shell / engine 真实版本号（自检未返回时显示「检查中…」）；
 *  - 分阶段清单：初始化 → 连接引擎 → 就绪（事件契约 'engine-stage'，
 *    由 Rust 引擎分片发射 {stage:'init'|'connect'|'ready'}；前端只消费，
 *    事件缺席时由 App.tsx 用 check_engine 结果兜底推进）；
 *  - 进度条：三阶段映射 25% / 60% / 100%。
 */

/** 引擎启动阶段（与 engine_chat.rs 的 'engine-stage' 事件 payload.stage 对齐） */
export type BootStage = 'init' | 'connect' | 'ready';

interface Props {
  /** 当前阶段（App 监听事件 + 自检结果兜底后传入） */
  stage: BootStage;
  /** 应用版本号（check_engine 返回，可缺） */
  appVersion?: string;
  /** 引擎版本号（check_engine 返回，可缺） */
  engineVersion?: string;
}

/** 阶段清单行（顺序即阶段推进顺序） */
const STAGE_ROWS: { key: BootStage; label: string }[] = [
  { key: 'init', label: '初始化应用' },
  { key: 'connect', label: '连接本地引擎' },
  { key: 'ready', label: '就绪，即将进入' },
];

/** 阶段 → 进度条百分比（预留余量，避免瞬时满屏） */
function stagePct(stage: BootStage): number {
  return stage === 'init' ? 25 : stage === 'connect' ? 60 : 100;
}

export default function BootSplash({ stage, appVersion, engineVersion }: Props) {
  const currentIdx = STAGE_ROWS.findIndex((r) => r.key === stage);

  return (
    <OnboardShell>
      <div className="flex flex-1 flex-col items-center justify-center px-6">
        {/* 标识位：呼吸柔光 + 浮动菊花（复用启动序列动效 vocab） */}
        <div className="boot-item-in relative mb-8 flex h-[112px] w-[112px] items-center justify-center">
          <div className="boot-halo" />
          <BrandMark size="lg" className="boot-float relative" />
        </div>

        {/* 应用名 */}
        <div className="boot-item-in text-[16px] font-semibold text-tuan-text" style={{ animationDelay: '0.08s' }}>
          青小团 Tuan
        </div>

        {/* 版本行：真实自检值，未返回时如实显示「检查中…」 */}
        <div
          className="boot-item-in tuan-mono mt-2 text-[12px] text-tuan-textSecondary"
          style={{ animationDelay: '0.14s' }}
        >
          <span className="term-meta-key">shell:</span>{' '}
          {appVersion ? `v${appVersion}` : 'v…'} ·{' '}
          <span className="term-meta-key">engine:</span>{' '}
          {engineVersion ? `v${engineVersion}` : '检查中…'}
        </div>

        {/* 分阶段清单：已完成打勾 / 当前 braille 旋转 / 未到达 dim */}
        <div className="boot-item-in mt-10 w-[320px] max-w-full space-y-2.5" style={{ animationDelay: '0.2s' }}>
          {STAGE_ROWS.map((row, i) => {
            const done = i < currentIdx || stage === 'ready';
            const active = i === currentIdx && stage !== 'ready';
            return (
              <div key={row.key} className="flex items-center gap-2.5 text-[13px]">
                <span className="flex h-4 w-4 flex-none items-center justify-center">
                  {done ? (
                    <OnboardCheck />
                  ) : active ? (
                    <BrailleSpinner className="text-tuan-accentSoft" />
                  ) : (
                    <span className="tuan-mono text-[12px] text-tuan-textSecondary/50">·</span>
                  )}
                </span>
                <span className={done ? 'text-tuan-text' : active ? 'text-tuan-text' : 'text-tuan-textSecondary'}>
                  {row.label}
                </span>
              </div>
            );
          })}
        </div>

        {/* 进度条 */}
        <div className="boot-item-in mt-6 w-[320px] max-w-full" style={{ animationDelay: '0.26s' }}>
          <OnboardProgress pct={stagePct(stage)} label={false} />
        </div>
      </div>
    </OnboardShell>
  );
}
