# -*- coding: utf-8 -*-
"""ContextForge 磁盘索引缓存测试: save/load/is_fresh + engine 跨进程复用。"""
import time

from qingxiaotuan.codedev.engine import CodeDevEngine
from qingxiaotuan.codedev.retrieval import CodeIndex


def _seed_repo(root, extra=""):
    (root / "mod.py").write_text(
        "def add(a, b):\n    \"\"\"加法: 返回两数之和\"\"\"\n    return a + b\n\n"
        "class Calculator:\n    def mul(self, a, b):\n        \"\"\"乘法运算\"\"\"\n        return a * b\n" + extra,
        encoding="utf-8",
    )
    (root / "app.js").write_text(
        "function greet(name) {\n  return 'hi ' + name;\n}\n",
        encoding="utf-8",
    )


def test_save_load_roundtrip(tmp_path):
    _seed_repo(tmp_path)
    idx = CodeIndex().build(tmp_path)
    assert idx.files_scanned == 2
    cache = tmp_path / ".qxt" / "code_index.json"
    assert idx.save(cache) is True
    idx2 = CodeIndex.load(cache)
    assert idx2 is not None
    assert idx2.files_scanned == 2
    assert len(idx2.symbols) == len(idx.symbols)
    names = {s.name for s in idx2.symbols}
    assert {"add", "Calculator", "Calculator.mul", "greet"} <= names


def test_is_fresh(tmp_path):
    _seed_repo(tmp_path)
    idx = CodeIndex().build(tmp_path)
    assert idx.is_fresh(tmp_path) is True
    # 修改文件 → 不新鲜
    time.sleep(0.02)
    (tmp_path / "mod.py").write_text("x = 1\n", encoding="utf-8")
    assert idx.is_fresh(tmp_path) is False
    # 换 root → 不新鲜
    other = tmp_path / "other"
    other.mkdir()
    _seed_repo(other)
    assert idx.is_fresh(other) is False


def test_load_bad_cache(tmp_path):
    cache = tmp_path / "bad.json"
    cache.write_text("not json", encoding="utf-8")
    assert CodeIndex.load(cache) is None
    cache.write_text('{"version": 99}', encoding="utf-8")
    assert CodeIndex.load(cache) is None


def test_engine_uses_disk_cache(tmp_path):
    _seed_repo(tmp_path)
    e1 = CodeDevEngine(workspace=str(tmp_path), cache_index=False)
    r1 = e1.forge_context("加法", top_k=2)
    assert r1.hits and r1.hits[0].symbol.name == "add"
    # 磁盘缓存文件已生成
    disk = tmp_path / ".qxt" / "code_index.json"
    assert disk.exists()
    # 新引擎实例 (跨进程模拟) 直接复用磁盘索引
    e2 = CodeDevEngine(workspace=str(tmp_path), cache_index=False)
    r2 = e2.forge_context("乘法", top_k=2)
    assert any(h.symbol.name == "Calculator.mul" for h in r2.hits)
    # 修改源文件后索引自动失效重建
    time.sleep(0.02)
    (tmp_path / "mod.py").write_text("def sub(a, b):\n    return a - b\n", encoding="utf-8")
    e3 = CodeDevEngine(workspace=str(tmp_path), cache_index=False)
    r3 = e3.forge_context("减法", top_k=2)
    assert any(h.symbol.name == "sub" for h in r3.hits)
