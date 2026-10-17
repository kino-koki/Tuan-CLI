"""tuan CLI argument parser and entry point.

Quick start: tuan | tuan --yolo | tuan --plan | tuan --isolation
Subcommands: dev | run | agent | setup | doctor | models | config |
  plugin | skill | memory | cron | improve | tutorial | session |
  undo | migrate | network | worktree | safe | ext | gh | sandbox
"""

from __future__ import annotations

import argparse
import importlib
import logging
import sys

from .. import __version__
from .parser_commands import register_subcommands


# ---------------------------------------------------------------------------
# 命令注册表 (Command Registry)
#
# 每个命令模块在导入时通过 _register_command() 注册自己。
# _resolve_func 从注册表查找，避免 if-elif 链随子命令增长。
#
# 规范:
# - 命令名 (如 "cmd_ext") 必须与模块内导出的函数名一致。
# - 隐藏命令 (如 "__dev_codedev") 通过 "hidden:" 前缀标记。
# - 注册失败会抛出 AssertionError，确保"漏注册=错误"。
# ---------------------------------------------------------------------------

_COMMAND_REGISTRY: dict[str, str] = {}  # name -> module_path


def _register_command(name: str, module_path: str) -> None:
    """注册一个命令到全局注册表。

    Args:
        name: 命令函数名 (如 "cmd_ext")。
        module_path: 模块相对路径 (如 ".ext_cli")。

    Raises:
        AssertionError: 若 name 已被注册或路径不合法，确保"漏注册=错误"。
    """
    if name in _COMMAND_REGISTRY:
        raise AssertionError(
            f"命令 '{name}' 已被注册到 {_COMMAND_REGISTRY[name]}, "
            "重复注册会导致歧义。请检查模块是否多次注册。"
        )
    _COMMAND_REGISTRY[name] = module_path


def _resolve_func(name: str):
    """从注册表延迟导入命令函数: 轻量命令 (--version/--help) 不加载 app 链。

    使用注册表后，新增子命令只需在对应模块顶部调用 _register_command，
    无需修改本函数，避免 UnboundLocalError 风险。

    对于 commands.py 的惰性路由命令，先检查全局注册表，未找到时从
    commands.py 惰性加载（保持向后兼容）。
    """
    # 1. 先检查全局注册表
    module_path = _COMMAND_REGISTRY.get(name)
    if module_path is None:
        # 2. 对于 commands.py 的惰性路由命令，尝试从 commands.py 加载
        # commands.py 使用 PEP 562 惰性路由，未导入时不会注册
        # 这里我们手动触发导入，让它通过 __getattr__ 返回函数
        if name.startswith("cmd_") or name.startswith("_cmd_"):
            try:
                from . import commands
                func = getattr(commands, name)
                # 成功获取，返回
                return func
            except (ImportError, AttributeError):
                pass

        # 3. 都没找到，抛出友好错误
        available = sorted(set(_COMMAND_REGISTRY.keys()))
        raise AttributeError(
            f"module {__name__!r} has no attribute {name!r}\n"
            f"可能的命令名: {available}"
        )

    # 4. 从注册表加载
    mod = importlib.import_module(module_path, __package__)
    return getattr(mod, name)


# ---------------------------------------------------------------------------
# 自动注册钩子: 模块导入时自动注册自己
# ---------------------------------------------------------------------------

def _auto_register() -> None:
    """在模块加载时自动注册所有命令函数。

    通过导入所有 CLI 模块，触发每个模块内的 _register_command 调用。
    新增子命令只需在对应模块顶部添加 _register_command 调用，
    无需修改本函数，避免 UnboundLocalError 风险。
    """
    # 按功能分组导入 CLI 模块
    importlib.import_module(".ext_cli", __package__)
    importlib.import_module(".improve_cli", __package__)
    importlib.import_module(".cmd_gh", __package__)
    importlib.import_module(".cmd_acp", __package__)
    importlib.import_module(".cmd_safe", __package__)
    importlib.import_module(".cmd_harden", __package__)
    importlib.import_module(".cmd_migrate", __package__)
    importlib.import_module(".cmd_network", __package__)
    importlib.import_module(".cmd_rewind", __package__)
    importlib.import_module(".cmd_project", __package__)
    importlib.import_module(".cmd_worktree", __package__)
    importlib.import_module(".cmd_handoff", __package__)
    importlib.import_module(".cmd_help", __package__)
    # 导入 commands.py，它会通过 PEP 562 惰性路由注册所有命令
    importlib.import_module(".commands", __package__)
    # 注意: commands.py 内的 _CMD_SOURCES 已经覆盖所有已注册 func
    # 无需手动导入 cmd_run / cmd_chat / cmd_dev / cmd_config 等。


