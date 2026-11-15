"""Agent-of-Agents 团组协调器 (v0.4.2) —— 一个协调者调度多个子代理。

把「Agent-of-Agents」落到团组维度: 一个 **协调者 (coordinator)** 把目标拆成
若干**能力标注的子任务 (worker)**, 并行派发给执行者, 强制每条涉及供应商的
路径先通过 :class:`~tuan_cli.core.team_security.TeamGroupSecurity` 的加固
验证 (验签 + 防重放 + 时段 + 次数), 再把结果带来源标注聚合回协调者。

与 :mod:`subagents` 的区别:
- ``subagents`` 是**单 Agent 内部**的并行子代理 (共享内核工具表, 跑隔离上下文);
- 本模块是**团组维度**的协调器: worker 可以映射到团组成员 + 能力, 关键路径
  必须过团组授权, 结果与派发全程进 ``team_audit.jsonl``。

设计不变量:
- **能力路由**: 每个 worker 声明它需要的能力名 (capability name) 与可选
  供应商/模型; 协调者据此路由到对应执行函数。
- **授权前置**: 任何声明了 ``provider`` 的 worker, 派发前必须过
  ``verify_grant_hardened``; 未通过即该 worker fail-closed, 不影响其它。
- **并行 + 隔离**: 用线程池并行; 单 worker 异常被捕获为失败结果, 不拖垮整轮。
- **结果聚合**: 汇总 ``ok``/``failed``/``skipped``, 附来源 (worker_id /
  capability / member), 供上层 (CLI/web/Agent) 直接消费。
- **纯本地**: 协调记录写团组审计, 不上传任何第三方。
"""

from __future__ import annotations

import concurrent.futures
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from .team_security import TeamGroupSecurity

log = logging.getLogger(__name__)

# 默认并行度上限 (worker 数); 协调者一次最多同时派发这么多
DEFAULT_MAX_PARALLEL = 8
# 单 worker 默认超时 (秒)
DEFAULT_WORKER_TIMEOUT = 120.0


class CoordinatorError(Exception):
    """团组协调器失败 (派发/聚合层错误, 与单 worker 失败区分)。"""


# ============================================================ 数据结构


@dataclass
class WorkerSpec:
    """一个待派发的子代理任务 (能力标注)。"""

    worker_id: str
    capability: str  # 能力名 (对齐 AgentCapability.name)
    prompt: str  # 任务描述 (交给执行函数)
    provider: Optional[str] = None  # 若涉及供应商, 派发前强制授权验证
    model: Optional[str] = None
    member: Optional[str] = None  # 目标团组成员 (可选, 用于归属/权限)
    nonce: Optional[str] = None  # 防重放 nonce (涉供应商时推荐)
    meta: Dict[str, Any] = field(default_factory=dict)


@dataclass
class WorkerResult:
    """单个 worker 的执行结果 (带来源标注 + 状态)。"""

    worker_id: str
    capability: str
    status: str  # ok / failed / skipped / timeout
    output: Any = None
    error: str = ""
    member: Optional[str] = None
    provider: Optional[str] = None
    duration_ms: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "worker_id": self.worker_id,
            "capability": self.capability,
            "status": self.status,
            "output": self.output,
            "error": self.error,
            "member": self.member,
            "provider": self.provider,
            "duration_ms": self.duration_ms,
        }


@dataclass
class CoordinatorReport:
    """一次协调派发的聚合报告。"""

    goal: str
    total: int
    ok: int
    failed: int
    skipped: int
    results: List[WorkerResult] = field(default_factory=list)
    started_at: float = 0.0
    duration_ms: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "goal": self.goal,
            "total": self.total,
            "ok": self.ok,
            "failed": self.failed,
            "skipped": self.skipped,
            "duration_ms": self.duration_ms,
            "results": [r.to_dict() for r in self.results],
        }


# ============================================================ 协调器


