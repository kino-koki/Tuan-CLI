# 青小团 × Claude Code v2.1.319：全模块超越计划

| 项 | 值 |
|---|---|
| 项目 | 青小团（Tuan-CLI） |
| 上游基线 | Claude Code **v2.1.319**（2026-11-06，GitHub tag v2.1.319，2026-11-06T17:04:01Z） |
| 计划起始 | 2026-11-07（B1） |
| 性质 | 全模块能力对照 → 找缺口 → 分轮补齐 → 在安全维度反超 → 每轮可机器核验 |
| 覆盖 | **14 个功能域 / 99 个模块 / 12 个轮次**（A 线 2 轮 + B 线 10 轮） |
| 当前结论 | **尚未「完全超越」**；26 个缺口、第三方自适应红队未做。详见 §3 硬判据与 §12（B2 落地） |
| 机器入口 | `tuan claude parity` / `--gaps` / `--probes` / `--report-json` |
| 归属 | `NOTICE` 第 14 条（专有产品，仅做行为契约对标） |

---

## 0. 先说结论

「超 Claude Code 最新版本」不是一句口号，也不靠把状态定义改漂亮来达成。本文档把它拆成三件可核验的事：

1. **锁定基线**：v2.1.319 是 2026-11-06 发布的最新稳定版，不是泛指「最新版」。它的新增与修复逐条列在 §2，来源列在 §10。
2. **全模块盘点**：99 个模块分 14 个域，五态标注。当前 **领先 10 / 已对齐 45 / 部分 10 / 缺口 26 / 不适用 8**（B2 落地 4 项，见 §12）。`not_applicable` 如实标不适用，**不包装成领先**。
3. **「超」有硬判据**：六个维度各有运行时探针（真调现有代码，不靠文档自述），`fully_superior` 必须同时满足 5 个条件才算成立（§3）。当前 5 个条件里只有 2 个为真，`fully_superior = false`。

**最该先看的不是领先项，是落后项**：`os_sandbox`（OS 级强制隔离）、`network_default_deny`（网络默认拒）、`credential_masking`（子进程不持密钥）、`worktree_sandbox_escape`。Claude Code 有真 OS 沙箱，Tuan 的 `--isolation` 是可选的 engine/process 级，L3 只在 `verdict.isolate` 时介入，`local` 后端 `enforced=False`。这些在第 1 轮对照 Codex 时就已如实承认，本计划不推翻、不美化，放在 **B2** 优先处理。

---

## 1. 两条线并行，不互相拆台

| 线 | 目标 | 落点 | 当前 | 关系 |
|---|---|---|---|---|
| **A 线** | TUI 与 OpenAI Codex **完全相同但有本地化** | `tuan_cli/tui/parity`、`inputkit`、`corekit`、`configkit`、`TUI_PARITY.md` | 165 模块中 aligned 35 / pending 10，`fully_identical=false` | 继续 A14 / A15 清零 |
| **B 线** | 全模块**超** Claude Code v2.1.319 | `tuan_cli/parity_claude/`、本文档 | B1 完成（基线 + 计划 + hooks 落地） | B2–B10 逐轮推进 |

两条线**共享同一条硬约束**：每轮都必须调用 `corekit.app.assert_wiring_intact()`，确认前 13 轮修好的 6 条既有安全接线（权限策略注入 / deny-all MCP / `ctx.confirm` / 审批卡片 / 副本确认 / 显式 ABORT）仍完好。为了对齐而重写入口、把侧门重新打开，会被矩阵自检先拦下。B 线**不碰** A 线的 `tui/parity` 文件；A 线不碰 B 线的 `parity_claude` 文件。

---

## 2. 上游基线：v2.1.319 到底带来了什么

### 2.1 版本口径（如实）

- GitHub tag `v2.1.319`，Published `2026-11-06T17:04:01Z`，非 prerelease。
- 官方 changelog 页面**按日期组织**（顶部可见 2026-11-04，对应 v2.1.318），不逐条写版本号；版本号取自 GitHub release 归档与公开 release tracker。
- 本计划锁定 **v2.1.319**；若后续出新版本，先更新 `catalog.CC_VERSION` / `CC_DATE` / `SOURCES` 并重跑矩阵，不许把新特性悄悄算进旧基线。

### 2.2 v2.1.319 的关键变更（与本计划直接相关）

| 变更 | 对 Tuan 的意义 | 本计划落点 |
|---|---|---|
| **MCP tasks 在终端后台化**：长时 MCP task 立即转后台、完成再通知 | Tuan 有 `background.py` / store / worker 基建，但未接到 MCP task | `mcp_tasks_background` → B6 |
| **`permissions.denyInsteadOfPrompting`**：本该等待审批的调用直接拒绝并继续 turn | 无人值守不卡死；Tuan 有 deny 优先但缺显式开关与「继续」语义 | `deny_instead_of_prompting` → B2 |
| **auto mode 不再回退内置分类器**：服务端查不了就询问或拒绝 | 这正是 Tuan 前几轮反复强调的「模型不作为安全边界」 | `auto_mode` 已对齐；B2/B8 补形式化断言 |
| **修复 worktree 创建时的沙箱逃逸** | Tuan 需证明 worktree 创建路径本身在隔离边界内 | `worktree_sandbox_escape` → B2 |
| **修复 Bash 权限绕过**（构造的环境前缀可藏住部分命令） | 与 Tuan 第 6 轮 fuzz 发现的「零宽字符 / ANSI-C / 注释换行」同类 | B8 规则前置断言 |
| **`/tasks` 增加「Earlier in this session」行**：结束的子代理重启后仍可重开 | Tuan 缺该持久化索引 | `task_list_earlier_in_session` → B5 |
| **`CLAUDE_CODE_DISABLE_FEATURE_FLAGS`** | CC 依赖远程 flag 拉取；Tuan 无该机制，标 `not_applicable` 而非领先 | §8 |

### 2.3 更早版本里被本计划当作「可反超」参照的事实

| 版本 / 日期 | 事实 | 为什么是反超切口 |
|---|---|---|
| v2.1.317 / 319 | `onFailure: "block"`：让破损/超时/异常退出的 hook 阻断而非放行 | **CC 需要用户逐条 hook 显式配置**，旧行为是静默 fail-open。Tuan B1 把它做成出厂默认 |
| v2.1.314 | `permissions.blockWritesOutsideWorkingDirectories`，Write/Edit/NotebookEdit 硬拒绝工作区外路径 | **默认关闭**；Tuan 是命令文本规则层，工具层硬约束仍缺，故标 `partial` 不标领先 |
| v2.1.318 | 修复「提示框弹出前的杂散按键会静默批准危险动作」 | Tuan 第 11 轮 `activation_key_guard` 已独立修过同类问题 |
| v2.1.221+ | Sandbox credential masking（sentinel + 出网代理注入真实密钥） | 仅 Linux/WSL；B1 时为 B2 缺口，**B2 后部分落地**（sentinel + 子进程剥离已接线，代理注入仍缺，见 §12） |
| v2.1.307 → 310 | `claude_code.safety_event` OTel 事件加了又移除 | Tuan 的 AEAD 审计链 + 跨会话关联是不同思路，见 §3 维度 2 |
| 2026-07-25 | `sandbox.network.strictAllowlist`、`DirectoryAdded` hook、per-command `allowed_domains` | 对应 B2 网络策略与 B3 扩展事件 |

---

## 3. 「超」的定义：六个可验证维度 + 硬判据

不比谁的提示词写得更严，也不比功能清单长度。只比六件能跑出结果的事：

| # | 维度 | 运行时探针（`superiority.py`） | 结果 |
|---|---|---|---|
| 1 | `fail_closed_default` 故障闭合是默认 | hook 故障默认阻断，带原因与可查询失败记录 | **OK** |
| 2 | `audit_replay` 防篡改审计与回放 | HMAC 防篡改 + AEAD round-trip + 跨会话重放可用 | **OK** |
| 3 | `config_correctness` 配置正确性 | sandbox / permissions / hooks 畸形配置被结构化拒绝 | **OK** |
| 4 | `least_authority` 最小权限与默认不信任 | 默认不信任 + 损坏即锁定拒绝一切 | **OK** |
| 5 | `local_offline_i18n` 本地离线 / 零遥测 / 多语言 | 10 语言 i18n + 10 语言 README 真实存在 | **OK** |
| 6 | `verifiable_parity` 可机器核验的对齐本身 | 165 模块矩阵自检干净，pending 如实为 10 | **OK** |

每个 `ahead` 模块必须归属一个维度并写清 `ahead_reason`；**该维度探针不通过，其领先项就不计入「已证实领先」**。当前声明 10 项、已证实 10 项、六维全 OK。这不是文档自述：`fail_closed_default` 探针真的注入一个不存在的 hook 二进制，`least_authority` 探针真的写坏 MCP 策略文件看是否 locked，`config_correctness` 探针真的喂畸形配置看是否被拒。

### 3.1 何时才算「完全超越」

```text
fully_superior = (
    gaps == 0
    and 六个维度探针全部 ok
    and 每个维度至少 1 个已证实 ahead 模块
    and 所有 B 轮次路线都已标记完成
    and external_adaptive_red_team is True
)
```

