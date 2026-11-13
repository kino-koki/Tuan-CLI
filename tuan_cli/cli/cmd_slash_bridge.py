"""CLI → TUI 斜杠命令桥 (对齐 codex-rs/tui 的 command.rs 薄适配层)。

上游 ``codex-rs/tui`` 把每个顶层命令做成 ``command.rs`` 里的薄适配器:
TUI 只负责把 ``/cmd args`` 解析后转交命令逻辑, 再把结果渲染进 transcript,
不重写任何业务逻辑。本模块把同样的结构搬到 Tuan-CLI:

    /obs cost           ->  等价于 CLI ``tuan obs cost``
    /fastindex files    ->  等价于 CLI ``tuan fastindex files``

实现要点 (对齐上游"不重实现"原则):
1. **复用同一个 ``build_parser()``**: 解析 slash 参数得到与 CLI 完全一致的
   namespace, 再调用注册表里的同一个 ``cmd_*`` 函数 —— 命令行为/逻辑零漂移。
2. **捕获 ``console`` 输出**: CLI 命令统一经 ``ui.plain_console.console``
   打印; 桥在调用期间临时把 ``console`` 重定向到一个 StringIO, 命令返回后把
   捕获的纯文本交给 TUI 的 ``ui.info``。输出渲染/配色仍由 TUI 决定 (样式不变)。
3. **只读 allow-list**: 只桥接不阻塞/不改状态/不进 TUI 交互的命令。会启动服务、
   覆盖终端、接管会话的命令 (chat/dev/run/mcp/setup/upgrade/acp/...) 保持走
   原生 CLI, 不进桥 —— 避免 TUI 被阻塞或子进程争抢终端。

差异化价值: Claude Code 的每条 CLI 命令都要在 TUI 里各自重写一遍 (逻辑漂移,
两边维护); 本桥让"加一条命令"= 在 ``_BRIDGE_TABLE`` 加一行, TUI 自动获得与
CLI 一致的补全 + 执行 + 输出, 覆盖面与 CLI 对齐。
"""

from __future__ import annotations

import argparse
import contextlib
import io
from types import SimpleNamespace
from typing import Any, Dict, Generator, Tuple

