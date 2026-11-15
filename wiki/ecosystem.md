# 生态与互操作（MCP / ACP / 多引擎）

> 本条目对应 `tuan_cli/runtime/mcp/`、`tuan_cli/runtime/acp/`、`tuan_cli/ecosystem/`、`tuan_cli/agents/`。

## 是什么

青小团的生态互操作层，融合 MCP / ACP / Agent-of-Agents 三种理念：

- **MCP 接入**（`runtime/mcp/`）：客户端协议接入外部工具生态，`tools/mcp/policy.py` 做工具级策略（`run_shell` 经 `assess_command` + `plan_egress` + 净化环境）。
- **ACP 接入**（`runtime/acp/`，4 文件/529 行）：客户端/服务端握手语义（`acp/protocol.py`、`acp/server.py`、`acp/version.py`）。
- **Agent-of-Agents 派发**（`agents/`，14 文件/759 行）：五适配器（DeepSeek Harness / Kimi Code / Claude Code / Codex / Hermes）+ mode/health 路由（`agents/router.py`、`web/dispatch_server.py`）。
- **生态桥**（`ecosystem/`，9 文件/1753 行）：多引擎隔离与互操作。

## 为什么

让青小团不是孤立 CLI，而是能**接入任何 MCP 服务器、通过 ACP 与其它宿主握手、作为 Agent-of-Agents 派发到多个后端**的生态节点。

## 关键文件

| 文件 | 职责 |
|---|---|
| `runtime/mcp/` | MCP 客户端协议 |
| `runtime/acp/bridge.py` | ACP 桥（elicitation RPC 携带会话 owner） |
| `agents/router.py` | 五适配器路由 |
| `agents/adapters/*.py` | 各引擎适配器 |
| `ecosystem/` | 多引擎隔离 |
| `tools/mcp/policy.py` | MCP 工具安全策略 |

## 卖点

- MCP 工具经安全滤网（run_shell 走 assess_command + plan_egress + 净化环境）。
- ACP 桥 elicitation RPC 用 `_resolve_owner`（显式 owner → ctx 句柄 → contextvar）携带会话标识。
- 五适配器 + mode/health 路由，Agent-of-Agents 派发完整。

## 局限

- MCP 服务器进程生命周期管理依赖外部进程（偶发争用）。
- 适配器质量参差（Claude Code 适配器对齐度高，其它按需）。
