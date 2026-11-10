# 安全基线（部署者必读）

> 本文面向**要把它跑在生产/托管环境里的人**，不是功能介绍。
> 目标是把「代码里有开关」和「部署时真的开了」分开说清楚，并明确当前设计**做不到什么**。
> 配套：`SECURITY.md` / `SECURITY_EN.md`（子系统权威说明）、`HARDENING.md`（加固工具）。

---

## 1. 一句话定位

Tuan-CLI 的安全模型是 **「确定性规则滤网 + 审计/回滚治理」**，边界主要落在**进程内的策略层**；
它不是「所有命令默认跑在 OS 级沙箱里」的执行器。这个差别决定了下面的部署要求：**必须在外面再垫一层隔离**。

不要只靠提示词、系统提示、模型对齐或静态红线来挡提示注入。自适应攻击下已发表的防御基本都可被绕过，
本项目 `bench/` 里的 10k / 5k / 2497 条数字是**自建静态数据集**，只用于回归门禁，不构成对抗真实攻击者的证明。

---

## 2. 本次加固（可复跑验证）

| 编号 | 问题 | 修复 |
|---|---|---|
| R1 | `SandboxManager.DEFAULT_POLICY.enforce_required=False` 与 `config/defaults.py` 的 `True` 冲突；`sandbox:` 段覆盖后漏写该键会静默降级为裸执行 | 两处统一为 `True`；新增「局部覆盖不丢失」回归用例 |
| R2 | 显式指定的强隔离后端不可用时 `fail-soft` 回落到 auto，可能最终落到 `local` 裸执行 | 返回 `(prefer, False)`，交由 `HardIsolationFilter` 在 `enforce_required=True` 时拒绝 |
| R3 | 6 处异常路径 `except: pass` = 静默放行（网络探测、红线引擎导入、网络红线判定、域名白名单、凭据扫描、域名解析） | 全部改为 fail-closed：拒绝或升级人工确认 |
| R4 | `pip/npm/yarn/pnpm/poetry/uv install`、`pytest/tox/nox/go test/cargo test/mvn/gradle/make` 被判「良性零确认」，但会执行仓库内 `postinstall` / `conftest.py` / `build.rs` / `Makefile` | L0 新增确认门控（`CONFIRM`，非 `DENY`），`--help/--version` 变体不触发 |
| R5 | 加固项只有文档、没有态势检查 | `tuan harden status` 输出 `enforce_required` / 默认禁网 / 域名白名单 / 强后端可用性，并列出待加固项 |
| R6 | E2 信任衰减**只有测试调用**：CLI 与 Web 都直接读 `record.level`，衰减从未生效；扫描异常 `except: pass` 静默放行；`last_used` 从不更新导致活跃工作区 30 天后被误判过期 | `check_trust()` 主链路自动衰减 + 敏感面指纹基线 + 扫描失败 fail-closed + `last_used` 自动维护 + 降级原因可观测 |
| R7 | E5 写风暴「不同文件数」按会话累计，触发后永久告警，与 60 秒滑动窗口矛盾；告警文案把次数误写成秒数 | 文件维度与次数维度共用窗口、告警态随窗口复位、修正文案 |
| R8 | `PermissionPolicy._hardening_confirm()` 安全引擎导入失败时 `except: pass` 后 YOLO 自动批准，超长命令 / FD 重定向 / IEX / Docker 守护进程重定向全部静默放行 | 异常时返回 `confirm` 并标注 fail-closed |
| R9 | `permissions.rules` 无法对单台 MCP server 精确管控，宽泛 allow 也没有负向排除（「永远允许」= 提权入口） | E6：`exclude` / `!glob` 负向排除（deny 忽略）、`mcp__<server>__<tool>` 规范化名 |
| R10 | `config/validate.py` 不覆盖 `sandbox` / `permissions`；非 dict 规则、未知 action、`sandbox.enabled=false` 都会静默失效 | E8：新增 `config/security_schema.py`，接入 `tuan config validate` 与 `tuan harden status` |
| R11 | **降级被误报为已隔离**：`SandboxManager._run_syscall()` 写死 `enforced=True`，platform 层内部退化为普通子进程时上层仍认为 OS 级强隔离生效 | E3：`SyscallResult` 带 `enforced` / `degraded_reason`，所有 fallback 置 `enforced=False`，由 `enforce_required` 决定拒绝 |
| R12 | `AssignProcessToJobObject` 失败时 `pass` 后照跑，却仍返回 `mechanism="job-object"`；配额设置失败也照跑 | E3：杀掉子进程并返回 `blocked=True / enforced=False`；配额任一步失败即抛错 |
| R13 | E3 名义配额：`cpu_rate_pct` 参数从未使用、`MaximumWorkingSetSize` 缺 `WORKINGSET` flag、后端探测只看 `sys.platform == "win32"` | E3：class 9 + class 15 双次 `SetInformationJobObject` 落 CPU 硬上限；真实 `CreateJobObjectW` 能力探测；三级进程树击杀兜底 |
| R14 | 审计逐条存储，同源反复红线无聚合信号；导出文件无轮转、权限不收紧 | E4：新增 `core/audit_correlation.py`（burst / cross_session / severity_escalation），历史 AEAD 重放；导出按大小轮转 + 0600 |
| R15 | 无控制终端（CI / 容器 / systemd）下 `os.getlogin()` 抛 OSError，整个审计器初始化失败 | 改为 best-effort 环境变量兜底；**指纹格式保持不变**，既有加密日志仍可解密 |
| R16 | **`copy_diff_apply` 是纯文档特性**：L2 写入 `verdict.workspace_mode`，但 `execute_isolated()` 从未读取，`isolate_workdir`/`diff`/`apply` 生产代码零调用点，高危命令实际在真实工作区裸跑 | E7：按 `workspace_mode` 分派，高危命令在隔离副本内执行，预览 + 确认后才写回 |
| R17 | `Snapshot.capture()` 跳过所有点目录，副本里改 `.github/workflows/ci.yml` 时 `diff()` 返回空 —— 确认界面显示「无变更」 | E7：只跳过 `_IGNORED` 与隔离副本自身，隐藏目录纳入快照 |
| R18 | 旧 `diff()` 只有 `path/status`，确认时看不到改了什么内容；敏感文件无高亮；`apply()` 无确认门控、无 TOCTOU 复检 | E7：`DiffPreview` 带内容预览/敏感标记，`confirm_apply()` fail-closed + 指纹复检，不引入缓存 |
| R19 | MCP 无「这台 server 被允许做什么」的权限域：只有内容层注入扫描，外层 `mcp_call` 一刀切；未登记 server 首次出现即按外层策略放行 | E1：`MCPPolicyStore` 持久化信任分级 + 工具级授权 + 会话内可回撤；默认 untrusted 拒绝、损坏即 locked；由 `build_permission_policy()` 接入主链路，策略层失败注入 DenyAll |
| R20 | E1/E7 只有后端 API，没有审批卡片；`ctx.confirm` 缺失的 headless 场景直接失败 | 新增 `ui/approval_overlay.py`（借鉴 Codex TUI 交互契约，等价移植、非 Rust 源码复制）：结构化审批卡片 + 显式决策事件 + Esc=Abort；E1 `request_grant()` 呈现完整权限域，E7 `confirm_apply()` 接 `card_renderer`，无 TUI 时提供同样要求显式决策的 headless 默认通道（精确确认码 + 非 TTY 即 ABORT）。**fail-closed 未放宽** |
| R21 | 文档把 Codex TUI 规模写成 567 个 `.rs` / 24.7 万行（来自不完整 sparse 解压）；且「与 Codex 完全相同」无度量口径 | 完整解压后更正为 165 模块 / 1216 `.rs` / 492414 行；新增 `tuan_cli/tui/parity/` 对齐层（组件树 / 键位 / 布局 / 文案 / 矩阵）、`tuan tui parity` 命令与 `TUI_PARITY.md`，把「完全相同」拆成可核销维度。**逐值对齐仅 8.5%、pending 31，如实标注 `fully_identical=false`** |
| R22 | 终端 OSC 序列被解释执行，而上游 `terminal_hyperlinks::web()` 不校验目的地、`terminal_program_status` 直接 `execute!(stdout())`；且 `input_keymap` 组 7 个模块仍未对齐 | 新增 `tui/inputkit/` 7 模块：`web()` http/https 白名单 + OSC/BEL 拦截 + 8192 字节上限、`TrustedWorkspaceFile` canonicalize 逃逸/symlink/隐藏目录拒绝、状态发射默认 no-op writer 且 detail 先净化转义、RAII 守卫异常路径也释放、双缓冲 diff 与同步帧。指标 pending 31→24、逐值对齐 8.5%→12.7%，**如实保持 `fully_identical=false`** |
| R23 | `core_app` 组 9 个模块未对齐；且上游诊断/录制若直接携带 SDP（含 ICE 凭据）或语音文本即泄漏，CLI 里「绕过审批」与「指定审批策略」静默共存会形成配置侧门；线程切换后旧回退选择可能跨会话生效 | 新增 `tui/corekit/` 9 模块：`Redacted` 全链路脱敏（`reveal()` 唯一出口带计数）、`UserVerificationResponse.proof` 不进录制、`cli` 两条审批冲突 fail-closed、`app_info` 严格字段白名单 + http/https 校验、有界事件队列、空 thread_id 拒绝、`bind_thread()` 失效 + revert 二次校验、双生命周期 busy。**`app.assert_wiring_intact()` 真实 import 验证 6 条既有安全接线（权限策略注入 / deny-all / ctx.confirm / 审批卡片 / 副本确认 / ABORT）并接入三层自检**，本轮未替换任何现有运行时对象。指标 pending 24→15、逐值对齐 12.7%→18.2%，**如实保持 `fully_identical=false`** |
| R24 | `config_models` + `misc` 组 5 个模块未对齐；且上游迁移模板的链式 `replace` 会把被污染模型名里的 `{model_to}` 二次替换、模式发现失败被静默压成空列表、`--add-dir` 被忽略时仅返回一句可能被漏打印的警告、侧栏命中测试与渲染分页可能不同源 | 新增 `tui/configkit/` 5 模块：**单次正则扫描**修链式二次替换（实测 `"old-{model_to}-x"` 不再变 `"old-NEW-x"`）、`DiscoveryResult` 区分 5 态且 `usable` 只允许 ok/empty、`AddDirDecision`+`enforce()` 把忽略升级为结构化拒绝并校验 `..`/控制字符/NUL（刻意不做「越出 cwd」判定，与 `--add-dir` 语义冲突）、`choice_rows`/`choice_at` 与 `TabStrip.hit`/`render_plan` 各自共用同一份几何并提供 `*_matches_render()` 自检。**强制迁移下 Esc 也 accept、事件耗尽默认 accept 的上游既有策略原样保留，但用 `policy_note()` 显式标注与审批 fail-closed 相反，绝不套用到审批链路**。`configkit_validate()` 调用 `corekit.app.assert_wiring_intact()`，6 条既有安全接线仍全绿；本轮未替换任何现有运行时对象。指标 pending 15→10、逐值对齐 18.2%→21.2%，**如实保持 `fully_identical=false`** |
| R25 | 上一轮 hook 层仍存在两个 fail-open 侧门：四种执行器失败时一律 `return None`，`run_pre` 直接 `continue`（安全 hook 自己挂了命令照跑）；`blocking` 默认 `False` 会吞掉 hook 返回的 `{"block": true}`。CC 直到 v2.1.317/319 才提供 `onFailure:"block"` 且需逐条显式配置 | 新增 `HookFailure` + `failures()` / `clear_failures()` / `on_failure_policy()`；**`hooks.on_failure` 出厂默认 `block`**，`ask` 同样阻断并标注需人工确认，`allow` 为显式且留痕的逃生口，未知值回退最严格档；失败类型细分 8 种，阻断带 `HookDecision.failure_kind` 与结构化 reason。看门狗超时由**主线程**补记（`last_failure` 为 thread-local，跨线程会绕过 fail-closed）。通知类事件只留痕不卡 turn。`blocking` 默认改 `True`，仅管 hook 自身决策、不管执行失败。`config/security_schema.py` 增加 `hooks.on_failure` 枚举校验，显式 `allow` 报安全降级。**行为变更如实标注并提供迁移开关**；既有超时测试断言更新并新增逃生口用例，未为变绿放宽策略。同时启动 `CLAUDE_PARITY.md`（14 域 / 99 模块 / 12 轮次）与 `tuan claude parity`，**`fully_superior=false`**（30 缺口、第三方红队未做）；OS 沙箱 / 网络默认拒 / 凭据注入 / worktree 逃逸**明确列为 B2 缺口，不宣称已对齐**。`matrix.validate()` 调用 `assert_wiring_intact()`，6 条既有接线全绿 |

回归：`tests/test_fail_closed_regressions.py`（37 例）、`tests/test_e2_e5_hardening.py`（16 例）、
`tests/test_e6_e8_hardening.py`（21 例）、`tests/test_e3_jobobject.py`（25 例）、
`tests/test_e4_correlation.py`（24 例）、`tests/test_e1_e7_hardening.py`（39 例）、
`tests/test_tui_approval_overlay.py`（59 例）、`tests/test_tui_parity.py`（新增）、
`bench/indep_verify.py`（29 例）；沙箱 / 权限 / 配置批次 156 例，
安全集成 / MCP / shell 守卫 / 文档一致性批次 264 例，
审批覆盖层与 E1/E7 接线 102 例、输入层 `test_tui_input_layer.py` 88 例、
应用核心 `test_tui_core_app_layer.py` 76 例、
配置/侧栏 `test_tui_config_layer.py` 106 例、
对齐矩阵 `test_tui_parity.py` 85 例通过；`tuan tui parity` 显示
「安全接线：既有链路完好 · 6 项检查」。

```bash
python -m pytest tests/test_fail_closed_regressions.py tests/test_e2_e5_hardening.py -q
python bench/indep_verify.py
tuan harden status
```

---

## 3. 生产部署基线（务必照做）

### 3.1 外面必须垫一层

把**整个 Tuan 进程**放进一次性容器或 VM，而不是指望 `--isolation`：

- 只读挂载代码，工作区单独可写卷；
- 容器以非 root 运行，禁止挂载 `/var/run/docker.sock`；
- 出网走代理 + 域名白名单，默认拒绝；
- 不把长期密钥、云凭据、`~/.ssh` 放进同一文件系统视图；
- 用完即毁，不复用容器跑第二个不可信任务。

`--isolation` / `--sandbox` 是 **engine/process 级**隔离，用于缩小爆炸半径和隔离失败，
**不是完整 OS 沙箱**（README 已明确）。默认配置下，绝大多数命令**不进入** L3 强隔离。

### 3.2 配置（`config.yaml`）

