import { useEffect, useMemo, useRef, useState } from 'react';
import { Search, CornerDownLeft } from 'lucide-react';

export interface PaletteAction {
  id: string;
  /** 展示名（参与过滤） */
  label: string;
  /** 分组名（同组连续渲染） */
  group: string;
  /** 右侧补充说明（不参与过滤的展示文本） */
  hint?: string;
  /** 快捷键徽标文本，如 ⌘N */
  shortcut?: string;
  /** 额外搜索关键词（拼音/别名/英文） */
  keywords?: string;
  /** 左侧图标 */
  icon?: React.ReactNode;
  /** 危险/高风险项（如无界模式）用危险色描边 */
  danger?: boolean;
  run: () => void;
}

interface Props {
  open: boolean;
  onClose: () => void;
  actions: PaletteAction[];
}

/**
 * Claude Code 桌面标志性的 ⌘K 命令面板：
 * 居中浮层 + 模糊过滤 + 分组 + 键盘导航（↑↓/↵/esc）。
 * 暖色 Claude 风格：米/炭底、圆角浮层、kbd 徽标、底部提示行。
 */
export default function CommandPalette({ open, onClose, actions }: Props) {
  const [query, setQuery] = useState('');
  const [active, setActive] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  // 打开时重置并聚焦；关闭时清空（避免下次打开闪现旧查询）
  useEffect(() => {
    if (open) {
      setQuery('');
      setActive(0);
      // 等浮层挂载完再聚焦，避免部分 WebView 下抢不到焦点
      const t = setTimeout(() => inputRef.current?.focus(), 30);
      return () => clearTimeout(t);
    }
  }, [open]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return actions;
    return actions.filter((a) =>
      [a.label, a.hint, a.keywords, a.group].some((s) => s && s.toLowerCase().includes(q)),
    );
  }, [actions, query]);

  // 过滤结果变化后把高亮收回复用区间，避免越界
  useEffect(() => {
    setActive((n) => Math.min(n, Math.max(0, filtered.length - 1)));
  }, [filtered.length]);

  // 高亮项滚动进可视区（键盘导航时）
  useEffect(() => {
    const el = listRef.current?.querySelector<HTMLElement>('[data-active="1"]');
    el?.scrollIntoView({ block: 'nearest' });
  }, [active, filtered.length]);

  const runAt = (i: number) => {
    const a = filtered[i];
    if (!a) return;
    onClose();
    // 让面板先完成关闭动画再执行动作，避免动作里 setState 与卸载竞争
    requestAnimationFrame(() => a.run());
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown' || (e.key === 'n' && e.ctrlKey)) {
      e.preventDefault();
      setActive((n) => (filtered.length ? (n + 1) % filtered.length : 0));
    } else if (e.key === 'ArrowUp' || (e.key === 'p' && e.ctrlKey)) {
      e.preventDefault();
      setActive((n) => (filtered.length ? (n - 1 + filtered.length) % filtered.length : 0));
    } else if (e.key === 'Enter') {
      e.preventDefault();
      runAt(active);
    } else if (e.key === 'Escape') {
      e.preventDefault();
      onClose();
    } else if (e.key === 'Tab') {
      // 简易焦点陷阱：Tab 在面板内循环，不逃到背后界面
      e.preventDefault();
      inputRef.current?.focus();
    }
  };

  if (!open) return null;

  // 按 group 保持顺序分块渲染（过滤后同组依然相邻）
  const groups: { name: string; items: { action: PaletteAction; index: number }[] }[] = [];
  filtered.forEach((a, i) => {
    let g = groups.find((x) => x.name === a.group);
    if (!g) {
      g = { name: a.group, items: [] };
      groups.push(g);
    }
    g.items.push({ action: a, index: i });
  });

  return (
    <div
      className="cc-palette-overlay fixed inset-0 z-50 flex items-start justify-center bg-black/40 px-4 pt-[12vh]"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        role="dialog"
        aria-label="命令面板"
        className="cc-palette-in w-full max-w-[560px] overflow-hidden rounded-2xl border border-tuan-border bg-tuan-bg shadow-[var(--shadow-pop)]"
        onKeyDown={onKeyDown}
      >
        {/* 搜索行 */}
        <div className="flex items-center gap-2.5 border-b border-tuan-border px-4">
          <Search size={16} className="flex-none text-tuan-textSecondary" />
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setActive(0);
            }}
            placeholder="输入指令或搜索…"
            className="h-12 flex-1 bg-transparent text-[14.5px] text-tuan-text outline-none placeholder:text-tuan-textSecondary"
          />
          <kbd className="cc-kbd">esc</kbd>
        </div>

        {/* 结果列表 */}
        <div ref={listRef} className="max-h-[min(360px,50vh)] overflow-y-auto custom-scrollbar p-2">
          {filtered.length === 0 && (
            <div className="px-3 py-8 text-center text-[13px] text-tuan-textSecondary">
              没有匹配的指令
            </div>
          )}
          {groups.map((g) => (
            <div key={g.name} className="mb-1 last:mb-0">
              <div className="px-3 pb-1 pt-2 text-[11px] font-medium text-tuan-textSecondary">
                {g.name}
              </div>
              {g.items.map(({ action: a, index }) => (
                <button
                  key={a.id}
                  data-active={active === index ? '1' : '0'}
                  onMouseMove={() => setActive(index)}
                  onClick={() => runAt(index)}
                  className={`mx-1 flex w-[calc(100%-8px)] items-center gap-2.5 rounded-xl px-3 py-2 text-left transition-colors ${
                    active === index ? 'bg-tuan-hover' : ''
                  } ${a.danger ? 'border border-[var(--tuan-danger)]/40' : 'border border-transparent'}`}
                >
                  {a.icon ? (
                    <span className="flex-none text-tuan-textSecondary">{a.icon}</span>
                  ) : null}
                  <span className="flex-1 truncate text-[14px] text-tuan-text">{a.label}</span>
                  {a.hint && (
                    <span className="flex-none truncate max-w-[40%] text-[12px] text-tuan-textSecondary">
                      {a.hint}
                    </span>
                  )}
                  {a.shortcut && <kbd className="cc-kbd flex-none">{a.shortcut}</kbd>}
                </button>
              ))}
            </div>
          ))}
        </div>

        {/* 底部提示行 */}
        <div className="flex h-8 items-center gap-3 border-t border-tuan-border px-4 text-[11px] text-tuan-textSecondary">
          <span className="flex items-center gap-1">
            <kbd className="cc-kbd">↑</kbd>
            <kbd className="cc-kbd">↓</kbd>
            选择
          </span>
          <span className="flex items-center gap-1">
            <kbd className="cc-kbd">
              <CornerDownLeft size={10} />
            </kbd>
            执行
          </span>
          <span className="ml-auto hidden sm:inline">Tuan-Chat 命令面板</span>
        </div>
      </div>
    </div>
  );
}
