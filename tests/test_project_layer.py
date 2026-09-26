"""B1: Project 层测试 —— init/info/list、隔离性、已有项目识别。"""

from __future__ import annotations

import json

from qingxiaotuan.core.project_layer import ProjectLayer


def test_init_creates_structure(tmp_path):
    ws = tmp_path / "proj"
    ws.mkdir()
    layer = ProjectLayer(ws)
    assert not layer.exists()
    info = layer.init()
    assert info.initialized is True
    assert info.project_id
    assert (ws / ".qxt" / "project.json").exists()
    assert (ws / ".qxt" / "config.yaml").exists()
    assert (ws / ".qxt" / "goal.json").exists()
    assert (ws / ".qxt" / "sessions.json").exists()
    assert (ws / ".qxt" / "snapshots").is_dir()
    assert (ws / "QXT.md").exists()  # 模板


def test_init_idempotent(tmp_path):
    ws = tmp_path / "proj"
    ws.mkdir()
    layer = ProjectLayer(ws)
    info1 = layer.init()
    info2 = layer.init()  # 已有项目不重复初始化
    assert info1.project_id == info2.project_id


def test_detect_existing_project(tmp_path):
    ws = tmp_path / "proj"
    ws.mkdir()
    assert ProjectLayer.detect(ws) is False
    ProjectLayer(ws).init()
    assert ProjectLayer.detect(ws) is True


def test_info_after_init(tmp_path):
    ws = tmp_path / "proj"
    ws.mkdir()
    layer = ProjectLayer(ws)
    layer.init()
    layer.attach_session("sess-1", "整理周报")
    info = layer.info()
    assert info.session_count == 1
    assert info.memory_count == 0  # 空 db


def test_list_projects_global_index(tmp_path, qxt_home):
    ws = tmp_path / "proj"
    ws.mkdir()
    ProjectLayer(ws).init()
    layer = ProjectLayer(tmp_path / "other")
    items = layer.list_projects()
    assert any(p["path"] == str(ws.resolve()) for p in items)


def test_isolation_between_projects(tmp_path):
    """不同目录的项目: 独立 .qxt / 独立 project_id / 会话不共享。"""
    ws1 = tmp_path / "p1"
    ws2 = tmp_path / "p2"
    ws1.mkdir()
    ws2.mkdir()
    l1 = ProjectLayer(ws1)
    l2 = ProjectLayer(ws2)
    i1 = l1.init()
    i2 = l2.init()
    assert i1.project_id != i2.project_id
    # p1 登记一个会话, p2 看不到
    l1.attach_session("sess-1")
    assert l1.info().session_count == 1
    assert l2.info().session_count == 0


def test_info_not_initialized(tmp_path):
    ws = tmp_path / "plain"
    ws.mkdir()
    info = ProjectLayer(ws).info()
    assert info.initialized is False
