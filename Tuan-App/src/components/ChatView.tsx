import { useEffect, useMemo, useRef, useState } from 'react';
import {
  ArrowUp,
  Plus,
  Square,
  Copy,
  Check,
  ChevronDown,
  Wrench,
  FileText,
  Globe,
  Terminal,
  XCircle,
  X,
  Trash2,
  Pencil,
  ShieldAlert,
  CheckCheck,
  Hand,
  RotateCcw,
  Code2,
  Mail,
  Palette,
} from 'lucide-react';
import { open as openDialog } from '@tauri-apps/plugin-dialog';
import { invoke, isTauri } from '@tauri-apps/api/core';
import type { ChatMessage, PendingApproval, Provider, ToolEvent } from '../types';
import { MODES, getMode, type ModeId } from '../platform/modes';
import { resolveMascot, useDarkTheme } from '../platform/mascot';
import { useMediaQuery } from '../platform/useMediaQuery';
import ComposerSelect, { type SelectOption } from './ComposerSelect';
import ReplyMarkdown from './ReplyMarkdown';

interface Props {
  convId?: string;
  /** 每次点新建对话自增；发送前用它作为立绘随机种子，保证空首页不跳图、换对话才换图 */
  newChatSeq?: number;
  providers: Provider[];
  providerId?: string;
  model?: string;
  onProviderChange: (id: string) => void;
  onModelChange: (m: string) => void;
  messages: ChatMessage[];
  /** 当前对话标题（用于聊天页头部显示；无则回落首条消息） */
  title?: string;
  streaming: boolean;
  error?: string;
  tools: ToolEvent[];
  /** 引擎安全闸门发起的危险操作审批；非空时渲染审批卡 */
  approval?: PendingApproval | null;
  onApprove?: (id: string, decision: 'allow' | 'deny') => void;
  /** 助手形象档（历史兼容字段，已无 UI 入口；二次元立绘为唯一形象） */
  avatarMode: 'anime' | 'default';
  onSend: (text: string) => void;
  onStop: () => void;
  onDeleteMessage?: (msgId: string) => void;
  onEditMessage?: (msgId: string, newText: string) => void;
  onRetry?: () => void;
  onOpenGuide?: () => void;
  onOpenSettings?: () => void;
  /** 新建对话（聊天页头部「新建」按钮） */
  onNewChat?: () => void;
  /** 打开 ⌘K 命令面板（状态栏入口） */
  onOpenPalette?: () => void;
  /** 五模式：闲聊 / 协同 / 灵码 / 感通 / 无界。当前模式；切换走 onModeChange。 */
  mode: ModeId;
  onModeChange: (m: ModeId) => void;
}

function greeting(): string {
  const h = new Date().getHours();
  if (h < 6) return '夜深了，还在忙吗？';
  if (h < 12) return '早上好，今天想先处理什么？';
  if (h < 18) return '下午好，有什么想一起完成的？';
  return '晚上好，接下来想做什么？';
}

/** 模式 L0–L4 风险点颜色（与 index.css 的 mode-pill 分档保持一致） */
const LEVEL_COLORS: Record<string, string> = {
  L0: 'var(--text-tuan-secondary)',
  L2: 'var(--tuan-link)',
  L3: 'var(--tuan-accent-soft)',
  L4: 'var(--tuan-danger)',
};

/** composer 模式弹层选项（桌面端）：名称 + tagline + 风险点 */
const MODE_SELECT_OPTIONS: SelectOption[] = MODES.map((m) => ({
  value: m.id,
  label: m.name,
  sub: m.tagline,
  dot: LEVEL_COLORS[m.level],
}));

/**
 * 首页示例提示（Claude 桌面式 2×2 卡片网格；窄屏退化为 chips）。
 * 点击把一段更完整的起始提示填入输入框，兼顾五种模式特色。
 */
interface SuggestionCard {
  icon: typeof Code2;
  title: string;
  sub: string;
  prompt: string;
}
const SUGGESTION_CARDS: SuggestionCard[] = [
  {
    icon: Code2,
    title: '灵码重构',
    sub: '把一段 Python 改写成异步',
    prompt: '用灵码模式帮我把这段 Python 重构成异步：\n\n',
  },
  {
    icon: FileText,
    title: '长文摘要',
    sub: '总结要点并列出关键信息',
    prompt: '帮我把下面这段长文总结成 3 个要点：\n\n',
  },
  {
    icon: Mail,
    title: '写封邮件',
    sub: '请假一天的中文邮件',
    prompt: '帮我写一封请假一天的中文邮件，语气礼貌简洁：\n\n',
  },
  {
    icon: Palette,
    title: '灵感文案',
    sub: '感通模式生成海报文案',
    prompt: '用感通模式为一张海边主题的海报生成文案：\n\n',
  },
];

/** 相对时间显示：刚刚/几分钟前/几小时前/昨天/具体日期 */
function formatRelativeTime(ts: number): string {
  const now = Date.now();
  const diff = now - ts;
  const seconds = Math.floor(diff / 1000);
  if (seconds < 60) return '刚刚';
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}分钟前`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}小时前`;
  const days = Math.floor(hours / 24);
  if (days === 1) return '昨天';
  if (days < 7) return `${days}天前`;
  // 超过 7 天显示具体日期
  const d = new Date(ts);
  const today = new Date(now);
  if (d.getFullYear() === today.getFullYear()) {
    return `${d.getMonth() + 1}月${d.getDate()}日`;
  }
  return `${d.getFullYear()}年${d.getMonth() + 1}月${d.getDate()}日`;
}

