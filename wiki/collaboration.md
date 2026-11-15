# 多 Agent 协作（Swarm / Collaboration）

> 本条目对应 `tuan_cli/core/swarm.py`、`tuan_cli/core/collaboration_protocol.py`。

## 是什么

青小团的多 Agent 协作协议：

- **Swarm**（`core/swarm.py`）：群组编排，多个 Agent 并行/协作。
- **Collaboration Protocol**（`core/collaboration_protocol.py`）：协作消息协议（角色、消息、黑板）。

## 为什么

让青小团不只"一个 Agent 干活"，而是"一群 Agent 分工协作"，覆盖并行任务、角色分工、黑板共享。

## 关键文件

| 文件 | 职责 |
|---|---|
| `core/swarm.py` | 群组编排 |
| `core/collaboration_protocol.py` | 协作协议 |

## 卖点

- Swarm + 协作协议齐备（与 orchestration 层联动）。
- 黑板快照支持群组状态持久化。

## 局限

- 协作协议为单机语义（无分布式锁）。
