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
2. **全模块盘点**：99 个模块分 14 个域，五态标注。当前 **领先 10 / 已对齐 46 / 部分 9 / 缺口 26 / 不适用 8**（B2 落地 4 项 + 收尾 1 项，见 §12/§13）。`not_applicable` 如实标不适用，**不包装成领先**。
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
| 安全与权限 `security_permissions` | 8 | 0 | 4 | 3 | 1 | 0 |
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
| **合计** | **99** | **10** | **46** | **9** | **26** | **8** |

状态定义即约束（`evidence.py` 运行时校验）：`ahead` 必须有 `ahead_reason` + 合法维度 + 存在的证据路径；`gap` 必须分配到某个 wave；`not_applicable` 不得带 wave 且必须写清理由；所有非 NA 模块的证据路径必须真实存在。想把缺口改成领先，就得补真实证据、写清理由、跑通探针——**改状态定义凑数会被自检拦下**。

### 4.2 逐域逐模块

#### 安全与权限 `security_permissions`

| 模块 | 状态 | 轮次 | 上游参照 / 判定依据 | 证据 |
|---|---|---|---|---|
| `os_sandbox` | **缺口** | B2 | 仍是最大落后项：CC 有 OS 级强制沙箱，Tuan 的 --isolation 是可选 engine/process 级。B2 补上 local 后端禁网裁决的 fail-closed 拒绝，但**没有**把 OS 级隔离变成默认执行边界 | `backends.py`, `manager.py`, `egress.py` |
| `network_default_deny` | 部分 | B2 | B2 修复执行层：local+禁网 fail-closed 拒绝（旧实现 block_net 未接线而裸跑）。仍缺：出厂 `deny_network_by_default` 仍 false、逐命令 `allowed_domains` 强绑定 | `egress.py`, `test_b2_boundaries.py` |
| `network_strict_allowlist` | 已对齐 | — | B2 收尾：逐命令 `allowed_domains` → `verdict.extra` → `SandboxProfile.allowed_domains` → **本地回环出网代理**在 CONNECT/明文 HTTP 主机层强绑定；声明外 403，检测不到域名也不静默放行（§13） | `egress_allowlist.py`, `egress_proxy.py`, `test_b2_egress_strict.py` |
| `credential_masking` | 部分 | B2 | sentinel 代理已落地；B2 收尾把 `inject_headers()` 接成**真实调用方**（明文 HTTP 代理转发还原真实凭据，真 socket 验证）。仍为 partial：HTTPS CONNECT 隧道看不到 header，注入不可用（§13） | `egress.py`, `egress_proxy.py`, `test_b2_egress_strict.py` |
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
| **B2 ◐ 部分（含收尾）** | 补齐最大落后项（原 5 个 gap） | 首轮 4 项（§12）+ 收尾 `network_strict_allowlist`→aligned、`credential_masking` 接真实代理（§13）；新增 5 个模块 + 77 例回归 | **`os_sandbox` 仍为 gap**：没把 OS 级隔离变成默认执行边界。出厂 `deny_network_by_default` 仍 false、未擅自翻；B2 未全清，`b_waves_done` 仍只有 B1 |
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


---

## 13. B2 收尾：把域名强绑定从文本层搬到出网路径

B2 首轮（§12）修掉的是「已有开关在执行层没接线」。收尾这轮盯着另一个
同类断点：**白名单只活在命令文本里，执行层和出网路径上完全没有域名概念**。

### 实测缺口（先复现再修）

| 复现 | 结果 |
|---|---|
| `SandboxProfile` 字段 | 只有 `network: bool` / `filesystem_ro` / `writable_paths` / `blocked_paths` / 内存 / CPU / `env_allowlist` —— **没有任何域名字段** |
| `SandboxManager._run_provider` | `SandboxProfile(network=verdict.network, max_memory_mb=...)` —— 强后端拿到的是「全开 / 全关」 |
| `assess_command('curl https://evil.example/x')` | `verdict.extra = {}` —— 裁决结果**不携带**本次允许哪些主机 |
| `TrustFilter` 的白名单 | 用 `guard.check(text).detected_domains` 做**文本识别**；前几轮 477 条 fuzz 已证零宽字符 / ANSI-C / 注释换行 / 变量间接引用可绕过 |

先纠正一处我自己的误读：首轮复现脚本里打印的是 `verdict.network` /
`verdict.isolate` 而非 `action`，一度以为全局白名单失效。补测确认
`TrustFilter.check` 对声明外域名确实返回 DENY —— **文本层是生效的**。
真正的缺口是「执行层拿不到域名」和「文本识别不是出网路径上的强制」。

### 落地：五个模块 / 三处真接线

| 模块 | 作用 |
|---|---|
| `sandbox/egress_allowlist.py` | `normalize_domain`（严格归一化）、`NetworkClaim`（**逐命令**声明 + `strict`）、`claim_from_args`（工具参数优先、回落全局并如实标 `source`）、`evaluate_claim`（声明外拒绝；`strict` 且未声明任何主机时拒绝一切；检测不到域名**标记 `undetectable`** 而不是悄悄当已证明合规） |
| `sandbox/egress_proxy.py` | **真实可运行**的 stdlib 本地回环代理：`CONNECT` 按 claim 校验主机（声明外 403、允许则建隧道）；明文 HTTP 绝对 URI 同样校验，转发时用 `CredentialBroker.inject_headers()` 把 sentinel 还原成真实值 |
| `core/sandbox_provider.py` | `SandboxProfile` 新增 `allowed_domains` 字段。**如实说明**：bwrap / seatbelt 只有 network namespace / IP 级规则，没有域名级过滤，这个字段是给后端参考的元数据；真正的强制点在代理 |
| `sandbox/manager.py` | `assess_tool` / `assess_command` 把 claim 写进 `verdict.extra`；`_run_provider` 传进 `SandboxProfile`；`_execute_backend` 的 local 分支用 `try/finally` 管代理生命周期，注入 `HTTP_PROXY`/`HTTPS_PROXY`/`ALL_PROXY` 并清空 `NO_PROXY` |
| `config/security_schema.py` | `sandbox.resource.egress_proxy_enabled` 校验；开启报**行为变更** warning |

**关键设计**：域名的最终强制点是**出网路径**（代理的主机校验），不是文本层。
`strict` 模式下即使命令文本里一个域名都检测不到也放行到代理，由代理在
CONNECT / HTTP 主机层裁决 —— 这样零宽字符绕过文本识别也没用。

### A′：本轮自己引入、自己抓回的静默放宽

初版 `normalize_domain` 用 `str.encode("idna")` 处理大小写与尾点。实测：

```
normalize_domain("evil\u200b.example")  ->  "evil.example"     # ZWSP 被 IDNA 丢弃
normalize_domain("api.github\u200b.com") -> "api.github.com"
```

攻击者只要在真实主机里插一个零宽字符，就能让「另一个主机」匹配上白名单
声明 —— 这正是前几轮反复强调的「静默折叠」。已加 **ASCII 约束 + 逐字符
白名单**先挡住，非 ASCII 一律返回 `None`；脏声明记为 `invalid_values`
并让 `evaluate_claim` fail-closed。代价是不支持国际化域名，如实写在边界里。

### 矩阵：不靠改口径凑数

> **§14 纠偏**：本节写「claim 的裁决层强绑定始终生效」时说得太满。
> 下一轮实测发现它只在 `_execute_backend` 的 **local 分支**生效，
> 强后端三条路径完全没有防护，`aligned` 的边界因此比本节写的窄得多。
> 状态未回退（能力已落地且缺口被如实拒绝，不是静默放行），但口径以 §14 为准。

`aligned 45 → 46`、`partial 10 → 9`，**`gap` 仍是 26**。
`network_strict_allowlist` 本来就是 `partial` 不是 `gap`，推进它不减少缺口；
`credential_masking` 保持 `partial`（理由见下）。
`fully_superior` 仍 `false`，`b_waves_done` 仍 `["B1"]`，判据一条没改。
两条既有计数断言同步到新基线，**不是放宽**（仍要求总和 99、逐项对应）。

### 如实边界

1. **`credential_masking` 仍是 partial**：明文 HTTP 的 sentinel 注入已真接线
   （真 socket 端到端验证，上游 `Authorization` 拿到真实值）；
   但 HTTPS 走 CONNECT 隧道后代理只转发加密字节、**看不到 header**，
   无法注入。覆盖 HTTPS 需 TLS 中间人 + 本地 CA 信任，会显著扩大攻击面，
   本轮不做，也不谎称与 CC「sentinel + 代理注入」完整对等。
2. **bwrap / seatbelt 没有域名级过滤**：`SandboxProfile.allowed_domains`
   只是元数据，不假装 OS 级后端能按域名放行。
3. `sandbox.resource.egress_proxy_enabled` **默认 false**：开启会改写所有
   子进程代理环境变量，是行为变更；只有显式开启 + `strict` 逐命令声明
   才构造代理。**§14 纠偏**：「claim 的裁决层强绑定始终生效」仅对 local
   分支成立；强后端没有接到 claim，且 `run_syscall_sandboxed` 连 env 都
   没有，父进程真实密钥原样进子进程。本轮已统一修复，见 §14。
4. `os_sandbox` 仍是 **gap**，`deny_network_by_default` 出厂仍 **false**、未翻。
   `block_writes_outside_wd` 仍是 partial，未在本轮动。
5. `evaluate_claim` 的 `undetectable` 是**标记**而非证明：文本层检测不到时
   依赖代理主机校验，若调用方绕过了 `env_overrides`（例如命令显式指定
   `--noproxy`），强绑定就失效。这是本地 CLI 的固有限制，不是漏洞伪装。
