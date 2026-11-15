# 上下文工程

> 本条目对应 `tuan_cli/context/`（6 文件/1058 行）。

## 是什么

青小团的**上下文管理**：

- `context/manager.py`：`compact_if_needed`（5 次迭代上限 + 融合单趟成形 + dedupe 可选，`manager.py:145-158`）、`estimate_messages` 估算。
- `context/indexer.py`：上下文索引（进程级缓存 `if self._cache and not force`，`build()` 每次会话重建）。
- `context/fast_index.py`：快速索引（增量逻辑）。
- `context/compaction_fusion.py`：融合/紧凑。
- `context/catalog.py`：上下文目录。

## 为什么

长对话会撑爆上下文窗口。compaction + 融合控制窗口，让 Agent 在长任务中保持质量。

## 关键文件

| 文件 | 职责 |
|---|---|
| `context/manager.py` | compaction |
| `context/indexer.py` | 索引 |
| `context/fast_index.py` | 快速索引 |
| `context/compaction_fusion.py` | 融合 |

## 卖点

- compaction 触发健全（5 次上限，无 O(n²) 热点）。
- 融合单趟成形 + dedupe 可选。

## 局限

- `indexer.py` 与 `fast_index.py` 都**非增量持久化**：indexer 每次会话重建，fast_index 增量逻辑未在主路径复用。
