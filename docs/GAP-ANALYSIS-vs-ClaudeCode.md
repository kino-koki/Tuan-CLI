# Tuan-CLI ↔ Claude Code v2.1.289 能力差距分析

> 目标：将 Tuan-CLI 所有功能完善并开发至 Claude Code 最新版本（v2.1.289，2026-10-03）同等能力。
> 本文件是三分类差距分析：**A 真实可补缺口** / **B 平台特定不适用** / **C 已有需对齐增强**。

## 对照基线

| 维度 | Claude Code v2.1.289 | Tuan-CLI（当前） | 结论 |
|---|---|---|---|
| Slash 命令 | ~80+（含 `/workflow` `/goal` `/design` `/code-review` 等） | 54 个（`SLASH_COMMAND_NAMES`） | **缺 ~30 项** |
| CLI 子命令 | `claude ...` 全量 | 43 核心 + 扩展 | 部分对齐 |
| Subagent | 可递归 spawn（链深上限 5） | 单层（`subagent_tool`） | **缺递归链深** |
| Dynamic Workflow | 数十~数百 subagent 后台编排 | `dynamic_workflow` 已存在 | 已具备，可增强 |
| `/goal` | 跨 turn 持续工作 | 已有 `_cmd_goal` | 已具备 |
| Background/Monitor | `/bg` `/tasks` Monitor 流式事件 | `background.py` 存在，slash 未接 | **缺 slash 入口** |
| Doctor | 修复型（诊断 + 可修复） | `tuan doctor` 只读诊断 | **缺修复能力** |
| Code Review | `/code-review --fix` `/security-review` | 工具层有 `code_review`，slash 未接 | **缺 slash 入口 + --fix** |
| Safe mode / auto mode | `--safe-mode` `auto-mode` | 安全四闸门已有，无 safe-mode 开关 | **缺开关** |
| fallbackModel / maxEffortLevel | 配置项 | 无 | **缺配置** |
| 主题/配色 | `/theme` `/color` | 无 | **缺** |
| 会话 fork/branch | `/fork` `/branch` `/cd` `/btw` | `session fork` 有，slash 无 | **缺 slash 入口** |
| 复制/后台化 | `/copy` `/background` | 无 | **缺** |

---

## A. 真实可补缺口（Tuan-CLI 定位下可实现、通用）

以下命令/能力在当前插件容器 + 三主循环 + 58 providers 架构下完全可落地，为本轮开发重点。

### A1. Slash 命令补全（`cmd_slash.py` 的 `_handle_slash`）

| 命令 | 功能 | 实现落点 |
|---|---|---|
| `/fork` | 复制当前对话到新后台会话 | 复用 `SessionStore.fork`（`cmd_session.py` 已有） |
| `/branch` | 对话分支（树视图 + 切分支） | 复用 `session tree`（`_print_tree`） |
| `/cd` | 会话内切换工作目录 | `ui.invalidate_git_cache` + 更新 `ctx.workspace` |
| `/btw` | side question（主任务不中断的旁问） | 派发子代理，回注摘要 |
| `/copy` | 复制最近一次响应到剪贴板 | `pyperclip` 或 `clip` 平台命令 |
| `/tasks` | 后台任务列表 | 复用 `BackgroundRunner` |
| `/theme` | 切换 UI 主题 | 新增 theme 配置 + `ui/theme.py` 应用 |
| `/color` | 配色方案 | 同 theme |
| `/loop` | 进入自主开发循环 | 复用 `loop_plugin.switch_loop` + `DevLoopProvider`（**已注册但 slash 未接**） |
| `/review` | 自动代码评审 | 复用 `tools/code_review.py` |
| `/code-review` | correctness bugs + `--fix` | 复用 `code_review` + 加 `--fix` |
| `/security-review` | 安全审查 | 复用安全四闸门 + code_review |
| `/simplify` | 简化冗余代码 | 新增 `tools/simplify` |
| `/debug` | 调试诊断 | 复用 `doctor` 诊断 + 日志 |
| `/batch` | 批量任务 | 复用 `_cmd_blast` 增强 |
| `/background` `/bg` | 分离为后台 agent | 复用 `BackgroundRunner` |
| `/config key=value` | 会话内改配置 | 复用 `cmd_config` set |
| `/doctor` | 修复型 setup checkup | 增强 `cmd_doctor`（修复型） |
| `/dataviz` | 数据可视化 | 复用 `chart-visualization` 思路 |
| `/design` | 设计工作流 | 前端设计 skill |
| `/artifacts` | 生成 artifact | 复用 `cmd_web` 产物 |
| `/auto-mode-setup` | 分类器代替权限提示 | 复用权限四闸门 + 自动模式 |

