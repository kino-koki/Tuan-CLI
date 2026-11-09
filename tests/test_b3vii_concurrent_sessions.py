"""B3 续轮 VII：C4 最后一角 —— **并发**多会话的派发归属隔离。

上一轮（VI）把模块级入口改成「构造时冻结 hooks + 实例级绑定」，并如实
留了一句边界：``_global_alerter`` / ``_notify_rc`` 仍是**进程级单例**，
两个会话**并发并存**时共用同一实例（后者复用前者的绑定）。本轮收尾，
一点广度没扩。

=====  =====================================================================
编号   修复前实测
=====  =====================================================================
O1     ``bind_session_hooks(B, owner="B")`` **无条件回填**单例的
       ``hooks``；A 会话订阅的 ``SecurityAlerter`` 在 B 绑定后告警 ->
       **A 零触发、B 代收**（实测 A=0 / B=1）。
O2     模块级 ``remote_control.notify()`` 同源：C 会话第一次通知到 C，
       D 会话 bind 之后 C 的第二次通知落到 **D**（实测 C=1 / D=1）。
O4     ``contextvars.ContextVar`` **不跨** ``threading.Thread``
       （主线程 "A" / 子线程 None，实测）。所以后台通知线程不能靠
       contextvar 拿 owner，必须由调用方烘进数据。
O3     ``get_alerter()`` 是进程级单例、``SecurityAlerter`` 持有
       ``AlertLogger(home)`` 与 bus 订阅、``RemoteControl`` 持有端口与
       会话文件 -> **判定不该修**：改成按 owner 多实例会引入文件竞争、
       重复订阅与端口冲突。回归明确锁住 ``x is y``。
O5     修 O1/O2 时**自己引入**的新风险（A'）：``owner=`` 改成动态查表
       后，「owner 拼错/未注册」会让决策类静默返回空决策放行。已改为
       fail-closed ``owner_not_registered``，通知类仍严格 no-op + 留痕。
=====  =====================================================================

**修复（如实，不夸大）**

1. ``hooks/triggers.py``：新增 ``ContextVar`` 会话 owner
   （``current_session_owner`` / ``set_session_owner`` /
   ``reset_session_owner``）、``hooks_for_owner``、
   ``owner_miss_stats``（有界、``<other>`` 归并、纯诊断）。
   ``HookTrigger(owner=...)`` 从「构造时查一次并冻结值」改成
   **冻结 owner、派发时按 owner 分桶查 registry**。查表是动态的，
   但 registry **按 owner 分桶而不是单槽**，所以 ``bind(B)`` 不会改
   A 桶 —— 既支持会话内热替换，又不会随别的会话漂移。这正是 VI 的
   单槽 provider 做不到的。
   ``owner`` 查不到**不回落** default（避免笔误串台），决策类另加
   fail-closed；无 ``owner`` 的构造仍冻结值，VI 的 C4-A 修复不破。
2. ``core/security_alert.py``：``AlertRecord`` 加
   ``owner: str = ""``（**进程内路由字段，不进 to_dict()**，既有审计
   格式零变化）；``alert()`` 在**调用线程**捕获 owner 烘进记录；
   后台线程 ``_notify_safely`` 用 ``record.owner`` 查分桶，绕开 O4。
3. ``core/remote_control.py``：``notify()`` 加可选关键字 ``owner``；
   优先级 **显式 hooks > 本会话 owner 分桶 > 实例冻结 hooks**。
   未注册 owner 时只沿用实例既有绑定，行为零退化。
4. ``runtime/acp/bridge.py``：``ask_user`` 支持已注册 owner 分桶；
   未设置时沿用 ``self.hooks``（一个 bridge 可服务多个 session_id，
   **owner 与 session_id 的映射由上层负责，本轮不自动派生**）。
5. ``app.py``：会话启动时 ``set_session_owner(_session_owner)``，
   在 ``set_default_hooks_provider`` / ``bind_session_hooks`` 之后。

**三条上轮断言同步（全部改强，不是放宽）**：
``test_module_level_notify_is_now_instance_bound`` 增加 owner 分桶、
``record.owner``、``AlertRecord.owner`` 与 ``current_session_owner``
断言。VI 的「冻结未破」「显式 hooks 优先」「无参消费点为 0」全部保留。

**矩阵一个状态没动**：``ahead 10 / aligned 46 / partial 9 / gap 26 /
not_applicable 8``；``fully_superior=false``；``b_waves_done=["B1"]``。
两个 B3 条目仍 ``STATUS_GAP``，``catalog.py`` 零改动 —— 本轮修的是
「并发会话的派发归属」，不是功能覆盖面，不靠改口径凑数。

**如实边界**：单例对象身份**仍是进程级**（不创建多实例，避免资源
竞争）；``bind_session_hooks`` 的**单槽回填仍在**（``al.hooks`` 会被
最后一次 bind 覆盖），只是有 owner 上下文的派发走分桶表、不再读它；
**未设置 owner 且未显式传 hooks** 的路径仍沿用最后一次 bind 的绑定
（既有行为，不宣称「完全多会话隔离」）。标语引擎 / 净化层 /
``mapping.py`` / ``tui.py`` / ``runtime_slogans.py`` 逐字节未改。
"""
from __future__ import annotations

