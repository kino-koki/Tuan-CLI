"""编排层 (Orchestrator) —— 持久化多 Agent 编排与故障恢复。

阶段 B「持久化多 Agent 编排与故障恢复」的核心: 把会话内协作升级为
**跨会话可恢复的编排层**。

与 swarm.py (黑板) / collaboration_protocol.py (结构化消息) 的关系:
- 黑板 = 共享状态容器 (key→value + 事件流);
- 协作协议 = Agent 间结构化通信 (消息类型/路由/依赖/冲突/版本);
- 本编排层 = **任务级调度** (DAG 拓扑 + 断点恢复 + 失败回滚 + 可重放),
  面向"一个目标拆成多个节点、由多个 worker 执行"的场景。
三者分层: 黑板是"状态", 协议是"通信", 编排是"调度"。

设计原则 (可测试/可复用, 不过度工程):
- 纯逻辑核心: 不直接执行 Agent/读 UI; 节点执行由注入的 `executor` 回调决定;
- 持久化: `GroupState` 用 JSON 落盘 (SQLite 可换), 含 DAG/worker/黑板/游标;
- fail-safe: 节点级失败 → 指数退避重试 → 仍失败触发依赖子树回滚;
- 可重放: 断点恢复时已完成节点复用结果, 未完成节点重跑。

典型用法::

    orch = Orchestrator(executor=my_exec, persist_dir=".tuan/groups")
    orch.plan("g1", [("a", []), ("b", ["a"]), ("c", ["a", "b"])])
    orch.execute("g1")
    orch.resume("g1")   # 崩溃后恢复
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple


class NodeState(str, Enum):
    """节点状态机: pending → running → done | failed | rolled_back。"""

    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


class GroupStateStore:
    """群组状态持久化 (JSON 落盘, 原子写)。

    存储约定: 每个群组一个 JSON 文件 `<persist_dir>/<group_id>.json`,
    含任务 DAG、worker 状态、黑板快照、阶段游标。崩溃安全 (临时文件 + os.replace)。
    """

    def __init__(self, persist_dir: str) -> None:
        self._dir = persist_dir
        os.makedirs(persist_dir, exist_ok=True)

    def _path(self, group_id: str) -> str:
        safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in group_id)
        return os.path.join(self._dir, f"{safe}.json")

    def save(self, group_id: str, data: Dict[str, Any]) -> str:
        """原子写群组状态。"""
        path = self._path(group_id)
        parent = os.path.dirname(path)
        fd, tmp = tempfile.mkstemp(prefix=os.path.basename(path) + ".",
                                   suffix=".tmp", dir=parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
        finally:
            try:
                os.unlink(tmp)
            except FileNotFoundError:
                pass
        return path

    def load(self, group_id: str) -> Optional[Dict[str, Any]]:
        path = self._path(group_id)
        if not os.path.exists(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                data: Dict[str, Any] = json.load(f)
                return data
        except (json.JSONDecodeError, OSError):
            return None

    def exists(self, group_id: str) -> bool:
        return os.path.exists(self._path(group_id))

    def list_groups(self) -> List[str]:
        if not os.path.isdir(self._dir):
            return []
        return sorted(f[:-5] for f in os.listdir(self._dir) if f.endswith(".json"))


@dataclass
class OrchestrationNode:
    """DAG 中的一个任务节点。"""

    node_id: str
    deps: List[str] = field(default_factory=list)   # 依赖的节点 ID
    state: NodeState = NodeState.PENDING
    result: Any = None                              # 执行产物
    attempts: int = 0
    max_attempts: int = 3
    error: Optional[str] = None
    started_at: float = 0.0
    finished_at: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "deps": list(self.deps),
            "state": self.state.value,
            "result": self.result,
            "attempts": self.attempts,
            "max_attempts": self.max_attempts,
            "error": self.error,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "OrchestrationNode":
        return cls(
            node_id=d.get("node_id", ""),
            deps=list(d.get("deps", [])),
            state=NodeState(d.get("state", "pending")),
            result=d.get("result"),
            attempts=d.get("attempts", 0),
            max_attempts=d.get("max_attempts", 3),
            error=d.get("error"),
            started_at=d.get("started_at", 0.0),
            finished_at=d.get("finished_at", 0.0),
        )


class Orchestrator:
    """可持久化、可重放、可恢复的多 Agent 任务编排。

    执行器约定 (executor): `(node: OrchestrationNode, blackboard: Dict) -> Any`
    返回节点产物; 抛异常视为节点失败。worker 身份等细节由调用方在 executor
    内实现 (可路由到不同 Agent), 编排层只关心 DAG 拓扑与故障恢复。
    """

    def __init__(
        self,
        executor: Callable[[OrchestrationNode, Dict[str, Any]], Any],
        persist_dir: str = ".tuan/groups",
        backoff_base: float = 1.0,
        backoff_max: float = 30.0,
    ) -> None:
        self._executor = executor
        self._store = GroupStateStore(persist_dir)
        self._backoff_base = backoff_base
        self._backoff_max = backoff_max
        self._nodes: Dict[str, OrchestrationNode] = {}
        self._blackboard: Dict[str, Any] = {}
        self._current_group: Optional[str] = None

    # ---------------------------------------------------------- 规划
    def plan(self, group_id: str,
             nodes: List[Tuple[str, List[str]]]) -> Dict[str, Any]:
        """定义任务 DAG: nodes = [(node_id, [dep_ids]), ...]。覆写旧计划。"""
        self._validate_dag(nodes)
        self._nodes = {}
        for nid, deps in nodes:
            self._nodes[nid] = OrchestrationNode(node_id=nid, deps=list(deps))
        self._blackboard = {}
        self._current_group = group_id
        self._persist()
        return {"group_id": group_id, "nodes": len(self._nodes)}

    def _validate_dag(self, nodes: List[Tuple[str, List[str]]]) -> None:
        """校验: 无重复 ID、依赖存在、无环。"""
        ids = [n[0] for n in nodes]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate node id in plan")
        idset = set(ids)
        for nid, deps in nodes:
            for d in deps:
                if d not in idset:
                    raise ValueError(f"node '{nid}' depends on unknown '{d}'")
        # 拓扑检测 (Kahn): 能完全排序即无环
        indeg = {n[0]: 0 for n in nodes}
        for _, deps in nodes:
            for d in deps:
                indeg[d] += 1  # 反向计数, 仅用于环检测
        # 用依赖图做环检测: 从无依赖节点剥层
        remaining = set(ids)
        while remaining:
            ready = {n[0] for n in nodes if n[0] in remaining
                     and all(d not in remaining for d in n[1])}
            if not ready:
                raise ValueError("cyclic dependency in plan")
            remaining -= ready

    # ---------------------------------------------------------- 执行
    def execute(self, group_id: str) -> Dict[str, Any]:
        """执行或恢复一个群组 (断点恢复: 已完成节点复用结果)。

        用显式 work-loop 而非单次遍历: 失败节点可重新入队重试,
        直到成功 / 耗尽重试 / 触发依赖子树回滚。
        """
        if not self._nodes or self._current_group != group_id:
            self._load_or_init(group_id)
        order = self._topo_order()
        summary = {"done": 0, "failed": 0, "rolled_back": 0, "skipped": 0}

        # work queue: 待处理节点 (拓扑序)。用 index 游标 + 重试栈。
        pending = list(order)   # 待处理
        retry_stack: List[str] = []   # 失败待重试节点

        while pending or retry_stack:
            # 优先重试栈 (保持 LIFO, 失败节点优先重试)
            nid = retry_stack.pop() if retry_stack else pending.pop(0)
            node = self._nodes[nid]
            if node.state == NodeState.DONE:
                summary["skipped"] += 1
                continue
            # 依赖未就绪 (上游失败) => 本节点自身回滚, 不入队重试
            if not self._deps_ready(nid):
                self._rollback_subtree(nid, reason="dependency not ready",
                                        mark_root=True)
                summary["rolled_back"] += 1
                continue
            node.state = NodeState.RUNNING
            node.attempts += 1
            node.started_at = time.time()
            self._persist()
            try:
                node.result = self._executor(node, self._blackboard)
                node.state = NodeState.DONE
                node.error = None
                self._blackboard[nid] = node.result
            except Exception as e:  # noqa: BLE001 - 节点失败 -> 重试/回滚
                node.error = str(e)
                if node.attempts < node.max_attempts:
                    node.state = NodeState.PENDING
                    summary["failed"] += 1
                    self._persist()
                    self._backoff(node.attempts)
                    retry_stack.append(nid)   # 重新入队重试
                    node.finished_at = time.time()
                    continue
                node.state = NodeState.FAILED
                self._rollback_subtree(nid, reason=f"node failed: {e}")
                summary["rolled_back"] += 1
            node.finished_at = time.time()
            self._persist()
        self._persist()
        summary["done"] = sum(1 for n in self._nodes.values()
                              if n.state == NodeState.DONE)
        return {"group_id": group_id, **summary}

    def _deps_ready(self, nid: str) -> bool:
        node = self._nodes[nid]
        return all(self._nodes[d].state == NodeState.DONE for d in node.deps)

    def _rollback_subtree(self, nid: str, reason: str,
                          mark_root: bool = False) -> None:
        """回滚以 nid 为根的依赖子树。

        两种语义:
        - ``mark_root=False`` (节点耗尽重试): 根节点保持当前状态 (FAILED,
          保留失败事实), 只有**依赖它的下游**节点才标记 ROLLED_BACK;
        - ``mark_root=True`` (依赖未就绪): 根节点自身即被标记 ROLLED_BACK
          (它因上游失败不可执行), 其下游一并回滚。
        """
        if mark_root:
            node = self._nodes.get(nid)
            if node is not None and node.state != NodeState.ROLLED_BACK:
                node.state = NodeState.ROLLED_BACK
                node.error = reason
        failed_set = {nid}
        # 找到依赖 failed 节点的下游
        changed = True
        while changed:
            changed = False
            for other in self._nodes.values():
                if other.state == NodeState.DONE and any(
                        d in failed_set for d in other.deps):
                    other.state = NodeState.ROLLED_BACK
                    other.error = reason
                    failed_set.add(other.node_id)
                    changed = True
        self._persist()

    def _backoff(self, attempt: int) -> None:
        """指数退避: base * 2^(attempt-1), 封顶 max。"""
        delay = min(self._backoff_max,
                    self._backoff_base * (2 ** max(0, attempt - 1)))
        if delay > 0:
            time.sleep(min(delay, 5.0))  # 测试/交互不长时间阻塞

    def _topo_order(self) -> List[str]:
        """Kahn 拓扑排序, 保证执行顺序满足依赖。"""
        in_deg: Dict[str, int] = {}
        for nid, node in self._nodes.items():
            in_deg[nid] = len([d for d in node.deps if d in self._nodes])
        ready = [nid for nid, deg in in_deg.items() if deg == 0]
        order: List[str] = []
        while ready:
            ready.sort()
            nid = ready.pop(0)
            order.append(nid)
            for other in self._nodes.values():
                if nid in other.deps and other.node_id in in_deg:
                    in_deg[other.node_id] -= 1
                    if in_deg[other.node_id] == 0:
                        ready.append(other.node_id)
        if len(order) != len(self._nodes):
            raise ValueError("cyclic dependency in plan")
        return order

    # ---------------------------------------------------------- 持久化
    def _persist(self) -> None:
        if not self._current_group:
            return
        data = {
            "group_id": self._current_group,
            "nodes": {nid: n.to_dict() for nid, n in self._nodes.items()},
            "blackboard": self._blackboard,
            "updated_at": time.time(),
        }
        self._store.save(self._current_group, data)

    def _load_or_init(self, group_id: str) -> None:
        data = self._store.load(group_id)
        if data:
            self._nodes = {nid: OrchestrationNode.from_dict(nd)
                           for nid, nd in data.get("nodes", {}).items()}
            self._blackboard = dict(data.get("blackboard", {}))
            self._current_group = group_id
        else:
            self._current_group = group_id
            self._nodes = {}
            self._blackboard = {}

    def resume(self, group_id: str) -> Dict[str, Any]:
        """从持久化状态恢复执行 (断点恢复)。"""
        self._load_or_init(group_id)
        return self.execute(group_id)

    def state(self, group_id: str) -> Dict[str, Any]:
        """查看群组状态快照 (供 UI/审计)。"""
        self._load_or_init(group_id)
        return {
            "group_id": group_id,
            "nodes": {nid: n.to_dict() for nid, n in self._nodes.items()},
            "blackboard": dict(self._blackboard),
        }

    def list_groups(self) -> List[str]:
        return self._store.list_groups()
