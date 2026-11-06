"""E4: 审计关联合并 + 跨会话异常检测 (纯观测, 绝不反作用于安全裁决)。

为什么需要这一层:
``SecurityAuditor`` 已经把每条安全决策 AEAD 加密落盘并串成防篡改链, 但它是
**逐条**的: 同一来源反复触发红线 (例如某个 MCP server 持续注入、某个仓库反复
诱导过宽授权) 在单条记录里看不出异常, 1000 条 `deny` 只是 1000 行日志。
SIEM 真正要的是「聚合后的信号」。

设计约束 (很重要):
- **纯观测**: 本模块不返回 allow/deny, 不修改 AuditRecord, 不参与任何裁决。
  任何异常都被吞掉并记 log, 绝不因为关联器坏了就影响主链路。
- **不依赖磁盘格式**: 输入是 ``AuditRecord`` / 任意有同名属性的对象,
  从加密日志重放出来的历史记录同样可喂。
- **有界内存**: 窗口 deque + 指纹表都有上限, 长驻进程不会无限增长。
- **跨会话**: 同一指纹在 >= 2 个不同 session_id 出现即告警 —— 提示注入 / 投毒
  内容常在多个会话里复用, 单会话的阈值检测抓不到。
"""
from __future__ import annotations

import hashlib
import logging
import re
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, Iterable, List, Optional, Set, Tuple

log = logging.getLogger(__name__)

# 输入摘要里高基数的部分 (路径 / 数字 / 十六进制) 归一化掉, 否则同一攻击
# 换一个临时路径就变成新指纹, 关联永远凑不齐。
_NOISE_RE = re.compile(
    r"(?:0x[0-9a-fA-F]+|/[^\s'\"|;]+|\b\d{2,}\b|[0-9a-fA-F]{16,})"
)

_SEVERITY_ORDER = {"none": 0, "low": 1, "medium": 2, "info": 1,
                   "high": 3, "critical": 4}


@dataclass(frozen=True)
class CorrelationAlert:
    """一条聚合告警 (只用于观测 / SIEM, 不是安全决策)。"""
    kind: str            # burst | cross_session | severity_escalation
    fingerprint: str
    module: str
    action: str
    severity: str
    count: int
    sessions: Tuple[str, ...]
    message: str
    first_ts: float
    last_ts: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind, "fingerprint": self.fingerprint,
            "module": self.module, "action": self.action,
            "severity": self.severity, "count": self.count,
            "sessions": list(self.sessions), "message": self.message,
            "first_ts": self.first_ts, "last_ts": self.last_ts,
        }


def fingerprint_of(rec: Any) -> str:
    """把一条审计记录映射到稳定指纹 (同来源同手法 -> 同指纹)。

    维度: module + action + 归一化后的 reasons 首条 + 归一化后的输入摘要。
    **不含 session_id / agent_id / seq / ts**, 否则跨会话检测永远不成立。
    """
    def _get(name: str, default: str = "") -> str:
        try:
            return str(getattr(rec, name, default) or default)
        except Exception:  # noqa: BLE001
            return default

    reasons = getattr(rec, "reasons", None) or []
    try:
        primary_reason = str(reasons[0]) if reasons else ""
    except Exception:  # noqa: BLE001
        primary_reason = ""
    raw = "|".join([
        _get("module"), _get("action"),
        _NOISE_RE.sub("<n>", primary_reason.lower()).strip(),
        _NOISE_RE.sub("<n>", _get("input_summary").lower()).strip()[:160],
    ])
    return hashlib.sha256(raw.encode("utf-8", "replace")).hexdigest()[:16]


