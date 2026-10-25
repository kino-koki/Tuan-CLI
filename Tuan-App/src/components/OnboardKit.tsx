import type { ReactNode } from 'react';
import { Check } from 'lucide-react';

/**
 * 加载 / 安装引导共享套件（BootScreen 与 EngineSetupPage 共用）。
 *
 * 设计语言：Claude 桌面端（claude.ai 桌面应用）——
 * - 底色 `bg-tuan-main`（与主界面同底的暖米纸，不做额外氛围色）；
 * - 卡片 = 白底 + 发丝边 + 16px 圆角 + 极轻投影（.tuan-card，与内部页一致）；
 * - 主按钮 = 陶土橘胶囊（cc-btn-accent），次按钮 = 细边幽灵（cc-btn-ghost）；
 * - 打勾 = 陶土橘实心圆 + 奶白勾，落入时只有 160ms 小缩放淡入（不弹跳）；
 * - 等待态 = 与聊天「思考中」同源的 12 瓣爬动菊花（cc-spinner，见 index.css）；
 * - 进度 = 3px 细轨 + 陶土橘填充 + 等宽数字；
 * - 命令 = 终端深色 chip（与聊天代码块同款 .tuan-codeblock 底色），可复制；
 * - hero 行才用衬线（Georgia，仅问候位，同 ChatView 空态），其余全部无衬线；
 * - 动效全场只有一种：淡入 + 6px 微下沉（onboard-in，220ms）——安静是这种风格的脸；
 * - 安全区：.onboard-shell 四边让出刘海 / Home Indicator；
 * - prefers-reduced-motion 下所有动效降级为直接呈现。
 *
 * 注意：爬动菊花与 ChatView.tsx 内的 Spinner 同源同 CSS 类（cc-spinner /
 * cc-crawler-petal），此处复制一份小尺寸实现，避免引导层反向依赖聊天组件。
 *
 * 兼容性（Android WebView / Chrome 68）：不用 flex gap / inset /
 * color-mix()——间距一律 space-*（margin 实现）。
 */

/** 12 瓣爬动菊花（与聊天思考态同源；size 由外层 .cc-spinner 控制） */
export function CrawlerSpinner({ className = '' }: { className?: string }) {
  const petals = Array.from({ length: 12 }, (_, i) => i);
  return (
    <span className={`cc-spinner ${className}`.trim()} aria-hidden="true">
      <svg viewBox="0 0 20 20" fill="none" aria-hidden="true" focusable="false">
        {petals.map((i) => {
          const rad = (i * 30 * Math.PI) / 180;
          const x1 = 10 + Math.cos(rad) * 6.2;
          const y1 = 10 + Math.sin(rad) * 6.2;
          const x2 = 10 + Math.cos(rad) * 9.2;
          const y2 = 10 + Math.sin(rad) * 9.2;
          return (
            <line
              key={i}
              x1={x1.toFixed(2)}
              y1={y1.toFixed(2)}
              x2={x2.toFixed(2)}
              y2={y2.toFixed(2)}
              className="cc-crawler-petal"
              style={{ animationDelay: `${(-i * 1000) / 12}ms` }}
            />
          );
        })}
      </svg>
    </span>
  );
}

/**
 * 打勾徽标：陶土橘实心圆 + 奶白勾（Claude 桌面端品牌色口径）。
 * 尺寸：sm = 清单行 / 步骤指示位（16px）；lg = 成功态（44px）。
 * 落入时只有克制的小缩放淡入（onboard-check-in），reduced-motion 下直接呈现。
 */
