"""tuan CLI 参数解析与命令注册测试 (cli/parser.py)。

验证:
- 每个顶层子命令都注册了 func 默认值 (main() 依赖它做分发);
- 子命令 -> func 的映射正确;
- 带嵌套子命令的父命令在缺省子命令时报错 (required=True);
- 各子命令的必需参数 / 可选 flag 解析正确;
- _resolve_func 把函数名映射到正确的模块 (ext/improve 走独立模块);
- main() 的分发逻辑 (无子命令 -> 交互对话(chat), --yolo -> mode=yolo, 非 TTY 拦截)。
"""

import argparse
import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from tuan_cli.cli import parser
from tuan_cli.cli.parser import build_parser


def _parse(*argv):
    return build_parser().parse_args(list(argv))


# ---------------------------------------------------------------- 子命令注册

def test_all_subcommands_have_func_default():
    """每个顶层子命令都必须注册 func, 否则 main() 无法分发。

    improve/evolve 例外: 它们是"必需子命令"父命令, func 由叶子子命令设置。
    """
    parser_obj = build_parser()
    sub_actions = [a for a in parser_obj._actions if isinstance(a, argparse._SubParsersAction)]
    assert len(sub_actions) == 1
    for name, sub in sub_actions[0].choices.items():
        if name in ("improve", "evolve"):
            continue
        assert "func" in sub._defaults, f"子命令 {name} 缺少 func 默认值"


def test_every_subcommand_func_is_resolvable():
    """每个子命令的 func 必须真的能解析到可调用对象。

    回归: `tuan web` 曾因 commands.py::_CMD_SOURCES 漏登记 cmd_web 而在
    运行时抛 AttributeError —— func 默认值存在但惰性路由取不到, 上面的
    "有 func" 检查抓不到。这里对全部子命令逐一解析, 保证不重蹈覆辙。
    """
    parser_obj = build_parser()
    sub_actions = [a for a in parser_obj._actions if isinstance(a, argparse._SubParsersAction)]
    assert len(sub_actions) == 1
    unresolvable = []
    for name, sub in sub_actions[0].choices.items():
        func_name = sub._defaults.get("func")
        if not func_name:
            continue  # improve 等父命令由叶子设置
        try:
            resolved = parser._resolve_func(func_name)
            assert callable(resolved), f"{name} -> {func_name} 解析结果不可调用"
        except Exception as exc:  # noqa: BLE001
            unresolvable.append(f"{name} -> {func_name} ({exc.__class__.__name__})")
    assert not unresolvable, "无法解析的子命令: " + ", ".join(unresolvable)


def test_all_leaf_subcommand_funcs_resolvable():
    """递归遍历全部层级的叶子子命令, func 必须都能解析成可调用对象。

    回归: 上面两条断言只遍历顶层 choices, 二级/三级叶子
    (``tuan web audit sessions`` / ``tuan bg logs`` / ``tuan safe redteam``) 从未
    被覆盖。cmd_web_audit 曾因此断裂: 模块 self-register 但无人 import,
    ``tuan web audit`` 运行时抛 AttributeError 而测试全绿。

    func 可由自身或任一祖先 set_defaults 提供: argparse 在父 parser 解析收尾时把
    父级 ``_defaults`` 作为兜底填进 namespace (子命令没自己设才轮到父级)。
    """
    parser_obj = build_parser()
    sub_actions = [a for a in parser_obj._actions
                   if isinstance(a, argparse._SubParsersAction)]
    assert len(sub_actions) == 1

    leaves: list[tuple[list[str], object]] = []

    def _choices(p):
        sp = [a for a in p._actions
              if isinstance(a, argparse._SubParsersAction)]
        return dict(sp[0].choices) if sp else {}

    def walk(sub, prefix, inherited):
        inner = _choices(sub)
        own = sub._defaults.get("func")
        effective = own if own else inherited
        if not inner:
            leaves.append((prefix, effective))
            return
        for name, nxt in inner.items():
            walk(nxt, prefix + [name], effective)

    for name, sub in sub_actions[0].choices.items():
        walk(sub, [name], None)

    missing = [p for p, f in leaves if not f]
    assert not missing, "叶子子命令无 func (任何层级): " + ", ".join(
        "tuan " + " ".join(p) for p in missing)

    bad = []
    for path, func in leaves:
        try:
            resolved = parser._resolve_func(func)
            assert callable(resolved), f"{' '.join(path)} 解析结果不可调用"
        except Exception as exc:  # noqa: BLE001
            bad.append(f"tuan {' '.join(path)} -> {func} "
                       f"({exc.__class__.__name__})")
    assert not bad, "无法解析的叶子子命令: " + ", ".join(bad)