6. 不是真机多平台验证；A 线 10 个 pending、分叉改动、第三方自适应
   红队仍未完成。标语引擎 / 净化层 / `mapping.py` / `tui.py` 逐字节未改。

### 验证

```
tests/test_b2_egress_strict.py                    43 passed（含真实 socket 代理端到端）
tests/test_b2_boundaries.py + parity/CLI/headless   全绿（合并批次）
matrix.validate() == []  |  evidence.verify_evidence() == []
verify_doc_numbers.py problems == []
fully_superior = false   |  gaps = 26  |  criteria 2 真 3 假
```


---

## 14. 深度轮：所有执行分支共用一个出网/凭据出口（纠偏 §13）

不扩广度，**矩阵计数一个没动**（`ahead 10 / aligned 46 / partial 9 /
gap 26 / not_applicable 8`，`fully_superior=false`，`b_waves_done=["B1"]`）。
这轮只做一件事：把上一轮自己接的链路逐分支实测一遍。

### 最值钱的发现：安全等级更高的路径反而没有刚补的防护

§13 把逐命令域名强绑定接到了 ``_execute_backend`` 的 **local 分支**。
逐分支核对 ``SandboxManager`` 源码后，实际覆盖是这样：

| 分支 | EgressGuard（凭据脱敏） | claim 检查 | 代理 env 注入 | `last_egress` |
|---|---|---|---|---|
| `local` | 有 | 有（裁决层） | 有 | 有 |
| `landlock` / `docker` / `seatbelt` / `bwrap` | **无** | 只传元数据 | **无** | **无** |
| `jobobject`（`_run_syscall`） | **无** | **无** | **无** | **无** |
| `copy_diff_apply` | 随下游 | 随下游 | 随下游 | 随下游 |

三处具体断点，都是**实测**不是推断：

1. ``SandboxProfile.allowed_domains`` 在整个 ``sandbox_provider.py`` 里
   **只出现 1 次** —— 就是 dataclass 字段定义，**没有任何后端消费它**。
   §13 写「只是元数据」属实，但没说**因此 strict claim 在强后端下
   完全失效**：把缺口当边界写，口径偏乐观。
2. ``_run_provider`` 调 ``provider.run(...)`` 不传 ``env``，走的是
   ``sanitize_env``（敏感键置空串），**不是** EgressGuard 的 sentinel +
   ``CredentialBroker`` 链路。
3. **最严重**：``_run_syscall`` 调 ``run_syscall_sandboxed``，该函数
   **根本没有 ``env`` 参数**。所有 ``Popen`` / ``run_with_tree_kill`` /
   ``os.execvp`` 一律继承父进程完整环境 —— Windows Job Object / Linux
   seccomp / 各 fallback 路径上，**真实密钥原样进入子进程，连置空都没有**。
   安全等级最高的路径，凭据保护反而是零。

### 落地：`plan_egress` 单一出口 + platform 层 env 全透传

| 模块 | 作用 |
|---|---|
| `sandbox/egress_plan.py`（新） | ``plan_egress(verdict, backend, policy, base_env)`` 在**分支之前**统一裁决，产出 `EgressPlan`（mode / env / claim / broker / 审计）。`plan_is_consistent_with_verdict()` 校验审计里的 claim 真的来自本次 verdict，防「说一套做一套」 |
| `sandbox/manager.py` | `_execute_backend` 删掉 local 分支里重复的 EgressGuard + 代理判断，四条路径统一拿 `plan.env` 并统一写 `last_egress`（含 `enforcement` / `claim_consistent` / `proxy_enabled`）；`_run_provider` / `_run_syscall` 新增 `env` 参数；`_make_egress_proxy(plan)` 只认 `plan.wants_proxy`，不再自己重复判断 |
| `arch/platform.py` | `run_syscall_sandboxed` / `_linux_seccomp_sandbox` / `_windows_job_object_sandbox` 全部新增 `env` 参数，透传到 Windows Job Object `Popen`、Linux seccomp `os.execvpe`、`unshare -n` 分支、Linux fallback `Popen`、其它平台 `run_with_tree_kill`。`env=None` 保持原继承语义，**旧调用点行为不变** |
| `config/defaults.py` + `security_schema.py` + `cli/cmd_harden.py` | 新键 `sandbox.resource.strict_claim_strong_backend`（`deny` 默认 / `metadata_only` 降级）。schema 只认两个枚举值，拼错**阻断**不是静默回落；`metadata_only` 报安全降级 warning；`tuan harden status` 打印当前策略并列入待加固项 |

**两条可执行契约**：

- **凭据**：任何后端都拿 `plan.env`（EgressGuard 脱敏 / sentinel），强后端
  不再继承父进程裸环境。真 socket / 真 `Popen` 回归验证子进程看到的是
  sentinel、看不到 `REAL_SECRET_VALUE`。
- **逐命令域名**：若 `claim.strict` 且 `claim.source == "tool_args"`
  （真正逐命令声明，而非全局白名单回落），则**必须**有出网代理能力。
  强后端没有域名级过滤、且 netns / seatbelt 隔离下宿主机回环代理不可达，
  **默认 fail-closed 拒绝**，不假装强绑定生效。

`source` 这个字段是 §13 在 `claim_from_args` 里刻意标注、但当时**没被
消费**的；它在这轮第一次真正决定行为。精确区分的意义：配了全局白名单
（`global_policy`）+ 强后端的既有部署**不被打断**，沿用既有文本层语义；
只有真正逐命令声明才触发新拒绝。

### A′：自己引入、自己抓回（本轮两次）

1. 统一 `to_audit_dict()` 时漏了 ``allowed`` 字段 —— 那是 B2 首轮
   `EgressDecision` 的既有可观测契约，`test_b2_boundaries` 直接 `KeyError`。
   **闸门锁紧了、监控却看不到 `allowed=false`**，比漏字段本身更危险。
   批次 A 回归抓回，已补回并加注释锁住。
2. 改 `_run_provider` 签名后，§13 的
   `test_profile_carries_allowed_domains` 里 FakeProvider 少了 `env` 参数。
   同步到新契约时**把断言改强**（不仅要求带域名元数据，还要求真拿到
   脱敏 env），不是放宽。共 3 条既有断言同步，全部更严。

### 矩阵：一个状态都没动

> **§15 纠偏**：本节「四条路径统一拿 `plan.env`」描述的是执行层内部，
> 但**路由层没接好** —— `tools/shell.py` 仍用 `verdict.enforced` 判断
> 是否采纳结果，plan 的拒绝结果天然 `enforced=False`，会在
> `enforce_required=false` 的部署上回落裸跑；`copy_diff_apply` 分支还会
> 把合规拒绝伪装成用户主动拒绝。下一轮实测发现并修复，见 §15。

本轮是纯深度修复，**不把修好侧门包装成 aligned 增加或 gap 减少**。
`test_b2s_egress_uniform.py::TestMatrixHonesty::test_counts_unchanged`
把 `by_status` 逐项、`gaps=26`、`fully_superior=false`、
`b_waves_done=["B1"]`、红队判据全钉死。
catalog 里 `network_strict_allowlist` / `credential_masking` 的 **note 补了
纠偏说明**（承认上一轮标 aligned 的边界比文档写的窄），但 `status` 与
`evidence` 结构不变，`matrix.validate()` 与 `evidence.verify_evidence()`
均返回空。

### 如实边界

1. **HTTPS CONNECT 隧道内 header 注入仍不可用**（§13 边界不变）：
   需 TLS 中间人 + 本地 CA，会显著扩大攻击面，不做也不谎称完整对等。
   `credential_masking` 仍 `partial`。
2. **bwrap / seatbelt / seccomp 没有域名级过滤**：`SandboxProfile.
   allowed_domains` 仍是元数据，不假装 OS 级后端能按域名放行。
   本轮的立场是「做不到就拒绝」，不是「做到了」。
3. `metadata_only` 是**真实降级**：逐命令声明在强后端只剩文本层判定，
   绕过文本识别即可出网到声明外主机。schema warning + harden status
   待加固项都明示，不藏。
4. `undetectable` 仍是**标记不是证明**；显式 `--noproxy` 可绕过
   `env_overrides`。本地 CLI 固有限制。
5. `os_sandbox` 仍 **gap**、`deny_network_by_default` 出厂仍 **false**
   未翻、`block_writes_outside_wd` 仍 `partial`。本轮没碰这些。
6. **不是真机多平台验证**：Windows Job Object / macOS Seatbelt 路径
   由 fake kernel32 / fake Popen 覆盖；Linux fallback `Popen` 是真实进程。
   `test_platform_portability.py` 长批次在本沙箱多次 502 / 超时，
   只跑到约 51% 且零失败，**如实按「未完整跑完」报告**，不冒充全通过。
7. `test_arch_security.py` 的 1 例失败（策略拒绝 `/usr/bin/python3`）
   上一轮已做 **baseline control**：把改动文件全部还原到 parent blob
   后同样失败，是既有环境行为，没为变绿改策略。
8. A 线 10 个 pending、分叉改动未合并、第三方自适应红队未做。
   标语引擎 / 净化层 / `mapping.py` / `tui.py` 逐字节未改。

### 验证

```
tests/test_b2s_egress_uniform.py + test_b2_egress_strict.py     80 passed
合并批次 A（B2 + boundaries + parity/CLI/headless + sandbox/schema/
            hardening/network/security + arch_platform + proc + risk）341 passed
逐文件：arch_platform 10 / arch_security_fixes 6 / proc 5 /
        risk_sandbox 14 passed；arch_security 1 failed（既有，见上）
matrix.validate() == []  |  evidence.verify_evidence() == []
verify_doc_numbers.py problems == []
fully_superior = false   |  gaps = 26  |  criteria 2 真 3 假
```

