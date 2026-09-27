# 竞品调研报告：身份提示词 / Skills 系统 / 用户体验

> 调研日期：2026-09-27
> 调研对象：Claude Code、Kimi Code、OpenAI Codex CLI、Google Gemini CLI（Antigravity）
> 用途：为「青小团 qxt」Agent CLI 做对标与差距分析提供事实底座
>
> 信源标注约定：
> - 【官方已查证】= 官方文档 / 官方 changelog / 官方 GitHub / npm  registry
> - 【第三方实测】= 独立评测站、社区博客、拆解文章
> - 【一方宣称】= 官方宣传但未独立复现

---

## 0. 版本与基本面（双信源核对）

| 产品 | 最新版本 | 发布时间 | 运行时形态 | 信源 |
|---|---|---|---|---|
| Claude Code | **v2.1.283**（npm `@anthropic-ai/claude-code`） | 2026-09-26 | 按平台分发的原生二进制（不再走 Node 打包 JS）；npm 通过 optional dep 拉 `@anthropic-ai/claude-code-<platform>` | 【官方已查证】npm registry、code.claude.com/docs/en/changelog；【第三方实测】releasealert.dev、aicoder.com 交叉核对 |
| Kimi Code CLI | **v2.0.0**（npm `@moonshot-ai/kimi-code`） | 2026-09-17 | 从 Python/uv 整体重写为 **TypeScript/Node.js**；同日发布 Kimi Code Desktop（macOS/Windows） | 【官方已查证】kimi.com/code/docs、moonshotai.github.io/kimi-code；旧 `kimi-cli` 仓库已归档 |
| OpenAI Codex CLI | **v0.157.1**（npm `@openai/codex`） | 2026-09-26 | **Rust** 实现；npm 包为分发入口；内置 background daemon / app-server 架构 | 【官方已查证】npmjs.com/package/@openai/codex；【第三方实测】aicoder.com、danielvaughan.com 释放指南交叉核对 |
| Gemini CLI / Code Assist | **已停服个人版**，2026-06-18 起个人/Google AI Pro/Ultra 流量切到 **Antigravity / Antigravity CLI** | 2026-06-18 | Node.js CLI 仍开源于 `google-gemini/gemini-cli`，但官方已停止个人版服务 | 【官方已查证】developers.google.com/gemini-code-assist/docs、docs.cloud.google.com release notes |

> 重要背景：Google 把 Gemini Code Assist 个人版并入 Antigravity 后，"Gemini CLI"作为独立竞品的连续性已经断裂。本报告仍将其作为"系统提示词可完全外部覆盖"这一做法的参考样本，但不把它作为活跃对标产品打分。

---

## 1. Claude Code（Anthropic）

官方文档入口：https://code.claude.com/docs/en/ ；changelog 由 GitHub CHANGELOG.md 自动生成。

### A. 身份提示词 / 系统提示词

**A1. 系统提示词的缓存/非缓存分段结构**【官方已查证 + 第三方拆解】

Claude Code 的系统提示词被显式切成"可缓存前缀"和"动态后缀"两段，这是其 prompt cache 友好性的核心设计：

- **缓存段（静态、全局可复用）**：身份定义、工具 schema、行为准则。跨会话、跨项目命中同一缓存前缀。
- **非缓存段（每次会话动态拼接）**：会话级指引、Memory（MEMORY.md + memory 文件）、运行环境（cwd / platform / model）、语言偏好、Output Style（若配置）、MCP 指令（永远不缓存）、Scratchpad 目录（若启用）、Function Result Clearing（若开 CACHED_MICROCOMPACT）。

> 信源：claude-code-explain.helmcode.com/system-prompt/ 对系统提示词分段的拆解【第三方实测】；官方 `ENABLE_PROMPT_CACHING_1H` 环境变量（changelog 2.1.108，2026-04-14）【官方已查证】。

**A2. 记忆注入的分层与顺序**【官方已查证】

按从高到低、从外到内的顺序拼接：

