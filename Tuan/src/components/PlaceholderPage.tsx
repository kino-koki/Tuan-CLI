interface Props {
  title: string;
  description: string;
  hint?: string;
}

/** Design-matched empty shell for modules that are iterated in later passes. */
export default function PlaceholderPage({ title, description, hint }: Props) {
  return (
    <div className="page-shell flex-1 overflow-y-auto custom-scrollbar">
      <h1 className="text-[20px] font-semibold text-tuan-text mb-1">{title}</h1>
      <p className="text-[13.5px] text-tuan-textSecondary mb-8">{description}</p>
      <div className="border border-dashed border-tuan-border rounded-2xl py-16 flex flex-col items-center text-center">
        <div className="w-10 h-10 rounded-xl bg-tuan-hover flex items-center justify-center text-tuan-textSecondary mb-3">
          <span className="text-lg">T</span>
        </div>
        <div className="text-[14px] font-medium text-tuan-text">{title}</div>
        <div className="text-[12.5px] text-tuan-textSecondary mt-1 max-w-sm">{hint ?? '模块已预留，将在后续迭代中补齐。'}</div>
      </div>
    </div>
  );
}
