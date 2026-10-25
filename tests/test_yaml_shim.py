"""``tuan_cli._yaml`` stdlib 子集解析器的差分测试。

**本文件必须调 ``_stdlib_safe_load`` / ``_stdlib_safe_dump``, 绝不能调 ``safe_load``。**

原因: ``_yaml.py`` 模块末尾有一段后端选择逻辑 —— PyYAML 可用时它会把
``safe_load`` / ``load`` / ``safe_load_all`` / ``dump`` 等名字**重绑定到 PyYAML**。
于是如果测试写 ``from tuan_cli import _yaml; _yaml.safe_load(...)`` 再跟 ``yaml.safe_load``
比较, 在装了 PyYAML 的环境里等于让 PyYAML 跟自己比:

- 永远绿灯, 拦不住 stdlib 后端的任何回归;
- 历史上那次"YAML 差分 5/5 全部通过"就是这样造成的**假阴性**, 让一个真实崩溃
  (``yes: 1`` 触发 ``AttributeError: 'bool' object has no attribute 'strip'``) 漏网。

下面的 ``SHIM`` / ``SHIM_DUMP`` 直接从模块私有名取 stdlib 内核, 不受重绑定影响。
"""

from __future__ import annotations

import math

import pytest

import yaml as pyyaml

from tuan_cli import _yaml

# 注意: 这两个是**测试专用别名**, 指向 stdlib 内核, 不受 PyYAML 重绑定影响。
SHIM = _yaml._stdlib_safe_load
SHIM_DUMP = _yaml._stdlib_safe_dump


# --------------------------------------------------------------------------- #
# 方法论自证: 防止有人把别名换成 safe_load 后测试继续假绿灯
# --------------------------------------------------------------------------- #
def test_shim_alias_is_not_pyyaml():
    """别名必须是 stdlib 内核, 而不是被重绑定到 PyYAML。"""
    assert SHIM is not pyyaml.safe_load
    assert SHIM.__module__ == _yaml.__name__
    assert SHIM.__name__ == "_impl_safe_load"
    # 同时确认真实后端状态被记录, 便于排查环境
    assert _yaml._BACKEND in ("pyyaml", "stdlib")


def test_shim_handles_anchors_with_line_numbered_error():
    """不支持的构造必须抛出带行号的错误, 而不是静默给错数据。"""
    with pytest.raises(_yaml.YAMLError) as exc:
        SHIM("a: &x {n: 1}\nb: *x\n")
    assert "1" in str(exc.value), str(exc.value)
    with pytest.raises(_yaml.YAMLError) as exc2:
        SHIM("b: *missing\n")
    assert "1" in str(exc2.value)


# --------------------------------------------------------------------------- #
# 与 PyYAML 的差分 (仅取本模块声称支持的构造)
# --------------------------------------------------------------------------- #
SUPPORTED_CONSTRUCTS = [
    "k: 1\n",
    "a: 1\nb: 2\n",
    "a:\n  - 1\n  - 2\n",
    # 与父键同缩进的序列 (0.3.2 修掉的静默 None 缺陷)
    "a:\n- 1\n- 2\n",
    "- key: value\n- key2: value2\n",
    "list: [1, 2, 3]\n",
    "map: {a: 1, b: 2}\n",
    "q: 'single quoted'\n",
    'q2: "double quoted"\n',
    "esc: \"a\\nb\"\n",
    "flag: true\nval: false\nz: ~\n",
    "i: 42\nf: 3.14\nneg: -7\nexp: 1e3\n",
    "cmd: |\n  echo hi\n  echo yo\n",
    "cmd2: >\n  line one\n  line two\n",
    "comment: # not a comment\n",
    "# top comment\nk: v\n",
    "a: 1 # trailing\nb: 2\n",
    "plain: first\n  second\n  third\n",
    "---\nk: v\n",
    "a: {b: {c: 1}}\n",
    "empty_val:\n",
    "seq_of_maps:\n  - name: a\n    v: 1\n  - name: b\n    v: 2\n",
    "b1: [1, 2]\nb2: [3]\nb3: {x: 1, y: 2}\n",
    "deep: {a: {b: {c: 1}}}\n",
]


@pytest.mark.parametrize("text", SUPPORTED_CONSTRUCTS, ids=repr)
def test_supported_construct_matches_pyyaml(text):
    assert SHIM(text) == pyyaml.safe_load(text)


# --------------------------------------------------------------------------- #
# 已知有意分歧: 明确断言, 防止被"顺手"改成跟 PyYAML 一致
# --------------------------------------------------------------------------- #
def test_intentional_divergence_yaml11_octal():
    """YAML 1.1 八进制不实现 (与六十进制同属反直觉行为), 保留为字符串。"""
    assert SHIM("num: 017\n") == {"num": "017"}
    assert pyyaml.safe_load("num: 017\n") == {"num": 15}


