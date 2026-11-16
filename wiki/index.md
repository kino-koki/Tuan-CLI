# 青小团 Tuan-CLI 百科全解 (Wiki)

> 本项目 wiki 是**面向读者与贡献者的百科全书式导航**，回答"青小团是什么、由哪些子系统构成、每个子系统解决了什么问题、关键卖点与已知局限"。
>
> 目标读者：想评估/使用青小团的人、想贡献代码的人、想对比它与 Claude Code / Codex / Cursor / Kimi Code 差异的人。
>
> 与 `docs/` 的区别：`docs/` 是**过程性文档**（路线图、差距分析、架构演进、协议契约），wiki 是**概念性百科**（每个子系统"是什么/为什么/关键文件/卖点/局限"）。

---

## 0. 一句话

**青小团 (Tuan-CLI)** 是一个 **safety-first、model-agnostic、纯 Python** 的多理念融合 AI Agent 终端宿主：它在 **0 星仓库**里用 **~723 个 Python 文件 / ~17.2 万行** 实现了插件容器、四道安全闸门、58 Provider 热切换、三主循环、三层记忆、技能自进化、MCP/ACP 生态互操作、Agent-of-Agents 派发、多 Agent 协作、cron、subagents、Goal mode、持久化编排、审批树、反思性自我进化闭环 —— 而运行时**只依赖 2 个第三方包**（rich、prompt_toolkit），其余 httpx/openai/pydantic/pyyaml 全部由内部零依赖实现替代。

## 1. 关键数字（2026-11-15 快照）

| 指标 | 值 |
|---|---|
| 顶层 CLI 子命令 | 94 |
| 斜杠 `/` 命令 | 88 |
| Python 文件（tuan_cli） | ~723 |
| 代码行（tuan_cli） | ~172,000 |
| 测试文件 | ~484 |
| 测试用例（收集） | 8,493 |
| Provider（模型/后端） | 58 |
| 运行时第三方依赖 | **2**（rich、prompt_toolkit） |
| 语言 README | 10 |
| 版本 | 0.4.2 |
| 安全闸门 | 4（硬红线 / YOLO 红线 / 事务账本 / 写边界） |
| 主循环 | 3（ReAct / Planner-Execute / DevLoop） |
| 内存层 | 3（短期 / 中期 / 长期） |

## 2. 子系统目录（百科条目）

每个条目是独立的 wiki 页面，聚焦"**是什么 → 为什么 → 关键文件 → 卖点 → 局限**"。

### 架构核心
- [架构与内核 Kernel](architecture.md) —— 插件容器、服务注册表、append-only 事件总线
- [分层分层 (arch)](arch.md) —— context/execution/platform/observability/security/orchestration
- [核心运行时 (core)](core.md) —— 主循环、agent、路由、账本、编排、写边界、背景 shell

### 安全
- [四道安全闸门](safety.md) —— 硬红线 / YOLO 红线 / 事务账本 / 写边界
- [沙箱与出站 (sandbox)](sandbox.md) —— assess_tool/assess_command/egress 计划/verdict
- [审批与策略 (approval)](approval.md) —— 审批树、可编程规则、审计联动
- [硬化与评审 (harden)](harden.md) —— /security-review、威胁扫描、白名单

### 生态与互操作
- [Provider 热切换 (models)](models.md) —— 58 Provider 注册表与路由
- [MCP 接入 (runtime/mcp)](mcp.md) —— 客户端协议、工具策略
- [ACP 接入 (runtime/acp)](acp.md) —— 客户端/服务端握手
- [Agent-of-Agents 派发 (agents)](agents.md) —— 五适配器 + mode/health 路由
- [技能与自进化 (self_improve)](self-improve.md) —— 蒸馏/规则/技能生成/进化闭环
- [生态桥 (ecosystem)](ecosystem.md) —— 多引擎隔离与互操作

### 编排与协作
- [多 Agent 编排 (core/orchestrator)](orchestrator.md) —— 群组持久化、DAG 断点恢复、失败回滚
- [Swarm / 协作协议](collaboration.md) —— 群组、协作、黑板
- [Goal mode](goal.md) —— 目标驱动执行
- [Cron 调度 (cron)](cron.md) —— 周期任务

