# Agent 四层边界 · 默认自动生效 (Four-Layer Boundary Auto)

> 配套文档: [four_layer_boundary.md](./four_layer_boundary.md) 讲「四层是什么、怎么手动用命令」;
> 本文讲「四层如何**内置默认自动生效** —— 用户无需记命令」。

四层边界原本是「命令驱动」(`qxt project init` / `/handoff` / `/subagent` / `/worktree`)。
本次改造把它们升级为**内置必须使用、默认自动生效**: 会话启动即建办公室、上下文满即自动交班、
重任务自动外包、并行实验自动开 worktree。用户什么都不用敲, 边界自然就在。

编排集中在 `qingxiaotuan/core/boundary_auto.py` (纯函数 + 轻量类, 不做重型插件),
hook 点在 CLI 层 (`cmd_chat.py` / `cmd_agents.py`), **不侵入内核**。

---

## 总览: 每层从「命令」变成「自动」

| 层 | 之前 (可选命令) | 现在 (默认自动生效) | 配置开关 (默认) |
|---|---|---|---|
| Project | `qxt project init` | 会话启动 / headless 任务启动即自动建 `.qxt/` | `project.auto_init` (true) |
| Chat | `/handoff` 手动 | 上下文超阈值自动交接, 打印 旧→新会话 + 摘要 | `chat.auto_handoff_enabled` (true) |
| Subagent | `/subagent run` 手动 | 长任务 / 多任务并行意图自动隔离, 失败回退主会话 | `subagent.auto_isolate` (true) |
| Worktree | `/worktree create` 手动 | 检测到「方案A/方案B」自动开 worktree | `worktree.auto_create` (true) |
| Rewind | (已自动) | 输入前自动快照 —— 保持现状, 无需改动 | —— |

---

## 1. Project 层: 会话启动自动初始化

任何交互会话 (`qxt chat` / `qxt --print` / TUI) 或 headless 任务 (`qxt run`) 启动时,
在构建内核之前 / 之后自动调用 `ensure_project_context(workspace, config)`:

```python
# qingxiaotuan/core/boundary_auto.py
def ensure_project_context(workspace, config=None, bare=False) -> ProjectInfo:
    if not config.get("project.auto_init", True):
        return ProjectLayer(workspace, config).info()
    return ProjectLayer(workspace, config).init()   # 幂等
```

- `ProjectLayer.init()` 幂等: 已有 `.qxt/` 直接返回, 不重建骨架、不覆盖 `QXT.md`;
- hook 点: `cmd_chat.py::_prepare_agent()` (build_kernel 之前) 与
  `cmd_agents.py::cmd_run()` (workspace 确定后、create_agent 之前);
- 失败一律 try/except 静默, 绝不阻断启动。

## 2. Chat 层: 超阈值自动交接 (而非仅提示)

`ChatHandoff` 新增方法:

```python
# qingxiaotuan/core/chat_handoff.py
def auto_handoff_if_needed(self, estimated_tokens, model_max_tokens,
                           old_session_id, messages, generate_fn=None,
                           project_id="") -> Optional[HandoffReport]:
    if not self.enabled:                                   # chat.handoff_enabled
        return None
    if not self._cfg("chat.auto_handoff_enabled", True):   # 自动执行开关
        return None
    if not should_handoff(estimated_tokens, model_max_tokens, self.threshold):
        return None
    return self.handoff(old_session_id, messages, ...)     # 直接交班
```

- 与旧 `maybe_prompt()` 的区别: `maybe_prompt` 只提醒用户; `auto_handoff_if_needed`
  **直接完成交班** (生成摘要 → 开新会话 → 旧会话归档 → 落 `.qxt/handoffs.json`)。
- 在 `_run_turn()` 每轮结束后, 用 `agent.context_stats()` 拿 `estimated_tokens /
  budget_tokens`, 达阈值即自动交接;
- 交接不打断当前输入流程: 轮次结束后静默执行并打印
  `旧会话 → 新会话 + 摘要预览`, 新 `session_id` 注入 REPL 后续轮次。

## 3. Subagent 层: 重任务自动隔离

```python
# qingxiaotuan/core/boundary_auto.py
def should_isolate_task(user_input: str) -> bool:
    if len(user_input) > 500:                 # 长任务
        return True
    return any(k in user_input for k in ("同时", "并行", "分别", "独立", "另外"))
```

- `_run_turn()` 命中启发式且 `subagent.auto_isolate=true` 时, 走
  `try_run_isolated()` → 直接调既有 `_run_subagent(agent.ctx, task=...)`,
  在隔离上下文里跑完只把摘要交回主会话;
- **失败回退**: 子代理报错 (`[子代理错误] ...`) / 任何异常 / 开关关闭, 一律返回 None,
  主会话照常 `agent.run()` —— 不污染主上下文, 也不丢任务。

> 这一层做不到 100% 全自动 (任务复杂度需判断), 设计为
> 「自动触发条件 + 自动执行 + 失败回退」。

## 4. Worktree 层: 并行实验意图自动创建

```python
# qingxiaotuan/core/boundary_auto.py
def detect_parallel_intent(user_input, counter=1) -> Optional[str]:
    # 命中「方案A/方案B」「对比」「试一下另一种」「两种方式」…
    # 返回建议名 experiment-N; 否则 None
```

- `_run_turn()` 命中意图且 `worktree.auto_create=true` 时, 自动
  `WorktreeLayer(workspace).create(name)` (名字冲突自动递增 experiment-1/2/…);
- **非 git 仓库优雅跳过** (`is_git_repo()` 为 False 时仅返回 None, 不报错);
- 创建后提示: `已为并行实验创建 worktree: <path>`。

## 5. Rewind: 保持现状

输入前自动快照已实现, 无需改动。`/rewind` 回退命令保留 —— 它是恢复操作, 不是日常负担。

---

## 配置项一览

| 配置项 | 默认 | 说明 |
|---|---|---|
| `project.auto_init` | `true` | 会话/任务启动自动建 `.qxt/` |
| `chat.auto_handoff_enabled` | `true` | 超阈值自动交接 (false 则退回「仅提示」) |
| `chat.handoff_enabled` | `true` | 交接总开关 (既有) |
| `chat.auto_handoff_threshold` | `0.8` | token 占窗口比例阈值 (既有) |
| `subagent.auto_isolate` | `true` | 重任务自动隔离执行 |
| `worktree.auto_create` | `true` | 并行实验意图自动开 worktree |

## bare 模式 (CI / 纯净模式)

`--bare` 时:
- **Project auto-init 仍执行** —— `.qxt/` 落在工作区内, 不污染用户全局配置;
- **auto-handoff / auto-subagent / auto-worktree 一律跳过** —— 保证评测可复现
  (`ensure_project_context` / 各自动函数都接受 `bare: bool = False` 参数)。

## 设计边界

- **附加、不破坏**: 所有自动行为都是「附加」的, 不改正常对话流程; 全部 try/except 包裹,
  失败即回退到原有路径;
- **微内核**: `boundary_auto.py` 是纯函数/轻量类集合, hook 在 CLI 层, 不动内核;
- **可关**: 每层都有配置开关, 用户随时退回手动模式;
- **测试**: `tests/test_boundary_auto_enabled.py` 验证自动建 `.qxt/`、超阈值自动交接、
  两个启发式函数、非 git 仓库跳过与 bare 短路; 既有四层测试保持绿。