import contextvars
import inspect
import tempfile
import threading
import time
from pathlib import Path

import pytest

from tuan_cli.hooks import (
    HookTrigger, set_default_hooks_provider, provider_diagnostics,
    bind_session_hooks, register_session, unregister_session,
    resolve_session, session_registry_diagnostics,
    current_session_owner, set_session_owner, reset_session_owner,
    owner_miss_stats, hooks_for_owner,
)
from tuan_cli.hooks.manager import HookDecision
from tuan_cli.core import security_alert as SA
from tuan_cli.core import remote_control as RC


class Rec:
    """最小 in-process hook。"""

    enabled = True

    def __init__(self, name="r"):
        self.name = name
        self.fired = []

    def run_notify(self, event, payload):
        self.fired.append((event, dict(payload)))

    def run_decision(self, event, tool_name="", payload=None):
        self.fired.append((event, "DECISION"))
        return HookDecision()


@pytest.fixture(autouse=True)
def _reset():
    from tuan_cli.hooks import triggers as _T

    def clean():
        SA._global_alerter = None
        RC._notify_rc = None
        for o in list(session_registry_diagnostics()["owners"]):
            unregister_session(o)
        _T._OWNER_MISSES.clear()
        set_default_hooks_provider(None)

    clean()
    yield
    clean()


# ================================================== O1 后台线程并发
class TestConcurrentAlerts:
    def _alert(self, alerter):
        # 真实路径：alert() 在调用线程烘 owner，_send_notification 起后台线程
        alerter.alert("high", "T", "M")
        time.sleep(0.15)

    def test_A_alert_is_not_stolen_by_B_bind(self):
        """O1 主缺陷：A 订阅、B 绑定后，A 的告警仍派到 A。"""
        a, b = Rec("A"), Rec("B")
        set_default_hooks_provider(lambda: a, owner="session-A")
        register_session("session-A", a)
        tok = set_session_owner("session-A")
        try:
            al = SA.get_alerter(
                home=Path(tempfile.mkdtemp(prefix="o1fix_")))

            def b_session():
                set_session_owner("session-B")
                bind_session_hooks(b, owner="session-B")

            t = threading.Thread(target=b_session)
            t.start()
            t.join()
            self._alert(al)
            assert len(a.fired) == 1 and b.fired == []
        finally:
            reset_session_owner(tok)

    def test_single_slot_backfill_still_exists_but_is_not_used(self):
        """如实边界：单槽回填仍在，但有 owner 的派发不读它。"""
        a, b = Rec("A"), Rec("B")
        set_default_hooks_provider(lambda: a, owner="session-A")
        register_session("session-A", a)
        tok = set_session_owner("session-A")
        try:
            al = SA.get_alerter(
                home=Path(tempfile.mkdtemp(prefix="o1b_")))
            set_session_owner("session-B")
            bind_session_hooks(b, owner="session-B")
            assert al.hooks is b                 # 单槽仍被覆盖（不粉饰）
            set_session_owner("session-A")       # 回到 A 上下文
            self._alert(al)
            assert len(a.fired) == 1 and b.fired == []
        finally:
            reset_session_owner(tok)

    def test_no_owner_falls_back_to_instance_hooks(self):
        """未设置 owner 时沿用既有实例绑定，行为零退化。"""
        r = Rec("R")
        al = SA.SecurityAlerter(
            home=Path(tempfile.mkdtemp(prefix="nowner_")),
            enable_desktop=False, hooks=r)
        al._notify_safely(
            SA.AlertRecord(title="T", message="M", severity="high"))
        assert len(r.fired) == 1

    def test_unregistered_owner_does_not_degrade_to_global(self):
        """owner 设了但没注册 -> 回落实例绑定，不回落单槽 default。"""
        r, other = Rec("R"), Rec("OTHER")
        al = SA.SecurityAlerter(
            home=Path(tempfile.mkdtemp(prefix="unreg_")),
            enable_desktop=False, hooks=r)
        set_default_hooks_provider(lambda: other, owner="other")
        al._notify_safely(SA.AlertRecord(
            title="T", message="M", severity="high",
            owner="never-registered"))
        assert len(r.fired) == 1 and other.fired == []