1. Managed：`/etc/claude-code/CLAUDE.md`（组织策略）
2. User：`~/.claude/CLAUDE.md`（个人全局规则）
3. Project：`CLAUDE.md`、`.claude/CLAUDE.md`，从 CWD 向上走到 repo root
4. Local：`CLAUDE.local.md`（私域、gitignore）
5. 仅当工作目录及以上都没有 CLAUDE.md 时，才回退到 AGENTS.md 风格文件。

**Auto Memory（自动记忆）**：Agent 自己往 `~/.claude/projects/<project-slug>/memory/` 写笔记，入口是 `MEMORY.md`，有 **200 行注入上限**；另提供 user/project/local 三档 agent-memory 目录（`~/.claude/agent-memory/`、`.claude/agent-memory/`、`.claude/agent-memory-local/`）。Agent 被指示"直接用 Write 工具写，不要 mkdir、不要检查存在性"。
> 信源：docs.anthropic.com/en/docs/claude-code/memory【官方已查证】；cc.bruniaux.com 指南【第三方实测】。

**A3. 压缩协议（compaction）**【官方已查证】

- 接近上下文上限时**自动 compact**，效果等价于手动 `/compact`；`/compact` 接受 focus 指令（`/compact 保留数据库相关讨论`）。
- **Micro-compact**：针对单个超大工具结果原地压缩（如 `npm test` 500 行只留 3 条失败），而非整段会话摘要。
- compact 后哪些东西"活下来"有一张明确表：系统提示词与输出风格继续生效；项目根 CLAUDE.md 与无 scope 规则从磁盘重注入；Auto Memory 从磁盘重注入；Git status 快照重新读取；plan 模式写的 plan 从磁盘重注入。
- 服务端 compaction beta（`compact-2026-01-12`）支持 `PauseAfterCompaction`。

**A4. 输出风格 / 多语言 / persona**【官方已查证】

- Output Style 是可配置项，放在非缓存段；系统提示词里有专门的 "Output Efficiency" 段落。
- 语言偏好作为独立字段注入。
- 可通过 CLAUDE.md 自定义 persona；Subagent 体系（`claude agents`）允许按会话定义独立身份。

### B. Skills 系统

**B1. SKILL.md 格式**【官方已查证】

每个技能是一个目录，内含一个 `SKILL.md`：

```
.claude/skills/security-check/
└── SKILL.md
```

- YAML frontmatter 必填 `name`、`description`；`description` 决定 Claude 何时自动调用。
- 正文是 Markdown 指令，可选附带 `FORMS.md`、`REFERENCE.md`、脚本等资源。
- 保留命名空间 `anthropic-skills:`（如 `anthropic-skills:pdf`），用于从 claude.ai 同步的技能。

**B2. 发现 / 加载 / 执行闭环（懒加载是关键）**【官方已查证】

- **会话启动时只加载 name + description**，正文不进上下文。
- 当 Claude 判断相关、或用户输入 `/skill-name` 时，才把完整 SKILL.md 正文读进上下文。
- 位置：`~/.claude/skills/`（个人）、`.claude/skills/`（项目）。
- 官方博客把内部技能归为 9 大类，强调"最好的技能只干净地落在一类里"。

**B3. 与 Hooks / Plugins / MCP 的联动**【官方已查证】

- 技能可注册动态 hooks；插件系统（`claude plugin enable/disable`）支持依赖强制（2.1.143 起）。
- `claude mcp login` 从 shell 完成 MCP server 鉴权（week 26）。
- v2.1.283 新增 `/doctor prompt-audit`，对 CLAUDE.md / skills / agents / commands 做提示词审计【官方已查证，aicoder.com 转述】。

**B4. 可蒸馏 / 自动学习**：未见官方"从对话自动生成技能"的闭环文档；auto memory 写的是记忆笔记，不是可复用技能包。

### C. 用户体验（TUI / 交互）

**C1. 渲染层**【官方已查证】