def test_intentional_divergence_keys_are_strings():
    """映射键一律字符串, 跟随 YAML 1.2 核心 schema。"""
    got = SHIM("yes: 1\nno: 1\nnull: 1\non: 1\n")
    assert got == {"yes": 1, "no": 1, "null": 1, "on": 1}
    assert set(got) == {"yes", "no", "null", "on"}


def test_key_reserved_words_do_not_crash():
    """0.3.2 修掉的真实崩溃: 保留词做键时曾抛 AttributeError 而非 YAMLError。

    根因是键被二次类型推断成 bool/None, 后续 ``.strip()`` 直接炸。
    """
    for kw in ("yes", "no", "on", "off", "true", "false", "null", "nil", "none", "0", "1"):
        got = SHIM(f"{kw}: value\n")
        assert got == {kw: "value"}, f"key {kw!r} -> {got!r}"


def test_flow_mapping_keys_are_strings():
    got = SHIM("m: {yes: 1, null: 2}\n")
    assert got == {"m": {"yes": 1, "null": 2}}


def test_quoted_keys_stay_quoted_semantics():
    got = SHIM("'true': 1\n\"null\": 2\n")
    assert got == {"true": 1, "null": 2}


# --------------------------------------------------------------------------- #
# dump / load 往返
# --------------------------------------------------------------------------- #
ROUNDTRIP_DOCS = [
    {"model": {"provider": "deepseek", "model": "x"}, "agent": {"max_iterations": 12}},
    {"list": [1, "two", True, None, 3.5]},
    {"nested": {"a": {"b": [1, 2]}}},
    {"block": "line1\nline2\n"},
    {"empty": {}},
    {"arr": []},
    {"empty_key": ""},
    # 保留词作键必须能往返, 这是 0.3.2 崩溃回归的守卫
    {"yes": 1, "no": 0, "true": False, "null": None},
]


@pytest.mark.parametrize("doc", ROUNDTRIP_DOCS, ids=repr)
def test_dump_load_roundtrip(doc):
    assert SHIM(SHIM_DUMP(doc)) == doc


def test_dump_load_roundtrip_matches_pyyaml_dump():
    """双向互操作: shim 的 dump 能被 PyYAML 解析出同样的值。

    刻意不含含换行的标量 —— 跨行引号标量属本模块声明不支持的构造
    (见模块 docstring「不支持」一节), PyYAML 会用单引号多行折叠表示, shim 不解析。
    """
    doc = {"a": [1, 2, 3], "b": {"c": True}, "yes": "yes", "num": 42}
    assert SHIM(pyyaml.safe_dump(doc)) == doc
    assert pyyaml.safe_load(SHIM_DUMP(doc)) == doc


def test_multiline_quoted_scalar_is_documented_limitation():
    """跨行引号标量不在支持范围内 —— 明确记录, 防止被当成回归。

    PyYAML 把 ``"x\\ny"`` dump 成单引号多行折叠形态, shim 不支持跨行引号, 解析结果
    会带出引号字符。这不是静默错误 (结果可肉眼看出不对), 但确实不是 PyYAML 兼容行为。
    真实配置里跨行文本应该用块标量 ``|`` / ``>``, 那部分 shim 是支持的。
    """
    text = pyyaml.safe_dump({"note": "x\ny"})
    assert text.count("\n") > 2, repr(text)  # 确实是多行折叠形态, 而非单行
    assert SHIM(text) != pyyaml.safe_load(text), "跨行引号标量确实不支持"
    # 块标量的三种收尾方式 (clip / strip / keep) shim 与 PyYAML 一致
    for t in ("a: |\n  x\n  y\n", "a: |-\n  x\n  y\n", "a: |+\n  x\n  y\n\n"):
        assert SHIM(t) == pyyaml.safe_load(t), repr(t)


# --------------------------------------------------------------------------- #
# 错误消息可诊断性
# --------------------------------------------------------------------------- #
def test_errors_mention_line_number():
    for bad in ("    a: 1\n", "a: 1\n  b: 2\n    c: 3\n", "{a: 1, b: }\n"):
        try:
            SHIM(bad)
        except Exception as exc:  # noqa: BLE001
            assert ("行" in str(exc)) or ("line" in str(exc).lower()), str(exc)


def test_nan_and_inf_survive_dump():
    doc = {"n": float("nan"), "p": float("inf"), "m": float("-inf")}
    text = SHIM_DUMP(doc)
    back = SHIM(text)
    assert math.isnan(back["n"]) and back["p"] == float("inf") and back["m"] == float("-inf")
