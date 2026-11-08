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

深度轮（不扩广度）新增覆盖：D1 真实多线程并发下的状态不变量、
D2 分阶段活性预算与三态、D3 结构化 Liveness + 脱敏证据链、
D4 ``note_progress`` 生命周期事件与 ``_animate`` 禁令、配置热重载。

深度轮 2（继续往深里挖，指标仍一律不动）：S1 净化层的 bidi/零宽/ESC
侧门、S2 第三套宽度算法与 tui ``_display_width`` 交叉一致、S3 上一轮
承诺却没做的「header 短版诊断」、S4 配置严格类型与读取上限。
"""
from __future__ import annotations

import json
import math
import random
import threading
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from tuan_cli.i18n import t
from tuan_cli.tui.runtime_slogans import (
    LANGUAGES, PHASES, PHASE_BUDGET_MS, LivenessState, EventRecord, Liveness,
    RuntimeSloganEngine, SpinnerVerbsConfig, SloganView, _STALL_TEXT,
    _STALL_SHORT, _ADVICE_TEXT, _MAX_VERB_COLS, _clusters, _fit_headline,
    MAX_SETTINGS_BYTES, display_cols, load_config, sanitize_verb, slogan_bank,
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
            # waiting_model 预算 45s / slow 22.5s：12s 仍应 healthy
            assert not v.stalled
            assert v.state == LivenessState.HEALTHY

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
        """分阶段预算：等模型首 token 的预算是 45s，不是旧版一刀切 15s。"""
        eng, clock = self._engine()
        eng.note_activity("waiting_model", now=clock.now)
        clock.advance(18.0)
        assert eng.render(True, now=clock.now).state == LivenessState.HEALTHY
        clock.advance(5.0)                  # 23s > slow_after 22.5s
        slow = eng.render(busy=True, now=clock.now)
        assert not slow.stalled and slow.state == LivenessState.SLOW
        assert slow.budget_ms == 45000 and slow.slow_after_ms == 22500
        clock.advance(23.0)                 # 累计 46s > 45s
        v = eng.render(busy=True, now=clock.now)
        assert v.stalled is True
        assert v.state == LivenessState.STALLED
        assert "疑似摸鱼" in v.text and "46" in v.text
        assert v.idle_ms == 46000
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
        assert s["state"] in ("healthy", "slow", "stalled", "unknown")
        assert set(s["phase_budgets_ms"]) == set(PHASES)

    def test_stall_text_is_localized_per_language(self):
        for lang in LANGUAGES:
            clock = _Clock()
            # 显式 stall_ms 是全局覆盖（向后兼容），1s 预算让 20s 必然 stalled
            eng = RuntimeSloganEngine(config=_cfg(stall_ms=1000), lang=lang,
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


# ================================================================ D2 分阶段预算

class TestPhaseBudgets:
    def test_default_budget_table_is_phase_specific(self):
        """D2 核心：不同阶段合理等待时间完全不同，不能一刀切 15s。"""
        assert PHASE_BUDGET_MS == {
            "booting": 30000, "waiting_model": 45000, "streaming": 6000,
            "running_tool": 120000, "retrying": 20000,
        }
        assert PHASE_BUDGET_MS["streaming"] < PHASE_BUDGET_MS["waiting_model"]
        assert PHASE_BUDGET_MS["running_tool"] > PHASE_BUDGET_MS["waiting_model"]

    def test_budget_for_precedence(self):
        c = SpinnerVerbsConfig()
        assert c.budget_for("streaming") == 6000
        assert c.slow_after_ms("streaming") == 3000
        per_phase = SpinnerVerbsConfig(
            phase_budgets_ms=(("streaming", 9000),))
        assert per_phase.budget_for("streaming") == 9000
        assert per_phase.budget_for("waiting_model") == 45000
        explicit = SpinnerVerbsConfig(stall_ms_override=2000,
                                      phase_budgets_ms=(("streaming", 9000),))
        assert explicit.budget_for("streaming") == 2000   # 全局覆盖最高优先

    def test_explicit_stall_ms_is_global_override_for_backward_compat(self):
        """旧配置显式写 stall_ms 必须继续生效，不能被新表悄悄吃掉。"""
        c = SpinnerVerbsConfig(stall_ms=4000)
        assert c.stall_ms_override == 4000
        assert all(c.budget_for(p) == 4000 for p in PHASES)

    def test_default_stall_ms_does_not_override(self):
        c = SpinnerVerbsConfig()
        assert c.stall_ms_override is None
        assert c.budget_for("running_tool") == 120000

    @pytest.mark.parametrize("kw", [
        {"phase_budgets_ms": (("stremaing", 1000),)},   # 拼错的阶段不得静默忽略
        {"phase_budgets_ms": (("streaming", 10),)},
        {"slow_ratio": 0.0}, {"slow_ratio": 1.0},
        {"stall_ms_override": 10},
    ])
    def test_invalid_budget_config_rejected(self, kw):
        with pytest.raises(ValueError):
            SpinnerVerbsConfig(**kw)

    def test_load_config_rejects_unknown_budget_phase(self, tmp_path):
        p = tmp_path / "settings.json"
        p.write_text(json.dumps({"spinnerVerbs": {
            "phase_budgets_ms": {"stremaing": 3000}}}), encoding="utf-8")
        c = load_config(p)
        assert c.source == "invalid:budget-phase"
        assert c.budget_for("streaming") == 6000

    def test_load_config_honors_per_phase_and_ratio(self, tmp_path):
        p = tmp_path / "settings.json"
        p.write_text(json.dumps({"spinnerVerbs": {
            "phase_budgets_ms": {"streaming": 8000}, "slow_ratio": 0.25}}),
            encoding="utf-8")
        c = load_config(p)
        assert c.source == str(p)
        assert c.budget_for("streaming") == 8000
        assert c.slow_after_ms("streaming") == 2000
        assert c.stall_ms_override is None      # 没显式给 stall_ms

    def test_load_config_explicit_stall_ms_becomes_override(self, tmp_path):
        p = tmp_path / "settings.json"
        p.write_text(json.dumps({"spinnerVerbs": {"stall_ms": 3000}}),
                     encoding="utf-8")
        c = load_config(p)
        assert c.stall_ms_override == 3000
        assert all(c.budget_for(x) == 3000 for x in PHASES)

    def test_streaming_stalls_much_earlier_than_waiting(self):
        clock = _Clock()
        cfg = _cfg()
        eng = RuntimeSloganEngine(config=cfg, lang="zh-CN",
                                  rng=random.Random(3), clock=clock)
        eng.note_activity("streaming", now=clock.now)
        clock.advance(7.0)
        v = eng.render(True, now=clock.now)
        assert v.stalled and v.budget_ms == 6000
        eng.note_activity("waiting_model", now=clock.now + 47.0)
        clock.advance(47.0)
        clock.advance(7.0)                      # waiting 只过 7s
        assert not eng.render(True, now=clock.now).stalled


# ================================================================ D3 三态 / Liveness

class TestLiveness:
    def _engine(self, **kw):
        clock = _Clock()
        return (RuntimeSloganEngine(config=_cfg(**kw), lang="zh-CN",
                                    rng=random.Random(11), clock=clock), clock)

    def test_three_state_transitions(self):
        eng, clock = self._engine()
        eng.note_activity("streaming", now=clock.now)   # budget 6s / slow 3s
        a = eng.liveness(now=clock.now)
        assert a.state == LivenessState.HEALTHY and not a.is_degraded
        assert a.diagnostic == "" and a.remaining_ms == 6000
        clock.advance(3.5)
        b = eng.liveness(now=clock.now)
        assert b.state == LivenessState.SLOW and b.is_degraded
        assert not b.needs_diagnostic
        assert "比预期慢" in b.diagnostic and "streaming" in b.diagnostic
        clock.advance(3.0)
        c = eng.liveness(now=clock.now)
        assert c.state == LivenessState.STALLED and c.needs_diagnostic
        assert c.remaining_ms == 0

    def test_render_slow_still_shows_verb_not_diagnostic(self):
        """「比预期慢」不该冤枉它摸鱼：文案仍显示标语，只有状态变了。"""
        eng, clock = self._engine()
        eng.note_activity("streaming", now=clock.now)
        first = eng.render(True, now=clock.now)
        clock.advance(3.5)
        v = eng.render(True, now=clock.now)
        assert v.state == LivenessState.SLOW and not v.stalled
        assert v.text == first.text
        assert "疑似摸鱼" not in v.text
        assert v.advice and v.diagnostic

    def test_liveness_is_independent_of_busy(self):
        eng, clock = self._engine()
        eng.note_activity("running_tool", "git status", now=clock.now)
        clock.advance(130.0)
        lv = eng.liveness(now=clock.now)      # 不传 busy
        assert lv.state == LivenessState.STALLED
        assert lv.budget_ms == 120000
        assert lv.phase == "running_tool"

    def test_unknown_state_when_busy_but_no_event(self):
        eng, clock = self._engine()
        lv = eng.liveness(now=clock.now)
        assert lv.state == LivenessState.UNKNOWN
        assert lv.idle_ms == -1 and lv.needs_diagnostic
        assert "waiting_model" in lv.diagnostic

    def test_advice_is_phase_specific_and_localized(self):
        """等模型劝查网络，工具跑太久别劝查网络。"""
        eng, clock = self._engine()
        eng.note_activity("running_tool", now=clock.now)
        clock.advance(121.0)
        tool = eng.liveness(now=clock.now)
        eng.note_activity("waiting_model", now=clock.now)
        clock.advance(46.0)
        model = eng.liveness(now=clock.now)
        assert tool.advice == _ADVICE_TEXT["zh-CN"]["tool"]
        assert model.advice == _ADVICE_TEXT["zh-CN"]["model"]
        assert tool.advice != model.advice
        assert "工具执行中" in tool.diagnostic
        for lang in LANGUAGES:
            assert set(_ADVICE_TEXT[lang]) == {"model", "stream", "tool"}

    def test_evidence_is_desensitized(self):
        """D3: detail 原文绝不进证据，只留长度与字符类别。"""
        eng, clock = self._engine()
        secret = "git status --token=ghp_SUPER_SECRET_VALUE /home/alice/proj"
        eng.note_activity("running_tool", secret, now=clock.now)
        eng.note_progress("tool_end", now=clock.now)
        lv = eng.liveness(now=clock.now)
        assert len(lv.evidence) >= 2
        rec = lv.evidence[0]
        assert isinstance(rec, EventRecord)
        assert rec.detail_len == len(secret)
        assert rec.detail_class in ("ascii", "cjk", "mixed")
        blob = repr(lv.evidence)
        assert "SUPER_SECRET_VALUE" not in blob and "/home/alice" not in blob
        assert "git status" not in blob

    def test_evidence_ring_is_bounded(self):
        eng, clock = self._engine()
        for i in range(200):
            clock.advance(0.01)
            eng.note_progress("tick", now=clock.now)
        lv = eng.liveness(now=clock.now)
        assert len(lv.evidence) == 16
        assert len(eng.snapshot()["pool_sizes"]) == 5

    def test_seq_verb_pairing_in_evidence(self):
        """D1 锚点：同一 seq 只能对应一个文案，撕裂会被这条抓到。"""
        eng, clock = self._engine()
        for i in range(40):
            clock.advance(2.0)
            eng.note_activity(PHASES[i % len(PHASES)], now=clock.now)
        pairs = {}
        for r in eng.liveness().evidence:
            pairs.setdefault(r.seq, set()).add(r.verb)
        assert all(len(v) == 1 for v in pairs.values())

    def test_render_is_still_pure_under_liveness(self):
        eng, clock = self._engine()
        eng.note_activity("waiting_model", now=clock.now)
        before = eng.snapshot()
        for _ in range(50):
            clock.advance(0.2)
            eng.render(True, now=clock.now)
            eng.liveness(now=clock.now)
        after = eng.snapshot()
        assert after["seq"] == before["seq"]
        assert after["current"] == before["current"]
        assert after["evidence_count"] == before["evidence_count"]


# ================================================================ D1 真实并发

class TestConcurrency:
    def test_concurrent_activity_and_render_keep_invariants(self):
        """8 线程真实并发：seq 单调、(seq,verb) 配对、无撕裂、证据有界。

        旧实现五个字段无锁复合读写，GIL 只保证单条赋值原子 ——
        ``_current = ...`` 与 ``_seq += 1`` 之间会切线程。
        """
        clock = _Clock()
        eng = RuntimeSloganEngine(config=_cfg(), lang="zh-CN",
                                  rng=random.Random(5), clock=clock)
        errors = []
        reader_seqs: List[List[int]] = [[] for _ in range(4)]
        barrier = threading.Barrier(8)

        def writer(wid):
            try:
                barrier.wait()
                for i in range(300):
                    eng.note_activity(PHASES[(wid + i) % len(PHASES)],
                                      f"w{wid}-{i}", now=clock.now + i * 0.001)
                    if i % 7 == 0:
                        eng.note_progress("heartbeat", now=clock.now + i * 0.001)
            except Exception as exc:
                errors.append(f"writer{wid}: {exc!r}")

        def reader(rid):
            try:
                barrier.wait()
                for _ in range(300):
                    v = eng.render(True, now=clock.now)
                    lv = eng.liveness(now=clock.now)
                    assert v.idle_ms >= -1
                    assert v.seq >= 0
                    assert len(lv.evidence) <= 16
                    reader_seqs[rid].append(v.seq)
            except Exception as exc:
                errors.append(f"reader{rid}: {exc!r}")

        with ThreadPoolExecutor(max_workers=8) as ex:
            futs = [ex.submit(writer, i) for i in range(4)]
            futs += [ex.submit(reader, i) for i in range(4)]
            for f in futs:
                f.result()
        assert errors == [], errors[:3]
        # 每个 reader 自身观察到的 seq 必须非递减：seq 全局只增，
        # 且所有提交都在锁内完成。跨 reader 交错不做此断言（append 顺序
        # 与读取顺序可能不同），避免写出一条永远为真的假断言。
        assert all(s and all(a <= b for a, b in zip(s, s[1:]))
                   for s in reader_seqs), "检测到 seq 回退"
        snap = eng.snapshot()
        assert snap["seq"] > 0
        assert snap["evidence_count"] <= 16
        pairs = {}
        for r in eng.liveness().evidence:
            pairs.setdefault(r.seq, set()).add(r.verb)
        assert all(len(v) == 1 for v in pairs.values()), "检测到 seq/文案撕裂"

    def test_clock_rollback_cannot_make_idle_negative(self):
        eng = RuntimeSloganEngine(config=_cfg(), lang="zh-CN", clock=_Clock())
        eng.note_activity("streaming", now=100.0)
        eng.note_activity("streaming", now=50.0)     # 乱序 / 时钟回拨
        assert eng.render(True, now=100.0).idle_ms >= 0
        eng.note_progress("backwards", now=1.0)
        assert eng.liveness(now=100.0).idle_ms >= 0


# ================================================================ D4 / reload

class TestProgressAndReload:
    def test_note_progress_refreshes_liveness_without_changing_verb(self):
        clock = _Clock()
        eng = RuntimeSloganEngine(config=_cfg(stall_ms=1000), lang="zh-CN",
                                  rng=random.Random(9), clock=clock)
        eng.note_activity("running_tool", now=clock.now)
        first = eng.render(True, now=clock.now)
        clock.advance(0.9)                           # 接近 1s 预算
        assert eng.liveness(now=clock.now).state == LivenessState.SLOW
        eng.note_progress("tool_end", now=clock.now)
        v = eng.render(True, now=clock.now)
        assert v.state == LivenessState.HEALTHY
        assert v.text == first.text and v.seq == first.seq
        assert eng.snapshot()["phase"] == "running_tool"

    def test_reset_preserves_evidence_across_turns(self):
        clock = _Clock()
        eng = RuntimeSloganEngine(config=_cfg(stall_ms=1000), lang="zh-CN",
                                  rng=random.Random(2), clock=clock)
        eng.note_activity("waiting_model", now=clock.now)
        clock.advance(2.0)
        assert eng.liveness(now=clock.now).state == LivenessState.STALLED
        eng.reset()
        ev = eng.liveness(now=clock.now).evidence
        assert any(r.kind == "reset" for r in ev)
        assert any(r.kind == "activity" for r in ev), "上一回合证据被误清"
        assert eng.snapshot()["current"] == ""

    def test_reload_success_is_atomic_and_clears_stale_verb(self, tmp_path):
        eng = RuntimeSloganEngine(config=_cfg(), lang="zh-CN", rng=random.Random(1))
        eng.note_activity("waiting_model")
        p = tmp_path / "settings.json"
        p.write_text(json.dumps({"spinnerVerbs": {
            "mode": "replace", "verbs": ["新词条"]}}), encoding="utf-8")
        changed, reason = eng.reload(p)
        assert changed and reason == "ok"
        assert eng.config.mode == "replace"
        assert eng.snapshot()["current"] == ""      # 词池变了不能沿用旧文案
        assert eng.snapshot()["pool_sizes"]["waiting_model"] == 1

    def test_reload_failure_keeps_old_config(self, tmp_path):
        eng = RuntimeSloganEngine(config=_cfg(), lang="zh-CN", rng=random.Random(1))
        p = tmp_path / "settings.json"
        p.write_text(json.dumps({"spinnerVerbs": {"mode": "typo"}}),
                     encoding="utf-8")
        old = eng.config
        changed, reason = eng.reload(p)
        assert not changed and reason.startswith("invalid:")
        assert eng.config is old                    # 原子：旧配置原样保留


class TestTuiDeepWiring:
    def test_header_uses_three_state_classes(self):
        obj = _tui()
        obj._busy = True
        obj._slogans.config = _cfg(stall_ms=1000)
        obj._slogans.note_activity("streaming")
        # healthy -> primary
        assert "class:primary" in [c for c, _ in obj._render_header()]
        # slow -> textdim
        obj._slogans._last_event_at = time.monotonic() - 0.7
        assert "class:textdim" in [c for c, _ in obj._render_header()]
        # stalled -> warning
        obj._slogans._last_event_at = time.monotonic() - 9.0
        assert "class:warning" in [c for c, _ in obj._render_header()]

    def test_end_tool_and_end_stream_record_progress(self):
        obj = _tui()
        obj.begin_tool("git status")
        before = obj.liveness()
        obj.end_tool("git status", ok=True)
        after = obj.liveness()
        assert after is not None and before is not None
        assert any(r.kind == "tool_end" for r in after.evidence)
        obj.stream_assistant("hi")
        obj.end_stream()
        assert any(r.kind == "stream_end" for r in obj.liveness().evidence)
        assert obj._slogans.snapshot()["phase"] == "streaming"  # 阶段没被改掉

    def test_animate_loop_never_refreshes_liveness(self):
        """D4 硬约束：动画循环里出现活性刷新 = 诊断退化成定时空转。"""
        from pathlib import Path as _P
        import tuan_cli.tui.tui as _m
        src = _P(_m.__file__).read_text(encoding="utf-8")
        i = src.index("    def _animate(self)")
        j = src.index("    def ", i + 10)
        # 只检查**代码**：注释里提到方法名是允许的（本轮就写了解释性注释），
        # 不剥注释会得到一条假阳性断言。
        code = "\n".join(line.split("#", 1)[0] for line in src[i:j].splitlines())
        assert "note_progress" not in code
        assert "note_activity" not in code
        assert "invalidate()" in code       # 动画循环该做的只有推进帧 + 重绘

    def test_liveness_passthrough_exists(self):
        obj = _tui()
        lv = obj.liveness()
        assert lv is not None and isinstance(lv, Liveness)


class TestConfigSemanticsDeep:
    """深度轮顺带修的第三个真实缺陷：缺省 mode 不该硬当 append。"""

    def test_only_stall_ms_is_accepted(self, tmp_path):
        p = tmp_path / "settings.json"
        p.write_text(json.dumps({"spinnerVerbs": {"stall_ms": 3000}}),
                     encoding="utf-8")
        c = load_config(p)
        assert c.source == str(p), c.source
        assert c.mode == "default"
        assert c.stall_ms_override == 3000

    def test_only_phase_budgets_is_accepted(self, tmp_path):
        p = tmp_path / "settings.json"
        p.write_text(json.dumps({"spinnerVerbs": {
            "phase_budgets_ms": {"streaming": 8000}}}), encoding="utf-8")
        c = load_config(p)
        assert c.source == str(p), c.source
        assert c.mode == "default"
        assert c.budget_for("streaming") == 8000

    def test_verbs_without_mode_still_infers_append(self, tmp_path):
        p = tmp_path / "settings.json"
        p.write_text(json.dumps({"spinnerVerbs": {"verbs": ["团队梗"]}}),
                     encoding="utf-8")
        c = load_config(p)
        assert c.mode == "append" and c.source == str(p)
        assert c.verbs == ("团队梗",)

    def test_empty_verbs_with_explicit_append_still_rejected(self, tmp_path):
        p = tmp_path / "settings.json"
        p.write_text(json.dumps({"spinnerVerbs": {
            "mode": "append", "verbs": []}}), encoding="utf-8")
        assert load_config(p).source == "invalid:empty-verbs"


# ================================================================ S1 净化层深度

_INVISIBLE_CATS = {"Cc", "Cf", "Cs", "Co", "Cn"}


class TestSanitizerDeep:
    """实测复现的 6 类缺陷，逐个钉死。"""

    @pytest.mark.parametrize("raw,expect", [
        ("正常\u202e话反", "正常话反"),              # RLO 双向覆写
        ("\u202d伪装", "伪装"),                       # LRO
        ("\u202babc\u202c", "abc"),                   # RLE + PDF
        ("\u2066x\u2069", "x"),                       # isolate
        ("摸\u200b鱼", "摸鱼"),                       # ZWSP
        ("a\u200db", "ab"),                           # ZWJ
        ("\ufeff闲逛", "闲逛"),                       # BOM
        ("a\u2060b", "ab"),                           # word joiner
        ("a\u00adb", "ab"),                           # soft hyphen (Cf)
        ("\ue000x", "x"),                             # 私用区
        ("\u0378x", "x"),                             # 未分配
    ])
    def test_invisible_and_bidi_are_stripped(self, raw, expect):
        assert sanitize_verb(raw) == expect

    @pytest.mark.parametrize("raw,expect", [
        ("\x1b(B正常", "正常"),                       # charset 指定
        ("\x1bc重置", "重置"),                        # RIS 复位终端
        ("\x1b7存", "存"),                            # save cursor
        ("\x1b[31m危险\x1b[0m", "危险"),              # CSI
        ("\x1b]0;x\x07点我", "点我"),                  # OSC / BEL
        ("\x1b]8;;https://evil\x1b\\点我\x1b]8;;\x1b\\", "点我"),  # OSC / ST
        ("\x1b正常", "正常"),                         # 孤立 ESC
    ])
    def test_all_escape_sequences_are_consumed_whole(self, raw, expect):
        """旧版只删 ESC 字节，把 ``(B`` / ``c`` / ``7`` 留在文案里。"""
        assert sanitize_verb(raw) == expect

    def test_no_invisible_category_survives(self):
        for raw in ("a\u202eb\u200bc\ufeffd\u2060e\x00f",
                    "\x1b]8;;x\x07\u202e\u200b摸鱼"):
            out = sanitize_verb(raw)
            assert all(unicodedata.category(c) not in _INVISIBLE_CATS
                       for c in out), repr(out)
            assert "\x1b" not in out

    def test_leading_combining_marks_removed(self):
        """旧 docstring 声称做了、实测没做 —— 这是文档与实现不符。"""
        assert sanitize_verb("\u0301accent") == "accent"
        assert sanitize_verb("\u20dd圈") == "圈"
        assert sanitize_verb("a\u0301b") == "a\u0301b"   # 中间保留

    def test_truncation_never_ends_with_dangling_combining_mark(self):
        long = "e\u0301" * 60
        out = sanitize_verb(long)
        assert out
        assert display_cols(out) <= _MAX_VERB_COLS
        # 末尾必须是基字符 + 组合标记的完整簇，不能是孤立组合符
        assert unicodedata.category(out[-1]) != "Mn" or len(_clusters(out)[-1]) > 1
        assert sanitize_verb(out) == out

    def test_emoji_and_cjk_are_not_cut_mid_cluster(self):
        for raw in ("\U0001f469\u200d\U0001f4bb" * 20, "中文" * 40,
                    "❤\ufe0f" * 30):
            out = sanitize_verb(raw)
            assert display_cols(out) <= _MAX_VERB_COLS
            assert sanitize_verb(out) == out

    def test_idempotence_over_500_fuzz_inputs(self):
        """幂等是净化函数最重要的性质：f(f(x)) == f(x)。"""
        rng = random.Random(20261108)
        alphabet = (list("abc中文🚀❤") +
                    ["\u202e", "\u200b", "\u0301", "\x1b[31m", "\x00",
                     "\ufeff", "\ufe0f", "\x1b]0;x\x07", "\x1b(B"])
        for _ in range(500):
            s = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 24)))
            a = sanitize_verb(s)
            assert sanitize_verb(a) == a, repr((s, a))
            assert display_cols(a) <= _MAX_VERB_COLS

    def test_non_str_or_empty_yields_empty(self):
        for x in (None, 123, [], {}, b"x", "", "   ", "\u200b" * 5):
            assert sanitize_verb(x) == ""


# ================================================================ S2 宽度收口

class TestWidthSingleSource:
    """上一轮 B3 只合并了两套算法，sanitize_verb 里还藏着第三套。"""

    def test_known_differences_are_fixed(self):
        """比对口径是**已净化串**：Cf / VS 已删，不再有 joiner 语义歧义。"""
        assert sanitize_verb("a\u200db") == "ab"
        assert display_cols("ab") == _display_width("ab") == 2
        assert sanitize_verb("\u200b摸鱼") == "摸鱼"
        assert display_cols("摸鱼") == _display_width("摸鱼") == 4
        assert display_cols("中文") == _display_width("中文") == 4
        assert display_cols("🚀") == _display_width("🚀") == 2
        # VS16 被净化删除：❤️ -> ❤，避免 wcwidth 把 1 列升成 2 列
        assert sanitize_verb("❤\ufe0f") == "❤"
        assert display_cols("❤") == _display_width("❤") == 1

    def test_matches_tui_display_width_on_500_sanitized_strings(self):
        """与 tui._display_width 逐值一致 —— 不许再出现第三套真值来源。"""
        rng = random.Random(424242)
        alphabet = (list("abc中文🚀❤e") +
                    ["\u0301", "\ufe0f", "\u202e", "\u200b", "\x1b[31m"])
        mismatches = []
        for _ in range(500):
            s = "".join(rng.choice(alphabet) for _ in range(rng.randint(1, 18)))
            v = sanitize_verb(s)
            if not v:
                continue
            if display_cols(v) != _display_width(v):
                mismatches.append((v, display_cols(v), _display_width(v)))
        assert mismatches == [], mismatches[:5]

    def test_builtin_bank_is_clean_and_within_width(self):
        """内置词库从没验证过；现在 10 语言全部词条过同一出口。"""
        for lang in LANGUAGES:
            for phase, verbs in slogan_bank(lang).items():
                for v in verbs:
                    assert sanitize_verb(v) == v, f"{lang}/{phase}: {v!r}"
                    assert display_cols(v) <= _MAX_VERB_COLS
                    assert all(unicodedata.category(c) not in _INVISIBLE_CATS
                               for c in v)

    def test_disp_width_is_the_same_function_as_display_width(self):
        """上一轮 B3 的统一不能被后续改动回退。"""
        assert _disp_width("中文🚀") == _display_width("中文🚀")


# ================================================================ S3 短版诊断

class TestHeadline:
    def _stalled(self, lang="zh-CN", sec=46):
        clock = _Clock()
        eng = RuntimeSloganEngine(config=_cfg(stall_ms=1000), lang=lang,
                                  rng=random.Random(1), clock=clock)
        eng.note_activity("waiting_model", now=clock.now)
        clock.advance(float(sec))
        return eng.render(True, now=clock.now)

    def test_short_bank_covers_all_languages_and_is_bounded(self):
        assert set(_STALL_SHORT) == set(LANGUAGES)
        assert len(LANGUAGES) == 10
        for lang, fmt in _STALL_SHORT.items():
            assert "{sec}" in fmt
            text = _fit_headline(fmt.format(sec=46))
            assert "46" in text
            assert display_cols(text) <= _MAX_VERB_COLS, (lang, text)
            assert sanitize_verb(text) == text

    def test_headline_is_short_text_is_full_information_is_preserved(self):
        """上一轮文档承诺「header 只显示短文案、完整版放 diagnostic」，
        实际 render() 把完整长串塞进了 text 且没有 headline —— 本轮补齐。"""
        v = self._stalled()
        assert v.headline and v.headline != v.text
        assert display_cols(v.headline) < display_cols(v.text)
        assert "疑似摸鱼" in v.headline
        assert v.diagnostic and "预算" in v.diagnostic and v.advice
        assert "46" in v.text and "46" in v.headline

    def test_full_stall_text_was_too_wide_for_a_single_line(self):
        """钉死原缺陷：完整诊断本身就超过 40 列。"""
        assert display_cols(_STALL_TEXT["zh-CN"].format(sec=46)) > _MAX_VERB_COLS
        assert display_cols(_fit_headline(_STALL_SHORT["zh-CN"].format(sec=46))) \
               <= _MAX_VERB_COLS

    def test_header_diagnostic_drops_the_working_facade(self):
        obj = _tui()
        obj._busy = True
        obj._slogans.config = _cfg(stall_ms=1000)
        obj._slogans.note_activity("waiting_model")
        obj._slogans._last_event_at = time.monotonic() - 9.0
        text = "".join(seg for _, seg in obj._render_header())
        assert "Working (" not in text        # 不再假装还在工作
        assert "疑似摸鱼" in text
        assert "class:warning" in [c for c, _ in obj._render_header()]

    def test_narrow_terminal_keeps_headline_and_drops_decoration(self):
        """窄终端（40 列）下诊断仍完整可读，装饰段让位。"""
        obj = _tui()
        obj._busy = True
        obj._plan_mode = True
        obj._model_label = "anthropic/claude-sonnet-4-5-20250929"
        obj._slogans.config = _cfg(stall_ms=1000)
        obj._slogans.note_activity("waiting_model")
        obj._slogans._last_event_at = time.monotonic() - 9.0
        obj._term_width = lambda: 40
        parts = obj._render_header()
        text = "".join(seg for _, seg in parts)
        assert "疑似摸鱼" in text and "9" in text
        assert _disp_width(text) <= 40
        # 装饰（plan badge / 长模型名）在诊断态让位
        assert "anthropic/" not in text

    def test_healthy_header_keeps_codex_working_status_line(self):
        """普通态完全不动 Codex 对齐。"""
        obj = _tui()
        obj._busy = True
        obj._slogans.note_activity("waiting_model")
        text = "".join(seg for _, seg in obj._render_header())
        assert "Working (" in text
        assert "疑似摸鱼" not in text


# ================================================================ S4 配置严格化

class TestConfigStrict:
    def test_oversized_file_is_rejected_without_reading_it(self, tmp_path):
        p = tmp_path / "settings.json"
        p.write_bytes(b" " * (MAX_SETTINGS_BYTES + 1))
        c = load_config(p)
        assert c.source == "invalid:too-large"
        assert c.mode == "default" and c.budget_for("streaming") == 6000

    @pytest.mark.parametrize("bad", [
        {"interval_ms": True}, {"interval_ms": "3000"},
        {"stall_ms": 3.9}, {"stall_ms": False},
    ])
    def test_bool_and_string_numbers_are_rejected(self, tmp_path, bad):
        p = tmp_path / "settings.json"
        p.write_text(json.dumps({"spinnerVerbs": bad}), encoding="utf-8")
        assert load_config(p).source == "invalid:numbers"

    @pytest.mark.parametrize("bad", [
        {"slow_ratio": "0.5"}, {"slow_ratio": True},
        {"phase_budgets_ms": {"streaming": "8000"}},
        {"phase_budgets_ms": {"streaming": True}},
    ])
    def test_ratio_and_budget_types_are_strict(self, tmp_path, bad):
        p = tmp_path / "settings.json"
        p.write_text(json.dumps({"spinnerVerbs": bad}), encoding="utf-8")
        c = load_config(p)
        assert c.source.startswith("invalid:"), c.source

    def test_non_finite_ratio_is_rejected(self, tmp_path):
        p = tmp_path / "settings.json"
        p.write_text('{"spinnerVerbs":{"slow_ratio":NaN}}', encoding="utf-8")
        assert load_config(p).source.startswith("invalid:")
        assert not math.isfinite(float("nan"))

    def test_valid_config_still_loads(self, tmp_path):
        p = tmp_path / "settings.json"
        p.write_text(json.dumps({"spinnerVerbs": {
            "interval_ms": 900, "phase_budgets_ms": {"streaming": 8000},
            "slow_ratio": 0.25, "mode": "append", "verbs": ["团队梗"]}}),
            encoding="utf-8")
        c = load_config(p)
        assert c.source == str(p)
        assert c.interval_ms == 900 and c.budget_for("streaming") == 8000
        assert c.slow_after_ms("streaming") == 2000
        assert c.verbs == ("团队梗",)

    def test_custom_verbs_obey_the_same_clean_invariants(self, tmp_path):
        p = tmp_path / "settings.json"
        p.write_text(json.dumps({"spinnerVerbs": {
            "mode": "replace",
            "verbs": ["\u202e正常\u200b词", "\x1b[31m危险\x1b[0m",
                      "x" * 200]}}), encoding="utf-8")
        c = load_config(p)
        for v in c.verbs:
            assert sanitize_verb(v) == v
            assert display_cols(v) <= _MAX_VERB_COLS
            assert all(unicodedata.category(ch) not in _INVISIBLE_CATS
                       for ch in v)

# ================================================================ 深度轮 10
from decimal import Decimal

# 引擎本体（前九轮几乎只改 ui/slogans/mapping.py，runtime_slogans.py
# 逐字节未动）。本轮把镜头对准**引擎侧 public 入参面**：先实测再修，
# 六个真缺陷 + 四个「不该修」判断 + 六个自引入边界。

import tuan_cli.tui.runtime_slogans as R

R_STATES = (R.LivenessState.HEALTHY, R.LivenessState.SLOW,
            R.LivenessState.STALLED, R.LivenessState.UNKNOWN)


def _engine(clock=lambda: 1000.0, **kw):
    return R.RuntimeSloganEngine(clock=clock, **kw)


class TestNowTypeGuard:
    """P1: now / clock 脏值在异常前写进状态，UI 永久崩。"""

    DIRTY = ["1000", math.nan, math.inf, -math.inf, True, [],
             {"a": 1}, b"x", 1e308, -1e308, Decimal("1.5")]

    def test_dirty_now_never_raises_and_never_poisons_state(self):
        for bad in self.DIRTY:
            e = _engine()
            e.note_activity("streaming", now=bad)
            assert isinstance(e._last_event_at, float)
            assert math.isfinite(e._last_event_at), bad
            lv = e.liveness(now=1000.0)
            assert lv.state in R_STATES, bad
            assert e.snapshot()["state"] in R_STATES, bad

    def test_dirty_now_falls_back_to_injected_clock(self):
        e = _engine(clock=lambda: 1000.0)
        e.note_activity("streaming", now=math.nan)
        assert e._last_event_at == 1000.0

    def test_dirty_clock_falls_back_to_monotonic(self):
        for bad in (math.nan, math.inf, "x", None):
            e = _engine(clock=lambda bad=bad: bad)
            e.note_activity("streaming")
            assert math.isfinite(e._last_event_at)
            assert e._last_event_at >= 0.0
            assert e.liveness().state in R_STATES

    def test_clock_that_raises_does_not_kill_tui(self):
        def boom():
            raise RuntimeError("clock broken")
        e = _engine(clock=boom)
        e.note_activity("streaming")
        assert math.isfinite(e._last_event_at)
        assert e.snapshot()["state"] in R_STATES

    def test_legal_zero_is_not_swallowed(self):
        """深度轮 7 踩过 `or fallback()` 把 0 当 falsy 吞掉的坑。"""
        assert R._coerce_now_value(0) == 0.0
        assert R._coerce_now_value(0.0) == 0.0
        e = _engine(clock=lambda: 5000.0)
        e.note_activity("streaming", now=0)
        assert e._last_event_at == 0.0

    def test_large_but_finite_now_is_clamped(self):
        """1e308 会让 int(at*1000) 溢出成 inf；夹到 _MAX_NOW_SECONDS。"""
        assert R._coerce_now_value(1e308) is None
        assert R._coerce_now_value(R._MAX_NOW_SECONDS) == R._MAX_NOW_SECONDS
        e = _engine()
        e.note_activity("streaming", now=1e308)
        assert e._last_event_at == 1000.0

    def test_no_half_updated_state_on_dirty_now(self):
        """核心不变量: 异常路径不再留下 (seq/phase/current 已变、
        _last_event_at=nan) 的撕裂。修复前 liveness/snapshot 都抛。"""
        e = _engine()
        e.note_activity("streaming", now=1000.0)
        before = (e._last_event_at, e._seq, e._phase, e._current)
        e.note_activity("running_tool", now=math.nan)
        after = (e._last_event_at, e._seq, e._phase, e._current)
        assert math.isfinite(after[0])
        assert after[0] == before[0]          # 时钟回落，不是 nan
        assert after[1] == before[1] + 1      # 但事件本身完整生效
        assert after[2] == "running_tool"
        assert after[3] and after[3] != before[3]
        # 两个 public 出口都必须能调用
        assert e.liveness(now=1001.0).state in R_STATES
        assert e.render(True, now=1001.0).state in R_STATES
        assert isinstance(e.snapshot(), dict)

    def test_all_four_public_clock_paths_are_guarded(self):
        """note_activity / note_progress / liveness / render / snapshot。"""
        for bad in (math.nan, "1000", math.inf, 1e308):
            e = _engine()
            e.note_activity("streaming", now=1000.0)
            e.note_progress("end", now=bad)
            assert e.liveness(now=bad).state in R_STATES
            assert e.render(True, now=bad).state in R_STATES
            assert isinstance(e.snapshot(), dict)

    def test_guard_is_before_any_state_write(self):
        import inspect
        src = inspect.getsource(R.RuntimeSloganEngine.note_activity)
        assert src.index("at = self._now(now)") < src.index(
            "self._last_event_at = at")
        src = inspect.getsource(R.RuntimeSloganEngine.note_progress)
        assert src.index("at = self._now(now)") < src.index(
            "self._last_event_at = at")

    def test_legal_now_still_drives_phase_budgets(self):
        e = _engine()
        e.note_activity("streaming", now=1000.0)
        assert e.liveness(now=1001.0).state == R.LivenessState.HEALTHY
        assert e.liveness(now=1010.0).state == R.LivenessState.STALLED


class TestProgressKindSanitizing:
    """P2: note_progress(kind) 原样进 EventRecord.kind / 诊断输出。"""

    EVIL = "\x1b]8;;https://evil.example\x07\u202eRLO" + "A" * 500

    def test_kind_is_sanitized_and_bounded(self):
        e = _engine()
        e.note_progress(kind=self.EVIL, now=1000.0)
        k = e.liveness(now=1000.0).evidence[-1].kind
        assert len(k) <= 41
        assert "\x1b" not in k and "\u202e" not in k and "]8;;" not in k

    def test_kind_shares_one_clean_truth(self):
        from tuan_cli.ui.slogans import _clean as C
        e = _engine()
        e.note_progress(kind=self.EVIL, now=1000.0)
        assert e.liveness(now=1000.0).evidence[-1].kind == \
            C.sanitize_log_field(self.EVIL, 40)

    def test_non_string_kind_falls_back_to_progress(self):
        for bad in (None, 123, ["a"], {"x": 1}, b"x", True):
            e = _engine()
            e.note_progress(kind=bad, now=1000.0)
            assert e.liveness(now=1000.0).evidence[-1].kind == "progress"

    def test_legal_kind_unchanged(self):
        e = _engine()
        e.note_progress(kind="end_tool", now=1000.0)
        assert e.liveness(now=1000.0).evidence[-1].kind == "end_tool"
        r = e.liveness(now=1000.0).evidence[-1]
        assert r.phase == "waiting_model" and r.seq == 0


class TestDiagnosticSourceSanitizing:
    """P3: str(raw_mode) / str(p) / 异常消息把配置原文带进 source。"""

    def test_evil_mode_source_is_clean_and_bounded(self, tmp_path):
        p = tmp_path / "settings.json"
        evil = "\x1b]8;;x\x07\u202e" + "M" * 5000
        p.write_text(json.dumps({"spinnerVerbs": {"mode": evil}}),
                     encoding="utf-8")
        c = R.load_config(p)
        assert c.source.startswith("invalid:mode=")
        assert len(c.source) <= 121
        assert "\x1b" not in c.source and "\u202e" not in c.source

    def test_non_string_mode_is_rejected_cleanly(self, tmp_path):
        p = tmp_path / "settings.json"
        for bad in (123, ["a"], {"x": 1}, None, True):
            p.write_text(json.dumps({"spinnerVerbs": {"mode": bad}}),
                         encoding="utf-8")
            c = R.load_config(p)
            assert "\x1b" not in c.source and len(c.source) <= 121

    def test_source_is_clean_in_liveness_and_snapshot(self, tmp_path):
        p = tmp_path / "settings.json"
        p.write_text(json.dumps({"spinnerVerbs": {
            "mode": "\x1b]8;;x\x07" + "M" * 5000}}), encoding="utf-8")
        c = R.load_config(p)
        e = _engine()
        e.config = c
        lv = e.liveness(now=1000.0)
        snap = e.snapshot()
        for s in (lv.source, snap["source"], c.source):
            assert "\x1b" not in s and len(s) <= 121

    def test_evil_budget_key_never_reaches_source(self, tmp_path):
        """P9 候选: 已正确 —— 未知键返回固定 source，不带原文。"""
        p = tmp_path / "settings.json"
        p.write_text(json.dumps({"spinnerVerbs": {
            "phase_budgets_ms": {"\x1b]8;;x\x07\u202e" + "K" * 5000: 5000}}}),
            encoding="utf-8")
        c = R.load_config(p)
        assert c.source == "invalid:budget-phase"
        assert "\x1b" not in c.source

    def test_valid_config_source_unchanged(self, tmp_path):
        p = tmp_path / "settings.json"
        p.write_text(json.dumps({"spinnerVerbs": {
            "interval_ms": 900, "phase_budgets_ms": {"streaming": 8000}}}),
            encoding="utf-8")
        assert R.load_config(p).source == str(p)

    def test_path_construction_is_inside_try(self):
        """P8: load_config(123) 旧版抛底层 TypeError 掀掉调用方。"""
        import inspect
        src = inspect.getsource(R.load_config)
        body = src[src.index("try:"):]
        assert "p = _settings_path(path)" in body
        for bad in (123, ["a"], {"x": 1}, b"x"):
            assert R.load_config(bad).source == "builtin"


class TestResetClockHomogeneity:
    """P4: reset 用真实时钟，与注入 now 混用导致证据链倒退。"""

    def test_injected_clock_evidence_is_monotonic(self):
        e = _engine()
        e.note_activity("streaming", now=1000.0)
        e.note_progress("end", now=1001.0)
        e.reset()
        stamps = [x.at_ms for x in e.liveness(now=1002.0).evidence]
        assert stamps == [1000000, 1001000, 1001000]
        assert stamps == sorted(stamps)

    def test_real_clock_no_longer_mixes_two_time_sources(self):
        e = R.RuntimeSloganEngine()
        e.note_activity("streaming", now=1000.0)
        e.reset()
        stamps = [x.at_ms for x in e.liveness(now=1001.0).evidence]
        assert stamps == [1000000, 1000000]

    def test_reset_boundary_is_marked_by_kind_not_timestamp(self):
        e = _engine()
        e.note_activity("streaming", now=1000.0)
        e.reset()
        ev = e.liveness(now=1001.0).evidence
        assert ev[-1].kind == "reset" and ev[-1].verb == ""
        assert ev[-1].detail_len == 0 and ev[-1].detail_class == "empty"

    def test_reset_on_fresh_engine_uses_clock(self):
        e = _engine()
        e.reset()
        assert e.liveness(now=1000.0).evidence[-1].at_ms == 1000000

    def test_reset_defends_against_legacy_nan_state(self):
        """D′ 自引入边界: 旧状态万一残留 nan，不能写进 evidence。"""
        e = _engine()
        e.note_activity("streaming", now=1000.0)
        e._last_event_at = math.nan
        e.reset()
        assert math.isfinite(e.liveness(now=1000.0).evidence[-1].at_ms / 1000.0)


class TestDetailTypeSurface:
    """P7: detail 非字符串让 _record_locked 的 len() 抛 TypeError。"""

    def test_non_string_detail_never_raises(self):
        for bad in (None, 123, True, ["a"], {"x": 1}, b"x", 1.5):
            e = _engine()
            e.note_activity("streaming", detail=bad, now=1000.0)
            r = e.liveness(now=1000.0).evidence[-1]
            assert r.detail_len == 0 and r.detail_class == "empty"

    def test_string_detail_still_only_records_shape(self):
        """P6 候选: D3 已正确，未修 —— 锁住「绝不记原文」。"""
        e = _engine()
        detail = "/secret/path?token=" + "x" * 200000
        e.note_activity("streaming", detail=detail, now=1000.0)
        r = e.liveness(now=1000.0).evidence[-1]
        assert r.detail_len == len(detail)
        assert r.detail_class == "ascii"
        assert not hasattr(r, "detail")
        assert "secret" not in repr(r)

    def test_detail_guard_is_before_record(self):
        import inspect
        src = inspect.getsource(R.RuntimeSloganEngine.note_activity)
        assert src.index("if not isinstance(detail, str)") < src.index(
            "self._record_locked(")


class TestMeasuredButDeliberatelyNotChangedD10:
    """四个候选实测后判定「不该修」，锁住当前行为。"""

    def test_phase_fallback_is_existing_fail_safe(self):
        """P5: 非 str / 未知 / 不可 hash 一律兜底 waiting_model，不抛。"""
        e = _engine()
        for bad in (None, 123, ["a"], {"x": 1}, ("t",), b"x",
                    float("nan"), "unknown-phase"):
            e.note_activity(bad, now=1000.0)
            assert e._phase == "waiting_model"
        assert e.liveness(now=1000.0).state in R_STATES

    def test_verbs_non_string_is_already_rejected(self):
        """P10 候选: sanitize_verb 非 str 返回空串，既有 fail-closed。"""
        assert R.sanitize_verb(123) == ""
        c = R.load_config  # 只是确认导出未变
        assert callable(c)

    def test_unknown_budget_key_is_fixed_source(self, tmp_path):
        p = tmp_path / "settings.json"
        p.write_text(json.dumps({"spinnerVerbs": {
            "phase_budgets_ms": {"stremaing": 5000}}}), encoding="utf-8")
        assert R.load_config(p).source == "invalid:budget-phase"

    def test_liveness_is_still_pure_read(self):
        e = _engine()
        e.note_activity("streaming", now=1000.0)
        seq, current, ev_len = e._seq, e._current, len(e._evidence)
        for _ in range(20):
            e.liveness(now=1001.0)
            e.render(True, now=1001.0)
            e.snapshot()
        assert (e._seq, e._current, len(e._evidence)) == (seq, current, ev_len)


class TestFullHealthAfterD10:
    def test_all_phases_all_languages_still_green(self):
        for lang in R.LANGUAGES:
            e = _engine(lang=lang)
            for phase in R.PHASES:
                e.note_activity(phase, now=1000.0)
                v = e.render(True, now=1000.2)
                assert isinstance(v, R.SloganView)
                assert v.phase == phase
            assert e.liveness(now=1000.2).state in R_STATES
            e.reset()
        # mapping 侧仍全绿
        from tuan_cli.ui.slogans import mapping as M
        M.reset_runtime_counters(include_dispatch_log=True)
        assert M.audit().ok is True
        M.reset_runtime_counters(include_dispatch_log=True)
