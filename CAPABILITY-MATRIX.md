# 青小团 × Claude Code 核心能力对照矩阵

- 项目: 青小团（Tuan-CLI）
- 版本: v0.3.3
- 日期: 2026-10-15
- 性质: 对照 Claude Code 官方 CLI 的 10 项核心能力，对青小团现有实现逐项审计 → 找缺口 → 补齐 → 测试 → 本文档

> **后续文档（2026-11-07）**：本矩阵只覆盖 10 项核心能力。全模块对照请见
> [`CLAUDE_PARITY.md`](CLAUDE_PARITY.md) —— 锁定 Claude Code **v2.1.319**
> （2026-11-06），14 个功能域 / 99 个模块 / 12 个轮次，带运行时证据校验、
> 六个超越维度探针与 `tuan claude parity` 机器入口。本文件保留为 2026-10-15
> 的历史基线，不删除、不回改；两处口径若不一致，以新矩阵为准。

## 总览

| # | 能力（官方） | 青小团实现位置 | 复刻状态 | 本次补齐概要 |
|---|---|---|---|---|
| 1 | Subagents & 多 Agent 团队（动态生成/编排） | `core/subagents.py`、`core/agents_registry.py`、`tools/subagent_tool.py`、`cli/cmd_agents.py` | 已有 | 补"真并行"时序证明测试（3 用例） |
| 2 | Hooks 系统（事件中间件） | `hooks/manager.py`、`tools/base.py`、`arch/execution.py`、`cli/cmd_hooks.py` | 已补齐 | 修复备用执行路径硬编码工具名/忽略阻断；新增 `/hooks enable/disable`；HTTP 型 hook 测试 |
| 3 | MCP（stdio/HTTP/SSE） | `tools/mcp/`、`runtime/mcp/`、`ecosystem/mcp_server.py`、`cli/cmd_mcp_cli.py` | 已补齐 | 修复 HttpMcpClient 信封未解包（http/sse 实际不可用）；新增 `/mcp remove`；真实端到端测试 |
| 4 | Skills（可复用指令包） | `skills/manager.py`、`skills/plugin.py`、`self_improve/auto_distiller.py` | 已补齐 | 修复蒸馏落盘双层 frontmatter；运行时注入端到端测试 |
| 5 | Plan Mode（计划/执行两阶段） | `tools/base.py`、`tools/shell.py`、`tools/session_tools.py`、`cli/cmd_slash.py` | 已补齐 | 计划产物落盘存档（`.tuan/plan.md` + `plan_mode.saved` 事件） |
| 6 | Worktree 隔离（并行 Git worktree） | `core/worktree_layer.py`、`cli/cmd_worktree.py` | 已有 | 补真实分支隔离证明测试（3 用例） |
| 7 | Headless 模式（CI/CD 无 TUI 驱动） | `cli/cmd_agents.py`（cmd_run）、`cli/parser_commands.py` | 已补齐 | `tuan run` 新增 `--resume/--continue` 续会话 |
| 8 | Security Plugin（漏洞扫描） | `core/tool_executor.py`（`_security_gate_check`）、`core/security_plugin.py`、`core/secret_scanner.py` | 已有 + 已补齐 | 执行前拦截链路已接通；新增密钥泄露扫描器（扫描+修复建议+总线留痕） |
| 9 | Scheduled Tasks（定时任务） | `cron/store.py`、`cron/runner.py`、`cron/daemon.py`、`cron/schedule.py`、`cli/cmd_cron.py` | 已补齐 | 新增零依赖 5 字段 cron 表达式解析器，`add/edit --cron` 支持标准排期 |
| 10 | Agent Teams / Multi-agent Orchestration | `core/swarm.py`、`core/collaboration_protocol.py`、`core/specialized_roles.py`、`core/devloop.py` | 已补齐 | 修复 `CollaborationProtocol.compare_and_swap` 不可重入锁死锁；补协议消息流转测试 |

## 测试基线

- 改动前全量: **3117 passed / 3 failed / 7 skipped**（3 个失败为历史遗留、与本任务无关，未修）：
  - `test_cli_safe_bench_report.py::test_cmd_bench_quick_with_fake_runners`
  - `test_rewind.py::test_list_and_restore_previous`（assert 3 == 2）
  - `test_tui_fixes.py::TestTuiBridge::test_attach_ui_replaces_singleton`
- 本次新增测试文件（9 个）: `test_subagent_parallel.py`、`test_collaboration_protocol.py`、`test_plan_archive.py`、`test_headless_resume.py`、`test_hooks_http.py`、`test_mcp_e2e.py`、`test_skills_runtime_injection.py`、`test_cron_schedule.py`、`test_secret_scanner.py`
- 改动后全量: 见文末「最终全量测试结果」（由 Organizer 统一复跑）

## 逐项明细

## 1. Subagents & 多 Agent 团队（Subagents / Dynamic Sub-agent Orchestration）
- 官方行为基准（Claude Code CLI）: 主 Agent 可动态派生子代理（独立上下文/系统提示词），多个子任务可并行，结果以摘要形式结构化回传主上下文，子代理有工具白名单/资源隔离；`/agents` 可查看与管理命名子代理。
- 青小团实现位置:
  - `tuan_cli/core/subagents.py`（SubAgentPool / SubTask / SubResult，线程池并发、独立工作目录、进程沙箱两种隔离）
  - `tuan_cli/core/agents_registry.py`（`.claude/agents/*.md` 三层发现 + frontmatter 解析）
  - `tuan_cli/tools/subagent_tool.py`（`subagent` / `agents_list` 工具，命名 agent 白名单折算）
  - `tuan_cli/cli/cmd_agents.py`、`cli/cmd_agents_view.py`（`tuan agents view/list/kill/attach` 会话面板）
- 审计发现（缺口清单）:
  1. 动态创建 / 独立上下文 / 结构化回传 / 隔离 均真实存在：`_run_one_thread` 每个子任务 `create_agent(..., system_extra=...)` 拿到独立 messages；`SubResult.to_block()`/`aggregate()` 带来源标注回传；`prepare_isolated_workdir` 落 `.tuan/subagents/<id>/`，另有 process 沙箱隔离。**未发现功能性缺口**。
  2. 唯一薄弱点：既有 `test_subagents_bg.py` 的"并发"用例用无延迟 EchoModel，串行/并行耗时一样，**从未从时序上证明"真并行"**。
- 补齐内容（本次改动）: 未改产品代码（链路本就完整）；新增时序证明测试，用各 sleep 的子任务断言真并行。
- 测试: 新增 `tests/test_subagent_parallel.py`（3 用例：真并行墙钟断言、结构化来源回传、批内失败隔离）—— **3 passed**；回归 `test_subagents_bg.py`、`test_subagent_integration.py`、`test_subagent_isolation.py`、`test_agents_registry.py` 通过。
- 复刻状态: 已有（补并行时序证明测试）。

