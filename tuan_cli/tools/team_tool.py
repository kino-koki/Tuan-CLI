"""团队协作工具 —— 暴露 CollaborationProtocol 给模型调用。

qwen_office 模式在 capabilities.tools 中已列出四个团队协作工具名:
    team_share_note / team_list_members / team_post_update / team_read_updates
此前无任何实现。本模块基于 core.collaboration_protocol.CollaborationProtocol
(经 collaboration_plugin.CollaborationPlugin 注册为内核服务 "collaboration_protocol")
补齐这四个工具, 让模型能在 qwen_office 模式下通过团队黑板共享笔记、
广播进度更新、读取最新动态与列出成员。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..core.collaboration_protocol import (
    CollaborationProtocol,
    MessagePriority,
    MessageType,
)
from ..core.kernel import Kernel, Plugin
from .base import Tool, ToolContext, string_prop

import logging
log = logging.getLogger(__name__)

# 保留发送者: 协议内部用作系统标识, 不作为团队成员列出
_RESERVED_SENDER = "__system__"

# 优先级映射: 工具参数 (字符串) -> 协议枚举
_PRIORITY_MAP: Dict[str, MessagePriority] = {
    "low": MessagePriority.LOW,
    "normal": MessagePriority.NORMAL,
    "high": MessagePriority.HIGH,
    "urgent": MessagePriority.URGENT,
}

# msg_type 过滤映射: note -> ARTIFACT; update -> STATUS/PROGRESS
_NOTE_TYPES = (MessageType.ARTIFACT,)
_UPDATE_TYPES = (MessageType.STATUS, MessageType.PROGRESS)


def _require_protocol(ctx: ToolContext) -> CollaborationProtocol:
    """从内核取协作协议服务; 不可用时抛错由外层 except 捕获。"""
    protocol: CollaborationProtocol = ctx.kernel.require("collaboration_protocol")
    return protocol


# ================================================================ team_share_note


def _team_share_note_handler(
    ctx: ToolContext, key: str = "", note: str = "", sender: str = "agent",
    **_kwargs: Any,
) -> str:
    if not key:
        return "[错误] team_share_note 需要 key 参数"
    if not note:
        return "[错误] team_share_note 需要 note 参数"
    try:
        protocol = _require_protocol(ctx)
        msg = protocol.write(
            key=key, value=note, sender=sender or "agent",
            msg_type=MessageType.ARTIFACT,
        )
        return f"已共享笔记 \"{key}\" (v{msg.version})"
    except Exception as exc:  # noqa: BLE001
        return f"[错误] 共享笔记失败: {type(exc).__name__}: {exc}"


def build_team_share_note_tool() -> Tool:
    return Tool(
        name="team_share_note",
        description=(
            "在团队协作黑板上共享一条持久化的笔记/产出物 (ARTIFACT 类型), "
            "供其他 Agent 读取与评审。重复使用同一 key 会版本递增; "
            "不同发送者对同一 key 写入不同值会触发冲突检测。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "key": string_prop("笔记标识 (如 'design:api' / 'doc:T1')"),
                "note": string_prop("笔记内容 (文本)"),
                "sender": string_prop("发送者标识 (可选, 默认 'agent')"),
            },
            "required": ["key", "note"],
        },
        handler=_team_share_note_handler,
        group="team",
        read_only=False,
    )


# ================================================================ team_post_update


def _team_post_update_handler(
    ctx: ToolContext, sender: str = "", update: str = "",
    priority: str = "normal", recipient: str = "*",
    **_kwargs: Any,
) -> str:
    if not sender:
        return "[错误] team_post_update 需要 sender 参数"
    if not update:
        return "[错误] team_post_update 需要 update 参数"
    prio = _PRIORITY_MAP.get(str(priority).lower(), MessagePriority.NORMAL)
    recipient = recipient or "*"
    try:
        protocol = _require_protocol(ctx)
        # 协议的 write() 始终广播 (recipient="*"), 无定向路由参数;
        # 这里把 recipient 嵌入 metadata 与 value 前缀, 保证路由信息不丢失,
        # 读取端可据此过滤或提示定向性。
        routed_update = update if recipient == "*" else f"[→ {recipient}] {update}"
        protocol.write(
            key="team:updates", value=routed_update, sender=sender,
            msg_type=MessageType.STATUS, priority=prio,
            metadata={"recipient": recipient, "priority": prio.value},
        )
        return f"已发布更新 (priority={prio.value}, → {recipient})"
    except Exception as exc:  # noqa: BLE001
        return f"[错误] 发布更新失败: {type(exc).__name__}: {exc}"


def build_team_post_update_tool() -> Tool:
    return Tool(
        name="team_post_update",
        description=(
            "向团队广播一条状态/进度更新 (STATUS 类型), 写入 'team:updates' 黑板键。"
            "priority 可选 low/normal/high/urgent; recipient 默认 '*' (全员广播), "
            "填具体角色/Agent ID (如 'planner'/'reviewer') 表示定向通知。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "sender": string_prop("发送者标识 (必填, 如 'planner'/'worker')"),
                "update": string_prop("更新内容 (状态/进度文本)"),
                "priority": {
                    "type": "string",
                    "enum": list(_PRIORITY_MAP.keys()),
                    "description": "优先级 (默认 normal)",
                },
                "recipient": string_prop(
                    "接收者标识 ('*' 广播 或 具体 Agent ID; 默认 '*')"
                ),
            },
            "required": ["sender", "update"],
        },
        handler=_team_post_update_handler,
        group="team",
        read_only=False,
    )


# ================================================================ team_read_updates


def _format_msg(m: Any) -> str:
    """把一条 CollabMessage 压缩成单行摘要。"""
    ts = ""
    try:
        import time as _time
        ts = _time.strftime("%H:%M:%S", _time.localtime(m.timestamp))
    except Exception:  # noqa: BLE001
        ts = "?"
    val = str(m.value).replace("\n", " ")[:200]
    recipient = ""
    try:
        rcpt = (getattr(m, "metadata", None) or {}).get("recipient")
        if rcpt and rcpt != "*":
            recipient = f" → {rcpt}"
    except Exception as exc:  # noqa: BLE001
        log.warning("_format_msg(): 非致命异常已忽略(设计内降级, 不改控制流): %s", exc)
        pass
    return (
        f"[{ts}] {m.sender} ({m.msg_type.value}/{m.priority.value}"
        f"{recipient}) {m.key} (v{m.version}): {val}"
    )


def _team_read_updates_handler(
    ctx: ToolContext, key: str = "", limit: int = 20, msg_type: str = "all",
    requester: str = "agent", **_kwargs: Any,
) -> str:
    try:
        protocol = _require_protocol(ctx)
        if key:
            # 读指定键的最新值
            value = protocol.read(key, requester=requester or "agent")
            if value is None:
                return f"(黑板暂无 {key})"
            version = protocol.read_version(key)
            return f"[{key}] (v{version}): {str(value)[:1000]}"
        # 否则按类型拉取最近消息
        mt = str(msg_type).lower()
        types: tuple = ()
        if mt == "note":
            types = _NOTE_TYPES
        elif mt == "update":
            types = _UPDATE_TYPES
        msgs: List[Any] = []
        if types:
            for t in types:
                msgs.extend(protocol.get_messages(msg_type=t, limit=limit))
            msgs.sort(key=lambda m: m.timestamp, reverse=True)
            msgs = msgs[:limit]
        else:
            msgs = protocol.get_messages(limit=limit)
        if not msgs:
            return "(黑板暂无消息)"
        return "\n".join(_format_msg(m) for m in msgs)
    except Exception as exc:  # noqa: BLE001
        return f"[错误] 读取更新失败: {type(exc).__name__}: {exc}"


def build_team_read_updates_tool() -> Tool:
    return Tool(
        name="team_read_updates",
        description=(
            "读取团队黑板上的最近消息/笔记 (默认返回最近 20 条压缩摘要)。"
            "给 key 参数则只读该键的最新值; msg_type 可选 "
            "'note' (ARTIFACT 笔记) / 'update' (STATUS/PROGRESS 更新) / 'all' (默认)。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "key": string_prop("仅读该键的最新值 (可选)"),
                "limit": {
                    "type": "integer",
                    "description": "最多返回的条数 (默认 20)",
                },
                "msg_type": {
                    "type": "string",
                    "enum": ["note", "update", "all"],
                    "description": "消息类型过滤 (默认 all)",
                },
                "requester": string_prop("请求者标识 (可选, 默认 'agent')"),
            },
        },
        handler=_team_read_updates_handler,
        group="team",
        read_only=True,
    )


# ================================================================ team_list_members


def _team_list_members_handler(
    ctx: ToolContext, limit: int = 100, **_kwargs: Any,
) -> str:
    try:
        protocol = _require_protocol(ctx)
        msgs = protocol.get_messages(limit=limit)
        seen: List[str] = []
        for m in msgs:
            s = m.sender
            if not s or s == _RESERVED_SENDER or s in seen:
                continue
            seen.append(s)
        if not seen:
            return "(黑板暂无成员)"
        return f"团队成员 ({len(seen)}): {', '.join(seen)}"
    except Exception as exc:  # noqa: BLE001
        return f"[错误] 列出成员失败: {type(exc).__name__}: {exc}"


def build_team_list_members_tool() -> Tool:
    return Tool(
        name="team_list_members",
        description=(
            "列出最近在团队黑板上写入过消息的成员 (按消息历史去重, 排除系统标识)。"
            "用于确认哪些 Agent 已加入协作、当前有哪些角色在线。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "扫描最近多少条消息以提取成员 (默认 100)",
                },
            },
        },
        handler=_team_list_members_handler,
        group="team",
        read_only=True,
    )


# ================================================================ 插件


class TeamToolPlugin(Plugin):
    """团队协作工具插件: 把 4 个 team_* 工具注册到工具注册表。"""

    name = "tools.team"
    provides = ["tools.team"]
    requires = ["tool_registry"]

    def activate(self, kernel: Kernel) -> None:
        registry = kernel.require("tool_registry")
        registry.register(build_team_share_note_tool())
        registry.register(build_team_post_update_tool())
        registry.register(build_team_read_updates_tool())
        registry.register(build_team_list_members_tool())
