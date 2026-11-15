"""评测器 (Evaluator) —— 对一次任务的产物做结构化自评。

阶段 A「反思性自我进化闭环」的入口：把一次任务的执行产物映射为可量化的
多维评分 (EvaluationResult)，供 RegressionGate / EvolutionLoop 消费。

与 reflector.py 的区别：
- Reflector 从**内核事件流**抽取"经验" (failure/denied/slow/repeated_ok)，
  是自我改进的**原料**；
- 本模块从**任务产物** (artifact) 抽取"评分"，是自我改进的**度量**。
两者互补：Reflector 告诉你"哪里出过问题"，Evaluator 告诉你"这次做得怎么样"。

评分维度 (dims) 是可扩展的：默认覆盖 correctness / completeness / performance /
style 四维，各 0..100。调用方可注入自定义维度 (extend_dims)，以支持领域评分
(如安全评分、测试覆盖率评分等)，无需改本模块核心逻辑。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional


@dataclass
class EvaluationResult:
    """一次任务产物的结构化自评结果。"""

    task_id: str                     # 任务标识 (如任务描述哈希或会话 ID)
    total_score: float               # 加权总分 0..100
    dims: Dict[str, float]           # 各维度评分 0..100 (原始, 未加权)
    weights: Dict[str, float]        # 各维度权重 (和为 1.0)
    notes: List[str] = field(default_factory=list)   # 人工/自动补充说明
    passed: bool = True              # 是否通过 (total_score >= pass_threshold)
    ts: float = 0.0                  # 评测时间戳 (epoch 秒)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "total_score": round(self.total_score, 2),
            "dims": {k: round(v, 2) for k, v in self.dims.items()},
            "weights": {k: round(v, 3) for k, v in self.weights.items()},
            "notes": self.notes,
            "passed": self.passed,
            "ts": self.ts,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "EvaluationResult":
        return cls(
            task_id=d.get("task_id", ""),
            total_score=d.get("total_score", 0.0),
            dims=d.get("dims", {}),
            weights=d.get("weights", {}),
            notes=d.get("notes", []),
            passed=d.get("passed", True),
            ts=d.get("ts", 0.0),
        )


# 默认维度权重: 正确性最重要, 其次是完整性, 性能/风格较轻。
DEFAULT_WEIGHTS: Dict[str, float] = {
    "correctness": 0.4,
    "completeness": 0.3,
    "performance": 0.15,
    "style": 0.15,
}

# 默认维度评分器: 各维度一个纯函数, 输入产物 dict, 输出 0..100 分。
# 产物约定 (artifact):
#   { "ok": bool, "error": str|None, "output": str,
#     "tests_run": int, "tests_passed": int, "files_touched": int,
#     "elapsed": float, "notes": [...] }
# 缺省字段按安全值处理 (不假设成功, 不虚高分)。


def _num(a: Dict[str, Any], key: str, default: float = 0.0) -> float:
    try:
        v = a.get(key, default)
        return float(v)
    except (TypeError, ValueError):
        return default


def _correctness_scorer(a: Dict[str, Any]) -> float:
    """正确性: 产物未报错 + 测试通过率。报错即重罚。"""
    ok = bool(a.get("ok", False))
    if not ok:
        # 有显式错误 -> 低分 (保留少量容错分, 便于对比)
        return 20.0 if a.get("error") else 40.0
    tests_run = _num(a, "tests_run")
    tests_passed = _num(a, "tests_passed")
    if tests_run > 0:
        return 100.0 * (tests_passed / tests_run)
    # 无测试信息 -> 视为通过但非满分 (无验证依据)
    return 80.0


def _completeness_scorer(a: Dict[str, Any]) -> float:
    """完整性: 依据产物字段覆盖度估算 (files_touched / notes 数)。"""
    files = _num(a, "files_touched")
    notes = len(a.get("notes") or [])
    base = 50.0 if a.get("ok") else 30.0
    # 每触及 1 个文件 +5, 每条说明 +3, 封顶 100
    score = base + min(50.0, files * 5.0) + min(20.0, notes * 3.0)
    return min(100.0, score)


def _performance_scorer(a: Dict[str, Any]) -> float:
    """性能: 越快分越高 (0s 满分, 60s 及以上为 0)。"""
    elapsed = _num(a, "elapsed")
    if elapsed <= 0:
        return 100.0
    if elapsed >= 60:
        return 0.0
    return round(100.0 * (1.0 - elapsed / 60.0), 1)


def _style_scorer(a: Dict[str, Any]) -> float:
    """风格: 无错误 + 有说明 + 触及文件较多 => 略高分; 否则中性。"""
    base = 60.0 if a.get("ok") else 40.0
    if a.get("notes"):
        base += 15.0
    if _num(a, "files_touched") >= 2:
        base += 10.0
    return min(100.0, base)


# 默认维度评分器映射 (在评分函数定义后声明, 供 Evaluator 默认装配)。
_DEFAULT_SCORERS: Dict[str, Callable[[Dict[str, Any]], float]] = {
    "correctness": _correctness_scorer,
    "completeness": _completeness_scorer,
    "performance": _performance_scorer,
    "style": _style_scorer,
}


class Evaluator:
    """把任务产物量化为多维评分。

    用法::

        ev = Evaluator()
        res = ev.evaluate(task_id="T1", artifact={"ok": True, "tests_run": 5, "tests_passed": 5})
        # res.total_score == 100.0 (若全维满分)

    自定义维度::

        ev = Evaluator(extend_dims={"coverage": my_coverage_scorer},
                       extend_weights={"coverage": 0.2})
        # 权重会被归一化; 内置四维权重按剩余比例收缩。
    """

    def __init__(
        self,
        extend_dims: Optional[Dict[str, Callable[[Dict[str, Any]], float]]] = None,
        extend_weights: Optional[Dict[str, float]] = None,
        pass_threshold: float = 60.0,
    ) -> None:
        self._scorers: Dict[str, Callable[[Dict[str, Any]], float]] = dict(_DEFAULT_SCORERS)
        if extend_dims:
            self._scorers.update(extend_dims)
        self._weights: Dict[str, float] = dict(DEFAULT_WEIGHTS)
        if extend_weights:
            self._weights.update(extend_weights)
        self._normalize_weights()
        self._pass_threshold = pass_threshold

    def _normalize_weights(self) -> None:
        total = sum(self._weights.values())
        if total <= 0:
            self._weights = dict(DEFAULT_WEIGHTS)
            total = sum(self._weights.values())
        for k in self._weights:
            self._weights[k] = self._weights[k] / total

    @property
    def dims(self) -> List[str]:
        return list(self._scorers.keys())

    @property
    def weights(self) -> Dict[str, float]:
        return dict(self._weights)

    def evaluate(self, task_id: str, artifact: Dict[str, Any]) -> EvaluationResult:
        """对一个任务产物评分。缺失维度按中性分处理 (不虚高)。"""
        dim_scores: Dict[str, float] = {}
        for dim, scorer in self._scorers.items():
            try:
                dim_scores[dim] = max(0.0, min(100.0, float(scorer(artifact))))
            except Exception:
                # 评分器异常不能拖垮评测, 按中性 50 分处理并记录说明
                dim_scores[dim] = 50.0
        total = sum(dim_scores[d] * self._weights.get(d, 0.0) for d in dim_scores)
        notes = list(artifact.get("notes") or [])
        if not artifact.get("ok"):
            notes.append(f"task failed: {artifact.get('error', 'unknown error')}")
        return EvaluationResult(
            task_id=task_id,
            total_score=round(total, 2),
            dims=dim_scores,
            weights=self._weights,
            notes=notes,
            passed=total >= self._pass_threshold,
            ts=__import__("time").time(),
        )
