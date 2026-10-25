# -*- coding: utf-8 -*-
"""C-3 Tab 补全增强 + C-5.2 离线横幅 回归测试。

覆盖 tuan_cli/tui/tui.py 的增量能力:
- C-3.1 模糊匹配: 前缀 /mo→/mode, 子串 /od→/mode, 子序列 /md→/mode
- C-3.2 多级补全: /safe → bench/allow/report → --quick
- C-3.3 参数预览: 补全项 display_meta 带帮助文本
- C-3.4 帮助提示: 面板底部 "? 帮助" 行
- C-3.5 历史优先: 最近使用的命令 (MRU, ≤10) 在空前缀菜单中排前
- C-3.6 Windows 兼容: win_compat.menu_glyph 降级逻辑
- C-5.2 离线横幅: core.network_check 缺失时静默; 存在且离线时 footer 出现横幅

headless: 直接调 Completer.get_completions(document, complete_event), 不起 Application。
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from prompt_toolkit.document import Document  # noqa: E402

from tuan_cli.tui.tui import (  # noqa: E402
    QxtTUI,
    _SLASH_SUBCMDS,
    _SlashCompleter,
    _fuzzy_rank,
)


def _items(completer, text):
    """跑一次 get_completions, 返回 [(display, meta)] 列表。"""
    doc = Document(text, cursor_position=len(text))
    out = []
    for it in completer.get_completions(doc, None):
        disp = it.display_text if hasattr(it, "display_text") else str(it.display)
        meta = it.display_meta_text if hasattr(it, "display_meta_text") else str(it.display_meta)
        out.append((disp, meta))
    return out


# ---------------------------------------------------------------- 单元: 模糊匹配
class TestFuzzyRank:
    def test_prefix_hit(self):
        assert _fuzzy_rank("mode", "mo") == 0
        assert _fuzzy_rank("", "") == 0

    def test_substring_hit(self):
        assert _fuzzy_rank("mode", "od") == 1

    def test_subsequence_hit(self):
        assert _fuzzy_rank("mode", "md") == 2   # m ... d
        assert _fuzzy_rank("memory", "mry") == 2  # m ... r ... y

    def test_no_hit(self):
        assert _fuzzy_rank("mode", "xyz") == -1
        assert _fuzzy_rank("mode", "mx") == -1


class TestCompleterFuzzy:
    WORDS = ["/mode", "/model", "/memory", "/mcp", "/help"]

    def _c(self):
        return _SlashCompleter(self.WORDS, {w: f"meta of {w}" for w in self.WORDS})

    def test_prefix_completes_mode(self):
        names = [n for n, _m in _items(self._c(), "/mo")]
        assert "/mode" in names
        assert "/model" in names

    def test_substring_fuzzy(self):
        names = [n for n, _m in _items(self._c(), "/od")]
        assert "/mode" in names

    def test_subsequence_fuzzy(self):
        # /md → /mode (m 到 d 中间跳 o/e)
        names = [n for n, _m in _items(self._c(), "/md")]
        assert "/mode" in names

    def test_plus_slash_prefix(self):
        names = [n for n, _m in _items(self._c(), "+/mo")]
        assert any("mode" in n for n in names)

    def test_non_slash_no_completion(self):
        assert _items(self._c(), "hello") == []


# ---------------------------------------------------------------- 单元: 多级补全
class TestMultiLevel:
    WORDS = ["/safe", "/mode", "/help"]

    def _c(self):
        return _SlashCompleter(self.WORDS, {w: f"meta of {w}" for w in self.WORDS})

    def test_safe_lists_subcommands(self):
        out = _items(self._c(), "/safe ")
        names = [n for n, _m in out]
        assert "bench" in names
        assert "allow" in names
        assert "report" in names

    def test_safe_partial_subcommand(self):
        out = _items(self._c(), "/safe be")
        names = [n for n, _m in out]
        assert names == ["bench"]

    def test_flag_third_level(self):
        out = _items(self._c(), "/safe bench --q")
        names = [n for n, _m in out]
        assert "--quick" in names

    def test_subcommand_has_param_preview(self):
        out = dict(_items(self._c(), "/safe "))
        # C-3.3: 子命令项的 display_meta 是帮助文本 (而非命令元数据)
        assert "bench" in out and out["bench"]
        assert "白名单" in out["allow"]

    def test_unknown_command_no_arg_completion(self):
        # 不在子命令表的命令输空格不补参数 (既有行为)
        assert _items(self._c(), "/help ") == []


# ---------------------------------------------------------------- 单元: 历史优先
class TestHistoryPriority:
    WORDS = ["/help", "/mode", "/model", "/clear"]

    def test_history_first(self):
        c = _SlashCompleter(self.WORDS, {w: "m" for w in self.WORDS},
                            history=["/clear", "/mode"])
        names = [n for n, _m in _items(c, "/")]
        # 历史项在前, 且按 MRU 序 (/clear 最近用过)
        assert names[0] == "/clear"
        assert names[1] == "/mode"


# ---------------------------------------------------------------- 面板集成: QxtTUI
CMDS = ["/help", "/model", "/clear", "/compact", "/mcp", "/tools", "/plan",
        "/mode", "/effort", "/offline", "/web", "/quit", "/cost", "/ctx",
        "/memory", "/safe"]


def _tui(commands=CMDS, history=()):
    t = QxtTUI(
        on_submit=lambda _x: "ok",
        commands=commands,
        command_meta={c: f"desc of {c}" for c in commands},
    )
    t._booting = False
    t._boot_error = None
    t._slash_history = list(history)
    return t


def _type(t, text):
    t._input.text = text
    t._on_input_changed()


class TestPanelIntegration:
    def test_safe_space_opens_subcommand_menu(self):
        t = _tui()
        _type(t, "/safe ")
        assert t._slash_open is True
        assert t._slash_arg_mode is True
        assert "bench" in t._slash_items
        assert "allow" in t._slash_items
        assert "report" in t._slash_items

    def test_subcommand_item_has_preview_meta(self):
        t = _tui()
        _type(t, "/safe ")
        idx = t._slash_items.index("bench")
        assert t._slash_metas[idx]

    def test_flag_level_after_subcommand(self):
        t = _tui()
        _type(t, "/safe bench --q")
        assert t._slash_open is True
        assert "--quick" in t._slash_items

    def test_help_row_rendered(self):
        t = _tui()
        _type(t, "/help")
        text = "".join(seg for _c, seg in t._render_slash_menu())
        assert "? 帮助" in text

    def test_history_reorders_empty_menu(self):
        t = _tui(history=["/clear"])
        _type(t, "/")
        # /clear 在命令表中且为 core; 历史优先应排到最前
        assert t._slash_items[0] == "/clear"

    def test_record_slash_usage_mru(self):
        t = _tui()
        t._record_slash_usage("/mode list")
        t._record_slash_usage("/help")
        t._record_slash_usage("/mode")
        assert t._slash_history[0] == "/mode"      # 最近使用的顶上去重
        assert len(t._slash_history) <= 10

    def test_prefix_filter_stable(self):
        t = _tui()
        _type(t, "/mo")
        # 既有手感: /mo 只出前缀命中, 不因子串带出 /memory
        assert t._slash_items == ["/model", "/mode"]


# ---------------------------------------------------------------- Windows 兼容
class TestWinCompatGlyph:
    def test_menu_glyph_default(self, monkeypatch):
        from tuan_cli.tui import win_compat
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        monkeypatch.delenv("CI", raising=False)
        monkeypatch.setattr(win_compat, "_initialized", False)
        monkeypatch.setattr(sys, "platform", "win32")
        # VT 未启用的 legacy ConHost: 退回 ASCII
        assert win_compat.menu_glyph("select") == ">"

    def test_menu_glyph_keeps_symbol_when_vt(self, monkeypatch):
        from tuan_cli.tui import win_compat
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        monkeypatch.delenv("CI", raising=False)
        monkeypatch.setattr(win_compat, "_initialized", True)
        monkeypatch.setattr(sys, "platform", "win32")
        assert win_compat.menu_glyph("select") == "▶"


# ---------------------------------------------------------------- C-5.2 离线横幅
class TestOfflineBanner:
    def test_footer_no_banner_when_module_absent(self, monkeypatch):
        # network_check 未落地 (当前真实状态): footer 不报错也不出现横幅
        t = _tui()
        t._booting = False
        footer = "".join(seg for _c, seg in t._render_footer())
        assert "离线模式" not in footer

    def test_footer_banner_when_offline(self, monkeypatch):
        # 模拟 CLI 核心分片落地: 注入假的 core.network_check.is_offline()
        fake_mod = types.ModuleType("tuan_cli.core.network_check")
        fake_mod.is_offline = lambda: True
        monkeypatch.setitem(sys.modules, "tuan_cli.core.network_check", fake_mod)
        t = _tui()
        t._booting = False
        footer = "".join(seg for _c, seg in t._render_footer())
        assert "离线模式" in footer
        assert "ollama/qwen2.5:7b" in footer

    def test_footer_no_banner_when_online(self, monkeypatch):
        fake_mod = types.ModuleType("tuan_cli.core.network_check")
        fake_mod.is_offline = lambda: False
        monkeypatch.setitem(sys.modules, "tuan_cli.core.network_check", fake_mod)
        t = _tui()
        t._booting = False
        footer = "".join(seg for _c, seg in t._render_footer())
        assert "离线模式" not in footer
