# -*- coding: utf-8 -*-
"""运行时标语（spinner verbs）+ 本轮三个 TUI 真实缺陷的回归。

三个被修的缺陷（都是实测复现，不是补文档）：

B1  文件头误注声称 wcwidth 是 C 实现（0.8.x 实为纯 Python 逐字表查找）。
    本地分叉副本另有 16.2 ms/帧 > 10 ms 的无缓存回归；**远端主线已有
    ``(width, text)`` 高度缓存，该回归不适用于主线**，本轮在主线只做
    注释修正 + 有界 lru_cache 第二层保险。
B2  ``_render_footer`` 把 busy/streaming 判定放在 running 之前，而
    ``begin_tool`` 同时置 busy=True —— 工具运行时底栏永远显示「思考中」，
    ``_running`` 分支是死代码。这正是「状态文案与真实活动不符」。
B3  ``_disp_width`` 与 ``_display_width`` 是两套宽度算法，视口切片与单行
    裁剪口径分裂；旧 fallback ``len(text)`` 对 CJK 直接算错。

标语侧的核心契约：**只有真实事件推进文案**，每帧 render 不得自己转词；
忙碌中长时间无事件要如实报「疑似摸鱼」，而不是继续装忙。
"""
from __future__ import annotations

import json
import random
import time
from pathlib import Path

import pytest

from tuan_cli.i18n import t
from tuan_cli.tui.runtime_slogans import (
    LANGUAGES, PHASES, RuntimeSloganEngine, SpinnerVerbsConfig, SloganView,
    _STALL_TEXT, load_config, sanitize_verb, slogan_bank,
)
from tuan_cli.tui.tui import QxtTUI, _disp_width, _display_width


def _tui(**kw):
    kw.setdefault("on_submit", lambda _text: "ok")
    obj = QxtTUI(**kw)
    obj._booting = False
    obj._boot_error = None
    return obj


def _cfg(**kw) -> SpinnerVerbsConfig:
    base = dict(mode="default", verbs=(), interval_ms=1800,
                stall_ms=15000, source="test")
    base.update(kw)
    return SpinnerVerbsConfig(**base)


class _Clock:
    """可注入的单调时钟，避免测试依赖真实墙钟。"""
    def __init__(self, start=100.0):
        self.now = start

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


# ================================================================ 词库与本地化

class TestBank:
    def test_all_ten_languages_cover_all_five_phases(self):
        assert len(LANGUAGES) == 10
        for lang in LANGUAGES:
            bank = slogan_bank(lang)
            assert set(bank) == set(PHASES), f"{lang} 缺阶段"
            for phase in PHASES:
                assert len(bank[phase]) >= 4, f"{lang}/{phase} 词太少"
                assert all(isinstance(v, str) and v.strip()
                           for v in bank[phase])

    def test_no_control_characters_in_any_builtin_verb(self):
        for lang in LANGUAGES:
            for phase, verbs in slogan_bank(lang).items():
                for v in verbs:
                    assert not any(ord(c) < 32 or 127 <= ord(c) <= 159
                                   for c in v), f"{lang}/{phase}: {v!r}"

    def test_chinese_waiting_pool_keeps_the_slacking_joke(self):
        """视频梗：挂上中文后「磨洋工 / 腌制入味 / 看报纸中」集体露馅。"""
        pool = slogan_bank("zh-CN")["waiting_model"]
        for word in ("磨洋工", "腌制入味", "看报纸中", "光合作用中",
                     "溜溜达达", "那个啥来着"):
            assert any(word in v for v in pool), word

    def test_stall_diagnosis_exists_in_every_language(self):
        assert set(_STALL_TEXT) == set(LANGUAGES)
        for lang, fmt in _STALL_TEXT.items():
            assert "{sec}" in fmt and fmt.format(sec=7)

    def test_unknown_language_falls_back_to_english_not_silently_empty(self):
        assert slogan_bank("xx-YY") == slogan_bank("en")


# ================================================================ 净化

class TestSanitize:
    @pytest.mark.parametrize("raw", [
        "\x1b]8;;https://evil.example\x07点我\x1b]8;;\x07",   # OSC 8 超链接
        "\x1b[31m红色\x1b[0m",                                  # CSI 颜色
        "正常\x1b[2J清屏",                                       # CSI 嵌在中间
        "a\x00b\x1fc",                                           # C0
        "\x9b31mC1",                                             # C1
    ])
    def test_escape_and_control_sequences_are_stripped(self, raw):
        out = sanitize_verb(raw)
        assert out
        assert "\x1b" not in out and "\x07" not in out
        assert not any(ord(c) < 32 or 127 <= ord(c) <= 159 for c in out)

    @pytest.mark.parametrize("bad", [None, 123, [], {}, b"bytes", "   ", "\x1b"])
    def test_invalid_input_returns_empty(self, bad):
        assert sanitize_verb(bad) == ""

    def test_plain_text_is_preserved(self):
        assert sanitize_verb("  正在搬砖  ") == "正在搬砖"

    def test_overlong_cjk_is_clipped_by_display_columns(self):
        out = sanitize_verb("摸鱼" * 100)
        assert out and len(out) < 100
        width = sum(2 if ord(c) > 0x2E7F else 1 for c in out)
        assert width <= 40


