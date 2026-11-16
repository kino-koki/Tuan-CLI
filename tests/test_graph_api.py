# -*- coding: utf-8 -*-
"""阶段 7 —— /web 工作台接线 DataFlowGraph 测试 (graph_api: 存储 / 套件执行器 / 执行封装)。"""

from __future__ import annotations

import json

from tuan_cli.web.graph_api import (
    GraphStore,
    _media_rel,
    build_runner,
    run_graph,
    suite_exec_fn,
)


# ---------------------------------------------------------------------------
# 图持久化 (GraphStore)
# ---------------------------------------------------------------------------

class TestGraphStore:
    def test_save_load_roundtrip(self, tmp_path):
        st = GraphStore(str(tmp_path))
        rec = st.save("mygraph", {"name": "My Graph", "data": {
            "nodes": [{"node_id": "a", "ntype": "text", "params": {}}],
            "edges": [],
        }})
        assert rec["id"] == "mygraph"
        assert rec["name"] == "My Graph"
        loaded = st.load("mygraph")
        assert loaded is not None
        assert loaded["data"]["nodes"][0]["node_id"] == "a"

    def test_list_sorted_by_updated(self, tmp_path):
        st = GraphStore(str(tmp_path))
        st.save("older", {"name": "Older"})
        st.save("newer", {"name": "Newer"})
        names = [g["name"] for g in st.list_graphs()]
        assert names[0] == "Newer"  # 后保存的最新在前

    def test_unsafe_id_rejected(self, tmp_path):
        import pytest

        st = GraphStore(str(tmp_path))
        with pytest.raises(ValueError):
            st.save("../../evil", {"name": "x"})
        with pytest.raises(ValueError):
            st.save("a/b", {"name": "x"})

    def test_missing_load_returns_none(self, tmp_path):
        st = GraphStore(str(tmp_path))
        assert st.load("ghost") is None

    def test_media_rel_maps_under_media(self, tmp_path):
        """_media_rel 把绝对输出路径映射为相对 workspace/media/ 的子路径。"""
        media = tmp_path / "media"
        media.mkdir(parents=True, exist_ok=True)
        out = media / "graph_1.mp4"
        assert _media_rel(str(tmp_path), str(out)) == "graph_1.mp4"

    def test_media_rel_outside_falls_back_to_name(self, tmp_path):
        """_media_rel 对 media/ 之外的路径退化为文件名 (不抛错)。"""
        outside = tmp_path / "elsewhere" / "x.mp4"
        assert _media_rel(str(tmp_path), str(outside)) == "x.mp4"


# ---------------------------------------------------------------------------
# 套件执行器 (suite_exec_fn) 与执行封装
# ---------------------------------------------------------------------------

def _mk_graph(nodes, edges):
    return {"nodes": nodes, "edges": edges}


def test_run_graph_builtin_chain():
    """text → identity → concat (separator 分隔) 最小链路执行成功。"""
    data = _mk_graph(
        [
            {"node_id": "a", "ntype": "text", "params": {"content": "hi"},
             "inputs": [], "outputs": [{"name": "out", "ptype": "text"}]},
            {"node_id": "b", "ntype": "text", "params": {"content": "you"},
             "inputs": [], "outputs": [{"name": "out", "ptype": "text"}]},
            {"node_id": "c", "ntype": "concat", "params": {},
             "inputs": [{"name": "x", "ptype": "any"}, {"name": "y", "ptype": "any"}],
             "outputs": [{"name": "out", "ptype": "text"}]},
        ],
        [
            {"src_node": "a", "src_port": "out", "dst_node": "c", "dst_port": "x"},
            {"src_node": "b", "src_port": "out", "dst_node": "c", "dst_port": "y"},
        ],
    )
    out = run_graph(data)
    assert out["results"]["c"] == "hiyou"
    assert out["results"]["a"] == "hi"
    # 状态快照: 全部 completed
    assert all(lg["status"] == "completed" for lg in out["logs"] if lg["node_id"] == "c")


def test_run_graph_fail_closed_unknown_node():
    """未知节点类型 → fail-closed 抛错 (不静默跳过)。"""
    data = _mk_graph(
        [{"node_id": "x", "ntype": "ghost", "params": {},
          "inputs": [], "outputs": []}],
        [],
    )
    try:
        run_graph(data)
        assert False, "应抛 ValueError"
    except ValueError as exc:
        assert "未知节点类型" in str(exc)