判据写死在 `matrix.py`，**不许通过修改判据提前达成**。当前逐项：

| 条件 | 当前 |
|---|---|
| `gaps_zero` | ✗ |
| `all_probes_ok` | ✓ |
| `every_dimension_has_ahead` | ✓ |
| `all_b_waves_done` | ✗ |
| `external_adaptive_red_team` | ✗ |
| **`fully_superior`** | **否** |

最后一项 `external_adaptive_red_team` 是**外部条件**：静态 10k 对抗样本、自建 fuzz、自己写的 CI gate 都不算。提示注入目前没有根治方案，自适应攻击下已发表防御基本都被绕过，所以「超」最终必须由第三方自适应红队背书，不能自证。

---

## 4. 全模块矩阵（14 域 / 99 个模块）

### 4.1 汇总

| 功能域 | 模块 | 领先 | 已对齐 | 部分 | 缺口 | 不适用 |
|---|---:|---:|---:|---:|---:|---:|
| 安全与权限 `security_permissions` | 8 | 0 | 3 | 4 | 1 | 0 |
| 安全扫描与审计 `safety_audit` | 7 | 4 | 2 | 0 | 1 | 0 |
| 生命周期钩子 `hooks` | 8 | 1 | 5 | 0 | 2 | 0 |
| 技能与记忆 `skills_memory` | 7 | 0 | 5 | 1 | 1 | 0 |
| 子代理与团队 `subagents_teams` | 9 | 0 | 8 | 0 | 1 | 0 |
| MCP 全栈 `mcp` | 8 | 1 | 3 | 0 | 4 | 0 |
| 插件与市场 `plugins_marketplace` | 7 | 0 | 0 | 2 | 5 | 0 |
| 模式与上下文 `modes_context` | 7 | 0 | 4 | 0 | 1 | 2 |
| 会话 / 无头 / SDK `session_headless` | 7 | 0 | 6 | 0 | 1 | 0 |
| TUI 与交互 `tui_interaction` | 8 | 2 | 1 | 1 | 4 | 0 |
| Git / 后台任务 `git_background` | 6 | 0 | 5 | 0 | 1 | 0 |
| 代码智能 `code_intelligence` | 5 | 0 | 2 | 0 | 3 | 0 |
| 云 / 远程 / 集成 `cloud_remote` | 6 | 0 | 0 | 1 | 0 | 5 |
| 可观测 / 模型 / 成本 `observability_models` | 6 | 2 | 1 | 1 | 1 | 1 |
| **合计** | **99** | **10** | **45** | **10** | **26** | **8** |

状态定义即约束（`evidence.py` 运行时校验）：`ahead` 必须有 `ahead_reason` + 合法维度 + 存在的证据路径；`gap` 必须分配到某个 wave；`not_applicable` 不得带 wave 且必须写清理由；所有非 NA 模块的证据路径必须真实存在。想把缺口改成领先，就得补真实证据、写清理由、跑通探针——**改状态定义凑数会被自检拦下**。

### 4.2 逐域逐模块

#### 安全与权限 `security_permissions`

| 模块 | 状态 | 轮次 | 上游参照 / 判定依据 | 证据 |
|---|---|---|---|---|
| `os_sandbox` | **缺口** | B2 | 仍是最大落后项：CC 有 OS 级强制沙箱，Tuan 的 --isolation 是可选 engine/process 级。B2 补上 local 后端禁网裁决的 fail-closed 拒绝，但**没有**把 OS 级隔离变成默认执行边界 | `backends.py`, `manager.py`, `egress.py` |
| `network_default_deny` | 部分 | B2 | B2 修复执行层：local+禁网 fail-closed 拒绝（旧实现 block_net 未接线而裸跑）。仍缺：出厂 `deny_network_by_default` 仍 false、逐命令 `allowed_domains` 强绑定 | `egress.py`, `test_b2_boundaries.py` |
| `network_strict_allowlist` | 部分 | B2 | sandbox.network.strictAllowlist; per-command allowed_domains (v2.1.271) — 有域名策略与 NetworkGuard，但缺「逐命令声明所需主机、其余一律拒绝」的强绑定 | `network_policy.py`, `network_guard.py` |
| `credential_masking` | 部分 | B2 | B2 落地 sentinel 代理：子进程敏感环境变量替换为 `tuan-egress-sentinel-v1:<fp>`，真实值只在进程内内存。仍缺：出网代理转发注入未接线（`inject_headers` 默认关闭） | `egress.py`, `test_b2_boundaries.py` |
| `permission_modes` | 已对齐 | — | default / acceptEdits / plan / bypass / auto (Shift+Tab) — 五模式注册表与切换器已在；auto 模式的确定性规则前置见 auto_mode | `registry.py`, `switcher.py`, `policy.py` |
| `deny_rules_exclude_glob` | 已对齐 | — | permissions rules / deniedMcpServers URL (v2.1.318) — E6 负向排除 + MCP 规范化精确管控；deny 忽略 exclude，拒绝规则不允许被放宽 | `security_schema.py`, `policy.py` |
| `deny_instead_of_prompting` | 已对齐 | — | 显式开关（默认关）+ 两种 scope + `continue_turn`/`suppressed_prompt` 结构化；真接到 `assess_tool` 的 CONFIRM 路径，配置非法 fail-closed（§12） | `unattended.py`, `manager.py`, `test_b2_boundaries.py` |
| `block_writes_outside_wd` | 部分 | B2 | permissions.blockWritesOutsideWorkingDirectories (v2.1.314，默认关) — CC 在 Write/Edit/NotebookEdit 工具层硬拒绝（但默认关闭）；Tuan 是命令文本规则层，工具层硬约束待补。不标 ahead —— 两者都还不是默认强边界 | `filters.py`, `path_safety.py` |

#### 安全扫描与审计 `safety_audit`

| 模块 | 状态 | 轮次 | 上游参照 / 判定依据 | 证据 |
|---|---|---|---|---|
| `secret_scanner` | 已对齐 | — | /security; key/token leak scanning — 确定性正则扫 AWS/GitHub/OpenAI/Anthropic/JWT/PEM，分级 + 修复建议 + 只留前后缀不二次泄露 | `secret_scanner.py`, `test_secret_scanner.py` |
| `audit_chain_aead` | **领先** | — | Transcript / OTel tool_decision events — CC 记录 transcript 与 OTel 事件，但无防篡改链；Tuan 的审计记录 AES-GCM/HMAC 封装 + 轮转 + 脱敏 | `crypto_provider.py`, `store.py` |
| `audit_correlation` | **领先** | — | claude_code.safety_event OTel event (v2.1.307 加，v2.1.310 又移除) — Tuan 有 burst / cross_session / severity_escalation 三类聚合告警，指纹归一化路径数字、replay() 跨进程重启 | `audit_correlation.py` |
| `safety_event_otel` | **缺口** | B9 | claude_code.safety_event / tool_decision OTel events — 缺结构化安全事件的 OTel 导出（本地零遥测优先，但需可导出的标准 schema） | `telemetry.py` |
| `workspace_trust` | 已对齐 | — | workspace trust check (ultrareview /ultrareview) — 工作区信任判定已在 | `workspace_trust.py` |
| `config_schema_validate` | **领先** | — | startup warnings about permission rules in settings — CC 大量 startup warning 是提示；Tuan 的 tuan config validate / harden status 对 sandbox/permissions 做**结构化拒绝** | `security_schema.py`, `cmd_config.py` |
| `harden_status` | **领先** | — | /doctor / sandbox status — tuan harden status 给出基线态势并告警；CC /doctor 是环境体检，不校验安全基线开关一致性 | `cmd_harden.py`, `` |

#### 生命周期钩子 `hooks`

| 模块 | 状态 | 轮次 | 上游参照 / 判定依据 | 证据 |
|---|---|---|---|---|
| `hook_command` | 已对齐 | — | Hooks type: command — argv + stdin JSON + stdout decision，看门狗线程 + 进程树强杀 | `manager.py`, `test_hooks.py` |
| `hook_http` | 已对齐 | — | Hooks type: http — HTTP POST 型，本地真实端到端测试覆盖 Pre 阻断 / 改参 / Post 通知 | `manager.py`, `test_hooks_http.py` |
| `hook_prompt` | 已对齐 | — | Hooks type: prompt (v2.1.x) — _exec_prompt 已实现（模型单轮评估返回 JSON 决策） | `manager.py` |
| `hook_agent` | 已对齐 | — | Hooks type: agent (v2.1.x) — _exec_subagent 已实现（派生隔离子代理） | `manager.py` |
| `hook_events_core` | 已对齐 | — | PreToolUse / PostToolUse / UserPromptSubmit / Stop / SubagentStop / PreCompact / SessionStart / SessionEnd — HOOK_EVENTS 8 个核心事件 + SessionStart/SessionEnd CLI 边界接线 + UserPromptSubmit 注入 additionalContext | `manager.py`, `test_hooks_events.py` |
| `hook_events_extended` | **缺口** | B3 | PermissionRequest / Notification / DirectoryAdded / ConfigChange / WorktreeCreate / Elicitation / ElicitationResult — 缺 7 个扩展事件；DirectoryAdded 是 CC 2026-07-25 新增（/add-dir 注册工作目录后触发） | `manager.py` |
| `hook_on_failure` | **领先** | — | onFailure: "block" (v2.1.317/319；CC 需显式配置，默认 fail-open) — B1 本轮落地：spawn 失败 / 超时 / 异常 / 非零退出**默认阻断** PreToolUse，带结构化原因与审计；通知类只记录不卡 turn | `manager.py`, `test_claude_parity.py` |
| `hook_updated_input_validation` | **缺口** | B3 | updatedInput unknown keys dropped / rejected input denies the call — 改参目前直接接受 dict，未按工具 schema 校验未知键 | `manager.py` |

