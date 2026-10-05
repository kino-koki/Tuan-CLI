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

- 主链路位于 [`qingxiaotuan/sandbox/`](qingxiaotuan/sandbox/)（`SandboxManager` 统一入口）。
- 工具执行闸门位于 [`qingxiaotuan/core/tool_executor.py`](qingxiaotuan/core/tool_executor.py)（`_security_gate_check` + `_sandbox_gate_check`）。

---

## 3. 四层沙箱滤网

| 层 | 模块 | 职责 | 裁决落点 |
|----|------|------|----------|
| L0 意图 | `sandbox/filters.py::IntentFilter` | 硬红线(`rm -rf /`/`format c:`)、数据外泄、远程执行 → deny-critical/high | 模型无关、确定性最强 |
| L1 信任 | `sandbox/filters.py::TrustFilter` | 工作区信任分级(trusted/limited/untrusted/unknown) + 域名白名单 + 计划模式 | trusted 放行 / untrusted 拒 / unknown 确认 |
| L2 资源 | `sandbox/filters.py::ResourceFilter` | 默认禁网 → 无网隔离；高危写 → 副本模式 | 决定"上不上 L3" |
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
- **L2 资源滤网**：负责**存在性 + 无网开关**：含网络请求且默认禁网 → `network=False + isolate=True`（气隙执行）。本地命令不受影响。

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

| # | 模块 | 增强方向 |
|---|------|----------|
| E1 | `tools/mcp/policy.py` + `security.py` | MCP **server 信任分级**：把每台 server 的权限域(只读/工具白名单/允许的域名)落到持久化策略；新增"调用前工具级授权 + 会话内可回撤"，取代散落的临时确认 |
| E2 | `core/workspace_trust.py` | 信任**自动衰减与重校验**：trusted 在目录变更/新敏感文件(.env/.git/config/密钥)出现时自动降级到 limited 并提示复议 |
| E3 | `sandbox/backends.py` + `arch/platform.py` | **Job Object 资源配额落地**：CPU 配额、内存上限、进程树击杀超时兜底(当前仅存在性探测) |
| E4 | `core/security_auditor.py` + `harden/audit_export.py` | 审计**关联合并 + 跨会话异常检测**：同源多次红线(如 MCP 反复注入)聚合告警；导出支持轮转与加密 |
| E5 | `core/tool_executor.py` | **写操作风暴检测**：单会话内高频率写/删除触发节流与告警，防误删批量任务 |
| E6 | `tools/permissions.py` | `permissions.rules` 增强：**负向 glob**(`!bin/**`)、MCP 工具名规则、会话内临时授权提升 |
| E7 | `sandbox/isolation.py` | 副本模式的 **diff 可视化确认**：以 CLI/交互卡片展示变更后再 apply |
| E8 | `config` | `sandbox`/`permissions` 配置的 **schema 强校验 + fail-closed 可观测性**（开启项/降级项可视化） |

> 判定"先做哪些"：优先级高且可独立演进 → **E2、E3、E5**；依赖交互设计 → **E1、E7**；属加固打磨 → **E4、E6、E8**。

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

1. **手动授权**：用户通过 `qxt safe allow <command>` 将命令加入白名单
2. **白名单生效后**：同类操作**自动执行**，不再弹出确认（前缀匹配，如 `git status` 匹配 `git status --short`）
3. **用户随时可撤销**：通过 `qxt safe deny <cmd>` 撤销白名单
4. **白名单永远低于黑名单**：即使命令在白名单中，如果命中红线模式，**仍然拦截**
5. **红线命令无法加入白名单**：`is_redline` 命中的命令，`qxt safe allow` 会直接拒绝

> **注意**：用户在某次确认通道中「放行」的命令**仅本次生效**，不会自动写入白名单。
> 白名单存储在 `~/.qingxiaotuan/whitelist.json`。

白名单管理命令：`qxt safe list`（查看）· `qxt safe allow <command>`（添加，红线命令会被拒绝）· `qxt safe deny <cmd>`（移除）· `qxt safe status`（查看安全系统状态，含白名单条目数与存储路径）。

### 10.6 月度更新（黑名单演进）

**每月第一个工作日**，团队必须 review 并更新黑名单：检查新攻击模式 / 新绕过方式 → 更新 `_CRITICAL_PATTERNS` / `_HIGH_PATTERNS` 正则库 → 更新本节命令列表 → 记录变更到 `CHANGELOG.md`。

### 10.7 验证机制（实时可用，非虚构接口）

```bash
qxt ext call safety score '{"command":"rm -rf /"}'
# 输出: { "risk": "critical", "score": 100, "block": true, "reasons": ["recursive force delete (递归强制删除)"], ... }

qxt ext call safety score '{"command":"ls -la"}'
# 输出: { "risk": "none", "score": 0, "block": false, "reasons": [], ... }
```

> **注**: 旧文档曾出现 `qxt safety check` 命令，该命令**不存在**（未实现），请使用上述 `qxt ext call safety score` 替代。

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

1. **环境脱敏**：server 子进程的环境变量中抹除密钥类变量（`API_KEY`、`SECRET`、`TOKEN`、`PASSWORD`、`QXT_*`、`OPENAI*`、`AWS_*`、`DATABASE_URL` 等），防止密钥泄漏到 server。
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
- 超过频率限制 → `qxt config set mcp.security.max_calls_per_minute 120`（重启后生效）。
- **注**: `/mcp config` 命令**不存在**。调整 MCP 配置请使用 `qxt config set <key> <value>`，或直接编辑 `~/.qingxiaotuan/config.yaml` 的 `mcp:` 段。
- 沙箱执行失败 → 检查 server `command`/`args` 是否可执行（`qxt mcp list`）；闸门拦截是预期行为（查 `/mcp audit` 中 `sandbox-gate-denied` 记录）；密钥被抹除导致行为异常时请在 server 的 `env:` 段显式声明（仍建议最小必要权限）。

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
- `tests/test_cli_e2e.py` CLI 入口夹具：`_qxt_bin()` 解析的 `run` 控制台脚本不存在。

---

*最后修订：2026-09-06 · 适用于：Tuan-CLI 所有版本*