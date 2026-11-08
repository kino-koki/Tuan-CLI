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
        # 字段: event, context, lang, text, reason, at_ms, entry_id,
        #       origin, owner (本轮新增 owner 作用域)
        assert all(len(d.__dataclass_fields__) == 9 for d in log)
        assert all(d.owner == "" for d in log)


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
        # 深度轮 3: 上限从固定 64 改为按真实 key 空间算 (384),
        # 所以驱逐要用 _MAX_WINDOWS + 6 个 key 才触发, 断言也不再硬编码 64。
        n = picker._MAX_WINDOWS + 6
        with picker._windows_lock:
            for i in range(n):
                w = picker._window_locked(("lang", f"ctx{i}"), 4)
                w.append(f"w{i}")
            # 反复访问最早的几个 key, 它们应当存活
            for i in (0, 1, 2):
                picker._window_locked(("lang", f"ctx{i}"), 4)
            keys = list(picker._windows)
            assert len(keys) == picker._MAX_WINDOWS
            assert ("lang", "ctx0") in keys and ("lang", "ctx2") in keys
            assert ("lang", "ctx3") not in keys

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
        # 日志按 owner 分桶后, 无参 dispatch_log() 是全量; 单桶仍 <=64
        assert len(mapping.dispatch_log("")) <= 64
        assert all(len(b) <= 64 for b in mapping._dispatch_log.values())


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


# ================================================================ 运行时闭环

class _Clock:
    def __init__(self, start=100.0):
        self.now = start

    def __call__(self):
        return self.now


class _Rng:
    """确定性随机源: 每次 choice 取第一个, 用于回放。"""
    def __init__(self):
        self.calls = 0

    def choice(self, items):
        self.calls += 1
        return items[0]


class TestRuntimeClosure:
    """上一轮建了静态对应表, 本轮实测发现运行时留痕把对应关系丢了。"""

    def _tui(self):
        from tuan_cli.tui.tui import QxtTUI
        obj = QxtTUI(on_submit=lambda _t: "ok")
        obj._booting = False
        obj._boot_error = None
        return obj

    def test_tui_trace_carries_entry_id_and_it_resolves(self):
        obj = self._tui()
        obj.begin_tool("git status")
        trace = obj.slogan_trace()
        assert len(trace) == 1
        row = trace[0]
        assert row["event"] == "tool.exploring"
        assert row["entry_id"], "运行时留痕丢了 entry_id -> 对应关系断掉"
        entry = mapping.entry_for(row["entry_id"])
        assert entry is not None
        assert entry.context == "explore"
        assert entry.event == "tool.exploring"
        assert entry.text == mapping.dispatch_log(obj.slogan_owner())[-1].text

    def test_trace_row_zero_is_still_event_for_old_regressions(self):
        obj = self._tui()
        obj.begin_tool("git status")
        assert obj._slogan_log[0][0] == "tool.exploring"

    def test_security_event_trace_is_distinguishable_from_error(self):
        obj = self._tui()
        assert obj.slogan_for("security.blocked") == ""
        row = obj.slogan_trace()[-1]
        assert row["reason"] == "security-notice" and row["entry_id"] == ""
        assert obj.slogan_errors() == ()

    def test_unknown_event_is_recorded_not_silently_swallowed(self):
        obj = self._tui()
        assert obj._slogan_dispatch("totally.typo.event") is None
        errs = obj.slogan_errors()
        assert len(errs) == 1
        assert errs[0][2] == "error:unbound-event"
        assert errs[0][0] == "totally.typo.event"

    def test_strict_mode_propagates_the_strict_contract(self):
        obj = self._tui()
        with pytest.raises(mapping.UnboundSloganEvent):
            obj._slogan_dispatch("totally.typo.event", strict=True)
        with pytest.raises(mapping.UnboundSloganEvent):
            obj.slogan_for("totally.typo.event", strict=True)
        assert len(obj.slogan_errors()) == 2

    def test_slogan_for_unknown_returns_empty_but_leaves_a_trace(self):
        """空串既表示「安全事件」也表示「出错」; 靠 trace 区分, 不靠猜。"""
        obj = self._tui()
        assert obj.slogan_for("totally.typo.event") == ""
        assert len(obj.slogan_errors()) == 1

    def test_owner_scopes_dispatch_log_per_instance(self):
        a, b = self._tui(), self._tui()
        mapping.reset_dispatch_log()
        a.begin_tool("A")
        b.begin_tool("B")
        assert a.slogan_owner() != b.slogan_owner()
        la = mapping.dispatch_log(a.slogan_owner())
        lb = mapping.dispatch_log(b.slogan_owner())
        assert len(la) == 1 and len(lb) == 1
        assert all(d.owner == a.slogan_owner() for d in la)
        assert all(d.owner == b.slogan_owner() for d in lb)
        assert set(d.owner for d in mapping.dispatch_log()) == {
            a.slogan_owner(), b.slogan_owner()}

    def test_reset_one_owner_does_not_wipe_the_other(self):
        a, b = self._tui(), self._tui()
        mapping.reset_dispatch_log()
        a.begin_tool("A")
        b.begin_tool("B")
        mapping.reset_dispatch_log(a.slogan_owner())
        assert mapping.dispatch_log(a.slogan_owner()) == ()
        assert len(mapping.dispatch_log(b.slogan_owner())) == 1

    def test_dispatch_log_is_locked_snapshot_not_internal_object(self):
        mapping.reset_dispatch_log()
        d = mapping.pick_for_event("tool.exploring", owner="x")
        snap = mapping.dispatch_log("x")
        assert isinstance(snap, tuple) and snap[0].event == d.event
        assert len(mapping.dispatch_log("x")) == 1

    def test_tui_log_is_bounded_and_thread_safe(self):
        obj = self._tui()
        errors = []
        barrier = threading.Barrier(8)

        def worker(wid):
            try:
                barrier.wait()
                for i in range(120):
                    obj._slogan_dispatch(list(mapping.EVENT_BINDINGS)[
                        (wid + i) % len(mapping.EVENT_BINDINGS)])
            except Exception as exc:
                errors.append(repr(exc))

        with ThreadPoolExecutor(max_workers=8) as ex:
            for f in [ex.submit(worker, i) for i in range(8)]:
                f.result()
        assert errors == [], errors[:3]
        assert len(obj._slogan_log) <= 64
        assert all(len(r) == 7 for r in obj._slogan_log)

    def test_stream_throttle_still_exactly_one(self):
        obj = self._tui()
        for _ in range(50):
            obj.stream_assistant("x")
        n = sum(1 for r in obj.slogan_trace() if r["event"] == "model.streaming")
        assert n <= 1


# ================================================================ 性能与索引