#### 技能与记忆 `skills_memory`

| 模块 | 状态 | 轮次 | 上游参照 / 判定依据 | 证据 |
|---|---|---|---|---|
| `skill_frontmatter` | 已对齐 | — | SKILL.md + frontmatter (name/description) — 单文件 .md 与 <slug>/SKILL.md 目录型均支持，frontmatter 超集 | `manager.py`, `universal_format.py` |
| `skill_autodiscovery` | 已对齐 | — | auto-load from project / user / plugin scopes — project(.tuan/.agents/.claude) / user / extra_dirs / builtin 四层，同名按优先级覆盖 | `manager.py` |
| `skill_runtime_injection` | 已对齐 | — | auto-activate by description at runtime — build_task_context → activate_for_task → 注册表条目注入 user 消息；正文经 skill_read 惰性加载 | `prompts.py`, `agent.py`, `test_skills_runtime_injection.py` |
| `skill_cli` | 已对齐 | — | /skills, claude plugin init, /reload-skills — tuan skill list/show/import/audit/consolidate/lint 与会话内 /skills 齐全 | `cmd_skills.py` |
| `skill_distiller` | 已对齐 | — | Skill auto-generation — 蒸馏产出走 save() 写标准 frontmatter（双层 frontmatter 缺陷已修） | `auto_distiller.py` |
| `claude_md_memory` | 部分 | B4 | CLAUDE.md persistent project memory / @-mentions — 有 TUAN.md 与 memory 层，但缺 CLAUDE.md 语义等价的多层项目记忆与 @ 文件提及（CC 2.1.312 刚修过大文件覆盖） | `plugin.py`, `TUAN.md` |
| `skill_integrity_signature` | **缺口** | B4 | per-directory skills / managed skills — 缺技能包完整性签名与权限域声明（Tuan 拟做的超越点：技能不可悄悄扩权） | `governance.py` |

#### 子代理与团队 `subagents_teams`

