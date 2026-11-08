#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""「每个标语都要对应的」纯 stdlib 独立验证。

沙盒偶发 502 会清空全局 site-packages, pytest 环境不稳定。本脚本只
import 纯 stdlib 模块 (``tuan_cli.ui.slogans`` 及其子模块、``_clean``),
不依赖 pytest / prompt_toolkit / rich / wcwidth / i18n。

运行: PYTHONPATH=/data/workspace/push_verify2 python3 /data/workspace/verify_mapping.py
"""
from __future__ import annotations

import math
import sys
import threading
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]  # 仓库根目录
sys.path.insert(0, str(REPO))

from tuan_cli.ui.slogans import (  # noqa: E402
    mapping, picker, extra, extra_locales, universal, _clean,
)
from tuan_cli.ui.slogans import locales as L  # noqa: E402
from tuan_cli.ui.slogans.locales import patches  # noqa: E402

PASS, FAIL = [], []
_INVIS = {"Cc", "Cf", "Cs", "Co", "Cn"}


def check(name, fn):
    try:
        fn()
        PASS.append(name)
    except Exception as exc:
        FAIL.append((name, "%s: %s" % (type(exc).__name__, exc)))


# ---------------------------------------------------------------- 规模
def t_bank_sizes():
    assert universal.count() == 300
    assert extra.count() == 60
    assert sum(len(v) for v in universal.GROUPS.values()) == 300
    assert sum(len(v) for lang in L.LANGUAGES for v in L.groups(lang).values()) == 500
    assert extra_locales.count() == 240
    assert patches.count() == 8
    assert len(mapping.ALL_CONTEXTS) == 16
    assert len(L.LANGUAGES) == 10


def t_audit_all_invariants():
    r = mapping.audit()
    assert r.ok, r.as_dict()
    assert not any((r.orphan_slogans, r.events_without_pool,
                    r.contexts_without_event, r.events_without_context,
                    r.locale_gaps, r.empty_pools, r.duplicate_ids,
                    r.unsafe_bindings, r.phase_gaps, r.clipped_slogans))
    assert r.sanitizer_shared is True


# ---------------------------------------------------------------- 对应
def t_every_slogan_has_event():
    valid = set(mapping.EVENT_BINDINGS)
    for e in mapping.registry():
        assert e.event and e.event in valid, e.id
        assert mapping.EVENT_BINDINGS[e.event].context == e.context


def t_every_context_one_primary_event():
    assert set(mapping.CONTEXT_EVENTS) == set(mapping.ALL_CONTEXTS)
    assert len(mapping.CONTEXT_EVENTS) == 16
    for ctx, ev in mapping.CONTEXT_EVENTS.items():
        assert mapping.EVENT_BINDINGS[ev].context == ctx


def t_every_event_has_pool():
    for ev, b in mapping.EVENT_BINDINGS.items():
        assert b.context in mapping.ALL_CONTEXTS
        assert any(picker.pool_entries(b.context, lang) for lang in L.LANGUAGES)


def t_all_phases_mapped():
    assert set(mapping.PHASE_EVENTS) == {
        "booting", "waiting_model", "streaming", "running_tool", "retrying"}
    for phase, ev in mapping.PHASE_EVENTS.items():
        assert ev in mapping.EVENT_BINDINGS
        assert mapping.verbs_for_phase(phase, "zh-CN")


def t_ids_unique_reversible():
    reg = mapping.registry()
    assert len({e.id for e in reg}) == len(reg)
    s = reg[len(reg) // 2]
    assert mapping.entry_for(s.id).text == s.text
    assert mapping.entry_for("no:such:id") is None


def t_no_orphan_in_any_language():
    """每个 (语种, 上下文) 都至少有 1 条本语种词条。"""
    for lang in L.LANGUAGES:
        for ctx in mapping.ALL_CONTEXTS:
            es = picker.pool_entries(ctx, lang)
            assert es, (lang, ctx)
            if lang != "en":
                assert any(e.is_local for e in es), (lang, ctx)


# ---------------------------------------------------------------- 严格分发
def t_unknown_event_raises():
    try:
        mapping.pick_for_event("totally.unknown", lang="zh-CN")
        raise AssertionError("未知事件竟未抛异常")
    except mapping.UnboundSloganEvent:
        pass


def t_security_events_empty():
    for ev in sorted(mapping.SECURITY_EVENTS):
        d = mapping.pick_for_event(ev, lang="zh-CN")
        assert d.text == "" and d.reason == "security-notice"
        assert d.context is None
    assert mapping.SECURITY_EVENTS.isdisjoint(mapping.EVENT_BINDINGS)


def t_every_event_every_language():
    for ev in mapping.EVENT_BINDINGS:
        for lang in L.LANGUAGES:
            d = mapping.pick_for_event(ev, lang=lang)
            assert d.text and d.reason == "ok", (ev, lang, d.reason)
            assert _clean.sanitize_verb(d.text) == d.text
            assert _clean.display_cols(d.text) <= _clean._MAX_VERB_COLS
            assert all(unicodedata.category(c) not in _INVIS for c in d.text)


def t_local_first_no_leak():
    for lang in set(L.LANGUAGES) - {"en"}:
        for _ in range(100):
            for ev in ("background.progress", "memory.written",
                       "model.switched", "remote.paired",
                       "budget.warning", "background.started"):
                d = mapping.pick_for_event(ev, lang=lang)
                assert d.origin == "locale", (lang, ev, d.origin)


def t_dispatch_log_bounded():
    mapping.reset_dispatch_log()
    for _ in range(200):
        mapping.pick_for_event("tool.exploring", lang="ja")
    assert len(mapping.dispatch_log()) == 64


# ---------------------------------------------------------------- 补池
def t_extra_locales_fill_48_gaps():
    for lang in extra_locales.LANGUAGES:
        for ctx in extra.CONTEXTS:
            local = [e for e in picker.pool_entries(ctx, lang) if e.is_local]
            assert len(local) == 5, (lang, ctx, len(local))
            assert all(e.origin == "locale-extra" for e in local)


def t_de_together_patch():
    local = [e for e in picker.pool_entries("together", "de") if e.is_local]
    assert len(local) == 5
    assert all(e.origin == "locale-patch" for e in local)
    assert "Zusammen geht's leichter." in [e.text for e in local]


def t_overlong_replacements():
    for original, short in patches.REPLACEMENTS.items():
        assert _clean.display_cols(original) > _clean._MAX_VERB_COLS
        assert _clean.display_cols(short) <= _clean._MAX_VERB_COLS
        assert _clean.sanitize_verb(short) == short
    all_texts = {e.text for e in mapping.registry()}
    assert all_texts.isdisjoint(patches.REPLACEMENTS)


# ---------------------------------------------------------------- 净化共享
def t_sanitizer_is_shared():
    # 活性引擎 re-export 的是同一个函数对象, 不是第二套实现
    from tuan_cli.tui import runtime_slogans as RS
    assert RS.sanitize_verb is _clean.sanitize_verb
    assert RS.display_cols is _clean.display_cols
    assert RS._clusters is _clean._clusters
    assert RS._fit_headline is _clean._fit_headline


def t_all_pool_verbs_clean():
    for lang in L.LANGUAGES:
        for ctx in mapping.ALL_CONTEXTS:
            for e in picker.pool_entries(ctx, lang):
                assert _clean.sanitize_verb(e.text) == e.text, (lang, ctx, e.text)
                assert _clean.display_cols(e.text) <= _clean._MAX_VERB_COLS
                assert all(unicodedata.category(c) not in _INVIS for c in e.text)
                assert "\x1b" not in e.text


def t_side_doors_closed():
    assert _clean.sanitize_verb("正常\u202e话反") == "正常话反"
    assert _clean.sanitize_verb("\x1b(B正常") == "正常"
    assert _clean.sanitize_verb("❤\ufe0f") == "❤"


# ---------------------------------------------------------------- picker 修复
def t_min_interval_strict():
    for bad in (-1.0, float("nan"), float("inf"), "5", True):
        try:
            picker.SloganPicker(min_interval=bad)
            raise AssertionError("应拒绝 %r" % (bad,))
        except (ValueError, TypeError):
            pass
    assert picker.SloganPicker(min_interval=0.0).min_interval == 0.0


def t_injected_clock():
    now = [100.0]
    p = picker.SloganPicker(lang="zh-CN", min_interval=5.0,
                            clock=lambda: now[0])
    a = p.pick("thinking")
    now[0] += 1.0
    assert p.pick("thinking") == a
    now[0] += 4.1
    p.pick("thinking")
    assert math.isclose(p._last[("zh-CN", "thinking")][1], 105.1)


def t_window_lru_and_history():
    picker._windows.clear()
    with picker._windows_lock:
        picker._window_locked(("x", "k"), 5).append("历史词")
        picker._window_locked(("x", "k"), 20)
        assert "历史词" in list(picker._windows[("x", "k")])
        assert picker._windows[("x", "k")].maxlen == 20
    picker._windows.clear()
    with picker._windows_lock:
        for i in range(70):
            picker._window_locked(("lang", f"ctx{i}"), 4).append(f"w{i}")
        for i in (0, 1, 2):
            picker._window_locked(("lang", f"ctx{i}"), 4)
        keys = list(picker._windows)
        assert len(keys) == 64
        assert ("lang", "ctx0") in keys and ("lang", "ctx2") in keys


def t_single_item_short_circuit():
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


def t_thread_safety():
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
    # 本轮日志按 owner 分桶, 无参 dispatch_log() 是**全量**;
    # 单桶上界仍为 64 (旧断言假设全局单桶, 需按新语义收窄)。
    assert len(mapping.dispatch_log("")) <= 64
    assert all(len(b) <= 64 for b in mapping._dispatch_log.values())


# ---------------------------------------------------------------- TUI 接线
def t_tui_source_wiring():
    src = (REPO / "tuan_cli/tui/tui.py").read_text(encoding="utf-8")
    assert "def _slogan_dispatch(self, event: str, *, strict: bool = False)" in src
    assert "def slogan_for(self, event: str, *, strict: bool = False)" in src
    assert src.count('self._slogan_dispatch("tool.exploring")') == 1
    assert src.count('self._slogan_dispatch("model.streaming")') == 1
    assert src.count('self._slogan_dispatch("turn.completed")') == 1
    assert src.count('self._slogan_dispatch("session.exit")') == 1
    assert "1.0" in src  # 流式节流


def t_compat_shims():
    import slogans  # noqa: F401
    import slogans.picker as sp
    assert sp.pick is picker.pick
    assert slogans.universal.GROUPS is universal.GROUPS

# ---------------------------------------------------------------- 运行时闭环
def t_trace_carries_entry_id():
    src = (REPO / "tuan_cli/tui/tui.py").read_text(encoding="utf-8")
    assert "def _slogan_row(self, d)" in src
    assert "d.entry_id" in src
    assert "def slogan_trace(self)" in src
    assert "def slogan_errors(self)" in src
    assert "def slogan_owner(self)" in src


def t_no_silent_swallow():
    src = (REPO / "tuan_cli/tui/tui.py").read_text(encoding="utf-8")
    assert "except mapping.UnboundSloganEvent:" in src
    assert "self._slogan_error(event, \"unbound-event\")" in src
    assert '"error:" + kind' in src          # 错误前缀由拼接生成
    # 旧实现是 except Exception: return None 且什么都没记
    assert "return None" in src


def t_strict_mode_exists():
    src = (REPO / "tuan_cli/tui/tui.py").read_text(encoding="utf-8")
    assert "strict: bool = False" in src
    assert src.count("if strict:") >= 2


def t_tui_lock_and_owner():
    src = (REPO / "tuan_cli/tui/tui.py").read_text(encoding="utf-8")
    assert "self._slogan_lock = threading.RLock()" in src
    assert "self._slogan_owner" in src
    assert "owner=self._slogan_owner" in src


def t_index_stats():
    st = mapping.index_stats()
    assert st["by_id"] == st["registry"] == 1695
    assert st["by_text"] == 1695
    assert st["clipped_cached"] == 0


def t_clipped_is_cached_not_recomputed():
    src = (REPO / "tuan_cli/ui/slogans/mapping.py").read_text(encoding="utf-8")
    assert "_CLIPPED_IDS" in src
    assert "_ensure_index_locked()" in src
    assert "clipped = list(_CLIPPED_IDS)" in src
    # audit 不该再对 reg 逐条跑 sanitize_verb
    seg = src[src.index("def audit() -> AuditReport:"):]
    assert "sanitize_verb(e.text)" not in seg.split("def pick_for_event")[0]


def t_shared_event_groups():
    """model.streaming 触发的标语必须也声明它属于触发事件集合。"""
    for ctx in ("thinking", "undo"):
        entries = [e for e in mapping.registry()
                   if e.context == ctx and e.lang == "zh-CN"]
        assert entries
        expected = set(ev for ev, b in mapping.EVENT_BINDINGS.items()
                       if b.context == ctx)
        for e in entries:
            assert set(e.events) == expected, (e.id, e.events, expected)
            assert e.event == mapping.CONTEXT_EVENTS[ctx]
    think = set(mapping.registry()[0].events)  # 至少含主事件
    assert think


def t_every_dispatch_resolves_via_index():
    for lang in L.LANGUAGES:
        for ev in mapping.EVENT_BINDINGS:
            d = mapping.pick_for_event(ev, lang=lang, owner="verify-idx")
            assert d.reason == "ok" and d.entry_id, (ev, lang)
            e = mapping.entry_for(d.entry_id)
            assert e is not None and d.event in e.events
            assert e.text == d.text


def t_owner_scoped_log():
    mapping.reset_dispatch_log()
    a = mapping.pick_for_event("tool.exploring", owner="session-A")
    b = mapping.pick_for_event("turn.completed", owner="session-B")
    la = mapping.dispatch_log("session-A")
    lb = mapping.dispatch_log("session-B")
    assert len(la) == 1 and len(lb) == 1
    assert la[0].event == "tool.exploring" and lb[0].event == "turn.completed"
    assert all(d.owner == "session-A" for d in la)
    assert all(d.owner == "session-B" for d in lb)
    assert len(mapping.dispatch_log()) == 2
    mapping.reset_dispatch_log("session-A")
    assert mapping.dispatch_log("session-A") == ()
    assert len(mapping.dispatch_log("session-B")) == 1


def t_owner_buckets_are_bounded():
    mapping.reset_dispatch_log()
    for i in range(150):
        mapping.pick_for_event("tool.exploring", owner="bounded")
    assert len(mapping.dispatch_log("bounded")) == 64


class _VerifyRng:
    def __init__(self):
        self.calls = 0

    def choice(self, items):
        self.calls += 1
        return items[0]


def t_deterministic_replay():
    r1, r2 = _VerifyRng(), _VerifyRng()
    a = mapping.pick_for_event("turn.completed", lang="ja", now=42.0,
                               rng=r1, owner="replay-1")
    b = mapping.pick_for_event("turn.completed", lang="ja", now=42.0,
                               rng=r2, owner="replay-2")
    assert a.text == b.text and a.entry_id == b.entry_id
    assert a.at_ms == b.at_ms == 42000
    # 关键: 全局避重窗口不得污染回放 (旧实现第二次会 choice 13 次)
    assert r1.calls == r2.calls == 1


def t_rng_isolates_global_window():
    src = (REPO / "tuan_cli/ui/slogans/picker.py").read_text(encoding="utf-8")
    assert "def _choose_with(" in src
    assert "if rng is not None:" in src
    assert "_windows_lock" in src  # 生产路径仍加锁


def t_dispatch_lock_exists():
    src = (REPO / "tuan_cli/ui/slogans/mapping.py").read_text(encoding="utf-8")
    assert "_dispatch_lock = threading.RLock()" in src
    assert "def dispatch_log(owner: Optional[str] = None)" in src
    assert "def reset_dispatch_log(owner: Optional[str] = None)" in src
    assert "_registry_lock = threading.RLock()" in src


def t_audit_still_ok_and_fast():
    import time as _time
    t0 = _time.perf_counter()
    for _ in range(20):
        r = mapping.audit()
    elapsed = (_time.perf_counter() - t0) * 1000
    assert r.ok and r.index_consistent and r.sanitizer_shared
    assert not r.clipped_slogans
    # 修复前 763.7 ms; 缓存后 355.6 ms (剩余开销是 10x16 次 pool_entries)
    assert elapsed < 700, "20 次 audit %.1f ms, 疑似退回逐条净化" % elapsed


def t_dispatch_no_linear_scan():
    import inspect
    src = inspect.getsource(mapping.pick_for_event)
    assert "for e in registry()" not in src
    assert "entry_for_text(" in src


def t_thread_safe_dispatch():
    errors = []
    barrier = threading.Barrier(8)

    def worker(wid):
        try:
            barrier.wait()
            for i in range(150):
                ev = list(mapping.EVENT_BINDINGS)[(wid + i) % 18]
                d = mapping.pick_for_event(ev, lang=L.LANGUAGES[wid % 10],
                                           owner="thr-%d" % wid)
                assert d.text and d.entry_id
        except Exception as exc:
            errors.append(repr(exc))

    with ThreadPoolExecutor(max_workers=8) as ex:
        for f in [ex.submit(worker, i) for i in range(8)]:
            f.result()
    assert errors == [], errors[:3]
    for wid in range(8):
        assert len(mapping.dispatch_log("thr-%d" % wid)) == 64


for name, fn in sorted(globals().items()):
    if name.startswith("t_") and callable(fn):
        check(name, fn)

print("PASS: %d" % len(PASS))
for n in PASS:
    print("  [OK] " + n)
if FAIL:
    print("FAIL: %d" % len(FAIL))
    for n, why in FAIL:
        print("  [!!] %s -> %s" % (n, why))
print("TOTAL: %d" % (len(PASS) + len(FAIL)))
sys.exit(1 if FAIL else 0)
