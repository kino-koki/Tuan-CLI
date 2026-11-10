"""B 线「超 Claude Code」的**深度真实性基线**（只读，不改任何判据）。

为什么要单独做这一层
====================
``matrix.summary()`` 报 ``aligned 46 / ahead 10 / partial 9``，
``superiority.probe_all()`` 六维探针全绿 —— 但这两个数字都**不是
模块级**的：

- 六维探针是**聚合维度**（如 ``security_defaults`` 一个探针覆盖十几个
  模块），它绿只证明该维度挑出来的几个运行时检查通过；
- 46 个 ``aligned`` 里绝大多数只有 ``catalog.py`` 的一条 ``evidence``
  路径 + 一段 note，没有任何「真调该模块、断言行为」的探针。

若直接按 73.7% 覆盖率往「100%」堆功能，就是用户明确反对的「仅仅
广度」。本模块先**把水分量化出来**，再给出 26 个 gap 的逐项真实
缺失证据，作为下一轮逐域补齐的工作队列。

**刻意不改** ``fully_superior`` 的判据（它已写死在 ``matrix.py``，
任何一轮都不许靠修改判据提前达成）。本模块只提供新的可观测字段，
不参与裁决；``summary()`` 会把 ``module_depth`` 作为信息项带上。

三层证据（逐级变硬）：

1. ``path``  —— ``catalog`` 里列的 evidence 文件在仓库里存在；
2. ``note``  —— 有非空 note / ahead_reason 说明契约；
3. ``probe`` —— 注册在 ``MODULE_PROBES`` 的模块级运行时探针真调通过。

当前预期：第 3 层为 **0**，这不是「能力没做」，而是「做得深浅还
没被逐模块验证过」。如实列出，不包装成成果。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, List, Tuple

from . import catalog

# 模块级运行时探针注册表。当前为空 —— 下一轮起每消一个 gap / partial
# 就必须在这里注册一个真调代码的探针，否则不认「已验证」。
MODULE_PROBES: Dict[str, Callable[[], dict]] = {}


def register(module: str) -> Callable[[Callable[[], dict]], Callable[[], dict]]:
    def deco(fn: Callable[[], dict]) -> Callable[[], dict]:
        if module in MODULE_PROBES:
            raise ValueError("重复注册模块探针: %s" % module)
        MODULE_PROBES[module] = fn
        return fn
    return deco


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _path_evidence(m: Any) -> Tuple[bool, List[str]]:
    ok: List[str] = []
    bad: List[str] = []
    root = _repo_root()
    for rel in (m.evidence or ()):
        if not isinstance(rel, str) or not rel:
            continue
        (ok if (root / rel).exists() else bad).append(rel)
    return (not bad and bool(ok)), bad


def module_depth_audit() -> dict:
    """对全部非 gap / 非 na 模块逐项核销三层证据。"""
    rows: Dict[str, dict] = {}
    for m in catalog.MODULES:
        if m.status in (catalog.STATUS_GAP, catalog.STATUS_NA):
            continue
        path_ok, missing_paths = _path_evidence(m)
        note = (m.note or m.ahead_reason or "").strip()
        probe = MODULE_PROBES.get(m.name)
        probe_ok = False
        probe_evidence = "未注册模块级探针"
        if probe is not None:
            try:
                r = probe()
                probe_ok = bool(r.get("ok")) and not (r.get("problems") or [])
                probe_evidence = str(r.get("evidence") or "")
            except Exception as exc:  # noqa: BLE001
                probe_evidence = "探针抛 %s" % type(exc).__name__
        rows[m.name] = {
            "status": m.status, "domain": m.domain, "wave": m.wave,
            "path_ok": path_ok, "missing_paths": missing_paths,
            "note_present": bool(note), "probe_ok": probe_ok,
            "probe_evidence": probe_evidence,
        }
    claimed = len(rows)
    return {
        "claimed": claimed,
        "path_ok": sum(1 for r in rows.values() if r["path_ok"]),
        "note_present": sum(1 for r in rows.values() if r["note_present"]),
        "probe_verified": sum(1 for r in rows.values() if r["probe_ok"]),
        "runtime_verified_pct": round(
            sum(1 for r in rows.values() if r["probe_ok"]) * 100.0 / claimed,
            1) if claimed else 0.0,
        "rows": rows,
    }


def gap_queue() -> dict:
    """26 个 gap 的逐项**真实缺失证据** + 下一轮逐域顺序。

    这里不猜「该怎么实现」，只做可复现的静态核销：该模块在
    ``catalog`` 里声明的 evidence 文件是否存在、仓库里能否找到同名
    符号。结果是下一轮的工作队列，不是已完成清单。
    """
    root = _repo_root()
    items: List[dict] = []
    for m in catalog.MODULES:
        if m.status != catalog.STATUS_GAP:
            continue
        # A′ 实测修正：初版扫全仓 1300+ 个 .py 求符号命中，耗时
        # 18.8s，挂在 summary() 上会把每次矩阵查询拖垮。改成只核销
        # **本模块自己声明的 evidence 文件**（26 x <=3 个小文件），
        # 语义更精确（「声明的证据里有没有这个能力」），也可复现。
        exists: List[str] = []
        hits = 0
        for rel in (m.evidence or ()):
            if not isinstance(rel, str) or not (root / rel).exists():
                continue
            exists.append(rel)
            try:
                hits += (root / rel).read_text(
                    encoding="utf-8").count(m.name)
            except Exception:  # noqa: BLE001
                pass
        items.append({
            "name": m.name, "domain": m.domain, "wave": m.wave,
            "evidence_paths": list(m.evidence or ()),
            "evidence_present": exists,
            "symbol_hits_in_declared_evidence": hits,
            "note": (m.note or "").strip()[:180],
        })
    by_wave: Dict[str, int] = {}
    for it in items:
        by_wave[it["wave"]] = by_wave.get(it["wave"], 0) + 1
    return {
        "gaps": len(items),
        "by_wave": dict(sorted(by_wave.items())),
        "items": sorted(items, key=lambda x: (x["wave"], x["name"])),
    }


def baseline_report() -> dict:
    """只读总报告，供 ``matrix.summary()`` 作信息项带上。"""
    return {"module_depth": module_depth_audit(), "gap_queue": gap_queue()}
