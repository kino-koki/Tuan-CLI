"""标语取词器 — 根目录历史垫片。

词库与取词逻辑的**唯一真身**在 ``tuan_cli/ui/slogans/picker.py``。
本模块通过 ``sys.modules`` 把自身指向真身模块对象, 保证
``slogans.picker is tuan_cli.ui.slogans.picker`` (老 import 路径与新
路径访问的是同一份实现与数据, 不产生第二套真值)。
"""

from __future__ import annotations

import sys

_core = __import__("tuan_cli.ui.slogans.picker", fromlist=["*"])
sys.modules[__name__] = _core
