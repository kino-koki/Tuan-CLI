"""文件系统工具插件: 读 / 写 / 改 / 移动 / 删除 / 列目录 / 搜索 / glob。

补充的 Agent 核心能力 (对比原版):
- glob: 按通配符批量定位文件 (Agent 探索仓库的常用入口)。
- move_file / rename: 重命名与移动 (跨文件重构必备)。
- delete_file: 删除单文件 (危险, 需确认; YOLO 下自动批准)。
write_file 本身在 YOLO 下属于高风险写入, 也标记为 dangerous 以便统一管控。
"""

from __future__ import annotations

import os
import shutil
import stat
import tempfile
from pathlib import Path
from typing import Optional

from ..core.kernel import Kernel, Plugin
from .base import Tool, ToolContext, string_prop

MAX_READ_CHARS = 40000


def _atomic_write_text(path: Path, content: str) -> None:
    """原子写: 同目录临时文件 + fsync + os.replace, 崩溃不留半截文件。

    保留目标文件的既有权限位 (源码/脚本的可执行位不能被替换掉),
    新文件 (目标不存在) 用默认 0644 & umask。
    """
    directory = path.parent
    directory.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        if path.exists():
            try:
                os.chmod(tmp_name, stat.S_IMODE(path.stat().st_mode))
            except OSError:
                pass
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def _resolve(ctx: ToolContext, path: str) -> Path:
    workspace = Path(ctx.workspace).resolve()
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = workspace / candidate
    resolved = candidate.resolve()
    try:
        resolved.relative_to(workspace)
    except ValueError as exc:
        raise ValueError(f"路径必须位于工作区内: {path}") from exc
    return resolved


def _rel(ctx: ToolContext, p: Path) -> str:
    try:
        return str(p.relative_to(ctx.workspace))
    except ValueError:
        return str(p)


def glob(ctx: ToolContext, pattern: str, path: str = ".") -> str:
    """按 glob 通配符匹配文件 (如 '**/*.py', 'src/**/*.ts')。"""
    root = _resolve(ctx, path)
    if not root.exists():
        return f"[错误] 目录不存在: {root}"
    matches = sorted(p for p in root.glob(pattern) if p.is_file())
    if not matches:
        return f"未匹配到文件: {pattern}"
    lines = []
    for m in matches[:200]:
        lines.append(_rel(ctx, m))
    if len(matches) > 200:
        lines.append(f"...[共 {len(matches)} 个, 截断显示前 200]")
    return "\n".join(lines)


def move_file(ctx: ToolContext, src: str, dst: str) -> str:
    """移动或重命名文件/目录。"""
    s = _resolve(ctx, src)
    d = _resolve(ctx, dst)
    if not s.exists():
        return f"[错误] 源不存在: {s}"
    d.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(s), str(d))
    return f"已移动 {_rel(ctx, s)} -> {_rel(ctx, d)}"


def delete_file(ctx: ToolContext, path: str) -> str:
    """删除单个文件 (危险操作, 需确认)。"""
    p = _resolve(ctx, path)
    if not p.exists():
        return f"[错误] 文件不存在: {p}"
    if p.is_dir():
        return f"[错误] {p} 是目录, 请用 delete_dir"
    p.unlink()
    return f"已删除 {_rel(ctx, p)}"


def delete_dir(ctx: ToolContext, path: str) -> str:
    """递归删除整个目录 (极危险, 需确认, YOLO 仍建议保留红名单)。"""
    import shutil as _shutil

    p = _resolve(ctx, path)
    if not p.exists():
        return f"[错误] 目录不存在: {p}"
    if not p.is_dir():
        return f"[错误] {p} 不是目录"
    _shutil.rmtree(str(p))
    return f"已递归删除目录 {_rel(ctx, p)}"


def read_file(ctx: ToolContext, path: str, offset: int = 0, limit: int = 0) -> str:
    p = _resolve(ctx, path)
    if not p.exists():
        return f"[错误] 文件不存在: {p}"
    text = p.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    if offset:
        lines = lines[offset:]
    if limit:
        lines = lines[:limit]
    out = "\n".join(lines)
    if len(out) > MAX_READ_CHARS:
        out = out[:MAX_READ_CHARS] + f"\n...[截断, 全文 {len(text)} 字符]"
    # 记录为本会话已读, 供 Read-before-Edit 守卫放行后续 edit/write
    ctx.mark_read(str(p))
    return f"# {p}\n{out}"


