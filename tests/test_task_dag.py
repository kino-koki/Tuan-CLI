"""TaskDAG 专项测试 —— 任务依赖图 + 智能调度器。

覆盖 tuan_cli.core.task_dag:
- TaskStatus 枚举值
- DAGNode: elapsed / can_retry / to_dict
- TaskDAG: add_node / add_dependency / add_dependencies / get_node
- mark_running / mark_completed / mark_failed (含重试与下游跳过)
- cancel
- get_ready_tasks (依赖满足/失败跳过/优先级排序)
- get_wave (并发度限制)
- get_status_summary
- critical_path (最长依赖链)
- detect_cycles / break_cycles
- from_plan (含循环打破)
"""

from __future__ import annotations

import time

import pytest

from tuan_cli.core.task_dag import DAGNode, TaskDAG, TaskStatus


# ---------------------------------------------------------------- TaskStatus

def test_task_status_values():
    assert TaskStatus.PENDING.value == "pending"
    assert TaskStatus.READY.value == "ready"
    assert TaskStatus.RUNNING.value == "running"
    assert TaskStatus.COMPLETED.value == "completed"
    assert TaskStatus.FAILED.value == "failed"
    assert TaskStatus.SKIPPED.value == "skipped"
    assert TaskStatus.CANCELLED.value == "cancelled"


# ---------------------------------------------------------------- DAGNode

def test_node_elapsed_zero_when_not_started():
    n = DAGNode(task_id="T1", title="t", prompt="p")
    assert n.elapsed == 0.0


def test_node_elapsed_computed():
    n = DAGNode(task_id="T1", title="t", prompt="p")
    n.started_at = time.time() - 5
    n.completed_at = time.time() - 2
    assert 2.9 < n.elapsed < 3.1


def test_node_elapsed_uses_now_when_running():
    n = DAGNode(task_id="T1", title="t", prompt="p")
    n.started_at = time.time() - 3
    assert 2.9 < n.elapsed < 3.1


def test_node_can_retry():
    n = DAGNode(task_id="T1", title="t", prompt="p", max_retries=2)
    assert n.can_retry  # retries=0 < 2
    n.retries = 2
    assert not n.can_retry


def test_node_to_dict():
    n = DAGNode(task_id="T1", title="t", prompt="p", role="architect")
    n.dependencies = {"D1", "D2"}
    n.assigned_to = "agent-a"
    d = n.to_dict()
    assert d["task_id"] == "T1"
    assert d["status"] == "pending"
    assert d["role"] == "architect"
    assert set(d["dependencies"]) == {"D1", "D2"}
    assert d["assigned_to"] == "agent-a"
    assert d["elapsed"] == 0.0


# ---------------------------------------------------------------- add / get

def test_add_node_returns_node():
    dag = TaskDAG()
    n = dag.add_node("T1", "分析", "prompt", role="architect", priority=3)
    assert n.task_id == "T1"
    assert n.role == "architect"
    assert n.priority == 3
    assert dag.get_node("T1") is n
    assert dag.get_node("nope") is None


def test_add_dependency_only_known_task():
    dag = TaskDAG()
    dag.add_node("T1", "a", "p")
    dag.add_node("T2", "b", "p")
    dag.add_dependency("T2", "T1")
    assert dag.get_node("T2").dependencies == {"T1"}
    # 未知 task_id 静默忽略
    dag.add_dependency("T3", "T1")
    assert dag.get_node("T3") is None


def test_add_dependencies_multiple():
    dag = TaskDAG()
    dag.add_node("T3", "c", "p")
    dag.add_dependencies("T3", ["T1", "T2"])
    assert dag.get_node("T3").dependencies == {"T1", "T2"}


# ---------------------------------------------------------------- 状态管理

def test_mark_running():
    dag = TaskDAG()
    dag.add_node("T1", "a", "p")
    dag.mark_running("T1", assigned_to="agent-x")
    n = dag.get_node("T1")
    assert n.status == TaskStatus.RUNNING
    assert n.assigned_to == "agent-x"
    assert n.started_at is not None


def test_mark_completed():
    dag = TaskDAG()
    dag.add_node("T1", "a", "p")
    dag.mark_completed("T1", "done")
    n = dag.get_node("T1")
    assert n.status == TaskStatus.COMPLETED
    assert n.result == "done"
    assert n.completed_at is not None


