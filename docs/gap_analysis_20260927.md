# 差距分析报告：青小团 qxt vs Claude Code / Kimi Code / Codex CLI

> 调研日期：2026-09-27
> 评分基准：5 分制，相对位置（非绝对质量）。信源标签见 `competitive_analysis_20260927.md`。
> 差距等级图例：
> - 🏆 **领先**：qxt 已做、且竞品未做或做得更弱
> - ✅ **持平**：大家都有，差异不构成竞争劣势
> - ⚠️ **明显差距**：竞品有成熟做法，qxt 缺失或粗糙
> - ❌ **显著差距**：竞品已产品化、qxt 完全没有，影响选型

---

## 1. 总览评分矩阵

| 维度 / 子项 | qxt | Claude Code 2.1.283 | Kimi Code 2.0.0 | Codex CLI 0.157.1 | qxt 相对位置 |
|---|---|---|---|---|---|
| **A. 身份提示词** | **3.8** | **5.0** | **4.5** | **4.0** | 落后一线 |
| A1 系统提示词缓存分段 | 2 | 5 | 3 | 3 | ❌ |
| A2 项目指令分层与回退 | 4.5 | 5 | 3.5 | 4.5 | ✅ 持平偏前 |
| A3 自动记忆笔记体系 | 2 | 5 | 3 | 2 | ❌ |
| A4 压缩/上下文交接契约 | 3 | 5 | 4 | 3.5 | ⚠️ |
| A5 输出风格 / persona | 4.5 | 4 | 4 | 3.5 | 🏆 |
| A6 Windows 原生外骨骼 | 5 | 2 | 2.5 | 2 | 🏆 |
| **B. Skills 系统** | **4.0** | **5.0** | **4.5** | **4.5** | 落后但有差异点 |
| B1 SKILL.md 格式 | 4 | 5 | 4.5 | 5 | ⚠️ |
| B2 懒加载（name/desc 先入） | 4 | 5 | 4.5 | 4.5 | ✅ |
| B3 技能激活策略 | 4.5 | 4 | 4 | 3.5 | 🏆（四档激活） |
| B4 自动蒸馏/学习闭环 | 4.5 | 2 | 3 | 2 | 🏆（SkillDistiller） |
| B5 跨厂商可移植性 | 4.5 | 4.5 | 3.5 | 5 | 🏆（三方桥） |
| B6 技能治理（review/consolidate） | 2.5 | 3.5 | 4.5 | 3.5 | ⚠️ |
| B7 插件打包（skill+MCP+cmd+agent） | 2 | 4.5 | 5 | 4 | ❌ |
| **D. 生态互操作**（v0.2.018 新增维度） | **5.0** | **3.5** | **2.0** | **3.0** | 🏆 **第一且唯一** |
| D1 技能双向搬运（Claude/Hermes ⇄ qxt） | 5 | 2 | 1 | 2.5 | 🏆 |
| D2 记忆/人格互通（MEMORY.md/SOUL.md） | 5 | 2 | 1 | 1.5 | 🏆 |
| D3 MCP 配置互导（.mcp.json / config.yaml） | 4.5 | 2 | 1 | 2 | 🏆 |
| D4 以 MCP server 被对方调用（serve/link） | 5 | 1 | 1 | 2 | 🏆 |
| D5 会话内委派对方（claude_code_run/hermes_run） | 4.5 | 2 | 1 | 2.5 | 🏆 |
| **C. 用户体验** | **3.7** | **5.0** | **4.5** | **4.5** | 落后一线 |
| C1 全屏 transcript 渲染 | 3 | 5 | 4 | 5 | ⚠️ |
| C2 会话搜索 / 切换 / fork | 3 | 4.5 | 4.5 | 4.5 | ⚠️ |
| C3 时间旅行（rewind/handoff） | 4.5 | 5 | 3.5 | 4 | ✅ 偏前 |
| C4 权限模型 | 3 | 4 | 4 | 5 | ⚠️ |
| C5 后台化 / 多 agent | 4 | 4.5 | 5 | 4.5 | ⚠️ |
| C6 诊断 / onboarding | 2.5 | 4.5 | 4.5 | 4 | ❌ |
| C7 非交互 headless | 4.5 | 5 | 4.5 | 5 | ✅ |

