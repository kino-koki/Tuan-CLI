"""测试 Kimi 移植的用量配额面板纯函数 (kimi_modules 的 usage 部分)。

这些函数直接移植自 Kimi Code ui/shell/usage.py, 且被 TUI 的
``append_usage_panel`` 使用。测试确保: 解析/格式/渲染三层的纯函数语义
与 Kimi 原始实现一致 (窄接口形态), 且对 TUI 调用方友好 (无副作用、无 IO)。
"""

from __future__ import annotations

import pytest

from tuan_cli.tui.kimi_modules import (
    UsageRow,
    _fmt_seconds_duration,
    _format_reset_time,
    _ratio_color,
    _remaining_quota,
    _usage_reset_hint,
    _usage_to_int,
    build_usage_rows,
    format_usage_row,
    render_usage_panel,
)


# --------------------------------------------------------------------------- #
# _usage_to_int: 容忍 None / 字符串 / 溢出
# --------------------------------------------------------------------------- #

class TestUsageToInt:
    def test_plain_int(self):
        assert _usage_to_int(5) == 5

    def test_numeric_string(self):
        assert _usage_to_int("42") == 42

    def test_float_truncates(self):
        assert _usage_to_int(3.9) == 3

    def test_none_returns_none(self):
        assert _usage_to_int(None) is None

    def test_garbage_returns_none(self):
        assert _usage_to_int("abc") is None
        assert _usage_to_int([1, 2]) is None


# --------------------------------------------------------------------------- #
# _remaining_quota: (remaining, ratio, total) 语义
# --------------------------------------------------------------------------- #

class TestRemainingQuota:
    def test_full_quota(self):
        row = UsageRow(label="x", used=0, limit=100)
        remaining, ratio, total = _remaining_quota(row)
        assert (remaining, total) == (100, 100)
        assert ratio == 1.0

    def test_partial_used(self):
        row = UsageRow(label="x", used=30, limit=100)
        remaining, ratio, total = _remaining_quota(row)
        assert remaining == 70
        assert ratio == pytest.approx(0.7)
        assert total == 100

    def test_over_use_clamped_to_zero(self):
        row = UsageRow(label="x", used=200, limit=100)
        remaining, ratio, total = _remaining_quota(row)
        assert remaining == 0
        assert ratio == 0.0
        assert total == 100

    def test_zero_limit_returns_safe_default(self):
        row = UsageRow(label="x", used=5, limit=0)
        remaining, ratio, total = _remaining_quota(row)
        assert (remaining, ratio, total) == (0, 0, 1)


# --------------------------------------------------------------------------- #
# _ratio_color: Kimi 同款阈值 (<=0.1 red, <=0.3 yellow, else green)
# --------------------------------------------------------------------------- #

class TestRatioColor:
    def test_danger(self):
        assert _ratio_color(0.0) == "red"
        assert _ratio_color(0.1) == "red"

    def test_warning(self):
        assert _ratio_color(0.2) == "yellow"
        assert _ratio_color(0.3) == "yellow"

    def test_healthy(self):
        assert _ratio_color(0.5) == "green"
        assert _ratio_color(1.0) == "green"


# --------------------------------------------------------------------------- #
# _fmt_seconds_duration: 秒 → 人类可读时长
# --------------------------------------------------------------------------- #

class TestFmtSecondsDuration:
    def test_sub_minute(self):
        assert _fmt_seconds_duration(45) == "45s"

    def test_minutes(self):
        assert _fmt_seconds_duration(60) == "1m"
        assert _fmt_seconds_duration(90) == "1m"

    def test_hours_with_rem(self):
        assert _fmt_seconds_duration(3600) == "1h"
        assert _fmt_seconds_duration(5400) == "1h30m"

    def test_days_with_rem(self):
        assert _fmt_seconds_duration(86400) == "1d"
        assert _fmt_seconds_duration(90000) == "1d1h"

    def test_negative_clamped(self):
        assert _fmt_seconds_duration(-10) == "0s"


