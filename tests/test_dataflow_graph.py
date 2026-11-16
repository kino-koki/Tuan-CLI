# -*- coding: utf-8 -*-
"""阶段 1 —— ComfyUI 类数据流节点图执行引擎测试 (DataFlowGraph / GraphRunner)。"""

from __future__ import annotations

import pytest

from tuan_cli.web.dataflow_graph import (
    DataFlowGraph,
    GraphRunner,
    PortKind,
    builtin_exec_fn,
)


# ---------------------------------------------------------------------------
# 图构建与连线校验
# ---------------------------------------------------------------------------

class TestGraphBuild:
    def test_add_node_and_ports(self):
        g = DataFlowGraph()
        n = g.add_node("a", "text", params={"content": "hi"},
                       inputs=[("src", "text")], outputs=[("out", "text")])
        assert n.input_port("src") is not None
        assert n.input_port("src").kind == PortKind.INPUT
        assert n.output_port("out").ptype == "text"
        assert g.node_ids() == ["a"]

    def test_duplicate_node_rejected(self):
        g = DataFlowGraph()
        g.add_node("a", "text")
        with pytest.raises(ValueError):
            g.add_node("a", "text")

    def test_connect_unknown_node_rejected(self):
        g = DataFlowGraph()
        g.add_node("a", "text", outputs=[("out", "any")])
        with pytest.raises(ValueError):
            g.connect("a", "out", "ghost", "in")

    def test_self_loop_rejected(self):
        g = DataFlowGraph()
        g.add_node("a", "text", inputs=[("in", "any")], outputs=[("out", "any")])
        with pytest.raises(ValueError):
            g.connect("a", "out", "a", "in")

    def test_missing_port_rejected(self):
        g = DataFlowGraph()
        g.add_node("a", "text", outputs=[("out", "any")])
        g.add_node("b", "text", inputs=[("in", "any")])
        with pytest.raises(ValueError):
            g.connect("a", "no_such", "b", "in")

    def test_type_mismatch_rejected(self):
        g = DataFlowGraph()
        g.add_node("a", "text", outputs=[("out", "image")])
        g.add_node("b", "text", inputs=[("in", "video")])
        with pytest.raises(ValueError):
            g.connect("a", "out", "b", "in")

    def test_type_any_compatible(self):
        g = DataFlowGraph()
        g.add_node("a", "text", outputs=[("out", "any")])
        g.add_node("b", "text", inputs=[("in", "video")])
        g.connect("a", "out", "b", "in")  # any 兼容一切, 不抛

    def test_unknown_port_type_degrades_to_any(self):
        g = DataFlowGraph()
        n = g.add_node("a", "text", outputs=[("out", "weird")])
        assert n.output_port("out").ptype == "any"


# ---------------------------------------------------------------------------
# 拓扑排序与环检测
# ---------------------------------------------------------------------------

class TestTopology:
    def _linear(self):
        g = DataFlowGraph()
        g.add_node("a", "text", outputs=[("out", "any")])
        g.add_node("b", "text", inputs=[("in", "any")], outputs=[("out", "any")])
        g.add_node("c", "text", inputs=[("in", "any")])
        g.connect("a", "out", "b", "in")
        g.connect("b", "out", "c", "in")
        return g

    def test_linear_order(self):
        g = self._linear()
        assert g.topological_order() == ["a", "b", "c"]

    def test_cycle_detected(self):
        g = DataFlowGraph()
        g.add_node("a", "text", inputs=[("in", "any")], outputs=[("out", "any")])
        g.add_node("b", "text", inputs=[("in", "any")], outputs=[("out", "any")])
        g.connect("a", "out", "b", "in")
        g.connect("b", "out", "a", "in")  # 形成环
        assert g.has_cycle()
        with pytest.raises(ValueError):
            g.topological_order()

    def test_diamond_order(self):
        g = DataFlowGraph()
        g.add_node("src", "text", outputs=[("out", "any")])
        g.add_node("l", "text", inputs=[("in", "any")], outputs=[("out", "any")])
        g.add_node("r", "text", inputs=[("in", "any")], outputs=[("out", "any")])
        g.add_node("sink", "text", inputs=[("in", "any")])
        g.connect("src", "out", "l", "in")
        g.connect("src", "out", "r", "in")
        g.connect("l", "out", "sink", "in")
        g.connect("r", "out", "sink", "in")
        order = g.topological_order()
        assert order[0] == "src"
        assert order[-1] == "sink"
        assert set(order[1:3]) == {"l", "r"}


# ---------------------------------------------------------------------------
# 执行: 数据流注入 / 缓存 / 增量重跑 / 失败传播
# ---------------------------------------------------------------------------

