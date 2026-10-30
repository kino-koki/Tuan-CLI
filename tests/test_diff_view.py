"""测试 diff_view —— REPL / 终端 diff 美化输出 (对标 Claude Code /diff)。

覆盖:
  - colorize_unified_diff (新增绿/删除红/头信息灰/普通行原样)
  - summarize_diff (+/-/文件数统计, 排除 +++/--- 头)
  - render_edit_diff (生成统一 diff 并上色 / 无差异空串)
  - last_edit_diff (从账本取最近编辑 / 无账本 None / 无编辑 None)
  - format_no_diff
"""

from __future__ import annotations

import json
import pytest

from tuan_cli.core.diff_view import (
    colorize_unified_diff,
    summarize_diff,
    render_edit_diff,
    last_edit_diff,
    format_no_diff,
)


_GREEN = "\033[32m"
_RED = "\033[31m"
_DIM = "\033[2m"
_RESET = "\033[0m"


class TestColorize:
    def test_added_line_green(self):
        out = colorize_unified_diff("+new")
        assert out == f"{_GREEN}+new{_RESET}"

    def test_removed_line_red(self):
        out = colorize_unified_diff("-old")
        assert out == f"{_RED}-old{_RESET}"

    def test_header_dim(self):
        out = colorize_unified_diff("--- a/x\n+++ b/x")
        assert f"{_DIM}--- a/x{_RESET}" in out
        assert f"{_DIM}+++ b/x{_RESET}" in out

    def test_hunk_header_dim(self):
        out = colorize_unified_diff("@@ -1,3 +1,3 @@")
        assert f"{_DIM}@@ -1,3 +1,3 @@{_RESET}" in out

    def test_context_unchanged(self):
        out = colorize_unified_diff(" context")
        assert " context" in out
        assert _GREEN not in out and _RED not in out


class TestSummarize:
    def test_counts(self):
        diff = "--- a/x\n+++ b/x\n@@ -1,2 +1,2 @@\n- old\n+ new\n+ new2\n"
        added, removed, files = summarize_diff(diff)
        assert added == 2
        assert removed == 1
        assert files == 1

    def test_multiple_files(self):
        diff = "--- a/x\n+++ b/x\n--- a/y\n+++ b/y\n"
        added, removed, files = summarize_diff(diff)
        assert files == 2

    def test_empty(self):
        assert summarize_diff("") == (0, 0, 0)

    def test_header_excluded(self):
        # +++/--- 头不计入 +/-
        diff = "+++ b/x\n--- a/x\n"
        added, removed, _ = summarize_diff(diff)
        assert added == 0 and removed == 0


class TestRenderEditDiff:
    def test_renders_diff(self):
        out = render_edit_diff("a\nb\nc", "a\nb2\nc", "file.txt")
        assert "--- a/file.txt" in out
        assert "+++ b/file.txt" in out
        assert "-b" in out
        assert "+b2" in out

    def test_no_diff_empty(self):
        assert render_edit_diff("same", "same", "f") == ""

    def test_colored(self):
        out = render_edit_diff("x", "y", "f.txt")
        assert _GREEN in out and _RED in out


class TestLastEditDiff:
    def test_no_ledger_returns_none(self, tmp_path):
        assert last_edit_diff(tmp_path) is None

    def test_returns_recent_edit(self, tmp_path):
        ws = tmp_path
        ledger = ws / ".tuan" / "ledger"
        ledger.mkdir(parents=True)
        events = [
            {"type": "edit", "path": "a.txt", "old": "x", "new": "y"},
            {"type": "edit", "path": "b.txt", "old": "1", "new": "2"},
        ]
        (ledger / "events.jsonl").write_text(
            "\n".join(json.dumps(e) for e in events), encoding="utf-8")
        path, colored = last_edit_diff(ws)
        assert path == "b.txt"
        assert "b.txt" in colored

    def test_recent_edit_takes_last(self, tmp_path):
        ws = tmp_path
        ledger = ws / ".tuan" / "ledger"
        ledger.mkdir(parents=True)
        events = [
            {"type": "edit", "path": "a.txt", "old": "x", "new": "y"},
            {"type": "write", "path": "c.txt", "old": "p", "new": "q"},
        ]
        (ledger / "events.jsonl").write_text(
            "\n".join(json.dumps(e) for e in events), encoding="utf-8")
        path, _ = last_edit_diff(ws)
        assert path == "c.txt"

    def test_ignores_non_edit_types(self, tmp_path):
        ws = tmp_path
        ledger = ws / ".tuan" / "ledger"
        ledger.mkdir(parents=True)
        events = [{"type": "read", "path": "a.txt", "old": "x", "new": "y"}]
        (ledger / "events.jsonl").write_text(
            "\n".join(json.dumps(e) for e in events), encoding="utf-8")
        assert last_edit_diff(ws) is None

    def test_malformed_lines_skipped(self, tmp_path):
        ws = tmp_path
        ledger = ws / ".tuan" / "ledger"
        ledger.mkdir(parents=True)
        (ledger / "events.jsonl").write_text("not json\n", encoding="utf-8")
        assert last_edit_diff(ws) is None

    def test_ledger_as_file(self, tmp_path):
        # 账本可能是单个文件而非目录
        ws = tmp_path
        ledger = ws / ".tuan" / "ledger"
        ledger.parent.mkdir(parents=True)
        ledger.write_text(json.dumps({"type": "edit", "path": "a.txt",
                                      "old": "1", "new": "2"}), encoding="utf-8")
        path, _ = last_edit_diff(ws)
        assert path == "a.txt"


class TestFormatNoDiff:
    def test_message(self):
        assert "没有" in format_no_diff()
        assert format_no_diff() == "当前没有可展示的 diff (尚未发生文件编辑, 或工作区干净)。"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v", "-p", "no:cacheprovider"]))
