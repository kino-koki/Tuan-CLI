"""历史兼容垫片 — 真正的数据与实现在 ``tuan_cli/ui/slogans/``。

本包曾位于仓库根目录, 而它的 docstring 全写
``from tuan_cli.ui.slogans import ...`` —— 那个路径当时不存在, 导致
860 条标语**零真实接入点**。本轮把实现落到正确包路径后, 这里只保留
re-export, 让旧引用不崩, 且词库只有一份、不会各自漂移。
"""

from __future__ import annotations

from tuan_cli.ui.slogans.locales.pt_BR import GROUPS  # noqa: F401
