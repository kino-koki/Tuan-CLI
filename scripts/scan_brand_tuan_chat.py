"""扫描 Tuan-Chat 内用户可见的 Claude/Anthropic 品牌文本（排除技术引用与模型 id）。

排除:
  - CSS 类名/变量、注释、import/require、console 日志
  - Anthropic API 协议字段 (ANTHROPIC_ env、anthropic-version、format='anthropic'、
    x-api-key、/v1/messages、web_search_20250305、api.anthropic.com)
  - 第三方模型 id 字面量 (claude-xxx) 与外部供应商目录
输出: 文件:行号 -> 命中行 (JSX 渲染文本与字符串字面量)
"""
from __future__ import annotations
import re
from pathlib import Path

ROOT = Path(r"E:\Tuan-CLI\Tuan-Chat")
SKIP_DIRS = {"node_modules", "engine-py", "release", "dist", ".git", ".github", "build", "public"}
SKIP_FILES = {"claude-thinking-sprite.css", "claude-thinking-sprite.html", "claude-thinking-sprite.svg"}
PATTERNS = re.compile(r"Claude|claude|Anthropic|anthropic")

TECH_TOKENS = (
    "className", "class=", "ANTHROPIC_", "anthropic.com", "api.anthropic",
    "isClaudeFamily", "claudeCode", "claude_code", "CLAUDE_CODE_", ".claude", "~/.claude",
    "import ", "require(", "//", "/*", "console.log", "console.error", "console.warn",
    "anthropic-version", "anthropic-beta", "x-api-key", "web_search_20250305", "web_search",
    "format: 'anthropic'", "format: \"anthropic\"", "'anthropic'", "callAnthropic",
    "anthropic_native", "anthropic-protocol",
)


def is_tech(line: str) -> bool:
    for tok in TECH_TOKENS:
        if tok in line:
            return True
    if re.search(r"['\"]claude-[\w.\-]+['\"]", line):  # 模型 id 字面量
        return True
    if re.search(r"[a-zA-Z_]claude|claude[a-zA-Z_]", line):
        return True
    return False


def main() -> None:
    hits = []
    for p in ROOT.rglob("*"):
        if p.is_dir():
            continue
        rel = p.relative_to(ROOT).as_posix()
        if any(rel.startswith(d + "/") for d in SKIP_DIRS):
            continue
        if p.name in SKIP_FILES:
            continue
        if p.suffix not in (".tsx", ".ts", ".jsx", ".js", ".cjs", ".html", ".md", ".txt"):
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if not PATTERNS.search(line):
                continue
            if is_tech(line):
                continue
            stripped = line.strip()
            if stripped.startswith("//") or stripped.startswith("*") or stripped.startswith("<!--"):
                continue
            hits.append((rel, i, stripped[:180]))
    print(f"=== 候选可见品牌文本: {len(hits)} 处 ===")
    for rel, ln, text in hits:
        print(f"{rel}:{ln}\t{text}")


if __name__ == "__main__":
    main()