**加权结论**：qxt 在"生态互操作枢纽（Claude Code / Hermes 资产三方双向复用，v0.2.018 落地）"上是**第一且唯一**的差异点；在"身份分层 + Windows 原生 + 技能激活策略 + 自动蒸馏"四个点上也有真实差异；在"系统提示词工程化（缓存分段/自动记忆/压缩契约）"、"Skills 可移植性（现已部分反超）"与"全屏 TUI 细节 + 诊断工具"上仍落后于 Claude Code。

---

## 2. 逐项差距详析

### A. 身份提示词 / 系统提示词

#### A1. 系统提示词缓存分段 — ❌ 显著差距
- **竞品做法**：Claude Code 把系统提示词切成"静态缓存前缀（身份+工具 schema+行为准则）"与"动态非缓存后缀（memory/env/output style/MCP/scratchpad）"，并提供 `ENABLE_PROMPT_CACHING_1H`。【官方已查证】
- **qxt 现状**：`prompts.py` 有稳定 system 前缀与任务上下文分离，但未公开声明哪一段是 cache 友好的稳定前缀、哪一段是每轮必变的动态段。
- **可补齐性**：高。纯架构整理，不改行为。
- **建议**：在 prompts.py 里显式分两段，前缀只放身份/工具描述/行为准则；后缀放 cwd/OS/skill registry 快照。在文档里声明 cache 边界。

#### A2. 项目指令分层 — ✅ 持平偏前
- **竞品做法**：Claude Code 四级（Managed/User/Project/Local），仅当无 CLAUDE.md 才回退 AGENTS.md；Codex 三级 AGENTS.md + 32KiB 上限。
- **qxt 现状**：QXT.md / AGENTS.md / CLAUDE.md 三读，等于天然兼容两种生态。
- **建议**：把"三读"写成官方卖点；补一个文件大小上限与溢出提示（对标 Codex `project_doc_max_bytes`）。

#### A3. 自动记忆笔记体系 — ❌ 显著差距
- **竞品做法**：Claude Code 有 `~/.claude/projects/<slug>/memory/MEMORY.md` + 200 行注入上限 + user/project/local 三档 agent-memory 目录，Agent 被指示"直接 Write，不要 mkdir"。【官方已查证】
- **qxt 现状**：有 memory/ 目录（agent workspace），但未见"Agent 自动把用户偏好/修正写成笔记并在下次会话注入"的闭环。
- **可补齐性**：中。需要写一个记忆写入工具 + 注入上限 + 去重策略。
- **建议**：P0 实现。

#### A4. 压缩/上下文交接契约 — ⚠️ 明显差距
- **竞品做法**：Claude Code 有一张明确的表——compact 后系统提示词/output style/CLAUDE.md/auto memory/git 快照/plan 全部"从磁盘重注入"；Kimi Code `/compact` 把 todo list 附在摘要后。【官方已查证】
- **qxt 现状**：有 `/handoff`，但未见"compact 后哪些状态必须重建"的显式契约文档。
- **可补齐性**：高。
- **建议**：写一张与 Claude Code 对齐的"compact 存活表"，落到 prompts.py 的注释与开发者文档里。

#### A5. 输出风格 / persona — 🏆 领先
- **qxt 现状**：concise / explanatory / learning 三档，learning 档带教学意味。
- **竞品**：Claude Code 有 Output Style 配置但是单一用户级设置；Kimi/Codex 无教学模式。
- **建议**：把 learning 模式做成可演示的差异化 feature（如在 `qxt run --style learning` 下逐步解释自己为什么这么做）。

#### A6. Windows 原生外骨骼 — 🏆 领先
- **竞品**：Codex 在 Windows 上需要三个 exe（`codex.exe` + sandbox-setup + command-runner）才能做受限 token；Kimi Code 在 Windows 缺 Git Bash 时 fail early；Claude Code 虽是原生二进制但 POSIX 习惯深。
- **qxt 现状**：PowerShell 5.1 一等公民、无 bash 依赖、Windows 命令外骨骼。
- **建议**：这是 qxt 在中文 Windows 开发者场景下最硬的护城河，应在 README/官网首屏强调。

