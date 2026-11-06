"""``tuan tui parity`` —— 输出与 OpenAI Codex TUI 的对齐态势。

用途：把「完全相同但有本地化」变成**可观测、可核销**的状态，而不是一句
口号。默认打印中文摘要；``--report-json`` 输出结构化报告供 CI / 文档生成消费；
``--gaps`` 列出待对齐模块队列。

上游源码规模、165 个模块、键位表与布局常量均来自本地完整解压核查，
见 ``tuan_cli/tui/parity/upstream_spec.py`` 与 ``TUI_PARITY.md``。
"""
from __future__ import annotations

import json
import sys
from typing import Any


def cmd_tui_parity(args: Any) -> int:
    from ..tui.parity import parity_report, parity_validate, matrix, keymap

    report = parity_report()
    problems = parity_validate()
    wants_json = bool(getattr(args, "report_json", False))
    show_gaps = bool(getattr(args, "gaps", False))

    if wants_json:
        out = dict(report)
        out["validate"] = problems
        if show_gaps:
            out["gaps"] = [{"group": g, "module": m} for g, m in matrix.gaps()]
        print(json.dumps(out, ensure_ascii=False, indent=2, sort_keys=True))
        return 1 if problems else 0

    s = report["scale"]
    m = report["matrix"]
    km = report["keymap"]
    i18 = report["i18n"]
    print("[tui parity] 与 OpenAI Codex TUI 的对齐态势")
    print(f"  上游      : {s['upstream']} / {s['crate']} ({s['license']})")
    print(f"  规模      : {s['top_level_modules']} 个顶层模块 · "
          f"{s['rs_files']} 个 .rs · {s['rs_lines']} 行 · "
          f"跳过 {s['snapshot_files_skipped']} 个快照文件")
    print(f"  渲染栈    : {s['language']} + {'/'.join(s['render_stack'])} "
          f"→ 本地 Python + prompt_toolkit/rich (本地化实现)")
    print(f"  组件状态  : aligned {m['by_status']['aligned']} · "
          f"localized {m['by_status']['localized']} · "
          f"not_applicable {m['by_status']['not_applicable']} · "
          f"pending {m['by_status']['pending']}")
    print(f"  覆盖率    : 宽口径 {m['coverage_pct']}% · "
          f"严格对齐 {m['aligned_pct']}% · "
          f"逐值对齐 {m['aligned_only_pct']}%")
    print(f"  键位      : {km['contexts']} 个 context · {km['actions']} 个动作 · "
          f"{km['actions_with_binding']} 个已绑定 · {km['conflicts']} 处冲突")
    print(f"  文案      : {len(i18['languages'])} 语言 · {i18['total_keys']} 条 "
          f"(en / zh-CN 全量)")
    ik = report.get("inputkit", {})
    if isinstance(ik, dict) and "modules" in ik:
        print(f"  输入层    : inputkit {ik['modules']} 个模块已对齐 "
              f"(第 11 轮: vim_search / activation / copy_guard / "
              f"custom_terminal / status / hyperlinks / viz_instructions)")
    print(f"  完全相同  : {'是' if m['fully_identical'] else '否'} "
          f"(还有 {m['pending']} 个模块待对齐)")
    if problems:
        for p in problems:
            print(f"  !! 自检失败: {p}")
    else:
        print("  自检      : OK (组件树 / 键位 / 文案覆盖自洽)")
    if show_gaps:
        gaps = matrix.gaps()
        print(f"\n  待对齐队列 ({len(gaps)}):")
        for g, mod in gaps:
            print(f"    - {g:22s} {mod}")
        print("\n  下一轮优先: core_app 组 9 个 (见 TUI_PARITY.md §5)")
    print("\n  归属: NOTICE 第 9 条 · THIRD_PARTY_LICENSES/ · TUI_PARITY.md")
    return 1 if problems else 0


from .parser import _register_command  # noqa: E402

_register_command("cmd_tui_parity", ".cmd_tui_parity")
