"""回归测试: 供应商目录与模型清单的结构完整性。

守护此前修复的两类 Bug:
1) 同名供应商被重复登记 (历史上出现过 sensenova 重名、azure-openai 在 B 区与 D 区重复);
   虽运行时 _dedup_presets 会掩盖, 但源文件里不应再出现同名条目。
2) 模型清单条目缺少 |free/|paid 标注 (如历史上的 sensenova-u1-fast 漏标)。

这两类问题都会导致"模型列表不统一 / 用户选不到正确模型", 故以测试锁死。
"""

import ast
import os
import re

import pytest

REPO = os.path.join(os.path.dirname(__file__), "..")
MODEL_LISTS_PATH = os.path.join(REPO, "tuan_cli", "models", "model_lists.py")
CATALOG_PATH = os.path.join(REPO, "tuan_cli", "models", "provider_catalog.py")


def _load_model_lists():
    src = open(MODEL_LISTS_PATH, encoding="utf-8").read()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.AnnAssign) and getattr(node.target, "id", "") == "MODEL_LISTS":
            return ast.literal_eval(node.value)
    raise AssertionError("MODEL_LISTS not found in model_lists.py")


def test_model_lists_entries_have_valid_tag():
    lists = _load_model_lists()
    bad = []
    for prov, models in lists.items():
        for m in models:
            if "|" not in m:
                bad.append((prov, m))
                continue
            _mid, tag = m.rsplit("|", 1)
            if tag not in ("free", "paid"):
                bad.append((prov, m))
    assert not bad, f"模型清单含非法条目 (缺 |free/|paid 或标签错误): {bad[:10]}"


def test_model_lists_no_within_section_duplicates():
    lists = _load_model_lists()
    bad = []
    for prov, models in lists.items():
        ids = [m.rsplit("|", 1)[0] for m in models]
        seen, dups = set(), set()
        for i in ids:
            if i in seen:
                dups.add(i)
            seen.add(i)
        if dups:
            bad.append((prov, sorted(dups)))
    assert not bad, f"模型清单含段内重复模型 ID: {bad[:10]}"


def test_catalog_no_duplicate_provider_names():
    src = open(CATALOG_PATH, encoding="utf-8").read()
    names = re.findall(r'\bname="([^"]+)"', src)
    dupes = sorted({n for n in set(names) if names.count(n) > 1})
    assert not dupes, f"供应商目录存在同名重复登记: {dupes}"
