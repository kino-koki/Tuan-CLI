#!/usr/bin/env python3
"""能力接线对照表生成器 (审计 #20)。

把 ``tuan_cli/tools/__init__.py::builtin_tool_plugins()`` 里的每个工具插件在
最小内核 (仅 config + tool_registry) 上真实激活一次, 记录:
  - 每个插件实际注册进 Agent 工具面的工具 (名称 / 只读 / 分组 / 暴露层级);
  - 激活失败的插件与其原因 (即「有 CLI 命令、无 Agent 工具」的接线缺口)。

输出 markdown 到 docs/capability_wiring.md (可用 --out 指定其他路径)。
纯本地、不触网、不建真实模型连接。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tuan_cli.core.kernel import Kernel  # noqa: E402
from tuan_cli.config import Config  # noqa: E402
from tuan_cli.tools import builtin_tool_plugins  # noqa: E402
from tuan_cli.tools.base import ToolRegistry  # noqa: E402
from tuan_cli.tools.tiers import CORE_TOOLS, DEFERRED_TOOLS  # noqa: E402

OUT = ROOT / "docs" / "capability_wiring.md"


def main() -> int:
    kernel = Kernel()
    kernel.provide("config", Config(), owner="wiring-dump")
    registry = ToolRegistry()
    kernel.provide("tool_registry", registry, owner="wiring-dump")

    rows: list[tuple[str, str, str, str]] = []   # tool, plugin, read_only, group
    gaps: list[tuple[str, str]] = []
    for plugin in builtin_tool_plugins():
        before = {t.name for t in registry.tools}
        try:
            plugin.activate(kernel)
        except Exception as exc:  # noqa: BLE001 - 如实记录接线缺口
            gaps.append((getattr(plugin, "name", type(plugin).__name__),
                         f"{type(exc).__name__}: {exc}"))
            continue
        added = {t.name for t in registry.tools} - before
        for name in sorted(added):
            tool = registry.tools[[t.name for t in registry.tools].index(name)]
            rows.append((name, str(getattr(plugin, "name", "")),
                         "yes" if getattr(tool, "read_only", False) else "no",
                         str(getattr(tool, "group", ""))))

    lines = [
        "# Agent 工具面能力接线对照表",
        "",
        "> 由 `python scripts/dump_tool_wiring.py` 生成 (审计 #20: 核对「有命令、",
        "> 无接线」)。方法: 在最小内核 (config + tool_registry) 上逐个真实激活",
        "> `builtin_tool_plugins()` 的全部插件, 记录其注册进注册表的工具。",
        f"> 生成时工具面共 **{len(rows)}** 个工具; 激活失败插件 **{len(gaps)}** 个。",
        "",
        "| 工具 | 注册插件 | 只读 | 分组 | 默认暴露层级 |",
        "|---|---|---|---|---|",
    ]
    for name, plugin, ro, group in rows:
        if name in CORE_TOOLS:
            tier = "core"
        elif name in DEFERRED_TOOLS:
            tier = "deferred (tool_search 按需检索)"
        else:
            tier = "extended"
        lines.append(f"| `{name}` | {plugin} | {ro} | {group} | {tier} |")

    lines += ["", "## 激活失败 / 需要额外服务的插件 (接线缺口)", ""]
    if gaps:
        lines += [f"- `{name}` — {reason}" for name, reason in gaps]
    else:
        lines += ["(无 —— 全部内置工具插件在最小内核上激活成功。)"]
    lines += [
        "",
        "## 口径说明",
        "",
        "- 本表只回答「Agent 工具面接了什么」; CLI 子命令面 (`tuan ...`) 是另一套",
        "  入口, 二者不一一对应。历史上 `create_artifact` / `send_message` /",
        "  `subagent` / `workflow` / `cron` / `gh` / `ecosystem` / `audit` /",
        "  `dispatch` 等只有 CLI 命令、未接 Agent 工具面, 0.4.5 起已补齐接线",
        "  (见 `tuan_cli/tools/__init__.py` 内注释)。",
        "- 「激活失败」多数表示该插件需要额外服务 (如 memory/skill 的引擎服务),",
        "  在完整内核里是否可用以运行时为准; 本表给出的是**最小内核**下的接线事实。",
    ]

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"written {OUT} ({len(rows)} tools, {len(gaps)} activation gaps)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
