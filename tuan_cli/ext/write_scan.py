"""文件内容写入扫描 (write-scan) —— 检测模型写入的恶意命令。

目标: 防止模型在 write_file/edit_file/edit_files 中写入包含危险命令的内容,
     复用现有 CRITICAL_PATTERNS 正则库, 在写入前做静态扫描。

设计原则:
- fail-closed: 任何匹配均拒绝写入 (宁可误杀, 不可放行)
- 最小影响半径: 仅检查写入的文本内容, 不解析 AST/字节码
- 可扩展: 新增模式只需在 safety_patterns.py 中添加, 本模块自动复用

返回格式:
- (False, None): 安全, 可写入
- (True, list[dict]): 危险, 返回所有匹配的模式 (包含 label 与位置信息)
"""

from __future__ import annotations

import re
from typing import List, Tuple, Optional

from .safety_patterns import _CRITICAL_PATTERNS

# 补充模式: CRITICAL_PATTERNS 未覆盖的写入场景常见危险命令。
# 这些模式仅用于 write_scan, 不加入 CRITICAL_PATTERNS 以免影响 shell 引擎的精确 token 分析。
_EXTRA_WRITE_PATTERNS: List[Tuple[str, str]] = [
    # rm -rf 危险目标 (根目录 / 用户主目录)
    # 注: shell 引擎的 has_recursive_rm 函数做精确 token 分析, 此处正则兜底覆盖文件内容扫描。
    (r"\brm\s+\S*-[rRfF]+\S*\s+/",
     "rm -rf / (递归强制删除根目录)"),
    (r"\brm\s+\S*-[rRfF]+\S*\s+~",
     "rm -rf ~ (递归强制删除用户主目录)"),
]

_ALL_PATTERNS = _CRITICAL_PATTERNS + _EXTRA_WRITE_PATTERNS


def scan_content_for_danger(content: str) -> Tuple[bool, List[dict] | None]:
    """扫描文件内容, 检测是否包含危险命令。

    Args:
        content: 待写入的文本内容

    Returns:
        (is_safe, matches):
        - is_safe: False 表示发现危险内容, 应拒绝写入
        - matches: 危险模式列表, 每项包含 {pattern, label, match, position}
    """
    if not content:
        return False, None

    matches: List[dict] = []
    lines = content.splitlines()

    for pattern, label in _ALL_PATTERNS:
        for line_num, line in enumerate(lines, start=1):
            for match in re.finditer(pattern, line, re.IGNORECASE):
                # 记录匹配详情
                matches.append({
                    "pattern": pattern,
                    "label": label,
                    "match": match.group(),
                    "line": line_num,
                    "column": match.start() + 1,  # 1-based column
                    "line_content": line.strip(),
                })

    if matches:
        return True, matches

    return False, None


def format_matches_for_user(matches: List[dict]) -> str:
    """将匹配结果格式化为用户可读的警告信息。"""
    if not matches:
        return ""

    lines = ["检测到危险内容, 已阻止写入:", ""]
    seen_patterns = set()

    for m in matches:
        pattern = m["pattern"]
        if pattern in seen_patterns:
            continue
        seen_patterns.add(pattern)

        lines.append(f"  ⚠️  {m['label']}")
        lines.append(f"     位置: 行 {m['line']}, 列 {m['column']}")
        lines.append(f"     匹配: {m['match']!r}")
        lines.append(f"     内容: {m['line_content'][:100]}")
        lines.append("")

    return "\n".join(lines)


def _resolve_path_for_warning(path: str) -> str:
    """将路径转换为相对路径 (用于警告信息)。"""
    try:
        from pathlib import Path
        p = Path(path)
        if p.is_absolute():
            # 尝试转换为相对于工作区的相对路径
            try:
                workspace = Path.cwd()
                return str(p.relative_to(workspace))
            except ValueError:
                return str(p)
        return path
    except Exception:
        return path
