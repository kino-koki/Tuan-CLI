# 生态互操作层（Ecosystem Bridge）

> 青小团 ⇄ Claude Code ⇄ Hermes Agent —— 一个 Harness，直接用遍三个生态的积累。

青小团不满足于「又一个 Agent CLI」。除了自身的原生能力（微内核 + 插件、四道闸安全、
事务化撤销、技能自进化），它把自己定位为 **Agent 生态的互操作枢纽**：在一台机器上
同时装有 Claude Code（Anthropic）与 Hermes Agent（Nous Research）时，三方积累的
可移植资产——技能、命名 Agent、长期记忆、人格、上下文文件、MCP server 配置——
都能在**任意一方**里直接使用，不需要重复配置、重复维护。

```text
            ┌─────────────────────────────────────────────┐
            │                青小团 qxt                     │
            │        (生态互操作枢纽 / Ecosystem Hub)        │
            │                                               │
            │  原生: 微内核+插件 · 四道闸安全 · 事务撤销      │
            ├───────────────────────────────────────────────┤
            │  import/export:  技能·Agent·记忆·SOUL·MCP配置   │
            │  运行时发现:     会话自动挂载双方技能/子代理     │
            │  MCP Server:    qxt ecosystem serve           │
            │  委派工具:       claude_code_run / hermes_run  │
            └───────────────┬───────────────┬───────────────┘
                            │               │
              ┌─────────────▼─────┐   ┌─────▼─────────────┐
              │  Claude Code      │   │  Hermes Agent     │
              │  .claude/skills   │   │  ~/.hermes/skills │
              │  .claude/agents   │   │  MEMORY.md/USER.md│
              │  .mcp.json        │   │  SOUL.md          │
              │  CLAUDE.md        │   │  AGENTS.md/CLAUDE │
              └───────────────────┘   └───────────────────┘
```

## 为什么做这件事

三个 Agent 生态的资产格式**高度同构**，但彼此默认不互相发现：

| 资产 | Claude Code | Hermes Agent | 青小团 qxt |
| --- | --- | --- | --- |
| 技能 | `.claude/skills/**/SKILL.md` | `~/.hermes/skills/**/SKILL.md` | `SKILL.md` 开放标准（三方同源） |
| 命名 Agent | `.claude/agents/*.md` | （Bot Mode，形态不同） | `.claude/agents/*.md`（同格式） |
| 长期记忆 | 项目 memory/ | `MEMORY.md` + `USER.md`（`§` 分隔） | `memories/MEMORY.md` + `USER.md` |
| 人格 | — | `SOUL.md` | `SOUL.md`（首段系统提示） |
| 上下文文件 | `CLAUDE.md` | `AGENTS.md` / `CLAUDE.md` | `QXT.md` / `AGENTS.md` / `CLAUDE.md` |
| MCP 配置 | `.mcp.json` | `config.yaml` 的 `mcp.servers` | `mcp.servers` |

既然 SKILL.md 是三方共用的开放标准、agents 是同一份 Markdown+frontmatter、
记忆/人格是同名同构文件，**互操作的成本极低、收益极高**——这正是本层存在的理由。

## 快速开始

```bash
# 1. 看看本机装了哪些生态、各有多少资产（只读）
qxt ecosystem scan

# 2. 把 Claude Code + Hermes 的全部技能/子代理/记忆/SOUL/MCP 配置并入青小团
qxt ecosystem import all          # 按来源细分: --from claude | --from hermes
qxt ecosystem import memory       # 只导记忆（含 Hermes SOUL.md → qxt SOUL.md）
qxt ecosystem import agents       # 只导 Claude Code 子代理
qxt ecosystem import mcp          # 把对方配好的 MCP server 并入 qxt

# 3. 把青小团的资产导出给对方
qxt ecosystem export skills --to claude    # → .claude/skills
qxt ecosystem export skills --to hermes    # → ~/.hermes/skills
qxt ecosystem export agents --to claude    # → .claude/agents
qxt ecosystem export memory --to hermes    # → ~/.hermes/memories

# 4. 反向挂载：让 Claude Code / Hermes 直接调用青小团（MCP）
qxt ecosystem link               # 写 .mcp.json + 打印 hermes 接入命令
qxt ecosystem link --apply       # 同时写入 Hermes config.yaml

# 5. 会话内委派（模型会自动用，也可以手动触发）
#    claude_code_run / hermes_run 工具：把任务交给对方完整环境执行
```

## 运行时自动发现（零配置即生效）

除手动 `import/export` 外，青小团的会话**默认自动发现**对方生态的本机资产：

- **技能**：`SkillManager` 的搜索目录已扩展——
  `项目/.claude/skills`、`~/.claude/skills`、`~/.hermes/skills`、`~/.hermes/profiles/*/skills`
  按「项目级 > 用户级 > 生态级 > 额外级 > 内置级」合并，同名高优先级覆盖。
  也就是说：Claude Code 装过的技能、Hermes 蒸馏出的技能，青小团会话里直接可用；
  青小团技能导出后，另外两个生态也直接可用。
