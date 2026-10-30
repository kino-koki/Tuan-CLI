"""测试 markers —— 共享的「任务完成」判定标记。

覆盖:
  - DONE_MARKERS 常量
  - is_done (各标记命中 / 空文本安全 / 未命中)
"""

from __future__ import annotations

import pytest

from tuan_cli.core.markers import DONE_MARKERS, is_done


class TestDoneMarkers:
    def test_constants(self):
        assert "【已完成】" in DONE_MARKERS
        assert "DONE:" in DONE_MARKERS
        assert "TASK_DONE" in DONE_MARKERS
        assert len(DONE_MARKERS) >= 4


class TestIsDone:
    def test_chinese_complete(self):
        assert is_done("已修复所有 bug【已完成】") is True

    def test_checkmark(self):
        assert is_done("全部搞定 ✅ 完成") is True

    def test_feature_complete(self):
        assert is_done("功能已完成") is True

    def test_task_done(self):
        assert is_done("TASK_DONE") is True

    def test_done_colon(self):
        assert is_done("DONE: 全部完成") is True

    def test_not_done(self):
        assert is_done("还在处理中, 下一步是...") is False

    def test_empty(self):
        assert is_done("") is False

    def test_none(self):
        assert is_done(None) is False

    def test_marker_as_substring(self):
        assert is_done("任务完成后会通知你") is True


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v", "-p", "no:cacheprovider"]))