/**
 * Claude Code 风格菊花：SVG 圆环 + stroke-dasharray 3/4 缺口，匀速旋转。
 * 只动画 transform: rotate()，走 GPU 合成，低端 WebView 不掉帧。
 * 颜色走 currentColor（继承容器 --tuan-accent-soft），
 * 浅/深色主题下都清晰可见。思考中 / 输出中 / 工具执行中统一用它，
 * 替代原先那颗原地明灭的 .think-glow 呼吸光点。
 */
function Spinner({ className = '' }: { className?: string }) {
  return (
    <span className={`cc-spinner ${className}`.trim()} aria-hidden="true">
      <svg viewBox="0 0 20 20" fill="none" aria-hidden="true" focusable="false">
        <circle className="cc-spinner-track" cx="10" cy="10" r="8" pathLength="100" />
        <circle className="cc-spinner-ring" cx="10" cy="10" r="8" pathLength="100" />
      </svg>
    </span>
  );
}

function toolIcon(name: string) {
  const n = name.toLowerCase();
  if (n.includes('file') || n.includes('read') || n.includes('edit') || n.includes('write')) return FileText;
  if (n.includes('bash') || n.includes('shell') || n.includes('exec') || n.includes('run')) return Terminal;
  if (n.includes('web') || n.includes('search') || n.includes('fetch') || n.includes('browse')) return Globe;
  return Wrench;
}

/** Claude Code 风格思考块：菊花旋转 + 计时，可折叠；结束后打勾。 */
function ThoughtBlock({ text, streaming, startedAt }: { text: string; streaming: boolean; startedAt: number }) {
  const [open, setOpen] = useState(true);
  const [, force] = useState(0);
  useEffect(() => {
    if (!streaming) return;
    const t = setInterval(() => force((n) => n + 1), 500);
    return () => clearInterval(t);
  }, [streaming]);
  const secs = Math.max(1, Math.floor((Date.now() - startedAt) / 1000));
  return (
    <div className="mb-2 rounded-2xl border border-tuan-border bg-tuan-input overflow-hidden">
      <button
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center gap-2 px-3 py-2 text-[13px] text-tuan-textSecondary hover:bg-tuan-hover transition-colors"
      >
        {streaming ? (
          <Spinner className="cc-spinner-lg" />
        ) : (
          <Check size={14} className="text-emerald-600 dark:text-emerald-400" />
        )}
        <span className="font-medium text-tuan-text">
          {streaming ? '思考中…' : '已思考'}
        </span>
        {streaming && <span className="tabular-nums">{secs}s</span>}
        <ChevronDown
          size={14}
          className={`ml-auto transition-transform ${open ? 'rotate-180' : ''}`}
        />
      </button>
      {open && (
        <div className="px-3 pb-2.5 text-[13px] leading-relaxed text-tuan-textSecondary whitespace-pre-wrap break-words font-mono max-h-64 overflow-y-auto custom-scrollbar">
          {text}
        </div>
      )}
    </div>
  );
}

/** Claude Code 风格工具调用卡：执行中菊花 → 成功勾 / 失败叉，统一圆角。 */
function ToolCard({ tool }: { tool: ToolEvent }) {
  const Icon = toolIcon(tool.name);
  return (
    <div className="flex items-start gap-2.5 rounded-2xl border border-tuan-border bg-tuan-input px-3 py-2">
      <div className={`w-6 h-6 rounded-lg flex-none flex items-center justify-center ${tool.status === 'error' ? 'text-[var(--tuan-danger)]' : 'bg-tuan-hover text-tuan-text'}`}>
        <Icon size={13} />
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 text-[13px]">
          <span className="font-medium text-tuan-text">{tool.name}</span>
          {tool.status === 'running' && (
            <span className="inline-flex items-center gap-1 text-tuan-textSecondary">
              <Spinner /> 执行中
            </span>
          )}
          {tool.status === 'done' && <Check size={13} className="text-emerald-600 dark:text-emerald-400" />}
          {tool.status === 'error' && <XCircle size={13} className="text-[var(--tuan-danger)]" />}
        </div>
        {tool.args && tool.args.length > 0 && (
          <div className="mt-1 text-[12px] text-tuan-textSecondary font-mono truncate">{tool.args}</div>
        )}
      </div>
    </div>
  );
}

/** 工具调用区：整轮工具卡竖向排列（渲染在用户消息与回复之间）。 */
function ToolStack({ tools }: { tools: ToolEvent[] }) {
  if (tools.length === 0) return null;
  return (
    <div className="flex flex-col gap-1.5 my-2">
      {tools.map((t, i) => (
        <ToolCard key={`${t.name}-${i}`} tool={t} />
      ))}
    </div>
  );
}

/**
 * 危险操作审批卡。
 *
 * 引擎在 `_ask_approval` 里把审批请求推进 SSE 后**阻塞等待**，300 秒内不答复
 * 就按拒绝处理（fail-closed）。所以这张卡一出现就必须让用户能立刻决定，
 * 而不是埋在消息流里需要往下翻。
 */