# ------------------------------------------------------------------ Read-before-Edit 守卫
# 对标 Kimi Code v0.38.0 "Edit/Write must Read first": 未先 read 就改/覆盖既有文件一律拦截。
# 通过配置 tools.require_read_before_edit: false 关闭 (默认开启)。

def _guard_enabled(ctx: ToolContext) -> bool:
    v = ctx.config("tools.require_read_before_edit", True)
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "yes", "on")
    return bool(v)


def _read_before_edit_blocked(ctx: ToolContext, p: Path) -> Optional[str]:
    """返回非空错误串表示应拦截; None 表示放行。

    - edit_file 目标必然存在, 一律要求先 read;
    - write_file 仅当文件已存在 (覆盖) 时要求先 read, 新建文件放行。
    """
    if not _guard_enabled(ctx):
        return None
    if ctx.has_read(str(p)):
        return None
    return (f"[错误] 请先 read_file 读取该文件后再编辑: {_rel(ctx, p)}\n"
            "(Read-before-Edit 守卫; 如需关闭可设 tools.require_read_before_edit: false)")


# ------------------------------------------------------------------ diff 预览

def _unified_diff_text(old: str, new: str, p: Path, n: int = 3) -> str:
    """生成 unified diff 文本 (对标 Claude Code /diff 面板), 不写盘。"""
    import difflib
    lines = list(difflib.unified_diff(
        old.splitlines(), new.splitlines(),
        fromfile=f"a/{p.name}", tofile=f"b/{p.name}", lineterm="", n=n,
    ))
    if not lines:
        return "(无差异)"
    body = lines[:200]
    more = len(lines) - len(body)
    text = "\n".join(body)
    if more > 0:
        text += f"\n...[diff 共 {len(lines)} 行, 截断显示前 {len(body)} 行]"
    return text


def _apply_replacements(text: str, replacements: list) -> tuple:
    """按序应用多组替换。返回 (new_text, errors)。

    任一组 old_string 未找到或不唯一即记错误; 全部成功时 new_text 为替换后全文。
    调用方据此决定是否写盘 —— 任一失败则整体回滚 (不写)。
    """
    working = text
    errors: list[str] = []
    for i, rep in enumerate(replacements):
        old = rep.get("old_string", "") if isinstance(rep, dict) else ""
        new = rep.get("new_string", "") if isinstance(rep, dict) else ""
        if not old:
            errors.append(f"第 {i + 1} 组: old_string 为空")
            continue
        count = working.count(old)
        if count == 0:
            errors.append(f"第 {i + 1} 组: old_string 未找到")
        elif count > 1:
            errors.append(f"第 {i + 1} 组: old_string 出现 {count} 次, 不唯一, 请扩大上下文")
        else:
            working = working.replace(old, new, 1)
    return working, errors


def _normalize_replacements(old_string, new_string, replacements) -> Optional[list]:
    """统一为 replacements 列表; 两种调用方式缺一不可时返回 None (由调用方报错)。"""
    if replacements is not None:
        return list(replacements)
    if old_string is not None and new_string is not None:
        return [{"old_string": old_string, "new_string": new_string}]
    return None


def write_file(ctx: ToolContext, path: str, content: str) -> str:
    p = _resolve(ctx, path)
    # 覆盖既有文件前要求先读; 新建文件放行
    if p.exists():
        blocked = _read_before_edit_blocked(ctx, p)
        if blocked is not None:
            return blocked
    _atomic_write_text(p, content)
    return f"已写入 {p} ({len(content)} 字符)"