```yaml
sandbox:
  enabled: true
  backend: auto                      # 确保机器上真有 docker / bwrap / seatbelt 之一
  enforce_required: true             # 无强后端时拒绝, 绝不裸执行 (必须保持 true)
  deny_unknown_shell: true           # 未知信任工作区的 shell 直接拒绝
  allowed_domains:                   # 出网域名白名单, 生产不要留空
    - pypi.org
    - registry.npmjs.org
    - github.com
  resource:
    deny_network_by_default: true     # 默认禁网 (出厂为 false, 生产请开启)
    max_memory_mb: 2048
    max_timeout: 300
    isolate_copy_threshold: high

security:
  network:
    deny_remote_exec: true
    deny_data_exfil: true
    one_way_mode: true
    egress_cidr_allow: []            # 按需收紧
  mcp:
    audit_enabled: true
    block_on_injection: true
```

> 开启 `deny_network_by_default` 后，含网络特征的命令会 `network=False + isolate=True`。
> 若机器上没有可用强后端且 `enforce_required=true`，这些命令会被**拒绝**——这是预期行为，
> 不是 bug：先装好隔离运行时，再谈出网。

### 3.3 运行态检查清单

- [ ] `tuan harden status` 显示 `fail-closed=OK`、`默认禁网=OK`、强后端非空
- [ ] `tuan harden repro-lock --verify --out requirements.lock` 通过（依赖未漂移）
- [ ] `tuan harden sbom` 产出 SPDX，且发布件与 SBOM 对应
- [ ] 审计日志落在进程外的追加式存储（WORM / 自签名链），不要只信工作区里的 `.git/logs`
- [ ] 发布 tag 已签名（`git tag -s`），且能从干净 checkout 复现构建
- [ ] 对不可信仓库跑任务时，人工审批通道可用且**审批超时按拒绝处理**

---

## 4. 已知局限（不回避）

1. **规则层在前、内核层在后**：L3 强隔离只在 `verdict.isolate` 为真时触发，而 `isolate` 主要由「severity ≥ high」或「开启默认禁网」置位。这不是「所有命令默认在 OS 沙箱内」。要获得与内核级沙箱等价的保证，只能靠 §3.1 的外部容器/VM。
2. **网络管控是「看命令文本」**：`NetworkGuard` 识别命令串里的域名/IP/CIDR 特征，不是出网路径上的强制拦截。绕过字符串识别的外传（如被注入的子进程自行联网）需要外部代理兜底。
3. **静态基准 ≠ 对抗鲁棒性**：自建 10k 对抗样本、2497 条 bypass matrix 用于回归；项目未提供第三方自适应红队报告。误杀/漏拦数字请自行本地复跑后再引用。
4. **YOLO 仍会放大风险**：`--yolo` 自动批准本需确认的操作（硬红线仍拒）。托管服务不要开；也不要把「永远允许」类持久规则交给模型提议。
5. **发布溯源**：发布时建议为 tag 签名（`git tag -s`），并在每次发布附上提交 SHA、文件清单哈希与工具链版本，使「发布件是否等于测试件」可独立核验。
6. **成熟度**：单人维护、无第三方安全审计、无公开 CVE/公告流程。`SECURITY_EN.md §8` 的 E1–E8 仍是未完成项，其中 E1（MCP server 信任分级 / 会话内可撤销授权）、E2（信任自动衰减）、E5（写风暴检测）与安全直接相关，优先级最高。

---

## 5. 不要做的事

- 不要在没有外部容器/VM 的宿主机上，用长期云凭据跑不可信仓库的自主任务；
- 不要为了「少弹窗」把 `enforce_required` 改回 `false` 或把 `deny_network_by_default` 永久关掉；
- 不要把 `pip install` / `pytest` 的确认当成噪音批量「始终允许」；
- 不要用 `bench/` 的数字对外宣称「100% 防提示注入」。

---

## 6. 复现

```bash
pip install -e ".[dev]"
python -m pytest tests/test_fail_closed_regressions.py -q
python -m pytest tests/test_sandbox_system.py tests/test_security_integration.py -q
python bench/indep_verify.py
python -m tuan_cli.cli.cmd_harden status   # 或安装后: tuan harden status
```


---

## R27 · 运行时标语与 TUI 状态口径（本轮新增）

| 项 | 风险 | 处置 |
|---|---|---|
| R27 | 自定义标语直接渲染进终端；上游同类 UI 不校验 OSC 目的地。footer 在工具运行期显示 `Working (...)` 而非真实工具名（状态与真实活动不符）；`_disp_width` 与 `_display_width` 两套宽度算法导致视口切片与裁剪错位 | `sanitize_verb()` 去掉 OSC 8 / CSI / C0 / C1 并按显示列宽截断；配置非法回落出厂值并留痕；footer 工具名优先；宽度统一到 `_display_width` 单一真值来源；修正「wcwidth 是 C 实现」错误注释 |

如实边界：主线 `_line_heights` 已自带 `(width, text)` 高度缓存，本地分叉副本
实测的 16.2 → 0.39 ms/帧 **不适用于主线**；本轮在主线未宣称性能修复。
`stall` 诊断是启发式可观测提示，不是安全闸门、心跳或超时控制。详见
`RUNTIME_SLOGANS.md`。


---

## R28 · 运行时标语深度轮

| 项 | 风险 | 处置 |
|---|---|---|
| R28 | 引擎被 UI/模型/工具/动画四类线程并发读写，无锁复合状态会撕裂；证据链若记 detail 原文会泄露工具参数/路径；未知阶段键静默忽略会造成「以为收紧了预算其实没变」；缺省 `mode` 误判让合法配置静默回落出厂值 | `RLock` 全线性化 + 时钟单调化 + `(seq, verb)` 并发回归；证据只记长度/字符类别、不记原文、不落盘；未知阶段键整段拒绝；按是否给 `verbs` 推断 `mode` |

如实边界：`stall` 仍是启发式可观测提示（非安全闸门/心跳/超时控制），
`slow` 只是视觉降级，`reload()` 需显式调用，`_animate` 禁止刷新活性。
分阶段预算表与优先级见 `RUNTIME_SLOGANS.md` §10.3。本轮**不改**
`fully_superior`、99 模块基线与任何对齐指标。


---

## R29 · 净化边界深度轮 2

| 项 | 风险 | 处置 |
|---|---|---|
| R29 | `sanitize_verb` 原样输出 bidi 覆写/isolate 与零宽字符（终端显示方向可被重排）；非 CSI/OSC 的 ESC 序列只删 ESC 字节；组合标记开头未按文档处理；按码点截断切断 grapheme；净化不保证幂等；内置诊断文案约 52 列且绕过净化层直接进单行 header；`_char_cols` 是第三套宽度算法（`👩‍💻` 算 5 列 vs wcwidth 2 列）；配置接受 `bool`/字符串数字/`NaN`、无读取上限 | 按 Unicode 类别删 `Cc/Cf/Cs/Co/Cn` + 变体选择符；OSC→CSI→通用 ESC→C0/C1 完整剥序列；拒绝开头组合标记；grapheme 簇边界截断；迭代到不动点、不收敛 fail-closed；新增 `_STALL_SHORT`(10 语言) + `SloganView.headline` + `_fit_headline()` 单一出口，诊断态 header 不再挂 `Working (Ns)`；新增 `display_cols()` 并做 500 串与 `tui._display_width` 交叉一致回归；1 MiB 上限 + `_strict_int`/`_strict_ratio` |

如实边界：VS16 删除会让 emoji 呈现退化成文本样式（宽度可预测优先）；
`stall` 仍是启发式可观测提示，非安全闸门/心跳/超时控制；不是真机 TUI
长跑；分叉改动仍未合并。详见 `RUNTIME_SLOGANS.md` §11。本轮**不改**
`fully_superior`、99 模块基线与任何对齐指标。


---

## R30 · 标语一一对应与严格分发

| 项 | 风险 | 处置 |
|---|---|---|
| R30 | 860 条标语零真实接入点（包路径与 docstring 不符、13 处「接入」全是示例）；未知上下文静默飘出无对应事件的标语；8 语种 × 6 场景跨语种英文泄漏；3 条超长内置文案被净化出口截成半句；`_windows`/`_last` 裸 dict 并发复合读写；`min_interval` 接受 `Inf`/`NaN`/字符串；安全告警可能被俏皮话降级 | 包落 `tuan_cli/ui/slogans/` + 根目录 15 个薄垫片；`mapping.py` 18 事件 ↔ 16 上下文 + 1695 条注册表 + 10 项 `audit()` 不变量；`pick_for_event` 未知事件抛异常、`SECURITY_EVENTS` 返回空；240 条补池 + 5 条空组 + 3 条完整短句替换；`pick_local_first` 5400 次分发 0 兜底；净化层抽到 `_clean.py` 并断言同一函数对象；`RLock` / 真 LRU / 严格 `min_interval` |

如实边界：TUI 只建立分发与留痕，**未替换既有 i18n 文案**；英文兜底
词条仍在注册表（各有 event）但本地优先；10 个 `thin_pools` 如实披露未硬凑；
`stall` 仍是启发式可观测提示，非安全闸门；分叉改动仍未合并；第三方
自适应红队仍未做。详见 `SLOGAN_MAPPING.md`。本轮**不改**
`fully_superior`、99 模块基线与任何对齐指标。


---

## R31 · 运行时对应关系闭环

| 项 | 风险 | 处置 |
|---|---|---|
| R31 | TUI 留痕无 `entry_id`（静态表对应上了、运行时反查断掉）；`except Exception: return None` 静默吞掉未知事件异常；全局裸 list 日志跨 TUI 实例互串且 `reset` 会清掉他人记录；`audit()` O(n²) `ids.count` + 每次重跑 1695 条净化（20 次 763.7 ms）；`pick_for_event` 线性扫全表反查（2000 次 58.9 ms）；随机源不可注入无法回放；共享事件 (`model.streaming`) 归属歧义 | 留痕改 7 元组含 `entry_id`/`owner`/`at_ms` + `slogan_trace()`；`_slogan_error()` 必留痕 + `slogan_errors()` + `strict=True` 向上抛；日志按 `owner` 分桶 + `RLock`，快照返回 tuple；`Counter` + `_CLIPPED_IDS` 构建时缓存；`_BY_ID`/`_BY_TEXT` O(1) 索引 + `entry_for_text()` + 第 11 项不变量 `index_consistent`；`rng`/`now`/`owner` 注入 + 一次性局部避重窗口；`SloganEntry.events` 列全部触发事件 |

实测：`20 次 audit 763.7 → 355.6 ms`、`2000 次分发 58.9 → 33.1 ms`、
`index_stats registry/by_id/by_text = 1695/1695/1695`。

如实边界：12 线程压测**未复现**日志长度超限（峰值仍 64），加锁是消除
对 GIL 的依赖而非修复已观测故障；20 次 audit 仍有 355.6 ms 的
`pool_entries` 开销，未加缓存（避免审计依赖缓存时间点）；6 类
`SECURITY_EVENTS` 仍返回空且不绑标语，空串语义靠 `trace.reason` 区分；
TUI 未替换既有 i18n 文案；分叉改动仍未合并；第三方自适应红队仍未做。
详见 `SLOGAN_MAPPING.md` §11。本轮**不改** `fully_superior`、99 模块
基线与任何对齐指标。


---

## R32 · 运行时对应关系补漏

| 项 | 风险 | 处置 |
|---|---|---|
| R32 | `_BY_TEXT` 用原始文案、分发用净化后文案 → 注入含 ZWSP 词条后 `reason='ok'` 但 `entry_id=''` 静默断裂；owner 桶只限长度不限数量（2000 会话 = 2000 桶）且 `close()` 不释放；错误只写 TUI 实例日志、全局日志 0 条；`_MAX_WINDOWS=64` < 真实 key 空间 320 导致避重失效；`index_consistent` 只要求 `by_text > 0` | 新增 `_BY_CLEAN` 净化后索引 + `entry_for_clean()`，未命中即 `index-miss` + 空文案 + 计数，净化撞车检测；`_dispatch_log` → LRU `OrderedDict` + `_MAX_OWNERS=128`，`release_owner()` / `dispatch_log_stats()` / `reset_runtime_counters()`，`close()` 释放；`record_error()` 双层留痕（安全事件仍 `security-notice` 不混）；`_MAX_WINDOWS=384` 按真实维度算；不变量加严为三份索引全等 + 零撞车 + 零运行时 miss + 事件组完整，`AuditReport` 增 3 字段纳入 `ok`/`as_dict()` |

实测：`2000 会话后 owners=128 / decisions=128`、
`index_stats registry/by_id/by_text/by_clean = 1695×4`、
`clipped=0 / clean_collisions=0 / index_misses=0`、
遍历 320 key 后 `len(_windows)=320` 且起始窗口存活。

如实边界：`index-miss` 只抑制标语显示、不改裁决；`release_owner()`
只释放全局桶；128/384 是有界折中，最久未用历史仍被淘汰；冷启动首次
`audit()` 303.9 ms、热态 20 次 37.4 ms、同进程含冷启动 20 次 53.1 ms
——与上一轮 355.6 ms 是**口径差异**，不宣称性能提升。分叉改动仍未
合并；第三方自适应红队仍未做。详见 `SLOGAN_MAPPING.md` §12。
本轮**不改** `fully_superior`、99 模块基线与任何对齐指标。


---

## R33 · 自愈 / 证据保全 / 日志字段净化

| 项 | 风险 | 处置 |
|---|---|---|
| R33 | 累计 `_INDEX_MISSES` 让一次已修复的历史 miss 永久污染 `audit().ok`, 且 `reset_runtime_counters()` 强绑 `reset_dispatch_log()` (实测 `decisions: 21->0`); `close()` 刚记 `session.exit` 就删桶; LRU 只读不刷新致活跃会话被淘汰; `record_error` 的 event/kind 原样写日志 (实测 5030 码点含 OSC8 + RLO), 异常消息进 traceback; `clipped` 与净化后索引口径冲突; 分发侧二次按码点截断破坏簇边界 | 区分 `_UNRESOLVED_MISSES` (连续/fatal, 一次成功即归零) 与 `_INDEX_MISSES` (累计/信息项), 新增 `acknowledge_runtime_misses()`, `reset_runtime_counters(include_dispatch_log=False)` 默认不清日志; `close()` 封存整桶快照到 `slogan_closed_trace()` 再释放, 新增 `take_owner_log()`; `dispatch_log(owner)` 读刷新 LRU (全量读不刷新); `_clean` 拆出 `_clean_once` + 新增 `sanitize_log_field` 共用清理核心, `record_error`/异常消息/TUI 降级路径全净化; `clipped` 降信息项, 新增 `unrenderable`/`unresolved_misses` 为 fatal; 分发与索引共用 `sanitize_verb` 单一出口 |

实测：`一次 miss 后 ok=False / unresolved=1` → `恢复后 ok=True /
累计证据=1 / 日志 2 条`；`注入串 5030 → 121 码点, ESC/RLO/OSC8 全清`；
`高频只读 s-0 存活, s-1 被淘汰`；
`index_stats 1695×4 / unrenderable=0 / collisions=0`。

