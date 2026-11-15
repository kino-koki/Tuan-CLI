# 多 Agent 编排与故障恢复

> 本条目对应 `tuan_cli/core/orchestrator.py`、`tuan_cli/core/ledger.py`、`tuan_cli/superagent/`。

## 是什么

把会话内协作升级为**跨会话可恢复的编排层**（AGENT-EVOLUTION-ROADMAP 阶段 B）：

- **GroupState 持久化**：任务 DAG、worker 状态、黑板快照、阶段游标落盘（SQLite/JSON），`GroupStateStore` 原子写（`orchestrator.py:63-80`）。
- **DAG 断点恢复**：`resume()`（`orchestrator.py:345-348`）——未完成节点重跑、已完成节点复用结果、依赖拓扑排序。
- **失败重试/回滚**：每节点独立重试（指数退避 `orchestrator.py:294-299`），节点级失败触发依赖子树回滚（`_rollback_subtree` `265-292`）。
- **可重放编排层**：`Orchestrator` 暴露 `plan/execute/resume/rollback`，替换/增强 `cmd_dag`。

## 为什么

单 Agent 会话崩溃后无法恢复。跨会话持久化编排让"长任务中途断电 → 恢复继续"成为可能，是 Agent 系统走向生产可用的关键。

## 关键文件

| 文件 | 职责 |
|---|---|
| `core/orchestrator.py` | Orchestrator + GroupStateStore + 断点恢复/回滚 |
| `core/ledger.py` | 事务账本（与编排联动） |
| `superagent/` | 超级 Agent 派发 |
| `cli/cmd_dag.py` | `/dag` 命令 |

## 卖点

- 断点恢复 + 失败回滚 + 指数退避齐备。
- 事务账本 `/undo` 完整（undo_last/undo_file/undo_all/undo_since）。
- 12 个编排持久化测试通过（阶段 B 验收）。

## 局限

- `GroupStateStore` 默认存储引擎为 JSON/SQLite，无分布式锁（单机语义）。
- 编排层不感知外部引擎进程退出（仅内部 worker 状态）。
