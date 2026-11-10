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


---

## 深度轮（续五）：接线**之后**的第二层 —— 写盘成败 / 重入递归 / 分类真值 / 串台可见性

> 沿用**自足标题**，不新增数字章节编号。**矩阵计数一个没动**：
> `ahead 10 / aligned 46 / partial 9 / gap 26 / not_applicable 8`，
> `fully_superior=false`，`b_waves_done=["B1"]`。两个 B3 条目仍
> `STATUS_GAP`，`catalog.py` **本轮零改动** —— 它的 note 没说错，只是
> 没提本轮的正确性修复，不为了让文档变长去碰它。
>
> 上一轮把 5 个扩展事件接上了生产触发点。这轮只问一句：
> **「接上之后，它会不会在错误的时候派发 / 派发到错误的会话 / 无限派发？」**
> 一点广度没扩。

### 六个候选的实测判定（4 修 / 2 不该修）

| 编号 | 实测结果 | 判定 |
|---|---|---|
| C1 | 把 `user_config_path` 指向一个目录 → `dump_yaml` 内部 `os.replace` 抛 `IsADirectoryError` 并**吞掉**返回 `None`；`Config.set_user` 照旧派发 `ConfigChange`。磁盘上**没有文件**，hook 却收到「配置已变更」 | **修**。与上一轮在 `ManagedSettings.reload` 写下的「失败不派发，否则外部 hook 会误以为配置已生效」**直接矛盾** |
| C2 | in-process hook 的 `run_notify` 里再调 `Config.set_user` → 递归 **247 层**，`dump_yaml` 连 `RecursionError` 也吞掉：stderr 出现「配置写入失败 ... maximum recursion depth exceeded」，但每一层仍继续派发，既不报错也不停止 | **修** |
| C3 | 上一轮 `test_event_classification_not_mixed` 只检查 `triggers.py` 自己的字符串，**没有**核对 `manager.py` 的真实 `_NOTIFY_EVENTS` / `_DECISION_EVENTS` 集合 —— 若引擎把 Elicitation 归成 notify，刚接的触发点会静默失效而测试全绿 | **不该修代码**，但补一条**真值回归**（查常量），比字符串断言更强 |
| C4 | 两次 `set_default_hooks_provider(A)/(B)` 之后，先用 A 构造的 `HookTrigger` 派发 → **A 零触发、B 收到 A 的事件**。进程级 provider 是单会话假设，多会话静默串台 | **部分修**（见下） |
| C5 | `Notification` payload 含正文但 `ConfigChange` payload 只有 `source/key/origin`，**不含配置值**（实测 `api.key` 的值没进 hook） | **不该修**，加回归锁住 |
| C6 | `delete_user` 返回 False 时不派发 | **不该修**（上一轮已正确），加回归锁住 |

### 修复（如实，不夸大）

| 位置 | 修复 |
|---|---|
| `config/loader.py` | `dump_yaml` 拆出单一实现 `_dump_yaml_impl`，新增 `dump_yaml_checked` **如实返回落盘成败**；**`dump_yaml` 仍返回 `None`、仍吞异常、行为逐值不变**（全仓既有调用方忽略返回值，源码级断言 `mkstemp` 只出现 1 次）。`Config.set_user` / `delete_user` 只在 `ok` 时派发，新增 `last_write_persisted` 供诊断。刻意**不回读比对值**：`safe_dump`/`safe_load` 的序列化差异会造成假阴性，且会引入「判定依赖文件系统时间点」的缓存 —— 与前几轮拒绝给活性判定加文件系统缓存是同一个理由 |
| `hooks/triggers.py` | **thread-local 重入守卫**：同线程同事件重入，通知类跳过并计数、决策类 **fail-closed** 返回 `failure_kind="reentry_suppressed"`（绝不返回空决策放行，否则递归变成安全绕过）；`try/finally` 清理，异常后同事件仍可派发；不同线程并发同事件**不互相抑制**。跨进程 command hook **不需要**守卫：子进程不继承父进程 thread-local，天然不会形成这条递归链 —— 如实标注，不夸大覆盖面 |
| `app.py` | 把 `config._hooks` **显式回填**为本会话 hooks。Config 构造最早、生命周期最长，此前只能靠全局 fallback，是 C4 的主链路；`/worktree` 与 `ask_user` 上一轮已显式传 hooks |
| `hooks/triggers.py` / `hooks/__init__.py` | `set_default_hooks_provider(fn, *, owner=None)` + `provider_diagnostics()` 暴露 `owner / generation / overrides / reentry`。**串台没被消除，只变成可诊断**：模块级 `remote_control.notify` / `SecurityAlerter` 后台线程仍用全局 fallback，真正多会话隔离需上游给这些入口显式传 owner，本轮不改 5 个子系统签名以免把接线变脆 |

**C4 的诚实结论**：修掉了最长的那条链（Config），但没宣称「多会话已隔离」。
`test_overrides_are_visible_not_silent` **同时断言串台仍存在**且
`overrides >= 1` —— 把边界写成可执行事实，而不是包装成成果。

### 为什么两个 B3 条目仍 `STATUS_GAP`
与上一轮同一组硬理由，本轮一个都没消：官方 hooks 参考的事件面远大于
7 个、CC exit-code-2 → decline 未实现、`Elicitation` 语义刻意不等价、
`ToolPipeline` 无生产构造方、`cmd_hooks` 取 schema 依赖 kernel 暴露
`tool_registry`。本轮修的是「已接线触发点的正确性」，不是功能覆盖面。
`catalog.py` 零改动，`status`/`evidence` 结构不变，**不靠改口径凑数**。

### 断言同步（不是放宽）
新增 `tests/test_b3v_depth.py`（约 30 例）：C3 从「查 `triggers.py`
字符串」升级为「核对 `manager.py` 的 `_NOTIFY_EVENTS` /
`_DECISION_EVENTS` 真值」；`tests/test_b3s_triggers.py` 与
`tests/test_b3_hooks_extended.py` **一条未改**，全部通过；矩阵计数
逐项钉死。

### A′ ×2（自己写错自己抓回）
1. **写盘失败 delete 用例走错分支**：初版把 `user_config_path` 直接
   指向目录，结果 `_load_yaml` 先读不到 `x.y`，`delete_user` 走
   「键不存在 → `return False`」，根本没到写盘。改成 monkeypatch
   写盘出口返回 `False`，才真正覆盖目标分支；`set_user` 的失败由
   C1 那个真实目录用例覆盖。
2. **子进程校验用了 `str` 而非 `Path`**：`_load_yaml` 调
   `path.exists()` 直接 `AttributeError` 导致子进程 rc=1。改成
   `Path(...)` 并重跑通过。

两处都是**新写测试自身**的问题，不是产品代码回归。

### 验证（按分批报告，批次间有重叠、不累加）

```
B3 续轮 V + 上一轮 B3 + 5 个 hooks 既有文件 + mixin +
    config / config_schema / config_error_fastfail /
    api_config_fixes                                    182 passed
宽合并批次（parity / worktree / session / arch / 写边界 /
    两条侧门 / B2 各轮 / slash）                        （见报告）
matrix.validate() == []  |  evidence.verify_evidence() == []
verify_doc_numbers.py problems == []
py_compile: 改动 Python 文件全部 OK
```

`tests/test_b3v_depth.py` 覆盖：写盘失败不派发 / 正常写派发 /
`last_write_persisted` / 删除命中但写失败不派发 / `dump_yaml` 行为逐值
不变 / `checked` 出口 True+False / 单一实现无重复 / payload 不含配置值 /
通知类重入只 1 次 / 决策类重入 fail-closed / 异常后守卫释放 /
4 线程并发不抑制 / **真子进程验证不继承 thread-local** / 计数只是信息项 /
分类真值 / 15 事件表 / overrides 可见 / 显式 hooks 不受覆盖 /
`app.py` 回填 + owner 源码断言 / 模块级 fallback 如实标注 / 矩阵钉死 /
`catalog.py` 零改动。

### 如实边界
- **C4 未完全修**：模块级通知入口仍可能串台，只是可诊断；真正隔离需
  上游给这些入口显式传 owner。
- **跨进程 command hook 不是靠守卫保证的**，是进程边界天然成立；
  若未来把 hook 执行器改成 in-process 同步，守卫才开始覆盖那条链。
- **写盘失败时内存视图仍更新**（既有行为），重启后会丢失 —— 本轮
  只保证「不把失败伪装成 ConfigChange」，不扩大改动面去修它。
- **不回读比对值**，依赖 `os.replace` 原子成功；并发外部改写配置
  不在检测范围。
- **行为变更**：`Config.set_user/delete_user` 写盘失败时不再派发
  `ConfigChange`；`app.py` 会回填 `config._hooks`。
- `os_sandbox` 仍 gap、`deny_network_by_default` 仍 false 未翻、
  `credential_masking` 仍 partial；A 线 10 pending、分叉改动未合并、
  第三方自适应红队未做；不是真机多平台验证。
- 标语引擎 / 净化层 / `mapping.py` / `tui.py` /
  `runtime_slogans.py` 逐字节未改。


---

## 深度轮（续六）：C4 收尾 —— 模块级入口的**真正会话绑定**

> 沿用**自足标题**，不新增数字章节编号。**矩阵计数一个没动**：
> `ahead 10 / aligned 46 / partial 9 / gap 26 / not_applicable 8`，
> `gaps=26`，`fully_superior=false`，`b_waves_done=["B1"]`。两个 B3
> 条目仍 `STATUS_GAP`，`catalog.py` **本轮零改动** —— 本轮修的是
> 「已接线触发点的会话归属」，不是功能覆盖面，不靠改口径凑数。
>
> 上一轮如实留了一句边界：`remote_control.notify` / `SecurityAlerter`
> 后台线程 / ACP `ask_user` 仍是全局 fallback，串台只是「可见」没被
> 消除。这轮把它收尾，一点广度没扩。

### 五个候选的实测判定（4 修 / 1 不该修）

