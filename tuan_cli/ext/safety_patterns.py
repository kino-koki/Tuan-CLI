"""安全引擎模式库 (safety_engine 拆分模块)。

纯数据: 致命/高危/中危/极高危四档「(正则, label)」模式库。
本模块不做任何判定, 仅供 safety_redline.py 与 safety_score.py 复用。

维护约定:
- 每条为 ``(regex, label)``; label 双语 (英文便于测试/日志, 中文便于展示)。
- label 是用户本地黑名单减负 (`tuan safe reduce <label关键字>`) 的匹配键, 改动 label
  会影响既有用户的减负声明, 请谨慎。
- 新增模式请同步补 tests/ 下的回归用例 (见 test_safety_redteam_round4.py)。
- 模式数据现拆分至 ``patterns_data/`` 子包 (critical/high/medium/extreme);
  本文件仅作为薄薄的再导出 shim, 保持既有 import 路径不变。
"""

from .patterns_data.critical import _CRITICAL_PATTERNS, _RAW_DISK  # noqa: F401
from .patterns_data.extreme import _EXTREME_PATTERNS  # noqa: F401
from .patterns_data.high import _HIGH_PATTERNS  # noqa: F401
from .patterns_data.medium import _MEDIUM_PATTERNS  # noqa: F401

__all__ = [
    "_RAW_DISK",
    "_CRITICAL_PATTERNS",
    "_HIGH_PATTERNS",
    "_MEDIUM_PATTERNS",
    "_EXTREME_PATTERNS",
]