- **Fullscreen 渲染自 2026-05-06 起成为默认**（对 feature-flag 命中的新用户）；`/tui fullscreen` 可在会话中切换"无闪烁渲染"。
- Diff 面板有独立 keybinding 上下文（`DiffDialog` / `DiffPanel`）。

**C2. 会话与时间旅行**【官方已查证】

- `/rewind`（别名 `/undo`）可回退；week 26 起 `/rewind` 能恢复 `/clear` 之前的对话——重开的会话从回退点启动，而不是从磁盘上更长的 transcript 启动。
- `/resume`、background sessions 置顶后保持活跃并出现在 `/resume` 列表。
- `/compact`、`/clear`（别名 `/reset`、`/new`，项目记忆保留）、`/btw`（侧信道短问，不打断主轮次；Shift+Left/Right 在 btw 答复间切换，v2.1.257 起）。

**C3. 视图与帮助**【官方已查证】

- 三档视图：Verbose / Normal / Summary（从完整工具调用透明到只看结果）。
- `⌘+/`（Ctrl+/）呼出完整快捷键表；footer 指示条导航（tasks / teams / diff / artifacts）。
- `!` 前缀 shell mode：直接给 shell mode 命令输出一个 Claude 回复（week 26）。

**C4. Onboarding / 错误处理**：`claude doctor`、启动时对 wildcard Bash allow 规则给警告（2.1.246）。

---

## 2. Kimi Code（Moonshot AI）

官方文档：https://moonshotai.github.io/kimi-code/ ；changelog：https://www.kimi.com/code/docs/en/kimi-code/whats-new.html

### A. 身份提示词 / 系统提示词

**A1. 系统提示词的外部覆盖机制**【官方已查证】

- `$KIMI_CODE_HOME/SYSTEM.md`：写一份纯 Markdown 即可**永久替换**主 agent 的系统提示词，无需每次 `--agent` / `--agent-file`；显式传入的 agent file 优先级更高。（v0.29.0）
- 插件可通过 `kimi.plugin.json` 的 `systemPrompt` / `systemPromptPath` 字段向系统提示词注入指令，且在 TUI、`kimi -p`、`kimi web` 三种入口同时生效。（v0.31.0）

**A2. 多身份 / Subagent**【官方已查证】

- 自定义 agent 就是一个 Markdown 文件：frontmatter 声明 name / description / 工具权限，正文即系统提示词。v0.29 起在 web 可用，v0.31 起 TUI 也可用。
- 内置三类 subagent：`coder`（通用工程）、`explore`（只读快速探查）、`plan`（架构与实现规划）。
- **每个 subagent 拥有完全独立的上下文窗口**：只能看到主 agent 显式传入的任务描述，看不到主对话历史；中间推理与工具调用不回流，只有最终结果回到主上下文。
- v0.36.0 引入 subagent **model pool**：`[secondary_model]` 下列候选模型与描述，主 agent 按任务自选；可 `/secondary-model` 钉死默认。

**A3. 项目指令 / 记忆**【官方已查证】

- Skills 与 global agent instructions 从 `KIMI_CODE_HOME` 加载。
- `/compact` 摘要时**把 to-do list 附在摘要后面**，防止 agent 忘记进度。（v0.8.0）
- Micro compaction 默认开启（v0.12.0 stable）：裁剪过大的旧工具结果；`experimental.micro_compaction = false` 可关（v0.22.1 移除该开关）。
- `/model`、`/effort` 切换时会**警告 prompt cache 将失效**，建议 `/new` 以省 token。（v0.28.0）

### B. Skills 系统

**B1. 技能形态**【官方已查证】

- 内置 Skill 直接出现在斜杠命令面板里，**不需要 `skill:` 前缀**；输入 `/` 即见，按组排在外部 Skill 前面。（v0.11.0）
- 单个 prompt 可激活多个 Skill：在空白后输入 `/` 插入 skill 标签；agent 忙时输入的 skill 命令会**排队而非拒绝**。（v0.37.0）

**B2. Sub-Skill 自治理体系（差异点）**【官方已查证】

