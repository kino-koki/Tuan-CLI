"""safe 子命令分发契约回归测试。

固化两个方向的契约, 防止未来再次出现"注册了但分发不到"或"分发了但注册不到":
  1. 每个注册进 argparse 的 safe_cmd 合法值, 必须被 cmd_safe 分发处理
     (内联分支 或 _EXTENDED_SAFE_DISPATCH 惰性路由)。
  2. 每个可分发值 (内联分支 + _EXTENDED_SAFE_DISPATCH 键), 必须能通过 argparse
     解析成功 (否则是死分支)。
  3. 每个 _EXTENDED_SAFE_DISPATCH 值指向的模块/函数必须可导入且可调用 (0/1 参)。
"""
from __future__ import annotations

import inspect
import re
import pathlib
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from tuan_cli.cli.cmd_safe import _EXTENDED_SAFE_DISPATCH  # noqa: E402


def _safety_cli_source() -> str:
    p = _ROOT / "tuan_cli/cli/subcommands/safety_cli.py"
    return p.read_text(encoding="utf-8")


def _registered_safe_cmds() -> set[str]:
    """从 safety_cli 源码提取所有 set_defaults(safe_cmd=...) 的注册值。"""
    src = _safety_cli_source()
    return set(re.findall(r'safe_cmd="([a-z]+)"', src))


def _inline_dispatch_set() -> set[str]:
    """cmd_safe 内联 if-elif 分支覆盖的 safe_cmd 值。"""
    src = (_ROOT / "tuan_cli/cli/cmd_safe.py").read_text(encoding="utf-8")
    body = src[src.index("def cmd_safe"):]
    next_def = re.search(r"\n(?:async )?def ", body[1:])
    if next_def:
        body = body[: next_def.start() + 1]
    return set(re.findall(r'safe_cmd == "([a-z]+)"', body))


class TestSafeDispatchContract:
    def test_every_registered_value_is_handled(self):
        """每个注册的 safe_cmd 都必须有分发路径 (内联或扩展表)。"""
        registered = _registered_safe_cmds()
        handled = _inline_dispatch_set() | set(_EXTENDED_SAFE_DISPATCH.keys())
        missing = sorted(registered - handled)
        assert not missing, f"已注册但分发未覆盖: {missing}"

    def test_every_dispatch_key_is_registered(self):
        """每个可分发值都必须能被 argparse 解析 (否则是死分支)。"""
        from tuan_cli.cli.parser import build_parser

        handled = _inline_dispatch_set() | set(_EXTENDED_SAFE_DISPATCH.keys())
        parser = build_parser()
        for value in sorted(handled):
            argv = ["safe", value]
            args = None
            last_exc: SystemExit | None = None
            # 逐级补位: 0 个位置参数 → 1 个 → 2 个, 直到能解析 (仅验证可达, 不执行)
            for _extra in (0, 1, 2):
                probe = argv + ["__probe__"] * _extra
                try:
                    args = parser.parse_args(probe)
                    break
                except SystemExit as exc:  # noqa: PERF203
                    last_exc = exc
            assert args is not None, f"分发键 {value} 无法解析 (SystemExit {last_exc.code if last_exc else '?'})"
            assert getattr(args, "safe_cmd", None) == value, f"分发键 {value} 解析后 safe_cmd 不符"

    def test_extended_dispatch_targets_resolvable(self):
        """_EXTENDED_SAFE_DISPATCH 的每个 (模块, 函数) 必须可导入且签名 0/1 参。"""
        for cmd, (mod_path, func_name) in _EXTENDED_SAFE_DISPATCH.items():
            try:
                import importlib

                mod = importlib.import_module(mod_path, "tuan_cli.cli")
            except Exception as exc:  # noqa: BLE001
                pytest.fail(f"safe {cmd} 模块 {mod_path} 导入失败: {exc}")
            fn = getattr(mod, func_name, None)
            assert fn is not None, f"safe {cmd} 函数 {func_name} 不存在"
            n_params = len(inspect.signature(fn).parameters)
            assert n_params in (0, 1), f"safe {cmd} {func_name} 签名应为 0/1 参, 实为 {n_params}"
