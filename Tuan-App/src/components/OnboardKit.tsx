import { useEffect, useState, type ReactNode } from 'react';
import { Check } from 'lucide-react';

/**
 * 加载 / 安装引导共享套件（BootScreen 与 EngineSetupPage 共用）。
 *
 * 设计语言：OpenAI Codex 的安装 / 加载界面（2026-10-25 起照抄，只改
 * 颜色与图标）——
 * - 终端窗口（term-window）：三点窗饰 + 等宽标题栏 + 底部单行状态栏；
 * - `>_` 标识行 + meta 行（key: value，等宽）；
 * - 清单行：左状态符（braille 旋转 / 打勾）· 标签 · 右状态；
 * - 命令 = `$` 前缀终端 chip（与聊天代码块 .tuan-codeblock 同款底色），可复制；
 * - 完成标记 = 审批式 `[ ]/[x]`（Codex approval prompt 的口径）；
 * - 底色 `bg-tuan-main`（与主界面同底的暖米纸）；主按钮 = 陶土橘胶囊
 *   （cc-btn-accent），次按钮 = 细边幽灵（cc-btn-ghost）；
 * - 动效 vocab（豆包 × CodeX，应用户要求保留）：呼吸光晕（boot-halo）/
 *   标识浮动（boot-float）/ 逐行落入（boot-item-in）/ 弹跳打勾
 *   （boot-check-pop）/ 细旋转环（boot-spinner）/ 卡片交错落入
 *   （onboard-card-in）/ 成功柔光（onboard-success-glow）；
 * - 安全区：.onboard-shell 四边让出刘海 / Home Indicator；
 * - prefers-reduced-motion 下所有动效降级为直接呈现。
 *
 * 兼容性：桌面端优先（Android 端不需要），term-* 可用 flex gap 等现代 CSS；
 * 间距在 TSX 内仍以 space-*（margin）书写，与全库一致。
 */

/** CodeX TUI 的 braille 旋转符：10 帧 80ms 一轮；reduced-motion 下静止为省略号 */
const BRAILLE_FRAMES = ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏'];

export function BrailleSpinner({ className = '' }: { className?: string }) {
  const reduced =
    typeof window !== 'undefined' &&
    !!window.matchMedia &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const [frame, setFrame] = useState(0);
  useEffect(() => {
    if (reduced) return;
    const timer = window.setInterval(() => setFrame((v) => (v + 1) % BRAILLE_FRAMES.length), 80);
    return () => window.clearInterval(timer);
  }, [reduced]);
  return (
    <span
      className={`tuan-mono inline-block h-4 w-[14px] flex-none text-center leading-4 ${className}`.trim()}
      aria-hidden="true"
    >
      {reduced ? '…' : BRAILLE_FRAMES[frame]}
    </span>
  );
}

/**
 * 打勾徽标：陶土橘实心圆 + 奶白勾（Claude 桌面端品牌色口径）。
 * 尺寸：sm = 清单行 / 步骤指示位（16px）；lg = 成功态（44px）。
 * 落入时弹跳落入（boot-check-pop：scale 0 → 1.25 → 1），reduced-motion 下直接呈现。
 */
export function OnboardCheck({ size = 'sm' }: { size?: 'sm' | 'lg' }) {
  if (size === 'lg') {
    return (
      <span
        className="boot-check-pop inline-flex h-11 w-11 flex-none items-center justify-center rounded-full bg-tuan-accentSoft"
        role="img"
        aria-label="完成"
      >
        <Check size={22} className="text-tuan-onAccent" strokeWidth={2.5} />
      </span>
    );
  }
  return (
    <span
      className="boot-check-pop inline-flex h-4 w-4 flex-none items-center justify-center rounded-full bg-tuan-accentSoft"
      role="img"
      aria-label="完成"
    >
      <Check size={11} className="text-tuan-onAccent" strokeWidth={3} />
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
 * CodeX 式终端窗口：三点窗饰 + 等宽标题栏 + 可选底部状态栏。
 * BootScreen 与 EngineSetupPage 的一切内容都装进这扇"终端"里——
 * 这是引导层照抄 Codex 的结构主体，颜色 / 图标随 Tuan 品牌。
 */
export function TermWindow({
  title,
  right,
  footer,
  children,
  className = '',
}: {
  title: string;
  /** 标题栏右侧的等宽小字（通常是真实版本号） */
  right?: string;
  /** 底部单行状态栏（CodeX TUI status bar 的同位） */
  footer?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={`term-window ${className}`.trim()}>
      <div className="term-window-bar">
        <span className="term-dot bg-tuan-accentSoft" />
        <span className="term-dot term-dot-dim" />
        <span className="term-dot term-dot-dim" />
        <span className="tuan-mono ml-2.5 min-w-0 flex-1 truncate text-[12px] text-tuan-textSecondary">
          {title}
        </span>
        {right && <span className="tuan-mono flex-none text-[11.5px] text-tuan-textSecondary">{right}</span>}
      </div>
      <div className="term-window-body">{children}</div>
      {footer && <div className="term-window-foot">{footer}</div>}
    </div>
  );
}

/**
 * 可复制命令行：`$` 前缀 + 终端深色 chip——与聊天代码块
 * （.tuan-codeblock）同款底色，让安装向导里的命令和用户在对话里
 * 看到的代码是"同一种东西"。`$` 用暗一级的前景色（Codex 文档
 * 安装代码块的口径）。
 */
export function TermCommand({
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
        className="tuan-mono min-w-0 flex-1 truncate rounded-[8px] border border-tuan-border bg-tuan-terminalBg px-2.5 py-1.5 text-[12px] text-tuan-terminalText"
        title={text}
      >
        <span className="text-tuan-terminalDim">$ </span>
        {text}
      </code>
      <button
        onClick={onCopy}
        className="inline-flex w-[34px] flex-none items-center justify-center rounded-[8px] border border-tuan-border bg-tuan-terminalBg text-tuan-terminalDim transition-colors hover:text-white"
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