新增 `tests/test_b2s_egress_uniform.py`（37 例）：plan 模式矩阵、
`source` 消费验证、四条分支 env 真透传、强后端默认拒绝、显式降级可见、
全局白名单部署不破坏、platform 签名/`env=None` 兼容/真实 `Popen` 看到
sentinel、配置枚举与告警、`last_egress` 每分支必写、矩阵计数钉死。


---

## 15. 深度轮：终态拒绝不回落、内层不吃掉占位符（纠偏 §13/§14）

不扩广度，**矩阵计数一个没动**（`ahead 10 / aligned 46 / partial 9 /
gap 26 / not_applicable 8`，`fully_superior=false`，`b_waves_done=["B1"]`）。
沿 §14 刚统一的 `plan_egress` 链路**往上走一层（路由消费）**、
**往下走一层（provider 内层）**，找到四个断点。

### R1（最值钱）：被拒绝的命令会在真实工作区裸跑一遍

`tools/shell.py::_route_sandbox_isolation` 用

```python
if verdict.enforced or getattr(verdict, "backend_available", False):
    return res.as_shell_text() ...
return None      # ← run_shell 继续 subprocess.Popen 在真实工作区执行
```

判断是否采纳隔离结果。但 **`plan_egress` 的拒绝结果天然 `enforced=False`**
（它根本没执行，何来「隔离生效」）。用 `enforced` 当「是否采纳结果」的
开关是语义错配：`HardIsolationFilter` 在 `enforce_required=false` 且无强
后端时返回 `backend_available=False, enforced=False`，于是路由返回
`None` —— **`run_shell` 把刚被出网合规拒绝的命令在真实工作区裸跑一遍**。

实测三种 verdict 配置，`(enforced=False, backend_available=False)` 确实
回落；另外两种因 `backend_available` / `enforced` 为真而正确返回错误文本。
也就是说：**越是需要 fail-closed 的降级部署，越保不住拒绝裁决**。

### R2：copy_diff_apply 把「合规拒绝」伪装成「用户主动拒绝」

`plan_egress` 在**执行前**就拒绝时，`_execute_copy_diff_apply` 仍走完整
流程：`build_diff_preview → make_confirm_callable → confirm_apply`。
实测 `calls=['isolate','build_diff_preview','make_confirm_callable',
'confirm_apply','cleanup']`，而副本其实是**空的**（根本没执行命令）：

- `error` 变成「denied + 预览文本」，用户看到的是「自己点了拒绝」，看不到
  真正的出网合规拒绝原因；
- 无条件 `verdict.enforced = True` **宣称「已隔离执行」** —— 这行原本是
  为了防止路由回落裸跑（见 §14 注释），却在拒绝路径上变成语义谎言；
- 还弹确认卡片要用户确认写回一个根本没发生的变更。

### R3：内层 `_sanitize_env` 把刚接好的 sentinel 又抹掉了

§14 验证「四条分支都拿到 sentinel」时，测的是**传给 `provider.run` 的
`env` 参数**，不是子进程实际拿到的值。`SandboxProvider._sanitize_env`
→ `sanitize_env` 按**键名**把 `OPENAI_API_KEY` 等置空串，于是
`tuan-egress-sentinel-v1:<fp>` 占位符也在接线内层被抹成 `''`：

```
输入 OPENAI_API_KEY = tuan-egress-sentinel-v1:deadbeef
输出 OPENAI_API_KEY = ''
```

强后端子进程拿不到可还原标记，出网代理 `inject_headers()` 链路静默断裂。
**又是「上层接好了、内层吃掉」**，与前几轮抓的同类缺陷一致。
如实说明：当前默认配置下强后端 + 真正逐命令声明会被 §14 拒绝、不启代理，
所以这个断裂**不产生已观测的实际危害**；修的是接线一致性，防止未来
放宽（例如 `metadata_only` + host 网络代理）时静默失效。

### R4：`TUAN_WORKSPACE` 在三个强后端被抹空

`SECRET_HINTS` 含 `"TUAN_"`，`TUAN_WORKSPACE` 被 `sanitize_env` 置空；
只有 `LocalSandbox` 在之后补回，另外三个强后端此前都没补，子进程拿不到
工作区指示。实测 `sanitize_env({'TUAN_WORKSPACE':'/tmp/w'})` → `''`。

### 落地

| 位置 | 修复 |
|---|---|
| `sandbox/manager.py` | `SandboxExecResult` 新增 `terminal_refusal: bool = False`，把「终态安全拒绝」与「隔离是否生效」**解耦**；`_execute_backend` 在 `not plan.allowed` 时置 True；`_execute_copy_diff_apply` 检测到它立刻返回（不建 diff、不要确认、不设 `verdict.enforced=True`） |
| `tools/shell.py` | `_route_sandbox_isolation` **优先**检查 `res.terminal_refusal` → 无条件返回 `[错误] <拒绝原因>`，绝不回落。正常执行路径逻辑原样不动 |
| `core/security_utils.py` | 新增 `MASKED_PLACEHOLDER_PREFIX` 与 `is_masked_placeholder()`（放共享原语层，避免 `core → sandbox` 反向循环导入）；**不改** `sanitize_env` 全局语义 |
| `core/sandbox_provider.py` | `_sanitize_env` 按**值**原样保留占位符（真实值仍按键名抹空）；四个后端统一以 `workspace` 参数为准补 `TUAN_WORKSPACE`（不信任外部 env 里的假路径） |

两处配合是关键：去掉 `verdict.enforced=True` 之前必须先在路由层堵住回落，
否则「修语义谎言」会直接变成「放开裸跑」。`terminal_refusal` 是这两处
共享的单一契约。

### A′：本轮自己引入、自己抓回

写 `_execute_copy_diff_apply` 的注释时用了带 `\n` 的错误文案示例，
在 Python 三引号字符串里 `\n` 被解释成**真实换行**，写入源码后变成
独立一行 `preview"),`，`py_compile` 直接 `SyntaxError: unterminated
string literal`（manager.py:496）。改成不含反斜杠的文案后恢复。
这是文档注释破坏可编译性，不是运行时缺陷，但如实记为本轮 A′。

### 四个「不该修」（都配了可执行回归）

1. **`last_egress` 并发撕裂未复现**：双线程 × 200 次写，0 次撕裂
   （GIL 兜住）。延续前几轮立场 —— 加锁是消除对 CPython 实现细节的
   依赖，不是修已观测故障，本轮**不加锁**，只锁住「不抛异常、结构完整」，
   不宣称线程安全。
2. **`cmd_safe.py` 不是执行侧门**：`SandboxProvider.create("local")` 只调
   `is_available()` / `.name`，不执行命令。
3. **`orchestration.py` 不是执行侧门**：只把实例挂到 `agent.ctx.
   sandbox_provider`，全仓没有 `.run()` 调用点。新增源码扫描回归：
   除 `manager.py` 外，`SandboxProvider.create` 之后 12 行窗口内不得出现
   `.run(`。**如实标注**：若未来下游工具自己调
   `ctx.sandbox_provider.run()`，就会绕过整套 `plan_egress`，目前没有。
4. **全局 `sanitize_env` 行为不变**：只在 provider 层按值保留占位符，
   不放宽共享脱敏原语，避免影响 `core/sandbox.py` / `arch/security.py` /
   `tools/mcp/sandbox.py` 等其它调用点。

### 矩阵：一个状态没动

> **§16 纠偏**：本节用 `terminal_refusal` 堵住的是「plan 拒绝」这一条
> 分支，但**回落开关本身仍用错字段** —— 路由拿
> `verdict.enforced / backend_available` 判断是否采纳结果。下一轮实测
> 发现降级部署里命令被双重执行，执行异常 / 超时 / 副本创建失败也照样
> 回落裸跑。已改为由结果自身 `decided` 单一契约决定，见 §16。

`test_b2su_refusal_routing.py::TestMatrixHonesty::test_counts_unchanged`
把 `by_status` 逐项、`gaps=26`、`fully_superior=false`、
`b_waves_done=["B1"]`、红队判据全钉死。catalog 里
`network_strict_allowlist` / `credential_masking` 的 note 补了**第三轮
纠偏说明**（§13 说得太满 → §14 纠偏 → §15 再纠偏），`status` 与
`evidence` 结构不变，`matrix.validate()` / `evidence.verify_evidence()`
均返回空。

### 如实边界

1. **HTTPS CONNECT 隧道内 header 注入仍不可用**（§13/§14 边界不变），
   `credential_masking` 仍 `partial`。
2. bwrap / seatbelt / seccomp **没有域名级过滤**，`allowed_domains` 仍是
   元数据；强后端 + 逐命令声明仍默认拒绝，`metadata_only` 仍是真实降级。
3. R3 在当前默认配置下**不产生已观测危害**（强后端被拒绝、不启代理），
   修的是接线一致性，不是已发生的安全事故 —— 不夸大。
4. `last_egress` 仍非线程安全（见「不该修」1）；`undetectable` 仍是标记
   不是证明；显式 `--noproxy` 可绕过 `env_overrides`。
5. `os_sandbox` 仍 **gap**、`deny_network_by_default` 出厂仍 **false**
   未翻、`block_writes_outside_wd` 仍 `partial`，本轮没碰。
6. **不是真机多平台验证**：Windows Job Object / macOS Seatbelt 由 fake
   覆盖；`test_platform_portability.py` 长批次在上一轮已多次 502/超时
   只跑到约 51% 零失败，本轮**未重跑**，如实沿用「未完整跑完」结论。
   `test_arch_security.py` 1 例失败（策略拒绝 `/usr/bin/python3`）
   上一轮 parent-blob baseline control 已证是既有环境行为，本轮复跑仍
   1 failed / 6 passed，**没为变绿改策略**。
