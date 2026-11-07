"""与 Codex ``tui/src/vim_search.rs`` 对齐的字面 Vim 搜索查询。

上游模块头原文（功能性契约，逐条对齐）：

    "Surface-independent literal Vim search queries. Matches span complete
    graphemes; callers own navigation, operator ranges, and the lifetime of
    accepted versus pending input."

即：**只做字面匹配**，不做正则；匹配范围必须覆盖完整 grapheme 簇；
导航、operator range、已接受/待定输入的生命周期由调用方负责，本模块不碰。

本地化修改（如实列出）：
  - 上游用 ``unicode-segmentation`` 的扩展 grapheme 簇；本环境无该库，
    改用 stdlib ``unicodedata`` 的 **UAX #29 近似实现**（组合标记 / ZWJ /
    变体选择符 / 区域指示符对 / emoji 修饰符 / CRLF）。这在 CJK + 组合
    字符场景下是本地化增强，但**不声称与 Rust 库逐字节一致**。
  - ``matching_ranges`` 返回 ``range`` 列表而非 Rust 惰性迭代器；
    空查询返回空列表（对齐上游 ``if query.is_empty() { "" }``）。

许可：Apache-2.0（见 ``NOTICE`` 第 11 条）。无 Rust 源码逐字复制。
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable, List, Tuple


class SearchDirection(str, Enum):
    """对齐上游 ``SearchDirection``，默认 Forward。"""

    FORWARD = "forward"
    BACKWARD = "backward"

    def reversed(self) -> "SearchDirection":
        return (SearchDirection.BACKWARD if self is SearchDirection.FORWARD
                else SearchDirection.FORWARD)

    @classmethod
    def default(cls) -> "SearchDirection":
        return cls.FORWARD


@dataclass
class SearchQuery:
    """对齐上游 ``SearchQuery``：text + direction，默认 forward / 空串。"""

    text: str = ""
    direction: SearchDirection = field(default_factory=SearchDirection.default)


# ---------------------------------------------------------------- grapheme 分段
def _is_extend(ch: str) -> bool:
    """组合标记 / 变体选择符 / emoji 修饰符：依附于前一个簇。"""
    if unicodedata.combining(ch):
        return True
    cp = ord(ch)
    # Variation Selectors FE00-FE0F + VS17-FE0F..E01EF；emoji modifiers 1F3FB-1F3FF
    if 0xFE00 <= cp <= 0xFE0F or 0xE0100 <= cp <= 0xE01EF:
        return True
    if 0x1F3FB <= cp <= 0x1F3FF:
        return True
    return unicodedata.category(ch) in ("Mn", "Me")


def _is_zwj(ch: str) -> bool:
    return ch == "\u200d"


def _is_regional_indicator(ch: str) -> bool:
    return 0x1F1E6 <= ord(ch) <= 0x1F1FF


def iter_graphemes(text: str) -> Iterable[Tuple[int, str]]:
    """产出 ``(起始字节偏移? 不, 是字符索引, 簇文本)``。

    **索引口径**：与 Rust 的 ``grapheme_indices`` 一致，返回的是 **UTF-8
    字节偏移** 会让 Python 调用方困惑；这里返回 **字符索引**，并在
    ``matching_ranges`` 内部统一用字符索引做切片。文档如实标注该差异。

    近似 UAX #29：
      - CRLF 视为一个簇；
      - 控制字符各自成簇；
      - ``Extend`` 依附前一簇；
      - ZWJ 把下一个簇并入当前簇；
      - 区域指示符两两成对（国旗）。
    """
    if not text:
        return
    i = 0
    n = len(text)
    cluster_start = 0
    cluster_chars: List[str] = []
    pending_zwj = False
    ri_count = 0

    def emit(start: int, chars: List[str]) -> Tuple[int, str]:
        return start, "".join(chars)

    while i < n:
        ch = text[i]
        cp = ord(ch)

        if cluster_chars and ch == "\n" and cluster_chars[-1] == "\r":
            cluster_chars.append(ch)
            i += 1
            pending_zwj = False
            ri_count = 0
            continue

        if cluster_chars and unicodedata.category(ch).startswith("C") \
                and ch not in ("\t",):
            yield emit(cluster_start, cluster_chars)
            cluster_start = i
            cluster_chars = []
            pending_zwj = False
            ri_count = 0
            # 控制字符单独成簇
            cluster_chars.append(ch)
            i += 1
            continue

        if _is_zwj(ch):
            cluster_chars.append(ch)
            pending_zwj = True
            i += 1
            continue

        if _is_extend(ch) and cluster_chars:
            cluster_chars.append(ch)
            i += 1
            continue

        if _is_regional_indicator(ch) and ri_count % 2 == 1 and not pending_zwj:
            cluster_chars.append(ch)
            ri_count += 1
            i += 1
            continue

        if cluster_chars and not pending_zwj:
            yield emit(cluster_start, cluster_chars)

        cluster_start = i
        cluster_chars = [ch]
        pending_zwj = False
        ri_count = 1 if _is_regional_indicator(ch) else 0
        i += 1

    if cluster_chars:
        yield emit(cluster_start, cluster_chars)


def matching_ranges(text: str, query: str) -> List[range]:
    """返回字面匹配的范围列表，每个范围覆盖**完整 grapheme 簇**。

    对齐上游：
      - 空查询 -> 无匹配；
      - 匹配起点必须是某个 grapheme 簇的起点（``starts_with``）；
      - 终点扩展到第一个使 ``len >= len(query)`` 的簇尾（含 CJK/组合
        字符时不会切断半个字）；
      - 找不到时回退到 ``len(text)``。
    """
    if not query:
        return []
    if not text:
        return []

    clusters = list(iter_graphemes(text))
    out: List[range] = []
    qchars = len(query)
    for start, _ in clusters:
        if not text[start:].startswith(query):
            continue
        end = len(text)
        for off, grapheme in clusters:
            if off < start:
                continue
            candidate = off + len(grapheme)
            if candidate >= start + qchars:
                end = candidate
                break
        out.append(range(start, end))
    return out


def matching_ranges_backward(text: str, query: str,
                             before: int | None = None) -> List[range]:
    """本地化增强：Vim ``?`` 反向搜索的便利封装（上游由调用方负责导航）。

    只返回 ``before`` 之前、按位置升序排列的匹配；导航与游标移动仍由
    调用方处理，不越出上游职责边界。
    """
    all_ranges = matching_ranges(text, query)
    if before is None:
        return all_ranges
    return [r for r in all_ranges if r.start < before]
