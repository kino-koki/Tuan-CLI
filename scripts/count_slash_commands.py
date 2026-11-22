#!/usr/bin/env python3
"""可复现的 slash / 子命令计数 (README「The command surface」数字来源).

数字必须能被第三方用一条命令复现; 本脚本从权威清单
``tuan_cli.cli.cmd_slash.SLASH_COMMAND_NAMES`` (与 ``_handle_slash`` 的
elif 分支一一对应) 与 ``slash_tier`` 分层定义直接推导, 不维护第二份清单。

用法:
    python scripts/count_slash_commands.py           # 人读输出
    python scripts/count_slash_commands.py --markdown  # 供 README 引用的片段
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tuan_cli.cli.cmd_slash import SLASH_COMMAND_NAMES  # noqa: E402
from tuan_cli.cli.slash_tier import (  # noqa: E402
    CORE_SLASH_COMMANDS,
    EXPERT_SLASH_COMMANDS,
)


def main() -> int:
    names = list(SLASH_COMMAND_NAMES)
    unique = sorted(set(names))
    dupes = sorted({n for n in names if names.count(n) > 1})
    core = [n for n in unique if n in CORE_SLASH_COMMANDS]
    expert = [n for n in unique if n in EXPERT_SLASH_COMMANDS]
    untyped = [n for n in unique
               if n not in CORE_SLASH_COMMANDS and n not in EXPERT_SLASH_COMMANDS]

    if dupes:
        print(f"WARNING: duplicated names in SLASH_COMMAND_NAMES: {dupes}")

    print(f"slash commands (authoritative SLASH_COMMAND_NAMES): {len(unique)} "
          f"({len(names)} declared, {len(dupes)} duplicated)")
    print(f"  core tier:   {len(core)}")
    print(f"  expert tier: {len(expert)}")
    if untyped:
        print(f"  not in any tier set: {len(untyped)} -> {untyped}")

    if "--markdown" in sys.argv:
        print()
        print(f"{len(unique)} slash commands "
              f"({len(core)} core + {len(expert)} expert), "
              f"authoritative list: `tuan_cli/cli/cmd_slash.py::SLASH_COMMAND_NAMES`, "
              f"reproduce with `python scripts/count_slash_commands.py`.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
