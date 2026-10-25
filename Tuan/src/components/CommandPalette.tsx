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
  /** 额外搜索关键词（英文 / 斜杠命令 / 别名） */
  keywords?: string;
  /** 标签的拼音首字母串（如「新建对话」→ xjdh）：纯字母查询时做首字母子序列匹配 */
  py?: string;
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

/** 最近使用记录：localStorage key + 上限 5 条 */
const RECENT_KEY = 'tuan.palette.recent';
const RECENT_LIMIT = 5;

function readRecentIds(): string[] {
  try {
    const raw = JSON.parse(localStorage.getItem(RECENT_KEY) || '[]');
    return Array.isArray(raw) ? raw.slice(0, RECENT_LIMIT) : [];
  } catch {
    return [];
  }
}

/** 执行动作时登记：去重置顶、截断 5 条；隐私模式等异常静默忽略 */
function pushRecentId(id: string): void {
  try {
    const next = [id, ...readRecentIds().filter((x) => x !== id)].slice(0, RECENT_LIMIT);
    localStorage.setItem(RECENT_KEY, JSON.stringify(next));
  } catch {
    /* 忽略 */
  }
}

/**
 * 模糊匹配（T-4.3）：
 *  1. 包含匹配：label / hint / keywords / group 任一包含查询串（前缀自然命中）；
 *  2. 拼音首字母子序列匹配：查询为纯小写字母时，依次命中 py 中的字母
 *     （如「xjdh」→ 新建对话），中间允许跳字。
 */
function matches(a: PaletteAction, q: string): boolean {
  const hit = [a.label, a.hint, a.keywords, a.group].some(
    (s) => s && s.toLowerCase().includes(q),
  );
  if (hit) return true;
  if (a.py && /^[a-z]+$/.test(q)) {
    let i = 0;
    const py = a.py.toLowerCase();
    for (const ch of py) {
      if (ch === q[i]) i++;
      if (i === q.length) return true;
    }
  }
  return false;
}

/**
 * Claude Code 桌面标志性的 ⌘K 命令面板：
 * 居中浮层 + 模糊过滤 + 分组 + 键盘导航（↑↓/↵/esc/tab）。
 * 搜索为空时置顶最近 5 条常用命令（T-4.5，localStorage 持久化）。
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

  /** 查询词（去空白） */
  const q = query.trim().toLowerCase();

  /** 查询非空：模糊过滤结果 */
  const filtered = useMemo(() => {
    if (!q) return actions;
    return actions.filter((a) => matches(a, q));
  }, [actions, q]);

  /** 查询为空时的最近使用（按 id 反解动作，被删的动作自动跳过） */
  const recent = useMemo(() => {
    if (q) return [];
    return readRecentIds()
      .map((id) => actions.find((a) => a.id === id))
      .filter((a): a is PaletteAction => !!a);
  }, [actions, q]);

  /** 最终可见列表：空查询时最近使用置顶，其余动作去掉重复 */
  const visible = useMemo(() => {
    if (q) return filtered;
    const recentIds = new Set(recent.map((a) => a.id));
    return [...recent, ...actions.filter((a) => !recentIds.has(a.id))];
  }, [q, filtered, recent, actions]);

  // 过滤结果变化后把高亮收回复用区间，避免越界
  useEffect(() => {
    setActive((n) => Math.min(n, Math.max(0, visible.length - 1)));
  }, [visible.length]);

  // 高亮项滚动进可视区（键盘导航时）
  useEffect(() => {
    const el = listRef.current?.querySelector<HTMLElement>('[data-active="1"]');
    el?.scrollIntoView({ block: 'nearest' });
  }, [active, visible.length]);

  const runAt = (i: number) => {
    const a = visible[i];
    if (!a) return;
    pushRecentId(a.id); // 登记最近使用（T-4.5）
    onClose();
    // 让面板先完成关闭动画再执行动作，避免动作里 setState 与卸载竞争
    requestAnimationFrame(() => a.run());
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown' || (e.key === 'n' && e.ctrlKey)) {
      e.preventDefault();
      setActive((n) => (visible.length ? (n + 1) % visible.length : 0));
    } else if (e.key === 'ArrowUp' || (e.key === 'p' && e.ctrlKey)) {
      e.preventDefault();
      setActive((n) => (visible.length ? (n - 1 + visible.length) % visible.length : 0));
    } else if (e.key === 'Enter') {
      e.preventDefault();
      runAt(active);
    } else if (e.key === 'Escape') {
      e.preventDefault();
      onClose();
    } else if (e.key === 'Tab') {
      // Tab 补全：把高亮动作的名字补进搜索框（区别于当前词时），便于二次筛选
      e.preventDefault();
      const a = visible[active];
      if (a && q && !a.label.toLowerCase().includes(q)) {
        setQuery(a.label);
        setActive(0);
      } else {
        inputRef.current?.focus();
      }
    }
  };

  if (!open) return null;

  // 按 group 保持顺序分块渲染（空查询时「最近使用」天然排在最前）
  const groups: { name: string; items: { action: PaletteAction; index: number }[] }[] = [];
  visible.forEach((a, i) => {
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
          {visible.length === 0 && (
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
          <span className="flex items-center gap-1">
            <kbd className="cc-kbd">tab</kbd>
            补全
          </span>
          <span className="ml-auto hidden sm:inline">Tuan 命令面板</span>
        </div>
      </div>
    </div>
  );
}