class AuditCorrelator:
    """滑动窗口关联器。

    用法::

        corr = AuditCorrelator(window_seconds=300, burst_threshold=5)
        corr.replay(historical_records)          # 可选: 从加密日志重放历史
        alerts = corr.assess(new_record)         # 每条新记录调用
        corr.recent_alerts()                     # 给 UI / SIEM 拉取
    """

    def __init__(
        self,
        window_seconds: float = 300.0,
        burst_threshold: int = 5,
        cross_session_threshold: int = 2,
        max_window_events: int = 5000,
        max_fingerprints: int = 20000,
        max_alerts: int = 500,
        now_fn: Optional[Any] = None,
    ) -> None:
        self.window_seconds = float(window_seconds)
        self.burst_threshold = int(burst_threshold)
        self.cross_session_threshold = int(cross_session_threshold)
        self._max_events = int(max_window_events)
        self._max_fps = int(max_fingerprints)
        self._max_alerts = int(max_alerts)
        self._now = now_fn or time.time

        self._lock = threading.Lock()
        # (ts, fingerprint, session_id, severity_rank)
        self._events: Deque[Tuple[float, str, str, int]] = deque()
        # fingerprint -> 见过的 session 集合 (跨会话检测, 不受滑动窗口淘汰)
        self._sessions: Dict[str, Set[str]] = {}
        # (fingerprint, 窗口桶) -> 已告警, 避免同一波事件每条都刷屏
        self._alerted: Set[Tuple[str, int]] = set()
        self._alerts: List[CorrelationAlert] = []
        # fingerprint -> 历史最高严重度 (升级检测)
        self._peak_severity: Dict[str, int] = {}

    # -------------------------------------------------------------- 内部
    def _prune(self, now: float) -> None:
        cutoff = now - self.window_seconds
        while self._events and self._events[0][0] < cutoff:
            self._events.popleft()
        while len(self._events) > self._max_events:
            self._events.popleft()
        bucket = int(now // self.window_seconds)
        self._alerted = {k for k in self._alerted if k[1] >= bucket - 1}
        if len(self._sessions) > self._max_fps:
            # 淘汰最早插入的一半 (dict 保序), 保证有界
            for k in list(self._sessions)[: self._max_fps // 2]:
                self._sessions.pop(k, None)
                self._peak_severity.pop(k, None)

    def _push_alert(self, alert: CorrelationAlert) -> None:
        self._alerts.append(alert)
        if len(self._alerts) > self._max_alerts:
            self._alerts = self._alerts[-self._max_alerts:]

    # -------------------------------------------------------------- 公共 API
    def replay(self, records: Iterable[Any]) -> int:
        """把历史记录喂进关联器 (不产生告警), 返回纳入条数。

        用于 SecurityAuditor 启动时从 AEAD 日志重放, 使「跨会话」检测能跨越
        进程重启 —— 否则每次重启都只剩本进程内的会话, 跨会话信号会丢失。
        """
        n = 0
        try:
            with self._lock:
                for rec in records:
                    fp = fingerprint_of(rec)
                    sid = str(getattr(rec, "session_id", "") or "")
                    sev = str(getattr(rec, "severity", "") or "").lower()
                    self._sessions.setdefault(fp, set())
                    if sid:
                        self._sessions[fp].add(sid)
                    rank = _SEVERITY_ORDER.get(sev, 0)
                    if rank > self._peak_severity.get(fp, 0):
                        self._peak_severity[fp] = rank
                    n += 1
                self._prune(self._now())
        except Exception as exc:  # noqa: BLE001 - 观测层绝不抛给主链路
            log.warning("审计关联历史重放失败: %s", exc)
        return n

    def assess(self, rec: Any) -> List[CorrelationAlert]:
        """评估一条新记录, 返回本次触发的聚合告警 (可能为空)。"""
        try:
            now = float(self._now())
            fp = fingerprint_of(rec)
            sid = str(getattr(rec, "session_id", "") or "")
            module = str(getattr(rec, "module", "") or "")
            action = str(getattr(rec, "action", "") or "")
            sev = str(getattr(rec, "severity", "") or "").lower()
            rank = _SEVERITY_ORDER.get(sev, 0)
            ts = float(getattr(rec, "ts", 0) or now)
            out: List[CorrelationAlert] = []

            with self._lock:
                # 先 append 再 prune: 否则 _max_events 裁剪发生在新增之前,
                # 窗口会稳定地多出 1 条 (长驻进程里就是无界偏差的起点)。
                self._events.append((ts, fp, sid, rank))
                self._prune(now)
                seen = self._sessions.setdefault(fp, set())
                if sid:
                    seen.add(sid)
                prev_peak = self._peak_severity.get(fp, 0)
                if rank > prev_peak:
                    self._peak_severity[fp] = rank

                # 窗口内同源事件
                window_hits = [(t, s) for t, f, s, _ in self._events if f == fp]
                bucket = int(now // self.window_seconds)

                # 1) 同源高频红线聚合
                if (len(window_hits) >= self.burst_threshold
                        and (fp, bucket) not in self._alerted):
                    self._alerted.add((fp, bucket))
                    a = CorrelationAlert(
                        kind="burst", fingerprint=fp, module=module,
                        action=action, severity=sev or "high",
                        count=len(window_hits),
                        sessions=tuple(sorted({s for _, s in window_hits if s})),
                        message=(f"{module} 在 {self.window_seconds:.0f}s 内重复触发 "
                                 f"{len(window_hits)} 次同类红线 ({action}), 疑似持续注入/循环试探"),
                        first_ts=min(t for t, _ in window_hits),
                        last_ts=max(t for t, _ in window_hits),
                    )
                    self._push_alert(a); out.append(a)

                # 2) 跨会话复用 (含历史重放得到的会话)
                if (len(seen) >= self.cross_session_threshold
                        and (fp + ":cross", bucket) not in self._alerted):
                    self._alerted.add((fp + ":cross", bucket))
                    a = CorrelationAlert(
                        kind="cross_session", fingerprint=fp, module=module,
                        action=action, severity="critical",
                        count=len(window_hits), sessions=tuple(sorted(seen)),
                        message=(f"同一攻击指纹 {fp} 出现在 {len(seen)} 个不同会话 "
                                 f"({', '.join(sorted(seen))[:120]}), 疑似跨会话投毒/提示注入复用"),
                        first_ts=min((t for t, _ in window_hits), default=ts),
                        last_ts=ts,
                    )
                    self._push_alert(a); out.append(a)

                # 3) 严重度升级 (同源从低危升到 critical)
                if (rank >= 4 and prev_peak <= 1
                        and (fp + ":esc", bucket) not in self._alerted):
                    self._alerted.add((fp + ":esc", bucket))
                    a = CorrelationAlert(
                        kind="severity_escalation", fingerprint=fp,
                        module=module, action=action, severity="critical",
                        count=len(window_hits), sessions=tuple(sorted(seen)),
                        message=(f"同源事件严重度从 low/none 跃升到 critical "
                                 f"({module}/{action}), 疑似渐进式权限试探"),
                        first_ts=ts, last_ts=ts,
                    )
                    self._push_alert(a); out.append(a)
            return out
        except Exception as exc:  # noqa: BLE001
            log.warning("审计关联评估失败 (不影响裁决): %s", exc)
            return []

    def recent_alerts(self, limit: int = 50) -> List[CorrelationAlert]:
        with self._lock:
            return list(self._alerts[-max(0, int(limit)):])

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "window_events": len(self._events),
                "tracked_fingerprints": len(self._sessions),
                "alerts_total": len(self._alerts),
                "by_kind": {
                    k: sum(1 for a in self._alerts if a.kind == k)
                    for k in ("burst", "cross_session", "severity_escalation")
                },
                "window_seconds": self.window_seconds,
                "burst_threshold": self.burst_threshold,
            }

    def reset(self) -> None:
        with self._lock:
            self._events.clear()
            self._sessions.clear()
            self._alerted.clear()
            self._alerts.clear()
            self._peak_severity.clear()
