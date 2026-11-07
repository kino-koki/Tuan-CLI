"""Super-Agent 领域对象模型。

对标 DeepSeek Super-agent 概念中的四个核心对象:
- Trigger: 一条外部事件 (消息/评论/状态变化/CI 结果);
- Thread: 一组按时间排列的相关事件 (同一 IM 话题或同一 PR 的连续评论);
- Ticket: 一项已经获准推进的工作 (含输入/进展/交付状态);
- Subscription: 把 Thread 的后续事件直接送到对应 Worker。

另有:
- TicketStatus: 工单生命周期状态;
- WorkMode: 主动候选的三档接单模式 (off / observe / auto);
- EventSource: 事件来源抽象 (IM / GitHub / 文件监视等), 支持注册事件源。
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


def _now() -> float:
    return time.time()


def _uid(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


class TriggerKind(str, Enum):
    """触发器类型。"""
    MESSAGE = "message"        # IM / 群聊消息
    COMMENT = "comment"        # PR / issue 评论
    PR = "pr"                  # PR 状态变化
    CI = "ci"                  # CI 运行结果
    ISSUE = "issue"            # issue 创建/变更
    SCHEDULE = "schedule"      # 日程/定时
    MAIL = "mail"              # 邮件
    FILE = "file"              # 本地文件变化
    MANUAL = "manual"          # 人工注入
    UNKNOWN = "unknown"


class TriggerSource(str, Enum):
    """触发器来源渠道。"""
    IM = "im"                  # 即时通讯 (飞书/微信/QQ 群)
    GITHUB = "github"          # GitHub PR/issue/评论
    CI = "ci"                  # CI 管道
    MAIL = "mail"              # 邮箱
    FILE = "file"              # 本地文件系统
    SCHEDULE = "schedule"      # 定时任务
    LOCAL = "local"            # 本地手动/脚本
    UNKNOWN = "unknown"


class TicketStatus(str, Enum):
    """工单生命周期状态。

    与 DeepSeek 面板设计对齐: 需要区分「Agent 还在工作」vs「等一条外部消息」、
    「结果可审阅」vs「只是一个未完成草稿」、「需要人补资源」vs「系统正在重试」。
    """
    PENDING = "pending"          # 已获准, 尚未开始
    RUNNING = "running"          # Worker 正在执行
    BLOCKED = "blocked"          # 受阻: 需要人提供资源/决策
    NEEDS_INPUT = "needs_input"  # 等待用户输入/回答
    REVIEW = "review"            # 有可审阅结果, 等用户验收
    DRAFT = "draft"              # 仅产出未完成草稿 (未达交付标准)
    RETRYING = "retrying"        # 系统正在重试
    DONE = "done"                # 已完成并交付
    FAILED = "failed"            # 失败 (不可自动恢复)
    CANCELLED = "cancelled"      # 已取消


class WorkMode(str, Enum):
    """主动候选 (推断的工作机会) 的三档接单模式。

    - off:     不接收这类候选;
    - observe: 评估候选, 正面判断只记录「本来会接单」, 实际不开工单 (默认);
    - auto:    在匹配启用规则后, 允许接单。

    明确授权的请求 (请修复这个问题) 在三档模式下均可执行。
    """
    OFF = "off"
    OBSERVE = "observe"
    AUTO = "auto"


@dataclass
class Trigger:
    """一条外部事件。"""
    trigger_id: str = field(default_factory=lambda: _uid("trg"))
    kind: TriggerKind = TriggerKind.UNKNOWN
    source: TriggerSource = TriggerSource.UNKNOWN
    channel: str = ""            # 具体渠道名 (群名/仓库名/PR 号)
    content: str = ""            # 事件正文
    sender: str = ""             # 发送者/作者
    meta: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=_now)
    thread_id: str = ""          # 关联 Thread (可为空)
    ticket_id: str = ""          # 已关联的工单 (直达 Worker 用)
    # 准入过滤结果
    program_passed: bool = False  # 程序规则是否通过 (两级过滤第一级)
    model_passed: bool = False    # 模型研判是否通过 (两级过滤第二级)

    @property
    def is_actionable(self) -> bool:
        """是否值得交给模型研判 (程序层过滤后)。"""
        return self.program_passed


@dataclass
class Thread:
    """一组按时间排列的相关事件 (同一话题的连续 Trigger)。"""
    thread_id: str = field(default_factory=lambda: _uid("thr"))
    topic: str = ""               # 话题描述 (如 "PR #42 的修复讨论")
    source: TriggerSource = TriggerSource.UNKNOWN
    channel: str = ""
    triggers: List[str] = field(default_factory=list)  # trigger_id 列表
    ticket_id: str = ""           # 已关联工单
    created_at: float = field(default_factory=_now)
    updated_at: float = field(default_factory=_now)


@dataclass
class Subscription:
    """把 Thread 的后续事件直接送到对应 Worker (减少 Router 转发)。"""
    subscription_id: str = field(default_factory=lambda: _uid("sub"))
    thread_id: str = ""
    worker_id: str = ""           # 目标 Worker
    ticket_id: str = ""           # 关联工单
    created_at: float = field(default_factory=_now)


@dataclass
class Ticket:
    """一项已获准推进的工作。

    每个工单有自己的执行会话与目录; Worker 内部还可以调用子 Agent。
    """
    ticket_id: str = field(default_factory=lambda: _uid("tkt"))
    title: str = ""
    prompt: str = ""
    source_trigger_id: str = ""   # 触发它的第一条 Trigger
    thread_id: str = ""
    authorization: str = "explicit"  # explicit (明确请求) | inferred (推断候选)
    status: TicketStatus = TicketStatus.PENDING
    worker_id: str = ""
    workdir: str = ""             # 独立执行目录
    progress: str = ""            # 进度摘要 (Worker 汇报)
    result: str = ""              # 交付结果
    error: str = ""               # 失败原因
    created_at: float = field(default_factory=_now)
    updated_at: float = field(default_factory=_now)
    started_at: float = 0.0
    finished_at: float = 0.0
    meta: Dict[str, Any] = field(default_factory=dict)
    # 先记录后执行 (Write-Ahead): 已持久化则重放时可安全恢复
    persisted: bool = False

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "ticket_id": self.ticket_id,
            "title": self.title,
            "prompt": self.prompt,
            "source_trigger_id": self.source_trigger_id,
            "thread_id": self.thread_id,
            "authorization": self.authorization,
            "status": self.status.value,
            "worker_id": self.worker_id,
            "workdir": self.workdir,
            "progress": self.progress,
            "result": self.result,
            "error": self.error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "meta": self.meta,
            "persisted": self.persisted,
        }
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Ticket":
        try:
            status = TicketStatus(d.get("status", "pending"))
        except ValueError:
            status = TicketStatus.PENDING
        return cls(
            ticket_id=d.get("ticket_id", _uid("tkt")),
            title=d.get("title", ""),
            prompt=d.get("prompt", ""),
            source_trigger_id=d.get("source_trigger_id", ""),
            thread_id=d.get("thread_id", ""),
            authorization=d.get("authorization", "explicit"),
            status=status,
            worker_id=d.get("worker_id", ""),
            workdir=d.get("workdir", ""),
            progress=d.get("progress", ""),
            result=d.get("result", ""),
            error=d.get("error", ""),
            created_at=d.get("created_at", _now()),
            updated_at=d.get("updated_at", _now()),
            started_at=d.get("started_at", 0.0),
            finished_at=d.get("finished_at", 0.0),
            meta=d.get("meta", {}),
            persisted=d.get("persisted", False),
        )


class EventSource:
    """事件源抽象基类。

    事件源把外部信息转换为 Trigger, 交给 SuperAgent 的 EventBus。
    子类可覆写 poll() (轮询) 或提供异步回调注册 (如 IM webhook)。
    """

    def __init__(self, source: TriggerSource, channel: str = "") -> None:
        self.source = source
        self.channel = channel
        self._agent: Optional[Any] = None

    def attach(self, agent: Any) -> None:
        """绑定 SuperAgent 实例 (由引擎在注册时调用)。"""
        self._agent = agent

    def emit(self, kind: TriggerKind, content: str,
             sender: str = "", **meta: Any) -> Trigger:
        """生成并投递一条 Trigger。"""
        trg = Trigger(
            kind=kind,
            source=self.source,
            channel=self.channel,
            content=content,
            sender=sender,
            meta=meta,
        )
        if self._agent is not None:
            self._agent.on_event(trg)
        return trg

    def start(self) -> None:
        """开始监听 (子类可覆写, 启动轮询线程等)。"""

    def stop(self) -> None:
        """停止监听 (子类可覆写)。"""


class EventStatus(str, Enum):
    """事件处理状态。"""
    RECEIVED = "received"        # 已接收
    FILTERED = "filtered"        # 程序层过滤掉 (无关)
    ASSESSED = "assessed"        # 模型研判: 会接单但未开单 (observe)
    ROUTED = "routed"            # 已路由到工单/Worker
    DELIVERED = "delivered"      # 已直达 Worker (Subscription)
    IGNORED = "ignored"          # 模型研判: 无需行动
