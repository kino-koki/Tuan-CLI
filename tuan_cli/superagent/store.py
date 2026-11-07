"""持久化层 —— 状态落盘、恢复、先记录后执行 (Write-Ahead)。

对标 DeepSeek Super-agent 的持久运行要求:
- 保留会话、目录、订阅和待处理输入;
- 主进程重启后, 中断的派工可重新启动, 附带恢复说明;
- 执行端先检查目录/Git 历史/平台状态, 再决定如何继续;
- 派工、输入投递、消息发送等工作先记录、后执行 (Write-Ahead);
- 持久队列 + 重试处理投递失败。

注意: 持久状态 ≠ 持续存活的进程。进程重启会终止后台作业, 恢复机制不能
保证外部动作恰好执行一次 (恰好一次需要外部幂等键)。
"""

from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from .models import Ticket, TicketStatus, Trigger

log = logging.getLogger(__name__)


class StateStore:
    """把 Super-Agent 状态持久化到 <home>/superagent/state.json。

    线程安全: 用 RLock 保护; 写盘用临时文件 + os.replace (原子替换)。
    """

    def __init__(self, home: str | Path) -> None:
        self.dir = Path(home) / "superagent"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.file = self.dir / "state.json"
        self.queue_file = self.dir / "outbox.json"   # 先记录后执行队列
        self._lock = threading.RLock()
        self._state: Dict[str, Any] = {
            "tickets": {}, "threads": {}, "subscriptions": {}, "context": [],
        }
        self._outbox: List[Dict[str, Any]] = []
        self._load()

    # ---------------------------------------------------------- 加载/保存

    def _load(self) -> None:
        if self.file.exists():
            try:
                data = json.loads(self.file.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    self._state = data
            except Exception:  # noqa: BLE001
                log.warning("superagent state.json 损坏, 重新初始化")
        # 兼容旧 state.json (无 context 键): 回填空列表
        if "context" not in self._state:
            self._state["context"] = []
        if self.queue_file.exists():
            try:
                data = json.loads(self.queue_file.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    self._outbox = data
            except Exception:  # noqa: BLE001
                self._outbox = []

    def _save(self) -> None:
        tmp = self.file.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self._state, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self.file)

    def _save_outbox(self) -> None:
        tmp = self.queue_file.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self._outbox, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self.queue_file)

    # ---------------------------------------------------------- Tickets

    def save_ticket(self, ticket: Ticket) -> None:
        """先记录后执行: 派工前把工单写入状态 (Write-Ahead)。"""
        with self._lock:
            self._state["tickets"][ticket.ticket_id] = ticket.to_dict()
            ticket.persisted = True
            self._save()

    def get_ticket(self, ticket_id: str) -> Optional[Ticket]:
        with self._lock:
            d = self._state["tickets"].get(ticket_id)
            return Ticket.from_dict(d) if d else None

    def all_tickets(self) -> List[Ticket]:
        with self._lock:
            return [Ticket.from_dict(d) for d in self._state["tickets"].values()]

    def pending_tickets(self) -> List[Ticket]:
        """中断/未完成工单 (供重启恢复)。"""
        out = []
        for t in self.all_tickets():
            if t.status in (TicketStatus.PENDING, TicketStatus.RUNNING,
                            TicketStatus.RETRYING, TicketStatus.BLOCKED):
                out.append(t)
        return out

    # ---------------------------------------------------------- Outbox (WAL)

    def enqueue(self, op: Dict[str, Any]) -> None:
        """先记录后执行: 把操作写入持久队列, 返回前已落盘。"""
        with self._lock:
            self._outbox.append(op)
            self._save_outbox()

    def dequeue(self, op_id: str) -> bool:
        with self._lock:
            before = len(self._outbox)
            self._outbox = [o for o in self._outbox if o.get("id") != op_id]
            if len(self._outbox) != before:
                self._save_outbox()
                return True
            return False

    def outbox(self) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self._outbox)

    # ---------------------------------------------------------- Subscriptions

    def save_subscription(self, thread_id: str, worker_id: str) -> None:
        with self._lock:
            self._state["subscriptions"][thread_id] = worker_id
            self._save()

    def subscriptions(self) -> Dict[str, str]:
        with self._lock:
            return dict(self._state["subscriptions"])

    def remove_subscription(self, thread_id: str) -> None:
        with self._lock:
            self._state["subscriptions"].pop(thread_id, None)
            self._save()

    # ---------------------------------------------------------- 观察上下文 (跨任务上下文持久化)

    def save_context(self, entry: Dict[str, Any], limit: int = 40) -> None:
        """把一条观察上下文追加进持久状态 (环形缓冲, 保留最近 limit 条)。

        与 Router 的内存环形缓冲同构: 崩溃/重启后 recent_context() 仍可用。
        """
        with self._lock:
            ctx = self._state.setdefault("context", [])
            ctx.append(dict(entry))
            if len(ctx) > limit:
                del ctx[:len(ctx) - limit]
            self._save()

    def load_context(self) -> List[Dict[str, Any]]:
        """读取全部持久化上下文 (供 Router 重启回填)。"""
        with self._lock:
            return list(self._state.get("context", []))

    # ---------------------------------------------------------- 统计

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "tickets": len(self._state["tickets"]),
                "threads": len(self._state["threads"]),
                "subscriptions": len(self._state["subscriptions"]),
                "context": len(self._state.get("context", [])),
                "outbox": len(self._outbox),
                "recoverable": len(self.pending_tickets()),
            }
