import { useState } from 'react';
import { Plus, Trash2, FolderKanban, Pencil, Check, X, MessageSquare, Calendar } from 'lucide-react';

export interface Project {
  id: string;
  title: string;
  description: string;
  createdAt: number;
}

interface Props {
  projects: Project[];
  conversations?: { id: string; title: string; projectId?: string; updatedAt: number }[];
  onCreate: (p: Omit<Project, 'id' | 'createdAt'>) => void;
  onUpdate: (id: string, p: Omit<Project, 'id' | 'createdAt'>) => void;
  onDelete: (id: string) => void;
}

export default function ProjectsPage({ projects, conversations = [], onCreate, onUpdate, onDelete }: Props) {
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editTitle, setEditTitle] = useState('');
  const [editDesc, setEditDesc] = useState('');

  // 项目统计
  const stats = {
    total: projects.length,
    totalConversations: conversations.length,
    thisMonth: projects.filter((p) => {
      const now = new Date();
      const pDate = new Date(p.createdAt);
      return pDate.getMonth() === now.getMonth() && pDate.getFullYear() === now.getFullYear();
    }).length,
  };

  const getProjectConversations = (projectId: string) => {
    return conversations.filter((c) => c.projectId === projectId).length;
  };

  const submit = () => {
    if (!title.trim()) return;
    onCreate({ title: title.trim(), description: description.trim() });
    setTitle('');
    setDescription('');
  };

  const startEdit = (p: Project) => {
    setEditingId(p.id);
    setEditTitle(p.title);
    setEditDesc(p.description);
  };

  const commitEdit = () => {
    if (editingId && editTitle.trim()) {
      onUpdate(editingId, { title: editTitle.trim(), description: editDesc.trim() });
    }
    setEditingId(null);
    setEditTitle('');
    setEditDesc('');
  };

  return (
    <div className="page-shell flex-1 overflow-y-auto custom-scrollbar">
      <h1 className="text-[20px] font-semibold text-tuan-text mb-1">项目</h1>
      <p className="text-[13.5px] text-tuan-textSecondary mb-6">
        上传资料、设置自定义指令，在同一空间里归集对话与项目知识。
      </p>

      <div className="max-w-[720px] space-y-5">
        {/* 项目统计 */}
        {projects.length > 0 && (
          <div className="grid grid-cols-3 gap-3">
            <div className="border border-tuan-border rounded-xl p-4 bg-tuan-input text-center">
              <div className="text-[24px] font-semibold text-tuan-text">{stats.total}</div>
              <div className="text-[12px] text-tuan-textSecondary mt-1">总项目数</div>
            </div>
            <div className="border border-tuan-border rounded-xl p-4 bg-tuan-input text-center">
              <div className="text-[24px] font-semibold text-tuan-text">{stats.totalConversations}</div>
              <div className="text-[12px] text-tuan-textSecondary mt-1">关联对话</div>
            </div>
            <div className="border border-tuan-border rounded-xl p-4 bg-tuan-input text-center">
              <div className="text-[24px] font-semibold text-tuan-text">{stats.thisMonth}</div>
              <div className="text-[12px] text-tuan-textSecondary mt-1">本月新增</div>
            </div>
          </div>
        )}

        <div className="border border-tuan-border rounded-xl p-5 bg-tuan-input space-y-3">
          <div className="flex items-center gap-2 font-medium text-tuan-text">
            <Plus size={16} /> 创建个人项目
          </div>
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="项目名称，例如：季度市场计划"
            className="w-full bg-tuan-input border border-tuan-border rounded-lg px-3 py-2 text-[13.5px] text-tuan-text outline-none focus:border-tuan-accent"
          />
          <textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="项目描述，可随时修改"
            rows={2}
            className="w-full bg-tuan-input border border-tuan-border rounded-lg px-3 py-2 text-[13.5px] text-tuan-text outline-none focus:border-tuan-accent resize-none"
          />
          <button
            onClick={submit}
            disabled={!title.trim()}
            className="cc-btn-primary px-5 py-2 text-[13px] font-medium disabled:opacity-40"
          >
            创建项目
          </button>
        </div>

        {projects.length === 0 ? (
          <div className="border border-dashed border-tuan-border rounded-xl py-16 flex flex-col items-center text-center px-4">
            <div className="w-14 h-14 rounded-xl bg-tuan-hover flex items-center justify-center mb-3">
              <FolderKanban size={24} className="text-tuan-textSecondary" />
            </div>
            <div className="text-[14px] font-medium text-tuan-text mb-1">还没有项目</div>
            <div className="text-[12.5px] text-tuan-textSecondary mt-1 max-w-sm leading-relaxed">
              先创建一个项目，把资料和对话组织起来，为不同任务建立专属空间。
            </div>
          </div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            {projects.map((p) => (
              <div key={p.id} className="border border-tuan-border rounded-xl p-4 bg-tuan-input">
                {editingId === p.id ? (
                  <div className="space-y-2">
                    <input
                      autoFocus
                      value={editTitle}
                      onChange={(e) => setEditTitle(e.target.value)}
                      className="w-full bg-tuan-main border border-tuan-border rounded-lg px-3 py-2 text-[13.5px] text-tuan-text outline-none focus:border-tuan-accent"
                    />
                    <textarea
                      value={editDesc}
                      onChange={(e) => setEditDesc(e.target.value)}
                      rows={2}
                      className="w-full bg-tuan-main border border-tuan-border rounded-lg px-3 py-2 text-[13.5px] text-tuan-text outline-none focus:border-tuan-accent resize-none"
                    />
                    <div className="flex gap-2">
                      <button onClick={commitEdit} className="cc-btn-primary px-3 py-1.5 text-[12.5px]">
                        <Check size={13} /> 保存
                      </button>
                      <button onClick={() => setEditingId(null)} className="cc-btn-ghost px-3 py-1.5 text-[12.5px]">
                        <X size={13} /> 取消
                      </button>
                    </div>
                  </div>
                ) : (
                  <>
                    <div className="flex items-center gap-2">
                      <FolderKanban size={18} className="text-tuan-accent" />
                      <span className="font-medium text-tuan-text truncate">{p.title}</span>
                      <div className="ml-auto flex gap-1">
                        <button
                          onClick={() => startEdit(p)}
                          className="p-1.5 rounded-lg text-tuan-textSecondary hover:bg-tuan-hover"
                          title="编辑项目"
                        >
                          <Pencil size={15} />
                        </button>
                        <button
                          onClick={() => onDelete(p.id)}
                          className="p-1.5 rounded-lg text-[var(--tuan-danger)] hover:bg-[var(--tuan-danger-bg)]"
                          title="删除项目"
                        >
                          <Trash2 size={15} />
                        </button>
                      </div>
                    </div>
                    <div className="flex items-center gap-2 mt-2 text-[12px] text-tuan-textSecondary">
                      <Calendar size={12} />
                      <span>{new Date(p.createdAt).toLocaleDateString('zh-CN')}</span>
                      {getProjectConversations(p.id) > 0 && (
                        <span className="flex items-center gap-1">
                          <MessageSquare size={12} />
                          {getProjectConversations(p.id)} 条对话
                        </span>
                      )}
                    </div>
                    <p className="text-[12.5px] text-tuan-textSecondary mt-2 leading-relaxed">
                      {p.description || '暂无描述'}
                    </p>
                  </>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
