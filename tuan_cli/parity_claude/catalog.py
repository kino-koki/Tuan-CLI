"""Claude Code **v2.1.319**（2026-11-06）全模块能力目录。

这是「超 Claude Code 最新版本」计划的**上游基线**，只记录公开可核验的
能力事实，不含任何 Anthropic 专有源码、混淆产物或商标资产。

版本口径（如实）：
  - GitHub tag ``v2.1.319``，Published ``2026-11-06T17:04:01Z``，
    非 prerelease；官方 release notes 明确列出 MCP tasks 后台化、
    ``permissions.denyInsteadOfPrompting``、auto mode 不再回退内置
    分类器，以及 worktree 创建沙箱逃逸 / Bash 权限绕过修复。
  - 官方 changelog 页面按**日期**组织（顶部可见 2026-11-04，对应
    v2.1.318），不逐条写版本号；版本号取自 GitHub release 归档与
    公开 release tracker。
  - 本文件锁定 **v2.1.319** 作为对比基线，日期与来源逐条列在
    ``SOURCES``，避免把"某功能存在于某个版本"写成模糊的"最新版有"。

模块状态（五态，定义即约束）：
  - ``ahead``         Tuan 在**可验证维度**上领先，必须给 ``ahead_reason``
                      与存在的证据路径；
  - ``aligned``       能力对等且本仓库有实现 + 测试/证据指向；
  - ``partial``       有实现但不完整，必须写清缺什么；
  - ``gap``           缺失，必须分配到某个 ``wave``（B2..B10）；
  - ``not_applicable`` Anthropic 云 / 订阅 / 闭源专属，本地离线 CLI
                      不需要；**如实标不适用，不包装成领先**。

许可与合规：Claude Code 是 Anthropic 的专有产品（Commercial Terms
of Service）。本目录仅做能力对标与行为契约描述，**未复制任何源码**，
不使用其商标/品牌资产，"超"仅指可验证的能力与安全姿态对比，
不代表 affiliation 或 endorsement。详见 ``NOTICE`` 第 14 条。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Tuple

CC_PRODUCT = "Claude Code"
CC_VERSION = "2.1.319"
CC_DATE = "2026-11-06"
CC_TAG_TIMESTAMP = "2026-11-06T17:04:01Z"

SOURCES: Tuple[Dict[str, str], ...] = (
    {"kind": "official", "title": "GitHub release anthropics/claude-code v2.1.319",
     "url": "https://github.com/anthropics/claude-code/releases/tag/v2.1.319",
     "note": "版本号、发布时间、MCP tasks / denyInsteadOfPrompting / auto mode / 沙箱逃逸修复"},
    {"kind": "official", "title": "Claude Code changelog",
     "url": "https://code.claude.com/docs/en/changelog",
     "note": "按日期组织的官方变更记录（顶部 2026-11-04 对应 v2.1.318）"},
    {"kind": "official", "title": "扩展 Claude Code（功能分层）",
     "url": "https://code.claude.com/docs/en/features-overview",
     "note": "CLAUDE.md / Skills / 代码智能 / MCP / Subagent / Agent Teams / Hooks / Plugins"},
    {"kind": "official", "title": "Agent SDK overview",
     "url": "https://platform.claude.com/docs/en/agent-sdk/overview",
     "note": "内置工具、Hooks、Subagents、MCP、Permissions、Sessions、Skills、Plugins"},
    {"kind": "official", "title": "功能可用性",
     "url": "https://code.claude.com/docs/en/feature-availability",
     "note": "订阅/云专属 vs 所有提供商可用，用于 not_applicable 判定"},
    {"kind": "third_party", "title": "Claude Code Feature Catalog",
     "url": "https://github.com/anthropics/claude-code",
     "note": "四型 hook、Agent Teams、Task List、worktree、sandbox、MCP OAuth/tool search/elicitation、LSP、self-hosted runner"},
    {"kind": "third_party", "title": "Release tracker / 版本归档",
     "url": "https://releases.sh/anthropic/claude-code",
     "note": "v2.1.319 (11/6)、v2.1.318 (11/4)、v2.1.314 blockWritesOutsideWorkingDirectories 默认关"},
    {"kind": "third_party", "title": "What's New in Claude Code（hooks onFailure）",
     "url": "https://codewithclaude.net/whats-new",
     "note": "onFailure:\"block\" 需显式配置；破损/超时的 hook 旧行为是静默 fail-open"},
)

DOMAINS: Tuple[str, ...] = (
    "security_permissions",   # 安全与权限
    "safety_audit",           # 安全扫描与审计
    "hooks",                  # 生命周期钩子
    "skills_memory",          # 技能与记忆
    "subagents_teams",        # 子代理与团队
    "mcp",                    # MCP 全栈
    "plugins_marketplace",    # 插件与市场
    "modes_context",          # 模式与上下文
    "session_headless",       # 会话 / 无头 / SDK
    "tui_interaction",        # TUI 与交互
    "git_background",         # Git / 后台任务
    "code_intelligence",      # 代码智能
    "cloud_remote",           # 云 / 远程 / 集成
    "observability_models",   # 可观测 / 模型 / 成本
)

STATUS_AHEAD = "ahead"
STATUS_ALIGNED = "aligned"
STATUS_PARTIAL = "partial"
STATUS_GAP = "gap"
STATUS_NA = "not_applicable"
STATUSES = (STATUS_AHEAD, STATUS_ALIGNED, STATUS_PARTIAL, STATUS_GAP, STATUS_NA)

# 「超」的六个可验证维度。每个 ahead 模块必须归属其中一个维度，
# 且该维度至少有一个运行时探针（superiority.py）跑通才算数。
SUPERIORITY_DIMENSIONS: Tuple[str, ...] = (
    "fail_closed_default",     # 故障闭合是默认，不是可选项
    "audit_replay",            # 防篡改审计与跨会话回放
    "config_correctness",      # 配置错误被拒绝而非静默生效
    "least_authority",         # 最小权限域与默认不信任
    "local_offline_i18n",      # 完全本地 / 零遥测 / 10 语言
    "verifiable_parity",       # 可机器核验的对齐矩阵本身
)


@dataclass(frozen=True)
class Module:
    name: str
    domain: str
    cc_ref: str
    status: str
    evidence: Tuple[str, ...]
    note: str
    wave: str = ""
    ahead_reason: str = ""
    ahead_dim: str = ""


def M(name, domain, cc_ref, status, evidence, note,
      wave="", ahead_reason="", ahead_dim="") -> Module:
    ev = tuple(e for e in evidence if e)
    return Module(name, domain, cc_ref, status, ev, note,
                  wave, ahead_reason, ahead_dim)


# ---------------------------------------------------------------- 1 安全与权限
D1 = (
    M("os_sandbox", "security_permissions", "Sandboxing /sandbox; v2.1.319 修复 worktree 创建沙箱逃逸",
      STATUS_GAP, ("tuan_cli/sandbox/backends.py", "tuan_cli/sandbox/manager.py",
                   "tuan_cli/sandbox/egress.py"),
      "仍为最大落后项：CC 有 OS 级强制沙箱，Tuan 的 --isolation 是可选 engine/process 级，L3 仅在 verdict.isolate 时介入。B2 补上了 local 后端禁网裁决的 fail-closed 拒绝(不再裸跑)，但**没有**把 OS 级隔离变成默认执行边界；强后端仍需显式可用",
      "B2"),
    M("network_default_deny", "security_permissions", "sandbox.network.strictAllowlist (2026-07-25)",
      STATUS_PARTIAL, ("tuan_cli/config/defaults.py", "tuan_cli/sandbox/filters.py",
                       "tuan_cli/sandbox/egress.py", "tests/test_b2_boundaries.py"),
      "B2 实测并修复：_execute_backend 算出 block_net 却未传给 local 分支，禁网裁决在唯一没有 OS 级出网隔离能力的后端上静默失效；现在 local+禁网 fail-closed 拒绝、强后端仍走自身边界。**仍缺**：deny_network_by_default 出厂值仍是 false（未擅自翻），且缺 CC 逐命令 allowed_domains 的强绑定",
      "B2"),
    M("network_strict_allowlist", "security_permissions", "sandbox.network.strictAllowlist; per-command allowed_domains (v2.1.271)",
      STATUS_ALIGNED, ("tuan_cli/sandbox/egress_allowlist.py", "tuan_cli/sandbox/egress_proxy.py",
                       "tuan_cli/sandbox/egress_plan.py",
                       "tuan_cli/core/sandbox_provider.py", "tuan_cli/sandbox/manager.py",
                       "tests/test_b2_egress_strict.py", "tests/test_b2s_egress_uniform.py",
                       "tests/test_b2su_refusal_routing.py"),
      "B2 收尾落地逐命令 allowed_domains → verdict.extra → SandboxProfile.allowed_domains → **本地回环出网代理**在 CONNECT/明文 HTTP 主机层强绑定(声明外 403)。**本轮纠偏**：上一轮标 aligned 说得太满 —— 实测那套只接在 _execute_backend 的 local 分支；landlock/docker/seatbelt 只把 allowed_domains 当元数据传进后端(整个 provider 文件里该字段只出现 1 次、无任何后端消费)，jobobject/run_syscall_sandboxed 连 env 参数都没有、子进程继承父进程全部真实密钥。安全等级更高的路径反而没有刚补的防护。本轮统一 plan_egress 单一出口：所有分支共用 EgressGuard 脱敏/sentinel env 并写 last_egress；真正逐命令声明(source=tool_args) + 强后端因无域名级过滤且回环代理在 netns/seatbelt 下不可达，**默认 fail-closed 拒绝**（可配 strict_claim_strong_backend=metadata_only 显式降级，schema/harden status 报安全降级）；全局白名单回落(source=global_policy)沿用既有文本层语义，不破坏既有部署。状态仍 aligned 是因为能力已落地且缺口被如实拒绝而非静默放行，但边界比上一轮文档写的窄得多。**§15 再纠偏**：plan 的「拒绝」本身也没接好 —— tools/shell.py 路由只用 verdict.enforced/backend_available 判断是否采纳结果，拒绝结果天然 enforced=False，在 enforce_required=false 的部署上返回 None、把被拒命令在真实工作区裸跑一遍；copy_diff_apply 分支还会把合规拒绝伪装成用户主动拒绝并宣称已隔离执行。已用 SandboxExecResult.terminal_refusal 解耦并全路径闭环，见 §15",
      "B2"),
    M("credential_masking", "security_permissions", "Sandbox credential masking (v2.1.221+, Linux/WSL)",
      STATUS_PARTIAL, ("tuan_cli/harden/crypto_provider.py", "tuan_cli/core/secret_scanner.py",
                       "tuan_cli/sandbox/egress.py", "tuan_cli/core/security_utils.py",
                       "tuan_cli/core/sandbox_provider.py", "tests/test_b2_boundaries.py",
                       "tests/test_b2su_refusal_routing.py"),
      "B2 首轮落地 sentinel 代理：子进程敏感键替换为 tuan-egress-sentinel-v1:<fp>，真实值只在 CredentialBroker 进程内内存。B2 收尾把 inject_headers() 接成真实调用方(明文 HTTP 代理转发还原真实凭据，真 socket 验证)。**本轮补的更大缺口**：上一轮只有 local 分支走 EgressGuard；_run_provider 不传 env(走 sanitize_env 置空而非 sentinel)，run_syscall_sandboxed 根本没有 env 参数、Job Object/seccomp/fallback 全部 Popen 继承父进程完整环境 —— 强隔离路径上真实密钥原样进子进程。本轮给 platform 层全路径加 env 透传(含 os.execvpe)，由统一 plan_egress 提供脱敏 env。**§15 纠偏**：上一轮「四条执行分支实测都拿到 sentinel」验证的是**传给 provider.run 的 env 参数**，不是子进程实际拿到的值 —— SandboxProvider._sanitize_env 按键名把 OPENAI_API_KEY 置空，把 plan 注入的 tuan-egress-sentinel-v1:<fp> 占位符也在接线内层抹成空串，强后端子进程拿不到可还原标记、inject_headers() 链路静默断裂。本轮按**值**保留占位符(真实值仍抹空)，并补齐三个强后端被 TUAN_ hint 抹掉的 TUAN_WORKSPACE。**仍为 partial**：HTTPS CONNECT 隧道内 header 不可见、无法注入；覆盖需 TLS 中间人 + 本地 CA，会显著扩大攻击面，不做也不谎称完整对等",
      "B2"),
    M("permission_modes", "security_permissions", "default / acceptEdits / plan / bypass / auto (Shift+Tab)",
      STATUS_ALIGNED, ("tuan_cli/modes/registry.py", "tuan_cli/modes/switcher.py", "tuan_cli/modes/policy.py"),
      "五模式注册表与切换器已在；auto 模式的确定性规则前置见 auto_mode"),
    M("deny_rules_exclude_glob", "security_permissions", "permissions rules / deniedMcpServers URL (v2.1.318)",
      STATUS_ALIGNED, ("tuan_cli/config/security_schema.py", "tuan_cli/tools/mcp/policy.py"),
      "E6 负向排除 + MCP 规范化精确管控；deny 忽略 exclude，拒绝规则不允许被放宽"),
    M("deny_instead_of_prompting", "security_permissions", "permissions.denyInsteadOfPrompting (v2.1.319 新增)",
      STATUS_ALIGNED, ("tuan_cli/sandbox/unattended.py", "tuan_cli/sandbox/manager.py",
                       "tuan_cli/config/security_schema.py", "tests/test_b2_boundaries.py"),
      "B2 落地：显式开关(默认关)、no_confirm_channel / all_confirmations 两种 scope、denied=True 是硬事实而 continue_turn / suppressed_prompt 结构化写入 verdict.extra 与可查询审计；已接到 assess_tool 的真实 CONFIRM 路径，配置非法 fail-closed"),
    M("block_writes_outside_wd", "security_permissions", "permissions.blockWritesOutsideWorkingDirectories (v2.1.314，默认关)",
      STATUS_PARTIAL, ("tuan_cli/sandbox/filters.py", "tuan_cli/core/path_safety.py"),
      "CC 在 Write/Edit/NotebookEdit 工具层硬拒绝（但默认关闭）；Tuan 是命令文本规则层，工具层硬约束待补。不标 ahead —— 两者都还不是默认强边界",
      "B2"),
)

# ---------------------------------------------------------------- 2 安全扫描与审计
D2 = (
    M("secret_scanner", "safety_audit", "/security; key/token leak scanning",
      STATUS_ALIGNED, ("tuan_cli/core/secret_scanner.py", "tests/test_secret_scanner.py"),
      "确定性正则扫 AWS/GitHub/OpenAI/Anthropic/JWT/PEM，分级 + 修复建议 + 只留前后缀不二次泄露"),
    M("audit_chain_aead", "safety_audit", "Transcript / OTel tool_decision events",
      STATUS_AHEAD, ("tuan_cli/harden/crypto_provider.py", "tuan_cli/audit/store.py"),
      "CC 记录 transcript 与 OTel 事件，但无防篡改链；Tuan 的审计记录 AES-GCM/HMAC 封装 + 轮转 + 脱敏",
      ahead_reason="审计落盘带 AEAD 防篡改与设备指纹，篡改可被检出，CC 公开能力面无对等物",
      ahead_dim="audit_replay"),
    M("audit_correlation", "safety_audit", "claude_code.safety_event OTel event (v2.1.307 加，v2.1.310 又移除)",
      STATUS_AHEAD, ("tuan_cli/core/audit_correlation.py",),
      "Tuan 有 burst / cross_session / severity_escalation 三类聚合告警，指纹归一化路径数字、replay() 跨进程重启",
      ahead_reason="跨会话关联检测与 AEAD 日志重放，且不反作用于裁决；CC 的 safety_event 是逐条遥测且经历加/删",
      ahead_dim="audit_replay"),
    M("safety_event_otel", "safety_audit", "claude_code.safety_event / tool_decision OTel events",
      STATUS_GAP, ("tuan_cli/core/telemetry.py",),
      "缺结构化安全事件的 OTel 导出（本地零遥测优先，但需可导出的标准 schema）",
      "B9"),
    M("workspace_trust", "safety_audit", "workspace trust check (ultrareview /ultrareview)",
      STATUS_ALIGNED, ("tuan_cli/core/workspace_trust.py",),
      "工作区信任判定已在"),
    M("config_schema_validate", "safety_audit", "startup warnings about permission rules in settings",
      STATUS_AHEAD, ("tuan_cli/config/security_schema.py", "tuan_cli/cli/cmd_config.py"),
      "CC 大量 startup warning 是提示；Tuan 的 tuan config validate / harden status 对 sandbox/permissions 做**结构化拒绝**",
      ahead_reason="畸形配置（非 dict 规则、未知 action、sandbox.enabled=false）被拒绝而非静默让整条滤网失效",
      ahead_dim="config_correctness"),
    M("harden_status", "safety_audit", "/doctor / sandbox status",
      STATUS_AHEAD, ("tuan_cli/cli/cmd_harden.py", "tuan_cli/harden/"),
      "tuan harden status 给出基线态势并告警；CC /doctor 是环境体检，不校验安全基线开关一致性",
      ahead_reason="把「安全加固是否真的生效」做成可查询态势，而非只是环境诊断",
      ahead_dim="config_correctness"),
)

# ---------------------------------------------------------------- 3 Hooks
D3 = (
    M("hook_command", "hooks", "Hooks type: command",
      STATUS_ALIGNED, ("tuan_cli/hooks/manager.py", "tests/test_hooks.py"),
      "argv + stdin JSON + stdout decision，看门狗线程 + 进程树强杀"),
    M("hook_http", "hooks", "Hooks type: http",
      STATUS_ALIGNED, ("tuan_cli/hooks/manager.py", "tests/test_hooks_http.py"),
      "HTTP POST 型，本地真实端到端测试覆盖 Pre 阻断 / 改参 / Post 通知"),
    M("hook_prompt", "hooks", "Hooks type: prompt (v2.1.x)",
      STATUS_ALIGNED, ("tuan_cli/hooks/manager.py",),
      "_exec_prompt 已实现（模型单轮评估返回 JSON 决策）"),
    M("hook_agent", "hooks", "Hooks type: agent (v2.1.x)",
      STATUS_ALIGNED, ("tuan_cli/hooks/manager.py",),
      "_exec_subagent 已实现（派生隔离子代理）"),
    M("hook_events_core", "hooks", "PreToolUse / PostToolUse / UserPromptSubmit / Stop / SubagentStop / PreCompact / SessionStart / SessionEnd",
      STATUS_ALIGNED, ("tuan_cli/hooks/manager.py", "tests/test_hooks_events.py"),
      "HOOK_EVENTS 8 个核心事件 + SessionStart/SessionEnd CLI 边界接线 + UserPromptSubmit 注入 additionalContext"),
    M("hook_events_extended", "hooks", "PermissionRequest / Notification / DirectoryAdded / ConfigChange / WorktreeCreate / Elicitation / ElicitationResult",
      STATUS_GAP, ("tuan_cli/hooks/manager.py",),
      "缺 7 个扩展事件；DirectoryAdded 是 CC 2026-07-25 新增（/add-dir 注册工作目录后触发）",
      "B3"),
    M("hook_on_failure", "hooks", "onFailure: \"block\" (v2.1.317/319；CC 需显式配置，默认 fail-open)",
      STATUS_AHEAD, ("tuan_cli/hooks/manager.py", "tests/test_claude_parity.py"),
      "B1 本轮落地：spawn 失败 / 超时 / 异常 / 非零退出**默认阻断** PreToolUse，带结构化原因与审计；通知类只记录不卡 turn",
      ahead_reason="故障闭合是出厂默认且逐失败类型可审计，CC 需要用户逐条 hook 显式写 onFailure:\"block\"",
      ahead_dim="fail_closed_default"),
    M("hook_updated_input_validation", "hooks", "updatedInput unknown keys dropped / rejected input denies the call",
      STATUS_GAP, ("tuan_cli/hooks/manager.py",),
      "改参目前直接接受 dict，未按工具 schema 校验未知键",
      "B3"),
)

# ---------------------------------------------------------------- 4 技能与记忆
D4 = (
    M("skill_frontmatter", "skills_memory", "SKILL.md + frontmatter (name/description)",
      STATUS_ALIGNED, ("tuan_cli/skills/manager.py", "tuan_cli/skills/universal_format.py"),
      "单文件 .md 与 <slug>/SKILL.md 目录型均支持，frontmatter 超集"),
    M("skill_autodiscovery", "skills_memory", "auto-load from project / user / plugin scopes",
      STATUS_ALIGNED, ("tuan_cli/skills/manager.py",),
      "project(.tuan/.agents/.claude) / user / extra_dirs / builtin 四层，同名按优先级覆盖"),
    M("skill_runtime_injection", "skills_memory", "auto-activate by description at runtime",
      STATUS_ALIGNED, ("tuan_cli/core/prompts.py", "tuan_cli/core/agent.py", "tests/test_skills_runtime_injection.py"),
      "build_task_context → activate_for_task → 注册表条目注入 user 消息；正文经 skill_read 惰性加载"),
    M("skill_cli", "skills_memory", "/skills, claude plugin init, /reload-skills",
      STATUS_ALIGNED, ("tuan_cli/cli/cmd_skills.py",),
      "tuan skill list/show/import/audit/consolidate/lint 与会话内 /skills 齐全"),
    M("skill_distiller", "skills_memory", "Skill auto-generation",
      STATUS_ALIGNED, ("tuan_cli/self_improve/auto_distiller.py",),
      "蒸馏产出走 save() 写标准 frontmatter（双层 frontmatter 缺陷已修）"),
    M("claude_md_memory", "skills_memory", "CLAUDE.md persistent project memory / @-mentions",
      STATUS_PARTIAL, ("tuan_cli/memory/plugin.py", "TUAN.md"),
      "有 TUAN.md 与 memory 层，但缺 CLAUDE.md 语义等价的多层项目记忆与 @ 文件提及（CC 2.1.312 刚修过大文件覆盖）",
      "B4"),
    M("skill_integrity_signature", "skills_memory", "per-directory skills / managed skills",
      STATUS_GAP, ("tuan_cli/skills/governance.py",),
      "缺技能包完整性签名与权限域声明（Tuan 拟做的超越点：技能不可悄悄扩权）",
      "B4"),
)

# ---------------------------------------------------------------- 5 子代理与团队
D5 = (
    M("subagent_pool", "subagents_teams", "Subagents (isolated loop, own context)",
      STATUS_ALIGNED, ("tuan_cli/core/subagents.py", "tests/test_subagent_parallel.py"),
      "线程池真并行（含墙钟断言）、独立工作目录、两种隔离"),
    M("subagent_isolated_context", "subagents_teams", "isolated context / system prompt",
      STATUS_ALIGNED, ("tuan_cli/core/subagents.py",),
      "每个子任务 create_agent(..., system_extra=...) 拿独立 messages"),
    M("subagent_structured_return", "subagents_teams", "structured summary back to parent",
      STATUS_ALIGNED, ("tuan_cli/core/subagents.py",),
      "SubResult.to_block()/aggregate() 带来源标注回传"),
    M("agents_registry", "subagents_teams", ".claude/agents/*.md discovery",
      STATUS_ALIGNED, ("tuan_cli/core/agents_registry.py",),
      "三层发现 + frontmatter 解析 + 命名 agent 工具白名单折算"),
    M("agents_cli", "subagents_teams", "/agents view/list/kill/attach",
      STATUS_ALIGNED, ("tuan_cli/cli/cmd_agents.py", "tuan_cli/cli/cmd_agents_view.py"),
      "会话面板齐全"),
    M("background_agents", "subagents_teams", "background subagents by default (v2.1.198)",
      STATUS_ALIGNED, ("tuan_cli/core/background.py", "tuan_cli/core/background_worker.py"),
      "后台代理 + store + worker 三件套"),
    M("agent_teams", "subagents_teams", "Agent Teams (shared tasks, peer messaging)",
      STATUS_ALIGNED, ("tuan_cli/core/swarm.py", "tuan_cli/core/collaboration_protocol.py", "tuan_cli/core/messaging.py"),
      "共享任务与点对点消息（compare_and_swap 死锁已修）"),
    M("dynamic_workflow", "subagents_teams", "dynamic workflows / workflowSizeGuideline (<15 agents)",
      STATUS_ALIGNED, ("tuan_cli/core/dynamic_workflow.py", "tuan_cli/core/task_dag.py", "tuan_cli/core/devloop.py"),
      "动态工作流与 DAG 编排已在"),
    M("task_list_earlier_in_session", "subagents_teams", "/tasks \"Earlier in this session\" row (v2.1.319 新增)",
      STATUS_GAP, ("tuan_cli/cli/cmd_agents_view.py",),
      "已结束的子代理离开列表 / 重启后仍可重开并继续发消息，Tuan 缺该持久化索引",
      "B5"),
)

# ---------------------------------------------------------------- 6 MCP
D6 = (
    M("mcp_stdio", "mcp", "MCP stdio transport",
      STATUS_ALIGNED, ("tuan_cli/tools/mcp/client.py", "tests/test_mcp_e2e.py"),
      "initialize→notifications/initialized→tools/list→tools/call 全握手 + 指数退避"),
    M("mcp_http_sse", "mcp", "MCP HTTP / SSE transports",
      STATUS_ALIGNED, ("tuan_cli/runtime/mcp/client_http.py", "tests/test_mcp_e2e.py"),
      "JSON-RPC 信封解包缺陷已修，本地真实 HTTP server 端到端覆盖"),
    M("mcp_namespace", "mcp", "mcp__<server>__<tool> namespacing",
      STATUS_ALIGNED, ("tuan_cli/runtime/mcp/naming.py",),
      "前缀命名空间 + >64 字符 FNV-1a 碰撞安全截断"),
    M("mcp_trust_tier", "mcp", "allowedMcpServers / deniedMcpServers (flat allowlist)",
      STATUS_AHEAD, ("tuan_cli/tools/mcp/policy.py", "tuan_cli/config/security_schema.py"),
      "默认 untrusted、trusted 强制显式白名单、deny 优先、域名白名单、会话配额、会话内可回撤、策略损坏进入 locked 拒绝一切",
      ahead_reason="CC 是扁平 server allowlist/denylist；Tuan 有信任等级 + 权限域 + 可回撤 + 损坏即锁定，权限边界更细且默认不信任",
      ahead_dim="least_authority"),
    M("mcp_oauth", "mcp", "MCP OAuth authentication",
      STATUS_GAP, ("tuan_cli/runtime/mcp/config.py",), "缺 OAuth 客户端注册与凭据生命周期", "B6"),
    M("mcp_tool_search", "mcp", "MCP Tool Search (dynamic discovery)",
      STATUS_GAP, ("tuan_cli/tools/mcp/",), "缺跨 server 的动态工具检索", "B6"),
    M("mcp_elicitation", "mcp", "Elicitation / ElicitationResult hook events",
      STATUS_GAP, ("tuan_cli/tools/mcp/",), "缺 MCP server 执行中请求用户输入的通道", "B6"),
    M("mcp_tasks_background", "mcp", "MCP tasks backgrounded in terminal (v2.1.319 新增)",
      STATUS_GAP, ("tuan_cli/core/background.py", "tuan_cli/tools/mcp/client.py"),
      "长时 MCP task 立即转后台、完成再通知；Tuan 有 background 基建但未接到 MCP task",
      "B6"),
)

# ---------------------------------------------------------------- 7 插件与市场
D7 = (
    M("plugin_manifest", "plugins_marketplace", "plugin.json / .claude-plugin",
      STATUS_PARTIAL, ("tuan_cli/ecosystem/registry.py", "tuan_cli/skills/plugin_sdk.py"),
      "有组件注册表与 plugin SDK，但无与 CC 对等的 plugin.json 清单模型", "B7"),
    M("plugin_marketplace", "plugins_marketplace", "Plugins & Marketplaces",
      STATUS_GAP, ("tuan_cli/ecosystem/",), "缺 marketplace 发现/安装/更新通道", "B7"),
    M("plugin_sha256_pin", "plugins_marketplace", "plugin source pinned by sha256 (v2.1.224+)",
      STATUS_GAP, ("tuan_cli/harden/repro_build.py",), "缺 HTTPS zip 安装 + sha256 固定", "B7"),
    M("plugin_owner_wildcard", "plugins_marketplace", "owner/* marketplace wildcards (v2.1.223+)",
      STATUS_GAP, ("tuan_cli/ecosystem/registry.py",), "缺 strictKnownMarketplaces / blockedMarketplaces 的 owner 通配", "B7"),
    M("plugin_init_validate", "plugins_marketplace", "claude plugin init / validate / eval",
      STATUS_GAP, ("tuan_cli/cli/cmd_ecosystem.py",), "缺脚手架与清单校验命令", "B7"),
    M("plugin_lsp", "plugins_marketplace", "Plugin LSP Support",
      STATUS_GAP, ("ide/",), "缺插件声明的 LSP server 接线", "B7"),
    M("managed_dropins", "plugins_marketplace", "Managed Drop-ins (v2.1.83)",
      STATUS_PARTIAL, ("tuan_cli/config/",), "有配置分层但缺组织级自动下发", "B7"),
)

# ---------------------------------------------------------------- 8 模式与上下文
D8 = (
    M("plan_mode", "modes_context", "Plan Mode (read-only explore → confirm → execute)",
      STATUS_ALIGNED, ("tuan_cli/tools/session_tools.py", "tuan_cli/tools/base.py", "tests/test_plan_archive.py"),
      "只读硬拦 + 两阶段切换 + 计划原子落盘 .tuan/plan.md"),
    M("auto_mode", "modes_context", "Auto Mode (background safety classifier)",
      STATUS_ALIGNED, ("tuan_cli/core/auto_mode.py", "tuan_cli/sandbox/filters.py"),
      "有分类器且有确定性规则前置；CC 直到 v2.1.319 才停止回退内置分类器"),
    M("mode_switcher", "modes_context", "Shift+Tab mode cycling",
      STATUS_ALIGNED, ("tuan_cli/modes/switcher.py",), "模式切换器已在"),
    M("compaction", "modes_context", "context compaction / /compact",
      STATUS_ALIGNED, ("tuan_cli/context/compaction_fusion.py", "tuan_cli/runtime/session/compact_survival.py"),
      "压缩与压缩后存活策略已在"),
    M("idle_compaction", "modes_context", "Idle compaction 200K+ tokens (~54min, v2.1.290+)",
      STATUS_GAP, ("tuan_cli/context/compaction_fusion.py",),
      "缺空闲触发（缓存过期前预压缩）与 CLI/IDE 一致性", "B8"),
    M("context_1m", "modes_context", "1M-token context (Sonnet/Opus/Haiku 5.5)",
      STATUS_NA, ("tuan_cli/models/",),
      "模型侧能力，取决于用户接入的本地/远端模型，非 CLI 功能缺口，不适用"),
    M("effort_ultrathink", "modes_context", "/effort /fast / ultrathink (xhigh)",
      STATUS_NA, ("tuan_cli/models/",),
      "Anthropic 模型特有的 effort 语义，本地模型不适用；不包装成领先"),
)

# ---------------------------------------------------------------- 9 会话 / 无头 / SDK
D9 = (
    M("resume_continue", "session_headless", "--resume / --continue / session fork",
      STATUS_ALIGNED, ("tuan_cli/cli/cmd_agents.py", "tests/test_headless_resume.py"),
      "tuan run --resume/--continue 已补齐，恢复失败退出码 1"),
    M("fork_session", "session_headless", "session fork / subagent_type: fork",
      STATUS_ALIGNED, ("tuan_cli/session/store.py",), "会话存储支持派生"),
    M("stream_json", "session_headless", "--output-format stream-json (NDJSON)",
      STATUS_ALIGNED, ("tuan_cli/stream_json/",), "schema / translate / headless 齐全"),
    M("headless_print", "session_headless", "claude -p",
      STATUS_ALIGNED, ("tuan_cli/cli/cmd_agents.py", "tests/test_headless_print.py"),
      "tuan run -p 真跑 agent.run，stdin/stdout/stderr/退出码语义正确"),
    M("output_format_json", "session_headless", "--output-format json",
      STATUS_ALIGNED, ("tuan_cli/cli/cmd_agents.py",), "NDJSON text/tool_call/tool_result/thinking/finish"),
    M("agent_sdk", "session_headless", "Agent SDK (Python / TypeScript)",
      STATUS_GAP, ("tuan_cli/acp/",),
      "ACP server 已有但缺可嵌入的 Python SDK（进程内 agent + hooks + permissions）", "B9"),
    M("acp", "session_headless", "Editor / ACP integration",
      STATUS_ALIGNED, ("tuan_cli/acp/", "ide/"), "ACP 协议与 server 已在"),
)

# ---------------------------------------------------------------- 10 TUI 与交互
D10 = (
    M("fullscreen_tui", "tui_interaction", "fullscreen TUI",
      STATUS_ALIGNED, ("tuan_cli/tui/tui.py", "tuan_cli/ui/fullscreen.py"),
      "prompt_toolkit/rich 全屏 TUI 与审批覆盖层"),
    M("codex_tui_parity", "tui_interaction", "(none — CC TUI is proprietary, no public parity matrix)",
      STATUS_AHEAD, ("tuan_cli/tui/parity/", "TUI_PARITY.md"),
      "13 轮把 165 个 Codex TUI 模块做成可机器核验矩阵（键位/布局/组件树/文案），CC 无可对等的公开可核验对齐层",
      ahead_reason="把「与上游是否一致」变成 tuan tui parity --gaps 可查询、带派生一致性校验的事实，而非口号",
      ahead_dim="verifiable_parity"),
    M("vim_mode", "tui_interaction", "Vim mode (/vim), % motion, chord support",
      STATUS_PARTIAL, ("tuan_cli/tui/parity/keymap.py", "tuan_cli/tui/inputkit/vim_search.py"),
      "有 vim_search 与 keymap 上下文，但缺完整 NORMAL/INSERT 状态机与 % 匹配", "B10"),
    M("keybindings_chords", "tui_interaction", "/keybindings, ~/.claude/keybindings.json, chords",
      STATUS_GAP, ("tuan_cli/tui/parity/keymap.py",), "缺用户可编辑键位文件与和弦序列", "B10"),
    M("statusline", "tui_interaction", "status line / cost in status line",
      STATUS_GAP, ("tuan_cli/ui/",), "缺可配置状态行", "B10"),
    M("output_styles", "tui_interaction", "Output styles (Explanatory / Learning)",
      STATUS_GAP, ("tuan_cli/modes/prompts.py",), "缺输出风格切换", "B10"),
    M("prompt_suggestions", "tui_interaction", "Context-aware prompt suggestions",
      STATUS_GAP, ("tuan_cli/tui/",), "缺上下文感知的建议", "B10"),
    M("i18n_10_languages", "tui_interaction", "English-only UI",
      STATUS_AHEAD, ("tuan_cli/i18n/", "README_zh-CN.md", "README_de.md"),
      "10 语言 README + i18n 运行时，默认简体中文；CC 为英文单语",
      ahead_reason="完整 10 语言本地化且默认中文，CC 公开 UI 仅英文",
      ahead_dim="local_offline_i18n"),
)

# ---------------------------------------------------------------- 11 Git / 后台
D11 = (
    M("worktree", "git_background", "Git Worktrees / /worktree",
      STATUS_ALIGNED, ("tuan_cli/core/worktree_layer.py", "tests/test_worktree_layer.py"),
      "真调 git worktree add -b，create/list/remove/switch 四子命令 + 隔离证明测试"),
    M("worktree_sandbox_escape", "git_background", "v2.1.319 修复创建 worktree 时的沙箱逃逸",
      STATUS_ALIGNED, ("tuan_cli/core/worktree_layer.py",
                       "tuan_cli/sandbox/worktree_boundary.py", "tests/test_b2_boundaries.py"),
      "B2 落地且**真接线**：create / create_agent_worktree 在 fast-resume 之前断言解析后 target 在 workspace 内(含 symlink 祖先)，_git 剥离 GIT_DIR/GIT_WORK_TREE/GIT_INDEX_FILE 等重定向变量并拒绝 git -C/--git-dir 等越界 argv；边界证明可查询"),
    M("diff_view", "git_background", "/diff, word-level diff",
      STATUS_ALIGNED, ("tuan_cli/core/diff_view.py", "tuan_cli/sandbox/isolation.py"),
      "diff 渲染 + 副本 diff 预览（含点目录修复）"),
    M("background_bash", "git_background", "background Bash / long-running commands",
      STATUS_ALIGNED, ("tuan_cli/core/background_shell.py", "tuan_cli/core/background_store.py"),
      "后台 shell 与存储已在"),
    M("loop_cron", "git_background", "/loop, CronCreate, scheduled tasks",
      STATUS_ALIGNED, ("tuan_cli/cron/", "tests/test_cron_schedule.py"),
      "零依赖 5 字段 cron 解析器 + daemon/runner/store"),
    M("scheduled_tasks_ui", "git_background", "/tasks background task management panel",
      STATUS_GAP, ("tuan_cli/cli/cmd_cron.py",), "缺统一后台任务面板", "B10"),
)

# ---------------------------------------------------------------- 12 代码智能
D12 = (
    M("lsp", "code_intelligence", "Code intelligence / LSP via plugins",
      STATUS_GAP, ("ide/",), "缺 LSP client 接线", "B7"),
    M("symbols_navigation", "code_intelligence", "symbol-level navigation & live type errors",
      STATUS_GAP, ("tuan_cli/context/fast_index.py",), "有快速索引但缺符号级导航与实时诊断", "B7"),
    M("code_review", "code_intelligence", "Code Review / @claude review",
      STATUS_ALIGNED, ("tuan_cli/cli/cmd_review_cli.py",), "代码审查命令已在"),
    M("security_review", "code_intelligence", "/security review",
      STATUS_ALIGNED, ("tuan_cli/cli/cmd_safe.py", "tuan_cli/core/security_auditor.py"),
      "安全审计与报告已在"),
    M("ultrareview", "code_intelligence", "claude ultrareview --trust-workspace",
      STATUS_GAP, ("tuan_cli/cli/cmd_review_cli.py",), "缺带工作区信任门控的深度审查", "B7"),
)

# ---------------------------------------------------------------- 13 云 / 远程 / 集成
D13 = (
    M("remote_control", "cloud_remote", "Remote Control (session host + reconnect)",
      STATUS_PARTIAL, ("tuan_cli/core/remote_control.py",),
      "有远程控制模块但无 CC 对等的会话托管/重连语义", "B9"),
    M("cloud_sessions", "cloud_remote", "Web / mobile / desktop cloud sessions",
      STATUS_NA, (), "Anthropic 托管云会话，需 claude.ai 订阅；本地离线 CLI 明确不实现"),
    M("self_hosted_runner", "cloud_remote", "Self-Hosted Runner (Team/Enterprise, v2.1.224+)",
      STATUS_NA, (), "Anthropic 托管编排，需 Team/Enterprise 订阅，不适用；不包装成领先"),
    M("chrome_integration", "cloud_remote", "Claude in Chrome extension / computer use",
      STATUS_NA, (), "浏览器扩展与登录态依赖，需订阅；不实现"),
    M("channels_voice", "cloud_remote", "Channels (Slack/Telegram), Voice Dictation",
      STATUS_NA, (), "研究预览 / 订阅功能；本地 CLI 不适用"),
    M("gateway_managed_settings", "cloud_remote", "Claude apps gateway, managed policies, pooled budgets",
      STATUS_NA, (), "企业网关与计费策略，Anthropic 专属基础设施，不适用"),
)

# ---------------------------------------------------------------- 14 可观测 / 模型 / 成本
D14 = (
    M("otel_metrics", "observability_models", "OpenTelemetry metrics / events / spans",
      STATUS_PARTIAL, ("tuan_cli/core/telemetry.py", "tuan_cli/arch/observability.py"),
      "有遥测与可观测模块，但缺 CC 对等的 OTel exporter 与标准事件 schema", "B9"),
    M("settings_layers", "observability_models", "user / project / local / managed settings layers",
      STATUS_ALIGNED, ("tuan_cli/config/",), "配置分层已在"),
    M("cost_budget", "observability_models", "/cost, /usage, --max-budget-usd, status line cost",
      STATUS_GAP, ("tuan_cli/cli/cmd_model.py",), "缺 token 成本计量与预算硬上限", "B9"),
    M("feature_flags", "observability_models", "CLAUDE_CODE_DISABLE_FEATURE_FLAGS (v2.1.319)",
      STATUS_NA, (), "CC 依赖远程 feature-flag 拉取；Tuan 无该机制，不适用而非领先"),
    M("local_models_offline", "observability_models", "Claude models / Bedrock / Vertex / Foundry",
      STATUS_AHEAD, ("tuan_cli/models/", "README_zh-CN.md", "SUPPORTED_MODELS.md"),
      "完全本地离线、可接任意本地/兼容模型，不依赖账号登录与模型订阅",
      ahead_reason="无账号、无云端编排、无订阅绑定即可完整运行，CC 多数能力需 claude.ai 登录",
      ahead_dim="local_offline_i18n"),
    M("zero_telemetry", "observability_models", "telemetry / feature-flag fetching (DISABLE_TELEMETRY opt-out)",
      STATUS_AHEAD, ("tuan_cli/core/telemetry.py", "README_zh-CN.md"),
      "Tuan 默认不外发；CC 需显式 DISABLE_TELEMETRY 才关闭（且 auto mode 曾因遥测关闭而回退分类器）",
      ahead_reason="零外发是出厂默认而非可选项，且不因关闭遥测而削弱安全判定",
      ahead_dim="local_offline_i18n"),
)

MODULES: Tuple[Module, ...] = D1 + D2 + D3 + D4 + D5 + D6 + D7 + D8 + D9 + D10 + D11 + D12 + D13 + D14

# 后续轮次路线。每个 gap 必须且只能出现在一个 wave 中（matrix 自检）。
WAVES: Tuple[Dict[str, str], ...] = (
    {"wave": "A14", "line": "A (Codex TUI 对齐)", "target": "streaming_async + tools_exec + history_transcript 剩余 5 个",
     "note": "与 B 线并行，不碰 B 线文件"},
    {"wave": "A15", "line": "A (Codex TUI 对齐)", "target": "最后 5 个 pending 清零，fully_identical 才可能为 true",
     "note": "TUI_PARITY.md §5 既有路线"},
    {"wave": "B1", "line": "B (超 Claude Code)", "target": "基线矩阵 + 详细计划 + hooks 默认 fail-closed 落地",
     "note": "本轮：CLAUDE_PARITY.md / parity_claude 包 / tuan claude parity / NOTICE 第 14 条"},
    {"wave": "B2", "line": "B (超 Claude Code)", "target": "OS 沙箱默认化 + 网络默认拒 + 凭据代理注入 + denyInsteadOfPrompting + worktree 逃逸证明",
     "note": "最大落后项，属于破坏性行为变更，需逐项给迁移开关与真机验证。**部分落地**：首轮 4 个 gap 推进(2 aligned + 2 partial, §12)，收尾把 network_strict_allowlist 从 partial 推到 aligned、credential_masking 接上真实出网代理(§13)；os_sandbox 仍 gap、deny_network_by_default 出厂仍 false 未翻，B2 未全清"},
    {"wave": "B3", "line": "B (超 Claude Code)", "target": "7 个扩展 hook 事件 + updatedInput 校验 + 四型 hook 统一失败语义",
     "note": "每一步都保持默认 fail-closed"},
    {"wave": "B4", "line": "B (超 Claude Code)", "target": "CLAUDE.md 语义等价记忆 + @ 提及 + 技能完整性签名与权限域声明",
     "note": "技能不可悄悄扩权是 CC 无对等物的超越点"},
    {"wave": "B5", "line": "B (超 Claude Code)", "target": "/tasks 持久化索引 + 每 subagent 独立沙箱与权限域 + 跨会话审计关联",
     "note": "把已有 audit_correlation 接到子代理生命周期"},
    {"wave": "B6", "line": "B (超 Claude Code)", "target": "MCP OAuth / tool search / elicitation / tasks 后台化",
     "note": "复用已有 trust tier，不重开侧门"},
    {"wave": "B7", "line": "B (超 Claude Code)", "target": "Plugins + Marketplace(sha256 pin, owner/*) + LSP + 符号导航 + ultrareview",
     "note": "默认 untrusted + 清单签名，沿用 MCP 信任分级模型"},
    {"wave": "B8", "line": "B (超 Claude Code)", "target": "permission modes 统一 + idle compaction + 确定性规则前置的形式化证明",
     "note": "模型不作为安全边界；规则前置要有断言而非只写文档"},
    {"wave": "B9", "line": "B (超 Claude Code)", "target": "Python SDK / ACP / OTel schema / cost+budget / safety_event 导出",
     "note": "本地零遥测优先，导出需显式开启"},
    {"wave": "B10", "line": "B (超 Claude Code)", "target": "Vim 状态机 / chords / statusline / output styles / 建议 / 任务面板 / 10 语言一致",
     "note": "与 A15 的 TUI 收尾合并验证"},
)


def constants() -> Dict[str, object]:
    return {
        "cc_product": CC_PRODUCT,
        "cc_version": CC_VERSION,
        "cc_date": CC_DATE,
        "cc_tag_timestamp": CC_TAG_TIMESTAMP,
        "sources": len(SOURCES),
        "domains": list(DOMAINS),
        "statuses": list(STATUSES),
        "superiority_dimensions": list(SUPERIORITY_DIMENSIONS),
        "waves": [w["wave"] for w in WAVES],
        "total_modules": len(MODULES),
    }
