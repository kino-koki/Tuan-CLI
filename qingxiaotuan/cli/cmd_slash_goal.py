"""斜杠命令 /goal — Goal 模式。

拆分自 cmd_slash.py。

增强 (对标 Claude Code goal / Kimi Code Goal):
- 首次设置时自动拆解为 3~7 个子步骤;
- 每轮结束后自动验证步骤并续轮推进, 直到目标达成;
- 状态持久化到 <workspace>/.qxt/goal.json, 新会话可恢复;
- /goal status 查看步骤级进度, /goal clear 清除。
"""

from __future__ import annotations

import os

from ._ui_singleton import ui


def _build_engine(agent):
    """从 agent.workspace 构造 GoalEngine (注入可选配置)。"""
    from ..core.goal_mode import GoalEngine

    workspace = getattr(agent, "workspace", None) or os.getcwd()
    max_iter = 10
    auto_continue = True
    enabled = True
    # 配置项存在则覆盖 (config 由宿主在 agent 上挂 _config)
    cfg = getattr(agent, "_config", None)
    if cfg is not None:
        try:
            enabled = bool(cfg.get("goal.enabled", True))
            auto_continue = bool(cfg.get("goal.auto_continue", True))
            max_iter = int(cfg.get("goal.max_auto_iterations", 10) or 10)
        except Exception:  # noqa: BLE001
            pass
    return GoalEngine(workspace, max_auto_iterations=max_iter,
                      auto_continue=auto_continue, enabled=enabled)


def _show_status(agent) -> None:
    eng = _build_engine(agent)
    st = eng.status()
    if st:
        for line in eng.summary_lines():
            ui.info(line)
    elif agent._goal:
        ui.info(f"  当前 Goal: {agent._goal} (旧版文本模式, 无子步骤)")
        ui.info("  使用 /goal clear 可清除")
    else:
        ui.info("  未设置 Goal。用法: /goal <目标描述>")
        ui.info("  示例: /goal all tests pass and lint is clean")


def _cmd_goal(agent, arg: str) -> None:
    """/goal [目标描述|status|clear] — Goal 模式: 拆解执行直到目标满足。

    用法:
      /goal all tests pass and lint is clean   # 设置目标 (自动拆解子步骤)
      /goal                                     # 查看当前目标与步骤进度
      /goal status                              # 显式查看进度
      /goal clear                               # 清除目标
    """
    if not arg or arg.strip().lower() == "status":
        _show_status(agent)
        return

    if arg.strip().lower() in ("clear", "off", "stop", "cancel"):
        eng = _build_engine(agent)
        eng.clear()
        agent.clear_goal()
        ui.success("Goal 模式已关闭, 目标状态已清除。")
        return

    # 设置目标: 同时写入旧版 agent._goal (兼容既有检查闭环) 与增强引擎
    eng = _build_engine(agent)
    eng.set_goal(arg.strip())
    agent.set_goal(arg.strip())
    ui.success(f"Goal 已设置: {arg.strip()}")
    for line in eng.summary_lines():
        ui.info(line)
    ui.info("代理将在每轮结束后自动验证当前步骤并继续推进; /goal clear 可随时停止。")
