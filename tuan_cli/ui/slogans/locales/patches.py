"""主体场景的**空组补池** — 只补真正为 0 的组合, 不硬凑数量。

为什么不直接改 ``de.py``: 十个语种文件的 docstring 都写明了各自的
分布统计 (``de.py`` 原文: "协作 (together) 在本列表中无对应表达 ——
该组完全由通用池 (30 条) 承担")。改写原文件会让这份分布说明变成
假文档。单独成补丁文件, 由 ``picker`` 合并, 原编号与统计保持可核验。

实测缺口: 唯一一个「非英语语种 + 主体上下文 = 0 条本语种词条」的组合
是 ``de:together`` —— 德语用户看到英文协作语。``en:explore`` 也是
空元组, 但英文会与 ``universal`` 合并 (同为英文), 不构成跨语种泄漏,
``audit()`` 对 ``lang == "en"`` 单独按英文池口径计算。

其余薄组 (如 ``ja:together=1`` / ``ko:thinking=2`` / ``ru:undo=2``)
**刻意不补**: 有本语种词条就说明「对应上了」, 数量少是文案风格取舍,
不是缺陷。``AuditReport.thin_pools`` 如实披露, 但**不**计入 ``ok`` 失败。
"""

from __future__ import annotations

from typing import Dict, Tuple

PATCHES: Dict[str, Dict[str, Tuple[str, ...]]] = {
    "de": {
        "together": (
            "Zusammen geht's leichter.",   # de.py docstring 自己建议的第一条
            "Ich halt die Leiter.",        # 同上, 第二条
            "Du steuerst, ich schau auf den Rand.",
            "Gib her, ich trag's.",
            "Zwei Augen sehen mehr.",
        ),
    },
}


#: 超长内置文案 -> **语义完整**的短版。
#:
#: 实测: 3 条原文超过 ``_MAX_VERB_COLS``(40 列), 走统一净化出口时会被
#: 截成半句 (西班牙语那条变成 "…más tempra", 葡萄牙语变成 "…até")。
#: 用户看到的会是残句 —— 这不是「对应上了」。刻意改写原文件会让它
#: docstring 里的分布统计变成假文档, 所以在这里做显式替换并留痕。
REPLACEMENTS: Dict[str, str] = {
    "No por mucho madrugar amanece más temprano.": "Con calma, se llega.",
    "Água mole em pedra dura, tanto bate até que fura.": "Água mole, pedra dura.",
    "Chercher une aiguille dans une botte de foin.": "Chercher une aiguille.",
}


def count() -> int:
    return (sum(len(v) for lang in PATCHES.values() for v in lang.values())
            + len(REPLACEMENTS))