def test_run_graph_cycle_rejected():
    """含环 → fail-closed 抛错。"""
    data = _mk_graph(
        [
            {"node_id": "a", "ntype": "text", "params": {"content": "x"},
             "inputs": [{"name": "in", "ptype": "any"}], "outputs": [{"name": "out", "ptype": "any"}]},
            {"node_id": "b", "ntype": "text", "params": {"content": "y"},
             "inputs": [{"name": "in", "ptype": "any"}], "outputs": [{"name": "out", "ptype": "any"}]},
        ],
        [
            {"src_node": "a", "src_port": "out", "dst_node": "b", "dst_port": "in"},
            {"src_node": "b", "src_port": "out", "dst_node": "a", "dst_port": "in"},
        ],
    )
    try:
        run_graph(data)
        assert False, "应抛环异常"
    except ValueError as exc:
        assert "环" in str(exc) or "cycle" in str(exc).lower()


def test_suite_execfn_llm_call_missing_prompt():
    """llm_call 节点缺 prompt → fail-closed。"""
    from tuan_cli.web.dataflow_graph import FlowNode

    node = FlowNode("n", "llm_call", params={})
    try:
        suite_exec_fn(node, {}, {})
        assert False, "应抛 ValueError"
    except ValueError as exc:
        assert "prompt" in str(exc)


def test_suite_execfn_codeanim_bad_project():
    """codeanim 节点 project_json 非法 → fail-closed。"""
    from tuan_cli.web.dataflow_graph import FlowNode

    node = FlowNode("n", "codeanim", params={"project_json": "not-a-dict"})
    try:
        suite_exec_fn(node, {}, {})
        assert False, "应抛 ValueError"
    except ValueError as exc:
        assert "project_json" in str(exc)


def test_llm_call_outputs_project_json_field(monkeypatch):
    """llm_call 输出含 project_json 结构化字段 (供下游 codeanim 取)。"""
    from tuan_cli.web.dataflow_graph import FlowNode

    class _FakeGW:
        def generate(self, *a, **kw):
            return {"text": "ok", "json": {"width": 640}, "provider_id": "x", "model": "m"}

    import tuan_cli.runtime.gateway as rt_gw
    monkeypatch.setattr(rt_gw, "ModelGateway", lambda: _FakeGW())
    out = suite_exec_fn(
        FlowNode("n", "llm_call", params={"prompt": "hi", "intent": "video_gen"}),
        {}, {},
    )
    assert out["project_json"] == {"width": 640}
    assert out["text"] == "ok"


def test_llm_call_video_gen_injects_schema(monkeypatch):
    """intent='video_gen' 且未显式给 json_schema → 自动注入 VIDEO_GEN_SCHEMA。"""
    from tuan_cli.web.dataflow_graph import FlowNode
    from tuan_cli.web import graph_api as ga

    seen = {}

    class _FakeGW:
        def generate(self, prompt, **kw):
            seen["json_schema"] = kw.get("json_schema")
            seen["intent"] = kw.get("intent")
            return {"text": "ok", "json": None, "provider_id": "x", "model": "m"}

    import tuan_cli.runtime.gateway as rt_gw
    monkeypatch.setattr(rt_gw, "ModelGateway", lambda: _FakeGW())
    suite_exec_fn(
        FlowNode("n", "llm_call", params={"prompt": "hi", "intent": "video_gen"}),
        {}, {},
    )
    assert seen["intent"] == "video_gen"
    assert seen["json_schema"] == ga.VIDEO_GEN_SCHEMA


def test_llm_call_explicit_schema_wins(monkeypatch):
    """显式给 json_schema → 不覆盖 (video_gen 意图不强行注入)。"""
    from tuan_cli.web.dataflow_graph import FlowNode

    seen = {}

    class _FakeGW:
        def generate(self, prompt, **kw):
            seen["json_schema"] = kw.get("json_schema")
            return {"text": "ok", "json": None, "provider_id": "x", "model": "m"}

    import tuan_cli.runtime.gateway as rt_gw
    monkeypatch.setattr(rt_gw, "ModelGateway", lambda: _FakeGW())
    custom = {"type": "object", "properties": {"x": {"type": "string"}}}
    suite_exec_fn(
        FlowNode("n", "llm_call",
                 params={"prompt": "hi", "intent": "video_gen", "json_schema": custom}),
        {}, {},
    )
    assert seen["json_schema"] == custom