# 模块加载时自动注册
_auto_register()


# ---------------------------------------------------------------------------
# 后备注册表 (用于调试/测试，避免"未注册=错误"在生产环境崩溃)
# ---------------------------------------------------------------------------

def _get_all_registered_commands() -> list[str]:
    """获取所有已注册的命令名（调试用）。"""
    return sorted(_COMMAND_REGISTRY.keys())


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tuan", description="青小团 CLI - 会成长的插件化 Agent"
    )
    parser.add_argument("--version", action="version", version=f"tuan {__version__}")
    parser.add_argument(
        "--profile",
        default="default",
        help="使用指定 profile (~/.tuan/profiles/<name>)",
    )
    parser.add_argument("--patch", help="一次性配置覆盖文件 (dsh 风格, 整值替换)")
    parser.add_argument("--workspace", help="工作区目录 (默认当前目录)")
    parser.add_argument("--model", help="临时覆盖模型名 (如 deepseek-v4-free)")
    parser.add_argument(
        "--effort",
        choices=["low", "medium", "high", "xhigh", "max"],
        help="推理投入级别 (low/medium/high/xhigh/max)",
    )
    parser.add_argument(
        "--allowed-tools",
        dest="allowed_tools",
        help="免确认工具/作用域: 如 'Bash(npm test),Read,Write' (命中者不提示)",
    )
    parser.add_argument(
        "--tools",
        dest="tools",
        choices=["minimal", "standard", "full", "auto"],
        help="工具暴露档位 (控制发给模型的工具数量): "
             "minimal=仅核心闭环 / standard=核心+常用(默认) / full=全量 87 个 / "
             "auto=按模型能力自动。长尾工具仍可经 tool_search 检索调用。",
    )
    parser.add_argument(
        "--mode",
        choices=["standard", "yolo", "plan"],
        help="运行模式: standard(默认,需确认) / yolo(自动批准) / plan(只读规划)",
    )
    parser.add_argument(
        "--permission-mode",
        choices=[
            "default",
            "acceptEdits",
            "plan",
            "auto",
            "dontAsk",
            "bypassPermissions",
        ],
        dest="permission_mode",
        help="权限模式 (映射: dontAsk/bypassPermissions→yolo, plan→plan, 其余→standard)",
    )
    parser.add_argument(
        "--fallback-model",
        help="主模型不可用时的备用模型",
    )
    parser.add_argument(
        "--yolo",
        action="store_true",
        help="无限制模式: 危险操作自动批准 (等同于 --mode yolo)",
    )
    parser.add_argument(
        "--plan",
        action="store_true",
        help="Plan 模式: 窗口 Agent 只读, 不修改任何文件 (等同于 --mode plan)",
    )
    parser.add_argument(
        "--bare",
        action="store_true",
        help="CI/纯净模式: 仅用内置默认配置+内置工具, 跳过用户配置/skills自动加载/hooks/MCP/memory自动注入, 保证评测可复现",
    )
    parser.add_argument(
        "--isolation",
        action="store_true",
        help="引擎进程级隔离: 开启后非判定类引擎(diff/crypto/index/ansi/json/search/notify/rules)以真实 JSONL 子进程运行, 子进程崩溃/超时安全回落进程内; safety 引擎恒进程内(fail-closed)。默认关(进程内直调)。持久开启用 `tuan config set engine.isolation true`",
    )
    parser.add_argument(
        "--print",
        action="store_true",
        dest="print_mode",
        help="非交互输出模式: 跑完任务直接输出结果到 stdout, 不进 REPL (可管道化)",
    )
    parser.add_argument(
        "--json-schema",
        dest="json_schema",
        default=None,
        metavar="SPEC",
        help="结构化输出: 要求最终回答符合给定 JSON Schema (内联 JSON 或 @file.json), "
        "输出通过校验的 JSON; 并提供 --json-schema-strict/--json-schema-retries",
    )
    parser.add_argument(
        "--json-schema-strict",
        dest="json_schema_strict",
        action="store_true",
        help="--json-schema 严格模式: 回答必须仅含合法 JSON, 不含多余文字",
    )
    parser.add_argument(
        "--json-schema-retries",
        dest="json_schema_retries",
        type=int,
        default=3,
        help="--json-schema 校验失败时的自动修复重试次数 (默认 3)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help="详细输出级别: -v=工具调用与计时, -vv=系统提示与完整请求, -vvv=原始 API 与完整 token",
    )
    parser.add_argument(
        "--max-cost",
        type=float,
        default=0.0,
        help="单次会话最大花费上限 (USD), 超过自动停止; 0=不限制",
    )
    sub = parser.add_subparsers(dest="cmd")
    register_subcommands(sub)

    return parser


