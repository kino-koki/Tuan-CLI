"""risk_vector.py —— 命令风险的多维向量评估 (安全系统 v0.4 第一层)。

背景: 此前安全引擎输出的是**单一分值** (none→critical)。单分有两个问题:
  1. 无法回答"这条命令到底危险在哪一类" —— 删文件和偷凭据都是 critical, 但处置完全不同;
  2. 无法据此选择**执行域** (宿主 / 进程沙箱 / 微 VM) —— 决策需要知道风险构成而非总分。

本模块在既有引擎 (safety_engine 的模式库/归一化/红线判定) **之上**工作, 不重复检测:
  - 复用 ``_normalize`` 做混淆还原 (Base64/ANSI-C/解释器内联/全角…), 避免被变体绕过;
  - 六维信号 (文件系统 / 网络 / 进程 / 凭据 / 数据流 / 混淆) 各 0-10 分;
  - 加权综合分, 权重可由配置覆盖 (``security.risk.weights``)。

分级语义 (供 sandbox.decide_execution_tier 消费):
    0-2  safe      宿主直跑
    2-4  low       宿主直跑 + 记审计
    4-6  medium    建议 L1 (进程级沙箱) / 需确认
    6-8  high      强制 L2 (微 VM) + 详细审批
    8-10 critical  默认拒绝 (硬红线另有独立拦截)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

# 各维度的检测信号 (在**归一化后**的命令文本上匹配; 小写)
_FS_SIGNALS = (
    (r"\brm\b[^|;&]*\s-[a-z]*[rf]", 8.0),          # 递归/强制删除
    (r"\b(mkfs|format|diskpart)\b", 10.0),          # 文件系统级抹除
    (r"\bdd\b[^|;&]*of=", 9.0),                     # 直接写设备
    (r"\b(shutdown|reboot|halt|poweroff)\b", 6.0),  # 关机
    (r"[>|]\s*/(?:etc|usr|bin|sbin|boot)", 8.0),    # 写系统路径
    (r"\bchmod\b[^|;&]*777|\bchown\b[^|;&]*root", 5.0),
)
_NET_SIGNALS = (
    (r"\b(curl|wget|nc|ncat|netcat|telnet|ftp|ssh|scp)\b", 6.0),
    (r"\b(dig|nslookup|host)\b", 3.0),
    (r"\bping\b", 2.0),
    (r"--(upload-file|data|form)\b", 5.0),          # curl 外发数据
)
_PROC_SIGNALS = (
    (r"\b(kill|pkill|killall)\b", 5.0),
    (r"\b(nohup|disown|setsid)\b", 3.0),
    (r"&\s*$", 2.0),                                # 后台执行
    (r"\b(sudo|su|doas)\b", 6.0),                   # 提权
    (r"\b(chmod|\+s|setuid)\b", 4.0),
)
_CRED_SIGNALS = (
    (r"~?/\.ssh|id_rsa|id_ed25519|authorized_keys", 9.0),
    (r"\.env\b|\.npmrc|\.pypirc|credentials\b", 7.0),
    (r"~?/\.aws|\.config/gcloud|\.kube/config", 9.0),
    (r"\b(password|passwd|shadow|token|api[_-]?key|secret)\b", 6.0),
    (r"\b(export [A-Z_]*(KEY|TOKEN|SECRET|PASSWORD))\b", 7.0),
)
_FLOW_SIGNALS = (
    (r"\|\s*(sh|bash|zsh|python|perl|node)\b", 9.0),   # 管道进解释器
    (r">\s*/dev/", 6.0),                                # 写设备
    (r"\b(tea|nc)\b[^|;&]*\|", 5.0),
    (r"\b(scp|rsync|curl|wget)\b[^|;&]*(--upload|-T|-F|-d)", 7.0),  # 上传
    (r">>?", 2.0),                                      # 重定向
)
_OBF_SIGNALS = (
    (r"\bbase64\b", 6.0),
    (r"\b(eval|exec)\b", 6.0),
    (r"-e\b|-[ec]\b.*\bpopen|os\.system|subprocess", 5.0),
    (r"\b(printf|echo)\b[^|;&]*\\x[0-9a-f]{2}", 6.0),   # 十六进制载荷
    (r"\$\(.*\$\(", 5.0),                               # 嵌套命令替换
    (r"\bxargs\b", 4.0),
)

DEFAULT_WEIGHTS: Dict[str, float] = {
    "credential": 0.25,
    "data_flow": 0.20,
    "filesystem": 0.15,
    "process": 0.15,
    "network": 0.10,
    "obfuscation": 0.10,
}


def _signal_score(text: str, signals) -> float:
    """一组信号的最高命中分 (取 max 而非累加 —— 同类多信号不重复放大)。"""
    best = 0.0
    for pat, weight in signals:
        try:
            if re.search(pat, text, re.IGNORECASE):
                best = max(best, weight)
        except re.error:  # noqa: BLE001
            continue
    return best


@dataclass
class RiskVector:
    """六维风险向量 (各维 0-10)。"""

    filesystem: float = 0.0
    network: float = 0.0
    process: float = 0.0
    credential: float = 0.0
    data_flow: float = 0.0
    obfuscation: float = 0.0
    weights: Dict[str, float] = field(default_factory=lambda: dict(DEFAULT_WEIGHTS))

    engine_floor: float = 0.0
    """引擎判定下限: SafetyEngine 的模式库远比信号表全面 (2310 条对抗载荷沉淀),
    不能让信号表把引擎已经判为 critical/high 的命令拉低。composite() 会取两者较大值。"""

    def composite(self) -> float:
        """综合分 (0-10): 加权均值与引擎判定下限取较大者。

        只用加权均值有个结构性缺陷 —— 单一维度顶格 (如纯凭据窃取 10 分) 最多只能
        贡献 10*0.25=2.5, 会让 `rm -rf /` 这种"只命中一类但极危险"的命令被严重低估。
        """
        total = 0.0
        for name, w in self.weights.items():
            total += getattr(self, name, 0.0) * float(w)
        return round(min(10.0, max(0.0, total, self.engine_floor)), 1)

    def level(self) -> str:
        """综合分 → 分级 (safe/low/medium/high/critical)。"""
        c = self.composite()
        if c >= 8: return "critical"
        if c >= 6: return "high"
        if c >= 4: return "medium"
        if c >= 2: return "low"
        return "safe"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "filesystem": self.filesystem, "network": self.network,
            "process": self.process, "credential": self.credential,
            "data_flow": self.data_flow, "obfuscation": self.obfuscation,
            "composite": self.composite(), "level": self.level(),
        }


def assess(command: str, weights: Optional[Dict[str, float]] = None,
           safety_score: Optional[Dict[str, Any]] = None) -> RiskVector:
    """对一条命令做多维风险评估。

    command: **原始**命令文本 (内部会先走既有引擎的 ``_normalize`` 做混淆还原,
             再在归一化文本上匹配信号 —— 与红线判定同源, 不给变体绕过留口子)。
    safety_score: 可选传入 SafetyEngine.score() 的结果, 用于吸收其 blast_radius
             (影响半径里有文件/服务/数据命中时, 相应维度保底抬分)。
    """
    from .safety_normalize import _normalize

    raw = str(command or "")
    norm = ""
    try:
        norm = _normalize(raw) or ""
    except Exception:  # noqa: BLE001
        norm = raw
    text = f"{raw}\n{norm}".lower()

    w = dict(DEFAULT_WEIGHTS)
    if weights:
        for k, v in weights.items():
            if k in w:
                try:
                    w[k] = float(v)
                except (TypeError, ValueError):
                    pass

    rv = RiskVector(
        filesystem=_signal_score(text, _FS_SIGNALS),
        network=_signal_score(text, _NET_SIGNALS),
        process=_signal_score(text, _PROC_SIGNALS),
        credential=_signal_score(text, _CRED_SIGNALS),
        data_flow=_signal_score(text, _FLOW_SIGNALS),
        obfuscation=_signal_score(text, _OBF_SIGNALS),
        weights=w,
    )

    # 吸收既有引擎的判定 (单一来源): 影响半径归位到维度 + 风险等级作为综合分下限
    if safety_score:
        br = safety_score.get("blast_radius") or {}
        if br.get("files"):
            rv.filesystem = max(rv.filesystem, 6.0)
        if br.get("services"):
            rv.process = max(rv.process, 6.0)
        if br.get("data"):
            rv.data_flow = max(rv.data_flow, 6.0)
        rv.engine_floor = {"critical": 10.0, "high": 7.0, "medium": 5.0}.get(
            str(safety_score.get("risk") or ""), 0.0)
    return rv


__all__ = ["RiskVector", "assess", "DEFAULT_WEIGHTS"]