---

### B. Skills 系统

#### B1. SKILL.md 格式 — ✅ 持平（v0.2.017 已补齐）
- **竞品做法**：Codex 与 Claude Code 已事实统一为 YAML frontmatter（name/description）+ Markdown 正文，Codex 额外有 `display_name`/`short_description`/`default_prompt`/`policy.allow_implicit_invocation`。
- **qxt 现状**：frontmatter 超集已对齐——识别并存储 `display_name`/`short_description`/`default_prompt`/`policy.allow_implicit_invocation`，同时保留 qxt 自有字段（激活档/热度/标签/版本），写入输出全部字段、旧文件向后兼容。
- **可补齐性**：已补齐。

#### B2. 懒加载 — ✅ 持平
- qxt 已有 lazy 激活档；与 Claude Code "name+description 先入、正文按需"一致。

#### B3. 技能激活策略 — 🏆 领先
- **qxt 现状**：lazy / auto / always / proactive 四档。
- **竞品**：Claude Code 只有"自动触发或 `/name`"两态；Codex 多了 `allow_implicit_invocation` 布尔。
- **建议**：把四档激活写成 frontmatter schema 并文档化，这是 qxt 技能系统最可讲的差异点。

#### B4. 自动蒸馏闭环 — 🏆 领先
- **竞品**：Claude Code 只写 memory 笔记，不产出可复用技能包；Kimi Code 有 sub-skill.review / consolidate 但仍是人工触发；Codex 无自动蒸馏。
- **qxt 现状**：SkillDistiller 自动蒸馏 + 同名保存=refine + 热度追踪。
- **可验证的超越点**：一次成功的重复工作流结束后，qxt 能主动提议"要不要把它存成技能？"并写出带 frontmatter 的 SKILL.md；再次遇到相似任务时按热度自动激活。
- **建议**：P0 把这条链路做端到端可演示（蒸馏提议 → 人工确认 → 下次自动命中），作为官网 demo 视频主线。

#### B5. 跨厂商可移植性 — 🏆 三方桥（v0.2.017 基础 + v0.2.018 反超）
- **竞品做法**：Codex 明确支持 `.agents/skills/SKILL.md` 四档路径（REPO/USER/ADMIN/SYSTEM），Claude Code 技能可"最小改动搬到 Codex"。【第三方实测】
- **qxt 现状**：搜索目录已含 `.qxt/skills`、`.agents/skills`、`.claude/skills`、`~/.claude/skills`、`~/.hermes/skills`（含 profiles），按优先级合并；v0.2.018 新增 `qxt ecosystem import/export skills` 双向搬运与可移植目录包导出——不再只是"单向读取竞品目录"，而是三方互写。
- **建议**：已超越"最小改动搬运"（qxt 是零改动直接可用 + 双向同步）。

#### B6. 技能治理 — ⚠️ 明显差距
- **竞品**：Kimi Code 有 `sub-skill.review`（审计）与 `sub-skill.consolidate`（合并层级）。
- **qxt 现状**：有热度追踪但无审计/合并命令。
- **建议**：P2，补 `/skills audit` 与 `/skills consolidate` 两个斜杠命令。

#### B7. 插件打包 — ❌ 显著差距
- **竞品做法**：Kimi Code 插件 = Skills + MCP server + 斜杠命令 + Agents + systemPrompt 注入，有 marketplace；Claude Code 有 plugin 依赖强制。
- **qxt 现状**：技能注册表存在，但没有"一个目录 = 一个可分发插件"的打包格式与安装命令。
- **可补齐性**：中。
- **建议**：P1，定义 `qxt-plugin.json` 清单，先支持"技能 + 斜杠命令"打包，MCP 与 systemPrompt 注入后置。

---

### C. 用户体验

#### C1. 全屏 transcript 渲染 — ⚠️ 明显差距
- **竞品**：Claude Code 2026-05 起全屏默认；Kimi Code 实验性 alternate-screen（可滚动/鼠标选/可点链接/Ctrl-Shift-F 搜索）；Codex v0.157 全屏 transcript 默认。
- **qxt 现状**：textual TUI + Web workbench，未见 alternate-screen 全屏模式与 TUI 内搜索。
- **建议**：P1。