| 模块 | 状态 | 轮次 | 上游参照 / 判定依据 | 证据 |
|---|---|---|---|---|
| `subagent_pool` | 已对齐 | — | Subagents (isolated loop, own context) — 线程池真并行（含墙钟断言）、独立工作目录、两种隔离 | `subagents.py`, `test_subagent_parallel.py` |
| `subagent_isolated_context` | 已对齐 | — | isolated context / system prompt — 每个子任务 create_agent(..., system_extra=...) 拿独立 messages | `subagents.py` |
| `subagent_structured_return` | 已对齐 | — | structured summary back to parent — SubResult.to_block()/aggregate() 带来源标注回传 | `subagents.py` |
| `agents_registry` | 已对齐 | — | .claude/agents/*.md discovery — 三层发现 + frontmatter 解析 + 命名 agent 工具白名单折算 | `agents_registry.py` |
| `agents_cli` | 已对齐 | — | /agents view/list/kill/attach — 会话面板齐全 | `cmd_agents.py`, `cmd_agents_view.py` |
| `background_agents` | 已对齐 | — | background subagents by default (v2.1.198) — 后台代理 + store + worker 三件套 | `background.py`, `background_worker.py` |
| `agent_teams` | 已对齐 | — | Agent Teams (shared tasks, peer messaging) — 共享任务与点对点消息（compare_and_swap 死锁已修） | `swarm.py`, `collaboration_protocol.py`, `messaging.py` |
| `dynamic_workflow` | 已对齐 | — | dynamic workflows / workflowSizeGuideline (<15 agents) — 动态工作流与 DAG 编排已在 | `dynamic_workflow.py`, `task_dag.py`, `devloop.py` |
| `task_list_earlier_in_session` | **缺口** | B5 | /tasks "Earlier in this session" row (v2.1.319 新增) — 已结束的子代理离开列表 / 重启后仍可重开并继续发消息，Tuan 缺该持久化索引 | `cmd_agents_view.py` |

#### MCP 全栈 `mcp`

| 模块 | 状态 | 轮次 | 上游参照 / 判定依据 | 证据 |
|---|---|---|---|---|
| `mcp_stdio` | 已对齐 | — | MCP stdio transport — initialize→notifications/initialized→tools/list→tools/call 全握手 + 指数退避 | `client.py`, `test_mcp_e2e.py` |
| `mcp_http_sse` | 已对齐 | — | MCP HTTP / SSE transports — JSON-RPC 信封解包缺陷已修，本地真实 HTTP server 端到端覆盖 | `client_http.py`, `test_mcp_e2e.py` |
| `mcp_namespace` | 已对齐 | — | mcp__<server>__<tool> namespacing — 前缀命名空间 + >64 字符 FNV-1a 碰撞安全截断 | `naming.py` |
| `mcp_trust_tier` | **领先** | — | allowedMcpServers / deniedMcpServers (flat allowlist) — 默认 untrusted、trusted 强制显式白名单、deny 优先、域名白名单、会话配额、会话内可回撤、策略损坏进入 locked 拒绝一切 | `policy.py`, `security_schema.py` |
| `mcp_oauth` | **缺口** | B6 | MCP OAuth authentication — 缺 OAuth 客户端注册与凭据生命周期 | `config.py` |
| `mcp_tool_search` | **缺口** | B6 | MCP Tool Search (dynamic discovery) — 缺跨 server 的动态工具检索 | `` |
| `mcp_elicitation` | **缺口** | B6 | Elicitation / ElicitationResult hook events — 缺 MCP server 执行中请求用户输入的通道 | `` |
| `mcp_tasks_background` | **缺口** | B6 | MCP tasks backgrounded in terminal (v2.1.319 新增) — 长时 MCP task 立即转后台、完成再通知；Tuan 有 background 基建但未接到 MCP task | `background.py`, `client.py` |

#### 插件与市场 `plugins_marketplace`

| 模块 | 状态 | 轮次 | 上游参照 / 判定依据 | 证据 |
|---|---|---|---|---|
| `plugin_manifest` | 部分 | B7 | plugin.json / .claude-plugin — 有组件注册表与 plugin SDK，但无与 CC 对等的 plugin.json 清单模型 | `registry.py`, `plugin_sdk.py` |
| `plugin_marketplace` | **缺口** | B7 | Plugins & Marketplaces — 缺 marketplace 发现/安装/更新通道 | `` |
| `plugin_sha256_pin` | **缺口** | B7 | plugin source pinned by sha256 (v2.1.224+) — 缺 HTTPS zip 安装 + sha256 固定 | `repro_build.py` |
| `plugin_owner_wildcard` | **缺口** | B7 | owner/* marketplace wildcards (v2.1.223+) — 缺 strictKnownMarketplaces / blockedMarketplaces 的 owner 通配 | `registry.py` |
| `plugin_init_validate` | **缺口** | B7 | claude plugin init / validate / eval — 缺脚手架与清单校验命令 | `cmd_ecosystem.py` |
| `plugin_lsp` | **缺口** | B7 | Plugin LSP Support — 缺插件声明的 LSP server 接线 | `` |
| `managed_dropins` | 部分 | B7 | Managed Drop-ins (v2.1.83) — 有配置分层但缺组织级自动下发 | `` |

#### 模式与上下文 `modes_context`

| 模块 | 状态 | 轮次 | 上游参照 / 判定依据 | 证据 |
|---|---|---|---|---|
| `plan_mode` | 已对齐 | — | Plan Mode (read-only explore → confirm → execute) — 只读硬拦 + 两阶段切换 + 计划原子落盘 .tuan/plan.md | `session_tools.py`, `base.py`, `test_plan_archive.py` |
| `auto_mode` | 已对齐 | — | Auto Mode (background safety classifier) — 有分类器且有确定性规则前置；CC 直到 v2.1.319 才停止回退内置分类器 | `auto_mode.py`, `filters.py` |
| `mode_switcher` | 已对齐 | — | Shift+Tab mode cycling — 模式切换器已在 | `switcher.py` |
| `compaction` | 已对齐 | — | context compaction / /compact — 压缩与压缩后存活策略已在 | `compaction_fusion.py`, `compact_survival.py` |
| `idle_compaction` | **缺口** | B8 | Idle compaction 200K+ tokens (~54min, v2.1.290+) — 缺空闲触发（缓存过期前预压缩）与 CLI/IDE 一致性 | `compaction_fusion.py` |
| `context_1m` | 不适用 | — | 1M-token context (Sonnet/Opus/Haiku 5.5) — 模型侧能力，取决于用户接入的本地/远端模型，非 CLI 功能缺口，不适用 | `` |
| `effort_ultrathink` | 不适用 | — | /effort /fast / ultrathink (xhigh) — Anthropic 模型特有的 effort 语义，本地模型不适用；不包装成领先 | `` |

#### 会话 / 无头 / SDK `session_headless`

| 模块 | 状态 | 轮次 | 上游参照 / 判定依据 | 证据 |
|---|---|---|---|---|
| `resume_continue` | 已对齐 | — | --resume / --continue / session fork — tuan run --resume/--continue 已补齐，恢复失败退出码 1 | `cmd_agents.py`, `test_headless_resume.py` |
| `fork_session` | 已对齐 | — | session fork / subagent_type: fork — 会话存储支持派生 | `store.py` |
| `stream_json` | 已对齐 | — | --output-format stream-json (NDJSON) — schema / translate / headless 齐全 | `` |
| `headless_print` | 已对齐 | — | claude -p — tuan run -p 真跑 agent.run，stdin/stdout/stderr/退出码语义正确 | `cmd_agents.py`, `test_headless_print.py` |
| `output_format_json` | 已对齐 | — | --output-format json — NDJSON text/tool_call/tool_result/thinking/finish | `cmd_agents.py` |
| `agent_sdk` | **缺口** | B9 | Agent SDK (Python / TypeScript) — ACP server 已有但缺可嵌入的 Python SDK（进程内 agent + hooks + permissions） | `` |
| `acp` | 已对齐 | — | Editor / ACP integration — ACP 协议与 server 已在 | ``, `` |

#### TUI 与交互 `tui_interaction`

| 模块 | 状态 | 轮次 | 上游参照 / 判定依据 | 证据 |
|---|---|---|---|---|
| `fullscreen_tui` | 已对齐 | — | fullscreen TUI — prompt_toolkit/rich 全屏 TUI 与审批覆盖层 | `tui.py`, `fullscreen.py` |
| `codex_tui_parity` | **领先** | — | (none — CC TUI is proprietary, no public parity matrix) — 13 轮把 165 个 Codex TUI 模块做成可机器核验矩阵（键位/布局/组件树/文案），CC 无可对等的公开可核验对齐层 | ``, `TUI_PARITY.md` |
| `vim_mode` | 部分 | B10 | Vim mode (/vim), % motion, chord support — 有 vim_search 与 keymap 上下文，但缺完整 NORMAL/INSERT 状态机与 % 匹配 | `keymap.py`, `vim_search.py` |
| `keybindings_chords` | **缺口** | B10 | /keybindings, ~/.claude/keybindings.json, chords — 缺用户可编辑键位文件与和弦序列 | `keymap.py` |
| `statusline` | **缺口** | B10 | status line / cost in status line — 缺可配置状态行 | `` |
| `output_styles` | **缺口** | B10 | Output styles (Explanatory / Learning) — 缺输出风格切换 | `prompts.py` |
| `prompt_suggestions` | **缺口** | B10 | Context-aware prompt suggestions — 缺上下文感知的建议 | `` |
| `i18n_10_languages` | **领先** | — | English-only UI — 10 语言 README + i18n 运行时，默认简体中文；CC 为英文单语 | ``, `README_zh-CN.md`, `README_de.md` |

#### Git / 后台任务 `git_background`

| 模块 | 状态 | 轮次 | 上游参照 / 判定依据 | 证据 |
|---|---|---|---|---|
| `worktree` | 已对齐 | — | Git Worktrees / /worktree — 真调 git worktree add -b，create/list/remove/switch 四子命令 + 隔离证明测试 | `worktree_layer.py`, `test_worktree_layer.py` |
| `worktree_sandbox_escape` | 已对齐 | — | B2 真接线：`create`/`create_agent_worktree` 在 fast-resume 之前断言解析后 target 在 workspace 内（含 symlink 祖先）；`_git` 剥离 git 重定向变量、拒绝越界 argv（§12） | `worktree_boundary.py`, `test_b2_boundaries.py` |
| `diff_view` | 已对齐 | — | /diff, word-level diff — diff 渲染 + 副本 diff 预览（含点目录修复） | `diff_view.py`, `isolation.py` |
| `background_bash` | 已对齐 | — | background Bash / long-running commands — 后台 shell 与存储已在 | `background_shell.py`, `background_store.py` |
| `loop_cron` | 已对齐 | — | /loop, CronCreate, scheduled tasks — 零依赖 5 字段 cron 解析器 + daemon/runner/store | ``, `test_cron_schedule.py` |
| `scheduled_tasks_ui` | **缺口** | B10 | /tasks background task management panel — 缺统一后台任务面板 | `cmd_cron.py` |

#### 代码智能 `code_intelligence`

| 模块 | 状态 | 轮次 | 上游参照 / 判定依据 | 证据 |
|---|---|---|---|---|
| `lsp` | **缺口** | B7 | Code intelligence / LSP via plugins — 缺 LSP client 接线 | `` |
| `symbols_navigation` | **缺口** | B7 | symbol-level navigation & live type errors — 有快速索引但缺符号级导航与实时诊断 | `fast_index.py` |
| `code_review` | 已对齐 | — | Code Review / @claude review — 代码审查命令已在 | `cmd_review_cli.py` |
| `security_review` | 已对齐 | — | /security review — 安全审计与报告已在 | `cmd_safe.py`, `security_auditor.py` |
| `ultrareview` | **缺口** | B7 | claude ultrareview --trust-workspace — 缺带工作区信任门控的深度审查 | `cmd_review_cli.py` |

#### 云 / 远程 / 集成 `cloud_remote`

| 模块 | 状态 | 轮次 | 上游参照 / 判定依据 | 证据 |
|---|---|---|---|---|
| `remote_control` | 部分 | B9 | Remote Control (session host + reconnect) — 有远程控制模块但无 CC 对等的会话托管/重连语义 | `remote_control.py` |
| `cloud_sessions` | 不适用 | — | Web / mobile / desktop cloud sessions — Anthropic 托管云会话，需 claude.ai 订阅；本地离线 CLI 明确不实现 | — |
| `self_hosted_runner` | 不适用 | — | Self-Hosted Runner (Team/Enterprise, v2.1.224+) — Anthropic 托管编排，需 Team/Enterprise 订阅，不适用；不包装成领先 | — |
| `chrome_integration` | 不适用 | — | Claude in Chrome extension / computer use — 浏览器扩展与登录态依赖，需订阅；不实现 | — |
| `channels_voice` | 不适用 | — | Channels (Slack/Telegram), Voice Dictation — 研究预览 / 订阅功能；本地 CLI 不适用 | — |
| `gateway_managed_settings` | 不适用 | — | Claude apps gateway, managed policies, pooled budgets — 企业网关与计费策略，Anthropic 专属基础设施，不适用 | — |

#### 可观测 / 模型 / 成本 `observability_models`

| 模块 | 状态 | 轮次 | 上游参照 / 判定依据 | 证据 |
|---|---|---|---|---|
| `otel_metrics` | 部分 | B9 | OpenTelemetry metrics / events / spans — 有遥测与可观测模块，但缺 CC 对等的 OTel exporter 与标准事件 schema | `telemetry.py`, `observability.py` |
| `settings_layers` | 已对齐 | — | user / project / local / managed settings layers — 配置分层已在 | `` |
| `cost_budget` | **缺口** | B9 | /cost, /usage, --max-budget-usd, status line cost — 缺 token 成本计量与预算硬上限 | `cmd_model.py` |
| `feature_flags` | 不适用 | — | CLAUDE_CODE_DISABLE_FEATURE_FLAGS (v2.1.319) — CC 依赖远程 feature-flag 拉取；Tuan 无该机制，不适用而非领先 | — |
| `local_models_offline` | **领先** | — | Claude models / Bedrock / Vertex / Foundry — 完全本地离线、可接任意本地/兼容模型，不依赖账号登录与模型订阅 | ``, `README_zh-CN.md`, `SUPPORTED_MODELS.md` |
| `zero_telemetry` | **领先** | — | telemetry / feature-flag fetching (DISABLE_TELEMETRY opt-out) — Tuan 默认不外发；CC 需显式 DISABLE_TELEMETRY 才关闭（且 auto mode 曾因遥测关闭而回退分类器） | `telemetry.py`, `README_zh-CN.md` |

---

## 5. 差距队列（26 个，按轮次）

`tuan claude parity --gaps` 实时输出同一份清单；`--report-json` 供 CI 消费。

| 轮次 | 功能域 | 模块 |
|---|---|---|
| B10 | Git / 后台任务 | `scheduled_tasks_ui` |
| B10 | TUI 与交互 | `keybindings_chords` |
| B10 | TUI 与交互 | `output_styles` |
| B10 | TUI 与交互 | `prompt_suggestions` |
| B10 | TUI 与交互 | `statusline` |
| B2 | 安全与权限 | `os_sandbox` |
| B3 | 生命周期钩子 | `hook_events_extended` |
| B3 | 生命周期钩子 | `hook_updated_input_validation` |
| B4 | 技能与记忆 | `skill_integrity_signature` |
| B5 | 子代理与团队 | `task_list_earlier_in_session` |
| B6 | MCP 全栈 | `mcp_elicitation` |
| B6 | MCP 全栈 | `mcp_oauth` |
| B6 | MCP 全栈 | `mcp_tasks_background` |
| B6 | MCP 全栈 | `mcp_tool_search` |
| B7 | 代码智能 | `lsp` |
| B7 | 代码智能 | `symbols_navigation` |
| B7 | 代码智能 | `ultrareview` |
| B7 | 插件与市场 | `plugin_init_validate` |
| B7 | 插件与市场 | `plugin_lsp` |
| B7 | 插件与市场 | `plugin_marketplace` |
| B7 | 插件与市场 | `plugin_owner_wildcard` |
| B7 | 插件与市场 | `plugin_sha256_pin` |
| B8 | 模式与上下文 | `idle_compaction` |
| B9 | 可观测 / 模型 / 成本 | `cost_budget` |
| B9 | 安全扫描与审计 | `safety_event_otel` |
| B9 | 会话 / 无头 / SDK | `agent_sdk` |

按轮次（**上表只列 gap**）：B10 5 个、B2 1 个、B3 2 个、B4 1 个、B5 1 个、B6 4 个、B7 8 个、B8 1 个、B9 3 个。
若按 ``wave_load``（含仍带 wave 的 ``partial`` 模块）则为：B2 5、B3 2、B4 2、B5 1、B6 4、B7 10、B8 1、B9 5、B10 6，合计 36 —— 两种口径此前被混写，这里分开列清楚。

---

## 6. 分轮详细计划

每轮都必须同时满足 §9 的 6 条验收标准。**不靠改状态定义凑数，不为变绿放宽策略，不擅自翻破坏性默认值。**

### A 线（并行，不占 B 线轮次）

| 轮次 | 目标 | 产出 |
|---|---|---|
| A14 | `streaming_async` + `tools_exec` + `history_transcript` 剩余 5 个 （`streaming` / `async_question_reply` / `exec_command` / `rendered_selection` / `insert_history`） | 5 模块实现 + 回归，`pending 10→5` |
| A15 | 最后 5 个（`local_settings` / `clock_format` / `external_agent_config_migration` / `tests` / `auto_review_denials`） | 清零 `pending`，届时 `fully_identical` 才可能为 `true` |

### B 线

| 轮次 | 目标 | 交付 | 主要风险 / 不做的事 |
|---|---|---|---|
| **B1 ✅** | 基线 + 详细计划 + **hooks 默认 fail-closed 落地** | `parity_claude/` 4 模块、`CLAUDE_PARITY.md`、`tuan claude parity`、`tests/test_claude_parity.py` 58 例、`NOTICE` 14 条 | 行为变更已如实标注；不改 OS 沙箱默认值、不碰 A 线文件 |
| **B2 ◐ 部分** | 补齐最大落后项（原 5 个 gap） | 本轮落地 4 项：`network_default_deny`→partial、`credential_masking`→partial、`deny_instead_of_prompting`→aligned、`worktree_sandbox_escape`→aligned；新增 `egress.py` / `unattended.py` / `worktree_boundary.py` + 34 例回归，详见 §12 | **`os_sandbox` 仍为 gap**：没把 OS 级隔离变成默认执行边界，只修了 local 后端禁网裁决裸跑。出厂 `deny_network_by_default` 仍 false、未擅自翻；B2 未全清，故 `b_waves_done` 仍只有 B1 |
| **B3** | 7 个扩展 hook 事件（PermissionRequest / Notification / DirectoryAdded / ConfigChange / WorktreeCreate / Elicitation / ElicitationResult）+ `updatedInput` 按工具 schema 校验 | `HOOK_EVENTS` 扩展 + 四型 hook 统一失败语义 + 回归 | 通知类事件失败**只留痕不卡 turn**；不把新事件做成新的 fail-open 侧门 |
| **B4** | CLAUDE.md 语义等价的多层项目记忆 + `@` 文件提及 + **技能完整性签名与权限域声明** | `memory` 分层 + skill 签名校验 | 大文件不得被 Write 工具只看开头就覆盖（CC v2.1.312 刚修过）；技能不可悄悄扩权是 CC 无对等物的超越点 |
| **B5** | `/tasks` 持久化索引（含「Earlier in this session」）+ 每 subagent 独立沙箱与权限域 + 跨会话审计关联接到代理生命周期 | 子代理任务索引 + 权限域隔离 | 关联检测**纯观测，绝不反作用于裁决**（沿用 E4 约束） |
| **B6** | MCP OAuth / tool search / elicitation / tasks 后台化 | 复用已有 `mcp_trust_tier`，不重开侧门 | 长时 task 后台化不得让未登记 server 借机全放行 |
| **B7** | Plugins + Marketplace（HTTPS zip + **sha256 pin** + `owner/*` 通配） + LSP + 符号导航 + ultrareview | 清单模型 / 校验 / 安装通道 / LSP client | **默认 untrusted + 清单签名**；插件不以当前用户裸权限运行 |
| **B8** | permission modes 统一 + idle compaction + **确定性规则前置的形式化断言** | 模式矩阵 + 空闲压缩 + 规则前置断言 | 模型不作为安全边界；断言要挡住「有人把截断挪到原始文本」这类回归 |
| **B9** | Python SDK / ACP / OTel 标准 schema / cost+budget / `safety_event` 导出 / remote_control 收敛 | 可嵌入 SDK + 导出 + 预算硬上限 | 本地零遥测优先，导出必须显式开启；不因关闭遥测削弱安全判定 |
| **B10** | Vim 状态机 / chords / statusline / output styles / prompt suggestions / 任务面板 / 10 语言一致性 | 交互层收尾 | 与 A15 的 TUI 收尾合并验证；不得为对齐重开既有安全接线 |

### 6.1 每轮「超」的加法（不是复制）

CC 的每个能力补进 Tuan 时，都要附带一条 CC 没有的硬约束：

| 补齐项 | 附加的超越约束 |
|---|---|
| Hooks 全事件 | 默认 fail-closed（CC 需逐条 `onFailure:"block"`） |
| Subagents / Teams | 每 agent 独立权限域 + 沙箱 + 跨会话审计关联 |
| Skills | 完整性签名 + 权限域声明，技能不可悄悄扩权 |
| Plugins | sha256 pin + 默认 untrusted + 信任分级 + 会话内可回撤 |
| Checkpoints / Worktrees | 与 AEAD 审计链绑定，可回放 |
| Cost / OTel | 本地零遥测默认，导出显式开启 |
| 全部 | 每轮 `assert_wiring_intact()` 6 项既有接线全绿 |

---

## 7. B1 本轮落地：两个真实 fail-open 侧门

B1 不是只写计划。审计 `hooks/manager.py` 时发现两个与 CC `onFailure:"block"` 直接对应的静默放行：

**侧门 1 — hook 故障即放行。** `_exec_command` / `_exec_http` / `_exec_prompt` / `_exec_subagent` 在 spawn 失败、超时、`communicate` 异常、HTTP 错误、无模型/无内核时一律 `return None`；`run_pre()` 对 `None` 直接 `continue`。也就是说：**一个用来挡危险命令的 hook 自己挂了，命令照跑**。CC 直到 v2.1.317/319 才提供 `onFailure:"block"`，且需要用户逐条配置。

**侧门 2 — `blocking` 默认 False 吞掉阻断。** `_parse_spec` 里 `blocking=bool(item.get("blocking", False))`。hook 明明返回 `{"block": true}`，若没显式写 `blocking: true`，`run_pre` 只记一条 `block_denied` 而不阻断——配置侧门。

### 7.1 修法

- 新增 `HookFailure` 结构化记录与 `HookManager.failures()` / `clear_failures()` / `on_failure_policy()`；失败类型细分 `invalid_spec / spawn_error / timeout / error / nonzero_rc / http_error / no_kernel / no_model`。
- `hooks.on_failure` **出厂默认 `block`**，可设 `ask` / `allow`；单条 hook 可 `on_failure` 覆盖；未知取值回退最严格档并记审计。
- `PreToolUse` 遇 hook 故障：默认阻断，reason 带 `event / hook uid / kind / detail`，`HookDecision.failure_kind` 可机读。
- **`blocking` 改为默认 True**；仍可显式 `blocking: false` 关闭。注意 `blocking` 只管 hook **自己返回的** block 决策，**不管执行失败的 fail-closed** —— 失败阻断不受该开关影响。
- 通知类事件（PostToolUse / Stop / SubagentStop / Session* / UserPromptSubmit）没有 action 可阻断，失败**只留痕不卡住主回合**，但全部进 `failures()`。
- 看门狗线程只审计，**失败记录由主线程在 `killed` 分支补记**：`last_failure` 是 thread-local，若在看门狗线程写，`run_pre` 读不到，fail-closed 会被跨线程绕过（已由超时回归覆盖）。
- `config/security_schema.py` 增加 `hooks.on_failure` 白名单校验；显式 `allow` 报为「安全降级」warning。

### 7.2 行为变更（如实，需迁移）

| 变更 | 旧 | 新 | 逃生口 |
|---|---|---|---|
| hook 故障 | 静默放行 | 默认阻断 PreToolUse | `hooks.on_failure: allow`（全局或单条），会记 `failure_allowed` 审计 |
| `blocking` 默认值 | False（阻断被吞） | True | 单条 `blocking: false` |
| 既有测试 | `test_timeout_kills_hook` 断言「超时不阻断」 | 改为断言「超时 fail-closed 阻断」+ 新增 `test_timeout_can_be_explicitly_allowed` | 旧行为仍可通过 `allow` 到达 |

**这是安全加固，不是悄悄改语义**：如果生产环境依赖某个「挂了也放行」的 hook，升级后会被挡住，需要显式配置 `allow` 并接受审计告警。

### 7.3 配置层差异（别踩坑）

`HookManager` 读的是嵌套 `config.get("hooks")`，而 `validate_security_config` 用**扁平键** `"permissions.rules"` 与 嵌套 `"hooks"`。两者是不同配置层，写探针/接线时不可混用；已在 `superiority.py` 注释标明。

---

## 8. 如实边界

1. **最大落后项没修**：`os_sandbox` / `network_default_deny` / `credential_masking` / `worktree_sandbox_escape` 都在 B2。Claude Code 有 OS 级强制沙箱；Tuan 的 `--isolation` 是可选的 engine/process 级，`local` 后端 `enforced=False`。**不要因为本轮 6 个探针全绿就以为安全边界已经对齐**。
2. **`deny_network_by_default` 出厂仍是 `false`**（前 13 轮如实保留）。翻 true 是破坏性行为变更，B2 会给迁移开关，不擅自翻。
3. **`fully_superior=false`**：26 个缺口、B 轮完成 B1 且 **B2 部分落地**（未全清，`b_waves_done` 仍只有 B1）、第三方自适应红队未做。判据 5 项里只有 2 项为真。
4. **`not_applicable` 不包装成领先**：云会话 / self-hosted runner / Chrome / Channels / 语音 / 网关 / 1M 上下文 / effort / feature flags 共 8 项，如实标不适用。
5. **版本口径**：官方 changelog 按日期组织不写版本号，版本号取自 GitHub release 归档；若后续出新版本，先更新基线再谈超越。
6. **探针是内部证据，不是第三方证明**：六维探针真调现有代码，但仍是自测。静态基准 / 自建 fuzz / CI gate 都不能替代自适应红队。
7. **A 线未完成**：Codex TUI 对齐还剩 10 个 pending，`fully_identical=false`。两条线的「完成」互不替代。
8. **本轮改的是真实运行时**：`hooks/manager.py` 与 `config/security_schema.py` 是生产代码，不是只加 wrapper，风险比纯 wrapper 高，需上游复核；回归集已覆盖行为变更。

---

## 9. 每轮验收标准（六条，缺一不算完成）

1. 新增/修改模块状态有**实现 + 测试指向**，证据路径真实存在；
2. 既有回归全绿（含 `tests/test_hooks*.py`、`test_claude_parity.py`）；
3. `tuan claude parity` 自检干净（`validate == []`）；
4. 六个维度探针全 OK，且 `assert_wiring_intact()` 6 项既有接线完好；
5. 文档指标同步（本文档 §4 汇总、§5 队列、§6 路线、`CHANGELOG` / `SECURITY.md` / `SECURITY_EN.md` / `SECURITY_BASELINE.md` / `NOTICE`）；
6. **行为变更如实标注 + 迁移开关**，不为变绿放宽策略，不靠改状态定义凑数。

推送约束延续前 13 轮：**fast-forward、不 force push、不改写历史**。

---

## 10. 合规与归属

Claude Code 是 Anthropic 的**专有产品**（Commercial Terms of Service）。本计划与 `parity_claude` 包：

- 仅依据**公开文档、官方 changelog、GitHub release notes、功能目录**做行为契约与能力对标；
- **未复制任何源码、混淆产物或商标/品牌资产**，不使用其 ASCII art 或视觉元素；
- 「超」仅指可验证的能力与安全姿态对比，不代表 Anthropic 的 affiliation、赞助或背书；
- 全部来源列在 `catalog.SOURCES`（8 条），逐条带 URL 与取用说明。

归属与本地化修改点逐条记在 **`NOTICE` 第 14 条**。A 线的 Codex TUI 对齐仍按 `NOTICE` 第 9–13 条（Apache-2.0）处理，两条线的许可口径互不混用。


---

## 11. 增量：运行时标语（spinner verbs）与 TUI 状态口径修复

用户提供的 B 站视频标题「给 Claude Code 转圈的英文挂上中文后，我发现它在
摸鱼」点出一个被本计划矩阵**漏掉的 CC 标志性 UI 特性**：等待时 spinner 旁
随机显示一个英文动名词（v2.1.42 约 185 个，`~/.claude/settings.json` 的
`spinnerVerbs` 可 `replace`/`append` 定制，官方文档不收录）。中文社区把词表
译出后，「磨洋工 / 溜达 / 看报纸中」集体露馅，这就是「摸鱼」梗。

### 11.1 本轮落地

- `tuan_cli/tui/runtime_slogans.py`：10 语言词库、同款 `spinnerVerbs` 配置
  接口、OSC/CSI/C0/C1 净化、事件驱动引擎。完整说明见 `RUNTIME_SLOGANS.md`。
- **「超」的落点不是词多，是诚实**：上游那些词纯随机、不对应任何阶段或
  进展。本实现把标语绑定到真实事件（`submit` / 流式分片 / `begin_tool`），
  `render()` 纯读不转词；忙碌中超过 `stall_ms` 无事件则显示「疑似摸鱼」
  诊断。这是对 §3 维度「可观测/诚实」的加法，不是复制文案。
- 顺带修主线同样存在的状态口径分裂（footer 工具运行期显示 `Working` 而非
  工具名）与双宽度算法分裂；并修正「wcwidth 是 C 实现」的错误注释。

### 11.2 口径决定：99 基线不动，`fully_superior` 仍为 false

**刻意不把 spinner verbs 加成第 100 个模块**：它属于 UI 文案层，不是独立
功能域，作为 B10 `statusline` 的前置实现记录更准确；加模块会连带改
`ahead/aligned/partial/gap` 四个计数、§4 汇总、§5 队列与多处测试断言，
正是 §9「不靠改状态定义凑数」要防的动作。因此 **`fully_superior` 仍为
`false`，26 个缺口，B3–B10 未完，第三方自适应红队未做**。

### 11.3 推送范围（如实）

本提交基于远端真实 HEAD `8611d5ddf` 逐文件比对 tree 做增量提交。
核查发现本地工作副本与远端主线**存在实质分叉**（`tui.py` 4694 行 vs
2563 行等），因此此前若干轮次在本地副本上的改动**未推送**，避免覆盖回退
主线；只推 3 个新增文件 + 1 个在远端基线上精确改动的 `tui.py` +
7 个追加文档。本地分叉改动另打包，需人工决定是否合并。

### 11.4 合规

Claude Code 是专有产品。本轮仅依据公开资料做行为对标，**未复制任何源码、
混淆产物或商标资产**；中文词池里「腌制入味 / 磨洋工 / 看报纸中」等短词条
借鉴自公开社区对 185 词的译名（事实性短 UI 文案），其余词条、阶段划分、
10 语言自译、事件驱动引擎与诊断均为独立编写。归属记在 `NOTICE` 第 15 条，
Anthropic 不背书。视频正文未获取，不转述其内容。


---

## 12. 深度轮声明：指标一律不动

用户要求「不再执着于广度而放弃深度」。本轮**只深化 §11 的运行时标语**，
因此以下关于「超 Claude Code」的判据**全部保持原值，不是成果**：

- `fully_superior` 仍为 `false`；**26 个缺口**，B3–B10 未完；
- 99 模块、14 域，`ahead / aligned / partial / gap / not_applicable`
  五个计数**一个都没动**；
- 六维探针与 `superiority_criteria` 六项判据**一个都没动**；
- 第三方自适应红队仍未做，静态基准不能当对抗证明；
- 未新增 CLI 子命令（51 / 含嵌套 197 不变）。

刻意不把「并发安全 / 分阶段预算 / 结构化活性」包装成新的 `ahead` 项：
它们属于既有 UI 能力的工程正确性，不是新的功能域；加条目会连带改
§4 汇总、§5 队列与多处测试断言，正是 §9「不靠改状态定义凑数」要防的。

本轮的真实内容是修三个工程缺陷：无锁并发竞态、单一 15s 阈值语义过浅、
缺省 `mode` 导致合法配置被静默误拒。详见 `RUNTIME_SLOGANS.md` §10。


---

## 13. 深度轮 2 声明：指标仍一律不动

延续 §12，本轮把运行时标语的**净化边界**继续往下挖，因此
「超 Claude Code」的所有判据**保持原值，不是成果**：

- `fully_superior` 仍为 `false`；**26 个缺口**，B3–B10 未完；
- 99 模块、14 域与五个状态计数一个没动；六维探针与
  `superiority_criteria` 六项判据一个没动；
- 第三方自适应红队仍未做；未新增 CLI 子命令（51 / 含嵌套 197 不变）。

刻意不把「bidi 净化 / 宽度收口 / 短版诊断」包装成新的 `ahead` 项：
它们属于既有 UI 能力的**工程正确性与修上一轮未兑现的承诺**，
不是新的功能域。加条目会连带改 §4 汇总、§5 队列与多处断言，
正是 §9「不靠改状态定义凑数」要防的。详见 `RUNTIME_SLOGANS.md` §11。


---

## 14. 「每个标语都要对应的」声明：指标仍一律不动

本轮接入的是用户提供的标语库 (15 文件 / 860 条), 属于**既有 UI 文案
能力的工程正确性**, 不是新的功能域。因此关于「超 Claude Code」的所有
判据**保持原值, 不是成果**:

- `fully_superior` 仍为 `false`; **26 个缺口**, B3–B10 未完;
- 99 模块、14 域与五个状态计数一个没动; 六维探针与
  `superiority_criteria` 六项判据一个没动;
- 第三方自适应红队仍未做; 未新增 CLI 子命令 (51 / 含嵌套 197 不变)。

刻意不把「一一对应表 / 240 条补池 / 严格分发」包装成新的 `ahead` 项:
加条目会连带改 §4 汇总、§5 队列与多处断言, 正是 §9「不靠改状态定义
凑数」要防的。`audit().ok` 是另一套独立的运行时不变量, 与「超不超」
这条线**不混用口径**。详见 `SLOGAN_MAPPING.md`。


---

## 15. 运行时闭环声明：指标仍一律不动

本轮把上一轮的静态对应表在**运行时**做实 (留痕反查 / 错误不静默 /
按会话分域 / O(1) 索引 / 可确定性回放), 属于既有 UI 能力的工程
正确性, 不是新的功能域。关于「超 Claude Code」的所有判据
**保持原值, 不是成果**:

- `fully_superior` 仍为 `false`; **26 个缺口**, B3–B10 未完;
- 99 模块、14 域与五个状态计数一个没动; 六维探针与
  `superiority_criteria` 六项判据一个没动;
- 第三方自适应红队仍未做; 未新增 CLI 子命令 (51 / 含嵌套 197 不变)。

18 个事件、16 个上下文、1108 条标语词条全部不变。`audit()` 新增的
第 11 项不变量 `index_consistent` 是另一套独立的运行时自检,
与「超不超」这条线**不混用口径**。详见 `SLOGAN_MAPPING.md` §11。


---

## 16. 闭环补漏声明：指标仍一律不动

本轮修的是既有 UI 能力的工程正确性（净化后索引、桶上界、错误双层
留痕、避重窗口容量、不变量加严），不是新的功能域。关于「超 Claude
Code」的所有判据**保持原值，不是成果**：

- `fully_superior` 仍为 `false`；**26 个缺口**，B3–B10 未完；
- 99 模块、14 域与五个状态计数一个没动；六维探针与
  `superiority_criteria` 六项判据一个没动；
- 第三方自适应红队仍未做；未新增 CLI 子命令（51 / 含嵌套 197 不变）。

18 个事件、16 个上下文、1108 条标语词条全部不变。`audit()` 的新增
不变量是另一套独立的运行时自检，与「超不超」这条线**不混用口径**。
详见 `SLOGAN_MAPPING.md` §12。


---

## 17. 自愈/证据保全声明：指标仍一律不动

本轮修的是既有 UI 能力的工程正确性（连续 miss 自愈、会话退出证据
封存、LRU 读刷新、日志字段净化、信息项与 fatal 分离、单一渲染出口），
不是新的功能域。关于「超 Claude Code」的所有判据**保持原值，
不是成果**：

- `fully_superior` 仍为 `false`；**26 个缺口**，B3–B10 未完；
- 99 模块、14 域与五个状态计数一个没动；六维探针与
  `superiority_criteria` 六项判据一个没动；
- 第三方自适应红队仍未做；未新增 CLI 子命令（51 / 含嵌套 197 不变）。

18 个事件、16 个上下文、1108 条标语词条全部不变。`audit()` 的
fatal/信息项分离是另一套独立运行时自检，与「超不超」这条线
**不混用口径**。详见 `SLOGAN_MAPPING.md` §13。


---

## 18. owner 归一 / 淘汰留痕声明：指标仍一律不动

本轮修的是既有 UI 能力的工程正确性（public 入参 `owner` 全链路归一
且严格幂等、`limit` 类型校验、LRU 被动淘汰留脱敏痕迹、`close()`
收敛单一释放出口、封存写加锁），不是新的功能域。关于「超 Claude
Code」的所有判据**保持原值，不是成果**：

- `fully_superior` 仍为 `false`；**26 个缺口**，B3–B10 未完；
- 99 模块、14 域与五个状态计数一个没动；六维探针与
  `superiority_criteria` 六项判据一个没动；
- 第三方自适应红队仍未做；未新增 CLI 子命令（51 / 含嵌套 197 不变）。

18 个事件、16 个上下文、1108 条标语词条全部不变。`evicted_recent`
是观测项、**不参与** `audit().ok`，也不计入「超不超」这条线，
两套口径不混用。详见 `SLOGAN_MAPPING.md` §14。


---

## 19. 净化顺序 / 时钟贯穿声明：指标仍一律不动

本轮修的是既有 UI 能力的工程正确性（日志字段先清理后截断、
连续 ESC 串不再吞字符、淘汰痕与 decision 共用注入时钟、
`reason_counts` 摘要、`OWNER_LIMIT` 口径精确化），不是新的功能域。
关于「超 Claude Code」的所有判据**保持原值，不是成果**：

- `fully_superior` 仍为 `false`；**26 个缺口**，B3–B10 未完；
- 99 模块、14 域与五个状态计数一个没动；六维探针与
  `superiority_criteria` 六项判据一个没动；
- 第三方自适应红队仍未做；未新增 CLI 子命令（51 / 含嵌套 197 不变）。

18 个事件、16 个上下文、1108 条标语词条全部不变。
`reason_counts` / `evicted_recent` 是观测项、**不参与** `audit().ok`，
也不计入「超不超」这条线，两套口径不混用。
详见 `SLOGAN_MAPPING.md` §15。


---

## 20. ESC+ / 时钟 / 摘要声明：指标仍一律不动

本轮修的是既有 UI 能力的工程正确性（OSC/CSI 允许 `ESC+` 引导、
注入时钟严格类型校验、owner 有界摘要、累计淘汰证据），不是新的
功能域。关于「超 Claude Code」的所有判据**保持原值，不是成果**：

- `fully_superior` 仍为 `false`；**26 个缺口**，B3–B10 未完；
- 99 模块、14 域与五个状态计数一个没动；六维探针与
  `superiority_criteria` 六项判据一个没动；
- 第三方自适应红队仍未做；未新增 CLI 子命令（51 / 含嵌套 197 不变）。

18 个事件、16 个上下文、1108 条标语词条全部不变。
`evicted_total` 是观测项、**不参与** `audit().ok`，也不计入
「超不超」这条线，两套口径不混用。详见 `SLOGAN_MAPPING.md` §16。


---

## 21. 裁剪证据声明：指标仍一律不动

本轮修的是既有 UI 能力的**可观测性**（桶内裁剪留痕、累计决策数），
不是新的功能域。关于「超 Claude Code」的所有判据**保持原值，
不是成果**：

- `fully_superior` 仍为 `false`；**26 个缺口**，B3–B10 未完；
- 99 模块、14 域与五个状态计数一个没动；六维探针与
  `superiority_criteria` 六项判据一个没动；
- 第三方自适应红队仍未做；未新增 CLI 子命令（51 / 含嵌套 197 不变）。

18 个事件、16 个上下文、1108 条标语词条全部不变。
`trimmed_decisions` / `bucket_trims` / `decisions_total` 是观测项、
**不参与** `audit().ok`，也不计入「超不超」这条线。
详见 `SLOGAN_MAPPING.md` §17。


---

## 22. public 入参类型面声明：指标仍一律不动

本轮修的是既有 UI 能力的**入参健壮性**（event 类型守卫、
非字符串 owner 隔离留痕），不是新的功能域。关于「超 Claude Code」
的所有判据**保持原值，不是成果**：

- `fully_superior` 仍为 `false`；**26 个缺口**，B3–B10 未完；
- 99 模块、14 域与五个状态计数一个没动；六维探针与
  `superiority_criteria` 六项判据一个没动；
- 第三方自适应红队仍未做；未新增 CLI 子命令（51 / 含嵌套 197 不变）。

18 个事件、16 个上下文、1108 条标语词条全部不变。
`invalid_owner_calls` / `invalid_owner_types` 是观测项、
**不参与** `audit().ok`，也不计入「超不超」这条线。
详见 `SLOGAN_MAPPING.md` §18。


---

## 23. 引擎入参面声明：指标仍一律不动

本轮修的是**运行时标语引擎本体**（``tui/runtime_slogans.py``）的
public 入参健壮性，不是新的功能域。关于「超 Claude Code」的所有判据
**保持原值，不是成果**：

- `fully_superior` 仍为 `false`；**26 个缺口**，B3–B10 未完；
- 99 模块、14 域与五个状态计数一个没动；六维探针与
  `superiority_criteria` 六项判据一个没动；
- 第三方自适应红队仍未做；未新增 CLI 子命令（51 / 含嵌套 197 不变）。

18 个事件、16 个上下文、1108 条标语词条全部不变。
`_now()` / `_safe_source()` / `source` 净化都是既有能力的可观测性
与健壮性补漏，**不参与** `audit().ok`，也不计入「超不超」这条线。
详见 `SLOGAN_MAPPING.md` §19。


---

## 24. 注入契约轮声明：指标仍一律不动

本轮修的是运行时标语引擎的**注入契约与配置切换锚点**
（`__init__` 的 falsy 注入、`load_config` 静默截断、
`reload()` 的 `(seq, verb)` 对齐），不是新的功能域。关于
「超 Claude Code」的所有判据**保持原值，不是成果**：

- `fully_superior` 仍为 `false`；**26 个缺口**，B3–B10 未完；
- 99 模块、14 域与五个状态计数一个没动；六维探针与
  `superiority_criteria` 六项判据一个没动；
- 第三方自适应红队仍未做；未新增 CLI 子命令（51 / 含嵌套 197 不变）。

18 个事件、16 个上下文、1108 条标语词条全部不变。
`kind="reload"` 证据与 `invalid:too-many-verbs` 都是既有能力的
健壮性补漏，**不参与** `audit().ok`，也不计入「超不超」这条线。
详见 `SLOGAN_MAPPING.md` §20。


---

## 12. B2 落地：先修实测 fail-open，不靠改状态凑数

B2 原计划列了 5 个 gap。本轮**没有**把它们一股脑改成 aligned —— 只把
4 个有真实代码 + 真实接线 + 真实测试的能力推进，`os_sandbox` 保持 gap。
结果：`gap 30 → 26`、`aligned 43 → 45`、`partial 8 → 10`，
`fully_superior` 仍 `false`，`b_waves_done` 仍 `["B1"]`（B2 未全清）。
`tuan claude parity --gaps` 与 `§5` 队列已同步到 26。

### 最值钱的发现：宣称与实现之间的断层

`SandboxManager._execute_backend` 算出 `block_net = not verdict.network`，
但 `local` 分支调用 `run_with_tree_kill` 时 **既不传 block_net 也不传
env**。实测两件事：

1. 当 `verdict.network=False` 且后端落到 `local`，命令仍以父进程完整
   `os.environ` 裸跑 —— 「默认禁网」在**唯一没有 OS 级出网隔离能力**
   的后端上静默失效。L2 的 `_has_network_request` 只是命令文本识别，
   前几轮 fuzz 已证明零宽字符 / ANSI-C / 注释换行都能绕过文本层。
2. 父进程里的 `GITHUB_TOKEN` / `AWS_SECRET_ACCESS_KEY` 等真实凭据
   原样进入子进程，与目录里「子进程不持密钥」的宣称相反。

也就是说 `network_default_deny` 和 `credential_masking` 这两个最大落后项，
不是「缺一个大功能」，而是**已有开关在执行层根本没接线**。这比新写
一个沙箱更值得先做。

### 四个模块的真实落地

| 模块 | 旧 → 新 | 做了什么 |
|---|---|---|
| `network_default_deny` | gap → **partial** | `egress.py::enforce_local_egress`：local + 禁网 **fail-closed 拒绝**，绝不假装禁网成功；强后端仍走自身边界。出厂 `deny_network_by_default` 仍 false（未擅自翻），逐命令 `allowed_domains` 强绑定仍缺 → 只标 partial |
| `credential_masking` | gap → **partial** | `CredentialBroker`：子进程环境里敏感键替换为 `tuan-egress-sentinel-v1:<fp>`，真实值只在进程内内存；`repr` / 审计 / 异常 / `to_audit_dict()` 均不泄露。出网代理注入 `inject_headers()` 是**默认关闭**的预留接口，没有转发进程调用它 → 只标 partial |
| `deny_instead_of_prompting` | gap → **aligned** | `unattended.py`：显式开关（默认关）、`no_confirm_channel` / `all_confirmations` 两种 scope、`denied=True` 是硬事实而 `continue_turn` / `suppressed_prompt` 结构化写入 `verdict.extra` 与可查询审计；**真接**到 `assess_tool` 的 CONFIRM 路径，配置非法 fail-closed |
| `worktree_sandbox_escape` | gap → **aligned** | `worktree_boundary.py` **真接线**到 `worktree_layer.py`：`create` / `create_agent_worktree` 在 fast-resume **之前**断言解析后 target 在 workspace 内（含 symlink 祖先）；`_git` 剥离 `GIT_DIR` / `GIT_WORK_TREE` / `GIT_INDEX_FILE` 等重定向变量并拒绝 `git -C` / `--git-dir` 越界 argv |

**`os_sandbox` 保持 gap**：本轮只修了 local 后端的禁网裁决，没有把
Landlock/seccomp/Seatbelt 这类 OS 级隔离变成**默认执行边界**，
`enforce_required=True` 仍要求显式可用的强后端。这是最大落后项，
不因为「egress 修好了」就改状态。

### 新增配置与行为变更（如实）

| 键 | 默认 | 说明 |
|---|---|---|
| `sandbox.resource.egress_credential_masking` | `true` | 敏感环境变量替换为 sentinel。**行为变更**：依赖真实凭据的子进程需显式关闭；关闭时 `config validate` 报安全降级 |
| `sandbox.resource.egress_block_local_when_denied` | `true` | local 后端收到禁网裁决时拒绝执行。显式关闭报安全降级 |
| `permissions.denyInsteadOfPrompting` | `false` | 开启后无人值守的需确认调用直接拒绝并继续 turn；`config validate` 报**行为变更** warning |
| `permissions.denyInsteadOfPromptingScope` | `no_confirm_channel` | 或 `all_confirmations`；非法值在配置阶段拒绝 |

`deny_network_by_default` **仍是 false**，没有翻。前 13 轮明确承诺
「翻 true 是破坏性行为变更，需给迁移开关、不擅自翻」，本轮兑现的是
「执行层不再静默失效」，不是「默认禁网」。

### 口径修正（两处历史笔误）

1. 本文档 §3 / §5 / §10 曾写 **30 个缺口**，而 §11 之后十几轮追加段落
   一直复制「**25 个缺口不变**」—— 实际 `catalog.py` 里是 30。
   本轮把这些历史段落统一改成 **26**（B2 后的真实值），不再声称「不变」。
   此前回复里跟着写过 25，一并更正。
2. §5 末尾「按轮次」一行混用了两种口径：表格只列 `gap`，数字却是
   `wave_load`（含仍带 wave 的 `partial`）。现在分开列：
   gap 26 / wave_load 36。

### 验证

```
tests/test_b2_boundaries.py                                  34 passed
tests/test_claude_parity.py + test_cli_parity.py +
  test_headless_parity.py                                   108 passed (合计)
sandbox / worktree / hooks / config / hardening 相关批次     353 passed
  + 3 项 config.schema 在完整副本补齐后全绿
matrix.validate() == []  |  security_wiring_intact = true
fully_superior = false   |  criteria 2 真 3 假
```

**两条既有测试断言同步到新基线，不是放宽**：
`test_status_counts_are_derived` 的 `by_status` 与
`test_gaps_listing` 的「待补齐队列」都改为与 `catalog` 派生一致的新数值，
断言强度不变（仍要求总和 99、逐项对应）。

### 如实边界

1. `fully_superior` 仍 **false**：26 个缺口、B2 未全清（`b_waves_done`
   仍只有 B1）、第三方自适应红队未做。判据一条没改。
2. `os_sandbox` 仍是 gap；`network_default_deny` / `credential_masking`
   是 partial 不是 aligned，理由写在各自的 note 里。
3. `inject_headers()` 默认关闭、没有出网代理进程，**不宣称**「CC 的
   sentinel + 代理注入已完整对等」。
4. 新增两个默认 `true` 的出网开关是**修复实测 fail-open**，但确实改变
   了「依赖真实凭据的子进程」的行为，已在上表标注逃生口。
5. 不是真机多平台验证：Linux 本机路径与 mock 覆盖；Windows Job Object /
   macOS Seatbelt 的强后端网络隔离未在本轮实机跑过。
6. A 线（Codex TUI 完全相同）仍剩 10 个 pending，`fully_identical=false`，
   与 B 线互不替代；分叉改动仍未合并；静态基准不能当对抗证明。
7. 本轮未新增第三方素材，`NOTICE` 第 9–15 条归属不变；标语引擎 /
   净化层 / `_clean.py` / `mapping.py` / `tui.py` 逐字节未改。
