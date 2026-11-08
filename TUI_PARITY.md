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

**第 13 轮：配置/侧栏对齐层**（`tuan_cli/tui/configkit/`，5 个模块，
纯 Python、零 Rust 源码）。本轮把 `config_models` + `misc` 两组从
`pending 5` 清零，**同样没有替换任何现有运行时对象**：

| 上游模块 | 本包落点 | 逐值/逐分支对齐点 |
|---|---|---|
| `additional_dirs.rs` | `additional_dirs.py` | 4 个早退分支（空目录 / Disabled·External / 全盘写 / cwd 可写）、警告模板英文原文、逗号空格拼接路径 |
| `collaboration_modes.rs` | `collaboration_modes.py` | `filtered_presets` 只留 `is_tui_visible`、`default_mask` 先 Default 再首个、`next_mask` 循环、`mask_for_kind` 先判可见性、**2 秒**发现超时、`developer_instructions: Some(None)` 清覆盖、5 字段严格白名单 |
| `model_migration.rs` | `model_migration.py` | `Accepted/Rejected/Exit` 三态、`TryNewModel/UseExistingModel` 两态及英文 label、强制与可选两套键位策略、`is_ctrl_exit_combo`（Ctrl+C/D）、`AltScreenGuard` RAII、标题/推荐语/可选退出行模板 |
| `sidebar_chooser.rs` | `sidebar_chooser.py` | `WIDE_WIDTH=58`、`body_row` 宽度 `area.width-3`、窄屏双行/宽屏单行分页、`choice_at` 命中、footer 三项 + 可选 `hide_pane`、`"←/→ resize · Enter/Esc done"` 短提示逐字、`CHAT_TAB=" Side chat "` |
| `sidebar_tab_strip.rs` | `sidebar_tab_strip.py` | `TabState` 三态、`targets()` 几何逐值（`width-1` / `plus=min(width,3)` / `available` / `(selected+1)-count`）、**add 按钮恒留最右**、hit 先查 add 再查 tab、三态样式映射 |

三条最值钱的修正（都不是「对齐」本身，且均已实测）：

1. **链式 `replace` 二次替换**。上游 `fill_migration_markdown` 先
   `.replace("{model_from}", current)` 再 `.replace("{model_to}", target)`。
   模型名来自服务端/配置，若 `current_model` 含字面量 `{model_to}`，
   会被第二次替换成 `target_model`。实测模板
   `"从 {model_from} 迁移到 {model_to}"` + current `"old-{model_to}-x"`
   上游产出 `"从 old-NEW-x 迁移到 NEW"`。本包改成**单次正则扫描**
   （一个 pass 同时替换两个占位符），替换值不参与后续匹配；
   未知 `{...}` 原样保留，不吞不展开。
2. **发现失败不能静默当空**。上游 `list()` 把超时、RPC 错误、协议
   错误一律压成空 `Vec` + warn（模块头原话 "Missing discovery adds no
   presets"）。调用方分不清「没查到」与「查了但没有」，一个网络错误
   会被当成「无需展示模式选择器」。`DiscoveryResult` 显式区分
   `ok / empty / unavailable / timeout / protocol_error`，`usable`
   只允许 `ok/empty`，调用方必须显式处理 `unavailable`。
3. **`--add-dir` 不能静默丢弃**。上游只返回一句警告字符串，让调用方
   "负责呈现"；忘了打印就等于静默忽略，用户以为加了可写根、实际操作
   落空或落到别处。`AddDirDecision` + `enforce()` 把「忽略」升级为
   **结构化拒绝**，并做 `..` / 控制字符 / NUL / 空串校验。
   刻意**不做**「越出 cwd」判定 —— `--add-dir` 的本意就是加工作区外的
   可写根，把它当错误会与语义冲突；真正的边界在沙箱层。

另外两处几何一致性契约：`choice_rows`（渲染分页）与 `choice_at`
（命中测试）共用同一份 `height/visible/start` 计算；`TabStrip.hit`
与 `render_plan` 共用 `targets()`。二者都提供 `*_matches_render()`
自检并进回归集 —— 否则会出现「点第 3 项却打开第 2 项」「点到的和
看到的不一致」这类偏差，在带权限的侧栏里会让用户误开另一个会话。

