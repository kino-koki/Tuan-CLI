"""Tuan 标语库 — 根目录历史垫片包。

词库与取词逻辑的**唯一真身**在 ``tuan_cli/ui/slogans/``。本包只做 re-export,
让老 import 路径 ``import slogans`` / ``from slogans import pick`` 继续可用,
同时保证两套数据不会各自漂移 (任何属性都指向同一份对象)。

不要在本包添加新的词库数据 —— 一切新增应改 ``tuan_cli/ui/slogans/``。
"""

from __future__ import annotations

import importlib

# 取真身包的公开属性 (函数 / 类 / 子模块)。
# 用 importlib 保证 slogans.picker 是同一个模块对象,
# slogans.universal 也是同一个模块对象。
_core = importlib.import_module("tuan_cli.ui.slogans")

_CORE_MODULES = ("universal", "extra", "extra_locales", "picker",
                 "mapping", "_clean")
_CORE_ATTRS = tuple(_core.__all__) + ("stats",)

for _name in _CORE_MODULES:
    globals()[_name] = getattr(_core, _name)

for _attr in _CORE_ATTRS:
    globals()[_attr] = getattr(_core, _attr)

# 静态导出 (供类型检查工具识别)
__all__ = list(_CORE_ATTRS)
del _CORE_MODULES, _CORE_ATTRS, _name, _attr, _core, importlib
