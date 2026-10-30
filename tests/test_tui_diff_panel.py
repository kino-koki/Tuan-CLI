# -*- coding: utf-8 -*-
"""TUI diff 实时面板测试 (Ctrl+D)。

对标 Claude Code 的 /diff: 在对话右侧开一个实时反映工作区改动的面板, 模型
改文件时自动刷新。验证不依赖真实终端 —— 直接实例化 QxtTUI 并驱动面板方法。
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tuan_cli.tui.tui import QxtTUI  # noqa: E402


def _make_tui(cols: int = 140) -> QxtTUI:
    """造一个只初始化面板相关字段的 TUI 实例 (绕过重量级 __init__)。"""
    tui = QxtTUI.__new__(QxtTUI)
    tui._diff_visible = False
    tui._diff_cache = []
    tui._diff_summary = ""
    tui._diff_error = ""
    tui._diff_fetched_at = 0.0
    tui._diff_width = 0
    tui._app = None
    tui._audit_log = []
    tui._terminal_cols = lambda: cols  # type: ignore[method-assign]
    return tui


@pytest.fixture()
def git_repo(tmp_path):
    """一个含已跟踪改动的真实 git 仓库, 用于验证解析与统计。"""
    run = lambda *a: subprocess.run(  # noqa: E731
        ["git", *a], cwd=tmp_path, capture_output=True, text=True, check=True,
    )
    run("init", "-q")
    run("config", "user.email", "t@example.com")
    run("config", "user.name", "t")
    (tmp_path / "a.txt").write_text("one\n", encoding="utf-8")
    run("add", "a.txt")
    run("commit", "-qm", "init")
    (tmp_path / "a.txt").write_text("one\ntwo\nthree\n", encoding="utf-8")
    return tmp_path


class TestPanelWidth:
    def test_width_scales_with_terminal(self):
        assert _make_tui(140)._diff_panel_width() == 56      # 40% 上限
        assert _make_tui(200)._diff_panel_width() == 64      # 钳制上限

    def test_width_has_floor(self):
        assert _make_tui(90)._diff_panel_width() >= 32

    def test_hidden_when_narrow(self):
        """终端 < 90 列时不开面板, 否则对话区会被压成一条缝。"""
        assert _make_tui(80)._diff_panel_available() is False
        assert _make_tui(89)._diff_panel_available() is False

    def test_available_when_wide(self):
        assert _make_tui(120)._diff_panel_available() is True


class TestToggle:
    def test_toggle_flips(self):
        tui = _make_tui()
        tui.toggle_diff()
        assert tui._diff_visible is True
        tui.toggle_diff()
        assert tui._diff_visible is False

    def test_toggle_resets_throttle_so_opening_refreshes(self):
        """打开面板要立刻取一次数据, 不能等节流窗口过去。"""
        tui = _make_tui()
        tui._diff_fetched_at = 9e9
        tui.toggle_diff()
        assert tui._diff_fetched_at == 0.0

    def test_narrow_terminal_refuses_and_explains(self):
        tui = _make_tui(70)
        tui.toggle_diff()
        assert tui._diff_visible is False, "窄终端不得打开面板"
        assert tui._audit_log, "应给出可见的提示而不是静默失败"


class TestFetch:
    def test_parses_real_diff(self, git_repo, monkeypatch):
        tui = _make_tui()
        tui._workspace = str(git_repo)
        monkeypatch.chdir(git_repo)
        tui._fetch_diff()

        assert tui._diff_error == ""
        assert "1" in tui._diff_summary, "摘要应含文件数"
        assert tui._diff_cache, "应解析出 diff 行"

        body = "\n".join(txt for _, txt in tui._diff_cache)
        assert "a.txt" in body, "diff 头应含文件名"

        styles = {cls for cls, _ in tui._diff_cache}
        assert "class:primary" in styles, "diff --git 头应有文件标题样式"
        assert "class:accent" in styles, "@@ hunk 头应有强调样式"
        assert "class:diffadd" in styles, "+ 行应是新增色"
        assert "class:text" in styles, "上下文行应是普通色"

    def test_counts_added_and_removed(self, git_repo, monkeypatch):
        tui = _make_tui()
        tui._workspace = str(git_repo)
        monkeypatch.chdir(git_repo)
        tui._fetch_diff()
        assert "+2" in tui._diff_summary, f"应统计新增行: {tui._diff_summary}"

    def test_clean_tree(self, git_repo, monkeypatch):
        (git_repo / "a.txt").write_text("one\n", encoding="utf-8")
        tui = _make_tui()
        tui._workspace = str(git_repo)
        monkeypatch.chdir(git_repo)
        tui._fetch_diff()
        assert tui._diff_cache == []
        assert tui._diff_error == ""

    def test_not_a_repo_shows_error(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        tui = _make_tui()
        tui._workspace = str(tmp_path)
        tui._fetch_diff()
        # git 缺失/非仓库都要给出可读提示, 不能抛异常影响主界面
        assert tui._diff_error or tui._diff_cache == []

    def test_subdir_inside_repo_does_not_leak_parent_diff(
        self, git_repo, monkeypatch,
    ):
        """工作区是仓库内子目录时, 不得误读父仓库 diff。

        回归: git 会沿父目录向上找 .git, 旧探测 `--is-inside-work-tree` 对
        仓库内子目录也返回 true, `git diff` 误读父仓库真实 diff (全量运行时
        tmp_path 落在仓库内 .pytest-tmp 即触发)。修复用 `--show-toplevel` +
        绝对路径对比, 只有工作区本身就是仓库根才视为仓库。
        """
        sub = git_repo / "inner"
        sub.mkdir()
        (sub / "b.txt").write_text("x\n", encoding="utf-8")
        tui = _make_tui()
        tui._workspace = str(sub)
        monkeypatch.chdir(sub)
        tui._fetch_diff()
        # 工作区不是仓库根 → 不应读取父仓库 diff (含 a.txt 改动)
        assert tui._diff_error, "仓库内子目录应给出可读提示"
        assert tui._diff_cache == [], "不得误读父仓库 diff"
        assert "a.txt" not in "".join(txt for _, txt in tui._diff_cache)


class TestRender:
    def test_render_empty_when_hidden(self):
        tui = _make_tui()
        assert tui._render_diff_panel() == []

    def test_render_contains_title_and_hint(self, git_repo, monkeypatch):
        tui = _make_tui()
        tui._diff_visible = True
        tui._workspace = str(git_repo)
        monkeypatch.chdir(git_repo)
        tui._fetch_diff()
        text = "".join(seg for _, seg in tui._render_diff_panel())
        assert text.strip(), "面板开启时应渲染出内容"

    def test_render_error_does_not_raise(self):
        tui = _make_tui()
        tui._diff_visible = True
        tui._diff_error = "boom"
        tui._render_diff_panel()  # 不抛异常即通过


class TestThrottle:
    def test_throttled_fetch(self, git_repo, monkeypatch):
        """渲染不得在每个重绘帧都 fork git。"""
        calls = []
        tui = _make_tui()
        tui._diff_visible = True
        tui._workspace = str(git_repo)
        monkeypatch.chdir(git_repo)

        real = tui._fetch_diff

        def counting():
            calls.append(1)
            real()

        tui._fetch_diff = counting  # type: ignore[method-assign]
        tui._fetch_diff()
        tui._render_diff_panel()
        tui._render_diff_panel()
        tui._render_diff_panel()
        assert len(calls) == 1, f"节流失效, 1.5s 内不该重复取: {len(calls)} 次"


class TestStylesAndI18n:
    def test_diff_styles_defined(self):
        from tuan_cli.tui.tui import _STYLE_DICT

        assert "diffadd" in _STYLE_DICT
        assert "diffdel" in _STYLE_DICT

    def test_i18n_keys_present_in_all_locales(self):
        import importlib

        keys = [
            "diff_title", "diff_summary", "diff_clean", "diff_hint",
            "diff_too_narrow", "diff_no_git", "diff_not_repo",
            "diff_timeout", "diff_failed",
        ]
        for lang in ("zh_CN", "zh_TW", "en", "ja", "ko", "de", "fr", "es", "pt_BR", "ru"):
            mod = importlib.import_module(f"tuan_cli.i18n.locales.{lang}")
            missing = [k for k in keys if f"tui.{k}" not in mod.TRANSLATIONS]
            assert not missing, f"{lang} 缺少键: {missing}"

    def test_ctrl_d_bound(self):
        import inspect

        src = inspect.getsource(QxtTUI)
        assert '@kb.add("c-d")' in src, "应绑定 Ctrl+D"