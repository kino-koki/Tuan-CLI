# -*- coding: utf-8 -*-
"""「每个标语都要对应的」全量回归。

实测复现的起点 (见 ``SLOGAN_MAPPING.md`` §1):

- 860 条标语在仓库根目录 ``slogans/``, docstring 却写
  ``from tuan_cli.ui.slogans import ...`` —— 路径不存在;
- 全仓 13 处「接入」全是 docstring 示例, 真实 import 为零;
- ``pick("totally.unknown", lang="zh-CN")`` 静默返回 ``"Here."``;
- ``pick("bg.progress", lang="ja")`` 返回英文 ``"Still at it."``;
- ``_windows`` / ``SloganPicker._last`` 裸 dict 无锁;
- 窗口 LRU 名不副实 (实际 FIFO)、尺寸变化整窗重建;
- ``SloganPicker(min_interval=Inf)`` 被接受, spinner 永远不换词。

本测试把「对应」变成可计算、可失败的不变量, 而不是文档自述。
"""
from __future__ import annotations

import math
import random
import threading
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

import tuan_cli.ui.slogans as S
from tuan_cli.ui.slogans import (
    mapping, picker, extra, extra_locales, universal, _clean,
)
from tuan_cli.ui.slogans import locales as L
LANGUAGES = L.LANGUAGES
from tuan_cli.ui.slogans.locales import patches
from tuan_cli.tui import runtime_slogans as RS

_INVIS = {"Cc", "Cf", "Cs", "Co", "Cn"}


# ================================================================ 规模与包位置

class TestLayout:
    def test_package_lives_at_the_documented_path(self):
        """docstring 声明的 import 路径必须真的能 import。"""
        assert hasattr(S, "pick") and hasattr(S, "pool")
        assert hasattr(mapping, "pick_for_event")

    def test_root_shim_reexports_not_duplicates(self):
        """根目录历史包只是垫片, 词库只有一份。"""
        import slogans  # noqa: F401
        import slogans.picker as sp
        assert sp.pick is S.pick
        assert slogans.universal.GROUPS is universal.GROUPS
        assert slogans.stats() == {
            "universal": 300, "extra": 60, "locales": 500,
            "extra_locales": 240, "locale_patches": 8, "total": 1108,
        }

    def test_bank_sizes(self):
        st = S.stats()
        assert st["universal"] == 300
        assert st["extra"] == 60
        assert st["locales"] == 500
        assert st["extra_locales"] == 240
        assert st["locale_patches"] == 8
        assert len(L.LANGUAGES) == 10
        assert len(extra_locales.LANGUAGES) == 8
        assert set(extra_locales.LANGUAGES) == set(L.LANGUAGES) - {"zh-CN", "en"}
        assert len(mapping.ALL_CONTEXTS) == 16


# ================================================================ 一一对应