# --------------------------------------------------------------------------- #
# _format_reset_time: ISO 时间 → 可读重置提示
# --------------------------------------------------------------------------- #

class TestFormatResetTime:
    def test_invalid_returns_fallback(self):
        assert _format_reset_time("not-a-time") == "resets at not-a-time"

    def test_past_returns_reset(self):
        assert _format_reset_time("2020-01-01T00:00:00Z") == "reset"

    def test_future_returns_resets_in(self):
        # 未来 1 小时: 应形如 "resets in 1h"
        from datetime import UTC, datetime, timedelta
        future = (datetime.now(UTC) + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        result = _format_reset_time(future)
        assert result.startswith("resets in ")


# --------------------------------------------------------------------------- #
# _usage_reset_hint: 从 payload dict 提取重置提示
# --------------------------------------------------------------------------- #

class TestUsageResetHint:
    def test_iso_reset_at(self):
        data = {"reset_at": "2020-01-01T00:00:00Z"}
        assert _usage_reset_hint(data) == "reset"

    def test_ttl_seconds(self):
        data = {"ttl": 90}
        assert _usage_reset_hint(data) == "resets in 1m"

    def test_reset_in_minutes(self):
        data = {"reset_in": 300}
        assert _usage_reset_hint(data) == "resets in 5m"

    def test_empty_returns_none(self):
        assert _usage_reset_hint({}) is None


# --------------------------------------------------------------------------- #
# build_usage_rows: 本地 token 计数 → 配额行列表
# --------------------------------------------------------------------------- #

class TestBuildUsageRows:
    def test_with_budget(self):
        rows = build_usage_rows(1000, 500, budget_tokens=8000, context_used=600)
        labels = [r.label for r in rows]
        assert labels == ["Context budget", "Total tokens", "Prompt tokens", "Completion tokens"]
        ctx, total, prompt, comp = rows
        assert ctx.used == 600
        assert ctx.limit == 8000
        assert ctx.reset_hint == "8,000 token window"
        assert total.used == 1500
        assert total.limit == 8000
        assert prompt.used == 1000
        assert comp.used == 500

    def test_without_budget(self):
        rows = build_usage_rows(10, 5)
        labels = [r.label for r in rows]
        assert labels == ["Total tokens", "Prompt tokens", "Completion tokens"]
        assert rows[0].limit == 0  # 无预算: 进度条行 limit=0 → 纯文本

    def test_context_used_falls_back_to_sum(self):
        # context_used=0 时, 预算行 used 回退到 prompt+completion
        rows = build_usage_rows(100, 200, budget_tokens=1000, context_used=0)
        assert rows[0].used == 300


# --------------------------------------------------------------------------- #
# format_usage_row / render_usage_panel: rich 渲染不抛
# --------------------------------------------------------------------------- #

class TestRenderUsagePanel:
    def test_format_row_returns_renderable(self):
        row = UsageRow(label="Context budget", used=600, limit=8000,
                       reset_hint="8,000 token window")
        # 不抛即可; rich Table.grid 是合法 renderable
        assert format_usage_row(row, label_width=16) is not None

    def test_render_panel_empty(self):
        panel = render_usage_panel([])
        # Panel 有 title (rich Panel 的 title 属性)
        assert getattr(panel, "title", "") == "API Usage"

    def test_render_panel_with_rows(self):
        rows = build_usage_rows(1000, 500, 8000, 600)
        panel = render_usage_panel(rows)
        assert getattr(panel, "title", "") == "API Usage"

    def test_render_panel_roundtrip_via_console(self):
        # 模拟 TUI 的 console.print 路径 (去 ANSI)
        from io import StringIO
        from rich.console import Console
        rows = build_usage_rows(1000, 500, 8000, 600)
        panel = render_usage_panel(rows)
        buf = StringIO()
        Console(file=buf, force_terminal=False, color_system=None, width=100).print(panel)
        text = buf.getvalue()
        assert "API Usage" in text
        assert "Context budget" in text
        assert "Total tokens" in text
