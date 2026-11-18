# 顶级子命令精简提案（待决策 · 未实施）

> 状态：**提案，等待产品决策**。本文档只做分析，不改任何代码。
> 数据来源：`build_parser()` 实测注册表（非文档计数），见 `tests/test_command_consolidation.py` 既有回归。

## 现状

- 顶级子命令实测 **94 个**（`argparse` subparsers choices，含 1 个隐藏开发命令 `__dev_codedev`）。
- 历史精简轮次（2026-09-27，已有回归锁定）：删除/合并 12 个顶级命令
  （arch/ext/others/code-edit/impact/open/replay/trajectory/compact/bench/codedev）；
  `sessions` 曾并入 `session` 后以精简分片恢复；`mode` 删除后以五模式语义恢复。
- 命名重复：`net` 是 `network` 的显式别名（`parser_commands.py` 注释已声明等价）。

## 分族盘点（94 个按职能）

| 族 | 命令 | 数量 |
|---|---|---|
| 会话/工作区 | chat, session, sessions, checkpoint, rewind, undo, handoff, worktree, project, usercmd | 10 |
| Agent 族 | agent, agents, subagent, superagent, team, teamlead, collab | 7 |
| 安全族 | safe, safety, trust, permissions, boundary, posture, harden, integrity, security-review | 9 |
| 观测族 | obs, telemetry, cost, ledger, alerts, auditstore | 6 |
| 网络/远端 | network, net, web, webcache, offline, remote | 6 |
| 配置/生命周期 | config, setup, onboarding, migrate, upgrade, mode, models | 7 |
| 知识/技能 | memory, skill, skills, prompt, personality, roles | 6 |
| 任务/编排 | run, cron, workflow, dispatch, loop, evolve, resilience, batch, bg, auto-mode | 10 |
| 代码质量 | review, simplify, improve, verify, debug, dev | 6 |
| 数据/工具 | artifact, dag, diff, fastindex, storage, image, msg, goal | 8 |
| 平台/生态 | mcp, plugin, kernel, hooks, ecosystem, craft | 6 |
| 对齐/元 | claude, tui, tutorial, help, doctor, gh, __dev_codedev | 7 |
| 独立/横切 | acp, aggregate, commands, sandbox | 4 |

## 建议 A 档：合并（低风险，保留别名一个版本周期）

| 候选 | 并入 | 理由 |
|---|---|---|
| `net` | `network` | 已是显式别名，零新语义；正式 deprecate 后下个 major 删除 |
| `subagent` | `agent` | 同一实体两种叫法；`agent sub` 语义更清晰 |
| `superagent`, `teamlead` | `team` | 三者同管多 agent 协作，入口分裂 |
| `collab` | `team` | 同上 |
| `sessions` | `session` | 与 v0.4.0 轮方向一致；精简分片改为 `session list/rm` 子命令 |
| `webcache` | `web` | web 家族内部能力 |
| `security-review` | `review --security` 或 `safe review` | 与 review/safe 双向重叠 |
| `posture`, `boundary`, `integrity` | `safety` / `trust` 子命令 | 安全族入口过多，能力不减、入口归一 |
| `auditstore`, `alerts`, `cost`, `telemetry` | `obs` 子命令 | 观测族入口归一（能力全保留） |
| `artifact`, `dag`, `fastindex`, `storage` | `dev` / `storage` 子命令 | 纯工具能力，不需要顶级入口 |

预计 94 → **约 70** 个顶级入口；所有被并命令保留 `argparse aliases=` 一个版本周期，行为零变化。

## 建议 B 档：保留（核心面，不动）

chat / run / config / models / session / mcp / hooks / skills / skill / memory /
todo / plan / goal / workflow / cron / sandbox / safe / trust / permissions /
doctor / setup / onboarding / upgrade / migrate / tui / web / network / gh /
help / agent / agents / team / review / verify / debug / evol? 等。

## 建议 C 档：仅清理

- `__dev_codedev`：保持隐藏（已满足）；评估移入 `dev` 命名空间。

## 实施原则

1. 每一步先加 `aliases=` 兼容，再在下个版本周期删旧名；
2. `tests/test_command_consolidation.py` 同步扩展：DELETED / KEPT / ALIAS 三张表；
3. README×10 语言同步命令数；
4. 不做"静默删除"：删除前一个版本在 help 与文档标记 deprecated。

## 明确不建议动的

- `claude`（对齐态势旗舰入口）、`kernel`、`ecosystem`、`dispatch`、`handoff`：
  均为近 7 天新增能力的公开入口，精简它们会抵消刚完成的整合收益。