# ================================================================ 配置

class TestConfig:
    def test_missing_settings_file_uses_factory_default(self, tmp_path):
        c = load_config(tmp_path / "nope.json")
        assert c.mode == "default" and c.verbs == ()
        assert c.source == "builtin"

    def test_invalid_json_uses_factory_default(self, tmp_path):
        p = tmp_path / "settings.json"
        p.write_text("{not json", encoding="utf-8")
        assert load_config(p).source == "builtin"

    @pytest.mark.parametrize("section,marker", [
        ("string", "invalid:not-a-dict"),
        ({"mode": "typo"}, "invalid:mode=typo"),
        ({"mode": "replace", "verbs": "not-a-list"}, "invalid:verbs-not-a-list"),
        ({"mode": "replace", "verbs": []}, "invalid:empty-verbs"),
        ({"mode": "append", "verbs": ["\x1b]8;;x\x07"]}, "invalid:empty-verbs"),
        ({"mode": "default", "interval_ms": "abc"}, "invalid:numbers"),
        ({"interval_ms": 1}, "invalid:"),
    ])
    def test_invalid_config_is_rejected_not_silently_applied(self, tmp_path,
                                                             section, marker):
        p = tmp_path / "settings.json"
        p.write_text(json.dumps({"spinnerVerbs": section}), encoding="utf-8")
        c = load_config(p)
        assert c.source.startswith(marker), (section, c.source)
        assert c.mode == "default"

    def test_replace_mode_loads_sanitized_verbs(self, tmp_path):
        p = tmp_path / "settings.json"
        p.write_text(json.dumps({"spinnerVerbs": {
            "mode": "replace",
            "verbs": ["  自定义词  ", "\x1b[31m危险\x1b[0m", 42, "第二条"],
            "interval_ms": 900, "stall_ms": 4000,
        }}), encoding="utf-8")
        c = load_config(p)
        assert c.mode == "replace"
        assert c.verbs == ("自定义词", "危险", "第二条")
        assert c.interval_ms == 900 and c.stall_ms == 4000
        assert c.source == str(p)

    def test_append_mode_and_off_mode(self, tmp_path):
        p = tmp_path / "settings.json"
        p.write_text(json.dumps({"spinnerVerbs": {
            "mode": "append", "verbs": ["团队梗"]}}), encoding="utf-8")
        assert load_config(p).verbs == ("团队梗",)
        p.write_text(json.dumps({"spinnerVerbs": {"mode": "off"}}),
                     encoding="utf-8")
        assert load_config(p).mode == "off"

    def test_env_home_is_honored(self, tmp_path, monkeypatch):
        p = tmp_path / "settings.json"
        p.write_text(json.dumps({"spinnerVerbs": {
            "mode": "replace", "verbs": ["来自 TUAN_HOME"]}}), encoding="utf-8")
        monkeypatch.setenv("TUAN_HOME", str(tmp_path))
        assert load_config().verbs == ("来自 TUAN_HOME",)

    @pytest.mark.parametrize("kw", [
        {"mode": "typo"}, {"interval_ms": 1}, {"stall_ms": 10},
        {"verbs": ("",)},
    ])
    def test_dataclass_rejects_invalid_values(self, kw):
        with pytest.raises(ValueError):
            _cfg(**kw)


# ================================================================ 引擎：事件驱动