- **命名 Agent**：`agents_registry` 三层发现本就包含 `项目/.claude/agents` 与
  `~/.claude/agents`——Claude Code 的子代理在青小团里就是同名 Agent。
- **上下文文件**：`QXT.md` / `AGENTS.md` / `CLAUDE.md` 分层加载（Claude Code 与
  Hermes 都读 CLAUDE.md / AGENTS.md，三方共用同一份项目指令）。
- **记忆**：qxt 的记忆文件就是 Hermes 风格布局（`MEMORY.md` + `USER.md`），
  导入后即合并，导出即同步。

开关（`~/.qingxiaotuan/config.yaml`）：

```yaml
ecosystem:
  claude_code:
    enabled: true        # 关闭后不再自动发现 .claude/skills
  hermes:
    enabled: true        # 关闭后不再自动发现 ~/.hermes/skills
    home: ""             # 显式指定 Hermes 主目录（空=自动探测 $HERMES_HOME / ~/.hermes）
  mcp:
    allow_dangerous_tools: false   # 对外部 MCP 暴露 run_shell（默认关，fail-closed）
```

## MCP Server（被对方调用）

`qxt ecosystem serve` 以 MCP stdio server 运行（JSON-RPC 2.0 换行帧，零依赖，
与 qxt 自带 MCP 客户端同构），对外暴露一组 **`qxt_*` 工具**：

| 工具 | 说明 | 危险 |
| --- | --- | --- |
| `qxt_status` | 生态桥接状态 + 双方资产计数（JSON） | 只读 |
| `qxt_run` | 把任务派给青小团 headless 执行（内部走完整四道闸） | 受控 |
| `memory_search` | 检索 qxt 跨会话记忆（含导入的 Hermes 记忆） | 只读 |
| `memory_write` | 往 qxt 长期记忆写一条事实 | 写记忆 |
| `skill_list` / `skill_read` | 技能清单 / 完整 SKILL.md 正文 | 只读 |
| `agent_list` | 命名 Agent 清单（含 Claude Code 子代理） | 只读 |
| `context_files` | 项目上下文文件 + SOUL.md 状态 | 只读 |
| `run_shell` | shell 执行（**默认不暴露**，需 `allow_dangerous_tools=true`） | 危险 |

接入方式：

```bash
# Claude Code（项目级）：qxt ecosystem link 已写好 .mcp.json，等价于：
# claude mcp add qxt -- qxt ecosystem serve

# Hermes：把 qxt 注册为 MCP server（qxt ecosystem link --apply 自动写入）
# hermes config set mcp.servers.qxt.command "qxt"
# hermes config set mcp.servers.qxt.args '["ecosystem","serve"]'
```

之后在 Claude Code / Hermes 会话里，模型就能直接调用青小团的记忆、技能与
headless 执行能力——**青小团成为另外两个生态的「能力后端」**。

## 委派工具（青小团调用对方）

`EcosystemPlugin` 在会话里注册两个委派工具（对应 CLI 存在时才注册）：

- `claude_code_run(task)`：`claude -p --output-format text` —— 用 Claude Code 的
  完整配置/记忆/技能/MCP 环境执行任务；
- `hermes_run(task)`：`hermes chat -q` —— 用 Hermes 的记忆/技能/cron 环境执行。

安全口径：参数数组直传（不经 shell）、超时上限、输出截断、工具标记 dangerous
（触发确认流程）。**任务文本原样传给对方进程**，不经 shell，防注入。

## 安全设计

- **fail-closed**：`run_shell` 等危险工具默认不暴露给外部 MCP；`allow_dangerous_tools`
  开启后仍由 qxt 安全引擎判定（硬红线一律拒绝，高风险命令拒绝自动执行）。
- **密钥不搬运**：MCP 配置互导时，含 `secret/token/password/api_key/key` 的
  env 值一律替换为占位符，绝不明文导出。
- **去重幂等**：导入同名资产默认跳过（`--force` 覆盖）；记忆按首行去重；
  MCP server 按名合并。
- **只读盘点**：`qxt ecosystem scan/status` 不写任何文件。

## 目录结构

```text
qingxiaotuan/ecosystem/
├── __init__.py          # 包说明 + 版本
├── detect.py            # 生态探测：定位双方 CLI/主目录 + 资产盘点（纯函数）
├── skills_bridge.py     # 技能双向搬运（SKILL.md 开放标准）
├── agents_bridge.py     # 命名 Agent 双向同步（.claude/agents）
├── memory_bridge.py     # 记忆/人格互通（MEMORY.md/USER.md/SOUL.md）
├── mcp_import.py        # MCP 配置互导（.mcp.json / config.yaml ⇄ qxt）
├── mcp_server.py        # MCP Server：qxt ecosystem serve
└── invoke.py            # 委派工具插件（claude_code_run / hermes_run）
```

测试：`tests/test_ecosystem.py`（21 项：探测/桥接/协议/门禁）+ `tests/test_ecosystem_cli.py`。
