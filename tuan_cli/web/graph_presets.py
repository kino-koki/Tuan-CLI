# -*- coding: utf-8 -*-
"""数据流图预置示例 (阶段 16) —— 一键载入即可运行的示例图。

定位: 让 /web/graph 三栏工作台打开即有可运行的起点, 不必从零拖节点/连边:

* ``PRESETS`` —— 预置示例图常量表 (纯数据, 无副作用, 跨会话稳定)。
* ``preset_graph(preset_id)`` —— 取一份深拷贝 (调用方可自由修改后保存)。
* ``list_presets()`` —— 前端「载入示例」下拉的目录。

每张预置图都遵守与 ``GraphStore`` 落盘图相同的序列化契约
(``{nodes:[{node_id,ntype,params,inputs,outputs}], edges:[{src_node,src_port,
dst_node,dst_port}]}``), 因此既可直接 POST 到 ``/api/graph/run``,
也可经 ``/api/graph/save`` 持久化后复用。

fail-closed 契约: 未知 preset_id 抛 ValueError (不静默返回空图)。
"""

from __future__ import annotations

import copy
from typing import Any, Dict, List


def _ports(names: List[str]) -> List[Dict[str, str]]:
    """把端口名列表转成序列化的端口描述 [{name, ptype}]。"""
    return [{"name": n, "ptype": "any"} for n in names]


def _code_demo_project() -> Dict[str, Any]:
    """代码动画示例 project_json: 语法高亮逐行揭示 + 标题 + 粒子点缀。"""
    code = (
        "def render(project, t):\n"
        "    frame = project.frame_at(t)\n"
        "    for node in frame.nodes:\n"
        "        node.draw(frame.canvas)\n"
        "    return frame.to_image()\n"
    )
    return {
        "width": 640, "height": 360, "fps": 24, "duration": 3.0,
        "nodes": [
            {"type": "bg", "start": 0, "end": 3, "props": {"type": "solid"}},
            {"type": "title", "start": 0.2, "end": 3, "props": {
                "text": "代码 → 动画 → 视频", "font_size": 28, "y": 24,
                "slide": True}},
            {"type": "code", "start": 0.8, "end": 2.6, "props": {
                "code": code, "title": "code_anim_render.py", "language": "python",
                "reveal": "lines", "font_size": 13, "line_height": 20,
                "x": 40, "y": 76, "w": 420, "h": 210}},
            {"type": "particles", "start": 2.4, "end": 3, "props": {
                "count": 60, "origin": "center", "spread": 180, "life": 1.2,
                "color": "#4FC3F7"}},
        ],
    }


#: 预置示例图 (id → {name, desc, data})。
PRESETS: Dict[str, Dict[str, Any]] = {
    "code_demo": {
        "name": "代码动画演示",
        "desc": "codeanim 单节点出整片 mp4 (语法高亮逐行揭示 + 标题 + 粒子), 零外部依赖",
        "data": {
            "nodes": [
                {"node_id": "anim", "ntype": "codeanim",
                 "params": {"mode": "render", "fps": 30,
                            "project_json": _code_demo_project()},
                 "inputs": _ports(["project_json"]),
                 "outputs": _ports(["out"])},
            ],
            "edges": [],
        },
    },
    "text_pipeline": {
        "name": "文本流水线",
        "desc": "text → identity → concat 内置节点链路 (数据流注入与缓存的最小闭环)",
        "data": {
            "nodes": [
                {"node_id": "a", "ntype": "text",
                 "params": {"content": "青小团"}, "inputs": [],
                 "outputs": _ports(["out"])},
                {"node_id": "b", "ntype": "identity", "params": {},
                 "inputs": _ports(["in"]), "outputs": _ports(["out"])},
                {"node_id": "c", "ntype": "text", "params": {"content": "数据流图"},
                 "inputs": [], "outputs": _ports(["out"])},
                {"node_id": "d", "ntype": "concat", "params": {"separator": " · "},
                 "inputs": _ports(["a", "b"]), "outputs": _ports(["out"])},
            ],
            "edges": [
                {"src_node": "a", "src_port": "out", "dst_node": "b", "dst_port": "in"},
                {"src_node": "b", "src_port": "out", "dst_node": "d", "dst_port": "a"},
                {"src_node": "c", "src_port": "out", "dst_node": "d", "dst_port": "b"},
            ],
        },
    },
    "video_gen": {
        "name": "一句话→动画视频",
        "desc": "llm_call(intent=video_gen, 自动注入 project schema) → codeanim 出整片; "
               "端口已连边时上游未给出 project 会 fail-closed, 不静默用默认项目",
        "data": {
            "nodes": [
                {"node_id": "llm", "ntype": "llm_call",
                 "params": {
                     "prompt": "做一个 640x360、3 秒、30fps 的代码动画: 深色背景, "
                               "标题 'Hello Code', 一段 5 行左右的 python 代码逐行揭示, "
                               "结尾粒子爆发。",
                     "intent": "video_gen", "max_tokens": 900},
                 "inputs": [], "outputs": _ports(["out", "project_json"])},
                {"node_id": "anim", "ntype": "codeanim",
                 "params": {"mode": "render", "fps": 30},
                 "inputs": _ports(["project_json"]),
                 "outputs": _ports(["out"])},
            ],
            "edges": [
                {"src_node": "llm", "src_port": "project_json",
                 "dst_node": "anim", "dst_port": "project_json"},
            ],
        },
    },
}


def list_presets() -> List[Dict[str, Any]]:
    """预置图目录 (前端「载入示例」下拉): [{id, name, desc, nodes, edges}]。"""
    items = []
    for pid, pre in PRESETS.items():
        data = pre.get("data") or {}
        items.append({
            "id": pid,
            "name": pre.get("name") or pid,
            "desc": pre.get("desc") or "",
            "nodes": len(data.get("nodes") or []),
            "edges": len(data.get("edges") or []),
        })
    return items


def preset_graph(preset_id: str) -> Dict[str, Any]:
    """取一份预置图的深拷贝 (含 name/data); 未知 id 抛 ValueError (fail-closed)。"""
    pre = PRESETS.get(preset_id)
    if pre is None:
        raise ValueError(f"未知预置示例: {preset_id} (可选: {sorted(PRESETS)}) "
                         f"(fail-closed)")
    return copy.deepcopy(pre)


def get_preset_data(preset_id: str) -> Dict[str, Any]:
    """取预置图的序列化图数据 (可直接 run/save); 未知 id 抛 ValueError。"""
    return preset_graph(preset_id)["data"]


__all__ = [
    "PRESETS", "list_presets", "preset_graph", "get_preset_data",
]