class TeamAgentCoordinator:
    """团组 Agent-of-Agents 协调器。

    通过 ``register_executor`` 注册「能力 -> 执行函数」的路由表; 执行函数签名
    ``fn(spec: WorkerSpec, ctx: Dict) -> Any``。未注册能力的 worker 会被标记
    ``skipped`` (而非报错), 便于渐进接入。

    涉供应商的 worker 在派发前由 :meth:`_authorize` 过加固验证; 通过后把
    验证结论放进 ``ctx["grant"]`` 传给执行函数。
    """

    def __init__(
        self, security: TeamGroupSecurity,
        max_parallel: int = DEFAULT_MAX_PARALLEL,
        worker_timeout: float = DEFAULT_WORKER_TIMEOUT,
    ) -> None:
        self._sec = security
        self._max_parallel = max(1, int(max_parallel))
        self._timeout = float(worker_timeout)
        self._executors: Dict[str, Callable[[WorkerSpec, Dict[str, Any]], Any]] = {}
        self._lock = threading.RLock()
        # 派发期暂存的授权结论 (worker_id -> grant verdict), 传给执行函数
        self._grant_ctx: Dict[str, Dict[str, Any]] = {}

    # ---------------------------------------------------------- 路由注册

    def register_executor(
        self, capability: str, fn: Callable[[WorkerSpec, Dict[str, Any]], Any],
    ) -> None:
        """注册某能力的执行函数 (重复注册覆盖)。"""
        with self._lock:
            self._executors[capability] = fn

    def registered_capabilities(self) -> List[str]:
        with self._lock:
            return sorted(self._executors.keys())

    # ---------------------------------------------------------- 派发

    def dispatch(self, goal: str, workers: List[WorkerSpec], actor: str = "") -> CoordinatorReport:
        """并行派发 workers, 聚合结果。goal/actor 仅用于审计与报告标注。"""
        if not workers:
            raise CoordinatorError("没有可派发的 worker")
        started = time.time()
        self._sec._store._audit(  # noqa: SLF001
            "coord_dispatch", actor=actor,
            detail={"goal": goal, "workers": [w.worker_id for w in workers]},
        )
        # 先做授权前置 (涉供应商的), 失败的标记 skipped, 不进线程池
        authorized: List[WorkerSpec] = []
        pre_results: Dict[str, WorkerResult] = {}
        for w in workers:
            if w.provider:
                try:
                    grant = self._authorize(w)
                    self._grant_ctx[w.worker_id] = grant
                    authorized.append(w)
                except Exception as exc:  # noqa: BLE001
                    pre_results[w.worker_id] = WorkerResult(
                        worker_id=w.worker_id, capability=w.capability,
                        status="skipped", error=f"授权失败: {exc}",
                        member=w.member, provider=w.provider,
                    )
            else:
                authorized.append(w)

        # 并行执行
        results: List[WorkerResult] = list(pre_results.values())
        if authorized:
            with concurrent.futures.ThreadPoolExecutor(
                max_workers=min(self._max_parallel, len(authorized)),
                thread_name_prefix="tuan-coord",
            ) as pool:
                future_map = {
                    pool.submit(self._run_one, w, actor): w for w in authorized
                }
                for fut in concurrent.futures.as_completed(
                    future_map, timeout=self._timeout * max(1, len(authorized))
                ):
                    results.append(fut.result())

        # 聚合
        ok = sum(1 for r in results if r.status == "ok")
        skipped = sum(1 for r in results if r.status == "skipped")
        failed = len(results) - ok - skipped  # failed + timeout 都算未成功
        report = CoordinatorReport(
            goal=goal, total=len(workers), ok=ok, failed=failed,
            skipped=skipped, results=results,
            started_at=started, duration_ms=int((time.time() - started) * 1000),
        )
        self._sec._store._audit(  # noqa: SLF001
            "coord_report", actor=actor,
            detail={"goal": goal, "ok": ok, "failed": report.failed, "skipped": skipped,
                    "duration_ms": report.duration_ms},
        )
        return report

    def _authorize(self, w: WorkerSpec) -> Dict[str, Any]:
        """涉供应商 worker 的授权前置 (加固版, fail-closed)。"""
        return self._sec.verify_grant_hardened(
            self._resolve_grant_id(w), w.provider, model=w.model, nonce=w.nonce,
        )

    def _resolve_grant_id(self, w: WorkerSpec) -> str:
        """从 worker 解析出要验证的 grant_id (meta.grant_id 优先)。"""
        gid = (w.meta or {}).get("grant_id")
        if not gid:
            raise CoordinatorError(f"worker {w.worker_id} 缺少 meta.grant_id")
        return str(gid)

    def _run_one(self, w: WorkerSpec, actor: str) -> WorkerResult:
        """执行单个 worker (隔离异常 + 超时由线程池整体约束)。"""
        t0 = time.time()
        with self._lock:
            fn = self._executors.get(w.capability)
        if fn is None:
            return WorkerResult(
                worker_id=w.worker_id, capability=w.capability, status="skipped",
                error=f"未注册能力执行器: {w.capability}",
                member=w.member, provider=w.provider,
                duration_ms=int((time.time() - t0) * 1000),
            )
        ctx = {
            "actor": actor,
            "grant": self._grant_ctx.get(w.worker_id),
            "member": w.member,
            "provider": w.provider,
            "model": w.model,
        }
        try:
            out = fn(w, ctx)
            return WorkerResult(
                worker_id=w.worker_id, capability=w.capability, status="ok",
                output=out, member=w.member, provider=w.provider,
                duration_ms=int((time.time() - t0) * 1000),
            )
        except Exception as exc:  # noqa: BLE001
            return WorkerResult(
                worker_id=w.worker_id, capability=w.capability, status="failed",
                error=str(exc), member=w.member, provider=w.provider,
                duration_ms=int((time.time() - t0) * 1000),
            )


# ============================================================ 工厂


def load_team_coordinator(
    security: TeamGroupSecurity,
    capability_registry: Optional[Any] = None,
) -> TeamAgentCoordinator:
    """构造协调器; 若传入 CapabilityRegistry, 自动把有 handler 的能力接进来。

    capability_registry 为可选 (避免硬依赖 capability 模块), 形状只需支持
    ``list() -> [{name, handler, ...}]``。
    """
    coord = TeamAgentCoordinator(security)
    if capability_registry is not None:
        try:
            for name, handler in capability_registry.iter_callables():
                coord.register_executor(
                    name, lambda spec, ctx, _h=handler: _h(
                        {"prompt": spec.prompt, "meta": spec.meta, "ctx": ctx}),
                )
        except Exception as exc:  # noqa: BLE001
            log.debug("从能力注册表接入执行器失败 (不阻断): %s", exc)
    return coord
