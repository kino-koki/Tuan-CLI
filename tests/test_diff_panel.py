"""/diff 与 REPL diff 美化测试 (qingxiaotuan/core/diff_view.py)。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from qingxiaotuan.core import diff_view


def test_colorize_additions_green():
    diff = "--- a/f\n+++ b/f\n@@ -1 +1 @@\n-old\n+new\n ctx\n"
    out = diff_view.colorize_unified_diff(diff)
    assert "\033[32m+new" in out      # 新增行绿色
    assert "\033[31m-old" in out      # 删除行红色
    assert "\033[2m@@" in out         # 块头灰色


def test_render_edit_diff_basic():
    old = "line1\nline2\nline3\n"
    new = "line1\nCHANGED\nline3\n"
    colored = diff_view.render_edit_diff(old, new, "demo.py")
    assert "CHANGED" in colored
    assert colored.startswith("\033[2m---")  # 头信息带色


def test_render_edit_diff_no_change():
    old = "same\n"
    assert diff_view.render_edit_diff(old, old, "f.txt") == ""


def test_summarize_diff_counts():
    text = "--- a/f\n+++ b/f\n@@ -1,2 +1,2 @@\n-a\n-b\n+x\n+y\n+z\n"
    added, removed, files = diff_view.summarize_diff(text)
    assert added == 3
    assert removed == 2


def test_no_diff_message():
    assert "没有可展示" in diff_view.format_no_diff()


def test_last_edit_diff_from_ledger(tmp_path):
    """账本里有最近一次 edit 事件 -> 返回 (路径, 着色 diff)。"""
    ledger_dir = tmp_path / ".qxt"
    ledger_dir.mkdir()
    ledger = ledger_dir / "ledger"
    ledger.mkdir()
    events = ledger / "events.jsonl"
    import json
    events.write_text(
        "\n".join([
            json.dumps({"type": "edit", "path": "src/a.py", "old": "x=1\n", "new": "x=2\n"}),
        ]) + "\n",
        encoding="utf-8",
    )
    result = diff_view.last_edit_diff(tmp_path)
    assert result is not None
    path, colored = result
    assert path == "src/a.py"
    assert "x=2" in colored


def test_last_edit_diff_no_ledger(tmp_path):
    """无账本 -> None (调用方应提示无 diff)。"""
    assert diff_view.last_edit_diff(tmp_path) is None
