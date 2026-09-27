"""功能1: SkillDistiller 端到端蒸馏闭环测试。

覆盖:
  - 多步任务后生成提议
  - 提议质量门控 (太短不提议)
  - 用户确认后技能写入磁盘
  - 下次相似任务自动激活 (activate_for_task)
  - /distill 手动触发 (DistillLoop 纯逻辑)
  - 配置项 auto_propose / min_tool_calls
"""

from __future__ import annotations

from pathlib import Path

from qingxiaotuan.skills.manager import SkillManager
from qingxiaotuan.self_improve.distill_loop import (
    DistillLoop,
    DistillProposal,
    count_steps,
    quality_gate,
)


def _mgr(tmp_path: Path) -> SkillManager:
    return SkillManager(tmp_path)


def test_multistep_task_produces_proposal(tmp_path):
    """≥3 个工具调用的多步任务应产出蒸馏提议。"""
    mgr = _mgr(tmp_path)
    loop = DistillLoop(skill_manager=mgr)
    loop.start_task("给 FastAPI 路由加鉴权并跑通测试")
    for tool in ["read_file", "edit_file", "run_tests"]:
        loop.record_tool_call(tool, ok=True)
    p = loop.maybe_propose()
    assert p is not None, "多步任务应产出提议"
    assert p.name
    assert len(p.source_tools) >= 3


def test_quality_gate_rejects_short_draft():
    """描述过短 / 步骤不足的草稿不通过门控。"""
    good = DistillProposal(
        name="好技能",
        description="这是一个足够长的技能描述, 超过十个字的门槛",
        body="1. 第一步\n2. 第二步\n3. 第三步\n",
    )
    assert quality_gate(good) is True

    short_desc = DistillProposal(name="x", description="太短", body="1. a\n2. b\n3. c\n")
    assert quality_gate(short_desc) is False

    too_few_steps = DistillProposal(
        name="y",
        description="这是一个足够长的技能描述, 超过十个字",
        body="1. 只有一步\n",
    )
    assert quality_gate(too_few_steps) is False


def test_below_min_tool_calls_no_proposal(tmp_path):
    """工具调用数低于 min_tool_calls 时不提议。"""
    mgr = _mgr(tmp_path)
    loop = DistillLoop(skill_manager=mgr, min_tool_calls=3)
    loop.start_task("简单任务")
    loop.record_tool_call("read_file", ok=True)
    loop.record_tool_call("edit_file", ok=True)
    assert loop.maybe_propose() is None


def test_confirm_writes_skill_to_disk(tmp_path):
    """用户确认后技能应写入用户级 skills/ 目录。"""
    mgr = _mgr(tmp_path)
    loop = DistillLoop(skill_manager=mgr)
    loop.start_task("系统地调试一个 Python 报错并修复")
    for tool in ["read_file", "edit_file", "run_tests"]:
        loop.record_tool_call(tool, ok=True)
    p = loop.maybe_propose()
    assert p is not None
    skill = loop.confirm(p)
    assert skill is not None
    # 磁盘上存在
    assert skill.path.exists()
    text = skill.path.read_text(encoding="utf-8")
    assert "source: auto-distill" in text
    assert count_steps(skill.body) >= 3


def test_next_similar_task_auto_activates(tmp_path):
    """确认写入后, 下次相似任务应因标签匹配被 activate_for_task 命中。"""
    mgr = _mgr(tmp_path)
    loop = DistillLoop(skill_manager=mgr)
    loop.start_task("用 pytest 跑测试并修复失败")
    for tool in ["read_file", "run_tests", "edit_file"]:
        loop.record_tool_call(tool, ok=True)
    p = loop.maybe_propose()
    assert p is not None
    loop.confirm(p)

    # 全新 manager (模拟下次会话), 同一 home 目录
    mgr2 = SkillManager(tmp_path)
    hits = mgr2.activate_for_task("跑 pytest 测试并修复失败")
    assert hits, "相似任务应自动命中蒸馏出的技能"
    assert any(s.source == "auto-distill" for s in hits)


def test_auto_propose_disabled(tmp_path):
    """auto_propose=false 时不自动提议。"""
    mgr = _mgr(tmp_path)
    loop = DistillLoop(skill_manager=mgr, auto_propose=False)
    loop.start_task("任务")
    for t in ["a", "b", "c"]:
        loop.record_tool_call(t, ok=True)
    assert loop.maybe_propose() is None


def test_manual_distill_trigger_builds_proposal(tmp_path):
    """/distill 手动触发: 即使 auto_propose 关闭, 也可显式构造提议。"""
    mgr = _mgr(tmp_path)
    loop = DistillLoop(skill_manager=mgr, auto_propose=False)
    loop.start_task("手动分析当前会话的可复用模式")
    for t in ["read_file", "grep", "edit_file", "run_tests"]:
        loop.record_tool_call(t, ok=True)
    p = loop.build_proposal()  # 手动触发不经过 auto 门控开关
    assert p is not None
    assert quality_gate(p)
