"""证据校验：让「已对齐 / 领先 / 部分」不能靠文档一句话成立。

每个 ``Module.evidence`` 是仓库内相对路径（文件或目录）。本模块在运行时
**真实检查路径存在**：

  - ``ahead`` / ``aligned`` / ``partial`` / ``gap``：证据路径必须全部存在；
    ``not_applicable`` 允许空证据（但必须写 note 说明为何不适用）；
  - ``ahead`` 另外必须给 ``ahead_reason`` 与合法的 ``ahead_dim``；
  - ``gap`` 必须分配到 ``catalog.WAVES`` 里的某个 wave；
  - 同一模块名不得重复，domain 必须在 ``DOMAINS`` 内。

这样「改状态定义凑数」会被自检拦下：想把 gap 改成 ahead，就必须补
真实存在的证据、写清领先理由并归属某个维度，而该维度还得有运行时
探针跑通（见 ``superiority.py``）。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

from . import catalog

# tuan_cli/parity_claude/evidence.py -> 仓库根需上溯 2 层
REPO_ROOT = Path(__file__).resolve().parents[2]


def repo_root() -> Path:
    return REPO_ROOT


def path_exists(rel: str) -> bool:
    """相对仓库根的路径存在（文件或目录均可），且不允许逃出仓库。"""
    if not rel or not isinstance(rel, str):
        return False
    p = (REPO_ROOT / rel).resolve()
    try:
        p.relative_to(REPO_ROOT)
    except ValueError:
        return False
    return p.exists()


def missing_paths(mod: catalog.Module) -> List[str]:
    return [e for e in mod.evidence if not path_exists(e)]


def verify_evidence() -> List[str]:
    """返回问题描述列表；空列表 = 全部证据可核验。"""
    problems: List[str] = []
    seen: Dict[str, int] = {}
    for m in catalog.MODULES:
        seen[m.name] = seen.get(m.name, 0) + 1
        if m.domain not in catalog.DOMAINS:
            problems.append(f"{m.name}: 未知 domain {m.domain!r}")
        if m.status not in catalog.STATUSES:
            problems.append(f"{m.name}: 未知 status {m.status!r}")
        for miss in missing_paths(m):
            problems.append(f"{m.name}: 证据路径不存在 {miss}")
        if not m.note.strip():
            problems.append(f"{m.name}: 缺少说明")
        if m.status == catalog.STATUS_NA:
            if m.wave:
                problems.append(f"{m.name}: not_applicable 不应分配 wave")
        else:
            if not m.evidence:
                problems.append(f"{m.name}: 非 not_applicable 模块必须有证据路径")
        if m.status == catalog.STATUS_AHEAD:
            if not m.ahead_reason.strip():
                problems.append(f"{m.name}: ahead 缺少 ahead_reason")
            if m.ahead_dim not in catalog.SUPERIORITY_DIMENSIONS:
                problems.append(f"{m.name}: ahead 维度 {m.ahead_dim!r} 非法")
        elif m.ahead_reason or m.ahead_dim:
            problems.append(f"{m.name}: 非 ahead 模块不得携带 ahead_reason/dim")
        if m.status == catalog.STATUS_GAP:
            waves = {w["wave"] for w in catalog.WAVES}
            if m.wave not in waves:
                problems.append(f"{m.name}: gap 未分配到有效 wave ({m.wave!r})")
        elif m.wave and m.status != catalog.STATUS_GAP:
            # aligned/partial/ahead 允许标 wave 表示「仍会再加强」，但必须合法
            waves = {w["wave"] for w in catalog.WAVES}
            if m.wave not in waves:
                problems.append(f"{m.name}: 非法 wave {m.wave!r}")
    for name, n in seen.items():
        if n > 1:
            problems.append(f"模块名重复 {name} x{n}")
    return problems


def evidence_report() -> Dict[str, Any]:
    """可观测：每个状态的证据覆盖率。"""
    by_status: Dict[str, Dict[str, int]] = {}
    for s in catalog.STATUSES:
        mods = [m for m in catalog.MODULES if m.status == s]
        with_ev = [m for m in mods if m.evidence and not missing_paths(m)]
        by_status[s] = {"modules": len(mods), "evidence_ok": len(with_ev)}
    return {
        "repo_root": str(REPO_ROOT),
        "total_modules": len(catalog.MODULES),
        "by_status": by_status,
        "problems": verify_evidence(),
    }


def domain_counts() -> Dict[str, Dict[str, int]]:
    out: Dict[str, Dict[str, int]] = {}
    for d in catalog.DOMAINS:
        mods = [m for m in catalog.MODULES if m.domain == d]
        row = {s: sum(1 for m in mods if m.status == s)
               for s in catalog.STATUSES}
        row["total"] = len(mods)
        out[d] = row
    return out


def gaps() -> List[Tuple[str, str, str]]:
    """返回 ``(domain, module, wave)``，按 wave 再 domain 排序。"""
    rows = [(m.domain, m.name, m.wave) for m in catalog.MODULES
            if m.status == catalog.STATUS_GAP]
    return sorted(rows, key=lambda r: (r[2], r[0], r[1]))


def ahead_by_dimension() -> Dict[str, List[str]]:
    out: Dict[str, List[str]] = {d: [] for d in catalog.SUPERIORITY_DIMENSIONS}
    for m in catalog.MODULES:
        if m.status == catalog.STATUS_AHEAD:
            out[m.ahead_dim].append(m.name)
    return out


def wave_load() -> Dict[str, List[str]]:
    out: Dict[str, List[str]] = {w["wave"]: [] for w in catalog.WAVES}
    for m in catalog.MODULES:
        if m.wave and m.wave in out:
            out[m.wave].append(m.name)
    return out


def readme_languages() -> Sequence[str]:
    """真实统计仓库里全部 README（含英文 README.md），供本地化探针使用。

    英文原文是 ``README.md``，其余语言是 ``README_<lang>.md``，两者相加
    才是完整的 10 语言口径；只数带下划线的会少算英文。
    """
    return sorted(p.name for p in REPO_ROOT.glob("README*.md"))
