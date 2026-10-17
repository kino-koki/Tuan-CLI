"""快速读写工具测试: read_files (并行批量读) / edit_files (事务性多文件编辑)。

对标 Freebuff/Codebuff 工程做法:
- read_files: 一次往返并行拿 N 个文件, 单文件失败互不影响, 成功即 mark_read;
- edit_files: 两阶段事务 —— 全部校验通过才落盘, 任一不匹配/未读整体拒绝, 零变化。
"""

import json
import time

import pytest

from tuan_cli.core.kernel import Kernel
from tuan_cli.config import Config
from tuan_cli.tools import ToolRegistryPlugin, builtin_tool_plugins
from tuan_cli.tools.base import ToolContext
import tuan_cli.tools.filesystem as fsmod


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


# ================================================================== read_files

def test_read_files_merges_multiple(tmp_path):
    """多文件内容正确合并为 === path === 块。"""
    k = _kernel_with_tools()
    reg = k.require("tool_registry")
    ctx = _ctx(k, tmp_path)
    (tmp_path / "a.txt").write_text("AAA\n", encoding="utf-8")
    (tmp_path / "b.txt").write_text("BBB\n", encoding="utf-8")
    out = reg.dispatch("read_files", json.dumps({"paths": ["a.txt", "b.txt"]}), ctx)
    assert "=== a.txt ===" in out
    assert "=== b.txt ===" in out
    assert "AAA" in out
    assert "BBB" in out


def test_read_files_parallel_faster_than_serial(tmp_path, monkeypatch):
    """并行性: 用可控 sleep 的 worker 证明墙钟明显小于串行 (CI 稳定, 不依赖磁盘)。"""
    k = _kernel_with_tools()
    reg = k.require("tool_registry")
    ctx = _ctx(k, tmp_path)
    paths = [f"f{i}.txt" for i in range(8)]
    for p in paths:
        (tmp_path / p).write_text("x", encoding="utf-8")

    def fake_worker(ctx, path, offset, limit, max_bytes):
        time.sleep(0.1)  # 模拟每个文件的 I/O/处理延迟
        return f"=== {path} ===\nbody-{path}"

    monkeypatch.setattr(fsmod, "_read_one_file", fake_worker)

    t0 = time.perf_counter()
    out = reg.dispatch("read_files", json.dumps({"paths": paths, "max_workers": 8}), ctx)
    wall_parallel = time.perf_counter() - t0
    assert "=== f0.txt ===" in out and "=== f7.txt ===" in out

    t0 = time.perf_counter()
    reg.dispatch("read_files", json.dumps({"paths": paths, "max_workers": 1}), ctx)
    wall_serial = time.perf_counter() - t0

    # 8 个 0.1s 任务: 8 线程并行应 ~0.1s; 单线程串行应 ~0.8s
    assert wall_parallel < 0.45, f"并行读墙钟过长: {wall_parallel:.2f}s"
    assert wall_serial > 0.6, f"串行读墙钟过短 (未串行?): {wall_serial:.2f}s"
    assert wall_parallel < wall_serial / 2


def test_read_files_missing_does_not_interrupt_others(tmp_path):
    """单文件不存在: 该块标注错误, 其他文件照常返回。"""
    k = _kernel_with_tools()
    reg = k.require("tool_registry")
    ctx = _ctx(k, tmp_path)
    (tmp_path / "good.txt").write_text("GOOD\n", encoding="utf-8")
    out = reg.dispatch("read_files",
                      json.dumps({"paths": ["nope.txt", "good.txt"]}), ctx)
    assert "nope.txt" in out
    assert "文件不存在" in out
    assert "GOOD" in out  # 好文件仍读到了


def test_read_files_binary_skipped(tmp_path):
    """二进制文件 (含 NUL) 标注跳过, 不影响其他文件。"""
    k = _kernel_with_tools()
    reg = k.require("tool_registry")
    ctx = _ctx(k, tmp_path)
    (tmp_path / "bin.bin").write_bytes(b"\x00\x01\x02\x03")
    (tmp_path / "ok.txt").write_text("OK\n", encoding="utf-8")
    out = reg.dispatch("read_files",
                      json.dumps({"paths": ["bin.bin", "ok.txt"]}), ctx)
    assert "二进制" in out
    assert "OK" in out


