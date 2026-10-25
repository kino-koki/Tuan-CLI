import { PanelLeft, Menu, Search, Wrench } from 'lucide-react';

interface Props {
  onToggleSidebar: () => void;
  /** 打开 ⌘K 命令面板 */
  onOpenPalette: () => void;
  /** 桌面端本地引擎缺失：显示可点的状态灯，引导去装引擎 */
  engineMissing?: boolean;
  onOpenSetup?: () => void;
}

/** 可拖拽的自定义标题栏（细条 + 左侧控制区 + 右侧 ⌘K 指令入口，贴近 Claude Code 桌面）。 */
export default function TitleBar({ onToggleSidebar, onOpenPalette, engineMissing, onOpenSetup }: Props) {
  return (
    <div
      className="h-[44px] flex items-center select-none bg-tuan-bg border-b border-tuan-border z-40 flex-shrink-0"
      style={{ WebkitAppRegion: 'drag' } as React.CSSProperties}
    >
      <div className="h-full flex items-center gap-0.5 px-1" style={{ WebkitAppRegion: 'no-drag' } as React.CSSProperties}>
        <button
          onClick={onToggleSidebar}
          className="p-2 hover:bg-black/5 dark:hover:bg-white/5 rounded-lg text-tuan-textSecondary hover:text-tuan-text transition-colors"
          title="菜单"
        >
          <Menu size={18} className="opacity-80" />
        </button>
        <button
          onClick={onToggleSidebar}
          className="p-1.5 hidden md:flex hover:bg-black/5 dark:hover:bg-white/5 rounded-lg text-tuan-textSecondary hover:text-tuan-text transition-colors"
          title="折叠 / 展开侧栏（⌘B）"
        >
          <PanelLeft size={20} />
        </button>
      </div>
      <div className="flex-1 text-center md:hidden text-[15px] font-medium text-tuan-textSecondary pr-10">
        Tuan
      </div>
      {/* 引擎状态灯：本地引擎缺失时可点击，打开安装向导 */}
      {engineMissing && onOpenSetup && (
        <button
          onClick={onOpenSetup}
          className="flex items-center gap-1.5 h-[26px] px-2.5 mr-1 rounded-full border border-amber-300 dark:border-amber-700 bg-amber-50 dark:bg-amber-950/40 text-[11.5px] text-amber-700 dark:text-amber-400 hover:bg-amber-100 dark:hover:bg-amber-900/40 transition-colors"
          title="本地引擎未就绪 — 点击打开安装向导"
          style={{ WebkitAppRegion: 'no-drag' } as React.CSSProperties}
        >
          <Wrench size={12} />
          <span className="hidden sm:inline">引擎未就绪</span>
        </button>
      )}
      {/* ⌘K 命令面板入口：桌面端显示为搜索条（Claude Code 桌面风格），窄屏退化为图标按钮 */}
      <div className="pr-2" style={{ WebkitAppRegion: 'no-drag' } as React.CSSProperties}>
        <button
          onClick={onOpenPalette}
          className="hidden md:flex items-center gap-2 h-[28px] pl-2.5 pr-2 rounded-lg border border-tuan-border bg-tuan-input text-[12px] text-tuan-textSecondary hover:text-tuan-text transition-colors"
          title="命令面板（⌘K）"
        >
          <Search size={13} />
          <span>搜索或输入指令</span>
          <kbd className="cc-kbd">⌘K</kbd>
        </button>
        <button
          onClick={onOpenPalette}
          className="md:hidden p-2 rounded-lg text-tuan-textSecondary hover:text-tuan-text hover:bg-black/5 dark:hover:bg-white/5 transition-colors"
          title="命令面板"
        >
          <Search size={17} />
        </button>
      </div>
    </div>
  );
}
