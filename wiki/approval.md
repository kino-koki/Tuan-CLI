# 审批与策略（人机协同）

> 本条目对应 `tuan_cli/ui/approval_policy.py`、`tuan_cli/sandbox/unattended.py`、`tuan_cli/tools/mcp/policy.py`。

## 是什么

AGENT-EVOLUTION-ROADMAP 阶段 C：把审批从"二选一确认"升级为**策略可编程审批树 + 审计联动**：

- **ApprovalTree**：按风险等级分层策略（默认 / 白名单 / 需人工 / 硬红线），可编程规则（`ui/approval_policy.py`）。
- **审计联动**：每次审批决策写入审计事件流（who/what/decision/timestamp），可追溯。
- **审批策略可配置**：`permissions.approval_policy` 配置节，支持自定义规则 DSL。
- **unattended 模式**（`sandbox/unattended.py`）：无人值守审批。
- **MCP 工具策略**（`tools/mcp/policy.py`）：MCP 工具级审批。

## 为什么

"世界最强"的人机协同不是"全自动"或"全人工"，而是**风险自适应**：低风险白名单直通、中风险需人工、高风险硬红线拦截，且每个决策可审计追溯。

## 关键文件

| 文件 | 职责 |
|---|---|
| `ui/approval_policy.py` | 审批树 |
| `sandbox/unattended.py` | 无人值守 |
| `tools/mcp/policy.py` | MCP 工具策略 |
| `config/security_schema.py` | 安全 schema（含 approval_policy） |

## 卖点

- 审批树分层路由 + 规则覆盖 + 审计写入（13 个审批树测试通过，阶段 C 验收）。
- 重入 fail-closed（决策类不放行）。
- 白名单 / 需人工 / 硬红线分层清晰。

## 局限

- 审批树规则 DSL 为内部实现，无外部规则语言文档化。
- 无人值守模式默认关闭（需显式启用）。
