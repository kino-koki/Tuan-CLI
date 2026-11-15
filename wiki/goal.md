# Goal Mode（目标驱动执行）

> 本条目对应 `tuan_cli/goal/`（4 文件/1058 行）、`tuan_cli/cli/cmd_goal.py`。

## 是什么

对标 Claude Code 的 **Goal mode**：

- `goal/`（4 文件/1058 行）：Goal 状态机、目标规划、执行跟踪。
- `cli/cmd_goal.py`：`/goal`、`/goal-plan`、`/goal-apply`、`/goal-report` 等命令。

## 为什么

让用户以"目标"而非"逐条指令"驱动 Agent：定义一个目标，Agent 自动规划、执行、跟踪进度。

## 关键文件

| 文件 | 职责 |
|---|---|
| `goal/` | Goal 状态机 |
| `cli/cmd_goal.py` | goal CLI |

## 卖点

- Goal mode 已实现（诊断 2026-11-15 核实）。
- 目标规划 + 执行跟踪齐备。

## 局限

- Goal 规划依赖模型质量，无独立求解器。