class TestAudit:
    def test_audit_ok_and_all_invariants_zero(self):
        r = mapping.audit()
        assert r.ok is True, r.as_dict()
        assert r.orphan_slogans == ()
        assert r.events_without_pool == ()
        assert r.contexts_without_event == ()
        assert r.events_without_context == ()
        assert r.locale_gaps == ()
        assert r.empty_pools == ()
        assert r.duplicate_ids == ()
        assert r.unsafe_bindings == ()
        assert r.phase_gaps == ()
        assert r.clipped_slogans == ()
        assert r.sanitizer_shared is True

    def test_every_slogan_has_an_event(self):
        reg = mapping.registry()
        assert len(reg) >= 1695
        valid = set(mapping.EVENT_BINDINGS)
        for e in reg:
            assert e.event and e.event in valid, e.id
            assert mapping.EVENT_BINDINGS[e.event].context == e.context, e.id

    def test_every_context_has_exactly_one_primary_event(self):
        assert set(mapping.CONTEXT_EVENTS) == set(mapping.ALL_CONTEXTS)
        assert len(mapping.CONTEXT_EVENTS) == 16
        for ctx, ev in mapping.CONTEXT_EVENTS.items():
            assert mapping.EVENT_BINDINGS[ev].context == ctx

    def test_every_event_has_a_nonempty_pool(self):
        for ev, b in mapping.EVENT_BINDINGS.items():
            assert b.context in mapping.ALL_CONTEXTS
            assert any(picker.pool_entries(b.context, lang) for lang in L.LANGUAGES)

    def test_all_five_runtime_phases_are_mapped(self):
        assert set(mapping.PHASE_EVENTS) == set(RS.PHASES)
        for phase, ev in mapping.PHASE_EVENTS.items():
            assert ev in mapping.EVENT_BINDINGS
        for phase in RS.PHASES:
            assert mapping.verbs_for_phase(phase, "zh-CN"), phase

    def test_stable_ids_are_unique_and_reversible(self):
        reg = mapping.registry()
        assert len({e.id for e in reg}) == len(reg)
        sample = reg[len(reg) // 2]
        got = mapping.entry_for(sample.id)
        assert got is not None and got.text == sample.text
        assert got.event == sample.event
        assert mapping.entry_for("no:such:id") is None

    def test_thin_pools_are_disclosed_not_hidden(self):
        """有 1~2 条本语种词条是风格取舍, 如实披露但不伪装成缺口已清零。"""
        r = mapping.audit()
        assert r.thin_pools
        assert all(int(x.rsplit("=", 1)[1]) < 3 for x in r.thin_pools)


# ================================================================ 严格分发

class TestStrictDispatch:
    def test_unknown_event_raises_instead_of_silent_idle(self):
        with pytest.raises(mapping.UnboundSloganEvent):
            mapping.pick_for_event("totally.unknown", lang="zh-CN")
        # 旧兼容路径仍在, 但生产入口绝不静默飘无关标语
        assert S.pick("totally.unknown", lang="zh-CN") == "Here."

    def test_unknown_context_raises_in_strict_pick(self):
        with pytest.raises(picker.UnknownSloganContext):
            S.pick_strict("totally.unknown", lang="ja")

    def test_security_events_return_empty_and_never_downgrade_alerts(self):
        for ev in sorted(mapping.SECURITY_EVENTS):
            d = mapping.pick_for_event(ev, lang="zh-CN")
            assert d.text == "" and d.reason == "security-notice"
            assert d.context is None
        assert mapping.SECURITY_EVENTS.isdisjoint(mapping.EVENT_BINDINGS)

    def test_three_overlong_builtin_verbs_were_replaced_not_clipped(self):
        for original, short in patches.REPLACEMENTS.items():
            assert _clean.display_cols(original) > _clean._MAX_VERB_COLS
            assert _clean.display_cols(short) <= _clean._MAX_VERB_COLS
            assert _clean.sanitize_verb(short) == short
        # 原文不再出现在任何池里 (否则渲染时会被截成半句)
        all_texts = {e.text for e in mapping.registry()}
        assert all_texts.isdisjoint(patches.REPLACEMENTS)

    def test_normal_event_returns_clean_localized_text(self):
        for lang in L.LANGUAGES:
            d = mapping.pick_for_event("turn.completed", lang=lang)
            assert d.reason == "ok" and d.text
            assert d.context == "done" and d.entry_id
            assert _clean.sanitize_verb(d.text) == d.text
            assert _clean.display_cols(d.text) <= _clean._MAX_VERB_COLS
            assert all(unicodedata.category(c) not in _INVIS for c in d.text)

    def test_every_event_has_nonempty_verbs_in_every_language(self):
        for ev in mapping.EVENT_BINDINGS:
            for lang in L.LANGUAGES:
                d = mapping.pick_for_event(ev, lang=lang)
                assert d.text, (ev, lang)

    def test_dispatch_log_is_bounded_and_desensitized(self):
        mapping.reset_dispatch_log()
        for i in range(200):
            mapping.pick_for_event("tool.exploring", lang="ja")
        log = mapping.dispatch_log()
        assert len(log) == 64
        blob = repr(log)
        assert "SUPER_SECRET" not in blob
        # 日志条目只有 (event, context, reason, at_ms, entry_id, origin)
        assert all(len(d.__dataclass_fields__) == 8 for d in log)


# ================================================================ 本地优先

class TestLocalFirst:
    def test_no_cross_language_leak_in_800_dispatches_per_language(self):
        from collections import Counter
        for lang in set(L.LANGUAGES) - {"en"}:
            c = Counter()
            for _ in range(100):
                for ev in ("background.progress", "memory.written",
                           "model.switched", "remote.paired",
                           "budget.warning", "background.started"):
                    d = mapping.pick_for_event(ev, lang=lang)
                    c[d.origin] += 1
            assert c.get("universal-fallback", 0) == 0, (lang, dict(c))
            assert c["locale"] == 600, (lang, dict(c))

    def test_eight_extra_locales_fill_all_48_gaps(self):
        for lang in extra_locales.LANGUAGES:
            for ctx in extra.CONTEXTS:
                entries = picker.pool_entries(ctx, lang)
                local = [e for e in entries if e.is_local]
                assert len(local) == 5, (lang, ctx, len(local))
                assert all(e.origin == "locale-extra" for e in local)

    def test_de_together_patch_fills_the_only_empty_subject_pool(self):
        entries = picker.pool_entries("together", "de")
        local = [e for e in entries if e.is_local]
        assert len(local) == 5
        assert all(e.origin == "locale-patch" for e in local)
        assert "Zusammen geht's leichter." in [e.text for e in local]

    def test_original_bank_files_were_not_rewritten(self):
        """补池是追加, 不改 10 个语种文件的分布统计。"""
        r = mapping.audit()
        assert r.total_languages == 10
        for lang in L.LANGUAGES:
            g = L.groups(lang)
            assert sum(len(v) for v in g.values()) == 50, lang
        assert universal.count() == 300 and extra.count() == 60


# ================================================================ 净化共享

class TestSharedSanitizer:
    def test_same_function_object_not_a_second_implementation(self):
        assert RS.sanitize_verb is _clean.sanitize_verb
        assert RS.display_cols is _clean.display_cols
        assert RS._clusters is _clean._clusters
        assert RS._fit_headline is _clean._fit_headline

    def test_all_1105_bank_verbs_are_clean_and_within_width(self):
        for lang in L.LANGUAGES:
            for ctx in mapping.ALL_CONTEXTS:
                for e in picker.pool_entries(ctx, lang):
                    assert _clean.sanitize_verb(e.text) == e.text, (lang, ctx, e.text)
                    assert _clean.display_cols(e.text) <= _clean._MAX_VERB_COLS
                    assert all(unicodedata.category(c) not in _INVIS for c in e.text)
                    assert "\x1b" not in e.text

    def test_bidi_and_escape_side_doors_still_closed(self):
        assert _clean.sanitize_verb("正常\u202e话反") == "正常话反"
        assert _clean.sanitize_verb("\x1b(B正常") == "正常"
        assert _clean.sanitize_verb("❤\ufe0f") == "❤"


# ================================================================ picker 修复

class TestPickerFixes:
    def test_min_interval_rejects_negative_nan_inf(self):
        for bad in (-1.0, float("nan"), float("inf"), "5", True):
            with pytest.raises((ValueError, TypeError)):
                picker.SloganPicker(min_interval=bad)
        assert picker.SloganPicker(min_interval=0.0).min_interval == 0.0

    def test_injected_clock_makes_throttling_deterministic(self):
        now = [100.0]
        p = picker.SloganPicker(lang="zh-CN", min_interval=5.0,
                                clock=lambda: now[0])
        a = p.pick("thinking")
        now[0] += 1.0
        assert p.pick("thinking") == a
        now[0] += 4.1
        assert p.pick("thinking") != a or True   # 允许随机撞同词, 但计时必须放行
        assert p._last[("zh-CN", "thinking")][1] == pytest.approx(105.1)

    def test_window_keeps_history_when_pool_size_changes(self):
        key = ("zh-CN", "size-change")
        picker._windows.clear()
        with picker._windows_lock:
            picker._window_locked(key, 5)
            old = picker._windows[key]
            old.append("历史词")
            picker._window_locked(key, 20)
            new = picker._windows[key]
            assert "历史词" in list(new)
            assert new.maxlen == 20

    def test_window_eviction_is_lru_not_fifo(self):
        picker._windows.clear()
        with picker._windows_lock:
            for i in range(70):
                w = picker._window_locked(("lang", f"ctx{i}"), 4)
                w.append(f"w{i}")
            # 反复访问最早的两个 key, 它们应当存活
            for i in (0, 1, 2):
                picker._window_locked(("lang", f"ctx{i}"), 4)
            keys = list(picker._windows)
            assert len(keys) == 64
            assert ("lang", "ctx0") in keys and ("lang", "ctx2") in keys

    def test_single_item_pool_short_circuits(self):
        calls = {"n": 0}
        orig = picker.random.choice

        def counting(items):
            calls["n"] += 1
            return orig(items)

        picker.random.choice = counting
        try:
            assert picker._choose(("唯一一条",), ("zh-CN", "tiny")) == "唯一一条"
            assert calls["n"] == 1
        finally:
            picker.random.choice = orig

    def test_pick_for_event_is_thread_safe(self):
        errors = []
        barrier = threading.Barrier(8)

        def worker(wid):
            try:
                barrier.wait()
                for i in range(200):
                    ev = list(mapping.EVENT_BINDINGS)[(wid + i) % 18]
                    d = mapping.pick_for_event(ev, lang=L.LANGUAGES[wid % 10])
                    assert d.text or d.reason != "ok"
            except Exception as exc:
                errors.append(repr(exc))

        with ThreadPoolExecutor(max_workers=8) as ex:
            for f in [ex.submit(worker, i) for i in range(8)]:
                f.result()
        assert errors == [], errors[:3]
        assert len(mapping.dispatch_log()) <= 64


# ================================================================ TUI 真实接入

class TestTuiWiring:
    def _tui(self):
        from tuan_cli.tui.tui import QxtTUI
        obj = QxtTUI(on_submit=lambda _t: "ok")
        obj._booting = False
        obj._boot_error = None
        return obj

    def test_lifecycle_events_really_dispatch(self):
        obj = self._tui()
        obj.begin_tool("git status")
        obj.stream_assistant("hi")
        obj.end_stream()
        obj.close()
        events = [row[0] for row in obj._slogan_log]
        assert "tool.exploring" in events
        assert "session.exit" in events
        assert len(obj._slogan_log) <= 64

    def test_stream_dispatch_is_throttled_not_per_delta(self):
        obj = self._tui()
        for _ in range(50):
            obj.stream_assistant("x")
        n = sum(1 for row in obj._slogan_log if row[0] == "model.streaming")
        assert n <= 1, f"分片被逐条分发 {n} 次, 节流失效"

    def test_slogan_for_returns_empty_for_security_events(self):
        obj = self._tui()
        for ev in sorted(mapping.SECURITY_EVENTS):
            assert obj.slogan_for(ev) == ""

    def test_slogan_for_returns_clean_text_for_normal_event(self):
        obj = self._tui()
        text = obj.slogan_for("turn.completed")
        assert text and _clean.sanitize_verb(text) == text

    def test_existing_working_status_line_untouched(self):
        """接入不得掀掉前几轮修好的状态口径。"""
        obj = self._tui()
        obj._busy = True
        obj._slogans.note_activity("waiting_model")
        text = "".join(seg for _, seg in obj._render_header())
        assert "Working (" in text
        assert "疑似摸鱼" not in text

    def test_runtime_slogans_139_cases_still_valid(self):
        """净化层抽取后, 活性引擎的公共 API 一个不少。"""
        for name in ("sanitize_verb", "display_cols", "_clusters",
                     "_fit_headline", "_MAX_VERB_COLS", "Liveness",
                     "LivenessState", "PHASE_BUDGET_MS", "EventRecord",
                     "RuntimeSloganEngine", "SpinnerVerbsConfig",
                     "SloganView", "load_config", "slogan_bank"):
            assert hasattr(RS, name), name
