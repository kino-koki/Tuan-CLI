"""源码卫生回归测试: 编码洁净 + rules_engine 表达式语义。

覆盖两个真实缺陷:

1. UTF-8 BOM —— 11 个源文件曾带文件头 BOM。CPython 解释器容忍文件头 BOM,
   所以模块能正常 import; 但 ``ast.parse`` / 从字符串 ``compile`` / 任何按
   文本读源码的静态分析 (包括本项目自己的 ``ext/ast_scan.py``) 都会抛
   ``SyntaxError: invalid non-printable character U+FEFF``。这里把"全量源码
   可被 ast 解析"固化为门禁, 防止 BOM 或任何非打印控制字符回流。

2. rules_engine 算术与谓词语义 —— ``CODE_REVIEW.md`` §11 曾把
   ``len(x) > 5 + 3`` 这类含算术的规则记为"静默丢弃多余 token"的残留缺陷。
   复核源码后确认递归下降解析器已实现完整优先级 (multiplicative > additive
   > compare), 且 ``matches`` / ``regex_contains`` 已统一为
   ``(subject, pattern)`` 语义。这里用回归用例把这两条锁死。
"""

from __future__ import annotations

import ast
import pathlib

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC_ROOT = REPO_ROOT / "tuan_cli"


# ---------------------------------------------------------------- 编码卫生


def _source_files() -> list[pathlib.Path]:
    """所有包内 .py 源码 (排除 __pycache__ 编译产物)。"""
    return [
        p
        for p in sorted(SRC_ROOT.rglob("*.py"))
        if "__pycache__" not in p.parts
    ]


def test_no_utf8_bom_in_source_files() -> None:
    """任何源文件都不允许带 UTF-8 BOM。"""
    offenders = [
        str(p.relative_to(REPO_ROOT))
        for p in _source_files()
        if p.read_bytes()[:3] == b"\xef\xbb\xbf"
    ]
    assert not offenders, (
        f"以下源文件带 UTF-8 BOM, 会破坏 ast.parse / py_compile 字符串编译: "
        f"{offenders}"
    )


def test_all_source_files_parse_with_ast() -> None:
    """全量源码必须能被 ast.parse 解析 (等价于'对文本管道可读')。"""
    failures: list[str] = []
    for p in _source_files():
        try:
            ast.parse(p.read_text(encoding="utf-8"))
        except SyntaxError as exc:
            failures.append(f"{p.relative_to(REPO_ROOT)}:{exc.lineno}: {exc.msg}")
    assert not failures, f"ast.parse 失败 {len(failures)} 个文件:\n" + "\n".join(failures)


def test_no_stray_control_characters_in_source() -> None:
    """除 \\t \\n \\r 外的控制字符不允许出现在源码中。

    控制字符最常见的来源就是粘贴自别处文本时带入的 BOM / 零宽空格 /
    NBSP, 它们不会让解释器报错, 但会让 diff、搜索、正则全部静默失效。
    """
    allowed = {0x09, 0x0A, 0x0D}  # \t \n \r
    offenders: list[str] = []
    for p in _source_files():
        text = p.read_text(encoding="utf-8", errors="replace")
        for lineno, line in enumerate(text.split("\n"), start=1):
            for ch in line:
                if ord(ch) < 0x20 and ord(ch) not in allowed:
                    offenders.append(f"{p.relative_to(REPO_ROOT)}:{lineno}: U+{ord(ch):04X}")
                    break
    assert not offenders, f"发现非打印控制字符: {offenders[:20]}"


# ---------------------------------------------------------------- rules_engine


@pytest.fixture(scope="module")
def rules() -> tuple:
    from tuan_cli.ext.rules_engine import _Parser, _eval, _tokenize

    return _tokenize, _Parser, _eval


def _eval_expr(rules, expr: str, scope: dict):
    _tokenize, _Parser, _eval = rules
    return _eval(_Parser(_tokenize(expr)).parse(), scope)


class TestArithmeticPrecedence:
    """算术运算符必须实现完整递归下降优先级, 不再静默丢弃 token。"""

    def test_addition_inside_comparison(self, rules):
        # len("abcdefgh") == 8; 8 > 5 + 3 == 8  -> False
        assert _eval_expr(rules, "len(text) > 5 + 3", {"text": "abcdefgh"}) is False

    def test_subtraction_and_multiplication_precedence(self, rules):
        # 10 - 4 * 2 == 2; len == 8 >= 2 -> True
        assert _eval_expr(rules, "len(text) >= 10 - 4 * 2", {"text": "abcdefgh"}) is True

    def test_parentheses_override_precedence(self, rules):
        assert _eval_expr(rules, "(1 + 2) * 3 > 5", {}) is True

    def test_repeated_operators_associate_left(self, rules):
        # 2 + 3 + 4 == 9 > 8
        assert _eval_expr(rules, "2 + 3 + 4 > 8", {}) is True

    def test_arithmetic_inside_function_argument(self, rules):
        # min_len(text, 2+1) == len >= 3 -> "hello" 通过
        assert _eval_expr(rules, "min_len(text, 2 + 1) && max_len(text, 10)",
                          {"text": "hello"}) is True