## 2. Hooks 系统（Hooks）
- 官方行为基准（Claude Code CLI）: 在 PreToolUse / PostToolUse / SessionStart / SessionEnd / UserPromptSubmit / Stop 等事件触发用户挂载的脚本；hook 用 matcher 按工具名过滤，command（shell）/http 执行，stdout 回传 decision（block / modified_args）；/hooks 可 list / enable / disable。
- 青小团实现位置: `tuan_cli/hooks/manager.py`、`tuan_cli/core/agent_hooks.py`、`tuan_cli/tools/base.py`（dispatch_result 的 _apply_pre_hooks / _exec_and_record）、`tuan_cli/arch/execution.py`、`tuan_cli/cli/cmd_hooks.py`、`tuan_cli/cli/parser_commands.py`
- 审计发现（缺口清单）:
  - PreToolUse/PostToolUse：主链路 `tools/base.py dispatch_result` 已真实挂载（真实工具名/参数/结果传入，Pre 阻断返回 denied 且 handler 不执行、改参生效）。但备用执行路径 `arch/execution.py` 把工具名硬编码为 `"tool"`、参数包成嵌套字典、且完全忽略返回的阻断决策——matcher 过滤失效、Pre 阻断不生效（真实缺口）。
  - SessionStart/SessionEnd：已在 CLI 会话边界（cmd_chat._prepare_agent + finally、cmd_agents）真实触发。
  - UserPromptSubmit：已接入 agent.run（agent.py:556），stdout 作为附加上下文注入本回合 user 消息。
  - `/hooks`：仅有 list / test，缺 enable / disable（真实缺口）。
  - command 执行有测试覆盖；http（_exec_http）实现完整但无任何测试覆盖（真实缺口）。
  - matcher 过滤（_match，支持 `*` / `|` / `!` 排除）与 decision JSON 协议（_parse_decision 兼容 decision/block/args）：已实现，未发现缺口。
- 补齐内容（本次改动）:
  - `tuan_cli/arch/execution.py`：hook 调用改为传入真实 `call.name` / `call.args`，并尊重 `HookDecision.block`（阻断即返回）与 `decision.args`（改参后再执行）。
  - `tuan_cli/cli/cmd_hooks.py` + `parser_commands.py`：新增 `tuan hooks enable` / `tuan hooks disable`，经 Config.set_user 写入 `hooks.enabled` 用户层配置。
  - 新增 `tests/test_hooks_http.py`：本地起 HTTP 端点，验证 url 型 hook 的 Pre 阻断、改参、Post 通知，以及 enable/disable 正确写配置。
- 测试: `tests/test_hooks.py` + `test_hooks_events.py` + `test_hooks_http.py` = **26 passed**。
- 复刻状态: 已补齐。

## 3. MCP（Model Context Protocol）
- 官方行为基准（Claude Code CLI）: /mcp 管理多 server；stdio（command 启动子进程）与远程 http/sse（URL）两类传输；工具以 server 名作前缀命名空间；支持状态查看、连接测试、重连；调用经安全扫描。
- 青小团实现位置: `tuan_cli/tools/mcp/`（client.py、plugin.py、multitransport.py、security.py、audit.py、sandbox.py）、`tuan_cli/runtime/mcp/`（client_http.py、client_sse.py、connection_manager.py、config.py、naming.py、types.py）、`tuan_cli/cli/cmd_mcp_cli.py`、`tuan_cli/cli/cmd_slash_mcp.py`
- 审计发现（缺口清单）:
  - stdio 传输：完整（initialize→notifications/initialized→tools/list→tools/call 握手、重试指数退避、超时、黑名单/频率/沙箱闸门），未发现缺口。
  - http/sse：经融合层 MultiTransportMCP；门控键 `fusion.mcp_multitransport` 在 plugin.py 读取默认 True（defaults.py 无 fusion 键），即**开箱即开**（注释写"默认关闭"为过时描述，行为本身已开，无需改默认值）。但既有测试全部用 fake manager/client，无真实端到端。发现真实 bug：`HttpMcpClient._rpc` 直接返回整个 JSON-RPC 信封而未解包 result，导致 tools/list、tools/call 永远拿到空 payload——**远程 http 传输实际不可用**（真实缺口）。
  - `/mcp`：有 list / add / test / tools / call / audit / security，缺 remove；且远程 http/sse server 状态不进 list（真实缺口）。
  - 命名空间 `mcp__server__tool` + 碰撞安全截断（>64 字符 FNV-1a 哈希）、重连（connection_manager.reconnect）、安全扫描（register_mcp_tool 内描述/参数注入扫描 + client 黑名单/频率/沙箱闸门）：已实现，未发现缺口。
- 补齐内容（本次改动）:
  - `tuan_cli/runtime/mcp/client_http.py`：`_rpc` 解包 JSON-RPC 信封的 result 段并处理 error（与 stdio 读循环语义对齐），SseMcpClient 继承同一修复。
  - `tuan_cli/cli/cmd_mcp_cli.py`：新增 `tuan mcp remove <name>`；list 合并显示远程 server 实时状态（endpoint/transport/tool_count）。
  - `tuan_cli/tools/mcp/plugin.py`：把融合层 MultiTransportMCP 暴露为内核服务 `mcp_remote`，供 list 读取远程 server 状态。
  - 新增 `tests/test_mcp_e2e.py`：本地起 python stdio 子进程 server 与本地 mock HTTP MCP server，各真实跑通一次握手 + tools/list + tools/call（不连任何外部服务器，fixture teardown 关闭本地服务）。
- 测试: `tests/test_mcp.py` + `test_mcp_multitransport.py` + `test_mcp_security.py` + `test_mcp_e2e.py` = **38 passed**（其中 e2e 3 passed：stdio 握手/调用、黑名单拦截、http 融合层端到端）。
- 复刻状态: 已补齐。

## 4. Skills（可复用指令包）
- 官方行为基准（Claude Code CLI）: skills 是可复用指令包：目录含 SKILL.md（frontmatter: name、description）+ 资源文件；按 description 自动发现、运行时按需加载注入；/skills 可查看。
- 青小团实现位置: `tuan_cli/skills/manager.py`、`tuan_cli/skills/plugin.py`、`tuan_cli/core/prompts.py`（build_task_context）、`tuan_cli/core/agent.py`（注入）、`tuan_cli/tools/skill_tool.py`（skill_read 按需读正文）、`tuan_cli/self_improve/auto_distiller.py`、`tuan_cli/cli/cmd_slash.py`（/skills）、`tuan_cli/cli/parser_commands.py`（tuan skill）
- 审计发现（缺口清单）:
  - 格式约定：SKILL.md + frontmatter（name、description + 超集 display_name / short_description / default_prompt / policy.allow_implicit_invocation）；单文件 .md 与目录型包 `<slug>/SKILL.md` 均支持，未发现缺口。
  - 自动发现路径：project（.tuan/.agents/.claude/skills）、user（home/skills、.agents、.claude、.hermes）、extra_dirs、builtin，同名按优先级覆盖，未发现缺口。
  - 运行时按需注入：真实存在——agent.run → build_task_context → activate_for_task（按 description/标签）→ render_for_prompt 渲染"注册表条目"注入本回合 user 消息，lazy 技能正文经 skill_read 工具按需加载（非仅静态读取）。
  - /skills：会话内 /skills（list/audit/consolidate）与 tuan skill list/show/import/audit/consolidate/lint 均存在，未发现缺口。
  - SkillDistiller 产出：经 skill_manager.save 写同一 frontmatter 格式、可 load 回读；发现小瑕疵——`_sync_to_skill_manager` 把已含内嵌 frontmatter 的 `to_skill_md()` 整段塞进 save()，落盘出现**双层 frontmatter**（真实缺口）。
- 补齐内容（本次改动）:
  - `tuan_cli/self_improve/auto_distiller.py`：同步前剥掉 `to_skill_md()` 内嵌 frontmatter，仅传正文给 save()，落盘只留一份标准 frontmatter。
  - 新增 `tests/test_skills_runtime_injection.py`：证明按 description 关键词发现 → build_task_context 渲染注册表 → agent.run 端到端把命中技能注入 user 消息，以及蒸馏产出 round-trip 可被 load() 重新加载。
- 测试: `tests/test_skill_multi_repo.py` + `test_skill_frontmatter_superset.py` + `test_skill_governance.py` + `test_skill_distillation_loop.py` + `test_distiller_loop.py` + `test_skills_runtime_injection.py` = **33 passed**（其中新增 runtime_injection 4 passed）。
- 复刻状态: 已补齐。

