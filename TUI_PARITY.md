# TUI 与 OpenAI Codex CLI 的对齐矩阵

> 目标：**TUI 与 Codex 完全相同，但保留 Tuan 自己的本地化。**
> 本文把这句话拆成可核验、可度量、可增量推进的条目，而不是一句口号。
> 当前状态由 `tuan tui parity` 实时计算，本文与之互为印证。

---

## 1. 「完全相同」的准确含义

逐字复制 49.2 万行 Rust 到 Python 仓库既不可执行、也会把前九轮修好的
安全接线全部甩掉（权限策略注入、`ctx.confirm`、沙箱路由都挂在现有 TUI
入口上）。因此本文定义的「完全相同」是**五个可核验维度**：

| 维度 | 含义 | 本地化是否允许改 |
|---|---|---|
| 组件树 | 165 个顶层模块的划分与职责 | 否（结构对齐，实现可换语言） |
| 键位 | `built_in_defaults` 的绑定、优先级、冲突规则、和弦 | 否（**完全相同**最硬的一部分） |
| 布局常量 | gutter 列数、弹层行数、侧栏阈值等数值 | 否 |
| 交互契约 | 显式决策事件、Esc→Cancel、UI 不判安全、作用域区分 | 只允许**更严格** |
| 呈现文案 | 给人看的字 | **是**，这是「有自己本地化」的落点 |

此外明确**不做**的：不引入 ratatui / crossterm / tokio；不替换
prompt_toolkit/rich 应用骨架；不接 OpenAI 账号、云服务、订阅与更新通道。
这些是渲染后端与产品边界，不是「外壳」的可对齐部分。

---

## 2. 上游事实（本地完整核验）

| 项 | 值 |
|---|---|
| 仓库 / 引用 | `openai/codex` main（tarball commit `2c502d8`） |
| crate | `codex-rs/tui` (`codex-tui`) |
| 语言 / 渲染栈 | Rust + ratatui + crossterm + tokio |
| 顶层模块 | **165**（逐条取自 `lib.rs` 的 `mod` 声明） |
| `.rs` 文件 | **1216** |
| `.rs` 总行数 | **492414** |
| 跳过的快照文件 | 1491 |
| 许可 | Apache-2.0（全文 `THIRD_PARTY_LICENSES/Codex-LICENSE.txt`） |

> **口径更正**：上一轮文档写的「567 个 `.rs` / 约 24.7 万行」来自一次不完整的
> sparse 解压（只解出 1135 个文件）。本轮从 tarball 完整提取后得到上表数值，
> 所有引用旧数字的位置（`NOTICE` / `SECURITY.md` / `SECURITY_EN.md` /
> `CHANGELOG.md`）已同步修正。**低估不当事实用。**

---

## 3. 本轮落地的对齐层

代码在 `tuan_cli/tui/parity/`，纯 Python、零 Rust 源码、可被测试核销：

| 文件 | 内容 |
|---|---|
| `upstream_spec.py` | 规模事实、165 模块树与功能域分组、布局常量、键位规格规范化 |
| `keymap.py` | Codex 默认键位表（8 context / 82 动作 / 74 已绑定）、`RuntimeKeymap` |
| `i18n.py` | 17 条 Codex 英文原文 → 10 语言文案（en / zh-CN 全量） |
| `matrix.py` | 逐模块状态、覆盖率、差距队列、自检 |

**键位对齐**：逐值取自 `keymap.rs::built_in_defaults()`。解析规则对齐
`config/src/tui_keymap.rs`：
- 优先级 `context → global fallback → built-in defaults`；
- 键位串规范化：修饰键恒按 `ctrl-alt-shift-super-<key>` 排序，
  `escape→esc` / `return→enter` / `pageup→page-up` 等别名；
- 和弦最多 2 击、`leader <key>` 语法；
- 三态覆盖：未配置=用默认、`[]`/`null`=**显式解绑**、字符串/列表=自定义；
- 唯一性冲突检测 + 保留键 `ctrl-c`（`fixed.interrupt_or_quit`）不可重绑；
- 错误带 `tui.keymap.<context>.<action>` 配置路径。

**审批键位改为 Codex 原生**（`approval_overlay.rs`）：