如实边界：`unresolved_misses` 是**连续**语义, 累计值才是完整历史;
`slogan_closed_trace()` 只保全 close 那一刻快照, 128 桶上界不变;
`sanitize_log_field` 按码点限长不按列宽 (日志不参与渲染), 但与 UI
共用 `_clean_once` 不是第二套净化真值; `index-miss` 只抑制标语显示
不改裁决; 分叉改动仍未合并; 第三方自适应红队仍未做。详见
`SLOGAN_MAPPING.md` §13。本轮**不改** `fully_superior`、99 模块
基线与任何对齐指标。


---

## R34 · owner 归一 / 被动淘汰留痕 / 单一释放出口

| 项 | 风险 | 处置 |
|---|---|---|
| R34 | public 入参 `owner` 全链路未净化 (实测 5033 码点含 OSC8+RLO 进 `SloganDecision.owner` / 桶 key / `slogan_trace()`); 修净化时初版 key 74 码点**不幂等**, 二次归一重算指纹致 `dispatch_log(evil)` 返回 0; `sanitize_log_field(limit=None/nan/inf)` 抛 TypeError/ValueError/OverflowError; LRU 被动淘汰静默丢含 `turn.completed` 的整桶 (D4 只覆盖显式 close); `close()` 与 `take_owner_log()` 两套实现; `_slogan_sealed` 写无锁 | 写入/查询共用 `norm_owner()` (干净零改动, 脏串定长 `owner:<fp16>` 22 码点严格幂等); 新增 `_coerce_log_limit()` 脏值回落默认 120 不抛; 新增 `EvictionRecord` + 有界 `_EVICTED` (64) + `evicted_owner_log()` + stats `evicted_recent`/`evicted_cap` (脱敏、不复活决策、不参与 `ok`); `close()` 收敛 `take_owner_log()` 并加 `_slogan_lock`; 删未使用 `keys` 变量 |

实测：`5033 -> 22` 码点且 ESC/RLO/OSC8 全清、`norm_owner(n)==n`、
`dispatch_log(evil)` 命中；`EvictionRecord(owner='s-0', dropped=2,
last_reason='ok')`；`stats owners=128 / evicted_recent=1 / evicted_cap=64`；
`limit` 的 `None/nan/inf/-1/True/'5'` 全返回 `'abc'`；
`index_stats 1695×4 / audit ok=True`。

如实边界：**A′ 是本轮修 A 时自己引入、再被实测抓回来的**（key 归一
不幂等会让写入与查询静默分叉）；脏 owner 原串不进日志（可读性取舍）；
淘汰记录只保留最近 64 次且不复活决策内容，`evicted_recent` 是观测项
不参与 `audit().ok`；并发压测仍未复现 list 撕裂；不是真机长跑；
TUI 仍未替换既有 i18n 文案；分叉改动仍未合并；第三方自适应红队
仍未做。详见 `SLOGAN_MAPPING.md` §14。本轮**不改** `fully_superior`、
99 模块基线与任何对齐指标。


---

## R35 · 先清理后截断 / 注入时钟贯穿 / 淘汰痕摘要

| 项 | 风险 | 处置 |
|---|---|---|
| R35 | `sanitize_log_field` 先按 `lim*4` 粗切再清理, 实测 `' '*1000+'OK'` 返回空串 (尾部合法内容不可达); 修后暴露连续 ESC 串吞字符 `''*900+'END' -> 'ND'`; 淘汰痕用 `time.monotonic()` 与注入 `now` 两套时钟 (实测 1000000 vs 76564); `last_reason` 掩盖桶内 `error:boom`; `norm_owner` docstring「干净输入零改动」对 >64 码点不精确 | 改为**先 `_clean_once` 迭代到不动点再截断** + `_SCAN_CAP=65536` 扫描上限; 新增 `_ESC_RUN_RE={2,}` 排在 OSC/CSI 之后整体删连续 ESC; `_record(d, at_ms=None)` 接受注入时钟, 5 个分发分支 + `record_error` 全传 `at`; `EvictionRecord` 增排序 `reason_counts` (不含文案/entry_id); 新增 `OWNER_LIMIT=64` 并精确化 docstring |

实测：`' '*1000+'OK' -> 'OK'`（旧 `''`）、
`''*900+'END' -> 'END'`（旧 `'ND'`）、
`'[31m' -> ''`（未误伤 CSI）、
`now=1000.0` 时 `decision.at_ms == eviction.at_ms == 1000000`、
`reason_counts=(('error:boom',1),('ok',2))`、
`index_stats 1695×4 / audit ok=True`。

如实边界：**候选 A（孤立 ESC 残留）实测不成立、未修**
（`_CTRL_RE` 的 `-` 已含 0x1b），只加回归锁住既有正确行为；
`_SCAN_CAP` 之外仍先粗切（实测 `' '*70000+'OK' -> ''`）；
**单个** `'END' -> 'ND'` 是 ECMA-48 固有歧义，未改，ESC 已清除
故无安全风险；超长 owner 全串 sha1 成本未修（2 MiB ≈ 1.7 ms）；
`reason_counts` 不复活决策内容、只保留最近 64 次淘汰、
不参与 `audit().ok`；`tui.py`/`runtime_slogans.py` 文件零改动但
共享 `_clean_once` 对连续 ESC 更保真；并发压测仍未复现 list 撕裂；
不是真机长跑；分叉改动仍未合并；第三方自适应红队仍未做；
**不宣称性能提升**。详见 `SLOGAN_MAPPING.md` §15。
本轮**不改** `fully_superior`、99 模块基线与任何对齐指标。


---

## R36 · ESC+ 引导 / 时钟严格化 / 有界摘要 / 累计淘汰证据

| 项 | 风险 | 处置 |
|---|---|---|
| R36 | 上一轮 ESC_RUN 覆盖缺口: `]8;;evilOK -> 'K'`、`[31mRED -> 'ED'` (OSC/CSI 从 ESC 串最后一个 ESC 匹配, 留孤立 ESC 吞尾部首字符); public 时钟入参 `now=nan/inf/'1000'` 抛异常/产出 4000 位天文数字, `record_error(at_ms='1000')` 把字符串存进 `at_ms`; **本轮自引入** `or _fallback_ms()` 吞掉合法 0; owner 整串 sha1 无上界 (1 MiB ≈12.7 ms); 淘汰只有 `evicted_recent=64`, 无累计 | OSC/CSI 引导改 `+` 整段剥; 新增 `_coerce_ms(value, is_seconds)` 拒绝 bool/非数值/非有限/负值/超上界, 脏值回落真实单调时钟, 三入口统一; 改显式 `ms is None` 保住合法 0; `OWNER_SCAN_CAP=4096` + 头 2048/总长/尾 2048 有界摘要; `_EVICT_TOTAL` + `evicted_total()` + stats/audit 携带 (不参与 `ok`) |

实测：`']8;;evilOK' -> 'OK'`（旧 `'K'`）、
`'[31mRED' -> 'RED'`（旧 `'ED'`）、
`now=nan/inf/'1000'/True/-1/1e300` 全部产出合法正 int；
`now=0 -> 0`、`now=1 -> 1000`、`now=1000.0 -> 1000000`；
100k+`A` vs 100k+`B` 不撞且幂等；64KiB→8MiB 归一均 ≈12–14 ms；
`evicted_recent=64 / evicted_total=114 / audit ok=True`；
`index_stats 1695×4 / index_misses=0`。

如实边界：**A′ 是本轮修 B 时自己引入、再被实测抓回来的**；
**A 是上一轮 ESC_RUN 修复的覆盖缺口**，不是全新洞；四个候选
（3 次不收敛误杀 / 开头组合标记 / lone surrogate 撞车 / kind 净化）
实测不成立、未修；单个 `END` 的 ECMA-48 歧义未解决（ESC 已
清除无安全风险）；`_SCAN_CAP` 之外仍先粗切；有界摘要对「仅中间段
不同」的超长 owner 存在碰撞面；脏时钟注入**不保证可回放**；
`evicted_total` 不参与 `audit().ok`；`tui.py`/`runtime_slogans.py`
文件零改动（本轮推送不含）但共享 `_clean_once` 更保真；并发压测
仍未复现 list 撕裂；不是真机长跑；分叉改动仍未合并；第三方
自适应红队仍未做；**不宣称性能提升**。详见 `SLOGAN_MAPPING.md` §16。
本轮**不改** `fully_superior`、99 模块基线与任何对齐指标。


---

## R37 · 裁剪证据与两个「不该修」的保真度候选

| 项 | 风险 | 处置 |
|---|---|---|
| R37 | `_DISPATCH_CAP=64` 的 `del bucket[:-cap]` 静默裁掉早期决策: 实测一条 `error:boom` + 84 条后桶内 error 消失, 而 `evicted_recent=0`/`evicted_total=0` (**根本没淘汰**), 上一轮淘汰痕只汇总「淘汰时当前桶」覆盖不到; `decisions` 只反映留存条数, 答不出累计分发数; **本轮自引入** reason 种类上限让 64 具体 + `<other>` = 65 键 | 裁剪前先取 `dropped`, 累加 `_DECISIONS_TOTAL`/`_BUCKET_TRIMS`/`_TRIMMED_DECISIONS`/`_TRIMMED_REASONS`(具体种类 ≤64 + `<other>`)/`_TRIMMED_BY_OWNER`; `EvictionRecord` 增 `trimmed_dropped`/`trimmed_reason_counts` 随 LRU 淘汰带走; 新增 `bucket_trim_stats()` + stats 3 字段 + audit 自动携带; cap 改为按具体种类计数 |

实测：`decisions_total=86 / decisions=64 / bucket_trims=22 /
trimmed_decisions=22`；`bucket_trim_stats.reason_counts=
(('error:boom',1),('ok',21))`；淘汰后
`trimmed_reason_counts=(('error:boom',1),('ok',21))`；
`index_stats 1695×4 / audit ok=True`。全部信息项，**不参与 `audit().ok`**。

如实边界：**两个候选确认成立但判定不该修** ——
① 未终止 OSC 吞光整行属 ECMA-48 规范行为，尝试修会让 904 码点
参数残留进入日志（放宽净化）且 120 码点截断后 `END` 仍不可达；
② ZWJ emoji 拆散，但 1695 条词条 ZWJ/VS16/ESC 全为 0，修它要
放宽 Cf 清理并改 `_clusters`/`display_cols`/500 串宽度回归，
实际标语零收益。两者都有可执行回归作证据。
**C′ 是本轮自引入又抓回的 off-by-one**。per-owner 裁剪摘要只在
LRU 淘汰时带走，显式释放不带走（全局累计仍保留）；全局摘要不归属
具体 owner；`<other>` 合并尾部种类。未终止 OSC 歧义、ZWJ 拆散、
`_SCAN_CAP` 之外先粗切三者**未解决**，均有回归锁住当前行为。
`_clean.py`/`tui.py`/`runtime_slogans.py` 逐字节未改，**不在本轮
推送清单**；并发压测仍未复现 list 撕裂；不是真机长跑；分叉改动
仍未合并；第三方自适应红队仍未做；**不宣称性能提升**。
详见 `SLOGAN_MAPPING.md` §17。本轮**不改** `fully_superior`、
99 模块基线与任何对齐指标。


---

## R38 · public 入参类型面：event 守卫与脏 owner 隔离

| 项 | 风险 | 处置 |
|---|---|---|
| R38 | N1: `event` 查表前无类型守卫, `pick_for_event(['a'])` 抛底层 `TypeError: unhashable type: 'list'`, TUI `except UnboundSloganEvent` 接不住、`strict=True` 契约被绕过; N2: `norm_owner` 把 `None/123/True/bytes/list/dict/float` **全部静默折叠成空 key**, 七个脏 owner 共桶且污染默认桶, `dispatch_log(None)` 全量 vs `dispatch_log(123)` 空桶实测 9 条 vs 8 条 | N1: `pick_for_event` 开头 `isinstance` 守卫, 非 str 统一 `UnboundSloganEvent` + 固定占位 `<invalid-event>` (不调用 `str(raw)`); N2: `None` 仍为「无 owner」, 其余非字符串归 `_INVALID_OWNER_KEY="owner:invalid"` 固定隔离桶 (13 码点、严格幂等、写入/查询自动对上); 入口 `_coerce_owner()` 调 `_note_invalid_owner()` 留痕 (类型名过同一净化核心、限长 32、种类上限 32 + `<other>`); `dispatch_log_stats()` 加 `invalid_owner_calls`/`invalid_owner_types`, audit 自动携带, 全清才归零 |

实测：`pick_for_event(['a'])` 从 `TypeError` 变 `UnboundSloganEvent`；
`owners=3 / decisions=9 / invalid_owner_calls=6`、
`dispatch_log(None)=9 / dispatch_log(123)=6 / dispatch_log("")=2 /
dispatch_log("real")=1`；`norm_owner('owner:invalid')` 严格幂等；
`audit ok=True / index_stats 1695×4`。自引入边界 A′–E′ 逐个量过：
20 轮查询不重复计、类名脱敏 33 码点、60 种类型 → 32 具体 +
`<other>`、reset 语义、falsy 非 str 同样隔离；**本轮实测未发现需回修
的自引入缺陷**。

如实边界：**四个候选判定不该修** —— `lang` 非 str 回落默认语种、
`record_error` 的 event/kind 已净化、`sanitize_*` 非 str 返回空、
`owner=None` 同默认桶且 `dispatch_log(None)` 全量（后两条是文档
兼容契约）。**行为变更仅针对错误用法**：非字符串 owner 从默认桶
移到隔离桶，正常字符串/`None`/`''` 零变化；依赖「传数字也进默认桶」
的调用方需改传字符串。固定键有碰撞面（真用字符串
`"owner:invalid"` 会撞脏值桶，已加回归锁住，不宣称零碰撞）。
类型分布最多 32 具体 + 1 `<other>`；超长类名只留前 32 码点 +
省略号。**一条既有源码级断言同步到新契约，不是放宽**
（`t_d5_owner_normalization`）。`_clean.py`/`tui.py`/
`runtime_slogans.py`/`test_runtime_slogans.py` 逐字节未改、**不在
本轮推送清单**；并发压测仍未复现 list 撕裂；不是真机长跑；分叉
改动仍未合并；第三方自适应红队仍未做；**不宣称性能提升**。
详见 `SLOGAN_MAPPING.md` §18。本轮**不改** `fully_superior`、
99 模块基线与任何对齐指标。


---

## R39 · 引擎本体 public 入参面（前九轮只改了 mapping.py）

| 项 | 风险 | 处置 |
|---|---|---|
| R39 | **P1** `now=nan` 抛 ValueError 前已把 `_last_event_at=nan`/`_seq`/`_phase`/`_current` 全写好, 随后 `liveness()`/`snapshot()` 永久抛 → TUI 渲染停摆; 同路径 `'1000'` 抛 TypeError、`inf` 抛 OverflowError、`True` 当 1 秒、`1e308` 合法有限却在 `int(at*1000)` 溢出、注入 clock 脏值/抛异常同样掀 UI; **P2** `note_progress(kind)` 原样进 `EventRecord.kind` (530 码点含 OSC8+RLO); **P3** `str(raw_mode)` 把 5000 码点含 ESC/RLO 的串原样拼进 `source`; **P4** `reset()` 真实时钟 vs 注入 now → 证据链 `[1000000,1001000,1000000]` 倒退 / 两套时间源; **P7** `detail=None/123` 让 `len(detail)` 抛 TypeError, `detail=['a']` 被当字符串遍历; **P8** `load_config(123)` 抛底层 TypeError (`_settings_path` 在 try 之外) | 统一时钟入口 `_now()` + `_coerce_now_value` (有限实数秒、拒 bool/非数值/非有限/负数/>1e9, 校验在**所有字段写入之前**, `0` 显式判 `is None`), 五个 public 出口全走它; P2 `sanitize_log_field(kind,40)` + `"progress"` 回落; P3 `_safe_source()` 统一净化限长 120 + `mode`/阶段键/`str(p)` 净化; P4 `reset()` 沿用 `_last_event_at` (nan/inf 防御, 不改签名); P7 非 str `detail` → `""`; P8 `_settings_path` 挪进 try |

