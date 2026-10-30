"""测试 output_sanitize —— 输出净化 (emoji / pictograph 硬移除)。

覆盖:
  - _is_emoji (各 Unicode 区间边界)
  - strip_emoji (基本移除 / 计数 / 无可移除原样返回 / 空输入)
  - 保留排版符号 (箭头/勾叉/数学/制表/区块字符)
  - 变体选择符 / ZWJ 悬空字符清理
  - 行尾空白清理 (保留行首缩进)
  - has_emoji
"""

from __future__ import annotations

import pytest

from tuan_cli.core.output_sanitize import (
    _is_emoji,
    strip_emoji,
    has_emoji,
)


class TestIsEmoji:
    def test_main_emoji(self):
        assert _is_emoji("\U0001F600") is True  # 😀

    def test_misc_symbols(self):
        assert _is_emoji("\u26A0") is True  # ⚠

    def test_dingbats(self):
        assert _is_emoji("\u2705") is True  # ✅

    def test_arrow_geometry(self):
        assert _is_emoji("\u2B50") is True  # ⭐

    def test_variation_selector(self):
        assert _is_emoji("\uFE0F") is True  # VS16

    def test_range_boundaries(self):
        # 区间边界精确
        assert _is_emoji("\U0001F000") is True
        assert _is_emoji("\U0001FAFF") is True
        assert _is_emoji("\u2600") is True
        assert _is_emoji("\u26FF") is True
        assert _is_emoji("\u2700") is True
        assert _is_emoji("\u27BF") is True
        assert _is_emoji("\u2B00") is True
        assert _is_emoji("\u2BFF") is True

    def test_non_emoji(self):
        # 常规 ASCII / 中文 / 排版箭头 / 勾叉 / 数学符号 → 不是 emoji
        assert _is_emoji("a") is False
        assert _is_emoji("中") is False
        assert _is_emoji("→") is False  # 排版箭头保留
        assert _is_emoji("√") is False  # 数学符号保留
        assert _is_emoji("×") is False
        assert _is_emoji("\u2588") is False  # 区块字符保留


class TestStripEmoji:
    def test_empty(self):
        assert strip_emoji("") == ("", 0)
        assert strip_emoji(None) == (None, 0)

    def test_no_emoji_returns_original(self):
        s = "普通中文技术写作 -> 保持原样 √"
        out, n = strip_emoji(s)
        assert out == s
        assert n == 0

    def test_remove_single(self):
        # 移除 emoji 后行尾空白也一并清掉 (_TRAILING_WS)
        out, n = strip_emoji("完成 ✅")
        assert out == "完成"
        assert n == 1

    def test_remove_multi(self):
        out, n = strip_emoji("a😀b🎉c")
        assert out == "abc"
        assert n == 2

    def test_remove_pictograph(self):
        # ⚠ 计 1, 变体选择符 \uFE0F 计 1 → 共 2 (悬空变体选择符被清掉)
        out, n = strip_emoji("警告⚠️ 系统")
        assert out == "警告 系统"
        assert n == 2

    def test_zwj_dangling_removed(self):
        # ZWJ 序列: 👨‍👩‍👧 → 移除后 ZWJ 也一并清掉
        out, n = strip_emoji("家庭👨\u200d👩\u200d👧")
        assert out == "家庭"
        assert n >= 1

    def test_trailing_ws_cleaned(self):
        # 移除后行尾多余空白清掉, 行首缩进保留
        out, n = strip_emoji("第一步 ✅\n  第二步 🎉")
        assert out == "第一步\n  第二步"
        assert n == 2

    def test_leading_indent_preserved(self):
        out, _ = strip_emoji("  ✅ 完成")
        # 行首缩进保留; emoji 位于中间时其两侧空格也保留 (2 原缩进 + 2 空格)
        assert out == "   完成"

    def test_mixed_line_trailing_ws_cleaned(self):
        out, _ = strip_emoji("a ✅   \nb ✅  \n")
        assert out == "a\nb\n"

    def test_has_emoji(self):
        assert has_emoji("a😀b") is True
        assert has_emoji("普通文本") is False
        assert has_emoji("") is False
        assert has_emoji(None) is False


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v", "-p", "no:cacheprovider"]))
