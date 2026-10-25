import { useEffect, useMemo, useRef, useState } from 'react';
import BrandMark from './BrandMark';
import { MoreHorizontal, Settings, MessageSquare, FolderKanban, Package, Wrench, Blocks, Puzzle, Search, X, Pin, Plus, ChevronUp, ChevronDown, SlidersHorizontal, Sun, Moon, SquarePen, Trash2, RefreshCw, Download } from 'lucide-react';
import { store } from '../store/config';
import { getConvModeLabel, refreshSessionsFromEngine } from '../platform/sessions';
import { onInstallPromptAvailable, promptInstall } from '../platform/pwa';

export type PageKey =
  | 'chats' | 'projects' | 'artifacts' | 'skills' | 'mcp' | 'plugins' | 'settings';

/** 侧栏单条会话的元信息（mode 为可选模式标签，由数据侧落盘后展示） */
export interface RecentConv {
  id: string;
  title: string;
  ts?: number;
  /** 会话模式标签（可选；无数据源时不显示） */
  mode?: string;
}

interface Props {
  page: PageKey;
  onNavigate: (p: PageKey) => void;
  onNewChat: () => void;
  recent: RecentConv[];
  activeId?: string;
  onOpenConv: (id: string) => void;
  onRename: (id: string, title: string) => void;
  onDelete: (id: string) => void;
  /** 折叠态（桌面端折叠为图标轨；窄屏折叠为抽屉关闭） */
  collapsed?: boolean;
  /** 是否窄屏（手机 / 窄窗口） */
  isNarrow?: boolean;
  /** 当前主题（用户弹层内切换深浅色） */
  theme?: 'light' | 'dark';
  onToggleTheme?: () => void;
}