| 编号 | 修复前实测 | 判定 |
|---|---|---|
| A | `set_default_hooks_provider(A)` 后用 A 构造 `HookTrigger()`，切到 B 再派发 → **A 零触发、B 代收**。根因：`_effective()` 在**每次派发时**才读全局 provider，构造不冻结 | **修** |
| C | A 会话订阅的 `SecurityAlerter`，B 覆盖 provider 后在后台线程 `_notify_safely` 派发 → **A 零触发、B 代收**。后台线程执行时刻与订阅时刻不同，现场 `HookTrigger()` 必然读到最新覆盖 | **修** |
| D | `remote_control.notify()` 签名无 hooks 入参，每次现场 `HookTrigger()`；串行会话切换后单例归属完全取决于**派发时刻**而非会话 | **修** |
| E | ACP `KernelAcpBridge.ask_user` 无 `self.hooks`，`HookTrigger()` 无参，Elicitation 事件无会话绑定 | **修** |
| B | `get_alerter()` 是进程级单例，第二次传 `home` 被静默忽略（实测 `y._home == h1`） | **不该修**：重写单例架构超出本轮；但新增 `hooks` 属性 + `bind_session_hooks()` 回填让它在**串行**会话切换后指向正确会话。回归里明确锁住 `x is y` 这个既有事实 |

### 修复（如实，不夸大）

1. **`HookTrigger.__init__` 构造时冻结** hooks，支持 `owner=` 查 registry；
   `_effective()` 不再读全局。现场构造的 trigger 仍绑定调用时刻的当前
   会话（A2 回归验证），只有「长期持有 trigger 跨覆盖」的行为变化 ——
   那正是要修的串台。`owner` 查不到时**不回落** default（避免拼错
   owner 就静默派到别的会话）。
2. **按 owner 分桶的 session registry**：`register_session` /
   `unregister_session` / `resolve_session` /
   `session_registry_diagnostics`。**超出 64 上界直接拒绝，不做 LRU
   静默淘汰** —— 安全绑定被悄悄挤掉会让老会话突然派到别处或静默
   no-op。`hooks=None` 是合法注册值，注销不靠 `pop` 值判空（与深度轮
   5/11 的 A′ 同类）。
3. **`bind_session_hooks(hooks, owner=...)`**：注册 registry + 回填已存在
   的 `_global_alerter` / `_notify_rc` 两个进程级单例。顺序刻意在
   `set_default_hooks_provider` **之后**：新建消费者靠
   `current_session_hooks()` 捕获，已存在的靠这里显式回填。只改
   `hooks` 属性、不改单例对象身份，既有调用方零感知。
4. **三个模块级消费者改为实例级绑定**：
   `RemoteControl(..., hooks=)` / `SecurityAlerter(..., hooks=)` /
   `KernelAcpBridge(..., hooks=)`；派发时用 `self.hooks`，不再现场读
   全局。`remote_control.notify()` 另加**可选关键字** `hooks` 入参
   （向后兼容），给调用方显式通道。全仓无参 `HookTrigger()` **代码**
   消费点降为 0（源码扫描排除注释行）。
5. `security_plugin.py` 构造 alerter 时传 `config._hooks`（plugin 初始化
   可能早于 app.py 回填，此时 `SecurityAlerter` 内部退回
   `current_session_hooks()`）；`app.py` 调用 `bind_session_hooks`。

### 三条上轮断言同步（**全部改强，不是放宽**）

| 上轮断言 | 本轮同步 |
|---|---|
| `test_overrides_are_visible_not_silent` 锁住「串台仍存在」 | 改为「A 收到、B 零」+ `overrides` 仍可见（覆盖仍是诊断项，只是不再能改变已构造 trigger 的归属） |
| `test_app_backfills...` 查 `owner=` 字面串 | 增加 `_session_owner`、`bind_session_hooks(...)` **及顺序**断言 |
| `test_module_level_notify_still_uses_global_fallback` | 改名 `..._is_now_instance_bound`，断言 `HookTrigger(_h)` / `getattr(_rc, "hooks", None)` / `HookTrigger(self.hooks)`，且全仓无参消费点为 0 |

### A′ ×1（自己写错自己抓回）
新写的全仓源码扫描把**注释行**里的 `HookTrigger()` 字面串也算成消费点
（两处行注释在描述「上一版」行为），误报 2 条。改为只看非注释行。
是**新写测试自身**的问题，产品代码零回归。

### 验证（按分批报告，批次间有重叠、不累加）

```
B3 续轮 VI + 上一轮 V + B3 两轮 + 5 个 hooks 既有文件 + mixin +
    config                                              185 passed
宽回归 A（parity / worktree / session / arch / 写边界 / 两条侧门
          / B2 各轮 / slash 前半）                        （见报告）
宽回归 B（arch_security / B2 剩余 / slash 后半）        （见报告）
matrix.validate() == []  |  evidence.verify_evidence() == []
verify_doc_numbers.py problems == []
py_compile: 改动 Python 文件全部 OK
```

`tests/test_b3vi_session_binding.py` 覆盖：构造时冻结 / 现场构造仍绑定
调用时刻 / 显式 hooks 优先 / `owner` 查不到不回落 / 决策类重入守卫
未破坏 / 单例架构如实锁住 / 三个构造函数默认捕获 / 后台线程派到本会话
/ `bind_session_hooks` 回填两个单例 / 无单例时绑定不掀翻 /
模块级 notify 用单例绑定 + 显式 `hooks` 参数 + `rc is None` 仍派发 +
返回值语义不变 / ACP 实例绑定 + 全仓无参消费点为 0 /
registry 注册·解析·注销·`None` 合法值·非法 owner·**64 上界拒绝而非淘汰** /
`provider_diagnostics()` 新增 `sessions` / provider 异常 no-op /
app.py 顺序断言 / plugin 注入 / 矩阵钉死 / `catalog.py` 零改动。

### 如实边界
- **`_global_alerter` / `_notify_rc` 仍是进程级单例**，两个会话**并发
  并存**时会共用同一实例（后者复用前者的绑定）—— 重写单例架构超出
  本轮，回归里明确锁住 `x is y`。**串行**会话切换已由
  `bind_session_hooks` 回填修好，不宣称「完全多会话隔离」。
- registry 上界拒绝只影响显式 `owner=` 查询；**已绑定实例的派发不受
  影响**（`bind_session_hooks` 仍会回填单例）。这是「诊断 fail-open、
  裁决 fail-closed」的刻意取舍，如实标注。
- **行为变更**：`HookTrigger` 构造时冻结（长期持有的 trigger 不再随
  provider 覆盖漂移）；三个构造函数新增 `hooks` 参数；`notify()` 新增
  可选关键字参数；`app.py` 多一次 registry 注册。
- 跨进程 command hook 仍不继承 thread-local（上一轮如实边界，未变）。
- `os_sandbox` 仍 gap、`deny_network_by_default` 仍 `false` 未翻、
  `credential_masking` 仍 partial；A 线 10 pending、分叉改动未合并、
  第三方自适应红队未做；不是真机多平台验证。
- 标语引擎 / 净化层 / `mapping.py` / `tui.py` / `runtime_slogans.py`
  逐字节未改。


---

## 深度轮（续七）：C4 最后一角 —— **并发**多会话的派发归属隔离

> 沿用**自足标题**，不新增数字章节编号。**矩阵计数一个没动**：
> `ahead 10 / aligned 46 / partial 9 / gap 26 / not_applicable 8`，
> `gaps=26`，`fully_superior=false`，`b_waves_done=["B1"]`。两个 B3
> 条目仍 `STATUS_GAP`，`catalog.py` **本轮零改动** —— 本轮修的是
> 「并发会话的派发归属」，不是功能覆盖面，不靠改口径凑数。
>
> 上一轮（VI）如实留了一句边界：`_global_alerter` / `_notify_rc` 仍是
> **进程级单例**，两个会话**并发并存**时共用同一实例（后者复用前者的
> 绑定）。这轮收尾，一点广度没扩。

### 五个候选的实测判定（4 修 / 1 不该修）

| 编号 | 修复前实测 | 判定 |
|---|---|---|
| O1 | `bind_session_hooks(B, owner="B")` **无条件回填**单例的 `hooks`；A 会话订阅的 `SecurityAlerter` 在 B 绑定后告警 → **A 零触发、B 代收**（实测 A=0 / B=1） | **修** |
| O2 | 模块级 `remote_control.notify()` 同源：C 会话第一次通知到 C，D 会话 bind 之后 C 的第二次通知落到 **D**（实测 C=1 / D=1） | **修** |
| O4 | `contextvars.ContextVar` **不跨** `threading.Thread`（主线程 `"A"` / 子线程 `None`，实测）。后台通知线程不能靠 contextvar 拿 owner | **修**（由调用方烘进数据） |
| O5 | 修 O1/O2 时**自己引入**的新风险（A′）：`owner=` 改成动态查表后，「owner 拼错/未注册」会让决策类静默返回空决策放行 | **修**：fail-closed `owner_not_registered` |
| O3 | `get_alerter()` 是进程级单例；`SecurityAlerter` 持有 `AlertLogger(home)` 与 bus 订阅、`RemoteControl` 持有端口与会话文件 | **不该修**：改成按 owner 多实例会引入文件竞争、重复订阅与端口冲突。回归明确锁住 `x is y` |

### 修复（如实，不夸大）

1. **`hooks/triggers.py`**：新增 `ContextVar` 会话 owner
   （`current_session_owner` / `set_session_owner` /
   `reset_session_owner`）、`hooks_for_owner`、`owner_miss_stats`
   （有界、`<other>` 归并、纯诊断）。`HookTrigger(owner=...)` 从
   「构造时查一次并冻结值」改成 **冻结 owner、派发时按 owner 分桶查
   registry**。查表是动态的，但 registry **按 owner 分桶而不是单槽**，
   所以 `bind(B)` 不会改 A 桶 —— 既支持会话内热替换，又不会随别的
   会话漂移。这正是 VI 的单槽 provider 做不到的。
   `owner` 查不到**不回落** default（避免笔误串台），决策类另加
   fail-closed；无 `owner` 的构造仍冻结值，VI 的 C4-A 修复不破。
2. **`core/security_alert.py`**：`AlertRecord` 加 `owner: str = ""`
   （**进程内路由字段，不进 `to_dict()`**，既有审计格式零变化）；
   `alert()` 在**调用线程**捕获 owner 烘进记录；后台线程
   `_notify_safely` 用 `record.owner` 查分桶，绕开 O4。