| 键 | Codex 动作 | Tuan 决策 |
|---|---|---|
| `y` | Approve | `ONCE` |
| `a` | AcceptForSession | `SESSION` |
| `p` | ApproveForPrefix | `PREFIX`（新增，本地化映射到会话内授权并显式标注） |
| `d` | No / Deny | `DENY` |
| `n` | No, and tell the agent what to do differently | `DECLINE`（新增） |
| `c` | Cancel | `ABORT` |
| `Esc` | decline（exec）/ Cancel（MCP elicitation） | **`ABORT`**（本地化增强，见 §6） |

上一轮的 `s` / `1` / `2` 等保留为**本地化兼容别名**，不破坏既有用户习惯。

**布局常量对齐**：`LIVE_PREFIX_COLS=2`、`FOOTER_INDENT_COLS=2`、
`MAX_POPUP_ROWS=8`、`MIN_LIST_WIDTH_FOR_SIDE=40`、`SIDE_CONTENT_GAP=2`、
`MENU_SURFACE_HORIZONTAL_INSET=4`、`MAX_KEY_CHORD_STROKES=2`。

**文案本地化**：`pt()` 先查项目现有 10 语言 i18n 的 `parity.*` 覆盖，
再查内置表（当前语言 → zh-CN → en → key），永不抛异常、永不返回空串。

**第 11 轮：输入/终端能力对齐层**（`tuan_cli/tui/inputkit/`，7 个模块，
纯 Python、零 Rust 源码）。本轮把 `input_keymap` 组从 `pending 7` 清零：

| 上游模块 | 本包落点 | 逐值/逐分支对齐点 |
|---|---|---|
| `vim_search.rs` | `vim_search.py` | 字面匹配（非正则）、范围覆盖完整 grapheme、`Forward/Backward` 与 `reversed()`、空查询无匹配 |
| `activation_key_guard.rs` | `activation_key_guard.py` | `INITIAL_GUARD=1s` / `LEGACY_REPEAT_GUARD=1s`、Press/Repeat/Release 六分支状态机、物理键比较 |
| `copy_input_guard.rs` | `copy_input_guard.py` | RAII/Drop 语义：`TranscriptCopyClosed` 释放、**异常路径也必须释放**、幂等 |
| `custom_terminal.rs` | `custom_terminal.py` | 双缓冲 `diff_buffers`：行尾单条 `ClearToEnd`、`AlwaysUpdate` 空白不被尾部过滤、宽字符跨界强制清除、`Skip` 语义、BSU/ESU 同步帧、Drop 恢复光标 |
| `terminal_program_status.rs` | `terminal_program_status.py` | `MIN_VTE_VERSION_WITH_SAFE_OSC=5400`、OSC 7501/21337、`Idle/Working/Waiting` 与 `#00d75f/#ff9500/#5f87ff`、Mutex 去重缓存、`invalidate()`、`;`/`\` 转义 |
| `terminal_hyperlinks.rs` | `terminal_hyperlinks.py` | `MAX_HYPERLINK_DESTINATION_BYTES=8192`、**17 项**工作区扩展名白名单、`canonicalize`+`strip_prefix` 逃逸校验、symlink/隐藏目录拒绝、图片魔数探测、OSC 8 字节不参与几何 |
| `terminal_visualization_instructions.rs` | `terminal_visualization_instructions.py` | feature gate、非空拼接、四条约束（表格/树/时间线/**ASCII-only**），中文常量为默认 |

其中 `terminal_hyperlinks` 是安全价值最高的一块：链接目标会被终端解释，
所以 `web()` 额外做了 **http/https scheme 白名单**与 OSC/BEL 控制字符
拦截（上游 `web()` 不校验目的地，这是本项目**更严格**的本地化增强，
不是削弱）。`terminal_program_status` 也做了安全默认：**未显式
`configure(writer=...)` 时绝不往终端写任何转义序列**。

**第 12 轮：应用核心对齐层**（`tuan_cli/tui/corekit/`，9 个模块，
纯 Python、零 Rust 源码）。本轮把 `core_app` 组从 `pending 9` 清零，
且**没有替换任何现有运行时对象**：

| 上游模块 | 本包落点 | 逐值/逐分支对齐点 |
|---|---|---|
| `app.rs` | `app.py` | `THREAD_EVENT_CHANNEL_CAPACITY=32768`、`EXTERNAL_EDITOR_HINT` 原文、`AppRunControl` / `ExitReason` / `AppExitInfo::fatal` 清空其他字段、`rollout_path_is_resumable`（存在 + 普通文件 + len>0） |
| `app_backtrack.rs` | `app_backtrack.py` | 六步 Esc/Enter 状态机（prime → 浏览 → 左右选 → Ctrl+T 详情 → Esc 恢复 → Enter revert）、`base_id` 变更强制失效、`usize::MAX` 无选择语义、两条提示常量 |
| `app_command.rs` | `app_command.py` | **`RealtimeOfferSdp` / `RealtimeSpeechText` 的 Debug 与 Serialize 恒为 `<redacted>`**，明文只在信令边界还原；`CloudSubmissionIntent` 三态；`UserVerificationResponse.proof` 带 `serde(skip_serializing)` |
| `app_event.rs` | `app_event.py` | 类型化事件、`CodexOp` **不双记** inbound 日志、`ExitMode` 三态（Immediate 明确会丢在途工作）、`FeedbackCategory` / `RunningTaskExitAction` / `SideStartMode` |
| `app_event_sender.rs` | `app_event_sender.py` | **voice_only 白名单先判定再记日志**（被丢弃事件不进日志）、Ops 不双记、发送失败吞错并记 error、10 个便捷方法 |
| `app_info.rs` | `app_info.py` | wire→domain **显式转换函数**（不用 `From`，对齐 Rust 孤儿规则）、15 / 6 / 11 / 1 / 3 字段逐项解构、Option 用 map 递归 |
| `chatwidget.rs` | `chatwidget.py` | committed cells + 原地可变的 active cell、缓存键变化才重建 live tail、**`agent_turn_running` 与 `mcp_startup_status` 两个独立生命周期派生单一 busy 指示器** |
| `cli.rs` | `cli.py` | 公开 flag 与 `#[clap(skip)]` 内部参数分离、**`mark_tui_args` 两条冲突规则** |
| `resize_reflow_cap.rs` | `resize_reflow_cap.py` | `1000 / 9001 / 3500 / 10000` 四档、Auto/Disabled/Limit 三态（`None` = 显式禁用保留全部行）、**VS Code 环境探测优先于终端名** |

