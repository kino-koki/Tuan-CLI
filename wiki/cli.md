# CLI 命令面

> 本条目对应 `tuan_cli/cli/`（127 文件/29500 行）。

## 是什么

青小团的命令面分三层：

- **顶层 CLI 子命令**：**156 个**（`parser_commands.py` 顶层 `sub.add_parser`，`set_defaults(func=...)` 引用 52 个 func，逐一反查全部有定义）。
- **斜杠 `/` 命令**：**82 个**（`SLASH_COMMAND_NAMES` 唯一命令，`cmd_slash.py:147`），`_handle_slash` elif 分支对照：清单无分支 = 0（全部接线）。
- **子命令分组**：`cli/subcommands/`（安全、内核、账本、会话、工作区、信任策略等）。

## 为什么

命令面是 Agent 系统的"可发现性"入口。156 子命令覆盖安全、模型、MCP、cron、subagent、审批、编排、演化、遥测、审计等；82 斜杠命令对标 Claude Code 的 `/` 交互。

## 关键文件

| 文件 | 职责 |
|---|---|
| `cli/parser_commands.py` | 顶层命令注册（156） |
| `cli/cmd_slash.py` | 斜杠命令分发（82） |
| `cli/cmd_slash_claude.py` | Claude 风格斜杠（fork/branch/cd/btw/copy/tasks/theme/loop/review 等） |
| `cli/cmd_evolve.py` | 进化闭环命令 |
| `cli/cmd_agents_view.py` | /agents 管理界面 |
| `cli/cmd_subagent.py` | subagent 类型注册表 |
| `cli/cmd_harden.py` | /security-review 硬化 |

## 卖点

- 156 子命令 + 82 斜杠命令，全部接线（诊断核实无"已实现但未接线"）。
- `/agents` CLI **与斜杠入口均实现**（`tuan agents` + `/agents`，view/watch/kill/attach，`cmd_agents_view.py:261-294`）。
- `/review --security` 真接线（categories="security"）。
- `/help` 输出与 `SLASH_COMMAND_NAMES` 全量同步（82 命令全覆盖，含 `/teamlead`/`/team` 补齐）。

## 局限

- `subagent` 仅"按难度/类型"自动路由（按角色选择已有 Role 模式，见 ecosystem.md，但无独立 `/subagent --role` 开关）。
- `--input-format stream-json` 仅 headless 驱动器支持，主 CLI 无独立分支。
