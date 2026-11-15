"""tuan 子命令注册分片 (`register_subcommands` 按功能域拆分)。

`cli/parser_commands.py` 仅保留同名入口函数并依次调用这里的
`register_*`, 因此对外导入路径不变, 行为不变。

注意: 本包不叫 ``commands``, 因为 ``cli/commands.py`` 已存在 (PEP 562 惰性路由门面),
同名包会遮蔽该模块。
"""

from __future__ import annotations