7. A 线 10 个 pending、分叉改动未合并、第三方自适应红队未做。
   标语引擎 / 净化层 / `mapping.py` / `tui.py` 逐字节未改。

### 验证（按分批报告，不冒充全量单跑）

```
本轮 + 上两轮（refusal_routing + uniform + egress_strict）   106 passed
shell 路由影响面（run_shell_impact / shell_safety_guard /
    security_gate_hardening）                                 99 passed
parity + 配置 + 安全回归（7 文件）                            170 passed
sandbox/platform/proc 逐文件（7 文件合计）                     91 passed
    test_sandbox 5 / sandbox_gaps 12 / sandbox_system 39 /
    risk_sandbox 14 / arch_platform 10 / arch_security_fixes 6 / proc 5
matrix.validate() == []  |  evidence.verify_evidence() == []
verify_doc_numbers.py problems == []
fully_superior = false   |  gaps = 26  |  criteria 2 真 3 假
```

各批次有重叠文件（如 `test_b2_boundaries`），**不累加成总数**。
新增 `tests/test_b2su_refusal_routing.py`（26 例）：四种 verdict 配置下
终态拒绝不回落、真实 manager 不 patch 的拒绝、EgressGuard 拒绝、
非拒绝路径不变、结果默认值向后兼容、copy_diff_apply 不建 diff/不确认、
错误显示真实原因、占位符常量一致与保全、四个后端工作区指示、
四个「不该修」判定、矩阵计数钉死。


---

## 16. 深度轮：是否回落由结果自身决定（`decided` 单一契约）

不扩广度，**矩阵计数一个没动**（`ahead 10 / aligned 46 / partial 9 /
gap 26 / not_applicable 8`，`fully_superior=false`，`b_waves_done=["B1"]`）。
沿 §15 刚修好的 `terminal_refusal` 继续往下挖，发现它**只堵了一条拒绝
分支**，而「是否回落」的开关本身从一开始就选错了字段。

### G（最值钱）：降级部署里命令被双重执行

`tools/shell.py::_route_sandbox_isolation` 的核心判定是：

```python
if verdict.enforced or getattr(verdict, "backend_available", False):
    return res.as_shell_text() ...
return None      # ← run_shell 继续在真实工作区 subprocess.Popen
```

§15 已经证明「plan 拒绝结果天然 `enforced=False`」会回落裸跑，于是给
拒绝结果加了 `terminal_refusal` 特例。但**根本问题没动**：
`verdict.enforced / backend_available` 是**裁决字段**，描述的是「这次
隔离用没用上强后端」，不是「`execute_isolated` 到底做没做事」。

在 `enforce_required=false` 且无强后端的降级部署里，
`HardIsolationFilter` 返回 `backend=local, backend_available=False,
enforced=False`，然后 `_execute_backend` 的 **local 分支真实执行了命令**。
路由却因两个字段都为假而返回 `None`，`run_shell` 再用
`subprocess.Popen` 在真实工作区跑**第二遍**：

- 实测隔离层执行 1 次 + bare `Popen` 1 次，`run_shell` 返回的是
  `BARE_RAN`（第二次的结果），隔离层的 `ISOLATED_RAN` 被整个丢弃；
- 隔离层的脱敏 env / 出网裁决 / `last_egress` 全部白做；
- 任何有副作用的命令（写文件、发请求、扣费）执行两次。

**「隔离后端不可用」不等于「命令还没跑」** —— 回落 local 分支本身就是
一次执行。用裁决字段当「是否采纳结果」的开关，必然推出这个错。

### 另外五个实测断点

| 编号 | 实测结果 |
|---|---|
| **F1** | `_run_provider` 强后端抛异常 → 捕获后返回 `returncode=-1, enforced=False` → 同样回落裸跑 |
| **F2** | `subprocess.TimeoutExpired` → 同样回落裸跑 |
| **F3** | `copy_diff_apply` 的 `isolate_workdir` 抛异常 → 外层 `except` 返回 **`enforced=True` 宣称「已隔离执行」**（一个副本都没建、命令根本没跑），但路由只看 `verdict.enforced`（仍 False）→ 同样回落裸跑。`res.enforced` 这个字段在路由里根本没被消费 |
| **F4** | `build_diff_preview` 失败时 `error` 直接拼 `str(exc)`，实测 `GITHUB_TOKEN=ghp_REAL_SECRET_VALUE` **原样回显**给用户；OSC 8 超链接与 RLO 也进终端。异常消息可能来自工具参数 / 路径 / 命令文本 |
| **F5** | `copy_diff_apply` 只拦了 `terminal_refusal`；执行层超时 / 崩溃返回 `returncode=-1` 时仍走 `build_diff_preview → confirm_apply`，让用户确认写回一个**根本没成功执行**的副本 |

### 落地：一个字段，一处判定

| 位置 | 修复 |
|---|---|
| `sandbox/manager.py` | `SandboxExecResult` 新增 `decided: bool = True`（**默认 fail-closed**）。只要 `execute_isolated` 真的被调用，任何结果（成功 / 失败 / 拒绝 / 降级 local 执行）都是终态。`execute_isolated` 的 `not verdict.isolate` 分支是**唯一**显式 `decided=False`（「我什么都没做」） |
| `tools/shell.py` | 路由不再看 `verdict.enforced` / `backend_available`，只问 `res.decided`；为假才返回 `None`。`terminal_refusal` 仍优先展示真实拒绝原因 |
| `core/security_utils.py` | 新增 `safe_error_text()`：非 str 只取类型名（不 `str()` 未知对象避免 repr 泄露）→ 剥离 Cc/Cf/bidi/OSC 控制字符 → 复用既有 `redact_sensitive()` 遮蔽密钥 → 限长 400；`limit` 脏值回落默认，净化自身绝不抛异常 |
| `sandbox/manager.py` | 所有 `except` / 超时 / diff 失败分支改用 `safe_error_text(str(exc))` 并显式 `decided=True`；`copy_diff_apply` 对 `res.returncode < 0` 也立刻返回（不建 diff、不弹确认）；外层异常如实 `enforced=False` |
| `tools/shell.py` | 自身 `except` 分支同样净化，且返回终态错误文本而不回落 |

**净化在来源处做，出口不二次净化**：路由的 `f"[错误] {res.error}"`
原样使用，因为 `confirm_apply` 用户主动拒绝时 `res.error` 里含
**diff 预览正文**，用户必须能看见「本来要改什么」。二次净化会破坏它。
新增源码级回归锁住「出口不调 `safe_error_text(res.error)`」。

**用途边界**：`safe_error_text` 只保证异常消息回显到终端时不被解释成
转义序列、不回显密钥，**不做** grapheme 簇或显示宽度判定，因此不与
标语轮那套 UI 净化层构成第三套宽度真值。

### A′：本轮自己引入、自己抓回

新写的 `test_no_second_sanitization_at_route_exit` 初版断言
`window.count("safe_error_text") == 1`，实测是 **2** —— 同一个 `except`
分支里既有 `from ... import safe_error_text` 又有一次调用，两处都在
自身异常分支内，不是出口二次净化。断言改成「次数为 2 + 出口原样使用
`res.error` + 不出现 `safe_error_text(res.error`」，语义更准。
这是测试断言写错，不是代码缺陷，如实记为 A′。

### 三个「不该修」（都配可执行回归）

1. **未终止 OSC 的参数残留**：`ESC ]8;;https://evil BEL END` 净化后
   剩 `]8;;https://evilEND`。ESC / BEL / RLO 已剥离，终端不会再解释；
   残留只是可读性略差。彻底删参数会误伤合法文本，且错误文本不参与
   UI 布局，与 §15 那条「未终止 OSC 吞光整行」的 UI 判定不冲突。
2. **全局 `redact_sensitive` 行为不变**：控制字符剥离是
   `safe_error_text` 的职责，不放进共享脱敏原语，避免影响审计日志 /
   MCP 审计 / 导出链路等其它调用点。
3. **`cmd_safe.py` / `orchestration.py` 仍不是执行侧门**：沿用 §15 的
   源码扫描回归，本轮未改。

### 矩阵：一个状态没动

`test_b2su_decided_routing.py::TestMatrixHonesty::test_counts_unchanged`
把 `by_status` 逐项、`gaps=26`、`fully_superior=false`、
`b_waves_done=["B1"]`、红队判据全钉死。catalog 两条 note 补了**第四轮
纠偏指向**（§13 太满 → §14 → §15 → §16），`status` 与 `evidence`
结构不变，`matrix.validate()` / `evidence.verify_evidence()` 均空。

### 如实边界

1. **HTTPS CONNECT 隧道内 header 注入仍不可用**（§13/§14/§15 边界
   不变），`credential_masking` 仍 `partial`。
2. bwrap / seatbelt / seccomp **没有域名级过滤**，`allowed_domains` 仍是
   元数据；强后端 + 逐命令声明仍默认拒绝，`metadata_only` 仍是真实降级。
3. `decided` 默认 True 是**行为变更**：任何直接构造
   `SandboxExecResult` 并交给路由的调用方，结果都会被采纳而不是回落。
   这正是修复目标，但依赖旧回落语义的第三方集成需核对。
4. `safe_error_text` 只处理**执行层异常消息**；`confirm_apply` 的 diff
   预览正文仍原样回显（用户要看），若预览内容本身含密钥，那属于
   工作区文件内容、不在本轮范围。
5. `last_egress` 仍非线程安全；`undetectable` 是标记不是证明；显式
   `--noproxy` 可绕过 `env_overrides`。