## 5. Plan Mode（计划/执行两阶段）
- 官方行为基准（Claude Code CLI）: `/plan` 进入只读计划阶段——只探索不改文件；产出计划后交用户确认；确认后切到执行模式按计划落地；计划可存档/回看。
- 青小团实现位置:
  - `tuan_cli/tools/base.py`（`_pre_exec_check`：plan_mode 下非 read_only 工具一律 denied）
  - `tuan_cli/tools/shell.py`（`_is_readonly_command`，写类命令在 plan 模式被硬拦）
  - `tuan_cli/tools/session_tools.py`（`enter_plan_mode`/`exit_plan_mode` 工具 + 本次新增计划存档）
  - `tuan_cli/cli/cmd_slash.py`（`/plan [on|off]` 切换）、`core/goal_mode.py`/`agent_goal.py`/`cli/cmd_slash_goal.py`（Goal 引擎，.tuan/goal.json 持久化）
- 审计发现（缺口清单）:
  1. 只读防护真实有效：`base.py:267` 对 `not tool.read_only` 返回 denied，`shell.py:527/585` 拦写类命令，`sandbox/filters.py:151` 沙箱侧同样拦截——计划阶段确实改不了文件。已有 `test_plan_mode.py` 覆盖。
  2. 两阶段切换真实：`exit_plan_mode` 提交计划文本后 `_set_plan_mode(False)`，写工具放行；`/plan` 斜杠命令与 `enter/exit_plan_mode` 工具均接线。
  3. **真实缺口**：计划产物不存档——`exit_plan_mode` 此前只把计划文本回灌对话，不落盘，跨会话不可恢复、不可审计（Goal 引擎有 `goal.json`，Plan 却没有对应存档）。
- 补齐内容（本次改动）:
  - `tools/session_tools.py` 新增 `_archive_plan(ctx, plan_text)`：把经确认的实施计划**原子写入** `<workspace>/.tuan/plan.md`（先 .tmp 再 os.replace），写盘成功后发 `plan_mode.saved` 事件；写盘失败静默降级，不阻断退出 Plan 模式。`_exit_plan_handler` 退出时调用之，并在返回里告知存档路径。
- 测试: 新增 `tests/test_plan_archive.py`（5 用例：退出即落盘且含正文、空 plan 拒绝且不写盘、原子写盘无 .tmp 残留、坏 workspace 静默降级、enter→exit 往返标志复位）—— **5 passed**；回归 `test_plan_mode.py`、`test_plan_execute.py`、`test_plan_launch.py` 通过。
- 复刻状态: 已补齐（计划落盘存档）。

## 6. Worktree 隔离（Parallel Git Worktree）
- 官方行为基准（Claude Code CLI）: `/worktree create/list/remove/switch`，基于真实 `git worktree` 为并行实验开出独立目录/分支，互不污染工作区，完成后合并或丢弃；switch 切换会话当前工作目录。
- 青小团实现位置:
  - `tuan_cli/core/worktree_layer.py`（WorktreeLayer：create/list/remove/switch，subprocess 真调 git）
  - `tuan_cli/cli/cmd_worktree.py`（`tuan worktree` 子命令）
  - `tuan_cli/cli/cmd_slash_boundary.py`（TUI `/worktree` 斜杠命令分发）
  - `tuan_cli/cli/parser_commands.py`（create/list/remove/switch 子命令注册）
- 审计发现（缺口清单）:
  - create 经 `git worktree add -b <name> <path>` 真建分支与工作树（非模拟目录），已核实；
  - create/list/remove/switch 四子命令 CLI 与 TUI 斜杠命令均已注册齐全；
  - `is_git_repo()` 仅当 workspace 自身就是仓库根（`git rev-parse --show-toplevel` 绝对路径比对）才认，仓库内子目录不误判（有回归测试）；
  - 非 git 仓库有友好报错（提示先 `git init`）；
  - switch 返回路径由 TUI/调用方 chdir（`worktree_layer.switch` 文档化契约），实际可用；
  - 结论：**未发现缺口**（依据：测试在临时 `git init` 仓库里真跑 worktree add/list/remove 全通）。
- 补齐内容（本次改动）:
  - 生产代码无需改动（能力已成立）；
  - 强化测试：在 `tests/test_worktree_layer.py` 新增 3 个用例，证明 create 产出的是带独立分支的真实工作树（`git branch --list` 含新分支、worktree 内 HEAD 分支名==name）、switch 返回路径真实存在且被 `git worktree list` 识别、主工作区与实验 worktree 文件相互隔离。
- 测试: `tests/test_worktree_layer.py`（9 个用例，含新增 3 个隔离用例），结果 **9 passed**。
- 复刻状态: 已有。

## 7. Headless 模式（CI/CD 无 TUI 驱动）
- 官方行为基准（Claude Code CLI）: `claude -p "..."` 无 TUI 非交互完整跑完一轮 agent 并打印输出；退出码区分成功/失败；支持 stdin 输入、`--resume` 续会话、`--output-format json`；供 CI/CD 调用。
- 青小团实现位置:
  - `tuan_cli/cli/cmd_agents.py`（`cmd_run`：`-p/--print`、`--output-format json`(NDJSON)、`--bare`、stdin、退出码 0/1）
  - `tuan_cli/cli/parser_commands.py`（`run` 子命令参数定义）
  - `tuan_cli/core/remote_control.py`（远程控制，非 headless 主路径）、`core/auto_mode.py`（权限分类器）
- 审计发现（缺口清单）:
  1. 完整一轮驱动：`cmd_run` 真跑 `agent.run(...)` 而非只打印横幅；退出码语义正确（`[模型错误]`→1，否则 0）；stderr 走错误、stdout 走数据；stdin 管道读取；`--output-format json` 输出 NDJSON（text/tool_call/tool_result/thinking/finish）；`--bare` 跳过用户配置/技能注入。已有 `test_headless_print.py` 覆盖。
  2. **真实缺口**：`--resume` 只在交互入口 `cmd_chat --print` 接线，专用 headless 子命令 `tuan run`（`cmd_run`）**没有 `--resume/--continue`**——CI/CD 多步流水线无法在无 TUI 下续上一轮会话。
- 补齐内容（本次改动）:
  - `cli/parser_commands.py`：`run` 子命令新增 `--resume`/`--continue [会话ID|编号|latest]`（nargs='?' const='latest'）。
  - `cli/cmd_agents.py` `cmd_run`：创建 agent 后，若 `args.resume` 非空则复用 `cmd_chat._resume_session` 恢复历史上下文；恢复失败以退出码 1 报错（stderr），恢复成功则带历史上下文正常跑一轮。
- 测试: 新增 `tests/test_headless_resume.py`（7 用例：`--resume <id>` / `--continue` 别名 / `--resume` 置末尾取 latest / `--resume=latest` 等号形 / 不带 resume 为 None / 恢复失败退出码 1 且 stderr 提示 / 恢复成功跑一轮退出码 0）—— **7 passed**；回归 `test_headless_print.py`、`test_mode_override.py` 通过。
- 复刻状态: 已补齐（`tuan run --resume` 续会话）。

## 8. Security Plugin（漏洞扫描与执行前拦截）
- 官方行为基准（Claude Code CLI）: `/security` 做漏洞/配置/网络暴露/密钥泄露扫描并给修复建议；安全检查在 agent 工具执行路径上拦截/告警，危险操作 fail-closed。
- 青小团实现位置:
  - `tuan_cli/core/tool_executor.py`（`_security_gate_check`，并行与串行两条真实派发路径调用）
  - `tuan_cli/core/security_plugin.py`、`security_auditor.py`、`security_policy.py`、`security_bus.py`、`security_classifier.py`
  - `tuan_cli/cli/cmd_harden.py`（sbom/network-check/audit-export）、`tuan_cli/cli/cmd_safe.py`（状态/报告/建议）
  - 新增 `tuan_cli/core/secret_scanner.py`
