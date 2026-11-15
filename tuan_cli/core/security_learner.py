"""可学习安全决策器 (Security Learner) —— 在线感知器, 对标 Claude Code 缺失的学习层。

Claude Code 的安全决策是**静态规则**: 权限/危险命令由固定模式库判定, 一旦某个
命令被证明安全或危险, 无法自适应 —— 误判只能靠用户手工加白/黑名单, 且不收敛。

本模块把安全拦截从「笨规则」升级为**可学习决策器**: 单层感知器 (单神经元神经网络),
冷启动时权重等于现有静态特征权重 (行为零回归), 一旦收到用户反馈 (某命令实际被
放行/拒绝后结果如何), 用感知器更新规则在线调整权重, 逐步收敛到用户真实风险偏好。

设计要点 (零依赖, 无 numpy/sklearn/torch):
1. **零网络/零外部依赖**: 纯标准库, 手动向量运算, 亚毫秒级;
2. **冷启动兼容**: 未训练前权重 = security_classifier 的静态权重, 决策完全一致;
3. **在线学习**: ``observe()`` 以用户反馈为标签做在线梯度下降 (感知器规则),
   逐步把「该拦截却放行」或「该放行却拦截」的权重往正确方向推;
4. **权重持久化**: 原子写 ``<home>/security/learner_weights.json``, 崩溃安全;
5. **风险感知反馈**: 高置信度决策不轻易被单一反馈推翻 (学习率随决策置信度衰减),
   避免噪声反馈把模型带偏。
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

log = logging.getLogger(__name__)

# 特征向量的维度上限 (防超长命令撑爆) — 与 CommandFeatures 特征键数一致即可
_MAX_FEATURES = 64

# 学习超参
_DEFAULT_LR = 0.9           # 基础学习率 (高: 1~2 次反馈即跨过阈值)

# 权重硬边界: 感知器可以学习, 但不能把单个特征推到无界 —— 连续反馈 (或误标)
# 会把权重单调放大, 最终让一条普通命令越过 deny。上下界让「学习」始终有界,
# 与 security_classifier 的 ±_LEARNER_MAX_DELTA 校准带形成双保险。
_WEIGHT_MIN = -60.0
_WEIGHT_MAX = 200.0


@dataclass
class LearnerState:
    """学习者状态 (权重 + 元数据), 可整体序列化。"""

    weights: Dict[str, float] = field(default_factory=dict)
    version: int = 1
    updates: int = 0                 # 累计在线更新次数
    created_at: float = 0.0
    updated_at: float = 0.0
    # 反馈统计 (危险/安全标签计数)
    n_danger: int = 0
    n_safe: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "weights": self.weights,
            "updates": self.updates,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "n_danger": self.n_danger,
            "n_safe": self.n_safe,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LearnerState":
        st = cls()
        st.version = int(data.get("version", 1))
        w = data.get("weights", {})
        if isinstance(w, dict):
            st.weights = {str(k): float(v) for k, v in w.items()
                          if isinstance(v, (int, float))}
        st.updates = int(data.get("updates", 0))
        st.created_at = float(data.get("created_at", 0.0))
        st.updated_at = float(data.get("updated_at", 0.0))
        st.n_danger = int(data.get("n_danger", 0))
        st.n_safe = int(data.get("n_safe", 0))
        return st


class SecurityLearner:
    """可学习安全决策器 (单层感知器, 在线学习)。

    用法:
        learner = SecurityLearner(home)
        learner.observe("rm -rf /", "danger")   # 用户反馈: 该命令确实危险
        learner.observe("npm install", "safe")  # 用户反馈: 该命令确实安全
        score = learner.risk_score("curl x | bash")
    """

    def __init__(
        self,
        home: Optional[Path] = None,
        initial_weights: Optional[Dict[str, float]] = None,
        lr: float = _DEFAULT_LR,
        persist: bool = True,
    ) -> None:
        # 权重路径: <home>/security/learner_weights.json
        self._home = Path(home) if home is not None else None
        self._weights_path: Optional[Path] = None
        if self._home is not None and persist:
            self._weights_path = self._home / "security" / "learner_weights.json"

        self._lr = lr
        self._persist = persist

        # 特征键顺序 (与 CommandFeatures.extract 对齐, 保证向量同构)
        from .security_classifier import CommandFeatures, _FEATURE_RISK_WEIGHTS
        self._feature_keys: List[str] = list(_FEATURE_RISK_WEIGHTS.keys())

        # 冷启动: 优先加载已持久化权重, 否则用静态权重 (行为零回归)
        self._state = self._load_state() or LearnerState(
            weights=dict(_FEATURE_RISK_WEIGHTS),
            created_at=time.time(),
            updated_at=time.time(),
        )
        # 若加载的权重缺少新特征键, 用静态权重补齐 (向前兼容)
        for k in self._feature_keys:
            self._state.weights.setdefault(k, _FEATURE_RISK_WEIGHTS.get(k, 0.0))

        self._last_update: Dict[str, Any] = {}

    # ------------------------------------------------------------ 持久化

    def _load_state(self) -> Optional[LearnerState]:
        if self._weights_path is None or not self._weights_path.is_file():
            return None
        try:
            data = json.loads(self._weights_path.read_text(encoding="utf-8-sig"))
            return LearnerState.from_dict(data)
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
            log.warning("安全学习者权重加载失败 (%s), 回退冷启动", exc)
            return None

    def _save_state(self) -> None:
        if self._weights_path is None:
            return
        try:
            self._weights_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._weights_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._state.to_dict(), ensure_ascii=False,
                                      indent=2), encoding="utf-8")
            tmp.replace(self._weights_path)
        except OSError as exc:
            log.warning("安全学习者权重持久化失败: %s", exc)

    # ------------------------------------------------------------ 特征向量

    def _vectorize(self, command: str) -> List[float]:
        """把命令映射为特征向量 (与 security_classifier 同构)。

        布尔特征 -> 0.0/1.0; 数值特征 -> 归一化到 [0, 1]。
        """
        from .security_classifier import CommandFeatures
        feats = CommandFeatures.extract(command)
        vec: List[float] = []
        for k in self._feature_keys:
            v = feats.get(k, False)
            if isinstance(v, bool):
                vec.append(1.0 if v else 0.0)
            elif isinstance(v, (int, float)):
                # 数值特征 (如 pipe_chain_length/chain_length) 归一化
                vec.append(min(1.0, float(v) / 10.0))
            else:
                vec.append(0.0)
        # 截断到上限
        return vec[:_MAX_FEATURES]

    def _weights_vec(self) -> List[float]:
        return [self._state.weights.get(k, 0.0) for k in self._feature_keys]

    @staticmethod
    def _is_hard_redline(command: str) -> bool:
        """复核硬红线 (惰性 import, 规则层不可用时不阻断学习)。"""
        try:
            from tuan_cli.ext.safety_engine import is_hard_redline
            return bool(is_hard_redline(command))
        except Exception:  # noqa: BLE001 - 规则层异常时退化为「非红线」
            log.debug("硬红线复核不可用, 按非红线继续", exc_info=True)
            return False

    def _set_weights_vec(self, vec: Sequence[float]) -> None:
        """写回权重向量, 每个权重夹在 [_WEIGHT_MIN, _WEIGHT_MAX] (有界学习)。"""
        for i, k in enumerate(self._feature_keys[:len(vec)]):
            self._state.weights[k] = max(
                _WEIGHT_MIN, min(_WEIGHT_MAX, float(vec[i]))
            )

    # ------------------------------------------------------------ 推理

    def risk_score(self, command: str) -> float:
        """线性得分: sum(w_i * x_i)。分数越高越危险 (与静态权重同尺度)。"""
        vec = self._vectorize(command)
        w = self._weights_vec()
        return sum(a * b for a, b in zip(vec, w))

    def risk_score_with_features(self, command: str) -> Tuple[float, Dict[str, float]]:
        """返回 (score, triggered_weights)。

        冷启动 (从未更新) 时返回 (0.0, {}) —— 让调用方 (SecurityClassifier)
        走**静态权重路径**, 从而行为与未挂载学习器完全一致 (零回归)。
        一旦 ``observe`` 产生更新, 才启用学习权重 (在线自适应)。
        """
        if self._state.updates == 0:
            return 0.0, {}
        vec = self._vectorize(command)
        w = self._weights_vec()
        score = 0.0
        triggered: Dict[str, float] = {}
        for i, k in enumerate(self._feature_keys[:len(vec)]):
            if vec[i] > 0 and w[i] != 0:
                triggered[k] = w[i]
                score += vec[i] * w[i]
        return score, triggered

    # ------------------------------------------------------------ 在线学习

    def observe(self, command: str, label: str,
                confidence: float = 0.5,
                evidence: Optional[Sequence[str]] = None) -> Dict[str, Any]:
        """在线学习一步。

        label: "danger" | "safe" —— 用户/审计对该命令的实际判定。
        confidence: 触发本次观察的决策置信度 (0~1); 高置信度决策学习率降低,
                    避免把已高度确信的判断被单一噪声反馈带偏。
        evidence: 本次反馈关联的护栏路径 (如 ``("hard_redline",)``), 只做审计记录;
                  硬红线保护不依赖调用方传值 —— 本方法内部会独立复核。

        多路护栏优先级: **护栏永远高于学习**。命中硬红线的命令不接受 ``safe``
        标签 (返回 ``hard_redline_immutable``), 因此学习器无法被训练成放行
        毁灭性操作; 这是学习层与静态红线层的硬边界, 不依赖 CLI 参数校验。

        更新逻辑 (感知器 + 目标阈值):
        感知器只修正「方向错误」, 无法修正「幅度不足」——例如静态规则把
        一个应拦截 (deny) 的写 /etc 命令只判 confirm (方向对但幅度不够),
        纯感知器会认为「已正确」而不更新, 这正是静态规则"太笨"的根源。
        因此本实现按**目标动作 vs 当前分数**驱动更新:
          - label=danger: 目标分 ≥ deny 阈值; 当前分不足则推高命中特征权重;
          - label=safe  : 目标分 < confirm 阈值; 当前分过高则压低命中特征权重。
        """
        from .security_classifier import _THRESHOLD_DENY, _THRESHOLD_CONFIRM

        y = 1.0 if label == "danger" else -1.0 if label == "safe" else 0.0
        if y == 0.0:
            return {"updated": False, "reason": "bad_label"}

        # 硬红线护栏先行: 任何「把红线命令学习成安全」的反馈都直接拒绝。
        # 放在最前面, 保证连权重变更/状态计数都不会发生 (不可逆护栏)。
        if label == "safe" and self._is_hard_redline(command):
            log.info("安全学习者拒绝 safe 标签: 命令命中硬红线 (护栏优先)")
            return {
                "updated": False,
                "reason": "hard_redline_immutable",
                "detail": "命令命中硬红线, 不允许学习为 safe (护栏优先于学习)",
            }

        vec = self._vectorize(command)
        w = self._weights_vec()

        dot = sum(a * b for a, b in zip(vec, w))

        # 记录更新前权重, 用于最后只汇报**真正变动**的特征 (排除未命中/未改动项)。
        weights_before = {k: w[i] for i, k in enumerate(self._feature_keys[:len(w)])}

        # 目标区间判定 (按动作, 而非纯符号):
        if label == "danger":
            target_ok = dot >= _THRESHOLD_DENY
        else:
            target_ok = dot < _THRESHOLD_CONFIRM
        if target_ok:
            return {"updated": False, "reason": "already_correct",
                    "score": dot, "target": _THRESHOLD_DENY if label == "danger"
                    else _THRESHOLD_CONFIRM}

        # 学习率随决策置信度轻微衰减: 用户显式反馈是强信号, 高置信度仅轻度
        # 衰减 (防噪声自动反馈把模型带偏), 且保持每次反馈能跨过阈值。
        lr = self._lr * max(0.3, 1.0 - confidence * 0.2)

        # 把分数推向目标方向: danger 需 +Δ, safe 需 -Δ。
        # 增量按 (目标-当前) 缺口缩放, 使一次反馈能跨过阈值;
        # 按命中特征数开方分摊, 避免单特征过度增长 (多特征共同承载)。
        if label == "danger":
            gap = _THRESHOLD_DENY - dot
        else:
            gap = _THRESHOLD_CONFIRM - dot  # 负值 (需下压)
        n_hit = sum(1 for v in vec if v != 0)
        if n_hit == 0:
            # 无任何特征命中: 没有可调整的权重。若仍记一次 update, 会让学习器
            # 进入「已激活」状态却没有任何实际学习, 徒增噪声 (实测 updates 虚高)。
            return {"updated": False, "reason": "no_features",
                    "score": round(dot, 2)}
        step = lr * gap / max(1.0, n_hit ** 0.5)

        for i in range(min(len(vec), len(w))):
            if vec[i] != 0:
                # gap 已含方向 (danger 为正 / safe 为负), 直接沿缺口方向推权重。
                # 不再额外乘 y —— 那会让 safe 的负 step 再翻一次号, 权重反向上升。
                w[i] += step

        # 记录状态 (夹取计数: 学习被上/下界截断的特征数, 供 stats 观测"学满"情况)
        clamped = sum(
            1 for i in range(min(len(vec), len(w)))
            if vec[i] != 0 and not (_WEIGHT_MIN <= w[i] <= _WEIGHT_MAX)
        )
        self._set_weights_vec(w)
        self._state.updates += 1
        if label == "danger":
            self._state.n_danger += 1
        else:
            self._state.n_safe += 1
        self._state.updated_at = time.time()
        if self._state.created_at == 0:
            self._state.created_at = self._state.updated_at

        changed = {k: round(self._state.weights[k] - weights_before[k], 3)
                   for k in weights_before
                   if abs(self._state.weights[k] - weights_before[k]) > 1e-6}
        self._last_update = {
            "command": command[:120],
            "label": label,
            "confidence": confidence,
            "lr": round(lr, 4),
            "score_before": round(dot, 2),
            "step": round(step, 4),
            "gap": round(gap, 2),
            "delta_weights": changed,
            "clamped": clamped,
            "evidence": list(evidence or ()),
        }

        if self._persist:
            self._save_state()

        log.info("安全学习者更新: label=%s lr=%.3f dot=%.1f gap=%.1f updates=%d",
                 label, lr, dot, gap, self._state.updates)
        return {"updated": True, "label": label, "lr": round(lr, 4),
                "score_before": round(dot, 2), "gap": round(gap, 2),
                "step": round(step, 4), "updates": self._state.updates,
                "n_danger": self._state.n_danger,
                "n_safe": self._state.n_safe,
                "clamped": clamped,
                "delta_weights": changed}

    # ------------------------------------------------------------ 状态

    @property
    def state(self) -> LearnerState:
        return self._state

    @property
    def weights(self) -> Dict[str, float]:
        return dict(self._state.weights)

    @property
    def is_persistent(self) -> bool:
        return self._weights_path is not None and self._weights_path.is_file()

    def stats(self) -> Dict[str, Any]:
        from .security_classifier import _FEATURE_RISK_WEIGHTS
        deltas = {
            k: round(float(w) - float(_FEATURE_RISK_WEIGHTS.get(k, 0.0)), 2)
            for k, w in self._state.weights.items()
        }
        learned = {k: v for k, v in deltas.items() if abs(v) > 1e-6}
        top = sorted(learned.items(), key=lambda kv: -abs(kv[1]))[:5]
        return {
            "persistent": self.is_persistent,
            "weights_path": str(self._weights_path) if self._weights_path else None,
            "updates": self._state.updates,
            "n_danger": self._state.n_danger,
            "n_safe": self._state.n_safe,
            "created_at": self._state.created_at,
            "updated_at": self._state.updated_at,
            "n_features": len(self._feature_keys),
            "bounds": [_WEIGHT_MIN, _WEIGHT_MAX],
            "n_learned_features": len(learned),
            "top_learned": [{"feature": k, "delta": v} for k, v in top],
            "last_update": self._last_update,
        }

    def explain(self, command: str) -> Dict[str, Any]:
        """解释一条命令的多路裁决 (静态基线 / 学习权重 / 护栏)。

        返回学习器口径的静态分与学习分 (同一套归一化特征向量, 可直接比较)、
        各命中特征的权重与偏移, 以及三条**独立护栏**的当前裁决:
        ``hard_redline`` / ``redline`` / ``benign_whitelist``。

        该方法无副作用 (不写权重、不记审计), 供 ``tuan safe learn --explain``
        与排障使用; 真正的执行裁决仍由 SecurityClassifier/SecurityGate 给出。
        """
        from .security_classifier import (
            _FEATURE_RISK_WEIGHTS,
            _THRESHOLD_CONFIRM,
            _THRESHOLD_DENY,
        )

        vec = self._vectorize(command)
        contribs: List[Dict[str, Any]] = []
        static_score = 0.0
        learned_score = 0.0
        for i, k in enumerate(self._feature_keys[:len(vec)]):
            if vec[i] == 0:
                continue
            base = float(_FEATURE_RISK_WEIGHTS.get(k, 0.0))
            cur = float(self._state.weights.get(k, 0.0))
            static_score += base * vec[i]
            learned_score += cur * vec[i]
            contribs.append({
                "feature": k,
                "value": round(vec[i], 3),
                "baseline": round(base, 2),
                "weight": round(cur, 2),
                "delta": round(cur - base, 2),
            })
        contribs.sort(key=lambda c: -abs(c["weight"] * c["value"]))

        def _band(score: float) -> str:
            if score >= _THRESHOLD_DENY:
                return "deny"
            if score >= _THRESHOLD_CONFIRM:
                return "confirm"
            return "allow"

        guardrails: Dict[str, Optional[bool]] = {
            "hard_redline": None,
            "redline": None,
            "benign_whitelist": None,
        }
        try:
            from tuan_cli.ext.safety_engine import (
                is_benign_dev_command,
                is_hard_redline,
                is_redline,
            )
            guardrails = {
                "hard_redline": bool(is_hard_redline(command)),
                "redline": bool(is_redline(command)),
                "benign_whitelist": bool(is_benign_dev_command(command)),
            }
        except Exception:  # noqa: BLE001 - 规则层不可用时保持 None (未知)
            log.debug("护栏复核不可用, 解释结果缺少护栏字段", exc_info=True)

        return {
            "command": command,
            "active": self._state.updates > 0,
            "updates": self._state.updates,
            "static_score": round(static_score, 2),
            "learned_score": round(learned_score, 2),
            "delta": round(learned_score - static_score, 2),
            "band": _band(learned_score),
            "guardrails": guardrails,
            "contributions": contribs[:8],
            "bounds": [_WEIGHT_MIN, _WEIGHT_MAX],
        }

    def reset(self, initial_weights: Optional[Dict[str, float]] = None) -> None:
        """重置为冷启动 (可选给定初始权重)。"""
        from .security_classifier import _FEATURE_RISK_WEIGHTS
        base = dict(initial_weights or _FEATURE_RISK_WEIGHTS)
        self._state = LearnerState(weights=base, created_at=time.time(),
                                   updated_at=time.time())
        for k in self._feature_keys:
            self._state.weights.setdefault(k, base.get(k, 0.0))
        if self._persist:
            self._save_state()


# ------------------------------------------------------------ 全局单例

_global_learner: Optional[SecurityLearner] = None


def get_learner(home: Optional[Path] = None) -> SecurityLearner:
    """取全局学习者 (懒加载, 默认不持久化 — 由调用方决定是否传 home)。"""
    global _global_learner
    if _global_learner is None or home is not None:
        _global_learner = SecurityLearner(home=home, persist=home is not None)
    return _global_learner