3. **`core/remote_control.py`**：`notify()` 加可选关键字 `owner`；
   优先级 **显式 hooks > 本会话 owner 分桶 > 实例冻结 hooks**。
   未注册 owner 时只沿用实例既有绑定，行为零退化。
4. **`runtime/acp/bridge.py`**：`ask_user` 支持已注册 owner 分桶；
   未设置时沿用 `self.hooks`。一个 bridge 可服务多个 `session_id`，
   **owner 与 session_id 的映射由上层负责，本轮不自动派生**。
5. **`app.py`**：会话启动时 `set_session_owner(_session_owner)`，
   在 `set_default_hooks_provider` / `bind_session_hooks` 之后。

### 三条上轮断言同步（**全部改强，不是放宽**）
`test_module_level_notify_is_now_instance_bound` 增加 owner 分桶、
`getattr(record, "owner", "")`、`AlertRecord.owner` 与
`current_session_owner` 断言。VI 的「冻结未破」「显式 hooks 优先」
「无参消费点为 0」全部保留。

### A′ ×2（自己写错自己抓回）
1. **O5** 是修 O1/O2 时自己引入的新风险（动态查表 → 决策类静默
   放行），由新写回归抓回并改为 fail-closed。
2. 新断言里写了 `"record.owner"`，实际代码用
   `getattr(record, "owner", "")`（兼容旧记录），字面串对不上 →
   改成检查真实写法。产品代码零回归。

### 验证（按分批报告，批次间有重叠、不累加）

```
B3 续轮 VII + 上两轮 B3 + 5 个 hooks 既有文件 + mixin + config +
    alert / remote / plugin / bus / bridge / ACP 相关       330 passed
宽回归 A（parity / worktree / session / arch / 写边界 / 两条侧门
          / B2 各轮 / slash 前半）                        （见报告）
宽回归 B（arch_security / B2 剩余 / slash 后半）        （见报告）
matrix.validate() == []  |  evidence.verify_evidence() == []
verify_doc_numbers.py problems == []
py_compile: 改动 Python 文件全部 OK
```

`tests/test_b3vii_concurrent_sessions.py` 覆盖：O1 后台线程并发 /
单槽回填仍在但派发不读它 / 无 owner 回落实例绑定 / 未注册 owner 不
回落单槽 default / O2 模块级 notify 并发 + 显式 hooks 与 owner 优先级
+ 签名向后兼容 + `rc is None` 仍派发 / O4 set·reset·非法 owner·
跨线程·foreign token·`AlertRecord.owner` 不序列化 / owner 动态分桶
热替换 + 别会话 bind 不改我的桶 + VI 冻结未破 / O5 决策 fail-closed
+ 通知 no-op + miss 有界 + diagnostics / O3 单例身份与资源冲突面 /
app 接线顺序 + bridge + 全仓无参消费点 + 矩阵钉死 + `catalog.py` 零改动。

### 如实边界
- **单例对象身份仍是进程级**（不创建多实例，避免文件竞争、重复
  bus 订阅与端口冲突）。隔离的是**派发归属**，不是实例本身。
- `bind_session_hooks` 的**单槽回填仍在**（`al.hooks` 会被最后一次
  bind 覆盖），只是有 owner 上下文的派发走分桶表、不再读它；
  **未设置 owner 且未显式传 hooks** 的路径仍沿用最后一次 bind 的
  绑定（既有行为）—— **不宣称「完全多会话隔离」**。
- `owner_miss_stats` 是纯诊断项，不参与裁决；决策类的 fail-closed
  只针对**显式绑定 `owner=` 却查不到**的路径。
- ACP 的 `session_id` ↔ owner 映射由上层负责，本轮不自动派生。
- **行为变更**：`HookTrigger(owner=)` 从冻结值改为冻结 owner +
  动态分桶；`notify()` 新增可选 `owner`；`AlertRecord` 新增字段；
  `app.py` 设置 contextvar。
- `os_sandbox` 仍 gap、`deny_network_by_default` 仍 `false` 未翻、
  `credential_masking` 仍 partial；A 线 10 pending、分叉改动未合并、
  第三方自适应红队未做；不是真机多平台验证。
- 标语引擎 / 净化层 / `mapping.py` / `tui.py` / `runtime_slogans.py`
  逐字节未改。


---

## 深度轮（续八）：会话生命周期收口 + 跨线程 owner 句柄化

> 沿用**自足标题**，不新增数字章节编号。**矩阵计数一个没动**：
> `ahead 10 / aligned 46 / partial 9 / gap 26 / not_applicable 8`，
> `gaps=26`，`fully_superior=false`，`b_waves_done=["B1"]`。两个 B3
> 条目仍 `STATUS_GAP`，`catalog.py` **本轮零改动** —— 本轮修的是
> 「会话生命周期与线程边界」，不是功能覆盖面，不靠改口径凑数。
>
> 上两轮把「派发归属」从单槽 provider 推到 owner 分桶，但留了三处
> 生命周期/线程边界没处理。本轮一点广度没扩，只把这条线挖到底。

### 六个候选的实测判定（5 修 / 1 不该修）

| 编号 | 修复前实测 | 判定 |
|---|---|---|
| P1 | `unregister_session` 在生产代码里**零调用点**（只有定义与 `__init__` 导出）。registry 只增不减，占满 64 槽后 `bind_session_hooks(..., owner=NEW)` 返回 **False**，而 `app.py` 完全不检查返回值 —— 第 65 个会话的 `HookTrigger(owner=NEW).config_change()` 静默 no-op | **修** |
| P2 | `set_session_owner` 设完从不复位；同线程复用（CLI 循环、ACP server 长驻、测试）时，第二个会话构造失败后 owner 仍是第一个会话的值（实测残留 = True） | **修** |
| P3 | `ContextVar` **不跨** executor 线程（主线程 `"ctx-main"` / `ThreadPoolExecutor` 线程 `None`，实测）。`KernelAcpBridge` 原先在 `ask_user` 里**运行时**读 `current_session_owner()`，权限回调 / `_AcpUIHandle` 跑在 executor 线程 —— owner 解析退化为实例冻结 hooks | **修**（显式句柄化） |
| P4 | `_bump_owner_miss` **锁外**读 `len()` / `in`、锁内写入，是 TOCTOU。GIL 下本次未稳定复现越界。上界语义也含糊：实际最多 `_MAX_MISS_KEYS` 个具体 owner + 1 个 `<other>` = 65 | **修**（锁内 + 口径） |
| P5 | `bind_session_hooks` docstring 写「回填 **3** 个模块级单例」，但 `for` 元组里一直只有 2 个（`_global_alerter` / `_notify_rc`）；ACP bridge 是 per-agent 实例，不是模块级单例 | **修**（口径改如实） |
| O3 | `get_alerter()` 仍是进程级单例（改成多实例会引入文件竞争、重复 bus 订阅、端口冲突） | **不该修**：前两轮已锁 `x is y`，本轮不动 |

### 修复（如实，不夸大）

1. **`hooks/triggers.py`**：新增 `SessionHandle` /
   `activate_session(owner=, hooks=, provider=)` /
   `deactivate_session(handle)`。四个动作（注入 provider、绑定
   contextvar、注册 registry、回填单例）收成一个入口，返回携带
   **复位 token** 的句柄；`deactivate` 注销 registry + 复位
   contextvar。注册被拒新增 `rejected` 计数并进
   `provider_diagnostics()` —— **可见，不再静默**。
   `deactivate` 刻意**不清** default provider：清掉会打断仍在运行的
   其他会话（既有行为）。
2. **`app.py`**：改用 `activate_session`；把 `session_owner` 与
   `session_handle` 显式挂到 `agent.ctx`；`active=False` 时
   `logger.warning`，不静默退化到单槽绑定。
3. **`runtime/acp/bridge.py`**：新增构造参数 `owner` 与
   `_resolve_owner()`，优先级 **显式 owner > `agent.ctx.session_owner`
   > `current_session_owner()`**。前两者跨线程稳定，不依赖
   contextvar；`ask_user` 改用它。仍**不**按 `session_id` 自动派生
   owner（一个 bridge 可服务多个 session_id，映射由上层负责）。
4. **`_bump_owner_miss`** 整个判定收进锁内，docstring 明确
   「最多 64 个具体 owner + 1 个 `<other>` = 65」。
5. **`bind_session_hooks`** docstring 口径改成「2 个」。

### 四条上轮断言同步（**全部改强，不是放宽**）
`test_app_backfills_config_hooks_and_passes_owner` /
`test_app_calls_bind_after_setting_provider` /
`test_app_sets_session_owner_after_bind` /
`test_app_injects_default_provider` 从「检查分散调用与顺序」改为
「检查单一入口 + ctx 挂载 + `active` 失败可见 + 生命周期 API 导出 +
旧分散调用已消失」；`test_bridge_supports_owner_without_auto_mapping`
补上 `_resolve_owner` 与显式句柄断言；
`test_diagnostics_in_provider_diagnostics` 增加 `rejected` 与顶层
`session_rejections` 一致性断言。

### A′ ×3（自己写错自己抓回）
1. **产品代码真缺陷**：`reset_session_owner` 只吞
   `ValueError/TypeError`，但 `ContextVar.reset()` 对**已用过**的
   token 抛 `RuntimeError("Token has already been used once")`。
   `deactivate_session` 重复调用（幂等关闭路径）会掀翻 —— 本轮
   新写回归直接抓到，已改为三类异常一律吞（已复位 == 已达目标状态）。
2. **测试自身**：4 处源码扫描把**注释行**里的
   `set_default_hooks_provider(A)/(B)` 历史说明算成调用，误报 →
   改为只看非注释行。
3. **测试自身**：`deactivate_session` 扫描把 `def deactivate_session(`
   **定义行**算成宿主调用，误报 → 排除 `def ` / `from ` 行。

### 验证（按分批报告，批次间有重叠、不累加）

```
B3 续轮 VIII + 上三轮 B3（生命周期/并发/绑定/V）       131 passed
既有 hooks / config / alert / remote / plugin / bus /
   bridge / ACP 相关                                  233 passed
宽回归 A（parity / worktree / session / arch / 写边界 /
   两条侧门 / B2 各轮 / slash 前半）                 （见报告）
宽回归 B（arch_security / B2 剩余 / slash 后半）     （见报告）
matrix.validate() == []  |  evidence.verify_evidence() == []
verify_doc_numbers.py problems == []
py_compile: 改动 Python 文件全部 OK
```