class TestPredicateSemantics:
    """matches / regex_contains 统一为 (subject, pattern) 语义, 不再抛 AttributeError。"""

    def test_matches_subject_pattern(self, rules):
        assert _eval_expr(rules, 'matches(text, "^[a-z]+$")', {"text": "hello"}) is True
        assert _eval_expr(rules, 'matches(text, "^[a-z]+$")', {"text": "hello1"}) is False

    def test_regex_contains_string_pattern(self, rules):
        assert _eval_expr(rules, r'regex_contains(text, "\d+")', {"text": "abc123"}) is True
        assert _eval_expr(rules, r'regex_contains(text, "\d+")', {"text": "abc"}) is False

    def test_invalid_regex_returns_false_not_raise(self, rules):
        # 危险/非法正则应视为不匹配, 而不是让整条规则记为 eval error
        assert _eval_expr(rules, r'regex_contains(text, "(")', {"text": "abc"}) is False

    def test_boolean_short_circuit(self, rules):
        assert _eval_expr(rules, 'matches(text, "^x$") || len(text) > 0', {"text": "abc"}) is True
        assert _eval_expr(rules, 'matches(text, "^x$") && len(text) > 10', {"text": "abc"}) is False


class TestEngineLevel:
    """引擎入口的 validate / check / enforce 语义闭环。"""

    def test_validate_accepts_arithmetic_assert(self, rules, tmp_path):
        from tuan_cli.ext.rules_engine import RuleEngine

        yaml_text = (
            "- id: r1\n"
            "  severity: warn\n"
            "  match: {content: \"alpha\"}\n"
            "  assert: 'contains(content, \"alpha\") && len(content) > 4 + 1'\n"
            "  message: 'alpha present'\n"
            "- id: r2\n"
            "  severity: error\n"
            "  match: {path: \"*.py\"}\n"
            "  assert: 'contains(content, \"eval(\")'\n"
            "  message: 'eval forbidden'\n"
        )
        eng = RuleEngine()
        assert eng.load_yaml_text(yaml_text) == 2
        assert eng.validate() == {"valid": True, "issues": []}

    def test_check_flags_violation(self, rules):
        """``assert`` 是正向断言 (必须成立); 禁止式规则要写 ``not contains(...)``。"""
        from tuan_cli.ext.rules_engine import RuleEngine

        eng = RuleEngine()
        eng.load_yaml_text(
            "- id: r2\n"
            "  severity: error\n"
            "  match: {path: \"*.py\"}\n"
            "  assert: 'not contains(content, \"eval(\")'\n"
            "  message: 'eval forbidden'\n"
        )
        violations = eng.check("a/b.py", "eval('1+1')")
        assert len(violations) == 1
        assert violations[0]["id"] == "r2"
        assert violations[0]["severity"] == "error"

        # 干净文件: 断言成立, 零违规
        assert eng.check("a/b.py", "print('ok')") == []

    def test_enforce_blocks_error_severity(self, rules):
        from tuan_cli.ext.rules_engine import RuleEngine

        eng = RuleEngine()
        eng.load_yaml_text(
            "- id: r2\n"
            "  severity: error\n"
            "  match: {path: \"*.py\"}\n"
            "  assert: 'not contains(content, \"eval(\")'\n"
            "  message: 'eval forbidden'\n"
        )
        assert eng.enforce("eval('x')", "a/b.py") is not None
        assert eng.enforce("print('ok')", "a/b.py") is None

    def test_hit_lines_points_at_offending_line(self, rules):
        from tuan_cli.ext.rules_engine import RuleEngine

        eng = RuleEngine()
        eng.load_yaml_text(
            "- id: r3\n"
            "  severity: warn\n"
            "  match: {content: \"\"}\n"
            "  assert: 'not contains(content, \"banana\")'\n"
            "  message: 'banana forbidden'\n"
        )
        content = "apple\n\nbanana\ncherry\n"
        violations = eng.check("x.txt", content)
        assert violations and violations[0]["hit_lines"] == [3]
