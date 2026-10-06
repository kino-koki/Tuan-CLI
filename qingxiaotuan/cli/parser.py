"""qxt 命令行参数解析与入口。

最简用法 (开箱即用):
    qxt              直接打开交互界面 (默认进对话)
    qxt --yolo       无限制模式: 危险操作自动批准
    qxt --plan       Plan 模式启动: 窗口 Agent 只读, 不修改任何文件
    qxt --isolation  引擎进程级隔离: 非判定类引擎以真实 JSONL 子进程运行 (崩溃/超时安全回落)
    qxt models       配置/热切换模型供应商 (开箱支持51家, 含 Ollama/llama.cpp 本地)
    qxt help [子命令]  显示帮助 (等效于 qxt --help / qxt <子命令> --help)

子命令一览:
    qxt dev "任务"            进入自主开发循环 (分析→实现→自测→核实→汇报, 直到你满意)
    qxt dev codedev demo|doctor|retrieve|verify   代码开发子系统 (检索/验证/分解)
    qxt run "任务"            headless 一次性任务, 跑完退出 (适合脚本/CI)
    qxt agent "任务"          后台自主任务 (终端不阻塞)
    qxt setup                 初始化向导 (API Key 等)
    qxt doctor [--compact]    环境健康检查 (--compact 额外跑上下文压缩存活自检)
    qxt models                配置/热切换模型供应商 (55 家开箱即用, 含本地 Ollama/llama.cpp)
    qxt config get/set/dump   配置管理 (含 mode: qxt config get mode / qxt config set mode yolo)
    qxt plugin list           查看微内核插件与服务
    qxt skill list/show       技能管理
    qxt memory list/search    记忆管理
    qxt cron add/list/remove/enable/disable/edit/run/logs/tick/start/stop/status  定时任务 (含常驻守护)
    qxt improve summarize/apply      自我改进闭环 (从执行历史提炼规则与技能草稿)
    qxt tutorial list/run <name>     任务驱动内置教程 (安全/撤销/协作/成本)
    qxt session list/resume/delete/replay/trajectory  会话管理 (回放/轨迹已并入 session)
    qxt undo [--impact]       事务化回滚 (--impact 展示操作账本影响半径)
    qxt migrate detect/run/status    旧版 ~/.kimi 配置/会话 → 新版 一键迁移
    qxt network configuration      联网/搜索配置 (搜索上限/默认条数/截断/top_k/超时; 短写 qxt net con)
"""

from __future__ import annotations

import argparse
import importlib
import logging
import sys

from .. import __version__
from .parser_commands import register_subcommands


