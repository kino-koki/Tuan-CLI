"""「超 Claude Code v2.1.319」矩阵统计、差距队列与一致性自检。

**「何时可以说超越」的判据**（写死在代码里，不靠文档口号）：

    fully_superior = (
        gaps == 0
        and 六个维度探针全部 ok
        and 每个维度至少 1 个已证实 ahead 模块
        and 所有 B 轮次路线都已标记完成
        and external_red_team is True      # 第三方自适应红队, 外部条件
    )

当前 ``external_red_team=False`` 且 gaps > 0，所以 **必然是 false**。
任何一轮都不许通过修改这个判据来"提前达成"。

派生一致性（防靠改状态定义凑数）：
  - 各状态计数之和 == 模块总数；
  - 各 domain 计数之和 == 模块总数；
  - ``gaps()`` 长度 == gap 状态数；
  - 每个 gap 的 wave 合法且唯一，wave_load 里能反查到；
  - 每个超越维度至少有一个 ahead 声明，且都有对应探针；
  - 既有 6 条安全接线仍完好（调用第 12 轮 corekit 的
    ``assert_wiring_intact()``）。
"""
from __future__ import annotations

from typing import Any, Dict, List

from . import catalog, evidence, superiority


def _existing_security_wiring() -> Dict[str, Any]:
    """硬约束：B 线每一轮都必须验证没有重开前 13 轮修好的侧门。"""
    try:
        from ..tui.corekit.app import assert_wiring_intact
        w = assert_wiring_intact()
        return {"intact": bool(w.intact),
                "checks": dict(getattr(w, "checks", {}) or {}),
                "problems": list(getattr(w, "problems", []) or [])}
    except Exception as exc:  # noqa: BLE001
        return {"intact": False, "checks": {},
                "problems": [f"接线校验不可用: {type(exc).__name__}: {exc}"]}


def summary(probes: Dict[str, superiority.ProbeResult] | None = None
            ) -> Dict[str, Any]:
    probes = probes if probes is not None else superiority.probe_all()
    ahead = superiority.verified_ahead(probes)
    by_status = {s: sum(1 for m in catalog.MODULES if m.status == s)
                 for s in catalog.STATUSES}
    gaps = evidence.gaps()
    dim_ahead = evidence.ahead_by_dimension()
    external_red_team = False  # 第三方自适应红队尚未做，如实
    dims_all_ok = all(probes[d].ok for d in catalog.SUPERIORITY_DIMENSIONS)
    dims_have_ahead = all(dim_ahead[d] for d in catalog.SUPERIORITY_DIMENSIONS)
    b_waves = [w["wave"] for w in catalog.WAVES if w["wave"].startswith("B")]
    b_waves_done: List[str] = ["B1"]  # 本轮完成；后续轮次逐步加入
    fully_superior = (
        by_status[catalog.STATUS_GAP] == 0
        and dims_all_ok
        and dims_have_ahead
        and all(w in b_waves_done for w in b_waves)
        and external_red_team
    )
    return {
        "cc_version": catalog.CC_VERSION,
        "cc_date": catalog.CC_DATE,
        "total_modules": len(catalog.MODULES),
        "domains": len(catalog.DOMAINS),
        "by_status": by_status,
        "domain_counts": evidence.domain_counts(),
        "gaps": len(gaps),
        "gap_queue": [{"domain": d, "module": m, "wave": w} for d, m, w in gaps],
        "wave_load": {k: len(v) for k, v in evidence.wave_load().items()},
        "ahead_declared": ahead["declared_ahead"],
        "ahead_verified": ahead["verified_ahead"],
        "ahead_verified_by_dim": ahead["verified"],
        "ahead_unverified_by_dim": ahead["unverified"],
        "dimensions_ok": ahead["dimensions_ok"],
        "dimensions_unverified": ahead["dimensions_unverified"],
        "superiority_criteria": {
            "gaps_zero": by_status[catalog.STATUS_GAP] == 0,
            "all_probes_ok": dims_all_ok,
            "every_dimension_has_ahead": dims_have_ahead,
            "all_b_waves_done": all(w in b_waves_done for w in b_waves),
            "external_adaptive_red_team": external_red_team,
        },
        "fully_superior": fully_superior,
        "b_waves_done": b_waves_done,
        "security_wiring": _existing_security_wiring(),
    }


def validate(probes: Dict[str, superiority.ProbeResult] | None = None
             ) -> List[str]:
    """返回问题描述列表；空列表 = 矩阵与接线自洽。"""
    probes = probes if probes is not None else superiority.probe_all()
    problems: List[str] = list(evidence.verify_evidence())
    s = summary(probes)

    # ---- 派生一致性
    if sum(s["by_status"].values()) != s["total_modules"]:
        problems.append("状态计数之和 != 模块总数")
    if sum(d["total"] for d in s["domain_counts"].values()) != s["total_modules"]:
        problems.append("各域计数之和 != 模块总数")
    if s["gaps"] != s["by_status"][catalog.STATUS_GAP]:
        problems.append("gaps() 长度 != gap 状态数")
    wave_names = {w["wave"] for w in catalog.WAVES}
    for m in catalog.MODULES:
        if m.status == catalog.STATUS_GAP and m.wave not in wave_names:
            problems.append(f"gap {m.name} 的 wave {m.wave!r} 不在路线表中")
    load = evidence.wave_load()
    for d, mod, wave in evidence.gaps():
        if mod not in load.get(wave, []):
            problems.append(f"gap {mod} 未出现在 wave_load[{wave}]")
    for dim in catalog.SUPERIORITY_DIMENSIONS:
        if dim not in superiority.PROBES:
            problems.append(f"维度 {dim} 没有运行时探针")
        if not evidence.ahead_by_dimension()[dim]:
            problems.append(f"维度 {dim} 没有任何 ahead 模块声明")
    if len(superiority.PROBES) != len(catalog.SUPERIORITY_DIMENSIONS):
        problems.append("探针数与超越维度数不一致")

    # ---- 领先必须经探针证实（未证实的如实列出，但不算错误：
    #      探针失败是发现问题的信号，由 report 显式呈现）
    w = s["security_wiring"]
    if not w["intact"]:
        problems.extend(f"既有安全接线: {p}" for p in w["problems"])
    return problems


def constants() -> Dict[str, Any]:
    return {"statuses": list(catalog.STATUSES),
            "waves": [x["wave"] for x in catalog.WAVES],
            "fully_superior_criteria": [
                "gaps_zero", "all_probes_ok", "every_dimension_has_ahead",
                "all_b_waves_done", "external_adaptive_red_team"]}