#### C2. 会话搜索 / 切换 — ⚠️ 明显差距
- **竞品**：Kimi Code `Ctrl/Cmd+K` 按标题/workspace/最近 prompt 过滤；Codex v0.134 起会话历史搜索。
- **qxt 现状**：有 `/handoff` 与 session 概念，但未见快速搜索面板。
- **建议**：P1，在 textual TUI 里加一个 Ctrl-K palette。

#### C3. 时间旅行 — ✅ 持平偏前
- **qxt 现状**：`/rewind` + `/worktree` + `/handoff` 三件套。
- **竞品**：Claude Code `/rewind` 可恢复 `/clear` 之前；Codex `/fork` + `/undo`。
- **建议**：把 `/handoff` 包装成一个"可导出/可贴给同事"的交接文件，这是竞品没有的形态。

#### C4. 权限模型 — ⚠️ 明显差距
- **竞品做法**：Codex 把 sandbox（技术能力边界）与 approval（何时问人）拆成两个正交控制，废弃 `--full-auto`；Kimi Code workspace trust 提示展示 MCP 启动目标、默认拒绝。
- **qxt 现状**：有 `!` shell 与权限概念，但未见二维矩阵。
- **建议**：P1，把权限配置从一维布尔改成"能力 × 触发条件"二维。

#### C5. 后台化 / 多 agent — ⚠️ 明显差距
- **竞品**：Kimi Code goal 队列 + `/swarm` 并行 + background agent；Codex daemon 自动随 TUI 起；Claude Code background sessions 置顶。
- **qxt 现状**：有 `/goal` `/subagent`，但后台任务的可观察性（进度查询/停止/置顶）需要补。
- **建议**：P1。

#### C6. 诊断 / onboarding — ❌ 显著差距
- **竞品**：Claude Code v2.1.283 加 `/doctor prompt-audit`（审计 CLAUDE.md/skills/agents/commands）；Kimi Code `kimi doctor` + `/experiments` 可视化开关面板。
- **qxt 现状**：未见对等命令。
- **可补齐性**：高。
- **建议**：P0，先做 `qxt doctor`（配置语法 + 技能 frontmatter 合法性 + 项目指令文件可读性），这是低成本高感知。

#### C7. 非交互 headless — ✅ 持平
- qxt `qxt run / -p / --print` 与 `claude -p` / `kimi -p` / `codex exec` 对等。

---

## 3. 「超越点」清单（qxt 可以做得比所有竞品都好）

> 每条都附"可验证方式"，避免营销话术。

### 超越点 7：生态互操作枢纽（Claude Code / Hermes Agent 三方桥）⭐ 新王者
- **事实**：Claude Code / Kimi Code / Codex 各自只认自家资产目录，彼此默认不互通；Hermes Agent 的记忆/技能/SOUL 与 Claude Code 的 `.claude/skills`/`.claude/agents` 更是互不认识。qxt `v0.2.018` 把它们全部打通——**双向搬运 + 双向被调用**：
  - **拿来**（`qxt ecosystem import`）：把 `~/.claude/skills`、`~/.hermes/skills`（含 profiles）导入 qxt；Hermes 的 `MEMORY.md`/`USER.md`/`SOUL.md` 并入 qxt 记忆与人格；`.claude/agents` 子代理原样可用；对方配好的 MCP server（`.mcp.json`/`config.yaml`）并入 qxt 配置（密钥脱敏）。
  - **给出去**（`qxt ecosystem export`）：qxt 技能导出为对方可直接加载的可移植 SKILL.md 目录包；agents 同步到 `.claude/agents`；记忆导出回 Hermes（按字符预算）。
  - **被调用**（`qxt ecosystem link` + `serve`）：qxt 以 MCP stdio server 挂进 Claude Code / Hermes，对方会话里直接多出 `qxt_*` 工具（记忆检索/写入、技能清单/读取、headless 任务派发）。
  - **调用对方**（会话内 `claude_code_run`/`hermes_run` 委派工具）：把任务交给对方完整环境执行。
