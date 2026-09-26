# 青小团(qxt) vs Kimi Code vs Claude Code 差距分析报告

> 调研截止：2026-09-26 | 青小团版本：v0.2.017 | Kimi Code：v2.1.1 | Claude Code：v2.1.283
> 可信度标注：【官方已查证】= 官方文档/changelog/GitHub；【第三方实测】= 独立评测/社区；【一方宣称】= 官方宣传未独立复现

---

## 一、总览评分矩阵

| 维度 | 青小团 qxt | Kimi Code v2.1.1 | Claude Code v2.1.283 | 差距判定 |
|---|---|---|---|---|
| 安装/分发/更新 | pip + ps1 + bat，无自动更新 | 官方脚本/npm/Homebrew/单二进制，`kimi upgrade` | npm(弃用)/原生二进制，`claude install` | ⚠️ qxt缺自动更新 |
| 模型/Provider | 51 provider，模型中立 ✅ | 自家K3+第三方6类，双协议API | 仅Claude系列+Bedrock/Vertex/Foundry | ✅ qxt领先 |
| Agent模式/自主性 | plan/auto/agent/dev/run/bg，SubAgentPool，DevLoop | Plan/Goal/三档权限/AgentSwarm/Tower/WaitFor | Plan/Auto(默认)/Bypass/goal/fork/Ultraplan/Workflows | ⚠️ 缺Goal模式、WaitFor、dynamic workflows |
| 代码编辑精度 | str_replace单次编辑，code_edit助手，run_tests | Edit/Write须先Read，危险命令守卫，symlink防护 | Edit(multi-cut)/Write/NotebookEdit，沙箱Bash，Monitor，ultrareview | ⚠️ Edit工具偏弱，缺diff预览 |
| 终端UI/TUI | textual TUI + Web workbench | 全交互TUI，Mermaid/LaTeX渲染，全屏模式 | 流式TUI，diff面板，vim模式，agent view，Rewind | ⚠️ 缺diff面板、agent view、Rewind |
| IDE集成 | ACP服务端，无IDE扩展 | VS Code扩展+桌面端+ACP接JetBrains/Zed | VS Code+JetBrains+Desktop+Web | ❌ qxt无IDE扩展 |
| 上下文/记忆 | QXT.md多层级，MemoryStore(FTS5)，代码索引，上下文压缩 | compact，会话恢复/派生/全局搜索，1M上下文 | CLAUDE.md，Auto Memory(4类)，三层压缩，1M上下文 | ⚠️ 缺Auto Memory自动写入 |
| MCP/工具生态 | MCP完整，微内核插件，Skills，Hooks(8事件) | MCP，插件市场，Skills，Hooks | MCP，Plugins+Marketplaces，Skills，Hooks，plugin eval | ✅ 基本持平 |
| 安全/权限 | auto mode风险分类，沙箱，安全审计，工作区信任 | 三档权限，危险命令守卫，工作区信任，Web鉴权 | 三层权限+Tool(param:value)，沙箱Bash，hard deny，--restricted | ⚠️ 缺Tool(param:value)精确匹配、--restricted |
| 插件/自定义 | 微内核@plugin，服务注册表，事件总线 | 插件清单(MCP+skills+agents+systemPrompt) | Plugins+Marketplaces，Hooks，settings.json分层 | ✅ qxt架构领先 |
| 自动化/CI | qxt run(headless)，cron，Web API，后台任务 | -p print，stream-json，Server API，Remote Control | -p/--print，--bare，/loop，Routines，ultrareview CI | ⚠️ 缺-p简洁模式、--bare、stream-json |
| 性能/上下文 | 取决于provider | 1M上下文(K3)，260 tok/s(宣称) | 1M上下文(Opus5/Sonnet5)，fast mode | ✅ 模型中立无差距 |
| 多语言 | 10语言README + i18n ✅ | 中英界面，多语言文档站 | 英/日/中/韩/德/法/西/葡/俄/印尼 | ✅ qxt领先 |
| 价格 | 开源免费 ✅ | CLI免费MIT，会员¥49-699/月 | Pro$20/Max$100-200 | ✅ qxt领先 |
| 开源 | MIT ✅ | MIT ✅ | 闭源(Commercial Terms) | ✅ qxt领先 |