实测：`now=nan` 从「异常 + 半更新 + liveness/snapshot 抛」变「回落
1000.0 + 事件完整生效 + 两者 healthy」；`now=0 -> 0.0`（零值不吞）、
`now=1e308 -> 回落`（不溢出）；`clock` 脏值/抛异常 → `time.monotonic()`；
P2 530 → 41 码点无控制字符；P3 5021 → 54 码点无控制字符；
P4 `[1000000,1001000,1000000] -> [1000000,1001000,1001000]`、
真实时钟 `[1000000,1945418] -> [1000000,1000000]`；P7 非 str →
长度 0/class empty 不抛；P8 `load_config(123) -> 'builtin'`。
`audit ok=True / index_stats 1695×4`。

如实边界：**四个候选判定不该修** —— P5 `phase` 兜底 `waiting_model`
(含不可 hash, 既有 fail-safe)、P6 字符串 `detail` 只记长度/类别
(D3 脱敏契约)、P9 未知阶段键固定 `invalid:budget-phase`、
P10 `sanitize_verb(123)==''`；另锁住 `liveness`/`render`/`snapshot`
纯读。**行为变更仅针对错误用法**，合法 `now`/配置/`kind`、字符串
`detail`、`reset()` 签名零变化。`now` 夹 `[0,1e9]` 秒 (为
`int(at*1000)` 不溢出, 不是业务上限)；`reset()` 与最后证据 `at_ms`
可能相同, 边界靠 `kind="reset"`；不传 `now` 与注入时钟混用时保证
不倒退/不同源混写, 根因仍靠调用方自律。**本轮唯一改动的运行时代码
是 `runtime_slogans.py`**, `mapping.py`/`_clean.py`/`tui.py`/
`ui/slogans/__init__.py`/`test_slogan_mapping.py` 逐字节未改、**不在
本轮推送清单**；既有断言一条未动、一条未放宽；本轮实测未发现需回修
的自引入缺陷 (零值/极大值/clock 抛异常/非 str kind/reset 残留 nan/
`Decimal` 六个边界都量过)；并发压测仍未复现 list 撕裂；不是真机
长跑；分叉改动仍未合并；第三方自适应红队仍未做；**不宣称性能提升**。
详见 `SLOGAN_MAPPING.md` §19。本轮**不改** `fully_superior`、
99 模块基线与任何对齐指标。


---

## R40 · 注入契约与配置切换锚点（同一个 seq 不能对应两个文案）

| 项 | 风险 | 处置 |
|---|---|---|
| R40 | **D** `reload()` 清 `_current` 却不推进 seq / 不记证据, 实测事件后 `seq=1/current='正在刷屏'/evidence.verb='正在刷屏'`, reload 后 `seq=1/current=''`, 而 `render.text='重装后的词'` → **同一 seq 对应两个文案**, 打断 D1 撕裂检测锚点; 第二次 reload 返回 `unchanged` 却照样静默换词; **A** `__init__` 的 `config or load_config()` / `rng or random.Random()` 吞掉 falsy 但合法的注入对象 (实测 `INJECTED→builtin`、注入 rng 调用 0 次、两个同构引擎文案不同, 深度轮 7 A′ 第三次同源); **B** `raw_verbs[:200]` 静默截断 205→200 条且 source 正常路径无提示; **C** `mode=default` + verbs 全不可渲染时 source 正常路径, 用户以为自定义了标语实际全用内置词库 | **D** `unchanged` 真 no-op; `changed` 时新文案取新词池首条 (确定性、不调 rng)、推进 seq、记 `kind="reload"` 证据, `verb` 与屏幕严格相等, 时间戳沿用 `_last_event_at` 与 P4 `reset()` 同源; **A** `config`/`rng` 改显式 `is None` (`lang` 刻意不改, 实测改了会让 `lang=''` 从 zh-CN 变英文); **B** 超 200 条**整段拒绝** `invalid:too-many-verbs`; **C** 全不可渲染对所有 mode 用既有 `invalid:empty-verbs` 拒绝 (复用既有 source) |

实测：`reload` 后 `seq 1→2`、`current = evidence.verb = render.text
= '重装后的词'`、连续 5 次恒为词池首条、真实时钟下
`[1000000,1000000]`；`config/rng` 注入原样保留、`rng.choice` 调用
1 次、两个同构引擎一致、`None` 仍回落出厂值；205 条 →
`invalid:too-many-verbs`、200 条全生效；`default` + 全脏 verbs →
`invalid:empty-verbs`。`audit ok=True / index_stats 1695×4`。

如实边界：**四个候选判定不该修** —— `lang` 的 `or` (改它是行为
退化)、`phase_budgets_ms` 的 `[:10]` (合法键上限 5 < 10, **不可达
代码**)、`snapshot()` 写 `_pools` (确定/幂等/纯内存无害缓存)、
`evidence_seq` 饱和语义 (deque maxlen=16 兼容字段)。**上一轮回归
`test_liveness_is_still_pure_read` 漏检 `_pools`**, 本轮新增
`test_snapshot_populates_pools_deterministically` 补严口径。
**两处行为变更**: (a) >200 条 verbs 从静默截断变整段拒绝，依赖
201+ 条的部署需拆分或减词条; (b) `reload()` 成功后 `current`
从 `""` 变新词池首条且 `seq` +1、多一条 `kind="reload"` 证据
(失败/unchanged/合法 now/正常事件路径零变化)。**一条既有运行时
断言 + 一条上轮独立脚本断言同步到新契约，不是放宽** (原
`current == ""` 改为同时要求新文案/kind/verb/seq/render 对齐，
断言更强)，其余既有断言一条未动。本轮唯一改动的运行时代码是
`runtime_slogans.py`, `mapping.py`/`_clean.py`/`tui.py`/
`ui/slogans/__init__.py`/`test_slogan_mapping.py` 逐字节未改、
**不在本轮推送清单**；净化层连续两轮零改动；本轮实测未发现需
回修的自引入缺陷 (连续第三次，七个边界都量过)；并发压测仍未
复现 list 撕裂；不是真机长跑；分叉改动仍未合并；第三方自适应
红队仍未做；**不宣称性能提升**。详见 `SLOGAN_MAPPING.md` §20。
本轮**不改** `fully_superior`、99 模块基线与任何对齐指标。


---

## R41 · B2 子进程出网边界（完整复现见 `CLAUDE_PARITY.md` §12）

| 项 | 风险 | 处置 |
|---|---|---|
| R41 | `_execute_backend` 算出 `block_net` 却不传给 `local` 分支、也不传 `env`：`verdict.network=False` 在**唯一没有 OS 级出网隔离能力**的后端上静默裸跑；父进程 `GITHUB_TOKEN` / `AWS_SECRET_ACCESS_KEY` 等真实凭据原样进子进程；`worktree_layer._git` 继承完整 `os.environ` 且 `GIT_WORK_TREE`/`GIT_DIR` 可把 git 元数据重定向到工作区外 | `egress.py`（`CredentialBroker` sentinel / `build_child_env` 脏输入空环境 / `enforce_local_egress` local+禁网 fail-closed 拒绝 / `EgressGuard`）+ manager local 分支真传 `env=`；`unattended.py` 落地 `denyInsteadOfPrompting`（默认关、`continue_turn` 结构化、真接 `assess_tool`）；`worktree_boundary.py` 真接 `create`/`create_agent_worktree`(fast-resume 之前)/`_git`，剥重定向变量、拒越界 argv、断言解析后 target 在 workspace 内 |

配置：`sandbox.resource.egress_credential_masking=true`、
`egress_block_local_when_denied=true`（显式关闭报安全降级）、
`permissions.denyInsteadOfPrompting=false`（开启报行为变更 warning）。
**`deny_network_by_default` 仍 false，没翻**。

矩阵：`gap 30 → 26`、`aligned 43 → 45`、`partial 8 → 10`；
`network_default_deny` / `credential_masking` → partial，
`deny_instead_of_prompting` / `worktree_sandbox_escape` → aligned，
**`os_sandbox` 保持 gap**。`fully_superior` 仍 false，
`b_waves_done` 仍 `["B1"]`（B2 未全清）。

如实边界：`inject_headers()` 默认关闭、无出网代理转发进程，
不宣称与 CC「sentinel + 代理注入」完整对等；OS 级默认隔离仍未做；
逐命令 `allowed_domains` 强绑定仍缺；不是真机多平台验证
（Windows Job Object / macOS Seatbelt 未实机跑）；A 线 10 个 pending、
分叉改动、第三方自适应红队仍未完成。新增两个默认 true 的出网开关
确实改变「依赖真实凭据的子进程」行为，已给逃生口并在校验里报降级。

验证：34 例新回归 + 108 例 parity/CLI/headless + 353 例相关批次全绿；
`matrix.validate() == []`、`security_wiring_intact=true`。两条既有计数
断言同步到新基线，**不是放宽**（仍要求总和 99、逐项对应）。


---

## R42 · B2 收尾：域名强绑定的执行层接线（完整复现见 `CLAUDE_PARITY.md` §13）

| 项 | 风险 | 处置 |
|---|---|---|
| R42 | `SandboxProfile` 只有布尔 `network`、`verdict.extra={}` —— 执行层/出网路径没有域名概念；全局白名单只在可绕过的命令文本层生效 | `egress_allowlist.py`（逐命令 `NetworkClaim` / 严格归一化 / `evaluate_claim`）+ `egress_proxy.py`（**真实**本地回环代理，CONNECT/明文 HTTP 主机校验 + sentinel 注入）+ `SandboxProfile.allowed_domains` + manager 三处真接线（`try/finally` 管代理生命周期） |

配置：`sandbox.resource.egress_proxy_enabled=false`（默认；开启报行为变更
warning，会改写子进程 `HTTP_PROXY`/`HTTPS_PROXY`/`ALL_PROXY`、清空
`NO_PROXY`）。只有显式开启 + `strict` 逐命令声明才构造代理。
**`deny_network_by_default` 仍 false，没翻**。

**A′ 自引入自修复**：初版 `normalize_domain` 的 `idna` 编码吞掉 U+200B
ZWSP，`evil\u200b.example → evil.example`，可让不同主机匹配白名单声明。
已加 ASCII + 逐字符白名单，非 ASCII 一律拒绝；脏声明 fail-closed。

矩阵：`aligned 45 → 46`、`partial 10 → 9`、**gap 仍 26**
（partial→aligned 不减少缺口，不靠改口径凑数）；`os_sandbox` 仍 gap、
`credential_masking` 仍 partial（明文 HTTP 注入已真接线，HTTPS CONNECT
隧道看不到 header）、`block_writes_outside_wd` 仍 partial。
`fully_superior` 仍 false，`b_waves_done` 仍 `["B1"]`。

如实边界：HTTPS 隧道内 header 注入不可用（需 TLS MITM + 本地 CA，本轮不做）；
bwrap/seatbelt 无域名级过滤，`allowed_domains` 只是元数据；`undetectable`
是标记不是证明（命令显式 `--noproxy` 可绕过 env 注入）；不支持国际化域名；
不是真机多平台验证。

验证：43 例新回归（含真 socket 代理端到端）+ 合并批次全绿；
`matrix.validate() == []`、`verify_doc_numbers.py problems == []`。
两条既有计数断言同步到新基线，**不是放宽**。


---

## R43 · 深度轮：四条执行分支共用同一个出网/凭据出口（见 `CLAUDE_PARITY.md` §14）

| 项 | 风险 | 处置 |
|---|---|---|
| R43-A | §13 的强绑定只接在 `_execute_backend` 的 **local 分支**；强后端三条路径完全没有 EgressGuard / claim 检查 / 代理 env / `last_egress` | `egress_plan.py`（`plan_egress` 单一出口 + `plan_is_consistent_with_verdict` 派生一致性）+ manager 四分支统一 `plan.env` 与 `last_egress` |
| R43-B | `SandboxProfile.allowed_domains` 在整个 provider 文件里只出现 1 次（字段定义），**无后端消费** → strict claim 在强后端完全失效 | 不假装后端能按域名放行：真正逐命令声明（`source=tool_args`）+ 强后端 **默认 fail-closed 拒绝**；全局回落（`global_policy`）沿用文本层语义，既有部署不破坏 |
| R43-C | **`run_syscall_sandboxed` 根本没有 `env` 参数**，Job Object / seccomp / 所有 fallback 的 `Popen` 继承父进程完整环境，真实密钥原样进子进程 | `arch/platform.py` 三入口全加 `env` 并透传 `Popen` / `os.execvpe` / `unshare -n` / fallback；`env=None` 保持继承语义向后兼容 |

配置：`sandbox.resource.strict_claim_strong_backend` = `deny`（默认）|
`metadata_only`（显式降级）。schema 只认两枚举、拼错阻断；`metadata_only`
报安全降级 warning；`tuan harden status` 打印策略并列入待加固项。
**`deny_network_by_default` 仍 false，没翻。**

**A′（自己引入自己抓回）**：统一 `to_audit_dict()` 漏了 `allowed` 字段
（B2 首轮既有可观测契约），`test_b2_boundaries` 直接 `KeyError` ——
闸门锁紧了监控却看不到 `allowed=false`，批次 A 抓回已补。另 3 条既有断言
因签名变更同步且**全部改强**（要求真拿到脱敏 env），不是放宽。

矩阵：**一个状态没动** —— `aligned 46 / partial 9 / gap 26`、
`fully_superior=false`、`b_waves_done=["B1"]`。catalog 两条 note 补纠偏说明
但 `status`/`evidence` 结构不变，`matrix.validate()` 与
`evidence.verify_evidence()` 均空。新增回归把计数逐项钉死。

如实边界：HTTPS CONNECT 隧道内 header 注入仍不可用（需 TLS MITM +
本地 CA，`credential_masking` 仍 partial）；bwrap/seatbelt/seccomp 无域名级
过滤，`allowed_domains` 仍是元数据；`metadata_only` 是真实降级；
`undetectable` 是标记不是证明；`os_sandbox` 仍 gap、
`block_writes_outside_wd` 仍 partial；不是真机多平台验证；
`test_platform_portability.py` 长批次多次 502/超时只跑到约 51% 且零失败，
按未完整跑完如实报告；`test_arch_security.py` 1 例失败上一轮 baseline
control 已证是既有环境行为，没为变绿改策略。

