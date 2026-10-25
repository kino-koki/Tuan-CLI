import { useEffect, useMemo, useRef, useState } from 'react';
import { BookText, Search, X, ArrowLeft, ArrowRight, FileText } from 'lucide-react';
import ReplyMarkdown from './ReplyMarkdown';
import {
  DOC_ARTICLES,
  DOC_ENGINE_VERSION,
  DOC_GROUPS,
  findDocArticle,
} from '../docs/articles';

interface Props {
  /** 当前文章 id（App 持有，命令面板可深链到具体文章） */
  activeId: string;
  onActiveChange: (id: string) => void;
}

/**
 * 内置技术文档模块。
 *
 * 设计原则：与 Tuan 内部 UI 完全同源——
 * - 页面骨架用 page-shell（安全区）与 GuidePage 一致；
 * - 正文渲染复用 ReplyMarkdown（.tuan-md / .tuan-codeblock），
 *   与聊天里的 Markdown 排版、代码块、复制按钮一模一样；
 * - 导航/搜索/分组的视觉语言复用侧栏模式（分组小标签 + 圆角行 + hover）。
 * 内容随引擎版本内置更新（src/docs/articles.ts），离线可读。
 */
export default function DocsPage({ activeId, onActiveChange }: Props) {
  const [query, setQuery] = useState('');
  const scrollRef = useRef<HTMLDivElement>(null);

  const article = useMemo(() => findDocArticle(activeId) ?? DOC_ARTICLES[0], [activeId]);

  // 文章在全部文章中的序号（上一篇 / 下一篇）
  const index = DOC_ARTICLES.findIndex((a) => a.id === article.id);
  const prev = index > 0 ? DOC_ARTICLES[index - 1] : undefined;
  const next = index >= 0 && index < DOC_ARTICLES.length - 1 ? DOC_ARTICLES[index + 1] : undefined;

  // 搜索：标题 / 简介 / 关键词（大小写不敏感）
  const q = query.trim().toLowerCase();
  const matched = useMemo(() => {
    if (!q) return null;
    return DOC_ARTICLES.filter((a) =>
      [a.title, a.summary, a.keywords, a.id].some((s) => s && s.toLowerCase().includes(q)),
    );
  }, [q]);

  // 切换文章时把滚动容器复位到顶部（page-shell 即滚动容器）
  useEffect(() => {
    scrollRef.current?.scrollTo({ top: 0 });
  }, [article.id]);

  const openArticle = (id: string) => {
    onActiveChange(id);
    setQuery('');
  };

  return (
    <div ref={scrollRef} className="page-shell flex-1 overflow-y-auto custom-scrollbar">
      {/* 页头（与 GuidePage 同构：图标 + 标题 + 副标题） */}
      <div className="flex items-center gap-2 mb-1">
        <BookText size={20} className="text-tuan-textSecondary" />
        <h1 className="text-[20px] font-semibold text-tuan-text">技术文档</h1>
        <span className="ml-1 inline-flex items-center rounded-full border border-tuan-border bg-tuan-input px-2 py-0.5 text-[11px] text-tuan-textSecondary">
          引擎 {DOC_ENGINE_VERSION}
        </span>
      </div>
      <p className="text-[13.5px] text-tuan-textSecondary mb-5">
        青小团的架构、安全模型、调度协议与桌面端实现，全部离线可读。内容随 Tuan 内置更新。
      </p>

      {/* 搜索框（与侧栏搜索同一视觉语言） */}
      <div className="relative mb-4 max-w-[520px]">
        <div className="flex items-center gap-2 bg-tuan-input border border-tuan-border rounded-xl px-3 py-1.5">
          <Search size={14} className="text-tuan-textSecondary flex-shrink-0" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="搜索文档（架构 / 安全 / 路由 / 协议…）"
            className="flex-1 bg-transparent outline-none text-[13px] text-tuan-text placeholder:text-tuan-textSecondary"
          />
          {query && (
            <button onClick={() => setQuery('')} className="text-tuan-textSecondary hover:text-tuan-text">
              <X size={13} />
            </button>
          )}
        </div>
      </div>

      <div className="flex gap-4 items-start">
        {/* 左侧文档导航（桌面端；窄屏退化为下方 chips） */}
        <aside className="hidden md:block w-[230px] flex-none bg-tuan-input border border-tuan-border rounded-xl p-2 sticky top-0">
          {matched ? (
            <div>
              <div className="px-3 pt-2 pb-1 text-[11px] font-medium text-tuan-textSecondary">
                搜索结果 · {matched.length} 篇
              </div>
              {matched.map((a) => (
                <NavItem key={a.id} article={a} active={a.id === article.id} onOpen={openArticle} />
              ))}
              {matched.length === 0 && (
                <div className="px-3 py-6 text-center text-[12.5px] text-tuan-textSecondary">
                  没有匹配的文档
                </div>
              )}
            </div>
          ) : (
            DOC_GROUPS.map((g) => (
              <div key={g.id}>
                <div className="px-3 pt-3 pb-1 text-[11px] font-medium text-tuan-textSecondary">
                  {g.title}
                </div>
                {g.articles.map((a) => (
                  <NavItem key={a.id} article={a} active={a.id === article.id} onOpen={openArticle} />
                ))}
              </div>
            ))
          )}
        </aside>

        {/* 右侧正文 */}
        <div className="flex-1 min-w-0">
          <article className="bg-tuan-input border border-tuan-border rounded-2xl px-5 py-5 sm:px-7 sm:py-6">
            <h2 className="text-[21px] font-semibold text-tuan-heading leading-snug">{article.title}</h2>
            <p className="text-[13.5px] text-tuan-textSecondary mt-1.5">{article.summary}</p>
            <div className="mt-4 border-t border-tuan-border pt-4">
              <ReplyMarkdown text={article.body} />
            </div>
          </article>

          {/* 上一篇 / 下一篇 */}
          <div className="flex items-center justify-between gap-3 mt-4">
            {prev ? (
              <button
                onClick={() => openArticle(prev.id)}
                className="inline-flex items-center gap-1.5 h-9 px-4 rounded-full border border-tuan-border text-[13px] text-tuan-textSecondary hover:bg-tuan-hover hover:text-tuan-text transition-colors min-w-0"
              >
                <ArrowLeft size={14} className="flex-none" />
                <span className="truncate max-w-[180px]">{prev.title}</span>
              </button>
            ) : (
              <span />
            )}
            {next ? (
              <button
                onClick={() => openArticle(next.id)}
                className="inline-flex items-center gap-1.5 h-9 px-4 rounded-full border border-tuan-border text-[13px] text-tuan-textSecondary hover:bg-tuan-hover hover:text-tuan-text transition-colors min-w-0"
              >
                <span className="truncate max-w-[180px]">{next.title}</span>
                <ArrowRight size={14} className="flex-none" />
              </button>
            ) : (
              <span />
            )}
          </div>

          {/* 窄屏文档导航：chips（与桌面端侧栏同数据同筛选） */}
          <div className="md:hidden mt-4">
            <div className="text-[11px] font-medium text-tuan-textSecondary mb-2">
              {matched ? `搜索结果 · ${matched.length} 篇` : '全部文档'}
            </div>
            <div className="flex flex-wrap gap-2">
              {(matched ?? DOC_ARTICLES).map((a) => (
                <button
                  key={a.id}
                  onClick={() => openArticle(a.id)}
                  className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-[12.5px] transition-colors ${
                    a.id === article.id
                      ? 'border-tuan-accent bg-tuan-hover text-tuan-text'
                      : 'border-tuan-border text-tuan-textSecondary hover:bg-tuan-hover hover:text-tuan-text'
                  }`}
                >
                  <FileText size={12} className="flex-none" />
                  {a.title}
                </button>
              ))}
              {matched && matched.length === 0 && (
                <span className="text-[12.5px] text-tuan-textSecondary">没有匹配的文档</span>
              )}
            </div>
          </div>

          {/* 页脚说明 */}
          <p className="mt-6 text-[11.5px] leading-relaxed text-tuan-textSecondary">
            文档版本 {DOC_ENGINE_VERSION} · 共 {DOC_ARTICLES.length} 篇 · 内容与仓库内 ARCHITECTURE.md、docs/ 等文档同步维护。
          </p>
        </div>
      </div>
    </div>
  );
}

/** 左侧导航的一行 */
function NavItem({
  article,
  active,
  onOpen,
}: {
  article: { id: string; title: string; summary: string };
  active: boolean;
  onOpen: (id: string) => void;
}) {
  return (
    <button
      onClick={() => onOpen(article.id)}
      title={article.summary}
      className={`w-full text-left px-3 py-1.5 rounded-xl text-[13px] transition-colors truncate ${
        active
          ? 'bg-tuan-hover text-tuan-text font-medium'
          : 'text-tuan-textSecondary hover:bg-tuan-hover hover:text-tuan-text'
      }`}
    >
      {article.title}
    </button>
  );
}