### A2. CLI 命令面对齐（`parser_commands.py`）

| 目标 | Tuan-CLI 落点 |
|---|---|
| `claude doctor` 修复型 | `tuan doctor --fix` |
| `claude code-review` | `tuan review`（新） |
| `claude security-review` | `tuan security-review`（新） |
| `claude simplify` | `tuan simplify`（新） |
| `claude debug` | `tuan debug`（新） |
| `claude auto-mode` | `tuan auto-mode`（新） |
| `claude project purge` | `tuan project purge` |
| `claude agents` 视图 | 已有 `tuan agents view` |
| `claude bg` | 已有 `tuan bg` |

### A3. Subagent 递归 spawn（链深上限 5）

- `subagent_tool.py`：给 `_run_subagent` 增加 `depth` 参数；`ctx` 上维护 `subagent_chain`；
- 当子代理内部再调用 `subagent` 工具时，`depth+1`；超过上限返回 `[错误] 子代理链深超限(5)`；
- 事件总线已定义 `SubagentSpawnedEvent` 等，可复用。

### A4. 后台任务 + Monitor 流式事件

- `background.py` 已有 `BackgroundRunner`；补 `/tasks`、`/background`、`/bg` slash 入口；
- 补 `Monitor` 工具：流式推送 `background.job_*` 事件。

### A5. 配置增强

- `fallbackModel`（最多 3 个回退模型）：`config` 增加 `model.fallbacks`，`router` 失败时按序回退；
- `maxEffortLevel`：`config` 增加 `agent.max_effort_level`；
- `--safe-mode`：全局开关禁用所有定制（hooks/skills/personality）；
- `auto-mode`：分类器代替权限提示。

---

## B. 平台特定 / 云依赖（不适用或需权衡）

以下依赖 Anthropic 订阅/云服务或特定平台，Tuan-CLI 定位下不实现（保持本地 + 开源多 provider）：

- `/chrome` `/radio` `/desktop`（桌面/广播，需 Anthropic Desktop）
- `/teleport` `/remote-control`（跨机器，需云）
- `/cloud` `--cloud` `--channels`（需 Anthropic 云）
- `claude gateway` `claude self-hosted-runner` `claude setup-token`（需 Anthropic 基础设施）
- `/autofix-pr` `/ultrareview` `--advisor`（需 Anthropic 云审查）
- Cowork（协作平台）

这些在 `CAPABILITY-MATRIX.md` 中标注为"不适用（平台特定）"，不阻塞本轮目标。

---

## C. 已有需对齐 / 增强

| 项 | 现状 | 增强点 |
|---|---|---|
| `/workflow` | 已有 list/status/result/cancel/retry | 补 `/workflow-authoring`、`/deep-research` 编排模式 |
| `/goal` | 已有 | 对齐跨 turn 持续工作语义 |
| `/verify` | 已有 | 补 `--fix` 自修复增强 |
| `/subagent` | 已有 | 补递归 spawn + 链深 |
| `/effort` | 已有 | 补 maxEffortLevel |
| `/memory` | 已有 | 补长期记忆增强 |
| `/permissions` | 已有 | 补 auto-mode |
| `/doctor` | 只读 | **升级修复型** |
| 主题 | `ui/theme.py` | 补 `/theme` `/color` |

---

## 优先级与阶段

- **P1（高价值，本阶段）**：A1 slash 命令补全（fork/branch/cd/btw/copy/tasks/theme/color/loop/review/config=）+ A2 CLI 面对齐 + A3 subagent 递归 + A5 配置增强
- **P2（中价值）**：A1 剩余（code-review/security-review/simplify/debug/batch/background/dataviz）+ A4 Monitor + auto-mode
- **P3（对齐）**：C 类增强项

> 注：B 类平台特定功能不在本轮范围，属架构定位差异而非能力缺失。
