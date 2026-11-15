# 三层记忆与上下文工程

> 本条目对应 `tuan_cli/memory/`（6 文件/1285 行）、`tuan_cli/context/`（6 文件/1058 行）、`tuan_cli/session/`。

## 是什么

Hermes 理念的**三层记忆** + 上下文工程：

- **短期记忆**：当前会话消息窗口。
- **中期记忆**：跨会话的会话摘要/工作区状态。
- **长期记忆**：持久化的知识/偏好（`memory/`）。
- **上下文工程**（`context/`）：`manager.py` 的 `compact_if_needed`（5 次迭代上限 + 融合单趟成形 + dedupe 可选，`manager.py:145-158`）、`indexer.py` 全量索引（进程级缓存 `if self._cache and not force`）、`fast_index.py` 增量逻辑、`compaction_fusion.py` 融合。
- **会话与快照**（`session/`）：会话生命周期、断点恢复（`headless_resume`）。

## 为什么

长对话会撑爆上下文窗口。三层记忆让"重要信息长期留存、近期信息精确回忆"，上下文工程用 compaction + 融合控制窗口，让 Agent 在长任务中保持质量。

## 关键文件

| 文件 | 职责 |
|---|---|
| `memory/` | 三层记忆 |
| `context/manager.py` | 上下文管理 + compaction |
| `context/indexer.py` | 上下文索引（进程级缓存） |
| `context/fast_index.py` | 快速索引（增量逻辑） |
| `context/compaction_fusion.py` | 融合/紧凑 |
| `session/` | 会话生命周期 |

## 卖点

- compaction 触发健全（5 次上限，无 O(n²) 热点，`estimate_messages` 估算合理）。
- 三层记忆覆盖短期/中期/长期。
- 会话断点恢复（headless_resume）。

## 局限

- `indexer.py` 与 `fast_index.py` 都**非增量持久化**：indexer 每次会话重建，未持久化缓存；fast_index 有增量逻辑但主路径未复用（诊断 2026-11-15）。
