import { Package } from 'lucide-react';

export default function ArtifactsPage() {
  return (
    <div className="page-shell flex-1 overflow-y-auto custom-scrollbar">
      <h1 className="text-[20px] font-semibold text-tuan-text mb-1">成品</h1>
      <p className="text-[13.5px] text-tuan-textSecondary mb-6">
        对话中生成的可运行成品会集中展示在这里。
      </p>
      <div className="border border-dashed border-tuan-border rounded-xl py-20 flex flex-col items-center text-center px-4">
        <div className="w-16 h-16 rounded-2xl bg-tuan-hover flex items-center justify-center mb-4">
          <Package size={28} className="text-tuan-textSecondary" />
        </div>
        <div className="text-[15px] font-medium text-tuan-text mb-1">暂无成品</div>
        <div className="text-[13px] text-tuan-textSecondary mt-1 max-w-md leading-relaxed">
          在对话中让助手生成网页、工具或文档后，成品会出现在这里。
          比如让它写一个待办清单小工具、生成一份 Markdown 报告，或搭建一个网页原型。
        </div>
      </div>
    </div>
  );
}
