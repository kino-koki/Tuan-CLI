"""彻底枚举 Tuan-Chat src 里疑似未翻译的英文（JSX 文本/属性/确认框/UI 字符串字面量）。"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "Tuan-Chat" / "src"
if not ROOT.is_dir():
    print(f"未找到 Tuan-Chat/src（{ROOT}），跳过。")
    raise SystemExit(0)
SKIP_TOKENS = (
    "http", "SKILL.md", "markdown", "PDF", "Slack", "GitHub", "OpenAI", "GPT", "DeepSeek",
    "Qwen", "GLM", "Gemini", "MiniMax", "SiliconFlow", "API", "URL", "MCP", "json", "html",
    "OAuth", "Composio", "WebView", "Tuan-Chat", "Tuan", "HTTP", "SSE", "WebSocket",
    "Anthropic", "anthropic", "OpenRouter", "DeepL", "MyMemory", "LibreTranslate", "Google",
    "Azure", "Windows", "Git", "Bash", "npm", "node", "React", "Tailwind", "CSS",
    "Kubernetes", "PostgreSQL", "SQL", "Redis", "Docker", "Figma",
    "Notion", "Linear", "Asana", "Jira", "Zoom", "Gmail", "Drive", "Calendar", "Docs", "Sheets",
)

node_re = re.compile(r">([^<>{}=();]*?)<")
attr_re = re.compile(r'(?:placeholder|title|aria-label|alt|label|heading|tooltip|caption)\s*=\s*"([^"]{6,})"')
str_re = re.compile(r"'([^'\\]{8,})'|\"([^\"\\]{8,})\"|`([^`\\]{8,})`")
CODE_NOISE = ("useState", "useRef", "const ", "=>", "pathname", "data.", "item.", "=>", "Math.", "parsed.", "?.", "?:")


def chinese(s):
    return bool(re.search(r"[一-鿿]", s))


def clean(s):
    return re.sub(r"\s+", " ", s).strip()


for p in sorted(ROOT.rglob("*")):
    if p.suffix not in (".tsx", ".ts"):
        continue
    if p.name.endswith(".test.tsx") or p.name.endswith(".test.ts"):
        continue
    if p.name in ("modelsCatalog.ts", "i18n.ts"):
        continue
    text = p.read_text(encoding="utf-8", errors="replace")
    out = []
    for m in node_re.finditer(text):
        s = clean(m.group(1))
        if len(s) < 10 or chinese(s):
            continue
        if any(k in s for k in SKIP_TOKENS) or any(k in s for k in CODE_NOISE):
            continue
        if re.search(r"[=(){};]|\bconst\b|=>|pathname", s):
            continue
        if len(re.findall(r"[A-Za-z']+", s)) < 3:
            continue
        out.append(("node", s[:160]))
    for m in attr_re.finditer(text):
        s = clean(m.group(1))
        if len(s) < 8 or chinese(s) or any(k in s for k in SKIP_TOKENS):
            continue
        out.append(("attr", s[:160]))
    for m in str_re.finditer(text):
        s = clean(next(g for g in m.groups() if g))
        if len(s) < 10 or chinese(s):
            continue
        if any(k in s for k in SKIP_TOKENS) or any(k in s for k in CODE_NOISE):
            continue
        if len(re.findall(r"[A-Za-z']+", s)) < 3:
            continue
        # className / 代码 / 样式字面量：含连字符尾wind 工具类或代码符号则跳过
        if re.search(r"[{}()=;]|^\.|^#|px\b|rgba?\(|\b(flex|grid|text-|bg-|p-[0-9]|m-[0-9]|w-|h-|rounded|border|hover:|dark:|items-|justify|gap-|space-|font-|leading|tracking|opacity|transition|absolute|relative|overflow|inline|block|hidden|shrink|min-|max-|shadow|cursor|sticky|fixed|sticky)\b", s):
            continue
        out.append(("str", s[:160]))
    if out:
        print(f"\n##### {p.relative_to(ROOT)} ({len(out)})")
        for kind, s in out:
            print(f"[{kind}] {s}")