`tests/test_b3viii_session_lifecycle.py` 覆盖：P1 64 槽耗尽 +
`rejected` 可见 + 注销后槽位可复用 + `activate`/`deactivate` 往返 +
provider 注入 + 拒绝句柄安全关闭 / P2 token 复位 + 会话失败不残留 +
幂等关闭 + foreign token / P3 contextvar 不跨 executor +
`_resolve_owner` 从 `agent.ctx` 跨线程解析 + 显式 owner 优先 +
回退 contextvar + 构造签名 + `ask_user` 用 `_resolve_owner` + 不按
`session_id` 自动映射 / P4 有界 `<other>` + 并发 24 线程不丢计数 +
判定在锁内 / P5 docstring 2 个单例 + `rejected` 文档 / 不该修的
单例身份、单槽回填、`AlertRecord.owner` 不序列化、上轮契约 /
app 接线 + 生命周期 API 导出 + 全仓无参消费点 + 矩阵钉死 +
`catalog.py` 零改动 + **`deactivate` 未接到所有宿主如实锁住**。

### 如实边界
- **`deactivate_session` 没有接到所有宿主**：项目里没有统一的 agent
  close 钩子，本轮只提供 API + `agent.ctx.session_handle` 供宿主调用。
  未调用的长跑进程仍会占满 64 槽，但现在 `rejected` 可见、`app.py`
  会 warning，**不再静默**。
- **P3 修的是「显式句柄传递」，不是「已观测 ACP 串台」**：
  `ask_user` 经 `run_coroutine_threadsafe` 跑在事件循环线程，
  `create_agent` 也在该线程，所以原实现多数场景能拿到 contextvar；
  本轮消除的是「依赖线程上下文」这一脆弱性（executor 线程实测
  拿不到），不夸大成修了某个已复现的串台故障。
- **P4 锁内化未对应到已复现的越界**：GIL 下本次未稳定复现，加锁
  是消除对 GIL 实现细节的依赖（与前几轮同口径），不宣称修了已观测
  故障；上界语义明确为 65 而非 64。
- 单例对象身份仍进程级；`bind_session_hooks` 单槽回填仍在；
  `AlertRecord.owner` 仍不进 `to_dict()`；单 bridge 不按
  `session_id` 自动派生 owner。
- **行为变更**：`activate_session` 取代 app.py 里四个分散调用；
  `KernelAcpBridge` 新增 `owner` 构造参数与 `_resolve_owner()`；
  `reset_session_owner` 多吞一类异常；`session_registry_diagnostics`
  多一个 `rejected` 字段。
- `os_sandbox` 仍 gap、`deny_network_by_default` 仍 `false` 未翻、
  `credential_masking` 仍 partial；A 线 10 pending、分叉改动未合并、
  第三方自适应红队未做；不是真机多平台验证。
- 标语引擎 / 净化层 / `mapping.py` / `tui.py` / `runtime_slogans.py`
  逐字节未改。


---

## 深度轮（续九）：会话激活事务化 + owner 冲突拒绝 + CLI 主路径接线

> 沿用**自足标题**，不新增数字章节编号。**矩阵计数一个没动**：
> `ahead 10 / aligned 46 / partial 9 / gap 26 / not_applicable 8`，
> `gaps=26`，`fully_superior=false`，`b_waves_done=["B1"]`。两个 B3
> 条目仍 `STATUS_GAP`，`catalog.py` **本轮零改动** —— 本轮修的是
> 「会话激活的事务性与生命周期收尾」，不是功能覆盖面，不靠改口径凑数。
>
> 上一轮（VIII）把会话生命周期收成 `activate_session` /
> `deactivate_session`，并如实留下三条边界：`deactivate` 没接到所有
> 宿主、注册被拒「可见但 provider 可能已被切换」、`SessionHandle` 无
> 关闭标记。本轮一点广度没扩，只把这条线挖到底。

### 六个候选的实测判定（6 修 / 5 项「不该修」契约锁住）

| 编号 | 修复前实测 | 判定 |
|---|---|---|
| Q1 | `activate_session` **先切 provider 再注册**。占满 64 槽后第 65 个会话注册返回 False，但 `set_default_hooks_provider` 已切到新会话 —— 老会话里尚未回填 hooks 的无 owner 消费者从此派到被拒会话（实测 A fired=0 / NEW fired=1） | **修** |
| Q1b | `bind_session_hooks` 无论注册成功与否都继续回填两个模块级单例。实测注册失败时 `_global_alerter.hooks` 被改成**被拒会话**的 hooks（Q1 污染的隐藏面） | **修** |
| Q2 | owner 用 `"agent:%x" % id(agent)`，CPython 里 `id` 会被新对象复用（实测同型对象销毁后新建拿到同一 id）。旧 `_SESSIONS[owner] = hooks` **静默覆盖**先建会话的桶；先建会话的旧句柄 `deactivate` 会删掉后建会话（ABA，实测 `resolve_session -> None`） | **修（行为变更）** |
| Q3 | `bind` 中途抛异常时 provider 已切、contextvar 已设、却没有句柄可复位 —— 实测 `current_session_owner` 泄漏 `"sess-boom"` 且 `provider_diagnostics()["owner"]` 已被改 | **修** |
| Q4 | `deactivate_session` 不清 `agent.ctx` 上的 `session_owner` / `session_handle`。实测关闭后 `bridge._resolve_owner()` 仍返回**已注销**的 owner | **修** |
| Q5 | `SessionHandle` 是 frozen、无 `closed` 标记，重复 `deactivate` 只能靠「registry 里还有没有 key」反推 | **修** |
| Q6 | `deactivate_session` 在生产代码里**零调用点**（只有定义与 `__init__` 导出），registry 只增不减 | **修（接 CLI 主路径）** |

**不该修（配可执行回归锁住）**：`get_alerter()` 仍是进程级单例（多实例会引入文件竞争、重复 bus 订阅、端口冲突）；单 bridge 不按 `session_id` 自动派生 owner；`deactivate` 刻意**不清** default provider（清掉会打断仍在运行的其他会话）；`AlertRecord.owner` 仍不进 `to_dict()`；ACP server / web / stream_json / TUI.close / `AcpSession.dispose` **仍未接线**。

### 修复（如实，不夸大）

1. **`hooks/triggers.py`**：把 **registry 注册**作为唯一事务边界。
   - `bind_session_hooks` 注册失败立即 `return False`，**不回填单例**。
   - `activate_session` 改为：先 `bind`（成功才回填）→ 失败/异常返回
     `active=False, closed=True` 句柄，**零全局副作用** → 成功才注入
     provider、绑定 contextvar、把 owner/handle 挂到 `ctx`；阶段 2
     自身异常则精确回滚刚注册的槽并复位 token。
   - `register_session` 对**已存在 owner 一律拒绝**（不再覆盖）并计数
     `conflicts`；`unregister_session(owner, *, expected=)` 仅在桶里
     仍是同一 hooks 对象时删除（ABA 防护，不传则旧语义）。
   - `SessionHandle` 改为可变 dataclass，新增 `hooks` / `ctx` /
     `closed`；`deactivate_session` 检查 `closed`、精确注销、仅当
     `ctx.session_handle is handle` 时清理 ctx 残留。
   - 新增 `session_scope(...)` 上下文管理器（异常安全自动关闭）。
2. **`app.py`**：改为 `activate_session(..., ctx=agent.ctx)`，删掉手动
   挂载（失败路径不再留脏 ctx）。
3. **`cli/cmd_chat.py`**：新增 `_close_agent_session(agent)`，在**两个**
   SessionEnd finally 中 `_run_session_hooks` **之后**调用 —— CLI 主
   路径的 TUI 分支与普通 REPL 分支都接上 `deactivate_session`。

### 11 处上轮断言同步（**全部改强，不是放宽**）

`test_app_uses_activate_and_checks_active` /
`test_app_calls_bind_after_setting_provider` /
`test_app_backfills_config_hooks_and_passes_owner` /
`test_app_injects_default_provider` 改为检查 `ctx=agent.ctx` 入参且
app.py 不再手动挂载；`test_app_sets_session_owner_after_bind` 改为检查
事务化顺序 `bind < provider < set_owner` 与失败早返回；
`test_hot_replace_within_session` 改为检查同 owner 二次注册被拒 +
`conflicts` 可见 + 显式 unregister/register 的动态查表仍生效；
`test_diagnostics_in_provider_diagnostics` 补 `conflicts`；
`test_deactivate_not_wired_to_all_hosts_is_documented` 改为「cmd_chat
恰好 1 处宿主接线 + 其余宿主逐一锁住未接」；
`test_lifecycle_api_exported` 补 `session_scope`；
`test_session_registry_rejected_is_documented` 补 `conflicts`；
`test_bind_docstring_says_two_singletons` 扩大窗口并补 Q1b 早返回。

### A′ ×4（自己写错自己抓回）

1. **产品代码语法错误**：`hooks/__init__.py` 是反斜续行 import，新增
   `session_scope` 时误加尾逗号，`py_compile` 直接 `SyntaxError` ——
   改成续行反斜杠，已重编通过。
2. **新写 docstring 误伤 4 个既有回归**：`activate_session` docstring
   里写了 ``HookTrigger()`` 字面串，而全仓「无参消费点」扫描只排除
   `#` 行注释、不排除 docstring → 4 处误报。改成不含括号的写法，
   产品代码逻辑零改动。
3. **新测试自身**：Q1b 用 `Rec.hooks.n` 断言，但「零副作用」的正确
   表现恰是**属性根本没被设置**（`AttributeError`）→ 改成
   `not hasattr(...)`，并补「注册成功确实回填」的对照，避免恒真断言。
4. **新测试自身**：对照用例写 `unregister_session("filler-0")`，而
   `fill()` 默认前缀是 `f-0` → 改成 `f-0`。

### 验证（按分批报告，批次间有重叠、不累加）