验证：`test_b2s_egress_uniform.py` + `test_b2_egress_strict.py` **80 passed**；
合并批次 A **341 passed**；逐文件 arch_platform 10 / arch_security_fixes 6 /
proc 5 / risk_sandbox 14 passed；`verify_doc_numbers.py problems == []`。


---

## R44 · 深度轮：终态拒绝不回落 + 内层占位符保全（见 `CLAUDE_PARITY.md` §15）

| 项 | 风险 | 处置 |
|---|---|---|
| R44-A | `tools/shell.py::_route_sandbox_isolation` 用 `verdict.enforced / backend_available` 判断是否采纳隔离结果；plan 拒绝结果天然 `enforced=False`，`enforce_required=false` 且无强后端时返回 `None` → **被拒命令在真实工作区裸跑一遍** | `SandboxExecResult.terminal_refusal` 把「终态安全拒绝」与「隔离是否生效」解耦；路由**优先**检查它并无条件返回 `[错误] <拒绝原因>`，绝不回落 |
| R44-B | `copy_diff_apply` 在拒绝后仍走 diff/确认流程，把合规拒绝伪装成用户主动拒绝，还无条件 `verdict.enforced=True` 宣称已隔离执行 | 检测到 `terminal_refusal` 立刻返回：不建 diff、不要确认、不设 `enforced=True`、展示真实拒绝原因 |
| R44-C | `SandboxProvider._sanitize_env` 按键名把 `tuan-egress-sentinel-v1:<fp>` 占位符也抹成空串（§14 只验了传给 `provider.run` 的参数，没验子进程实收值） | `core/security_utils.py` 新增 `is_masked_placeholder()`；provider 按**值**保留占位符，真实值仍按键名抹空；全局 `sanitize_env` 语义不变 |
| R44-D | `SECRET_HINTS` 含 `"TUAN_"`，三个强后端的 `TUAN_WORKSPACE` 被抹空且没补回 | 四个后端统一以 `workspace` 参数为准补回，不信任外部 env 假路径 |

**两处必须配合**：先堵回落才能去掉 `verdict.enforced=True`，否则修语义
谎言会变成放开裸跑。

**A′（自己引入自己抓回）**：注释里带 `\n` 的文案示例被 Python 三引号
解释成真实换行，`py_compile` 报 `SyntaxError`（manager.py:496），改成
不含反斜杠的文案后恢复。

**四个「不该修」**（都配可执行回归）：`last_egress` 并发撕裂未复现
（双线程 × 200 次 0 撕裂，GIL 兜住，本轮不加锁、不宣称线程安全）；
`cmd_safe.py` 只查可用性；`orchestration.py` 只挂 ctx、全仓无 `.run()`
调用点（新增源码扫描，并标注未来若下游自己调 `ctx.sandbox_provider.run()`
会绕过整套 `plan_egress`）；全局 `sanitize_env` 行为不变。

矩阵：**一个状态没动** —— `aligned 46 / partial 9 / gap 26`、
`fully_superior=false`、`b_waves_done=["B1"]`。catalog 两条 note 补第三轮
纠偏说明但 `status`/`evidence` 结构不变，`matrix.validate()` 与
`evidence.verify_evidence()` 均空。新增回归把计数逐项钉死。

如实边界：HTTPS CONNECT 隧道内 header 注入仍不可用（`credential_masking`
仍 partial）；bwrap/seatbelt/seccomp 无域名级过滤、`allowed_domains` 仍是
元数据；R44-C 当前默认配置下**不产生已观测危害**（强后端被拒绝、不启
代理），修的是接线一致性，不夸大；`os_sandbox` 仍 gap、
`deny_network_by_default` 仍 false 未翻、`block_writes_outside_wd` 仍
partial；不是真机多平台验证，`test_platform_portability.py` 长批次上一轮
只跑到约 51% 零失败、本轮未重跑；`test_arch_security.py` 1 例失败上一轮
baseline control 已证是既有环境行为，没为变绿改策略。

验证（按分批报告，批次间有重叠、不累加）：本轮 + 上两轮 **106 passed**；
shell 路由影响面 **99 passed**；parity + 配置 + 安全回归 **170 passed**；
sandbox/platform/proc 逐文件合计 **91 passed**；
`verify_doc_numbers.py problems == []`。


---

## R45 · 深度轮：`decided` 单一契约 + 执行层异常文本净化（见 `CLAUDE_PARITY.md` §16）

| 项 | 风险 | 处置 |
|---|---|---|
| R45-A | 路由用 `verdict.enforced / backend_available`（裁决字段）判断是否采纳结果。降级部署里 local 分支**已真实执行命令**却返回 `None`，`run_shell` 再裸跑第二遍 —— **命令双重执行**，隔离层脱敏 env / 出网裁决全部白做 | `SandboxExecResult.decided: bool = True`（默认 fail-closed）；路由只问 `res.decided`，唯一合法回落是 `not verdict.isolate` 显式 `decided=False` |
| R45-B | 执行层异常 / 超时 / 强后端崩溃 / `isolate_workdir` 失败都返回 `enforced=False` → 同一条回落路径 | 所有失败分支显式 `decided=True`；路由自身 `except` 也返回终态错误文本 |
| R45-C | `copy_diff_apply` 的 `isolate_workdir` 异常时旧实现 `enforced=True` **宣称已隔离执行**（副本都没建），且 `res.enforced` 在路由里从未被消费 | 如实 `enforced=False`；对 `res.returncode < 0` 也立刻返回，不建 diff、不弹确认 |
| R45-D | `except` 分支把 `str(exc)` 原样放进 `res.error` 并回显，实测 `GITHUB_TOKEN=ghp_...` 与 OSC 8 / RLO 进用户终端 | `core/security_utils.safe_error_text()`：非 str 只取类型名 → 剥离 Cc/Cf/bidi/OSC → 复用 `redact_sensitive()` → 限长 400；净化在**来源处**做，出口不二次净化以保留 diff 预览可读性 |

**A′（自己引入自己抓回）**：`test_no_second_sanitization_at_route_exit`
初版断言 `count("safe_error_text") == 1`，实测是 2（同一 except 分支里
import + 调用）。断言改成「次数 2 + 出口原样使用 `res.error` + 不出现
`safe_error_text(res.error`」。测试断言写错，不是代码缺陷。

**三个「不该修」**（都配可执行回归）：未终止 OSC 参数残留（ESC/BEL/RLO
已剥离，终端不会再解释）；全局 `redact_sensitive` 行为不变（避免影响
审计日志 / MCP 审计 / 导出链路）；`cmd_safe.py` / `orchestration.py`
仍不是执行侧门（沿用 §15 源码扫描）。

矩阵：**一个状态没动** —— `aligned 46 / partial 9 / gap 26`、
`fully_superior=false`、`b_waves_done=["B1"]`。catalog 两条 note 补第四轮
纠偏指向但 `status`/`evidence` 结构不变，`matrix.validate()` 与
`evidence.verify_evidence()` 均空。新增回归把计数逐项钉死。

如实边界：HTTPS CONNECT 隧道内 header 注入仍不可用
（`credential_masking` 仍 partial）；bwrap/seatbelt/seccomp 无域名级过滤、
`allowed_domains` 仍是元数据；**`decided` 默认 True 是行为变更**，依赖
旧回落语义的第三方集成需核对；`safe_error_text` 只处理执行层异常消息，
diff 预览正文仍原样回显；`os_sandbox` 仍 gap、
`deny_network_by_default` 仍 false 未翻、`block_writes_outside_wd` 仍
partial；不是真机多平台验证，`test_platform_portability.py` 长批次
§14 轮只跑到约 51% 零失败、本轮未重跑；`test_arch_security.py` 1 例
失败已由 baseline control 证明是既有环境行为，没为变绿改策略。

验证（按分批报告，批次间有重叠、不累加）：本轮 + 上三轮 + boundaries
+ claude_parity **227 passed**；shell 路由影响面 **99 passed**；
parity + 配置 + 安全回归 **170 passed**；sandbox/platform/proc/e1e7
逐文件合计 **130 passed**；`verify_doc_numbers.py problems == []`。


---

## R46 · 深度轮：`! cmd` 后台执行侧门（完整复现见 `CLAUDE_PARITY.md` 末尾）

| 项 | 风险 | 处置 |
|---|---|---|
| R46-A | `run_shell` 的 `is_bg_command` 分支在 `_pre_exec_guard` 与 `_route_sandbox_isolation` **之前** return。实测带 `isolate=True` 裁决的 `! cmd`：隔离层 0 次、bare `Popen` 1 次，整条 plan_egress / 沙箱 / 出网合规 / 脱敏链路被绕过。`decided` 契约只管主链路路由返回值，覆盖不到 | `_start_background` 读 `ctx._sandbox_verdict`，`isolate=True` → **fail-closed 拒绝**，提示去掉 `!` 走前台 |
| R46-B | `BackgroundShellManager.start` 的 Popen 不传 env，后台子进程继承父进程完整环境，真实 `GITHUB_TOKEN` 原样进入不受出网管控的异步进程 | `start` / `run_in_background` 增加 `env` 形参（`None` 保持继承语义向后兼容），调用方显式传 `sanitize_env()` + 补 `TUAN_WORKSPACE` |

## R47 · 深度轮：对外 MCP `run_shell` 侧门 + `safe_exception_text` 收口

| 项 | 风险 | 处置 |
|---|---|---|
| R47-A | `ecosystem/mcp_server.py::_h_run_shell` 是全仓唯一「外部 Agent 直接给 `command` + `shell=True`」入口，却只做文本红线、不经过四层滤网 / `plan_egress`；fuzz 已证文本层可绕过 | 接 `SandboxManager.assess_command`：DENY / CONFIRM / `isolate=True` 一律 fail-closed 拒绝；接 `plan_egress(verdict, "local", ...)`：`allowed=False` 拒绝。backend 固定 `local`，绝不假装已隔离 |
| R47-B | `subprocess.run` 不传 env，实测真实密钥原样进子进程（与 §13/§15 矛盾） | `plan.env`（sentinel 脱敏）显式传给 `subprocess.run`，补 `TUAN_WORKSPACE`；工具描述如实标注「没有 OS 级隔离 / 逐命令域名强绑定 / 副本确认」 |
| R47-C | `str(exc)` 原样回显（MCP 3 处 + `shell.py` 5 处 + `background_shell.py` 1 处），真实密钥串与 OSC/RLO 外泄 | 全部 12 处错误出口统一走 `safe_exception_text` |
| R47-D | 上一轮 `f"{type(exc).__name__}: {safe_error_text(str(exc))}"` 中 `str(exc)` 在**调用方**先执行；实测异常对象 `__str__` 抛错掀翻整个 `except` 分支 | `safe_exception_text()` 把 `str(exc)` 包进 try，异常时丢弃原文只留类型名；正常时复用 `safe_error_text` |

**章节编号纠偏**：`CLAUDE_PARITY.md` / `SECURITY.md` / `SECURITY_EN.md` /
`SLOGAN_MAPPING.md` 各有 §17 且指代四个不同主题；上一轮后台注释引用
「§17」实际指向不存在。本轮改用自足标题 + 代码注释改自足描述，**不做
全局重编号**。

**三个「不该修」**（都配可执行回归）：`ignored` 死字段与 `decided` 不冲突
（全仓零构造点）；`verdict.enforced` 全仓无消费点但不删（删除会改变
verdict 状态）；`artifact_tool.py` / `code.py` 的 Popen 打开编辑器/文件、
不执行用户 shell 命令。

**A′ ×2**：批量替换破坏两处多行 f-string 拼接（已改 `+`）；上一轮测试
固定 2600 字符窗口切片被注释变长挤出、且实际代码是
`safe_exception_text`（断言改用 `inspect.getsource`）。均为测试/替换
脆弱性，不是代码回归。

矩阵：**一个状态没动** —— `aligned 46 / partial 9 / gap 26`、
`fully_superior=false`、`b_waves_done=["B1"]`；catalog 两条 note 补第五/六
轮纠偏指向但 `status`/`evidence` 结构不变，`matrix.validate()` 与
`evidence.verify_evidence()` 均空。

如实边界：**MCP 通道仍没有 OS 级隔离 / 域名强绑定 / 副本确认**，本轮做的是
fail-closed 拒绝 + 脱敏 env，`credential_masking` 仍 partial；后台/MCP 都是
**行为变更**；`ctx` 无 `_sandbox_verdict` 时后台不拦（裁决链上游边界，
不伪造裁决、不靠文本猜高危）；`safe_exception_text` 只覆盖异常消息，
diff 预览正文仍原样回显；`os_sandbox` 仍 gap、`deny_network_by_default`
仍 false 未翻、`block_writes_outside_wd` 仍 partial；不是真机多平台
验证，长批次多次 502/超时按分批如实报告；`test_arch_security.py`
1 例失败已由 baseline control 证明是既有环境行为。

验证（按分批报告，批次间有重叠、不累加）：本轮 + 并行线 + 上四轮
**276 passed**；shell/后台影响面 **82 passed**；parity + 配置 + 安全回归
**78 passed**；sandbox/platform/proc/e1e7 逐文件 **130 passed**（沿用
§16 分批结果）；`verify_doc_numbers.py problems == []`。
新增 `tests/test_b2se_background_side_door.py`（约 24 例）与
`tests/test_b2su_mcp_shell_gate.py`（约 25 例）。


---

## R48 · 深度轮：工具层写路径硬边界 + `/add-dir` 口径纠偏 + `edit_files` 真事务

完整复现见 `CLAUDE_PARITY.md` 末尾「深度轮（续二）」。沿用自足标题，
不新增数字章节编号。

| 项 | 风险 | 处置 |
|---|---|---|
| R48-W1 | `permissions.blockWritesOutsideWorkingDirectories` 代码里 0 命中；`filesystem._resolve` 只做读路径裁决、读写不分；CC v2.1.314 在 Write/Edit/NotebookEdit 工具层硬拒绝 | 新增 `core/write_boundary.py` 单一裁决出口 + `filesystem._resolve_write`，六处写操作统一走它；默认值 `false` 与 CC 出厂一致，**不做破坏性默认变更** |
| R48-W2 | `/add-dir` 三处文案写「仅读」，实测 `write_file` / `move_file` / `delete_file` 全部越界放行 —— 确认对话不是路径硬边界 | 文案改如实；`authorize_extra_dir(..., writable=False)`，普通授权只授读，`--writable` 显式登记可写根（per-session 内存态，Agent 无自助授权工具）；系统关键目录仍拒 |
| R48-W3 | `edit_files` 危险内容扫描在阶段 2 边写边扫：第 3 项含 `rm -rf /` 时前 2 项已落盘 `BBB`，返回文本却写「未写入任何文件」 | 扫描前移到阶段 1；写入前对**全体**目标复检；阶段 2 循环内无拒绝分支 |
| R48-C | 配置值拼错成 `"true"` / `1` 时 `bool()` 会静默放行或行为突变 | 非 bool → fail-closed 启用并给出 reason；`security_schema` 在校验阶段直接报错；`harden status` 显示当前生效状态 |

