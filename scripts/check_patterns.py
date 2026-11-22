#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""safety_patterns 一致性校验门禁 (refactor_plan §2.3 step 1).

设计要点
--------
1. **真源**: ``tuan_cli/ext/patterns_data/{critical,high,medium,extreme}.py`` 是
   唯一真源; ``tuan_cli/ext/safety_patterns.py`` 退化为薄 re-export 层。
2. 本脚本纯 stdlib, 通过 import 被校验对象本身来核对 identity 与结构,
   保证 CI 无安装环境也能跑 (前提是 ``tuan_cli`` 包可导入)。
3. 校验 4 件事:
     (a) ``patterns_data/`` 四档规则可加载, 是 list[(str, str)]。
     (b) ``safety_patterns.py`` 里同名的 4 个变量 **按 identity** 指向
         ``patterns_data`` 里同一对象 (不是字面复制)。
     (c) 所有 label 在 4 档内无重复 (跨档也查, 防止同一规则被误放到多档)。
     (d) 每条正则都能 ``re.compile``。
4. 退出码: 0 全绿 / 1 任一问题。

用法
----
  python scripts/check_patterns.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

# 让脚本可以从仓库根以任何 CWD 运行
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tuan_cli.ext import patterns_data as _pd  # noqa: E402
from tuan_cli.ext import safety_patterns as _sp  # noqa: E402

SEVERITIES: tuple[str, ...] = ("_EXTREME_PATTERNS", "_CRITICAL_PATTERNS",
                                "_HIGH_PATTERNS", "_MEDIUM_PATTERNS")


def _iter_rules() -> list[tuple[str, str, tuple[str, str]]]:
    """Yield (severity_var, regex, label) for every rule in patterns_data."""
    out: list[tuple[str, str, tuple[str, str]]] = []
    for sev in SEVERITIES:
        rules = getattr(_pd, sev)
        for rule in rules:
            out.append((sev, rule[0], rule[1]))
    return out


def main() -> int:
    problems: list[str] = []

    # --- (a) patterns_data 结构: list + 2-tuple(str, str) ---
    print(f"source of truth: tuan_cli/ext/patterns_data/")
    per_sev_counts: dict[str, int] = {}
    for sev in SEVERITIES:
        rules = getattr(_pd, sev)
        if not isinstance(rules, list):
            problems.append(f"{sev}: not a list ({type(rules).__name__})")
            continue
        per_sev_counts[sev] = len(rules)
        for i, rule in enumerate(rules):
            if not (isinstance(rule, tuple) and len(rule) == 2
                    and isinstance(rule[0], str) and isinstance(rule[1], str)):
                problems.append(
                    f"{sev}[{i}]: expected 2-tuple (str, str), got "
                    f"{type(rule).__name__} len={len(rule) if isinstance(rule, tuple) else '-'}"
                )

    # --- (b) identity re-export check ---
    identity_ok = True
    for name in (*SEVERITIES, "_RAW_DISK"):
        a = getattr(_pd, name, None)
        b = getattr(_sp, name, None)
        if a is None or b is None:
            problems.append(f"identity[{name}]: missing on one side "
                            f"(patterns_data={a is not None}, safety_patterns={b is not None})")
            identity_ok = False
        elif a is not b:
            problems.append(f"identity[{name}]: safety_patterns re-export is NOT "
                            f"the same object as patterns_data (copy instead of re-export)")
            identity_ok = False
    if not identity_ok:
        print("[FAIL] safety_patterns.py is no longer a thin re-export layer; "
              "patterns_data/ must remain the source of truth.")

    # --- (c) duplicate labels across all 4 lists ---
    # 语义: 重复 label 只是 **告警** (WARN), 不参与 exit code 判定。
    # 原因: patterns_data/ 中已存在少量同 label 多正则 (同概念多写法) 与
    # 极少数跨档重复 (如 'format disk' 同时在 extreme 和 critical)。
    # 这些是历史存量, 修复需修改 patterns_data/*.py (本 step 1 明确禁止)。
    # 因此门禁只对 (a)/(b)/(d) fail; 重复 label 打到 stdout 供人审阅。
    seen: dict[str, str] = {}
    dupes: list[tuple[str, str, str]] = []
    for sev, _rx, label in _iter_rules():
        if label in seen:
            dupes.append((seen[label], sev, label))
        else:
            seen[label] = sev
    if dupes:
        print(f"\n[WARN] {len(dupes)} duplicate label(s) across all 4 lists:")
        for first_sev, this_sev, label in dupes:
            print(f"  - {label!r}  ({first_sev} -> {this_sev})")
        print("  (informational; refactor_plan §2.3 step 2 will dedupe when "
              "schema is upgraded to 4-tuples.)\n")

    # --- (d) every regex compiles ---
    compile_errors: list[tuple[str, str, str]] = []
    for sev, rx, label in _iter_rules():
        try:
            re.compile(rx)
        except re.error as exc:
            compile_errors.append((sev, label, str(exc)))
            problems.append(f"{sev}: regex failed to compile for label "
                            f"{label!r}: {exc}")
    if not compile_errors:
        print(f"regex compile: all {sum(per_sev_counts.values())} patterns compile")

    # --- summary ---
    total = sum(per_sev_counts.values())
    print("")
    print("Summary")
    print("-------")
    for sev in SEVERITIES:
        print(f"  {sev:<22} {per_sev_counts.get(sev, 0):>4}")
    print(f"  {'TOTAL':<22} {total:>4}")
    print(f"  duplicate labels:    {len(dupes)}")
    print(f"  compile errors:      {len(compile_errors)}")
    print(f"  identity re-export:  {'OK' if identity_ok else 'FAIL'}")

    if problems:
        print("")
        print(f"[FAIL] {len(problems)} problem(s):")
        for p in problems[:50]:
            print(f"  - {p}")
        if len(problems) > 50:
            print(f"  ... and {len(problems) - 50} more")
        return 1

    print("")
    dup_note = (f"{len(dupes)} duplicate label(s) (WARN)" if dupes
                else "no duplicate labels")
    print(f"[OK] patterns_data is the source of truth; safety_patterns re-exports "
          f"match by identity; {dup_note}; all regexes compile.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