- 审计发现（缺口清单）:
  - (a) 工具执行前扫描链路**已真接通**：`ToolExecutor` 每个工具调用在 dispatch 前过 `_security_gate_check`（策略引擎 deny → SecurityGate 红线 → MCP 注入扫描 → shell 硬红线 → 文件写闸门），命中即 `status=denied` 阻断并写审计，不是只提供 API 类；
  - (b) 扫描类型：命令注入/红线 ✓、网络策略 ✓（NetworkGuard）、文件路径策略 ✓（SecurityPolicyEngine）、依赖/SBOM ✓（`harden sbom`）；**缺口：没有独立的"已提交密钥泄露扫描器"**——旧栈只有 `redact_sensitive`（被动脱敏）与"命令是否访问敏感文件"的分类器，缺少把写进源码/配置的明文密钥揪出并给修复建议的能力；
  - (c) `/security` 入口：`tuan safe`/`tuan harden` 已有状态/报告/网络检查/SBOM；
  - (d) `security_bus` 审计订阅可用：`SecurityAuditor.subscribe_bus`、`SecurityAlerter.subscribe_bus` 均真实订阅总线事件并落盘。
- 补齐内容（本次改动）:
  - 新增 `tuan_cli/core/secret_scanner.py`：确定性正则扫描 AWS Access Key、GitHub token、OpenAI/Anthropic sk-、JWT、PEM 私钥块、明文 key=value 赋值；按 high/medium/low 分级，每条带修复建议；命中值只保留前后缀（xxxx…yyyy），不二次泄露完整密钥；支持 `scan_text/scan_file/scan_directory`（跳过 .git/node_modules/二进制文件），并可把高危发现经 `emit_findings` 汇入安全总线（事件类型 `security.secret.leak`）做审计留痕。
- 测试:
  - 新增 `tests/test_secret_scanner.py`（15 个用例：各规则命中、不误报、脱敏、目录扫描跳过 .git/二进制、总线汇入、报告输出），结果 **15 passed**；
  - 既有安全套件回归：`tests/test_security_*.py` 共 **172 passed, 1 skipped**（1 个 skip 为既有环境跳过，非本次引入）。
- 复刻状态: 已有（执行前拦截链路）+ 已补齐（密钥泄露扫描与修复建议）。

## 9. Scheduled Tasks（定时任务 / cron 表达式）
- 官方行为基准（Claude Code CLI）: `/schedule` 用标准 cron 表达式注册任务，后台 daemon 轮询执行、状态查询、list/remove，任务持久化、重启不丢。
- 青小团实现位置:
  - `tuan_cli/cron/store.py`（CronStore，jobs.json 原子写）、`runner.py`（CronRunner/run_due_jobs，含墙钟超时 + 调度互斥锁防重入）、`daemon.py`（轮询守护 + 心跳）、`plugin.py`（注册内核服务）
  - 新增 `tuan_cli/cron/schedule.py`（5 字段 cron 解析/校验/匹配）
  - `tuan_cli/cli/cmd_cron.py`、`tuan_cli/cli/parser_commands.py`
- 审计发现（缺口清单）:
  - 持久化 ✓（jobs.json 临时文件+原子替换，进程重启任务仍在）；
  - daemon 轮询 ✓（run_due_jobs 循环 + 文件锁，持锁方跳过、锁内重读 due 防陈旧列表重复执行）；
  - runner 执行并记录结果 ✓（墙钟超时强判失败、写会话流、mark_run 推进）；
  - CLI 子命令齐全（add/list/remove/enable/disable/edit/logs/run/tick/start/stop/status）；
  - **缺口（核心）**：只有 `interval_minutes`（每隔 N 分钟），**不支持标准 cron 表达式**，无法表达"每工作日 09:00""每周一 08:30"等真实排期。
- 补齐内容（本次改动）:
  - 新增 `cron/schedule.py`：零第三方依赖的 5 字段 cron 解析器（分/时/日/月/周），支持 `*`、`,`、`-`、`/` 步长与组合，`?`=`*`，dow 的 `7` 归一化为周日，dom 与 dow 都被限定时按标准 cron 取 OR；非法表达式抛 `CronParseError`；提供 `last_fire(now)` 计算最近一次命中分钟；
  - `CronStore.add(..., schedule=...)`：传入 cron 表达式即校验并落盘（非法不写坏数据）；`due()` 在有 `schedule` 时改用"最近命中分钟 > last_run"判定到期，无 schedule 回退原间隔语义；畸形 schedule 条目跳过不炸整轮；
  - CLI：`add`/`edit` 新增 `--cron` 参数（非法表达式返回错误码且不写盘），`list` 有 schedule 时显示 cron 表达式。
- 测试:
  - 新增 `tests/test_cron_schedule.py`（20 个用例：解析校验、工作时段/步长/列表/区间/dom-dow OR 语义、最近命中、store cron 到期判定与持久化、畸形 schedule 跳过、CLI add/edit/list/非法 cron），结果 **20 passed**；
  - cron 全套回归：`test_cron_cli.py` + `test_cron_runner.py` + `test_cron_schedule.py` 共 **43 passed**。
- 复刻状态: 已补齐。

## 10. Agent Teams / Multi-agent Orchestration
- 官方行为基准（Claude Code CLI）: 多 Agent 按角色组队，有编排协议（消息类型、leader/follower、职责分工），团队级任务可分解、黑板通信、结果汇总。
- 青小团实现位置:
  - `tuan_cli/core/swarm.py`（herdr 式 planner/worker/acceptor + Blackboard + depends_on 分波拓扑）
  - `tuan_cli/core/collaboration_protocol.py`（结构化消息：类型/优先级/CAS/冲突检测/订阅）
  - `tuan_cli/core/specialized_roles.py`（reviewer/tester/debugger/architect/security_auditor/documenter/implementer 7 角色）
  - `tuan_cli/core/collaboration_plugin.py`（注册 collaboration_protocol / role_registry / result_aggregator_factory 到内核）
  - `tuan_cli/tools/dispatch.py`（`dispatch_tasks` 的 parallel/dag/role 三模式）、`core/devloop.py` V2（角色化 + CollaborationProtocol 黑板编排）
- 审计发现（缺口清单）:
  1. 编排链路真实可用：Swarm 把任务拓扑分波并发执行、前波结果写黑板供后波引用、强模型 acceptor 汇总；`dispatch_tasks` role 模式按 `specialized_roles` 注入角色系统提示。**角色可被编排消费**（dispatch.py / devloop.py 均 get_role）。
  2. **真实缺陷（死锁）**：`CollaborationProtocol.compare_and_swap` 在持有 `self._lock`（不可重入 threading.Lock）时又调用 `_notify_subscribers`，后者再次抢同一把锁 → **CAS 写入必卡死**。该协议此前全仓库零直接测试，缺陷从未被触发发现。
  3. 协议层（消息类型/CAS/冲突/订阅）无任何测试覆盖，"编排协议消息流转"从未被证明。
- 补齐内容（本次改动）:
  - 修复 `core/collaboration_protocol.py` `compare_and_swap` 死锁：改为"锁内完成数据写入与消息落账，锁外再 `_notify_subscribers`"，与 write() 语义对齐；补充注释说明不可重入锁约束。
