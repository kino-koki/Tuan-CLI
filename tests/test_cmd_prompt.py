"""cmd_prompt tests -- prompt tier diagnostics CLI."""
from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

from tuan_cli.cli import cmd_prompt as P
from tuan_cli.core.prompt_tier import COMPACT, FULL


# ---------------------------------------------------------------- fakes

class FakeBudget:
    def __init__(self, skill_limit=20, memory_notes_max_lines=200,
                 project_doc_max_bytes=8192, long_memory_max_chars=4096):
        self.skill_limit = skill_limit
        self.memory_notes_max_lines = memory_notes_max_lines
        self.project_doc_max_bytes = project_doc_max_bytes
        self.long_memory_max_chars = long_memory_max_chars


class FakeConfig:
    def __init__(self, *args, **kwargs):
        self._data = {}

    def get(self, key, default=None):
        return self._data.get(key, default)


@pytest.fixture(autouse=True)
def _patch(monkeypatch):
    monkeypatch.setattr("tuan_cli.config.Config",
                        lambda *a, **kw: FakeConfig())
    monkeypatch.setattr(P, "Config", FakeConfig)


def _args(**kw):
    base = dict(prompt_cmd=None, profile="default", patch=None,
                model=None, provider=None, window=None, tier=None, json=False)
    base.update(kw)
    return SimpleNamespace(**base)


# ---------------------------------------------------------------- helpers

class TestHelpers:
    def test_human_window_1m(self):
        assert "1.0M" in P._human_window(1_048_576) or "M" in P._human_window(1_048_576)

    def test_human_window_128k(self):
        out = P._human_window(131072)
        assert "128k" in out

    def test_human_window_small(self):
        assert P._human_window(4096) == "4k"
        assert P._human_window(500) == "500"

    def test_soul_file_compact(self):
        assert P._soul_file_for(COMPACT) == "SOUL_COMPACT.md"

    def test_soul_file_full(self):
        assert P._soul_file_for(FULL) == "SOUL_FULL.md"


# ---------------------------------------------------------------- dispatch

class TestDispatch:
    def test_unknown_sub(self, capsys):
        rc = P.cmd_prompt(_args(prompt_cmd="nope"))
        assert rc == 1
        assert "未知子命令" in capsys.readouterr().out

    def test_default_tier(self, capsys):
        rc = P.cmd_prompt(_args())
        assert rc == 0
        assert "提示词分层" in capsys.readouterr().out


# ---------------------------------------------------------------- tier

class TestTier:
    def test_tier_text_smoke(self, capsys):
        # 真实调用, 不 mock 核心逻辑: 只验证不崩、退出 0、有输出
        rc = P.cmd_prompt(_args())
        assert rc == 0
        out = capsys.readouterr().out
        assert "提示词分层" in out or "分档" in out or "Prompt" in out
