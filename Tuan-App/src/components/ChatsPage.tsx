import { useState } from 'react';
import { Search, Trash2, Pencil, Check, X, MessageSquare, Download } from 'lucide-react';
import type { Conversation } from '../types';

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

  const filtered = conversations.filter(
    (c) => !query.trim() || c.title.toLowerCase().includes(query.trim().toLowerCase()),
  );

  const commitRename = (id: string) => {
    if (draft.trim()) onRename(id, draft.trim());
    setRenaming(null);
    setDraft('');
  };

  const exportConversation = (conv: Conversation) => {
    const lines = [
      `# ${conv.title}`,
      ``,
      `导出时间：${new Date().toLocaleString('zh-CN')}`,
      ``,
      '---',
      ``,
    ];
    for (const m of conv.messages) {
      const time = new Date(m.ts).toLocaleString('zh-CN');
      const role = m.role === 'user' ? '我' : '助手';
      lines.push(`**${role}** (${time})`);
      lines.push(``);
      lines.push(m.content);
      lines.push(``);
      lines.push('---');
      lines.push(``);
    }
    const blob = new Blob([lines.join('\n')], { type: 'text/markdown' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${conv.title.replace(/[/\\:*?"<>|]/g, '_')}.md`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="page-shell flex-1 overflow-y-auto custom-scrollbar">
      <h1 className="text-[20px] font-semibold text-tuan-text mb-1">聊天</h1>
      <p className="text-[13.5px] text-tuan-textSecondary mb-5">按时间排列的全部对话记录。</p>

      <div className="max-w-[720px] mb-4">
        <div className="flex items-center gap-2 bg-tuan-input border border-tuan-border rounded-lg px-3 py-2">
          <Search size={16} className="text-tuan-textSecondary" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="搜索对话标题"
            className="flex-1 bg-transparent outline-none text-[13.5px] text-tuan-text placeholder:text-tuan-textSecondary"
          />
        </div>
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
                ? '试试其他关键词。'
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
                <button
                  onClick={(e) => { e.stopPropagation(); exportConversation(c); }}
                  className="p-1.5 rounded-lg text-tuan-textSecondary hover:bg-tuan-hover"
                  title="导出为 Markdown"
                >
                  <Download size={15} />
                </button>
                <button
                  onClick={(e) => { e.stopPropagation(); onDelete(c.id); }}
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
