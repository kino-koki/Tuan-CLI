"""单一版本号源 (Single Source of Truth for tuan version).

所有子模块 (tuan_cli / tuan_cli.ecosystem / 各 CLI 命令) 都
应当从本文件导入 `__version__`, 不再各自硬编码。

历史上出现过:
- 主包 tuan_cli.__version__ = "0.3.1"
- tuan_cli.ecosystem.__version__ = "0.1.0"
两者语义混淆: 一个是"CLI 主程序版本", 另一个被误读为"生态互操作子模块
独立版本", 但实际上 ecosystem 只是 CLI 的一个功能域, 不应有自己的版本号。

规范:
    1. 主包 `tuan_cli/__init__.py` 通过 `from .version import __version__`
       获取版本, 对外暴露 `tuan_cli.__version__`。
    2. ecosystem 子模块不再定义自己的 `__version__`, 仅 re-export 主包版本。
    3. CLI 各命令 (cmd_upgrade / cmd_doctor / cmd_web / ui/repl / tui 等)
       统一 `from .. import __version__` (从主包读), 不再各自维护。

升级主包版本时只需修改本文件。
"""

# 单一版本号源: 升级时只改这里 (v0.3.1 起发布名 = tuan-cli)
__version__ = "0.3.1"