---

## 二、逐项差距详析

### 差距1：Headless/CI 模式不够简洁（高优先级）

**对标能力**：
- Claude Code：`claude -p "任务"` 非交互一次性运行，stdin/stdout 管道友好，`--bare` 跳过所有自定义化确保CI可复现，`--permission-prompts none` 无人值守
- Kimi Code：`kimi -p "任务"`，`--output-format stream-json` 每行一个JSON对象便于程序解析

**青小团现状**：
- `qxt run "任务"` 存在，但输出混合 console.print 与 token stream，不是纯管道模式
- 无 `--output-format json` 结构化输出
- 无 `--bare` 纯净模式（会加载用户配置/skills/hooks/MCP，CI环境不可复现）
- 无 stdin 管道输入（`cat file | qxt -p "explain"`）

**差距等级**：⚠️ 明显差距，CI/自动化场景核心能力缺失

**可补齐性**：高。在现有 `cmd_run` 基础上增加 `-p/--print` 标志、`--output-format` 参数、`--bare` 标志即可。

---

### 差距2：代码编辑工具精度不足（高优先级）

**对标能力**：
- Claude Code：`Edit` 工具支持 **multi-cut**（一次调用多组 old_string/new_string），编辑前可 `/diff` 实时预览，`NotebookEdit` 支持Jupyter
- Kimi Code：v0.38.0 起 Edit/Write **必须先 Read** 才能改（防止盲改），symlink 逃逸阻断

**青小团现状**：
- `edit_file` 仅支持**单次** str_replace（old_string 必须唯一）
- 无编辑前 diff 预览确认机制
- 无 "Edit 必须先 Read" 防护
- 无 NotebookEdit

**差距等级**：⚠️ 明显差距，直接影响代码编辑可靠性

**可补齐性**：高。增强 `edit_file` 支持多组替换，增加 diff 预览工具，在工具执行管线中加 Read-before-Edit 守卫。

---

### 差距3：Auto Memory 自动记忆缺失（高优先级）

**对标能力**：
- Claude Code：Auto Memory 自动把用户纠正/偏好/项目决策写成记忆笔记，分 **user/feedback/project/reference** 四类，`/memory` 查看与开关，会话启动自动注入
- Kimi Code：无独立长期记忆模块（靠1M上下文+skills）

**青小团现状**：
- `MemoryStore` 已有 FTS5 全文检索、标签、时间索引、上下文感知召回
- 但记忆是**被动**的：Agent 需显式调用 `memory_write` 工具才写入
- 无自动从对话中提取用户偏好/纠正/决策的机制
- 无四类记忆分类

**差距等级**：⚠️ 明显差距，Claude Code 核心差异化体验

**可补齐性**：高。在 agent loop 的 PostToolUse / Stop hook 中增加自动记忆提取器，复用现有 MemoryStore，分四类存储。

---

### 差距4：缺少 `--bare` CI 纯净模式（中优先级）

**对标能力**：
- Claude Code：`--bare` 跳过 hooks/skills/commands/subagents/plugins/MCP/auto memory/CLAUDE.md 自动加载，确保 CI 可复现

**青小团现状**：
- 无此模式，`qxt run` 会加载全部用户配置和插件

**差距等级**：⚠️ 中等差距，CI/评测场景需要

**可补齐性**：高。在 build_kernel 时增加 bare 标志，跳过插件/skills/hooks/MCP 加载。

---

### 差距5：缺少会话导出/打包（中优先级）

**对标能力**：
- Kimi Code：`kimi export [sessionId] -o out.zip` 打包会话用于分享/归档/bug report
- Kimi Code：`kimi vis` 浏览器实时检视会话展开过程