function ApprovalCard({
  approval,
  onApprove,
}: {
  approval: PendingApproval;
  onApprove?: (id: string, decision: 'allow' | 'deny') => void;
}) {
  // verdict 是 analyze_command 的 JSON（risk / reasons / blast_radius / suggestions）。
  // 解析失败不影响主流程 —— prompt 与两个按钮已经足够做决定。
  const verdict = useMemo(() => {
    if (!approval.verdict) return null;
    try {
      const v = JSON.parse(approval.verdict) as Record<string, unknown>;
      return {
        risk: typeof v.risk === 'string' ? v.risk : v.risk == null ? undefined : String(v.risk),
        reasons: Array.isArray(v.reasons) ? v.reasons.map(String) : undefined,
        blast:
          typeof v.blast_radius === 'string'
            ? v.blast_radius
            : typeof v.blast === 'string'
              ? v.blast
              : undefined,
        suggestions: Array.isArray(v.suggestions) ? v.suggestions.map(String) : undefined,
      };
    } catch {
      return null;
    }
  }, [approval.verdict]);

  const high = verdict?.risk == null || /high|high|危|危|block|deny/i.test(verdict.risk ?? 'high');

  return (
    <div
      className="mx-auto w-full max-w-[768px] mb-2 rounded-2xl border px-3.5 py-3"
      style={{
        borderColor: 'var(--tuan-danger)',
        background: 'var(--tuan-danger-bg)',
      }}
    >
      <div className="flex items-start gap-2.5">
        <ShieldAlert size={17} className="shrink-0 mt-0.5" style={{ color: 'var(--tuan-danger)' }} />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="text-[13px] font-semibold" style={{ color: 'var(--tuan-danger)' }}>
              需要你确认
            </span>
            {verdict?.risk ? (
              <span
                className="text-[11px] px-1.5 py-0.5 rounded-md border"
                style={{
                  color: high ? 'var(--tuan-danger)' : 'var(--tuan-textSecondary)',
                  borderColor: high ? 'var(--tuan-danger)' : 'var(--tuan-border)',
                }}
              >
                风险：{verdict.risk}
              </span>
            ) : null}
          </div>
          <pre
            className="mt-1.5 mb-0 text-[12.5px] leading-relaxed whitespace-pre-wrap break-all font-mono max-h-40 overflow-auto"
            style={{ color: 'var(--tuan-text)' }}
          >
            {approval.prompt || '(引擎未给出操作说明)'}
          </pre>
          {verdict?.blast ? (
            <div className="mt-1 text-[11.5px]" style={{ color: 'var(--tuan-textSecondary)' }}>
              影响半径：{verdict.blast}
            </div>
          ) : null}
          {verdict?.reasons && verdict.reasons.length > 0 ? (
            <ul
              className="mt-1 text-[11.5px] leading-snug list-disc pl-4"
              style={{ color: 'var(--tuan-textSecondary)' }}
            >
              {verdict.reasons.map((r, i) => (
                <li key={i}>{r}</li>
              ))}
            </ul>
          ) : null}
          {verdict?.suggestions && verdict.suggestions.length > 0 ? (
            <div className="mt-1 text-[11.5px]" style={{ color: 'var(--tuan-textSecondary)' }}>
              安全替代：{verdict.suggestions.join('；')}
            </div>
          ) : null}
        </div>
      </div>
      <div className="mt-2.5 flex items-center justify-end gap-2">
        <button
          onClick={() => approval.id && onApprove?.(approval.id, 'deny')}
          className="inline-flex items-center gap-1.5 rounded-xl border px-3 py-1.5 text-[12.5px] hover:opacity-85 transition-opacity"
          style={{ borderColor: 'var(--tuan-border)', color: 'var(--tuan-text)' }}
        >
          <Hand size={14} />
          拒绝
        </button>
        <button
          onClick={() => approval.id && onApprove?.(approval.id, 'allow')}
          className="inline-flex items-center gap-1.5 rounded-xl px-3 py-1.5 text-[12.5px] text-white transition-opacity hover:opacity-90"
          style={{ background: 'var(--tuan-danger)' }}
        >
          <CheckCheck size={14} />
          允许执行
        </button>
      </div>
    </div>
  );
}

