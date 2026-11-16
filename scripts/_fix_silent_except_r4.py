#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一次性脚本: except 治理第四轮 —— 清剩余全部静默吞 (web/cli/tui/tools/arch 等)。

取 scripts/except_inventory.txt silent 明细中的**全部剩余站点**, 逐处:
  - ``except Exception:`` 补 ``as exc`` 绑定 (如尚未绑定);
  - 处理体首行前插入日志 (文案含所在函数名);
  - 模块缺 logger 时自动补 ``import logging`` + ``log = logging.getLogger(__name__)``。

原则: **只加日志, 不改控制流**。级别: 处理体 pass -> warning; continue/return -> debug。
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INVENTORY = Path(__file__).resolve().parent / "except_inventory.txt"


def parse_sites() -> dict[str, list[dict]]:
    sites: dict[str, list[dict]] = {}
    in_silent = False
    for line in INVENTORY.read_text(encoding="utf-8").splitlines():
        if line.startswith("== silent"):
            in_silent = True
            continue
        if line.startswith("== fallback"):
            in_silent = False
            continue
        if not in_silent or line.startswith("[SEC]") or not line.strip():
            continue
        m = re.match(r"\s+(\S+?):(\d+) \((\w+)\)", line)
        if not m:
            continue
        rel, ln = m.group(1), int(m.group(2))
        body_m = re.search(r"body@(\d+): (.*)$", line)
        sites.setdefault(rel, []).append({
            "lineno": ln,
            "body_lineno": int(body_m.group(1)) if body_m else ln + 1,
            "body_text": body_m.group(2).strip() if body_m else "",
        })
    return sites


def func_map(src: str) -> list[tuple[int, int, str]]:
    out: list[tuple[int, int, str]] = []
    tree = ast.parse(src)

    def walk(nodes: list[ast.stmt], cls: str | None) -> None:
        for n in nodes:
            if isinstance(n, ast.ClassDef):
                walk(n.body, n.name)
            elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                name = f"{cls}.{n.name}" if cls else n.name
                out.append((n.lineno, n.end_lineno or n.lineno, name))
                walk(n.body, cls)

    walk(tree.body, None)
    return out


def func_at(spans: list[tuple[int, int, str]], lineno: int) -> str:
    best = None
    for s, e, name in spans:
        if s <= lineno <= e and (best is None or (e - s) < (best[1] - best[0])):
            best = (s, e, name)
    return best[2] if best else ""


def logger_name(src: str) -> str | None:
    for m in re.finditer(r"^(\w+) = logging\.getLogger\(", src, re.M):
        return m.group(1)
    return None


def main() -> None:
    sites = parse_sites()
    total = sum(len(v) for v in sites.values())
    print(f"第四轮待治理: {total} 处, 涉及 {len(sites)} 个文件")
    fixed = 0
    for rel, items in sorted(sites.items(), key=lambda kv: -len(kv[1])):
        path = ROOT / rel
        src = path.read_text(encoding="utf-8")
        lines = src.splitlines(keepends=False)
        spans = func_map(src)
        edits: list[tuple[int, str]] = []
        replaces: list[tuple[int, str, str]] = []

        lname = logger_name(src)
        if lname is None:
            tree = ast.parse(src)
            last_import = 0
            for node in tree.body:
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    last_import = max(last_import, node.end_lineno)
            if last_import == 0:
                print(f"  跳过(无 import 可锚定, 需手工): {rel}")
                continue
            # 逆序插入, 最终顺序为: 空行 / import logging / log = ...
            edits += [(last_import, "log = logging.getLogger(__name__)"),
                      (last_import, "import logging"),
                      (last_import, "")]
            lname = "log"

        for it in items:
            hidx = it["lineno"] - 1
            bidx = it["body_lineno"] - 1
            hline = lines[hidx]
            if it["body_lineno"] == it["lineno"]:
                print(f"  跳过(单行 except, 需手工): {rel}:{it['lineno']}: {hline.strip()[:70]}")
                continue
            if " as " not in hline:
                new_h = re.sub(r"except (Exception|BaseException)(\s*):",
                               r"except \1 as exc\2:", hline, count=1)
                assert new_h != hline and ":" in new_h, (rel, hline)
                replaces.append((hidx, hline, new_h))
            body_indent = re.match(r"\s*", lines[bidx]).group(0)  # type: ignore[union-attr]
            level = "warning" if it["body_text"].startswith("pass") else "debug"
            fname = func_at(spans, it["lineno"])
            where = f"{fname}(): " if fname else "模块顶层: "
            msg = f"{where}非致命异常已忽略(设计内降级, 不改控制流): %s"
            edits.append((bidx, f'{body_indent}{lname}.{level}("{msg}", exc)'))

        for idx, old, new in sorted(replaces, key=lambda x: -x[0]):
            assert lines[idx] == old, (rel, idx, lines[idx], old)
            lines[idx] = new
        for idx, text in sorted(edits, key=lambda x: -x[0]):
            lines.insert(idx, text)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        fixed += len(items)
        print(f"  {rel}: 修复 {len(items)} 处")
    print(f"共修复 {fixed} 处")


if __name__ == "__main__":
    main()
