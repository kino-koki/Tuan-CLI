/**
 * 上下文查看面板 (Context View Panel) —— 模块 3 的详情视图。
 *
 * 点击状态栏 ctx 进度条弹出：展示当前会话的上下文构成（估算 token / 窗口 /
 * 消息数 / 字符数）与全部会话排行。滚动容器 overflow-y: auto,
 * 鼠标滚轮可直接滚动 —— 满足「上下文查看新增可使用鼠标滚轮滚动」。
 */
import { useEffect, useState } from 'react';
import { fetchContextDetail, gaugeColor, gaugeLabel, type ContextDetail } from '../platform/context';
import { X } from 'lucide-react';

export default function ContextViewPanel({
  convId,
  onClose,
}: {
  convId?: string;
  onClose: () => void;
}) {
  const [detail, setDetail] = useState<ContextDetail | null>(null);
  const [busy, setBusy] = useState(true);

  useEffect(() => {
    let alive = true;
    setBusy(true);
    fetchContextDetail(convId)
      .then((d) => {
        if (alive) setDetail(d);
      })
      .finally(() => {
        if (alive) setBusy(false);
      });
    return () => {
      alive = false;
    };
  }, [convId]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const cur = detail?.current;
  const curRatio = cur && detail ? Math.min(cur.estTokens / detail.window, 2) : 0;

  return (
    <div
      className="fixed inset-0 z-[120] flex items-center justify-center p-4"
      role="dialog"
      aria-modal="true"
      aria-label="上下文查看"
    >
      {/* 遮罩: 点击关闭 */}
      <div className="absolute inset-0 bg-black/40" onClick={onClose} />
      <div className="relative w-full max-w-[520px] max-h-[70vh] flex flex-col rounded-2xl border border-tuan-border bg-tuan-main shadow-2xl">
        {/* 头部 */}
        <div className="flex items-center gap-2 px-4 h-12 border-b border-tuan-border flex-none">
          <span className="text-[14px] font-semibold text-tuan-text">上下文查看</span>
          <span className="text-[11.5px] text-tuan-textSecondary font-mono">
            est. ~3 字符/token
          </span>
          <button
            onClick={onClose}
            className="ml-auto cc-btn-ghost w-8 h-8 !p-0 flex items-center justify-center"
            title="关闭 (Esc)"
          >
            <X size={15} />
          </button>
        </div>

        {/* 滚动主体: 鼠标滚轮可滚动 */}
        <div className="overflow-y-auto p-4 space-y-3 min-h-0 context-panel-scroll">
          {busy && <div className="text-[13px] text-tuan-textSecondary py-6 text-center">加载中…</div>}
          {!busy && !detail && (
            <div className="text-[13px] text-tuan-textSecondary py-6 text-center">
              引擎未就绪，无法读取上下文
            </div>
          )}
          {detail && (
            <>
              {/* 当前会话卡片 */}
              <div className="rounded-xl border border-tuan-border p-3 bg-tuan-input">
                <div className="flex items-center justify-between mb-1.5">
                  <span className="text-[13px] font-medium text-tuan-text truncate max-w-[240px]">
                    {cur ? cur.title : '当前会话'}
                  </span>
                  <span className="text-[12px] font-mono" style={{ color: gaugeColor(curRatio) }}>
                    {gaugeLabel(curRatio)}
                  </span>
                </div>
                <div className="h-2 rounded-full bg-[var(--border-tuan)] overflow-hidden">
                  <div
                    className="h-full rounded-full transition-all"
                    style={{ width: `${Math.min(curRatio, 1) * 100}%`, background: gaugeColor(curRatio) }}
                  />
                </div>
                {cur && (
                  <div className="mt-2 grid grid-cols-3 gap-2 text-center">
                    <div className="rounded-lg bg-tuan-hover py-1.5">
                      <div className="text-[15px] font-mono text-tuan-text">{cur.estTokens.toLocaleString()}</div>
                      <div className="text-[11px] text-tuan-textSecondary">估算 token</div>
                    </div>
                    <div className="rounded-lg bg-tuan-hover py-1.5">
                      <div className="text-[15px] font-mono text-tuan-text">{cur.messages}</div>
                      <div className="text-[11px] text-tuan-textSecondary">消息数</div>
                    </div>
                    <div className="rounded-lg bg-tuan-hover py-1.5">
                      <div className="text-[15px] font-mono text-tuan-text">{(cur.chars / 1000).toFixed(1)}k</div>
                      <div className="text-[11px] text-tuan-textSecondary">字符</div>
                    </div>
                  </div>
                )}
                <div className="mt-2 text-[11.5px] text-tuan-textSecondary">
                  窗口上限 {detail.window.toLocaleString()} tokens · 全部会话合计{' '}
                  {detail.totalEstTokens.toLocaleString()} tokens
                </div>
              </div>

              {/* 全部会话排行 */}
              <div>
                <div className="text-[12px] font-medium text-tuan-textSecondary mb-1.5">
                  全部会话（{detail.sessions.length}）
                </div>
                {detail.sessions.length === 0 && (
                  <div className="text-[12.5px] text-tuan-textSecondary py-3 text-center">
                    暂无会话数据
                  </div>
                )}
                <div className="space-y-1.5">
                  {detail.sessions.map((s) => {
                    const r = Math.min(s.estTokens / detail.window, 2);
                    return (
                      <div
                        key={s.id}
                        className={`flex items-center gap-2 rounded-lg px-2.5 py-1.5 text-[12.5px] ${s.id === convId ? 'bg-tuan-hover ring-1 ring-[var(--border-tuan)]' : ''}`}
                        title={s.id}
                      >
                        <span className="flex-1 truncate text-tuan-text">{s.title}</span>
                        <span className="w-16 h-1.5 rounded-full bg-[var(--border-tuan)] overflow-hidden flex-none">
                          <span
                            className="block h-full rounded-full"
                            style={{ width: `${Math.min(r, 1) * 100}%`, background: gaugeColor(r) }}
                          />
                        </span>
                        <span className="font-mono text-tuan-textSecondary w-[64px] text-right flex-none">
                          {s.estTokens.toLocaleString()}
                        </span>
                      </div>
                    );
                  })}
                </div>
              </div>

              <div className="text-[11.5px] text-tuan-textSecondary leading-relaxed">
                <span className="font-medium text-tuan-text">提示：</span>
                占用超过 70% 建议执行 <span className="font-mono">/compact</span> 压缩上下文；
                超过 100% 模型可能开始截断早期内容。数字为估算值（约 3 字符/token），
                非精确分词。
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