def edit_file(ctx: ToolContext, path: str, old_string: Optional[str] = None,
              new_string: Optional[str] = None,
              replacements: Optional[list] = None) -> str:
    """精确替换文本 (支持单组与 multi-cut 多组替换)。

    - 单组: edit_file(path, old_string, new_string)
    - 多组: edit_file(path, replacements=[{old_string, new_string}, ...])
    多组按顺序应用; 任一组未找到或不唯一则整体回滚 (不写入)。
    """
    p = _resolve(ctx, path)
    if not p.exists():
        return f"[错误] 文件不存在: {p}"
    blocked = _read_before_edit_blocked(ctx, p)
    if blocked is not None:
        return blocked
    reps = _normalize_replacements(old_string, new_string, replacements)
    if reps is None:
        return "[错误] 需提供 old_string/new_string 或 replacements 之一"
    text = p.read_text(encoding="utf-8")
    new_text, errors = _apply_replacements(text, reps)
    if errors:
        return ("[错误] 多组替换未全部通过, 已整体回滚 (未写入):\n" + "\n".join(errors))
    _atomic_write_text(p, new_text)
    diff = _unified_diff_text(text, new_text, p)
    n = len(reps)
    header = f"已修改 {p} ({n} 处替换)" if n > 1 else f"已修改 {p}"
    return f"{header}\n已应用变更, diff 如下:\n{diff}"


def diff_preview(ctx: ToolContext, path: str, old_string: Optional[str] = None,
                 new_string: Optional[str] = None,
                 replacements: Optional[list] = None) -> str:
    """预览对文件执行替换后的 unified diff, 不实际修改文件 (对标 Claude Code /diff 面板)。"""
    p = _resolve(ctx, path)
    if not p.exists():
        return f"[错误] 文件不存在: {p}"
    reps = _normalize_replacements(old_string, new_string, replacements)
    if reps is None:
        return "[错误] 需提供 old_string/new_string 或 replacements 之一"
    text = p.read_text(encoding="utf-8")
    new_text, errors = _apply_replacements(text, reps)
    if errors:
        return "[错误] 无法生成预览 (替换无法全部应用, 文件未改动):\n" + "\n".join(errors)
    diff = _unified_diff_text(text, new_text, p)
    return f"diff 预览 (未修改文件 {_rel(ctx, p)}):\n{diff}"


def list_dir(ctx: ToolContext, path: str = ".", depth: int = 2) -> str:
    root = _resolve(ctx, path)
    if not root.is_dir():
        return f"[错误] 目录不存在: {root}"
    lines: list[str] = []
    max_depth = min(depth, 4)
    for current, dirs, files in os.walk(root):
        rel = Path(current).relative_to(root)
        level = len(rel.parts)
        if level >= max_depth:
            dirs[:] = []
        dirs[:] = [d for d in sorted(dirs) if not d.startswith(".") and d != "__pycache__"]
        indent = "  " * level
        name = "." if str(rel) == "." else rel.name + "/"
        lines.append(f"{indent}{name}")
        for f in sorted(files)[:50]:
            lines.append(f"{indent}  {f}")
        if len(lines) > 400:
            lines.append("...[截断]")
            break
    return "\n".join(lines)