6. `os_sandbox` 仍 **gap**、`deny_network_by_default` 出厂仍 **false**
   未翻、`block_writes_outside_wd` 仍 `partial`，本轮没碰。
7. **不是真机多平台验证**：Windows Job Object / macOS Seatbelt 由 fake
   覆盖；`test_platform_portability.py` 长批次在 §14 轮已多次 502/超时
   只跑到约 51% 零失败，本轮**未重跑**，如实沿用「未完整跑完」结论。
   `test_arch_security.py` 1 例失败（策略拒绝 `/usr/bin/python3`）
   已由 parent-blob baseline control 证明是既有环境行为，没为变绿改策略。
8. A 线 10 个 pending、分叉改动未合并、第三方自适应红队未做。
   标语引擎 / 净化层 / `mapping.py` / `tui.py` 逐字节未改。

### 验证（按分批报告，不冒充全量单跑）

```
本轮 + 上三轮（decided + refusal_routing + uniform + strict）
    + boundaries + claude_parity                          227 passed
shell 路由影响面（run_shell_impact / shell_safety_guard /
    security_gate_hardening）                             99 passed
parity + 配置 + 安全回归（7 文件）                        170 passed
sandbox/platform/proc/e1e7 逐文件（8 文件合计）            130 passed
    test_sandbox 5 / sandbox_gaps 12 / sandbox_system 39 /
    risk_sandbox 14 / arch_platform 10 / arch_security_fixes 6 /
    proc 5 / e1_e7_hardening 39
matrix.validate() == []  |  evidence.verify_evidence() == []
verify_doc_numbers.py problems == []
fully_superior = false   |  gaps = 26  |  criteria 2 真 3 假
```

各批次有重叠文件（如 `test_claude_parity` / `test_b2_boundaries`），
**不累加成总数**。新增 `tests/test_b2su_decided_routing.py`（约 30 例）：
`decided` 契约与唯一合法回落、四种裁决标志组合都采纳结果、端到端
`run_shell` 不 bare Popen、强后端崩溃 / 超时 / 副本创建失败 / 路由自身
异常都不回落且不回显密钥、副本创建失败不宣称 enforced、执行失败不弹
确认、用户主动拒绝仍显示完整 diff、`safe_error_text` 脱敏/控制字符/
非 str/脏 limit/绝不抛异常、三个「不该修」判定、矩阵计数钉死。


---

## 深度轮（续）：两条执行侧门收口 —— 后台 `! cmd` 与对外 MCP `run_shell`

> **关于章节编号的如实纠偏**：本仓库存在多套编号体系 ——
> `CLAUDE_PARITY.md` 的 §17 是标语线的「自愈/证据保全声明」，`SECURITY.md`
> 的 §17 是「运行时闭环」，`SECURITY_EN.md` 的 §17 是
> 「Owner Normalization」，`SLOGAN_MAPPING.md` 又有一套 §17。上一轮
> 后台分支的代码注释曾写「本轮 §17」，实际指向并不存在。本轮**不再沿用
> 数字编号**，改用自足标题；代码注释也改成自足描述。不做全局重编号，
> 因为那会改动大量既有交叉引用、把口径问题变成新问题。

**两轮合并推送**（此前因沙箱 502 中断未推）：矩阵计数**一个没动**
（`ahead 10 / aligned 46 / partial 9 / gap 26 / not_applicable 8`，
`fully_superior=false`，`b_waves_done=["B1"]`），纯深度修复。

### 第一条：`! cmd` 后台分支绕过整套闸门

`run_shell` 开头 `if is_bg_command(command): return _start_background(...)`
位于 `_pre_exec_guard` **和** `_route_sandbox_isolation` 之前。实测带
`isolate=True` 裁决的 `! curl https://evil.example`：隔离层调用 **0 次**、
bare `Popen` **1 次**，返回「后台已启动」。整条 plan_egress / 沙箱后端 /
出网合规裁决 / 凭据脱敏链路被绕过。这正是前两轮刚收口的 `decided`
契约**覆盖不到**的地方 —— `decided` 只管主链路路由的返回值。

更糟的是 `BackgroundShellManager.start` 的 `subprocess.Popen`
**完全不传 env**，后台子进程继承父进程完整环境。实测
`os.environ['GITHUB_TOKEN']='ghp_...'` 时子进程拿到真实值；而后台分支
本来就拿不到 plan_egress 的 sentinel 代理注入，等于真实密钥直接进一个
不受任何出网管控的异步进程。

### 第二条：对外 MCP `run_shell` 是另一处裸执行入口

`ecosystem/mcp_server.py::_h_run_shell` 是**全仓唯一一处**「外部 Agent
直接提供 `command`、用 `shell=True` 执行」的入口（默认
`allow_dangerous_tools=false` 不暴露，显式开启后才可见），却完全没接闸门：

| 编号 | 实测结果 |
|---|---|
| M1 | 只做 `is_hard_redline` / `is_redline` **文本判定**，不经过 `SandboxManager.assess_command` / `plan_egress`。深度轮 fuzz 已证明零宽字符 / ANSI-C / 注释换行能绕过文本层 |
| M2 | `subprocess.run` **不传 env**，实测 `GITHUB_TOKEN=ghp_REAL_SECRET_VALUE` 原样进入子进程，与 §13/§15 刚落地的「子进程不持密钥」直接矛盾 |
| M3 | 异常分支把 `str(exc)` 原样回显给外部 Agent：真实密钥串、OSC / RLO 控制字符都会外泄（执行失败 + 安全判定失败两处） |

### 一个横跨两轮的真缺陷：`str(exc)` 在调用方先执行

上一轮把所有错误路径写成
`f"{type(exc).__name__}: {safe_error_text(str(exc))}"`，但净化**管不到**
`str(exc)` 本身。实测异常对象 `__str__` 抛 RuntimeError 时，整个 `except`
分支被掀翻 —— 安全错误路径反而变成未捕获异常。`shell.py` 另有 5 处、
`background_shell.py` 1 处、MCP 3 处裸 `{exc}` 回显，实测
`GITHUB_TOKEN=ghp_REAL_SECRET_VALUE` 与 OSC 8 / RLO 原样进终端。

### 落地（如实，不夸大）

| 位置 | 修复 |
|---|---|
| `core/security_utils.py` | 新增 `safe_exception_text(exc)`：把 `str(exc)` 包进 try，异常时丢弃原文只留类型名；正常时复用 `safe_error_text`。**全部 12 处**错误出口统一走它 |
| `tools/shell.py` `_start_background` | 裁决 `isolate=True` → **fail-closed 拒绝**（异步路径套不上同步隔离执行器 / copy-diff-apply 确认，绝不假装隔离生效）；其余后台命令显式传 `sanitize_env()` 脱敏环境并补 `TUAN_WORKSPACE` |
| `core/background_shell.py` | `start` / `run_in_background` 增加 `env` 形参（`None` 保持既有继承语义向后兼容），`Popen` 透传；后台线程异常终态改走 `safe_exception_text` |
| `ecosystem/mcp_server.py` | 接 `SandboxManager.assess_command`：DENY / CONFIRM / `isolate=True` 一律 fail-closed 拒绝；接 `plan_egress(verdict, "local", ...)`：`allowed=False` 拒绝，`plan.env` 脱敏值显式传给 `subprocess.run`；所有异常出口净化；工具描述如实标注「**没有 OS 级隔离 / 逐命令域名强绑定 / 副本确认**」 |
| `sandbox/manager.py` | 5 处 `safe_error_text(str(exc))` → `safe_exception_text(exc)` |

**backend 固定 `local`**：MCP 本来就是同步裸 subprocess，绝不拿 verdict
里的强后端名字假装已隔离。默认 `allow_dangerous_tools=false` 行为不变。

### 三个「不该修」（都配可执行回归）

1. `ignored` 是死字段（全仓零构造点），与 `decided` 默认 True **不冲突**；
   保留做向后兼容，源码扫描锁住结论。
2. `verdict.enforced` 现在全仓无消费点（只是 copy_diff_apply 成功后的
   审计状态）；**不删**，删除会改变 verdict 对象状态，可能有外部集成读取。
3. `artifact_tool.py` / `code.py` 的 Popen 打开编辑器/文件，不执行用户
   提供的 shell 命令、不受 shell 裁决管辖；如实记录、本轮不动。
   若未来改成执行任意命令，需重新评估。

### A′ ×2（自己引入、自己抓回）

- manager.py 批量替换 `safe_error_text(str(exc))` → `safe_exception_text(exc)`
  时**破坏了两处多行 f-string 拼接**，`py_compile` 直接 SyntaxError；已改为
  字符串 `+` 拼接并复跑语法检查。
- 上一轮 `test_no_second_sanitization_at_route_exit` 用固定 2600 字符
  窗口切片，注释改成自足描述后 docstring 变长把 except 分支挤出窗口；
  且实际代码用的是 `safe_exception_text` 而非 `safe_error_text`。断言改用
  `inspect.getsource` 取完整函数体并按真实代码形态锁定。**测试断言脆弱性，
  不是代码回归**。

### 验证（按分批报告，批次间有重叠、不累加）

```
本轮 + 并行线 + 上四轮（mcp_gate / background_side_door /
    decided / refusal / uniform / strict / boundaries / claude_parity）
                                                       276 passed
shell / 后台影响面（run_shell_impact / shell_safety_guard /
    background_shell）                                  82 passed
parity + 配置 + 安全回归（5 文件）                      78 passed
sandbox/platform/proc/e1e7 逐文件（沿用 §16 分批结果）  130 passed
matrix.validate() == []  |  evidence.verify_evidence() == []
verify_doc_numbers.py problems == []
```

