import { useEffect, useMemo, useRef, useState } from 'react';
import { MoreHorizontal, Settings, MessageSquare, FolderKanban, Package, Wrench, Blocks, Puzzle, BookOpen, BookText, Search, X, Pin, Plus, ChevronUp } from 'lucide-react';

export type PageKey =
  | 'chats' | 'projects' | 'artifacts' | 'skills' | 'mcp' | 'plugins' | 'guide' | 'docs' | 'settings';

interface Props {
  page: PageKey;
  onNavigate: (p: PageKey) => void;
  onNewChat: () => void;
  recent: { id: string; title: string; ts?: number }[];
  activeId?: string;
  onOpenConv: (id: string) => void;
  onRename: (id: string, title: string) => void;
  onDelete: (id: string) => void;
  /** 折叠态（桌面端折叠为图标轨；窄屏折叠为抽屉关闭） */
  collapsed?: boolean;
  /** 是否窄屏（手机 / 窄窗口） */
  isNarrow?: boolean;
}

/** 相对时间显示：今天/昨天/星期X/几月几号 */
function formatTime(ts: number): string {
  const d = new Date(ts);
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const dayStart = new Date(d.getFullYear(), d.getMonth(), d.getDate());
  const diff = Math.floor((today.getTime() - dayStart.getTime()) / 86400000);
  if (diff === 0) {
    return d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
  }
  if (diff === 1) return '昨天';
  if (diff < 7) return ['周日','周一','周二','周三','周四','周五','周六'][d.getDay()];
  return `${d.getMonth() + 1}/${d.getDate()}`;
}

/** 按日期分组对话 */
function groupConversations(recent: { id: string; title: string; ts?: number }[]) {
  const groups: { label: string; items: typeof recent }[] = [];
  const today = new Date();
  today.setHours(0, 0, 0, 0);

  for (const conv of recent) {
    if (!conv.ts) {
      let group = groups.find(g => g.label === '更早');
      if (!group) {
        group = { label: '更早', items: [] };
        groups.push(group);
      }
      group.items.push(conv);
      continue;
    }

    const d = new Date(conv.ts);
    const diff = Math.floor((today.getTime() - new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime()) / 86400000);

    let label = '更早';
    if (diff === 0) label = '今天';
    else if (diff === 1) label = '昨天';
    else if (diff < 7) label = '最近 7 天';
    else label = '更早';

    let group = groups.find(g => g.label === label);
    if (!group) {
      group = { label, items: [] };
      groups.push(group);
    }
    group.items.push(conv);
  }
  return groups;
}

interface MenuItem { key: PageKey; label: string; icon: typeof MessageSquare }
const MENU_GROUPS: { title: string; items: MenuItem[] }[] = [
  {
    title: '对话',
    items: [{ key: 'chats', label: '聊天记录', icon: MessageSquare }],
  },
  {
    title: '资源',
    items: [
      { key: 'projects', label: '项目', icon: FolderKanban },
      { key: 'artifacts', label: '成品', icon: Package },
    ],
  },
  {
    title: '扩展',
    items: [
      { key: 'skills', label: '技能', icon: Wrench },
      { key: 'mcp', label: 'MCP 服务', icon: Blocks },
      { key: 'plugins', label: '插件', icon: Puzzle },
    ],
  },
  {
    title: '帮助与系统',
    items: [
      { key: 'guide', label: '使用教程', icon: BookOpen },
      { key: 'docs', label: '技术文档', icon: BookText },
      { key: 'settings', label: '设置', icon: Settings },
    ],
  },
];

/** 全部导航项（图标轨与内联导航共用） */
const NAV_ITEMS: MenuItem[] = MENU_GROUPS.flatMap((g) => g.items);

