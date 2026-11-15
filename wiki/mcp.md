# MCP 接入

> 本条目对应 `tuan_cli/runtime/mcp/`、`tuan_cli/tools/mcp/policy.py`。

## 是什么

青小团的 **MCP 客户端协议接入层**：

- `runtime/mcp/`：MCP 客户端协议（连接、工具发现、调用）。
- `tools/mcp/policy.py`：MCP 工具级安全策略（`run_shell` 经 `assess_command` + `plan_egress` + 净化环境）。

## 为什么

让青小团**接入任何 MCP 服务器**的工具生态，而非只用内置工具。MCP 工具执行前必须过安全滤网。

## 关键文件

| 文件 | 职责 |
|---|---|
| `runtime/mcp/` | MCP 客户端协议 |
| `tools/mcp/policy.py` | 工具级安全策略 |

## 卖点

- MCP 工具经安全滤网（run_shell 走 assess_command + plan_egress + 净化环境）。
- MCP/ACP 互操作已完整（诊断 2026-11-15 核实）。

## 局限

- MCP 服务器进程生命周期管理依赖外部进程（偶发争用）。