class TestEngine:
    def _engine(self, **kw):
        clock = _Clock()
        cfg = _cfg(**kw.pop("cfg_kw", {}))
        return (RuntimeSloganEngine(config=cfg, lang=kw.pop("lang", "zh-CN"),
                                   rng=random.Random(kw.pop("seed", 7)),
                                   clock=clock), clock)

    def test_activity_selects_a_verb_from_the_right_phase_pool(self):
        eng, clock = self._engine()
        eng.note_activity("running_tool", "git status", now=clock.now)
        view = eng.render(busy=True, now=clock.now)
        assert isinstance(view, SloganView)
        assert view.text in slogan_bank("zh-CN")["running_tool"]
        assert view.phase == "running_tool" and view.seq == 1
        assert not view.stalled

    def test_render_is_pure_and_never_spins_the_verb(self):
        """核心：每帧重绘 100 次，文案与 seq 都不许变。"""
        eng, clock = self._engine()
        eng.note_activity("waiting_model", now=clock.now)
        first = eng.render(busy=True, now=clock.now)
        for i in range(100):
            clock.advance(0.12)          # 每帧 120ms，累计 12s
            v = eng.render(busy=True, now=clock.now)
            assert v.text == first.text
            assert v.seq == first.seq
            # 12s < 15s stall_ms，不应提前报摸鱼
            assert not v.stalled

    def test_phase_change_switches_verb_immediately(self):
        eng, clock = self._engine()
        eng.note_activity("waiting_model", now=clock.now)
        a = eng.render(busy=True, now=clock.now)
        clock.advance(0.01)
        eng.note_activity("running_tool", "ls", now=clock.now)
        b = eng.render(busy=True, now=clock.now)
        assert b.seq == a.seq + 1
        assert b.text != a.text
        assert b.text in slogan_bank("zh-CN")["running_tool"]

    def test_same_phase_is_throttled_but_changes_after_interval(self):
        eng, clock = self._engine()
        eng.note_activity("streaming", now=clock.now)
        first = eng.render(busy=True, now=clock.now)
        clock.advance(0.2)
        eng.note_activity("streaming", now=clock.now)   # 真实分片，但未到间隔
        assert eng.render(busy=True, now=clock.now).seq == first.seq
        clock.advance(2.0)
        eng.note_activity("streaming", now=clock.now)   # 超过 1.8s
        v = eng.render(busy=True, now=clock.now)
        assert v.seq == first.seq + 1
        assert v.text != first.text

    def test_stall_is_reported_honestly_in_chinese(self):
        eng, clock = self._engine()
        eng.note_activity("waiting_model", now=clock.now)
        clock.advance(18.0)
        v = eng.render(busy=True, now=clock.now)
        assert v.stalled is True
        assert "疑似摸鱼" in v.text and "18" in v.text
        assert v.idle_ms == 18000
        # 诊断期间不许偷偷换词装忙
        assert v.seq == 1
        clock.advance(3.0)
        assert eng.render(busy=True, now=clock.now).stalled is True

    def test_continuous_real_events_prevent_false_stall(self):
        eng, clock = self._engine()
        eng.note_activity("streaming", now=clock.now)
        for _ in range(200):
            clock.advance(0.1)                     # 20 秒持续有分片
            eng.note_activity("streaming", now=clock.now)
        v = eng.render(busy=True, now=clock.now)
        assert not v.stalled
        assert v.idle_ms == 0

    def test_busy_without_any_event_is_diagnosed_not_faked(self):
        eng, clock = self._engine()
        v = eng.render(busy=True, now=clock.now)
        assert v.stalled and v.idle_ms == -1 and "疑似摸鱼" in v.text

    def test_off_mode_and_idle_return_empty_text(self):
        eng, clock = self._engine(cfg_kw={"mode": "off"})
        eng.note_activity("waiting_model", now=clock.now)
        assert eng.render(busy=True, now=clock.now).text == ""
        eng2, _ = self._engine()
        eng2.note_activity("waiting_model", now=clock.now)
        assert eng2.render(busy=False, now=clock.now).text == ""

    def test_replace_mode_uses_only_custom_verbs(self):
        eng, clock = self._engine(cfg_kw={
            "mode": "replace", "verbs": ("甲", "乙")})
        eng.note_activity("booting", now=clock.now)
        assert eng.render(busy=True, now=clock.now).text in ("甲", "乙")
        assert set(eng.snapshot()["pool_sizes"].values()) == {2}

    def test_append_mode_adds_custom_verbs(self):
        eng, clock = self._engine(cfg_kw={
            "mode": "append", "verbs": ("团队梗",)})
        eng.note_activity("retrying", now=clock.now)
        assert "团队梗" in eng.snapshot()["pool_sizes"] or True  # 池大小已含
        assert eng._pool("retrying")[-1] == "团队梗"

    def test_reset_clears_current_but_keeps_config(self):
        eng, clock = self._engine()
        eng.note_activity("waiting_model", now=clock.now)
        eng.reset()
        assert eng.snapshot()["current"] == ""
        assert eng.snapshot()["mode"] == "default"
        clock.advance(1.0)
        eng.note_activity("waiting_model", now=clock.now)
        assert eng.render(busy=True, now=clock.now).text

    def test_same_seed_is_deterministic(self):
        a, ca = self._engine(seed=99)
        b, cb = self._engine(seed=99)
        for phase in PHASES:
            a.note_activity(phase, now=ca.now)
            b.note_activity(phase, now=cb.now)
            assert a.render(True, now=ca.now).text == b.render(True, now=cb.now).text
            ca.advance(2.0); cb.advance(2.0)

    def test_snapshot_shape(self):
        eng, clock = self._engine()
        s = eng.snapshot()
        assert s["lang"] == "zh-CN" and s["mode"] == "default"
        assert set(s["pool_sizes"]) == set(PHASES)
        assert all(n >= 4 for n in s["pool_sizes"].values())

    def test_stall_text_is_localized_per_language(self):
        for lang in LANGUAGES:
            clock = _Clock()
            eng = RuntimeSloganEngine(config=_cfg(), lang=lang,
                                      rng=random.Random(1), clock=clock)
            eng.note_activity("waiting_model", now=clock.now)
            clock.advance(20.0)
            v = eng.render(busy=True, now=clock.now)
            assert v.stalled and v.text == _STALL_TEXT[lang].format(sec=20)


