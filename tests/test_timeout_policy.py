# -*- coding: utf-8 -*-
"""读超时策略回归测试 (`models.timeout_policy`)。

背景: 用户反馈「模型老是超时」。真因不是默认值不够大, 而是早期一档 timeout
(120s) 被当作 read 固化进了用户的 config.yaml; 之后默认值升到 300s, 但
deep_merge 语义是「用户配置覆盖默认值」, 于是陈旧值继续生效 —— 任何「调大默认值」
的改动都治不好它。本模块以「下限兜底」终结这一类问题。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tuan_cli.models.timeout_policy import (  # noqa: E402
    MIN_READ_TIMEOUT,
    REASONING_READ_TIMEOUT,
    is_reasoning_model,
    resolve_read_timeout,
)


class TestFloorGuard:
    def test_stale_120_lifted_to_floor(self):
        """历史固化值 120 必须抬到 300 —— 这正是「老是超时」的元凶。"""
        assert resolve_read_timeout(120.0, "gpt-5.6-sol") == MIN_READ_TIMEOUT

    def test_just_below_floor_lifted(self):
        assert resolve_read_timeout(299.0, "any-model") == MIN_READ_TIMEOUT

    def test_at_floor_untouched(self):
        assert resolve_read_timeout(300.0, "any-model") == MIN_READ_TIMEOUT

    def test_higher_user_value_respected(self):
        """用户显式配的更大值一律尊重 (只抬低, 不压高)。"""
        assert resolve_read_timeout(900.0, "any-model") == 900.0


class TestInvalidValues:
    def test_none(self):
        assert resolve_read_timeout(None, "m") == MIN_READ_TIMEOUT

    def test_empty_string(self):
        assert resolve_read_timeout("", "m") == MIN_READ_TIMEOUT

    def test_zero(self):
        assert resolve_read_timeout(0, "m") == MIN_READ_TIMEOUT

    def test_garbage_string(self):
        assert resolve_read_timeout("not-a-number", "m") == MIN_READ_TIMEOUT


class TestReasoningModels:
    def test_reasoning_detected(self):
        for name in ("deepseek-reasoner", "o3-mini", "o1-preview", "deepseek-r1",
                     "gemini-2.5-flash-thinking", "claude-thinking-v1"):
            assert is_reasoning_model(name), name

    def test_normal_models_not_reasoning(self):
        for name in ("gpt-5.6-sol", "deepseek-chat", "sensenova-6.8-flash-lite", "", None):
            assert not is_reasoning_model(name), name

    def test_reasoning_uses_higher_floor(self):
        """思考型模型的下限是 600, 陈旧配置也要抬到 600 而非 300。"""
        assert resolve_read_timeout(300.0, "deepseek-reasoner") == REASONING_READ_TIMEOUT
        assert resolve_read_timeout(120.0, "o3-mini") == REASONING_READ_TIMEOUT

    def test_reasoning_at_cap_respected(self):
        assert resolve_read_timeout(700.0, "o1") == 700.0

    def test_reasoning_exact_cap(self):
        assert resolve_read_timeout(REASONING_READ_TIMEOUT, "deepseek-r1") == REASONING_READ_TIMEOUT


class TestBackendWiring:
    """两条后端 + 兜底链路都必须走同一策略, 否则改一处漏一处。"""

    def _cfg(self, model, read_timeout):
        from tuan_cli.config import Config

        cfg = Config()
        cfg.set_user("model.provider", "sensenova")
        cfg.set_user("model.base_url", "https://token.sensenova.cn/v1")
        cfg.set_user("model.model", model)
        cfg.set_user("model.read_timeout", read_timeout)
        return cfg

    def test_legacy_backend_lifts_stale_value(self):
        from tuan_cli.models import create_adapter

        adapter = create_adapter(self._cfg("sensenova-6.8-flash-lite", 120.0))
        assert adapter.read_timeout == MIN_READ_TIMEOUT

    def test_legacy_backend_reasoning_widen(self):
        from tuan_cli.models import create_adapter

        adapter = create_adapter(self._cfg("deepseek-reasoner", 120.0))
        assert adapter.read_timeout == REASONING_READ_TIMEOUT

    def test_kernel_backend_lifts_stale_value(self):
        from tuan_cli.models.kernel_adapter import create_kernel_adapter

        adapter = create_kernel_adapter(self._cfg("sensenova-6.8-flash-lite", 120.0))
        assert adapter._provider._read_timeout == MIN_READ_TIMEOUT

    def test_kernel_backend_reasoning_widen(self):
        from tuan_cli.models.kernel_adapter import create_kernel_adapter

        adapter = create_kernel_adapter(self._cfg("deepseek-reasoner", 120.0))
        assert adapter._provider._read_timeout == REASONING_READ_TIMEOUT