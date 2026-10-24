import { PanelLeft, Menu } from 'lucide-react';

interface Props {
  onToggleSidebar: () => void;
}

/** 可拖拽的自定义标题栏（与旧版一致的细条 + 左侧控制区）。 */
export default function TitleBar({ onToggleSidebar }: Props) {
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
          title="折叠 / 展开侧栏"
        >
          <PanelLeft size={20} />
        </button>
      </div>
      <div className="flex-1 text-center md:hidden text-[15px] font-medium text-tuan-textSecondary pr-10">
        Tuan-Chat
      </div>
    </div>
  );
}