def test_mark_failed_retry_resets_pending():
    dag = TaskDAG()
    dag.add_node("T1", "a", "p", max_retries=2)
    dag.mark_failed("T1", "boom")
    n = dag.get_node("T1")
    assert n.status == TaskStatus.PENDING
    assert n.retries == 1
    assert n.error == "boom"


def test_mark_failed_exhausted_sets_failed_and_skips_downstream():
    dag = TaskDAG()
    dag.add_node("T1", "a", "p", max_retries=0)
    dag.add_node("T2", "b", "p")
    dag.add_node("T3", "c", "p")
    dag.add_dependency("T2", "T1")
    dag.add_dependency("T3", "T2")
    dag.mark_failed("T1", "fatal")
    assert dag.get_node("T1").status == TaskStatus.FAILED
    assert dag.get_node("T2").status == TaskStatus.SKIPPED
    assert dag.get_node("T3").status == TaskStatus.SKIPPED


def test_mark_failed_unknown_task_noop():
    dag = TaskDAG()
    dag.mark_failed("T1", "x")  # 不抛
    dag.mark_running("T1")
    dag.mark_completed("T1", "x")


def test_cancel_pending_and_ready():
    dag = TaskDAG()
    dag.add_node("T1", "a", "p")
    dag.add_node("T2", "b", "p")
    dag.add_dependency("T2", "T1")
    dag.mark_running("T1")
    dag.mark_completed("T1", "ok")
    # T2 无依赖, get_ready 直接置为 READY
    dag.get_ready_tasks()
    assert dag.get_node("T2").status == TaskStatus.READY
    dag.cancel("T2")
    assert dag.get_node("T2").status == TaskStatus.CANCELLED
    # running 状态不可取消
    dag.mark_running("T1")
    dag.cancel("T1")
    assert dag.get_node("T1").status == TaskStatus.RUNNING


# ---------------------------------------------------------------- ready / wave

def test_get_ready_no_deps():
    dag = TaskDAG()
    dag.add_node("T1", "a", "p")
    ready = dag.get_ready_tasks()
    assert [n.task_id for n in ready] == ["T1"]


def test_get_ready_waits_for_deps():
    dag = TaskDAG()
    dag.add_node("T1", "a", "p")
    dag.add_node("T2", "b", "p")
    dag.add_dependency("T2", "T1")
    # T1 本身 pending, 会被 get_ready 置为 READY; 但 T2 依赖未满足仍不 ready
    ready = dag.get_ready_tasks()
    assert [n.task_id for n in ready] == ["T1"]
    dag.mark_completed("T1", "ok")
    ready = dag.get_ready_tasks()
    assert [n.task_id for n in ready] == ["T2"]


def test_get_ready_skips_if_dep_failed():
    dag = TaskDAG()
    dag.add_node("T1", "a", "p", max_retries=0)
    dag.add_node("T2", "b", "p")
    dag.add_dependency("T2", "T1")
    dag.mark_failed("T1", "x")
    # T2 依赖已 FAILED -> 自身 SKIPPED, 不出现在 ready
    assert dag.get_ready_tasks() == []
    assert dag.get_node("T2").status == TaskStatus.SKIPPED


def test_get_ready_orders_by_priority_desc():
    dag = TaskDAG()
    dag.add_node("low", "a", "p", priority=1)
    dag.add_node("high", "b", "p", priority=10)
    dag.add_node("mid", "c", "p", priority=5)
    ready = dag.get_ready_tasks()
    assert [n.task_id for n in ready] == ["high", "mid", "low"]


def test_get_wave_respects_max_concurrent():
    dag = TaskDAG()
    for i in range(6):
        dag.add_node(f"T{i}", f"t{i}", "p")
    wave = dag.get_wave(max_concurrent=3)
    assert len(wave) == 3
    # 剩余仍为 PENDING (未取出的不自动转 READY, 但下次调用会把它们置 READY)
    dag2 = TaskDAG()
    for i in range(6):
        dag2.add_node(f"T{i}", f"t{i}", "p")
    wave2 = dag2.get_wave(max_concurrent=100)
    assert len(wave2) == 6