def test_read_files_oversize_skipped(tmp_path):
    """单文件超 max_bytes 只提示不读全文, 其他文件正常。"""
    k = _kernel_with_tools()
    cfg = k.require("config")
    cfg.data.setdefault("tools", {}).setdefault("read_files", {})["max_bytes"] = 5
    reg = k.require("tool_registry")
    ctx = _ctx(k, tmp_path)
    (tmp_path / "big.txt").write_text("this is definitely more than 5 bytes\n", encoding="utf-8")
    (tmp_path / "small.txt").write_text("hi", encoding="utf-8")
    out = reg.dispatch("read_files",
                      json.dumps({"paths": ["big.txt", "small.txt"]}), ctx)
    assert "文件过大" in out
    assert "分段" in out
    assert "hi" in out  # 小文件仍读到


def test_read_files_marks_read_enables_edit(tmp_path):
    """read_files 成功读取的文件自动 mark_read, 后续 edit_file 守卫放行。"""
    k = _kernel_with_tools()
    reg = k.require("tool_registry")
    ctx = _ctx(k, tmp_path)
    (tmp_path / "a.txt").write_text("hello world\n", encoding="utf-8")
    # 未读时先确认守卫拦得住直接 edit
    blocked = reg.dispatch("edit_file", json.dumps(
        {"path": "a.txt", "old_string": "hello", "new_string": "HELLO"}), ctx)
    assert "请先 read_file" in blocked
    # 用 read_files 批量读后, edit 放行
    reg.dispatch("read_files", json.dumps({"paths": ["a.txt"]}), ctx)
    out = reg.dispatch("edit_file", json.dumps(
        {"path": "a.txt", "old_string": "hello", "new_string": "HELLO"}), ctx)
    assert "已修改" in out
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "HELLO world\n"


def test_read_files_schema_and_flags(tmp_path):
    """read_only=True (Plan 放行), schema 合法。"""
    k = _kernel_with_tools()
    reg = k.require("tool_registry")
    t = reg.get("read_files")
    assert t is not None
    assert t.read_only is True
    sch = t.schema()
    assert sch["function"]["name"] == "read_files"
    assert "paths" in sch["function"]["parameters"]["properties"]
    assert "paths" in sch["function"]["parameters"]["required"]


# ================================================================== edit_files

def _edit_ctx(tmp_path):
    k = _kernel_with_tools()
    reg = k.require("tool_registry")
    ctx = _ctx(k, tmp_path)
    return reg, ctx


def test_edit_files_transaction_rejects_and_keeps_disk_untouched(tmp_path):
    """事务性: items 中一处 old 不匹配 -> 整体拒绝, 所有文件磁盘内容零变化。"""
    reg, ctx = _edit_ctx(tmp_path)
    (tmp_path / "a.txt").write_text("alpha\n", encoding="utf-8")
    (tmp_path / "b.txt").write_text("beta\n", encoding="utf-8")
    # 先读两文件 (满足守卫)
    reg.dispatch("read_files", json.dumps({"paths": ["a.txt", "b.txt"]}), ctx)
    out = reg.dispatch("edit_files", json.dumps({"items": [
        {"path": "a.txt", "old_string": "WRONG_A", "new_string": "ALPHA"},
        {"path": "b.txt", "old_string": "MISSING", "new_string": "BETA2"},
    ]}), ctx)
    assert "整体拒绝" in out
    assert "未写入任何文件" in out
    # 两处失败点都要一次性列出
    assert "第 1 项" in out
    assert "第 2 项" in out
    # 磁盘零变化: 两个文件都原样
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "alpha\n"
    assert (tmp_path / "b.txt").read_text(encoding="utf-8") == "beta\n"