# ---------------------------------------------------------------------------
# 青小团 TUI —— 纯 Python 实现 (开箱即用, 不依赖 Node)
# ---------------------------------------------------------------------------
# tuan / tuan --plan / tuan --yolo 等交互式启动形态直接走内置 Python TUI:
#   tuan_cli/tui/tui.py::QxtTUI  (cmd_chat.fast_chat -> QxtTUI)
#   - 渲染/皮肤: 青小团自己的 Mascot (▐█▛█▛█▌ block art logo) + prompt_toolkit 主题;
#   - 底层:      build_kernel() + create_agent() + Agent.run() (青小团自己的 agent);
#   - 依赖:      仅 rich + prompt_toolkit (已随 tuan 安装), 无需 Node / 无需构建步骤。
# 历史上曾尝试复用 kimi 的 TS TUI (kimi-code-main/apps/tuan_cli-tui), 但那会
# 强依赖 Node 工具链 (tsdown + Node>=24.15 + 构建), 违背「开箱即用」, 故已移除该
# 启动路径, 仅保留下方纯 Python TUI。不再有任何 Node 进程被 tuan 拉起。


def _rewrite_dev_codedev(argv):
    """把 `dev codedev <rest>` 透明改写为 `__dev_codedev <rest>`。

    ``dev`` 的 task 是自由文本位置参数, 无法在其 ArgumentParser 上直接挂
    subparsers (否则任意任务首词会被 argparse 当作未知子命令而报 invalid choice)。
    codedev 子命令组因此由隐藏顶层解析器 ``__dev_codedev`` 承载; 仅在 main() 入口
    对 argv 做这一次无感知改写, 用户侧仍是 `tuan dev codedev demo|doctor|...`。
    """
    if len(argv) >= 2 and argv[0] == "dev" and argv[1] == "codedev":
        return ["__dev_codedev", *argv[2:]]
    return argv