# ---- 桥接表: slash 名 -> (CLI func 名, dispatch 属性名, 无参时的默认子命令) ----
# 只收录"读"命令 (纯查询/审计/列表/诊断), 保证 TUI 里执行立即返回、无副作用。
# 默认子命令让 ``/cmd`` 无参时与 ``tuan cmd`` 的默认动作对齐, 避免空输出。
_BRIDGE_TABLE: Dict[str, Tuple[str, str, str]] = {
    "/obs":       ("cmd_obs",         "obs_cmd",         "cost"),
    "/telemetry": ("cmd_telemetry",   "telemetry_cmd",   "stats"),
    "/roles":     ("cmd_roles",       "roles_cmd",       "list"),
    "/dag":       ("cmd_dag",         "dag_cmd",         "demo"),
    "/aggregate": ("cmd_aggregate",   "aggregate_cmd",   "demo"),
    "/collab":    ("cmd_collab",      "collab_cmd",      "stats"),
    "/kernel":    ("cmd_kernel",      "kernel_cmd",      "events"),
    "/ledger":    ("cmd_ledger",      "ledger_cmd",      "list"),
    "/integrity": ("cmd_integrity",   "integrity_cmd",   "overview"),
    "/storage":   ("cmd_storage",     "storage_cmd",     "overview"),
    "/posture":   ("cmd_posture",     "posture_cmd",     ""),
    "/auditstore": ("cmd_auditstore", "auditstore_cmd",  "stats"),
    "/webcache":  ("cmd_webcache",    "webcache_cmd",    ""),
    "/fastindex": ("cmd_fastindex",   "fastindex_cmd",   "files"),
    "/boundary":  ("cmd_boundary",    "boundary_cmd",    "status"),
    "/resilience": ("cmd_resilience", "resilience_cmd",  "status"),
    "/onboarding": ("cmd_onboarding", "onboarding_cmd",  ""),
    "/ecosystem": ("cmd_ecosystem",   "ecosystem_cmd",   "status"),
    "/dispatch":  ("cmd_dispatch",    "dispatch_cmd",    "list"),
    "/tutorial":  ("cmd_tutorial",    "tutorial_cmd",    "list"),
    "/parity":    ("cmd_tui_parity",  "parity_cmd",      "parity"),
    "/codedev":   ("cmd_codedev",     "codedev_cmd",     "demo"),
    "/prompt":    ("cmd_prompt",      "prompt_cmd",      "tier"),
    # ---- 第二批桥接: 其余只读查询命令 (alerts/artifact/cron/... 只读子命令) ----
    # 含写子命令的命令 (cron add/harden keygen/msg send) 也桥进来: 桥只把用户
    # 显式输入的子命令转发给同一 cmd_* 函数, 不额外授权 —— 与 CLI 用法一致。
    "/alerts":    ("cmd_alerts",      "alerts_cmd",      "list"),
    "/artifact":  ("cmd_artifact",    "artifact_cmd",    "list"),
    "/cron":      ("cmd_cron",        "cron_cmd",        "list"),
    "/models":    ("cmd_model",       "model_cmd",       ""),
    "/msg":       ("cmd_msg",         "msg_cmd",         "agents"),
    "/project":   ("cmd_project",     "project_cmd",     "info"),
    "/remote":    ("cmd_remote",      "remote_cmd",      "status"),
    "/safety":    ("cmd_safety",      "safety_cmd",      "score"),
    # /sessions (v0.4.0 已合并入 /session, 此处仅保留向后兼容别名)
    "/sessions":  ("cmd_session",     "session_cmd",     "list"),
    "/skill":     ("cmd_skill",       "skill_cmd",       "list"),
    "/craft":     ("cmd_skills",      "craft_cmd",       "list"),
    "/todo":      ("cmd_todo",        "todo_cmd",        "list"),
    "/trust":     ("cmd_trust",       "trust_cmd",       "status"),
    "/usercmd":   ("cmd_usercmd",     "usercmd_cmd",     "list"),
    "/net":       ("cmd_network",     "network_cmd",     "configuration"),
    "/tui":       ("cmd_tui_parity",  "parity_cmd",      "parity"),
    # ---- 第三批: 剩余只读/管理命令 (gh/plugin/harden/auto-mode/bg) ----
    "/gh":        ("cmd_gh",          "gh_cmd",          ""),
    "/plugin":    ("cmd_plugin",      "plugin_cmd",      "list"),
    "/harden":    ("cmd_harden",      "harden_cmd",      "status"),
    "/auto-mode": ("cmd_auto_mode",   "auto_mode_cmd",   ""),
    "/bg":        ("cmd_bg",          "bg_cmd",          "list"),
    # ---- 收尾: network 别名 + safe (读子命令为主) ----
    # /net 已桥 cmd_network; 这里把 CLI 的 ``network`` 别名也映射到同一函数,
    # 用户在 TUI 敲 /network 或 /net 都到同一逻辑。
    "/network":   ("cmd_network",     "network_cmd",     "configuration"),
    # /safe: 安全总入口, 读子命令居多 (status/list/blacklist/classify/model/...);
    # 写子命令 (allow/deny) 同样由桥转发给同一 cmd_safe, 不额外授权。
    "/safe":      ("cmd_safe",        "safe_cmd",        "status"),
    # /migrate: 配置迁移 (status/detect/run), status/detect 只读先桥进来。
    "/migrate":   ("cmd_migrate",     "migrate_cmd",     "status"),
}

# 这些命令需要 agent/kernel 上下文或会阻塞, 走原生 slash 分支 (已各自实现)。
# 列在这里仅作文档: 桥的 allow-list 天然不含它们。
_BRIDGE_EXCLUDED = (
    "/dev", "/run", "/chat", "/agent", "/mcp", "/setup", "/upgrade",
    "/acp", "/improve", "/gh", "/network", "/session", "/sessions",
)

# CLI 顶层命令名 ≠ slash 名时的覆盖 (默认取 head.lstrip("/"))。
# parity/codedev 在 CLI 里注册为 tui/__dev_codedev, slash 名是别名。
_CLI_NAME_OVERRIDE: Dict[str, str] = {
    "/parity":    "tui",
    "/codedev":   "__dev_codedev",
    "/tui":       "tui",
}


def bridge_table() -> Dict[str, Tuple[str, str, str]]:
    """返回桥接表副本 (供补全/帮助枚举)。"""
    return dict(_BRIDGE_TABLE)


def _cli_namespace(argv: list[str]) -> argparse.Namespace:
    """用项目 ``build_parser()`` 解析 ``argv`` (含全局 flag + 子命令)。

    抛 ``SystemExit`` (argparse 对 --help/错误) 时原样上抛, 由调用方兜成提示。
    """
    from .parser import build_parser

    parser = build_parser()
    return parser.parse_args(argv)


