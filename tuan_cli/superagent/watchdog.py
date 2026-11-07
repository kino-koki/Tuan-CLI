"""Watchdog —— 独立巡检会话, 监控进展并介入异常。

对标 DeepSeek Super-agent 的外部 Watchdog:
- 在主架构之外设置独立 Watchdog Session, 形成外部控制回路;
- 不仅监控接口报错、状态恢复失败等基础设施问题;
- 还会通过模型判断 Worker 是否取得实质进展、执行方向是否偏离目标;
- 发现异常时介入修复 (重启卡住的 Worker / 标记失败 / 触发重试)。

与 Router/Worker 不同, Watchdog 是**外部监督者**, 不参与正常任务流。
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable, Dict, List, Optional

from .models import TicketStatus

log = logging.getLogger(__name__)


class Watchdog:
    """周期巡检所有 Worker 与工单, 检测停滞/异常并介入。

    判据:
    - 接口错误/状态恢复失败 (infra errors);
    - Worker 长时间无实质进展 (stall);
    - 执行方向偏离目标 (由注入的 judge_fn 用模型判断, 可选);
    - 超时未完成 (max_runtime)。
    """

    def __init__(
        self,
        router: Any = None,
        worker_pool: Any = None,
        interval: float = 15.0,
        stall_seconds: float = 300.0,
        max_runtime: float = 1800.0,
        judge_fn: Optional[Callable[[Any], Dict[str, Any]]] = None,
        heal_fn: Optional[Callable[[str, str], str]] = None,
        enabled: bool = True,
    ) -> None:
        self.router = router
        self.worker_pool = worker_pool
        self.interval = interval
        self.stall_seconds = stall_seconds
        self.max_runtime = max_runtime
        self.judge_fn = judge_fn     # 模型判断方向/进展 (可选)
        self.heal_fn = heal_fn       # 修复动作 (可选)
        self.enabled = enabled
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._checks = 0
        self._interventions = 0
        self._log: List[Dict[str, Any]] = []

    # ---------------------------------------------------------- 生命周期

    def start(self) -> None:
        if not self.enabled:
            return
        self._thread = threading.Thread(target=self._loop, name="superagent-watchdog", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.check_once()
            except Exception:  # noqa: BLE001
                log.exception("watchdog check failed")
            self._stop.wait(self.interval)

    # ---------------------------------------------------------- 巡检

    def check_once(self) -> List[Dict[str, Any]]:
        """执行一轮巡检, 返回本轮发现的问题列表。"""
        self._checks += 1
        findings: List[Dict[str, Any]] = []
        if self.worker_pool is None:
            return findings
        now = time.time()
        for w in self.worker_pool.status():
            if not w["alive"]:
                continue
            ticket_id = w["ticket_id"]
            elapsed = w["elapsed"]
            progress = w["progress"]
            # 超时
            if elapsed > self.max_runtime:
                finding = self._intervene(
                    "timeout", ticket_id, f"Worker {w['worker_id']} 运行超过 {self.max_runtime:.0f}s"
                )
                findings.append(finding)
                continue
            # 停滞: 长时间无进展 (无进度更新)
            if elapsed > self.stall_seconds and not progress:
                finding = self._intervene(
                    "stall", ticket_id, f"Worker {w['worker_id']} 停滞 {elapsed:.0f}s 无进展"
                )
                findings.append(finding)
                continue
            # 模型判断方向 (可选, 每 N 轮做一次避免开销)
            if self.judge_fn is not None and self._checks % 10 == 0:
                try:
                    verdict = self.judge_fn(w)
                    if verdict.get("off_track"):
                        finding = self._intervene(
                            "off_track", ticket_id, verdict.get("reason", "方向偏离目标")
                        )
                        findings.append(finding)
                except Exception:  # noqa: BLE001
                    pass
        # 工单层面的异常状态巡检 (BLOCKED 长时间无人处理)
        if self.router is not None:
            for t in self.router.ticket_summary():
                if t["status"] == "blocked" and (now - t["updated_at"] > self.stall_seconds):
                    finding = self._intervene(
                        "blocked_stale", t["ticket_id"], "工单长期受阻, 需要人工资源或决策"
                    )
                    findings.append(finding)
        return findings

    def _intervene(self, kind: str, ticket_id: str, reason: str) -> Dict[str, Any]:
        """介入: 记录 + 触发修复 (heal_fn 若提供)。"""
        self._interventions += 1
        entry = {
            "kind": kind,
            "ticket_id": ticket_id,
            "reason": reason,
            "time": time.time(),
            "healed": False,
        }
        if self.heal_fn is not None:
            try:
                note = self.heal_fn(kind, ticket_id)
                entry["healed"] = True
                entry["note"] = note
            except Exception as exc:  # noqa: BLE001
                entry["note"] = f"修复失败: {exc}"
        self._log.append(entry)
        # 同步到 Router 工单状态
        if self.router is not None:
            ticket = self.router.tickets.get(ticket_id)
            if ticket is not None:
                if kind in ("timeout", "stall", "off_track"):
                    ticket.status = TicketStatus.RETRYING
                    ticket.progress = f"Watchdog 介入: {reason}"
                elif kind == "blocked_stale":
                    ticket.status = TicketStatus.BLOCKED
                    ticket.progress = f"Watchdog: {reason}"
                ticket.updated_at = time.time()
        log.warning("watchdog intervene: %s ticket=%s reason=%s", kind, ticket_id, reason)
        return entry

    # ---------------------------------------------------------- 状态

    def metrics(self) -> Dict[str, Any]:
        return {
            "enabled": self.enabled,
            "checks": self._checks,
            "interventions": self._interventions,
            "recent": self._log[-10:],
        }