export default function Sidebar({
  page,
  onNavigate,
  onNewChat,
  recent,
  activeId,
  onOpenConv,
  onRename,
  onDelete,
  collapsed,
  isNarrow,
}: Props) {
  // 桌面端折叠 = 图标轨；窄屏折叠 = 抽屉关闭（不渲染）。
  const rail = !!collapsed && !isNarrow;

  const [searchQuery, setSearchQuery] = useState('');
  const [pinnedIds, setPinnedIds] = useState<string[]>(() => {
    try {
      return JSON.parse(localStorage.getItem('tuan.pinnedConvs') || '[]');
    } catch {
      return [];
    }
  });
  const searchRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    localStorage.setItem('tuan.pinnedConvs', JSON.stringify(pinnedIds));
  }, [pinnedIds]);

  const togglePin = (id: string) => {
    setPinnedIds((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]
    );
  };

  const sortedRecent = useMemo(() => {
    const pinned = recent.filter((c) => pinnedIds.includes(c.id));
    const unpinned = recent.filter((c) => !pinnedIds.includes(c.id));
    return [...pinned, ...unpinned];
  }, [recent, pinnedIds]);

  const filteredRecent = useMemo(() => {
    if (!searchQuery.trim()) return sortedRecent;
    const q = searchQuery.trim().toLowerCase();
    return sortedRecent.filter((c) => c.title.toLowerCase().includes(q));
  }, [sortedRecent, searchQuery]);

  // Ctrl+F 聚焦搜索框
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.ctrlKey && e.key === 'f') {
        e.preventDefault();
        searchRef.current?.focus();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  // ===== 图标轨（桌面端折叠态）=====
  if (rail) {
    return (
      <aside className="sidebar-rail h-full w-[68px] flex-shrink-0 flex flex-col items-center bg-tuan-sidebar border-r border-tuan-border overflow-hidden py-3">
        <button
          onClick={onNewChat}
          className="w-10 h-10 mb-3 flex items-center justify-center rounded-xl bg-tuan-accent text-white hover:opacity-90 transition-opacity"
          title="新建对话"
        >
          <Plus size={20} />
        </button>
        <nav className="flex-1 flex flex-col items-center gap-1 w-full overflow-y-auto custom-scrollbar px-1">
          {NAV_ITEMS.map(({ key, label, icon: Icon }) => (
            <button
              key={key}
              onClick={() => onNavigate(key)}
              title={label}
              className={`w-11 h-11 flex items-center justify-center rounded-xl transition-colors ${
                page === key ? 'bg-tuan-hover text-tuan-text' : 'text-tuan-textSecondary hover:bg-tuan-hover hover:text-tuan-text'
              }`}
            >
              <Icon size={20} className="dark:invert" />
            </button>
          ))}
        </nav>
        <button
          onClick={() => onNavigate('settings')}
          title="本地用户 · 设置"
          className="w-10 h-10 mt-2 flex items-center justify-center rounded-full bg-tuan-accent text-white text-[15px] font-medium"
        >
          U
        </button>
      </aside>
    );
  }

  // ===== 完整侧栏（含内联导航，替代原"菜单"弹层）=====
  return (
    <aside className="sidebar-fixed h-full w-[260px] flex-shrink-0 flex flex-col bg-tuan-sidebar border-r border-tuan-border overflow-hidden">
      {/* 品牌区 */}
      <div className="flex items-center gap-2.5 px-[18px] pt-[16px] pb-[8px] flex-shrink-0">
        <img src="/icons/star.png" alt="Tuan" className="h-[28px] w-[28px] object-contain" />
        <span className="text-[15px] font-semibold tracking-wide text-[var(--tuan-heading)] select-none">
          Tuan
        </span>
      </div>

      {/* 固定操作：新建对话 */}
      <div className="flex-shrink-0 px-[9px]">
        <button
          onClick={onNewChat}
          className="w-full flex items-center gap-2 rounded-xl px-3 py-[6px] text-[14px] text-tuan-text hover:bg-tuan-hover transition-colors"
          style={{ fontWeight: 400 }}
        >
          <span className="flex items-center justify-center" style={{ width: '20px', height: '20px' }}>
            <img src="/icons/new_chat.png" alt="" className="h-[20px] w-[20px] object-contain dark:invert" />
          </span>
          新建对话
        </button>
      </div>

      {/* 滚动区：搜索 + 最近对话 + 内联导航 */}
      <div className="flex-1 overflow-y-auto sidebar-scroll min-h-0 px-[9px] pt-3 pb-6">
        {/* 搜索框 */}
        <div className="relative mb-2 px-2">
          <div className="flex items-center gap-2 bg-tuan-input border border-tuan-border rounded-xl px-3 py-1.5">
            <Search size={14} className="text-tuan-textSecondary flex-shrink-0" />
            <input
              ref={searchRef}
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="搜索对话"
              className="flex-1 bg-transparent outline-none text-[13px] text-tuan-text placeholder:text-tuan-textSecondary"
            />
            {searchQuery && (
              <button
                onClick={() => setSearchQuery('')}
                className="text-tuan-textSecondary hover:text-tuan-text"
              >
                <X size={13} />
              </button>
            )}
          </div>
        </div>
        <div className="px-3 pb-2 text-[13px] font-medium text-tuan-textSecondary">
          {searchQuery ? '搜索结果' : '最近对话'}
        </div>
        <div className="space-y-px">
          {filteredRecent.length === 0 && (
            <div className="px-3 py-2 text-[13px] text-tuan-textSecondary">
              {searchQuery ? '未找到匹配的对话' : '暂无对话'}
            </div>
          )}
          {!searchQuery && (
            groupConversations(filteredRecent).map((group) => (
              <div key={group.label}>
                <div className="px-3 pt-2 pb-1 text-[11px] font-medium text-tuan-textSecondary">
                  {group.label}
                </div>
                {group.items.map((c) => (
                  <ConvRow
                    key={c.id}
                    conv={c}
                    active={activeId === c.id}
                    pinned={pinnedIds.includes(c.id)}
                    onOpen={() => onOpenConv(c.id)}
                    onTogglePin={() => togglePin(c.id)}
                    onRename={() => {
                      const t = window.prompt('重命名对话', c.title);
                      if (t?.trim()) onRename(c.id, t.trim());
                    }}
                    onDelete={() => onDelete(c.id)}
                  />
                ))}
              </div>
            ))
          )}
          {searchQuery && filteredRecent.map((c) => (
            <ConvRow
              key={c.id}
              conv={c}
              active={activeId === c.id}
              pinned={pinnedIds.includes(c.id)}
              onOpen={() => onOpenConv(c.id)}
              onTogglePin={() => togglePin(c.id)}
              onRename={() => {
                const t = window.prompt('重命名对话', c.title);
                if (t?.trim()) onRename(c.id, t.trim());
              }}
              onDelete={() => onDelete(c.id)}
            />
          ))}
        </div>

        {/* 内联导航分组（替代原"菜单"弹层，更可发现） */}
        <div className="mt-4 pt-3 border-t border-tuan-border/60">
          {MENU_GROUPS.map((g) => (
            <div key={g.title}>
              <div className="px-3 pb-1 text-[11.5px] font-medium text-tuan-textSecondary">{g.title}</div>
              {g.items.map(({ key, label, icon: Icon }) => (
                <button
                  key={key}
                  onClick={() => onNavigate(key)}
                  className={`w-full flex items-center gap-3 px-3 py-2 text-[14px] transition-colors rounded-xl ${
                    page === key ? 'bg-tuan-hover text-tuan-text' : 'text-tuan-text hover:bg-tuan-hover'
                  }`}
                >
                  <Icon size={17} className="flex-shrink-0 dark:invert" />
                  {label}
                </button>
              ))}
            </div>
          ))}
        </div>
      </div>

      {/* 底部用户行 */}
      <div className="border-t border-tuan-border px-3 py-3 flex-shrink-0">
        <button
          onClick={() => onNavigate('settings')}
          className="w-full flex items-center gap-2 rounded-xl p-2 hover:bg-tuan-hover transition-colors cursor-pointer"
        >
          <div className="h-8 w-8 rounded-full bg-tuan-accent text-white flex items-center justify-center text-[15px] font-medium flex-shrink-0">
            U
          </div>
          <div className="flex-1 min-w-0 text-left">
            <div className="text-[15px] font-medium text-tuan-text leading-tight">本地用户</div>
            <div className="text-[13px] text-tuan-textSecondary mt-0.5">本地自托管</div>
          </div>
          <ChevronUp size={16} className="text-tuan-textSecondary" />
        </button>
      </div>
    </aside>
  );
}

