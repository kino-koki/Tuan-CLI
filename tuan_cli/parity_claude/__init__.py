"""Tuan × Claude Code v2.1.319 全模块超越计划：**机器可核验的基线**。

这是 B 线的第 1 轮（B1）。与 A 线（把 TUI 对齐 OpenAI Codex）并行：

  - A 线：``tuan_cli/tui/parity`` + ``TUI_PARITY.md``；续轮 XI 后
  ``pending=0``，但 ``fully_identical`` 加严为「还须深度探针全覆盖」，
  当前 ``depth_verified/depth_claimed`` 见 ``matrix.summary()``；
  - B 线：本包 + ``CLAUDE_PARITY.md``，对标 Claude Code **v2.1.319**
    （GitHub tag v2.1.319, 2026-11-06），目标是全模块补齐并反超。

包内分工：
  - ``catalog.py``     14 个功能域 / 逐模块能力清单（带 CC 版本引用、
                        状态、证据路径、领先理由、轮次）；
  - ``evidence.py``    运行时校验证据路径真实存在，五态定义互相约束；
  - ``superiority.py`` 六个「超越维度」的**运行时探针**（真调现有代码）；
  - ``matrix.py``      统计、差距队列、「何时算超越」的硬判据、一致性自检。

**本轮真实落地**（不是只写计划）：``tuan_cli/hooks/manager.py`` 的两个
fail-open 侧门被修：

  1. hook 的 spawn 失败 / 超时 / 异常 / 无模型 / 非零退出原先一律
     ``return None``，``run_pre`` 对 ``None`` 直接 ``continue`` → **静默放行**。
     现在全部记入 ``failures()`` 并默认 ``on_failure="block"`` 阻断
     PreToolUse，带结构化原因与审计。CC 的 ``onFailure:"block"`` 需要
     用户逐条 hook 显式配置，旧行为正是静默 fail-open。
  2. ``blocking`` 默认 False 会吞掉 hook 返回的 ``{"block": true}``
     （只记 ``block_denied``）。现在默认 True，仍可显式关闭。

因此 ``fail_closed_default`` 维度的探针会真实跑通，而不是文档自述。

**合规**：Claude Code 是 Anthropic 专有产品。本包只做公开文档/changelog
的行为契约对标，**未复制任何源码、未使用其商标资产**；「超」仅指可验证
的能力与安全姿态对比。见 ``NOTICE`` 第 14 条。
"""
from __future__ import annotations

from typing import Any, Dict

from . import catalog, evidence, matrix, superiority

__all__ = [
    "catalog", "evidence", "matrix", "superiority",
    "claude_parity_report", "claude_parity_validate",
]


def claude_parity_report() -> Dict[str, Any]:
    """``tuan claude parity`` 的结构化报告（含探针结果）。"""
    probes = superiority.probe_all()
    return {
        "baseline": catalog.constants(),
        "sources": [dict(x) for x in catalog.SOURCES],
        "evidence": evidence.evidence_report(),
        "probes": {d: r.to_dict() for d, r in probes.items()},
        "matrix": matrix.summary(probes),
        "waves": [dict(x) for x in catalog.WAVES],
        "validate": matrix.validate(probes),
    }


def claude_parity_validate() -> list[str]:
    """CI 入口：证据 / 矩阵 / 探针 / 既有安全接线，一项不过即非空。"""
    return matrix.validate()