新增 `tests/test_b2se_background_side_door.py`（约 24 例）与
`tests/test_b2su_mcp_shell_gate.py`（约 25 例）：后台 fail-closed 与
脱敏 env、`env=None` 向后兼容、损坏 `__str__` 不掀翻错误路径、全部异常
出口不泄露密钥、MCP 的 DENY/CONFIRM/isolate/禁网四类拒绝零执行、
sentinel 真实进入子进程且真实值不残留、工具默认不暴露 + 描述如实、
三个「不该修」判定、矩阵计数钉死。

### 如实边界

1. **MCP 通道仍没有 OS 级隔离 / 逐命令域名强绑定 / 副本确认**：本轮做的是
   fail-closed 拒绝 + 脱敏 env，**不是**把这些能力补上。`credential_masking`
   仍 `partial`（HTTPS CONNECT 隧道内 header 不可见）。
2. **后台/MCP 都是行为变更**：需隔离的后台命令从「静默裸跑」变「明确
   拒绝」；MCP `run_shell` 从「只看文本红线」变「走四层滤网裁决」。
   依赖旧行为的集成需核对。
3. `ctx` 没有 `_sandbox_verdict` 时后台分支不拦 —— 这是**裁决链上游**
   的边界，本轮不伪造裁决、也不用文本层猜命令是否高危（那会重新引入
   「看字符串」的绕过面），回归锁住当前事实。
4. `safe_exception_text` 只覆盖异常消息；`confirm_apply` 的 diff 预览
   正文仍原样回显（用户要看），若预览含密钥属工作区文件内容。
5. `os_sandbox` 仍 **gap**、`deny_network_by_default` 出厂仍 **false**
   未翻、`block_writes_outside_wd` 仍 `partial`，本轮没碰。
6. **不是真机多平台验证**；长批次在本沙箱多次 502/超时，按分批如实
   报告，不冒充全量单跑。`test_arch_security.py` 1 例失败已由
   parent-blob baseline control 证明是既有环境行为，没为变绿改策略。
7. A 线 10 个 pending、分叉改动未合并、第三方自适应红队未做。
   标语引擎 / 净化层 / `mapping.py` / `tui.py` 逐字节未改。


---

## 深度轮（续二）：工具层写路径硬边界、`/add-dir` 口径纠偏、`edit_files` 真事务

> 沿用上一轮的**自足标题**约定，不新增数字章节编号（仓库里存在多套
> §17 且指代四个不同主题）。矩阵计数**一个没动**：
> `ahead 10 / aligned 46 / partial 9 / gap 26 / not_applicable 8`，
> `fully_superior=false`，`b_waves_done=["B1"]`。

### 三个实测缺陷（先复现再修）

| 编号 | 实测结果 |
|---|---|
| W1 | `permissions.blockWritesOutsideWorkingDirectories` 在**代码里 0 命中**（只在 `catalog.py` 的对标描述中出现）。`tools/filesystem.py::_resolve` 是读路径裁决且读写不分；CC v2.1.314 是在 **Write/Edit/NotebookEdit 工具层**硬拒绝越界写 |
| W2 | `/add-dir` 的 REPL 帮助、`authorize_extra_dir` docstring、模块注释**三处**都写「可读上下文 / 仅读; 写仍走既有守卫」。实测 `/add-dir /tmp/ext` 之后 `write_file` 真的创建文件、`move_file` 改名、`delete_file` 删除，全部越界放行 —— **确认对话不是路径硬边界**，YOLO / 无人值守 / 直接函数调用都不经过它 |
| W3 | `edit_files` docstring 声称「任一失败 → 整体拒绝, 不写任何文件」，但危险内容扫描在**阶段 2 边写边扫**。实测 3 项里第 3 项含 `rm -rf /`：返回「已整体拒绝 (未写入任何文件)」，而 `f0.txt` / `f1.txt` 已变成 `BBB`。返回文本与磁盘状态不一致 |

W3 是这个仓库里少见的**正确性缺陷**（前十几轮多是安全 fail-open），
而且返回文本主动说谎，会误导上层 Agent 以为可以安全重试。

### 落地（如实，不夸大）

| 位置 | 修复 |
|---|---|
| `core/write_boundary.py`（新增） | `recheck_write` / `decide_write` / `boundary_enabled` / `writable_roots` 单一裁决出口。开关默认 **`False`**（与 CC 出厂一致，**不做破坏性默认变更**）；配置值非 bool → **fail-closed 启用**，避免 `bool("false") == True` 的静默放行；开启后写目标必须在 `工作区 ∪ 显式 writable 授权根` 内；写入点重新解析父目录链，抓 symlink 替换型 TOCTOU |
| `tools/filesystem.py` | 新增 `_resolve_write`，`write_file` / `edit_file` / `edit_files` / `move_file(dst)` / `delete_file` / `delete_dir` **六处**统一改走它；`move_file` 的源仍走 `_resolve`（读裁决）；写入点再复检一次 |
| `tools/filesystem.py` `authorize_extra_dir` | 新增 `writable=False` 形参。普通 `/add-dir` 只授读；`--writable` 显式登记 `extra_writable_dirs`（per-session 内存态，Agent 无自助授权工具）；系统关键目录仍拒绝 |
| `tools/filesystem.py` `edit_files` | 危险内容扫描**前移到阶段 1**；写入前对**全体**目标做一次复检（必须在任何落盘之前，否则中途拒绝仍会部分写入）；阶段 2 循环内不再有任何拒绝分支 |
| `config/defaults.py` | 新增 `permissions.blockWritesOutsideWorkingDirectories: False` |
| `config/security_schema.py` | 强校验（非 bool 直接报错，不让运行时按 fail-closed 悄悄改写行为）；开启时报「行为变更」warning |
| `cli/cmd_harden.py` | `harden status` 显示写边界**当前生效状态**；`_CfgProbe` 复用同一份 fail-closed 判定，配错值也会在 status 里显示 |
| `cli/cmd_slash.py` | `/add-dir` 帮助文案改成如实；支持 `/add-dir <path> --writable`；无参列表区分「可写 / 仅读或默认可写」 |
| `parity_claude/catalog.py` | `block_writes_outside_wd` 的 note 补纠偏，**`status` 仍 `partial`**、`evidence` 结构不变 |

### 为什么状态仍是 `partial`，不标 `aligned`

1. **命令层重定向不在工具层约束内**：`echo x > /tmp/out` 由 shell 执行，
   本模块管不到；CC 靠 sandbox 规则覆盖命令层，Tuan 尚无对应能力。
2. **出厂默认仍 `false`**（与 CC 一致，但两者都还不是默认强边界）。
3. **TOCTOU 只做二次解析**：检查与 `os.replace` 之间仍有窗口；
   彻底消除要上 `O_NOFOLLOW` + `dir_fd` 系列，会改动既有原子写实现，
   本轮不做也不谎称覆盖。

### 三个「不该修」（都配可执行回归）

- **读路径不受影响**：`read_file` / `list_dir` / `glob` / `diff_preview`
  对 `/add-dir` 目录照常可读（这是该功能本来的承诺）。
- **`artifact_tool.py` / `worktree_layer.py` 不走 `_resolve`**：它们写的是
  `workspace/.tuan/artifacts` 与 `workspace/.tuan/worktrees` 固定内部路径，
  不是用户提供的任意路径。源码扫描锁住结论；若未来改成写任意路径需重评。
- **`move_file` 的源是读、目标是写**：源继续用 `_resolve`，只给目标加边界；
  把源也当成写会误拒「从授权只读目录搬进工作区」的合理操作。

### A′：一处接口写错、当场自查抓回

`harden status` 初版给 `_CfgProbe` 写了 `get()`，但 `write_boundary` 读的是
`ctx.config()`；且初版调用了需要 `ctx.workspace` 的 `allowed_roots()`。
自查后改成 `config()` 并去掉 workspace 依赖，避免 status 直接抛异常。
另有一处测试里的死代码（未调用的 `_swap_then_resolve`）已清理。

### 验证（按分批报告，批次间有重叠、不累加）

```
本轮新回归 tests/test_b2su_write_boundary.py                38 passed
路径/编辑/读守卫/工作区影响面（6 文件）            119 passed / 1 skipped
config / harden / slash / parity（7 文件）                  114 passed
matrix.validate() == []  |  evidence.verify_evidence() == []
verify_doc_numbers.py problems == []
py_compile: 8 个改动 Python 文件 OK
```

端到端实测（非仅单测）：开关关闭时既有 `/add-dir` 写行为不变；开启后同一
授权目录的 write / edit / move / delete / delete_dir 五类全部返回
「写路径越出工作目录」且磁盘零变更，读仍可读；`--writable` 显式授权后写
放行；W3 场景三个文件全部保持 `AAA`。

### 如实边界

- **默认不改既有行为**：`blockWritesOutsideWorkingDirectories=false` 时
  `/add-dir` 目录仍可写，文档已改成如实（旧文案是错的）。开启才是**行为
  变更**，依赖「/add-dir 可写」的部署需显式 `--writable` 授权或保持关闭。
- **W3 修复是行为变更**：`edit_files` 现在危险内容命中时一个文件都不写
  （旧版会写前 N 个）。上层若依赖「部分成功」需核对；但旧返回文本本就
  声称「未写入任何文件」，所以修复是让实现对齐承诺。
- **状态 2 写路径复检不是完整 TOCTOU 防护**；`edit_files` 阶段 2 的
  `_atomic_write_text` 若因 OS 错误（磁盘满 / 权限）中途失败，仍可能部分
  落盘 —— 这不是本轮引入，也不谎称「完全事务」。
- `os_sandbox` 仍 **gap**、`deny_network_by_default` 仍 **false** 未翻、
  `credential_masking` 仍 `partial`（HTTPS CONNECT 隧道内 header 不可见）；
  A 线 10 个 pending、分叉改动未合并、第三方自适应红队未做。
