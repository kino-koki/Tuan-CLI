"""本地化标语池的懒加载入口。

与 ``tuan_cli.i18n`` 的关系:

- **不复用 i18n 的 key→单条机制** (标语是分组随机池, 语义不同);
- **复用 i18n 的语言代码与当前语言状态** (``get_language()``), 不重写第二套语言选择逻辑;
- 语言代码与 ``i18n.LANGUAGES`` 严格对齐 (10 种)。

代码归一: ``zh-GAT`` 是标语库初稿里的历史写法 (内容实为粤语),
这里别名到 ``zh-TW``, 使旧引用不崩。粤语若日后正式支持, 应作为第 11 语种新增。
"""

from __future__ import annotations

from importlib import import_module
from typing import Dict, Optional, Tuple

__all__ = ["LANGUAGES", "normalize", "groups", "available"]

# 与 i18n.LANGUAGES 一一对应
LANGUAGES: Tuple[str, ...] = (
    "zh-CN", "zh-TW", "en", "ja", "ko",
    "es", "pt-BR", "fr", "de", "ru",
)

# 文件名映射
_MODULES: Dict[str, str] = {
    "zh-CN": "zh_CN",
    "zh-TW": "zh_TW",
    "en": "en",
    "ja": "ja",
    "ko": "ko",
    "es": "es",
    "pt-BR": "pt_BR",
    "fr": "fr",
    "de": "de",
    "ru": "ru",
}

# 别名归一 (吸收历史写法与常见变体)
_ALIASES: Dict[str, str] = {
    "zh": "zh-CN", "zh-hans": "zh-CN", "zh-cn": "zh-CN", "chs": "zh-CN",
    # 历史遗留: 标语库初稿写作 zh-GAT, 归到 zh-TW 以免旧引用失效
    "zh-gat": "zh-TW",
    # 注意: i18n._ALIASES 把 zh-hk 也归到 zh-TW; 粤语未正式支持前保持一致
    "zh-hant": "zh-TW", "zh-tw": "zh-TW", "zh-hk": "zh-TW", "cht": "zh-TW",
    "en-us": "en", "en-gb": "en",
    "ja-jp": "ja", "jp": "ja",
    "ko-kr": "ko",
    "es-es": "es", "es-mx": "es", "es-419": "es",
    "pt-br": "pt-BR", "pt-pt": "pt-BR", "pt": "pt-BR",
    "fr-fr": "fr",
    "de-de": "de",
    "ru-ru": "ru",
}

_cache: Dict[str, Optional[Dict[str, Tuple[str, ...]]]] = {}


def normalize(code: str) -> str:
    """把任意大小写/别名形式归一到 LANGUAGES 里的标准代码; 无法识别返回空串。"""
    if not code:
        return ""
    v = str(code).strip().replace("_", "-")
    if v in LANGUAGES:
        return v
    low = v.lower()
    if low in _ALIASES:
        return _ALIASES[low]
    primary = low.split("-", 1)[0]
    return _ALIASES.get(primary, "")


def groups(code: str) -> Dict[str, Tuple[str, ...]]:
    """取某语种的分组标语池; 未识别语种或模块缺失时返回空 dict (永不抛异常)。"""
    std = normalize(code)
    if not std:
        return {}
    if std not in _cache:
        try:
            mod = import_module(f".{_MODULES[std]}", __name__)
            _cache[std] = getattr(mod, "GROUPS", {})
        except ImportError:
            _cache[std] = None
    return _cache[std] or {}


def available(code: str) -> bool:
    """该语种是否有本地化标语池。"""
    return bool(groups(code))