def test_no_self_registered_cmd_is_unreachable():
    """self-register 的 cmd 模块必须真实可达 (注册表或 commands 门面之一)。

    回归: cmd_web_audit / cmd_claude_parity 在模块底部调 _register_command,
    但从未被 _auto_register 导入也不在 commands._CMD_SOURCES → func 永远
    解析不到。cmd_chat_handoff / cmd_evolve 经 _CMD_SOURCES 门面路由可达,
    属合法形态 (不导入才符合 main() 的惰性加载契约)。
    """
    import re

    from tuan_cli.cli import commands
    from tuan_cli.cli.parser import _COMMAND_REGISTRY

    cli_dir = Path(__file__).resolve().parent.parent / "tuan_cli" / "cli"
    parser_src = (cli_dir / "parser.py").read_text(encoding="utf-8")
    body = parser_src[parser_src.index("def _auto_register"):
                       parser_src.index("# 模块加载时自动注册")]
    imported = set(re.findall(r'import_module\("(\.[a-z_0-9]+)"', body))
    reachable = set(_COMMAND_REGISTRY) | set(commands._CMD_SOURCES)

    orphan = []
    for py in sorted(cli_dir.glob("*.py")):
        if not py.stem.startswith("cmd_") and py.stem not in (
                "ext_cli", "improve_cli"):
            continue
        text = py.read_text(encoding="utf-8")
        for m in re.finditer(
                r'_register_command\("([a-z_0-9]+)",\s*"(\.[a-z_0-9]+)"\)', text):
            name, mod = m.group(1), m.group(2)
            if mod not in imported and name not in reachable:
                orphan.append(f"{name} ({mod})")
    assert not orphan, "self-register 但不可达的 cmd 模块: " + ", ".join(orphan)


def test_subcommand_func_values():
    cases = {
        "dev": ("cmd_dev", ["task"]),
        "run": ("cmd_run", ["task"]),
        "agent": ("cmd_agent", ["task"]),
        "bg": ("cmd_bg", ["list"]),
        "setup": ("cmd_setup", []),
        "doctor": ("cmd_doctor", []),
        "models": ("cmd_model", []),
        "config": ("cmd_config", ["dump"]),
        "plugin": ("cmd_plugin", ["list"]),
        "skill": ("cmd_skill", ["list"]),
        "memory": ("cmd_memory", ["list"]),
        "cron": ("cmd_cron", ["list"]),
        "mcp": ("cmd_mcp", ["list"]),
        "hooks": ("cmd_hooks", ["list"]),
        "undo": ("cmd_undo", []),
        "session": ("cmd_session", ["list"]),
    }
    for name, (func, extra) in cases.items():
        assert _parse(name, *extra).func == func, f"{name} -> {func}"


def test_improve_leaves_set_func():
    """improve 父命令无 func, 叶子子命令负责设置。"""
    assert _parse("improve", "summarize").func == "cmd_improve"
    assert _parse("improve", "apply").func == "cmd_improve"


def test_evolve_leaves_set_func():
    """evolve 父命令无 func, 叶子子命令 (run/report) 负责设置。"""
    assert _parse("evolve", "run", "--tasks", "T1").func == "cmd_evolve"
    assert _parse("evolve", "report").func == "cmd_evolve"


def test_nested_subcommands_required():
    """带嵌套子命令的父命令必须提供子命令 (models 例外: 无子命令进交互选择)。"""
    for parent in ["bg", "config", "plugin", "skill", "memory",
                   "cron", "mcp", "hooks", "improve", "session", "evolve"]:
        with pytest.raises(SystemExit):
            _parse(parent)


def test_model_without_subcommand_is_valid():
    args = _parse("models")
    assert args.func == "cmd_model"
    assert getattr(args, "model_cmd", None) is None


# ---------------------------------------------------------------- 参数解析

def test_run_parses_task_and_flags():
    args = _parse("run", "do the thing", "--yes", "--no-stream", "--model", "m")
    assert args.task == "do the thing"
    assert args.yes is True
    assert args.no_stream is True
    assert args.model == "m"


def test_dev_requires_task():
    with pytest.raises(SystemExit):
        _parse("dev")


def test_cron_add_parses_interval_and_output():
    args = _parse("cron", "add", "nightly", "run report", "--interval", "120", "--output", "r.txt")
    assert args.name == "nightly"
    assert args.prompt == "run report"
    assert args.interval == 120
    assert args.output == "r.txt"


def test_model_set_parses_positional():
    args = _parse("models", "set", "deepseek", "deepseek-chat")
    assert args.provider == "deepseek"
    assert args.model == "deepseek-chat"
    assert args.base_url is None
    assert args.api_key_env is None


def test_mcp_call_parses_json():
    args = _parse("mcp", "call", "srv", "tool", "--json", '{"text":"hi"}')
    assert args.server == "srv"
    assert args.tool == "tool"
    assert args.json == '{"text":"hi"}'


def test_session_resume_optional_target():
    assert _parse("session", "resume").target is None
    assert _parse("session", "resume", "3").target == "3"


def test_undo_default_target():
    assert _parse("undo").target == ""