- 不是真机多平台验证；Windows 路径未实测。标语引擎 / 净化层 /
  `mapping.py` / `tui.py` / `runtime_slogans.py` 逐字节未改。


---

## 深度轮（续三）：Hooks 扩展事件引擎 + CC 原生协议 + `updatedInput` schema 校验

> 沿用**自足标题**约定，不新增数字章节编号（本仓库多套 §17 指代四个
> 不同主题）。矩阵计数**一个没动**：
> `ahead 10 / aligned 46 / partial 9 / gap 26 / not_applicable 8`，
> `fully_superior=false`，`b_waves_done=["B1"]`。
>
> 这轮是 **B3 的引擎/协议层深度修复**，不是功能广度补齐。两个 B3
> 条目仍标 `STATUS_GAP`，理由见下文「为什么不消 gap」。

### 四个实测缺陷（先复现再修）

| 编号 | 实测结果 |
|---|---|
| R1 | 旧 `HookManager.__init__` 只遍历 8 个 `HOOK_EVENTS`。配置里写 `DirectoryAdded` 或把 `PermissionRequest` 拼错成 `PermissionReqest`，整段被**静默丢弃**且零报错 —— 与之前修过的「规则表静默失效」同类 |
| R2 | `run_notify` 只认 5 个通知事件。若把 7 个扩展事件统统塞进 `_NOTIFY_EVENTS`，PermissionRequest / Elicitation / ElicitationResult 这类**决策类**事件的 stdout 会被静默吞掉：用户以为装了拦截器，实际什么都不做 |
| R3 | `_parse_decision` 只认 `args` / `block` / `decision`。按 Claude Code 官方文档写的 `{"hookSpecificOutput":{"permissionDecision":"deny","updatedInput":{...}}}` 被判 `None` 后 `continue` —— 既不阻断也不改参。**协议不兼容却宣称对齐** |
| R4 | 最严重：hook 返回 `{"args":{"path":"ok","TOTALLY_UNKNOWN":"pwn"}}` 时旧版原样采纳，`tools/base.py` 执行 `tool.handler(ctx, **args)` 直接抛 `TypeError`（未知关键字 + 缺必需参数）。实测 `f0/f1` 式的返回文本与磁盘状态不一致在本轮之前已修过一次，这里是**同类病换到 hook 改参路径** |

官方口径核对：Claude Code v2.1.300 起 `updatedInput` 是**替换**整个
`tool_input`（不是 merge）、未知键被丢弃、缺必需参数或类型不符的改参
**拒绝该次调用**；`hookSpecificOutput` 是 PreToolUse / ElicitationResult
等事件的原生输出容器。

### 落地（如实，不夸大）

| 位置 | 修复 |
|---|---|
| `hooks/manager.py` | 事件表 8 → 15（`CORE_HOOK_EVENTS` 8 + `EXTENDED_HOOK_EVENTS` 7）；未知事件键显式 `unknown_hook_event` 审计；`_DECISION_EVENTS` 4 个独立 `run_decision()` 裁决出口（复用 B1 的 fail-closed），误走 `run_notify` 留痕拒绝；`_parse_decision` 同时支持 CC 原生 `hookSpecificOutput` 与本地旧格式，`ask` 在无确认通道时 fail-closed；CC advisory `additionalContext` 无本地注入通道 → 留痕不假装 |
| `hooks/input_validation.py`（新增） | `validate_updated_input()` 单一裁决出口。有 schema：按 `properties` 白名单丢未知键、校验 `required` / `type` / `enum`，不符 → `deny=True`（`run_pre` 转成 `block=True` + `invalid_updated_input`）；无 schema：退化为**保守子集约束**（不得引入原 args 没有的新键，挡住 TypeError 注入面），`enforced=False` 绝不包装成「已通过校验」 |
| `tools/base.py` | `_apply_pre_hooks` 传 `tool_schema=tool.parameters`；危险工具审批前派发 `PermissionRequest`，**只允许收紧、不允许 hook 代答跳过确认**（CC 的程序化代答在 Tuan 会绕过安全闸门，刻意不等价） |
| `cli/cmd_slash.py` | `/add-dir` 授权**成功**后派发 `DirectoryAdded`（失败信息不触发，否则外部 hook 误以为目录已纳入上下文）；`--writable` 标志透传 |
| `arch/execution.py` | `ToolCall` 加可选 `tool_schema` 字段并传给 `run_pre`；既有调用方不填时仍走保守子集，如实标注 |
| `hooks/__init__.py` | 导出 `HookFailure` / `CORE_HOOK_EVENTS` / `EXTENDED_HOOK_EVENTS` |

### 为什么不消 gap（两个 B3 条目仍 `STATUS_GAP`）

1. **`hook_events_extended`**：`ConfigChange` / `WorktreeCreate` /
   `Elicitation` / `ElicitationResult` **4 个事件没有本地生产触发点**，
   `Notification` 同样未接 —— 配置了也不会触发，等于没有该能力。
   官方最新 hooks 参考列出的事件远多于这 7 个（PermissionDenied /
   PostToolBatch / TaskCompleted / FileChanged ...），本轮只补 catalog
   已登记的 7 个，不假装全事件对齐。CC 的 exit-code-2 → decline 语义
   未实现。
2. **`hook_updated_input_validation`**：主链路 `tools/base.py` 已严格
   校验，但 `arch/execution.py` 的 `ToolPipeline` 既有调用方不填
   `tool_schema`、`cmd_hooks.py` 手动测试入口同样无 schema，两条旁路
   走保守子集。CC 覆盖所有工具调用路径，Tuan 只覆盖主链路。

**两个 note 都补了纠偏说明，但 `status` / `evidence` 结构不变** ——
不靠改口径凑数。下一轮的真实进度是接 5 个生产触发点 + 给旁路补
schema，那时消 gap 才成立。

### 三处既有断言同步到新契约（**不是放宽**）

- `test_hooks_events.py::test_hook_events_surface`：从「8 事件」同步到
  「8 核心 + 7 扩展 = 15」，**新增**对 `EXTENDED_HOOK_EVENTS` 的逐项
  枚举与并集校验 —— 事件表仍被完整钉死，多一个少一个都失败。
- `test_hooks.py::test_args_rewrite_allowed` 与
  `test_hooks_http.py::test_http_hook_pre_modify_args`：旧断言要求
  hook 能注入 `_hook_injected` 新键。这正是 R4 的注入面。改成
  「既有键改写仍生效 **且** 新键被丢弃」，断言更强、语义更准。

### A′：一个残留装饰器、当场自查抓回

`_parse_decision` 从 `@staticmethod` 改成实例方法时，替换串没包含上方
的 `@staticmethod` 行，导致 `self` 变成显式形参，12 条既有 hooks 测试
全部 `TypeError: missing 1 required positional argument: 'stdout'`。
自查后删掉装饰器，复跑 83 例全绿。这是**替换脆弱性**，不是代码回归。

### 验证（按分批报告，批次间有重叠、不累加）

```
B3 新回归 + 5 个 hooks 既有文件                        83 passed
parity / 写边界 / 两条侧门 / B2 各轮 / config / slash  356 passed
matrix.validate() == []  |  evidence.verify_evidence() == []
verify_doc_numbers.py problems == []
py_compile: 改动 Python 文件全部 OK
```

`tests/test_b3_hooks_extended.py` 覆盖：15 事件表、未知事件审计、决策类
误路由留痕、CC 原生 deny/ask/allow、matcher、决策类不改参、B1 fail-closed
在决策事件同样生效、未知键丢弃、缺 required / 类型 / enum 拒绝、
无 schema 的 `enforced=False`、修复前 `handler(**raw)` 确实抛 TypeError
而 sanitized 不抛、`/add-dir` 成功才派发、`PermissionRequest` 的 allow
**不能**跳过人工确认、5 个事件无生产触发点的源码扫描、矩阵计数钉死。

### 如实边界

- **5 个扩展事件只有引擎，没有生产触发点**；CC 的 exit-code-2 → decline
  未实现；官方事件面比 catalog 的 7 个大得多。
- **无 schema 的旁路只是保守子集**，不是 schema 校验；审计里
  `enforced=False` 明示。`arch/execution.py` 的 `ToolCall.tool_schema`
  是可选字段，既有调用方不填。
- **`PermissionRequest` 刻意不等价 CC**：Tuan 的 `ctx.confirm` 是安全
  闸门，hook 的 `allow` 只留痕、不跳过确认（CC 可程序化代答）。这是
  「比 CC 更严格」，不是「已对齐」。
- **行为变更**：hook 改参不再能注入原 args 没有的新键（此前会
  `TypeError`）；旧格式 `{"args": {...}}` 同样走校验，不留侧门。
  依赖「hook 注入标记字段」的集成需改用具名 schema 字段。
- `os_sandbox` 仍 gap、`deny_network_by_default` 仍 false 未翻、
  `credential_masking` 仍 partial；A 线 10 pending、分叉改动未合并、
  第三方自适应红队未做；不是真机多平台验证。
- 标语引擎 / 净化层 / `mapping.py` / `tui.py` / `runtime_slogans.py`
  逐字节未改。


---

## 深度轮（续四）：5 个扩展事件的**生产触发点** + 旁路契约

> 沿用**自足标题**约定，不新增数字章节编号。**矩阵计数一个没动**：
> `ahead 10 / aligned 46 / partial 9 / gap 26 / not_applicable 8`，
> `fully_superior=false`，`b_waves_done=["B1"]`。
>
> 这轮是上一轮「引擎层已就绪但仍是 gap」的**直接续作**：把「配置了
> 也不触发」这个最刺眼的断点接上，不扩广度。两个 B3 条目仍
> `STATUS_GAP`，理由见下文「为什么还不消 gap」。