def test_codeanim_consumes_upstream_llm_project_json(monkeypatch, tmp_path):
    """codeanim 从上游 llm_call 的 project_json 输入取结构化 project, 渲染单帧。"""
    from tuan_cli.web.dataflow_graph import FlowNode

    project = {"width": 64, "height": 36, "fps": 30, "duration": 2,
               "nodes": [{"type": "bg", "start": 0, "end": 2,
                          "props": {"type": "solid", "color": [255, 0, 0]}}]}
    # 模拟上游 llm_call 输出 dict (含 project_json 键)
    inputs = {"project_json": {"text": "ok", "json": project, "project_json": project}}
    node = FlowNode("n", "codeanim",
                    params={"mode": "frame", "t": 0, "project_json": None})
    ctx = {"graph": type("G", (), {"workspace": str(tmp_path)})()}
    result = suite_exec_fn(node, inputs, ctx)
    assert result["width"] == 64
    assert result["height"] == 36
    assert result["png_data_url"].startswith("data:image/png;base64,")


def test_codeanim_upstream_priority_over_default(monkeypatch, tmp_path):
    """阶段 16: 上游已连边 (project_json 键存在) 时优先用上游, 不静默回退节点默认。"""
    from tuan_cli.web.dataflow_graph import FlowNode

    project = {"width": 48, "height": 32, "fps": 30, "duration": 2,
               "nodes": [{"type": "bg", "start": 0, "end": 2,
                          "props": {"type": "solid", "color": [0, 0, 255]}}]}
    default_proj = {"width": 999, "height": 999, "fps": 30, "duration": 2,
                    "nodes": [{"type": "bg", "start": 0, "end": 2,
                               "props": {"type": "solid"}}]}
    # 节点自带默认 project_json, 但上游连了边且给了可用项目 → 用上游 (48x32)
    node = FlowNode("n", "codeanim",
                    params={"mode": "frame", "t": 0, "project_json": default_proj})
    ctx = {"graph": type("G", (), {"workspace": str(tmp_path)})()}
    result = suite_exec_fn(node, {"project_json": project}, ctx)
    assert result["width"] == 48 and result["height"] == 32


def test_codeanim_upstream_bad_fail_closed(monkeypatch, tmp_path):
    """阶段 16: 上游已连边但未给出可用 project_json → fail-closed (不回退默认)。"""
    from tuan_cli.web.dataflow_graph import FlowNode

    default_proj = {"width": 640, "height": 360, "fps": 30, "duration": 2,
                    "nodes": [{"type": "bg", "start": 0, "end": 2,
                               "props": {"type": "solid"}}]}
    node = FlowNode("n", "codeanim",
                    params={"mode": "frame", "t": 0, "project_json": default_proj})
    ctx = {"graph": type("G", (), {"workspace": str(tmp_path)})()}
    try:
        suite_exec_fn(node, {"project_json": {"text": "no project here"}}, ctx)
        assert False, "应抛 ValueError"
    except ValueError as exc:
        assert "project_json" in str(exc)


def test_coerce_project_strips_wrapper(monkeypatch):
    """_coerce_project 从 llm_call 输出包中提取结构化 project_json。"""
    from tuan_cli.web.graph_api import _coerce_project

    project = {"width": 64, "height": 36}
    assert _coerce_project({"json": project, "project_json": project}) == project
    assert _coerce_project({"json": project}) == project
    assert _coerce_project(project) == project
    assert _coerce_project("not-a-dict") is None
    assert _coerce_project(None) is None


def test_build_runner_roundtrip():
    """build_runner 从序列化数据重建 runner, 图可执行。"""
    data = _mk_graph(
        [{"node_id": "a", "ntype": "text", "params": {"content": "ok"},
          "inputs": [], "outputs": [{"name": "out", "ptype": "text"}]}],
        [],
    )
    runner = build_runner(data)
    assert runner.graph.node_ids() == ["a"]
