"""扩充词库 — 根目录历史垫片。

真身在 ``tuan_cli/ui/slogans/extra.py``。本模块通过 ``sys.modules``
把自身指向真身模块对象, 保证 ``slogans.extra`` 与新路径是同一份词库数据。
"""

from __future__ import annotations

import sys

_core = __import__("tuan_cli.ui.slogans.extra", fromlist=["*"])
sys.modules[__name__] = _core
