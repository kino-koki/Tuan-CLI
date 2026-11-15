"""通用词库 — 根目录历史垫片。

真身在 ``tuan_cli/ui/slogans/universal.py``。本模块通过 ``sys.modules``
把自身指向真身模块对象, 保证 ``slogans.universal`` 与新路径是同一份
词库数据 (GROUPS 等常量对象 identity 相同, 不产生第二套数据)。
"""

from __future__ import annotations

import sys

_core = __import__("tuan_cli.ui.slogans.universal", fromlist=["*"])
sys.modules[__name__] = _core