**一条必须挑明的上游语义**：`model_migration` 在**强制迁移**
（`can_opt_out=false`）下，Enter 与 **Esc 都接受**，事件流耗尽也默认
接受；仅在可选模式下 `2` 才是拒绝，且 Esc 是「确认当前选中」而非取消。
这与本项目审批覆盖层「无输入 / Esc 绝不变成同意」的 fail-closed 契约
**相反**。本包原样保留上游既有键盘策略，但用 `policy_note()`
显式标注并写进文档：它只适用于模型升级提示，**绝不套用到审批链路**。

**硬约束延续**：`configkit_validate()` 调用第 12 轮的
`corekit.app.assert_wiring_intact()`，确认本轮没破坏前 12 轮修好的
6 条既有安全接线；`tuan tui parity` 仍显示「既有链路完好」。

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
| config_models | 4 | 7 | 5 | **0** |
| updates_analytics | 0 | 2 | 5 | 1 |
| streaming_async | 1 | 0 | 2 | 2 |
| external_editor | 0 | 2 | 0 | 1 |
| daemon | 0 | 0 | 3 | 0 |
| infra | 2 | 0 | 2 | 1 |
| misc | 2 | 2 | 5 | **0** |

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
| `additional_dirs` | `tui/configkit/additional_dirs.py`（第 13 轮，忽略即拒绝） |
| `collaboration_modes` | `tui/configkit/collaboration_modes.py`（第 13 轮） |
| `model_migration` | `tui/configkit/model_migration.py`（第 13 轮） |
| `sidebar_chooser` | `tui/configkit/sidebar_chooser.py`（第 13 轮） |
| `sidebar_tab_strip` | `tui/configkit/sidebar_tab_strip.py`（第 13 轮） |

### 当前指标

```
总模块            165
aligned            35   (逐值对齐，第 13 轮 +5)
localized          57   (本地化等价)
not_applicable     63   (OpenAI 专属)
pending            10   (待对齐，第 13 轮 -5)
宽口径覆盖率      93.9%  (aligned+localized+na)
严格对齐率        55.8%  (aligned+localized)
逐值对齐率        21.2%  (aligned only)
完全相同           否    (pending != 0)
```

三个指标刻意都列出来：**不把「不适用」包装成成果**。真正逐值对齐的
只有 21.2%，这是后续轮次的主要工作量。

### 待对齐队列（10）

> 第 11 轮完成 `input_keymap` 组 7 个、第 12 轮完成 `core_app` 组 9 个、
> 第 13 轮完成 `config_models` + `misc` 组 5 个，三组 `pending = 0`。

```
approval_perm.    auto_review_denials
history_trans.    insert_history
session_startup   local_settings
tools_exec        exec_command, rendered_selection
updates_analytics clock_format
streaming_async   streaming, async_question_reply
external_editor   external_agent_config_migration
infra             tests
```

`tuan tui parity --gaps` 实时输出同一份清单。

---

## 5. 后续轮次路线（直到 `pending == 0`）

| 轮次 | 目标组 | 产出 |
|---|---|---|
| 11 ✅ | `input_keymap`（7） | **已完成**：`tui/inputkit/` 7 个模块 + 88 例回归；Vim 搜索、激活键守卫、复制守卫、双缓冲 diff、OSC 状态、语义超链接、可视化指令 |
| 12 ✅ | `core_app`（9） | **已完成**：`tui/corekit/` 9 个模块 + 76 例回归；类型化事件/命令、脱敏 newtype、六步回退状态机、双生命周期 busy、审批冲突 fail-closed、四档重排上限；**6 项既有安全接线校验全绿** |
| 13 ✅ | `config_models` + `misc`（5） | **已完成**：`tui/configkit/` 5 个模块 + 106 例回归；修链式 replace 二次替换、发现失败不冒充空、`--add-dir` 忽略即拒绝；两处 hit/render 几何同源自检；**6 项既有安全接线仍全绿** |
| 14 | `streaming_async` + `tools_exec` + `history_transcript`（5） | `streaming` / `async_question_reply` / `exec_command` / `rendered_selection` / `insert_history` |
| 15 | 剩余 5 个 | `local_settings` / `clock_format` / `external_agent_config_migration` / `tests` / `auto_review_denials`，清零 `pending` |