# ================================================== O2 模块级 notify
class TestConcurrentNotify:
    def test_C_notify_stays_with_C_after_D_bind(self):
        """O2 主缺陷：C 的两次通知都在 C，D 零触发。"""
        c, d = Rec("C"), Rec("D")
        set_default_hooks_provider(lambda: c, owner="session-C")
        register_session("session-C", c)
        tok = set_session_owner("session-C")
        try:
            RC.notify("c1", "b1")

            def d_session():
                set_session_owner("session-D")
                bind_session_hooks(d, owner="session-D")

            t = threading.Thread(target=d_session)
            t.start()
            t.join()
            RC.notify("c2", "b2")
            assert len(c.fired) == 2 and d.fired == []
        finally:
            reset_session_owner(tok)

    def test_explicit_hooks_wins_over_owner(self):
        """显式 hooks 优先级高于 owner 分桶（VI 回归不破）。"""
        a, b = Rec("A"), Rec("B")
        register_session("session-A", a)
        tok = set_session_owner("session-A")
        try:
            RC.notify("t", "b", hooks=b)
            assert len(b.fired) == 1 and a.fired == []
        finally:
            reset_session_owner(tok)

    def test_explicit_owner_argument(self):
        """notify(owner=...) 可跨上下文指定归属。"""
        a, b = Rec("A"), Rec("B")
        register_session("session-A", a)
        register_session("session-B", b)
        tok = set_session_owner("session-A")
        try:
            RC.notify("t", "b", owner="session-B")
            assert len(b.fired) == 1 and a.fired == []
        finally:
            reset_session_owner(tok)

    def test_signature_backward_compatible(self):
        sig = inspect.signature(RC.notify)
        assert list(sig.parameters)[:3] == ["title", "body", "kind"]
        for k in ("hooks", "owner"):
            assert sig.parameters[k].kind is inspect.Parameter.KEYWORD_ONLY
            assert sig.parameters[k].default is None

    def test_rc_none_still_dispatches(self, monkeypatch):
        """上一轮契约：无推送对象也派发 Notification，返回值不变。"""
        k = Rec("K")
        register_session("session-K", k)
        tok = set_session_owner("session-K")
        try:
            monkeypatch.setattr(RC, "_shared_rc", lambda: None)
            assert RC.notify("x", "y") is False
            assert len(k.fired) == 1
        finally:
            reset_session_owner(tok)


# ================================================== O4 contextvar
class TestOwnerContext:
    def test_set_reset_and_current(self):
        assert current_session_owner() is None
        tok = set_session_owner("sess-1")
        try:
            assert current_session_owner() == "sess-1"
        finally:
            reset_session_owner(tok)
        assert current_session_owner() is None

    def test_invalid_owner_rejected(self):
        for bad in ("", 123, None, [], True):
            with pytest.raises(ValueError):
                set_session_owner(bad)

    def test_contextvar_does_not_cross_threads(self):
        """O4 实测：新线程拿到的是 None，不是主线程的 owner。"""
        seen = []
        tok = set_session_owner("ctx-A")
        try:
            def sub():
                seen.append(current_session_owner())

            t = threading.Thread(target=sub)
            t.start()
            t.join()
            assert seen == [None]
            assert current_session_owner() == "ctx-A"
        finally:
            reset_session_owner(tok)

    def test_reset_with_foreign_token_is_no_op(self):
        """别的 Context 的 token 不得掀翻主路径。"""
        box = []

        def make():
            box.append(set_session_owner("foreign"))

        t = threading.Thread(target=make)
        t.start()
        t.join()
        reset_session_owner(box[0])          # 不应抛
        assert current_session_owner() is None

    def test_alert_record_carries_owner(self):
        """alert() 在调用线程把 owner 烘进 AlertRecord。"""
        tok = set_session_owner("sess-A")
        try:
            al = SA.SecurityAlerter(
                home=Path(tempfile.mkdtemp(prefix="rec_")),
                enable_desktop=False)
            r = al.alert("low", "T", "M")
            assert r.owner == "sess-A"
        finally:
            reset_session_owner(tok)

    def test_owner_is_not_serialized(self):
        """owner 是进程内路由字段，不进 to_dict()（既有审计格式零变化）。"""
        r = SA.AlertRecord(title="T", message="M", severity="low",
                           owner="sess-A")
        assert "owner" not in r.to_dict()

    def test_alert_record_owner_defaults_empty(self):
        assert SA.AlertRecord(title="T", severity="low").owner == ""


