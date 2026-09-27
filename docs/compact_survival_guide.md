# Compact 存活表 (压缩 / 上下文交接契约)

> 对标 Claude Code「compact 后系统提示词 / output style / CLAUDE.md / auto memory / git 快照 /
> plan 全部从磁盘重注入」的显式契约。
> 对应代码: `qingxiaotuan/runtime/session/compact_survival.py`、`qingxiaotuan/core/prompts.py`。
> 自检命令: `qxt compact --verify`。

## 为什么需要这张表

`/compact`（或上下文超限自动压缩）会把早期对话折叠成一段摘要。**对话历史里的细节会丢**，
但 Agent 不能因此「失忆」。凡是跨压缩必须保留的状态，都不能只放在对话消息里——
必须落在磁盘文件、配置或内核服务上，压缩后由系统提示词 / 启动流程**重新发现**。

## 存活清单

| # | 状态 | 压缩后从哪里重建 | 重建入口 | 丢失后果 |
|---|------|------------------|----------|----------|
| 1 | SOUL.md 身份 | `<home>/SOUL.md`（缺失则用内置回退文案） | `prompts.build_system_prompt_stable` | 身份/信条漂移 |
| 2 | 分层项目指令 | 工作区沿途 `QXT.md` / `AGENTS.md` / `CLAUDE.md` + `~/.agents/AGENTS.md` | `prompts._discover_project_instructions` | 项目约定被遗忘 |
| 3 | MEMORY.md 记忆笔记 | `<home>/projects/<slug>/memory/MEMORY.md`（≤200 行注入） | `prompts.build_system_prompt_dynamic` | 用户偏好/纠正丢失 |
| 4 | FTS5 长期记忆 | `memory_store` 服务（`recall_context` 召回） | `build_task_context` / memory 插件 | 结构化事实检索失效 |
| 5 | Git 上下文 | 工作区 `.git`（分支 / 最近 commit / dirty 数） | `prompts._get_git_context` | 误以为工作区干净 |
| 6 | 技能注册表快照 | `skill_manager` 服务（按热度 top-N） | `prompts.build_system_prompt_dynamic` | 可复用技能不再被提示 |
| 7 | TodoWrite 任务清单 | `<workspace>/.qxt/todo.json` | todo 工具恢复 | 进行中任务状态丢失 |
| 8 | Goal 目标进度 | `<workspace>/.qxt/goal.json` | goal 模式恢复 | 自动续轮中断 |
| 9 | 输出风格 / 回复语言 | `config`（`ui.output_style` / `language`） | `prompts.build_system_prompt` | 风格/语言回退默认 |

## 重建顺序（新会话 / 压缩后）

1. 读 `config` → 拿到 home、语言、输出风格、各开关。
2. `build_system_prompt_stable()` → SOUL + 行为准则 + Windows/上网/编码/安全/技能/记忆笔记指引。
3. `build_system_prompt_dynamic()` → 环境 + Git + 项目指令 + 用户画像 + 长期记忆 + MEMORY.md + 代码库地图 + 技能快照 + 输出风格。
4. 首条 user 消息前贴 `build_task_context()` → 与本任务相关的记忆/技能语义召回。
5. 恢复 `.qxt/todo.json`、`.qxt/goal.json` 等会话内状态。

## 工程纪律

- **不要把关键状态只写在对话里**：用户偏好、项目决策、纠正，用 `memory_note_append`
  写进 MEMORY.md，或用 `memory_write` 写进 FTS5，而不是只在回复里说一遍。
- **稳定前缀可缓存，动态后缀不缓存**：见 `prompts.py` 顶部 docstring 的 cache 边界声明。
- **压缩后跑一次 `qxt compact --verify`**：确认上表 9 项在磁盘上都能重建。