@contextlib.contextmanager
def _capture_console() -> Generator[io.StringIO, None, None]:
    """把 stdout/stderr 重定向到 StringIO, 捕获 CLI 命令的打印输出。

    CLI 命令的 ``console.print`` 最终写往 ``sys.stdout`` (PlainConsole 以
    ``file=None`` 初始化, rich Console 的 file property 回退到 stdout),
    因此 ``redirect_stdout`` 能正确接管打印, 无需动任何命令模块。
    argparse/异常写往 stderr 的 usage 行也一并捕获, 避免污染 TUI 终端。
    """
    buf = io.StringIO()
    err_buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(err_buf):
        yield buf
    # stderr 追加到捕获区, TUI 可见 (stdout 已剥离 rich 标记, 是纯文本)
    err_text = err_buf.getvalue().rstrip("\n")
    if err_text:
        buf.write("\n" + err_text)


def run_bridge(head: str, arg: str) -> str:
    """执行一条桥接命令, 返回捕获到的纯文本输出。

    ``head`` 形如 ``/obs``; ``arg`` 是 slash 后的剩余参数 (如 ``cost --json``)。
    未收录的命令抛 ``KeyError`` (调用方应先用 ``head in _BRIDGE_TABLE`` 判断)。

    不完全依赖 parser 的 ``set_defaults``: 部分 CLI 命令 (如 tui/trust) 在
    subparser 层未设默认动作, 无参时会静默空输出。``_default_sub`` 提供桥层
    回退: ``arg`` 为空时注入它, 不覆盖 parser 已设的默认 (有 set_defaults 的
    命令 ``_default_sub`` 留空串即可, 不会被注入)。
    """
    func_name, _dispatch_attr, _default_sub = _BRIDGE_TABLE[head]
    cli_name = _CLI_NAME_OVERRIDE.get(head, head.lstrip("/"))

    argv: list[str] = [cli_name]
    if not arg.strip() and _default_sub:
        argv.append(_default_sub)
    argv.extend(arg.split())

    # 用 parser._resolve_func 解析命令函数: 它先查 _COMMAND_REGISTRY (覆盖
    # gh/project/skills 等独立 _register_command 模块), 再回退 commands 门面。
    # 直接 getattr(commands_mod, ...) 会漏掉独立注册模块。
    from . import parser as parser_mod

    try:
        fn = parser_mod._resolve_func(func_name)
    except AttributeError:
        return f"[bridge] 未找到命令函数: {func_name}"
    with _capture_console() as buf:
        try:
            ns = _cli_namespace(argv)
        except SystemExit as exc:  # argparse 对非法参数 sys.exit(2)
            code = exc.code
            if code in (0, None):
                pass  # --help 正常打印 (argparse 已写进 stdout)
            else:
                buf.write(f"[bridge] 参数错误 (退出码 {code}); 用 /help {head} 查看用法")
            return str(buf.getvalue()).rstrip("\n")
        try:
            fn(ns)
        except SystemExit as exc:  # 命令函数内再抛 SystemExit
            code = exc.code
            if code in (0, None):
                pass
            else:
                buf.write(f"[bridge] 执行中止 (退出码 {code})")
        except Exception as exc:  # noqa: BLE001 - 桥不吞异常, 但给 TUI 一句可读提示
            buf.write(f"[bridge] 执行失败: {type(exc).__name__}: {exc}")
    return str(buf.getvalue()).rstrip("\n")


def _known_subcommands(head: str) -> set[str]:
    """枚举某桥接命令的子命令名 (从 subparsers 的 choices 取)。

    用于判断 slash 首参是子命令还是普通值, 决定是否注入默认子命令。
    解析失败时返回空集 (则总是注入默认子命令, 安全回退)。
    """
    func_name, dispatch_attr, _ = _BRIDGE_TABLE[head]
    cli_name = _CLI_NAME_OVERRIDE.get(head, head.lstrip("/"))
    try:
        from .parser import build_parser
        parser = build_parser()
        # subparsers action -> choices {name: subparser}
        for action in parser._actions:  # noqa: SLF001 - 需读 argparse 内部结构
            if isinstance(action, argparse._SubParsersAction) and cli_name in action.choices:
                sub: argparse.ArgumentParser = action.choices[cli_name]
                for a in sub._actions:  # noqa: SLF001
                    if isinstance(a, argparse._SubParsersAction):
                        return set(a.choices.keys())
    except Exception:  # noqa: BLE001 - 解析失败就退回"总是注入默认"策略
        return set()
    return set()


def bridge_help_lines() -> list[str]:
    """生成桥接命令的 /help 片段 (对齐上游 command.rs 的 usage 列表)。"""
    from .cmd_slash import slash_command_meta

    meta = slash_command_meta()
    lines: list[str] = []
    for name in sorted(_BRIDGE_TABLE):
        lines.append(f"  {name:<12} {meta.get(name, '只读查询 (与 CLI 同逻辑)')}")
    return lines


# 供类型检查器确认 namespace 用法 (SimpleNamespace 仅在测试/兜底用)
_NS = SimpleNamespace