实验性 Sub-Skill 系统自带两个治理技能：
- `sub-skill.review`：审计现有技能；
- `sub-skill.consolidate`：把技能合并成层级组。
（v0.11.0，需 `KIMI_CODE_EXPERIMENTAL_SUB_SKILL=1`）

**B3. 插件 = Skills + MCP + 斜杠命令 + Agents 的打包单元**【官方已查证】

- v0.4.0 起插件系统上线，官方 marketplace 首个插件是 Kimi Datasource。
- v0.6.0 支持直接贴 GitHub URL 装社区插件，可钉版本，按 trust level 标注。
- v0.21.0 插件 manifest 的 `commands` 字段注册 `<plugin>:<command>`，支持 `$ARGUMENTS` 展开。
- v0.31.0 插件可自带 agents（manifest `agents` 字段，或插件根放 `agents/` 目录）。

### C. 用户体验

**C1. TUI 渲染**【官方已查证】

- v2.0 重写后是完整 TUI：chat view + status bar + approval panel。
- 实验性全屏 alternate-screen 模式（`KIMI_CODE_TUI_FULL_SCREEN=1`）：可滚动 transcript 视口、鼠标选文本、可点链接、Ctrl-Shift-F 搜索。（v0.36.0）
- TUI 直接渲染 LaTeX 数学公式（`$…$` / `$$…$$` → Unicode 公式）。（v0.36.0）
- 连续工具调用折叠成可堆叠分组，带 diff 行数与图片/视频/音频内联预览。（v0.28.0）
- `Cmd/Ctrl+K` 会话搜索面板，按标题 / workspace / 最近 prompt 过滤。（v0.28.0）

**C2. 交互模式与权限**【官方已查证】

- 三档权限：Always Ask / Ask When Needed / Never Ask；另设 `/auto`（自动批工具但不问问题，适合无人值守）与 `/yolo`。
- `Ctrl-X` 在 Agent 模式与 Shell 模式间切换。
- `/btw` 侧信道、`/swarm <task>` 多 agent 并行（v0.12.0，自动退出）。
- Goal 模式 + Goal 队列（`/goal next <objective>`，可 `manage` 重排）；后台结构化提问（agent 需要决策时挂起问题继续干别的）。
- workspace trust 提示会**展示项目 MCP 启动目标，默认拒绝信任**；不可信 workspace 不能同名种 `fd`/`stty` 可执行文件。（v0.36.0）

**C3. 工程化入口**【官方已查证】

- `kimi doctor` 校验配置语法；`/experiments` 可视化开关面板，改完自动写 config.toml 并 reload；`/reload` 热重载。
- `kimi acp` 通过 ACP 协议接入 Zed / JetBrains AI Chat。
- `kimi web` 前台运行自动开浏览器；会话可导出 Markdown 或打包 ZIP 提交反馈。
- 定时任务：自然语言设定时 / 一次性提醒。（v0.5.0）

---

## 3. OpenAI Codex CLI

官方：https://github.com/openai/codex ；文档：https://docs.github.com / platform.openai.com/docs/codex

### A. 身份提示词 / 系统提示词

**A1. AGENTS.md 分层**【官方已查证 + 第三方实测】

Codex 把项目指令统一收敛到 AGENTS.md：

- `~/.codex/AGENTS.md`：个人全局默认；
- `repo-root/AGENTS.md`：团队约定；
- `repo-root/src/api/AGENTS.md`：子目录局部指令。

自上而下合并。默认大小上限 **32 KiB**，可在 `~/.codex/config.toml` 用 `project_doc_max_bytes` 调整（示例给到 65536）；`project_doc_fallback_filenames` 可配回退文件名（如 `TEAM_GUIDE.md`、`.agents.md`）。
> 信源：learn.microsoft.com Azure Foundry Codex 文档【官方已查证】；danielvaughan.com context engineering 指南【第三方实测】。

**A2. 模型级 instructions 覆盖**【官方已查证】

`config.toml` 的 `model_instructions_file` 指定时，instructions 字段从该文件读；否则用模型自带的 `base_instructions`（打包在 CLI 仓库里，随版本发布）。

