# 青小团互操作层状态追踪（历史归档）

## 原则

`tuan_cli/ports/` 是青小团与外部系统交换数据的**互操作层**，属独立命名空间，
不影响主模块。代码为 Python 独立自研实现，对相关上游的公开协议/接口做对齐。

- 原生默认零破坏：`ports/` 是独立命名空间，不改动现有 `tuan_cli/` 模块。
- 每项互操作层带 pytest 测试、可 `py_compile`、可 import。
- 仅实现纯逻辑；对强依赖 node/React/原生绑定的部分标注 skip。
- **归属声明**：所有从上游 TypeScript 参考实现移植的模块，均在各文件头注释中
  标注 `Ported from <file>` 或 `Mirrors <module>`，完整归属清单见仓库根
  [NOTICE](../../NOTICE)。

## 历史说明

> **2026-08-29**：早期有一条「上游 TS 源码 → Python 1:1 移植」工作流，
> 后经评估整体终止——多余 8 个 TS 包（acp-adapter / acp-server / klient /
> node-sdk / agent-core / agent-core-v2 / minidb / kap-server，约 200k+ TS 行）
> 对 Python CLI 无实质影响，一律**不再移植**。
>
> 已移植并保留的模块（`ports/protocol/`、`ports/oauth/`、`ports/migration_legacy/`、
> `ports/transcript/`、`ports/telemetry/`、`ports/kaos/`）均为对上游**公开协议或
> 数据格式**的对齐实现，不是对上游产品功能的复刻。归属已在 NOTICE 中逐条披露。
>
> **2026-09-26**：上游 TS 参考树已从未跟踪状态中移除；删除脚本 `delete-kimi-ts.ps1`
> 不再保留于仓库中。原 TS 源码目录 `.trash-上游 TS 源码树/` 已清理。

## 能力层 / 互操作层（Python 落地、测试全绿）

| 能力层 | Python 位置 | 测试 | 归属 |
|---|---|---|---|
| protocol | tuan_cli/ports/protocol | 32 passed | 对齐上游 JSON-RPC/NDJSON 消息格式 |
| transcript | tuan_cli/ports/transcript | 9 passed | 对齐上游会话转录格式 |
| telemetry | tuan_cli/ports/telemetry | 26 passed | 对齐上游遥测事件协议 |
| kaos | tuan_cli/ports/kaos | 46 passed | 对齐上游 Kaos 接口 |
| oauth | tuan_cli/ports/oauth | 34 passed | 对齐上游 OAuth/identity 协议 |
| migration-legacy | tuan_cli/ports/migration_legacy | 40 passed | 对齐上游 kimi-cli 持久化格式 |

**合计：6 个互操作层落地，相关测试 187 passed + 1 skipped。**

## 未实现且已归档

`acp-adapter, acp-server, klient, node-sdk, agent-core, agent-core-v2, minidb,
kap-server`（大型/独立产品/原生绑定），以及明确不移植的 `pi-tui`（TUI/React
前端）、`tree-sitter-bash`（原生绑定）。其中 agent-core / acp 相关能力已由
`tuan_cli/kernel`、`tuan_cli/acp`、`tuan_cli/tools` 等自研模块覆盖。

图例：✅ 完成并测试  ⛔ 不移植/已放弃