```
B3 续轮 IX + 上四轮 B3（VIII/VII/VI/V/triggers）           196 passed
既有 hooks / config / alert / remote / plugin / bus /
   bridge / ACP 相关                                      203 passed
宽回归 A（parity / worktree / session / arch / 写边界 /
   两条侧门 / B2 各轮 / chat_handoff）                     218 passed
宽回归 B（arch_security / B2 剩余 / slash）              （见报告）
matrix.validate() == []  |  evidence.verify_evidence() == []
verify_doc_numbers.py problems == []
py_compile: 10 个改动 Python 文件全部 OK
```

`tests/test_b3ix_session_transaction.py` 覆盖：Q1 注册被拒不切
provider + 老会话 `HookTrigger` 仍收到事件 / Q1b 单例零副作用（含
成功对照）/ 失败句柄 `closed=True` 且安全 deactivate / contextvar 与
ctx 零残留 / Q2 id 复用实测 + 同 owner 拒绝 + ABA 误删防护 +
`unregister(expected=)` 语义 + conflict 不计入容量拒绝 / Q3 bind
异常注入 + 阶段 2 异常回滚 / Q4 ctx 清理 + 不误清新会话 / Q5
`closed` 字段与幂等 / `session_scope` 正常与异常路径 / Q6 两个
finally 顺序 + 外来 agent 安全 + 真释放槽位 + 其余宿主锁住 /
不该修契约 / 事务化顺序 / 矩阵钉死 / `catalog.py` 零改动。

### 如实边界

- **Q2 是行为变更**：同 owner 二次 `register_session` 从「覆盖」变
  「拒绝」，会话内热替换需显式 `unregister` + `register`；
  `HookTrigger(owner=)` 的动态查表仍生效（回归已验证）。
- **Q3 的异常是注入故障**（monkeypatch `bind` 抛错），不是线上已观测
  异常；**Q2 的 id 复用**是 CPython 实现特性实测，用「同 owner 字符
  串」模拟，不声称线上一定发生；**Q4 修的是「归属信息残留」，未
  对应已观测派发错误**（bridge 的 `ask_user` 会先校验
  `resolve_session(_o) is not None`）。
- **`deactivate_session` 只接了 CLI 主路径**：ACP server / web /
  stream_json / TUI.close / `AcpSession.dispose` 仍未接线，不宣称
  「全部宿主已覆盖」；`session_scope` 提供了统一契约但未强制改造。
- 事务化顺序变更意味着注册失败不再切 provider、不再回填单例、ctx
  不留脏值；`deactivate` 仍不清 default provider；单例对象身份仍
  进程级、单槽回填仍在、`AlertRecord.owner` 仍不序列化、单 bridge
  不按 `session_id` 自动派生 owner。
- `os_sandbox` 仍 gap、`deny_network_by_default` 仍 `false` 未翻、
  `credential_masking` 仍 partial；A 线 10 pending、分叉改动未合并、
  第三方自适应红队未做；不是真机多平台验证。
- 标语引擎 / 净化层 / `mapping.py` / `tui.py` / `runtime_slogans.py`
  逐字节未改。


---

## 深度轮（续十）：create_agent 的真实会话生命周期（纠偏 + R1–R4）

> 沿用**自足标题**，不新增数字章节编号。**矩阵计数一个没动**：
> `ahead 10 / aligned 46 / partial 9 / gap 26 / not_applicable 8`，
> `gaps=26`，`fully_superior=false`，`b_waves_done=["B1"]`。两个 B3
> 条目仍 `STATUS_GAP`，`catalog.py` **本轮零改动**。本轮修的是
> 「会话生命周期的真实泄漏面」，不是功能覆盖面，不靠改口径凑数。

### 先纠偏：上一轮「5 个未接宿主」的口径过宽

IX 结尾写「ACP server / web / stream_json / TUI.close /
AcpSession.dispose 仍未接线」。实测源码扫描：
**`tui.py` / `runtime/acp/session.py` / `runtime/acp/server.py` 的
`create_agent` 调用点都是 0** —— 它们根本不产生 `SessionHandle`，
「没接 deactivate」不构成缺陷。真正产生 handle 的是 **9 个
`create_agent` 调用方**：`cli/cmd_acp.py`、`web/server.py`、
`stream_json/headless.py`、`tools/subagent_tool.py`、
`tools/workflow_tool.py`、`hooks/manager.py`、`runtime/acp/bridge.py`、
`core/_sandbox_entry.py`、`core/background_worker.py`。

### 四个候选的实测判定（全部先复现再修）

| 编号 | 修复前实测（fake kernel 真跑 `app.create_agent`） | 判定 |
|---|---|---|
| R1 | `app.create_agent` 注入 `provider=lambda: getattr(getattr(agent, "ctx", None), "hooks", None)`。每个子 agent 创建都覆盖**进程级单槽**；主 agent A 与子 agent B 创建后，主会话里**新建**的无 owner 消费者派到 B（A fired=1 / B fired=1） | **修** |
| R2 | 同一个 lambda 的闭包 cell 类型就是 `Agent`：`set_default_hooks_provider` 把它存成模块级单槽，最后一个 agent **永远无法 GC**（删引用 + `gc.collect()` 后弱引用仍存活） | **修** |
| R3 | 短命子 agent 每次创建都注册一个槽、从不注销。70 次后打满 64 槽（`rejected=6`）；叠加 `"agent:%x" % id(agent)` 的 CPython id 复用（实测同型对象销毁后新建拿到同一 id），新会话被 IX 的 `conflicts` 拒绝、`active=False` —— **静默失去 hooks**。这是 IX 把「覆盖」改「拒绝」后，泄漏槽位暴露出来的真实回归链 | **修** |
| R4 | `deactivate_session` 刻意不清 default provider，关闭子会话后单槽仍指向已注销会话（`provider owner` 仍是 `sub`） | **修** |

**5 项「不该修」契约锁住**：`cli/cmd_acp.py` / `web/server.py` /
`runtime/acp/bridge.py` 三个长驻宿主**仍未接线**（下一轮）；
`core/_sandbox_entry.py` / `core/background_worker.py` 是独立子进程，
退出即清空 registry，显式关闭零收益；`get_alerter()` 进程级单例、
单槽回填、`AlertRecord.owner` 不序列化、单 bridge 不按 `session_id`
自动派生 owner、`deactivate` 不清 default provider —— 沿用前几轮契约。

### 修复（如实，不夸大）

1. **`hooks/triggers.py`**
   - 新增 **`default_hooks_resolver()`**：模块级**无闭包函数对象**，按
     `current_session_owner()` 分桶查 registry；无 owner（后台线程 /
     contextvar 未跨线程，P3 实测）时回落**最早存活会话**。不持有任何
     agent / ctx / hooks 引用 → R2 消除；单槽 `owner` 退化为纯信息项，
     不再决定派发归属 → R1/R4 消除。
   - 新增 **`close_agent_session(agent)`**：统一、幂等、异常隔离的关闭
     入口，从 `agent.ctx.session_handle` 取句柄。
   - 刻意**不做 GC 终结器兜底**：那会让槽位释放依赖 GC 时机，与前几轮
     「判定不依赖文件系统/缓存时间点」的立场一致；泄漏由各调用方在
     明确作用域出口显式关闭解决。
2. **`app.py`**：`provider=default_hooks_resolver`（共享函数，不再用
   lambda 捕获 agent）。
3. **`cli/cmd_chat.py`**：`_close_agent_session` 改为调用公共入口，
   CLI 侧只保留调用顺序与异常隔离。
4. **5 处显式接线（都在 `finally`，异常路径也释放）**：
   `cli/cmd_chat.py`（CLI 主路径 TUI + REPL）、`hooks/manager.py`
   （Subagent hook）、`tools/subagent_tool.py`、`tools/workflow_tool.py`、
   `stream_json/headless.py`（serve 退出出口）。

### 6 处上轮断言同步（**全部改强，不是放宽**）
4 条 `app.py` 的 `provider=lambda: getattr(` 改为
`provider=default_hooks_resolver` 且要求 `getattr(getattr(agent` 不再
出现；`cmd_chat` 断言改查 `close_agent_session(agent)` 且旧实现已
消失；`test_deactivate_wired_to_cmd_chat_only` **整条重写**为
「5 处接线 + 3 个长驻宿主未接 + 2 个独立子进程不该修 + 3 个伪宿主
0 调用点」，改名 `test_agent_sessions_wired_and_host_scope_corrected`。

### A′ ×3（自己写错自己抓回）
1. **新写 docstring 误伤新写回归（2 次失败）**：`default_hooks_resolver`
   的 docstring 里写了 `weakref.finalize` / `weakref.ref` 字面串，而
   「本轮刻意不做 GC 兜底」的回归检查 `"weakref" not in src` —— 与
   IX 的 `HookTrigger()` 同类误伤。改成不含该词的措辞，产品逻辑零改动。
2. **新测试自身**：`owner_miss_stats()` 返回结构不是
   `{"count": ...}`，断言 `["owner_misses"]["count"]` 直接 `KeyError`
   → 改用 `sum(stats.values()) >= 1`。
3. **替换脚本自身**：嵌套引号导致 `SyntaxError`，首次重跑仍在用旧
   断言（两条失败原样复现）→ 重写脚本后生效。

### 验证（按分批报告，批次间有重叠、不累加）

```
B3 续轮 X + 上五轮 B3（IX/VIII/VII/VI/V/triggers）          226 passed
既有 hooks / config / alert / remote / plugin / bus / ACP /
   workflow / subagent / headless / stream_json 相关           285 passed
宽回归 A（parity / worktree / session / arch / 写边界 /
   两条侧门 / B2 各轮 / chat_handoff）                        218 passed
宽回归 B（arch_security / B2 剩余 / slash）           185 passed / 1 failed
matrix.validate() == []  |  evidence.verify_evidence() == []
verify_doc_numbers.py problems == []
py_compile: 14 个改动 Python 文件全部 OK
```

那 **1 例失败**做了基线对照：`arch/security.py` /
`test_arch_security.py` / `arch/platform.py` / `tools/permissions.py`
与当前 parent 逐字节一致，是策略拒绝 `/usr/bin/python3` 的既有环境
行为，没为变绿动策略。

