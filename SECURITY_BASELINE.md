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