**青小团现状**：
- 会话存储在 `~/.qingxiaotuan/sessions/`，但无导出命令
- 无会话可视化

**差距等级**：⚠️ 中等差距，实用性功能

**可补齐性**：高。增加 `qxt session export` 命令，zip 打包会话文件。

---

### 差距6：缺少 `!` Shell 快捷模式（中优先级）

**对标能力**：
- Claude Code：`! npm test` 在会话里直接跑 shell，输出自动被解释，无需二次 prompt（Week 26）

**青小团现状**：
- 无此模式，需通过 Agent 调用 run_shell 工具

**差距等级**：⚠️ 中等差距，交互效率

**可补齐性**：高。在 REPL 输入解析中增加 `!` 前缀检测，直接执行 shell 并将结果注入上下文。

---

### 差距7：缺少 TodoWrite 内置工具（中优先级）

**对标能力**：
- Claude Code：`TodoWrite` 是内置工具，Agent 可创建/更新任务列表，用户可见

**青小团现状**：
- 有 checkpoint 工具，但无标准 TodoWrite
- DevLoop 内部有任务管理但不暴露为通用工具

**差距等级**：⚠️ 中等差距，任务透明度

**可补齐性**：高。增加 TodoWrite 工具插件，持久化到会话状态。

---

### 差距8：缺少 `/init` 项目引导（低优先级）

**对标能力**：
- Claude Code：`/init` 为新项目生成起始 CLAUDE.md

**青小团现状**：
- 无 `/init` 命令，QXT.md 需手动创建

**差距等级**：⚠️ 低差距，新手体验

**可补齐性**：高。增加 `/init` 斜杠命令，扫描项目生成 QXT.md。

---

### 差距9：IDE 扩展缺失（低优先级，工程量大）

**对标能力**：
- Kimi Code：VS Code 扩展 + 桌面端
- Claude Code：VS Code + JetBrains 插件 + Desktop

**青小团现状**：
- 有 ACP 服务端（`qingxiaotuan/acp/`），理论上可接 JetBrains/Zed
- 无 VS Code 扩展，无桌面端

**差距等级**：❌ 显著差距，但工程量极大（需独立 TS/JS 项目）
**决策**：报告中记录，本轮不实现（超出 CLI 项目范围）。ACP 协议已有，可作为未来接入点。

---

### 差距10：云端功能缺失（不可实现）

**对标能力**：
- Claude Code：Ultraplan 云规划、Routines 云端定时、ultrareview 云多代理评审、自托管云会话、remote-control 手机接管
- Kimi Code：Remote Control GA

**差距等级**：❌ 架构性差距，需要云基础设施
**决策**：青小团定位本地 CLI，不实现云端功能。cron + Web API 已覆盖本地自动化需求。

---

### 差距11：缺少 Tool(param:value) 精确权限匹配（低优先级）

**对标能力**：
- Claude Code：权限规则支持 `Tool(param:value)` 精确匹配，如 `Agent(model:opus)`、`Bash(rm -rf*)`

**青小团现状**：
- 权限规则按工具名匹配，支持 shell 命令模式匹配，但无通用的 `Tool(param:value)` 语法

**差距等级**：⚠️ 低差距，安全精细度
**可补齐性**：中。需扩展权限规则解析器。

---

### 差距12：缺少 agent view / Rewind（低优先级）

**对标能力**：
- Claude Code：`claude agents` 一屏看所有会话状态；`/rewind` 恢复 /clear 前对话
- Kimi Code：`/sessions` 浏览历史

**青小团现状**：
- `qxt session list` 存在，但无实时状态视图
- 无 Rewind

**差距等级**：⚠️ 低差距，体验优化

---

## 三、青小团已领先/持平的维度

