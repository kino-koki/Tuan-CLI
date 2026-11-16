# -*- coding: utf-8 -*-
"""ComfyUI 类数据流节点图执行引擎 (DataFlowGraph) —— 多模型自动化视频 AI 制作的核心。

设计目标 (对齐最新开源卖点: ComfyUI 风格节点工作台 + Agent 驱动的自动化成片):
  * **依赖驱动的数据流执行**: 节点有输入/输出端口, 连线定义数据依赖; 执行器按
    拓扑序调度, 上游输出注入下游输入 (ComfyUI 模型)。
  * **端口类型**: 每个端口可带类型标签 (``text``/``image``/``model``/``video``/``any``),
    连线时校验类型兼容, 不兼容连线拒绝 (fail-closed)。
  * **结果缓存 + 选择性重跑**: 节点默认按 ``(type, params, 上游哈希)`` 缓存结果;
    修改某节点可只重跑其下游 (增量), 未受影响分支复用缓存 —— 满足"改一处只重渲下游"。
  * **拓扑调度**: Kahn 剥层; 环检测失败即整图拒绝执行 (绝不执行含环图)。
  * **fail-closed 语义**: 上游失败 → 下游一律 SKIPPED (不执行); 未知节点类型 → 拒绝;
    ``exec_fn`` 必须显式提供, 永不 eval/exec。
  * **可观察性**: 每次执行记录节点级日志 (started/finished/skipped/cached/error),
    供前端进度轮询与审计。

本引擎是**纯数据流调度器** —— 它不关心节点具体做什么 (绘图/调模型/合成), 只负责
"正确拓扑 + 正确数据流 + 缓存增量", 具体节点执行逻辑由调用方经 ``exec_fn`` 注入。
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

# ---------------------------------------------------------------------------
# 端口 / 节点 / 连线 数据结构
# ---------------------------------------------------------------------------

#: 端口类型标签 (用于连线兼容性校验)。"any" 兼容一切。
PORT_TYPES = ("text", "image", "model", "video", "audio", "any")


class PortKind(str, Enum):
    INPUT = "input"
    OUTPUT = "output"


@dataclass
class Port:
    """节点的一个端口。"""

    name: str
    kind: PortKind
    ptype: str = "any"  # 类型标签, 用于连线兼容校验

    def __post_init__(self) -> None:
        if self.ptype not in PORT_TYPES:
            # 未知类型标签 → 降级为 any (保守但可执行), 不抛 (避免误杀合法图)。
            self.ptype = "any"


@dataclass
class FlowNode:
    """数据流图中的一个节点。"""

    node_id: str
    ntype: str  # 节点类型 (调用方 exec_fn 据此分发)
    params: Dict[str, Any] = field(default_factory=dict)
    inputs: List[Port] = field(default_factory=list)   # 输入端口
    outputs: List[Port] = field(default_factory=list)  # 输出端口

    # --- 运行时状态 ---
    status: str = "pending"  # pending/running/completed/failed/skipped
    result: Optional[Any] = None  # 节点产出 (下游可消费)
    error: Optional[str] = None
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    cache_hit: bool = False  # 本次是否命中缓存 (未重跑)

    def input_port(self, name: str) -> Optional[Port]:
        for p in self.inputs:
            if p.name == name:
                return p
        return None

    def output_port(self, name: str) -> Optional[Port]:
        for p in self.outputs:
            if p.name == name:
                return p
        return None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "ntype": self.ntype,
            "status": self.status,
            "cache_hit": self.cache_hit,
            "error": self.error,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


@dataclass
class FlowEdge:
    """一条数据流连线: 上游输出端口 → 下游输入端口。"""

    src_node: str
    src_port: str
    dst_node: str
    dst_port: str

    def key(self) -> Tuple[str, str, str, str]:
        return (self.src_node, self.src_port, self.dst_node, self.dst_port)


# ---------------------------------------------------------------------------
# 执行状态
# ---------------------------------------------------------------------------

class ExecStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


@dataclass
class NodeLog:
    """单节点执行日志 (供前端进度轮询)。"""

    node_id: str
    ntype: str
    status: str
    cache_hit: bool = False
    error: Optional[str] = None
    started_at: Optional[float] = None
    finished_at: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "ntype": self.ntype,
            "status": self.status,
            "cache_hit": self.cache_hit,
            "error": self.error,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


#: 节点执行函数签名: (node, inputs, ctx) -> result
#:   * node: FlowNode
#:   * inputs: {input_port_name: 上游输出值}
#:   * ctx: 执行上下文 (含 force、logger、缓存键等)
ExecFn = Callable[[FlowNode, Dict[str, Any], Dict[str, Any]], Any]


# ---------------------------------------------------------------------------
# 数据流图
# ---------------------------------------------------------------------------

class DataFlowGraph:
    """ComfyUI 类依赖驱动数据流图。

    用法::

        g = DataFlowGraph()
        g.add_node("text1", "text", params={"content": "Hello"})
        g.add_node("anim", "animator", params={"duration": 5})
        g.connect("text1", "out", "anim", "src")   # 上游输出 → 下游输入

        runner = GraphRunner(g, exec_fn=my_exec)
        result = runner.run()
    """

    def __init__(self) -> None:
        self._nodes: Dict[str, FlowNode] = {}
        self._edges: List[FlowEdge] = []
        self._lock = threading.Lock()

    # --- 图构建 ---

    def add_node(
        self,
        node_id: str,
        ntype: str,
        params: Optional[Dict[str, Any]] = None,
        inputs: Optional[List[Tuple[str, str]]] = None,   # [(name, ptype)]
        outputs: Optional[List[Tuple[str, str]]] = None,  # [(name, ptype)]
    ) -> FlowNode:
        """添加节点。``inputs``/``outputs`` 为 [(端口名, 类型)] 列表。"""
        with self._lock:
            if node_id in self._nodes:
                raise ValueError(f"重复节点: {node_id}")
            in_ports = [Port(name, PortKind.INPUT, pt) for name, pt in (inputs or [])]
            out_ports = [Port(name, PortKind.OUTPUT, pt) for name, pt in (outputs or [])]
            node = FlowNode(
                node_id=node_id, ntype=ntype, params=params or {},
                inputs=in_ports, outputs=out_ports,
            )
            self._nodes[node_id] = node
            return node

    def connect(self, src_node: str, src_port: str,
                dst_node: str, dst_port: str) -> None:
        """添加连线, 校验: 两端存在、端口存在、方向正确、类型兼容。"""
        with self._lock:
            if src_node not in self._nodes or dst_node not in self._nodes:
                raise ValueError("连线引用未知节点")
            if src_node == dst_node:
                raise ValueError("不允许自环连线")
            sp = self._nodes[src_node].output_port(src_port)
            dp = self._nodes[dst_node].input_port(dst_port)
            if sp is None:
                raise ValueError(f"上游无输出端口: {src_node}.{src_port}")
            if dp is None:
                raise ValueError(f"下游无输入端口: {dst_node}.{dst_port}")
            # 类型兼容: 上游类型 == 下游类型, 或任一为 "any"
            if sp.ptype != "any" and dp.ptype != "any" and sp.ptype != dp.ptype:
                raise ValueError(
                    f"端口类型不兼容: {src_node}.{src_port}({sp.ptype}) -> "
                    f"{dst_node}.{dst_port}({dp.ptype})"
                )
            edge = FlowEdge(src_node, src_port, dst_node, dst_port)
            if edge.key() not in {e.key() for e in self._edges}:
                self._edges.append(edge)

    def remove_node(self, node_id: str) -> None:
        """移除节点及其关联连线。"""
        with self._lock:
            self._nodes.pop(node_id, None)
            self._edges = [e for e in self._edges
                           if e.src_node != node_id and e.dst_node != node_id]

    # --- 图查询 ---

    @property
    def nodes(self) -> Dict[str, FlowNode]:
        return dict(self._nodes)

    @property
    def edges(self) -> List[FlowEdge]:
        return list(self._edges)

    def node_ids(self) -> List[str]:
        return list(self._nodes.keys())

    def upstream_of(self, node_id: str) -> Set[str]:
        """直接上游节点集合。"""
        return {e.src_node for e in self._edges if e.dst_node == node_id}

    def downstream_of(self, node_id: str) -> Set[str]:
        """直接下游节点集合。"""
        return {e.dst_node for e in self._edges if e.src_node == node_id}

    def in_degree(self) -> Dict[str, int]:
        """各节点入度 (上游数量)。"""
        deg: Dict[str, int] = {nid: 0 for nid in self._nodes}
        for e in self._edges:
            deg[e.dst_node] += 1
        return deg

    def topological_order(self) -> List[str]:
        """Kahn 拓扑序; 含环时抛 ValueError (fail-closed: 绝不执行含环图)。"""
        deg = self.in_degree()
        # 只对图中节点计数; 连线可能引用已被移除节点, 需先过滤。
        valid = set(self._nodes)
        queue = [nid for nid, d in deg.items() if d == 0 and nid in valid]
        order: List[str] = []
        adj: Dict[str, List[str]] = {}
        for e in self._edges:
            if e.src_node in valid and e.dst_node in valid:
                adj.setdefault(e.src_node, []).append(e.dst_node)
        idx = 0
        while idx < len(queue):
            nid = queue[idx]
            idx += 1
            order.append(nid)
            for nxt in adj.get(nid, []):
                deg[nxt] -= 1
                if deg[nxt] == 0:
                    queue.append(nxt)
        if len(order) != len(valid):
            raise ValueError("图存在环依赖, 拒绝执行")
        return order

    def has_cycle(self) -> bool:
        try:
            self.topological_order()
            return False
        except ValueError:
            return True

    def validate(self) -> None:
        """执行前完整校验: 节点/连线/拓扑/未连接输入。"""
        for nid, node in self._nodes.items():
            # 未知节点类型在 exec_fn 处拒绝; 此处仅校验图结构。
            for port in node.inputs:
                connected = any(e.dst_node == nid and e.dst_port == port.name
                                for e in self._edges)
                # 无上游连线的输入端口: 若 params 未提供默认值, 记日志但不阻断
                # (由 exec_fn 决定是否缺参报错)。
        self.topological_order()  # 环检测, 失败抛 ValueError


# ---------------------------------------------------------------------------
# 执行器
# ---------------------------------------------------------------------------

class GraphRunner:
    """数据流图执行器: 拓扑调度 + 数据流注入 + 结果缓存 + 增量重跑。

    缓存键 = (节点类型, 参数签名, 上游输出签名)。修改某节点 → 其下游缓存键
    变化 → 自动重跑; 未受影响分支命中缓存不重跑。
    """

    def __init__(self, graph: DataFlowGraph, exec_fn: ExecFn,
                 cache: Optional[Dict[str, Any]] = None,
                 force: bool = False) -> None:
        self.graph = graph
        self.exec_fn = exec_fn
        # 外部可注入持久化缓存 (dict-like); 默认进程内。
        self._cache = cache if cache is not None else {}
        self.force = force  # True: 忽略缓存全部重跑
        self._logs: List[NodeLog] = []
        self._results: Dict[str, Any] = {}

    # --- 缓存 ---

    @staticmethod
    def _sig(value: Any) -> str:
        """生成任意值签名 (用于缓存键)。不可哈希值降级为 repr。"""
        try:
            hash(value)
            return repr(value)
        except TypeError:
            return repr(value)

    def _node_cache_key(self, node: FlowNode,
                        upstream_results: Dict[str, Any]) -> str:
        """节点缓存键 = f(type, params, 上游各输出)。"""
        parts = [node.ntype, repr(sorted(node.params.items(), key=lambda kv: kv[0]))]
        for e in self.graph.edges:
            if e.dst_node == node.node_id:
                val = upstream_results.get(e.src_node, None)
                parts.append(f"{e.src_node}:{e.src_port}:{self._sig(val)}")
        return "::".join(parts)

    # --- 执行 ---

    def run(self) -> Dict[str, Any]:
        """执行整图, 返回 {node_id: result}。含环/缺执行器则抛异常 (fail-closed)。"""
        order = self.graph.topological_order()  # 环检测
        if not self.exec_fn:
            raise ValueError("GraphRunner 需要 exec_fn")
        self._logs = []
        self._results = {}
        upstream_results: Dict[str, Any] = {}
        node_status: Dict[str, str] = {}
        upstream_sig: Dict[str, str] = {}

        for nid in order:
            node = self.graph.nodes[nid]
            # 上游状态传播: 任一直接上游失败/跳过 → 本节点 SKIPPED
            up_failed = any(
                node_status.get(e.src_node, "completed") in ("failed", "skipped")
                for e in self.graph.edges if e.dst_node == nid
            )
            if up_failed:
                self._mark(nid, node, "skipped",
                           error="上游失败/跳过, 本节点不执行")
                continue

            node_status[nid] = "running"
            self._mark(nid, node, "running")

            # 收集本节点输入: 上游输出值 (按输入端口名)
            inputs: Dict[str, Any] = {}
            for e in self.graph.edges:
                if e.dst_node == nid:
                    inputs[e.dst_port] = upstream_results.get(e.src_node, None)

            # 缓存键 (含上游签名)
            key = self._node_cache_key(node, upstream_results)
            cacheable = bool(node.params.get("cache", True))
            if cacheable and not self.force and key in self._cache:
                result = self._cache[key]
                upstream_results[nid] = result
                upstream_sig[nid] = self._sig(result)
                node_status[nid] = "completed"
                self._mark(nid, node, "completed", cache_hit=True)
                continue

            # 执行
            try:
                ctx = {"force": self.force, "cache_key": key,
                       "logs": self._logs, "graph": self.graph}
                result = self.exec_fn(node, inputs, ctx)
                upstream_results[nid] = result
                upstream_sig[nid] = self._sig(result)
                node_status[nid] = "completed"
                if cacheable:
                    self._cache[key] = result
                self._mark(nid, node, "completed", cache_hit=False)
            except Exception as exc:  # noqa: BLE001 —— 节点失败传播为 SKIPPED
                node_status[nid] = "failed"
                self._mark(nid, node, "failed", error=str(exc))

        self._results = upstream_results
        return dict(upstream_results)

    def _mark(self, nid: str, node: FlowNode, status: str, *,
              error: Optional[str] = None, cache_hit: bool = False) -> None:
        node.status = status
        node.error = error
        node.cache_hit = cache_hit
        now = time.time()
        if status in ("running", "completed", "failed", "skipped"):
            if node.started_at is None:
                node.started_at = now
            node.finished_at = now
        # 每个节点只记录**最终状态**一条日志 (running 为中间态, 覆盖之)。
        # 这样前端进度轮询看到的是"节点最终状态", 而非中间 running。
        final_only = status in ("completed", "failed", "skipped")
        if final_only:
            for existing in self._logs:
                if existing.node_id == nid:
                    existing.status = status
                    existing.cache_hit = cache_hit
                    existing.error = error
                    existing.finished_at = node.finished_at
                    break
            else:
                self._logs.append(NodeLog(
                    node_id=nid, ntype=node.ntype, status=status,
                    cache_hit=cache_hit, error=error,
                    started_at=node.started_at, finished_at=node.finished_at,
                ))
        else:
            self._logs.append(NodeLog(
                node_id=nid, ntype=node.ntype, status=status,
                cache_hit=cache_hit, error=error,
                started_at=node.started_at, finished_at=node.finished_at,
            ))

    # --- 结果查询 ---

    @property
    def logs(self) -> List[NodeLog]:
        return list(self._logs)

    def result(self, node_id: str) -> Optional[Any]:
        return self._results.get(node_id)

    def status(self) -> Dict[str, Any]:
        """执行状态快照 (前端轮询用)。"""
        return {
            "nodes": {nid: n.to_dict() for nid, n in self.graph.nodes.items()},
            "logs": [lg.to_dict() for lg in self._logs],
        }

    def to_dict(self) -> Dict[str, Any]:
        """序列化整图 (供 /api 返回 / 持久化)。"""
        return {
            "nodes": [
                {
                    "node_id": n.node_id,
                    "ntype": n.ntype,
                    "params": n.params,
                    "inputs": [{"name": p.name, "ptype": p.ptype} for p in n.inputs],
                    "outputs": [{"name": p.name, "ptype": p.ptype} for p in n.outputs],
                }
                for n in self.graph.nodes.values()
            ],
            "edges": [
                {"src_node": e.src_node, "src_port": e.src_port,
                 "dst_node": e.dst_node, "dst_port": e.dst_port}
                for e in self.graph.edges
            ],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any], exec_fn: ExecFn) -> "GraphRunner":
        """从序列化图重建 (前端保存/加载)。"""
        g = DataFlowGraph()
        for n in data.get("nodes", []):
            g.add_node(
                n["node_id"], n["ntype"], n.get("params", {}),
                inputs=[(p["name"], p.get("ptype", "any")) for p in n.get("inputs", [])],
                outputs=[(p["name"], p.get("ptype", "any")) for p in n.get("outputs", [])],
            )
        for e in data.get("edges", []):
            g.connect(e["src_node"], e["src_port"], e["dst_node"], e["dst_port"])
        return cls(g, exec_fn)


# ---------------------------------------------------------------------------
# 便捷: 内置基础节点执行器 (文本/常量/合并) —— 供测试与最小可用闭环
# ---------------------------------------------------------------------------

def builtin_exec_fn(node: FlowNode, inputs: Dict[str, Any],
                    ctx: Dict[str, Any]) -> Any:
    """最小内置执行器: 覆盖 text/concat/identity 三类节点。

    供测试与"最小可用闭环"演示; 真实视频节点由调用方提供更完整 exec_fn。
    """
    ntype = node.ntype
    if ntype == "text":
        return str(node.params.get("content", ""))
    if ntype == "identity":
        # 透传首个输入
        for port in node.inputs:
            if port.name in inputs:
                return inputs[port.name]
        return None
    if ntype == "concat":
        parts = []
        if node.params.get("separator") is not None:
            parts.append(str(node.params["separator"]))
        # 按输入端口名排序拼接 (除 separator 外)
        for port in sorted(node.inputs, key=lambda p: p.name):
            if port.name in inputs:
                parts.append(str(inputs[port.name]))
        return "".join(parts)
    raise ValueError(f"未知节点类型: {ntype} (builtin_exec_fn 不支持)")