def search_files(ctx: ToolContext, pattern: str, path: str = ".") -> str:
    import re

    root = _resolve(ctx, path)
    if not root.is_dir():
        return f"[错误] 目录不存在: {root}"
    try:
        regex = re.compile(pattern)
    except re.error as exc:
        return f"[错误] 正则表达式无效: {exc}"
    hits: list[str] = []
    for current, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d != "__pycache__" and d != "node_modules"]
        for fname in files:
            fpath = Path(current) / fname
            try:
                for i, line in enumerate(fpath.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                    if regex.search(line):
                        hits.append(f"{fpath.relative_to(root)}:{i}: {line.strip()[:160]}")
                        if len(hits) >= 100:
                            return "\n".join(hits) + "\n...[超过 100 条, 截断]"
            except OSError:
                continue
    return "\n".join(hits) if hits else "未找到匹配内容"


class FilesystemPlugin(Plugin):
    name = "tools.filesystem"
    provides = []
    requires = ["tool_registry"]

    def activate(self, kernel: Kernel) -> None:
        registry = kernel.require("tool_registry")
        registry.register(Tool(
            name="read_file",
            description="读文件内容, 大文件用 offset/limit 分段",
            parameters={
                "type": "object",
                "properties": {
                    "path": string_prop("文件路径"),
                    "offset": {"type": "integer", "description": "起始行 (可选)"},
                    "limit": {"type": "integer", "description": "读取行数 (可选)"},
                },
                "required": ["path"],
            },
            handler=read_file, group="filesystem", read_only=True,
        ))
        registry.register(Tool(
            name="write_file",
            description="创建或覆盖文件",
            parameters={
                "type": "object",
                "properties": {
                    "path": string_prop("文件路径"),
                    "content": string_prop("完整内容"),
                },
                "required": ["path", "content"],
            },
            handler=write_file, group="filesystem", dangerous=True,
        ))
        registry.register(Tool(
            name="edit_file",
            description="精确替换文本, old_string 须唯一。两种方式: "
                        "(1) old_string/new_string 单组替换; "
                        "(2) replacements=[{old_string,new_string},...] 多组按序替换, "
                        "任一组未找到或不唯一则整体回滚不写入。覆盖已存在文件前须先 read_file。",
            parameters={
                "type": "object",
                "properties": {
                    "path": string_prop("文件路径"),
                    "old_string": string_prop("被替换原文 (单组方式)"),
                    "new_string": string_prop("新文本 (单组方式)"),
                    "replacements": {
                        "type": "array",
                        "description": "多组替换列表, 每项 {old_string, new_string} (multi-cut)",
                        "items": {
                            "type": "object",
                            "properties": {
                                "old_string": string_prop("被替换原文"),
                                "new_string": string_prop("新文本"),
                            },
                            "required": ["old_string", "new_string"],
                        },
                    },
                },
                "required": ["path"],
            },
            handler=edit_file, group="filesystem", dangerous=True,
        ))
        registry.register(Tool(
            name="diff_preview",
            description="预览对文件执行替换后的 unified diff, 不实际修改文件 "
                        "(对标 Claude Code /diff 面板)。支持单组 old_string/new_string "
                        "或 replacements 多组。",
            parameters={
                "type": "object",
                "properties": {
                    "path": string_prop("文件路径"),
                    "old_string": string_prop("被替换原文 (单组方式)"),
                    "new_string": string_prop("新文本 (单组方式)"),
                    "replacements": {
                        "type": "array",
                        "description": "多组替换列表, 每项 {old_string, new_string}",
                        "items": {
                            "type": "object",
                            "properties": {
                                "old_string": string_prop("被替换原文"),
                                "new_string": string_prop("新文本"),
                            },
                            "required": ["old_string", "new_string"],
                        },
                    },
                },
                "required": ["path"],
            },
            handler=diff_preview, group="filesystem", read_only=True,
        ))
        registry.register(Tool(
            name="list_dir",
            description="树形列出目录",
            parameters={
                "type": "object",
                "properties": {
                    "path": string_prop("目录, 默认工作区"),
                    "depth": {"type": "integer", "description": "深度, 默认 2"},
                },
                "required": [],
            },
            handler=list_dir, group="filesystem", read_only=True,
        ))
        registry.register(Tool(
            name="search_files",
            description="正则搜索文件内容",
            parameters={
                "type": "object",
                "properties": {
                    "pattern": string_prop("正则"),
                    "path": string_prop("根目录, 默认工作区"),
                },
                "required": ["pattern"],
            },
            handler=search_files, group="filesystem", read_only=True,
        ))
        registry.register(Tool(
            name="glob",
            description="按通配符批量定位文件, 如 '**/*.py'",
            parameters={
                "type": "object",
                "properties": {
                    "pattern": string_prop("glob 模式"),
                    "path": string_prop("根目录, 默认工作区"),
                },
                "required": ["pattern"],
            },
            handler=glob, group="filesystem", read_only=True,
        ))
        registry.register(Tool(
            name="move_file",
            description="移动或重命名文件/目录",
            parameters={
                "type": "object",
                "properties": {
                    "src": string_prop("源路径"),
                    "dst": string_prop("目标路径"),
                },
                "required": ["src", "dst"],
            },
            handler=move_file, group="filesystem", dangerous=True,
        ))
        registry.register(Tool(
            name="delete_file",
            description="删除单个文件 (不可逆, 需确认)",
            parameters={
                "type": "object",
                "properties": {
                    "path": string_prop("文件路径"),
                },
                "required": ["path"],
            },
            handler=delete_file, group="filesystem", dangerous=True,
        ))
        registry.register(Tool(
            name="delete_dir",
            description="递归删除整个目录 (极危险, 需确认)",
            parameters={
                "type": "object",
                "properties": {
                    "path": string_prop("目录路径"),
                },
                "required": ["path"],
            },
            handler=delete_dir, group="filesystem", dangerous=True,
        ))