1. **模型中立性**：51 provider，远超 Kimi Code(6类) 和 Claude Code(仅Claude)
2. **插件架构**：微内核 + @plugin 装饰器 + 服务注册表 + 事件总线，架构上优于两者的配置式插件
3. **多语言**：10语言 README + i18n 运行时翻译，领先
4. **开源**：MIT 开源，与 Kimi Code 并列，优于闭源的 Claude Code
5. **价格**：免费，优于两者的订阅制
6. **外部引擎架构**：9个 JSONL IPC 外部引擎（diff/json/safety/crypto/ansi/index/search/notify/rules），进程隔离，独特设计
7. **安全审计**：security_bus + audit-export + CIDR 出口白名单 + 单向模式，安全纵深强
8. **Hooks**：8种事件（PreToolUse/PostToolUse/UserPromptSubmit/Stop/SubagentStop/PreCompact/SessionStart/SessionEnd），与 Claude Code 持平
9. **MCP**：完整支持 stdio + HTTP，与两者持平
10. **子代理**：SubAgentPool 并发隔离上下文，与 Kimi Code AgentSwarm / Claude Code Subagents 持平
11. **cron**：内建定时任务，Kimi Code 无，Claude Code 靠 /loop + Routines

---

## 四、补齐优先级与实施计划

### 本轮实施（弄到顶级）

| # | 补齐项 | 对标 | 优先级 | 实施方式 |
|---|---|---|---|---|
| 1 | `-p/--print` headless + `--output-format json` | Claude/Kimi | P0 | 增强 cmd_run + 新增 JSON 流输出 |
| 2 | `--bare` CI 纯净模式 | Claude | P0 | build_kernel 增加 bare 标志 |
| 3 | Edit 工具 multi-cut + Read-before-Edit 守卫 | Claude/Kimi | P0 | 增强 filesystem.edit_file + 工具管线守卫 |
| 4 | 编辑前 diff 预览确认 | Claude /diff | P1 | 新增 diff_preview 工具 + 确认机制 |
| 5 | Auto Memory 自动记忆（4类） | Claude | P1 | PostToolUse/Stop hook 自动提取 + MemoryStore 分类 |
| 6 | `!` Shell 快捷模式 | Claude | P2 | REPL 输入解析 + shell 执行 |
| 7 | TodoWrite 内置工具 | Claude | P2 | 新增工具插件 |
| 8 | `/init` 项目引导 | Claude | P2 | 新增斜杠命令 |
| 9 | 会话导出 zip | Kimi | P2 | 新增 qxt session export |

### 记录但不实施

- IDE 扩展（工程量超出 CLI 范围，ACP 已有接入点）
- 云端功能（定位不符）
- Mermaid/LaTeX 终端渲染（价值有限）
- vim 模式（价值有限）
- 屏幕阅读器（价值有限）
- Tool(param:value) 精确权限（低优先级，后续迭代）
- agent view / Rewind（低优先级，后续迭代）
- 自动更新 `qxt upgrade`（需 PyPI 发布流程，后续）

---

## 五、信源索引

### Kimi Code
- 官方文档：https://moonshotai.github.io/kimi-code/
- 官方 changelog：https://moonshotai.github.io/kimi-code/en/release-notes/changelog.html
- npm 包：https://www.npmjs.com/package/@moonshot-ai/kimi-code
- GitHub：https://github.com/MoonshotAI/kimi-code (MIT)
- 第三方对比：https://aitoolsrecap.com/Blog/kimi-code-cli-vs-claude-code-2026

### Claude Code
- 官方文档：https://code.claude.com/docs
- 官方 changelog/whats-new：https://code.claude.com/docs/en/whats-new/index
- npm 包：https://www.npmjs.com/package/@anthropic-ai/claude-code
- 定价：https://claude.com/pricing
- 第三方 SWE-bench：https://vortx.ch/copilot-vs-claude-code-vs-cursor-july-2026-update/

### 青小团
- 项目根：E:\Qingxiaotuan Agent CLI
- 版本：v0.2.017（qingxiaotuan/__init__.py）
- 测试：210 文件 / 2545 用例