export function OnboardCheck({ size = 'sm' }: { size?: 'sm' | 'lg' }) {
  if (size === 'lg') {
    return (
      <span
        className="onboard-check-in inline-flex h-11 w-11 flex-none items-center justify-center rounded-full bg-tuan-accentSoft"
        role="img"
        aria-label="完成"
      >
        <Check size={22} className="text-tuan-onAccent" strokeWidth={2.5} />
      </span>
    );
  }
  return (
    <span
      className="onboard-check-in inline-flex h-4 w-4 flex-none items-center justify-center rounded-full bg-tuan-accentSoft"
      role="img"
      aria-label="完成"
    >
      <Check size={11} className="text-tuan-onAccent" strokeWidth={3} />
    </span>
  );
}

/**
 * 步骤指示位（安装向导）：26px 细边圆。
 * - 待完成 = 圈内序号（陶土橘只留给"完成"这一刻）；
 * - 进行中 = 圈内爬动菊花（busy）；
 * - 已完成 = 直接换成 OnboardCheck。
 */
export function OnboardStepDot({
  n,
  done,
  busy = false,
}: {
  n: number;
  done: boolean;
  busy?: boolean;
}) {
  if (done) return <OnboardCheck />;
  return (
    <span
      className="inline-flex h-[26px] w-[26px] flex-none items-center justify-center rounded-full border border-tuan-border"
      aria-hidden="true"
    >
      {busy ? (
        <CrawlerSpinner className="!h-[14px] !w-[14px]" />
      ) : (
        <span className="text-[13px] font-medium text-tuan-textSecondary tabular-nums">{n}</span>
      )}
    </span>
  );
}

/** 统一进度条：3px 细轨 + 陶土橘填充 + 等宽百分比（Boot / 向导共用） */
export function OnboardProgress({ pct, label = true }: { pct: number; label?: boolean }) {
  return (
    <div>
      <div className="h-[3px] overflow-hidden rounded-full bg-tuan-border">
        <div
          className="h-full rounded-full bg-tuan-accentSoft transition-all duration-500 ease-out"
          style={{ width: `${pct}%` }}
        />
      </div>
      {label && (
        <div className="mt-2 text-right text-[11.5px] text-tuan-textSecondary tabular-nums">
          {pct}%
        </div>
      )}
    </div>
  );
}

/**
 * 引导层外壳：全屏 + 主界面同底 + 四边安全区。
 * BootScreen（不滚动）与 EngineSetupPage（滚动）都以它为根。
 */
export function OnboardShell({
  children,
  scroll = false,
}: {
  children: ReactNode;
  /** 滚动型（安装向导内容较长，窄屏需要可滚动） */
  scroll?: boolean;
}) {
  return (
    <div
      className={`fixed inset-0 z-[90] bg-tuan-main ${
        scroll ? 'overflow-y-auto custom-scrollbar' : 'overflow-hidden'
      }`}
    >
      <div className="onboard-shell min-h-full flex flex-col">{children}</div>
    </div>
  );
}

/**
 * 可复制命令行：终端深色 chip——与聊天代码块（.tuan-codeblock）同款底色，
 * 让安装向导里的命令和用户在对话里看到的代码是"同一种东西"。
 */
export function OnboardCommand({
  text,
  note,
  onCopy,
  copied,
}: {
  text: string;
  note?: string;
  onCopy: () => void;
  copied: boolean;
}) {
  return (
    <div className="mt-2.5 flex items-stretch space-x-2">
      <code
        className="min-w-0 flex-1 truncate rounded-[10px] bg-tuan-terminalBg px-3 py-2 font-mono text-[12px] text-tuan-terminalText"
        title={text}
      >
        {text}
      </code>
      <button
        onClick={onCopy}
        className="inline-flex w-[34px] flex-none items-center justify-center rounded-[10px] bg-tuan-terminalBg text-tuan-terminalDim transition-colors hover:text-white"
        title={copied ? '已复制' : `复制${note ? ` ${note}` : ''}`}
        aria-label={copied ? '已复制' : '复制'}
      >
        {copied ? <Check size={14} /> : <CopyIcon />}
      </button>
    </div>
  );
}

function CopyIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <rect x="9" y="9" width="12" height="12" rx="2" />
      <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
    </svg>
  );
}