export default function ChatView({
  convId,
  newChatSeq,
  providers,
  providerId,
  model,
  onProviderChange,
  onModelChange,
  messages,
  title,
  streaming,
  error,
  tools,
  avatarMode,
  onSend,
  onStop,
  approval,
  onApprove,
  onDeleteMessage,
  onEditMessage,
  onRetry,
  onOpenGuide,
  onOpenSettings,
  onNewChat,
  onOpenPalette,
  mode,
  onModeChange,
}: Props) {
  const [draft, setDraft] = useState('');
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [editingMsgId, setEditingMsgId] = useState<string | null>(null);
  const [editDraft, setEditDraft] = useState('');
  const scrollRef = useRef<HTMLDivElement>(null);
  const taRef = useRef<HTMLTextAreaElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const streamStartRef = useRef<number>(Date.now());

  // 低端机（如骁龙 660）上一次性挂载上千条消息会导致掉帧、内存暴涨。
  // 这里只渲染最近 WINDOW 条，向上滚动到顶再逐段加载更早的历史。
  const WINDOW = 60;
  const [visibleCount, setVisibleCount] = useState(WINDOW);
  useEffect(() => {
    setVisibleCount((n) => Math.min(Math.max(n, WINDOW), messages.length));
  }, [messages.length]);
  const loadOlder = () => setVisibleCount((n) => (n >= messages.length ? n : n + WINDOW));
  const visibleMessages = useMemo(
    () => messages.slice(Math.max(0, messages.length - visibleCount)),
    [messages, visibleCount],
  );
  const hasOlder = visibleCount < messages.length;

  // 记录本轮流式生成的起始时间（思考计时/工具动画共用）
  useEffect(() => {
    if (streaming) streamStartRef.current = Date.now();
  }, [streaming]);

  const copyText = async (id: string, text: string) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopiedId(id);
      setTimeout(() => setCopiedId((c) => (c === id ? null : c)), 1500);
    } catch {
      /* 剪贴板不可用时忽略 */
    }
  };

  // 组件挂载时自动聚焦输入框
  useEffect(() => {
    // 延迟一点确保 DOM 渲染完成
    const timer = setTimeout(() => {
      taRef.current?.focus();
    }, 100);
    return () => clearTimeout(timer);
  }, []);

  const startEdit = (msgId: string, content: string) => {
    setEditingMsgId(msgId);
    setEditDraft(content);
  };

  const saveEdit = () => {
    if (editingMsgId && editDraft.trim()) {
      onEditMessage?.(editingMsgId, editDraft.trim());
    }
    setEditingMsgId(null);
    setEditDraft('');
  };

  const cancelEdit = () => {
    setEditingMsgId(null);
    setEditDraft('');
  };
  const activeProvider = providers.find((p) => p.id === providerId) ?? providers[0];
  const enabledModels = activeProvider?.models.filter((m) => m.enabled) ?? [];
  // 桌面端（宽窗口）用 Claude 桌面式弹层选择器；窄屏回落原生 <select>（低端 WebView 更稳）
  const desktop = useMediaQuery('(min-width: 820px)');
  const providerSelectOptions: SelectOption[] = providers.map((p) => ({
    value: p.id,
    label: p.name,
    sub: `${p.models.filter((m) => m.enabled).length} 个可用模型`,
  }));
  const modelSelectOptions: SelectOption[] = enabledModels.map((m) => ({
    value: m.id,
    label: m.name,
    sub: m.id,
  }));
  // 立绘按主题分两套资源（白底 / 黑底），主题切换时要重新解析，否则深色下仍挂白底图
  const dark = useDarkTheme();
  const mascot = resolveMascot(
    activeProvider,
    model || enabledModels[0]?.id,
    dark,
  );
  const empty = messages.length === 0;

  // 切换/新建对话时清空输入草稿
  useEffect(() => {
    setDraft('');
    requestAnimationFrame(() => {
      if (taRef.current) taRef.current.style.height = 'auto';
    });
  }, [convId]);

  // 仅当用户停留在底部附近时才自动跟随，上翻看历史不被打断
  const stickRef = useRef(true);
  const [showScrollBtn, setShowScrollBtn] = useState(false);
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const onScroll = () => {
      stickRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 120;
      setShowScrollBtn(!stickRef.current);
    };
    el.addEventListener('scroll', onScroll);
    return () => el.removeEventListener('scroll', onScroll);
  }, []);
  useEffect(() => {
    const el = scrollRef.current;
    if (el && stickRef.current) el.scrollTop = el.scrollHeight;
  }, [messages, tools]);

  const scrollToBottom = () => {
    const el = scrollRef.current;
    if (el) el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' });
    stickRef.current = true;
    setShowScrollBtn(false);
  };

  const autoGrow = () => {
    const ta = taRef.current;
    if (!ta) return;
    ta.style.height = 'auto';
    ta.style.height = Math.min(ta.scrollHeight, 200) + 'px';
  };

  const submit = () => {
    const text = draft.trim();
    if (!text || streaming) return;
    setDraft('');
    requestAnimationFrame(() => {
      if (taRef.current) taRef.current.style.height = 'auto';
    });
    onSend(text);
  };

  const canSend =
    draft.trim().length > 0 && !streaming && !!activeProvider && enabledModels.length > 0;

  const attach = (name: string, text: string) => {
    const snippet = text.length > 6000 ? text.slice(0, 6000) + '\n…（内容已截断）' : text;
    setDraft((d) => `${d ? d + '\n\n' : ''}【附件：${name}】\n${snippet}`);
    autoGrow();
  };

  const pickFile = async () => {
    if (isTauri()) {
      try {
        const sel = await openDialog({
          multiple: false,
          filters: [{ name: '文本文件', extensions: ['txt', 'md', 'json', 'py', 'js', 'ts', 'tsx', 'html', 'css', 'csv', 'log', 'ini', 'yaml', 'yml'] }],
        });
        if (!sel) return;
        const path = typeof sel === 'string' ? sel : (sel as { path: string }).path;
        const name = path.split(/[\\/]/).pop() || path;
        const text = await invoke<string>('read_text_file', { path });
        attach(name, text);
      } catch (e) {
        setDraft((d) => `${d ? d + '\n' : ''}[文件读取失败：${e instanceof Error ? e.message : String(e)}]`);
      }
    } else {
      fileRef.current?.click();
    }
  };

  const onPickFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    e.target.value = '';
    if (!f) return;
    let text = '';
    try {
      text = await f.text();
    } catch {
      setDraft((d) => (d ? `${d}\n[已附加文件：${f.name}（二进制，未读取内容）]` : `[已附加文件：${f.name}]`));
      return;
    }
    attach(f.name, text);
  };

  const card = (
    <div className="tuan-input-card w-full flex flex-col">
      <input ref={fileRef} type="file" className="hidden" onChange={onPickFile} />
      <textarea
        ref={taRef}
        value={draft}
        onChange={(e) => {
          setDraft(e.target.value);
          autoGrow();
        }}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            submit();
          }
        }}
        rows={1}
        placeholder="输入消息，Enter 发送，Shift+Enter 换行"
        className="w-full px-4 pt-4 pb-0 bg-transparent outline-none resize-none text-[16px] leading-[24px] font-[350] text-tuan-text placeholder:text-tuan-textSecondary"
      />
      {/* 底部一行：附件、供应商、模型、发送键横向排布 */}
      <div className="px-4 pb-3 pt-1 flex items-center justify-between gap-2">
        <div className="flex items-center gap-1.5">
          <button
            onClick={pickFile}
            className="cc-btn-ghost w-9 h-9 !p-0 flex-none"
            title="添加本地文件"
          >
            <Plus size={19} />
          </button>
          {draft.length > 0 && (
            <button
              onClick={() => { setDraft(''); requestAnimationFrame(() => { if (taRef.current) taRef.current.style.height = 'auto'; }); }}
              className="cc-btn-ghost w-9 h-9 !p-0 flex-none"
              title="清空输入"
            >
              <X size={17} />
            </button>
          )}
        </div>
        {/* W-4：切换行。三个胶囊 + 计数 + 发送键排在同一 flex 容器里，
            窄屏（Windows 窄窗口 / 手机横屏）自动折行，避免被挤成 40px 宽。 */}
        <div id="model-row" className="model-row flex-none max-w-full">
          {/* 字符计数：超过 2000 字时显示 */}
          {draft.length > 2000 && (
            <span className="text-[11px] text-tuan-textSecondary tabular-nums flex-none">
              {draft.length}
            </span>
          )}
          {/* 运行模式：闲聊 / 协同 / 灵码 / 感通 / 无界，切换即时生效并持久化。
              data-level 驱动 CSS 里的风险分档着色（L0 中性 → L4 危险色）。
              桌面端为 Claude 桌面式弹层（带 tagline + 风险点），窄屏回落原生 select。 */}
          {desktop ? (
            <ComposerSelect
              value={mode}
              options={MODE_SELECT_OPTIONS}
              onChange={(v) => onModeChange(v as ModeId)}
              title={getMode(mode).tagline}
              dataLevel={getMode(mode).level}
              className="cc-pill mode-pill min-w-[72px] max-w-[110px] justify-center"
            />
          ) : (
            <select
              value={mode}
              onChange={(e) => onModeChange(e.target.value as ModeId)}
              style={{ borderRadius: 9999 }}
              title={getMode(mode).tagline}
              data-level={getMode(mode).level}
              className="cc-pill mode-pill flex-none min-w-[72px] max-w-[110px] text-left truncate"
            >
              {MODES.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.name}
                </option>
              ))}
            </select>
          )}
          {desktop ? (
            <ComposerSelect
              value={activeProvider?.id ?? ''}
              options={providerSelectOptions}
              onChange={onProviderChange}
              className="cc-pill min-w-0 sm:min-w-[72px] sm:max-w-[120px] justify-center"
            />
          ) : (
            <select
              value={activeProvider?.id ?? ''}
              onChange={(e) => onProviderChange(e.target.value)}
              style={{ borderRadius: 9999 }}
              className="cc-pill min-w-0 flex-1 sm:flex-none sm:min-w-[72px] sm:max-w-[120px] text-left truncate"
            >
              {providers.length === 0 && <option>请先在设置添加供应商</option>}
              {providers.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          )}
          {desktop ? (
            <ComposerSelect
              value={model || enabledModels[0]?.id || ''}
              options={modelSelectOptions}
              onChange={onModelChange}
              disabled={enabledModels.length === 0}
              className="cc-pill min-w-0 sm:min-w-[72px] sm:max-w-[130px] justify-center"
            />
          ) : (
            <select
              value={model || enabledModels[0]?.id || ''}
              onChange={(e) => onModelChange(e.target.value)}
              disabled={enabledModels.length === 0}
              style={{ borderRadius: 9999 }}
              className="cc-pill min-w-0 flex-1 sm:flex-none sm:min-w-[72px] sm:max-w-[130px] text-left truncate"
            >
              {enabledModels.length === 0 && <option>暂无模型</option>}
              {enabledModels.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.name}
                </option>
              ))}
            </select>
          )}
          {streaming ? (
            <button
              onClick={onStop}
              className="cc-btn-primary w-9 h-9 !p-0 flex-none"
              title="停止生成"
            >
              <Square size={15} />
            </button>
          ) : (
            <button
              onMouseDown={(e) => e.preventDefault()}
              onClick={submit}
              disabled={!canSend}
              className="cc-btn-primary w-9 h-9 !p-0 flex-none"
              title="发送"
            >
              <ArrowUp size={20} strokeWidth={2.5} />
            </button>
          )}
        </div>
      </div>
    </div>
  );

  return (
    <div className="flex-1 bg-tuan-main h-full flex flex-col overflow-clip">
      {empty ? (
        <div className="flex-1 flex flex-col items-center justify-center px-4 w-full">
          <div className="mascot-in flex flex-col items-center mb-5">
            <div className="awa-breathe w-[112px] h-[112px] rounded-2xl overflow-hidden border border-tuan-border bg-tuan-artBg">
              <img src={mascot.img} alt={mascot.name} className="tuan-art-img w-full h-full object-cover object-top" />
            </div>
          </div>

          <h1
            className="mascot-in greeting-title text-center whitespace-normal text-[var(--tuan-heading)] text-[32px] sm:text-[40px] leading-[1.3] font-normal mb-[28px] max-w-full px-2 flex items-center justify-center gap-3"
            style={{ fontFamily: '"Spectral","Source Serif 4",Georgia,serif', animationDelay: '0.1s' }}
          >
            <span>{greeting()}</span>
          </h1>
          {/* 示例提示：桌面端 Claude 桌面式 2×2 卡片网格，窄屏退化为 chips；
              仅在已配置供应商时展示，点击填入输入框 */}
          {providers.length > 0 && (
            <>
              <div className="hidden sm:grid w-full max-w-[672px] grid-cols-2 gap-2 px-2 mb-[22px]">
                {SUGGESTION_CARDS.map(({ icon: Icon, title, sub, prompt }) => (
                  <button
                    key={title}
                    onClick={() => {
                      setDraft(prompt);
                      requestAnimationFrame(() => taRef.current?.focus());
                    }}
                    className="group flex items-start gap-2.5 rounded-xl border border-tuan-border bg-tuan-input/60 px-3.5 py-3 text-left transition-colors hover:bg-tuan-hover"
                  >
                    <span className="mt-0.5 flex h-7 w-7 flex-none items-center justify-center rounded-lg border border-tuan-border bg-tuan-artBg text-tuan-textSecondary transition-colors group-hover:text-tuan-text">
                      <Icon size={15} />
                    </span>
                    <span className="min-w-0">
                      <span className="block text-[13px] font-medium text-tuan-text">{title}</span>
                      <span className="block text-[11.5px] text-tuan-textSecondary truncate">{sub}</span>
                    </span>
                  </button>
                ))}
              </div>
              <div className="sm:hidden w-full max-w-[672px] flex flex-wrap justify-center gap-2 px-2 mb-[22px]">
                {SUGGESTION_CARDS.map(({ title, sub, prompt }) => (
                  <button
                    key={title}
                    onClick={() => {
                      setDraft(prompt);
                      requestAnimationFrame(() => taRef.current?.focus());
                    }}
                    className="cc-pill !rounded-full text-[13px] leading-snug text-tuan-textSecondary hover:text-tuan-text hover:bg-tuan-hover break-words max-w-full"
                    title={sub}
                  >
                    {title}：{sub}
                  </button>
                ))}
              </div>
            </>
          )}
          <div className="w-full max-w-[672px]">{card}</div>
          {error && (
            <div className="mt-4 w-full max-w-[672px] text-[13px] text-[var(--tuan-danger)] bg-[var(--tuan-danger-bg)] rounded-xl px-3.5 py-2.5 leading-relaxed">
              <div className="flex items-start gap-2">
                <span className="flex-1">{error}</span>
                {onRetry && (
                  <button
                    onClick={onRetry}
                    className="flex-shrink-0 px-2 py-0.5 rounded-lg bg-tuan-input border border-tuan-border text-[12px] text-tuan-text hover:bg-tuan-hover transition-colors"
                  >
                    重试
                  </button>
                )}
              </div>
            </div>
          )}
          {providers.length === 0 && (
            <div className="mt-6 w-full max-w-[672px] rounded-2xl border border-dashed border-tuan-border bg-tuan-input px-5 py-4 text-center">
              <div className="text-[14px] text-tuan-text font-medium">还没有配置供应商</div>
              <div className="mt-1 text-[12.5px] text-tuan-textSecondary">
                在「设置」里选一个官方平台并填入密钥，即可开始对话
              </div>
              <div className="mt-3 flex items-center justify-center gap-3">
                {onOpenSettings && (
                  <button onClick={onOpenSettings} className="cc-btn-primary h-9 px-4 text-[13.5px]">
                    去配置供应商
                  </button>
                )}
                {onOpenGuide && (
                  <button onClick={onOpenGuide} className="cc-btn-ghost h-9 px-4 text-[13.5px]">
                    使用教程
                  </button>
                )}
              </div>
            </div>
          )}
        </div>
      ) : (
        <>
          {/* 聊天页常驻头部（Claude Code 桌面 session header）：
              左=对话标题，右=模式风险徽标 + 供应商·模型上下文条 + 新建。
              把模式/模型从"埋在输入行"提升为全局可见。 */}
          <div className="flex items-center gap-2 h-12 px-4 flex-none border-b border-tuan-border bg-tuan-bg">
            <div className="flex-1 min-w-0">
              <div className="text-[14px] font-medium text-tuan-text truncate">
                {title || messages[0]?.content.slice(0, 24) || '新对话'}
              </div>
            </div>
            <span
              className="cc-pill mode-pill flex-none hidden sm:inline-flex"
              data-level={getMode(mode).level}
            >
              {getMode(mode).name}
            </span>
            {activeProvider && (
              <span className="text-[12.5px] text-tuan-textSecondary truncate max-w-[160px] hidden lg:block">
                {activeProvider.name}
                {model ? ` · ${model}` : ''}
              </span>
            )}
            {onNewChat && (
              <button
                onClick={onNewChat}
                className="cc-btn-ghost w-9 h-9 !p-0 flex-none"
                title="新建对话"
              >
                <Plus size={18} />
              </button>
            )}
          </div>
          <div className="relative flex-1 min-h-0">
            <div ref={scrollRef} className="absolute inset-0 overflow-y-auto chat-scroll">
              <div className="w-full mx-auto px-4 py-8" style={{ maxWidth: 768 }}>
              {hasOlder && (
                <div className="flex justify-center py-3">
                  <button
                    onClick={loadOlder}
                    className="text-[12.5px] text-tuan-textSecondary px-3 py-1.5 rounded-lg border border-tuan-border hover:bg-tuan-hover"
                  >
                    加载更早的消息（还有 {messages.length - visibleCount} 条）
                  </button>
                </div>
              )}
              {visibleMessages.map((m, idx) => {
                const realIdx = messages.length - visibleCount + idx;
                const isLast = realIdx === messages.length - 1;
                const isStreamingMsg = isLast && streaming && m.role === 'assistant';
                return m.role === 'user' ? (
                  <div key={m.id} className="flex flex-col items-end mb-3 group">
                    {editingMsgId === m.id ? (
                      <div className="w-full max-w-[85%]">
                        <textarea
                          autoFocus
                          value={editDraft}
                          onChange={(e) => setEditDraft(e.target.value)}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter' && !e.shiftKey) {
                              e.preventDefault();
                              saveEdit();
                            }
                            if (e.key === 'Escape') cancelEdit();
                          }}
                          rows={3}
                          className="w-full bg-tuan-input border border-tuan-border rounded-xl px-3 py-2 text-[15px] leading-relaxed text-tuan-text outline-none resize-none"
                        />
                        <div className="flex gap-2 mt-2">
                          <button onClick={saveEdit} className="cc-btn-primary px-3 py-1.5 text-[12.5px]">
                            保存
                          </button>
                          <button onClick={cancelEdit} className="cc-btn-ghost px-3 py-1.5 text-[12.5px]">
                            取消
                          </button>
                        </div>
                      </div>
                    ) : (
                      <>
                        <div className="max-w-[85%] w-fit bg-tuan-hover text-tuan-text px-3.5 py-2.5 text-[16px] leading-relaxed font-[350] whitespace-pre-wrap break-words rounded-2xl">
                          {m.content}
                        </div>
                        {m.ts && (
                          <span className="text-[12px] text-tuan-textSecondary mt-1 pr-1">
                            {formatRelativeTime(m.ts)}
                          </span>
                        )}
                        <div className="mt-1 flex items-center gap-2 opacity-0 group-hover:opacity-100 transition-opacity">
                          {onEditMessage && (
                            <button
                              onClick={() => startEdit(m.id, m.content)}
                              className="inline-flex items-center gap-1 text-[12px] text-tuan-textSecondary hover:text-tuan-text"
                              title="编辑消息"
                            >
                              <Pencil size={12} />
                              编辑
                            </button>
                          )}
                          {onDeleteMessage && (
                            <button
                              onClick={() => onDeleteMessage(m.id)}
                              className="inline-flex items-center gap-1 text-[12px] text-tuan-textSecondary hover:text-[var(--tuan-danger)]"
                              title="删除消息"
                            >
                              <Trash2 size={12} />
                              删除
                            </button>
                          )}
                        </div>
                      </>
                    )}
                  </div>
                ) : (
                  <div key={m.id} className="flex gap-2.5 my-3">
                    {/* 头像：常态缓慢自转/呼吸，思考时加速 + 外圈扩散环，
                        三重信号共同表达"正在生成"。
                        扩散环要溢出头像边界，故定位在外层，内层才裁剪。 */}
                    <div className="relative w-8 h-8 flex-none">
                      <div className="w-8 h-8 rounded-lg overflow-hidden flex items-center justify-center bg-tuan-artBg border border-tuan-border">
                        <img
                          src={mascot.img}
                          alt={mascot.name}
                          title={mascot.name}
                          className={`tuan-art-img w-full h-full object-cover ${isStreamingMsg ? 'awa-breathe-thinking' : 'awa-breathe'}`}
                        />
                      </div>
                      {isStreamingMsg && <span className="think-ring absolute inset-0 rounded-lg" />}
                    </div>
                    <div className="flex-1 min-w-0 text-tuan-text text-[16.5px] leading-normal group">
                      <div className="flex items-center gap-1.5 mb-1.5 -mt-0.5">
                        <span className="text-[12px] text-tuan-textSecondary leading-none">
                          {mascot.name}
                          {m.model ? ` · ${m.model}` : ''}
                        </span>
                      </div>
                      {m.reasoning ? (
                        <ThoughtBlock
                          text={m.reasoning}
                          streaming={!!isStreamingMsg}
                          startedAt={streamStartRef.current}
                        />
                      ) : (
                        isStreamingMsg && (
                          <div className="mb-2 rounded-2xl border border-tuan-border bg-tuan-input px-3 py-2 text-[13px] text-tuan-textSecondary inline-flex items-center gap-2">
                            <Spinner />
                            思考中…
                          </div>
                        )
                      )}
                      {/* 工具调用卡：渲染在本轮回复之前 */}
                      {isStreamingMsg && tools.length > 0 && <ToolStack tools={tools} />}
                      {m.content ? (
                        <div className="reply-card">
                          <ReplyMarkdown text={m.content} streaming={!!isStreamingMsg} />
                          {isStreamingMsg && <span className="cc-cursor" />}
                        </div>
                      ) : (
                        isStreamingMsg && (
                          <div className="text-[14px] text-tuan-textSecondary inline-flex items-center gap-1.5">
                            <Spinner />
                            <span>正在生成…</span>
                          </div>
                        )
                      )}
                      <div className="mt-1.5 flex items-center gap-2 opacity-0 group-hover:opacity-100 transition-opacity">
                        {onRetry && isLast && !isStreamingMsg && (
                          <button
                            onClick={onRetry}
                            className="inline-flex items-center gap-1 text-[12px] text-tuan-textSecondary hover:text-tuan-text"
                            title="重新生成回复"
                          >
                            <RotateCcw size={13} />
                            重试
                          </button>
                        )}
                        <button
                          onClick={() => copyText(m.id, m.content)}
                          className="inline-flex items-center gap-1 text-[12px] text-tuan-textSecondary hover:text-tuan-text"
                          title="复制回复"
                        >
                          {copiedId === m.id ? <Check size={13} /> : <Copy size={13} />}
                          {copiedId === m.id ? '已复制' : '复制'}
                        </button>
                        {onDeleteMessage && (
                          <button
                            onClick={() => onDeleteMessage(m.id)}
                            className="inline-flex items-center gap-1 text-[12px] text-tuan-textSecondary hover:text-[var(--tuan-danger)]"
                            title="删除消息"
                          >
                            <Trash2 size={13} />
                            删除
                          </button>
                        )}
                      </div>
                    </div>
                  </div>
                );
              })}
              {error && (
                <div className="text-[13px] text-[var(--tuan-danger)] bg-[var(--tuan-danger-bg)] px-3 py-2 rounded-xl my-2">
                  <div className="flex items-start gap-2">
                    <span className="flex-1">{error}</span>
                    {onRetry && (
                      <button
                        onClick={onRetry}
                        className="flex-shrink-0 px-2 py-0.5 rounded-lg bg-tuan-input border border-tuan-border text-[12px] text-tuan-text hover:bg-tuan-hover transition-colors"
                      >
                        重试
                      </button>
                    )}
                  </div>
                </div>
              )}
            </div>
            </div>
            {/* 回到底部按钮：用户上滚查看历史时浮出，点击平滑滚回最新消息 */}
            {showScrollBtn && !streaming && (
              <button
                onClick={scrollToBottom}
                className="scroll-bottom-btn absolute left-1/2 -translate-x-1/2 z-30 w-8 h-8 rounded-full bg-tuan-input border border-tuan-border shadow-[var(--shadow-pop)] flex items-center justify-center text-tuan-textSecondary hover:text-tuan-text transition-all"
                title="回到底部"
              >
                <ChevronDown size={16} />
              </button>
            )}
          </div>
          {/* 危险操作审批卡：引擎在阻塞等答复，固定贴在输入框上方，不随消息流滚走 */}
          {approval && onApprove && (
            <div className="relative px-3 pt-2 w-full">
              <ApprovalCard approval={approval} onApprove={onApprove} />
            </div>
          )}
          <div id="inputbar" className="input-dock relative px-3 pb-3 pt-2 w-full">
            <div className="mx-auto w-full max-w-[768px]">{card}</div>
          </div>
          {/* 底部状态栏（CodeX 风格 status line）：
              左=模式徽标 + 模型 · 供应商 + 消息数；右=免责声明 + ⌘K 入口 */}
          <div className="footer-note h-7 flex items-center gap-2 border-t border-tuan-border/60 px-4 text-[11px] text-tuan-textSecondary flex-none">
            <span
              className="cc-pill mode-pill flex-none !h-[18px] !px-1.5 !py-0 !text-[10.5px] leading-none"
              data-level={getMode(mode).level}
            >
              {getMode(mode).name}
            </span>
            {activeProvider && (
              <span className="truncate max-w-[42%]">
                {model || enabledModels[0]?.id || '未选模型'} · {activeProvider.name}
              </span>
            )}
            <span className="hidden sm:inline">· {messages.length} 条消息</span>
            <div className="flex-1" />
            <span className="hidden sm:inline truncate">由 AI 生成，可能出错，请仔细核对</span>
            {onOpenPalette && (
              <button
                onClick={onOpenPalette}
                className="cc-kbd flex-none hover:text-tuan-text transition-colors"
                title="命令面板（⌘K）"
              >
                ⌘K
              </button>
            )}
          </div>
        </>
      )}
    </div>
  );
}