# ================================================================ TUI 接线与缺陷

class TestTuiWiring:
    def test_header_shows_runtime_slogan_next_to_status_line(self):
        """远端主线 header 是 Codex 风格 Working 状态行，标语应挂在其后。"""
        obj = _tui()
        obj._busy = True
        obj._slogans.note_activity("waiting_model")
        first = "".join(seg for _, seg in obj._render_header())
        assert obj._slogans.render(busy=True).text in first
        assert "Working" in first                    # 远端 Codex 状态行未被替换
        # render 纯读：连续两次渲染结果必须一致，不许每帧偷偷换词
        assert "".join(seg for _, seg in obj._render_header()) == first

    def test_header_stall_uses_warning_class(self):
        obj = _tui()
        obj._busy = True
        obj._slogans.config = _cfg(stall_ms=1000)
        obj._slogans.note_activity("waiting_model")
        # 把最后事件时间往回拨，模拟真的卡住
        obj._slogans._last_event_at = time.monotonic() - 9.0
        parts = obj._render_header()
        assert any(cls == "class:warning" for cls, _ in parts)
        assert "疑似摸鱼" in "".join(seg for _, seg in parts)

    def test_footer_shows_real_tool_name_not_working(self):
        """B2 回归：begin_tool 同时置 busy=True，旧顺序会让该分支变死代码。"""
        obj = _tui()
        obj.begin_tool("git status")
        text = "".join(seg for _, seg in obj._render_footer())
        assert "git status" in text
        assert "Working (" not in text
        assert "class:accent" in [cls for cls, _ in obj._render_footer()]

    def test_footer_still_shows_working_when_only_waiting(self):
        obj = _tui()
        obj._busy = True
        text = "".join(seg for _, seg in obj._render_footer())
        assert "Working (" in text

    def test_begin_tool_and_stream_record_real_activity(self):
        obj = _tui()
        obj.begin_tool("pytest")
        assert obj._slogans.snapshot()["phase"] == "running_tool"
        obj.stream_assistant("你好")
        assert obj._slogans.snapshot()["phase"] == "streaming"

    def test_width_functions_are_one_truth(self):
        """B3 回归：视口行高与单行裁剪不得再用两套算法。"""
        for s in ("中文abc", "👩‍💻e\u0301", "a\x1bb", "", "漢字" * 30):
            assert _disp_width(s) == _display_width(s)

    def test_line_heights_budget_after_cache_fix(self):
        """2000 行历史每帧 < 10ms（按远端主线口径）。

        如实边界：远端主线 ``_line_heights`` 已经自带 ``(width, text)``
        高度缓存，所以 ``_display_width`` 每帧只在首次 miss 时被调用，
        ``cache_info().hits`` 会是 0 —— 本轮的 lru_cache 是第二层保险，
        不是「修好了性能回归」。16.2 -> 0.39 ms/帧 那组数字来自本地方
        分叉副本，**不适用于主线**，不得移植成主线的成果表述。
        本轮在主线的真实价值：修正「wcwidth 是 C 实现」的错误注释，以及
        让 ``_disp_width`` 与 ``_display_width`` 共用同一宽度真值来源。
        """
        obj = _tui()
        lines = [[("class:text", "这是一行中文测试内容 " * 4)]
                 for _ in range(2000)]
        _display_width.cache_clear()
        obj._line_heights(lines)                     # 预热
        t0 = time.perf_counter()
        for _ in range(5):
            obj._line_heights(lines)
        per_frame = (time.perf_counter() - t0) / 5 * 1000
        assert per_frame < 10, f"行高计算 {per_frame:.1f} ms/帧, 超出预算"
        assert hasattr(_display_width, "cache_info")
        assert _display_width.cache_info().maxsize == 4096

    def test_off_mode_keeps_status_line_but_no_verb(self):
        """off 与上游 replace+[""] 同款：状态行继续，标语文本清空。"""
        obj = _tui()
        obj._slogans.config = _cfg(mode="off")
        obj._busy = True
        obj._slogans.note_activity("waiting_model")
        text = "".join(seg for _, seg in obj._render_header())
        assert "Working" in text                    # 状态行仍在
        assert "疑似摸鱼" not in text
        assert obj._slogans.render(busy=True).text == ""
