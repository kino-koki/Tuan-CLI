"""进化循环驱动 (EvolutionLoop) —— 反思性自我改进的核心调度。

阶段 A「反思性自我进化闭环」的第三环: 串联
    Reflector (抽取经验) → Evaluator (度量) → CandidateGenerator (生成改进候选)
    → RegressionGate (回归验证) → 接受/回滚 → EvolutionLedger (账本落盘)

让青小团具备真正的"从经验中成长"能力: 一次任务结束后, 复盘它的执行经验,
生成改进候选 (如"把慢命令加缓存"、"把重复失败模式沉淀为规则"), 在**同一任务集**
上做回归验证, 只有净改进才接受并落账, 劣化一律回滚 (fail-safe)。

与 distill_loop (蒸馏技能) 的区别:
- distill_loop: 把"一次成功多步任务"沉淀为可复用**技能** (面向用户知识);
- EvolutionLoop: 把"执行表现"沉淀为可复用的**改进** (面向系统自身行为)。
后者是反思性闭环, 前者是知识蒸馏。两者互补。

纯逻辑核心: 不直接执行任务/读 UI, 任务执行与候选生成均由调用方注入回调。
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from .evaluator import EvaluationResult, Evaluator
from .regression_gate import RegressionGate, RegressionVerdict


@dataclass
class EvolutionCandidate:
    """一条改进候选: 应用/回滚 + 元信息。"""

    id: str
    summary: str
    apply: Callable[[], None]
    rollback: Callable[[], None]
    origin: str = "reflector"          # failure | denied | slow | repeated_ok | manual
    meta: Dict[str, Any] = field(default_factory=dict)


@dataclass
class EvolutionRecord:
    """一次进化迭代的完整记录 (写入账本)。"""

    candidate_id: str
    summary: str
    origin: str
    accepted: bool
    baseline_total: float
    candidate_total: float
    delta: float
    reason: str
    ts: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "summary": self.summary,
            "origin": self.origin,
            "accepted": self.accepted,
            "baseline_total": round(self.baseline_total, 2),
            "candidate_total": round(self.candidate_total, 2),
            "delta": round(self.delta, 2),
            "reason": self.reason,
            "ts": round(self.ts, 3),
        }


class EvolutionLedger:
    """进化账本: 每次迭代 append-only 落盘 JSONL, 可回放/审计。"""

    def __init__(self, path: str) -> None:
        self._path = path

    def append(self, record: EvolutionRecord) -> None:
        parent = os.path.dirname(self._path) or "."
        os.makedirs(parent, exist_ok=True)
        # append-only: 追加写, 不覆盖历史
        with open(self._path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record.to_dict(), ensure_ascii=False) + "\n")

    def load(self) -> List[Dict[str, Any]]:
        if not os.path.exists(self._path):
            return []
        records: List[Dict[str, Any]] = []
        with open(self._path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return records

    @property
    def path(self) -> str:
        return self._path


class EvolutionLoop:
    """反思性自我改进调度器。

    一次迭代::

        loop = EvolutionLoop(run_task=runner, tasks=["T1", "T2"],
                             ledger_path="~/.tuan/evolution.jsonl")
        result = loop.iterate(candidate_gen)

    candidate_gen(experiences) -> List[EvolutionCandidate]:
        由 Reflector 抽取的经验生成候选; 若无需改进返回 []。
    """

    def __init__(
        self,
        run_task: Callable[[str], Dict[str, Any]],
        tasks: List[str],
        ledger_path: Optional[str] = None,
        evaluator: Optional[Evaluator] = None,
        critical_dims: Optional[List[str]] = None,
    ) -> None:
        self._run_task = run_task
        self._tasks = list(tasks)
        self._ledger = EvolutionLedger(ledger_path or self._default_ledger_path())
        self._evaluator = evaluator or Evaluator()
        self._critical_dims = critical_dims or ["correctness"]

    @staticmethod
    def _default_ledger_path() -> str:
        home = os.path.expanduser("~")
        return os.path.join(home, ".tuan", "evolution.jsonl")

    @property
    def ledger(self) -> EvolutionLedger:
        return self._ledger

    def iterate(self, candidate_gen: Callable[[List[Any]], List[EvolutionCandidate]],
                experiences: Optional[List[Any]] = None) -> List[EvolutionRecord]:
        """运行一轮进化: 生成候选 → 逐个回归验证 → 接受/回滚 → 落账。

        experiences: 可选, 复盘得到的经验 (缺省为空, 由 candidate_gen 自行决定
        是否基于内部事件流生成候选)。
        """
        candidates = candidate_gen(experiences or [])
        records: List[EvolutionRecord] = []
        for cand in candidates:
            gate = RegressionGate(
                run_task=self._run_task,
                tasks=self._tasks,
                evaluator=self._evaluator,
                critical_dims=self._critical_dims,
            )
            verdict = gate.evaluate({"id": cand.id, "apply": cand.apply, "rollback": cand.rollback})
            record = EvolutionRecord(
                candidate_id=cand.id,
                summary=cand.summary,
                origin=cand.origin,
                accepted=verdict.accepted,
                baseline_total=verdict.baseline_total,
                candidate_total=verdict.candidate_total,
                delta=verdict.delta,
                reason=verdict.reason,
                ts=time.time(),
            )
            # 接受: 已应用且不回滚 (RegressionGate 内部已回滚候选; 此处对接受的
            # 候选需保持应用态 —— 由调用方在 apply 里做持久化, 本循环只记结果)。
            # 拒绝: RegressionGate 已回滚, 无残留。
            if verdict.accepted:
                # 接受的候选应保持应用: 重新 apply 一次 (RegressionGate 为了对比
                # 已 rollback), 失败则降级记录为未接受。
                try:
                    cand.apply()
                except Exception as e:  # noqa: BLE001
                    record.accepted = False
                    record.reason = f"re-apply after acceptance failed: {e}"
            self._ledger.append(record)
            records.append(record)
        return records

    def report(self) -> str:
        """渲染进化摘要 (含接受率与净改进)。"""
        records = self._ledger.load()
        if not records:
            return "(进化账本为空, 尚未运行任何迭代)"
        accepted = [r for r in records if r.get("accepted")]
        deltas = [r.get("delta", 0.0) for r in accepted]
        avg_delta = sum(deltas) / len(deltas) if deltas else 0.0
        lines = [
            f"# 进化摘要 · 共 {len(records)} 次迭代 · 接受 {len(accepted)} 次"
            f" · 接受率 {len(accepted)/len(records)*100:.0f}%",
            f"平均净改进: {avg_delta:+.2f} 分",
            "",
            "| 候选 | 来源 | 结果 | Δ分 | 原因 |",
            "|---|---|---|---|---|",
        ]
        for r in records:
            mark = "✓ 接受" if r.get("accepted") else "✗ 拒绝"
            lines.append(
                f"| {r.get('summary', r.get('candidate_id', ''))[:32]} | "
                f"{r.get('origin', '')} | {mark} | {r.get('delta', 0.0):+.1f} | "
                f"{r.get('reason', '')[:40]} |")
        return "\n".join(lines)
