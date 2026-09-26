"""diff_preview 工具测试 (对标 Claude Code /diff 实时面板)。"""

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


def test_diff_preview_returns_unified_diff(tmp_path):
    """返回合法 unified diff (含 ---/+++/@@ 头与 +/- 行)。"""
    k = _kernel_with_tools()
    registry = k.require("tool_registry")
    ctx = _ctx(k, tmp_path)
    (tmp_path / "f.txt").write_text("line1\nline2\nline3\n", encoding="utf-8")
    out = registry.dispatch("diff_preview", json.dumps(
        {"path": "f.txt", "old_string": "line2", "new_string": "LINE2"}), ctx)
    assert "---" in out
    assert "+++" in out
    assert "@@" in out
    assert "-line2" in out
    assert "+LINE2" in out


def test_diff_preview_does_not_modify_file(tmp_path):
    """预览不修改文件内容。"""
    k = _kernel_with_tools()
    registry = k.require("tool_registry")
    ctx = _ctx(k, tmp_path)
    original = "alpha\nbeta\ngamma\n"
    (tmp_path / "f.txt").write_text(original, encoding="utf-8")
    registry.dispatch("diff_preview", json.dumps(
        {"path": "f.txt", "old_string": "beta", "new_string": "BETA"}), ctx)
    assert (tmp_path / "f.txt").read_text(encoding="utf-8") == original


def test_diff_preview_multi_replace(tmp_path):
    """多组替换预览同时展示两处改动。"""
    k = _kernel_with_tools()
    registry = k.require("tool_registry")
    ctx = _ctx(k, tmp_path)
    (tmp_path / "f.txt").write_text("foo bar baz\n", encoding="utf-8")
    out = registry.dispatch("diff_preview", json.dumps({"path": "f.txt", "replacements": [
        {"old_string": "foo", "new_string": "FOO"},
        {"old_string": "bar", "new_string": "BAR"},
    ]}), ctx)
    assert "+FOO BAR baz" in out
    assert "-foo bar baz" in out
    # 仍未写盘
    assert (tmp_path / "f.txt").read_text(encoding="utf-8") == "foo bar baz\n"
