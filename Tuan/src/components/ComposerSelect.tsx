import { useEffect, useRef, useState, type ReactNode } from 'react';
import { Check, ChevronDown } from 'lucide-react';

export interface SelectOption {
  value: string;
  label: string;
  /** 次要说明：模式 tagline / 供应商模型数，渲染在标签下一行 */
  sub?: string;
  /** 左侧风险点颜色（模式 L0–L4 分档着色） */
  dot?: string;
  /** 前置图标（TRAE/Claude 菜单按钮式：触发钮与弹层选项都显示） */
  icon?: ReactNode;
}

interface Props {
  value: string;
  options: SelectOption[];
  onChange: (v: string) => void;
  title?: string;
  /** 触发按钮附加 class（复用 cc-pill / mode-pill） */
  className?: string;
  /** 模式风险分级：写到触发按钮的 data-level 上，由 CSS 着色 */
  dataLevel?: string;
  disabled?: boolean;
  /** 菜单展开方向：输入区贴屏幕底部，默认向上 */
  placement?: 'top' | 'bottom';
}

/**
 * Claude Code 桌面式 composer 下拉：
 * 触发按钮（pill）+ 向上浮层（勾选项 / 次要说明 / 风险点）。
 * 点击外部或 Esc 关闭；窄屏场景由调用方回落原生 <select>。
 */
export default function ComposerSelect({
  value,
  options,
  onChange,
  title,
  className = 'cc-pill',
  dataLevel,
  disabled,
  placement = 'top',
}: Props) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  // 点击外部关闭（mousedown 早于 click，避免“点开即关”竞争）
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.stopPropagation();
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', onDown);
    document.addEventListener('keydown', onKey, true);
    return () => {
      document.removeEventListener('mousedown', onDown);
      document.removeEventListener('keydown', onKey, true);
    };
  }, [open]);

  const current = options.find((o) => o.value === value);

  return (
    <div ref={rootRef} className="relative flex-none">
      <button
        type="button"
        disabled={disabled}
        data-level={dataLevel}
        data-open={open ? '1' : '0'}
        onClick={() => setOpen((o) => !o)}
        title={title}
        className={`${className} flex items-center gap-1.5 cursor-pointer disabled:cursor-not-allowed`}
      >
        {current?.icon && <span className="flex-none">{current.icon}</span>}
        {current?.dot && (
          <span className="w-1.5 h-1.5 rounded-full flex-none" style={{ background: current.dot }} />
        )}
        <span className="truncate">{current?.label ?? '未选择'}</span>
        <ChevronDown size={13} className="flex-none opacity-70" />
      </button>
      {open && (
        <div
          role="listbox"
          className={`absolute z-40 ${
            placement === 'top' ? 'bottom-full mb-2' : 'top-full mt-2'
          } left-0 min-w-[210px] max-w-[300px] max-h-[300px] overflow-y-auto custom-scrollbar rounded-xl border border-tuan-border bg-tuan-bg p-1.5 shadow-[var(--shadow-pop)]`}
        >
          {options.length === 0 && (
            <div className="px-2.5 py-2 text-[12.5px] text-tuan-textSecondary">暂无可用项</div>
          )}
          {options.map((o) => {
            const selected = o.value === value;
            return (
              <button
                key={o.value}
                type="button"
                role="option"
                aria-selected={selected}
                onClick={() => {
                  onChange(o.value);
                  setOpen(false);
                }}
                className={`flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-left transition-colors hover:bg-tuan-hover ${
                  selected ? 'bg-tuan-hover' : ''
                }`}
              >
                {o.icon && <span className="flex-none">{o.icon}</span>}
                {o.dot && (
                  <span className="w-1.5 h-1.5 rounded-full flex-none" style={{ background: o.dot }} />
                )}
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[13px] text-tuan-text">{o.label}</span>
                  {o.sub && (
                    <span className="block truncate text-[11px] text-tuan-textSecondary">{o.sub}</span>
                  )}
                </span>
                {selected && <Check size={14} className="flex-none text-tuan-textSecondary" />}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
