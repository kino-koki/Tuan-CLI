import { useEffect, useRef, useState, type ReactNode } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Check, Copy } from 'lucide-react';

function extractText(node: unknown): string {
  if (node == null) return '';
  if (typeof node === 'string' || typeof node === 'number') return String(node);
  if (Array.isArray(node)) return node.map(extractText).join('');
  if (typeof node === 'object' && 'props' in (node as Record<string, unknown>)) {
    return extractText((node as { props: { children?: unknown } }).props.children);
  }
  return '';
}

function langOf(node: unknown): string {
  if (typeof node !== 'object' || node == null || !('props' in (node as Record<string, unknown>))) return '';
  const cls = (node as { props: { className?: string } }).props.className ?? '';
  const m = /language-([\w+-]+)/.exec(cls);
  return m ? m[1] : '';
}

function CodeBlock({ children }: { children?: ReactNode }) {
  const raw = extractText(children).replace(/\n$/, '');
  const lang = langOf(children) || 'code';
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(raw);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* 剪贴板不可用时忽略 */
    }
  };
  return (
    <div className="tuan-codeblock my-2.5">
      <div className="tuan-codeblock-head">
        <span className="tuan-codeblock-lang">{lang}</span>
        <button onClick={copy} className="tuan-codeblock-copy" type="button">
          {copied ? <Check size={13} /> : <Copy size={13} />}
          {copied ? '已复制' : '复制'}
        </button>
      </div>
      <pre>
        <code>{raw}</code>
      </pre>
    </div>
  );
}

/**
 * 把「还没写完」的 Markdown 补成语法完整的文本，供流式期间直接解析。
 *
 * 为什么需要它：模型是按 token 逐段吐字的，任意时刻截断都可能停在
 * 半开的 ``` 围栏、半截表格分隔行或悬空的 ** 上。若把这样的文本直接
 * 交给 react-markdown，会出现「正文里夹着裸露的 #、-、|、`」的观感——
 * 也就是用户看到的"输出大量乱码"。此前用「流式期间整段按纯文本显示」
 * 规避，代价是全程看到裸标记；现在改成补全语法后仍走完整解析，
 * 用户看到的是排版好的正文，且与定稿态一致、不会视觉跳变。
 */
