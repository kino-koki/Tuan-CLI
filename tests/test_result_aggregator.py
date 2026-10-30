"""ResultAggregator 专项测试 —— 多 Agent 结果聚合 (去重/冲突/质量/合并)。

覆盖 tuan_cli.core.result_aggregator:
- ResultEntry: content_hash / similarity (Jaccard) / 空内容边界
- ResultAggregator.add_result
- aggregate: 空输入 / 去重 / 冲突检测 / 质量评估 / 合并 / 角色排序
- _auto_quality_score 各特征分支
- AggregatedResult.to_dict
"""

from __future__ import annotations

import pytest

from tuan_cli.core.result_aggregator import (
    AggregatedResult,
    AggregationDecision,
    ResultAggregator,
    ResultEntry,
)


# ---------------------------------------------------------------- ResultEntry

def test_result_entry_hash_stable_and_property():
    e1 = ResultEntry(task_id="T1", agent_id="a", content="hello world")
    e2 = ResultEntry(task_id="T1", agent_id="a", content="hello world")
    assert e1.content_hash == e2.content_hash
    assert e1.content_hash == e1._content_hash
    assert len(e1.content_hash) == 32  # md5 hex


def test_result_entry_similarity_identical_is_one():
    e1 = ResultEntry(task_id="T1", agent_id="a", content="the quick brown fox")
    e2 = ResultEntry(task_id="T2", agent_id="b", content="the quick brown fox")
    assert e1.similarity(e2) == 1.0


def test_result_entry_similarity_partial_overlap():
    e1 = ResultEntry(task_id="T1", agent_id="a", content="a b c d")
    e2 = ResultEntry(task_id="T2", agent_id="b", content="a b x y")
    # 交集 {a,b}=2, 并集 {a,b,c,d,x,y}=6 => 0.333
    assert abs(e1.similarity(e2) - 2 / 6) < 1e-9


def test_result_entry_similarity_empty_is_zero():
    e1 = ResultEntry(task_id="T1", agent_id="a", content="")
    e2 = ResultEntry(task_id="T2", agent_id="b", content="some words")
    assert e1.similarity(e2) == 0.0
    assert e2.similarity(e1) == 0.0


# ---------------------------------------------------------------- add_result / aggregate

def test_aggregate_empty_returns_placeholder():
    agg = ResultAggregator()
    res = agg.aggregate()
    assert res.entries == []
    assert res.merged_content == "(无结果)"
    assert res.conflicts == []
    assert res.quality_summary == {}


def test_aggregate_single_entry():
    agg = ResultAggregator()
    agg.add_result("T1", "agent_a", "分析结果 A", role="architect", quality_score=0.8)
    res = agg.aggregate()
    assert len(res.entries) == 1
    assert res.entries[0].task_id == "T1"
    assert "分析结果 A" in res.merged_content
    assert res.quality_summary == {"T1": 0.8}


def test_add_result_builds_metadata_default():
    agg = ResultAggregator()
    agg.add_result("T1", "agent_a", "content")
    assert agg._entries[0].metadata == {}
    assert agg._entries[0].role == ""


def test_aggregate_dedup_removes_similar_keeps_better():
    agg = ResultAggregator(dedup_threshold=0.8)
    agg.add_result("T1", "a", "shared words here", quality_score=0.5)
    agg.add_result("T2", "b", "shared words here", quality_score=0.9)
    res = agg.aggregate()
    # 相似度 1.0 > 0.8, 保留质量更高的 T2
    assert len(res.entries) == 1
    assert res.entries[0].task_id == "T2"
    assert any(d.decision_type == "dedup" for d in res.decisions)


def test_aggregate_dedup_keeps_higher_quality_first_added():
    agg = ResultAggregator(dedup_threshold=0.8)
    agg.add_result("T1", "a", "same content", quality_score=0.9)
    agg.add_result("T2", "b", "same content", quality_score=0.5)
    res = agg.aggregate()
    assert len(res.entries) == 1
    assert res.entries[0].task_id == "T1"


def test_aggregate_no_dedup_when_below_threshold():
    agg = ResultAggregator(dedup_threshold=0.95)
    agg.add_result("T1", "a", "completely different text one")
    agg.add_result("T2", "b", "totally unrelated text two")
    res = agg.aggregate()
    assert len(res.entries) == 2


def test_dedup_single_entry_no_decision():
    agg = ResultAggregator()
    agg.add_result("T1", "a", "x")
    res = agg.aggregate()
    assert not any(d.decision_type == "dedup" for d in res.decisions)


# ---------------------------------------------------------------- conflict

def test_detect_conflict_positive_negative():
    agg = ResultAggregator()
    agg.add_result("T1", "a", "我们应该使用方案 X")
    agg.add_result("T2", "b", "我们不应该使用方案 X")
    res = agg.aggregate()
    assert len(res.conflicts) == 1
    assert res.conflicts[0]["task_a"] == "T1"
    assert res.conflicts[0]["task_b"] == "T2"
    assert res.conflicts[0]["type"] == "contradiction"
    assert any(d.decision_type == "conflict" for d in res.decisions)


def test_detect_conflict_reverse_direction():
    agg = ResultAggregator()
    agg.add_result("T1", "a", "不建议这样做")
    agg.add_result("T2", "b", "建议这样做")
    res = agg.aggregate()
    assert len(res.conflicts) == 1


