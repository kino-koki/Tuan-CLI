#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一次性: 治理合并后回归的 [SEC] silent 站点 (13 处 / 5 文件)。"""
from __future__ import annotations

import re
from pathlib import Path

inv = Path("scripts/except_inventory.txt").read_text(encoding="utf-8")
sites: dict[str, list[tuple[int, int, str]]] = {}
in_s = False
for l in inv.splitlines():
    if l.startswith("== silent"):
        in_s = True
        continue
    if l.startswith("== fallback"):
        in_s = False
        continue
    if in_s and l.startswith("[SEC]"):
        m = re.match(r"\[SEC\] (\S+?):(\d+) \((\w+)\)", l)
        b = re.search(r"body@(\d+): (.*)$", l)
        sites.setdefault(m.group(1), []).append((int(m.group(2)), int(b.group(1)), b.group(2)))

print("SEC 回归站点:", sum(len(v) for v in sites.values()), "处 /", len(sites), "文件")
for rel, items in sites.items():
    p = Path(rel)
    lines = p.read_text(encoding="utf-8").splitlines()
    ops = []  # (index, kind, payload) —— 按行号降序统一应用, 避免位移
    for ln, bl, btxt in items:
        h = lines[ln - 1]
        if " as " not in h:
            nh = re.sub(r"except (Exception|BaseException)(\s*):", r"except \1 as exc\2:", h, count=1)
            assert nh != h and ":" in nh, (rel, ln, h)
            ops.append((ln - 1, "replace", nh))
        indent = re.match(r"\s*", lines[bl - 1]).group(0)
        level = "warning" if btxt.startswith("pass") else "debug"
        ops.append((bl - 1, "insert", f'{indent}log.{level}("安全路径静默吞已治理(补日志, 不改控制流): %s", exc)'))
    if not any(l.startswith("log = logging.getLogger") for l in lines):
        last = 0
        for i2, l2 in enumerate(lines):
            if re.match(r"^(import |from )", l2):
                last = i2 + 1
        ops += [(last, "insert", "log = logging.getLogger(__name__)"),
                (last, "insert", ""),
                (last, "insert", "import logging")]
    for idx, kind, payload in sorted(ops, key=lambda x: -x[0]):
        if kind == "replace":
            lines[idx] = payload
        else:
            lines.insert(idx, payload)
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"  {rel}: 修复 {len(items)} 处")
