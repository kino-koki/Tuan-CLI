import { useEffect, useState } from 'react';
import { Puzzle, Plus, Trash2 } from 'lucide-react';

interface Plugin {
  id: string;
  name: string;
  desc: string;
}

const KEY = 'tuan.plugins';

export default function PluginsPage() {
  const [list, setList] = useState<Plugin[]>(() => {
    try {
      return JSON.parse(localStorage.getItem(KEY) || '[]');
    } catch {
      return [];
    }
  });
  const [name, setName] = useState('');
  const [desc, setDesc] = useState('');

  useEffect(() => {
    localStorage.setItem(KEY, JSON.stringify(list));
  }, [list]);

  const add = () => {
    if (!name.trim()) return;
    setList((p) => [...p, { id: crypto.randomUUID(), name: name.trim(), desc: desc.trim() }]);
    setName('');
    setDesc('');
  };

  const remove = (id: string) => setList((p) => p.filter((x) => x.id !== id));

  return (
    <div className="page-shell flex-1 overflow-y-auto custom-scrollbar">
      <h1 className="text-[20px] font-semibold text-tuan-text mb-1">插件</h1>
      <p className="text-[13.5px] text-tuan-textSecondary mb-5">
        安装第三方插件，扩展助手的命令与能力。
      </p>

      <div className="max-w-[760px] bg-tuan-input border border-tuan-border rounded-xl p-5 space-y-4 mb-5">
        <div className="flex items-center gap-2 font-medium text-tuan-text">
          <Plus size={16} /> 添加插件
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <label className="block">
            <span className="text-[12px] text-tuan-textSecondary">插件名称</span>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="插件名称"
              className="mt-1 w-full bg-tuan-input border border-tuan-border rounded-lg px-3 py-2 text-[13.5px] text-tuan-text outline-none"
            />
          </label>
          <label className="block">
            <span className="text-[12px] text-tuan-textSecondary">说明（可选）</span>
            <input
              value={desc}
              onChange={(e) => setDesc(e.target.value)}
              placeholder="插件用途"
              className="mt-1 w-full bg-tuan-input border border-tuan-border rounded-lg px-3 py-2 text-[13.5px] text-tuan-text outline-none"
            />
          </label>
        </div>
        <button onClick={add} className="cc-btn-primary px-5 py-2 text-[13px] font-medium">
          添加插件
        </button>
      </div>

      <div className="max-w-[760px] space-y-2">
        {list.length === 0 && (
          <div className="border border-dashed border-tuan-border rounded-xl py-16 flex flex-col items-center text-center px-4">
            <div className="w-14 h-14 rounded-xl bg-tuan-hover flex items-center justify-center mb-3">
              <Puzzle size={24} className="text-tuan-textSecondary" />
            </div>
            <div className="text-[14px] font-medium text-tuan-text mb-1">还没有安装插件</div>
            <div className="text-[12.5px] text-tuan-textSecondary mt-1 max-w-sm leading-relaxed">
              添加插件来扩展助手的命令与能力，比如文件操作、数据分析或第三方服务集成。
            </div>
          </div>
        )}
        {list.map((p) => (
          <div key={p.id} className="flex items-center gap-3 bg-tuan-input border border-tuan-border rounded-xl px-4 py-3">
            <Puzzle size={18} className="text-tuan-textSecondary flex-shrink-0" />
            <div className="flex-1 min-w-0">
              <div className="text-[14.5px] font-medium text-tuan-text">{p.name}</div>
              {p.desc && <div className="text-[12.5px] text-tuan-textSecondary mt-0.5">{p.desc}</div>}
            </div>
            <button onClick={() => remove(p.id)} className="p-1.5 rounded-lg text-[var(--tuan-danger)] hover:bg-[var(--tuan-danger-bg)]" title="删除">
              <Trash2 size={15} />
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