三条最值钱的安全契约：

1. **脱敏 newtype**。上游把 ICE 凭据与语音文本排除在诊断/会话录制之外；
   本地化做得更严：`repr` / `str` / `f-string` / `to_dict` / `==` 全部
   走 `<redacted>`，只有显式 `reveal()` 能取明文且带调用计数。
2. **审批冲突 fail-closed**。上游 `mark_tui_args` 让
   `dangerously_bypass_approvals_and_sandbox` 与 `approval_policy`、
   `auto_review` 与 `approval_policy` 互斥。若本地解析让二者静默共存，
   就是「用户以为设了审批策略、实际被绕过开关吃掉」的配置侧门。本轮
   做成结构化拒绝并进 `corekit_validate()`。
3. **既有安全接线保护**（用户明确要求）。`app.assert_wiring_intact()`
   **真实 import** 现有模块，逐项验证 6 条：`build_permission_policy`
   注入、`_DenyAllMCPPolicy` 返回 deny、`ctx.confirm` 通道、
   `make_confirm_callable` 卡片接线、`confirm_apply` 副本确认、
   `ABORT` 显式决策（无输入 / Esc 绝不变成同意）。它接入
   `corekit_validate()`、`parity_validate()` 与回归集 —— 以后任何
   「为了对齐而重写入口」的改动会先被测试拦下。

另外两处跨会话/状态机正确性：`bind_thread()` 在线程变化时强制作废旧
选择（否则 A 会话的 revert 会落到 B 会话）；chatwidget 的双生命周期
保证 MCP 启动期间不误报空闲导致重复提交。

---

## 4. 对齐矩阵

状态定义：

- `aligned` — 行为/布局/键位/契约已对齐，且本仓库有实现与回归测试指向；
- `localized` — 上游有该组件，Tuan 用**本地化等价物**替代（中文/多语言、
  自有配色与吉祥物、本地模型、本地路径、本地审批作用域）。这就是需求里
  的「有自己本地化」；