def test_edit_files_rejects_on_unread_guard(tmp_path):
    """一处未 read 被守卫拦 -> 整体拒绝, 连已读文件也不落盘。"""
    reg, ctx = _edit_ctx(tmp_path)
    (tmp_path / "read.txt").write_text("seen\n", encoding="utf-8")
    (tmp_path / "unread.txt").write_text("hidden\n", encoding="utf-8")
    # 只读 read.txt
    reg.dispatch("read_file", json.dumps({"path": "read.txt"}), ctx)
    out = reg.dispatch("edit_files", json.dumps({"items": [
        {"path": "read.txt", "old_string": "seen", "new_string": "SEEN"},
        {"path": "unread.txt", "old_string": "hidden", "new_string": "HIDDEN"},
    ]}), ctx)
    assert "整体拒绝" in out
    assert "请先 read_file" in out
    # 已读的 read.txt 也没写 (事务整体性)
    assert (tmp_path / "read.txt").read_text(encoding="utf-8") == "seen\n"
    assert (tmp_path / "unread.txt").read_text(encoding="utf-8") == "hidden\n"


def test_edit_files_success_updates_all_with_diff(tmp_path):
    """全匹配时多文件一次更新, diff 摘要含各文件。"""
    reg, ctx = _edit_ctx(tmp_path)
    (tmp_path / "a.txt").write_text("one\n", encoding="utf-8")
    (tmp_path / "b.txt").write_text("two\n", encoding="utf-8")
    reg.dispatch("read_files", json.dumps({"paths": ["a.txt", "b.txt"]}), ctx)
    out = reg.dispatch("edit_files", json.dumps({"items": [
        {"path": "a.txt", "old_string": "one", "new_string": "ONE"},
        {"path": "b.txt", "old_string": "two", "new_string": "TWO"},
    ]}), ctx)
    assert "事务成功" in out
    assert "已修改 a.txt" in out
    assert "已修改 b.txt" in out
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "ONE\n"
    assert (tmp_path / "b.txt").read_text(encoding="utf-8") == "TWO\n"


def test_edit_files_multi_replacements_short_keys(tmp_path):
    """单文件多段 replacements (old/new 短键) 一次事务。"""
    reg, ctx = _edit_ctx(tmp_path)
    (tmp_path / "f.txt").write_text("foo bar baz\n", encoding="utf-8")
    reg.dispatch("read_file", json.dumps({"path": "f.txt"}), ctx)
    out = reg.dispatch("edit_files", json.dumps({"items": [
        {"path": "f.txt", "replacements": [
            {"old": "foo", "new": "FOO"},
            {"old": "bar", "new": "BAR"},
        ]},
    ]}), ctx)
    assert "事务成功" in out
    assert "2 处替换" in out
    assert (tmp_path / "f.txt").read_text(encoding="utf-8") == "FOO BAR baz\n"


def test_edit_files_uniqueness_check(tmp_path):
    """old 不唯一 -> 整体回滚, 不写入。"""
    reg, ctx = _edit_ctx(tmp_path)
    (tmp_path / "f.txt").write_text("x x y\n", encoding="utf-8")
    reg.dispatch("read_file", json.dumps({"path": "f.txt"}), ctx)
    out = reg.dispatch("edit_files", json.dumps({"items": [
        {"path": "f.txt", "old_string": "x", "new_string": "X"},
    ]}), ctx)
    assert "整体拒绝" in out
    assert "不唯一" in out
    assert (tmp_path / "f.txt").read_text(encoding="utf-8") == "x x y\n"


def test_edit_files_schema_and_flags(tmp_path):
    """read_only=False, dangerous=False (与 edit_file 同级但不强制确认), schema 合法。"""
    k = _kernel_with_tools()
    reg = k.require("tool_registry")
    t = reg.get("edit_files")
    assert t is not None
    assert t.read_only is False
    assert t.dangerous is False
    sch = t.schema()
    assert sch["function"]["name"] == "edit_files"
    assert "items" in sch["function"]["parameters"]["properties"]
    assert "items" in sch["function"]["parameters"]["required"]
