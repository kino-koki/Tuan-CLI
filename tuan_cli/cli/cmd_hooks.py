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
                      "(事件: PreToolUse / PostToolUse / SessionStart / SessionEnd)。")
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
    # B3: 决策类扩展事件统一走 run_decision；有工具 schema 时传给改参校验。
    schema = _lookup_tool_schema(kernel, tool)
    if event == "PreToolUse":
        d = mgr.run_pre(tool, payload, dangerous=True, tool_schema=schema)
        console.print(f"  block={d.block}  reason={d.reason!r}  args={d.args!r}")
        _print_validation_notes(d)
    elif event == "PostToolUse":
        mgr.run_post(tool, payload, None)
        console.print("  PostToolUse 已触发 (见 hook 脚本输出/审计事件)。")
    elif event in ("PermissionRequest", "WorktreeCreate",
                   "Elicitation", "ElicitationResult"):
        # 决策类扩展事件（可 block），stdout 解析失败 fail-closed
        mgr.run_decision(event, tool_name=tool, payload=payload)
        console.print(f"  {event} 已走 run_decision (见 hook 脚本输出/审计事件)。")
    else:
        mgr.run_notify(event, {"tool": tool, **payload})
        console.print(f"  {event} 已触发 (通知类, stdout 忽略)。")
    return 0


def _lookup_tool_schema(kernel: Any, tool_name: str) -> dict | None:
    """从内核 registry 取工具 schema (仅用于 run_pre 改参校验, 失败降级 None)。"""
    try:
        registry = kernel.get("tool_registry")
        tool = registry.get(tool_name) if registry is not None else None
        params = getattr(tool, "parameters", None)
        return params if isinstance(params, dict) else None
    except Exception:
        return None


def _print_validation_notes(d: Any) -> None:
    """把 run_pre 的改参校验结果落到 console (enforced / 保守子集)。"""
    if getattr(d, "args", None):
        console.print("  [改参] 已按工具 schema 校验；无 schema 时退化为保守子集 (enforced=False)，不声称通过校验。")


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
