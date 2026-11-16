"""阶段 D —— 主题 token 单一来源一致性测试。

验证目标:
  1. 品牌色 (primary #63A8F8 / secondary #5BC0BE) 在 `ui/theme.py` **唯一**定义,
     其余模块一律 import token, 不再各自硬编码 (D2 主题统一)。
  2. 关键消费点 (splash / mascot / kimi_modules / tui / common) 的常量
     确实派生自 token —— 值相等, 但来源是 import 而非字面量。
  3. 渲染冒烟: C / PT_STYLE / blank_pt_style / 配色方案 可用且值正确。
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

PKG = Path(__file__).resolve().parents[1] / "tuan_cli"
THEME = PKG / "ui" / "theme.py"

BRAND_PRIMARY = "#63A8F8"
BRAND_SECONDARY = "#5BC0BE"

# 应派生自 token 的模块级常量 (模块相对路径 -> 属性名)。
# 这些模块**不得**再出现硬编码品牌色字面量。
TOKEN_CONSUMERS = {
    "ui/splash.py": ("_PRIMARY", "_ACCENT", "_DIM", "_TEXT"),
    "ui/mascot.py": ("_PRIMARY", "_ACCENT"),
    "tui/kimi_modules.py": ("_PRIMARY", "_ACCENT", "_TEXT", "_DIM"),
    "tui/tui.py": ("_PRIMARY", "_BLUE_DIM", "_ACCENT", "_ROLEUSER"),
    "tui/common.py": ("_PRIMARY", "_BLUE_DIM", "_ACCENT", "_ROLEUSER"),
}

# 允许保留品牌色字面量的文件 (独立语境: HTML CSS 模板 / 纯字符串测试 /
# theme.py 作为权威定义本身)。
BRAND_LITERAL_ALLOWED = {
    PKG / "tools" / "artifact_tool.py",
    THEME,
}


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _module_assigns(path: Path) -> dict:
    """提取模块顶层直接赋值的 {名称: 值表达式源码}。"""
    tree = ast.parse(_read_text(path))
    out = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    try:
                        out[t.id] = ast.get_source_segment(_read_text(path), node.value)
                    except Exception:  # noqa: BLE001
                        out[t.id] = None
    return out


class TestBrandSingleSource:
    def test_theme_defines_authoritative_tokens(self):
        """theme.py 必须定义唯一品牌色 token, 且等于既定品牌色值。"""
        assigns = _module_assigns(THEME)
        assert assigns.get("BRAND_PRIMARY") == f'"{BRAND_PRIMARY}"'
        assert assigns.get("BRAND_SECONDARY") == f'"{BRAND_SECONDARY}"'
        # 辅助强调与主色同源 (引用同一 token, 非独立字面量)
        assert assigns.get("BRAND_ACCENT") == "BRAND_PRIMARY"

    def test_c_dict_derives_from_tokens(self):
        """C 颜色表 primary/accent/roleuser 必须引用 token, 非字面量。"""
        assigns = _module_assigns(THEME)
        assert "C" in assigns
        # C 是 dict 字面量, 检查关键值引用 token
        src = _read_text(THEME)
        c_section = re.search(r"C = \{.*?\n\}", src, re.S).group(0)  # type: ignore[union-attr]
        for key in ("primary", "accent", "roleuser"):
            assert re.search(
                rf'"{key}":\s*BRAND_(?:PRIMARY|ACCENT)', c_section
            ), f"C['{key}'] 应派生自 BRAND_PRIMARY/BRAND_ACCENT"
        assert '"text": BRAND_TEXT' in c_section
        assert '"textdim": BRAND_DIM' in c_section

    def test_pt_style_derives_from_tokens(self):
        """PT_STYLE 标题/徽章/提示符必须引用 token。"""
        src = _read_text(THEME)
        pt_section = re.search(r"PT_STYLE = \{.*?\n\}", src, re.S).group(0)  # type: ignore[union-attr]
        for key in ("title", "badge", "badge-plan", "prompt", "text-area.prompt"):
            assert re.search(
                rf'"{key}":\s*BRAND_PRIMARY', pt_section
            ), f"PT_STYLE['{key}'] 应派生自 BRAND_PRIMARY"

    def test_color_schemes_use_tokens(self):
        """配色方案 blue/green 的 accent 必须引用 BRAND_SECONDARY。"""
        src = _read_text(THEME)
        assert '"blue": {"primary": BRAND_PRIMARY, "accent": BRAND_SECONDARY}' in src
        assert '"green": {"primary": "#4EC87E", "accent": BRAND_SECONDARY}' in src

    def test_blank_pt_style_uses_token(self):
        """blank_pt_style 内联 primary 必须为 token 派生。"""
        src = _read_text(THEME)
        # 循环体内赋值, 检查函数体引用 BRAND_PRIMARY
        func = re.search(r"def blank_pt_style\(\) -> dict:.*?\n(?=\n\S)", src, re.S)
        assert func, "未找到 blank_pt_style"
        assert "base[k] = BRAND_PRIMARY" in func.group(0)

    def test_diff_header_uses_token(self):
        src = _read_text(THEME)
        assert "DIFF_HEADER = BRAND_PRIMARY" in src


class TestConsumerDerivation:
    @pytest.mark.parametrize("rel,attrs", list(TOKEN_CONSUMERS.items()))
    def test_consumers_derive_and_no_hardcode(self, rel: str, attrs: tuple):
        """消费模块: 属性值 == token 值, 且模块内无硬编码品牌色字面量。"""
        path = PKG / rel
        src = _read_text(path)
        assigns = _module_assigns(path)

        # 1) 硬编码品牌色字面量不得出现在这些模块 (独立语境除外)
        #    注释里引用 #63A8F8 是文档说明, 允许; 仅检测代码赋值部分。
        code_only = "\n".join(
            ln for ln in src.splitlines() if not ln.strip().startswith("#")
        )
        assert "#63A8F8" not in code_only, f"{rel} 残留硬编码 #63A8F8"
        assert "#5BC0BE" not in code_only, f"{rel} 残留硬编码 #5BC0BE"

        # 2) 属性必须引用 token (import 派生), 值等于品牌色
        for attr in attrs:
            expr = assigns.get(attr)
            assert expr, f"{rel} 缺少 {attr}"
            # 引用形式 (BRAND_PRIMARY / BRAND_SECONDARY / ...) 而非字面量
            assert re.fullmatch(r"\w+", expr or ""), f"{rel}.{attr} 应为 token 引用, 实际 {expr}"
            # 该 token 必须被 import
            assert expr in src, f"{rel} 未 import {expr}"
            assert expr in _imported_names(src), f"{rel} 未导入 {expr}"

    def test_theme_itself_owns_primary_literal(self):
        """品牌色字面量仅允许出现在 theme.py 权威定义。"""
        # 全库扫描: tuan_cli 内非注释/非文档字符串的 #63A8F8 / #5BC0BE
        # 只允许在 theme.py (权威定义), 其余必须改为 import token。
        for py in PKG.rglob("*.py"):
            if py in BRAND_LITERAL_ALLOWED:
                continue
            code_only = _code_without_comments_and_docstrings(_read_text(py))
            for literal in ("#63A8F8", "#5BC0BE"):
                assert literal not in code_only, (
                    f"{py} 残留硬编码品牌色 {literal} (应改为 import token)"
                )


def _code_without_comments_and_docstrings(src: str) -> str:
    """剔除注释行与文档字符串, 保留字符串常量赋值 (供检测硬编码字面量)。

    策略: 逐行扫描, 跳过纯注释行; 再用 AST 定位文档字符串的区间并抹除。
    常量赋值 (如 ``_PRIMARY = "#63A8F8"``) 保留, 因此能捕获硬编码。
    """
    lines = src.splitlines()

    # 1) 定位所有文档字符串区间 (模块/函数/类首条语句) 并抹除
    tree = ast.parse(src)
    doc_ranges = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                if isinstance(body[0].value.value, str):
                    doc_ranges.append((body[0].lineno, body[0].end_lineno))
    for start, end in doc_ranges:
        for i in range(start, end + 1):
            if 1 <= i <= len(lines):
                lines[i - 1] = ""

    # 2) 逐行剔除纯注释行
    for i, ln in enumerate(lines):
        if ln.strip().startswith("#"):
            lines[i] = ""
    return "\n".join(lines)


def _imported_names(src: str) -> set:
    """收集 from ... import (A, B) 形式导入的名字。"""
    names = set()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            for a in node.names:
                names.add(a.asname or a.name)
        elif isinstance(node, ast.Import):
            for a in node.names:
                names.add((a.asname or a.name).split(".")[0])
    return names


class TestRenderSmoke:
    def test_c_is_valid(self):
        from tuan_cli.ui import theme
        assert theme.C["primary"] == BRAND_PRIMARY
        assert theme.C["accent"] == BRAND_PRIMARY
        assert theme.C["roleuser"] == BRAND_PRIMARY
        assert theme.C["text"] == "#E0E0E0"

    def test_pt_style_valid(self):
        from tuan_cli.ui import theme
        assert theme.PT_STYLE["title"] == BRAND_PRIMARY
        assert theme.PT_STYLE["prompt"] == BRAND_PRIMARY
        assert theme.blank_pt_style()["title"] == BRAND_PRIMARY

    def test_brand_dict(self):
        from tuan_cli.ui import theme
        assert theme.BRAND["primary"] == BRAND_PRIMARY
        assert theme.BRAND["accent"] == BRAND_PRIMARY
        assert theme.ACCENT_COLOR == BRAND_PRIMARY

    def test_color_scheme_switch(self):
        from tuan_cli.ui import theme
        theme.set_color("blue")
        assert theme.C["primary"] == BRAND_PRIMARY
        theme.set_color("brand")  # 还原
        assert theme.C["primary"] == BRAND_PRIMARY

    def test_consumer_values_match(self):
        """消费模块常量值 == token 值 (渲染一致性冒烟)。"""
        from tuan_cli.ui import mascot, splash, theme
        assert splash._PRIMARY == theme.BRAND_PRIMARY
        assert splash._ACCENT == theme.BRAND_SECONDARY
        assert mascot._PRIMARY == theme.BRAND_PRIMARY
        assert mascot._ACCENT == theme.BRAND_SECONDARY

        from tuan_cli.tui import common
        assert common._PRIMARY == theme.BRAND_PRIMARY
        assert common._ROLEUSER == theme.BRAND_PRIMARY