- 测试:
  - 新增 `tests/test_collaboration_protocol.py`（9 用例：版本单调、消息按类型/发送者可追溯、优先级/key、跨发送者冲突检测、同值不冲突、CAS 版本号守卫、订阅通知、auto_resolve 消解、stats/上下文块）—— **9 passed**（修复后）；
  - 回归：`tests/test_swarm.py`、`test_swarm_concurrency.py`、`test_swarm_roles.py` 通过。
- 复刻状态: 已补齐（修复 CAS 死锁 + 补齐协议消息流转测试）。

---

## 最终全量测试结果

（Organizer 统一复跑，2026-10-06，`pytest tests` 全量）

- 最新一次全量: **3177 passed / 4 failed / 7 skipped**（本次含全部新增实现与测试）
- 其中 **3 个失败为既有/间歇性问题，与本任务改动无关**（基线即存在，不同轮次表现不同）：
  - `test_cli_safe_bench_report.py::test_cmd_bench_quick_with_fake_runners` — 基线 3 个失败之一，两次全量均失败
  - `test_rewind.py` — 间歇性：基线失败 `test_list_and_restore_previous`（assert 3 == 2），本次失败 `test_restore_to_index`（assert 2 == 1），中间一轮全量通过
  - `test_tui_fixes.py::TestTuiBridge::test_attach_ui_replaces_singleton` — 基线 3 个失败之一，间歇性出现
- **1 个失败为并发会话的进行中重构所致，非本任务改动**：
  - `test_version_policy.py::test_repo_versions_are_in_sync` — 另一并发会话于 2026-10-06 17:31 落地"版本号单一化"重构（新增 `tuan_cli/version.py` 为唯一版本源，`tuan_cli/__init__.py` 改为 `from .version import __version__` re-export），但 `scripts/check_version_policy.py` 的 `read_init_version()` 仍用正则匹配 `__init__.py` 内的字面 `__version__ = "..."` 赋值，未同步更新 → 返回 None。该测试在本任务改动后的上一轮全量（重构落地前）是通过的。按"绝不修改其他 Agent 正在改动的文件"硬约束，本任务未触碰 `tuan_cli/__init__.py`、`tuan_cli/version.py`、`scripts/check_version_policy.py`；建议由重构作者把检查器改为同时读取 `version.py`。
- 本任务 9 个新增测试文件 + 扩展用例全部通过（见各能力小节测试项），并在范围回归中逐一独立复验（编排类 86、基建类 97、运维类 84、修复回归后 arch/hooks 复验通过）。

### 改动文件清单（本任务）

新增:
- `tuan_cli/cron/schedule.py`（5 字段 cron 解析器）
- `tuan_cli/core/secret_scanner.py`（密钥泄露扫描器）
- 测试 9 个: `tests/test_subagent_parallel.py`、`test_collaboration_protocol.py`、`test_plan_archive.py`、`test_headless_resume.py`、`test_hooks_http.py`、`test_mcp_e2e.py`、`test_skills_runtime_injection.py`、`test_cron_schedule.py`、`test_secret_scanner.py`

修改（仅各能力小节列出的范围内文件）:
- `core/collaboration_protocol.py`（CAS 死锁修复）、`tools/session_tools.py`（计划存档）、`cli/parser_commands.py`（run --resume / cron --cron / hooks enable-disable）、`cli/cmd_agents.py`（run --resume）、`arch/execution.py`（真实工具名/参数 + 阻断决策 + PermissionError 阻断契约）、`cli/cmd_hooks.py`（enable/disable）、`runtime/mcp/client_http.py`（信封解包）、`cli/cmd_mcp_cli.py`（remove + 远程状态）、`tools/mcp/plugin.py`（mcp_remote 服务）、`self_improve/auto_distiller.py`（双层 frontmatter 修复）、`cron/store.py`（schedule 支持）、`cli/cmd_cron.py`（--cron）、`tests/test_worktree_layer.py`（+3 隔离用例）

冻结与版本: `pyproject.toml` version 保持 0.3.1；`README*.md`、`VERSION_POLICY.md`、`VERSION_FAQ.md`、`CHANGELOG.md`、`web/frontend.py`、`web/index.html`、`tui.py` 冻结区均未触碰。

---

# 第 2 轮：文件读写极速化 + Claude Code 对标（2026-10-06）

> 方向：借鉴 Freebuff/Codebuff 编码 Agent 的工程做法（本地代码地图 + 快速定位相关文件 + 并行批量读 + 事务性批量写 + 省 token 不读全文）实现文件读写极速化；同时继续功能对标 Claude Code CLI。完整文档见 `docs/FAST-IO.md`。

## 第 2 轮总览

| 模块 | 落点 | 状态 | 加速数据 |
|---|---|---|---|
| 代码地图 FastFileIndex（增量+持久化+rank/related） | `tuan_cli/context/fast_index.py` | 已补齐 | 冷建 2.0x、增量 2.5x（400 文件，只重扫 1/400）、rank ~1ms/次 |
| pick_files 工具（Freebuff 式 file-picker） | `tuan_cli/tools/picker.py` | 已补齐 | 未读全文、省 token |
| read_files 批量并行读 | `tuan_cli/tools/filesystem.py` | 已补齐 | 20 文件 8.68x |
| edit_files 事务性批量编辑 | `tuan_cli/tools/filesystem.py` | 已补齐 | 20 文件 522x，失败回滚 0.3ms 零落盘 |
| `--output-format stream-json`（消息级事件流） | `cli/cmd_agents.py` + `cli/parser_commands.py` | 已补齐 | 对标 `claude --output-format stream-json` |
| `--append-system-prompt` / `--append-user-prompt` | 同上 | 已补齐 | CI 注入提示词 |
| `--session-id` | 同上 | 已补齐 | CI 手工命名会话 |
| 审计判定已等价（未补） | — | `--allowed-tools`/`--permission-mode bypassPermissions`、`/git`（`_cmd_diff`+shell 确认流）、`-vvv` 调试日志、MCP 配置默认严格校验 | 证据见 `docs/FAST-IO.md` 审计表 |
| 真实缺口未实现（第 2 轮时） | `/add-dir` | 需跨文件边界改 `tools/filesystem.py` 协作语义，留待后续协调 | 已由第 3 轮实现（见下） |

## 第 2 轮测试（全部通过，Organizer 独立复跑确认）

- 新增测试文件 3 个：`tests/test_fast_index.py`（13）、`tests/test_fast_io_tools.py`（12）、`tests/test_headless_parity.py`（7）
- 独立复验：速度主线 25 passed、索引+对标 56 passed；全量 `--collect-only` 3230 用例 0 收集错误
- 全量复跑：**3225 passed / 2 failed / 7 skipped**（997.6s，2026-10-06）。2 个失败均为已知既有问题（bench 残留临时文件、version_policy 并发重构未同步），非本轮改动；无 timeout、无新增失败。

### 最终全量测试结果（第 2 轮）

`pytest tests` 全量，**3225 passed / 2 failed / 7 skipped（16:37）**。

- 2 个失败（基线已知，非本轮）：
  - `test_cli_safe_bench_report.py::test_cmd_bench_quick_with_fake_runners` — bench/ 残留 `.run_tmp_*` 临时文件致断言 `== []` 失败（历史遗留，第 1 轮两次全量均失败）
  - `test_version_policy.py::test_repo_versions_are_in_sync` — 并发会话"版本号单一化"重构后 `check_version_policy.read_init_version` 未同步（非本任务改动）
