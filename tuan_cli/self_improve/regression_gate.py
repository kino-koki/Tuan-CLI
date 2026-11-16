"""回归验证器 (RegressionGate) —— 改进前后对比, 只接受净改进。

阶段 A「反思性自我进化闭环」的第二环: 对一个改进候选, 在**同一任务集**上
分别跑"基线"与"改进后", 对比多维评分, 判定是否值得接受。

核心语义 (fail-safe):
- 接受条件: 改进后总分 >= 基线总分 且 关键维度 (默认 correctness) 不劣化;
- 任何维度若被显式列为红线维度 (critical_dims) 且劣化 => 一律拒绝 (fail-closed);
- 评分相等视为通过 (不追求虚高);
- 基线缺失/任务集为空 => 保守拒绝 (不凭空接受无对比的改进)。

本模块是纯逻辑 (打分 + 决策), 不执行任务; 任务执行由调用方注入
(run_task 回调), 便于测试与复用。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from .evaluator import EvaluationResult, Evaluator

import logging
log = logging.getLogger(__name__)


@dataclass
class RegressionVerdict:
    """一次回归验证的结论。"""

    accepted: bool
    baseline_total: float
    candidate_total: float
    delta: float
    baseline_dims: Dict[str, float] = field(default_factory=dict)
    candidate_dims: Dict[str, float] = field(default_factory=dict)
    rejected_dims: List[str] = field(default_factory=list)   # 触发拒绝的维度
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "accepted": self.accepted,
            "baseline_total": round(self.baseline_total, 2),
            "candidate_total": round(self.candidate_total, 2),
            "delta": round(self.delta, 2),
            "baseline_dims": {k: round(v, 2) for k, v in self.baseline_dims.items()},
            "candidate_dims": {k: round(v, 2) for k, v in self.candidate_dims.items()},
            "rejected_dims": self.rejected_dims,
            "reason": self.reason,
        }


class RegressionGate:
    """判定改进候选是否值得接受。

    用法::

        gate = RegressionGate(run_task=my_runner, tasks=["T1", "T2"])
        verdict = gate.evaluate(candidate={"apply": apply_fn, "id": "cand-1"})

    其中 run_task(task_id) 返回 artifact (供 Evaluator 评分)。
    candidate.apply() 应把改进应用到环境 (可回滚), candidate.rollback() 反之。
    """

    def __init__(
        self,
        run_task: Callable[[str], Dict[str, Any]],
        tasks: List[str],
        evaluator: Optional[Evaluator] = None,
        critical_dims: Optional[List[str]] = None,
    ) -> None:
        self._run_task = run_task
        self._tasks = list(tasks)
        self._evaluator = evaluator or Evaluator()
        # 默认红线维度: 正确性不可劣化; 可扩展
        self._critical_dims = critical_dims or ["correctness"]

    def _score_task(self, task_id: str) -> EvaluationResult:
        artifact = self._run_task(task_id) or {"ok": False, "error": "empty artifact"}
        return self._evaluator.evaluate(task_id, artifact)

    def baseline(self) -> Dict[str, EvaluationResult]:
        """跑基线任务集 (不应用候选)。"""
        return {t: self._score_task(t) for t in self._tasks}

    def evaluate(self, candidate: Dict[str, Any]) -> RegressionVerdict:
        """评估候选: 先测基线, 再应用候选测改进, 对比。失败时回滚。"""
        if not self._tasks:
            return RegressionVerdict(
                accepted=False, baseline_total=0, candidate_total=0, delta=0,
                reason="no tasks to compare", rejected_dims=[])

        # 1) 基线
        base = self.baseline()
        base_total = sum(r.total_score for r in base.values()) / len(base)
        base_dims = self._aggregate_dims(base)

        # 2) 应用候选 (失败则回滚, 保守拒绝)
        apply_fn = candidate.get("apply")
        if not callable(apply_fn):
            return RegressionVerdict(
                accepted=False, baseline_total=base_total,
                candidate_total=base_total, delta=0,
                reason="candidate has no apply callable", rejected_dims=[])

        applied = False
        try:
            apply_fn()
            applied = True
        except Exception as e:  # noqa: BLE001 - 候选应用失败即回滚拒绝
            return self._reject(base_total, base_dims, reason=f"apply failed: {e}")

        # 3) 改进后测分
        cand_total = 0.0
        cand_dims: Dict[str, float] = {}
        rejected: List[str] = []
        try:
            cand = {t: self._score_task(t) for t in self._tasks}
            cand_total = sum(r.total_score for r in cand.values()) / len(cand)
            cand_dims = self._aggregate_dims(cand)
        except Exception as e:  # noqa: BLE001
            return self._reject(base_total, base_dims, reason=f"post-apply scoring failed: {e}")
        finally:
            if applied:
                rollback = candidate.get("rollback")
                if callable(rollback):
                    try:
                        rollback()
                    except Exception as exc:  # noqa: BLE001 - 回滚失败不掩盖判定
                        log.warning("RegressionGate.evaluate(): 非致命异常已忽略(设计内降级, 不改控制流): %s", exc)
                        pass

        # 4) 判定
        delta = cand_total - base_total
        for dim in self._critical_dims:
            b = base_dims.get(dim, 0.0)
            c = cand_dims.get(dim, 0.0)
            if c < b - 1e-6:   # 红线维度劣化 => 拒绝
                rejected.append(dim)
        if rejected:
            return RegressionVerdict(
                accepted=False, baseline_total=base_total, candidate_total=cand_total,
                delta=delta, baseline_dims=base_dims, candidate_dims=cand_dims,
                rejected_dims=rejected,
                reason=f"critical dims regressed: {', '.join(rejected)}")
        if cand_total >= base_total - 1e-6:
            return RegressionVerdict(
                accepted=True, baseline_total=base_total, candidate_total=cand_total,
                delta=delta, baseline_dims=base_dims, candidate_dims=cand_dims,
                rejected_dims=[], reason="net improvement or no regression")
        return RegressionVerdict(
            accepted=False, baseline_total=base_total, candidate_total=cand_total,
            delta=delta, baseline_dims=base_dims, candidate_dims=cand_dims,
            rejected_dims=[], reason="candidate scored lower")

    def _aggregate_dims(self, results: Dict[str, EvaluationResult]) -> Dict[str, float]:
        """跨任务聚合各维度均值 (用于红线判定)。"""
        agg: Dict[str, List[float]] = {}
        for r in results.values():
            for dim, score in r.dims.items():
                agg.setdefault(dim, []).append(score)
        return {k: sum(v) / len(v) for k, v in agg.items()}

    def _reject(self, base_total: float, base_dims: Dict[str, float],
                reason: str) -> RegressionVerdict:
        return RegressionVerdict(
            accepted=False, baseline_total=base_total, candidate_total=base_total,
            delta=0.0, baseline_dims=base_dims, candidate_dims=base_dims,
            rejected_dims=[], reason=reason)