- `not_applicable` — OpenAI 专属能力（登录、云、订阅、更新通道、
  app-server 守护、worktree 等），本地 CLI 不需要，记为替代而非缺口；
- `pending` — 未对齐，后续轮次队列。

### 分组汇总

| 功能域 | aligned | localized | n/a | pending |
|---|---:|---:|---:|---:|
| core_app | 10 | 8 | 3 | **0** |
| input_keymap | 12 | 6 | 0 | **0** |
| bottom_pane | 1 | 8 | 2 | 0 |
| approval_permissions | 3 | 0 | 2 | 1 |
| history_transcript | 0 | 9 | 9 | 1 |
| session_startup | 0 | 8 | 16 | 1 |
| tools_exec | 2 | 3 | 10 | 2 |
| mcp_agents | 0 | 4 | 5 | 0 |
| config_models | 1 | 7 | 5 | 3 |
| updates_analytics | 0 | 2 | 5 | 1 |
| streaming_async | 1 | 0 | 2 | 2 |
| external_editor | 0 | 2 | 0 | 1 |
| daemon | 0 | 0 | 3 | 0 |
| infra | 2 | 0 | 2 | 1 |
| misc | 0 | 2 | 5 | 3 |

> 分组含少量交叠引用，故分组计数之和大于 165；权威总数为 165，由
> `matrix.parity_status()` 按模块去重计算。

### 关键模块逐条（aligned）

| 模块 | 落点 |
|---|---|
| `keymap` / `keymap_setup` | `parity/keymap.py::RuntimeKeymap` |
| `key_hint` / `shortcut_help` | `parity/upstream_spec.py::normalize_key_spec` + `primary_hint` |
| `footer_hint` | `parity/i18n.py::hint.transcript` / `hint.shortcuts` |
| `ui_consts` / `ui_tree` | `parity/upstream_spec.py` 常量与模块树 |
| `config_panel` | `tui.keymap.<ctx>.<action>` 配置路径 |
| `bottom_pane` / `diff_render` | `ui/approval_overlay.py` 卡片（第 9/10 轮） |
| `approval_events` | 显式决策事件与路由（第 9 轮） |
| `diff_model` | `sandbox/isolation.py::DiffPreview`（第 8 轮） |
| `permission_discovery` | `tools/mcp/policy.py`（第 8 轮） |
| `security_setup` | `SECURITY_BASELINE.md` R1–R22 |
| `vim_search` | `tui/inputkit/vim_search.py`（第 11 轮） |
| `activation_key_guard` | `tui/inputkit/activation_key_guard.py`（第 11 轮） |
| `copy_input_guard` | `tui/inputkit/copy_input_guard.py`（第 11 轮） |
| `custom_terminal` | `tui/inputkit/custom_terminal.py`（第 11 轮，MIT 派生见 §8） |
| `terminal_program_status` | `tui/inputkit/terminal_program_status.py`（第 11 轮） |
| `terminal_hyperlinks` | `tui/inputkit/terminal_hyperlinks.py`（第 11 轮） |
| `terminal_visualization_instructions` | `tui/inputkit/terminal_visualization_instructions.py`（第 11 轮） |
| `app` | `tui/corekit/app.py`（第 12 轮，含既有安全接线保护） |
| `app_backtrack` | `tui/corekit/app_backtrack.py`（第 12 轮） |
| `app_command` | `tui/corekit/app_command.py`（第 12 轮） |
| `app_event` | `tui/corekit/app_event.py`（第 12 轮） |
| `app_event_sender` | `tui/corekit/app_event_sender.py`（第 12 轮） |
| `app_info` | `tui/corekit/app_info.py`（第 12 轮） |
| `chatwidget` | `tui/corekit/chatwidget.py`（第 12 轮） |
| `cli` | `tui/corekit/cli.py`（第 12 轮） |
| `resize_reflow_cap` | `tui/corekit/resize_reflow_cap.py`（第 12 轮） |

### 当前指标

