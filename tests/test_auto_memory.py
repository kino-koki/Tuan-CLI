"""Auto Memory 自动记忆系统测试。

覆盖:
- 规则启发式分类 (user/feedback/project/reference)
- 去重写入
- 按 kind 检索
- 配置开关
- /memory 斜杠命令 (list/add)
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from qingxiaotuan.memory.auto_extractor import AutoMemoryExtractor
from qingxiaotuan.memory.store import MEMORY_KINDS, MemoryStore


# ------------------------------------------------------------------ 分类规则

def test_extract_user_preference() -> None:
    """'我喜欢用中文回复' 应被识别为 user 类偏好。"""
    ex = AutoMemoryExtractor()
    assert ex.classify("我喜欢用中文回复") == "user"
    assert ex.classify("我偏好 tabs 而非 spaces") == "user"


def test_extract_feedback() -> None:
    """'不对，应该用 pytest' 应被识别为 feedback 类纠正。"""
    ex = AutoMemoryExtractor()
    assert ex.classify("不对，应该用 pytest") == "feedback"
    assert ex.classify("不要用 sudo") == "feedback"


def test_extract_project_decision() -> None:
    """'我们决定用 PostgreSQL' 应被识别为 project 类决策。"""
    ex = AutoMemoryExtractor()
    assert ex.classify("我们决定用 PostgreSQL") == "project"


def test_extract_reference_fact() -> None:
    """URL / 版本号应被识别为 reference。"""
    ex = AutoMemoryExtractor()
    assert ex.classify("项目文档地址是 https://example.com/docs") == "reference"


# ------------------------------------------------------------------ 写入与去重

def test_dedup_similar_memory(tmp_path: Path) -> None:
    """相似内容不重复写入。"""
    store = MemoryStore(tmp_path, fts_enabled=True)
    id1 = store.add_auto_memory("用户喜欢用中文回复", kind="user", source="auto")
    assert id1 is not None
    # 高度相似的第二条应被去重拦截
    id2 = store.add_auto_memory("用户喜欢用中文回复", kind="user", source="auto")
    assert id2 is None
    # 同一内容但不同 kind 不算重复 (分类不同)
    id3 = store.add_auto_memory("用户喜欢用中文回复", kind="feedback", source="auto")
    assert id3 is not None


def test_search_by_kind(tmp_path: Path) -> None:
    """按 kind 检索正常。"""
    store = MemoryStore(tmp_path, fts_enabled=True)
    store.add_auto_memory("用户偏好中文回复", kind="user")
    store.add_auto_memory("项目决定用 PostgreSQL", kind="project")
    store.add_auto_memory("不要用 sudo", kind="feedback")

    user_hits = store.search_by_kind("user")
    assert len(user_hits) == 1
    assert "中文回复" in user_hits[0]["content"]
    assert user_hits[0]["kind"] == "user"

    proj_hits = store.search_by_kind("project")
    assert len(proj_hits) == 1
    assert "PostgreSQL" in proj_hits[0]["content"]

    # query 过滤
    fb = store.search_by_kind("feedback", query="sudo")
    assert len(fb) == 1
    fb_none = store.search_by_kind("feedback", query="python")
    assert fb_none == []


def test_auto_extract_can_be_disabled(tmp_path: Path) -> None:
    """配置 memory.auto_extract=false 后不自动提取。"""
    store = MemoryStore(tmp_path, fts_enabled=True)
    ex_on = AutoMemoryExtractor(store=store, enabled=True)
    written = ex_on.process_turn("我喜欢用中文回复")
    assert len(written) == 1

    ex_off = AutoMemoryExtractor(store=store, enabled=False)
    written2 = ex_off.process_turn("我喜欢用 Markdown 输出")
    assert written2 == []
    # disabled 后 extract 本身也应返回空
    assert ex_off.extract("我喜欢用 Markdown 输出") == []


def test_process_turn_end_to_end(tmp_path: Path) -> None:
    """process_turn 从用户消息抽取并落盘, 结果可被 search_by_kind 命中。"""
    store = MemoryStore(tmp_path, fts_enabled=True)
    ex = AutoMemoryExtractor(store=store, enabled=True)
    written = ex.process_turn("不对，应该用 pytest 而不是 unittest")
    assert len(written) == 1
    assert written[0]["kind"] == "feedback"
    # 落盘后可按 kind 检索到
    hits = store.search_by_kind("feedback", query="pytest")
    assert hits and "pytest" in hits[0]["content"]


# ------------------------------------------------------------------ /memory 斜杠命令

def _make_fake_agent(tmp_path: Path):
    """构造最小 fake agent/config 供 /memory 斜杠命令测试。"""
    store = MemoryStore(tmp_path, fts_enabled=True)
    kernel = SimpleNamespace(get=lambda name: store if name == "memory_store" else None)
    config = SimpleNamespace(
        _values={},
        get=lambda key, default=None: default,
        set_user=lambda key, val: None,
    )
    agent = SimpleNamespace(kernel=kernel)
    return agent, config, store


def test_memory_slash_list(tmp_path: Path, capsys) -> None:
    """/memory list 输出正常 (rich 表格不抛异常)。"""
    from qingxiaotuan.cli.cmd_slash import _cmd_memory

    agent, config, store = _make_fake_agent(tmp_path)
    store.add_auto_memory("用户偏好中文回复", kind="user")
    store.add_auto_memory("项目决定用 pytest", kind="project")

    # list 全部
    _cmd_memory(agent, config, "list")
    # list 按 kind 过滤
    _cmd_memory(agent, config, "list user")
    # list 非法 kind
    _cmd_memory(agent, config, "list bogus")
    # 不抛异常即通过


def test_memory_slash_add(tmp_path: Path) -> None:
    """/memory add 正常写入。"""
    from qingxiaotuan.cli.cmd_slash import _cmd_memory

    agent, config, store = _make_fake_agent(tmp_path)
    _cmd_memory(agent, config, "add reference 文档地址 https://example.com/docs")
    hits = store.search_by_kind("reference")
    assert hits and "example.com" in hits[0]["content"]

    # 非法 kind
    before = store.get_stats()["tag_entries"]
    _cmd_memory(agent, config, "add bogus 随便写点什么")
    after = store.get_stats()["tag_entries"]
    assert before == after, "非法 kind 不应写入"


def test_memory_slash_delete(tmp_path: Path) -> None:
    """/memory delete 按 id 删除。"""
    from qingxiaotuan.cli.cmd_slash import _cmd_memory

    agent, config, store = _make_fake_agent(tmp_path)
    new_id = store.add_auto_memory("待删除的临时记忆", kind="reference")
    assert new_id is not None
    _cmd_memory(agent, config, f"delete {new_id}")
    assert store.list_by_kind() == []


def test_memory_slash_on_off(tmp_path: Path) -> None:
    """/memory on|off 写配置。"""
    from qingxiaotuan.cli.cmd_slash import _cmd_memory

    captured = {}
    store = MemoryStore(tmp_path, fts_enabled=True)
    kernel = SimpleNamespace(get=lambda name: store if name == "memory_store" else None)
    config = SimpleNamespace(
        get=lambda key, default=None: default,
        set_user=lambda key, val: captured.update({key: val}),
    )
    agent = SimpleNamespace(kernel=kernel)
    _cmd_memory(agent, config, "off")
    assert captured.get("memory.auto_extract") is False
    _cmd_memory(agent, config, "on")
    assert captured.get("memory.auto_extract") is True