**A3. 压缩 / 上下文**【第三方实测】

- `/compact` 是有损摘要；`/status` 显示 model、token 用量、git branch、sandbox 模式。
- v0.134.0 起会话历史可搜索；v0.136.0 起会话归档（session archiving）。

### B. Skills 系统

**B1. SKILL.md 开放标准（跨厂商可移植）**【第三方实测，方向与 Anthropic 一致】

Codex 采用了与 Claude Code 同源的 SKILL.md 开放标准，四档位置：

| Scope | 路径 | 用途 |
|---|---|---|
| REPO | `.agents/skills/`（当前/父/根目录） | 团队工作流，进 git |
| USER | `$HOME/.agents/skills/` | 个人技能集 |
| ADMIN | `/etc/codex/skills/` | 组织级默认 |
| SYSTEM | 随 CLI 打包 | 内置技能 |

- 调用方式：显式 `$skill-name`，或 `policy.allow_implicit_invocation: true` 时由模型隐式触发。
- frontmatter 字段比 Claude Code 多：`display_name`、`short_description`、`default_prompt`（选中时预填 composer）、`policy`。
- 旧的自定义 prompt（`~/.codex/prompts/*.md`，`/prompts:deploy-dev` 调用）已被官方标记 deprecated，v0.117.0 做了迁移到 Skills 的 breaking change。
> 信源：codex.danielvaughan.com/2026/05/05/agent-skills-open-standard、/2026/04/10/migrating-custom-prompts-to-skills【第三方实测】。

**B2. 与 MCP / Plugin**【官方已查证】

- MCP 并发：v0.134.0 起只读 MCP 工具可并行跑。
- v0.146.0 起对齐 MCP 2026-07-28 终版规范（stateless core + Tasks extension + MCP Apps）；TUI 因不能渲染 iframe，MCP Apps 仅在 ChatGPT 桌面端内联。
- v0.147.0 起 secrets redaction、project trust gates、plugin search。

### C. 用户体验

**C1. 安全模型：sandbox 与 approval 解耦**【官方已查证】

这是 Codex 最有特色的 UX 决策：
- `--sandbox` 控制"技术上能干什么"（Seatbelt / bubblewrap / Windows sandbox 三层进程架构：`codex.exe` + `codex-windows-sandbox-setup.exe` + `codex-command-runner.exe`）；
- `--approve-for-me`（或 `approval_policy`）控制"什么时候必须问"；
- 旧的 `--full-auto` 被废弃，拆成这两个正交控制。
- approval 三档：`untrusted`（执行前全问）/ `on-request`（不确定才问）/ `never`。

**C2. 渲染与后台化**【官方已查证 + 第三方实测】

- v0.157.0 起**全屏 transcript 默认开启**，background server（daemon）自动随 TUI 启动；`f` 快捷键 fork 被锁住的对话；remote 与本地 daemon 会话都支持 `/import`。
- `codex exec` 非交互模式专供 CI / 脚本；OSC 8 可点超链接。
- v0.155.0 起实验性语音对话；Mac 上本地 MCP 请求支持 Touch ID 校验。

**C3. 斜杠命令面**【第三方实测】

`/resume`、`/fork`（从当前 transcript 分叉新线程）、`/side`（侧信道）、`/model`、`/fast on`、`/compact`、`/status`、`/clear`、`/permissions`、`/plugins`、`/undo`（回退最近文件改动）。

---

## 4. Google Gemini CLI（参考样本，已并入 Antigravity）

### A. 身份提示词

- **`GEMINI_SYSTEM_MD` 环境变量 = 完全外部替换系统提示词**（不是 merge，是 override）；`GEMINI_WRITE_SYSTEM_MD=1 gemini ...` 可把内置提示词 dump 到项目默认路径供改写。【官方已查证，raw.githubusercontent.com/google-gemini/gemini-cli/docs/cli/system-prompt.md】
- Subagent 用 `~/.gemini/agents/*.md`，YAML frontmatter + 正文即系统提示词。
- AGENTS.md 作为共享项目指令约定。