def test_version_flag_exits_zero():
    with pytest.raises(SystemExit) as e:
        _parse("--version")
    assert e.value.code == 0


# ---------------------------------------------------------------- 函数解析与分发

def test_resolve_func_routes_to_correct_module():
    with mock.patch("tuan_cli.cli.parser.importlib.import_module") as imp:
        parser._resolve_func("cmd_improve")
        assert imp.call_args[0][0] == ".improve_cli"
        parser._resolve_func("cmd_chat")
        # cmd_chat 经 commands.py::_CMD_SOURCES 路由到 .cmd_chat
        # (拆分后 cmd_chat 仍是交互对话实现模块, 不再是 .commands 门面)。
        assert imp.call_args[0][0] == ".cmd_chat"


def test_main_no_args_routes_to_interactive():
    """`tuan` (无子命令) 应进入交互启动 (fast_chat -> cmd_chat)。"""
    from tuan_cli.cli import fast_start
    captured = {}
    def spy(args):
        captured["called"] = True
        return 0
    with mock.patch.object(fast_start, "fast_chat", spy), \
         mock.patch("sys.stdin.isatty", return_value=True), \
         mock.patch.object(sys, "argv", ["tuan"]):
        assert parser.main() == 0
    assert captured["called"] is True


def test_main_yolo_sets_mode():
    from tuan_cli.cli import fast_start
    captured = {}
    def spy(args):
        captured["mode"] = getattr(args, "mode", None)
        return 0
    with mock.patch.object(fast_start, "fast_chat", spy), \
         mock.patch("sys.stdin.isatty", return_value=True), \
         mock.patch.object(sys, "argv", ["tuan", "--yolo"]):
        parser.main()
    assert captured["mode"] == "yolo"


def test_main_routes_run_to_cmd_run():
    from tuan_cli.cli import commands
    captured = {}
    def spy(args):
        captured["task"] = args.task
        return 0
    with mock.patch.object(commands, "cmd_run", spy), \
         mock.patch("sys.stdin.isatty", return_value=False), \
         mock.patch.object(sys, "argv", ["tuan", "run", "do it"]):
        assert parser.main() == 0
    assert captured["task"] == "do it"


def test_main_returns_2_when_not_tty_and_interactive():
    with mock.patch("sys.stdin.isatty", return_value=False), \
         mock.patch.object(sys, "argv", ["tuan"]):
        assert parser.main() == 2


def test_reload_rebuilds_registry_and_keeps_gateway():
    """reload 后注册表重建, 但不破坏 commands 门面路由。

    回归: test_api_config_fixes::test_verbose_alone_prints_version_no_tui 曾
    importlib.reload(parser) 重置 _COMMAND_REGISTRY, 而命令模块已缓存不重跑
    _register_command, 导致注册表为空。旧 _backfill_from_cmd_sources() 把
    cmd_run 等回填进注册表 (映射 .cmd_agents), 使 _resolve_func 绕过
    commands.__getattr__ 门面 → mock.patch.object(commands, "cmd_run", spy)
    失效 (test_main_routes_run_to_cmd_run 曾失败: assert 1 == 0)。
    修复后: reload 由 _ensure_registered_after_reload 重建 (14 个独立模块),
    剩余 cmd_* 继续走门面 fallback, 双轨保持可用。
    """
    saved = parser._COMMAND_REGISTRY.copy()
    parser._COMMAND_REGISTRY.clear()
    try:
        parser._ensure_registered_after_reload()

        # 独立注册模块重建进注册表
        assert "cmd_ext" in parser._COMMAND_REGISTRY
        assert parser._COMMAND_REGISTRY["cmd_ext"] == ".ext_cli"

        # cmd_run 等依赖 commands 门面惰性路由, 不得进注册表
        assert "cmd_run" not in parser._COMMAND_REGISTRY
        assert "cmd_dev" not in parser._COMMAND_REGISTRY

        # 双轨均能解析到可调用对象
        assert callable(parser._resolve_func("cmd_ext"))
        assert callable(parser._resolve_func("cmd_run"))
        assert callable(parser._resolve_func("cmd_dev"))
    finally:
        parser._COMMAND_REGISTRY.clear()
        parser._COMMAND_REGISTRY.update(saved)


def test_cmd_ext_registered_to_independent_module():
    """cmd_ext 必须注册到 .ext_cli (独立注册模块)。

    回归: ext_cli.py 曾定义 cmd_ext 但从未 _register_command("cmd_ext",
    ".ext_cli"), 也不在 _CMD_SOURCES → _resolve_func("cmd_ext") 抛
    AttributeError, `tuan ext` 子命令不可达。属既有缺陷, 补注册修复。
    """
    assert parser._COMMAND_REGISTRY.get("cmd_ext") == ".ext_cli"
    resolved = parser._resolve_func("cmd_ext")
    assert callable(resolved)
    assert resolved.__module__ == "tuan_cli.cli.ext_cli"
