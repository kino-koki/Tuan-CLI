# CLI 命令面

> 本条目对应 `tuan_cli/cli/`（127 文件/29500 行）。

## 是什么

青小团的命令面分三层：

- **顶层 CLI 子命令**：**92 个**（`parser_commands.py` 顶层 `sub.add_parser`；含嵌套共 194 个，面更广）。
- **斜杠 `/` 命令**：**91 个**（`SLASH_COMMAND_NAMES` 唯一命令，2026-11-22 补 `/watch` `/reach` `/approvals` 后核实；权威计数 `python scripts/count_slash_commands.py`），`_handle_slash` elif 分支对照：清单无分支 = 0（全部接线）。
- **子命令分组**：`cli/subcommands/`（安全、内核、账本、会话、工作区、信任策略等）。

## 为什么

命令面是 Agent 系统的"可发现性"入口。92 顶层子命令（含嵌套共 194 个）覆盖安全、模型、MCP、cron、subagent、审批、编排、演化、遥测、审计等；91 斜杠命令对标 Claude Code 的 `/` 交互。

## 关键文件

| 文件 | 职责 |
|---|---|
| `cli/parser_commands.py` | 顶层命令注册（92 顶层 + 分片） |
| `cli/cmd_slash.py` | 斜杠命令分发（91） |
| `cli/cmd_slash_claude.py` | Claude 风格斜杠（fork/branch/cd/btw/copy/tasks/theme/loop/review 等） |
| `cli/cmd_evolve.py` | 进化闭环命令 |
| `cli/cmd_agents_view.py` | /agents 管理界面 |
| `cli/cmd_subagent.py` | subagent 类型注册表 |
| `cli/cmd_harden.py` | /security-review 硬化 |

## 卖点

- 92 顶层子命令（含嵌套 194）+ 91 斜杠命令，全部接线（诊断核实无"已实现但未接线"）。
- `/agents` CLI **与斜杠入口均实现**（`tuan agents` + `/agents`，view/watch/kill/attach，`cmd_agents_view.py:261-294`）。
- `/review --security` 真接线（categories="security"）。
- `/help` 输出与 `SLASH_COMMAND_NAMES` 全量同步（91 命令全覆盖，含 `/teamlead`/`/team` 补齐）。
- v0.5.0 新增能力层斜杠命令：`/watch`（字幕优先 + 抽帧看视频）、`/reach`（多平台联网读取，含 `channels` / `doctor`）、`/approvals`（read-only / auto / full-access 三档审批）。

## 局限

- `subagent` 仅"按难度/类型"自动路由（按角色选择已有 Role 模式，见 ecosystem.md，但无独立 `/subagent --role` 开关）。
- `--input-format stream-json` 仅 headless 驱动器支持，主 CLI 无独立分支。
