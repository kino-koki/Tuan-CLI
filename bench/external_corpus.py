#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""外部对抗语料接入器 (审计 #22)。

用**你自己的**数据集评测 Tuan-CLI 安全检测层, 不要求把语料并入本仓库。

输入格式 (JSONL —— 每行一个 JSON 对象; 也接受单个 JSON 数组文件):

    {"name": "混淆变量拼接", "command": "a=rm; b=-rf; $a $b /", "expect": "block"}
    {"name": "git status",   "command": "git status",               "expect": "allow"}

字段:
  - name    可选, 展示名 (缺省用序号);
  - command 必填, 待判定命令全文 (不要截断, 截断会触发 P0-01 的 fail-closed 哨兵);
  - expect  "block" (应拦) 或 "allow" (应放行); 兼容 true/false。

判定口径与 bench/indep_verify.py 一致:
    拦 = tuan_cli.ext.safety_engine.is_hard_redline 或 is_redline 任一命中
    (硬红线 = 永不自动执行; 综合红线 = 需确认, 也绝不静默放行)。

结果: expect=block 未拦 → 漏拦 (硬缺陷, 记 MISS);
     expect=allow 被拦 → 误杀 (记 FP, 需人工判读, 不一定 fail)。
默认任何 MISS 即退出码 1; --ignore-fp 时 FP 不影响退出码。

用法:
    python bench/external_corpus.py --in my_corpus.jsonl
    python bench/external_corpus.py --in corpus.json --json out.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tuan_cli.ext import safety_engine as se  # noqa: E402


def load_cases(path: Path) -> list[dict]:
    # utf-8-sig: 容忍 Windows 工具链写出的带 BOM 文件
    raw = path.read_text(encoding="utf-8-sig", errors="replace")
    items: list[dict] = []
    if path.suffix.lower() == ".jsonl" or "\n" in raw.strip() and raw.lstrip().startswith("{"):
        for lineno, line in enumerate(raw.splitlines(), 1):
            line = line.strip()
            if not line:
                continue
            try:
                items.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise SystemExit(f"输入第 {lineno} 行不是合法 JSON: {exc}")
    else:
        data = json.loads(raw)
        if not isinstance(data, list):
            raise SystemExit("JSON 输入应为对象数组")
        items = data
    cases: list[dict] = []
    for i, it in enumerate(items):
        if not isinstance(it, dict) or not isinstance(it.get("command"), str):
            raise SystemExit(f"第 {i} 条缺少字符串字段 command: {it!r}")
        expect_raw = it.get("expect", "block")
        if isinstance(expect_raw, bool):
            expect = "block" if expect_raw else "allow"
        else:
            expect = str(expect_raw).lower()
        if expect not in ("block", "allow"):
            raise SystemExit(f"第 {i} 条 expect 必须是 block/allow, 得到 {expect_raw!r}")
        cases.append({"name": str(it.get("name") or f"case-{i}"),
                      "command": it["command"], "expect": expect})
    return cases


def run(cases: list[dict]) -> dict:
    ok = misses = fps = errors = 0
    miss_rows: list[dict] = []
    fp_rows: list[dict] = []
    err_rows: list[dict] = []
    for c in cases:
        try:
            got = bool(se.is_hard_redline(c["command"]) or se.is_redline(c["command"]))
        except Exception as exc:  # noqa: BLE001 - 引擎异常按 fail-closed 口径单列
            errors += 1
            err_rows.append({"name": c["name"], "command": c["command"],
                             "error": f"{type(exc).__name__}: {exc}"})
            continue
        expect_block = c["expect"] == "block"
        if got == expect_block:
            ok += 1
        elif expect_block:
            misses += 1
            miss_rows.append(c)
        else:
            fps += 1
            fp_rows.append(c)
    return {"total": len(cases), "match": ok, "miss": misses, "false_positive": fps,
            "engine_error": errors, "miss_rows": miss_rows, "fp_rows": fp_rows,
            "err_rows": err_rows}


def main() -> int:
    ap = argparse.ArgumentParser(description="外部对抗语料接入评测")
    ap.add_argument("--in", dest="inp", required=True, help="语料文件 (.jsonl 或 .json)")
    ap.add_argument("--json", dest="json_out", default=None, help="结果 JSON 输出路径")
    ap.add_argument("--ignore-fp", action="store_true",
                    help="误杀 (FP) 不影响退出码 (默认 FP 只警告; MISS 永远 fail)")
    args = ap.parse_args()

    cases = load_cases(Path(args.inp))
    res = run(cases)

    print(f"外部语料: {res['total']} 条")
    print(f"  判定一致 : {res['match']}")
    print(f"  漏拦 MISS: {res['miss']}  (期望拦但放行 —— 硬缺陷)")
    print(f"  误杀 FP  : {res['false_positive']}  (期望放行但被拦 —— 需人工判读)")
    print(f"  引擎异常 : {res['engine_error']}")
    for r in res["miss_rows"][:20]:
        print(f"  MISS {r['name']}: {r['command']!r}")
    for r in res["fp_rows"][:20]:
        print(f"  FP   {r['name']}: {r['command']!r}")
    for r in res["err_rows"][:20]:
        print(f"  ERR  {r['name']}: {r['error']}")

    if args.json_out:
        Path(args.json_out).write_text(json.dumps(
            {k: v for k, v in res.items()}, ensure_ascii=False, indent=2),
            encoding="utf-8")

    if res["miss"] or res["engine_error"]:
        return 1
    if res["false_positive"] and not args.ignore_fp:
        print("存在误杀 (FP): 默认按 fail 处理; 若属保守 fail-closed 设计内 escalation, "
              "请逐条判读后用 --ignore-fp 重跑。")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