/** 侧栏最多展示的最近会话条数（T-3.1） */
const MAX_RECENT = 20;

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
function groupConversations(recent: RecentConv[]) {
  const groups: { label: string; items: RecentConv[] }[] = [];
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
/** 一级导航（平铺，无分组标题：更简洁现代化） */
const PRIMARY_ITEMS: MenuItem[] = [
  { key: 'chats', label: '聊天记录', icon: MessageSquare },
  { key: 'projects', label: '项目', icon: FolderKanban },
  { key: 'artifacts', label: '成品', icon: Package },
];
/** 二级菜单「工坊」（原「扩展」栏目降级）：技能 / MCP 服务 / 插件 */
const WORKSHOP_ITEMS: MenuItem[] = [
  { key: 'skills', label: '技能', icon: Wrench },
  { key: 'mcp', label: 'MCP 服务', icon: Blocks },
  { key: 'plugins', label: '插件', icon: Puzzle },
];

/** 全部导航项（图标轨与内联导航共用） */
const NAV_ITEMS: MenuItem[] = [...PRIMARY_ITEMS, ...WORKSHOP_ITEMS];

/** 是否触屏设备（仅触屏设备才挂手势监听，桌面鼠标交互零影响） */
function isTouchDevice(): boolean {
  return typeof window !== 'undefined' && ('ontouchstart' in window || navigator.maxTouchPoints > 0);
}

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
  theme,
  onToggleTheme,
}: Props) {
  // 桌面端折叠 = 图标轨；窄屏折叠 = 抽屉关闭（不渲染）。
  const rail = !!collapsed && !isNarrow;

  const [searchQuery, setSearchQuery] = useState('');
  const [workshopOpen, setWorkshopOpen] = useState(false);
  const [userMenuOpen, setUserMenuOpen] = useState(false);
  const [pinnedIds, setPinnedIds] = useState<string[]>(() => {
    try {
      return JSON.parse(localStorage.getItem('tuan.pinnedConvs') || '[]');
    } catch {
      return [];
    }
  });
  // T-6.1 下拉刷新状态：下拉距离（px）与刷新中/提示文案
  const [pullDist, setPullDist] = useState(0);
  const [refreshing, setRefreshing] = useState(false);
  const [refreshTip, setRefreshTip] = useState('');
  // T-6.3 是否可安装（beforeinstallprompt 已捕获）
  const [canInstall, setCanInstall] = useState(false);
  const searchRef = useRef<HTMLInputElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  // 下拉刷新的触摸追踪状态
  const pullTrack = useRef<{ startY: number; startTop: number; active: boolean }>({ startY: 0, startTop: 0, active: false });

  useEffect(() => {
    localStorage.setItem('tuan.pinnedConvs', JSON.stringify(pinnedIds));
  }, [pinnedIds]);

  // 订阅 PWA 安装可用性
  useEffect(() => onInstallPromptAvailable(setCanInstall), []);

  const togglePin = (id: string) => {
    setPinnedIds((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]
    );
  };

  // T-3.5 删除二次确认：确认后再回调 App 的 onDelete（当前会话删除后 App 会自动切空）
  const requestDelete = (id: string) => {
    const ok = window.confirm('确定删除这条对话？删除后无法恢复。');
    if (ok) onDelete(id);
  };

  const sortedRecent = useMemo(() => {
    const pinned = recent.filter((c) => pinnedIds.includes(c.id));
    const unpinned = recent.filter((c) => !pinnedIds.includes(c.id));
    // T-3.1：最多展示最近 20 条
    return [...pinned, ...unpinned].slice(0, MAX_RECENT);
  }, [recent, pinnedIds]);

  // T-3.2 内容搜索索引：从本地存储读取各会话消息文本（props 只带标题/时间，内容从本地缓存补）
  const contentIndex = useMemo(() => {
    const m = new Map<string, string>();
    try {
      for (const c of store.conversations()) {
        m.set(c.id, c.messages.map((msg) => msg.content || '').join('\n'));
      }
    } catch {
      /* 本地缓存读取失败时只按标题搜 */
    }
    return m;
  }, [recent]);

  const filteredRecent = useMemo(() => {
    if (!searchQuery.trim()) return sortedRecent;
    const q = searchQuery.trim().toLowerCase();
    return sortedRecent.filter((c) => {
      if (c.title.toLowerCase().includes(q)) return true;
      // 内容实时过滤：命中消息正文也算
      const body = contentIndex.get(c.id);
      return !!body && body.toLowerCase().includes(q);
    });
  }, [sortedRecent, searchQuery, contentIndex]);

  // T-6.1 下拉刷新：在列表顶部下拉时拉取引擎会话列表并刷新本地缓存
  const onPullStart = (e: React.TouchEvent) => {
    const t = e.touches[0];
    const el = scrollRef.current;
    pullTrack.current = {
      startY: t.clientY,
      startTop: el ? el.scrollTop : 0,
      active: el ? el.scrollTop <= 0 : false,
    };
  };
  const onPullMove = (e: React.TouchEvent) => {
    if (!pullTrack.current.active || refreshing) return;
    const dy = e.touches[0].clientY - pullTrack.current.startY;
    // 只在顶部且往下拉时显示下拉距离（最大 72px，视觉限位）
    setPullDist(dy > 0 ? Math.min(dy, 72) : 0);
  };
  const onPullEnd = async () => {
    if (!pullTrack.current.active) return;
    pullTrack.current.active = false;
    if (pullDist > 64 && !refreshing) {
      setRefreshing(true);
      setRefreshTip('正在刷新…');
      await refreshSessionsFromEngine();
      setRefreshing(false);
      setRefreshTip('已刷新');
      window.setTimeout(() => setRefreshTip(''), 1200);
    }
    setPullDist(0);
  };

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
        <div className="relative">
          <button
            onClick={() => setUserMenuOpen((v) => !v)}
            title="本地用户 · 设置"
            className="w-10 h-10 mt-2 flex items-center justify-center rounded-full bg-tuan-accent text-white text-[15px] font-medium"
          >
            U
          </button>
          {userMenuOpen && (
            <div className="absolute bottom-12 left-1/2 -translate-x-1/2 z-30 w-44 rounded-xl border border-tuan-border bg-tuan-sidebar shadow-lg p-1.5">
              <div className="px-2.5 py-1.5 text-[12px] text-tuan-textSecondary truncate">本地自托管 · 完全离线</div>
              <button
                onClick={() => { setUserMenuOpen(false); onNavigate('settings'); }}
                className="w-full flex items-center gap-2 rounded-lg px-2.5 py-1.5 text-[13px] text-tuan-text hover:bg-tuan-hover transition-colors"
              >
                <Settings size={14} className="flex-shrink-0 dark:invert" />
                设置
              </button>
              <button
                onClick={() => { setUserMenuOpen(false); onToggleTheme?.(); }}
                className="w-full flex items-center gap-2 rounded-lg px-2.5 py-1.5 text-[13px] text-tuan-text hover:bg-tuan-hover transition-colors"
              >
                {theme === 'dark' ? <Sun size={14} className="flex-shrink-0 dark:invert" /> : <Moon size={14} className="flex-shrink-0 dark:invert" />}
                切换{theme === 'dark' ? '浅色' : '深色'}主题
              </button>
              <div className="px-2.5 pt-1.5 pb-0.5 text-[11px] text-tuan-textSecondary/70">Tuan 0.3.4</div>
            </div>
          )}
        </div>
      </aside>
    );
  }

  // ===== 完整侧栏（含内联导航，替代原"菜单"弹层）=====
  return (
    <aside className="sidebar-fixed h-full w-[260px] flex-shrink-0 flex flex-col bg-tuan-sidebar border-r border-tuan-border overflow-hidden">
      {/* 品牌区（紧凑） */}
      <div className="flex items-center gap-2 px-[16px] pt-[12px] pb-[6px] flex-shrink-0">
        <BrandMark size="md" />
        <span className="text-[14px] font-semibold tracking-wide text-[var(--tuan-heading)] select-none">
          Tuan
        </span>
      </div>

      {/* 固定操作：新建对话 */}
      <div className="flex-shrink-0 px-[8px]">
        <button
          onClick={onNewChat}
          className="w-full flex items-center gap-2 rounded-lg px-2.5 py-[5px] text-[13px] text-tuan-text hover:bg-tuan-hover transition-colors"
          style={{ fontWeight: 400 }}
        >
          <span className="flex items-center justify-center" style={{ width: '18px', height: '18px' }}>
            <SquarePen size={18} className="dark:invert" />
          </span>
          新建对话
        </button>
      </div>

      {/* T-6.1 下拉刷新指示：下拉距离驱动位移，刷新中旋转图标 */}
      <div
        className="flex-shrink-0 flex items-center justify-center overflow-hidden text-tuan-textSecondary"
        style={{ height: refreshing || refreshTip ? 28 : pullDist, transition: pullDist === 0 ? 'height .2s' : 'none' }}
      >
        {refreshing || refreshTip ? (
          <span className="flex items-center gap-1.5 text-[12px]">
            <RefreshCw size={13} className={refreshing ? 'animate-spin' : ''} />
            {refreshing ? '正在刷新…' : refreshTip}
          </span>
        ) : pullDist > 0 ? (
          <span className="text-[11px]">{pullDist > 64 ? '松开刷新' : '下拉刷新'}</span>
        ) : null}
      </div>

      {/* 滚动区：搜索 + 最近对话 + 内联导航 */}
      <div
        ref={scrollRef}
        className="flex-1 overflow-y-auto sidebar-scroll min-h-0 px-[8px] pt-2.5 pb-5"
        onTouchStart={isTouchDevice() ? onPullStart : undefined}
        onTouchMove={isTouchDevice() ? onPullMove : undefined}
        onTouchEnd={isTouchDevice() ? onPullEnd : undefined}
      >
        {/* 搜索框 */}
        <div className="relative mb-1.5 px-2">
          <div className="flex items-center gap-2 bg-tuan-input border border-tuan-border rounded-lg px-2.5 py-1">
            <Search size={13} className="text-tuan-textSecondary flex-shrink-0" />
            <input
              ref={searchRef}
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="搜索对话（标题 / 内容）"
              className="flex-1 bg-transparent outline-none text-[12.5px] text-tuan-text placeholder:text-tuan-textSecondary"
            />
            {searchQuery && (
              <button
                onClick={() => setSearchQuery('')}
                className="text-tuan-textSecondary hover:text-tuan-text"
              >
                <X size={12} />
              </button>
            )}
          </div>
        </div>
        <div className="px-3 pb-1 text-[12.5px] font-medium text-tuan-textSecondary flex items-center justify-between">
          <span>{searchQuery ? '搜索结果' : `最近对话（最多 ${MAX_RECENT} 条）`}</span>
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
                    onDelete={() => requestDelete(c.id)}
                    onSwipeNew={onNewChat}
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
              onDelete={() => requestDelete(c.id)}
              onSwipeNew={onNewChat}
            />
          ))}
        </div>

        {/* 内联导航（一级平铺 + 工坊二级菜单，简洁现代化） */}
        <div className="mt-3.5 pt-2.5 border-t border-tuan-border/60">
          {PRIMARY_ITEMS.map(({ key, label, icon: Icon }) => (
            <button
              key={key}
              onClick={() => onNavigate(key)}
              className={`w-full flex items-center gap-2.5 px-2.5 py-[5px] text-[13px] transition-colors rounded-lg ${
                page === key ? 'bg-tuan-hover text-tuan-text' : 'text-tuan-text hover:bg-tuan-hover'
              }`}
            >
              <Icon size={16} className="flex-shrink-0 dark:invert" />
              {label}
            </button>
          ))}
          {/* 工坊：二级菜单入口（原「扩展」栏目降级） */}
          <button
            onClick={() => setWorkshopOpen((v) => !v)}
            className={`w-full flex items-center gap-2.5 px-2.5 py-[5px] text-[13px] transition-colors rounded-lg ${
              !workshopOpen && WORKSHOP_ITEMS.some((w) => page === w.key)
                ? 'bg-tuan-hover text-tuan-text'
                : 'text-tuan-text hover:bg-tuan-hover'
            }`}
          >
            <SlidersHorizontal size={16} className="flex-shrink-0 dark:invert" />
            <span className="flex-1 text-left">工坊</span>
            <ChevronDown
              size={14}
              className={`text-tuan-textSecondary transition-transform ${workshopOpen ? 'rotate-180' : ''}`}
            />
          </button>
          {workshopOpen && (
            <div className="ml-2.5 pl-2.5 border-l border-tuan-border/60 space-y-px">
              {WORKSHOP_ITEMS.map(({ key, label, icon: Icon }) => (
                <button
                  key={key}
                  onClick={() => onNavigate(key)}
                  className={`w-full flex items-center gap-2.5 px-2.5 py-[5px] text-[13px] transition-colors rounded-lg ${
                    page === key ? 'bg-tuan-hover text-tuan-text' : 'text-tuan-text hover:bg-tuan-hover'
                  }`}
                >
                  <Icon size={15} className="flex-shrink-0 dark:invert" />
                  {label}
                </button>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* 底部用户行：点击弹出「设置 / 主题 / 安装应用」菜单 */}
      <div className="relative border-t border-tuan-border px-2.5 py-2 flex-shrink-0">
        <button
          onClick={() => setUserMenuOpen((v) => !v)}
          className="w-full flex items-center gap-2 rounded-lg p-1.5 hover:bg-tuan-hover transition-colors cursor-pointer"
        >
          <div className="h-7 w-7 rounded-full bg-tuan-accent text-white flex items-center justify-center text-[13px] font-medium flex-shrink-0">
            U
          </div>
          <div className="flex-1 min-w-0 text-left">
            <div className="text-[13.5px] font-medium text-tuan-text leading-tight">本地用户</div>
            <div className="text-[12px] text-tuan-textSecondary">本地自托管</div>
          </div>
          <ChevronUp size={14} className={`text-tuan-textSecondary transition-transform ${userMenuOpen ? 'rotate-180' : ''}`} />
        </button>
        {userMenuOpen && (
          <div className="absolute bottom-[calc(100%-4px)] left-2.5 right-2.5 z-30 rounded-xl border border-tuan-border bg-tuan-sidebar shadow-lg p-1.5">
            <div className="px-2.5 py-1.5 text-[12px] text-tuan-textSecondary">本地自托管 · 完全离线</div>
            <button
              onClick={() => { setUserMenuOpen(false); onNavigate('settings'); }}
              className="w-full flex items-center gap-2 rounded-lg px-2.5 py-1.5 text-[13px] text-tuan-text hover:bg-tuan-hover transition-colors"
            >
              <Settings size={14} className="flex-shrink-0 dark:invert" />
              设置
            </button>
            <button
              onClick={() => { setUserMenuOpen(false); onToggleTheme?.(); }}
              className="w-full flex items-center gap-2 rounded-lg px-2.5 py-1.5 text-[13px] text-tuan-text hover:bg-tuan-hover transition-colors"
            >
              {theme === 'dark' ? <Sun size={14} className="flex-shrink-0 dark:invert" /> : <Moon size={14} className="flex-shrink-0 dark:invert" />}
              切换{theme === 'dark' ? '浅色' : '深色'}主题
            </button>
            {/* T-6.3：PWA 安装入口（仅在浏览器捕获到 beforeinstallprompt 时出现） */}
            {canInstall && (
              <button
                onClick={() => { setUserMenuOpen(false); void promptInstall(); }}
                className="w-full flex items-center gap-2 rounded-lg px-2.5 py-1.5 text-[13px] text-tuan-text hover:bg-tuan-hover transition-colors"
              >
                <Download size={14} className="flex-shrink-0 dark:invert" />
                安装到桌面 / 主屏幕
              </button>
            )}
            <div className="px-2.5 pt-1.5 pb-0.5 text-[11px] text-tuan-textSecondary/70">Tuan 0.3.4</div>
          </div>
        )}
      </div>
    </aside>
  );
}

/** 单条对话行（含 hover 操作：置顶 / 重命名 / 删除；T-6.1 触屏左滑删除、右滑新建） */
function ConvRow({
  conv,
  active,
  pinned,
  onOpen,
  onTogglePin,
  onRename,
  onDelete,
  onSwipeNew,
}: {
  conv: RecentConv;
  active: boolean;
  pinned: boolean;
  onOpen: () => void;
  onTogglePin: () => void;
  onRename: () => void;
  onDelete: () => void;
  /** 触屏右滑触发新建对话（T-6.1） */
  onSwipeNew: () => void;
}) {
  // 手势追踪：滑动命中后吞掉同步 click，避免「左滑删除」之后又误触打开会话
  const track = useRef({ sx: 0, sy: 0, swiped: false, started: false });
  // 模式标签：优先 props 传入，其次读本地侧映射（可能为空）
  const modeLabel = conv.mode || getConvModeLabel(conv.id);

  const onTouchStart = (e: React.TouchEvent) => {
    const t = e.touches[0];
    track.current = { sx: t.clientX, sy: t.clientY, swiped: false, started: true };
  };
  const onTouchEnd = (e: React.TouchEvent) => {
    const start = track.current;
    if (!start.started) return;
    start.started = false;
    const t = e.changedTouches[0];
    const dx = t.clientX - start.sx;
    const dy = t.clientY - start.sy;
    // 横向为主（位移 >64px 且明显大于纵向）才判定为手势
    if (Math.abs(dx) > 64 && Math.abs(dx) > Math.abs(dy) * 2) {
      // 屏幕最左缘 40px 区域留给系统侧滑返回（platform/mobile.ts），不抢手势
      if (start.sx > 40) {
        start.swiped = true;
        if (dx < 0) {
          // 左滑 → 删除
          onDelete();
        } else {
          // 右滑 → 新建对话
          onSwipeNew();
        }
      }
    }
  };

  return (
    <div
      onClick={() => {
        if (track.current.swiped) {
          track.current.swiped = false;
          return;
        }
        onOpen();
      }}
      onTouchStart={isTouchDevice() ? onTouchStart : undefined}
      onTouchEnd={isTouchDevice() ? onTouchEnd : undefined}
      className={`group relative flex items-center min-h-[32px] rounded-xl px-3 py-1.5 cursor-pointer transition-colors ${
        active ? 'bg-tuan-hover' : 'hover:bg-tuan-hover'
      }`}
    >
      <div className="flex-1 min-w-0 pr-6">
        <div className="flex items-center gap-1.5">
          <span className="text-[13px] text-tuan-text truncate leading-snug">{conv.title}</span>
          {modeLabel && (
            <span className="flex-shrink-0 text-[10px] px-1 rounded bg-tuan-hover text-tuan-textSecondary leading-tight">
              {modeLabel}
            </span>
          )}
        </div>
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
          <Trash2 size={15} />
        </button>
      </div>
    </div>
  );
}