- 复跑过程中发现并修复 2 个全量稳定性缺陷（详见 `docs/FAST-IO.md` 第五节）：
  1. `ext/notify_engine.py` `_run_cmd`：`subprocess.run(capture_output, timeout)` 在 Windows 管道继承下可永久挂起 → 改为 Popen+临时文件+显式 wait/kill，超时必然返回；
  2. `core/security_plugin.py`：桌面通知默认值改为跟随 `sys.stdout.isatty()`（CI/headless 不弹窗），避免批量 toast 打爆系统通知服务；新增 `tests/test_security_plugin_desktop.py`（4 用例）。
- 修复后全量无 timeout，与第 1 轮基线（4 失败）对比失败数降至 2（均为既有项）。

---

# 第 3 轮：其余系统审计补齐（2026-10-06）

> 用户诉求："完善本项目其余系统开发"（外出 1 小时，自主开发、全程未提问）。
> 模式与前两轮一致：对前两轮未覆盖的高价值系统（沙箱执行隔离 / 长期记忆 / 上下文压缩+Checkpoint+`/add-dir`）逐项对照 Claude Code 审计 → 找缺口 → 补齐 → 测试 → 文档。

## 第 3 轮总览

| 系统 | 青小团实现位置 | 复刻状态 | 本轮补齐概要 |
|---|---|---|---|
| 沙箱执行隔离（Sandbox） | `sandbox/filters.py`、`sandbox/manager.py`、`sandbox/verdict.py`、`core/tool_executor.py`（`_sandbox_gate_check`） | 已有 + 已补齐 | 审计 6 项 5 项已有；补 GAP-A：L0 意图滤网接入 `secret_scanner`，写文件/命令内嵌 live 凭据（AWS/GitHub/PEM）需确认，堵密钥泄露旁路 |
| 长期记忆（Long-term Memory） | `memory/store.py`、`memory/auto_extractor.py`、`memory/sessions.py`、`core/agent.py`（自动沉淀/召回接入） | 已有 + 已补齐 | 审计 6 项 5 项已有；补 GAP：记忆落盘前接入 `redact_sensitive`（sk-*/Bearer/JWT/KEY=value 一律抹 [REDACTED]），持久层单一收口防密钥进 MEMORY.md/FTS |
| 上下文压缩（Context Compaction） | `context/manager.py`、`context/compaction_fusion.py`、`core/agent.py:727-729` | 已有 | 触发已真实接入 agent 循环、压缩保真（system 置首+保留最近 14+head/tail/elision+高价值救援）、成本指标齐全；唯一缺口（自动压缩用户可见成本提示/取消）位于非本轮独占的 agent 编排层，如实记录 |
| Checkpoint / Rewind 回滚 | `core/checkpoint_store.py`、`core/rewind.py`、`tools/checkpoint.py`、`core/tool_executor.py:750` | 已有 | 写工具成功后自动建点、代码+对话双线真实回滚、30 天 TTL 与轮转均已具备；观察项（自动建点名单未含 `edit_files`）记录不改 |
| `/add-dir`（工作区外目录纳入上下文） | `tools/filesystem.py`（`authorize_extra_dir`）、`cli/cmd_slash.py`（`/add-dir`） | **已补齐** | 第 2 轮审计确认的真实缺口：`_resolve` 双通道（工作区 OR 已授权目录）、拒绝不存在/盘符根/系统关键目录、授权仅挂 ctx 内存态不落盘、写仍走既有守卫；仅用户 REPL 可授权（无 Agent 自助提权工具） |

## 第 3 轮审计-补齐明细

### 沙箱执行隔离（Sandbox Execution Isolation）
- **官方基准**：工具执行前统一权限/隔离裁决，危险命令与越权写默认拒绝（fail-closed）；网络出口、工作区外读写、命令载荷、内嵌凭据各有独立拦截面；不能"无裁决即放行"。
- **审计结论（6 项）**：
  1. 真接入执行路径 — 已有（`core/tool_executor.py:459` 调 `_sandbox_gate_check`；run_shell→assess_command，其余→assess_tool，探针实证非注册表摆设）；
  2. fail-closed — 已有（`manager.assess` chain 异常→DENY critical；无确认通道/异常→denied，探针实测）；
  3. 网络隔离/network_guard 联动 — 已有（ssh、`curl|sh`、云元数据均 deny；`deny_network_by_default` 元数据下传执行端）；
  4. 文件系统读写限界 — 已有（`resolve_in_workspace` 越界抛错；真实写路径由 path_safety 承担）；
  5. 命令执行沙箱/PS 载荷 — 已有（`powershell -enc`、IEX、`python -c os.system` 全 deny）；
  6. **GAP-A（真实缺口，已补齐）**：L0 意图滤网未接 `core/secret_scanner`——探针实测 `write_file` 写入 `AKIA...`/PEM 私钥 **deny=False 放行**，凭据泄露旁路。
- **补齐**：`tuan_cli/sandbox/filters.py` 新增 `_scan_embedded_secrets()`（复用 secret_scanner 同一规则，high 级凭据→CONFIRM 附轮换建议，medium 不升级防误杀），在红线/网络硬拒后、良性放行前调用；yolo 模式用户已声明免确认则放行（红线仍硬拒）。
- **测试**：新增 `tests/test_sandbox_gaps.py`（12 例）；sandbox 全套 56 passed（44 基线+12 新增，0 回归）；secret_scanner 连带 15 passed。

### 长期记忆（Long-term Memory）
- **官方基准**：跨会话自动沉淀与召回；按相关性检索（优先级+新鲜度）；容量上限与轮换；敏感信息不得明文落盘；与 Skills/目录约定协同；提供手动接口。
- **审计结论（6 项）**：自动沉淀/召回已有（agent.py:598 Stop 后 `_auto_memory_extract`；agent.py:563 `build_task_context→recall_context` 注入）；检索质量已有（FTS5 相关性 + 近 24h + kind 优先级 user>feedback>project>reference + 去重）；容量轮换已有（2000/500/200 行上限，test_memory_rotation 覆盖），冲突消解记为"缺口及原因"（需 LLM 判定，规则误删风险高，与 Claude Code 一致依赖模型/人工，不强行造）；手动接口已有（`/memory list|add|delete|on|off` + memory_write/search 等 4 工具）；**GAP（真实缺口，已补齐）**：记忆写入 5 个入口全部直接明文落盘，未走项目内统一脱敏原语 `redact_sensitive`。
- **补齐**：`tuan_cli/memory/store.py`（`append_memory`/`update_user`/`add_auto_memory` 三个写入口落盘前脱敏）+ `tuan_cli/memory/memory_notes.py`（`write`/`append` 落盘前脱敏）；持久层单一收口，无论写入方是 auto_extractor、`/memory add` 还是工具，密钥一律抹 `[REDACTED]` 再落盘。
- **测试**：新增 `tests/test_memory_gaps.py`（8 例，含脱敏不落盘 + 零误杀回归）；记忆全套 56 passed（48 基线+8 新增）；导入冒烟无循环依赖。

### 上下文压缩（Context Compaction）
- **官方基准**：长对话接近水位自动 compact；压缩保真（系统提示不动、最近 N 轮保留、旧历史摘要折叠、关键决策不丢）；压缩前成本提示可感知。
- **审计结论**：触发真实接入（`core/agent.py:727-729` 每轮 `needs_compact`→`PreCompact` hook→`compact_if_needed`，阈值 `context.compact_trigger`/`budget_tokens` 默认 60000）；保真（manager.py `_compact_once*`：system 置首、保留最近 14、head/tail/elision 融合、tool 组不拆、高价值救援、压缩率/恢复率指标）；成本提示部分具备（PreCompact hook + stats 已记录，但自动压缩的用户可见 surface/取消在 `core/agent.py` 编排层——非本轮独占范围，如实记录）。
- **补齐**：本组独占文件（manager.py、compaction_fusion.py）审计确认无真实缺陷，**未改**；结论全部写入分片。
- **测试**：`test_compaction_fusion`/`test_cache_compact`/`test_compact_survival`/`test_slash_compact_cost` 全绿（随 70 passed 复跑）。

