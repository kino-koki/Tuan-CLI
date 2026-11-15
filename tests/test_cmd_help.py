"""cmd_help 单元测试 —— 帮助系统 / 命令元数据。"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from tuan_cli.cli import cmd_help as P


def _args(**kw) -> SimpleNamespace:
    base = dict(topic=None)
    base.update(kw)
    return SimpleNamespace(**base)


@pytest.fixture(autouse=True)
def _patch(monkeypatch):
    import tuan_cli.ui.plain_console as pc
    monkeypatch.setattr(pc, "console", SimpleNamespace(print=lambda *a, **k: None))


# ============================================================ categorized_help_text


class TestCategorizedHelpText:
    def test_returns_string(self, monkeypatch):
        monkeypatch.setattr(P, "_meta", lambda: {})
        text = P.categorized_help_text()
        assert isinstance(text, str)
        assert "斜杠命令" in text
        for cat in P.CATEGORIZED_HELP:
            assert cat in text

    def test_with_meta(self, monkeypatch):
        monkeypatch.setattr(P, "_meta", lambda: {"/help": "显示帮助", "/diff": "diff"})
        text = P.categorized_help_text()
        assert "/help" in text
        assert "显示帮助" in text


# ============================================================ help_for_command


class TestHelpForCommand:
    def test_keyboard(self, monkeypatch):
        monkeypatch.setattr(P, "_meta", lambda: {})
        text = P.help_for_command("keyboard")
        assert "快捷键" in text
        assert "Enter" in text

    def test_with_slash(self, monkeypatch):
        monkeypatch.setattr(P, "_meta", lambda: {"/diff": "diff viewer"})
        text = P.help_for_command("/diff")
        assert "/diff" in text
        assert "diff viewer" in text

    def test_without_slash(self, monkeypatch):
        monkeypatch.setattr(P, "_meta", lambda: {"/diff": "diff viewer"})
        text = P.help_for_command("diff")
        assert "/diff" in text

    def test_detail_usage(self, monkeypatch):
        monkeypatch.setattr(P, "_meta", lambda: {"/goal": "run goal"})
        text = P.help_for_command("/goal")
        assert "用法" in text
        assert "示例" in text

    def test_unknown(self, monkeypatch):
        monkeypatch.setattr(P, "_meta", lambda: {})
        text = P.help_for_command("/nonexistent")
        assert "未知命令" in text


# ============================================================ all_commands_metadata


class TestAllCommandsMetadata:
    def test_structure(self, monkeypatch):
        monkeypatch.setattr(P, "_meta", lambda: {"/help": "h", "/diff": "d"})
        result = P.all_commands_metadata()
        assert isinstance(result, list)
        assert all("name" in r and "description" in r and "category" in r for r in result)
        names = {r["name"] for r in result}
        assert "/help" in names

    def test_categorization(self, monkeypatch):
        monkeypatch.setattr(P, "_meta", lambda: {"/diff": "d", "/help": "h", "/model": "m"})
        result = P.all_commands_metadata()
        by_name = {r["name"]: r for r in result}
        assert by_name["/diff"]["category"] == "代码与工程"
        assert by_name["/help"]["category"] == "对话管理"
        assert by_name["/model"]["category"] == "系统与权限"

    def test_unknown_category_fallback(self, monkeypatch):
        monkeypatch.setattr(P, "_meta", lambda: {"/unknown": "x"})
        result = P.all_commands_metadata()
        assert result[0]["category"] == "其他"


# ============================================================ cmd_help


class TestCmdHelp:
    def test_no_topic_overview(self, monkeypatch):
        assert P.cmd_help(_args()) == 0

    def test_quickstart_missing(self, monkeypatch):
        monkeypatch.setattr(P, "_show_quickstart", lambda: None)
        assert P.cmd_help(_args(topic="quickstart")) == 0

    def test_topic_dispatch(self, monkeypatch):
        import tuan_cli.cli.parser as parser_mod
        class _FakeParser:
            def parse_args(self, argv):
                raise SystemExit(0)
        monkeypatch.setattr(parser_mod, "build_parser", lambda: _FakeParser())
        assert P.cmd_help(_args(topic="model")) == 0
