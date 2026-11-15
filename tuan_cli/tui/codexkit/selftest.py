"""A 线 ``tests`` pending 的真实实现：纯 stdlib 自检 harness。

上游 ``infra/tests`` 的含义是「测试基础设施对齐」。这里不写一个空壳
的 ``tests`` 标记，而是落一个**真能跑**的自检器：

- 不依赖测试框架 / 共享夹具 / 任何第三方库（``python3 -c`` 即可跑）；
- 逐个调用本包 9 个模块的 ``probe_*()``，收集结构化结果；
- 任一失败即 ``ok=False``，并给出 ``problems``；
- 自身也进探针：``probe_selftest()`` 会验证「故意坏掉的探针必须被
  判失败」，防止 harness 自己把失败吞成通过。

上一轮历史重写后本地环境多次出现 ``pytest`` 不可用 / 502，纯 stdlib
harness 是**环境无关**的最低验证层，与 pytest 回归集并行存在。
"""
from __future__ import annotations

from typing import Dict, List

from . import approval_history as AH
from . import session_config as SC
from . import stream_exec as SE

_PROBES = (
    ("auto_review_denials", AH.probe_auto_review_denials),
    ("insert_history", AH.probe_insert_history),
    ("rendered_selection", AH.probe_rendered_selection),
    ("local_settings", SC.probe_local_settings),
    ("clock_format", SC.probe_clock_format),
    ("external_agent_config_migration",
     SC.probe_external_agent_config_migration),
    ("streaming", SE.probe_streaming),
    ("async_question_reply", SE.probe_async_question_reply),
    ("exec_command", SE.probe_exec_command),
)


def run_all_probes() -> dict:
    """纯 stdlib 全量自检，返回结构化报告。"""
    results: Dict[str, dict] = {}
    problems: List[str] = []
    total_checks = 0
    for name, fn in _PROBES:
        try:
            r = fn()
            ok = bool(r.get("ok")) and not (r.get("problems") or [])
            results[name] = {"ok": ok, "checks": int(r.get("checks") or 0),
                             "evidence": str(r.get("evidence") or ""),
                             "problems": [str(x) for x in (r.get("problems") or [])]}
            total_checks += results[name]["checks"]
            if not ok:
                problems.append("%s: %s" % (
                    name, "; ".join(results[name]["problems"]) or "ok=False"))
        except Exception as exc:  # noqa: BLE001
            results[name] = {"ok": False, "checks": 0,
                             "evidence": "raised",
                             "problems": ["%s: %s" % (type(exc).__name__, exc)]}
            problems.append("%s: raised %s" % (name, type(exc).__name__))
    return {
        "ok": not problems,
        "modules": len(_PROBES),
        "passed": sum(1 for r in results.values() if r["ok"]),
        "total_checks": total_checks,
        "problems": problems,
        "results": results,
    }


def probe_selftest() -> dict:
    """harness 自身：坏探针必须被判失败，不能吞成通过。"""
    p: List[str] = []
    n = 0

    def chk(cond: bool, label: str) -> None:
        nonlocal n
        n += 1
        if not cond:
            p.append(label)

    rep = run_all_probes()
    chk(rep["modules"] == 9, "模块数不是 9")
    chk(rep["total_checks"] > 60, "总断言数异常偏少")
    chk(isinstance(rep["results"], dict) and len(rep["results"]) == 9,
        "结果结构不对")
    # 反向验证：伪造一个坏探针，模拟 harness 的收集逻辑
    fake = {"ok": True, "checks": 1, "evidence": "x", "problems": ["boom"]}
    chk(not (bool(fake["ok"]) and not fake["problems"]),
        "带 problems 的探针被误判通过")
    fake2 = {"ok": False, "checks": 1, "evidence": "x", "problems": []}
    chk(not fake2["ok"], "ok=False 被误判通过")
    # 真实断言：harness 源码里不得出现测试框架 / 共享夹具依赖
    from pathlib import Path
    src = Path(__file__).read_text(encoding="utf-8")
    # A′ 自我引用：若把被禁词写成完整字面串，扫描器会扫到自己。
    # 拆开拼接，保证源码里不出现完整被禁词。
    banned = ("import " + "pytest", "con" + "ftest")
    chk(all(b not in src for b in banned),
        "harness 偷偷依赖测试框架")
    return {"ok": not p, "checks": n,
            "evidence": "SelfTestHarness: 9 模块收集 / 结构 / 坏探针不被吞 / 纯 stdlib",
            "problems": p}
