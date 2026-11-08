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
    n = picker._MAX_WINDOWS + 6
    with picker._windows_lock:
        for i in range(n):
            picker._window_locked(("lang", f"ctx{i}"), 4).append(f"w{i}")
        for i in (0, 1, 2):
            picker._window_locked(("lang", f"ctx{i}"), 4)
        keys = list(picker._windows)
        assert len(keys) == picker._MAX_WINDOWS
        assert ("lang", "ctx0") in keys and ("lang", "ctx2") in keys
        assert ("lang", "ctx3") not in keys


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
    assert '"error:" + kd' in src            # 降级路径的错误前缀由拼接生成
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
    assert "entry_for_clean(" in src


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

# ---------------------------------------------------------------- 深度轮 3

def _d3_reset():
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


def t_clean_index_source_and_stats():
    src = (REPO / "tuan_cli/ui/slogans/mapping.py").read_text(encoding="utf-8")
    assert "_BY_CLEAN" in src
    assert "def entry_for_clean(" in src
    assert "entry_for_clean(resolved" in src
    st = mapping.index_stats()
    assert st["by_id"] == st["by_text"] == st["by_clean"] == st["registry"] == 1695
    assert st["clean_collisions"] == 0 and st["index_misses"] == 0


def t_clean_index_hits_sanitized_text():
    reg = mapping.registry()
    for e in (reg[0], reg[len(reg) // 2], reg[-1]):
        cleaned = _clean.sanitize_verb(e.text)
        got = mapping.entry_for_clean(e.lang, e.context, cleaned)
        assert got is not None and got.id == e.id
    assert mapping.entry_for_clean("ja", "explore", "查不到的词") is None
    # 兼容 API 仍按原始文案反查
    assert mapping.entry_for_text(reg[0].lang, reg[0].context,
                                  reg[0].text).id == reg[0].id


def t_zwsp_entry_resolves_after_fix():
    """实测复现场景: 修复前 reason='ok' 但 entry_id=''。"""
    orig = picker.pool_entries

    def patched(ctx, lang):
        out = list(orig(ctx, lang))
        if ctx == "explore" and lang == "ja":
            out.insert(0, picker.PoolEntry("探\u200b索中", "locale"))
        return tuple(out)

    class R:
        def choice(self, items):
            return items[0]

    picker.pool_entries = patched
    try:
        _d3_reset()
        d = mapping.pick_for_event("tool.exploring", lang="ja",
                                   rng=R(), owner="zwsp")
        assert d.reason == "ok", d.reason
        assert d.entry_id, "净化后索引未命中 -> 对应关系又断了"
        assert mapping.entry_for(d.entry_id).text == "探\u200b索中"
    finally:
        picker.pool_entries = orig
        _d3_reset()


def t_unresolvable_text_is_fail_closed():
    src = (REPO / "tuan_cli/ui/slogans/mapping.py").read_text(encoding="utf-8")
    assert '"index-miss"' in src
    assert "_INDEX_MISSES += 1" in src
    orig = picker.pick_local_first
    picker.pick_local_first = lambda ctx, lang, rng=None: ("凭空冒出的一句", "locale")
    try:
        d = mapping.pick_for_event("tool.exploring", lang="ja", owner="miss")
        assert d.reason == "index-miss" and d.text == "" and d.entry_id == ""
        assert mapping.index_stats()["index_misses"] == 1
        r = mapping.audit()
        assert r.runtime_index_misses == 1 and r.ok is False
    finally:
        picker.pick_local_first = orig
        _d3_reset()


def t_clean_collision_detected():
    orig = picker.pool_entries

    def patched(ctx, lang):
        out = list(orig(ctx, lang))
        if ctx == "explore" and lang == "ja":
            out.insert(0, picker.PoolEntry("撞车\u200b", "locale"))
            out.insert(1, picker.PoolEntry("撞车", "locale"))
        return tuple(out)

    picker.pool_entries = patched
    try:
        _d3_reset()
        assert mapping.index_stats()["clean_collisions"] >= 1
        r = mapping.audit()
        assert r.clean_collisions and r.ok is False
    finally:
        picker.pool_entries = orig
        _d3_reset()


def t_audit_index_consistent_is_strict():
    src = (REPO / "tuan_cli/ui/slogans/mapping.py").read_text(encoding="utf-8")
    assert 'idx["by_clean"]' in src
    assert 'idx["unresolved_misses"] == 0' in src
    assert "clean_collisions" in src
    r = mapping.audit()
    assert r.ok and r.index_consistent
    assert r.as_dict()["runtime_index_misses"] == 0
    key = next(iter(mapping._BY_CLEAN))
    saved = mapping._BY_CLEAN.pop(key)
    try:
        assert mapping.audit().index_consistent is False
    finally:
        mapping._BY_CLEAN[key] = saved
    assert mapping.audit().index_consistent is True


def t_owner_buckets_are_bounded():
    src = (REPO / "tuan_cli/ui/slogans/mapping.py").read_text(encoding="utf-8")
    assert "_MAX_OWNERS = 128" in src
    assert "popitem(last=False)" in src
    assert "def release_owner(" in src
    assert "def dispatch_log_stats(" in src
    _d3_reset()
    M = mapping._MAX_OWNERS
    for i in range(M + 20):
        mapping.pick_for_event("tool.exploring", owner="s-%d" % i)
    st = mapping.dispatch_log_stats()
    assert st["owners"] == M
    assert st["decisions"] <= M * st["cap_per_owner"]
    assert mapping.dispatch_log("s-0") == ()
    assert len(mapping.dispatch_log("s-%d" % (M + 19))) == 1
    _d3_reset()


def t_close_releases_owner():
    tui = (REPO / "tuan_cli/tui/tui.py").read_text(encoding="utf-8")
    assert "mapping.take_owner_log(self._slogan_owner)" in tui
    assert "def close(self) -> None:" in tui
    from tuan_cli.tui.tui import QxtTUI
    obj = QxtTUI(on_submit=lambda _t: "ok")
    obj._booting = False
    obj._boot_error = None
    obj.begin_tool("git status")
    owner = obj.slogan_owner()
    assert len(mapping.dispatch_log(owner)) == 1
    obj.close()
    assert mapping.dispatch_log(owner) == ()
    assert len(obj.slogan_trace()) >= 2
    _d3_reset()


def t_error_visible_in_two_layers():
    tui = (REPO / "tuan_cli/tui/tui.py").read_text(encoding="utf-8")
    assert "mapping.record_error(" in tui
    src = (REPO / "tuan_cli/ui/slogans/mapping.py").read_text(encoding="utf-8")
    assert "def record_error(" in src
    _d3_reset()
    from tuan_cli.tui.tui import QxtTUI
    obj = QxtTUI(on_submit=lambda _t: "ok")
    obj._booting = False
    obj._boot_error = None
    obj._slogan_dispatch("totally.typo.event")
    assert len(obj.slogan_errors()) == 1
    rows = [d for d in mapping.dispatch_log(obj.slogan_owner())
            if d.reason.startswith("error:")]
    assert len(rows) == 1
    assert rows[0].reason == "error:unbound-event"
    assert rows[0].text == "" and rows[0].entry_id == ""
    # 安全事件不能混成 error
    assert obj.slogan_for("security.blocked") == ""
    assert mapping.dispatch_log(obj.slogan_owner())[-1].reason == "security-notice"
    _d3_reset()


def t_window_capacity_covers_key_space():
    src = (REPO / "tuan_cli/ui/slogans/picker.py").read_text(encoding="utf-8")
    assert "_MAX_WINDOWS: int = (" in src
    assert "len(LANGUAGES) * (len(universal.CONTEXTS)" in src
    theoretical = len(L.LANGUAGES) * (
        len(universal.CONTEXTS) + len(extra.CONTEXTS)) * 2
    assert theoretical == 320
    assert picker._MAX_WINDOWS == 384 > theoretical
    _d3_reset()
    keys = [(l, c + s) for l in L.LANGUAGES
            for c in mapping.ALL_CONTEXTS for s in ("", ":local")]
    for k in keys:
        picker._choose(("a", "b", "c", "d", "e", "f", "g", "h"), k)
    assert len(picker._windows) == len(keys) == 320
    first = (L.LANGUAGES[0], mapping.ALL_CONTEXTS[0])
    assert picker._windows.get(first) is not None
    _d3_reset()


def t_every_event_still_resolves_with_full_index():
    _d3_reset()
    for lang in L.LANGUAGES:
        for ev in mapping.EVENT_BINDINGS:
            d = mapping.pick_for_event(ev, lang=lang, owner="final")
            assert d.reason == "ok" and d.entry_id, (ev, lang)
            e = mapping.entry_for(d.entry_id)
            assert e is not None and d.event in e.events
            assert d.text == _clean.sanitize_verb(e.text)
    r = mapping.audit()
    assert r.ok and r.index_consistent and r.runtime_index_misses == 0
    _d3_reset()

# ---------------------------------------------------------------- 深度轮 4


def _d4_reindex():
    with mapping._registry_lock:
        mapping._REGISTRY = None
        mapping._BY_ID.clear()
        mapping._BY_TEXT.clear()
        mapping._BY_CLEAN.clear()
        mapping._CLIPPED_IDS = ()
        mapping._UNRENDERABLE_IDS = ()
        mapping._CLEAN_COLLISIONS = ()
    mapping.reset_runtime_counters(include_dispatch_log=True)


class _D4Rng:
    def choice(self, items):
        return items[0]


def _d4_evil():
    return "x" * 5000 + "\x1b]8;;https://evil.example\x07" + "\u202eRLO"


def t_d4_audit_self_heals_without_losing_evidence():
    src = (REPO / "tuan_cli/ui/slogans/mapping.py").read_text(encoding="utf-8")
    assert "_UNRESOLVED_MISSES" in src
    assert "def acknowledge_runtime_misses(" in src
    assert "include_dispatch_log: bool = False" in src
    orig = picker.pick_local_first
    picker.pick_local_first = lambda ctx, lang, rng=None: ("查不到的词", "locale")
    try:
        _d4_reindex()
        d = mapping.pick_for_event("tool.exploring", owner="m")
        assert d.reason == "index-miss" and mapping.audit().ok is False
    finally:
        picker.pick_local_first = orig
    mapping.pick_for_event("tool.exploring", owner="healthy")
    r = mapping.audit()
    assert r.ok and r.index_consistent
    assert r.unresolved_misses == 0 and r.runtime_index_misses == 1
    assert mapping.dispatch_log_stats()["decisions"] >= 2
    _d4_reindex()


def t_d4_acknowledge_preserves_logs_and_cumulative():
    _d4_reindex()
    orig = picker.pick_local_first
    picker.pick_local_first = lambda ctx, lang, rng=None: ("查不到的词", "locale")
    try:
        mapping.pick_for_event("tool.exploring", owner="m")
        mapping.pick_for_event("tool.exploring", owner="m")
        before = mapping.dispatch_log_stats()
        n = mapping.acknowledge_runtime_misses()
        assert n == 2
        st = mapping.index_stats()
        assert st["unresolved_misses"] == 0
        assert st["index_misses"] == 2            # 累计证据不动
        assert mapping.dispatch_log_stats() == before
        assert mapping.audit().ok is True
    finally:
        picker.pick_local_first = orig
        _d4_reindex()


def t_d4_reset_counters_keeps_logs_by_default():
    _d4_reindex()
    mapping.pick_for_event("tool.exploring", owner="keep")
    mapping.reset_runtime_counters()
    assert len(mapping.dispatch_log("keep")) == 1
    mapping.reset_runtime_counters(include_dispatch_log=True)
    assert mapping.dispatch_log("keep") == ()


def t_d4_close_seals_session_exit():
    tui = (REPO / "tuan_cli/tui/tui.py").read_text(encoding="utf-8")
    assert "sealed = mapping.take_owner_log(self._slogan_owner)" in tui
    assert "with self._slogan_lock:" in tui
    assert "def slogan_closed_trace(self)" in tui
    from tuan_cli.tui.tui import QxtTUI
    obj = QxtTUI(on_submit=lambda _t: "ok")
    obj._booting = False
    obj._boot_error = None
    obj.begin_tool("git status")
    owner = obj.slogan_owner()
    obj.close()
    assert mapping.dispatch_log(owner) == ()
    sealed = obj.slogan_closed_trace()
    assert sealed and "session.exit" in [r["event"] for r in sealed]
    assert all(set(r) == {"event", "context", "reason", "origin",
                          "entry_id", "owner", "at_ms"} for r in sealed)
    _d4_reindex()


def t_d4_take_owner_log_returns_and_releases():
    src = (REPO / "tuan_cli/ui/slogans/mapping.py").read_text(encoding="utf-8")
    assert "def take_owner_log(" in src
    _d4_reindex()
    mapping.pick_for_event("tool.exploring", owner="take")
    mapping.pick_for_event("turn.completed", owner="take")
    snap = mapping.take_owner_log("take")
    assert len(snap) == 2 and snap[-1].event == "turn.completed"
    assert mapping.dispatch_log("take") == ()
    assert mapping.take_owner_log("take") == ()
    assert mapping.take_owner_log("") == ()


def t_d4_lru_read_refreshes_but_full_snapshot_does_not():
    src = (REPO / "tuan_cli/ui/slogans/mapping.py").read_text(encoding="utf-8")
    assert "_dispatch_log.move_to_end(key)" in src
    _d4_reindex()
    K = mapping._MAX_OWNERS
    for i in range(K):
        mapping.pick_for_event("tool.exploring", owner="s-%d" % i)
    for _ in range(50):
        mapping.dispatch_log("s-0")
    for i in range(K, K + 10):
        mapping.pick_for_event("tool.exploring", owner="s-%d" % i)
    assert len(mapping.dispatch_log("s-0")) == 1
    assert mapping.dispatch_log("s-1") == ()
    _d4_reindex()
    for i in range(K):
        mapping.pick_for_event("tool.exploring", owner="s-%d" % i)
    mapping.dispatch_log()                  # 全量读不刷新
    for i in range(K, K + 10):
        mapping.pick_for_event("tool.exploring", owner="s-%d" % i)
    assert mapping.dispatch_log("s-0") == ()
    _d4_reindex()


def t_d4_log_fields_are_sanitized():
    clean = (REPO / "tuan_cli/ui/slogans/_clean.py").read_text(encoding="utf-8")
    assert "def sanitize_log_field(" in clean
    assert "def _clean_once(" in clean
    mapping_src = (REPO / "tuan_cli/ui/slogans/mapping.py").read_text(encoding="utf-8")
    assert "_clean.sanitize_log_field(event)" in mapping_src
    tui = (REPO / "tuan_cli/tui/tui.py").read_text(encoding="utf-8")
    assert "_clean.sanitize_log_field(event)" in tui
    _d4_reindex()
    d = mapping.record_error(_d4_evil(), "boom", owner="inj")
    assert len(d.event) <= 121
    assert "\x1b" not in d.event and "\u202e" not in d.event
    assert "]8;;" not in d.event and d.reason == "error:boom"
    bad = mapping.record_error("\x1b\u200b\u202e", "\x1b", at_ms=1)
    assert bad.event == "<invalid-event>" and "\x1b" not in bad.event
    try:
        mapping.pick_for_event(_d4_evil())
    except mapping.UnboundSloganEvent as exc:
        msg = str(exc)
        assert "\x1b" not in msg and "\u202e" not in msg and "]8;;" not in msg
        assert len(msg) < 300
    else:
        raise AssertionError("unknown event must raise")
    from tuan_cli.tui.tui import QxtTUI
    obj = QxtTUI(on_submit=lambda _t: "ok")
    obj._booting = False
    obj._boot_error = None
    obj._slogan_dispatch(_d4_evil())
    errs = obj.slogan_errors()
    assert len(errs) == 1 and "\x1b" not in errs[0][0]
    rows = [d for d in mapping.dispatch_log(obj.slogan_owner())
            if d.reason.startswith("error:")]
    assert len(rows) == 1 and errs[0][0] == rows[0].event
    _d4_reindex()


def t_d4_log_field_shares_clean_core_and_is_idempotent():
    from tuan_cli.ui.slogans import _clean
    evil = _d4_evil()
    log = _clean.sanitize_log_field(evil)
    verb = _clean.sanitize_verb(evil)
    assert "\x1b" not in log and "\x1b" not in verb
    assert "\u202e" not in log and "\u202e" not in verb
    assert len(log) > len(verb)     # 120 码点 vs 40 列
    assert _clean.sanitize_log_field(log) == log
    assert _clean.sanitize_verb("正常文案 ✓") == "正常文案 ✓"


def t_d4_sanitized_is_informational_not_fatal():
    orig = picker.pool_entries

    def patched(ctx, lang):
        out = list(orig(ctx, lang))
        if ctx == "explore" and lang == "ja":
            out.insert(0, picker.PoolEntry("探\u200b索中", "locale"))
        return tuple(out)

    picker.pool_entries = patched
    try:
        _d4_reindex()
        d = mapping.pick_for_event("tool.exploring", lang="ja",
                                   rng=_D4Rng(), owner="clip")
        assert d.reason == "ok" and d.entry_id and d.text == "探索中"
        r = mapping.audit()
        assert r.ok and r.index_consistent
        assert len(r.sanitized_slogans) == 1
        assert r.unrenderable_slogans == ()
        assert r.clipped_slogans == r.sanitized_slogans
    finally:
        picker.pool_entries = orig
        _d4_reindex()


def t_d4_unrenderable_and_collision_still_fatal():
    orig = picker.pool_entries

    def bad_pool(ctx, lang):
        out = list(orig(ctx, lang))
        if ctx == "explore" and lang == "ja":
            out.insert(0, picker.PoolEntry("\x1b\u200b\u202e", "locale"))
        return tuple(out)

    picker.pool_entries = bad_pool
    try:
        _d4_reindex()
        r = mapping.audit()
        assert r.unrenderable_slogans and r.ok is False
    finally:
        picker.pool_entries = orig
        _d4_reindex()

    def colliding(ctx, lang):
        out = list(orig(ctx, lang))
        if ctx == "explore" and lang == "ja":
            out.insert(0, picker.PoolEntry("撞车\u200b", "locale"))
            out.insert(1, picker.PoolEntry("撞车", "locale"))
        return tuple(out)

    picker.pool_entries = colliding
    try:
        _d4_reindex()
        r = mapping.audit()
        assert r.clean_collisions and r.ok is False
    finally:
        picker.pool_entries = orig
        _d4_reindex()


def t_d4_single_render_exit():
    import inspect
    src = inspect.getsource(mapping.pick_for_event)
    assert "[:max_cols]" not in src
    assert "text = sanitize_verb(raw)" in src
    long = "很长的标语" * 30
    orig = picker.pool_entries

    def patched(ctx, lang):
        out = list(orig(ctx, lang))
        if ctx == "explore" and lang == "ja":
            out.insert(0, picker.PoolEntry(long, "locale"))
        return tuple(out)

    picker.pool_entries = patched
    try:
        _d4_reindex()
        d = mapping.pick_for_event("tool.exploring", lang="ja",
                                   rng=_D4Rng(), owner="long")
        assert d.reason == "ok" and d.entry_id, d.reason
        from tuan_cli.ui.slogans import _clean
        assert d.text == _clean.sanitize_verb(long)
        assert _clean.display_cols(d.text) <= _clean._MAX_VERB_COLS
    finally:
        picker.pool_entries = orig
        _d4_reindex()


def t_d4_audit_report_fields():
    r = mapping.audit().as_dict()
    assert r["ok"] is True
    assert r["unresolved_misses"] == 0
    assert r["runtime_index_misses"] == 0
    assert r["sanitized_slogans"] == 0
    assert r["unrenderable_slogans"] == 0
    assert mapping.index_stats()["unresolved_misses"] == 0
    assert mapping.index_stats()["unrenderable"] == 0
    assert mapping.audit().ok is True

# ---------------------------------------------------------------- 深度轮 5


def _d5_evil_owner():
    return "own" + "\x1b]8;;https://evil.example\x07" + "\u202eRLO" + "x" * 5000


def t_d5_owner_normalization():
    src = (REPO / "tuan_cli/ui/slogans/mapping.py").read_text(encoding="utf-8")
    assert "def norm_owner(" in src
    # 深度轮 9: 入口改走 _coerce_owner (非 str 隔离+留痕)，
    # 断言同步到新契约，不是放宽：仍要求 norm_owner 存在且被入口调用。
    assert "def norm_owner(" in src
    assert "def _coerce_owner(" in src
    assert "owner = _coerce_owner(owner)" in src
    assert "_coerce_owner(owner)" in src
    raw = _d5_evil_owner()
    n = mapping.norm_owner(raw)
    assert len(n) <= 30 and n.startswith("owner:")
    assert "\x1b" not in n and "\u202e" not in n and "]8;;" not in n
    assert mapping.norm_owner("s-0") == "s-0"
    assert mapping.norm_owner("tui:7f8a") == "tui:7f8a"
    assert mapping.norm_owner("") == "" and mapping.norm_owner(None) == ""


def t_d5_norm_owner_is_idempotent():
    """实测逼出来的: 初版 74 码点二次归一会重算指纹。"""
    raw = _d5_evil_owner()
    n = mapping.norm_owner(raw)
    assert mapping.norm_owner(n) == n
    assert mapping.norm_owner(mapping.norm_owner(raw)) == n
    assert mapping.norm_owner(raw) != mapping.norm_owner(raw + "y")


def t_d5_write_and_query_same_key():
    raw = _d5_evil_owner()
    mapping.reset_runtime_counters(include_dispatch_log=True)
    d = mapping.pick_for_event("tool.exploring", owner=raw)
    assert d.owner == mapping.norm_owner(raw)
    assert "\x1b" not in d.owner and "\u202e" not in d.owner
    assert len(mapping.dispatch_log(raw)) == 1
    assert len(mapping.dispatch_log(d.owner)) == 1
    assert mapping.release_owner(raw) == 1
    assert mapping.dispatch_log(raw) == ()
    mapping.pick_for_event("tool.exploring", owner=raw)
    snap = mapping.take_owner_log(raw)
    assert len(snap) == 1 and snap[0].owner == mapping.norm_owner(raw)
    mapping.reset_runtime_counters(include_dispatch_log=True)


def t_d5_record_error_owner_is_clean():
    raw = _d5_evil_owner()
    mapping.reset_runtime_counters(include_dispatch_log=True)
    d = mapping.record_error("typo.event", "boom", owner=raw)
    assert d.owner == mapping.norm_owner(raw)
    assert "\x1b" not in d.owner and "\u202e" not in d.owner
    assert len(mapping.dispatch_log(raw)) == 1
    mapping.reset_runtime_counters(include_dispatch_log=True)


def t_d5_log_limit_coercion():
    clean = (REPO / "tuan_cli/ui/slogans/_clean.py").read_text(encoding="utf-8")
    assert "def _coerce_log_limit(" in clean
    assert "math.isfinite" in clean
    from tuan_cli.ui.slogans import _clean
    for bad in ("5", None, float("nan"), float("inf"), -1,
                True, False, 0, 99999, 8.0, "abc"):
        assert _clean.sanitize_log_field("abc", bad) == "abc", bad
    assert len(_clean.sanitize_log_field("字" * 200, 20)) <= 21
    assert len(_clean.sanitize_log_field("a" * 5000)) == 121
    assert _clean.sanitize_verb("正常文案 ✓") == "正常文案 ✓"


def t_d5_passive_eviction_is_traced():
    src = (REPO / "tuan_cli/ui/slogans/mapping.py").read_text(encoding="utf-8")
    assert "class EvictionRecord" in src
    assert "def evicted_owner_log(" in src
    assert "_EVICTED.append(" in src
    assert "evicted_recent" in src
    mapping.reset_runtime_counters(include_dispatch_log=True)
    K = mapping._MAX_OWNERS
    mapping.pick_for_event("tool.exploring", owner="s-0")
    mapping.pick_for_event("turn.completed", owner="s-0")
    for i in range(1, K):
        mapping.pick_for_event("tool.exploring", owner="s-%d" % i)
    mapping.pick_for_event("tool.exploring", owner="trigger")
    assert mapping.dispatch_log("s-0") == ()
    recs = mapping.evicted_owner_log()
    r = next(r for r in recs if r.owner == "s-0")
    assert r.dropped == 2 and r.last_reason == "ok" and r.at_ms > 0
    assert not hasattr(r, "text") and not hasattr(r, "entry_id")
    assert mapping.audit().ok is True
    assert mapping.audit().as_dict()["dispatch_stats"]["evicted_recent"] >= 1
    mapping.reset_runtime_counters(include_dispatch_log=True)


def t_d5_eviction_log_is_bounded_and_resettable():
    mapping.reset_runtime_counters(include_dispatch_log=True)
    for i in range(mapping._EVICT_CAP + 200):
        mapping.pick_for_event("tool.exploring", owner="s-%d" % i)
    assert len(mapping.evicted_owner_log()) <= mapping._EVICT_CAP
    st = mapping.dispatch_log_stats()
    assert st["evicted_recent"] <= mapping._EVICT_CAP
    assert st["evicted_cap"] == 64 and st["owners"] == mapping._MAX_OWNERS
    mapping.reset_dispatch_log()
    assert mapping.evicted_owner_log() == ()


def t_d5_close_single_exit_and_locked_write():
    tui = (REPO / "tuan_cli/tui/tui.py").read_text(encoding="utf-8")
    i = tui.index("    def close(self) -> None:")
    j = tui.index("    def slogan_closed_trace(self)", i)
    close_src = tui[i:j]
    assert "mapping.take_owner_log(" in close_src
    assert "mapping.release_owner(" not in close_src
    assert "mapping.dispatch_log(self._slogan_owner)" not in close_src
    assert "with self._slogan_lock:" in close_src
    assert "self._slogan_sealed = sealed" in close_src
    trace_src = tui[j:j + 800]
    assert 'keys = ("event"' not in trace_src
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
    assert all(r.owner != obj.slogan_owner()
               for r in mapping.evicted_owner_log())
    mapping.reset_runtime_counters(include_dispatch_log=True)


def t_d5_full_health_after_all_fixes():
    mapping.reset_runtime_counters(include_dispatch_log=True)
    r = mapping.audit()
    assert r.ok and r.index_consistent
    st = mapping.index_stats()
    assert st["by_id"] == st["by_text"] == st["by_clean"] == 1695
    assert st["index_misses"] == 0 and st["unresolved_misses"] == 0
    for lang in L.LANGUAGES:
        for ev in mapping.EVENT_BINDINGS:
            d = mapping.pick_for_event(ev, lang=lang, owner="final")
            assert d.reason == "ok" and d.entry_id, (ev, lang)
    assert mapping.audit().ok is True
    mapping.reset_runtime_counters(include_dispatch_log=True)

# ---------------------------------------------------------------- 深度轮 6


def t_d6_clean_before_truncate():
    clean = (REPO / "tuan_cli/ui/slogans/_clean.py").read_text(encoding="utf-8")
    assert "_SCAN_CAP = 65536" in clean
    assert "raw[:lim * 4]" not in clean
    assert "_ESC_RUN_RE" in clean
    from tuan_cli.ui.slogans import _clean as C
    assert C.sanitize_log_field("\x00" * 1000 + "OK", 120) == "OK"
    assert C.sanitize_log_field("\x1b" * 900 + "END", 120) == "END"
    assert C.sanitize_log_field("\x00" * 300 + "A" + "\x00" * 300 + "B") == "AB"
    assert C.sanitize_log_field("\x1b\x1b[31m") == ""
    assert C.sanitize_log_field("\x1b\x1b\x1b[31m") == ""
    assert C.sanitize_log_field("\x1b]8;;evil\x07OK") == "OK"
    assert C.sanitize_verb("\x1b[31mRED\x1b[0m") == "RED"
    assert C.sanitize_verb("abc\x1b") == "abc"


def t_d6_log_field_idempotent_and_bounded():
    from tuan_cli.ui.slogans import _clean as C
    for raw in ("\x00" * 1000 + "OK", "a" * 500, "abc\x1b", "正常文案",
                "x" * 5000 + "\u202e" + "y"):
        once = C.sanitize_log_field(raw)
        assert C.sanitize_log_field(once) == once, raw[:20]
        assert "\x1b" not in once and "\u202e" not in once
    # 超过扫描上限是显式的 fail-closed 边界, 不宣称任意长度都能救回尾部
    assert C.sanitize_log_field("\x00" * 70000 + "OK") == ""
    assert len(C.sanitize_log_field("a" * 70000)) <= 121
    assert len(C.sanitize_log_field("a" * 5000)) == 121
    for bad in (None, float("nan"), float("inf"), "5", True, -1):
        assert C.sanitize_log_field("abc", bad) == "abc", bad
    assert C.sanitize_verb("正常文案 ✓") == "正常文案 ✓"


def t_d6_lone_esc_was_already_handled():
    """候选 A 实测不成立, 本轮未改孤立 ESC 逻辑。"""
    from tuan_cli.ui.slogans import _clean as C
    for raw in ("abc\x1b", "\x1b", "文案\x1b", "ok\x1b\x1b"):
        assert "\x1b" not in C.sanitize_verb(raw)
        assert "\x1b" not in C.sanitize_log_field(raw)
    # 单个 ESC + 可打印字母的 ECMA-48 歧义如实保留, 只保证无控制字符
    out = C.sanitize_log_field("\x1bEND")
    assert "\x1b" not in out and out in ("END", "ND")


def t_d6_eviction_clock_is_injected():
    src = (REPO / "tuan_cli/ui/slogans/mapping.py").read_text(encoding="utf-8")
    assert "def _record(d: SloganDecision, at_ms: Optional[int] = None)" in src
    assert "at_ms=stamp" in src or "at_ms=stamp," in src
    mapping.reset_runtime_counters(include_dispatch_log=True)
    K = mapping._MAX_OWNERS
    for i in range(K + 1):
        mapping.pick_for_event("tool.exploring", owner="s-%d" % i, now=1000.0)
    recs = mapping.evicted_owner_log()
    assert recs and all(r.at_ms == 1000000 for r in recs)
    d = mapping.pick_for_event("tool.exploring", owner="x", now=1000.0)
    assert d.at_ms == recs[-1].at_ms
    # 确定性回放
    first = tuple((r.owner, r.dropped, r.at_ms, r.reason_counts) for r in recs)
    mapping.reset_runtime_counters(include_dispatch_log=True)
    for i in range(K + 1):
        mapping.pick_for_event("tool.exploring", owner="s-%d" % i, now=1000.0)
    second = tuple((r.owner, r.dropped, r.at_ms, r.reason_counts)
                   for r in mapping.evicted_owner_log())
    assert first == second
    mapping.reset_runtime_counters(include_dispatch_log=True)


def t_d6_eviction_reason_summary():
    src = (REPO / "tuan_cli/ui/slogans/mapping.py").read_text(encoding="utf-8")
    assert "reason_counts: Tuple[Tuple[str, int], ...]" in src
    assert "Counter(x.reason for x in ev_bucket)" in src
    mapping.reset_runtime_counters(include_dispatch_log=True)
    K = mapping._MAX_OWNERS
    mapping.pick_for_event("tool.exploring", owner="s-0", now=1000.0)
    mapping.record_error("typo.event", "boom", owner="s-0", at_ms=1000000)
    mapping.pick_for_event("turn.completed", owner="s-0", now=1000.0)
    for i in range(1, K):
        mapping.pick_for_event("tool.exploring", owner="s-%d" % i, now=1000.0)
    mapping.pick_for_event("tool.exploring", owner="trigger", now=1000.0)
    r = next(r for r in mapping.evicted_owner_log() if r.owner == "s-0")
    assert r.last_reason == "ok"          # 旧版只看得到这个
    assert dict(r.reason_counts)["error:boom"] == 1
    assert dict(r.reason_counts)["ok"] == 2
    assert sum(n for _, n in r.reason_counts) == r.dropped
    assert list(r.reason_counts) == sorted(r.reason_counts)
    assert not hasattr(r, "text") and not hasattr(r, "entry_id")
    assert mapping.audit().ok is True
    mapping.reset_runtime_counters(include_dispatch_log=True)


def t_d6_owner_limit_wording():
    src = (REPO / "tuan_cli/ui/slogans/mapping.py").read_text(encoding="utf-8")
    assert "OWNER_LIMIT = 64" in src
    assert "≤ ``OWNER_LIMIT`` 码点零改动" in src
    assert mapping.OWNER_LIMIT == 64
    assert mapping.norm_owner("a" * 64) == "a" * 64
    assert mapping.norm_owner("a" * 65).startswith("owner:")
    raw = "session-" + "x" * 80
    mapping.reset_runtime_counters(include_dispatch_log=True)
    d = mapping.pick_for_event("tool.exploring", owner=raw)
    assert d.owner == mapping.norm_owner(raw)
    assert len(mapping.dispatch_log(raw)) == 1
    assert mapping.norm_owner(d.owner) == d.owner
    mapping.reset_runtime_counters(include_dispatch_log=True)


def t_d6_full_health():
    mapping.reset_runtime_counters(include_dispatch_log=True)
    r = mapping.audit()
    assert r.ok and r.index_consistent
    st = mapping.index_stats()
    assert st["by_id"] == st["by_text"] == st["by_clean"] == 1695
    assert st["index_misses"] == 0 and st["unresolved_misses"] == 0
    for lang in L.LANGUAGES:
        for ev in mapping.EVENT_BINDINGS:
            d = mapping.pick_for_event(ev, lang=lang, owner="final", now=1000.0)
            assert d.reason == "ok" and d.entry_id, (ev, lang)
    assert mapping.audit().ok is True
    mapping.reset_runtime_counters(include_dispatch_log=True)

# ---------------------------------------------------------------- 深度轮 7


def t_d7_esc_plus_sequence():
    clean = (REPO / "tuan_cli/ui/slogans/_clean.py").read_text(encoding="utf-8")
    assert r"\x1b+\]" in clean and r"\x1b+\[" in clean
    from tuan_cli.ui.slogans import _clean as C
    cases = {
        "\x1b\x1b]8;;https://evil.example\x07OK": "OK",
        "\x1b\x1b\x1b]8;;evil\x07END": "END",
        "\x1b\x1b[31mRED": "RED",
        "\x1b\x1b[?25lHIDE": "HIDE",
        "\x1b\x1b]0;title\x07TAIL": "TAIL",
    }
    for raw, expected in cases.items():
        assert C.sanitize_log_field(raw) == expected, repr(raw)
        assert C.sanitize_verb(raw) == expected, repr(raw)
    # 单 ESC 引导行为不变
    assert C.sanitize_log_field("\x1b]8;;evil\x07OK") == "OK"
    assert C.sanitize_verb("\x1b[31mRED\x1b[0m") == "RED"
    assert C.sanitize_log_field("\x1b\x1b[31m") == ""
    assert C.sanitize_log_field("\x1b" * 900 + "END") == "END"
    assert C.sanitize_log_field("abc\x1b") == "abc"
    # 单个 ESC 的 ECMA-48 歧义仍未改
    out = C.sanitize_log_field("\x1bEND")
    assert "\x1b" not in out and out in ("END", "ND")


def t_d7_clean_is_idempotent_after_regex_change():
    from tuan_cli.ui.slogans import _clean as C
    for raw in ("\x1b\x1b]8;;evil\x07OK", "\x1b\x1b[31mRED",
                "\x1b]8;;evil\x07OK", "\x1b[31mRED\x1b[0m",
                "\x00" * 1000 + "OK", "正常文案", "x" * 5000 + "\u202e"):
        once = C.sanitize_log_field(raw)
        assert C.sanitize_log_field(once) == once, repr(raw)[:30]
        assert "\x1b" not in once
    assert C.sanitize_verb("正常文案 ✓") == "正常文案 ✓"
    assert len(C.sanitize_log_field("a" * 5000)) == 121
    for bad in (None, float("nan"), float("inf"), "5", True, -1):
        assert C.sanitize_log_field("abc", bad) == "abc", bad


def t_d7_clock_coercion():
    src = (REPO / "tuan_cli/ui/slogans/mapping.py").read_text(encoding="utf-8")
    assert "def _coerce_ms(" in src
    assert "import math" in src
    assert "_MAX_NOW_S = 1e12" in src and "_MAX_AT_MS = 1e15" in src
    assert mapping._coerce_ms(1000.0, is_seconds=True) == 1000000
    assert mapping._coerce_ms(1000, is_seconds=False) == 1000
    assert mapping._coerce_ms(0, is_seconds=True) == 0
    for bad in (float("nan"), float("inf"), -float("inf"), "1000",
                None, True, False, -1, 1e300):
        assert mapping._coerce_ms(bad, is_seconds=True) is None, bad
    mapping.reset_runtime_counters(include_dispatch_log=True)
    for bad in (float("nan"), float("inf"), "1000", True, -1, 1e300):
        d = mapping.pick_for_event("tool.exploring", now=bad, owner="x")
        assert isinstance(d.at_ms, int) and 0 < d.at_ms < 10 ** 15, bad
        e = mapping.record_error("e", "k", at_ms=bad, owner="x")
        assert isinstance(e.at_ms, int) and e.at_ms > 0, bad
    mapping.reset_runtime_counters(include_dispatch_log=True)


def t_d7_legal_zero_not_swallowed():
    """A′: 本轮修 B 时自己引入、又被实测抓回的缺陷。"""
    src = (REPO / "tuan_cli/ui/slogans/mapping.py").read_text(encoding="utf-8")
    assert "at = _fallback_ms() if ms is None else ms" in src
    assert "stamp = _fallback_ms() if ms is None else ms" in src
    assert mapping.pick_for_event("tool.exploring", now=0).at_ms == 0
    assert mapping.pick_for_event("tool.exploring", now=1).at_ms == 1000
    assert mapping.pick_for_event("tool.exploring", now=1000.0).at_ms == 1000000
    assert mapping.record_error("e", "k", at_ms=0).at_ms == 0
    mapping.reset_runtime_counters(include_dispatch_log=True)
    K = mapping._MAX_OWNERS
    for i in range(K + 1):
        mapping.pick_for_event("tool.exploring", owner="s-%d" % i, now=0)
    assert mapping.evicted_owner_log()[-1].at_ms == 0
    mapping.reset_runtime_counters(include_dispatch_log=True)


def t_d7_bounded_owner_digest():
    src = (REPO / "tuan_cli/ui/slogans/mapping.py").read_text(encoding="utf-8")
    assert "OWNER_SCAN_CAP = 4096" in src
    assert "raw[-2048:]" in src
    assert mapping.OWNER_SCAN_CAP == 4096
    a = mapping.norm_owner("x" * 100000 + "A")
    b = mapping.norm_owner("x" * 100000 + "B")
    assert a != b and a.startswith("owner:") and len(a) == 22
    assert mapping.norm_owner(a) == a and mapping.norm_owner(b) == b
    raw = "o" * (2 << 20)
    n = mapping.norm_owner(raw)
    mapping.reset_runtime_counters(include_dispatch_log=True)
    d = mapping.pick_for_event("tool.exploring", owner=raw)
    assert d.owner == n and len(mapping.dispatch_log(raw)) == 1
    assert mapping.norm_owner("s-0") == "s-0"
    assert mapping.norm_owner("a" * 64) == "a" * 64
    assert mapping.norm_owner("a" * 65).startswith("owner:")
    mapping.reset_runtime_counters(include_dispatch_log=True)


def t_d7_cumulative_eviction_evidence():
    src = (REPO / "tuan_cli/ui/slogans/mapping.py").read_text(encoding="utf-8")
    assert "_EVICT_TOTAL = 0" in src and "def evicted_total(" in src
    assert "evicted_total" in src
    mapping.reset_runtime_counters(include_dispatch_log=True)
    K = mapping._MAX_OWNERS
    for i in range(K + mapping._EVICT_CAP + 50):
        mapping.pick_for_event("tool.exploring", owner="s-%d" % i, now=1000.0)
    st = mapping.dispatch_log_stats()
    assert st["evicted_recent"] == mapping._EVICT_CAP
    assert st["evicted_total"] > st["evicted_recent"]
    assert mapping.evicted_total() == st["evicted_total"]
    assert len(mapping.evicted_owner_log()) == mapping._EVICT_CAP
    assert mapping.audit().ok is True
    assert mapping.audit().as_dict()["dispatch_stats"]["evicted_total"] >= 1
    # 只有全清才归零
    mapping.reset_runtime_counters()
    assert mapping.evicted_total() >= 1
    mapping.reset_dispatch_log("one-owner")
    assert mapping.evicted_total() >= 1
    mapping.reset_dispatch_log()
    assert mapping.evicted_total() == 0


def t_d7_measured_false_candidates_are_locked():
    """C / C2 / E / G 实测不成立、本轮未改。"""
    from tuan_cli.ui.slogans import _clean as C
    for raw in ("正常文案", "a" + "\u0301" * 10, "❤" + "\ufe0f" * 20,
                "\u202e\u200b" * 20 + "OK", "\u200b\x1b\u2066" * 20 + "TAIL",
                "\u200b" * 20 + "OK"):
        assert C.sanitize_log_field(raw), repr(raw)
    assert C.sanitize_log_field("\u0301" * 3 + "OK") == "OK"
    assert C.sanitize_log_field("\u034f" * 5 + "OK") == "OK"
    assert C.sanitize_log_field("\u200d" * 3 + "OK") == "OK"
    a, b = mapping.norm_owner("s\ud800A"), mapping.norm_owner("s\ud800B")
    assert a != b and mapping.norm_owner(a) == a
    mapping.reset_runtime_counters(include_dispatch_log=True)
    d = mapping.record_error("ev", "\x1b]8;;https://evil\x07\u202eBOOM",
                             owner="x", at_ms=1000)
    assert d.reason == "error:BOOM"
    assert "\x1b" not in d.reason and "\u202e" not in d.reason
    mapping.reset_runtime_counters(include_dispatch_log=True)


def t_d7_full_health():
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

# ---------------------------------------------------------------- 深度轮 8


def t_d8_bucket_trim_evidence():
    src = (REPO / "tuan_cli/ui/slogans/mapping.py").read_text(encoding="utf-8")
    assert "_DECISIONS_TOTAL = 0" in src
    assert "_TRIMMED_BY_OWNER" in src
    assert "def bucket_trim_stats(" in src
    assert "trimmed_reason_counts" in src
    mapping.reset_runtime_counters(include_dispatch_log=True)
    mapping.pick_for_event("tool.exploring", owner="s0")
    mapping.record_error("typo.event", "boom", owner="s0", at_ms=1000)
    for i in range(mapping._DISPATCH_CAP + 20):
        mapping.pick_for_event("tool.exploring", owner="s0", now=1000.0 + i)
    rows = mapping.dispatch_log("s0")
    assert len(rows) == mapping._DISPATCH_CAP
    assert not any("error:boom" in r.reason for r in rows)
    st = mapping.bucket_trim_stats()
    assert st["trimmed_decisions"] >= 1 and st["bucket_trims"] >= 1
    assert dict(st["reason_counts"]).get("error:boom") == 1
    assert list(st["reason_counts"]) == sorted(st["reason_counts"])
    ds = mapping.dispatch_log_stats()
    assert ds["evicted_recent"] == 0 and ds["evicted_total"] == 0
    assert ds["decisions_total"] > ds["decisions"]
    assert ds["bucket_trims"] >= 1 and ds["trimmed_decisions"] >= 1
    assert mapping.audit().ok is True
    assert mapping.audit().as_dict()["dispatch_stats"]["trimmed_decisions"] >= 1


def t_d8_trim_summary_travels_with_eviction():
    mapping.reset_runtime_counters(include_dispatch_log=True)
    mapping.pick_for_event("tool.exploring", owner="s0")
    mapping.record_error("typo.event", "boom", owner="s0", at_ms=1000)
    for i in range(mapping._DISPATCH_CAP + 20):
        mapping.pick_for_event("tool.exploring", owner="s0", now=1000.0 + i)
    K = mapping._MAX_OWNERS
    for i in range(1, K):
        mapping.pick_for_event("tool.exploring", owner="s-%d" % i, now=1000.0)
    mapping.pick_for_event("tool.exploring", owner="trigger", now=1000.0)
    r = next(x for x in mapping.evicted_owner_log() if x.owner == "s0")
    assert r.trimmed_dropped >= 1
    assert dict(r.trimmed_reason_counts).get("error:boom") == 1
    assert r.reason_counts == (("ok", mapping._DISPATCH_CAP),)
    assert r.last_reason == "ok"
    assert not hasattr(r, "text") and not hasattr(r, "entry_id")


def t_d8_release_and_reset_semantics():
    mapping.reset_runtime_counters(include_dispatch_log=True)
    mapping.pick_for_event("tool.exploring", owner="s0")
    mapping.record_error("typo.event", "boom", owner="s0", at_ms=1000)
    for i in range(mapping._DISPATCH_CAP + 20):
        mapping.pick_for_event("tool.exploring", owner="s0", now=1000.0 + i)
    before = mapping.bucket_trim_stats()["trimmed_decisions"]
    mapping.release_owner("s0")
    assert mapping.bucket_trim_stats()["trimmed_decisions"] == before
    assert mapping._TRIMMED_BY_OWNER.get("s0") is None
    mapping.reset_runtime_counters()
    assert mapping.bucket_trim_stats()["trimmed_decisions"] == before
    mapping.reset_dispatch_log("s0")
    assert mapping.bucket_trim_stats()["trimmed_decisions"] == before
    mapping.reset_dispatch_log()
    st = mapping.bucket_trim_stats()
    assert st["trimmed_decisions"] == 0 and st["bucket_trims"] == 0
    assert st["reason_counts"] == ()
    ds = mapping.dispatch_log_stats()
    assert ds["decisions_total"] == 0 and ds["bucket_trims"] == 0
    assert ds["trimmed_decisions"] == 0 and ds["evicted_total"] == 0


def t_d8_reason_cap_is_bounded():
    """C′: 本轮自引入又抓回的 off-by-one。"""
    mapping.reset_runtime_counters(include_dispatch_log=True)
    for i in range(200):
        mapping.record_error("ev", "k%03d" % i, owner="x", at_ms=1000)
    for i in range(mapping._DISPATCH_CAP + 10):
        mapping.pick_for_event("tool.exploring", owner="x", now=1000.0)
    rc = mapping.bucket_trim_stats()["reason_counts"]
    assert len(rc) <= mapping._TRIMMED_REASON_CAP + 1
    assert sum(1 for k, _ in rc if k != "<other>") <= mapping._TRIMMED_REASON_CAP
    assert mapping.audit().ok is True
    mapping.reset_runtime_counters(include_dispatch_log=True)


def t_d8_unterminated_osc_is_unchanged_by_choice():
    """A: 实测成立但判定「不该修」，锁住 ECMA-48 规范行为。"""
    clean = (REPO / "tuan_cli/ui/slogans/_clean.py").read_text(encoding="utf-8")
    # 净化层本轮零改动：终止符仍是可选的
    assert r"\x1b+\][^\x07\x1b]*(?:\x07|\x1b\\)?" in clean
    assert "_OSC_UNTERMINATED_RE" not in clean
    from tuan_cli.ui.slogans import _clean as C
    assert C.sanitize_log_field("\x1b]8;;https://evil.example" + "OK") == ""
    assert C.sanitize_log_field("\x1b]0;title" + "TAIL") == ""
    assert C.sanitize_verb("\x1b]8;;u" + "OK") == ""
    assert C.sanitize_log_field("\x1b]8;;u\x07OK") == "OK"
    assert C.sanitize_verb("\x1b]8;;u\x1b\\OK") == "OK"
    # 两个出口共用同一净化核心
    from tuan_cli.tui import runtime_slogans as R
    assert R.sanitize_verb is C.sanitize_verb


def t_d8_attempted_osc_fix_would_leak_parameters():
    """把「不该修」的理由变成可执行证据。"""
    import re
    import unicodedata
    from tuan_cli.ui.slogans import _clean as C
    term = re.compile(r"\x1b+\][^\x07\x1b]*(?:\x07|\x1b\\)")
    unterminated = re.compile(r"\x1b+\][^\x07\x1b]{0,4096}")
    raw = "\x1b]8;;" + "A" * 5000 + "END"
    s = unterminated.sub("", term.sub("", raw))
    assert len(s) >= 900 and "END" in s
    drop = frozenset({"Cc", "Cf", "Cs", "Co", "Cn"})
    kept = "".join(ch for ch in s
                   if unicodedata.category(ch) not in drop
                   and not C._is_variation_selector(ch))
    assert len(kept) >= 900                  # 参数残留会进日志
    assert C.sanitize_log_field(raw) == ""  # 当前实现整段删
    truncated = kept[:C.LOG_FIELD_LIMIT].rstrip() + "…"
    assert "END" not in truncated          # 修了也看不到尾部


def t_d8_zwj_registry_and_known_cost():
    """B: 词条库零 ZWJ，修它收益为零、风险为正。"""
    zwj = vs = esc = 0
    for e in mapping.registry():
        text = getattr(e, "text", "") or ""
        zwj += "\u200d" in text
        vs += any(0xFE00 <= ord(c) <= 0xFE0F for c in text)
        esc += "\x1b" in text
    assert (zwj, vs, esc) == (0, 0, 0)
    assert len(list(mapping.registry())) == 1695
    from tuan_cli.ui.slogans import _clean as C
    assert C.sanitize_verb("👩\u200d💻") == "👩💻"
    assert C.sanitize_verb("👨\u200d👩\u200d👧") == "👨👩👧"
    assert C.sanitize_log_field("\u200d" * 3 + "OK") == "OK"
    assert "\u202e" not in C.sanitize_log_field("\u202eRLO\u200dOK")
    assert "\u2066" not in C.sanitize_log_field("\u2066ISO\u200dOK")
    assert C.sanitize_log_field("\u200bZWSP\u200dOK").startswith("ZWSP")


def t_d8_other_measured_candidates_are_locked():
    from tuan_cli.ui.slogans import _clean as C
    # D: 淘汰痕 reason_counts 已净化
    mapping.reset_runtime_counters(include_dispatch_log=True)
    K = mapping._MAX_OWNERS
    mapping.record_error("ev", "\x1b]8;;x\x07\u202eBAD", owner="s-0",
                         at_ms=1000)
    for i in range(1, K):
        mapping.pick_for_event("tool.exploring", owner="s-%d" % i)
    mapping.pick_for_event("tool.exploring", owner="trigger")
    r = next(x for x in mapping.evicted_owner_log() if x.owner == "s-0")
    blob = repr(r.reason_counts)
    assert "\x1b" not in blob and "\u202e" not in blob
    # E: _SCAN_CAP 卡点是 d6 已记录边界
    assert C._SCAN_CAP == 65536
    assert C.sanitize_log_field("\x00" * 65530 + "\u0301" * 3 + "OK") == "OK"
    assert C.sanitize_log_field("\x00" * 65533 + "\u0301" * 3 + "OK") == ""
    assert C.sanitize_log_field("\x00" * 70000 + "OK") == ""
    # F: 列宽截断是设计
    assert C.sanitize_verb("\x00" * 1000 + "OK") == "OK"
    assert len(C.sanitize_verb("a" * 500 + "END")) <= C._MAX_VERB_CHARS
    # 合法文本不误杀
    for raw in ("正常文案", "a" + "\u0301" * 10, "❤" + "\ufe0f" * 20,
                "\u202e\u200b" * 20 + "OK"):
        assert C.sanitize_log_field(raw), repr(raw)
    mapping.reset_runtime_counters(include_dispatch_log=True)


def t_d8_full_health():
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

# ---------------------------------------------------------------- 深度轮 9


def t_d9_event_type_guard():
    src = (REPO / "tuan_cli/ui/slogans/mapping.py").read_text(encoding="utf-8")
    assert "if not isinstance(event, str):" in src
    assert src.index("if not isinstance(event, str)") < src.index(
        "if event in SECURITY_EVENTS")
    for bad in (None, 123, True, b"x", ["a"], {"a": 1}, 1.5, ("t",)):
        try:
            mapping.pick_for_event(bad, owner="t")
            raise AssertionError("应抛 UnboundSloganEvent: %r" % (bad,))
        except mapping.UnboundSloganEvent as e:
            assert "<invalid-event>" in str(e), bad
            assert "\x1b" not in str(e) and "\u202e" not in str(e)
    # 合法事件行为不变
    mapping.reset_runtime_counters(include_dispatch_log=True)
    for ev in mapping.EVENT_BINDINGS:
        d = mapping.pick_for_event(ev, owner="legal", now=1000.0)
        assert d.reason in ("ok", "security-notice"), ev
    assert mapping.audit().ok is True
    mapping.reset_runtime_counters(include_dispatch_log=True)


def t_d9_invalid_owner_isolation():
    src = (REPO / "tuan_cli/ui/slogans/mapping.py").read_text(encoding="utf-8")
    assert '_INVALID_OWNER_KEY = "owner:invalid"' in src
    assert "def _coerce_owner(" in src and "def _note_invalid_owner(" in src
    assert "owner = _coerce_owner(owner)" in src
    dirty = [123, True, b"bytes", ["a"], {"x": 1}, 1.5, 0, False,
             0.0, [], {}, ()]
    mapping.reset_runtime_counters(include_dispatch_log=True)
    mapping.pick_for_event("tool.exploring", owner="")
    for bad in dirty:
        d = mapping.pick_for_event("tool.exploring", owner=bad)
        assert d.owner == mapping._INVALID_OWNER_KEY, bad
    assert len(mapping.dispatch_log("")) == 1
    assert len(mapping.dispatch_log(mapping._INVALID_OWNER_KEY)) == len(dirty)
    st = mapping.dispatch_log_stats()
    assert st["owners"] == 2
    assert st["invalid_owner_calls"] == len(dirty)
    assert sum(v for _, v in st["invalid_owner_types"]) == len(dirty)
    assert mapping.norm_owner(mapping._INVALID_OWNER_KEY) == mapping._INVALID_OWNER_KEY
    assert mapping.norm_owner(mapping.norm_owner(123)) == mapping._INVALID_OWNER_KEY
    assert mapping.audit().as_dict()["dispatch_stats"]["invalid_owner_calls"] == len(dirty)
    assert mapping.audit().ok is True


def t_d9_counter_counts_entries_not_queries():
    mapping.reset_runtime_counters(include_dispatch_log=True)
    d = mapping.pick_for_event("tool.exploring", owner=999)
    assert mapping.dispatch_log_stats()["invalid_owner_calls"] == 1
    for _ in range(20):
        mapping.dispatch_log(999)
        mapping.dispatch_log(d.owner)
        mapping.dispatch_log(None)
        mapping.dispatch_log_stats()
    assert mapping.dispatch_log_stats()["invalid_owner_calls"] == 1
    assert len(mapping.dispatch_log(d.owner)) == 1


def t_d9_type_distribution_is_desensitized_and_bounded():
    mapping.reset_runtime_counters(include_dispatch_log=True)
    cls = type("Evil", (), {})
    cls.__name__ = "\x1b]8;;x\x07\u202e" + "A" * 500
    mapping.pick_for_event("tool.exploring", owner=cls())
    types = mapping.dispatch_log_stats()["invalid_owner_types"]
    assert len(types) == 1 and len(types[0][0]) <= 33
    assert "\x1b" not in repr(types) and "\u202e" not in repr(types)
    mapping.reset_runtime_counters(include_dispatch_log=True)
    for i in range(60):
        c = type("T%02d" % i, (), {})
        mapping.pick_for_event("tool.exploring", owner=c())
    types = mapping.dispatch_log_stats()["invalid_owner_types"]
    assert sum(1 for k, _ in types if k != "<other>") <= mapping._INVALID_OWNER_TYPE_CAP
    assert len(types) <= mapping._INVALID_OWNER_TYPE_CAP + 1
    assert any(k == "<other>" for k, _ in types)
    assert mapping.dispatch_log_stats()["invalid_owner_calls"] == 60
    mapping.reset_runtime_counters(include_dispatch_log=True)


def t_d9_none_and_full_snapshot_contracts_unchanged():
    """不修的两个既有契约。"""
    mapping.reset_runtime_counters(include_dispatch_log=True)
    mapping.pick_for_event("tool.exploring", owner=None)
    mapping.pick_for_event("tool.exploring", owner="")
    mapping.pick_for_event("tool.exploring", owner="a")
    mapping.pick_for_event("tool.exploring", owner=123)
    assert mapping.dispatch_log_stats()["owners"] == 3
    assert mapping.dispatch_log_stats()["invalid_owner_calls"] == 1
    assert len(mapping.dispatch_log("")) == 2       # None + ''
    assert len(mapping.dispatch_log(None)) == 4     # 全量
    assert len(mapping.dispatch_log(123)) == 1      # 脏值桶


def t_d9_reset_semantics_and_record_error():
    mapping.reset_runtime_counters(include_dispatch_log=True)
    d = mapping.record_error("e", "k", owner={"bad": 1})
    assert d.owner == mapping._INVALID_OWNER_KEY
    assert mapping.dispatch_log_stats()["invalid_owner_calls"] == 1
    mapping.reset_runtime_counters()
    assert mapping.dispatch_log_stats()["invalid_owner_calls"] == 1
    mapping.reset_dispatch_log("one")
    assert mapping.dispatch_log_stats()["invalid_owner_calls"] == 1
    mapping.reset_dispatch_log()
    st = mapping.dispatch_log_stats()
    assert st["invalid_owner_calls"] == 0 and st["invalid_owner_types"] == ()


def t_d9_measured_but_not_changed():
    """四个候选判定「不该修」，锁住当前行为。"""
    from tuan_cli.ui.slogans import _clean as C
    # lang 非 str 静默回落默认语种
    mapping.reset_runtime_counters(include_dispatch_log=True)
    for bad in (123, True, b"x", ["a"], 1.5):
        d = mapping.pick_for_event("tool.exploring", lang=bad, owner="t")
        assert d.reason == "ok" and d.entry_id
    # record_error 的 event / kind 已净化
    for bad in (None, 123, True, b"x", ["a"], 1.5):
        d = mapping.record_error(bad, bad, owner="t")
        assert d.reason.startswith("error:")
        assert "\x1b" not in d.event and "\u202e" not in d.event
    # sanitize_log_field / sanitize_verb 非 str 返回空串
    for bad in (None, 123, True, b"x", ["a"], 1.5):
        assert C.sanitize_log_field(bad) == ""
    assert C.sanitize_verb(123) == ""
    assert mapping.audit().ok is True
    mapping.reset_runtime_counters(include_dispatch_log=True)


def t_d9_full_health():
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
