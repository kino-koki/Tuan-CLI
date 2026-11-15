# Agent-of-Agents 派发（agents）

> 本条目对应 `tuan_cli/agents/`（14 文件/759 行）。

## 是什么

青小团的 **Agent-of-Agents 派发层**：

- `agents/router.py`：五适配器路由（DeepSeek Harness / Kimi Code / Claude Code / Codex / Hermes）+ mode/health 路由。
- `agents/adapters/*.py`：各引擎适配器。
- `agents/factory.py`：Agent 工厂。
- `agents/types.py`：类型定义。
- `web/dispatch_server.py`：派发服务器（mode/health 路由）。

## 为什么

让青小团**作为一个超级 Agent 派发到多个后端**，而非只能连一个模型。mode/health 路由按会话模式与引擎健康动态选择。

## 关键文件

| 文件 | 职责 |
|---|---|
| `agents/router.py` | 路由 |
| `agents/adapters/*.py` | 适配器 |
| `agents/factory.py` | 工厂 |
| `web/dispatch_server.py` | 派发服务器 |

## 卖点

- 五适配器 + mode/health 路由齐备。
- `/superagent` `/subagent` 斜杠命令接线。
- `cmd_agents_view` 提供 view/watch/list/kill/attach（CLI）。

## 局限

- 斜杠 `/agents` 不在 SLASH_COMMAND_NAMES（仅 CLI `tuan agents`）。
- 适配器质量参差（Claude Code 对齐度高，其它按需）。
