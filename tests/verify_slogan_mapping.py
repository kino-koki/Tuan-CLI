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
    assert "mapping.release_owner(self._slogan_owner)" in tui
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
    assert "self._slogan_sealed = mapping.dispatch_log(self._slogan_owner)" in tui
    assert "mapping.release_owner(self._slogan_owner)" in tui
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
    assert "_dispatch_log.move_to_end(owner)" in src
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
