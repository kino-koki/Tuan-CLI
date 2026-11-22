# -*- coding: utf-8 -*-
"""数据流图 Web API 后端 —— 把 DataFlowGraph 接线进 /web 工作台。

对齐最新开源卖点 (ComfyUI 式多模型自动化视频工作台) 的 Web 层闭环:

* ``GraphStore`` —— 图定义持久化 (workspace/.tuan/graphs/*.json, 可跨会话保存/加载)。
* ``suite_exec_fn`` —— 视频套件感知的执行器: 除内置 text/identity/concat 外,
  还支持 ``llm_call`` (经 ModelGateway 直调多模型) 与 ``codeanim`` (调用
  code_anim_render 出单帧/整片), 让"文本模型调用 → 自动化视频"在图上成环。
* ``run_graph`` —— 构建 GraphRunner 并执行, 返回节点结果 + 状态快照 (前端轮询)。

全链路 fail-closed: 未知节点类型抛错、LLM 解析失败抛错、非法项目拒绝。
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .dataflow_graph import DataFlowGraph, FlowNode, GraphRunner, builtin_exec_fn

# codeanim project_json 的 JSON schema —— llm_call(intent='video_gen') 自动注入,
# 让模型输出结构化 project 可直接喂给 codeanim 生成动画视频 (一句话→视频)。
VIDEO_GEN_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "width": {"type": "integer", "minimum": 1},
        "height": {"type": "integer", "minimum": 1},
        "fps": {"type": "integer", "minimum": 1},
        "duration": {"type": "number", "exclusiveMinimum": 0},
        "nodes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "type": {"type": "string"},
                    "start": {"type": "number"},
                    "end": {"type": "number"},
                    "props": {"type": "object"},
                },
                "required": ["type", "start", "end"],
            },
        },
    },
    "required": ["width", "height", "fps", "duration", "nodes"],
}

GRAPHS_SUBDIR = ".tuan/graphs"
MAX_GRAPHS = 200


# ---------------------------------------------------------------------------
# 图持久化
# ---------------------------------------------------------------------------

class GraphStore:
    """图定义持久化 (JSON 文件, 原子写)。"""

    def __init__(self, workspace: Optional[str]) -> None:
        self.root = Path(workspace or ".") / GRAPHS_SUBDIR

    def _ensure(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)

    def list_graphs(self) -> List[Dict[str, Any]]:
        if not self.root.exists():
            return []
        items = []
        for fp in self.root.glob("*.json"):
            try:
                data = json.loads(fp.read_text(encoding="utf-8"))
                items.append({
                    "id": fp.stem,
                    "name": data.get("name", fp.stem),
                    "updated": data.get("updated", 0),
                    "nodes": len(data.get("data", {}).get("nodes", [])),
                    "edges": len(data.get("data", {}).get("edges", [])),
                })
            except (OSError, ValueError):
                continue
        items.sort(key=lambda x: x["updated"], reverse=True)
        return items[:MAX_GRAPHS]

    def load(self, graph_id: str) -> Optional[Dict[str, Any]]:
        if not self._safe_id(graph_id):
            return None
        fp = self.root / f"{graph_id}.json"
        if not fp.exists():
            return None
        try:
            loaded: Dict[str, Any] = json.loads(fp.read_text(encoding="utf-8"))
            return loaded
        except (OSError, ValueError):
            return None

    def save(self, graph_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        if not self._safe_id(graph_id):
            raise ValueError("graph_id 含非法字符 (fail-closed)")
        self._ensure()
        record = {
            "id": graph_id,
            "name": str(data.get("name") or graph_id),
            "updated": int(time.time()),
            "data": data.get("data") or data,
        }
        fp = self.root / f"{graph_id}.json"
        tmp = self.root / f"{graph_id}.tmp"
        tmp.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
        tmp.replace(fp)
        return record

    @staticmethod
    def _safe_id(graph_id: str) -> bool:
        return bool(graph_id) and "/" not in graph_id and "\\" not in graph_id \
            and ".." not in graph_id


RUNS_SUBDIR = ".tuan/runs"
MAX_RUNS = 100


class RunLog:
    """数据流图运行历史持久化 (workspace/.tuan/runs/*.json, 原子写)。

    每次 /api/graph/run 成功或失败后记录一条: 时间戳、图 id/名称、结果摘要、
    媒体产物路径、图数据快照 (供「载入该次运行」复用)。上限 MAX_RUNS, 超出清理最旧。
    """

    def __init__(self, workspace: Optional[str]) -> None:
        self.root = Path(workspace or ".") / RUNS_SUBDIR

    def _ensure(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)

    def record(self, graph_id: str, name: str, ok: bool,
               error: Optional[str], summary: Dict[str, Any],
               data: Dict[str, Any]) -> Dict[str, Any]:
        self._ensure()
        run_id = f"run_{int(time.time() * 1000)}"
        rec = {
            "run_id": run_id,
            "graph_id": str(graph_id or ""),
            "name": str(name or graph_id or "未命名"),
            "ts": int(time.time() * 1000),
            "ok": bool(ok),
            "error": error,
            "summary": summary,
            "data": data,
        }
        fp = self.root / f"{run_id}.json"
        tmp = self.root / f"{run_id}.tmp"
        tmp.write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
        tmp.replace(fp)
        self._prune()
        return rec

    def list_runs(self) -> List[Dict[str, Any]]:
        if not self.root.exists():
            return []
        items = []
        for fp in self.root.glob("run_*.json"):
            try:
                d = json.loads(fp.read_text(encoding="utf-8"))
                items.append({
                    "run_id": d.get("run_id", fp.stem),
                    "graph_id": d.get("graph_id", ""),
                    "name": d.get("name", fp.stem),
                    "ts": d.get("ts", 0),
                    "ok": d.get("ok", False),
                    "error": d.get("error"),
                    "summary": d.get("summary", {}),
                })
            except (OSError, ValueError):
                continue
        items.sort(key=lambda x: x["ts"], reverse=True)
        return items[:MAX_RUNS]

    def load(self, run_id: str) -> Optional[Dict[str, Any]]:
        if not run_id or "/" in run_id or "\\" in run_id or ".." in run_id:
            return None
        fp = self.root / f"{run_id}.json"
        if not fp.exists():
            return None
        try:
            loaded: Dict[str, Any] = json.loads(fp.read_text(encoding="utf-8"))
            return loaded
        except (OSError, ValueError):
            return None

    def _prune(self) -> None:
        """保留最近 MAX_RUNS 条, 清理最旧。"""
        if not self.root.exists():
            return
        runs = sorted(self.root.glob("run_*.json"), key=lambda p: p.stat().st_mtime,
                      reverse=True)
        for fp in runs[MAX_RUNS:]:
            try:
                fp.unlink()
            except OSError:
                pass


# ---------------------------------------------------------------------------
# 视频套件感知执行器
# ---------------------------------------------------------------------------

def suite_exec_fn(node: FlowNode, inputs: Dict[str, Any],
                  ctx: Dict[str, Any]) -> Any:
    """视频套件执行器: builtin + llm_call + codeanim。"""
    ntype = node.ntype
    # 先走内置基础节点
    if ntype in ("text", "identity", "concat"):
        return builtin_exec_fn(node, inputs, ctx)
    if ntype == "llm_call":
        return _exec_llm_call(node, inputs)
    if ntype == "codeanim":
        return _exec_codeanim(node, inputs, ctx)
    raise ValueError(f"未知节点类型: {ntype} (suite_exec_fn 不支持, fail-closed)")


def _exec_llm_call(node: FlowNode, inputs: Dict[str, Any]) -> Dict[str, Any]:
    """llm_call 节点: 经 ModelGateway 直调模型, 返回 {text, json, project_json, provider_id, model}。
    ``project_json`` 为结构化 json 输出 (供下游 codeanim 作为 project_json 输入), 无则 None。
    intent='video_gen' 且未显式给 json_schema 时, 自动注入 codeanim 的 project_json schema,
    让模型输出可直接喂给 codeanim (一句话→动画视频)。"""
    from ..runtime.gateway import ModelGateway

    p = node.params
    prompt = str(p.get("prompt") or inputs.get("prompt") or "")
    if not prompt:
        raise ValueError("llm_call 节点缺 prompt (fail-closed)")
    gw = ModelGateway()
    schema = p.get("json_schema") if isinstance(p.get("json_schema"), dict) else None
    if schema is None and p.get("intent") == "video_gen":
        schema = VIDEO_GEN_SCHEMA
    result = gw.generate(
        prompt,
        system_prompt=p.get("system_prompt") or inputs.get("system_prompt"),
        intent=p.get("intent"),
        provider_id=p.get("provider_id"),
        json_schema=schema,
        max_tokens=int(p["max_tokens"]) if p.get("max_tokens") else None,
        temperature=float(p["temperature"]) if p.get("temperature") is not None else None,
    )
    result["project_json"] = result.get("json")
    return result


def _coerce_project(value: Any) -> Optional[Dict[str, Any]]:
    """从上游输出 / 节点参数中提取 project_json dict; 无法提取返回 None。

    上游若是 llm_call 输出 dict (含 project_json/json 键), 取其结构化字段;
    裸 dict 直接返回 (是否合法由 validate_project 裁决, 不在这里放宽)。
    """
    if isinstance(value, dict) and ("project_json" in value or "json" in value):
        value = value.get("project_json") or value.get("json")
    return value if isinstance(value, dict) else None


def _exec_codeanim(node: FlowNode, inputs: Dict[str, Any],
                   ctx: Dict[str, Any]) -> Dict[str, Any]:
    """codeanim 节点: 调 code_anim_render 出单帧 (默认) 或整片。"""
    from . import code_anim_render as car

    p = node.params
    # 阶段 16: 用「端口是否被连边」而非「参数是否为空」决定输入来源。
    # GraphRunner 只为**已连边**的输入端口填充 inputs, 故键存在 ⟺ 上游已连边。
    # 这修掉了原实现的遮蔽 bug: codeanim 默认 params 自带非空 project_json,
    # 旧逻辑会让"已连边的上游输出"被节点默认项目静默覆盖。
    if "project_json" in inputs:
        pj = _coerce_project(inputs.get("project_json"))
        if pj is None:
            raise ValueError("codeanim 的 project_json 端口已连上游, 但上游未给出"
                             "可用的 project_json (fail-closed)")
    else:
        pj = _coerce_project(p.get("project_json"))
        if pj is None:
            raise ValueError("codeanim 节点缺 project_json (fail-closed)")
    err = car.validate_project(pj)
    if err:
        raise ValueError(f"codeanim project_json 非法: {err} (fail-closed)")
    mode = str(p.get("mode") or "frame")
    if mode == "render":
        workspace = (ctx.get("graph", None) and getattr(ctx["graph"], "workspace", None)) or None
        out = _codeanim_out_path(workspace or ".")
        fps = int(p.get("fps") or pj.get("fps") or 30)
        result = car.render_video(pj, out, fps=fps,
                                  workspace=workspace)
        # media_rel: 相对 workspace/media/ 的路径, 供前端拼 /api/media?path=
        media_rel = _media_rel(workspace or ".", out)
        return {"out_path": out, "media_rel": media_rel, **result}
    # 默认: 单帧
    t = float(p.get("t") or 0.0)
    img = car.draw_frame(pj, t)
    import base64
    import io
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return {
        "width": img.width,
        "height": img.height,
        "t": t,
        "png_data_url": f"data:image/png;base64,{b64}",
    }


def _codeanim_out_path(workspace: str) -> str:
    import time as _t
    base = Path(workspace) / "media"
    base.mkdir(parents=True, exist_ok=True)
    return str(base / f"graph_{int(_t.time() * 1000)}.mp4")


def _media_rel(workspace: str, out_path: str) -> str:
    """把绝对输出路径映射为相对 workspace/media/ 的子路径 (供前端 /api/media)。"""
    try:
        base = (Path(workspace) / "media").resolve()
        target = Path(out_path).resolve()
        return str(target.relative_to(base))
    except (ValueError, OSError):
        return Path(out_path).name


# ---------------------------------------------------------------------------
# 执行封装
# ---------------------------------------------------------------------------

def build_runner(data: Dict[str, Any], exec_fn: Optional[Callable[..., Any]] = None,
                 cache: Optional[Dict[str, Any]] = None,
                 force: bool = False) -> GraphRunner:
    """从序列化图数据构建 GraphRunner (默认用 suite_exec_fn)。"""
    fn = exec_fn or suite_exec_fn
    return _from_dict_with_cache(data, fn, cache, force)


def _from_dict_with_cache(data: Dict[str, Any], exec_fn: Callable[..., Any],
                          cache: Optional[Dict[str, Any]],
                          force: bool) -> GraphRunner:
    """重建 runner (带持久化缓存注入)。"""
    g = DataFlowGraph()
    for n in data.get("nodes", []):
        g.add_node(
            n["node_id"], n["ntype"], n.get("params", {}),
            inputs=[(p["name"], p.get("ptype", "any")) for p in n.get("inputs", [])],
            outputs=[(p["name"], p.get("ptype", "any")) for p in n.get("outputs", [])],
        )
    for e in data.get("edges", []):
        g.connect(e["src_node"], e["src_port"], e["dst_node"], e["dst_port"])
    return GraphRunner(g, exec_fn, cache=cache or {}, force=force)


def run_graph(data: Dict[str, Any], *,
              exec_fn: Optional[Callable[..., Any]] = None,
              cache: Optional[Dict[str, Any]] = None,
              force: bool = False) -> Dict[str, Any]:
    """执行图并返回 {results, logs, nodes}。

    fail-closed 契约:
    * 拓扑含环 / 缺执行器 → GraphRunner.run() 抛 ValueError。
    * 任一节点执行失败 → 此处聚合首个失败节点并抛 ValueError
      (避免"静默跳过"吞掉错误, 前端应显示而非假装成功)。
    """
    runner = build_runner(data, exec_fn=exec_fn, cache=cache, force=force)
    results = runner.run()
    # 聚合失败: 只要有一个节点 failed, 整图视为失败 (fail-closed)
    failed = [lg for lg in runner.logs if lg.status == "failed"]
    if failed:
        first = failed[0]
        raise ValueError(f"节点 {first.node_id} ({first.ntype}) 失败: "
                         f"{first.error or '未知错误'} (fail-closed)")
    return {
        "results": results,
        "logs": [lg.to_dict() for lg in runner.logs],
        "nodes": {nid: n.to_dict() for nid, n in runner.graph.nodes.items()},
    }


__all__ = [
    "GraphStore", "RunLog", "suite_exec_fn", "build_runner", "run_graph",
    "GRAPHS_SUBDIR", "RUNS_SUBDIR",
]