### Checkpoint / Rewind 回滚
- **官方基准**：编辑后自动建检查点；`/rewind` 回退对话与代码；恢复真实回滚 agent 状态（消息历史+文件改动）。
- **审计结论**：自动建点真实（`tool_executor.py:750` write_file/edit_file/str_replace 成功→`_auto_checkpoint`；RewindManager 用户输入前快照）；真实可回滚（`tools/checkpoint.py` `ledger.undo_since` 逆向回滚文件 + 对话截回协议合法边界）；`test_mcp_checkpoint_convergence` 实际覆盖 MCP 红线一致性（非 checkpoint↔MCP 收敛），checkpoint 链路不涉 MCP 状态，无缺口；观察项（自动建点名单未含第 2 轮新增 `edit_files` 批量编辑器）位于非独占文件，记录不改。
- **补齐**：本组 checkpoint 实现文件审计确认无真实缺陷，**未改**。
- **测试**：`test_checkpoint`/`test_checkpoint_store`/`test_mcp_checkpoint_convergence` 全绿（随 70 passed 复跑）。

### `/add-dir`（工作区外目录显式纳入上下文）
- **官方基准**：`/add-dir <路径>` 把工作区外目录显式纳入上下文授予读取访问；是用户显式授权动作，Agent 不能自助授权。
- **审计结论**：补齐前全仓源码+测试 0 命中（确认真实缺口，与第 2 轮结论一致）；`tools/filesystem.py:_resolve` 强制 `relative_to(workspace)`，工作区外一律拒绝，无显式授权通道。
- **补齐（最小实现）**：
  - `tools/filesystem.py`：`_resolve` 升级双通道（工作区内原样放行；越界时逐个比对 `_extra_allowed_roots(ctx)`，授权内放行、否则仍抛错并提示 `/add-dir`；授权为空时行为与改动前逐字节一致——既有守卫零削弱）；新增 `authorize_extra_dir`（拒绝不存在/非目录/盘符根/`_is_system_critical` 系统关键目录；工作区内 no-op；去重）、`list_extra_dirs`；授权只挂 ctx 内存态（`extra_allowed_dirs`），不写 config 不落盘（避免授权列表泄露）。
  - `cli/cmd_slash.py`：新增 `_cmd_add_dir`（无参列出、带参授权）+ dispatch 分支 + 注册进 `SLASH_COMMAND_NAMES`/`_CMD_META`/`_HELP`。
  - 安全取舍：不提供 Agent 可自助调用的 add_dir 工具（避免自我提权）；写操作仍走 dangerous 确认 + Read-before-Edit 守卫，不因授权绕过。
- **测试**：新增 `tests/test_context_gaps.py`（13 例：未授权越界仍拦、授权后可读、写守卫仍适用、不落盘、slash 接线、系统关键目录拒绝等）；filesystem 既有 25 项回归全绿；上下文+checkpoint+slash 全套 70 项全绿。

## 第 3 轮测试（Organizer 独立复跑确认）

- 新增测试文件 3 个：`tests/test_memory_gaps.py`（8）、`tests/test_sandbox_gaps.py`（12）、`tests/test_context_gaps.py`（13）
- 生产改动：`memory/store.py`、`memory/memory_notes.py`、`sandbox/filters.py`、`tools/filesystem.py`、`cli/cmd_slash.py`
- Organizer 独立复验（三组新测试 + 全部相关回归，一条命令）：**222 passed in 155s**（0 失败）
- 全量复跑：见下方「最终全量测试结果（第 3 轮）」

### 最终全量测试结果（第 3 轮）

`pytest tests` 全量 —— 结果待 Organizer 收尾补录。


---

## B2 增量（本轮）

`CLAUDE_PARITY.md` §12 是权威口径。本表只记增量，不重复整张矩阵：

- `network_default_deny`、`credential_masking`：gap → **partial**
- `deny_instead_of_prompting`、`worktree_sandbox_escape`：gap → **aligned**
- `os_sandbox`：**仍为 gap**
- 全局：`gap 30 → 26`、`aligned 43 → 45`、`partial 8 → 10`，
  `fully_superior` 仍 `false`，`b_waves_done` 仍 `["B1"]`

新增实现：`tuan_cli/sandbox/egress.py`、`unattended.py`、
`worktree_boundary.py`；新增回归 `tests/test_b2_boundaries.py`（34 例）。
新增配置键见 `SECURITY_BASELINE.md` R41。


---

## B2 收尾增量

`CLAUDE_PARITY.md` §13 是权威口径。本表只记增量：

- `network_strict_allowlist`：partial → **aligned**（逐命令域名强绑定真接到
  本地回环出网代理，声明外 403）
- `credential_masking`：保持 **partial**，但 `inject_headers()` 从预留接口
  接成真实调用方（明文 HTTP 代理转发还原真实凭据）；HTTPS CONNECT 隧道
  内 header 注入不可用，如实不宣称完整对等
- 全局：`aligned 45 → 46`、`partial 10 → 9`、**gap 仍 26**
  （partial→aligned 不减少缺口，不靠改口径凑数）
- `os_sandbox` 仍 gap、`deny_network_by_default` 仍 false 未翻、
  `fully_superior` 仍 false、`b_waves_done` 仍 `["B1"]`

新增实现：`tuan_cli/sandbox/egress_allowlist.py`、`egress_proxy.py`；
新增回归 `tests/test_b2_egress_strict.py`（43 例，含真 socket 代理端到端）。
新增配置键见 `SECURITY_BASELINE.md` R42。


---

## 深度轮增量（纠偏 B2 收尾）

`CLAUDE_PARITY.md` §14 是权威口径。**矩阵计数一个没动**：
`aligned 46 / partial 9 / gap 26`、`fully_superior=false`、
`b_waves_done=["B1"]` —— 纯深度修复，不把修好侧门包装成进度。

- 实测 §13 的强绑定只接在 `_execute_backend` 的 **local 分支**；
  强后端三条路径完全没有 EgressGuard / claim 检查 / 代理 env /
  `last_egress`；`run_syscall_sandboxed` 连 `env` 参数都没有，
  Job Object / seccomp 路径真实密钥原样进子进程。
- 新增 `egress_plan.py`（`plan_egress` 单一出口 + 派生一致性校验）；
  `manager.py` 四分支统一 `plan.env`；`arch/platform.py` 全路径
  `env` 透传（含 `os.execvpe`），`env=None` 向后兼容。
- 真正逐命令声明（`source=tool_args`）+ 强后端**默认 fail-closed 拒绝**；
  全局白名单回落（`global_policy`）沿用既有文本层语义，不破坏既有部署。
- 新键 `sandbox.resource.strict_claim_strong_backend`（`deny` 默认 /
  `metadata_only` 降级）：schema 枚举阻断 + 降级 warning +
  `harden status` 待加固项。详见 `SECURITY_BASELINE.md` R43。
- catalog 两条 note 补纠偏说明（承认 §13 标 aligned 的边界比文档写的
  窄），但 `status` 与 `evidence` 结构不变。

新增实现/回归：`tuan_cli/sandbox/egress_plan.py`、
`tests/test_b2s_egress_uniform.py`（37 例，含真实 `Popen` 看到 sentinel、
四条分支 env 真透传、强后端默认拒绝、矩阵计数钉死）。


---

## 深度轮增量（终态拒绝 / 占位符保全，纠偏 §13/§14）

