import { useState } from 'react';
import { Wrench, Blocks, Upload, Plus } from 'lucide-react';

type Tab = 'skills' | 'connectors';

export default function CustomizePage() {
  const [tab, setTab] = useState<Tab>('skills');

  return (
    <div className="page-shell flex-1 overflow-y-auto custom-scrollbar">
      <h1 className="text-[20px] font-semibold text-tuan-text mb-1">个性化</h1>
      <p className="text-[13.5px] text-tuan-textSecondary mb-5">
        创建技能、连接应用，打造属于你的工作流。
      </p>

      <div className="flex gap-1 bg-tuan-hover rounded-full p-1 w-fit mb-6">
        {(
          [
            { key: 'skills', label: '技能', icon: Wrench },
            { key: 'connectors', label: '连接器', icon: Blocks },
          ] as const
        ).map(({ key, label, icon: Icon }) => (
          <button
            key={key}
            onClick={() => setTab(key)}
            className={`flex items-center gap-1.5 px-3.5 py-1.5 rounded-full text-[13px] font-medium transition-colors ${
              tab === key ? 'bg-tuan-input text-tuan-text shadow-sm' : 'text-tuan-textSecondary hover:text-tuan-text'
            }`}
          >
            <Icon size={15} /> {label}
          </button>
        ))}
      </div>

      {tab === 'skills' ? (
        <div className="max-w-[720px] space-y-4">
          <div className="flex gap-2">
            <button className="cc-btn-primary px-3.5 py-2 text-[13px] font-medium">
              <Plus size={15} /> 新建技能
            </button>
            <button className="cc-btn-ghost px-3.5 py-2 text-[13px]">
              <Upload size={15} /> 导入技能
            </button>
          </div>
          <div className="border border-dashed border-tuan-border rounded-xl py-14 text-center text-[13.5px] text-tuan-textSecondary">
            还没有技能。编写技能说明，让助手按你的方式完成任务。
          </div>
        </div>
      ) : (
        <div className="max-w-[720px]">
          <div className="border border-dashed border-tuan-border rounded-xl py-14 text-center text-[13.5px] text-tuan-textSecondary">
            还没有连接任何应用。从应用目录选择并授权后即可使用。
          </div>
        </div>
      )}
    </div>
  );
}
