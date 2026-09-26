"""edit_file multi-cut (多组替换) 回归测试。"""

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


def _read(registry, ctx, path):
    registry.dispatch("read_file", json.dumps({"path": path}), ctx)


def test_single_replace_backward_compatible(tmp_path):
    """旧方式 edit_file(path, old_string, new_string) 仍正常工作。"""
    k = _kernel_with_tools()
    registry = k.require("tool_registry")
    ctx = _ctx(k, tmp_path)
    registry.dispatch("write_file", json.dumps(
        {"path": "f.txt", "content": "alpha beta gamma"}), ctx)
    _read(registry, ctx, "f.txt")
    out = registry.dispatch("edit_file", json.dumps(
        {"path": "f.txt", "old_string": "beta", "new_string": "BETA"}), ctx)
    assert "已修改" in out
    assert "BETA" in (tmp_path / "f.txt").read_text(encoding="utf-8")
    assert "beta" not in (tmp_path / "f.txt").read_text(encoding="utf-8")


def test_multi_replace_success(tmp_path):
    """多组替换全部成功, 按序应用。"""
    k = _kernel_with_tools()
    registry = k.require("tool_registry")
    ctx = _ctx(k, tmp_path)
    registry.dispatch("write_file", json.dumps(
        {"path": "f.txt", "content": "foo bar baz"}), ctx)
    _read(registry, ctx, "f.txt")
    out = registry.dispatch("edit_file", json.dumps({"path": "f.txt", "replacements": [
        {"old_string": "foo", "new_string": "FOO"},
        {"old_string": "bar", "new_string": "BAR"},
    ]}), ctx)
    assert "已修改" in out
    assert "2 处替换" in out
    assert (tmp_path / "f.txt").read_text(encoding="utf-8") == "FOO BAR baz"


def test_multi_replace_rollback_on_missing(tmp_path):
    """任一组 old_string 未找到 -> 整体回滚, 不写入。"""
    k = _kernel_with_tools()
    registry = k.require("tool_registry")
    ctx = _ctx(k, tmp_path)
    registry.dispatch("write_file", json.dumps(
        {"path": "f.txt", "content": "foo bar"}), ctx)
    _read(registry, ctx, "f.txt")
    out = registry.dispatch("edit_file", json.dumps({"path": "f.txt", "replacements": [
        {"old_string": "foo", "new_string": "FOO"},
        {"old_string": "nope", "new_string": "NOPE"},
    ]}), ctx)
    assert "回滚" in out
    assert "未找到" in out
    # 文件内容保持原样 (foo 那组也没写入)
    assert (tmp_path / "f.txt").read_text(encoding="utf-8") == "foo bar"


def test_multi_replace_rollback_on_ambiguous(tmp_path):
    """任一组 old_string 不唯一 -> 整体回滚, 不写入。"""
    k = _kernel_with_tools()
    registry = k.require("tool_registry")
    ctx = _ctx(k, tmp_path)
    registry.dispatch("write_file", json.dumps(
        {"path": "f.txt", "content": "x x y"}), ctx)
    _read(registry, ctx, "f.txt")
    out = registry.dispatch("edit_file", json.dumps({"path": "f.txt", "replacements": [
        {"old_string": "x", "new_string": "X"},
        {"old_string": "y", "new_string": "Y"},
    ]}), ctx)
    assert "回滚" in out
    assert "不唯一" in out
    assert (tmp_path / "f.txt").read_text(encoding="utf-8") == "x x y"
