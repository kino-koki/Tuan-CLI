import { useEffect, useState } from 'react';
import { Blocks, Plus, Trash2, Plug } from 'lucide-react';

interface McpServer {
  id: string;
  name: string;
  transport: 'stdio' | 'sse';
  command: string;
  url: string;
  args: string;
}

const KEY = 'tuan.mcp.servers';

export default function McpPage() {
  const [list, setList] = useState<McpServer[]>(() => {
    try {
      return JSON.parse(localStorage.getItem(KEY) || '[]');
    } catch {
      return [];
    }
  });
  const [form, setForm] = useState<{ name: string; transport: 'stdio' | 'sse'; command: string; url: string; args: string }>({
    name: '', transport: 'stdio', command: '', url: '', args: '',
  });

  useEffect(() => {
    localStorage.setItem(KEY, JSON.stringify(list));
  }, [list]);

  const add = () => {
    if (!form.name.trim() || (form.transport === 'stdio' ? !form.command.trim() : !form.url.trim())) return;
    setList((p) => [
      ...p,
      { id: crypto.randomUUID(), ...form, args: form.args },
    ]);
    setForm({ name: '', transport: 'stdio', command: '', url: '', args: '' });
  };

  const remove = (id: string) => setList((p) => p.filter((s) => s.id !== id));

  return (
    <div className="page-shell flex-1 overflow-y-auto custom-scrollbar">
      <h1 className="text-[20px] font-semibold text-tuan-text mb-1">MCP 服务</h1>
      <p className="text-[13.5px] text-tuan-textSecondary mb-5">
        连接 Model Context Protocol 服务，为助手扩展工具能力。
      </p>

      <div className="max-w-[760px] bg-tuan-input border border-tuan-border rounded-xl p-5 space-y-4 mb-5">
        <div className="flex items-center gap-2 font-medium text-tuan-text">
          <Plus size={16} /> 添加 MCP 服务
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <label className="block">
            <span className="text-[12px] text-tuan-textSecondary">名称</span>
            <input
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              placeholder="例如：filesystem"
              className="mt-1 w-full bg-tuan-input border border-tuan-border rounded-lg px-3 py-2 text-[13.5px] text-tuan-text outline-none"
            />
          </label>
          <label className="block">
            <span className="text-[12px] text-tuan-textSecondary">传输方式</span>
            <select
              value={form.transport}
              onChange={(e) => setForm({ ...form, transport: e.target.value as 'stdio' | 'sse' })}
              className="mt-1 w-full bg-tuan-input border border-tuan-border rounded-lg px-3 py-2 text-[13.5px] text-tuan-text outline-none"
            >
              <option value="stdio">stdio（本地命令）</option>
              <option value="sse">SSE（远程地址）</option>
            </select>
          </label>
        </div>
        {form.transport === 'stdio' ? (
          <label className="block">
            <span className="text-[12px] text-tuan-textSecondary">启动命令</span>
            <input
              value={form.command}
              onChange={(e) => setForm({ ...form, command: e.target.value })}
              placeholder="例如：npx -y @modelcontextprotocol/server-filesystem"
              className="mt-1 w-full bg-tuan-input border border-tuan-border rounded-lg px-3 py-2 text-[13.5px] text-tuan-text outline-none"
            />
          </label>
        ) : (
          <label className="block">
            <span className="text-[12px] text-tuan-textSecondary">SSE 地址</span>
            <input
              value={form.url}
              onChange={(e) => setForm({ ...form, url: e.target.value })}
              placeholder="https://example.com/sse"
              className="mt-1 w-full bg-tuan-input border border-tuan-border rounded-lg px-3 py-2 text-[13.5px] text-tuan-text outline-none"
            />
          </label>
        )}
        <label className="block">
          <span className="text-[12px] text-tuan-textSecondary">参数（空格分隔，可选）</span>
          <input
            value={form.args}
            onChange={(e) => setForm({ ...form, args: e.target.value })}
            placeholder="例如：/path/to/dir"
            className="mt-1 w-full bg-tuan-input border border-tuan-border rounded-lg px-3 py-2 text-[13.5px] text-tuan-text outline-none"
          />
        </label>
        <button
          onClick={add}
          className="cc-btn-primary px-5 py-2 text-[13px] font-medium"
        >
          添加服务
        </button>
      </div>

      <div className="max-w-[760px] space-y-2">
        {list.length === 0 && (
          <div className="border border-dashed border-tuan-border rounded-xl py-16 flex flex-col items-center text-center px-4">
            <div className="w-14 h-14 rounded-xl bg-tuan-hover flex items-center justify-center mb-3">
              <Blocks size={24} className="text-tuan-textSecondary" />
            </div>
            <div className="text-[14px] font-medium text-tuan-text mb-1">还没有添加 MCP 服务</div>
            <div className="text-[12.5px] text-tuan-textSecondary mt-1 max-w-sm leading-relaxed">
              连接 Model Context Protocol 服务，为助手扩展工具能力，比如文件系统访问、数据库查询或网络搜索。
            </div>
          </div>
        )}
        {list.map((s) => (
          <div key={s.id} className="flex items-center gap-3 bg-tuan-input border border-tuan-border rounded-xl px-4 py-3">
            <Plug size={18} className="text-tuan-textSecondary flex-shrink-0" />
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2">
                <span className="text-[14.5px] font-medium text-tuan-text">{s.name}</span>
                <span className={`text-[10.5px] px-1.5 py-0.5 rounded-full font-medium ${
                  s.transport === 'stdio'
                    ? 'bg-tuan-hover text-tuan-textSecondary'
                    : 'bg-[var(--tuan-ok-bg)] text-[var(--tuan-ok)]'
                }`}>
                  {s.transport === 'stdio' ? '本地' : '远程'}
                </span>
              </div>
              <div className="text-[12.5px] text-tuan-textSecondary mt-0.5 truncate">
                {s.transport === 'stdio' ? s.command : s.url}
              </div>
            </div>
            <button onClick={() => remove(s.id)} className="p-1.5 rounded-lg text-[var(--tuan-danger)] hover:bg-[var(--tuan-danger-bg)]" title="删除">
              <Trash2 size={15} />
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
