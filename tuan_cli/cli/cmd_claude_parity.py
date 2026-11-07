"""``tuan claude parity`` —— 「超 Claude Code v2.1.319」的可核验态势。

把「全模块超越」变成**可观测、可核销**的状态，而不是一句口号：
默认打印中文摘要；``--report-json`` 输出结构化报告供 CI / 文档生成；
``--gaps`` 列出 30 个待补齐模块及其轮次；``--probes`` 展开六个
超越维度的运行时探针明细。

上游基线、14 域 99 模块清单与六维判据见
``tuan_cli/parity_claude/`` 与 ``CLAUDE_PARITY.md``。
"""
from __future__ import annotations

import json
from typing import Any


def cmd_claude_parity(args: Any) -> int:
    from ..parity_claude import claude_parity_report

    report = claude_parity_report()
    wants_json = bool(getattr(args, "report_json", False))
    show_gaps = bool(getattr(args, "gaps", False))
    show_probes = bool(getattr(args, "probes", False))

    if wants_json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return 1 if report["validate"] else 0

    b = report["baseline"]
    m = report["matrix"]
    ev = report["evidence"]
    print("[claude parity] 与 Claude Code v2.1.319 的全模块对照态势")
    print(f"  上游      : {b['cc_product']} {b['cc_version']} "
          f"({b['cc_date']}, tag {b['cc_tag_timestamp']})")
    print(f"  来源      : {b['sources']} 条 (官方 changelog / release / "
          f"功能目录 / SDK 概览 / 归档)")
    print(f"  规模      : {len(b['domains'])} 个功能域 · "
          f"{m['total_modules']} 个模块 · {len(b['waves'])} 个轮次")
    st = m["by_status"]
    print(f"  模块状态  : ahead {st['ahead']} · aligned {st['aligned']} · "
          f"partial {st['partial']} · gap {st['gap']} · "
          f"not_applicable {st['not_applicable']}")
    print(f"  证据      : {sum(v['evidence_ok'] for v in ev['by_status'].values())} "
          f"个模块证据可核验 · {len(ev['problems'])} 处问题")
    print(f"  领先      : 声明 {m['ahead_declared']} 项 / "
          f"探针已证实 {m['ahead_verified']} 项 "
          f"(未证实维度: {', '.join(m['dimensions_unverified']) or '无'})")
    print(f"  差距      : {m['gaps']} 个 gap，分布在 "
          f"{len(set(g['wave'] for g in m['gap_queue']))} 个轮次")

    w = m["security_wiring"]
    print(f"  安全接线  : 既有链路{'完好' if w['intact'] else '异常'} · "
          f"{len(w['checks'])} 项检查")
    c = m["superiority_criteria"]
    print("  超越判据  : " + " · ".join(
        f"{k}={'✓' if v else '✗'}" for k, v in c.items()))
    print(f"  完全超越  : {'是' if m['fully_superior'] else '否'} "
          f"(如实：gap 未清零 / 第三方自适应红队未做)")

    if show_probes:
        print("\n  六维运行时探针:")
        for d, r in report["probes"].items():
            mark = "OK" if r["ok"] else "UNVERIFIED"
            print(f"    [{mark:10s}] {d:24s} {r['detail']}")

    if report["validate"]:
        for p in report["validate"]:
            print(f"  !! 自检失败: {p}")
    else:
        print("  自检      : OK (证据 / 派生一致性 / 六维探针 / 既有安全接线)")
    if show_gaps:
        rows = m["gap_queue"]
        print(f"\n  待补齐队列 ({len(rows)}):")
        for g in rows:
            print(f"    - {g['wave']:4s} {g['domain']:22s} {g['module']}")
        print("\n  下一轮 B2: OS 沙箱默认化 / 网络默认拒 / 凭据代理注入 / "
              "denyInsteadOfPrompting / worktree 逃逸证明")
    print("\n  归属: NOTICE 第 14 条 · CLAUDE_PARITY.md · "
          "tuan_cli/parity_claude/")
    print("  A 线并行: tuan tui parity (Codex TUI 对齐，还剩 10 个 pending)")
    return 1 if report["validate"] else 0


from .parser import _register_command  # noqa: E402

_register_command("cmd_claude_parity", ".cmd_claude_parity")