### 四个实测缺陷（先复现再修）

| 编号 | 实测结果 |
|---|---|
| R1 | 上一轮 5 个扩展事件**全部注册成功**（`len(m._specs)==5`），但跑真实操作 `Config.set_user` / `WorktreeLayer.create` / `_ask_user_handler` / `remote_control.notify` 之后 hook 实际触发 **0 次**；全仓源码扫描 `run_notify("ConfigChange"...` 等 5 个派发点 **0 命中**。配置能加载、引擎能裁决，但没有任何生产代码调用它们 —— 用户以为装了拦截器，实际什么都不发生 |
| R2 | `tuan hooks test --event PermissionRequest` 走 `run_session` → `run_notify`，被上一轮的 `decision_event_misrouted` 拒绝且**静默不执行**（实测 audit 里只有一条 misrouted）；4 个决策类扩展事件的 CLI 测试入口全部失效 |
| R3 | `cmd_hooks.py` 的 `run_pre(tool, payload, dangerous=True)` 不传 schema，手动测试入口的改参只走保守子集 |
| R4 | 上一轮给 `arch/execution.py::ToolCall` 加了 `tool_schema`，但全仓扫描确认 **`ToolPipeline` 没有生产构造方**（只有测试构造），所以那条「旁路补齐」其实没扩大覆盖面；而且强行传 `tool_schema=` 让老式 hook mock 的 `run_pre(name, args)` 抛 `TypeError`，实测 1 条既有回归失败 |

### 落地（如实，不夸大）

| 位置 | 修复 |
|---|---|
| `hooks/triggers.py`（新增） | 5 个事件收敛成单一 `HookTrigger` 出口：通知类走 `run_notify`、决策类走 `run_decision`（上一轮 R2 的坑）；**无 hooks 严格 no-op**、通知异常一律吞、用户显式配了 hook 但裁决通道炸了 → **fail-closed**；`set_default_hooks_provider()` 注入的是**只读取值函数**，不是把 HookManager 复制进各模块（这些模块构造早于 hooks） |
| `config/loader.py` / `config/managed.py` | `Config.set_user` / `delete_user` 写成功后、`ManagedSettings.reload()` 重载成功后 → `ConfigChange`（失败不派发，否则 hook 误以为配置已生效） |
| `core/worktree_layer.py` | `create()` / `create_agent_worktree()` 在**任何文件系统改动之前** → `WorktreeCreate` 决策类事件，block 即抛 `WorktreeError` 拒绝创建。刻意放在 fast-resume 复用分支之前（复用同样值得让策略拒绝），比 CC 语义更严，如实标注 |
| `tools/session_tools.py` / `runtime/acp/bridge.py` | `_ask_user_handler`（TUI+CLI 统一入口）与 ACP `ask_user`（真正的 `elicitation/create` 反向 RPC 宿主）→ `Elicitation` / `ElicitationResult`。**block 分别是「取消提问」「作废回答」，绝不代答、绝不把 hook 输出当新答案** —— CC 允许程序化代答，Tuan 刻意不等价（模型不能自问自答）。headless / 全屏降级路径没有真实用户响应，**不派发** `ElicitationResult` |
| `core/remote_control.py` / `core/security_alert.py` | `notify()` 所有返回路径之前、`_notify_safely()` 后台线程里 → `Notification`。放后台线程是因为 hook 是子进程，同步调用会阻塞 `_pre_exec_guard` 主路径 |
| `cli/cmd_slash_boundary.py` / `cli/cmd_worktree.py` / `app.py` | `/worktree` 显式传 `agent.ctx.hooks`；CLI 独立入口靠 default provider；`app.py` 启动时注入 `lambda: agent.ctx.hooks`（传函数而非对象，hooks 可被会话内置空） |
| `cli/cmd_hooks.py` | 决策类 4 事件改走 `run_decision`（修 R2）；`run_pre` 从工具注册表取 schema 并传入，取不到时**如实打印**「无 schema → 保守子集 enforced=False」（修 R3）；`hooks list` 提示从 4 个事件改为 15 个 |
| `arch/execution.py` | `ToolPipeline` 加 `schema_resolver`，且**只在有 schema 时**传 `tool_schema` 关键字（兼容老式 mock，修 R4）；如实标注无生产构造方 |

### 为什么还不消 gap（两个 B3 条目仍 `STATUS_GAP`）

**硬理由缩小了，但没消失**：

1. **`hook_events_extended`**：7 个事件现在都有生产触发点，但官方最新
   hooks 参考列出的事件远多于 7 个（PermissionDenied / PostToolBatch /
   PostToolUseFailure / TaskCompleted / TaskCreated / FileChanged /
   CwdChanged / InstructionsLoaded / WorktreeRemove ...）；CC 的
   exit-code-2 → decline 语义未实现；`Elicitation` 语义刻意不等价。
2. **`hook_updated_input_validation`**：主链路 + `cmd_hooks` 手动入口 +
   `ToolPipeline` 契约都补齐了，但 **`ToolPipeline` 没有生产构造方**，
   `schema_resolver` 是契约补齐而非覆盖面扩大；`cmd_hooks` 取 schema
   依赖 kernel 暴露 `tool_registry`，取不到仍回落保守子集。

两个 note 都补了纠偏说明，`status` / `evidence` 结构**不变**，新增回归把
计数逐项钉死。**不靠改口径凑数**。消 gap 需要「全事件面对齐 +
exit-code-2 + 真实生产调用链的全路径 schema 证据」，不是补 note。

### 三处断言同步（**不是放宽**）

- `test_b3_hooks_extended.py::test_five_events_have_no_production_trigger_yet`
  改成 `..._have_production_triggers_now`：逐一验证统一触发层 5 个方法、
  **11 处**子系统接线、default provider 注入、通知类/决策类分类不混淆。
  少任何一处接线都失败 —— 比原来的「0 命中」断言更强。
- `tests/test_arch_security_fixes.py` 的 `FakeHooks.run_pre(name, args)`
  不接受 `tool_schema`：`ToolPipeline` 改为无 schema 时不传该关键字，
  既有测试**原样保留、零修改**，行为与旧版完全一致。
- `tests/test_b3_hooks_extended.py` 其余计数/分类断言一条未动。

### A′ ×2：自己挖坑自己抓回

1. **`remote_control.notify` 的提前返回**：初版把 `Notification` 派发
   放在函数末尾 `return pushed` 之前，但 `rc is None: return False` 是
   **提前返回** —— 无推送对象时 hook 永远不触发。自查发现后移到
   `log.warning` 之后、所有返回路径之前。
2. **`ToolPipeline` 强传 `tool_schema=`**：上一轮的改动让老式 hook mock
   抛 `TypeError`（实测 1 条既有回归失败）。改成只在有 schema 时传，
   兼容且无 schema 时行为与旧版逐值一致。

两处都是**接线脆弱性**，不是原有代码回归，已各自加针对性断言。

### 验证（按分批报告，批次间有重叠、不累加）

```
B3 续轮新回归 + 上一轮 B3 + 5 个 hooks 既有文件        97 passed
最终合并批次（B3 续轮 + hooks + parity + 写边界 +
    两条侧门 + B2 各轮 + config + worktree + session +
    arch 执行/安全）                                    （见下）
matrix.validate() == []  |  evidence.verify_evidence() == []
verify_doc_numbers.py problems == []
py_compile: 改动 Python 文件全部 OK
```

`tests/test_b3s_triggers.py` 覆盖：无 hooks 严格 no-op、显式 hooks 优先于
default provider、provider 异常回落、通知异常不掀翻、决策通道异常
fail-closed、老式 mock 缺 `run_decision` 也 fail-closed、**5 个事件端到
端在真实操作上全部触发**（真 git init + 真 `git worktree add` + 真
`Config.set_user` + 真 `ask_user` + 真 `notify`）、payload 字段抽查、
`WorktreeCreate` deny 在任何 FS 改动前阻断、hook 二进制缺失 fail-closed、
`Elicitation` deny 取消提问且不再问用户、`ElicitationResult` deny 作废、
hook 的 `allow` **不能**变成用户答案、headless 不派发 Result、hook 通道
炸了 `Config.set_user` 仍写成功、CLI 决策类路由、CLI 传 schema、
`ToolPipeline` 老式 mock 兼容 + resolver 生效 + 无生产构造方、矩阵钉死。

### 如实边界

- **7 个事件有触发点 ≠ 全事件对齐**：官方事件面远大于 7 个；
  CC exit-code-2 → decline 未实现；`Elicitation` 语义刻意不等价。
- **`ToolPipeline` 无生产构造方**，`schema_resolver` 只是契约补齐；
  `cmd_hooks` 取 schema 依赖 kernel 暴露 `tool_registry`。
- **行为变更**：`WorktreeCreate` hook 现在真的能拒绝创建（此前不可能，
  因为根本不触发）；`Elicitation` 能取消提问、`ElicitationResult` 能作废
  回答；`Config.set_user` / `notify` 现在会派发已配置的 hook。
- **Notification 在后台线程派发**，顺序与桌面通知本身不保证一致；
  `remote_control.notify` 在无推送对象时也触发（按「尝试发通知」语义）。
- `os_sandbox` 仍 gap、`deny_network_by_default` 仍 false 未翻、
  `credential_masking` 仍 partial；A 线 10 pending、分叉改动未合并、
  第三方自适应红队未做；不是真机多平台验证。
- 标语引擎 / 净化层 / `mapping.py` / `tui.py` / `runtime_slogans.py`
  逐字节未改。