- **可验证**（本机 2026-09-27 实测）：`qxt ecosystem scan` 正确探测 Claude Code 2.1.239 + `~/.claude` 内技能 `tabbit`；MCP server 子进程真实握手（initialize → tools/list 8 工具 → qxt_status JSON → skill_list 列出 tabbit → 未知工具 -32602）；`tests/test_ecosystem.py` 21 项 + CLI e2e 全绿。Hermes CLI 未安装时优雅降级（HERMES_HOME 存在即探测）。
- **价值排序**：**#1**（超越"Windows 原生"，成为最能一句话讲清的选型理由："装一个，三个生态的积累共用"）。

### 超越点 1：Windows 原生、零 bash 依赖的 Agent CLI
- **事实**：Codex 在 Windows 需三 exe 沙箱；Kimi Code 缺 Git Bash 直接 fail；Claude Code 原生二进制但设计以 POSIX 为中心。qxt 把 PowerShell 5.1 作为一等公民。
- **可验证**：在一台干净 Windows 机器（无 Git Bash、无 WSL）上 `npm/pip install qxt` 后直接跑通"读代码→改文件→跑 pytest→提交"全流程；竞品在同一台机器上失败。
- **价值排序**：**#1**（中文 Windows 开发者场景的硬护城河）。

### 超越点 2：SkillDistiller 端到端自动蒸馏
- **事实**：Claude Code 只写 memory 笔记不产技能包；Kimi Code 的 sub-skill.review/consolidate 是人工触发的治理工具；Codex 无自动蒸馏。qxt 已有 SkillDistiller + 同名 refine + 热度追踪。
- **可验证**：用户在 qxt 里完成一次"给 FastAPI 路由加鉴权"的重复工作后，qxt 主动弹出"要不要存成技能？"，确认后下次同类任务自动按热度激活。
- **价值排序**：**#2**（这是 qxt 技能系统最该拍成 demo 的故事线）。

### 超越点 3：三读项目指令（QXT.md + AGENTS.md + CLAUDE.md）
- **事实**：Claude Code 仅在无 CLAUDE.md 时回退 AGENTS.md；Codex 只认 AGENTS.md。qxt 同时读三种文件，等于一个仓库无论按哪种生态写的约定都能被识别。
- **可验证**：在一个只写了 `AGENTS.md` 的开源仓库里 `cd` 进去跑 qxt，它能正确读出构建/测试命令；再把同样的仓库给 Claude Code，它读不到。
- **价值排序**：**#3**（低开发成本、高迁移友好度）。

### 超越点 4：四档技能激活（lazy/auto/always/proactive）
- **事实**：竞品只有"自动触发 / 手动斜杠命令"两态，最多加一个 `allow_implicit_invocation` 布尔。qxt 四档 frontmatter schema 更细。
- **可验证**：在 frontmatter 写 `activation: proactive` 的技能，会在会话开始时就预热；写 `lazy` 的只在命中时才读正文。
- **价值排序**：**#4**。

### 超越点 5：learning 输出风格
- **事实**：竞品的 Output Style 是"详略"开关；qxt 的 learning 档是"边做边教用户为什么"。
- **可验证**：`qxt --style learning run "修这个 bug"` 时，每步工具调用都附带一段对用户的解释，可切换回 concise。
- **价值排序**：**#5**（教育/培训场景差异化）。

### 超越点 6：`/handoff` 导出的可交接上下文包
- **事实**：竞品有 `/resume` `/fork`，但那是同一台机器上的会话分叉；qxt `/handoff` 可产出一份"给下一个人/下一台机器"的交接文件。
- **可验证**：A 用户在 qxt 里 `/handoff` 导出一个 Markdown；B 用户在自己机器上 `qxt resume handoff.md` 能接着干。
- **价值排序**：**#6**（团队协作/远程 pair 场景）。

---

## 4. 实施优先级表

