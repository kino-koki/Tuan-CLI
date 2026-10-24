import { useEffect, useMemo, useRef, useState } from 'react';
import { ChevronDown, ChevronUp, MoreHorizontal, Settings, Menu, MessageSquare, FolderKanban, Package, Wrench, Blocks, Puzzle, BookOpen, Search, X, Pin } from 'lucide-react';

export type PageKey =
  | 'chats' | 'projects' | 'artifacts' | 'skills' | 'mcp' | 'plugins' | 'guide' | 'settings';

interface Props {
  page: PageKey;
  onNavigate: (p: PageKey) => void;
  onNewChat: () => void;
  recent: { id: string; title: string; ts?: number }[];
  activeId?: string;
  onOpenConv: (id: string) => void;
  onRename: (id: string, title: string) => void;
  onDelete: (id: string) => void;
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
      // 没有时间戳的对话放到"更早"组
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
      { key: 'settings', label: '设置', icon: Settings },
    ],
  },
];

export default function Sidebar({
  page,
  onNavigate,
  onNewChat,
  recent,
  activeId,
  onOpenConv,
  onRename,
  onDelete,
}: Props) {
  const [menuOpen, setMenuOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [pinnedIds, setPinnedIds] = useState<string[]>(() => {
    try {
      return JSON.parse(localStorage.getItem('tuan.pinnedConvs') || '[]');
    } catch {
      return [];
    }
  });
  const menuRef = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);

  // 持久化置顶状态
  useEffect(() => {
    localStorage.setItem('tuan.pinnedConvs', JSON.stringify(pinnedIds));
  }, [pinnedIds]);

  const togglePin = (id: string) => {
    setPinnedIds((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]
    );
  };

  // 置顶对话排序：置顶在前，其余按时间
  const sortedRecent = useMemo(() => {
    const pinned = recent.filter((c) => pinnedIds.includes(c.id));
    const unpinned = recent.filter((c) => !pinnedIds.includes(c.id));
    return [...pinned, ...unpinned];
  }, [recent, pinnedIds]);

  // 搜索过滤对话
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

  // 点击菜单外区域自动收起（二级菜单完善：不残留打开态）
  useEffect(() => {
    if (!menuOpen) return;
    const onDoc = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setMenuOpen(false);
    };
    document.addEventListener('mousedown', onDoc);
    return () => document.removeEventListener('mousedown', onDoc);
  }, [menuOpen]);

  const go = (p: PageKey) => {
    onNavigate(p);
    setMenuOpen(false);
  };

  return (
    <aside className="sidebar-fixed h-full w-[260px] flex-shrink-0 flex flex-col bg-tuan-sidebar border-r border-tuan-border overflow-hidden">
      {/* 品牌区 */}
      <div className="flex items-center gap-2.5 px-[18px] pt-[16px] pb-[8px]">
        <img src="/icons/star.png" alt="Tuan-Chat" className="h-[28px] w-[28px] object-contain" />
        <span className="text-[15px] font-semibold tracking-wide text-[var(--tuan-heading)] select-none">
          Tuan-Chat
        </span>
      </div>

      {/* 固定操作：新建对话 + 菜单 */}
      <div className="flex-shrink-0 px-[9px] space-y-px">
        <button
          onClick={onNewChat}
          className="w-full flex items-center gap-2 rounded-xl px-0 py-[6px] text-[14px] text-tuan-text hover:bg-tuan-hover transition-colors"
          style={{ columnGap: '8px', fontWeight: 400 }}
        >
          <span className="flex items-center justify-center" style={{ width: '20px', height: '20px' }}>
            <img src="/icons/new_chat.png" alt="" className="h-[20px] w-[20px] object-contain dark:invert" />
          </span>
          新建对话
        </button>
        <div className="relative" ref={menuRef}>
          <button
            onClick={() => setMenuOpen((v) => !v)}
            className="w-full flex items-center gap-2 rounded-xl px-0 py-[6px] text-[14px] text-tuan-text hover:bg-tuan-hover transition-colors"
            style={{ columnGap: '8px', fontWeight: 400 }}
          >
            <span className="flex items-center justify-center" style={{ width: '20px', height: '20px' }}>
              <Menu size={18} className="dark:invert" />
            </span>
            菜单
            <ChevronDown
              size={14}
              className={`ml-auto text-tuan-textSecondary transition-transform ${menuOpen ? 'rotate-180' : ''}`}
            />
          </button>
          {menuOpen && (
            <div className="menu-pop absolute left-0 top-full mt-1.5 w-[210px] bg-tuan-input border border-tuan-border rounded-2xl shadow-[var(--shadow-pop)] py-1.5 z-50 max-h-[70vh] overflow-y-auto custom-scrollbar">
              {MENU_GROUPS.map((g, gi) => (
                <div key={g.title}>
                  {gi > 0 && <div className="mx-3 my-1 border-t border-tuan-border/60" />}
                  <div className="px-3 pt-1.5 pb-0.5 text-[11.5px] font-medium text-tuan-textSecondary">{g.title}</div>
                  {g.items.map(({ key, label, icon: Icon }) => (
                    <button
                      key={key}
                      onClick={() => go(key)}
                      className={`w-full flex items-center gap-3 px-3 py-2 text-[14px] transition-colors rounded-xl mx-0 ${
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
          )}
        </div>
      </div>

      {/* 最近对话 */}
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
                  <div
                    key={c.id}
                    onClick={() => onOpenConv(c.id)}
                    className={`group relative flex items-center min-h-[32px] rounded-xl px-3 py-1.5 cursor-pointer transition-colors ${
                      activeId === c.id ? 'bg-tuan-hover' : 'hover:bg-tuan-hover'
                    }`}
                  >
                    <div className="flex-1 min-w-0 pr-6">
                      <div className="text-[13px] text-tuan-text truncate leading-snug">{c.title}</div>
                      {c.ts && (
                        <div className="text-[11px] text-tuan-textSecondary mt-0.5 leading-none">
                          {formatTime(c.ts)}
                        </div>
                      )}
                    </div>
                    <div className="conv-actions absolute right-2 top-1/2 -translate-y-1/2 flex gap-1 opacity-0 group-hover:opacity-100">
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          togglePin(c.id);
                        }}
                        className={`p-1 rounded-lg hover:bg-tuan-hover ${
                          pinnedIds.includes(c.id)
                            ? 'text-tuan-accent'
                            : 'text-tuan-textSecondary hover:text-tuan-text'
                        }`}
                        title={pinnedIds.includes(c.id) ? '取消置顶' : '置顶对话'}
                      >
                        <Pin size={14} className={pinnedIds.includes(c.id) ? 'fill-current' : ''} />
                      </button>
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          const t = window.prompt('重命名对话', c.title);
                          if (t?.trim()) onRename(c.id, t.trim());
                        }}
                        className="p-1 rounded-lg text-tuan-textSecondary hover:text-tuan-text hover:bg-tuan-hover"
                        title="重命名"
                      >
                        <MoreHorizontal size={15} />
                      </button>
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          onDelete(c.id);
                        }}
                        className="p-1 rounded-lg text-[var(--tuan-danger)] hover:bg-[var(--tuan-danger-bg)]"
                        title="删除"
                      >
                        <TrashIcon />
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            ))
          )}
          {searchQuery && filteredRecent.map((c) => (
            <div
              key={c.id}
              onClick={() => onOpenConv(c.id)}
              className={`group relative flex items-center min-h-[32px] rounded-xl px-3 py-1.5 cursor-pointer transition-colors ${
                activeId === c.id ? 'bg-tuan-hover' : 'hover:bg-tuan-hover'
              }`}
            >
              <div className="flex-1 min-w-0 pr-6">
                <div className="text-[13px] text-tuan-text truncate leading-snug">{c.title}</div>
                {c.ts && (
                  <div className="text-[11px] text-tuan-textSecondary mt-0.5 leading-none">
                    {formatTime(c.ts)}
                  </div>
                )}
              </div>
              <div className="conv-actions absolute right-2 top-1/2 -translate-y-1/2 flex gap-1 opacity-0 group-hover:opacity-100">
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    togglePin(c.id);
                  }}
                  className={`p-1 rounded-lg hover:bg-tuan-hover ${
                    pinnedIds.includes(c.id)
                      ? 'text-tuan-accent'
                      : 'text-tuan-textSecondary hover:text-tuan-text'
                  }`}
                  title={pinnedIds.includes(c.id) ? '取消置顶' : '置顶对话'}
                >
                  <Pin size={14} className={pinnedIds.includes(c.id) ? 'fill-current' : ''} />
                </button>
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    const t = window.prompt('重命名对话', c.title);
                    if (t?.trim()) onRename(c.id, t.trim());
                  }}
                  className="p-1 rounded-lg text-tuan-textSecondary hover:text-tuan-text hover:bg-tuan-hover"
                  title="重命名"
                >
                  <MoreHorizontal size={15} />
                </button>
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    onDelete(c.id);
                  }}
                  className="p-1 rounded-lg text-[var(--tuan-danger)] hover:bg-[var(--tuan-danger-bg)]"
                  title="删除"
                >
                  <TrashIcon />
                </button>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* 底部用户行 */}
      <div className="border-t border-tuan-border px-3 py-3 flex-shrink-0">
        <button
          onClick={() => go('settings')}
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

function TrashIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 6h18M8 6V4a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v2m2 0v14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2V6" />
    </svg>
  );
}