# ================================================== owner 动态分桶
class TestOwnerBucketLookup:
    def test_hot_replace_within_session(self):
        """冻结 owner（而非值）-> 会话内替换 hooks 立即生效。"""
        e, f = Rec("E"), Rec("F")
        register_session("hot", e)
        tr = HookTrigger(owner="hot")
        tr.config_change(source="1")
        register_session("hot", f)
        tr.config_change(source="2")
        assert len(e.fired) == 1 and len(f.fired) == 1

    def test_other_session_bind_does_not_change_my_bucket(self):
        """分桶不是单槽：bind(B) 不改 A 桶。"""
        a, b = Rec("A"), Rec("B")
        register_session("A", a)
        ta = HookTrigger(owner="A")
        register_session("B", b)
        ta.config_change(source="from-A")
        assert len(a.fired) == 1 and b.fired == []

    def test_vi_freeze_intact_for_no_arg(self):
        """VI 的 C4-A 修复不破：无参构造仍冻结值。"""
        g, h = Rec("G"), Rec("H")
        set_default_hooks_provider(lambda: g, owner="G")
        tg = HookTrigger()
        set_default_hooks_provider(lambda: h, owner="H")
        tg.config_change(source="x")
        assert len(g.fired) == 1 and h.fired == []

    def test_explicit_hooks_still_wins(self):
        a, b = Rec("A"), Rec("B")
        register_session("A", a)
        HookTrigger(b).config_change(source="x")
        assert len(b.fired) == 1 and a.fired == []

    def test_effective_never_reads_single_slot_provider(self):
        src = Path("tuan_cli/hooks/triggers.py").read_text(
            encoding="utf-8")
        body = src[src.index("    def _effective"):]
        body = body[:body.index("\n    @staticmethod")]
        assert "_DEFAULT_PROVIDER" not in body
        assert "resolve_session" in body


# ================================================== O5 fail-closed
class TestUnregisteredOwner:
    def test_decision_is_fail_closed(self):
        d = HookTrigger(owner="never-registered").worktree_create(
            name="x", path="p", branch="b")
        assert d.block is True
        assert d.failure_kind == "owner_not_registered"

    def test_notify_is_strict_noop_and_visible(self):
        before = owner_miss_stats().get("never-registered", 0)
        assert HookTrigger(owner="never-registered").config_change(
            source="x") is False
        after = owner_miss_stats().get("never-registered", 0)
        assert after == before + 1

    def test_miss_stats_is_bounded(self):
        """尾部归并 <other>，不做无界增长。"""
        for i in range(80):
            HookTrigger(owner="m-%d" % i).config_change(source="x")
        d = owner_miss_stats()
        assert len(d) <= 65
        assert "<other>" in d

    def test_hooks_for_owner(self):
        r = Rec("R")
        register_session("s", r)
        assert hooks_for_owner("s") is r
        assert hooks_for_owner(None) is None
        assert hooks_for_owner("") is None

    def test_diagnostics_exposes_owner_and_misses(self):
        d = provider_diagnostics()
        assert "current_owner" in d and "owner_misses" in d
        tok = set_session_owner("diag")
        try:
            assert provider_diagnostics()["current_owner"] == "diag"
        finally:
            reset_session_owner(tok)


