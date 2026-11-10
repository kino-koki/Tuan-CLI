"""A 线最后 10 个 pending 模块的真实实现包（Codex TUI 对齐收尾）。

对应 ``tuan_cli/tui/parity/matrix.py`` 里剩余 10 个 ``PENDING``：

===================================  ==========================================
模块                                 实现文件 / 关键契约
===================================  ==========================================
``auto_review_denials``              ``approval_history.py::DenialLedger`` — 忽略即拒绝 / 去重 / 分桶 / 有界 ring
``insert_history``                   ``approval_history.py::HistoryBuffer`` — id 单调 / 越界拒绝 / 幂等 / backtrack 失效
``rendered_selection``               ``approval_history.py::SelectionGeometry`` — CJK 列宽 / hit==render
``local_settings``                   ``session_config.py::LocalSettings`` — 三层优先级 / 严格类型 / 不落盘
``clock_format``                     ``session_config.py::ClockFormat`` — 注入时钟 / 单调钳制 / 显式时区
``external_agent_config_migration``  ``session_config.py::migrate_external_agent_config`` — 单次模板替换 / 未知键留痕
``streaming``                        ``stream_exec.py::StreamAssembler`` — seq 单调 / done 拒绝 / render 纯读
``async_question_reply``             ``stream_exec.py::AsyncQuestionReply`` — 超时/取消/重复 / 绝不代答
``exec_command``                     ``stream_exec.py::ExecCommand`` — argv 强制 / 无 shell / 输出与超时上限
``tests``                            ``selftest.py::run_all_probes`` — 纯 stdlib 自检 harness
===================================  ==========================================

**深度而非广度**：每个模块不是「写个 note 指向文件」，而是在
``tui/parity/depth.py`` 注册一个**运行时探针** —— 真调代码、逐项断言
行为、返回结构化证据。``matrix.validate()`` 现在会对这 10 项逐一执行
``depth.run_probe()``，任一失败都算矩阵自检不通过；
``summary()["fully_identical"]`` 也加上 ``depth_ok`` 硬条件。

**延续前几轮实测过的真实缺陷**（不是凭空设计）：

- 链式 ``replace`` 二次替换（第 13 轮 ``model_migration``）
- hit / render 两套几何（第 13 轮 ``sidebar_tab_strip``）
- 渲染循环偷偷记活性（D4）、模型自问自答（B3 Elicitation）
- ``bool("false")`` / NaN 冒充数值、命令 ``shell=True`` 拼接
- 会话设置污染全局配置、自动审查决策被静默丢弃

**许可**：纯 Python 独立实现，按公开语义契约编写，**零 Rust 源码
复制**；见 ``NOTICE``。**本包不替换任何既有运行时对象**，不接 TUI
主循环，只提供可验证的对齐实现与探针。
"""
from __future__ import annotations

from typing import Dict, List

from . import approval_history as AH
from . import session_config as SC
from . import stream_exec as SE
from . import selftest as ST

__all__ = [
    "approval_history", "session_config", "stream_exec", "selftest",
    "MODULES", "PROBES", "codexkit_report", "codexkit_validate",
]

MODULES = (
    "auto_review_denials", "insert_history", "rendered_selection",
    "local_settings", "clock_format", "external_agent_config_migration",
    "streaming", "async_question_reply", "exec_command", "tests",
)

PROBES: Dict[str, object] = {
    "auto_review_denials": AH.probe_auto_review_denials,
    "insert_history": AH.probe_insert_history,
    "rendered_selection": AH.probe_rendered_selection,
    "local_settings": SC.probe_local_settings,
    "clock_format": SC.probe_clock_format,
    "external_agent_config_migration":
        SC.probe_external_agent_config_migration,
    "streaming": SE.probe_streaming,
    "async_question_reply": SE.probe_async_question_reply,
    "exec_command": SE.probe_exec_command,
    "tests": ST.probe_selftest,
}


def _to_probe_result(module: str) -> dict:
    fn = PROBES[module]
    r = fn()
    return {"ok": bool(r.get("ok")) and not (r.get("problems") or []),
            "checks": int(r.get("checks") or 0),
            "evidence": str(r.get("evidence") or ""),
            "problems": [str(x) for x in (r.get("problems") or [])]}


# ---------------------------------------------------------------- 注册到 depth
# 放在包导入时完成，保证 matrix.validate() 能看到全部 10 个探针。
try:
    from ..parity import depth as _depth
    for _m in MODULES:
        if _m not in _depth.PROBE_REGISTRY:
            _depth.register(_m)(lambda m=_m: _to_probe_result(m))
except Exception:  # noqa: BLE001 - 注册失败由 depth_audit 如实暴露
    pass


def codexkit_report() -> dict:
    return {"modules": len(MODULES), "probes": len(PROBES),
            "selftest": ST.run_all_probes()}


def codexkit_validate() -> List[str]:
    """自检：10 个探针全绿 + 纯 stdlib harness 全绿 + 既有安全接线。"""
    problems: List[str] = []
    for m in MODULES:
        try:
            r = _to_probe_result(m)
            if not r["ok"]:
                problems.append("%s: %s" % (
                    m, "; ".join(r["problems"]) or "ok=False"))
        except Exception as exc:  # noqa: BLE001
            problems.append("%s: raised %s" % (m, type(exc).__name__))
    rep = ST.run_all_probes()
    if not rep["ok"]:
        problems.extend("selftest: " + x for x in rep["problems"])
    try:
        from ..corekit.app import assert_wiring_intact
        w = assert_wiring_intact()
        if not w.intact:
            problems.extend("既有安全接线: " + x for x in w.problems)
    except Exception as exc:  # noqa: BLE001
        problems.append("既有安全接线校验不可用: %s" % type(exc).__name__)
    return problems