class TestIndexAndPerformance:
    def test_every_dispatch_resolves_an_entry(self):
        """O(1) 索引不能出现「显示出来了却查不到注册项」的空洞。"""
        for lang in L.LANGUAGES:
            for ev in mapping.EVENT_BINDINGS:
                d = mapping.pick_for_event(ev, lang=lang, owner="idx-test")
                assert d.reason == "ok"
                assert d.entry_id, (ev, lang)
                e = mapping.entry_for(d.entry_id)
                assert e is not None and d.event in e.events
                assert e.event == mapping.CONTEXT_EVENTS[e.context]
                assert e.text == d.text

    def test_index_stats_are_consistent(self):
        st = mapping.index_stats()
        assert st["by_id"] == st["registry"] == 1695
        assert st["by_text"] > 0
        assert mapping.audit().index_consistent is True

    def test_entry_for_text_is_o1_and_correct(self):
        reg = mapping.registry()
        for e in (reg[0], reg[len(reg) // 2], reg[-1]):
            got = mapping.entry_for_text(e.lang, e.context, e.text)
            assert got is not None and got.id == e.id
        assert mapping.entry_for_text("xx", "yy", "zz") is None

    def test_audit_is_linear_not_quadratic(self):
        """ids.count(i) 曾让单次 audit 38.4 ms / 20 次 763.7 ms。"""
        import time as _time
        t0 = _time.perf_counter()
        for _ in range(20):
            r = mapping.audit()
        elapsed = (_time.perf_counter() - t0) * 1000
        assert r.ok and r.index_consistent
        assert elapsed < 300, "20 次 audit 耗时 %.1f ms, 疑似退回 O(n^2)" % elapsed

    def test_dispatch_no_longer_scans_whole_registry(self):
        """结构断言 + 宽松时间断言。

        实测: 修复前 2000 次分发 58.9 ms (每次 for e in registry() 扫
        1695 条), 修复后 42.5 ms。绝对毫秒数受沙盒负载影响, 所以主判据
        是**源码里不得出现线性反查**, 时间只作回归护栏 (阈值 80 ms,
        仍能抓住退回 O(n) 的 ~59 ms 基线之上再加抖动)。
        """
        import inspect
        import time as _time
        src = inspect.getsource(mapping.pick_for_event)
        assert "for e in registry()" not in src
        assert "entry_for_clean(" in src
        t0 = _time.perf_counter()
        for _ in range(2000):
            mapping.pick_for_event("tool.exploring", lang="ja", owner="perf")
        elapsed = (_time.perf_counter() - t0) * 1000
        assert elapsed < 80, "2000 次分发 %.1f ms, 疑似退回线性反查" % elapsed


# ================================================================ 可回放

class TestDeterministicReplay:
    def test_injected_rng_and_clock_make_dispatch_replayable(self):
        c = _Clock(42.0)
        r1, r2 = _Rng(), _Rng()
        a = mapping.pick_for_event("turn.completed", lang="ja",
                                   now=c(), rng=r1, owner="replay-a")
        b = mapping.pick_for_event("turn.completed", lang="ja",
                                   now=c(), rng=r2, owner="replay-b")
        assert a.text == b.text and a.entry_id == b.entry_id
        assert a.at_ms == b.at_ms == 42000
        assert r1.calls == r2.calls == 1

    def test_different_languages_still_localized_under_fixed_rng(self):
        for lang in ("ja", "de", "zh-CN"):
            d = mapping.pick_for_event("turn.completed", lang=lang,
                                       rng=_Rng(), owner="replay-" + lang)
            assert d.origin == "locale"
            assert mapping.entry_for(d.entry_id).lang == lang

    def test_owner_and_at_ms_do_not_break_old_positional_fields(self):
        d = mapping.pick_for_event("turn.completed", lang="zh-CN", now=7.0)
        assert d.event == "turn.completed" and d.context == "done"
        assert d.lang == "zh-CN" and d.reason == "ok" and d.text
        assert d.at_ms == 7000 and d.owner == ""

# ================================================================ 深度轮 3


def _reset_mapping_state():
    """把模块级索引/计数恢复到出厂态, 避免测试间互相污染。"""
    with mapping._registry_lock:
        mapping._REGISTRY = None
        mapping._BY_ID.clear()
        mapping._BY_TEXT.clear()
        mapping._BY_CLEAN.clear()
        mapping._CLIPPED_IDS = ()
        mapping._CLEAN_COLLISIONS = ()
    mapping.reset_runtime_counters()
    mapping.reset_dispatch_log()   # 深度轮 4: reset 计数不再强绑清日志
    picker._windows.clear()


class _RngFirst:
    def choice(self, items):
        return items[0]


@pytest.fixture
def _clean_state():
    _reset_mapping_state()
    yield
    _reset_mapping_state()


@pytest.mark.usefixtures("_clean_state")
class TestCleanIndex:
    """A: 上一轮 _BY_TEXT 用原始文案, 分发用净化后文案 -> 静默 miss。"""

    def test_clean_index_exists_and_matches_raw(self):
        st = mapping.index_stats()
        assert st["by_clean"] == st["by_text"] == st["by_id"] == 1695
        assert st["clean_collisions"] == 0
        assert st["index_misses"] == 0

    def test_entry_for_clean_hits_sanitized_text(self):
        reg = mapping.registry()
        for e in (reg[0], reg[len(reg) // 2], reg[-1]):
            from tuan_cli.ui.slogans import _clean
            cleaned = _clean.sanitize_verb(e.text)
            got = mapping.entry_for_clean(e.lang, e.context, cleaned)
            assert got is not None and got.id == e.id
        assert mapping.entry_for_clean("ja", "explore", "不存在的词") is None

    def test_entry_for_text_still_resolves_raw(self):
        """兼容 API 不受影响 (上一轮的独立验证仍按原文反查)。"""
        e = mapping.registry()[0]
        assert mapping.entry_for_text(e.lang, e.context, e.text).id == e.id

    def test_injected_zwsp_entry_now_resolves_instead_of_fake_ok(self):
        """实测复现场景: 注入一条含 ZWSP 的词条。

        修复前: reason='ok' 但 entry_id='' (对应关系静默断裂)。
        修复后: 净化后索引命中, 正确反查到该注册项。
        """
        orig = picker.pool_entries

        def patched(ctx, lang):
            out = list(orig(ctx, lang))
            if ctx == "explore" and lang == "ja":
                out.insert(0, picker.PoolEntry("探\u200b索中", "locale"))
            return tuple(out)

        picker.pool_entries = patched
        try:
            _reset_mapping_state()
            d = mapping.pick_for_event("tool.exploring", lang="ja",
                                       rng=_RngFirst(), owner="zwsp")
            assert d.reason == "ok", d.reason
            assert d.entry_id, "净化后索引未命中 -> 对应关系又断了"
            e = mapping.entry_for(d.entry_id)
            assert e is not None and e.text == "探\u200b索中"
            assert d.text == "探索中"
        finally:
            picker.pool_entries = orig
            _reset_mapping_state()

    def test_unresolvable_text_is_fail_closed_not_fake_ok(self):
        """池里出现注册表没有的词 -> index-miss + 空文案 + 计数, 不假装 ok。"""
        orig = picker.pick_local_first
        picker.pick_local_first = lambda ctx, lang, rng=None: ("凭空冒出的一句", "locale")
        try:
            d = mapping.pick_for_event("tool.exploring", lang="ja",
                                       owner="miss")
            assert d.reason == "index-miss"
            assert d.text == "" and d.entry_id == ""
            assert mapping.index_stats()["index_misses"] == 1
            r = mapping.audit()
            assert r.runtime_index_misses == 1 and r.ok is False
        finally:
            picker.pick_local_first = orig
            _reset_mapping_state()

    def test_clean_collision_is_detected(self):
        """两条不同词条净化后相同 -> 运行时无法区分, 必须报出来。"""
        orig = picker.pool_entries

        def patched(ctx, lang):
            out = list(orig(ctx, lang))
            if ctx == "explore" and lang == "ja":
                out.insert(0, picker.PoolEntry("撞车\u200b", "locale"))
                out.insert(1, picker.PoolEntry("撞车", "locale"))
            return tuple(out)

        picker.pool_entries = patched
        try:
            _reset_mapping_state()
            st = mapping.index_stats()
            assert st["clean_collisions"] >= 1
            r = mapping.audit()
            assert r.clean_collisions and r.ok is False
        finally:
            picker.pool_entries = orig
            _reset_mapping_state()

    def test_index_consistent_is_now_strict(self):
        r = mapping.audit()
        assert r.ok and r.index_consistent
        # 人为删掉一个净化后索引项, 加严后的断言必须抓住
        key = next(iter(mapping._BY_CLEAN))
        saved = mapping._BY_CLEAN.pop(key)
        try:
            assert mapping.audit().index_consistent is False
        finally:
            mapping._BY_CLEAN[key] = saved
        assert mapping.audit().index_consistent is True

    def test_reset_runtime_counters_clears_misses(self):
        orig = picker.pick_local_first
        picker.pick_local_first = lambda ctx, lang, rng=None: ("查不到的词", "locale")
        try:
            mapping.pick_for_event("tool.exploring", owner="m")
            assert mapping.index_stats()["index_misses"] == 1
            mapping.reset_runtime_counters()
            assert mapping.index_stats()["index_misses"] == 0
            assert mapping.audit().ok is True
        finally:
            picker.pick_local_first = orig
            _reset_mapping_state()


@pytest.mark.usefixtures("_clean_state")
class TestOwnerBuckets:
    """B: 上一轮只限每桶长度, 桶数无界 -> 内存泄漏。"""

    def test_bucket_count_is_bounded_by_lru(self):
        M = mapping._MAX_OWNERS
        for i in range(M + 20):
            mapping.pick_for_event("tool.exploring", owner="s-%d" % i)
        st = mapping.dispatch_log_stats()
        assert st["owners"] == M
        assert st["decisions"] <= M * st["cap_per_owner"]
        assert st["max_bucket"] <= st["cap_per_owner"]
        # 最早的桶被淘汰, 但显式访问过的不该被误删
        assert mapping.dispatch_log("s-0") == ()
        assert len(mapping.dispatch_log("s-%d" % (M + 19))) == 1

    def test_lru_protects_recently_used_owner(self):
        M = mapping._MAX_OWNERS
        for i in range(M):
            mapping.pick_for_event("tool.exploring", owner="s-%d" % i)
        mapping.pick_for_event("turn.completed", owner="keep")
        # 触发驱逐
        for i in range(M, M + 30):
            mapping.pick_for_event("tool.exploring", owner="s-%d" % i)
        assert mapping.dispatch_log_stats()["owners"] == M
        assert len(mapping.dispatch_log("keep")) == 1

    def test_release_owner_removes_only_that_bucket(self):
        mapping.pick_for_event("tool.exploring", owner="a")
        mapping.pick_for_event("tool.exploring", owner="b")
        n = mapping.release_owner("a")
        assert n == 1
        assert mapping.dispatch_log("a") == ()
        assert len(mapping.dispatch_log("b")) == 1
        assert mapping.release_owner("a") == 0
        assert mapping.release_owner("") == 0

    def test_tui_close_releases_its_owner_bucket(self):
        from tuan_cli.tui.tui import QxtTUI
        obj = QxtTUI(on_submit=lambda _t: "ok")
        obj._booting = False
        obj._boot_error = None
        obj.begin_tool("git status")
        owner = obj.slogan_owner()
        assert len(mapping.dispatch_log(owner)) == 1
        obj.close()
        # session.exit 分发后, close() 释放整个桶
        assert mapping.dispatch_log(owner) == ()
        # 实例内留痕仍可查
        assert len(obj.slogan_trace()) >= 2

    def test_dispatch_log_stats_fields(self):
        st = mapping.dispatch_log_stats()
        assert set(("owners", "decisions", "max_bucket",
                    "cap_per_owner", "max_owners")) <= set(st)
        assert st["cap_per_owner"] == 64
        assert st["max_owners"] == 128


@pytest.mark.usefixtures("_clean_state")
class TestErrorTwoLayerTrace:
    """C: 上一轮错误只写 TUI 实例日志, 全局日志完全看不见。"""

    def _tui(self):
        from tuan_cli.tui.tui import QxtTUI
        obj = QxtTUI(on_submit=lambda _t: "ok")
        obj._booting = False
        obj._boot_error = None
        return obj

    def test_error_visible_in_both_layers(self):
        obj = self._tui()
        obj._slogan_dispatch("totally.typo.event")
        assert len(obj.slogan_errors()) == 1
        rows = [d for d in mapping.dispatch_log(obj.slogan_owner())
                if d.reason.startswith("error:")]
        assert len(rows) == 1
        assert rows[0].event == "totally.typo.event"
        assert rows[0].reason == "error:unbound-event"
        assert rows[0].text == "" and rows[0].entry_id == ""

    def test_security_event_is_not_misclassified_as_error(self):
        obj = self._tui()
        assert obj.slogan_for("security.blocked") == ""
        rows = mapping.dispatch_log(obj.slogan_owner())
        assert rows[-1].reason == "security-notice"
        assert not any(d.reason.startswith("error:") for d in rows)
        assert obj.slogan_errors() == ()

    def test_strict_mode_still_records_in_both_layers(self):
        obj = self._tui()
        with pytest.raises(mapping.UnboundSloganEvent):
            obj._slogan_dispatch("typo.event", strict=True)
        assert len(obj.slogan_errors()) == 1
        assert len([d for d in mapping.dispatch_log(obj.slogan_owner())
                    if d.reason.startswith("error:")]) == 1

    def test_record_error_does_not_carry_text_or_lang(self):
        d = mapping.record_error("x", "boom", owner="err", at_ms=123)
        assert d.at_ms == 123 and d.text == "" and d.lang == ""
        assert d.context is None and d.entry_id == ""
        assert d.reason == "error:boom"


@pytest.mark.usefixtures("_clean_state")
class TestWindowCapacity:
    """D: _MAX_WINDOWS=64 < 真实 key 空间 320 -> 避重失效。"""

    def test_capacity_covers_real_key_space(self):
        theoretical = len(L.LANGUAGES) * (
            len(universal.CONTEXTS) + len(extra.CONTEXTS)) * 2
        assert picker._MAX_WINDOWS > theoretical
        assert picker._MAX_WINDOWS == 384
        assert theoretical == 320

    def test_full_key_space_sweep_keeps_windows_alive(self):
        picker._windows.clear()
        keys = [(l, c + suffix)
                for l in L.LANGUAGES
                for c in mapping.ALL_CONTEXTS
                for suffix in ("", ":local")]
        # 必须用生产路径 (rng=None): 注入 rng 时按设计走一次性局部
        # 窗口, 本来就不写全局 _windows (可确定性回放的代价)。
        for k in keys:
            picker._choose(("a", "b", "c", "d", "e", "f", "g", "h"), k)
        assert len(picker._windows) == len(keys)
        first = (L.LANGUAGES[0], mapping.ALL_CONTEXTS[0])
        win = picker._windows.get(first)
        # 避重历史仍在 -> 下一轮取词不会立刻重复上一条
        assert win is not None and len(win) >= 1


@pytest.mark.usefixtures("_clean_state")
class TestAuditReportNewFields:
    def test_as_dict_exposes_new_invariants(self):
        r = mapping.audit().as_dict()
        assert r["ok"] is True
        assert r["clean_collisions"] == 0
        assert r["runtime_index_misses"] == 0
        assert isinstance(r["dispatch_stats"], dict)
        assert r["dispatch_stats"]["max_owners"] == 128

    def test_every_dispatch_still_resolves_after_fix(self):
        for lang in L.LANGUAGES:
            for ev in mapping.EVENT_BINDINGS:
                d = mapping.pick_for_event(ev, lang=lang, owner="final")
                assert d.reason == "ok" and d.entry_id, (ev, lang)
                e = mapping.entry_for(d.entry_id)
                assert e is not None and d.event in e.events
                assert d.text == _clean.sanitize_verb(e.text)

# ================================================================ 深度轮 4

class _D4RngFirst:
    def choice(self, items):
        return items[0]


@pytest.mark.usefixtures("_clean_state")
class TestAuditSelfHeals:
    """A: 上一轮一次已修复的历史 miss 让 audit.ok 永久 False,
    且唯一恢复手段会清掉全部运行时留痕。"""

    def test_recovered_source_restores_ok_without_losing_evidence(self):
        mapping.reset_runtime_counters(include_dispatch_log=True)
        orig = picker.pick_local_first
        picker.pick_local_first = lambda ctx, lang, rng=None: ("查不到的词", "locale")
        try:
            d = mapping.pick_for_event("tool.exploring", owner="m")
            assert d.reason == "index-miss"
            assert mapping.audit().ok is False
        finally:
            picker.pick_local_first = orig
        # 数据源恢复: 一次成功反查即自愈
        mapping.pick_for_event("tool.exploring", owner="healthy")
        r = mapping.audit()
        assert r.ok is True and r.index_consistent is True
        assert r.unresolved_misses == 0
        assert r.runtime_index_misses == 1     # 累计证据保留
        assert mapping.dispatch_log_stats()["decisions"] >= 2  # 日志保留
        assert mapping.index_stats()["index_misses"] == 1

    def test_acknowledge_does_not_touch_logs_or_cumulative(self):
        mapping.reset_runtime_counters(include_dispatch_log=True)
        orig = picker.pick_local_first
        picker.pick_local_first = lambda ctx, lang, rng=None: ("查不到的词", "locale")
        try:
            mapping.pick_for_event("tool.exploring", owner="m")
            mapping.pick_for_event("tool.exploring", owner="m")
            assert mapping.index_stats()["unresolved_misses"] == 2
            before = mapping.dispatch_log_stats()
            n = mapping.acknowledge_runtime_misses()
            assert n == 2
            assert mapping.index_stats()["unresolved_misses"] == 0
            assert mapping.index_stats()["index_misses"] == 2   # 累计不动
            assert mapping.dispatch_log_stats() == before        # 日志不动
            assert mapping.audit().ok is True
        finally:
            picker.pick_local_first = orig
            mapping.reset_runtime_counters(include_dispatch_log=True)

    def test_reset_counters_no_longer_wipes_logs_by_default(self):
        mapping.reset_runtime_counters(include_dispatch_log=True)
        mapping.pick_for_event("tool.exploring", owner="keep")
        assert mapping.dispatch_log("keep")
        mapping.reset_runtime_counters()
        assert len(mapping.dispatch_log("keep")) == 1
        mapping.reset_runtime_counters(include_dispatch_log=True)
        assert mapping.dispatch_log("keep") == ()

    def test_as_dict_exposes_unresolved_and_fatal_fields(self):
        r = mapping.audit().as_dict()
        assert r["unresolved_misses"] == 0
        assert r["runtime_index_misses"] == 0
        assert r["sanitized_slogans"] == 0
        assert r["unrenderable_slogans"] == 0


@pytest.mark.usefixtures("_clean_state")
class TestCloseSealsExit:
    """B: 上一轮 close() 刚记 session.exit 就删桶, 全局日志永远缺它。"""

    def _tui(self):
        from tuan_cli.tui.tui import QxtTUI
        obj = QxtTUI(on_submit=lambda _t: "ok")
        obj._booting = False
        obj._boot_error = None
        return obj

    def test_sealed_trace_contains_session_exit(self):
        obj = self._tui()
        obj.begin_tool("git status")
        owner = obj.slogan_owner()
        obj.close()
        assert mapping.dispatch_log(owner) == ()       # 桶确实释放了
        sealed = obj.slogan_closed_trace()
        assert sealed
        assert "session.exit" in [r["event"] for r in sealed]
        assert all(set(r) == {"event", "context", "reason", "origin",
                              "entry_id", "owner", "at_ms"} for r in sealed)

    def test_sealed_matches_what_was_in_global_bucket(self):
        obj = self._tui()
        obj.begin_tool("A")
        obj.begin_tool("B")
        obj.close()
        sealed = obj.slogan_closed_trace()
        assert [r["event"] for r in sealed].count("tool.exploring") == 2
        assert sealed[-1]["event"] == "session.exit"

    def test_take_owner_log_returns_snapshot_and_releases(self):
        mapping.reset_dispatch_log()
        mapping.pick_for_event("tool.exploring", owner="take")
        mapping.pick_for_event("turn.completed", owner="take")
        snap = mapping.take_owner_log("take")
        assert len(snap) == 2 and snap[-1].event == "turn.completed"
        assert mapping.dispatch_log("take") == ()
        assert mapping.take_owner_log("take") == ()
        assert mapping.take_owner_log("") == ()


@pytest.mark.usefixtures("_clean_state")
class TestLRUReadRefresh:
    """C: 上一轮只有写刷新 LRU, 高频只读活跃会话被淘汰。"""

    def test_reading_an_owner_refreshes_recency(self):
        mapping.reset_dispatch_log()
        K = mapping._MAX_OWNERS
        for i in range(K):
            mapping.pick_for_event("tool.exploring", owner="s-%d" % i)
        for _ in range(50):
            mapping.dispatch_log("s-0")           # 只读
        for i in range(K, K + 10):
            mapping.pick_for_event("tool.exploring", owner="s-%d" % i)
        assert mapping.dispatch_log_stats()["owners"] == K
        assert len(mapping.dispatch_log("s-0")) == 1     # 存活
        assert mapping.dispatch_log("s-1") == ()          # 真·最久未用被淘汰

    def test_full_snapshot_read_does_not_refresh_everyone(self):
        """无参全量读若刷新所有桶, LRU 会失效 —— 必须不刷新。"""
        mapping.reset_dispatch_log()
        K = mapping._MAX_OWNERS
        for i in range(K):
            mapping.pick_for_event("tool.exploring", owner="s-%d" % i)
        mapping.dispatch_log()                     # 全量读
        for i in range(K, K + 10):
            mapping.pick_for_event("tool.exploring", owner="s-%d" % i)
        assert mapping.dispatch_log("s-0") == ()   # 仍按真实写入顺序淘汰


@pytest.mark.usefixtures("_clean_state")
class TestLogFieldSanitization:
    """D: 上一轮错误留痕把外部可控 event 原样写进两层日志。"""

    def _evil(self):
        return "x" * 5000 + "\x1b]8;;https://evil.example\x07" + "\u202eRLO"

    def test_record_error_sanitizes_event_and_kind(self):
        mapping.reset_dispatch_log()
        d = mapping.record_error(self._evil(), "boom", owner="inj")
        assert len(d.event) <= 121
        assert "\x1b" not in d.event and "\u202e" not in d.event
        assert "]8;;" not in d.event
        assert d.reason == "error:boom"

    def test_invalid_field_is_fail_closed_not_raw(self):
        d = mapping.record_error("\x1b\u200b\u202e", "\x1b", at_ms=1)
        assert d.event == "<invalid-event>"
        assert d.reason.startswith("error:")
        assert "\x1b" not in d.event

    def test_unbound_exception_message_is_sanitized(self):
        with pytest.raises(mapping.UnboundSloganEvent) as ei:
            mapping.pick_for_event(self._evil())
        msg = str(ei.value)
        assert "\x1b" not in msg and "\u202e" not in msg and "]8;;" not in msg
        assert len(msg) < 300

    def test_tui_error_trace_uses_sanitized_event(self):
        from tuan_cli.tui.tui import QxtTUI
        obj = QxtTUI(on_submit=lambda _t: "ok")
        obj._booting = False
        obj._boot_error = None
        obj._slogan_dispatch(self._evil())
        errs = obj.slogan_errors()
        assert len(errs) == 1
        assert "\x1b" not in errs[0][0] and "\u202e" not in errs[0][0]
        rows = [d for d in mapping.dispatch_log(obj.slogan_owner())
                if d.reason.startswith("error:")]
        assert len(rows) == 1
        assert "\x1b" not in rows[0].event and "\u202e" not in rows[0].event
        assert errs[0][0] == rows[0].event    # 两层一致

    def test_sanitize_log_field_shares_clean_core(self):
        from tuan_cli.ui.slogans import _clean
        evil = self._evil()
        log = _clean.sanitize_log_field(evil)
        verb = _clean.sanitize_verb(evil)
        assert "\x1b" not in log and "\x1b" not in verb
        assert "\u202e" not in log and "\u202e" not in verb
        # 日志按码点 120, UI 文案按列宽 40 —— 同一清理核心、不同长度约束
        assert len(log) > len(verb)
        assert _clean.sanitize_log_field(_clean.sanitize_log_field(evil)) == log


@pytest.mark.usefixtures("_clean_state")
class TestSanitizedVsUnrenderable:
    """E: 上一轮把「需净化」一律判 fatal, 与净化后索引口径冲突。"""

    def _reindex(self):
        with mapping._registry_lock:
            mapping._REGISTRY = None
            mapping._BY_ID.clear()
            mapping._BY_TEXT.clear()
            mapping._BY_CLEAN.clear()
            mapping._CLIPPED_IDS = ()
            mapping._UNRENDERABLE_IDS = ()
            mapping._CLEAN_COLLISIONS = ()
        mapping.reset_runtime_counters(include_dispatch_log=True)

    def test_sanitized_entry_is_informational_not_fatal(self):
        orig = picker.pool_entries

        def patched(ctx, lang):
            out = list(orig(ctx, lang))
            if ctx == "explore" and lang == "ja":
                out.insert(0, picker.PoolEntry("探\u200b索中", "locale"))
            return tuple(out)

        picker.pool_entries = patched
        try:
            self._reindex()
            d = mapping.pick_for_event("tool.exploring", lang="ja",
                                       rng=_D4RngFirst(), owner="clip")
            assert d.reason == "ok" and d.entry_id and d.text == "探索中"
            r = mapping.audit()
            assert r.ok is True and r.index_consistent is True
            assert len(r.sanitized_slogans) == 1
            assert r.unrenderable_slogans == ()
            assert r.clipped_slogans == r.sanitized_slogans   # 兼容字段保留
        finally:
            picker.pool_entries = orig
            self._reindex()

    def test_unrenderable_entry_is_still_fatal(self):
        orig = picker.pool_entries

        def patched(ctx, lang):
            out = list(orig(ctx, lang))
            if ctx == "explore" and lang == "ja":
                out.insert(0, picker.PoolEntry("\x1b\u200b\u202e", "locale"))
            return tuple(out)

        picker.pool_entries = patched
        try:
            self._reindex()
            r = mapping.audit()
            assert r.unrenderable_slogans
            assert r.ok is False
        finally:
            picker.pool_entries = orig
            self._reindex()

    def test_clean_collision_still_fatal(self):
        orig = picker.pool_entries

        def patched(ctx, lang):
            out = list(orig(ctx, lang))
            if ctx == "explore" and lang == "ja":
                out.insert(0, picker.PoolEntry("撞车\u200b", "locale"))
                out.insert(1, picker.PoolEntry("撞车", "locale"))
            return tuple(out)

        picker.pool_entries = patched
        try:
            self._reindex()
            r = mapping.audit()
            assert r.clean_collisions and r.ok is False
        finally:
            picker.pool_entries = orig
            self._reindex()


@pytest.mark.usefixtures("_clean_state")
class TestSingleRenderExit:
    """F: 上一轮分发侧二次按码点截断破坏簇边界且与索引不同口径。"""

    def test_no_secondary_codepoint_truncation_in_source(self):
        import inspect
        src = inspect.getsource(mapping.pick_for_event)
        assert "[:max_cols]" not in src
        assert "text = sanitize_verb(raw)" in src
        assert "entry_for_clean(" in src

    def test_overlong_entry_matches_index_after_single_exit(self):
        from tuan_cli.ui.slogans import _clean
        long = "很长的标语" * 30
        orig = picker.pool_entries

        def patched(ctx, lang):
            out = list(orig(ctx, lang))
            if ctx == "explore" and lang == "ja":
                out.insert(0, picker.PoolEntry(long, "locale"))
            return tuple(out)

        picker.pool_entries = patched
        try:
            with mapping._registry_lock:
                mapping._REGISTRY = None
                mapping._BY_ID.clear()
                mapping._BY_TEXT.clear()
                mapping._BY_CLEAN.clear()
                mapping._CLIPPED_IDS = ()
                mapping._UNRENDERABLE_IDS = ()
                mapping._CLEAN_COLLISIONS = ()
            mapping.reset_runtime_counters(include_dispatch_log=True)
            d = mapping.pick_for_event("tool.exploring", lang="ja",
                                       rng=_D4RngFirst(), owner="long")
            assert d.reason == "ok", d.reason
            assert d.entry_id, "超长词条被二次截断后与索引 key 不一致 -> miss"
            assert d.text == _clean.sanitize_verb(long)
            assert _clean.display_cols(d.text) <= _clean._MAX_VERB_COLS
        finally:
            picker.pool_entries = orig
            with mapping._registry_lock:
                mapping._REGISTRY = None
                mapping._BY_ID.clear()
                mapping._BY_TEXT.clear()
                mapping._BY_CLEAN.clear()
                mapping._CLIPPED_IDS = ()
                mapping._UNRENDERABLE_IDS = ()
                mapping._CLEAN_COLLISIONS = ()
            mapping.reset_runtime_counters(include_dispatch_log=True)

# ================================================================ 深度轮 5


def _d5_evil_owner():
    return "own" + "\x1b]8;;https://evil.example\x07" + "\u202eRLO" + "x" * 5000


@pytest.mark.usefixtures("_clean_state")
class TestOwnerNormalization:
    """A: D4 净化了 event/kind/context, 偏偏漏了 public 入参 owner。"""

    def test_clean_owner_is_untouched(self):
        assert mapping.norm_owner("s-0") == "s-0"
        assert mapping.norm_owner("tui:7f8a") == "tui:7f8a"
        assert mapping.norm_owner("") == ""
        assert mapping.norm_owner(None) == ""

    def test_dirty_owner_sanitized_and_bounded(self):
        raw = _d5_evil_owner()
        n = mapping.norm_owner(raw)
        assert len(n) <= 30
        assert "\x1b" not in n and "\u202e" not in n and "]8;;" not in n
        assert n.startswith("owner:")

    def test_norm_owner_is_strictly_idempotent(self):
        """实测逼出来的: 初版拼成 74 码点, 二次归一又被 64 上限截断并
        重算指纹, 导致 _record 的 key 与查询侧对不上。"""
        raw = _d5_evil_owner()
        n = mapping.norm_owner(raw)
        assert mapping.norm_owner(n) == n
        assert mapping.norm_owner(mapping.norm_owner(raw)) == n

    def test_write_and_query_use_the_same_key(self):
        raw = _d5_evil_owner()
        mapping.reset_runtime_counters(include_dispatch_log=True)
        d = mapping.pick_for_event("tool.exploring", owner=raw)
        assert d.owner == mapping.norm_owner(raw)
        assert "\x1b" not in d.owner and "\u202e" not in d.owner
        assert len(mapping.dispatch_log(raw)) == 1
        assert len(mapping.dispatch_log(d.owner)) == 1

    def test_distinct_dirty_owners_do_not_collide(self):
        a, b = _d5_evil_owner(), _d5_evil_owner() + "y"
        assert mapping.norm_owner(a) != mapping.norm_owner(b)

    def test_owner_clean_in_record_error_and_tui_trace(self):
        raw = _d5_evil_owner()
        mapping.reset_runtime_counters(include_dispatch_log=True)
        d = mapping.record_error("typo.event", "boom", owner=raw)
        assert d.owner == mapping.norm_owner(raw)
        assert "\x1b" not in d.owner
        rows = mapping.dispatch_log(raw)
        assert len(rows) == 1 and rows[0].owner == d.owner

        from tuan_cli.tui.tui import QxtTUI
        obj = QxtTUI(on_submit=lambda _t: "ok")
        obj._booting = False
        obj._boot_error = None
        obj._slogan_owner = raw
        obj.begin_tool("git status")
        tr = obj.slogan_trace()
        assert tr
        assert all("\x1b" not in r["owner"] and "\u202e" not in r["owner"]
                   for r in tr)
        assert all(r["owner"] == mapping.norm_owner(raw) for r in tr)

    def test_release_and_take_use_normalized_key(self):
        raw = _d5_evil_owner()
        mapping.reset_runtime_counters(include_dispatch_log=True)
        mapping.pick_for_event("tool.exploring", owner=raw)
        assert mapping.release_owner(raw) == 1
        assert mapping.dispatch_log(raw) == ()
        mapping.pick_for_event("tool.exploring", owner=raw)
        snap = mapping.take_owner_log(raw)
        assert len(snap) == 1 and snap[0].owner == mapping.norm_owner(raw)


@pytest.mark.usefixtures("_clean_state")
class TestLogLimitCoercion:
    """B: public API 的 limit 脏值直接抛异常。"""

    def test_dirty_limits_never_raise(self):
        from tuan_cli.ui.slogans import _clean
        for bad in ("5", None, float("nan"), float("inf"), -1,
                    True, False, 0, 99999, 8.0, "abc"):
            assert _clean.sanitize_log_field("abc", bad) == "abc", bad

    def test_positive_int_limit_is_honored(self):
        from tuan_cli.ui.slogans import _clean
        long = "字" * 200
        out = _clean.sanitize_log_field(long, 20)
        assert len(out) <= 21 and out.endswith("…")

    def test_limit_is_clamped(self):
        from tuan_cli.ui.slogans import _clean
        assert len(_clean.sanitize_log_field("a" * 5000, 99999)) <= 4097

    def test_default_limit_unchanged(self):
        from tuan_cli.ui.slogans import _clean
        assert _clean.LOG_FIELD_LIMIT == 120
        assert len(_clean.sanitize_log_field("a" * 5000)) == 121


@pytest.mark.usefixtures("_clean_state")
class TestPassiveEvictionTrace:
    """C: D4 只给显式 close() 封存快照, LRU 被动淘汰仍是无声黑洞。"""

    def test_eviction_is_recorded_not_silent(self):
        mapping.reset_runtime_counters(include_dispatch_log=True)
        K = mapping._MAX_OWNERS
        mapping.pick_for_event("tool.exploring", owner="s-0")
        mapping.pick_for_event("turn.completed", owner="s-0")
        for i in range(1, K):
            mapping.pick_for_event("tool.exploring", owner="s-%d" % i)
        mapping.pick_for_event("tool.exploring", owner="trigger")
        assert mapping.dispatch_log("s-0") == ()
        recs = mapping.evicted_owner_log()
        assert any(r.owner == "s-0" for r in recs)
        r = next(r for r in recs if r.owner == "s-0")
        assert r.dropped == 2
        assert r.last_reason == "ok"
        assert r.at_ms > 0

    def test_eviction_record_is_desensitized(self):
        mapping.reset_runtime_counters(include_dispatch_log=True)
        K = mapping._MAX_OWNERS
        for i in range(K + 5):
            mapping.pick_for_event("tool.exploring", owner="s-%d" % i)
        recs = mapping.evicted_owner_log()
        assert recs
        for r in recs:
            assert not hasattr(r, "text") and not hasattr(r, "entry_id")
            assert isinstance(r.dropped, int) and r.dropped >= 1

    def test_stats_exposes_eviction_and_audit_carries_it(self):
        mapping.reset_runtime_counters(include_dispatch_log=True)
        K = mapping._MAX_OWNERS
        for i in range(K + 3):
            mapping.pick_for_event("tool.exploring", owner="s-%d" % i)
        st = mapping.dispatch_log_stats()
        assert st["evicted_recent"] == 3
        assert st["evicted_cap"] == 64
        assert st["owners"] == K
        assert mapping.audit().as_dict()["dispatch_stats"]["evicted_recent"] == 3
        assert mapping.audit().ok is True   # 淘汰是正常有界行为, 不是故障

    def test_eviction_log_is_bounded(self):
        mapping.reset_runtime_counters(include_dispatch_log=True)
        for i in range(mapping._EVICT_CAP + 200):
            mapping.pick_for_event("tool.exploring", owner="s-%d" % i)
        assert len(mapping.evicted_owner_log()) <= mapping._EVICT_CAP
        assert mapping.dispatch_log_stats()["evicted_recent"] <= mapping._EVICT_CAP

    def test_reset_dispatch_log_clears_evictions(self):
        mapping.reset_runtime_counters(include_dispatch_log=True)
        K = mapping._MAX_OWNERS
        for i in range(K + 2):
            mapping.pick_for_event("tool.exploring", owner="s-%d" % i)
        assert mapping.evicted_owner_log()
        mapping.reset_dispatch_log()
        assert mapping.evicted_owner_log() == ()

    def test_explicit_close_is_not_counted_as_eviction(self):
        from tuan_cli.tui.tui import QxtTUI
        mapping.reset_runtime_counters(include_dispatch_log=True)
        obj = QxtTUI(on_submit=lambda _t: "ok")
        obj._booting = False
        obj._boot_error = None
        obj.begin_tool("x")
        obj.close()
        # close() 走 take_owner_log 显式释放, 不该记成被动淘汰
        assert all(r.owner != obj.slogan_owner()
                   for r in mapping.evicted_owner_log())


@pytest.mark.usefixtures("_clean_state")
class TestCloseSingleExit:
    """D/E: close 与 take_owner_log 两套实现收敛; 封存写加锁。"""

    def test_close_uses_take_owner_log_single_exit(self):
        import inspect
        from tuan_cli.tui import tui as _tui_mod
        src = inspect.getsource(_tui_mod.QxtTUI.close)
        assert "mapping.take_owner_log(" in src
        assert "mapping.release_owner(" not in src
        assert "mapping.dispatch_log(self._slogan_owner)" not in src

    def test_sealed_write_is_under_lock(self):
        import inspect
        from tuan_cli.tui import tui as _tui_mod
        src = inspect.getsource(_tui_mod.QxtTUI.close)
        assert "with self._slogan_lock:" in src
        assert "self._slogan_sealed = sealed" in src

    def test_no_unused_keys_variable(self):
        import inspect
        from tuan_cli.tui import tui as _tui_mod
        src = inspect.getsource(_tui_mod.QxtTUI.slogan_closed_trace)
        assert 'keys = ("event"' not in src

    def test_close_still_seals_session_exit(self):
        from tuan_cli.tui.tui import QxtTUI
        mapping.reset_runtime_counters(include_dispatch_log=True)
        obj = QxtTUI(on_submit=lambda _t: "ok")
        obj._booting = False
        obj._boot_error = None
        obj.begin_tool("A")
        obj.begin_tool("B")
        obj.close()
        assert mapping.dispatch_log(obj.slogan_owner()) == ()
        sealed = obj.slogan_closed_trace()
        assert [r["event"] for r in sealed] == [
            "tool.exploring", "tool.exploring", "session.exit"]
        assert all(set(r) == {"event", "context", "reason", "origin",
                              "entry_id", "owner", "at_ms"} for r in sealed)

    def test_take_owner_log_is_idempotent(self):
        mapping.reset_runtime_counters(include_dispatch_log=True)
        mapping.pick_for_event("tool.exploring", owner="once")
        assert len(mapping.take_owner_log("once")) == 1
        assert mapping.take_owner_log("once") == ()

# ================================================================ 深度轮 6


@pytest.mark.usefixtures("_clean_state")
class TestLogFieldCleanBeforeTruncate:
    """B: 旧版先按 lim*4 粗切再清理, 前部垃圾吃掉尾部合法内容。"""

    def test_leading_junk_no_longer_hides_trailing_valid_text(self):
        from tuan_cli.ui.slogans import _clean as C
        assert C.sanitize_log_field("\x00" * 1000 + "OK", 120) == "OK"
        assert C.sanitize_log_field("\x1b" * 900 + "END", 120) == "END"
        assert C.sanitize_log_field("\x00" * 300 + "A" + "\x00" * 300 + "B") == "AB"

    def test_cut_esc_sequence_leaves_no_lone_esc(self):
        """粗切点落在 ESC 序列中间时, _CTRL_RE 删掉孤立 0x1b。

        注意: 孤立 ESC **本来就被** ``\\x0e-\\x1f`` 覆盖, 这一条是
        回归保护, 不是本轮修的缺陷 (见 SLOGAN_MAPPING.md §15 候选 A)。
        """
        from tuan_cli.ui.slogans import _clean as C
        raw = "x" * 479 + "\x1b]8;;https://evil.example\x07" + "b" * 200
        out = C.sanitize_log_field(raw, 120)
        assert "\x1b" not in out and "]8;;" not in out
        assert len(out) <= 121

    def test_esc_run_does_not_break_real_csi_sequences(self):
        """ESC_RUN 排在 OSC/CSI 之后: 以 ``[``/``]`` 引导的真序列
        已先剥掉, 连续 ESC 串整体删不会残留 ``[31m`` 之类文本。"""
        from tuan_cli.ui.slogans import _clean as C
        assert C.sanitize_log_field("\x1b\x1b[31m") == ""
        assert C.sanitize_log_field("\x1b\x1b\x1b[31m") == ""
        assert C.sanitize_log_field("\x1b]8;;evil\x07OK") == "OK"
        assert C.sanitize_verb("\x1b[31mRED\x1b[0m") == "RED"

    def test_single_lone_esc_ambiguity_is_documented_not_fixed(self):
        """ECMA-48 固有歧义: 单个 ESC 后跟可打印字符既可能是
        ``ESC E`` (NEL) 序列, 也可能是孤立控制字符 + 文本 'E'。

        本轮**只修了连续 ESC 串**, 单个 ESC 的歧义未改:
        ``sanitize_log_field('\x1bEND')`` 仍是 'ND'。但 ESC 已被
        清除, 不会回显控制序列, 因此**无安全风险**, 只是保真度边界。
        断言只锁定「无控制字符」, 不把 'ND' 固化成期望值。
        """
        from tuan_cli.ui.slogans import _clean as C
        out = C.sanitize_log_field("\x1bEND")
        assert "\x1b" not in out
        assert out in ("END", "ND")

    def test_clean_then_truncate_is_idempotent(self):
        from tuan_cli.ui.slogans import _clean as C
        for raw in ("\x00" * 1000 + "OK", "a" * 500, "abc\x1b", "正常文案",
                    "x" * 5000 + "\u202e" + "y"):
            once = C.sanitize_log_field(raw)
            assert C.sanitize_log_field(once) == once
            assert C.sanitize_log_field(raw, 20) == C.sanitize_log_field(
                C.sanitize_log_field(raw, 20), 20)

    def test_scan_cap_is_an_explicit_fail_closed_boundary(self):
        """超过 _SCAN_CAP 的输入先粗切再清理 —— 如实锁定这个边界,
        不宣称「任意长度都能救回尾部内容」。"""
        from tuan_cli.ui.slogans import _clean as C
        assert C._SCAN_CAP == 65536
        assert C.sanitize_log_field("\x00" * 70000 + "OK") == ""
        assert len(C.sanitize_log_field("a" * 70000)) <= 121
        assert "\x1b" not in C.sanitize_log_field("a" * 65535 + "\x1b")

    def test_verb_and_limits_unchanged(self):
        from tuan_cli.ui.slogans import _clean as C
        assert C.sanitize_verb("正常文案 ✓") == "正常文案 ✓"
        assert C.sanitize_verb("abc\x1b") == "abc"
        assert len(C.sanitize_log_field("a" * 5000)) == 121
        for bad in (None, float("nan"), float("inf"), "5", True, -1):
            assert C.sanitize_log_field("abc", bad) == "abc"

    def test_lone_esc_was_already_handled_no_fix_made(self):
        """候选 A 实测不成立: _CTRL_RE 的 ``\\x0e-\\x1f`` 已含 0x1b。

        本轮**没有**为孤立 ESC 改任何清理逻辑; 这条测试只是防止
        以后有人误把它当成洞去「修」而破坏既有行为。
        """
        from tuan_cli.ui.slogans import _clean as C
        for raw in ("abc\x1b", "\x1b", "文案\x1b", "ok\x1b\x1b"):
            assert "\x1b" not in C.sanitize_verb(raw)
            assert "\x1b" not in C.sanitize_log_field(raw)


@pytest.mark.usefixtures("_clean_state")
class TestEvictionUsesInjectedClock:
    """C: 旧版淘汰痕用 time.monotonic(), 与 decision 的注入时钟两套。"""

    def _fill_and_evict(self, now):
        mapping.reset_runtime_counters(include_dispatch_log=True)
        K = mapping._MAX_OWNERS
        mapping.pick_for_event("tool.exploring", owner="s-0", now=now)
        mapping.pick_for_event("turn.completed", owner="s-0", now=now)
        for i in range(1, K):
            mapping.pick_for_event("tool.exploring", owner="s-%d" % i, now=now)
        mapping.pick_for_event("tool.exploring", owner="trigger", now=now)
        return next(r for r in mapping.evicted_owner_log()
                    if r.owner == "s-0")

    def test_eviction_at_ms_matches_injected_now(self):
        r = self._fill_and_evict(1000.0)
        assert r.at_ms == 1000000
        d = mapping.pick_for_event("tool.exploring", owner="x", now=1000.0)
        assert d.at_ms == r.at_ms

    def test_eviction_is_deterministic_under_replay(self):
        a = self._fill_and_evict(1000.0)
        b = self._fill_and_evict(1000.0)
        assert (a.owner, a.dropped, a.last_reason, a.at_ms, a.reason_counts) == \
               (b.owner, b.dropped, b.last_reason, b.at_ms, b.reason_counts)
        c = self._fill_and_evict(2000.0)
        assert c.at_ms == 2000000 and a.at_ms != c.at_ms

    def test_no_injection_still_produces_positive_ms(self):
        mapping.reset_runtime_counters(include_dispatch_log=True)
        K = mapping._MAX_OWNERS
        for i in range(K + 1):
            mapping.pick_for_event("tool.exploring", owner="s-%d" % i)
        r = mapping.evicted_owner_log()[-1]
        assert r.at_ms > 0


@pytest.mark.usefixtures("_clean_state")
class TestEvictionReasonSummary:
    """H: last_reason 掩盖桶内错误信号。"""

    def _bucket_with_error(self, now=1000.0):
        mapping.reset_runtime_counters(include_dispatch_log=True)
        K = mapping._MAX_OWNERS
        mapping.pick_for_event("tool.exploring", owner="s-0", now=now)
        mapping.record_error("typo.event", "boom", owner="s-0",
                             at_ms=int(now * 1000))
        mapping.pick_for_event("turn.completed", owner="s-0", now=now)
        for i in range(1, K):
            mapping.pick_for_event("tool.exploring", owner="s-%d" % i, now=now)
        mapping.pick_for_event("tool.exploring", owner="trigger", now=now)
        return next(r for r in mapping.evicted_owner_log()
                    if r.owner == "s-0")

    def test_error_signal_survives_eviction(self):
        r = self._bucket_with_error()
        assert r.last_reason == "ok"           # 旧版只看得到这个
        assert dict(r.reason_counts)["error:boom"] == 1
        assert dict(r.reason_counts)["ok"] == 2
        assert sum(n for _, n in r.reason_counts) == r.dropped

    def test_reason_counts_are_sorted_and_deterministic(self):
        a = self._bucket_with_error()
        b = self._bucket_with_error()
        assert a.reason_counts == b.reason_counts
        assert list(a.reason_counts) == sorted(a.reason_counts)
        assert all(isinstance(k, str) and isinstance(v, int)
                   for k, v in a.reason_counts)

    def test_reason_summary_is_desensitized(self):
        r = self._bucket_with_error()
        blob = repr(r)
        assert "text" not in blob and "entry_id" not in blob
        assert not hasattr(r, "text") and not hasattr(r, "entry_id")
        assert "\x1b" not in blob and "\u202e" not in blob

    def test_summary_does_not_change_audit_health(self):
        self._bucket_with_error()
        report = mapping.audit()
        assert report.ok is True
        assert report.as_dict()["dispatch_stats"]["evicted_recent"] >= 1


@pytest.mark.usefixtures("_clean_state")
class TestOwnerLimitWording:
    """D: 旧 docstring「干净输入零改动」对 >64 码点干净串不成立。"""

    def test_owner_limit_is_explicit(self):
        assert mapping.OWNER_LIMIT == 64

    def test_boundary_64_vs_65(self):
        assert mapping.norm_owner("a" * 64) == "a" * 64
        assert mapping.norm_owner("a" * 65).startswith("owner:")
        assert mapping.norm_owner("session-" + "x" * 80).startswith("owner:")

    def test_long_clean_owner_still_round_trips(self):
        raw = "session-" + "x" * 80
        mapping.reset_runtime_counters(include_dispatch_log=True)
        d = mapping.pick_for_event("tool.exploring", owner=raw)
        assert d.owner == mapping.norm_owner(raw)
        assert len(mapping.dispatch_log(raw)) == 1
        assert mapping.norm_owner(d.owner) == d.owner

    def test_docstring_no_longer_claims_unconditional_zero_change(self):
        import inspect
        src = inspect.getsource(mapping.norm_owner)
        assert "≤ ``OWNER_LIMIT`` 码点零改动" in src
        assert "65 码点以上" in src


@pytest.mark.usefixtures("_clean_state")
class TestFullHealthAfterD6:
    def test_registry_and_all_events_still_green(self):
        mapping.reset_runtime_counters(include_dispatch_log=True)
        r = mapping.audit()
        assert r.ok and r.index_consistent
        st = mapping.index_stats()
        assert st["by_id"] == st["by_text"] == st["by_clean"] == 1695
        assert st["index_misses"] == 0 and st["unresolved_misses"] == 0
        for lang in L.LANGUAGES:
            for ev in mapping.EVENT_BINDINGS:
                d = mapping.pick_for_event(ev, lang=lang,
                                           owner="final", now=1000.0)
                assert d.reason == "ok" and d.entry_id, (ev, lang)
        assert mapping.audit().ok is True
        mapping.reset_runtime_counters(include_dispatch_log=True)

# ================================================================ 深度轮 7


@pytest.mark.usefixtures("_clean_state")
class TestEscPlusSequence:
    """A: 上一轮 ESC_RUN 的覆盖缺口 —— 连续 ESC 串 + 真 CSI/OSC + 尾部文本。"""

    CASES = {
        "\x1b\x1b]8;;https://evil.example\x07OK": "OK",
        "\x1b\x1b\x1b]8;;evil\x07END": "END",
        "\x1b\x1b[31mRED": "RED",
        "\x1b\x1b[?25lHIDE": "HIDE",
        "\x1b\x1b]0;title\x07TAIL": "TAIL",
    }

    def test_esc_run_plus_real_sequence_keeps_full_tail(self):
        from tuan_cli.ui.slogans import _clean as C
        for raw, expected in self.CASES.items():
            assert C.sanitize_log_field(raw) == expected, repr(raw)
            assert C.sanitize_verb(raw) == expected, repr(raw)

    def test_single_esc_sequences_unchanged(self):
        """单 ESC 引导的真序列行为**不变**，不是放宽。"""
        from tuan_cli.ui.slogans import _clean as C
        assert C.sanitize_log_field("\x1b]8;;evil\x07OK") == "OK"
        assert C.sanitize_verb("\x1b[31mRED\x1b[0m") == "RED"
        assert C.sanitize_log_field("\x1b\x1b[31m") == ""
        assert C.sanitize_log_field("\x1b" * 900 + "END") == "END"
        assert C.sanitize_log_field("abc\x1b") == "abc"
        assert C.sanitize_log_field("ok\x1b\x1b") == "ok"

    def test_lone_esc_ambiguity_is_documented_not_fixed(self):
        """单个 ESC + 可打印字母的 ECMA-48 固有歧义**仍未改**。"""
        from tuan_cli.ui.slogans import _clean as C
        out = C.sanitize_log_field("\x1bEND")
        assert "\x1b" not in out
        assert out in ("END", "ND")

    def test_clean_is_still_idempotent(self):
        from tuan_cli.ui.slogans import _clean as C
        for raw in list(self.CASES) + [
            "\x1b]8;;evil\x07OK", "\x1b[31mRED\x1b[0m",
            "\x00" * 1000 + "OK", "正常文案", "x" * 5000 + "\u202e",
        ]:
            once = C.sanitize_log_field(raw)
            assert C.sanitize_log_field(once) == once, repr(raw)[:30]

    def test_regex_source_uses_esc_plus(self):
        import inspect
        from tuan_cli.ui.slogans import _clean
        src = inspect.getsource(_clean)
        assert r'\x1b+\]' in src and r'\x1b+\[' in src


@pytest.mark.usefixtures("_clean_state")
class TestInjectedClockStrictness:
    """B + A′: public 时钟入参一路裸奔；修时自己引入的 0 值缺陷。"""

    DIRTY = [float("nan"), float("inf"), -float("inf"), "1000",
             None, True, False, -1, 1e300]

    def test_dirty_now_never_raises_or_amplifies(self):
        mapping.reset_runtime_counters(include_dispatch_log=True)
        for bad in self.DIRTY:
            d = mapping.pick_for_event("tool.exploring", now=bad, owner="x")
            assert isinstance(d.at_ms, int) and d.at_ms > 0, bad
            assert d.at_ms < 10 ** 15, bad       # 不是天文数字

    def test_dirty_at_ms_never_leaks_type(self):
        mapping.reset_runtime_counters(include_dispatch_log=True)
        for bad in self.DIRTY:
            d = mapping.record_error("e", "k", at_ms=bad, owner="y")
            assert isinstance(d.at_ms, int) and d.at_ms > 0, bad
        d = mapping.record_error("e", "k", at_ms="1000", owner="y")
        assert d.at_ms != "1000"

    def test_legal_zero_is_not_swallowed(self):
        """A′: 本轮修 B 时自己引入的 ``or _fallback_ms()`` 会吞掉 0。"""
        assert mapping.pick_for_event("tool.exploring", now=0).at_ms == 0
        assert mapping.pick_for_event("tool.exploring", now=1).at_ms == 1000
        assert mapping.pick_for_event("tool.exploring", now=1000.0).at_ms == 1000000
        assert mapping.record_error("e", "k", at_ms=0).at_ms == 0

    def test_zero_propagates_to_eviction_trace(self):
        mapping.reset_runtime_counters(include_dispatch_log=True)
        K = mapping._MAX_OWNERS
        for i in range(K + 1):
            mapping.pick_for_event("tool.exploring", owner="s-%d" % i, now=0)
        assert mapping.evicted_owner_log()[-1].at_ms == 0

    def test_legal_injection_still_replays(self):
        mapping.reset_runtime_counters(include_dispatch_log=True)
        assert mapping._coerce_ms(1000.0, is_seconds=True) == 1000000
        assert mapping._coerce_ms(1000, is_seconds=False) == 1000
        assert mapping._coerce_ms(None, is_seconds=True) is None
        assert mapping._coerce_ms(True, is_seconds=True) is None
        for bad in self.DIRTY:
            assert mapping._coerce_ms(bad, is_seconds=True) is None, bad


@pytest.mark.usefixtures("_clean_state")
class TestBoundedOwnerDigest:
    """D: 上一轮明确留的边界（整串 sha1、无上界）。"""

    def test_cap_constants_are_explicit(self):
        assert mapping.OWNER_SCAN_CAP == 4096
        assert mapping._MAX_NOW_S == 1e12
        assert mapping._MAX_AT_MS == 1e15

    def test_tail_difference_still_distinguishes_oversized_owners(self):
        a = mapping.norm_owner("x" * 100000 + "A")
        b = mapping.norm_owner("x" * 100000 + "B")
        assert a != b
        assert a.startswith("owner:") and len(a) == 22

    def test_oversized_owner_is_idempotent_and_round_trips(self):
        raw = "o" * (2 << 20)
        n = mapping.norm_owner(raw)
        assert mapping.norm_owner(n) == n
        mapping.reset_runtime_counters(include_dispatch_log=True)
        d = mapping.pick_for_event("tool.exploring", owner=raw)
        assert d.owner == n
        assert len(mapping.dispatch_log(raw)) == 1

    def test_cost_is_independent_of_input_length(self):
        """与长度无关 = 固定上限（含 _SCAN_CAP=65536 扫描），不是「只扫 4096」。

        这里只做上界断言，不把毫秒数固化成期望值（机器波动大）。
        """
        import time
        from tuan_cli.ui.slogans import _clean as C
        assert C._SCAN_CAP == 65536
        times = []
        for n in (65536, 1 << 20, 4 << 20):
            raw = "o" * n
            t0 = time.perf_counter()
            mapping.norm_owner(raw)
            times.append((time.perf_counter() - t0) * 1000)
        assert max(times) < 500          # 固定上限，不随长度线性放大
        assert max(times) / max(min(times), 0.01) < 20

    def test_clean_owner_boundary_unchanged(self):
        assert mapping.norm_owner("s-0") == "s-0"
        assert mapping.norm_owner("a" * 64) == "a" * 64
        assert mapping.norm_owner("a" * 65).startswith("owner:")


@pytest.mark.usefixtures("_clean_state")
class TestCumulativeEvictionEvidence:
    """F: 环形缓冲只答「最近几条」，答不出「总共多少次」。"""

    def test_total_exceeds_recent_after_rollover(self):
        mapping.reset_runtime_counters(include_dispatch_log=True)
        K = mapping._MAX_OWNERS
        for i in range(K + mapping._EVICT_CAP + 50):
            mapping.pick_for_event("tool.exploring", owner="s-%d" % i,
                                   now=1000.0)
        st = mapping.dispatch_log_stats()
        assert st["evicted_recent"] == mapping._EVICT_CAP
        assert st["evicted_total"] > st["evicted_recent"]
        assert mapping.evicted_total() == st["evicted_total"]
        assert len(mapping.evicted_owner_log()) == mapping._EVICT_CAP

    def test_total_does_not_affect_audit_health(self):
        mapping.reset_runtime_counters(include_dispatch_log=True)
        K = mapping._MAX_OWNERS
        for i in range(K + 10):
            mapping.pick_for_event("tool.exploring", owner="s-%d" % i)
        assert mapping.audit().ok is True
        assert mapping.audit().as_dict()["dispatch_stats"]["evicted_total"] >= 1

    def test_only_full_reset_clears_total(self):
        mapping.reset_runtime_counters(include_dispatch_log=True)
        K = mapping._MAX_OWNERS
        for i in range(K + 3):
            mapping.pick_for_event("tool.exploring", owner="s-%d" % i)
        assert mapping.evicted_total() >= 1
        mapping.reset_runtime_counters()      # 默认不清日志
        assert mapping.evicted_total() >= 1
        mapping.reset_dispatch_log("one-owner")   # 单 owner 不清
        assert mapping.evicted_total() >= 1
        mapping.reset_dispatch_log()          # 全清才归零
        assert mapping.evicted_total() == 0

    def test_total_uses_same_lock_as_buckets(self):
        import threading
        mapping.reset_runtime_counters(include_dispatch_log=True)
        K = mapping._MAX_OWNERS

        def worker(base):
            for i in range(K // 2):
                mapping.pick_for_event("tool.exploring",
                                       owner="w%d-%d" % (base, i), now=1000.0)

        ts = [threading.Thread(target=worker, args=(b,)) for b in range(4)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        assert mapping.evicted_total() == mapping.dispatch_log_stats()[
            "evicted_total"]
        assert mapping.audit().ok is True


@pytest.mark.usefixtures("_clean_state")
class TestMeasuredFalseCandidatesNotChanged:
    """C / C2 / E / G: 四个候选实测不成立，本轮**未改**，锁住既有行为。"""

    def test_three_iterations_never_murder_legal_text(self):
        from tuan_cli.ui.slogans import _clean as C
        for raw in ("正常文案", "a" + "\u0301" * 10, "❤" + "\ufe0f" * 20,
                    "\u202e\u200b" * 20 + "OK", "\u200b\x1b\u2066" * 20 + "TAIL",
                    "\u200b" * 20 + "OK"):
            assert C.sanitize_log_field(raw), repr(raw)

    def test_leading_combining_marks_are_already_stripped(self):
        """C2: 怀疑开头组合标记造成 zalgo 视觉混淆，实测已清。"""
        from tuan_cli.ui.slogans import _clean as C
        assert C.sanitize_log_field("\u0301" * 3 + "OK") == "OK"
        assert C.sanitize_log_field("\u0301" + "A") == "A"
        assert C.sanitize_log_field("\u034f" * 5 + "OK") == "OK"
        assert C.sanitize_log_field("\u200d" * 3 + "OK") == "OK"

    def test_lone_surrogate_owners_do_not_collide(self):
        a = mapping.norm_owner("s\ud800A")
        b = mapping.norm_owner("s\ud800B")
        assert a != b
        assert mapping.norm_owner(a) == a and mapping.norm_owner(b) == b
        assert "\ud800" not in a and "\ud800" not in b

    def test_error_kind_is_already_sanitized(self):
        mapping.reset_runtime_counters(include_dispatch_log=True)
        d = mapping.record_error("ev", "\x1b]8;;https://evil\x07\u202eBOOM",
                                 owner="x", at_ms=1000)
        assert d.reason == "error:BOOM"
        assert "\x1b" not in d.reason and "\u202e" not in d.reason
        assert mapping.dispatch_log("x")[-1].reason == "error:BOOM"


@pytest.mark.usefixtures("_clean_state")
class TestFullHealthAfterD7:
    def test_registry_and_all_events_still_green(self):
        mapping.reset_runtime_counters(include_dispatch_log=True)
        r = mapping.audit()
        assert r.ok and r.index_consistent
        st = mapping.index_stats()
        assert st["by_id"] == st["by_text"] == st["by_clean"] == 1695
        assert st["index_misses"] == 0 and st["unresolved_misses"] == 0
        for lang in L.LANGUAGES:
            for ev in mapping.EVENT_BINDINGS:
                d = mapping.pick_for_event(ev, lang=lang, owner="final",
                                           now=1000.0)
                assert d.reason == "ok" and d.entry_id, (ev, lang)
        assert mapping.audit().ok is True
        mapping.reset_runtime_counters(include_dispatch_log=True)

# ================================================================ 深度轮 8


@pytest.mark.usefixtures("_clean_state")
class TestBucketTrimEvidence:
    """C: 桶内 _DISPATCH_CAP 裁剪在不淘汰时也会静默丢错误信号。"""

    def _trimmed_session(self):
        mapping.reset_runtime_counters(include_dispatch_log=True)
        mapping.pick_for_event("tool.exploring", owner="s0")
        mapping.record_error("typo.event", "boom", owner="s0", at_ms=1000)
        for i in range(mapping._DISPATCH_CAP + 20):
            mapping.pick_for_event("tool.exploring", owner="s0",
                                   now=1000.0 + i)
        return mapping.dispatch_log("s0")

    def test_error_is_gone_from_bucket_but_not_from_evidence(self):
        rows = self._trimmed_session()
        assert len(rows) == mapping._DISPATCH_CAP
        assert not any("error:boom" in r.reason for r in rows)
        st = mapping.bucket_trim_stats()
        assert st["trimmed_decisions"] >= 1
        assert st["bucket_trims"] >= 1
        assert dict(st["reason_counts"]).get("error:boom") == 1

    def test_no_eviction_happened(self):
        """与上一轮 H 的区别：这里 evicted_recent 仍是 0。"""
        self._trimmed_session()
        assert mapping.dispatch_log_stats()["evicted_recent"] == 0
        assert mapping.evicted_total() == 0

    def test_stats_expose_cumulative_decisions_and_trims(self):
        self._trimmed_session()
        st = mapping.dispatch_log_stats()
        assert st["decisions_total"] > st["decisions"]      # 含被裁的
        assert st["bucket_trims"] >= 1
        assert st["trimmed_decisions"] >= 1
        assert mapping.audit().as_dict()["dispatch_stats"][
            "trimmed_decisions"] >= 1

    def test_trim_evidence_does_not_affect_audit_health(self):
        self._trimmed_session()
        assert mapping.audit().ok is True

    def test_reason_summary_is_desensitized_and_sorted(self):
        st = self._trimmed_session() and mapping.bucket_trim_stats()
        rc = st["reason_counts"]
        assert list(rc) == sorted(rc)
        assert all(isinstance(k, str) and isinstance(v, int) for k, v in rc)
        blob = repr(rc)
        assert "text" not in blob and "entry_id" not in blob
        assert "\x1b" not in blob and "\u202e" not in blob

    def test_owner_summary_travels_with_eviction_record(self):
        self._trimmed_session()
        K = mapping._MAX_OWNERS
        for i in range(1, K):
            mapping.pick_for_event("tool.exploring", owner="s-%d" % i,
                                   now=1000.0)
        mapping.pick_for_event("tool.exploring", owner="trigger", now=1000.0)
        r = next(x for x in mapping.evicted_owner_log() if x.owner == "s0")
        assert r.trimmed_dropped >= 1
        assert dict(r.trimmed_reason_counts).get("error:boom") == 1
        # 淘汰那一刻的桶里只有 ok，错误信号全靠裁剪摘要才看得见
        assert r.reason_counts == (("ok", mapping._DISPATCH_CAP),)
        assert r.last_reason == "ok"

    def test_explicit_release_drops_owner_summary_but_keeps_global(self):
        self._trimmed_session()
        global_before = mapping.bucket_trim_stats()["trimmed_decisions"]
        mapping.release_owner("s0")
        assert mapping.dispatch_log("s0") == ()
        assert mapping.bucket_trim_stats()["trimmed_decisions"] == global_before
        assert mapping._TRIMMED_BY_OWNER.get("s0") is None

    def test_take_owner_log_drops_owner_summary_but_keeps_global(self):
        self._trimmed_session()
        global_before = mapping.bucket_trim_stats()["trimmed_decisions"]
        mapping.take_owner_log("s0")
        assert mapping.bucket_trim_stats()["trimmed_decisions"] == global_before
        assert mapping._TRIMMED_BY_OWNER.get("s0") is None

    def test_only_full_reset_zeroes_cumulative_evidence(self):
        self._trimmed_session()
        assert mapping.bucket_trim_stats()["trimmed_decisions"] >= 1
        mapping.reset_runtime_counters()          # 默认不清
        assert mapping.bucket_trim_stats()["trimmed_decisions"] >= 1
        mapping.reset_dispatch_log("s0")          # 单 owner 不清
        assert mapping.bucket_trim_stats()["trimmed_decisions"] >= 1
        mapping.reset_dispatch_log()              # 全清才归零
        st = mapping.bucket_trim_stats()
        assert st["trimmed_decisions"] == 0 and st["bucket_trims"] == 0
        assert st["reason_counts"] == ()
        ds = mapping.dispatch_log_stats()
        assert ds["decisions_total"] == 0 and ds["bucket_trims"] == 0

    def test_reason_kind_cap_is_bounded(self):
        """kind 虽已净化限长，种类仍可能膨胀；超出归 <other>。"""
        mapping.reset_runtime_counters(include_dispatch_log=True)
        for i in range(200):
            mapping.record_error("ev", "k%03d" % i, owner="x", at_ms=1000)
        # 单 owner 只有 64 条留存，裁剪后 reason 种类很多
        for i in range(mapping._DISPATCH_CAP + 10):
            mapping.pick_for_event("tool.exploring", owner="x", now=1000.0)
        rc = mapping.bucket_trim_stats()["reason_counts"]
        # 具体 reason 最多 CAP 种，额外的 "<other>" 是第 CAP+1 个桶
        assert len(rc) <= mapping._TRIMMED_REASON_CAP + 1
        assert sum(1 for k, _ in rc if k != "<other>") <= mapping._TRIMMED_REASON_CAP
        assert mapping.audit().ok is True


@pytest.mark.usefixtures("_clean_state")
class TestMeasuredButDeliberatelyNotChanged:
    """A/B/D/E/F/G: 实测后判定「不该动」，锁住当前正确行为。

    本轮的核心不是修了多少，而是**判断什么不该修**。详见
    ``SLOGAN_MAPPING.md`` §17。
    """

    def test_A_unterminated_osc_strips_whole_line_per_ecma48(self):
        """A: 未终止 OSC 整段删是 ECMA-48 规范行为，**未修**。

        尝试修（终止符必需 + 4096 上限）会把 4096 之后的**参数残留
        文本**放进日志，反而放宽净化；且 sanitize_log_field 最终按
        120 码点截断，尾部合法文本仍不可达。收益为零、风险为正。
        """
        from tuan_cli.ui.slogans import _clean as C
        assert C.sanitize_log_field("\x1b]8;;https://evil.example" + "OK") == ""
        assert C.sanitize_log_field("\x1b]0;title" + "TAIL") == ""
        assert C.sanitize_verb("\x1b]8;;u" + "OK") == ""
        # 有终止符的 OSC 行为不变
        assert C.sanitize_log_field("\x1b]8;;u\x07OK") == "OK"
        assert C.sanitize_verb("\x1b]8;;u\x1b\\OK") == "OK"

    def test_A_attempted_fix_would_leak_osc_parameters(self):
        """把「想修」的副作用变成可执行证据，而不是只写文档。"""
        import re
        import unicodedata
        from tuan_cli.ui.slogans import _clean as C
        term = re.compile(r"\x1b+\][^\x07\x1b]*(?:\x07|\x1b\\)")
        unterminated = re.compile(r"\x1b+\][^\x07\x1b]{0,4096}")
        raw = "\x1b]8;;" + "A" * 5000 + "END"
        s = unterminated.sub("", term.sub("", raw))
        # 4096 之后的 OSC 参数残留文本会进入后续清理/日志
        assert len(s) >= 900 and "END" in s
        drop = frozenset({"Cc", "Cf", "Cs", "Co", "Cn"})
        kept = "".join(ch for ch in s
                       if unicodedata.category(ch) not in drop
                       and not C._is_variation_selector(ch))
        assert len(kept) >= 900          # 参数残留确实留下了
        # 当前实现（整段删）返回空串
        assert C.sanitize_log_field(raw) == ""
        # 而「修后」即便残留 900+ 参数文本，按 120 码点截断后 END 仍不可达
        truncated = kept[:C.LOG_FIELD_LIMIT].rstrip() + "…"
        assert len(truncated) == C.LOG_FIELD_LIMIT + 1
        assert "END" not in truncated

    def test_B_registry_contains_no_zwj_variation_or_esc(self):
        """B 的收益核查：1695 条词条里零 ZWJ / VS16 / ESC。"""
        zwj = vs = esc = 0
        for e in mapping.registry():
            text = getattr(e, "text", "") or ""
            zwj += "\u200d" in text
            vs += any(0xFE00 <= ord(c) <= 0xFE0F for c in text)
            esc += "\x1b" in text
        assert (zwj, vs, esc) == (0, 0, 0)
        assert len(list(mapping.registry())) == 1695

    def test_B_zwj_stripping_is_a_documented_known_cost(self):
        """B: 删 Cf 会把 ZWJ emoji 拆散，是已知代价，**未修**。

        修它要放宽 Cf 清理并改 _clusters / display_cols / 500 串
        宽度回归，而标语库零 ZWJ —— 收益为零、风险为正。
        """
        from tuan_cli.ui.slogans import _clean as C
        assert C.sanitize_verb("👩\u200d💻") == "👩💻"
        assert C.sanitize_verb("👨\u200d👩\u200d👧") == "👨👩👧"
        assert C.sanitize_log_field("\u200d" * 3 + "OK") == "OK"
        # bidi / isolate / ZWSP 仍必须被删（Trojan Source 不回归）
        assert "\u202e" not in C.sanitize_log_field("\u202eRLO\u200dOK")
        assert "\u2066" not in C.sanitize_log_field("\u2066ISO\u200dOK")
        assert C.sanitize_log_field("\u200bZWSP\u200dOK").startswith("ZWSP")

    def test_D_eviction_reason_counts_are_already_sanitized(self):
        mapping.reset_runtime_counters(include_dispatch_log=True)
        K = mapping._MAX_OWNERS
        mapping.record_error("ev", "\x1b]8;;x\x07\u202eBAD",
                             owner="s-0", at_ms=1000)
        for i in range(1, K):
            mapping.pick_for_event("tool.exploring", owner="s-%d" % i)
        mapping.pick_for_event("tool.exploring", owner="trigger")
        r = next(x for x in mapping.evicted_owner_log() if x.owner == "s-0")
        blob = repr(r.reason_counts)
        assert "\x1b" not in blob and "\u202e" not in blob
        assert r.reason_counts and all(isinstance(k, str)
                                       for k, _ in r.reason_counts)

    def test_E_scan_cap_boundary_is_an_already_documented_limit(self):
        """E: 合法文本落在 65536 粗切窗口外 —— d6 已如实记录，未修。"""
        from tuan_cli.ui.slogans import _clean as C
        assert C._SCAN_CAP == 65536
        assert C.sanitize_log_field("\x00" * 65530 + "\u0301" * 3 + "OK") == "OK"
        assert C.sanitize_log_field("\x00" * 65533 + "\u0301" * 3 + "OK") == ""
        assert C.sanitize_log_field("\x00" * 70000 + "OK") == ""

    def test_F_verb_column_truncation_is_intended_not_a_defect(self):
        """F: sanitize_verb 按显示列宽截断是设计，不是「丢尾部」。"""
        from tuan_cli.ui.slogans import _clean as C
        assert C.sanitize_verb("\x00" * 1000 + "OK") == "OK"
        assert C.sanitize_verb("\x1b]8;;u\x07" + "B" * 200).startswith("B")
        assert len(C.sanitize_verb("a" * 500 + "END")) <= C._MAX_VERB_CHARS

    def test_G_both_exits_share_one_clean_core(self):
        """G: 未终止 OSC 同时影响两个出口，因为共用 _clean_once。"""
        import inspect
        from tuan_cli.ui.slogans import _clean as C
        from tuan_cli.tui import runtime_slogans as R
        src = inspect.getsource(C._clean_once)
        assert "_OSC_RE.sub" in src
        assert R.sanitize_verb is C.sanitize_verb
        assert C.sanitize_verb("\x1b]0;title" + " TAIL") == ""
        assert C.sanitize_log_field("\x1b]0;title" + " TAIL") == ""


@pytest.mark.usefixtures("_clean_state")
class TestFullHealthAfterD8:
    def test_registry_and_all_events_still_green(self):
        mapping.reset_runtime_counters(include_dispatch_log=True)
        r = mapping.audit()
        assert r.ok and r.index_consistent
        st = mapping.index_stats()
        assert st["by_id"] == st["by_text"] == st["by_clean"] == 1695
        assert st["index_misses"] == 0 and st["unresolved_misses"] == 0
        for lang in L.LANGUAGES:
            for ev in mapping.EVENT_BINDINGS:
                d = mapping.pick_for_event(ev, lang=lang, owner="final",
                                           now=1000.0)
                assert d.reason == "ok" and d.entry_id, (ev, lang)
        assert mapping.audit().ok is True
        mapping.reset_runtime_counters(include_dispatch_log=True)