新增 `tests/test_b3x_agent_sessions.py` 覆盖：纠偏源码扫描（3 个
伪宿主 0 调用点 / 9 个真实调用方 / 5 处接线都在 finally）、R2 共享
provider 无闭包 cell + 真跑 `create_agent` 后 agent 可 GC + 多个
create_agent 注入同一函数对象、resolver 按 contextvar 分桶解析 +
无 owner 回落最早会话 + 死 owner 不回落单槽、R1 关闭 B 后主会话新
建消费者派到 A、R3 70 次短命子 agent **带关闭**不累积（对照：不带
关闭确实打满 64 槽）+ `workflow_tool._execute_subtask` 正常/异常两
路径真跑释放槽位、R4 关闭后 provider 不陈旧、`close_agent_session`
幂等/异常隔离/外来对象安全、不做 GC 兜底、不该修契约、矩阵钉死。

### 如实边界
- **R1 的「子 agent 存活期间同线程 contextvar 指向子会话」是同步
  作用域的正常状态**，本轮不改变它；修复的是**子 agent 结束后不
  残留**（关闭时复位 token）。
- `default_hooks_resolver` 在无 owner 的后台线程回落「最早存活
  会话」，该会话**可能是子 agent**，不谎称总是主会话；P3 的
  contextvar 不跨线程边界仍在。
- **R3 的 64 槽耗尽用直接 `activate_session` 模拟**，不是真跑 70
  个 LLM 子代理；**R2 的 GC 实测在 CPython 引用计数下成立**，其他
  实现不保证。
- **只接了 5 处**：`cli/cmd_acp.py` / `web/server.py` /
  `runtime/acp/bridge.py` 三个长驻宿主仍未接线，不宣称全面覆盖；
  独立子进程那两处判定不该修。
- 行为变更：`app.create_agent` 注入的 provider 从「每会话一个捕获
  agent 的 lambda」变成「共享无闭包函数」，`provider_diagnostics()`
  的 `owner` 语义从「决定派发归属」降为纯信息项；子 agent 调用方
  现在会在 `finally` 注销会话槽。
- `os_sandbox` 仍 gap、`deny_network_by_default` 仍 `false` 未翻、
  `credential_masking` 仍 partial；A 线 10 pending、分叉改动未合并、
  第三方自适应红队未做；不是真机多平台验证。
- 标语引擎 / 净化层 / `mapping.py` / `tui.py` / `runtime_slogans.py`
  逐字节未改。


---

## A 线续轮 XI：最后 10 个 pending 清零 + 深度真实性判据（B 线只读基线）

> **自足标题，不新增数字章节编号。** 用户原话：「确保深度的真实复现，
> 而非仅仅广度；开始做到百分百，同时融入 Codex 有但是 Tuan 还没有的」。
> 本轮把「对齐」从**一行 note** 重新定义成**一个通过的运行时探针**。

### 矩阵真实变化（实测）

| 线 | 上轮 | 本轮 |
|---|---|---|
| A 线 pending | 10 | **0** |
| A 线 aligned / localized / na | 35 / 57 / 63 | **45 / 57 / 63** |
| A 线宽口径 coverage | 93.9% | **100.0%** |
| A 线严格对齐 / 逐值 | 55.8% / 21.2% | **61.8% / 27.3%** |
| A 线 `all_modules_settled` | False | **True** |
| A 线 `fully_identical` | False | **仍 False** |
| A 线深度探针 | — | **10 / 102（9.8%）** |
| B 线 aligned / partial / gap | 46 / 9 / 26 | **46 / 9 / 26（一个没动）** |
| B 线 `fully_superior` | False | **仍 False** |

**`fully_identical` 为什么没变 true**：判据加严为
``pending == 0 and depth_audit()["ok"]``。旧口径只看状态表，
一条 note 指向某个 .py 文件只证明「有代码」，证明不了「跑起来行为
真的对」。现在 102 个 aligned/localized 里只有本轮 10 个有模块级
运行时探针，``depth_missing`` 如实列出 92 项 —— **不靠改状态定义
凑数**。这正是「深度而非广度」的代价，不是倒退。

### A 线：10 个真实实现（零 Rust 源码复制）

新建 ``tuan_cli/tui/codexkit/``，5 个文件、4 个实现模块 + 1 个
纯 stdlib 自检 harness。**每个模块都有 ``probe()``**：真调代码、
逐项断言、返回结构化证据，注册到 ``tui/parity/depth.py`` 的
``PROBE_REGISTRY``。合计 **127 条断言 + 6 条 harness 自检**。

| 上游模块 | 实现 | 关键契约（probe 数） |
|---|---|---|
| `auto_review_denials` | `approval_history.py::DenialLedger` | 忽略即拒绝 / 去重 / owner 分桶 / 有界 ring（13） |
| `insert_history` | `approval_history.py::HistoryBuffer` | id 单调 / 越界拒绝 / 幂等 / backtrack 失效 / 几何同源（12） |
| `rendered_selection` | `approval_history.py::SelectionGeometry` | CJK 列宽 / 组合标记 / `hit_matches_render()`（12） |
| `local_settings` | `session_config.py::LocalSettings` | 三层优先级 / 严格类型 / 不落盘（17） |
| `clock_format` | `session_config.py::ClockFormat` | 注入时钟 / 脏值回落 / 单调钳制 / 显式时区（16） |
| `external_agent_config_migration` | `session_config.py::migrate_external_agent_config` | 单次模板替换 / 未知键留痕 / 类型守卫（12） |
| `streaming` | `stream_exec.py::StreamAssembler` | seq 单调 / done 拒绝 / ESC 序列剥离 / render 纯读 / 上限（13） |
| `async_question_reply` | `stream_exec.py::AsyncQuestionReply` | 登记 / 超时 / 取消 / 重复 / 不覆盖 / **绝不代答**（17） |
| `exec_command` | `stream_exec.py::ExecCommand` | argv 强制 / 元字符与间接执行器拒绝 / 无 shell / 输出与超时上限（15） |
| `tests` | `selftest.py::run_all_probes` | 纯 stdlib harness / 坏探针不被吞（6） |

延续前几轮**实测过的真实缺陷**（不是凭空设计）：链式 ``replace``
二次替换（第 13 轮 ``model_migration``）、hit/render 两套几何
（``sidebar_tab_strip``）、渲染循环偷偷记活性（D4）、模型自问自答
（B3 Elicitation）、``bool("false")`` / NaN 冒充数值、``shell=True``
拼接、会话设置污染全局配置、自动审查决策被静默丢弃。

### 深度制度（两处硬约束）

1. ``tui/parity/depth.py``：``run_probe()`` 真调 + 计时 + 异常即失败；
   ``depth_audit()`` 对全部 102 项逐项核销，返回
   ``claimed / verified / ok / missing``；**不缓存**（判定不依赖缓存
   时间点）、**不自动降级状态**（两张独立证据表）。
   ``matrix.validate()`` 现在会对本轮 10 项逐一执行探针，任一失败
   都算矩阵自检不通过。
2. ``parity_claude/depth.py``（B 线，**只读**）：实测 65 个非 gap
   模块里 **65/65 有 evidence 路径、65/65 有 note，但模块级运行时
   探针 0 个**。六维 ``superiority.probe_all()`` 是**聚合维度**探针
   （一个探针覆盖十几个模块），它绿不等于模块级验证。
   ``gap_queue()`` 给出 26 个 gap 的逐项证据与按 wave 分组
   ``B2:1 / B3:2 / B4:1 / B5:1 / B6:4 / B7:8 / B8:1 / B9:3 / B10:5``。
   **本轮不改 B 线任何判据 / 状态**，``catalog.py`` 零改动。

### 一处真实联动缺陷（不是环境假阴性）

加严 ``fully_identical`` 后，B 线六维探针的
``_probe_verifiable_parity()`` 硬编码假设「``pending == 0`` ⇒
``fully_identical is True``」，直接判「指标自相矛盾」并失败，连带
``all_probes_ok=False``、CLI 输出 ``UNVERIFIED``、5 条既有回归红。
已改成逐项核销**双口径自洽**（``all_modules_settled`` 与 pending、
``fully_identical == settled and depth_strict_ok``、深度计数与
``depth_missing`` 对账）—— **改强不是放宽**。CLI 里两处硬编码
「还剩 10 个 pending」改成动态读 ``matrix.summary()``。

另同步 **9 条既有断言**到新基线（``pending 10→0``、
``aligned 35→45``、``coverage 93.9→100.0``、``len(gaps) 10→0``），
每条都**额外加** ``depth_verified == 10`` 等深度断言，不是单纯改数字。

### A′（本轮自己写错自己抓回，全部实测复现）

1. ``HistoryBuffer(base_id=7)`` 把 base_id 当 cell_id 单调下界，
   连 ``append(id=1)`` 都被拒 → base_id 只管 backtrack 失效判定。
