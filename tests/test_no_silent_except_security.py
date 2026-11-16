"""护栏: 核心安全/审计链模块禁止「静默吞异常」。

背景 (except Exception 治理第一轮): 安全/审计路径上的
``except Exception: pass`` 会让审计证据无声丢失 (审计链静默断链),
事后无法追溯。本测试用与 ``scripts/audit_except.py`` 同口径的 AST 分类,
锁定核心审计链 7 个模块: 这些模块里不允许再出现「无日志、无重抛」的
静默处理器; 新增例外必须先补日志或重抛, 再扩展本清单。

分类口径 (与 audit_except.py 一致):
  silent = 处理体无 raise、无日志调用, 且只由 pass/continue/return 常量构成。
"""
from __future__ import annotations

import ast
from pathlib import Path

# 核心审计链: 事件总线 / 落盘审计器 / 闸门 / 告警 / 导出 / 黑名单 / 命令护栏
GUARDED_MODULES = [
    "core/security_bus.py",
    "core/security_auditor.py",
    "core/security_alert.py",
    "core/blacklist_override.py",
    "core/command_guard.py",
    "ext/security_gate.py",
    "harden/audit_export.py",
    # ---- except 治理第二轮: 安全/审计路径其余模块 (含沙箱全链路) ----
    "tools/mcp/sandbox.py",
    "tools/mcp/audit.py",
    "tools/sandbox.py",
    "sandbox/backends.py",
    "sandbox/manager.py",
    "sandbox/filters.py",
    "sandbox/isolation.py",
    "core/sandbox_provider.py",
    "ext/sandbox.py",
    "ext/safety_normalize.py",
    "ext/safety_redline.py",
    "core/security_classifier.py",
    "core/security_utils.py",
    "core/security_policy.py",
    "core/workspace_trust.py",
    "core/security_plugin.py",
    "core/audit_correlation.py",
    "harden/crypto_provider.py",
    "config/security_schema.py",
    "cli/cmd_trust.py",
    # ---- except 治理第四轮: 其余全部模块 (web/cli/tui/tools/arch 等) ----
    "_http.py",
    "_openai_sdk.py",
    "agents/base.py",
    "arch/context.py",
    "arch/execution.py",
    "arch/orchestration.py",
    "arch/platform.py",
    "cli/__init__.py",
    "cli/cmd_acp.py",
    "cli/cmd_agents.py",
    "cli/cmd_agents_view.py",
    "cli/cmd_bang.py",
    "cli/cmd_chat.py",
    "cli/cmd_cost.py",
    "cli/cmd_diff.py",
    "cli/cmd_dispatch.py",
    "cli/cmd_doctor.py",
    "cli/cmd_help.py",
    "cli/cmd_hooks.py",
    "cli/cmd_kernel.py",
    "cli/cmd_loop.py",
    "cli/cmd_mcp_cli.py",
    "cli/cmd_obs.py",
    "cli/cmd_onboarding.py",
    "cli/cmd_remote.py",
    "cli/cmd_safe.py",
    "cli/cmd_session_export.py",
    "cli/cmd_setup.py",
    "cli/cmd_skills.py",
    "cli/cmd_slash.py",
    "cli/cmd_slash_claude.py",
    "cli/cmd_slash_goal.py",
    "cli/cmd_slash_image.py",
    "cli/cmd_slash_init.py",
    "cli/cmd_telemetry.py",
    "cli/cmd_webcache.py",
    "cli/parser.py",
    "cli/safe/bench_report.py",
    "cli/safe/observe_trend.py",
    "cli/safe/threat_scan.py",
    "cli/slash_tier.py",
    "cli/user_commands.py",
    "codedev/engine.py",
    "codedev/retrieval.py",
    "config/defaults.py",
    "config/loader.py",
    "config/managed.py",
    "cron/runner.py",
    "ecosystem/detect.py",
    "ecosystem/mcp_import.py",
    "ecosystem/mcp_server.py",
    "ecosystem/registry.py",
    "ext/diff_engine.py",
    "ext/index_engine.py",
    "ext/notify_engine.py",
    "ext/rules_engine.py",
    "ext/script_isolation.py",
    "ext/search_engine.py",
    "ext/write_scan.py",
    "gh/native.py",
    "harden/sbom.py",
    "hooks/lifecycle.py",
    "hooks/triggers.py",
    "kernel_patch/builtin.py",
    "kernel_patch/patch_base.py",
    "kernel_patch/plugin.py",
    "models/cache.py",
    "models/offline.py",
    "models/router.py",
    "modes/prompts.py",
    "modes/switcher.py",
    "parity_claude/depth.py",
    "parity_claude/matrix.py",
    "parity_claude/module_probes.py",
    "ports/kaos/shell_path_bridge.py",
    "ports/migration_legacy/stub_detect.py",
    "ports/oauth/identity.py",
    "ports/telemetry/otel.py",
    "ports/telemetry/sink.py",
    "self_improve/auto_distiller.py",
    "self_improve/plugin.py",
    "self_improve/regression_gate.py",
    "skills/enhanced.py",
    "skills/manager.py",
    "skills/plugin_sdk.py",
    "skills/universal_format.py",
    "stream_json/headless.py",
    "stream_json/translate.py",
    "superagent/engine.py",
    "superagent/events.py",
    "superagent/router.py",
    "superagent/watchdog.py",
    "superagent/worker.py",
    "tools/artifact_tool.py",
    "tools/base.py",
    "tools/browser.py",
    "tools/consolidate.py",
    "tools/external.py",
    "tools/filesystem.py",
    "tools/gh_borrow.py",
    "tools/image_gen.py",
    "tools/mcp/client.py",
    "tools/mcp/multitransport.py",
    "tools/mcp/plugin.py",
    "tools/mcp/policy.py",
    "tools/monitor_tool.py",
    "tools/permissions.py",
    "tools/session_tools.py",
    "tools/shell.py",
    "tools/subagent_tool.py",
    "tools/team_tool.py",
    "tools/todo_tool.py",
    "tools/web.py",
    "tools/workflow_tool.py",
    "tui/codexkit/__init__.py",
    "tui/codexkit/approval_history.py",
    "tui/codexkit/stream_exec.py",
    "tui/common.py",
    "tui/configkit/model_migration.py",
    "tui/interact.py",
    "tui/kimi_modules.py",
    "tui/layout.py",
    "tui/lifecycle.py",
    "tui/panels.py",
    "tui/parity/depth.py",
    "tui/render.py",
    "tui/runtime_slogans.py",
    "tui/slashmenu.py",
    "tui/state.py",
    "tui/tui.py",
    "tui/win_compat.py",
    "ui/approval_overlay.py",
    "ui/approval_policy.py",
    "ui/prefs.py",
    "ui/slogans/mapping.py",
    "ui/slogans/picker.py",
    "ui/splash.py",
    "ui/theme.py",
    "ui/tui_bridge.py",
    "web/_common.py",
    "web/code_anim_render.py",
    "web/dispatch_server.py",
    "web/handler.py",
    "web/mh_runner.py",
    "web/narration_tts.py",
    "web/server.py",
    "web/server_config.py",
    "web/server_ops.py",
    "web/server_runtime.py",
    "web/server_sessions.py",
    "tui/inputkit/copy_input_guard.py",
    # ---- except 治理第三轮: runtime/ 与 core/ 会话·事件·工具执行路径 ----
    "core/agent.py",
    "core/agent_helpers.py",
    "core/agent_loop_fusion.py",
    "core/agent_routing.py",
    "core/agent_turn.py",
    "core/background.py",
    "core/background_shell.py",
    "core/boundary_auto.py",
    "core/chat_handoff.py",
    "core/checkpoint_store.py",
    "core/collaboration_plugin.py",
    "core/collaboration_protocol.py",
    "core/cross_session.py",
    "core/dynamic_workflow.py",
    "core/engine_isolation.py",
    "core/event_sourcer.py",
    "core/file_integrity.py",
    "core/ipc_client.py",
    "core/json_schema.py",
    "core/ledger.py",
    "core/loop_provider.py",
    "core/message_bus.py",
    "core/messaging.py",
    "core/model_router.py",
    "core/network_check.py",
    "core/personality.py",
    "core/proc.py",
    "core/project_layer.py",
    "core/prompt_tier.py",
    "core/prompts.py",
    "core/remote_control.py",
    "core/resilience.py",
    "core/retry.py",
    "core/safe_text.py",
    "core/secret_scanner.py",
    "core/subagents.py",
    "core/swarm.py",
    "core/telemetry.py",
    "core/tool_executor.py",
    "core/trajectory_replay.py",
    "core/verify_loop.py",
    "core/worktree_layer.py",
    "core/write_boundary.py",
    "runtime/acp/bridge.py",
    "runtime/acp/server.py",
    "runtime/acp/session.py",
    "runtime/mcp/client_http.py",
    "runtime/mcp/client_sse.py",
    "runtime/mcp/client_stdio.py",
    "runtime/mcp/connection_manager.py",
    "runtime/mcp/tool.py",
    "runtime/provider_service.py",
    "runtime/providers/_http.py",
    "runtime/session/bridge.py",
    "runtime/tools/executor.py",
    "runtime/tools/permission.py",
    "runtime/tools/registry.py",
]