| 优先级 | 对标谁 | 做什么 | 验收标准 | 预估工作量 |
|---|---|---|---|---|
| **P0** | Claude Code | 把 prompts.py 显式切成"cache 稳定前缀 / 动态后缀"两段 | 代码注释 + 文档声明 cache 边界；跑一次 `qxt run` 抓请求日志，确认前缀在两轮间字节级一致 | 2 人日 |
| **P0** | Claude Code | 实现自动记忆笔记：`~/.qxt/projects/<slug>/memory/MEMORY.md` + 200 行注入上限 + 写工具 | 用户纠正 qxt 一次"别这么命名"后，下次新会话自动在系统提示词末尾看到这条偏好；超过 200 行时提示整理 | 5 人日 |
| **P0** | Claude Code | 写"compact 后存活表"并落到 prompts.py：哪些状态从磁盘重注入 | 文档化表格；`/compact` 后 git 状态/项目指令/记忆笔记/plan 全部重建，人工 diff 验证 | 2 人日 |
| **P0** | Kimi Code / Claude Code | `qxt doctor`：配置语法 + 技能 frontmatter 合法性 + 项目指令文件可读性 + cache 分段自检 | 一条命令输出结构化报告；故意写坏一个技能 frontmatter，doctor 能指出具体行 | 3 人日 |
| **P0** | 自我超越 | 把 SkillDistiller 端到端链路做成可演示：蒸馏提议 → 人工确认 → 下次自动命中 | 录一条 90 秒 demo；重复两次相似任务后第二次自动激活 | 5 人日 |
| **P1** | Codex / Claude Code | 技能加载器兼容 `.agents/skills/` 与 `~/.agents/skills/`；frontmatter 超集识别 `default_prompt`/`policy` | 把一个公开的 Claude Code SKILL.md 目录拷进 qxt 项目，不修改即可被 `/skill-name` 调用 | 3 人日 |
| **P1** | Codex | 权限模型二维化：`capability × ask_when`（对标 `--sandbox` × `--approve-for-me`） | config schema 重写；旧配置自动迁移；UI 上能分别设置"能否联网"和"何时问" | 5 人日 |
| **P1** | Kimi Code | TUI 全屏 alternate-screen 模式 + Ctrl-K 会话搜索 palette + TUI 内 Ctrl-F 搜索 | 全屏模式下可滚动 transcript、鼠标选文本、链接可点；Ctrl-K 按标题过滤会话 | 8 人日 |
| **P1** | Kimi Code | 插件打包格式 `qxt-plugin.json`（先支持 技能 + 斜杠命令；MCP/systemPrompt 后置） | 一个目录可 `qxt plugin install ./my-plugin`；卸载干净 | 6 人日 |
| **P1** | Claude Code | 后台任务可观察性：goal/subagent 进度查询、停止、置顶 | 长任务跑到一半时能在 TUI 里看到进度条并 `/stop` | 5 人日 |
| **P2** | Kimi Code | `/skills audit` 与 `/skills consolidate` 技能治理命令 | 审计报告列出未被命中过的技能；合并命令把相似技能归组 | 4 人日 |
| **P2** | Kimi Code | TUI 内 diff 行内预览（连续工具调用折叠分组 + diff 行数） | 一次改 10 个文件的工具调用在 TUI 里折叠成一行，展开看 diff | 5 人日 |
| **P2** | Kimi Code | TUI 渲染 Markdown / 简单 LaTeX | 回复里的 ```` ```python ```` 代码块与 `$...$` 公式正确渲染 | 3 人日 |
| **P2** | Codex | headless 模式对齐 `codex exec`：支持 `--json` 流式事件输出供外部脚本消费 | `qxt exec --json run "..."` 输出 NDJSON，可被 jq 解析 | 3 人日 |

**P0 合计**：17 人日；**P1 合计**：27 人日；**P2 合计**：15 人日。

---

## 5. 一句话结论

qxt 不需要在"系统提示词工程化"和"全屏 TUI"上硬追 Claude Code 第一。真正的护城河组合是：**生态互操作枢纽（唯一） + Windows 原生（唯一） + SkillDistiller 自动蒸馏（唯一） + 三读项目指令**——其中生态互操作已落地为 `qxt ecosystem` 一条命令级能力，是选型时最能一句话讲清、竞品全部做不到的差异点；同时用 P0 的低成本项（cache 分段、自动记忆、compact 契约、`qxt doctor`）把"看起来专业"的基础补齐。
