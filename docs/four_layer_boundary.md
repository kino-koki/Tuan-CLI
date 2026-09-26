# Agent 四层工作边界 (Four-Layer Boundary)

> 理念来源: B 站视频 BV1j3YL6oEvs —— 一个长期运行的 Agent, 应该有四层不同尺度的
> "工作边界", 各司其职, 不互相污染。

青小团把这四层全部落地为**可运行的命令 / 工具 / 配置**, 不是设计文档里的空中楼阁。

## 总览

| 层 | 解决什么问题 | 落地形式 |
|---|---|---|
| Project 层 | 长期工作需要固定办公室, 项目间不串味 | 每个目录独立 `.qxt/` |
| Chat 层 | 对话太长要及时交接, 别硬撑 | 摘要压缩 → 新会话 |
| Subagent 层 | 重任务隔离在外, 别把主上下文淹了 | 独立工作目录 + 独立上下文 |
| Worktree 层 | 并行修改时互不污染 | git worktree 分支 |

---

## 1. Project 层 —— 固定办公室

每个工作目录就是一个独立办公室, 有自己的记忆 / 配置 / 会话索引 / 快照:

```
<你的项目>/.qxt/
├── config.yaml      项目级配置 (覆盖全局)
├── goal.json        当前项目目标
├── memory.db        项目级记忆 (与全局记忆隔离)
├── project.json     项目 ID / 创建时间
├── sessions.json    本项目的会话索引
├── snapshots/       Rewind 快照
├── subagents/       子代理工作目录
└── worktrees/       git worktree 实验目录
```

用法:

```bash
cd 你的项目
qxt project init      # 初始化 (幂等; 已有 .qxt/ 自动识别)
qxt project info      # 查看项目 ID / 会话数 / 记忆数
qxt project list      # 列出所有已知项目 (~/.qingxiaotuan/projects.json)
```

隔离语义: 在 A 目录和 B 目录跑 qxt, 记忆、配置、会话列表互不可见。

配置:

| 配置项 | 默认 | 说明 |
|---|---|---|
| `project.isolation_enabled` | `true` | 项目级隔离开关 |

---

## 2. Chat 层 —— 及时交接

会话越长越贵、越容易跑偏。与其等系统硬压缩丢信息, 不如主动"交班":

```
旧会话 (归档)  --摘要-->  新会话 (继承项目记忆/配置)
```

摘要分四节: **目标 / 已完成 / 待办 / 关键文件与决策**。

用法:

```
/handoff                  # 会话中手动交接
qxt chat handoff <id>     # CLI 交接指定会话
```

上下文超过 `chat.auto_handoff_threshold`(默认模型窗口的 80%) 时会自动提示交接。
交接谱系落在 `.qxt/handoffs.json`, 可用 `qxt session resume <新会话ID>` 无缝接手。

配置:

| 配置项 | 默认 | 说明 |
|---|---|---|
| `chat.handoff_enabled` | `true` | 交接总开关 |
| `chat.auto_handoff_threshold` | `0.8` | token 占用达到窗口比例即提示 |

---

## 3. Subagent 层 —— 重任务外包

重活 (大批量调研、独立跑脚本) 派给子代理: 它在 `.qxt/subagents/<task_id>/`
独立目录里干活, 用独立上下文, 只把摘要交回来。

用法:

```
/subagent run 帮我调研三个竞品的定价
/subagent status          # 查看子任务状态
```

- 子代理的文件操作默认落在独立工作目录, 不污染主工作区;
- 子代理崩溃 / 超时不影响主会话;
- 超时自动 kill 并记录状态 (`done` / `failed` / `timeout`)。

配置:

| 配置项 | 默认 | 说明 |
|---|---|---|
| `subagent.isolated_workdir` | `true` | 独立工作目录 |
| `subagent.timeout` | `300` | 单任务超时秒数 |

---

## 4. Worktree 层 —— 并行实验

想同时试方案 A 和方案 B? 给每个实验开一个 git worktree:

```
/worktree create exp-redesign    # 开 .qxt/worktrees/exp-redesign (新分支)
/worktree list                   # 列出全部 worktree
/worktree switch exp-redesign    # 切换过去
/worktree remove exp-redesign    # 不要了就删
```

CLI 等价命令: `qxt worktree create|list|remove|switch <name>`。
满意就 `git merge` 回主分支, 不满意直接 remove, 主工作区毫发无损。
(非 git 仓库会提示先 `git init`。)

---

## Rewind (时间线回溯)

与四层边界配套: 每次你按回车发消息前, 青小团自动存一份快照。说错话了不用 `/clear`
清空一切:

```
/rewind              # 回退一步
/rewind list         # 看有哪些快照
/rewind to 3         # 精确回到 3 号快照
qxt rewind <id>      # CLI 离线回退某个会话
```

快照保存在 `.qxt/snapshots/`, 只留最近 `rewind.max_snapshots`(默认 20) 个。

## Agent View

```
qxt agents view          # rich 表格看全部会话状态
qxt agents view --watch  # top 模式实时刷新
qxt agents kill <id>     # 终止后台会话
```

## 设计原则

- 全部四层都是**微内核插件式增强**: 不改内核核心, 以 CLI 命令 / 斜杠命令 / 工具形式挂载;
- 每层都有独立测试 (`tests/test_project_layer.py` / `test_chat_handoff.py` /
  `test_subagent_isolation.py` / `test_worktree_layer.py`);
- 中文文档与注释。