def test_get_all_nodes():
    dag = TaskDAG()
    dag.add_node("T1", "a", "p")
    dag.add_node("T2", "b", "p")
    assert len(dag.get_all_nodes()) == 2


def test_get_status_summary():
    dag = TaskDAG()
    dag.add_node("T1", "a", "p")
    dag.add_node("T2", "b", "p")
    dag.mark_completed("T1", "ok")
    s = dag.get_status_summary()
    assert s["total"] == 2
    assert s["by_status"]["completed"] == 1
    assert s["by_status"]["pending"] == 1
    assert s["total_elapsed"] >= 0


# ---------------------------------------------------------------- critical_path

def test_critical_path_linear_chain():
    dag = TaskDAG()
    dag.add_node("A", "a", "p")
    dag.add_node("B", "b", "p")
    dag.add_node("C", "c", "p")
    dag.add_dependency("B", "A")
    dag.add_dependency("C", "B")
    assert dag.critical_path() == ["A", "B", "C"]


def test_critical_path_chooses_longest_branch():
    dag = TaskDAG()
    dag.add_node("A", "a", "p")
    dag.add_node("B1", "b1", "p")
    dag.add_node("B2", "b2", "p")
    dag.add_node("C1", "c1", "p")
    dag.add_node("C2", "c2", "p")
    dag.add_dependency("B1", "A")
    dag.add_dependency("B2", "A")
    dag.add_dependency("C1", "B1")
    dag.add_dependency("C2", "B2")
    # 让 A->B1->C1->D1 成为最长链 (长度 4)
    dag.add_node("D1", "d1", "p")
    dag.add_dependency("D1", "C1")
    path = dag.critical_path()
    assert path[0] == "A"
    assert path[-1] == "D1"
    assert path == ["A", "B1", "C1", "D1"]


def test_critical_path_empty():
    dag = TaskDAG()
    assert dag.critical_path() == []


# ---------------------------------------------------------------- cycles

def test_detect_cycles_clean_dag_returns_empty():
    dag = TaskDAG()
    dag.add_node("A", "a", "p")
    dag.add_node("B", "b", "p")
    dag.add_dependency("B", "A")
    assert dag.detect_cycles() == []


def test_detect_cycle_two_nodes():
    dag = TaskDAG()
    dag.add_node("A", "a", "p")
    dag.add_node("B", "b", "p")
    dag.add_dependency("B", "A")
    dag.add_dependency("A", "B")
    cycles = dag.detect_cycles()
    assert len(cycles) == 1
    assert set(cycles[0]) == {"A", "B"}


def test_break_cycles_removes_edge():
    dag = TaskDAG()
    dag.add_node("A", "a", "p")
    dag.add_node("B", "b", "p")
    dag.add_dependency("B", "A")
    dag.add_dependency("A", "B")
    removed = dag.break_cycles()
    assert removed >= 1
    assert dag.detect_cycles() == []


def test_break_cycles_no_cycle_returns_zero():
    dag = TaskDAG()
    dag.add_node("A", "a", "p")
    assert dag.break_cycles() == 0


# ---------------------------------------------------------------- from_plan

def test_from_plan_basic():
    dag = TaskDAG.from_plan([
        {"id": "T1", "title": "a", "prompt": "p", "role": "architect"},
        {"id": "T2", "title": "b", "prompt": "p", "depends_on": "T1"},
    ])
    assert dag.get_node("T1").role == "architect"
    assert dag.get_node("T2").dependencies == {"T1"}


def test_from_plan_semicolon_and_default_role():
    dag = TaskDAG.from_plan([
        {"id": "T1", "title": "a", "prompt": "p"},
        {"id": "T2", "title": "b", "prompt": "p", "depends_on": "T1;T3"},
        {"id": "T3", "title": "c", "prompt": "p"},
    ], default_role="tester")
    assert dag.get_node("T2").dependencies == {"T1", "T3"}
    assert dag.get_node("T1").role == "tester"


def test_from_plan_breaks_cycle():
    dag = TaskDAG.from_plan([
        {"id": "A", "title": "a", "prompt": "p", "depends_on": "B"},
        {"id": "B", "title": "b", "prompt": "p", "depends_on": "A"},
    ])
    assert dag.detect_cycles() == []