> **A/B 双线并行（2026-11-07 起）**：本节是 **A 线**（把 TUI 对齐
> OpenAI Codex）。同日启动的 **B 线**是「全模块超 Claude Code v2.1.319」，
> 见 `CLAUDE_PARITY.md` 与 `tuan claude parity`。两条线共享
> `assert_wiring_intact()` 硬约束，但**互不修改对方文件**：A 线不碰
> `tuan_cli/parity_claude/`，B 线不碰 `tuan_cli/tui/parity/`。A 线剩余
> 10 个 pending 仍按本节 A14/A15 清零，不因 B 线启动而重排。

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
| 迁移模板（本轮） | 链式 `.replace(A).replace(B)` | **单次正则扫描**，替换值不参与后续匹配；未知 `{...}` 原样保留（更严格） |
| 模式发现（本轮） | 失败一律空 `Vec` + warn | `DiscoveryResult` 区分 5 态，`usable` 只允许 ok/empty，调用方必须显式处理失败（更严格） |
| 模式 RPC 字段（本轮） | Rust 编译期类型 | 严格 5 字段白名单 + 控制字符/长度校验；`prompts_omitted=True` 让「服务端提供当前指令」可审计 |
| `--add-dir`（本轮） | 仅返回一句警告字符串 | `AddDirDecision` + `enforce()` **忽略即拒绝**，附退路径校验；刻意不做「越出 cwd」判定（与语义冲突） |
| 侧栏几何（本轮） | ratatui `Rect`/`Buffer` | 纯 Python dataclass；`tab_width=0` 显式返回空而非除零；CJK 显示宽度用 `east_asian_width` **近似**（如实标注，不声称逐字节一致） |
| 侧栏文案（本轮） | 英文 | 中文默认 + 英文原文常量保留供核销；短 resize 提示 `"←/→ resize · Enter/Esc done"` **逐字不改** |
| 强制迁移键盘策略（本轮） | Esc 也 accept、事件耗尽默认 accept | **原样保留**（上游既有策略），但 `policy_note()` 显式标注与审批 fail-closed 相反，绝不套用到审批链路 |

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
  第 12 轮的 `tui/corekit/` 9 个模块与第 13 轮的 `tui/configkit/`
  5 个模块同属 `codex-rs/tui/src` 的 Apache-2.0 范围，归属与本地化
  修改点逐条记在 `NOTICE` 第 12、13 条；同样**无 Rust 源码逐字复制**。
- 本仓库**未逐字复制任何 Rust 源码**。本轮新增的是可核验的功能事实
  （模块名、常量值、键位表、规范化规则）与 Python 独立实现，属于 Apache-2.0
  允许的派生设计；修改点已在 §6、模块 docstring 与 `NOTICE` 第 9 条列明。
- 组件树 / 键位 / 布局数值属于事实性内容，不主张版权；文案为**重新本地化**，
  不是上游表达性内容的复制。
- **OpenAI 不背书、不赞助本项目**（`NOTICE` 第 9 条明确声明）。
- 规模数字的口径更正如实记录于 §2，不隐藏上一轮的低估。


---

## 增量：运行时标语与 TUI 状态口径修复（不占 Codex 对齐指标）

本轮新增 `tuan_cli/tui/runtime_slogans.py`，在 Codex 风格 Working 状态行旁挂
**Claude Code 同款**运行时标语（10 语言本地化，中文保留「磨洋工 / 腌制入味 /
看报纸中」梗）。它是「与 Codex 完全相同**但有自己本地化**」这条 A 线约束的
具体体现：**转圈机制、键位、布局数值、组件树一律不动**，只在文案层做本地化，
且刻意比上游更诚实 —— 文案由真实事件驱动，忙碌无进展时显示「疑似摸鱼」
诊断，而不是靠定时器空转装忙。详见 `RUNTIME_SLOGANS.md`。

