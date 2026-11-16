#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一次性脚本: except 治理第三轮 —— runtime/ 与 core/ 的 non-SEC 静默吞。

从 scripts/except_inventory.txt 的 silent 明细中取**未标记 [SEC]**、且位于
``tuan_cli/runtime/`` 与 ``tuan_cli/core/`` 的全部站点, 逐处:
  - ``except Exception:`` 补 ``as exc`` 绑定 (如尚未绑定);
  - 处理体首行前插入日志, 文案含所在函数名, 便于定位;
  - 模块缺 logger 时自动补 ``import logging`` + ``log = logging.getLogger(__name__)``。

原则: **只加日志, 不改控制流**。级别规则与第二轮一致:
  处理体 pass -> warning; continue/return -> debug。
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
        if not re.match(r"tuan_cli/(runtime|core)/", rel):
            continue
        body_m = re.search(r"body@(\d+): (.*)$", line)
        sites.setdefault(rel, []).append({
            "lineno": ln,
            "body_lineno": int(body_m.group(1)) if body_m else ln + 1,
            "body_text": body_m.group(2).strip() if body_m else "",
        })
    return sites


def func_map(src: str) -> list[tuple[int, int, str]]:
    """[(start_line, end_line, 显示名)] —— 方法带类名前缀, 取最小-span 匹配。"""
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
    return best[2] if best else "module"


def logger_name(src: str) -> str | None:
    for m in re.finditer(r"^(\w+) = logging\.getLogger\(", src, re.M):
        return m.group(1)
    return None


def main() -> None:
    sites = parse_sites()
    total = sum(len(v) for v in sites.values())
    print(f"第三轮待治理: {total} 处, 涉及 {len(sites)} 个文件")
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
            assert last_import > 0, rel
            edits += [(last_import, ""), (last_import, "import logging"),
                      (last_import, "log = logging.getLogger(__name__)")]
            lname = "log"

        for it in items:
            hidx = it["lineno"] - 1
            bidx = it["body_lineno"] - 1
            hline = lines[hidx]
            if it["body_lineno"] == it["lineno"]:
                raise SystemExit(f"{rel}:{it['lineno']}: 单行 except, 请手工处理: {hline}")
            if " as " not in hline:
                new_h = re.sub(r"except (Exception|BaseException)(\s*):",
                               r"except \1 as exc\2:", hline, count=1)
                assert new_h != hline and ":" in new_h, (rel, hline)
                replaces.append((hidx, hline, new_h))
            body_indent = re.match(r"\s*", lines[bidx]).group(0)  # type: ignore[union-attr]
            level = "warning" if it["body_text"].startswith("pass") else "debug"
            fname = func_at(spans, it["lineno"])
            msg = f"{fname}(): 非致命异常已忽略(设计内降级, 不改控制流): %s"
            edits.append((bidx, f'{body_indent}{lname}.{level}("{msg}", exc)'))

        for idx, old, new in sorted(replaces, key=lambda x: -x[0]):
            assert lines[idx] == old, (rel, idx, lines[idx], old)
            lines[idx] = new
        for idx, text in sorted(edits, key=lambda x: -x[0]):
            lines.insert(idx, text)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"  {rel}: 修复 {len(items)} 处")


if __name__ == "__main__":
    main()