**三个「不该修」**（都配可执行回归）：读路径不受影响；
`artifact_tool.py` / `worktree_layer.py` 写的是 `workspace/.tuan/...`
固定内部路径、非用户任意路径（源码扫描锁住）；`move_file` 源是读、
目标是写。

**A′**：`harden status` 初版给 `_CfgProbe` 写了 `get()`，但
`write_boundary` 读 `ctx.config()`；且调用了依赖 `ctx.workspace` 的
`allowed_roots()`。自查后改为 `config()` 并去掉 workspace 依赖。

**仍为 `partial` 不标 `aligned`**：命令层重定向
(`echo x > /tmp/out`) 不在工具层约束内（CC 靠 sandbox 规则覆盖）；
出厂默认仍 `false`；TOCTOU 二次解析与 `os.replace` 之间仍有窗口
（彻底消除需 `O_NOFOLLOW` + `dir_fd`，会改动既有原子写实现）。

**矩阵一个状态没动**：`aligned 46 / partial 9 / gap 26`、
`fully_superior=false`、`b_waves_done=["B1"]`；catalog 该条 note 补纠偏但
`status`/`evidence` 结构不变；`matrix.validate()` 与
`evidence.verify_evidence()` 均空。

**如实边界**：默认不改既有行为（旧文案是错的，已改如实）；开启开关与
W3 修复都是**行为变更**；阶段 2 因 OS 错误中途失败仍可能部分落盘，
不是本轮引入也不谎称「完全事务」；`os_sandbox` 仍 gap、
`deny_network_by_default` 仍 false 未翻、`credential_masking` 仍 partial；
A 线 10 pending、分叉改动、第三方自适应红队未做；不是真机多平台验证，
Windows 路径未实测。标语引擎 / 净化层 / `mapping.py` / `tui.py` /
`runtime_slogans.py` 逐字节未改。

**验证（按分批报告，批次间有重叠、不累加）**：本轮新回归 **38 passed**；
路径/编辑/读守卫/工作区（6 文件）**119 passed / 1 skipped**；
config / harden / slash / parity（7 文件）**114 passed**；
`verify_doc_numbers.py problems == []`；8 个改动 Python 文件
`py_compile` OK。端到端实测：开关关闭时既有 `/add-dir` 写行为不变；
开启后 write / edit / move / delete / delete_dir 五类全部拒绝且磁盘零变更，
读仍可读；`--writable` 放行；W3 场景三个文件全部保持 `AAA`。
新增 `tests/test_b2su_write_boundary.py`（38 例）。


---

## R49 · B3 深度轮：Hooks 扩展事件 / CC 原生协议 / `updatedInput` 校验

完整复现见 `CLAUDE_PARITY.md` 末尾「深度轮（续三）」。沿用自足标题。

| 项 | 风险 | 处置 |
|---|---|---|
| R49-R1 | 扩展事件配置（含拼错事件名）被**静默丢弃**且零报错 | 事件表 8→15，未知事件键 `unknown_hook_event` 显式审计 |
| R49-R2 | 决策类事件走通知通道时 stdout 被吞，拦截器形同虚设 | 4 个决策类事件独立 `run_decision()` 裁决出口（复用 B1 fail-closed），误路由留痕拒绝 |
| R49-R3 | CC 原生 `hookSpecificOutput`（`permissionDecision` / `updatedInput`）被完全忽略 | `_parse_decision` 协议兼容；`ask` 无确认通道 fail-closed；advisory 无注入通道只留痕 |
| R49-R4 | hook 改参未知键原样进 `tool.handler(ctx, **args)` → `TypeError`；且旧实现替换掉必需参数 | 新增 `hooks/input_validation.py`：有 schema 丢未知键 + required/type/enum 校验，不符即 deny；无 schema 保守子集且 `enforced=False`。`tools/base.py` 传 `tool.parameters` |

**接线**：`/add-dir` 授权成功 → `DirectoryAdded`（失败不触发、
`--writable` 透传）；危险工具审批前 → `PermissionRequest`
（**只允许收紧**，hook 的 `allow` 不能跳过 `ctx.confirm`）；
`arch/execution.py` 的 `ToolCall` 加可选 `tool_schema`。

**两个 B3 条目仍 `STATUS_GAP`**：`ConfigChange` / `WorktreeCreate` /
`Elicitation` / `ElicitationResult` + `Notification` **没有本地生产
触发点**；官方事件面远大于 7 个；CC exit-code-2 → decline 未实现；
`arch/execution.py` / `cmd_hooks.py` 两条旁路拿不到 schema。
catalog note 补纠偏但 `status`/`evidence` 结构不变。

**三处既有断言同步（不是放宽）**：事件表 8→15 且新增扩展事件逐项
枚举；两条「hook 可注入新键」断言改为「既有键改写生效 **且** 新键被丢弃」。

**A′**：`_parse_decision` 改实例方法漏删 `@staticmethod`，12 条既有测试
`TypeError`；自查后删除装饰器。替换脆弱性，不是代码回归。

**矩阵一个状态没动**：`aligned 46 / partial 9 / gap 26`、
`fully_superior=false`、`b_waves_done=["B1"]`；
`matrix.validate()` 与 `evidence.verify_evidence()` 均空。

**如实边界**：5 个扩展事件只有引擎无触发点；无 schema 旁路只是保守
子集；`PermissionRequest` 刻意比 CC 更严格；**行为变更**：hook 改参
不再能注入新键，旧 `{"args":...}` 同样走校验；`os_sandbox` 仍 gap、
`deny_network_by_default` 仍 false 未翻、`credential_masking` 仍 partial；
A 线 10 pending、分叉改动、第三方自适应红队未做；不是真机多平台验证。
标语引擎 / 净化层 / `mapping.py` / `tui.py` / `runtime_slogans.py`
逐字节未改。

**验证（按分批，批次间有重叠、不累加）**：B3 新回归 + 5 个 hooks
既有文件 **83 passed**；parity / 写边界 / 两条侧门 / B2 各轮 / config /
slash **356 passed**；`verify_doc_numbers.py problems == []`；
`py_compile` 全 OK。新增 `tests/test_b3_hooks_extended.py`。


---

## R50 · B3 续轮：5 个扩展事件生产触发点 + 旁路契约

完整复现见 `CLAUDE_PARITY.md` 末尾「深度轮（续四）」。沿用自足标题。

| 项 | 风险 | 处置 |
|---|---|---|
| R50-R1 | 5 个事件配置能加载、引擎能裁决，但真实操作 hook 触发 **0 次**、源码 5 个派发点 **0 命中** | 新增 `hooks/triggers.py` 统一触发层，接上 5 个生产触发点；无 hooks 严格 no-op、裁决通道异常 fail-closed |
| R50-R2 | `tuan hooks test --event PermissionRequest` 被 misrouted 拒绝且静默不执行 | 决策类 4 事件改走 `run_decision` |
| R50-R3 | `cmd_hooks.run_pre` 无 schema，改参只走保守子集 | 从工具注册表取 schema，取不到如实标 `enforced=False` |
| R50-R4 | `ToolPipeline` 无生产构造方；强传 `tool_schema=` 让老式 mock `TypeError` | 加 `schema_resolver`，只在有 schema 时传关键字（兼容老式签名） |

**接线**：`Config.set_user/delete_user` + `ManagedSettings.reload` →
`ConfigChange`；`WorktreeLayer.create/create_agent_worktree` →
`WorktreeCreate`（**任何 FS 改动前可拒绝**，含 fast-resume）；
`_ask_user_handler` + ACP `ask_user` → `Elicitation` /
`ElicitationResult`（**可取消/作废，绝不代答、绝不覆盖用户答案**）；
`remote_control.notify` 所有返回路径前 + `SecurityAlerter` 后台线程 →
`Notification`；`app.py` 注入 `lambda: agent.ctx.hooks`。

**两个 B3 条目仍 `STATUS_GAP`**：官方事件面远大于 7 个、exit-code-2
未实现、Elicitation 语义不等价、`ToolPipeline` 无生产调用链、
`cmd_hooks` 取 schema 依赖 kernel 暴露 `tool_registry`。catalog note 补
纠偏但 `status`/`evidence` 结构不变，**不靠改口径凑数**。

**三处断言同步（不是放宽）**：「5 事件无触发点」改为逐一验证 5 方法 +
11 处接线 + provider + 分类（更强）；`test_arch_security_fixes.py` 既有
`FakeHooks` 测试原样保留零修改。

**A′ ×2**：`notify` 的提前返回让 Notification 永不触发（移到所有返回
路径之前）；`ToolPipeline` 强传关键字破坏老式 mock（改为条件传）。接线
脆弱性，不是原有代码回归。

**矩阵一个状态没动**：`aligned 46 / partial 9 / gap 26`、
`fully_superior=false`、`b_waves_done=["B1"]`；`matrix.validate()` 与
`evidence.verify_evidence()` 均空。

**如实边界**：7 事件有触发点 ≠ 全事件对齐；`ToolPipeline` 无生产调用链；
**行为变更**（WorktreeCreate 真能拒绝、Elicitation 能取消/作废、
Config/notify 会派发已配 hook）；Notification 后台线程派发；
`os_sandbox` 仍 gap、`deny_network_by_default` 仍 false 未翻、
`credential_masking` 仍 partial；A 线 10 pending、分叉改动、第三方自适应
红队未做；不是真机多平台验证。标语引擎 / 净化层 / `mapping.py` /
`tui.py` / `runtime_slogans.py` 逐字节未改。

**验证（按分批，批次间有重叠、不累加）**：B3 续轮 + 上一轮 B3 + 5 个
hooks 既有文件 **97 passed**；最终合并批次见报告；
`verify_doc_numbers.py problems == []`；`py_compile` 全 OK。新增
`tests/test_b3s_triggers.py`（真 git init + 真 `git worktree add` 的
5 事件端到端触发）。


---

## R51 · B3 续轮 V：接线之后的第二层

完整复现见 `CLAUDE_PARITY.md` 末尾「深度轮（续五）」。自足标题。

| 项 | 风险 | 处置 |
|---|---|---|
| R51-C1 | `dump_yaml` 吞掉写盘失败返回 `None`，`Config.set_user` 磁盘上**没有文件**却派发 `ConfigChange`，与上一轮 `ManagedSettings.reload` 的「失败不派发」契约矛盾 | 拆出 `_dump_yaml_impl` + `dump_yaml_checked` 如实返回成败；只在 `ok` 时派发；**`dump_yaml` 行为逐值不变**；新增 `last_write_persisted` |
| R51-C2 | in-process hook 里再写配置递归 **247 层**，`RecursionError` 也被吞，每层仍继续派发 | thread-local 重入守卫：通知类跳过计数、决策类 **fail-closed** `reentry_suppressed`；`try/finally` 清理；跨线程并发不抑制 |
| R51-C3 | 上一轮只查 `triggers.py` 字符串，没核对 `manager.py` 分类常量 | 补真值回归（查 `_NOTIFY_EVENTS` / `_DECISION_EVENTS`），不改产品代码 |
| R51-C4 | 两次 `set_default_hooks_provider(A)/(B)` 后 A 零触发、B 代收 | `app.py` 显式回填 `config._hooks` 修掉主链路；`provider_diagnostics()` 让覆盖可见。**模块级入口仍可能串台，未宣称多会话已隔离** |
| R51-C5/C6 | payload 不含配置值 / delete False 不派发 | 判定不该修，加回归锁住 |

**刻意不做**：不回读比对值（序列化差异假阴性 + 避免文件系统时间点
判定）；跨进程 command hook 不靠守卫（子进程不继承 thread-local，
天然不递归，如实标注）；不改 5 个模块级子系统签名去接 owner。

**两个 B3 条目仍 `STATUS_GAP`**：官方事件面远大于 7 个、exit-code-2
未实现、Elicitation 语义不等价、`ToolPipeline` 无生产构造方、
`cmd_hooks` 取 schema 依赖 kernel 暴露 `tool_registry`。本轮修的是
「已接线触发点的正确性」不是覆盖面；`catalog.py` **零改动**，
`status`/`evidence` 结构不变，**不靠改口径凑数**。

**断言同步（不是放宽）**：`tests/test_b3s_triggers.py` 与
`test_b3_hooks_extended.py` 一条未改；C3 升级为常量真值断言；矩阵
计数逐项钉死。

**A′ ×2**（新写测试自身）：写盘失败 delete 用例走错分支（改
monkeypatch 写盘出口）；子进程校验用 `str` 而非 `Path` 导致
`AttributeError`（改 `Path(...)`）。产品代码零回归。

**矩阵一个状态没动**：`aligned 46 / partial 9 / gap 26`、
`fully_superior=false`、`b_waves_done=["B1"]`；`matrix.validate()` 与
`evidence.verify_evidence()` 均空。

**如实边界**：C4 未完全修；写盘失败时内存视图仍更新（既有行为，
重启后丢失）；并发外部改写不在检测范围；**行为变更**（写盘失败不再
派发 ConfigChange、app.py 回填 `config._hooks`）；`os_sandbox` 仍 gap、
`deny_network_by_default` 仍 false 未翻、`credential_masking` 仍
partial；A 线 10 pending、分叉改动、第三方自适应红队未做；不是真机
多平台验证。标语引擎 / 净化层 / `mapping.py` / `tui.py` /
`runtime_slogans.py` 逐字节未改。

**验证（按分批，批次间有重叠、不累加）**：B3 续轮 V + 上一轮 B3 +
5 个 hooks 既有文件 + mixin + config 系列 **182 passed**；宽合并批次
见报告；`verify_doc_numbers.py problems == []`；`py_compile` 全 OK。
新增 `tests/test_b3v_depth.py`（真子进程 / 4 线程并发 / 决策重入
fail-closed / 单一实现扫描 / 矩阵钉死）。


---

## R52 · B3 续轮 VI：C4 收尾（模块级入口的真正会话绑定）

完整复现见 `CLAUDE_PARITY.md` 末尾「深度轮（续六）」。自足标题。

| 项 | 风险 | 处置 |
|---|---|---|
| R52-A | `HookTrigger._effective()` 每次派发才读全局 provider，A 构造的 trigger 在 B 覆盖后派到 B | **构造时冻结** + `owner=` 查 registry；`_effective()` 不再读全局；`owner` 查不到不回落 default |
| R52-C | `SecurityAlerter` 后台线程现场 `HookTrigger()`，A 订阅 B 覆盖后派到 B | 实例级 `self.hooks`，构造时捕获 |
| R52-D | `remote_control.notify()` 无 hooks 入参，归属取决于派发时刻 | 单例级 `_rc.hooks` + 可选关键字 `hooks`；`rc is None` 仍派发 |
| R52-E | ACP `KernelAcpBridge.ask_user` 无绑定 | `self.hooks`；全仓无参 `HookTrigger()` 代码消费点为 0 |
| R52-B | `get_alerter()` 单例忽略第二次 `home` | **判定不该修**，回归锁住 `x is y`；`bind_session_hooks()` 让串行切换正确 |

