"""文件型记忆笔记 MEMORY.md (对标 Claude Code 的 projects/<slug>/memory/MEMORY.md)。

与 FTS5 结构化长期记忆 (auto_extractor / MemoryStore) 并存、互补:
- FTS5 记忆: 规则自动抽取的四类结构化条目 (user/feedback/project/reference), 走全文检索;
- MEMORY.md 笔记: Agent 直接写入的「用户偏好 / 纠正 / 项目决策」自由文本笔记,
  下次会话经 system prompt 动态段全量注入 (默认 200 行上限)。

存储位置: <home>/projects/<project_slug>/memory/MEMORY.md
- project_slug = workspace 绝对路径规范化后 SHA1 前 8 位 (不同目录不同 slug)。
- 写入一律走 atomic_write_text (临时文件 + fsync + os.replace), 中断不损坏。
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import List, Optional

from ..core.atomicio import atomic_write_text

# 默认注入行数上限 (对标 Claude Code 200 行)。
DEFAULT_MAX_LINES = 200


def project_slug(workspace: str) -> str:
    """由 workspace 路径生成项目 slug: 规范化绝对路径后 SHA1 前 8 位。

    不同目录产出不同 slug; 同一路径在不同调用间稳定 (prompt cache / 跨会话一致)。
    """
    try:
        norm = str(Path(workspace).resolve())
    except OSError:
        norm = str(workspace)
    # 统一分隔符并去掉结尾斜杠, 避免 `foo` 与 `foo/` 产生不同 slug
    norm = norm.replace("\\", "/").rstrip("/")
    return hashlib.sha1(norm.encode("utf-8")).hexdigest()[:8]


class MemoryNotesStore:
    """管理单个项目的 MEMORY.md 笔记文件 (原子读写)。"""

    def __init__(self, home: Path, workspace: str, max_lines: int = DEFAULT_MAX_LINES) -> None:
        self.home = Path(home)
        self.workspace = str(workspace)
        self.max_lines = int(max_lines)
        self.slug = project_slug(self.workspace)
        self.dir = self.home / "projects" / self.slug / "memory"
        self.path = self.dir / "MEMORY.md"

    # ------------------------------------------------------------------ 读

    def read(self) -> str:
        """读取 MEMORY.md 全文; 不存在返回空串。"""
        try:
            if self.path.exists():
                return self.path.read_text(encoding="utf-8")
        except OSError:
            pass
        return ""

    def lines(self) -> List[str]:
        """返回逐行列表 (不含结尾换行符)。"""
        content = self.read()
        if not content:
            return []
        return content.splitlines()

    def line_count(self) -> int:
        """当前笔记行数。空文件 = 0。"""
        return len(self.lines())

    def is_full(self, limit: Optional[int] = None) -> bool:
        """是否达到行数上限 (默认 self.max_lines, 可传入其他 limit)。"""
        cap = self.max_lines if limit is None else int(limit)
        return self.line_count() >= cap

    def search(self, keyword: str) -> List[str]:
        """行内搜索: 返回包含 keyword 的行 (大小写不敏感)。"""
        if not keyword:
            return []
        kw = keyword.lower()
        return [ln for ln in self.lines() if kw in ln.lower()]

    # ------------------------------------------------------------------ 写 (原子)

    def write(self, content: str) -> None:
        """整体覆盖 MEMORY.md (原子写: 临时文件 + os.replace, 中断不损坏)。"""
        atomic_write_text(self.path, content)

    def append(self, content: str) -> int:
        """追加笔记 (可一行或多行); 返回追加后的总行数。

        - 自动在文件末尾补换行, 避免新笔记粘在上一行尾巴上;
        - 原子写, 中断时目标文件保持追加前内容;
        - 超过上限时仍允许追加 (由调用方决定是否警告), 但返回行数供判断。
        """
        current = self.read()
        block = content.strip("\n")
        if not block:
            return self.line_count()
        if current and not current.endswith("\n"):
            current += "\n"
        new_content = current + block + "\n"
        atomic_write_text(self.path, new_content)
        return self.line_count()