# ================================================== O3 不该修
class TestSingletonBoundary:
    def test_get_alerter_is_still_process_singleton(self):
        """O3：不创建多实例（文件竞争 / 重复订阅 / 端口冲突），如实锁住。"""
        h1 = Path(tempfile.mkdtemp(prefix="h1_"))
        h2 = Path(tempfile.mkdtemp(prefix="h2_"))
        try:
            x = SA.get_alerter(home=h1)
            y = SA.get_alerter(home=h2)
            assert x is y
            assert y._home == h1
        finally:
            import shutil
            shutil.rmtree(h1, ignore_errors=True)
            shutil.rmtree(h2, ignore_errors=True)

    def test_shared_rc_is_still_one_instance(self):
        a = RC._shared_rc()
        b = RC._shared_rc()
        assert a is b

    def test_resources_that_would_conflict(self):
        src = Path("tuan_cli/core/security_alert.py").read_text(
            encoding="utf-8")
        assert "AlertLogger(self._home)" in src
        assert "subscribe_bus" in src
        src2 = Path("tuan_cli/core/remote_control.py").read_text(
            encoding="utf-8")
        assert "_find_free_port" in src2
        assert "_load_sessions" in src2


# ================================================== 接线 / 矩阵
class TestWiringAndMatrix:
    def test_app_sets_session_owner_after_bind(self):
        """**B3 续轮 VIII 同步（改强）**：contextvar 绑定由 activate_session
        内部完成并**返回可复位 token**，不再有零散的 set 调用。
        """
        src = Path("tuan_cli/app.py").read_text(encoding="utf-8")
        assert "activate_session(" in src
        assert "agent.ctx.session_handle = _handle" in src
        assert "if not _handle.active:" in src
        assert "set_session_owner(_session_owner)" not in src
        # activate_session 内部顺序：provider -> set owner -> register/bind
        tsrc = Path("tuan_cli/hooks/triggers.py").read_text(
            encoding="utf-8")
        i = tsrc.index("def activate_session(")
        body = tsrc[i:i + 1200]
        assert body.index("set_default_hooks_provider(") < body.index(
            "set_session_owner(")
        assert body.index("set_session_owner(") < body.index(
            "bind_session_hooks(")

    def test_bridge_supports_owner_without_auto_mapping(self):
        """**B3 续轮 VIII 补强**：owner 改为**显式句柄**解析（P3），
        不再在运行时依赖 contextvar；仍不按 session_id 自动派生。
        """
        src = Path("tuan_cli/runtime/acp/bridge.py").read_text(
            encoding="utf-8")
        assert "HookTrigger(owner=_o)" in src
        assert "HookTrigger(self.hooks)" in src
        assert "HookTrigger()" not in src
        assert "_o = self._resolve_owner()" in src
        assert "def _resolve_owner(" in src
        assert "agent.ctx" in src or "session_owner" in src
        assert "owner: Optional[str] = None" in src
        assert "current_session_owner()" not in src.split(
            "def ask_user")[1][:900]   # ask_user 内不再直接读 contextvar

    def test_no_arg_hooktrigger_code_consumers_still_zero(self):
        hits = []
        for p in Path("tuan_cli").rglob("*.py"):
            for n, line in enumerate(p.read_text(
                    encoding="utf-8").splitlines(), 1):
                code = line.strip()
                if code.startswith("#"):
                    continue
                if "HookTrigger()" in code:
                    hits.append((str(p), n, code))
        assert hits == [], hits

    def test_matrix_counts_unchanged(self):
        from tuan_cli.parity_claude import matrix, evidence
        assert matrix.validate() == []
        assert evidence.verify_evidence() == []
        s = matrix.summary()
        assert s["by_status"] == {
            "ahead": 10, "aligned": 46, "partial": 9,
            "gap": 26, "not_applicable": 8}
        assert s["gaps"] == 26
        assert s["fully_superior"] is False
        assert s["b_waves_done"] == ["B1"]
        assert s["superiority_criteria"]["external_adaptive_red_team"] is False

    def test_catalog_unchanged_this_round(self):
        src = Path("tuan_cli/parity_claude/catalog.py").read_text(
            encoding="utf-8")
        for key in ("hook_events_extended", "hook_updated_input_validation"):
            i = src.index('M("%s"' % key)
            assert "STATUS_GAP" in src[i:i + 400], key

    def test_previous_round_contracts_still_present(self):
        src = Path("tuan_cli/hooks/triggers.py").read_text(
            encoding="utf-8")
        assert "_REENTRY_LOCAL = threading.local()" in src
        assert "reentry_suppressed" in src
        assert "_MAX_SESSIONS = 64" in src
        assert "bind_session_hooks" in src
        # VI 的单槽回填仍在（如实边界，未偷偷删掉）
        assert "inst.hooks = hooks" in src