**新增机制**：按 owner 分桶的 session registry（64 上界**拒绝**而非
LRU 静默淘汰；`hooks=None` 合法、注销不靠 `pop` 判空）、
`current_session_hooks()` 构造时刻快照、`bind_session_hooks()` 注册 +
回填已存在的两个进程级单例（只改属性不改身份）。
`security_plugin.py` 传 `config._hooks`；`app.py` 在
`set_default_hooks_provider` **之后**调用 `bind_session_hooks`。

**两个 B3 条目仍 `STATUS_GAP`**：官方事件面远大于 7 个、exit-code-2
未实现、Elicitation 语义不等价、`ToolPipeline` 无生产构造方、
`cmd_hooks` 取 schema 依赖 kernel 暴露 `tool_registry`。本轮修的是
「已接线触发点的会话归属」不是覆盖面；`catalog.py` **零改动**，
`status`/`evidence` 结构不变，**不靠改口径凑数**。

**三条上轮断言同步（全部改强）**：串台断言改为「A 收到、B 零」；
app.py 增加绑定与顺序断言；模块级 fallback 断言改名并断言全仓无参
消费点为 0。

**A′ ×1**（新写测试自身）：源码扫描把注释行里的 `HookTrigger()` 算成
消费点，误报 2 条 → 只看非注释行。产品代码零回归。

**矩阵一个状态没动**：`aligned 46 / partial 9 / gap 26`、
`fully_superior=false`、`b_waves_done=["B1"]`；`matrix.validate()` 与
`evidence.verify_evidence()` 均空。

**如实边界**：`_global_alerter` / `_notify_rc` 仍是**进程级单例**，
两个会话**并发并存**时共用同一实例 —— 未重写单例架构，串行切换已修好，
不宣称「完全多会话隔离」。registry 上界拒绝只影响显式 `owner=` 查询，
已绑定实例派发不受影响。**行为变更**：构造时冻结、三个构造函数新增
`hooks`、`notify()` 新增可选关键字、`app.py` 多一次注册。
`os_sandbox` 仍 gap、`deny_network_by_default` 仍 false 未翻、
`credential_masking` 仍 partial；A 线 10 pending、分叉改动、
第三方自适应红队未做；不是真机多平台验证。标语引擎 / 净化层 /
`mapping.py` / `tui.py` / `runtime_slogans.py` 逐字节未改。

**验证（按分批，批次间有重叠、不累加）**：B3 续轮 VI + 上一轮 V +
B3 两轮 + 5 个 hooks 既有文件 + mixin + config **185 passed**；
宽合并批次见报告；`verify_doc_numbers.py problems == []`；
`py_compile` 全 OK。新增 `tests/test_b3vi_session_binding.py`
（后台线程 / 回填两单例 / `rc is None` 仍派发 / 64 上界拒绝 /
全仓源码扫描 / 矩阵钉死）。


---

## R53 · B3 续轮 VII：C4 最后一角（并发多会话的派发归属隔离）

完整复现见 `CLAUDE_PARITY.md` 末尾「深度轮（续七）」。自足标题。

| 项 | 风险 | 处置 |
|---|---|---|
| R53-O1 | `bind_session_hooks(B)` 无条件回填单例 `hooks`，A 会话告警派到 B | `HookTrigger(owner=)` **冻结 owner + 派发时按 owner 分桶查 registry**；动态但不漂移（分桶非单槽） |
| R53-O2 | `remote_control.notify()` 同源，C 第二次通知落到 D | 新增可选 `owner`；优先级 显式 hooks > owner 分桶 > 实例冻结 hooks |
| R53-O4 | `ContextVar` 不跨 `threading.Thread`（实测） | `AlertRecord.owner` 由 `alert()` 在调用线程烘进，**不进 `to_dict()`**；后台线程用它查分桶 |
| R53-O5 | 修 O1/O2 时自己引入：owner 未注册 → 决策类静默放行 | fail-closed `owner_not_registered`；通知类 no-op + 有界 miss 留痕 |
| R53-O3 | `get_alerter()` 单例 + `AlertLogger(home)` / bus 订阅 / 端口与会话文件 | **判定不该修**：按 owner 多实例会引入文件竞争 / 重复订阅 / 端口冲突，回归锁住 `x is y` |

**新增机制**：`current_session_owner` / `set_session_owner` /
`reset_session_owner` / `hooks_for_owner` / `owner_miss_stats`
（有界、`<other>` 归并、纯诊断）；`provider_diagnostics()` 增加
`current_owner` 与 `owner_misses`。`app.py` 在
`set_default_hooks_provider` / `bind_session_hooks` **之后**调用
`set_session_owner`；ACP bridge 支持 owner 分桶（`session_id` ↔ owner
映射由上层负责，不自动派生）。

**两个 B3 条目仍 `STATUS_GAP`**：官方事件面远大于 7 个、exit-code-2
未实现、Elicitation 语义不等价、`ToolPipeline` 无生产构造方、
`cmd_hooks` 取 schema 依赖 kernel 暴露 `tool_registry`。本轮修的是
「并发会话的派发归属」不是覆盖面；`catalog.py` **零改动**，
`status`/`evidence` 结构不变，**不靠改口径凑数**。

**一条上轮断言同步（改强）**：`test_module_level_notify_is_now_
instance_bound` 增加 owner 分桶、`getattr(record, "owner", "")`、
`AlertRecord.owner`、`current_session_owner` 断言；VI 三条既有断言
全部保留。

**A′ ×2**（自己写错自己抓回）：O5 是修 O1/O2 时自己引入的新风险，
由新写回归抓回并改为 fail-closed；新断言写 `"record.owner"` 但代码
用 `getattr(...)`，字面串对不上 → 改检查真实写法。产品代码零回归。

**矩阵一个状态没动**：`aligned 46 / partial 9 / gap 26`、
`fully_superior=false`、`b_waves_done=["B1"]`；`matrix.validate()` 与
`evidence.verify_evidence()` 均空。

**如实边界**：单例对象身份仍进程级（不创建多实例），隔离的是**派发
归属**不是实例；`bind_session_hooks` 单槽回填仍在，只是 owner 路径
不读它；**未设置 owner 且未显式传 hooks** 的路径仍沿用最后一次
bind（既有行为），不宣称「完全多会话隔离」。`owner_miss_stats`
纯诊断不参与裁决；决策类 fail-closed 只针对显式 `owner=` 未注册。
**行为变更**：`HookTrigger(owner=)` 冻结 owner + 动态分桶、
`notify()` 新增 `owner`、`AlertRecord` 新增字段、`app.py` 设置
contextvar。`os_sandbox` 仍 gap、`deny_network_by_default` 仍 false
未翻、`credential_masking` 仍 partial；A 线 10 pending、分叉改动、
第三方自适应红队未做；不是真机多平台验证。标语引擎 / 净化层 /
`mapping.py` / `tui.py` / `runtime_slogans.py` 逐字节未改。

**验证（按分批，批次间有重叠、不累加）**：B3-VII + 上两轮 B3 +
5 个 hooks 既有文件 + mixin + config + alert/remote/plugin/bus/
bridge/ACP 相关 **330 passed**；宽合并批次见报告；
`verify_doc_numbers.py problems == []`；`py_compile` 全 OK。新增
`tests/test_b3vii_concurrent_sessions.py`（O1 后台线程并发 / 单槽
回填仍在但派发不读 / O2 优先级与 `rc is None` / O4 跨线程 /
owner 热替换 / O5 fail-closed + miss 有界 / O3 单例身份 / 矩阵钉死）。


---

## R54 · B3 续轮 VIII：会话生命周期收口 + 跨线程 owner 句柄化

完整复现见 `CLAUDE_PARITY.md` 末尾「深度轮（续八）」。自足标题。

| 项 | 风险 | 处置 |
|---|---|---|
| R54-P1 | `unregister_session` 生产零调用点，64 槽占满后新会话注册被拒且返回值被忽略 → 静默 no-op | `activate_session`/`deactivate_session` 生命周期对；`rejected` 计数 + `provider_diagnostics()` 暴露 + `app.py` warning |
| R54-P2 | `set_session_owner` 从不复位，同线程复用残留 | `SessionHandle.token` + `deactivate_session` 复位 |
| R54-P3 | `ContextVar` 不跨 executor（实测）；bridge 运行时读 contextvar 退化 | `KernelAcpBridge.owner` + `_resolve_owner()`（显式 > `agent.ctx.session_owner` > contextvar），`ask_user` 用显式句柄 |
| R54-P4 | `_bump_owner_miss` 锁外 TOCTOU（GIL 下未稳定复现）；上界语义含糊 | 判定收进锁内；明确 64 具体 owner + 1 `<other>` = 65 |
| R54-P5 | docstring「3 个模块级单例」实际 2 个 | 口径改如实，代码行为不变 |
| R54-O3 | `get_alerter()` 进程级单例 | **判定不该修**，回归锁住 `x is y` |

**新增机制**：`SessionHandle` / `activate_session(owner=, hooks=,
provider=)` / `deactivate_session(handle)`；四步收成单一入口，返回
携带复位 token 的句柄。`deactivate` 刻意**不清** default provider
（清掉会打断仍在运行的其他会话）。`app.py` 把 `session_owner` /
`session_handle` 显式挂到 `agent.ctx`，`active=False` 时
`logger.warning`，不再静默退化到单槽绑定。

**两个 B3 条目仍 `STATUS_GAP`**：官方事件面远大于 7 个、exit-code-2
未实现、Elicitation 语义不等价、`ToolPipeline` 无生产构造方、
`cmd_hooks` 取 schema 依赖 kernel 暴露 `tool_registry`。本轮修的是
「会话生命周期与线程边界」不是覆盖面；`catalog.py` **零改动**，
`status`/`evidence` 结构不变，**不靠改口径凑数**。

**四条上轮断言同步（全部改强）**：四条 app.py 相关断言改为检查单一
入口 + ctx 挂载 + `active` 失败可见 + API 导出 + 旧分散调用消失；
bridge 断言补 `_resolve_owner`；`provider_diagnostics` 断言补
`rejected` 一致性。

**A′ ×3**（自己写错自己抓回）：① **产品代码真缺陷** ——
`reset_session_owner` 只吞 `ValueError/TypeError`，但
`ContextVar.reset()` 对已用过 token 抛 `RuntimeError`，重复
`deactivate_session` 掀翻关闭路径；新写回归抓回，三类异常一律吞。
② 4 处源码扫描把**注释行**历史说明算成调用 → 只看非注释行。
③ `deactivate_session` 扫描把 `def` **定义行**算成宿主调用 →
排除 `def ` / `from ` 行。

**矩阵一个状态没动**：`aligned 46 / partial 9 / gap 26`、
`fully_superior=false`、`b_waves_done=["B1"]`；`matrix.validate()` 与
`evidence.verify_evidence()` 均空。

**如实边界**：`deactivate_session` **没接到所有宿主**（无统一 close
钩子），只提供 API + ctx 句柄；未调用的长跑仍会占满槽位，但
`rejected` 可见且 `app.py` warning，不再静默。**P3 修的是「消除对
线程上下文的依赖」不是已观测 ACP 串台**（`ask_user` 跑在 loop 线程，
多数场景原实现能拿到 contextvar）；**P4 锁内化未对应已复现越界**，
是消除对 GIL 实现细节的依赖。单例身份仍进程级、单槽回填仍在、
`AlertRecord.owner` 仍不序列化、单 bridge 不按 `session_id` 自动
派生。**行为变更**：`activate_session` 取代四个分散调用、bridge 新增
`owner` 参数与 `_resolve_owner()`、`reset_session_owner` 多吞一类
异常、`session_registry_diagnostics` 多 `rejected` 字段。
`os_sandbox` 仍 gap、`deny_network_by_default` 仍 false 未翻、
`credential_masking` 仍 partial；A 线 10 pending、分叉改动、
第三方自适应红队未做；不是真机多平台验证。标语引擎 / 净化层 /
`mapping.py` / `tui.py` / `runtime_slogans.py` 逐字节未改。

**验证（按分批，批次间有重叠、不累加）**：B3-VIII + 上三轮 B3
**131 passed**；既有 hooks/config/alert/remote/plugin/bus/bridge/ACP
相关 **233 passed**；宽合并批次见报告；
`verify_doc_numbers.py problems == []`；`py_compile` 全 OK。新增
`tests/test_b3viii_session_lifecycle.py`（64 槽耗尽 + `rejected`
可见 + 注销复用 + activate/deactivate 往返 + token 复位 + 幂等关闭 +
executor 跨线程 owner + `_resolve_owner` 优先级 + miss 有界/并发不丢
+ docstring 口径 + 不该修契约 + 矩阵钉死）。


---

## R55 · B3 续轮 IX：会话激活事务化 + owner 冲突拒绝 + CLI 主路径接线

完整复现见 `CLAUDE_PARITY.md` 末尾「深度轮（续九）」。自足标题。

| 项 | 风险 | 处置 |
|---|---|---|
| R55-Q1 | 注册被拒时 provider 已切到被拒会话，老会话无 owner 消费者派发污染 | 注册作为唯一事务边界；失败零副作用早返回 |
| R55-Q1b | 注册失败仍回填 `_global_alerter` / `_notify_rc` | `bind_session_hooks` 失败立即 `return False` 不回填 |
| R55-Q2 | `id(agent)` 复用 → 静默覆盖 + 旧句柄 ABA 误删 | 同 owner 拒绝 + `conflicts` 计数 + `unregister(expected=)` 精确注销 |
| R55-Q3 | bind 异常时 token 泄漏、无句柄可复位 | 事务化零副作用 + 阶段 2 异常精确回滚 |
| R55-Q4 | deactivate 不清 ctx 残留，bridge 返回已注销 owner | `SessionHandle.ctx` + 仅当 handle 仍挂载时清理 |
| R55-Q5 | frozen 句柄无 `closed`，重复关闭靠反推 | 可变 dataclass + `closed` 标记 + 幂等 |
| R55-Q6 | deactivate 生产零调用点，registry 只增不减 | `cmd_chat.py` 两个 SessionEnd finally 接 `_close_agent_session` |

**新增机制**：`session_scope(owner=, hooks=, provider=, ctx=)` 上下文
管理器（异常安全自动关闭）；`app.py` 改传 `ctx=agent.ctx`；
`SessionHandle` 新增 `hooks`/`ctx`/`closed`；`provider_diagnostics()`
新增 `session_conflicts`。`deactivate` 刻意**不清** default provider
（清掉会打断仍在运行的其他会话）。

**两个 B3 条目仍 `STATUS_GAP`**：官方事件面远大于 7 个、exit-code-2
未实现、Elicitation 语义不等价、`ToolPipeline` 无生产构造方、
`cmd_hooks` 取 schema 依赖 kernel 暴露 `tool_registry`。本轮修的是
「会话激活事务性与生命周期收尾」不是覆盖面；`catalog.py` **零改动**，
`status`/`evidence` 结构不变，**不靠改口径凑数**。