class TestRunner:
    def test_executes_linear_dataflow(self):
        g = DataFlowGraph()
        g.add_node("a", "text", params={"content": "Hello"}, outputs=[("out", "any")])
        g.add_node("b", "text", params={"content": "!"}, outputs=[("out", "any")])
        g.add_node("cat", "concat", params={"separator": ""},
                   inputs=[("x", "any"), ("y", "any")])
        g.connect("a", "out", "cat", "x")
        g.connect("b", "out", "cat", "y")
        runner = GraphRunner(g, builtin_exec_fn)
        results = runner.run()
        assert results["cat"] == "Hello!"

    def test_upstream_value_injected_to_input(self):
        """验证下游输入端口收到上游输出值。"""
        seen = {}

        def exec_fn(node, inputs, ctx):
            if node.node_id == "src":
                return "val"  # src 输出 "val"
            seen[node.node_id] = dict(inputs)
            return "ok"

        g = DataFlowGraph()
        g.add_node("src", "text", params={"content": "val"}, outputs=[("out", "any")])
        g.add_node("dst", "text", inputs=[("in", "any")])
        g.connect("src", "out", "dst", "in")
        GraphRunner(g, exec_fn).run()
        assert seen["dst"]["in"] == "val"

    def test_cache_hit_on_rerun_unchanged(self):
        calls = []

        def exec_fn(node, inputs, ctx):
            calls.append(node.node_id)
            return node.node_id + "-result"

        g = DataFlowGraph()
        g.add_node("a", "text", outputs=[("out", "any")])
        g.add_node("b", "text", inputs=[("in", "any")])
        g.connect("a", "out", "b", "in")
        cache = {}
        GraphRunner(g, exec_fn, cache=cache).run()
        assert len(calls) == 2
        # 第二次运行, 全部命中缓存, exec_fn 不再被调用
        GraphRunner(g, exec_fn, cache=cache).run()
        assert len(calls) == 2  # 未新增调用

    def test_force_reruns_all(self):
        calls = []

        def exec_fn(node, inputs, ctx):
            calls.append(node.node_id)
            return "r"

        g = DataFlowGraph()
        g.add_node("a", "text", outputs=[("out", "any")])
        cache = {}
        GraphRunner(g, exec_fn, cache=cache).run()
        GraphRunner(g, exec_fn, cache=cache, force=True).run()
        assert len(calls) == 2

    def test_upstream_change_invalidates_downstream_only(self):
        """改上游 → 下游重跑; 无关分支命中缓存。"""
        calls = []

        def exec_fn(node, inputs, ctx):
            calls.append(node.node_id)
            return f"{node.node_id}:{node.params.get('v', '')}"

        g = DataFlowGraph()
        g.add_node("src", "text", params={"v": 1}, outputs=[("out", "any")])
        g.add_node("left", "text", inputs=[("in", "any")])
        g.add_node("right", "text", params={"v": 99}, outputs=[("out", "any")])
        g.add_node("sink", "text", inputs=[("in", "any")])
        g.connect("src", "out", "left", "in")
        g.connect("right", "out", "sink", "in")
        cache = {}
        GraphRunner(g, exec_fn, cache=cache).run()
        calls.clear()
        # 修改 src 参数 → src + left 重跑; right/sink 命中缓存
        g.nodes["src"].params["v"] = 2
        GraphRunner(g, exec_fn, cache=cache).run()
        assert set(calls) == {"src", "left"}

    def test_upstream_failure_skips_downstream(self):
        """上游失败 → 下游 SKIPPED, 不执行。"""
        ran = []

        def exec_fn(node, inputs, ctx):
            if node.node_id == "boom":
                raise RuntimeError("fail")
            ran.append(node.node_id)
            return "ok"

        g = DataFlowGraph()
        g.add_node("boom", "text", outputs=[("out", "any")])
        g.add_node("leaf", "text", inputs=[("in", "any")])
        g.connect("boom", "out", "leaf", "in")
        runner = GraphRunner(g, exec_fn)
        runner.run()
        assert runner.graph.nodes["boom"].status == "failed"
        assert runner.graph.nodes["leaf"].status == "skipped"
        assert "leaf" not in ran

    def test_cycle_rejected_before_exec(self):
        """含环图在 run() 前抛异常, 绝不执行。"""
        ran = []

        def exec_fn(node, inputs, ctx):
            ran.append(node.node_id)
            return "ok"

        g = DataFlowGraph()
        g.add_node("a", "text", inputs=[("in", "any")], outputs=[("out", "any")])
        g.add_node("b", "text", inputs=[("in", "any")], outputs=[("out", "any")])
        g.connect("a", "out", "b", "in")
        g.connect("b", "out", "a", "in")
        with pytest.raises(ValueError):
            GraphRunner(g, exec_fn).run()
        assert ran == []

    def test_unknown_node_type_rejected_by_exec(self):
        """未知节点类型 → 节点标记 failed (不传播异常, fail-safe)。"""
        g = DataFlowGraph()
        g.add_node("x", "unknown_type")
        runner = GraphRunner(g, builtin_exec_fn)
        runner.run()
        assert runner.graph.nodes["x"].status == "failed"
        assert "未知节点类型" in (runner.graph.nodes["x"].error or "")

    def test_logs_captured(self):
        def exec_fn(node, inputs, ctx):
            return "v"

        g = DataFlowGraph()
        g.add_node("a", "text", outputs=[("out", "any")])
        runner = GraphRunner(g, exec_fn)
        runner.run()
        logs = runner.logs
        assert len(logs) == 1
        assert logs[0].node_id == "a"
        assert logs[0].status == "completed"

    def test_status_snapshot(self):
        def exec_fn(node, inputs, ctx):
            return "v"

        g = DataFlowGraph()
        g.add_node("a", "text", outputs=[("out", "any")])
        runner = GraphRunner(g, exec_fn)
        runner.run()
        snap = runner.status()
        assert snap["nodes"]["a"]["status"] == "completed"
        assert len(snap["logs"]) == 1


# ---------------------------------------------------------------------------
# 序列化 / 反序列化
# ---------------------------------------------------------------------------

class TestSerialization:
    def test_roundtrip(self):
        g = DataFlowGraph()
        g.add_node("a", "text", params={"content": "hi"},
                   outputs=[("out", "text")])
        g.add_node("b", "text", params={"content": "!"},
                   inputs=[("in", "text")])
        g.connect("a", "out", "b", "in")
        runner = GraphRunner(g, builtin_exec_fn)
        data = runner.to_dict()
        assert len(data["nodes"]) == 2
        assert len(data["edges"]) == 1

        runner2 = GraphRunner.from_dict(data, builtin_exec_fn)
        results = runner2.run()
        assert results["a"] == "hi"
