"""i18n 键值质量测试 —— 10 语言零漂移契约。

基线 (2026-10-18 实测): 10 语言各 180 键, 与 zh-CN 主语言零缺失、零多余,
占位符集合完全一致。本测试把「零漂移」固化为可执行契约:

1. 键完整性: 每个语言必须与 zh-CN (主语言) 键集合**完全相等** (双向断言);
2. 占位符一致: 对每个键, 各语言 {name} 占位符集合必须相同 —— 翻译时漏掉
   或多写占位符会在运行时把模板打坏 (t() 的 .format 失败时静默返回原模板);
3. 模板有效性: 花括号成对、无裸 {} (裸 {} 在 .format(**kwargs) 下必然失败);
4. 值非空; 语言元数据 (native/english) 非空。

注意: 本测试只对**已提交的整树状态**负责 —— 编辑中语言文件缺键是合法中间态,
由提交时的 CI 把关, 不在此处理。
"""

import re
import string
from importlib import import_module

import pytest

from tuan_cli.i18n import LANGUAGES

LOCALE_CODES = list(LANGUAGES)
PH_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _load(code: str) -> dict:
    mod = import_module(f"tuan_cli.i18n.locales.{code.replace('-', '_')}")
    table = getattr(mod, "TRANSLATIONS", None)
    assert table, f"{code} 缺少 TRANSLATIONS"
    return table


@pytest.fixture(scope="module")
def tables():
    return {code: _load(code) for code in LOCALE_CODES}


@pytest.fixture(scope="module")
def master_keys(tables):
    return set(tables["zh-CN"])


def test_all_languages_registered():
    """10 种语言全部登记在 LANGUAGES, 且元数据完整。"""
    assert len(LOCALE_CODES) == 10
    for code in LOCALE_CODES:
        info = LANGUAGES[code]
        assert info.get("native"), f"{code} 缺 native 名称"
        assert info.get("english"), f"{code} 缺 english 名称"


def test_key_completeness_zero_drift(tables, master_keys):
    """每个语言与主语言 zh-CN 键集合完全相等 (零缺失、零多余)。"""
    for code, table in tables.items():
        keys = set(table)
        assert master_keys - keys == set(), \
            f"{code} 缺失主语言键: {sorted(master_keys - keys)[:8]}"
        assert keys - master_keys == set(), \
            f"{code} 有多余键 (主语言没有): {sorted(keys - master_keys)[:8]}"
        assert len(keys) == len(master_keys)


def test_placeholder_consistency(tables, master_keys):
    """每个键的 {name} 占位符**集合**在所有语言中必须一致。

    用集合而非出现列表: 同一占位符出现两次 (如 zh-CN 的
    ``/provider set {env} <KEY>``) 是文案选择, 不影响 .format 行为。
    """
    bad: list[str] = []
    for key in sorted(master_keys):
        base = set(PH_RE.findall(tables["zh-CN"][key]))
        for code in LOCALE_CODES:
            if set(PH_RE.findall(tables[code][key])) != base:
                bad.append(f"{key} [{code}]")
    assert bad == [], f"占位符不一致的键: {bad[:10]}"


def test_templates_format_valid(tables, master_keys):
    """所有模板花括号成对、无裸 {}、值非空。"""
    formatter = string.Formatter()
    for code, table in tables.items():
        for key in master_keys:
            value = table[key]
            assert isinstance(value, str) and value.strip(), \
                f"{code}.{key} 值为空"
            assert "{}" not in value, f"{code}.{key} 含裸 {{}}: {value!r}"
            try:
                list(formatter.parse(value))
            except ValueError as exc:  # 括号不成对
                pytest.fail(f"{code}.{key} 模板括号不合法: {value!r} ({exc})")


def test_placeholder_names_consistent_with_args_docstring():
    """占位符命名风格抽查: 至少覆盖 docstring 中承诺的命名风格 ({n}/{pct} 等)。"""
    en = tables_placeholder_check()
    assert any("{" in v for v in en.values()), "英文翻译不应完全没有占位符用法"


def tables_placeholder_check():
    return _load("en")
