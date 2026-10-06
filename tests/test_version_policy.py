# -*- coding: utf-8 -*-
"""版本政策强制检查器的测试。

目标: 证明 scripts/check_version_policy.py 真的会拦住违规,
      而不是一个永远返回 0 的摆设。
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "check_version_policy.py"
CI_YML = REPO_ROOT / ".github" / "workflows" / "ci.yml"


def _load():
    spec = importlib.util.spec_from_file_location("check_version_policy", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


mod = _load()


# ---------------------------------------------------------------- 解析与折算
def test_parse_version():
    assert mod.parse_version("0.2.014") == (0, 2, 14)
    assert mod.parse_version("1.10.7") == (1, 10, 7)
    # 1.0 起支持两段写法, 缺省补丁段按 0 处理
    assert mod.parse_version("1.0") == (1, 0, 0)
    assert mod.parse_version("2.0") == (2, 0, 0)


def test_parse_version_rejects_garbage():
    with pytest.raises(mod.VersionError):
        mod.parse_version("not-a-version")


def test_to_units_matches_0001_increment():
    # 0.0.001 是数值化比较的最小单位 (to_units 仅用于比大小, 不再作为递增上限)
    assert mod.to_units((0, 2, 15)) - mod.to_units((0, 2, 14)) == 1
    assert mod.to_units((0, 3, 0)) - mod.to_units((0, 2, 999)) == 1


# ---------------------------------------------------------------- 规则: 禁止回退 / CHANGELOG 对齐
def test_single_increment_passes():
    assert mod.check("0.2.014", "0.2.013", "0.2.014") == []


def test_large_jump_allowed():
    # 1.0 起采用 SemVer, 递增幅度不限 (破坏性变更升 MAJOR)
    assert mod.check("0.2.016", "0.2.013", "0.2.016") == []
    assert mod.check("1.0", "0.2.018", "1.0") == []


def test_downgrade_blocked():
    problems = mod.check("0.2.011", "0.2.014", "0.2.011")
    assert any("回退" in p for p in problems)


def test_same_version_allowed():
    # 未发版重复 push 属正常情况, 同版本不再判违规
    assert mod.check("0.2.014", "0.2.014", "0.2.014") == []


def test_changelog_mismatch_blocked():
    problems = mod.check("0.2.014", "0.2.013", "0.2.011")
    assert any("CHANGELOG" in p for p in problems)


# ---------------------------------------------------------------- 仓库现状
def test_repo_versions_are_in_sync():
    """pyproject.toml 与 qingxiaotuan/__init__.py 必须一致(曾长期不同步)。"""
    pv = mod.read_pyproject_version()
    iv = mod.read_init_version()
    assert pv and iv, "两处版本号都应可读"
    assert mod.parse_version(pv) == mod.parse_version(iv), (
        f"版本不一致: pyproject={pv} vs __init__={iv}"
    )


def test_repo_version_matches_changelog_top():
    top = mod.read_changelog_top_version()
    pv = mod.read_pyproject_version()
    assert top and pv
    assert mod.parse_version(top) == mod.parse_version(pv)


def _changelog_versions() -> list[str]:
    import re

    text = (REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    return re.findall(r"(?m)^##\s*\[([0-9]+\.[0-9]+(?:\.[0-9]{1,3})?)\]", text)


def test_current_repo_state_passes_policy():
    """以『上一个 CHANGELOG 条目』为基线(= 上一次迭代), 当前仓库应合规。

    注意: 这里刻意不用 git HEAD 作基线 —— 本仓库存在多次迭代未提交的累积漂移
    (HEAD=0.2.0 vs 工作区=0.2.014), 对比 HEAD 会把 14 次迭代的增量算成一次违规。
    """
    versions = _changelog_versions()
    if len(versions) < 2:
        pytest.skip("CHANGELOG 条目不足")
    pv = mod.read_pyproject_version()
    problems = mod.check(pv, versions[1], versions[0])
    assert problems == [], problems


def test_git_drift_is_reported_not_silently_ignored():
    """暴露(而非隐藏)『多次迭代未提交』造成的版本漂移。

    这条不是断言失败, 而是把漂移量化出来, 提醒维护者及时提交/发版。
    """
    pv = mod.read_pyproject_version()
    base = mod.git_show_head_version()
    if base is None:
        pytest.skip("无 git 历史")
    delta = mod.to_units(mod.parse_version(pv)) - mod.to_units(mod.parse_version(base))
    # 漂移存在是事实, 这里仅记录; 折算单位 0.0.001, 值越大说明未提交的迭代越多
    print(f"\n[版本漂移] git HEAD={base} -> 工作区={pv}, 折算 +0.0.{delta:03d} (数值化差值 {delta})")
    assert delta >= 0, "工作区版本不应低于 git HEAD"


# ---------------------------------------------------------------- CI 接线
def test_ci_runs_version_policy_gate():
    """确保 CI 真的会跑这个门禁(否则机制形同虚设)。"""
    if not CI_YML.exists():
        pytest.skip("无 CI 配置")
    data = yaml.safe_load(CI_YML.read_text(encoding="utf-8"))
    steps = []
    for job in (data.get("jobs") or {}).values():
        steps.extend(job.get("steps") or [])
    joined = " ".join(str(s.get("run", "")) for s in steps)
    assert "check_version_policy.py" in joined, "CI 未接入版本政策门禁"