/** 单条对话行（含 hover 操作：置顶 / 重命名 / 删除） */
function ConvRow({
  conv,
  active,
  pinned,
  onOpen,
  onTogglePin,
  onRename,
  onDelete,
}: {
  conv: { id: string; title: string; ts?: number };
  active: boolean;
  pinned: boolean;
  onOpen: () => void;
  onTogglePin: () => void;
  onRename: () => void;
  onDelete: () => void;
}) {
  return (
    <div
      onClick={onOpen}
      className={`group relative flex items-center min-h-[32px] rounded-xl px-3 py-1.5 cursor-pointer transition-colors ${
        active ? 'bg-tuan-hover' : 'hover:bg-tuan-hover'
      }`}
    >
      <div className="flex-1 min-w-0 pr-6">
        <div className="text-[13px] text-tuan-text truncate leading-snug">{conv.title}</div>
        {conv.ts && (
          <div className="text-[11px] text-tuan-textSecondary mt-0.5 leading-none">
            {formatTime(conv.ts)}
          </div>
        )}
      </div>
      <div className="conv-actions absolute right-2 top-1/2 -translate-y-1/2 flex gap-1 opacity-0 group-hover:opacity-100">
        <button
          onClick={(e) => {
            e.stopPropagation();
            onTogglePin();
          }}
          className={`p-1 rounded-lg hover:bg-tuan-hover ${
            pinned ? 'text-tuan-accent' : 'text-tuan-textSecondary hover:text-tuan-text'
          }`}
          title={pinned ? '取消置顶' : '置顶对话'}
        >
          <Pin size={14} className={pinned ? 'fill-current' : ''} />
        </button>
        <button
          onClick={(e) => {
            e.stopPropagation();
            onRename();
          }}
          className="p-1 rounded-lg text-tuan-textSecondary hover:text-tuan-text hover:bg-tuan-hover"
          title="重命名"
        >
          <MoreHorizontal size={15} />
        </button>
        <button
          onClick={(e) => {
            e.stopPropagation();
            onDelete();
          }}
          className="p-1 rounded-lg text-[var(--tuan-danger)] hover:bg-[var(--tuan-danger-bg)]"
          title="删除"
        >
          <TrashIcon />
        </button>
      </div>
    </div>
  );
}

function TrashIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 6h18M8 6V4a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v2m2 0v14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2V6" />
    </svg>
  );
}
