"""人机交互面板 —— 优先展示「现在有什么需要我」。

对标 DeepSeek Super-agent 的面板设计:
- 面板优先展示待回答、待审阅、受阻或失败的工作;
- 再提供系统健康、历史记录和执行负载;
- 把人需要采取的动作放在前面, 把运行细节放在可按需展开的位置。

状态区分 (很重要):
- Agent 还在工作 vs 等一条外部消息;
- 结果已经可审阅 vs 只是提交了一个尚未完成的草稿;
- 遇到问题后需要人补资源 vs 系统正在重试。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .models import TicketStatus


@dataclass
class PanelItem:
    """面板中的一行条目 (带人需要采取的动作标识)。"""
    priority: int                # 越小越靠前 (0 = 待回答, 1 = 待审阅, 2 = 受阻, 3 = 正常)
    label: str                   # 状态标签 (如 "待回答" "待审阅" "受阻")
    title: str
    detail: str = ""
    action: str = ""             # 人需要做的动作 (如 "回答" "验收" "提供资源")
    ticket_id: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "priority": self.priority,
            "label": self.label,
            "title": self.title,
            "detail": self.detail,
            "action": self.action,
            "ticket_id": self.ticket_id,
        }


# 状态 → (priority, label, action) 映射
_STATUS_META = {
    TicketStatus.NEEDS_INPUT: (0, "待回答", "回答"),
    TicketStatus.REVIEW: (1, "待审阅", "验收"),
    TicketStatus.BLOCKED: (2, "受阻", "提供资源/决策"),
    TicketStatus.FAILED: (2, "失败", "查看/重试"),
    TicketStatus.DRAFT: (2, "草稿", "审阅"),
    TicketStatus.RETRYING: (3, "重试中", "等待"),
    TicketStatus.RUNNING: (3, "执行中", "等待"),
    TicketStatus.PENDING: (3, "待开始", "等待"),
    TicketStatus.DONE: (4, "完成", ""),
    TicketStatus.CANCELLED: (4, "已取消", ""),
}


class Panel:
    """从 Router 工单状态构建「现在有什么需要我」面板。"""

    def __init__(self, router: Any = None) -> None:
        self.router = router

    def build(self) -> List[PanelItem]:
        """按优先级排序的待办面板 (人需要动作的在前)。"""
        items: List[PanelItem] = []
        if self.router is None:
            return items
        for t in self.router.ticket_summary():
            try:
                status = TicketStatus(t["status"])
            except ValueError:
                status = TicketStatus.PENDING
            priority, label, action = _STATUS_META.get(status, (4, status.value, ""))
            detail = t["progress"] or t["error"] or ""
            items.append(PanelItem(
                priority=priority,
                label=label,
                title=t["title"],
                detail=detail,
                action=action,
                ticket_id=t["ticket_id"],
            ))
        # 同优先级内: 最近创建的工单排前面 (ticket_id 是字符串, 用其数字后缀比较)
        def _age(x: PanelItem) -> float:
            sid = x.ticket_id
            # 形如 tkt-103e298558b5; 用最后 8 位 hex 反序近似时间序
            try:
                return -int(sid.rsplit("-", 1)[-1], 16) if "-" in sid else 0.0
            except (ValueError, IndexError):
                return 0.0
        items.sort(key=lambda x: (x.priority, _age(x)))
        return items

    def needs_human(self) -> List[PanelItem]:
        """只返回需要人采取动作的条目 (待回答/待审阅/受阻/失败)。"""
        return [i for i in self.build() if i.action]

    def render(self) -> str:
        """渲染成可读文本 (CLI/TUI 用)。

        需要人动作的条目附上具体可执行的命令提示 (经 /superagent),
        让人不必查文档就知道下一步敲什么 —— 面板与人机交互动作闭环。
        """
        items = self.build()
        if not items:
            return "(当前没有工单)"
        lines: List[str] = []
        for i in items:
            action = f" → 需要你: {i.action}" if i.action else ""
            lines.append(f"[{i.label}] {i.title}{action}")
            if i.detail:
                lines.append(f"    {i.detail}")
            # 人机交互闭环: 给出可直接执行的命令 (经 TUI/CLI 斜杠命令)。
            cmd = self._action_cmd(i)
            if cmd:
                lines.append(f"    命令: {cmd}")
        return "\n".join(lines)

    @staticmethod
    def _action_cmd(item: PanelItem) -> str:
        """根据状态返回一条可直接执行的动作命令 (空串表示无需动作)。"""
        if not item.ticket_id:
            return ""
        sid = item.ticket_id
        label = item.label
        if label == "待回答":
            return f"/superagent reply {sid} <你的回答>"
        if label == "待审阅":
            return f"/superagent accept {sid}"
        if label == "受阻":
            return f"/superagent retry {sid}  (或先提供资源后再重试)"
        if label == "失败":
            return f"/superagent retry {sid}"
        if label == "草稿":
            return f"/superagent accept {sid}"
        return ""