def main() -> int:
    # 先把 ~/.tuan/.env 里的密钥加载进环境 (所有子命令共用)
    from ..config import load_dotenv

    load_dotenv()
    parser = build_parser()
    sys.argv[1:] = _rewrite_dev_codedev(sys.argv[1:])
    args = parser.parse_args()
    # 交互式/计划/免确认启动形态 (无子命令且非 --print) 直接走内置 Python TUI
    # (tuan_cli/tui/tui.py::QxtTUI, 仅依赖 rich + prompt_toolkit, 开箱即用,
    # 不依赖 Node / 任何 kimi 代码)。下方 fast_chat() 会接管终端。

    # -v 详细输出: 配置对应级别的日志 (concise 模式下 REPL 不显示但调试可用)
    verbose = getattr(args, "verbose", 0)
    if verbose >= 3:
        logging.getLogger().setLevel(logging.DEBUG)
    elif verbose >= 2:
        logging.getLogger().setLevel(logging.INFO)
    elif verbose >= 1:
        logging.getLogger("tuan_cli").setLevel(logging.DEBUG)
    # --print 模式: 非交互输出, stdin 不是 TTY 时不再报错退出
    is_print = getattr(args, "print_mode", False)
    # 引擎进程级隔离: --isolation 强制开启当前进程 (默认跟随配置, 配置默认关)。
    # 路由由 core/engine_isolation.EngineIsolation 负责, safety 引擎恒进程内。
    if getattr(args, "isolation", False):
        from ..core.engine_isolation import set_isolation, EngineIsolation

        set_isolation(EngineIsolation(isolation_enabled=True))
    # `tuan -v` / `tuan --verbose` (无子命令): 本意多为查版本/详细模式用法,
    # 直接启动全屏 TUI 是意外行为 (曾把 -v 当成普通交互启动)。改为打印
    # 版本 + 详细模式用法提示并退出, 不进入交互。此判断必须先于 TTY 检查,
    # 否则 tuan -v 在非 TTY 下会先命中"交互模式需要终端"而报错。
    if (
        verbose
        and not getattr(args, "cmd", None)
        and not is_print
        and not getattr(args, "yolo", False)
        and not getattr(args, "plan", False)
        and not getattr(args, "mode", None)
    ):
        from .. import __version__

        print(f"tuan {__version__}")
        print("-v/--verbose 是详细日志开关, 需搭配子命令使用, 例如:")
        print('    tuan run -v "你的任务"   跑任务并显示详细日志')
        print("    tuan dev -v <任务>    开发循环并显示详细日志")
        print("    tuan setup -v         配置向导并显示详细日志")
        print("查版本号请用: tuan --version")
        return 0
    _interactive_cmds = {None, "dev"}
    if (
        not is_print
        and getattr(args, "cmd", None) in _interactive_cmds
        and not sys.stdin.isatty()
    ):
        sys.stderr.write(
            "\n[青小团] 交互模式需要真实终端 (TTY)。\n"
            "  当前 stdin 不是终端, 无法显示输入框。\n"
            "  请在系统自带的终端里运行 (不要在本软件/IDE 的内嵌命令行里跑):\n"
            "    - Windows: 打开『命令提示符』或『Windows Terminal』, 输入 tuan\n"
            "    - 或在该终端里先 cd 到项目目录, 再 .venv\\Scripts\\Activate.ps1 后 tuan\n"
            '  非交互任务可用: tuan run "你的任务" (headless, 跑完退出)\n'
            '  管道输出可用: tuan --print chat "你的任务" (直接输出到 stdout)\n\n'
        )
        return 2
    # tuan help [<子命令>]: 只读打印帮助, 不进入交互、不写配置 (与 `tuan --help` / `tuan <子命令> --help` 等效)
    if getattr(args, "cmd", None) == "help":
        topic = getattr(args, "topic", None)
        if not topic:
            parser.print_help()
            return 0
        # 复用 argparse 公共能力: `tuan <topic> --help` 会打印该子命令帮助并退出。
        # 非法子命令由 argparse 自行报错 (exit 2); --help 触发 exit 0。
        try:
            parser.parse_args([topic, "--help"])
        except SystemExit as exc:
            return int(exc.code) if isinstance(exc.code, int) else 0
        return 2
    # 无子命令: 默认进入交互式对话 (tuan 直接开界面)。
    # fast_chat 内部把加载屏内嵌进 QxtTUI (单 Application), 内核后台构建, 杜绝双屏切换崩溃。
    if not getattr(args, "cmd", None):
        if getattr(args, "yolo", False) and not getattr(args, "mode", None):
            args.mode = "yolo"
        # 默认进入全屏 TUI (青小团对话界面); 终端异常时 cmd_chat 会回退 REPL。
        args.tui = True
        from .fast_start import fast_chat

        return int(fast_chat(args))
    func = args.func
    # 交互式对话: 同样走内嵌加载屏的 QxtTUI
    if func == "cmd_chat":
        from .fast_start import fast_chat

        return int(fast_chat(args))
    if callable(func):
        return int(func(args))
    return int(_resolve_func(func)(args))


if __name__ == "__main__":
    sys.exit(main())
