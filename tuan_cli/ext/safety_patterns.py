"""安全引擎模式库 (safety_engine 拆分模块)。

纯数据: 致命/高危/中危/极高危四档「(正则, label)」模式库。
本模块不做任何判定, 仅供 safety_redline.py 与 safety_score.py 复用。

维护约定:
- 每条为 ``(regex, label)``; label 双语 (英文便于测试/日志, 中文便于展示)。
- label 是用户本地黑名单减负 (`tuan safe reduce <label关键字>`) 的匹配键, 改动 label
  会影响既有用户的减负声明, 请谨慎。
- 新增模式请同步补 tests/ 下的回归用例 (见 test_safety_redteam_round4.py)。

单一真源 (2026-11-21 起)
------------------------
规则数据已下沉到 ``tuan_cli/ext/patterns_data/{critical,high,medium,extreme}.py``,
**该目录是唯一真源**。本模块退化为薄 re-export 层, 保持既有
``from tuan_cli.ext.safety_patterns import _CRITICAL_PATTERNS, ...`` 等引用不变。
请勿在本文件里直接增删规则 —— 改动请落到 ``patterns_data/`` 下对应子模块,
并由 ``scripts/check_patterns.py`` 做一致性校验。
"""

# 真源: tuan_cli/ext/patterns_data/ ; 此处仅 re-export, 不再内嵌规则字面量。
from .patterns_data import (  # noqa: F401  (re-export for legacy consumers)
    _CRITICAL_PATTERNS,
    _EXTREME_PATTERNS,
    _HIGH_PATTERNS,
    _MEDIUM_PATTERNS,
    _RAW_DISK,
)

__all__ = [
    "_CRITICAL_PATTERNS",
    "_EXTREME_PATTERNS",
    "_HIGH_PATTERNS",
    "_MEDIUM_PATTERNS",
    "_RAW_DISK",
]
