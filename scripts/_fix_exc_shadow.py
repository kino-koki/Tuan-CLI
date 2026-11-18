#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""修复 except 治理补日志时引入的 `as exc` 遮蔽/删除问题。

背景: 治理轮给大量 `except Exception:` 处理器补了 `as exc` + log。
Python 在 handler 退出时隐式 `del exc` —— 若函数参数/外层 handler 也叫 exc,
后续 `type(exc).__name__` 等引用会 UnboundLocalError (实测 loop_provider /
security_utils / tools.base 三处转红)。

修法: 对每个「引用点 X 已被某个 handler 退出删除」的位点, 找到**最后绑定 X
的 culprit handler**; 仅当其体内含治理新增的日志模板 (log.<level>(..., exc))
时, 把绑定改名为 `_fb_exc` 并同步改日志实参 —— 其余体内 exc 引用保持原名
(恢复其改写前对外层绑定的语义)。无治理日志模板的 culprit 属既有潜在问题,
只报告不改动。
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / "tuan_cli"


class Checker:
    def __init__(self, path):
        self.path = path
        self.deleted = set()
        self.last_binder = {}
        self.culprits = []          # (ref_lineno, name, handler_node)

    def visit_stmts(self, stmts):
        for s in stmts:
            self.visit_stmt(s)

    def visit_stmt(self, s):
        if isinstance(s, ast.Try) or s.__class__.__name__ == "TryStar":
            self.visit_stmts(s.body)
            for h in s.handlers:
                if h.name:
                    self.deleted.discard(h.name)
                    self.last_binder.pop(h.name, None)
                self.visit_stmts(h.body)
                if h.name:
                    self.deleted.add(h.name)
                    self.last_binder[h.name] = h
            self.visit_stmts(s.orelse)
            self.visit_stmts(s.finalbody)
        elif isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            saved_d, saved_b = set(self.deleted), dict(self.last_binder)
            self.visit_stmts(s.body)
            self.deleted, self.last_binder = saved_d, saved_b
        elif isinstance(s, ast.For):
            self.visit_exprs(s.iter)
            self._unbind(s.target)
            self.visit_stmts(s.body)
            self.visit_stmts(s.orelse)
        elif isinstance(s, ast.With) or s.__class__.__name__ == "AsyncWith":
            for item in s.items:
                self.visit_exprs(item.context_expr)
                if item.optional_vars is not None:
                    self._unbind(item.optional_vars)
            self.visit_stmts(s.body)
        elif isinstance(s, (ast.Assign, ast.AugAssign, ast.AnnAssign,
                            ast.Import, ast.ImportFrom)):
            self.visit_exprs(s)
            self._unbind(s)
        else:
            self.visit_exprs(s)
            for attr in ("body", "orelse", "finalbody"):
                sub = getattr(s, attr, None)
                if isinstance(sub, list):
                    self.visit_stmts(sub)

    def visit_exprs(self, node):
        for n in self._iter_local(node):
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load):
                if n.id in self.deleted:
                    h = self.last_binder.get(n.id)
                    if h is not None:
                        self.culprits.append((n.lineno, n.id, h))

    def _iter_local(self, node):
        """只遍历本语句的表达式, 不下钻子语句 (子语句由 visit_stmts 处理)。"""
        stack = list(ast.iter_child_nodes(node))
        stmt_like = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef,
                     ast.Lambda, ast.Try)
        while stack:
            n = stack.pop()
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef,
                              ast.ClassDef, ast.Lambda)):
                continue  # 作用域边界
            if isinstance(n, ast.Try) or n.__class__.__name__ in ("Try", "TryStar"):
                for h in n.handlers:
                    yield h.type
                continue
            if n.__class__.__name__ in ("If", "For", "While"):
                for f in ("test", "iter"):
                    v = getattr(n, f, None)
                    if v is not None:
                        yield v
                continue
            if n.__class__.__name__ in ("With", "AsyncWith"):
                for item in n.items:
                    yield item.context_expr
                continue
            yield n
            stack.extend(ast.iter_child_nodes(n))

    def _unbind(self, target):
        for n in ast.walk(target):
            if isinstance(n, ast.Name):
                self.deleted.discard(n.id)
                self.last_binder.pop(n.id, None)


def handler_refs_param(h, params):
    for n in ast.walk(h):
        if isinstance(n, ast.Name) and n.id in params and isinstance(n.ctx, ast.Load):
            return True
    return False


def main() -> int:
    culprits = {}   # (relpath, handler.lineno) -> handler node (需改名)
    reported = {}   # 无治理日志模板的既有隐患
    for p in sorted(TARGET.rglob("*.py")):
        rel = p.relative_to(ROOT).as_posix()
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        def walk_fns(node):
            for child in ast.iter_child_nodes(node):
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    params = {a.arg for a in (child.args.posonlyargs
                                              + child.args.args
                                              + child.args.kwonlyargs)}
                    if child.args.vararg: params.add(child.args.vararg.arg)
                    if child.args.kwarg: params.add(child.args.kwarg.arg)
                    c = Checker(rel)
                    c.visit_stmts(child.body)
                    for _ln, name, h in c.culprits:
                        key = (rel, h.lineno)
                        culprits.setdefault(key, h)
                    # 参数遮蔽: handler 绑定名 = 参数名且体内引用
                    for node2 in ast.walk(child):
                        if isinstance(node2, ast.Try):
                            for h in node2.handlers:
                                if h.name in params and handler_refs_param(h, params):
                                    if _has_our_log(h):
                                        culprits.setdefault((rel, h.lineno), h)
                                    else:
                                        reported.setdefault(key, h)
                walk_fns(child)
        walk_fns(tree)

    print(f"待改名 culprit handler: {len(culprits)}; 既有隐患(不动): {len(reported)}")
    changed = 0
    for (rel, hln), h in sorted(culprits.items()):
        path = ROOT / rel
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        i = h.lineno - 1
        line = lines[i]
        new_line = re.sub(r"as (\w+)(\s*:)", r"as _fb_exc\2", line, count=1)
        if new_line == line:
            print(f"  !! 未能改绑定 {rel}:{hln}")
            continue
        lines[i] = new_line
        old_name = re.search(r"as (\w+)", line).group(1)
        # handler 体内: 本语句日志模板的 exc 实参 → _fb_exc
        end = h.end_lineno or h.lineno
        for j in range(i, end):
            if "log." in lines[j] and f", {old_name})" in lines[j]:
                lines[j] = lines[j].replace(f", {old_name})", ", _fb_exc)")
        path.write_text("".join(lines), encoding="utf-8")
        changed += 1
    print(f"已改写 {changed} 个文件位置")
    return 0


def _has_our_log(h) -> bool:
    for n in ast.walk(h):
        if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and n.func.attr in ("debug", "info", "warning", "error")):
            src = ast.unparse(n)
            if "非致命异常已忽略" in src or "fallback 降级" in src or "降级" in src:
                return True
    return False


if __name__ == "__main__":
    raise SystemExit(main())