def _resolve_func(name: str):
    """延迟导入命令函数: 轻量命令 (--version/--help) 不加载 app 链。"""
    if name == "cmd_ext":
        mod = importlib.import_module(".ext_cli", __package__)
    elif name == "cmd_improve":
        mod = importlib.import_module(".improve_cli", __package__)
    elif name == "cmd_gh":
        mod = importlib.import_module(".cmd_gh", __package__)
    elif name == "cmd_acp":
        mod = importlib.import_module(".cmd_acp", __package__)
    elif name == "cmd_safe":
        mod = importlib.import_module(".cmd_safe", __package__)
    elif name == "cmd_harden":
        mod = importlib.import_module(".cmd_harden", __package__)
    elif name == "cmd_migrate":
        mod = importlib.import_module(".cmd_migrate", __package__)
    elif name == "cmd_network":
        mod = importlib.import_module(".cmd_network", __package__)
    elif name == "cmd_rewind":
        mod = importlib.import_module(".cmd_rewind", __package__)
    elif name == "cmd_project":
        mod = importlib.import_module(".cmd_project", __package__)
    elif name == "cmd_worktree":
        mod = importlib.import_module(".cmd_worktree", __package__)
    elif name == "cmd_chat_handoff":
        mod = importlib.import_module(".cmd_handoff", __package__)
    else:
        # 其余命令 (cmd_run / cmd_chat / cmd_dev / cmd_config / cmd_doctor /
        # cmd_onboarding / cmd_commands / cmd_session / ...) 统一走 commands 的 PEP 562 惰性路由,
        # 其 _CMD_SOURCES 覆盖所有已注册 func; 不可再漏分支 (否则 UnboundLocalError)。
        mod = importlib.import_module(".commands", __package__)
    return getattr(mod, name)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="qxt", description="青小团 CLI - 会成长的插件化 Agent"
    )
    parser.add_argument("--version", action="version", version=f"qxt {__version__}")
    parser.add_argument(
        "--profile",
        default="default",
        help="使用指定 profile (~/.qingxiaotuan/profiles/<name>)",
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
        help="Claude Code 风格免确认工具/作用域: 如 'Bash(npm test),Read,Write' (命中者不提示)",
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
        help="Claude Code 风格权限模式 (映射到内部模式: dontAsk/bypassPermissions→yolo, plan→plan, 其余→standard)",
    )
    parser.add_argument(
        "--fallback-model",
        help="主模型不可用时的备用模型 (对应 Claude Code --fallback-model)",
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
        help="引擎进程级隔离: 开启后非判定类引擎(diff/crypto/index/ansi/json/search/notify/rules)以真实 JSONL 子进程运行, 子进程崩溃/超时安全回落进程内; safety 引擎恒进程内(fail-closed)。默认关(进程内直调)。持久开启用 `qxt config set engine.isolation true`",
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
# qxt / qxt --plan / qxt --yolo 等交互式启动形态直接走内置 Python TUI:
#   qingxiaotuan/tui/tui.py::QxtTUI  (cmd_chat.fast_chat -> QxtTUI)
#   - 渲染/皮肤: 青小团自己的 Mascot (▐█▛█▛█▌ block art logo) + prompt_toolkit 主题;
#   - 底层:      build_kernel() + create_agent() + Agent.run() (青小团自己的 agent);
#   - 依赖:      仅 rich + prompt_toolkit (已随 qxt 安装), 无需 Node / 无需构建步骤。
# 历史上曾尝试复用 kimi 的 TS TUI (kimi-code-main/apps/qingxiaotuan-tui), 但那会
# 强依赖 Node 工具链 (tsdown + Node>=24.15 + 构建), 违背「开箱即用」, 故已移除该
# 启动路径, 仅保留下方纯 Python TUI。不再有任何 Node 进程被 qxt 拉起。


def _rewrite_dev_codedev(argv):
    """把 `dev codedev <rest>` 透明改写为 `__dev_codedev <rest>`。

    ``dev`` 的 task 是自由文本位置参数, 无法在其 ArgumentParser 上直接挂
    subparsers (否则任意任务首词会被 argparse 当作未知子命令而报 invalid choice)。
    codedev 子命令组因此由隐藏顶层解析器 ``__dev_codedev`` 承载; 仅在 main() 入口
    对 argv 做这一次无感知改写, 用户侧仍是 `qxt dev codedev demo|doctor|...`。
    """
    if len(argv) >= 2 and argv[0] == "dev" and argv[1] == "codedev":
        return ["__dev_codedev", *argv[2:]]
    return argv


def main() -> int:
    # 先把 ~/.qingxiaotuan/.env 里的密钥加载进环境 (所有子命令共用)
    from ..config import load_dotenv

    load_dotenv()
    parser = build_parser()
    sys.argv[1:] = _rewrite_dev_codedev(sys.argv[1:])
    args = parser.parse_args()
    # 交互式/计划/免确认启动形态 (无子命令且非 --print) 直接走内置 Python TUI
    # (qingxiaotuan/tui/tui.py::QxtTUI, 仅依赖 rich + prompt_toolkit, 开箱即用,
    # 不依赖 Node / 任何 kimi 代码)。下方 fast_chat() 会接管终端。

    # -v 详细输出: 配置对应级别的日志 (concise 模式下 REPL 不显示但调试可用)
    verbose = getattr(args, "verbose", 0)
    if verbose >= 3:
        logging.getLogger().setLevel(logging.DEBUG)
    elif verbose >= 2:
        logging.getLogger().setLevel(logging.INFO)
    elif verbose >= 1:
        logging.getLogger("qingxiaotuan").setLevel(logging.DEBUG)
    # --print 模式: 非交互输出, stdin 不是 TTY 时不再报错退出
    is_print = getattr(args, "print_mode", False)
    # 引擎进程级隔离: --isolation 强制开启当前进程 (默认跟随配置, 配置默认关)。
    # 路由由 core/engine_isolation.EngineIsolation 负责, safety 引擎恒进程内。
    if getattr(args, "isolation", False):
        from ..core.engine_isolation import set_isolation, EngineIsolation

        set_isolation(EngineIsolation(isolation_enabled=True))
    # `qxt -v` / `qxt --verbose` (无子命令): 本意多为查版本/详细模式用法,
    # 直接启动全屏 TUI 是意外行为 (曾把 -v 当成普通交互启动)。改为打印
    # 版本 + 详细模式用法提示并退出, 不进入交互。此判断必须先于 TTY 检查,
    # 否则 qxt -v 在非 TTY 下会先命中"交互模式需要终端"而报错。
    if (
        verbose
        and not getattr(args, "cmd", None)
        and not is_print
        and not getattr(args, "yolo", False)
        and not getattr(args, "plan", False)
        and not getattr(args, "mode", None)
    ):
        from .. import __version__

        print(f"qxt {__version__}")
        print("-v/--verbose 是详细日志开关, 需搭配子命令使用, 例如:")
        print('    qxt run -v "你的任务"   跑任务并显示详细日志')
        print("    qxt dev -v <任务>    开发循环并显示详细日志")
        print("    qxt setup -v         配置向导并显示详细日志")
        print("查版本号请用: qxt --version")
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
            "    - Windows: 打开『命令提示符』或『Windows Terminal』, 输入 qxt\n"
            "    - 或在该终端里先 cd 到项目目录, 再 .venv\\Scripts\\Activate.ps1 后 qxt\n"
            '  非交互任务可用: qxt run "你的任务" (headless, 跑完退出)\n'
            '  管道输出可用: qxt --print chat "你的任务" (直接输出到 stdout)\n\n'
        )
        return 2
    # qxt help [<子命令>]: 只读打印帮助, 不进入交互、不写配置 (与 `qxt --help` / `qxt <子命令> --help` 等效)
    if getattr(args, "cmd", None) == "help":
        topic = getattr(args, "topic", None)
        if not topic:
            parser.print_help()
            return 0
        # 复用 argparse 公共能力: `qxt <topic> --help` 会打印该子命令帮助并退出。
        # 非法子命令由 argparse 自行报错 (exit 2); --help 触发 exit 0。
        try:
            parser.parse_args([topic, "--help"])
        except SystemExit as exc:
            return int(exc.code) if isinstance(exc.code, int) else 0
        return 2
    # 无子命令: 默认进入交互式对话 (qxt 直接开界面)。
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
