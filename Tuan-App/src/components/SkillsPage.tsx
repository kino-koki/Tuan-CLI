import { useEffect, useState } from 'react';
import { Wrench, Search, Upload, Check, Download, ChevronDown } from 'lucide-react';

interface BuiltinSkill {
  id: string;
  name: string;
  desc: string;
  source: string;
  pack: string;
}

export default function SkillsPage() {
  const [all, setAll] = useState<BuiltinSkill[]>([]);
  const [query, setQuery] = useState('');
  const [enabled, setEnabled] = useState<Record<string, boolean>>({});
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});

  useEffect(() => {
    fetch('/data/skills.json')
      .then((r) => r.json())
      .then((data: BuiltinSkill[]) => setAll(data))
      .catch(() => setAll([]));
  }, []);

  const filtered = all.filter(
    (s) =>
      !query.trim() ||
      s.name.toLowerCase().includes(query.trim().toLowerCase()) ||
      s.desc.toLowerCase().includes(query.trim().toLowerCase()),
  );

  const toggle = (id: string) => setEnabled((p) => ({ ...p, [id]: !p[id] }));

  const install = () => {
    const path = window.prompt('输入要安装的技能目录或 SKILL.md 路径');
    if (path?.trim()) window.alert('已记录安装路径，将在引擎下次启动时加载：\n' + path.trim());
  };

  return (
    <div className="page-shell flex-1 overflow-y-auto custom-scrollbar">
      <h1 className="text-[20px] font-semibold text-tuan-text mb-1">技能</h1>
      <p className="text-[13.5px] text-tuan-textSecondary mb-5">
        查看并启用 tuan_cli 自带技能，也可以从本地目录安装自定义技能。
      </p>

      <div className="max-w-[760px] flex items-center gap-2 mb-4">
        <div className="flex flex-1 items-center gap-2 bg-tuan-input border border-tuan-border rounded-lg px-3 py-2">
          <Search size={16} className="text-tuan-textSecondary" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="搜索技能名称或说明"
            className="flex-1 bg-transparent outline-none text-[13.5px] text-tuan-text placeholder:text-tuan-textSecondary"
          />
        </div>
        <button
          onClick={install}
          className="cc-btn-ghost px-4 py-2 text-[13px] flex-none"
        >
          <Upload size={15} /> 安装本地技能
        </button>
      </div>

      <div className="max-w-[760px] space-y-2">
        {filtered.length === 0 && (
          <div className="border border-dashed border-tuan-border rounded-xl py-16 flex flex-col items-center text-center px-4">
            <div className="w-14 h-14 rounded-xl bg-tuan-hover flex items-center justify-center mb-3">
              <Wrench size={24} className="text-tuan-textSecondary" />
            </div>
            <div className="text-[14px] font-medium text-tuan-text mb-1">没有匹配的技能</div>
            <div className="text-[12.5px] text-tuan-textSecondary mt-1 max-w-sm leading-relaxed">
              试试其他关键词，或安装本地技能来扩展助手能力。
            </div>
          </div>
        )}
        {filtered.map((s) => {
          const on = !!enabled[s.id];
          const isOpen = !!expanded[s.id];
          const isLong = s.desc.length > 80;
          return (
            <div
              key={s.id}
              className="flex items-start gap-3 bg-tuan-input border border-tuan-border rounded-xl px-4 py-3"
            >
              <div className="h-9 w-9 rounded-lg bg-tuan-hover flex items-center justify-center flex-shrink-0">
                <Wrench size={17} className="text-tuan-textSecondary" />
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className="text-[14.5px] font-medium text-tuan-text">{s.name}</span>
                  <span className="text-[11px] px-2 py-0.5 rounded-full bg-tuan-hover text-tuan-textSecondary">
                    {s.source}
                  </span>
                  {isLong && (
                    <button
                      onClick={() => setExpanded((p) => ({ ...p, [s.id]: !isOpen }))}
                      className="flex items-center gap-0.5 text-[11.5px] text-tuan-textSecondary hover:text-tuan-text"
                    >
                      {isOpen ? '收起' : '展开'}
                      <ChevronDown size={12} className={`transition-transform ${isOpen ? 'rotate-180' : ''}`} />
                    </button>
                  )}
                </div>
                <div className={`text-[13px] text-tuan-textSecondary mt-1 leading-relaxed ${isOpen ? '' : 'line-clamp-2'}`}>
                  {s.desc}
                </div>
              </div>
              <button
                onClick={() => toggle(s.id)}
                className={`${on ? 'cc-btn-primary' : 'cc-btn-ghost'} px-3.5 py-1.5 text-[13px] flex-shrink-0`}
              >
                {on ? <Check size={14} /> : <Download size={14} />}
                {on ? '已启用' : '启用'}
              </button>
            </div>
          );
        })}
      </div>
    </div>
  );
}