```
总模块            165
aligned            30   (逐值对齐，第 12 轮 +9)
localized          57   (本地化等价)
not_applicable     63   (OpenAI 专属)
pending            15   (待对齐，第 12 轮 -9)
宽口径覆盖率      90.9%  (aligned+localized+na)
严格对齐率        52.7%  (aligned+localized)
逐值对齐率        18.2%  (aligned only)
完全相同           否    (pending != 0)
```

三个指标刻意都列出来：**不把「不适用」包装成成果**。真正逐值对齐的
只有 18.2%，这是后续轮次的主要工作量。

### 待对齐队列（15）

> 第 11 轮完成 `input_keymap` 组 7 个、第 12 轮完成 `core_app` 组 9 个，
> 两组 `pending = 0`。

```
approval_perm.    auto_review_denials
history_trans.    insert_history
session_startup   local_settings
tools_exec        exec_command, rendered_selection
config_models     collaboration_modes, model_migration, additional_dirs
updates_analytics clock_format
streaming_async   streaming, async_question_reply
external_editor   external_agent_config_migration
infra             tests
misc              sidebar_chooser, sidebar_tab_strip
```

`tuan tui parity --gaps` 实时输出同一份清单。

---

## 5. 后续轮次路线（直到 `pending == 0`）

| 轮次 | 目标组 | 产出 |
|---|---|---|
| 11 ✅ | `input_keymap`（7） | **已完成**：`tui/inputkit/` 7 个模块 + 88 例回归；Vim 搜索、激活键守卫、复制守卫、双缓冲 diff、OSC 状态、语义超链接、可视化指令 |
| 12 ✅ | `core_app`（9） | **已完成**：`tui/corekit/` 9 个模块 + 76 例回归；类型化事件/命令、脱敏 newtype、六步回退状态机、双生命周期 busy、审批冲突 fail-closed、四档重排上限；**6 项既有安全接线校验全绿** |
| 13 | `config_models` + `misc`（5） | `collaboration_modes` / `model_migration` / `additional_dirs` / `sidebar_chooser` / `sidebar_tab_strip` |
| 14 | `streaming_async` + `tools_exec` + `history_transcript`（5） | `streaming` / `async_question_reply` / `exec_command` / `rendered_selection` / `insert_history` |
| 15 | 剩余 5 个 | `local_settings` / `clock_format` / `external_agent_config_migration` / `tests` / `auto_review_denials`，清零 `pending` |

每轮必须同时满足：① 新增模块状态有实现与测试指向；② 既有回归全绿；
③ `parity_validate()` 无问题；④ 文档指标同步。**不靠改状态定义凑数。**

---

## 6. 本地化清单（允许的改动，逐条如实列出）

