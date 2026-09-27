"""四层边界自动生效编排 (微内核 · 纯函数 / 轻量类集合)。

四层边界原本是「命令驱动」(``qxt project init`` / ``/handoff`` / ``/subagent`` /
``/worktree``)。本模块把它们升级为「内置默认自动生效」—— 用户无需记命令:

- **Project 层**: 会话启动即自动确保 ``.qxt/`` 存在 (见 :func:`ensure_project_context`);
- **Subagent 层**: 重任务自动派给隔离子代理 (见 :func:`should_isolate_task` /
  :func:`try_run_isolated`);
- **Worktree 层**: 检测到「方案 A / 方案 B」类并行实验意图时自动开 worktree
  (见 :func:`detect_parallel_intent` / :func:`auto_create_parallel_worktree`)。
- **Chat 层** 的超阈值自动交接方法挂在 :class:`~qingxiaotuan.core.chat_handoff.ChatHandoff`
  上 (``auto_handoff_if_needed``), 本模块只做编排不重复实现;
- **Rewind** 输入前自动快照已在 ``_run_turn`` 落地, 无需改动。

设计约束:
- 本模块是纯函数 + 轻量编排, **不做成重型插件**; hook 点在 CLI 层 (cmd_chat /
  cmd_run), 不侵入内核;
- 所有自动行为都有配置开关 (默认开启), 且全部 try/except 包裹, 绝不阻断正常对话;
- **bare 模式** (CI / 纯净模式): project auto-init 仍执行 (``.qxt/`` 落在工作区内,
  不污染用户全局配置), 但 auto-handoff / auto-subagent / auto-worktree 一律跳过,
  保证评测可复现。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from .project_layer import ProjectInfo, ProjectLayer


# ------------------------------------------------------------------ 配置读取小工具

def _cfg(config: Any, key: str, default: Any) -> Any:
    """鸭子类型读配置: config 为 None / 无 get / 抛异常时一律回退 default。"""
    if config is None:
        return default
    try:
        return config.get(key, default)
    except Exception:  # noqa: BLE001
        return default


# ------------------------------------------------------------------ 1. Project 层: 会话启动自动初始化

def ensure_project_context(workspace: str | Path, config: Any = None,
                           bare: bool = False) -> ProjectInfo:
    """会话启动时确保 ``.qxt/`` 项目上下文存在 (幂等)。

    - ``project.auto_init`` 默认 ``true``; **bare 模式仍初始化** (``.qxt/`` 落在工作区内,
      不污染用户全局配置, 与「纯净模式」不冲突);
    - 已存在时 :meth:`ProjectLayer.init` 幂等, 直接返回已有 ProjectInfo, 不重复建骨架;
    - 关闭开关 (``project.auto_init=false``) 时只读 info, 不创建任何目录。

    返回: 当前项目信息 (initialized=True 表示本次已确保骨架就绪)。
    """
    if not bool(_cfg(config, "project.auto_init", True)):
        return ProjectLayer(workspace, config).info()
    return ProjectLayer(workspace, config).init()


# ------------------------------------------------------------------ 2. Subagent 层: 重任务自动隔离判定

_ISOLATE_KEYWORDS = ("同时", "并行", "分别", "独立", "另外")
_ISOLATE_LEN_THRESHOLD = 500


def should_isolate_task(user_input: str) -> bool:
    """启发式: 该任务是否值得派给 subagent 隔离执行 (纯函数, 便于测试)。

    命中任一即建议隔离:
    - 任务描述长度 > 500 字符 (长任务);
    - 包含「同时 / 并行 / 分别 / 独立 / 另外」等多任务并行意图关键词。
    """
    text = user_input or ""
    if len(text) > _ISOLATE_LEN_THRESHOLD:
        return True
    return any(k in text for k in _ISOLATE_KEYWORDS)


def try_run_isolated(agent: Any, user_input: str, config: Any = None,
                     bare: bool = False) -> Optional[str]:
    """尝试把重任务派给 subagent 隔离执行, 返回子代理摘要; 未触发 / 失败返回 None。

    返回 None 时由调用方回退主会话直接执行 (``agent.run``), 不污染主上下文。

    - bare 模式跳过 (评测可复现);
    - ``subagent.auto_isolate`` 默认 ``true``, 关闭则直接 None;
    - 任何异常 / 子代理内部报错 (``[子代理错误] ...``) 都吞掉返回 None。
    """
    if bare:
        return None
    cfg = config if config is not None else getattr(agent, "config", None)
    if not bool(_cfg(cfg, "subagent.auto_isolate", True)):
        return None
    if not should_isolate_task(user_input):
        return None
    try:
        # 延迟导入避免 app -> tools -> core -> app 循环依赖
        from ..tools.subagent_tool import _run_subagent
        summary = _run_subagent(agent.ctx, task=user_input)
    except Exception:  # noqa: BLE001
        return None
    # 子代理内部失败时返回 "[子代理错误] ..." —— 视为失败, 回退主会话
    if not summary or str(summary).startswith("[子代理错误]"):
        return None
    return summary


# ------------------------------------------------------------------ 3. Worktree 层: 并行实验意图自动创建

# 并行实验意图关键词 (统一去空格 + 小写后匹配)
_PARALLEL_PATTERNS = (
    "方案a", "方案b", "对比", "比较",
    "试一下另一种", "试另一种", "两种方式", "两种方法",
    "另一种思路", "另一个方案", "两个方案", "另一种",
)


def detect_parallel_intent(user_input: str, counter: int = 1) -> Optional[str]:
    """启发式: 是否表达了「并行试两个方向」的意图, 返回建议 worktree 名。

    命中「方案 A / 方案 B」「对比」「试一下另一种」「两种方式」等并行实验意图时,
    返回建议的 worktree 名 (默认 ``experiment-1``); 否则返回 None。纯函数, 便于测试。
    """
    norm = (user_input or "").lower().replace(" ", "")
    if any(p in norm for p in _PARALLEL_PATTERNS):
        return f"experiment-{max(1, int(counter))}"
    return None


def auto_create_parallel_worktree(workspace: str | Path, user_input: str,
                                  config: Any = None, bare: bool = False
                                  ) -> Optional[Any]:
    """检测到并行实验意图时自动创建 worktree, 返回 WorktreeInfo; 否则 / 失败返回 None。

    - bare 模式跳过;
    - ``worktree.auto_create`` 默认 ``true``, 关闭则跳过;
    - 非 git 仓库优雅跳过 (仅返回 None, 不报错 —— 由调用方决定是否提示);
    - 名字冲突时自动递增 ``experiment-N`` 直到找到可用名。
    """
    if bare:
        return None
    if not bool(_cfg(config, "worktree.auto_create", True)):
        return None
    if detect_parallel_intent(user_input) is None:
        return None
    from .worktree_layer import WorktreeError, WorktreeLayer
    layer = WorktreeLayer(workspace)
    if not layer.is_git_repo():
        return None  # 非 git 仓库: 静默跳过
    # 找一个不冲突的名字 (experiment-1, experiment-2, ...)
    try:
        existing = {i.name for i in layer.list()}
    except Exception:  # noqa: BLE001
        existing = set()
    name: Optional[str] = None
    for n in range(1, 50):
        candidate = f"experiment-{n}"
        if candidate not in existing:
            name = candidate
            break
    if name is None:
        return None
    try:
        return layer.create(name)
    except WorktreeError:
        return None