export function sanitizePartialMarkdown(input: string): string {
  let text = input ?? '';

  // 0) 断裂的 Unicode 代理对：模型按 token 吐字时，BMP 外字符（emoji / 中日韩扩展字）
  //    可能被拆成两个 UTF-16 码元，前一个码元单独出现在行尾时 TextDecoder 虽能处理，
  //    但 react-markdown 解析时可能产生不可见替换字符（U+FFFD）。这里扫描尾部的
  //    孤立高代理码元（\uD800–\uDBFF），若后无低代理则补一个 U+FFFD 占位，
  //    避免渲染出乱码方块。
  text = text.replace(/[\uD800-\uDBFF](?!\uDC00[\u0000-\uFFFF])\s*$/, '');
  text = text.replace(/\uDC00-\uFFFF$/g, ''); // 低代理孤立在行尾

  // 1) 代码围栏：``` 数量为奇数说明最后一个围栏还没闭合，补上。
  //    只统计围栏行（行首至多 3 个空格 + 三个反引号或波浪号），
  //    避免把正文里成对出现的 ``` 误判成围栏。
  const fenceRe = /^\s{0,3}(`{3,}|~{3,})/;
  const lines = text.split('\n');
  let fenceOpen = false;
  let fenceChar = '';
  const out: string[] = [];
  for (const line of lines) {
    const m = fenceRe.exec(line);
    if (m) {
      const marker = m[1];
      if (!fenceOpen) {
        fenceOpen = true;
        fenceChar = marker[0];
      } else if (marker[0] === fenceChar) {
        fenceOpen = false;
        fenceChar = '';
      }
    }
    out.push(line);
  }
  if (fenceOpen) out.push(`${fenceChar.repeat(3)}`);
  text = out.join('\n');

  // 2) 悬空的表格分隔行：形如 |---|---| 或 ---|---，只有当它前面一行
  //    不是表格行时才成立（否则是真表格，交给 remark-gfm 解析）。
  const sepRe = /^\s*\|?\s*:?-{2,}:?\s*(?:\|\s*:?-{2,}:?\s*)+\|?\s*$/;
  const sepLines = text.split('\n');
  let dropped = false;
  for (let i = sepLines.length - 1; i >= 0; i--) {
    if (!sepRe.test(sepLines[i])) break;
    const prev = sepLines[i - 1] ?? '';
    if (/^\s*\|/.test(prev) || prev.includes('|')) break; // 前面是表格行，保留
    sepLines.splice(i, 1);
    dropped = true;
    break;
  }
  if (dropped) text = sepLines.join('\n');

  // 3) 行尾悬空的强调标记：** / * / __ / _ / ~，会被渲染成字面量。
  //    只清每一行的行尾，不动正文中间的成对标记。
  text = text.replace(/([*]{1,3}|_{1,3}|~{1,2})\s*$/gm, '');

  // 4) 悬空的行内代码反引号（单个，非围栏）。
  const backticks = (text.match(/(?<!`)`/g) ?? []).length + (text.match(/`(?=`)/g) ?? []).length;
  if (backticks % 2 === 1) text += '`';

  // 5) 行尾悬空的竖线 |（表格行正在输入，尾部的 | 会渲染成可见的竖线符号）
  //    只清每一行的行尾，不动表格中间的竖线。
  text = text.replace(/\|\s*$/gm, '');

  // 6) 行尾悬空的分隔线标记：--- 正在输入，三个以上连字符会被渲染成 <hr>
  //    但用户可能还在输入第四个字符（如 ------）。
  //    只清行尾的纯连字符序列（3–5 个），不动行首的分隔线（那是真 hr）。
  const lastLine = text.split('\n').pop() ?? '';
  const hrMatch = lastLine.match(/\s-{3,5}\s*$/);
  if (hrMatch && text.includes('\n')) {
    // 只在有多行时才清，避免把整个消息误判成 hr
    text = text.replace(/\s-{3,5}\s*$/, '');
  }

  // 7) 悬空的引用标记 > 在行尾，会被渲染成引用样式但后面没内容
  text = text.replace(/\>\s*$/gm, '');

  return text;
}

export default function ReplyMarkdown({ text, streaming }: { text: string; streaming?: boolean }) {
  // 流式期间节流渲染：模型每个 token 都会触发一次 setState，
  // 直接同步重解析几千字的 Markdown 在低端机会掉帧。
  // 用 rAF + 时间窗把解析频率压到 ~12fps，肉眼与同步渲染无差别。
  const THROTTLE_MS = 80;
  const [live, setLive] = useState(() => (streaming ? sanitizePartialMarkdown(text) : text));
  const lastAt = useRef(0);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (!streaming) {
      setLive(text);
      return;
    }
    const now = Date.now();
    const pending = sanitizePartialMarkdown(text);
    if (now - lastAt.current >= THROTTLE_MS) {
      lastAt.current = now;
      setLive(pending);
      return;
    }
    if (timer.current) return;
    timer.current = setTimeout(() => {
      timer.current = null;
      lastAt.current = Date.now();
      setLive(pending);
    }, THROTTLE_MS - (now - lastAt.current));
    return () => {
      if (timer.current) {
        clearTimeout(timer.current);
        timer.current = null;
      }
    };
  }, [text, streaming]);

  return (
    <div className="tuan-md">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          pre: ({ children }) => <CodeBlock>{children}</CodeBlock>,
          a: ({ href, children }) => (
            <a href={href} target="_blank" rel="noreferrer" className="tuan-md-link">
              {children}
            </a>
          ),
        }}
      >
        {live}
      </ReactMarkdown>
    </div>
  );
}
