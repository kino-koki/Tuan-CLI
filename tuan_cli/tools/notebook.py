"""Jupyter Notebook (.ipynb) 读写工具 (对标 Claude Code NotebookEdit)。

Claude Code 提供 NotebookEdit 工具用于按单元格编辑 notebook；本模块补齐
这一能力，并保持与文件系统工具一致的安全约束：

- 路径必须位于工作区（或本会话经 ``/add-dir`` 显式授权的目录）内 —— 复用
  ``filesystem._resolve``，不新增越界可能；
- 写操作标记 ``dangerous``，走既有确认/YOLO 策略；
- 覆盖已有 notebook 前须先 ``notebook_read`` 或 ``read_file``（复用
  ``filesystem._read_before_edit_blocked``，Read-before-Edit 守卫）；
- 原子写（同目录临时文件 + fsync + ``os.replace``），崩溃不留半截文件；
- 只接受 nbformat 4（1-3 的旧格式直接拒绝并说明，不做静默"升级"）；
- 替换代码单元格时清空 ``outputs`` / ``execution_count``，避免旧输出与
  新输入不一致（Claude Code 同样行为）。

单元格定位优先级：``cell_id`` 命中单元格 ``id`` 字段 > 命中 ``cell-<n>``
别名 > 纯数字视为 0 基下标。都不命中即报错，绝不猜。
"""

from __future__ import annotations

import copy
import json
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..core.kernel import Kernel, Plugin
from .base import Tool, ToolContext, string_prop
from .filesystem import (
    _atomic_write_text,
    _read_before_edit_blocked,
    _rel,
    _resolve,
)

MAX_CELLS = 5000
MAX_SOURCE_CHARS = 4000
CELL_TYPES = ("code", "markdown", "raw")
EDIT_MODES = ("replace", "insert", "delete")


# ------------------------------------------------------------------ notebook IO
def _load_notebook(path: Path) -> Dict[str, Any]:
    """读取并校验 nbformat 4 notebook（失败抛 ValueError，错误信息可直接给模型）。"""
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"读取 notebook 失败: {exc}") from None
    try:
        nb = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"notebook 不是合法 JSON: {exc}") from None
    if not isinstance(nb, dict):
        raise ValueError("notebook 顶层必须是 JSON 对象")
    major = nb.get("nbformat")
    if not isinstance(major, int) or major != 4:
        raise ValueError(
            f"仅支持 nbformat 4, 当前为 {major!r}; 请先用 Jupyter 迁移旧格式")
    cells = nb.get("cells")
    if not isinstance(cells, list):
        raise ValueError("notebook 缺少 cells 数组")
    if len(cells) > MAX_CELLS:
        raise ValueError(f"单元格过多 ({len(cells)} > {MAX_CELLS}), 拒绝编辑")
    return nb


def _save_notebook(path: Path, nb: Dict[str, Any]) -> None:
    text = json.dumps(nb, ensure_ascii=False, indent=1) + "\n"
    _atomic_write_text(path, text)


def _cell_id(cell: Dict[str, Any], index: int) -> str:
    raw = cell.get("id")
    return str(raw) if raw else f"cell-{index}"


def _find_cell_index(cells: List[Dict[str, Any]], cell_id: str) -> int:
    for i, cell in enumerate(cells):
        if str(cell.get("id", "")) == cell_id:
            return i
    legacy = str(cell_id)
    if legacy.startswith("cell-"):
        legacy = legacy[len("cell-"):]
    if legacy.isdigit():
        idx = int(legacy)
        if 0 <= idx < len(cells):
            return idx
    raise ValueError(f"未找到单元格 cell_id={cell_id!r}")


def _source_to_list(source: str) -> List[str]:
    """把整体字符串转成 nbformat 的 source 行列表（保留行尾换行语义）。"""
    if not source:
        return []
    lines = source.splitlines(keepends=True)
    return lines


def _new_cell(cell_type: str, source: str, nbformat_minor: int) -> Dict[str, Any]:
    cell: Dict[str, Any] = {
        "cell_type": cell_type,
        "metadata": {},
        "source": _source_to_list(source),
    }
    if cell_type == "code":
        cell["execution_count"] = None
        cell["outputs"] = []
    if nbformat_minor >= 5:
        cell["id"] = uuid.uuid4().hex[:8]
    return cell


def _brief(value: Any, limit: int = MAX_SOURCE_CHARS) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    if len(text) > limit:
        return text[:limit] + f"…[截断, 共 {len(text)} 字符]"
    return text


# ------------------------------------------------------------------ tools
def notebook_read(ctx: ToolContext, notebook_path: str, cell_id: str = "") -> str:
    """读取 notebook 单元格概览（只读）。"""
    p = _resolve(ctx, notebook_path)
    if not p.exists():
        return f"[错误] notebook 不存在: {p}"
    if p.is_dir():
        return f"[错误] {p} 是目录, 不是 notebook"
    try:
        nb = _load_notebook(p)
    except ValueError as exc:
        return f"[错误] {exc}"
    cells = nb["cells"]
    minor = int(nb.get("nbformat_minor", 0) or 0)
    ctx.mark_read(str(p))
    out: List[str] = [
        f"# {_rel(ctx, p)} (nbformat 4.{minor}, {len(cells)} 个单元格)"]
    for i, cell in enumerate(cells):
        ctype = str(cell.get("cell_type", "?"))
        cid = _cell_id(cell, i)
        src = "".join(cell.get("source", [])) if isinstance(cell.get("source"), list) \
            else str(cell.get("source", ""))
        out.append(f"[{i}] id={cid} ({ctype}, {_brief(src, 120)!r})")
    return "\n".join(out)