### 人机交互
- [TUI 交互 (tui)](tui.md) —— 双渲染栈、键盘/鼠标、主题 token 单一来源
- [UI 权威渲染 (ui)](ui.md) —— splash/mascot/theme 单一来源
- [主题系统 (theme)](theme.md) —— BRAND_PRIMARY/BRAND_SECONDARY 唯一 token
- [10 语言 i18n](i18n.md) —— 国际化

### 记忆与上下文
- [三层记忆 (memory)](memory.md) —— 短期/中期/长期
- [上下文工程 (context)](context.md) —— 索引、compaction、fast-index
- [会话与快照 (session)](session.md) —— 会话生命周期、断点恢复

### 命令面
- [CLI 命令面 (cli)](cli.md) —— 94 子命令 + 88 斜杠命令
- [流式 I/O (stream_json)](stream-io.md) —— --input/--output-format stream-json 线协议
- [Parity 与差距分析 (parity)](parity.md) —— 与 Claude Code 对齐/领先/差距矩阵

### 其它
- [可观测性与审计 (audit)](audit.md) —— 审计存储、轨迹、诊断
- [远程控制与通知 (remote-control)](remote-control.md) —— QR 配对、跨设备推送、告警
- [Web / 桌面端 (web)](web.md) —— Web 工作台、dispatch server、桌面壳
- [开发者工具](devtools.md) —— doctor/bench/integrity/checkpoint/evolve

## 3. 如何阅读

1. 想快速上手：`docs/QUICKSTART.md`
2. 想了解能力边界：`docs/API_FREEZE.md`、`docs/parity/CAPABILITY-MATRIX.md`
3. 想评估安全性：本 wiki 的 [四道安全闸门](safety.md)
4. 想对比竞品：`docs/GAP-ANALYSIS-vs-ClaudeCode.md`、本 wiki 的 [Parity](parity.md)
5. 想理解演进方向：`docs/AGENT-EVOLUTION-ROADMAP.md`、`docs/ROADMAP.md`
6. 想贡献代码：本 wiki 各子系统的"关键文件"，加 `docs/modes_contract_20261023.md`

## 4. 已知局限（诚实清单）

- `ipc_client._spawn_once` 全量并行偶发 60s 超时（环境相关，非稳定缺陷）。
- 事件总线 `_MAX_EVENTS=2000` 上限 + 溢出回调（有意设计，非无限日志）。
- `--input-format stream-json` 流式输入由 `tuan_cli.stream_json` headless 驱动器支持（`headless.py` + `__main__.py`，输入/输出格式校验已实现）；主 CLI 无独立 input-format 分支（headless 专有）。
- TUI 无 aria/screen-reader 支持（键盘/鼠标已完整，可访问性待补）。
- 索引非增量持久化（indexer 每次会话重建）。
- 测试收集 8493，实跑全量含少数环境相关偶发（如外部引擎 diff 子进程争用）。

## 5. 相关文档索引

| 文档 | 主题 |
|---|---|
| `docs/AGENT-EVOLUTION-ROADMAP.md` | 阶段 A/B/C/D 演进路线图（A 进化闭环 B 编排恢复 C 审批树 D 主题收敛） |
| `docs/GAP-ANALYSIS-vs-ClaudeCode.md` | 与 Claude Code 的差距分析 |
| `docs/FAST-IO.md` | 流式/快速 I/O |
| `docs/ROADMAP.md` | 总路线图 |
| `docs/QUICKSTART.md` | 快速开始 |
| `docs/CHANGELOG-archive.md` | 变更日志归档 |
| `docs/ecosystem_bridge.md` | 生态桥 |
| `docs/API_FREEZE.md` | 冻结 API |
| `docs/TUAN-DISPATCH-PROTOCOL.md` | 派发协议 |
| `docs/TUAN-CHAT-NATIVE-ARCHITECTURE.md` | 聊天原生架构 |
| `docs/modes_contract_20261023.md` | 模式契约 |
| `docs/skill_distillation_guide.md` | 技能蒸馏指南 |

## 6. 维护约定

- 本 wiki 是**概念性百科**，不承载过程性文档（那些在 `docs/`）。
- 每个条目必须诚实列出局限，不夸大卖点。
- 更新：改动某子系统时同步更新对应条目；新增子系统时在 §2 加行。
- 指标快照（§1）在重大版本时刷新。