def test_no_conflict_when_both_positive():
    agg = ResultAggregator()
    agg.add_result("T1", "a", "建议方案 A")
    agg.add_result("T2", "b", "建议方案 B")
    res = agg.aggregate()
    assert res.conflicts == []


def test_conflict_includes_warning_in_merged():
    agg = ResultAggregator()
    agg.add_result("T1", "a", "应该使用 X")
    agg.add_result("T2", "b", "不应该使用 X")
    res = agg.aggregate()
    assert "矛盾" in res.merged_content


# ---------------------------------------------------------------- quality

def test_auto_quality_empty_content_zero():
    agg = ResultAggregator()
    entry = ResultEntry(task_id="T1", agent_id="a", content="")
    assert agg._auto_quality_score(entry) == 0.0


def test_auto_quality_base_and_bonuses():
    agg = ResultAggregator()
    # 长内容 + 数字 + 中文 + 工具调用
    content = "结论 3.14 是正确的。" + "x" * 200
    entry = ResultEntry(task_id="T1", agent_id="a", content=content, tool_calls=2)
    score = agg._auto_quality_score(entry)
    # 0.5 基础 + 0.1 长度 + 0.05 数字 + 0.05 中文 + 0.1 工具 = 0.8
    assert score == pytest.approx(0.8)


def test_auto_quality_code_block_and_heading():
    agg = ResultAggregator()
    content = "# 标题\n```python\nx=1\n```\n" + "y" * 150
    entry = ResultEntry(task_id="T1", agent_id="a", content=content)
    score = agg._auto_quality_score(entry)
    assert score >= 0.5 + 0.1 + 0.1 + 0.05  # 基础+长度+代码块+标题


def test_auto_quality_caps_at_one():
    agg = ResultAggregator()
    # 很多加分项 + 工具调用
    content = "# 标题\n```\ncode\n```\n中文 3.14\n" + "z" * 200
    entry = ResultEntry(task_id="T1", agent_id="a", content=content, tool_calls=10)
    assert agg._auto_quality_score(entry) <= 1.0


def test_auto_quality_too_long_only_small_bonus():
    agg = ResultAggregator()
    content = "x" * 20000
    entry = ResultEntry(task_id="T1", agent_id="a", content=content)
    # 超长内容只 +0.05, 不是 +0.1
    assert agg._auto_quality_score(entry) == pytest.approx(0.55)


def test_assess_quality_uses_provided_score_when_nonzero():
    agg = ResultAggregator()
    agg.add_result("T1", "a", "some content", quality_score=0.7)
    res = agg.aggregate()
    assert res.quality_summary["T1"] == 0.7


def test_assess_quality_auto_scores_zero():
    agg = ResultAggregator()
    agg.add_result("T1", "a", "内容 3.14 中文说明", tool_calls=1)
    res = agg.aggregate()
    assert res.quality_summary["T1"] > 0.0


# ---------------------------------------------------------------- merge / role ordering

def test_merge_orders_by_predefined_roles():
    agg = ResultAggregator()
    agg.add_result("T1", "a", "实现内容", role="implementer", quality_score=0.9)
    agg.add_result("T2", "b", "架构内容", role="architect", quality_score=0.8)
    res = agg.aggregate()
    # architect 在 implementer 之前
    arch_idx = res.merged_content.index("架构内容")
    impl_idx = res.merged_content.index("实现内容")
    assert arch_idx < impl_idx


def test_merge_unknown_role_appended_last():
    agg = ResultAggregator()
    agg.add_result("T1", "a", "已知角色", role="tester")
    agg.add_result("T2", "b", "未知角色", role="weird_role")
    res = agg.aggregate()
    known_idx = res.merged_content.index("已知角色")
    unknown_idx = res.merged_content.index("未知角色")
    assert known_idx < unknown_idx


def test_merge_sorts_within_role_by_quality():
    agg = ResultAggregator()
    agg.add_result("T1", "a", "低质量", role="reviewer", quality_score=0.3)
    agg.add_result("T2", "b", "高质量", role="reviewer", quality_score=0.9)
    res = agg.aggregate()
    hi_idx = res.merged_content.index("高质量")
    lo_idx = res.merged_content.index("低质量")
    assert hi_idx < lo_idx


# ---------------------------------------------------------------- to_dict / stats

def test_aggregated_result_to_dict():
    res = AggregatedResult(
        entries=[ResultEntry(task_id="T1", agent_id="a", content="x")],
        merged_content="merged",
        conflicts=[],
        decisions=[AggregationDecision("dedup", "desc", ["T1"])],
        quality_summary={"T1": 0.5},
    )
    d = res.to_dict()
    assert d["entry_count"] == 1
    assert d["conflict_count"] == 0
    assert d["decision_count"] == 1
    assert d["merged_content_len"] == len("merged")
    assert d["quality_summary"] == {"T1": 0.5}


def test_stats_property():
    agg = ResultAggregator()
    assert agg.stats == {"total_entries": 0, "decisions": 0}
    agg.add_result("T1", "a", "x")
    agg.aggregate()
    assert agg.stats["total_entries"] == 1
    assert agg.stats["decisions"] >= 0