同时修两个实测缺陷，均**不改变任何 Codex 对齐指标**（`pending`、
`fully_identical`、逐值对齐率保持原值，不靠改状态定义凑数）：

| 编号 | 缺陷 | 修复 |
|---|---|---|
| B2 | `_render_footer` 判定顺序让 `_running` 分支成死代码，工具运行时显示 `Working (...)` | 工具名优先，状态与真实活动一致 |
| B3 | `_disp_width` 与 `_display_width` 两套宽度算法，视口切片与单行裁剪口径分裂 | 统一到 `_display_width` 单一真值来源 |

**B1 口径如实更正**：主线 `_line_heights` 已自带 `(width, text)` 高度缓存，
本地分叉副本上实测的 16.2 → 0.39 ms/帧 **不适用于主线**；本轮在主线只修正
「wcwidth 是 C 实现」的错误注释并加有界 LRU 作第二层保险，不宣称性能成果。

回归 `tests/test_runtime_slogans.py` 57 例全绿（远端基线 + 本轮改动副本）。
许可口径：该能力对标的是 Claude Code 的公开 UI 行为（专有产品，仅行为契约
对标、未复制源码），归 `NOTICE` 第 15 条；**不与本文件 §6–§8 的
Apache-2.0 / MIT Codex 归属混用**。


---

## 深度轮（不占任何 Codex 对齐指标）

本轮只深化「运行时标语」这条线，**`pending` / `fully_identical` /
逐值对齐率 / 宽口径覆盖率全部保持原值**，不靠改状态定义凑数：

- 引擎在 `RLock` 内线性化（UI / 模型 / 工具线程并发进入，动画线程渲染）；
- 单一 15s 阈值改为分阶段活性预算 + 三态；
- `Liveness` 结构化快照 + 脱敏证据链 + 10 语言分类建议；
- `note_progress` 补 `end_tool` / `end_stream` 生命周期事件，
  并从源码层禁止在 `_animate` 刷新活性（否则诊断退化成定时空转）；
- header 三态分级 warning / textdim / primary。

**Codex 的键位、布局数值、组件树、交互契约一律未动** —— 这正是
「完全相同但有自己本地化」的 A 线约束。93 例 pytest + 22 项纯 stdlib
独立验证全绿。详见 `RUNTIME_SLOGANS.md` §10。


---

## 深度轮 2（仍不占任何 Codex 对齐指标）

本轮只深化运行时标语的净化与 header 呈现，
**`pending` / `fully_identical` / 逐值对齐率 / 宽口径覆盖率全部保持原值**：

- 净化层补齐 bidi/零宽/ESC 序列/变体选择符/组合标记开头，
  grapheme 簇边界截断，构造性幂等；
- `display_cols()` 与 `tui._display_width` 做 500 串交叉一致回归，
  堵住 B3 漏掉的第三套宽度算法；
- 诊断态 header 改用短版 `headline`，完整诊断留在 `diagnostic`；
  **普通态的 Codex `Working (Ns • esc)` 状态行完全不动**，
  键位、布局数值、组件树、交互契约一律未改。

40 列窄终端、10 语言短文案、139 例 pytest + 20 项纯 stdlib 验证全绿。
详见 `RUNTIME_SLOGANS.md` §11。


---

## 「每个标语都要对应的」（不占任何 Codex 对齐指标）

本轮把用户提供的 15 文件标语库接到真实运行时事件上,
**`pending` / `fully_identical` / 逐值对齐率 / 宽口径覆盖率全部保持原值**:

