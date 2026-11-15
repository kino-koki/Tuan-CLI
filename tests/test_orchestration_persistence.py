"""阶段 B 测试: 持久化多 Agent 编排与故障恢复 (orchestrator)。"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tuan_cli.core.orchestrator import (  # noqa: E402
    GroupStateStore,
    NodeState,
    OrchestrationNode,
    Orchestrator,
)


# ------------------------------------------------------------- 基础 DAG
class TestDagValidation:
    def test_valid_dag_executes_in_topological_order(self, tmp_path):
        calls = []
        def exec(node, bb):
            calls.append(node.node_id)
            return f"result:{node.node_id}"
        orch = Orchestrator(exec, persist_dir=str(tmp_path))
        orch.plan("g", [("a", []), ("b", ["a"]), ("c", ["a", "b"])])
        res = orch.execute("g")
        assert res["done"] == 3
        assert calls.index("a") < calls.index("b") < calls.index("c")
        assert res["failed"] == 0

    def test_duplicate_node_rejected(self, tmp_path):
        orch = Orchestrator(lambda n, bb: None, persist_dir=str(tmp_path))
        with pytest.raises(ValueError):
            orch.plan("g", [("a", []), ("a", [])])

    def test_unknown_dep_rejected(self, tmp_path):
        orch = Orchestrator(lambda n, bb: None, persist_dir=str(tmp_path))
        with pytest.raises(ValueError):
            orch.plan("g", [("a", []), ("b", ["missing"])])

    def test_cycle_rejected(self, tmp_path):
        orch = Orchestrator(lambda n, bb: None, persist_dir=str(tmp_path))
        with pytest.raises(ValueError):
            orch.plan("g", [("a", ["b"]), ("b", ["a"])])


# ------------------------------------------------------------- 断点恢复
class TestResume:
    def test_resume_reuses_done_and_runs_pending(self, tmp_path):
        done = set()
        def exec(node, bb):
            done.add(node.node_id)
            return node.node_id
        orch = Orchestrator(exec, persist_dir=str(tmp_path))
        orch.plan("g", [("a", []), ("b", ["a"])])
        # 手动把 a 标记 done (模拟上次会话已完成)
        orch._nodes["a"].state = NodeState.DONE
        orch._nodes["a"].result = "a"
        orch._blackboard["a"] = "a"
        orch._persist()
        # 模拟崩溃后新实例恢复
        orch2 = Orchestrator(exec, persist_dir=str(tmp_path))
        res = orch2.resume("g")
        assert res["done"] == 2
        assert "a" not in done   # a 复用结果, 不重跑
        assert "b" in done       # b 补跑

    def test_resume_no_state_initializes_empty(self, tmp_path):
        orch = Orchestrator(lambda n, bb: None, persist_dir=str(tmp_path))
        res = orch.resume("g")
        assert res["done"] == 0


# ------------------------------------------------------------- 失败处理
class TestFailure:
    def test_node_failure_propagates_to_downstream(self, tmp_path):
        """b 失败 -> 上游 a 保持 DONE, 下游 c (依赖 b) 被回滚。"""
        def exec(node, bb):
            if node.node_id == "a":
                return "a-ok"
            raise RuntimeError("boom")   # b 失败
        orch = Orchestrator(exec, persist_dir=str(tmp_path), backoff_base=0.0)
        orch.plan("g", [("a", []), ("b", ["a"]), ("c", ["b"])])
        res = orch.execute("g")
        assert orch._nodes["a"].state == NodeState.DONE
        assert orch._nodes["b"].state == NodeState.FAILED
        # c 依赖 b, 因依赖不满足被回滚
        assert orch._nodes["c"].state == NodeState.ROLLED_BACK
        assert res["rolled_back"] >= 1

    def test_retry_with_backoff_then_success(self, tmp_path):
        attempts = {"n": 0}
        def exec(node, bb):
            attempts["n"] += 1
            if attempts["n"] < 2:
                raise RuntimeError("transient")
            return "ok"
        orch = Orchestrator(exec, persist_dir=str(tmp_path), backoff_base=0.0)
        orch.plan("g", [("a", [])])
        res = orch.execute("g")
        assert res["done"] == 1
        assert attempts["n"] == 2

    def test_exhausted_retries_marks_failed(self, tmp_path):
        def exec(node, bb):
            raise RuntimeError("always")
        orch = Orchestrator(exec, persist_dir=str(tmp_path), backoff_base=0.0)
        orch.plan("g", [("a", [])])
        res = orch.execute("g")
        assert orch._nodes["a"].state == NodeState.FAILED
        assert res["failed"] >= 1


# ------------------------------------------------------------- 持久化
class TestPersistence:
    def test_state_roundtrip(self, tmp_path):
        def exec(node, bb):
            return node.node_id
        orch = Orchestrator(exec, persist_dir=str(tmp_path))
        orch.plan("g", [("a", [])])
        orch.execute("g")
        # 新实例读取
        store = GroupStateStore(str(tmp_path))
        data = store.load("g")
        assert data is not None
        assert "a" in data["nodes"]
        assert data["nodes"]["a"]["state"] == "done"

    def test_atomic_write_no_partial(self, tmp_path):
        store = GroupStateStore(str(tmp_path))
        store.save("g", {"group_id": "g", "nodes": {"a": {"state": "done"}}})
        # 无残留临时文件
        files = os.listdir(str(tmp_path))
        assert all(not f.endswith(".tmp") for f in files)
        assert store.exists("g")
        assert store.list_groups() == ["g"]

    def test_list_groups_empty(self, tmp_path):
        store = GroupStateStore(str(tmp_path))
        assert store.list_groups() == []
