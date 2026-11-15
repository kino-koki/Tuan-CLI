# 核心运行时（core）

> 本条目对应 `tuan_cli/core/`（24 文件/11516 行）。

## 是什么

青小团的**核心运行时**，汇聚主循环与基础设施：

- 主循环：ReAct / Planner-Execute / DevLoop（三主循环）。
- `core/agent.py`：Agent 主类。
- `core/agent_routing.py`、`core/agent_types.py`：路由与类型。
- `core/ledger.py`：事务账本。
- `core/kernel.py`：插件容器 + 事件总线。
- `core/orchestrator.py`：多 Agent 编排。
- `core/write_boundary.py`：写边界。
- `core/remote_control.py`：远程控制。
- `core/security_alert.py`：安全告警。
- `core/background_shell.py`：后台 shell（`_read_stream` None 防御已修）。
- `core/ipc_client.py`：IPC 客户端。
- `core/ledger.py`：/undo。
- `core/event_bus.py`：事件总线。

## 为什么

core 是青小团的中枢：主循环驱动 Agent 执行，账本保证可恢复，写边界保证安全，编排保证多 Agent。

## 关键文件

| 文件 | 职责 |
|---|---|
| `core/kernel.py` | 插件容器 + 事件总线 |
| `core/agent.py` | Agent 主类 |
| `core/ledger.py` | 事务账本 |
| `core/orchestrator.py` | 编排 |
| `core/write_boundary.py` | 写边界 |
| `core/background_shell.py` | 后台 shell |

## 卖点

- 三主循环 + 事件总线 + 账本 + 写边界 + 编排齐备。
- `background_shell._read_stream` None 防御（崩溃已修）。

## 局限

- `ipc_client._spawn_once` 全量并行偶发 60s 超时（环境相关，非稳定缺陷）。
- 事件总线 2000 条上限（有意设计）。