### B/C

- agent mode 内置 `/tools`、`/mcp`、`/deploy` 等命令；MCP server 可配。
- 个人版已于 2026-06-18 停服，流量迁 Antigravity，不再作为活跃竞品。

---

## 5. 横向速查表

| 维度 | Claude Code 2.1.283 | Kimi Code 2.0.0 | Codex CLI 0.157.1 |
|---|---|---|---|
| 系统提示词缓存分段 | ✅ 显式 cached/uncached 两段 | ⚠️ 有 cache 失效提醒，但未见公开分段文档 | ⚠️ 模型自带 base_instructions |
| 项目指令分层 | Managed/User/Project/Local 四级 + 自动回退 AGENTS.md | KIMI_CODE_HOME + SYSTEM.md + 插件注入 | ~/.codex + root + 子目录 AGENTS.md，32KiB 上限可调 |
| 自动记忆 | ✅ MEMORY.md + 200 行上限 + user/project/local 三档 agent-memory | ⚠️ 未强调 auto memory，靠 /compact 挂 todo | ❌ 未见自动记忆笔记体系 |
| 压缩协议 | 自动 compact + focus + micro-compact（单工具结果级） | /compact 挂 todo + micro compaction 默认开 | /compact 有损摘要 + 会话归档/搜索 |
| Skill 懒加载 | ✅ 只加载 name+description，正文按需 | ✅ 内置 skill 直出斜杠命令，多 skill 同 prompt | ✅ `$skill-name`，frontmatter 带 default_prompt/policy |
| Skill 治理 | 9 类归类 + hooks + plugin 依赖 | sub-skill.review / consolidate 自审计 | 开放标准跨 30+ 工具可移植 |
| 插件打包 | skills + hooks + plugins | skills + MCP + 斜杠命令 + agents 一体化 | MCP 2026-07-28 对齐 |
| 全屏 TUI | ✅ 2026-05 起默认 | 实验性全屏模式 | ✅ v0.157 默认全屏 transcript |
| 时间旅行 | /rewind 恢复 /clear 之前 | /goal 队列 + background agent | /fork + /undo |
| 安全模型 | Bash allow 规则启动警告 | workspace trust 展示 MCP 目标、默认拒绝 | sandbox × approval 双正交控制 |
| 后台化 | background sessions 置顶 | goal 后台跑 + swarm 并行 | daemon 自动随 TUI 起 |
| 非交互 | `claude -p` | `kimi -p` | `codex exec` |

---

## 6. 对 qxt 最有参考价值的五条事实

1. **Claude Code 的"系统提示词两段式 + compact 后从磁盘重注入清单"**是目前最工程化的上下文管理文档；qxt 的 prompts.py 已经有分层项目指令，但缺一份"compact 后什么必须从磁盘重读"的显式契约。【官方已查证】
2. **Kimi Code 的插件 = Skills + MCP + 斜杠命令 + Agents 打包单元**，且插件可注入 systemPrompt；这比 qxt 当前"技能注册表"更接近一个可分发的能力包格式。【官方已查证】
3. **Codex 把 sandbox 与 approval 拆成两个正交控制**（`--sandbox` vs `--approve-for-me`），废弃 `--full-auto`；qxt 的权限模型可参考这个二维矩阵。【官方已查证】
4. **SKILL.md 正在变成跨厂商开放标准**（Claude Code / Codex / 30+ 工具共用 `.agents/skills/` 布局）；qxt 的 Markdown+frontmatter 方向正确，但应评估是否对齐 `.agents/skills/` 与 `$skill-name` 调用约定以获得可移植性。【第三方实测】
5. **三家都在做"全屏 transcript + 后台 daemon + 会话 fork/rewind"**；qxt 已有 textual TUI + /rewind /worktree /subagent，方向对齐，但全屏 alternate-screen、Ctrl-K 会话搜索、diff 行内预览这些细节仍有差距。【官方已查证】