def notebook_edit(
    ctx: ToolContext,
    notebook_path: str,
    cell_id: str = "",
    new_source: str = "",
    cell_type: str = "code",
    edit_mode: str = "replace",
) -> str:
    """按单元格编辑 notebook（危险写操作，需确认）。"""
    mode = (edit_mode or "replace").strip().lower()
    if mode not in EDIT_MODES:
        return f"[错误] edit_mode 须为 {EDIT_MODES}, 收到 {edit_mode!r}"
    ctype = (cell_type or "code").strip().lower()
    if ctype not in CELL_TYPES:
        return f"[错误] cell_type 须为 {CELL_TYPES}, 收到 {cell_type!r}"

    p = _resolve(ctx, notebook_path)
    if p.suffix.lower() != ".ipynb":
        return "[错误] notebook_edit 只接受 .ipynb 文件"
    if p.is_dir():
        return f"[错误] {p} 是目录, 不是 notebook"

    if p.exists():
        blocked = _read_before_edit_blocked(ctx, p)
        if blocked:
            return blocked
        try:
            nb = _load_notebook(p)
        except ValueError as exc:
            return f"[错误] {exc}"
    else:
        # 新建 notebook：仅允许 insert 语义（等价于从空 notebook 追加）
        if mode != "insert":
            return "[错误] notebook 不存在; 新建请使用 edit_mode=insert"
        nb = {"cells": [], "metadata": {}, "nbformat": 4, "nbformat_minor": 5}

    cells: List[Dict[str, Any]] = nb["cells"]
    minor = int(nb.get("nbformat_minor", 0) or 0)

    if mode == "insert":
        new_cell = _new_cell(ctype, new_source, minor)
        if cell_id:
            idx = _find_cell_index(cells, cell_id)
            insert_at = idx + 1  # 对标 Claude Code: 插到目标单元格之后
        else:
            insert_at = len(cells)
        cells.insert(insert_at, new_cell)
        action = f"插入 {ctype} 单元格到位置 {insert_at}"
    elif mode == "delete":
        if not cell_id:
            return "[错误] delete 模式必须提供 cell_id"
        idx = _find_cell_index(cells, cell_id)
        removed = cells.pop(idx)
        action = f"删除单元格 [{idx}] id={_cell_id(removed, idx)}"
    else:  # replace
        if not cell_id:
            return "[错误] replace 模式必须提供 cell_id"
        idx = _find_cell_index(cells, cell_id)
        cell = cells[idx]
        cell["cell_type"] = ctype
        cell["source"] = _source_to_list(new_source)
        cell.setdefault("metadata", {})
        if ctype == "code":
            # 输入已变, 旧输出不再可信 —— 与 Claude Code 一致地清空
            cell["outputs"] = []
            cell["execution_count"] = None
        else:
            cell.pop("outputs", None)
            cell.pop("execution_count", None)
        action = f"替换单元格 [{idx}] id={_cell_id(cell, idx)}"

    _save_notebook(p, copy.deepcopy(nb))
    ctx.mark_read(str(p))
    return f"{action}; 已保存 {_rel(ctx, p)} (共 {len(nb['cells'])} 个单元格)"


class NotebookPlugin(Plugin):
    name = "tools.notebook"
    provides = []
    requires = ["tool_registry"]

    def activate(self, kernel: Kernel) -> None:
        registry = kernel.require("tool_registry")
        registry.register(Tool(
            name="notebook_read",
            description="读取 Jupyter notebook 单元格概览 (下标 / id / 类型 / 源码摘要); "
                        "读取后可直接 notebook_edit 编辑。",
            parameters={
                "type": "object",
                "properties": {
                    "notebook_path": string_prop("notebook 文件路径 (.ipynb)"),
                    "cell_id": string_prop("只读某单元格 (可选; 单元格 id 或 cell-<下标>)"),
                },
                "required": ["notebook_path"],
            },
            handler=notebook_read, group="filesystem", read_only=True,
        ))
        registry.register(Tool(
            name="notebook_edit",
            description="按单元格编辑 Jupyter notebook (对标 Claude Code NotebookEdit)。"
                        "edit_mode=replace 需 cell_id; insert 可省略 cell_id(追加到末尾) "
                        "或指定后插入到该单元格之后; delete 需 cell_id。"
                        "仅支持 nbformat 4; 替换代码单元格会清空旧输出。",
            parameters={
                "type": "object",
                "properties": {
                    "notebook_path": string_prop("notebook 文件路径 (.ipynb)"),
                    "cell_id": string_prop("目标单元格 id 或 cell-<下标>"),
                    "new_source": string_prop("新源码 (replace/insert 必填)"),
                    "cell_type": {
                        "type": "string",
                        "enum": list(CELL_TYPES),
                        "description": "单元格类型, 默认 code",
                    },
                    "edit_mode": {
                        "type": "string",
                        "enum": list(EDIT_MODES),
                        "description": "编辑模式, 默认 replace",
                    },
                },
                "required": ["notebook_path"],
            },
            handler=notebook_edit, group="filesystem", dangerous=True,
        ))
