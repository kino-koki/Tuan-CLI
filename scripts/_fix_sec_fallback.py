#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""except 治理 · 安全/审计路径 fallback 处理器补 log.debug。

对路径名命中 SEC_MARKERS 的模块里、被 audit_except 分类为 ``fallback``
(处理体有降级逻辑但无日志无重抛) 的宽 except 处理器, 在处理体首行插入
``log.debug("安全路径 fallback 降级: %s", exc)``:

- 行为零变化: 只加日志, 不改任何返回/降级逻辑;
- 处理器未绑定异常名时补 ``as exc`` (``except Exception:`` →
  ``except Exception as exc:``; 裸 ``except:`` → ``except as exc:``, 均合法);
- 模块无模块级 logger 时补 ``import logging`` + ``log = logging.getLogger``
  (插入位置由 AST 的顶层 import 结束行决定, 不破坏 ``__future__`` 与
  括号续行 import);
- 所有编辑按原始行号**降序**应用, 互不漂移;
- 幂等: 已有日志的处理器 (logged/rethrow) 自动跳过。

纯 stdlib; 用法: ``python scripts/_fix_sec_fallback.py``。
"""
from __future__ import annotations

import ast
import py_compile
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
from audit_except import SEC_MARKERS, classify, exc_type_name  # noqa: E402

TARGET = ROOT / "tuan_cli"
LOG_STMT = 'log.debug("安全路径 fallback 降级: %s", {bind})'


def logger_plan(tree: ast.Module, src: str) -> list[tuple[int, list[str]]]:
    """返回 logger 补齐编辑 [(0-based 插入下标, 行列表)]; 已有则空。"""
    if re.search(r"^(\w+)\s*=\s*(?:logging|structlog)\.getLogger", src, re.M):
        return []
    first_imp = None
    last_imp = 0
    has_logging_import = False
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            is_future = (isinstance(node, ast.ImportFrom)
                         and node.module == "__future__")
            if not is_future:
                if first_imp is None:
                    first_imp = node.lineno - 1
                last_imp = max(last_imp, node.end_lineno or node.lineno)
            if isinstance(node, ast.Import) and any(
                    a.name == "logging" for a in node.names):
                has_logging_import = True
    edits: list[tuple[int, list[str]]] = []
    if first_imp is None:  # 顶层只有 __future__ 或完全没有 import
        return [(last_imp, ["import logging\n", "\n",
                            "log = logging.getLogger(__name__)\n", "\n"])]
    if not has_logging_import:
        edits.append((first_imp, ["import logging\n"]))
    edits.append((last_imp, ["\n", "log = logging.getLogger(__name__)\n"]))
    return edits


def handler_edits(h: ast.ExceptHandler) -> list[tuple[int, str, list[str]]]:
    """单个 fallback 处理器的编辑, (0-based 行号, 类型, 内容) 降序应用。

    类型: replace1 (整行替换为多行) / insert (插入行) / modify (原行改写)。
    """
    bind = h.name or "exc"
    logstmt = LOG_STMT.format(bind=bind)
    body0 = h.body[0]
    edits: list[tuple[int, str, list[str]]] = []
    need_bind = h.name is None
    if body0.lineno == h.lineno:  # 单行 handler: except ...: body
        header = "except" if h.type is None else "except " + ast.unparse(h.type)
        if need_bind:
            header += " as exc"
        indent = " " * (h.col_offset + 4)
        # 原行冒号后的内容 (可能带行内注释) 作为处理体保留
        raw = (h.lineno, "split", [header, indent + logstmt])
        edits.append(raw)
        return edits
    if need_bind:
        edits.append((h.lineno - 1, "bind", []))
    edits.append((body0.lineno - 1, "insert",
                  [" " * body0.col_offset + logstmt + "\n"]))
    return edits


def apply_edits(lines: list[str],
                edits: list[tuple[int, str, list[str]]],
                src: str) -> list[str]:
    """按行号降序应用编辑; 同行号时先 insert/replace 后 bind/split。"""
    order = {"insert": 0, "replace1": 0, "split": 1, "bind": 2}
    for idx, kind, payload in sorted(
            edits, key=lambda e: (-e[0], order.get(e[1], 0))):
        if kind == "insert":
            lines[idx:idx] = payload
        elif kind == "replace1":
            lines[idx:idx + 1] = payload
        elif kind == "split":
            # idx 行原为 `except ...: body`; payload=[新头, 日志行]
            line = lines[idx]
            ci = line.index(":")
            header, rest = line[:ci].rstrip(), line[ci + 1:].lstrip()
            indent = " " * (len(line) - len(line.lstrip()) + 4)
            new = [header + ":\n", payload[1] + "\n"]
            if rest:
                new.append(indent + rest)
            lines[idx:idx + 1] = new
        elif kind == "bind":
            line = lines[idx]
            ci = line.index(":")
            lines[idx] = line[:ci] + " as exc" + line[ci:]
    return lines


def fix_file(path: Path) -> int:
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    edits: list[tuple[int, str, list[str]]] = []
    handlers = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        for h in node.handlers:
            if exc_type_name(h) not in ("Exception", "bare", "BaseException"):
                continue
            if classify(h) != "fallback":
                continue
            handlers.append(h)
    if not handlers:
        return 0
    for h in handlers:
        edits.extend(handler_edits(h))
    lines = src.splitlines(keepends=True)
    for idx, ins in logger_plan(tree, src):
        edits.append((idx, "insert", ins))
    lines = apply_edits(lines, edits, src)
    path.write_text("".join(lines), encoding="utf-8")
    py_compile.compile(str(path), doraise=True)
    return len(handlers)


def main() -> int:
    total = 0
    touched: list[str] = []
    for path in sorted(TARGET.rglob("*.py")):
        rel = path.relative_to(ROOT).as_posix()
        if not any(m in rel for m in SEC_MARKERS):
            continue
        n = fix_file(path)
        if n:
            touched.append(f"{rel}: {n}")
            total += n
    print(f"共补日志 {total} 处, 涉及 {len(touched)} 个文件:")
    for t in touched:
        print(" ", t)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