- 包落到正确路径 `tuan_cli/ui/slogans/`, 根目录历史包改薄垫片;
- 18 事件 ↔ 16 上下文双向表 + 1695 条注册项 + 10 项 `audit()` 不变量;
- 240 条补池消除 48 个跨语种英文组合, 5400 次分发 0 次落到兜底;
- 净化层抽到 `_clean.py`, 活性引擎 re-export **同一函数对象**;
- TUI 四个真实生命周期点分发并留痕, **不替换任何既有 i18n 文案**,
  Codex 状态行 / 键位 / 布局数值 / 组件树 / 交互契约一律未改。

175 例 pytest + 26 项纯 stdlib 验证全绿。详见 `SLOGAN_MAPPING.md`。


---

## 运行时留痕闭环（不占任何 Codex 对齐指标）

本轮只把「事件 → 标语」的对应关系在运行时做实,
**`pending` / `fully_identical` / 逐值对齐率 / 宽口径覆盖率全部保持原值**:

- TUI 留痕补 `entry_id`/`owner`/`at_ms`, `slogan_trace()` 可反查;
- 未知事件由静默吞掉改为必留痕 (`strict=True` 才向上抛);
- 日志按实例分域 + `RLock`, O(1) 索引, `Counter` 审计, rng/clock 回放;
- **未新增任何生命周期事件**, `begin_tool`/`stream_assistant`/
  完成/`close` 四个点不变; **未替换任何既有 i18n 文案**;
  Codex 状态行 / 键位 / 布局数值 / 组件树 / 交互契约一律未改。

194 例 pytest + 42 项纯 stdlib 验证全绿。详见 `SLOGAN_MAPPING.md` §11。


---

## 闭环补漏（不占任何 Codex 对齐指标）

本轮只把上一轮的运行时对应关系补漏，**`pending` / `fully_identical` /
逐值对齐率 / 宽口径覆盖率全部保持原值**：

- `_BY_CLEAN` 净化后索引 + miss fail-closed；owner 桶 LRU 上界与
  `close()` 释放；错误双层留痕；`_MAX_WINDOWS` 按真实 key 空间算；
  `audit()` 不变量加严。
- **未新增任何生命周期事件**，四个分发点不变；**未替换任何既有
  i18n 文案**；Codex 状态行 / 键位 / 布局数值 / 组件树 / 交互契约
  一律未改。

215 例 pytest + 52 项纯 stdlib 验证全绿。详见 `SLOGAN_MAPPING.md` §12。


---

## 自愈与证据保全（不占任何 Codex 对齐指标）

本轮只把前三轮的运行时对应关系补漏，**`pending` / `fully_identical` /
逐值对齐率 / 宽口径覆盖率全部保持原值**：

- 连续 miss 自愈且累计证据/日志不丢；`close()` 封存含 `session.exit`
  的桶快照；`dispatch_log(owner)` 读刷新 LRU；日志字段统一净化；
  `sanitized` 与 `unrenderable` 分离；分发与索引共用单一渲染出口。
- **未新增任何生命周期事件**，四个分发点不变；**未替换任何既有
  i18n 文案**；Codex 状态行 / 键位 / 布局数值 / 组件树 / 交互契约
  一律未改。

234 例 pytest + 64 项纯 stdlib 验证全绿。详见 `SLOGAN_MAPPING.md` §13。


---

## owner 归一与淘汰留痕（不占任何 Codex 对齐指标）

本轮只把前四轮的运行时对应关系补漏，**`pending` /
`fully_identical` / 逐值对齐率 / 宽口径覆盖率全部保持原值**：

- public 入参 `owner` 全链路归一且严格幂等；`limit` 脏值不再抛
  异常；LRU 被动淘汰留脱敏痕迹；`close()` 收敛到
  `take_owner_log()` 单一出口；`_slogan_sealed` 写加锁。
- **未新增任何生命周期事件**，四个分发点不变；**未替换任何既有
  i18n 文案**；Codex 状态行 / 键位 / 布局数值 / 组件树 / 交互契约
  一律未改。

256 例 pytest + 73 项纯 stdlib 验证全绿。
详见 `SLOGAN_MAPPING.md` §14。


---

## 净化顺序与淘汰痕摘要（不占任何 Codex 对齐指标）

