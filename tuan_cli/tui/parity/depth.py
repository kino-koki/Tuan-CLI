"""TUI 对齐矩阵的**深度真实性判据**（A 线）。

为什么需要这一层
================
前面十几轮把 ``pending`` 从 30 一路压到 10，靠的是把每个模块写进
``EXPLICIT_ALIGNED`` / ``EXPLICIT_LOCALIZED`` 并指向实现文件。这能证明
「有代码」，但**证明不了「跑起来行为真的对」**：一条 note 指向某个
.py 文件，文件可能存在却没人调用、常量可能被改、状态机可能退化成
空壳。如果只按这张表报百分比，就是用户明确反对的「仅仅广度」。

本模块把「对齐」重新定义成**可执行契约**：

    aligned / localized  !=  写了一行 note
    aligned / localized  ==  有一个注册在 PROBE_REGISTRY 的运行时探针，
                             真调该模块的代码，逐项断言行为，且全部通过

``run_probe`` 真调函数、捕获异常、计时、返回结构化 ``ProbeResult``；
``depth_audit()`` 对**所有**非 pending / 非 not_applicable 的模块逐项
核验，返回 ``verified / claimed / ok / missing``。矩阵 ``summary()``
的 ``fully_identical`` 现在要求 ``pending == 0`` **且** ``depth_ok``。

**刻意不做的两件事**（与前几轮立场一致）：

- 不缓存探针结果。每次 ``depth_audit()`` 都重跑，判定不依赖缓存
  时间点；探针本身必须是纯内存、无文件 I/O、无网络的。
- 不因为「探针没注册」就自动把模块降级成 pending。状态表与探针表
  是两张独立证据：前者记「实现了什么」，后者记「验证到什么程度」，
  ``missing`` 如实列出，不许靠改状态定义凑数。

许可：纯 Python 独立实现，零 Rust 源码复制；见 ``NOTICE``。
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Dict, List, Tuple

# 探针签名：返回 {"ok": bool, "checks": int, "evidence": str,
#                 "problems": [str, ...]}。不许抛异常出门（由 run_probe 兜住）。
ProbeFn = Callable[[], dict]

PROBE_REGISTRY: Dict[str, ProbeFn] = {}
_REGISTRY_READY = False


def _ensure_registry() -> None:
    """触发实现包导入，让探针完成注册。

    A′ 实测修正：注册写在 ``codexkit/__init__.py``，若 ``depth_audit()``
    只 import matrix 而不 import 实现包，10 个探针一个都不会出现，
    ``depth_verified`` 直接报 0 —— 这是审计器自己的假阴性。
    """
    global _REGISTRY_READY
    if _REGISTRY_READY:
        return
    _REGISTRY_READY = True
    try:
        import importlib
        importlib.import_module("tuan_cli.tui.codexkit")
    except Exception:  # noqa: BLE001 - 导入失败由 missing 如实暴露
        pass


@dataclass(frozen=True)
class ProbeResult:
    module: str
    ok: bool
    checks: int
    evidence: str
    problems: Tuple[str, ...] = ()
    elapsed_ms: float = 0.0

    def to_dict(self) -> dict:
        return {
            "module": self.module, "ok": self.ok, "checks": self.checks,
            "evidence": self.evidence, "problems": list(self.problems),
            "elapsed_ms": round(self.elapsed_ms, 3),
        }


def register(module: str) -> Callable[[ProbeFn], ProbeFn]:
    """注册探针；重复注册直接报错（避免两个实现互相覆盖还显示通过）。"""
    def deco(fn: ProbeFn) -> ProbeFn:
        if module in PROBE_REGISTRY:
            raise ValueError("重复注册探针: %s" % module)
        PROBE_REGISTRY[module] = fn
        return fn
    return deco


def run_probe(module: str) -> ProbeResult:
    """真调一次探针。**任何异常都算不通过**，绝不静默降级为「未验证=通过」。"""
    fn = PROBE_REGISTRY.get(module)
    if fn is None:
        return ProbeResult(module, False, 0, "未注册运行时探针",
                           ("unverified: no probe registered",))
    t0 = time.perf_counter()
    try:
        r = fn()
        if not isinstance(r, dict):
            return ProbeResult(module, False, 0, "探针返回值不是 dict",
                               ("probe_return_type: %s" % type(r).__name__),
                               (time.perf_counter() - t0) * 1000)
        problems = tuple(str(x) for x in (r.get("problems") or []))
        ok = bool(r.get("ok")) and not problems
        return ProbeResult(module, ok, int(r.get("checks") or 0),
                           str(r.get("evidence") or ""), problems,
                           (time.perf_counter() - t0) * 1000)
    except Exception as exc:  # noqa: BLE001 - 探针异常即不通过
        return ProbeResult(module, False, 0,
                           "探针抛出 %s" % type(exc).__name__,
                           ("probe_raised: %s: %s" % (type(exc).__name__, exc)),
                           (time.perf_counter() - t0) * 1000)


def run_all() -> Dict[str, ProbeResult]:
    _ensure_registry()
    return {m: run_probe(m) for m in sorted(PROBE_REGISTRY)}


def depth_audit() -> dict:
    """对矩阵里全部 aligned / localized 逐项核验，返回可观测报告。

    ``ok`` 为 True 的充要条件：claimed 里每一项都有探针且探针通过。
    ``missing`` 如实列出无探针或失败的模块，**不自动改状态**。
    """
    _ensure_registry()
    from .matrix import parity_status, ALIGNED, LOCALIZED
    claimed: List[str] = [r.module for r in parity_status()
                          if r.status in (ALIGNED, LOCALIZED)]
    results = {m: run_probe(m) for m in claimed}
    verified = [m for m, r in results.items() if r.ok]
    missing = [m for m, r in results.items() if not r.ok]
    total = len(claimed)
    return {
        "claimed": total,
        "verified": len(verified),
        "ok": total > 0 and not missing,
        "coverage_pct": round(len(verified) * 100.0 / total, 1) if total else 0.0,
        "missing": missing,
        "results": {m: r.to_dict() for m, r in results.items()},
    }


def assert_depth_intact() -> dict:
    """供 ``validate()`` 调用：任一新增对齐项没探针/探针失败都算问题。"""
    _ensure_registry()
    from .matrix import NEW_DEPTH_MODULES
    problems: List[str] = []
    checked = 0
    for m in NEW_DEPTH_MODULES:
        r = run_probe(m)
        checked += 1
        if not r.ok:
            problems.append("%s: %s" % (m, ", ".join(r.problems) or r.evidence))
    return {"checked": checked, "problems": problems, "intact": not problems}


# ---------------------------------------------------------------- 注册既有层
# 第 11–13 轮落的三个包各有 validate()，把它们包装成模块级探针。
# 注意：这些 validate() 返回「问题描述列表」，空列表才代表通过。
def _wrap_package_probe(package: str, fn_name: str) -> ProbeFn:
    def _probe() -> dict:
        import importlib
        mod = importlib.import_module(package)
        problems = getattr(mod, fn_name)()
        return {"ok": not problems, "checks": 1,
                "evidence": "%s.%s() -> %d problems" % (
                    package, fn_name, len(problems)),
                "problems": [str(p) for p in problems]}
    return _probe


for _pkg, _fn in (
    ("tuan_cli.tui.inputkit", "inputkit_validate"),
    ("tuan_cli.tui.corekit", "corekit_validate"),
    ("tuan_cli.tui.configkit", "configkit_validate"),
):
    try:
        import importlib as _il
        _m = _il.import_module(_pkg)
        if hasattr(_m, _fn):
            PROBE_REGISTRY["__package__:" + _pkg] = _wrap_package_probe(_pkg, _fn)
    except Exception:  # noqa: BLE001 - 包不可导入时不注册，audit 会如实暴露
        pass
