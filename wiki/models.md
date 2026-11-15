# Provider 热切换与模型路由

> 本条目对应 `tuan_cli/models/`、`tuan_cli/core/agent_routing.py`、`tuan_cli/core/agent_types.py`。

## 是什么

**58 个 Provider（模型/后端）注册表** + 热切换 + 路由：

- `models/`（15 文件 / 4744 行）：Provider 目录、连接信息、预设 profile、密钥管理。
- `core/agent_routing.py`：按难度/类型路由到子代理。
- `core/agent_types.py`：AgentType 定义，`_parse_agent_file` 解析自定义 `agents/*.md`。

## 为什么

model-agnostic 是核心卖点之一：不锁死单一模型商，用户可在 DeepSeek / Kimi / Claude / Codex / Hermes / Qwen / Gemini / Doubao 等之间热切换。

## 关键文件

| 文件 | 职责 |
|---|---|
| `models/` | Provider 注册表（58 个） |
| `core/agent_routing.py` | 路由逻辑 |
| `core/agent_types.py` | 类型定义 + 自定义文件解析 |
| `config/defaults.py` | 默认配置（含 provider 预设） |
| `config/security_schema.py` | 密钥/安全 schema |

## 卖点

- 58 Provider 覆盖主流模型商与本地引擎（DeepSeek Harness / Kimi Code / Claude Code / Codex / Hermes / Qwen / Gemini / Doubao / OpenCode / Aider 等）。
- Provider 连接信息 `_autofill_preset_fields` 自动补全（只写 provider 名即可）。
- 密钥管理不落明文（环境变量/安全 schema）。

## 局限

- Provider 路由按难度/类型只读查询，无"按角色选择 spawn"（`cmd_subagent` 仅 types/refresh）。
- 密钥策略依赖环境变量约定，无内置保险库。