**11 处上轮断言同步（全部改强）**：四条 app.py 断言改查
`ctx=agent.ctx`；事务化顺序改查 `bind < provider < set_owner`；
热替换改查同 owner 拒绝 + `conflicts` + 显式替换动态查表；
diagnostics 补 `conflicts`；「未接宿主」改查「cmd_chat 恰好 1 处 +
其余逐一锁住」；lifecycle API 补 `session_scope`；rejected 文档补
`conflicts`；docstring 断言扩大窗口并补 Q1b 早返回。

**A′ ×4**（自己写错自己抓回）：① **产品代码语法错误** ——
`hooks/__init__.py` 反斜续行 import 新增导出时误加尾逗号，
`py_compile` 直接 SyntaxError → 改续行反斜杠。② 新写 docstring
里 ``HookTrigger()`` 字面串被 4 个既有全仓源码扫描误判 → 改成不含
括号写法，产品逻辑零改动。③ Q1b 新测试用 `Rec.hooks.n`，但「零
副作用」恰是属性不存在 → 改 `not hasattr` 并补成功对照避免恒真。
④ 对照用例 `unregister_session("filler-0")` 而 `fill()` 默认前缀是
`f-0` → 改 `f-0`。

**矩阵一个状态没动**：`aligned 46 / partial 9 / gap 26`、
`fully_superior=false`、`b_waves_done=["B1"]`；`matrix.validate()` 与
`evidence.verify_evidence()` 均空。

**如实边界**：**Q2 是行为变更**（同 owner 二次注册从覆盖变拒绝，热
替换需显式 unregister + register）；**Q3 是注入故障**不是线上已观测
异常；**Q2 的 id 复用**用同 owner 字符串模拟，不声称线上一定发生；
**Q4 修的是归属信息残留**未对应已观测派发错误。**`deactivate` 只接
CLI 主路径**：ACP server / web / stream_json / TUI.close /
`AcpSession.dispose` 仍未接线。单例身份仍进程级、单槽回填仍在、
`AlertRecord.owner` 仍不序列化、单 bridge 不按 `session_id` 自动
派生。`os_sandbox` 仍 gap、`deny_network_by_default` 仍 false 未翻、
`credential_masking` 仍 partial；A 线 10 pending、分叉改动、
第三方自适应红队未做；不是真机多平台验证。标语引擎 / 净化层 /
`mapping.py` / `tui.py` / `runtime_slogans.py` 逐字节未改。

**验证（按分批，批次间有重叠、不累加）**：B3-IX + 上四轮 B3
**196 passed**；既有 hooks/config/alert/remote/plugin/bus/bridge/ACP
相关 **203 passed**；宽回归 A **218 passed**；宽回归 B 见报告；
`verify_doc_numbers.py problems == []`；10 文件 `py_compile` 全 OK。
新增 `tests/test_b3ix_session_transaction.py`（Q1–Q6 + 不该修契约
+ 事务化顺序 + 矩阵钉死）。


---

## R56 · B3 续轮 X：create_agent 真实会话生命周期（纠偏 + R1–R4）

完整复现见 `CLAUDE_PARITY.md` 末尾「深度轮（续十）」。自足标题。

| 项 | 风险 | 处置 |
|---|---|---|
| 纠偏 | IX 点名的 `tui.py` / `runtime/acp/session.py` / `runtime/acp/server.py` 的 `create_agent` 调用点都是 0，不是会话宿主 | 口径改为「9 个真实 `create_agent` 调用方」 |
| R56-R1 | 每个子 agent 创建覆盖进程级单槽 provider，主会话新建无 owner 消费者派到子 agent | 共享 `default_hooks_resolver()` 按 contextvar 分桶解析；单槽 `owner` 降为纯信息项 |
| R56-R2 | provider lambda 闭包强引用 agent，最后一个 agent 永不 GC | 模块级无闭包函数对象，`app.py` 改传共享 resolver |
| R56-R3 | 短命子 agent 不注销 → 64 槽满 + id 复用被 `conflicts` 拒绝 → 新会话静默失去 hooks | 上提 `close_agent_session(agent)`，5 处 `finally` 接线 |
| R56-R4 | 关闭子会话后单槽仍指向已注销会话 | 共享 resolver 不绑 owner，关闭后不陈旧 |

**新增机制**：`default_hooks_resolver()`（按 `current_session_owner()`
分桶查 registry；无 owner 回落最早存活会话；不持有 agent/ctx/hooks）；
`close_agent_session(agent)`（统一、幂等、异常隔离）；`hooks/__init__.py`
导出两者。**刻意不做 GC 终结器兜底** —— 槽位释放不依赖 GC 时机，
与前几轮「判定不依赖文件系统/缓存时间点」立场一致。

**5 处 `finally` 接线**：`cli/cmd_chat.py`（TUI + REPL）、
`hooks/manager.py`（Subagent hook）、`tools/subagent_tool.py`、
`tools/workflow_tool.py`、`stream_json/headless.py`（serve 出口）。

**两个 B3 条目仍 `STATUS_GAP`**：官方事件面远大于 7 个、exit-code-2
未实现、Elicitation 语义不等价、`ToolPipeline` 无生产构造方、
`cmd_hooks` 取 schema 依赖 kernel 暴露 `tool_registry`。本轮修的是
「会话生命周期的真实泄漏面」不是覆盖面；`catalog.py` **零改动**，
`status`/`evidence` 结构不变，**不靠改口径凑数**。

**6 处上轮断言同步（全部改强）**：4 条 `app.py` 的
`provider=lambda: getattr(` 改为共享 resolver 且
`getattr(getattr(agent` 不再出现；`cmd_chat` 改查
`close_agent_session(agent)` 且旧实现已消失；
`test_deactivate_wired_to_cmd_chat_only` 整条重写为「5 处接线 +
3 个长驻宿主未接 + 2 个独立子进程不该修 + 3 个伪宿主 0 调用点」。

**A′ ×3**（自己写错自己抓回）：① 新写 `default_hooks_resolver`
docstring 里 `weakref.finalize` / `weakref.ref` 字面串被「不做 GC
兜底」回归误判（2 次失败）→ 改措辞，产品逻辑零改动。②
`owner_miss_stats()` 结构误判 `KeyError` → 改
`sum(stats.values()) >= 1`。③ 替换脚本嵌套引号 `SyntaxError`，首次
重跑仍在用旧断言 → 重写生效。

**矩阵一个状态没动**：`aligned 46 / partial 9 / gap 26`、
`fully_superior=false`、`b_waves_done=["B1"]`；`matrix.validate()` 与
`evidence.verify_evidence()` 均空。

**如实边界**：子 agent 存活期间同线程 contextvar 指向子会话是同步
作用域正常状态，本轮不改变；修复的是结束后不残留。后台线程无
owner 时回落「最早存活会话」可能是子 agent；R3 的 64 槽耗尽是
模拟不是真跑 70 个 LLM 子代理；R2 的 GC 实测在 CPython 引用计数下
成立，其他实现不保证。**只接了 5 处**：`cli/cmd_acp.py` /
`web/server.py` / `runtime/acp/bridge.py` 三个长驻宿主仍未接线；
两个独立子进程判定不该修。行为变更：provider 从每会话 lambda 变
共享函数，`provider_diagnostics()["owner"]` 降为纯信息项；子 agent
调用方现在会在 `finally` 注销槽。`deactivate` 仍不清 default
provider；单例身份仍进程级、单槽回填仍在、`AlertRecord.owner` 仍
不序列化。`os_sandbox` 仍 gap、`deny_network_by_default` 仍 false
未翻、`credential_masking` 仍 partial；A 线 10 pending、分叉改动、
第三方自适应红队未做；不是真机多平台验证。标语引擎 / 净化层 /
`mapping.py` / `tui.py` / `runtime_slogans.py` 逐字节未改。

**验证（按分批，批次间有重叠、不累加）**：B3-X + 上五轮 B3
**226 passed**；既有 hooks/config/alert/remote/plugin/bus/ACP/workflow/
subagent/headless/stream_json 相关 **285 passed**；宽回归 A
**218 passed**；宽回归 B **185 passed / 1 failed**（4 个文件与
parent 逐字节一致，策略拒绝 `/usr/bin/python3` 的既有环境行为，
没为变绿动策略）；`verify_doc_numbers.py problems == []`；14 文件
`py_compile` 全 OK。新增 `tests/test_b3x_agent_sessions.py`。


---

## R57 · A 线续轮 XI：深度真实性判据 + Codex 侧清零

完整复现见 ``CLAUDE_PARITY.md`` 末尾「A 线续轮 XI」。自足标题。

| 项 | 风险 | 处置 |
|---|---|---|
| 状态表虚高 | 一行 note 指向 .py 只证明「有代码」，证明不了行为正确 | ``tui/parity/depth.py``：每个 aligned/localized 必须有注册探针且真调通过 |
| 判据可凑数 | 旧 ``fully_identical`` 只看 ``pending==0`` | 加严为 ``pending==0 and depth_audit()["ok"]``；当前 10/102，如实 False |
| B 线水分 | 六维聚合探针绿 ≠ 模块级验证 | ``parity_claude/depth.py`` 只读量化：65/65 有路径与 note，**模块级探针 0** |
| 双口径联动 | 加严后 B 线 ``verifiable_parity`` 硬编码假设误报「指标自相矛盾」 | 逐项核销 ``all_modules_settled`` / ``depth_strict_ok`` / 计数对账（改强） |
| 26 gap 无基线 | 直接堆功能会滑向广度 | ``gap_queue()`` 逐项证据 + wave 分组，下一轮按此逐域补 |

**新增机制**：``tui/codexkit/`` 5 文件 10 个真实实现（审批拒绝 /
历史插入 / 选区几何 / 本地设置 / 时钟格式 / 外部配置迁移 /
流式装配 / 异步问答 / 命令类型化 / 纯 stdlib harness），
**127 条探针断言**；``PROBE_REGISTRY`` 注册 + ``matrix.validate()``
逐一执行；不缓存、不自动降级状态。``parity_claude/depth.py`` 只读，
**不改 B 线任何判据/状态**，``catalog.py`` 零改动。

**矩阵**：A 线 ``pending 10→0`` / ``aligned 35→45`` /
``coverage 93.9%→100.0%`` / ``all_modules_settled=True`` /
``depth 10/102`` / ``fully_identical=False``；
B 线 ``aligned 46 / partial 9 / gap 26`` / ``fully_superior=false``
**一个没动**。

**9 条既有断言同步（全部改强）**：数字更新之外，每条额外加
``depth_verified==10`` 等深度断言；CLI 两处硬编码「还剩 10 个
pending」改动态读 ``matrix.summary()``。

**A′ ×8**（自查抓回）：base_id 语义 / ESC 残片 / 探针断言写反 /
间接 shell / 重复计数 / 源码扫描自我引用 ×3 / 探针未注册 /
``gap_queue`` 18.8s→352ms。

**验证（分批，不累加）**：85 + 555 + 286 passed / 1 failed
（4 文件与 parent ``814c3231`` 逐字节一致，策略拒绝
``/usr/bin/python3`` 的既有环境行为，没为变绿动策略）；
纯 stdlib ``xi_verify.py`` 30/30；``matrix.validate()`` /
``evidence.verify_evidence()`` / ``verify_doc_numbers.py`` /
14 文件 ``py_compile`` 全干净。新增 ``tests/test_codexkit_depth.py``。

**如实边界**：A 线 92 个既有 aligned/localized 仍无模块级探针；
B 线 26 gap 一个未消，下一轮起按 ``gap_queue()`` 逐域补且
每消一个必须注册模块级探针；``os_sandbox`` 仍 gap、
``deny_network_by_default`` 仍 false 未翻、``credential_masking``
仍 partial；``b_waves_done=["B1"]``、第三方红队未做；不是真机
多平台验证。``codexkit`` 不接 TUI 主循环、不替换任何既有运行时
对象；纯 Python，零 Rust 源码复制。标语引擎 / 净化层 /
``mapping.py`` / ``tui.py`` / ``runtime_slogans.py`` 逐字节未改。


---

## R58 · B3 续轮 XII：hooks exit-code-2 深度真实性（状态不动）

完整复现见 ``CLAUDE_PARITY.md`` 末尾「B3 续轮 XII」。自足标题。

| 项 | 风险 | 处置 |
|---|---|---|
| **H1 真实安全洞** | ``exit 2`` + stderr 阻断原因 + stdout 一行 ``permissionDecision:allow`` → ``block=False, reason=''`` | ``hooks/exit_semantics.py`` 33 事件真值表 + ``classify()``；``HookExit``；``_exit_gate()``；exit 2 强制阻断且 JSON 绝不覆盖 |
| H2/H3 | CC 官方 PR ``decision.behavior`` / ``updatedInput`` 静默放行 | ``_parse_decision`` 补官方协议 |
| H4 | ``WorktreeCreate`` 非零 rc 被 JSON allow 绕过 | 任何非零 rc 都失败 |
| H5 | 18 个官方事件配置 0 加载 | 事件表 15 → 33（真值表单一真值源） |
| H6 | ``ToolPipeline`` 生产构造方 0 个 | ``ToolExecutor.__init__`` 真实构造 |
| H7 | bridge 旁路 ``handler(ctx,**args)`` 无 schema 校验 | 接 ``validate_updated_input`` |
| 深度虚高 | 六维聚合探针 ≠ 逐模块验证 | 两条 B3 gap 各注册 1 个真调代码的模块级探针（30+18 断言），``gap_probe_audit() 2/2``；``module_depth`` 仍如实 0/65 |

**逐事件真值表**：16 事件 exit 2 阻断；PR exit 2 不生效；3 事件完全忽略
exit code；WorktreeCreate/Remove 任何非零失败；stderr 去向逐事件标注。
**Tuan 差异保留**：``on_failure=block`` 比 CC 更严（B1 立场），
``compare_with_tuan_policy()`` 逐项列出；``json_may_override`` 只在
非 2 非零时为真。

**矩阵**：B 线 ``aligned 46 / partial 9 / gap 26`` /
``fully_superior=false`` / ``b_waves_done=["B1"]`` **一个没动**；
catalog status 字段逐字节未改，两条 note 按实测收窄。A 线
``pending 0 / depth 10/102 / fully_identical=False`` 不变。

**A′ ×4**：不存在的哨兵 import / rc=1 JSON reason 被吞（既有回归变红）
/ 事件面断言 import 路径 / 审计文件残留复查。

**验证（分批，不累加）**：171 + 552 + 232 passed / 1 failed（4 文件与
parent ``0fa1653c`` 逐字节一致，策略拒绝 ``/usr/bin/python3`` 的既有
环境行为，没为变绿动策略）+ 67 + 纯 stdlib 32/32；矩阵 / 证据 /
文档数字 / 真值表 / 10 文件 py_compile 全干净。新增
``tests/test_b3xii_exit_semantics.py``。

**如实边界**：26 gap 一个未消（新增 18 事件无生产触发点 / 无 JSON
decision 通道、Elicitation 语义刻意不等价、``ToolPipeline`` 是可选
通道、HTTP/prompt/agent hook 类型未覆盖）；第三方红队未做；不是真机
多平台验证。标语引擎 / 净化层 / ``mapping.py`` / ``tui.py`` /
``runtime_slogans.py`` 逐字节未改。
