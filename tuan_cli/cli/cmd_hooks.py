"""`tuan hooks` 与 `/hooks` —— 用户级 Hooks 管理 (拆分自 cmd_services.py)。"""

from __future__ import annotations
from typing import Any

from ..paths import default_workspace

import json
import os

from ..hooks import HookManager, HOOK_EVENTS
from ._ui_singleton import console, ui


def build_kernel(*a: Any, **k: Any) -> Any:
    """惰性构建内核: 仅实际执行 hooks 命令时才加载 app 链。"""
    from ..app import build_kernel as _f
    return _f(*a, **k)


def cmd_hooks(args: Any) -> int:
    """用户级 Hooks 管理: 列出 / 测试 / 启用 / 禁用。"""
    sub = getattr(args, "hook_cmd", None)
    workspace = getattr(args, "workspace", None) or default_workspace()
    if sub == "list":
        return _hooks_list(workspace)
    if sub == "test":
        return _hooks_test(workspace, args)
    if sub == "enable":
        return _hooks_set_enabled(True)
    if sub == "disable":
        return _hooks_set_enabled(False)
    console.print("未知子命令。可用: list / test / enable / disable")
    return 1


def _hooks_set_enabled(enabled: bool) -> int:
    """全局启用/禁用 Hooks (写入用户层 config.yaml 的 hooks.enabled)。

    禁用后所有事件 (Pre/Post/Session/...) 立即
    静默不执行, 无需逐条删配置。写入用户层配置, 重启会话后依然生效。
    """
    from ..config import Config

    try:
        config = Config()
    except Exception as exc:  # noqa: BLE001
        console.print(f"读取配置失败: {exc}")
        return 1
    config.set_user("hooks.enabled", enabled)
    state = "已启用" if enabled else "已禁用"
    console.print(f"Hooks 全局{state} (hooks.enabled={str(enabled).lower()})。"
                  f"下次构建内核的会话即生效。")
    return 0


def _hooks_list(workspace: str) -> int:
    try:
        kernel = build_kernel()
        config = kernel.require("config")
    except Exception as exc:
        console.print(f"启动失败: {exc}")
        return 1
    mgr = HookManager(config, workspace, kernel=kernel)
    if not mgr.enabled or not mgr.list_hooks():
        console.print("未配置任何 Hooks。在配置中 hooks.<事件> 下添加命令即可 "
                      f"(共 {len(HOOK_EVENTS)} 个事件: "
                      "8 个核心 + 7 个扩展；`tuan hooks list` 列出全部)。")
        return 0
    for evt in HOOK_EVENTS:
        specs = [h for h in mgr.list_hooks() if h["event"] == evt]
        if not specs:
            continue
        console.print(f"{evt}")
        for h in specs:
            flag = "阻断" if (h["blocking"] and mgr.allow_blocking) else "审计"
            edit = "可改参" if (h["allow_edit_args"] or mgr.allow_edit_args) else "只读"
            console.print(f"  matcher={h['matcher']!r}  {flag}/{edit}  cmd={' '.join(h['command'])}")
            if h["description"]:
                console.print(f"    {h['description']}")
    return 0


def _hooks_test(workspace: str, args: Any) -> int:
    event = getattr(args, "event", None) or "PreToolUse"
    tool = getattr(args, "tool", None) or "echo_text"
    raw = getattr(args, "tool_input", None) or "{}"
    try:
        payload = json.loads(raw)
    except Exception as exc:
        console.print(f"--json 不是合法 JSON: {exc}")
        return 1
    try:
        kernel = build_kernel()
        config = kernel.require("config")
    except Exception as exc:
        console.print(f"启动失败: {exc}")
        return 1
    mgr = HookManager(config, workspace, kernel=kernel)
    if not mgr.enabled_for(event):
        console.print(f"事件 {event} 未配置任何 hook。")
        return 0
    console.print(f"触发 {event} (tool={tool}) ...")
    if event == "PreToolUse":
        # B3 续轮: 从工具注册表拿 schema，让手动测试入口也走严格
        # updatedInput 校验。取不到时如实打印「保守子集」而不是假装
        # 已通过 schema 校验。
        schema = None
        try:
            reg = kernel.get("tool_registry") or kernel.require("tools")
            getter = getattr(reg, "get", None)
            obj = getter(tool) if getter else None
            schema = getattr(obj, "parameters", None)
        except Exception:  # noqa: BLE001
            schema = None
        d = mgr.run_pre(tool, payload, dangerous=True, tool_schema=schema)
        console.print(f"  block={d.block}  reason={d.reason!r}  args={d.args!r}")
        console.print(f"  updatedInput 校验: {'schema' if schema else '无 schema → 保守子集 (enforced=False)'}")
    elif event == "PostToolUse":
        mgr.run_post(tool, payload, None)
        console.print("  PostToolUse 已触发 (见 hook 脚本输出/审计事件)。")
    elif event in ("PermissionRequest", "WorktreeCreate", "Elicitation",
                   "ElicitationResult"):
        # B3 续轮 R: 旧实现把一切都塞给 run_session → run_notify，
        # 决策类事件会被 `decision_event_misrouted` 拒绝并静默不执行。
        # 现在走真正的裁决出口。
        d = mgr.run_decision(event, tool_name=tool,
                             payload={"tool": tool, **payload})
        console.print(f"  block={d.block}  reason={d.reason!r}  "
                      f"failure_kind={d.failure_kind!r}")
    else:
        mgr.run_notify(event, {"tool": tool, **payload})
        console.print(f"  {event} 已触发。")
    return 0


def _cmd_hooks(agent: Any, arg: str) -> None:
    """/hooks: 列出当前会话生效的 Hooks。"""
    hooks = getattr(getattr(agent, "ctx", None), "hooks", None)
    if hooks is None or not hooks.enabled:
        ui.info("未启用 Hooks。配置中设置 hooks.enabled=true 并添加 hooks.<事件>。")
        return
    specs = hooks.list_hooks()
    if not specs:
        ui.info("已启用 Hooks, 但当前未配置任何规则。")
        return
    for evt in HOOK_EVENTS:
        rows = [h for h in specs if h["event"] == evt]
        if not rows:
            continue
        ui.info(f"  {evt}:")
        for h in rows:
            flag = "阻断" if (h["blocking"] and hooks.allow_blocking) else "审计"
            edit = "可改参" if (h["allow_edit_args"] or hooks.allow_edit_args) else "只读"
            ui.info(f"    matcher={h['matcher']}  [{flag}/{edit}]  {' '.join(h['command'])}")