本轮只把前五轮的运行时对应关系补漏，**`pending` /
`fully_identical` / 逐值对齐率 / 宽口径覆盖率全部保持原值**：

- 日志字段改为先清理后截断（带 64KiB 扫描上限）；连续 ESC 串
  整体删，不再吞掉尾部合法字符；淘汰痕与 decision 共用注入时钟；
  `EvictionRecord` 增 `reason_counts`；`OWNER_LIMIT` 口径精确化。
- **未新增任何生命周期事件**，四个分发点不变；**未替换任何既有
  i18n 文案**；Codex 状态行 / 键位 / 布局数值 / 组件树 / 交互契约
  一律未改。`tui.py` 本轮文件零改动。

276 例 pytest + 80 项纯 stdlib 验证全绿。
详见 `SLOGAN_MAPPING.md` §15。


---

## ESC+ 与时钟严格化（不占任何 Codex 对齐指标）

本轮只把前六轮的运行时对应关系补漏，**`pending` /
`fully_identical` / 逐值对齐率 / 宽口径覆盖率全部保持原值**：

- OSC/CSI 允许 `ESC+` 引导；注入时钟严格类型校验且合法 0 不再被吞；
  owner 用有界摘要；淘汰累计证据 `evicted_total`。
- **未新增任何生命周期事件**，四个分发点不变；**未替换任何既有
  i18n 文案**；Codex 状态行 / 键位 / 布局数值 / 组件树 / 交互契约
  一律未改。`tui.py` 本轮文件零改动，**未包含在本轮推送清单**。

300 例 pytest + 88 项纯 stdlib 验证全绿。
详见 `SLOGAN_MAPPING.md` §16。


---

## 裁剪证据（不占任何 Codex 对齐指标）

本轮只把前七轮的运行时对应关系补漏，**`pending` /
`fully_identical` / 逐值对齐率 / 宽口径覆盖率全部保持原值**：

- `mapping.py` 新增桶内裁剪留痕与累计决策数；净化层、TUI、
  生命周期事件、i18n 文案、Codex 状态行 / 键位 / 布局数值 /
  组件树 / 交互契约**一律未改**。
- **`tui.py` 本轮逐字节未改，未包含在本轮推送清单。**

319 例 pytest + 97 项纯 stdlib 验证全绿。
详见 `SLOGAN_MAPPING.md` §17。


---

## public 入参类型面（不占任何 Codex 对齐指标）

本轮只把前八轮的运行时对应关系补漏，**`pending` /
`fully_identical` / 逐值对齐率 / 宽口径覆盖率全部保持原值**：

- `mapping.py` 加 event 类型守卫与非字符串 owner 隔离留痕；
  净化层、TUI、生命周期事件、i18n 文案、Codex 状态行 / 键位 /
  布局数值 / 组件树 / 交互契约**一律未改**。
- **`tui.py` 本轮逐字节未改，未包含在本轮推送清单。**
  但 `_slogan_dispatch` 的 `except UnboundSloganEvent` 现在真的能
  接住不可 hash 的 event（`strict=True` 契约不再被底层
  `TypeError` 绕过），这是行为修复而非对齐改动。

343 例 pytest + 105 项纯 stdlib 验证全绿。
详见 `SLOGAN_MAPPING.md` §18。


---

## 引擎入参面（不占任何 Codex 对齐指标）

本轮只把引擎本体的 public 入参面补漏，**`pending` /
`fully_identical` / 逐值对齐率 / 宽口径覆盖率全部保持原值**：

- `runtime_slogans.py` 加统一时钟入口、`kind` / `source` / `detail`
  净化、`reset` 时钟同源、`path` 的 try 边界；
  `mapping.py` / `_clean.py` / **TUI** / 生命周期事件 / i18n 文案 /
  Codex 状态行 / 键位 / 布局数值 / 组件树 / 交互契约**一律未改**。
- **`tui.py` 本轮逐字节未改，未包含在本轮推送清单。**

376 例 pytest + 117 项纯 stdlib 验证全绿。
详见 `SLOGAN_MAPPING.md` §19。
