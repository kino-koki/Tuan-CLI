#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""except Exception 治理 · 第一步: 全量盘点与风险分类。

扫描 ``tuan_cli/`` 下所有 ``except Exception`` / 裸 ``except:`` 处理器,
按处理体行为分为四类:

  rethrow    处理体含 raise (重抛/包装重抛) —— 语义最完整, 无需处理
  logged     处理体含日志调用但吞掉异常 —— 可接受, 视重要性升级日志级别
  silent     处理体只有 pass/continue/return 常量等 —— **静默吞, 治理重点**
  fallback   处理体有其他逻辑 (赋值/调用/降级) 但不留痕 —— 次优先治理

输出: 终端汇总 + 完整清单写入 ``scripts/except_inventory.txt``。
安全/审计路径 (路径名含 security/safety/audit/sandbox/taint/guard/trust/crypto)
在清单中标记 [SEC], 供优先治理排序。

纯 stdlib; 用法: ``python scripts/audit_except.py``。
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / "tuan_cli"
REPORT = Path(__file__).resolve().parent / "except_inventory.txt"

SEC_MARKERS = ("security", "safety", "audit", "sandbox", "taint", "guard",
               "trust", "crypto", "whitelist", "blacklist")

LOG_ATTRS = {"debug", "info", "warning", "warn", "error", "exception",
             "critical", "log", "trace"}


def is_log_call(node: ast.AST) -> bool:
    """是否为日志调用: < anything >.debug(...) 形态 (log/logger/console 等)。"""
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        return node.func.attr in LOG_ATTRS
    return False


def classify(handler: ast.ExceptHandler) -> str:
    """按处理体行为分类 (优先级: rethrow > logged > silent > fallback)。"""
    has_log = False
    has_raise = False
    only_trivial = True  # 是否只由 pass/continue/return 常量构成
    for node in ast.walk(handler):
        if isinstance(node, ast.Raise):
            has_raise = True
        if is_log_call(node):
            has_log = True
        if isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign,
                             ast.For, ast.While, ast.If, ast.With,
                             ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            only_trivial = False
        if isinstance(node, ast.Return):
            # return 常量/空 仍算 trivial; return 带复杂表达式按 fallback
            if node.value is not None and not isinstance(
                    node.value, (ast.Constant, ast.Name, ast.List, ast.Tuple, ast.Dict)):
                only_trivial = False
        if isinstance(node, ast.Expr) and not isinstance(node.value, ast.Constant):
            only_trivial = False
    if has_raise:
        return "rethrow"
    if has_log:
        return "logged"
    if only_trivial:
        return "silent"
    return "fallback"


def exc_type_name(handler: ast.ExceptHandler) -> str:
    t = handler.type
    if t is None:
        return "bare"
    return ast.unparse(t)


def main() -> int:
    rows: list[tuple[str, int, str, str, str]] = []  # (relpath, lineno, kind, category, snippet)
    for path in sorted(TARGET.rglob("*.py")):
        rel = path.relative_to(ROOT).as_posix()
        src = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(src)
        except SyntaxError as exc:  # noqa: BLE001
            print(f"跳过语法错误文件 {rel}: {exc}", file=sys.stderr)
            continue
        lines = src.splitlines()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Try):
                continue
            for h in node.handlers:
                tname = exc_type_name(h)
                if tname not in ("Exception", "bare", "BaseException"):
                    continue
                cat = classify(h)
                snippet = (lines[h.lineno - 1] or "").strip()
                body_line = h.body[0].lineno if h.body else h.lineno
                rows.append((rel, h.lineno, tname, cat,
                             f"{snippet}  | body@{body_line}: {(lines[body_line - 1] or '').strip()[:70]}"))

    counts: dict[str, int] = {"rethrow": 0, "logged": 0, "silent": 0, "fallback": 0}
    sec_counts: dict[str, int] = {"rethrow": 0, "logged": 0, "silent": 0, "fallback": 0}
    for rel, _ln, _t, cat, _s in rows:
        counts[cat] += 1
        if any(m in rel for m in SEC_MARKERS):
            sec_counts[cat] += 1

    print(f"共扫描到 except Exception/裸except: {len(rows)} 处")
    print(f"  全仓分布 : {counts}")
    print(f"  安全/审计路径分布: {sec_counts}")
    print(f"  治理重点 silent 全仓 {counts['silent']} 处, 其中安全/审计路径 {sec_counts['silent']} 处")

    by_file: dict[str, dict[str, int]] = {}
    for rel, _ln, _t, cat, _s in rows:
        by_file.setdefault(rel, {"rethrow": 0, "logged": 0, "silent": 0, "fallback": 0})
        by_file[rel][cat] += 1
    silent_files = sorted(by_file.items(), key=lambda kv: -kv[1]["silent"])

    with REPORT.open("w", encoding="utf-8") as fh:
        fh.write("except Exception 盘点 (scripts/audit_except.py 生成)\n")
        fh.write(f"总计 {len(rows)}; 分类 {counts}; 安全/审计 {sec_counts}\n\n")
        fh.write("== 按文件汇总 (silent 降序) ==\n")
        for rel, c in silent_files:
            if sum(c.values()) == 0:
                continue
            fh.write(f"{rel}: total={sum(c.values())} {c}\n")
        fh.write("\n== silent 明细 (治理清单) ==\n")
        for rel, ln, tname, cat, snippet in rows:
            if cat != "silent":
                continue
            sec = "[SEC]" if any(m in rel for m in SEC_MARKERS) else "     "
            fh.write(f"{sec} {rel}:{ln} ({tname}) {snippet[:90]}\n")
        fh.write("\n== fallback 明细 ==\n")
        for rel, ln, tname, cat, snippet in rows:
            if cat != "fallback":
                continue
            sec = "[SEC]" if any(m in rel for m in SEC_MARKERS) else "     "
            fh.write(f"{sec} {rel}:{ln} ({tname}) {snippet[:90]}\n")
        fh.write("\n== logged 明细 ==\n")
        for rel, ln, tname, cat, snippet in rows:
            if cat != "logged":
                continue
            fh.write(f"{rel}:{ln} ({tname}) {snippet[:90]}\n")
    print(f"完整清单已写入 {REPORT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