`CLAUDE_PARITY.md` §15 是权威口径。**矩阵计数一个没动**：
`aligned 46 / partial 9 / gap 26`、`fully_superior=false`、
`b_waves_done=["B1"]` —— 纯深度修复，不把修好侧门包装成进度。

- **R1**：`tools/shell.py` 路由用 `verdict.enforced` 判断是否采纳结果，
  plan 拒绝天然 `enforced=False` → `enforce_required=false` 部署上
  **被拒命令回落真实工作区裸跑**。
- **R2**：`copy_diff_apply` 拒绝后仍走 diff/确认，把合规拒绝伪装成用户
  主动拒绝并宣称已隔离执行。
- **R3**：`_sanitize_env` 按键名把 `plan_egress` 注入的 sentinel 占位符
  也抹空（§14 只验了传给 `provider.run` 的参数，没验子进程实收值）。
- **R4**：`TUAN_WORKSPACE` 在三个强后端被 `TUAN_` hint 抹空且没补回。

修复：`SandboxExecResult.terminal_refusal` 解耦终态拒绝与隔离生效；
shell 路由优先检查它、绝不回落；copy_diff_apply 立刻返回；
`core/security_utils.py` 新增 `is_masked_placeholder()`（不改全局
`sanitize_env` 语义）；provider 按值保留占位符、四个后端统一补
`TUAN_WORKSPACE`。

catalog 两条 note 补**第三轮纠偏说明**，但 `status` 与 `evidence`
结构不变。新增 `tests/test_b2su_refusal_routing.py`（26 例，含四个
「不该修」判定与矩阵计数钉死）。详见 `SECURITY_BASELINE.md` R44。


---

## 深度轮增量（`decided` 单一契约，纠偏 §13–§15）

`CLAUDE_PARITY.md` §16 是权威口径。**矩阵计数一个没动**：
`aligned 46 / partial 9 / gap 26`、`fully_superior=false`、
`b_waves_done=["B1"]` —— 纯深度修复，不把修好侧门包装成进度。

- **G**：路由用 `verdict.enforced / backend_available` 判断是否采纳结果，
  降级部署里 local 分支已真实执行却返回 `None` → **命令双重执行**。
- **F1/F2/F3**：强后端崩溃、超时、副本创建失败都走同一条回落裸跑；
  副本创建失败还 `enforced=True` 宣称已隔离执行。
- **F4**：`str(exc)` 原样回显，实测 `GITHUB_TOKEN=ghp_...` 与 OSC/RLO
  进用户终端。
- **F5**：执行失败仍走 diff → confirm，要用户确认写回没成功执行的副本。

修复：`SandboxExecResult.decided` 默认 True（fail-closed），路由只问它；
`core/security_utils.safe_error_text()` 在来源处脱敏 + 剥离控制字符 +
限长，出口不二次净化以保留 diff 预览；`copy_diff_apply` 对
`returncode < 0` 早返回、外层异常如实 `enforced=False`。

catalog 两条 note 补**第四轮纠偏指向**，但 `status` 与 `evidence`
结构不变。新增 `tests/test_b2su_decided_routing.py`（约 30 例，含端到端
`run_shell` 不 bare Popen、三个「不该修」判定与矩阵计数钉死）。
详见 `SECURITY_BASELINE.md` R45。


---

## 深度轮增量（两条执行侧门收口，纠偏 §16）

`CLAUDE_PARITY.md` 末尾「深度轮（续）」是权威口径。**矩阵计数一个没动**：
`aligned 46 / partial 9 / gap 26`、`fully_superior=false`、
`b_waves_done=["B1"]` —— 纯深度修复。

- **后台 `! cmd`**：`run_shell` 里它位于 guard / 隔离路由之前就 return，
  实测带 `isolate=True` 裁决时隔离层调用 0 次、bare Popen 1 次；且后台
  子进程不传 env、继承父进程真实密钥。现在需隔离一律 fail-closed 拒绝，
  其余显式传脱敏 env。
- **对外 MCP `run_shell`**：全仓唯一「外部 Agent 直接给 command +
  shell=True」入口，只做文本红线、不传 env、`str(exc)` 原样回显。现在接
  四层滤网裁决（DENY / CONFIRM / isolate 全拒绝）+ `plan_egress` 脱敏 env，
  工具描述如实标注「没有 OS 级隔离」。
- **`safe_exception_text()`**：`str(exc)` 在调用方先执行，损坏对象会掀翻
  `except`；全部 12 处错误出口统一收口。

**章节编号纠偏**：仓库里 `CLAUDE_PARITY.md` / `SECURITY.md` /
`SECURITY_EN.md` / `SLOGAN_MAPPING.md` 各有 §17 且指代四个不同主题，
上一轮后台注释引用「§17」实际指向不存在。本轮改用自足标题，不做全局
重编号。新增 `tests/test_b2se_background_side_door.py` 与
`tests/test_b2su_mcp_shell_gate.py`。详见 `SECURITY_BASELINE.md` R46/R47。


---

## 深度轮增量（工具层写路径硬边界，纠偏 catalog note）

`CLAUDE_PARITY.md` 末尾「深度轮（续二）」是权威口径。**矩阵计数一个没动**：
`aligned 46 / partial 9 / gap 26`、`fully_superior=false`、
`b_waves_done=["B1"]`。

- **W1**：`permissions.blockWritesOutsideWorkingDirectories` 此前在代码里
  0 命中；新增 `core/write_boundary.py` + `filesystem._resolve_write`，
  六个写操作统一裁决，默认 `false` 与 CC 出厂一致。
- **W2**：`/add-dir` 三处文案声称「仅读」，实测 write/move/delete 全越界
  放行。改为如实文案 + `--writable` 显式可写授权；开启开关后普通授权
  才真正仅读。
- **W3**：`edit_files` 假事务（第 3 项危险内容时前 2 项已落盘却返回
  「未写入任何文件」）。危险扫描前移到校验阶段，写入前全体复检，
  阶段 2 无拒绝分支。

`block_writes_outside_wd` 仍 **`partial`**：命令层重定向不覆盖、
默认仍关闭、TOCTOU 二次解析与 `os.replace` 之间仍有窗口。详见
`SECURITY_BASELINE.md` R48。新增 `tests/test_b2su_write_boundary.py`（38 例）。


---

## B3 深度轮增量（Hooks 引擎 / 协议 / updatedInput 校验）

`CLAUDE_PARITY.md` 末尾「深度轮（续三）」是权威口径。**矩阵计数一个没动**：
`aligned 46 / partial 9 / gap 26`、`fully_superior=false`、
`b_waves_done=["B1"]`。

- **R1** 扩展事件配置静默丢弃 → 事件表 8→15 + 未知事件键显式审计。
- **R2** 决策类事件若走通知通道 stdout 被吞 → 独立 `run_decision()`
  裁决出口。
- **R3** `_parse_decision` 不认 CC 原生 `hookSpecificOutput` → 协议兼容
  （`permissionDecision` / `updatedInput` / `additionalContext`）。
- **R4** hook 改参未知键直接 `tool.handler(ctx, **args)` 抛 TypeError →
  新增 `hooks/input_validation.py`，有 schema 严格校验（丢未知键 /
  required / type / enum，不符即 deny），无 schema 保守子集且
  `enforced=False`。

两个 B3 条目**仍 `STATUS_GAP`**：4+1 个扩展事件没有生产触发点、
旁路调用链拿不到 schema。catalog note 补纠偏但 `status`/`evidence`
结构不变。接线：`/add-dir` → `DirectoryAdded`、危险审批 →
`PermissionRequest`（只允许收紧）。新增
`tests/test_b3_hooks_extended.py`。详见 `SECURITY_BASELINE.md` R49。