_LOG_ATTRS = {"debug", "info", "warning", "warn", "error", "exception",
              "critical", "log", "trace"}


def _is_log_call(node: ast.AST) -> bool:
    return (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr in _LOG_ATTRS)


def _is_silent(handler: ast.ExceptHandler) -> bool:
    has_log = False
    has_raise = False
    only_trivial = True
    for node in ast.walk(handler):
        if isinstance(node, ast.Raise):
            has_raise = True
        if _is_log_call(node):
            has_log = True
        if isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign, ast.For,
                             ast.While, ast.If, ast.With, ast.FunctionDef,
                             ast.AsyncFunctionDef, ast.ClassDef)):
            only_trivial = False
        if isinstance(node, ast.Return):
            if node.value is not None and not isinstance(
                    node.value, (ast.Constant, ast.Name, ast.List, ast.Tuple, ast.Dict)):
                only_trivial = False
        if isinstance(node, ast.Expr) and not isinstance(node.value, ast.Constant):
            only_trivial = False
    return not has_raise and not has_log and only_trivial


def _is_wide_except(handler: ast.ExceptHandler) -> bool:
    t = handler.type
    if t is None:
        return True
    return ast.unparse(t) in ("Exception", "BaseException")


def _silent_sites(src: str) -> list[tuple[int, str]]:
    sites: list[tuple[int, str]] = []
    for node in ast.walk(ast.parse(src)):
        if not isinstance(node, ast.Try):
            continue
        for h in node.handlers:
            if _is_wide_except(h) and _is_silent(h):
                snippet = ast.unparse(h)[:60]
                sites.append((h.lineno, snippet))
    return sites


def test_core_audit_chain_has_no_silent_except():
    """核心审计链模块不允许新增静默吞异常。"""
    root = Path(__file__).resolve().parents[1]
    offenders: list[str] = []
    for rel in GUARDED_MODULES:
        src = (root / "tuan_cli" / rel).read_text(encoding="utf-8")
        for ln, snippet in _silent_sites(src):
            offenders.append(f"tuan_cli/{rel}:{ln}: {snippet}")
    assert not offenders, (
        "核心审计链出现静默吞异常 (无日志/无重抛) —— 请补日志或重抛后再合入:\n"
        + "\n".join(offenders)
    )


def test_guarded_modules_exist():
    """清单里的模块必须真实存在, 防止路径改名后护栏空转。"""
    root = Path(__file__).resolve().parents[1]
    missing = [rel for rel in GUARDED_MODULES
               if not (root / "tuan_cli" / rel).exists()]
    assert not missing, f"护栏清单里的模块不存在: {missing}"