2. 流式净化只删 ESC 字节，留下 ``[31m`` 残片 → 先整段剥 CSI/OSC。
3. 两条探针断言写反（净化分片应返回 True、拼接结果口径）。
4. ``sh -c x`` 不含 shell 元字符却等于间接启用解释器 → 加执行器
   黑名单（``sh/bash/python3 -c`` 等）。
5. ``probe_clock_format`` 重复自增 checks → 计数失真。
6. harness 的「不得依赖测试框架」源码扫描**扫到自己** 3 次
   （docstring / 注释 / 扫描代码里的字面串）→ 改措辞 + 拆分字面串。
7. ``depth_audit()`` 不 import 实现包导致 10 个探针一个没注册、
   ``depth_verified`` 假报 0 → 加幂等 ``_ensure_registry()``。
8. B 线 ``gap_queue()`` 初版扫全仓 1300+ 个 .py 耗时 **18.8s**
   → 改为只核销每个模块自己声明的 evidence 文件（**352ms**）。

### 验证（分批报告，批次间有重叠、不累加）

```
新回归 + B 线 parity 全量                        85 passed
宽回归 A（codexkit / claude parity / tui parity / cli parity /
   config/core/input layer / headless / fullscreen / overlay / layout） 555 passed
宽回归 B（arch_security / B2 各轮 / hooks / worktree / slash）  286 passed / 1 failed
纯 stdlib 独立验证 xi_verify.py                  30 / 30 全绿
matrix.validate() / evidence.verify_evidence() / verify_doc_numbers.py  全干净
py_compile 14 个改动文件全过
```

那 **1 例失败**做了 parent-blob 基线对照：``arch/security.py`` /
``test_arch_security.py`` / ``arch/platform.py`` /
``tools/permissions.py`` 与 parent ``814c3231`` 逐字节一致，是策略
拒绝 ``/usr/bin/python3`` 的既有环境行为，没为变绿动策略。

### 如实边界 / 下一轮

- **A 线 92 个既有 aligned/localized 仍无模块级探针**，
  ``fully_identical=False``；``depth_missing`` 是下一轮工作队列。
- **B 线 26 个 gap 一个未消**：本轮只立深度基线，没堆功能。
  下一轮起按 ``gap_queue()`` 逐域真实补齐，**每消一个必须同时注册
  一个模块级探针**（``MODULE_PROBES``），优先 B3 两个 hooks gap
  （前面十几轮引擎已挖透，剩余硬理由明确）。
- ``os_sandbox`` 仍 gap、``deny_network_by_default`` 仍 ``false``
  未翻、``credential_masking`` 仍 partial；``b_waves_done=["B1"]``、
  ``external_adaptive_red_team=False``；A 线分叉改动未合并、第三方
  自适应红队未做；不是真机多平台验证。
- ``codexkit`` **不接 TUI 主循环**、不替换任何既有运行时对象，
  只提供可验证的对齐实现与探针；纯 Python，零 Rust 源码复制。
- 标语引擎 / 净化层 / ``mapping.py`` / ``tui.py`` /
  ``runtime_slogans.py`` 本轮逐字节未改。


---

## B3 续轮 XII：hooks exit-code-2 深度真实性（状态一个没动）

> **自足标题，不新增数字章节编号。** 用户约束：「确保深度的真实复现，
> 而非仅仅广度；开始做到百分百」。本轮**没有把任何 gap 数字往下刷**：
> B 线仍是 ``aligned 46 / partial 9 / gap 26``、
> ``fully_superior=false``、``b_waves_done=["B1"]``。原因是先实测复现
> 出**一个真实安全洞**和六个协议/旁路缺口，把它们做深做透，比把
> 26 改成 25 更有价值。

### 最值钱的发现：失败闭合被一行 stdout JSON 打穿（H1）

实测（真起子进程）：

```
hook: exit 2
  stderr = "BLOCKED: 禁止写 /etc"
  stdout = '{"hookSpecificOutput":{"permissionDecision":"allow"}}'
Tuan 旧行为: block=False, reason="", failure_kind=""
CC 官方行为: 阻断工具调用，stderr 作为阻断原因反馈给模型，
             stdout 的 allow 不能覆盖 exit 2
```

旧 ``_exec_command`` 把 ``rc`` / ``stderr`` 埋进 ``failure.detail``
字符串，调用方拿不到结构化值；只要 stdout 非空就跳过失败判定，直接
把 ``permissionDecision:allow`` 当放行。**这不是文档口径问题，是
真实的安全洞**：stderr 里的阻断原因也彻底丢失。

### 修复（全部先复现再修）

| # | 缺陷（实测复现） | 处置 |
|---|---|---|
| H1 | exit 2 + JSON allow 绕过 fail-closed | ``hooks/exit_semantics.py`` 33 事件逐事件真值表 + ``classify()`` 结构化裁决；``_exec_command`` 记 ``HookExit(rc,stderr,stdout)``；``run_pre``/``run_decision`` 加统一闸门 |
| H2 | CC 官方 ``hookSpecificOutput.decision.behavior="deny"`` 旧版完全不识别、静默放行 | ``_parse_decision`` 补官方 PermissionRequest 格式 |
| H3 | 官方 ``allow + updatedInput`` 不识别；决策类一律忽略 args | 按官方语义解析并暴露 ``decision.args``；allow 缺 updatedInput 时如实不生效 |
| H4 | ``WorktreeCreate`` rc=1 + JSON allow 被放行 | CC 语义：任何非零 rc 都失败，JSON 说了不算 |
| H5 | 官方事件面 33 项、旧表 15；**18 个官方事件配置全部 0 加载** | 事件表 15 → 33，以真值表为单一真值源派生 ``OFFICIAL_EXTRA_EVENTS`` |
| H6 | ``ToolPipeline`` 生产构造方全仓 **0 个**（只有测试构造） | ``core/tool_executor.py::ToolExecutor.__init__`` 真实构造并挂 ``self.pipeline`` + ``_resolve_tool_schema()`` |
| H7 | ``runtime/tools/bridge.py`` 真实生产旁路直接 ``handler(ctx,**args)``，未知键抛 TypeError、缺 required / 类型不符无人校验 | 接 ``validate_updated_input`` 同一份真值，4 类 case 真跑 asyncio 验证 |

### exit-code-2 逐事件真值表（官方口径）

联网核对官方 Hooks 参考 + 逐事件表交叉核对后做成常量：

- **exit 2 阻断**：PreToolUse / UserPromptSubmit / UserPromptExpansion /
  Stop / SubagentStop / TeammateIdle / TaskCreated / TaskCompleted /
  ConfigChange / PostToolBatch / PreCompact / Elicitation /
  ElicitationResult / PreModelSwitch / WorktreeCreate / WorktreeRemove
- **exit 2 不生效**：``PermissionRequest``（权限流照旧、stderr 丢弃，
  只有 JSON decision 能 deny）
- **exit code 完全忽略**：``PermissionDenied`` / ``StopFailure`` /
  ``InstructionsLoaded``
- **任何非零都失败**：``WorktreeCreate`` / ``WorktreeRemove``
- **动作已发生、stderr 只作反馈**：PostToolUse / PostToolUseFailure /
  PostModelSwitch / SessionEnd / Notification / CwdChanged / FileChanged /
  DirectoryAdded / PostCompact / MessageDisplay
- **stderr 去向**（claude / user / discarded / debug_log / ignored）逐事件标注；
  ``NO_MATCHER_EVENTS`` 10 项可反查。

**刻意保留的 Tuan 差异**：``on_failure=block`` 出厂默认比 CC 更严
（CC 里 exit 1 是非阻断错误），这是 B1 既有安全立场，**不因为对标就
放宽**；``compare_with_tuan_policy()`` 把差异逐项列出来。
CC 不同页面对「exit 2 时 stdout JSON 是否被读取」措辞有差异，锁死的
是所有来源一致的硬规则：**allow 不能覆盖 exit 2**。

### 两个模块级运行时探针（B 线深度从 0 → gap 级 2）

``parity_claude/module_probes.py`` 给两条 B3 gap 各注册一个**真调代码**
的探针到 ``depth.MODULE_PROBES``：

- ``hook_events_extended``：30 条断言（真起 exit-2 子进程、真调
  run_pre/run_decision、真解析 CC 官方协议、逐事件语义核销）
- ``hook_updated_input_validation``：18 条断言（真调
  validate_updated_input、真跑 bridge asyncio、真构造 ToolExecutor
  拿生产 pipeline + schema_resolver、4 处源码证据）

新增独立入口 ``depth.gap_probe_audit()``：``registered 2 / verified 2 /
ok=True``。**刻意不把 gap 探针混进 ``module_depth.probe_verified``** ——
后者统计的是「65 个非 gap 模块里有多少被逐模块验证过」，仍如实为
**0 / 65（0.0%）**，两张证据表分开。

### 状态仍 GAP 的剩余硬理由（收窄但未消除）

- ``hook_events_extended``：新增 18 个事件**只有通知通道、无生产触发点、
  无 JSON decision 裁决**；Elicitation 语义刻意不等价（Tuan 不允许
  模型自问自答，CC 允许程序化代答）；CC 事件面持续演进。
- ``hook_updated_input_validation``：``cmd_hooks`` 取 schema 仍依赖
  kernel 暴露 ``tool_registry``，取不到回落保守子集并标
  ``enforced=False``；``ToolPipeline`` 是**可选执行通道**、主链路仍是
  ``execute_batch``，不假称所有调用改走 pipeline；CC 的 updatedInput
  覆盖也含 HTTP/prompt/agent hook 类型，本地只覆盖 command 类型。

catalog 两条 note 已按实测收窄，**status 字段逐字节未动**，不靠改
状态定义凑数。下一轮按 ``gap_queue()`` 逐域消 gap，每消一个必须
同时注册模块级探针。

### A′ 自查抓回

1. ``module_probes.py`` 初版写了一个不存在的 ``exit_semantics_bridge``
   哨兵 import → 模块刚加载就 ImportError、两个探针一个注册不上。
2. ``classify()`` 初版对 rc=1 也把 JSON 全忽略 → 既有回归
   ``test_nonzero_rc_with_valid_decision_still_honors_decision`` 变红
   （``reason`` 从 ``"rc1"`` 变成 Tuan 闭合文案）。CC 在**非 2** 的
   非零退出码下仍读取有效 JSON decision；新增 ``json_may_override``
   字段，只有 exit 2 / any_nonzero_fails 才锁死 JSON 覆盖。
3. 事件表断言从 15 同步到 33 时 import 路径写错（从 ``hooks`` 包取
   未导出的名字）→ 改从 ``hooks.manager`` 取。
4. 上一轮历史重写后本地残留的审计文件被列成「新增」差点推回 main
   —— 本轮推送前再次确认它不在清单（见续轮 XI 报告）。

### 验证（分批报告，批次间有重叠，不累加）

```
新回归 + B3/hooks + claude_parity + codexkit + headless     171 passed
宽回归 A（+ tui parity / cli parity / config / core / input /
  fullscreen）                                            552 passed
宽回归 B（B2 各轮 / worktree / slash / arch_security）      232 passed / 1 failed
ToolExecutor / bridge / arch_execution 相关                    67 passed
纯 stdlib 独立验证 xi_verify.py                              32 / 32 全绿
matrix.validate() / evidence.verify_evidence() / exit_semantics.validate()
verify_doc_numbers.py / 10 文件 py_compile                    全干净
```

那 1 例失败做了 parent-blob 基线对照：``arch/security.py`` /
``test_arch_security.py`` / ``arch/platform.py`` /
``tools/permissions.py`` 与 parent ``0fa1653c`` 逐字节一致，是策略
拒绝 ``/usr/bin/python3`` 的既有环境行为，没为变绿动策略。

### 如实边界

- B 线 26 个 gap 一个未消，``os_sandbox`` 仍 gap、
  ``deny_network_by_default`` 仍 false 未翻、``credential_masking``
  仍 partial；A 线 92 个既有 aligned/localized 仍无模块级探针、
  ``fully_identical=False``；第三方自适应红队未做，不是真机多平台验证。
- ``exit_semantics`` 事件面 33 项来自官方 Hooks 参考 + 逐事件表交叉
  核对，**不宣称与某一 CC 发行版逐值相等**。
- 标语引擎 / 净化层 / ``mapping.py`` / ``tui.py`` /
  ``runtime_slogans.py`` / catalog 状态字段逐字节未改。


## B3 续轮 XIII｜新增官方 hooks 事件的真实生产触发点与 decision 通道

基线 parent ``7954c4df``。本轮沿用户约束「**确保深度的真实复现，而非仅仅广度；
开始做到百分百，同时融入 Codex 有但是 Tuan 还没有的**」继续，一点广度没扩：
不新增 CLI 子命令、不新增模块域、矩阵状态字段一个不动。

### 先实测复现，再决定修什么

| 编号 | 实测现象 | 判定 |
|---|---|---|
| D1 | 18 个新增事件**全部**落在 ``_NOTIFY_EVENTS``；按官方真值表 ConfigChange / TaskCreated / TaskCompleted / PreCompact / PreModelSwitch / Stop / PostToolBatch 等是**可阻断 / 支持 JSON decision** 的事件，``run_notify`` 把 hook stdout 裁决整个吞掉 | 真缺陷（B3 主链路 R2 的坑在新增事件上重现） |
| D2 | 18 条 hook 配置 100% 加载，真跑压缩 / chdir / git worktree / todo / 工具失败 / 权限拒绝 / 批量 / 模型切换 / 指令读取 / setup，触发 **0 次**；全仓生产侧源码扫描几乎全 0 命中 | 真缺陷 |
| D3 | 上一轮 note「CC 的 updatedInput 覆盖含 HTTP/prompt/agent 类型，本地只覆盖 command」实测**为错误口径**：``_exec()`` 对四种类型统一返回 ``out``，``validate_updated_input`` 调用点前后 900 字符无 ``hook_type`` 分支 | 口径错误，纠正并锁回归 |
| D4 | 13 个真实生命周期点在源码里存在，但没有任何一个调用派发 | 真缺陷 |

### 修复

- ``hooks/exit_semantics.py`` 新增 **DECISION_CAPABLE_EVENTS(20) / NOTIFY_ONLY_EVENTS(13) /
  NO_LOCAL_LIFECYCLE(5) / LOCAL_CAPABLE_EVENTS(27)** 四张显式真值表；``validate()``
  加硬规则：可阻断事件必须落决策类、exit 被忽略的事件（除 PermissionDenied）不得进决策类、
  决策/通知分类必须覆盖全部 33 事件。
- ``hooks/manager.py`` 新增 ``run_event()`` **通用事件裁决出口**（既有 ``run_decision``
  硬编码 4 个事件，本轮零改动），决策类事件走它才不吞 stdout；
  ``HookDecision.retry`` + ``hookSpecificOutput.retry`` 官方协议真读出。
- 新增 ``hooks/lifecycle.py``：``emit()`` 按真值表自动路由；``blocked`` 由
  ``semantics_for(event).blocks_on_exit2`` 区分「可预防动作（真阻断）」与
  「动作已发生、只作反馈（不阻断但保留 reason）」；thread-local 重入守卫；
  全路径异常隔离；``coverage()`` 把 **wired 27（本轮 13 + 既有 14）/
  no_local_lifecycle 5 / not_wired 1（StopFailure）** 三张表分开核销，
  绝不把「本地有对应概念」虚报成「已接生产触发点」。
- **13 个真实生产触发点**：PreCompact/PostCompact → ``TieredContext._maybe_compact``
  真压缩前后；CwdChanged → ``/cd`` 真 chdir 后；PostToolBatch →
  ``ToolExecutor.execute_batch`` 一批解决后；PostToolUseFailure / PermissionDenied
  → ``tools/base.py`` 真失败 / 真拒绝结果路径；Pre/PostModelSwitch →
  ``KernelAcpBridge.set_model``；InstructionsLoaded →
  ``_read_instruction_capped`` 真读到内容后（payload **不带正文**，脱敏）；
  Setup → ``cmd_setup`` 向导入口；WorktreeRemove → ``WorktreeLayer.remove``
  真 git 移除前；TaskCreated/TaskCompleted → todo 真新建 / 真转完成。
- **4 个可预防动作真阻断**（不是只返回标记）：PreCompact block → ``compactions``
  不增、hot 如实超预算；WorktreeRemove block → 不执行 ``git worktree remove``；
  PreModelSwitch block → ``_model`` 不变；TaskCreated block → 回滚不写 ``ctx.todos``。
- 既有 7 个扩展事件与 CORE 生命周期路由**零改动**（ConfigChange 仍是 B3 V
  的「写盘成功后通知」契约），语义差异在 ``lifecycle.SEMANTIC_DIFFERENCES``
  显式登记，包括「PreCompact 双重触发」「PostToolBatch 不擅自终止回合」
  「InstructionsLoaded 不带正文」等。

### 矩阵一个状态没动

``ahead 10 / aligned 46 / partial 9 / gap 26 / not_applicable 8``、
``fully_superior=false``、``b_waves_done=["B1"]``。catalog 两条 B3 note 补了 XIII
实测段与错误口径纠正，**status 字段逐字节未改**。中途曾把两条翻成 partial
（26→24），但全仓 20+ 个历史轮次回归把 26/9 硬编码为「当时矩阵没动」的证据，
为本轮数字去改它们等于篡改历史；且剩余硬理由真实存在，**刻意回退**并在 note
里写明「为什么不翻状态」。

**深度确实推进**：``gap_probe_audit()`` 从 2 个探针变成 **3 个**
（30 + 18 + 27 条断言，3/3 全绿）；第三个 ``hook_lifecycle_triggers`` 真起
hook 子进程、真跑 git init/worktree add/remove、真 chdir、真压缩、真工具失败
与权限拒绝。但 ``module_depth.probe_verified`` 仍如实为 **0/65**，两张证据表
分开，不混进覆盖率。

### A′ 自查抓回（全部有可执行证据）

1. ``cmd_cd`` 插入的 payload 引用只在相对路径分支定义的 ``base``，传绝对路径
   时 ``NameError`` 被 ``except`` 吞掉 → CwdChanged 静默不派发。**端到端真跑**
   抓回，源码扫描看不出；改成函数开头记录 ``previous_cwd``。
2. ``cmd_setup`` 派发点放在 ``build_kernel()`` / ``input()`` 之后，重依赖链
   一阻塞就静默不触发 → 移到函数最开头。
3. ``PostModelSwitch`` 同时出现在 ``NO_LOCAL_LIFECYCLE`` 与接线清单，
   ``validate()`` 立刻报「有交集 / 三表不相加」→ 移到语义差异表。
4. ``lifecycle.py`` 三表分类重构残留旧 ``WIRED_EVENTS`` 块 →
   ``IndentationError``，删净。
5. 新写测试的源码扫描起点写错（``_exec`` 在 ``run_pre`` 之后）→ 修正。
6. 新模块级探针直接 import CLI 模块，连带拉起 ``rich``，**破坏了
   ``xi_verify.py`` 的纯 stdlib 干净环境约束**（本轮自引入）→ 改为
   「能 import 就真跑；import 不了就把 CwdChanged/Setup 降级为源码级核销」，
   ``cli_runtime`` / ``runtime_events`` / ``source_only_events`` 分表如实上报，
   绝不把降级冒充真跑。两种环境各跑一次均 34/34。
7. 探针用了未定义的 ``root`` → 补 ``Path(__file__).resolve().parents[2]``。
8. 宽回归暴露 **3 个 XII 遗留的过时断言**（``len(HOOK_EVENTS)==15``、
   ``ToolPipeline(`` 生产命中为空）。**parent-blob 实证对照**：把
   ``manager.py`` / ``tool_executor.py`` / ``module_probes.py`` 还原到
   ``7954c4df`` 后复跑同样失败，与本轮无关。同步到官方真值并**改强**
   （逐值等于 ``OFFICIAL_EVENTS``、历史 15 是子集、决策分类自洽、
   生产 ToolPipeline 带 ``schema_resolver``、两条旁路有 schema 证据）。

### 验证（分批报告，批次间有重叠，不累加）

```
核心回归（XIII + XII + B3/hooks + parity + doc_numbers + cli/tui）  343 passed
宽回归 B（B2 各轮 + B3 各续轮，改强同步后重跑）                    522 passed
核心回归批次（XIII + XII + hooks + parity + codexkit + tui/cli）     284 passed
纯 stdlib xi_verify.py（无 rich 干净环境 / 有 rich 环境各一次）       34 / 34 全绿
gap_probe_audit() 3/3（30 + 18 + 27 条断言）
verify_doc_numbers.py / matrix.validate() / evidence.verify_evidence()
exit_semantics.validate() / lifecycle.validate() / 20 文件 py_compile   全干净
```

### 如实边界

- **5 个事件本地无对应生命周期**（FileChanged / MessageDisplay /
  SubagentStart / TeammateIdle / UserPromptExpansion），**不造空转触发点** ——
  那正是「转圈标语装忙」要反对的东西；``StopFailure`` 本地有能力但本轮未接，
  ``coverage().not_wired`` 如实为 1。
- CC 事件面持续演进，不宣称与某一发行版逐值相等；ConfigChange 仍是
  post-hoc 通知、Elicitation 语义刻意不等价（Tuan 不许模型自问自答）。
- 干净环境下 CwdChanged/Setup 只做源码级核销，端到端真跑由安装 rich 的
  pytest 批次覆盖，分表可查。
- B 线 26 个 gap 一个未消，``os_sandbox`` 仍 gap、
  ``deny_network_by_default`` 仍 false 未翻、``credential_masking`` 仍 partial；
  A 线 92 个既有 aligned/localized 仍无模块级探针、``fully_identical=False``；
  第三方自适应红队未做，不是真机多平台验证。
- 行为变更：13 个事件现在会派发已配置的 hook、4 个动作可被真阻断、
  ``PreCompact`` 在 context 层有第二个派发点（与 agent 层既有通知并存）。
