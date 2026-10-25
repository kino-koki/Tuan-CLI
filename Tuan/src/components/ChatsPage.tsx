import { useEffect, useState } from 'react';
import { Search, Trash2, Pencil, Check, X, MessageSquare, FileText, FileJson, AlertTriangle, Eraser } from 'lucide-react';
import type { Conversation } from '../types';
import {
  exportConversationMarkdown,
  exportConversationJson,
  exportAllConversationsMarkdown,
  exportAllConversationsJson,
  isAppOnline,
  onOnlineStatusChange,
} from '../platform/sessions';

interface Props {
  conversations: Conversation[];
  activeId?: string;
  onOpen: (id: string) => void;
  onDelete: (id: string) => void;
  onRename: (id: string, title: string) => void;
}

function fmt(ts: number) {
  const d = new Date(ts);
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export default function ChatsPage({ conversations, activeId, onOpen, onDelete, onRename }: Props) {
  const [query, setQuery] = useState('');
  const [renaming, setRenaming] = useState<string | null>(null);
  const [draft, setDraft] = useState('');
  // T-6.2 离线状态：断网时展示离线提示，列表读本地缓存（即当前 localStorage 会话）
  const [online, setOnline] = useState<boolean>(() => isAppOnline());

  useEffect(() => onOnlineStatusChange(setOnline), []);

  // T-3.2 实时过滤：标题 + 消息内容
  const q = query.trim().toLowerCase();
  const filtered = conversations.filter(
    (c) =>
      !q ||
      c.title.toLowerCase().includes(q) ||
      c.messages.some((m) => (m.content || '').toLowerCase().includes(q)),
  );

  const commitRename = (id: string) => {
    if (draft.trim()) onRename(id, draft.trim());
    setRenaming(null);
    setDraft('');
  };

  // T-3.5 删除二次确认
  const requestDelete = (id: string) => {
    const ok = window.confirm('确定删除这条对话？删除后无法恢复。');
    if (ok) onDelete(id);
  };

  // T-3.5 全部清空：二次确认后逐条删除（App 的 onDelete 会同步更新当前会话指针）
  const requestClearAll = () => {
    if (conversations.length === 0) return;
    const ok = window.confirm(
      `确定清空全部 ${conversations.length} 条对话？\n此操作不可恢复，建议先导出备份。`,
    );
    if (!ok) return;
    for (const c of conversations) onDelete(c.id);
  };

  return (
    <div className="page-shell flex-1 overflow-y-auto custom-scrollbar">
      <div className="flex items-center gap-3 mb-1">
        <h1 className="text-[20px] font-semibold text-tuan-text">聊天</h1>
        {/* T-6.2 离线指示器：断网时明确告知当前展示的是本地缓存 */}
        {!online && (
          <span className="flex items-center gap-1 rounded-full bg-amber-50 dark:bg-amber-950/40 border border-amber-200 dark:border-amber-800 px-2 py-0.5 text-[11px] text-amber-700 dark:text-amber-300">
            <AlertTriangle size={11} />
            离线模式 · 展示本地缓存
          </span>
        )}
      </div>
      <p className="text-[13.5px] text-tuan-textSecondary mb-5">按时间排列的全部对话记录。</p>

      <div className="max-w-[720px] mb-3 flex items-center gap-2">
        <div className="flex-1 flex items-center gap-2 bg-tuan-input border border-tuan-border rounded-lg px-3 py-2">
          <Search size={16} className="text-tuan-textSecondary" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="搜索对话标题或内容"
            className="flex-1 bg-transparent outline-none text-[13.5px] text-tuan-text placeholder:text-tuan-textSecondary"
          />
          {query && (
            <button onClick={() => setQuery('')} className="text-tuan-textSecondary hover:text-tuan-text">
              <X size={14} />
            </button>
          )}
        </div>
        {/* T-3.4 全部导出：Markdown / JSON 两个入口 */}
        <button
          onClick={() => exportAllConversationsMarkdown(conversations)}
          disabled={conversations.length === 0}
          className="flex items-center gap-1.5 rounded-lg border border-tuan-border px-2.5 py-2 text-[12.5px] text-tuan-text hover:bg-tuan-hover disabled:opacity-40"
          title="把全部会话合并导出为一个 Markdown 文件"
        >
          <FileText size={14} />
          导出全部 MD
        </button>
        <button
          onClick={() => exportAllConversationsJson(conversations)}
          disabled={conversations.length === 0}
          className="flex items-center gap-1.5 rounded-lg border border-tuan-border px-2.5 py-2 text-[12.5px] text-tuan-text hover:bg-tuan-hover disabled:opacity-40"
          title="把全部会话导出为一个 JSON 文件"
        >
          <FileJson size={14} />
          导出全部 JSON
        </button>
        <button
          onClick={requestClearAll}
          disabled={conversations.length === 0}
          className="flex items-center gap-1.5 rounded-lg border border-[var(--tuan-danger)]/40 px-2.5 py-2 text-[12.5px] text-[var(--tuan-danger)] hover:bg-[var(--tuan-danger-bg)] disabled:opacity-40"
          title="清空全部对话（需二次确认）"
        >
          <Eraser size={14} />
          清空全部
        </button>
      </div>

      <div className="max-w-[720px] space-y-2">
        {filtered.length === 0 && (
          <div className="border border-dashed border-tuan-border rounded-xl py-16 flex flex-col items-center text-center px-4">
            <div className="w-14 h-14 rounded-xl bg-tuan-hover flex items-center justify-center mb-3">
              <MessageSquare size={24} className="text-tuan-textSecondary" />
            </div>
            <div className="text-[14px] font-medium text-tuan-text mb-1">
              {query ? '未找到匹配的对话' : '暂无对话'}
            </div>
            <div className="text-[12.5px] text-tuan-textSecondary mt-1 max-w-sm leading-relaxed">
              {query
                ? '试试其他关键词（支持标题与正文）。'
                : '开始一次新对话，记录会出现在这里。'}
            </div>
          </div>
        )}
        {filtered.map((c) => (
          <div
            key={c.id}
            onClick={() => onOpen(c.id)}
            className={`flex items-center gap-3 border border-tuan-border rounded-xl px-4 py-3 cursor-pointer transition-colors ${
              activeId === c.id ? 'bg-tuan-hover' : 'bg-tuan-input hover:bg-tuan-hover'
            }`}
          >
            <MessageSquare size={18} className="text-tuan-textSecondary shrink-0" />
            {renaming === c.id ? (
              <div className="flex items-center gap-2 flex-1" onClick={(e) => e.stopPropagation()}>
                <input
                  autoFocus
                  value={draft}
                  onChange={(e) => setDraft(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') commitRename(c.id);
                    if (e.key === 'Escape') setRenaming(null);
                  }}
                  className="flex-1 bg-tuan-main border border-tuan-border rounded-lg px-2 py-1 text-[13.5px] outline-none"
                />
                <button onClick={() => commitRename(c.id)} className="p-1 text-green-600"><Check size={16} /></button>
                <button onClick={() => setRenaming(null)} className="p-1 text-tuan-textSecondary"><X size={16} /></button>
              </div>
            ) : (
              <>
                <div className="flex-1 min-w-0">
                  <div className="text-[14px] text-tuan-text truncate">{c.title}</div>
                  <div className="text-[12px] text-tuan-textSecondary mt-0.5 flex items-center gap-2">
                    <span>{fmt(c.updatedAt)}</span>
                    {c.messages?.length ? (
                      <span className="text-tuan-textSecondary/70">· {c.messages.length} 条</span>
                    ) : null}
                  </div>
                </div>
                <button
                  onClick={(e) => { e.stopPropagation(); setRenaming(c.id); setDraft(c.title); }}
                  className="p-1.5 rounded-lg text-tuan-textSecondary hover:bg-tuan-hover"
                  title="重命名"
                >
                  <Pencil size={15} />
                </button>
                {/* T-3.4 单条导出：Markdown */}
                <button
                  onClick={(e) => { e.stopPropagation(); exportConversationMarkdown(c); }}
                  className="p-1.5 rounded-lg text-tuan-textSecondary hover:bg-tuan-hover"
                  title="导出为 Markdown"
                >
                  <FileText size={15} />
                </button>
                {/* T-3.4 单条导出：JSON */}
                <button
                  onClick={(e) => { e.stopPropagation(); exportConversationJson(c); }}
                  className="p-1.5 rounded-lg text-tuan-textSecondary hover:bg-tuan-hover"
                  title="导出为 JSON"
                >
                  <FileJson size={15} />
                </button>
                <button
                  onClick={(e) => { e.stopPropagation(); requestDelete(c.id); }}
                  className="p-1.5 rounded-lg text-[var(--tuan-danger)] hover:bg-[var(--tuan-danger-bg)]"
                  title="删除"
                >
                  <Trash2 size={15} />
                </button>
              </>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
