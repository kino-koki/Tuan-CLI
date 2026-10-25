"""输出净化 —— emoji / pictograph 硬移除（提示词之外的兜底）。

为什么需要这一层
----------------
系统提示词里已经写死「零 emoji」硬规则 (见 ``core.prompts._no_emoji_rule``),
但**提示词是请求, 不是保证**: 模型仍可能偶发输出 emoji, 尤其是从训练语料里
带出来的装饰性符号。而用户在 HTML / PPT 场景下要的是「一定不能」—— emoji 在
那里会渲染成豆腐方框、触发字体回退, 属交付缺陷。

因此再加一道**确定性兜底**: 在所有运行路径的公共收尾 ``Agent._teardown_run``
里对最终答案做一次净化, 保证落盘会话 / 历史回看 / 导出 Markdown 里都不含 emoji。

边界 (刻意保守, 避免把正常中文技术写作改坏)
--------------------------------------------
- 只移除**真正的 emoji / pictograph**: U+1F000–U+1FAFF 等 Unicode 图形区,
  以及 Misc Symbols / Dingbats / 常用彩色符号。
- **保留**排版箭头 (->  ← ↑ ↓)、勾叉 (√ ×)、数学与制表符号、区块字符:
  它们在中文技术写作里是常规用法, 一并抹掉反而像 bug。
- 不触碰**工具写出的文件**: 文件内容属于用户资产 (可能正当地在字符串里用
  emoji), 净化范围严格限定在「对话回复文本」。
"""

from __future__ import annotations

import re
from typing import Tuple

# 需要整体移除的 Unicode 区间 (码位为闭区间)。
# 覆盖: 麻将/扑克牌、主要 emoji 区、杂项符号、装饰符号、带彩色图标的常用符号。
_EMOJI_RANGES: Tuple[Tuple[int, int], ...] = (
    (0x1F000, 0x1FAFF),   # 麻将/扑克/杂项图形/表情/交通/补充 emoji
    (0x2600, 0x26FF),     # Misc Symbols (⚠ ☀ ☁ …)
    (0x2700, 0x27BF),     # Dingbats (✅ ❌ ✂ ✈ …)
    (0x2B00, 0x2BFF),     # 箭头/几何图形中的 emoji 化符号 (⭐ ⬆ ⏰ …)
    (0xFE00, 0xFE0F),     # 变体选择符 (VS15/VS16), 移除后避免残留
    (0x1F1E6, 0x1F1FF),   # 区域指示符 (国旗), 已被上面大区间覆盖, 显式保留无害
)


def _is_emoji(ch: str) -> bool:
    cp = ord(ch)
    for lo, hi in _EMOJI_RANGES:
        if lo <= cp <= hi:
            return True
    return False


# ZWJ / 变体选择符会在移除后留下悬空字符, 一并清掉。
_DANGLING = re.compile(r"[\u200d\ufe0e\ufe0f]+")
# 移除 emoji 后行尾可能留下多余空白 (如 "完成 ✅" -> "完成 ")。只清**行尾**空白,
# 不动行首缩进 —— 否则会破坏代码块对齐。
_TRAILING_WS = re.compile(r"[ \t]+(?=\r?$)", re.MULTILINE)


def strip_emoji(text: str) -> Tuple[str, int]:
    """移除文本中的 emoji / pictograph。

    Args:
        text: 原始文本。

    Returns:
        ``(净化后的文本, 被移除的字符数)``。无可移除字符时原样返回, 且计数为 0,
        因此调用方可以用「计数是否为 0」判断是否发生了改写 (便于按需记录审计)。
    """
    if not text:
        return text, 0

    out_chars = []
    removed = 0
    for ch in text:
        if _is_emoji(ch):
            removed += 1
            continue
        out_chars.append(ch)
    if not removed:
        return text, 0

    cleaned = _DANGLING.sub("", "".join(out_chars))
    # 去掉因移除而残留的行尾空白 (保留行首缩进, 不动代码块对齐)
    cleaned = _TRAILING_WS.sub("", cleaned)
    return cleaned, removed


def has_emoji(text: str) -> bool:
    """文本中是否含 emoji (供测试与校验使用)。"""
    return any(_is_emoji(ch) for ch in (text or ""))