| 位置 | Codex 原文 | Tuan 本地化 |
|---|---|---|
| 全部 UI 文案 | 英文 | 10 语言 i18n，默认简体中文 |
| 视觉 token | Codex 主题 | Kimi Code MIT 视觉 token（NOTICE 第 1 条）+ 自有吉祥物 |
| 渲染后端 | ratatui `Widget`/`Buffer` | prompt_toolkit/rich 盒子渲染器 |
| 模型目录 | OpenAI 模型 | 本地/多厂商模型清单 |
| 登录/引导 | ChatGPT 账号 | 本地首启语言选择器，无账号 |
| 审批作用域 | `AcceptForSession` | E1 的 SESSION 是**写盘持久化**（跨重启，比上游更宽），卡片明示 |
| `approve_for_prefix` | 命令/权限前缀 | 本地无前缀模型 → 会话内临时授权，返回值标注 `prefix_localized_to_session` |
| `Esc` | exec 里是 decline | **ABORT**（更严格的 fail-closed，上一轮契约保留） |
| 确认通道 | ratatui 模态 | 现有 `ctx.confirm` 挂起式卡片 + headless 精确确认码 |
| 敏感标记 | 无 | `[!敏感]` 高亮 `.env`/私钥/credentials |
| 渲染后端（本轮） | crossterm / ratatui `Backend` | 可注入 Python `TerminalBackend` 协议，不依赖 PTY |
| grapheme 分段 | `unicode-segmentation` 扩展簇 | stdlib `unicodedata` 的 UAX #29 **近似**实现（如实标注：不声称逐字节一致） |
| 时间源 | `Instant` | `time.monotonic()` + 可注入时钟（确定性测试） |
| 超链接目的地 | `web()` 不校验 | **http/https 白名单 + 控制字符拦截**（更严格） |
| 终端状态发射 | `execute!(stdout())` | 默认 **no-op writer**，必须显式 `configure()`；detail 额外剥离 OSC/BEL 并限长 |
| 可视化指令 | 英文常量 | 中文常量为默认，英文原文保留供核销；ASCII-only 约束不变 |
| `custom_terminal` 图片 | kitty / sixel | 不实现（`not_applicable`），字段保留为空，不谎称支持 |
| 遥测/更新 | OpenAI 服务 | 本地统计，不上报、不接更新通道 |
| 事件通道（本轮） | tokio `UnboundedSender` | 可注入 sink + **有界队列**（满则拒绝计数），不引入无界内存增长 |
| 事件日志（本轮） | `session_log` / `tracing` | 可注入 logger；**未知事件名一律不记**（防敏感字段进日志） |
| wire 转换（本轮） | Rust 编译期类型 | **严格字段白名单**，未知字段拒绝而非透传；URL 限 http/https |
| 脱敏（本轮） | Debug / Serialize 输出 `<redacted>` | `repr`/`str`/`format`/`to_dict`/`==` 全脱敏，`reveal()` 唯一出口且计数（更严格） |
| 审批冲突（本轮） | clap `conflicts_with` 报错退出 | 结构化问题列表 + `is_safe_to_start()` 拒绝启动，原因可审计（更严格） |
| 线程提交（本轮） | 编译期 `ThreadId` | `validate_thread_op()` 拒绝空 id，防跨会话误投 |
| 回退选择（本轮） | `base_id` 变更失效 | 显式 `bind_thread()` 强制失效 + `confirm_revert()` 二次校验线程 |
| 重排上限（本轮） | 上游 config 常量 | fallback 显式默认 1000 且可注入；非法 `Limit` **fail-closed 回退**而非无限重放 |
| 实时语音 / 云命令 | `RealtimeConversation*` | 不实现（OpenAI 专属），仅保留变体名供白名单契约核验，标未实现 |

**键位、布局数值、组件树、交互契约没有本地化** —— 它们就是「完全相同」
的锚点。改动集中在「给人看的字」与「后端实现」，不动行为契约。

---

## 7. 使用方式

```bash
tuan tui parity              # 中文摘要
tuan tui parity --gaps       # 列出待对齐队列
tuan tui parity --report-json # 结构化 JSON（CI / 文档生成）
```

`--report-json` 而非 `--json` 是为了避开主解析器 `--json-schema*` 的
argparse 前缀歧义。

---

## 8. 合规声明

- 上游 `codex-tui` 为 **Apache-2.0**。`LICENSE` 与 `NOTICE` 原文完整照抄在
  `THIRD_PARTY_LICENSES/`（上游 NOTICE 另含 Ratatui 的 MIT 声明）。
  第 11 轮的 `inputkit/custom_terminal.py` 对齐的是上游明确标注
  「derived from `ratatui::Terminal`」、采用 **MIT** 的
  `custom_terminal.rs` 算法契约；MIT 全文归属于
  `THIRD_PARTY_LICENSES/Codex-NOTICE.txt` 与 `NOTICE` 第 11 条。
  第 12 轮的 `tui/corekit/` 9 个模块同属 `codex-rs/tui/src` 的
  Apache-2.0 范围，归属与本地化修改点逐条记在 `NOTICE` 第 12 条；
  同样**无 Rust 源码逐字复制**。
- 本仓库**未逐字复制任何 Rust 源码**。本轮新增的是可核验的功能事实
  （模块名、常量值、键位表、规范化规则）与 Python 独立实现，属于 Apache-2.0
  允许的派生设计；修改点已在 §6、模块 docstring 与 `NOTICE` 第 9 条列明。
- 组件树 / 键位 / 布局数值属于事实性内容，不主张版权；文案为**重新本地化**，
  不是上游表达性内容的复制。
- **OpenAI 不背书、不赞助本项目**（`NOTICE` 第 9 条明确声明）。
- 规模数字的口径更正如实记录于 §2，不隐藏上一轮的低估。
