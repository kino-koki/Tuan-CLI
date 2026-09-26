"""Read-before-Edit 守卫测试 (对标 Kimi Code v0.38.0)。"""

import json

from qingxiaotuan.core.kernel import Kernel
from qingxiaotuan.config import Config
from qingxiaotuan.tools import ToolRegistryPlugin, builtin_tool_plugins
from qingxiaotuan.tools.base import ToolContext


def _kernel_with_tools():
    k = Kernel()
    k.provide("config", Config(), owner="test")
    k.register(ToolRegistryPlugin())
    for p in builtin_tool_plugins():
        if p.name in ("tools.filesystem",):
            k.register(p)
    k.activate_all()
    return k


def _ctx(k, tmp_path):
    return ToolContext(kernel=k, workspace=str(tmp_path), confirm=lambda _p: True)


def test_edit_without_read_blocked(tmp_path):
    """未读文件直接 edit 被拦截。"""
    k = _kernel_with_tools()
    registry = k.require("tool_registry")
    ctx = _ctx(k, tmp_path)
    (tmp_path / "a.txt").write_text("hello", encoding="utf-8")
    out = registry.dispatch("edit_file", json.dumps(
        {"path": "a.txt", "old_string": "hello", "new_string": "HELLO"}), ctx)
    assert "请先 read_file" in out
    # 未写入
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "hello"


def test_edit_after_read_allowed(tmp_path):
    """read 之后再 edit 正常放行。"""
    k = _kernel_with_tools()
    registry = k.require("tool_registry")
    ctx = _ctx(k, tmp_path)
    (tmp_path / "a.txt").write_text("hello", encoding="utf-8")
    registry.dispatch("read_file", json.dumps({"path": "a.txt"}), ctx)
    out = registry.dispatch("edit_file", json.dumps(
        {"path": "a.txt", "old_string": "hello", "new_string": "HELLO"}), ctx)
    assert "已修改" in out
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "HELLO"


def test_write_without_read_blocked(tmp_path):
    """未读文件直接覆盖写被拦截。"""
    k = _kernel_with_tools()
    registry = k.require("tool_registry")
    ctx = _ctx(k, tmp_path)
    (tmp_path / "a.txt").write_text("old", encoding="utf-8")
    out = registry.dispatch("write_file", json.dumps(
        {"path": "a.txt", "content": "new"}), ctx)
    assert "请先 read_file" in out
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "old"


def test_guard_can_be_disabled(tmp_path):
    """配置 tools.require_read_before_edit: false 后守卫不生效。"""
    k = _kernel_with_tools()
    cfg = k.require("config")
    cfg.data.setdefault("tools", {})["require_read_before_edit"] = False
    registry = k.require("tool_registry")
    ctx = _ctx(k, tmp_path)
    (tmp_path / "a.txt").write_text("hello", encoding="utf-8")
    out = registry.dispatch("edit_file", json.dumps(
        {"path": "a.txt", "old_string": "hello", "new_string": "HELLO"}), ctx)
    assert "已修改" in out
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "HELLO"


def test_write_new_file_allowed(tmp_path):
    """新建文件 (磁盘上不存在) 无需先 read 即可写。"""
    k = _kernel_with_tools()
    registry = k.require("tool_registry")
    ctx = _ctx(k, tmp_path)
    out = registry.dispatch("write_file", json.dumps(
        {"path": "new.txt", "content": "brand new"}), ctx)
    assert "已写入" in out
    assert (tmp_path / "new.txt").read_text(encoding="utf-8") == "brand new"
