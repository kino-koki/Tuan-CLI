"""扫描 claude-desktop-app 内用户可见的 Claude/Anthropic 品牌文本（供 Tuan-Chat 替换）。

排除:
  - CSS 类名/变量 (className=/bg-claude/text-claude 等)
  - 注释 (// 或 /* */) 与 import 语句
  - ClaudeLogo 组件(claude 动画) 与 claude-thinking-* 动画资源
  - 技术字段 (ANTHROPIC_API_KEY 等 env、claude- 模型 id、api.claude.com 等)
输出: 文件:行号 → 命中行 (仅 JSX 渲染文本与字符串字面量)
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(r"E:\Qingxiaotuan Agent CLI\claude-desktop-app")
SKIP_DIRS = {"node_modules", "engine", "engine-py", "release", "dist", ".git", ".github", "build"}
SKIP_FILES = {"ClaudeLogo.tsx", "claude-thinking-sprite.css", "claude-thinking-sprite.html", "claude-thinking-sprite.svg"}
# 这些文件整体跳过(技术/设计文档或已被替换目标文件)
SKIP_WHOLE = {"COWORK-REDESIGN.md", "GEMINI.md", "package-lock.json", "refactor.cjs", "refactor.js", "noop.cjs"}

PATTERNS = re.compile(r"Claude|claude|Anthropic|anthropic")

# 命中行里出现这些 token 视为技术/样式引用, 跳过
TECH_TOKENS = (
    "className", "class=", "bg-claude", "text-claude", "border-claude", "from-claude",
    "font-serif-claude", "selection:", "hover:", "ANTHROPIC_", "anthropic.com",
    "api.claude.com", "claude-code", "claude-code/", "isClaudeFamily", "^claude-",
    "/^claude/", "claude-", # 模型 id 前缀(如 claude-opus-4-6-thinking)单独判断
    "claudeCode", "claude_code", "claudeCodePath", "CLAUDE_CODE_", ".claude", "~/.claude",
    "import ", "require(", "//", "/*", "* ", "console.log", "README", "LICENSE",
)


def is_tech(line: str) -> bool:
    for tok in TECH_TOKENS:
        if tok in line:
            return True
    # 模型 id 字面量 (claude-xxx) 单独规则
    if re.search(r"['\"]claude-[\w.\-]+['\"]", line):
        return True
    if re.search(r"[a-zA-Z_]claude|claude[a-zA-Z_]", line):
        return True
    return False


def walk():
    hits = []
    for p in ROOT.rglob("*"):
        if p.is_dir():
            continue
        rel = p.relative_to(ROOT).as_posix()
        if any(rel.startswith(d + "/") for d in SKIP_DIRS):
            continue
        if p.name in SKIP_FILES or p.name in SKIP_WHOLE:
            continue
        if p.suffix not in (".tsx", ".ts", ".jsx", ".js", ".cjs", ".html", ".json", ".md", ".txt"):
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
            # 去掉纯注释行
            stripped = line.strip()
            if stripped.startswith("//") or stripped.startswith("*") or stripped.startswith("<!--"):
                continue
            hits.append((rel, i, stripped[:160]))
    return hits


if __name__ == "__main__":
    hits = walk()
    print(f"=== 候选可见品牌文本: {len(hits)} 处 ===")
    for rel, ln, text in hits:
        print(f"{rel}:{ln}\t{text}")
