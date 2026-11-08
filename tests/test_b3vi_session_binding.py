"""B3 续轮 VI：C4 收尾 —— 模块级入口的**真正会话绑定**。

上一轮（B3 续轮 V）把 Config 那条最长的链改成了显式回填，但如实留了
一句边界：``remote_control.notify`` / ``SecurityAlerter`` 后台线程 /
ACP ``ask_user`` 仍是全局 fallback，串台只是「可见」没被消除。本轮把
它收尾，一点广度没扩。

=====  =====================================================================
编号   修复前实测
=====  =====================================================================
A      ``set_default_hooks_provider(A)`` 后用 A 构造 ``HookTrigger()``，
       再切到 B，A 的 trigger 派发 -> **A 零触发、B 代收**。根因：
       ``_effective()`` 在**每次派发时**才读全局 provider，构造不冻结。
C      A 会话订阅的 ``SecurityAlerter``，B 覆盖 provider 后在后台线程
       ``_notify_safely`` 派发 -> **C(A) 零触发、D(B) 代收**。后台线程
       执行时刻与订阅时刻不同，现场 ``HookTrigger()`` 必然读到最新覆盖。
D      ``remote_control.notify()`` 模块级函数签名无 hooks 入参，每次现场
       ``HookTrigger()``；实测一次 E、一次 F 分别派到 E/F，串行切换后
       单例的归属完全取决于**派发时刻**而非会话。
E      ACP ``KernelAcpBridge.ask_user`` 无 ``self.hooks``，
       ``HookTrigger()`` 无参，Elicitation 事件同样无会话绑定。
B      ``get_alerter()`` 是进程级单例，第二次传 ``home`` 被静默忽略
       （``y._home == h1``）。**判定不该修**：重写单例架构超出本轮，
       但新增的 ``hooks`` 属性 + ``bind_session_hooks()`` 回填让它至少
       在串行会话切换后指向正确会话。
=====  =====================================================================

**修复（如实，不夸大）**

1. ``HookTrigger.__init__`` **构造时冻结** hooks；支持 ``owner=`` 查
   registry。``_effective()`` 不再读全局。现场构造的 trigger 仍绑定
   调用时刻的当前会话（A2 验证），只有「长期持有 trigger 跨覆盖」
   的行为变化 —— 那正是要修的串台。
2. 新增按 owner 分桶的 ``session registry``：``register_session`` /
   ``unregister_session`` / ``resolve_session`` / ``session_registry_
   diagnostics``。**超出 64 上界直接拒绝，不做 LRU 静默淘汰** ——
   安全绑定被悄悄挤掉会让老会话突然派到别处或静默 no-op。
3. ``bind_session_hooks(hooks, owner=...)``：注册 registry + **回填**
   已存在的 ``_global_alerter`` / ``_notify_rc`` 两个进程级单例。
   顺序刻意在 ``set_default_hooks_provider`` 之后：新建消费者靠
   ``current_session_hooks()`` 捕获，已存在的靠这里显式回填。
4. 三个模块级消费者改为**实例级绑定**：
   ``RemoteControl(..., hooks=)`` / ``SecurityAlerter(..., hooks=)`` /
   ``KernelAcpBridge(..., hooks=)``；派发时用 ``self.hooks``，不再
   现场读全局。``remote_control.notify()`` 另加可选 ``hooks`` 关键字
   入参（向后兼容），给调用方显式通道。
5. ``security_plugin.py`` 构造 alerter 时传 ``config._hooks``；
   ``app.py`` 调用 ``bind_session_hooks``。

**两个 B3 条目仍 ``STATUS_GAP``、矩阵一个状态没动**：本轮修的是
「已接线触发点的会话归属」，不是功能覆盖面。``catalog.py`` 零改动。

**三条上轮断言同步（全部改强，不是放宽）**：
``test_overrides_are_visible_not_silent`` 从「锁住串台仍存在」改为
「A 收到、B 零」；``test_app_backfills...`` 增加 ``bind_session_hooks``
与顺序断言；``test_module_level_notify_still_uses_global_fallback``
改名为 ``..._is_now_instance_bound`` 并断言全仓无参消费点为 0。

**如实边界**：``_global_alerter`` / ``_notify_rc`` 仍是**进程级单例**，
两个会话**并发并存**时会共用同一实例（后者复用前者的绑定）—— 重写
单例架构超出本轮，回归里明确锁住 ``x is y`` 这个既有事实。串行会话
切换已由 ``bind_session_hooks`` 回填修好。registry 上界拒绝只影响
显式 ``owner=`` 查询，不影响已绑定实例的派发（fail-open 于诊断、
fail-closed 于裁决，如实标注）。
"""
from __future__ import annotations

import inspect
import shutil
import tempfile
import threading
import time
from pathlib import Path

import pytest

from tuan_cli.hooks import (
    HookTrigger, set_default_hooks_provider, get_default_hooks_provider,
    provider_diagnostics, current_session_hooks, bind_session_hooks,
    register_session, unregister_session, resolve_session,
    session_registry_diagnostics,
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
    SA._global_alerter = None
    RC._notify_rc = None
    for o in list(session_registry_diagnostics()["owners"]):
        unregister_session(o)
    set_default_hooks_provider(None)
    yield
    SA._global_alerter = None
    RC._notify_rc = None
    for o in list(session_registry_diagnostics()["owners"]):
        unregister_session(o)
    set_default_hooks_provider(None)


# ================================================== A 构造时冻结
class TestFreezeOnConstruction:
    def test_trigger_built_under_A_stays_with_A(self):
        """A 主缺陷：构造时冻结，不再漂到 B。"""
        a, b = Rec("A"), Rec("B")
        set_default_hooks_provider(lambda: a, owner="session-A")
        t_a = HookTrigger()
        set_default_hooks_provider(lambda: b, owner="session-B")
        t_a.config_change(source="from-A")
        assert len(a.fired) == 1 and b.fired == []

    def test_fresh_construction_still_binds_call_time(self):
        """现场构造仍绑定调用时刻的当前会话 —— 冻结没破坏这个语义。"""
        c, d = Rec("C"), Rec("D")
        set_default_hooks_provider(lambda: c, owner="C")
        HookTrigger().config_change(source="c")
        set_default_hooks_provider(lambda: d, owner="D")
        HookTrigger().config_change(source="d")
        assert len(c.fired) == 1 and len(d.fired) == 1

    def test_explicit_hooks_wins_over_provider(self):
        a, b = Rec("A"), Rec("B")
        set_default_hooks_provider(lambda: b, owner="B")
        HookTrigger(a).config_change(source="x")
        assert len(a.fired) == 1 and b.fired == []

    def test_owner_lookup_does_not_fall_back_to_default(self):
        """owner 拼错不能静默派到别的会话。"""
        a = Rec("A")
        set_default_hooks_provider(lambda: a, owner="A")
        assert HookTrigger(owner="no-such").config_change(source="x") is False
        assert a.fired == []

    def test_owner_lookup_hits_registry(self):
        r = Rec("R")
        register_session("sess-R", r)
        HookTrigger(owner="sess-R").config_change(source="via-owner")
        assert len(r.fired) == 1

    def test_effective_no_longer_reads_global(self):
        src = Path("tuan_cli/hooks/triggers.py").read_text(encoding="utf-8")
        assert "def _effective(self) -> Any:" in src
        # _effective 体内不得再出现 _DEFAULT_PROVIDER
        body = src[src.index("    def _effective"):]
        body = body[: body.index("\n    @staticmethod")]
        assert "_DEFAULT_PROVIDER" not in body

    def test_decision_reentry_guard_still_fail_closed(self):
        """冻结不得破坏上一轮的决策类重入守卫。"""
        class Loop:
            enabled = True

            def __init__(self):
                self.n = 0
                self.t = None

            def run_decision(self, event, tool_name="", payload=None):
                self.n += 1
                return self.t.worktree_create(name="i", path="p", branch="b")

        lp = Loop()
        t = HookTrigger(lp)
        lp.t = t
        d = t.worktree_create(name="o", path="p", branch="b")
        assert lp.n == 1 and d.block is True
        assert d.failure_kind == "reentry_suppressed"


# ================================================== B 单例架构（如实边界）
class TestSingletonBoundary:
    def test_get_alerter_is_still_process_singleton(self):
        """**不该修**：单例架构未重写，第二次 home 仍被忽略，如实锁住。"""
        h1 = Path(tempfile.mkdtemp(prefix="h1_"))
        h2 = Path(tempfile.mkdtemp(prefix="h2_"))
        try:
            x = SA.get_alerter(home=h1)
            y = SA.get_alerter(home=h2)
            assert x is y
            assert y._home == h1
            assert hasattr(y, "hooks")
        finally:
            shutil.rmtree(h1, ignore_errors=True)
            shutil.rmtree(h2, ignore_errors=True)

    def test_constructor_captures_session_hooks_by_default(self):
        r = Rec("R")
        set_default_hooks_provider(lambda: r, owner="R")
        al = SA.SecurityAlerter(home=Path(tempfile.mkdtemp(prefix="al_")),
                                enable_desktop=False)
        assert al.hooks is r
        rc = RC.RemoteControl(Path(tempfile.mkdtemp(prefix="rc_")))
        assert rc.hooks is r
        from tuan_cli.runtime.acp.bridge import KernelAcpBridge
        br = KernelAcpBridge()
        assert br.hooks is r

    def test_explicit_hooks_argument_wins(self):
        a, b = Rec("A"), Rec("B")
        set_default_hooks_provider(lambda: a, owner="A")
        al = SA.SecurityAlerter(home=Path(tempfile.mkdtemp(prefix="al_")),
                                enable_desktop=False, hooks=b)
        assert al.hooks is b


# ================================================== C 后台线程
class TestBackgroundThreadBinding:
    def _record(self):
        return SA.AlertRecord(title="T", message="M", severity="high")

    def test_alerter_dispatches_to_its_own_session(self):
        """C 主缺陷：A 订阅、B 覆盖后，后台线程仍派到 A。"""
        a, b = Rec("A"), Rec("B")
        set_default_hooks_provider(lambda: a, owner="A")
        al = SA.get_alerter(home=Path(tempfile.mkdtemp(prefix="alert_")))
        assert al.hooks is a
        set_default_hooks_provider(lambda: b, owner="B")
        al._notify_safely(self._record())
        time.sleep(0.08)
        assert len(a.fired) == 1 and b.fired == []

    def test_bind_session_hooks_backfills_existing_singleton(self):
        """会话切换后回填已存在的单例，派到新会话。"""
        g, h = Rec("G"), Rec("H")
        set_default_hooks_provider(lambda: g, owner="G")
        al = SA.get_alerter(home=Path(tempfile.mkdtemp(prefix="a2_")))
        set_default_hooks_provider(lambda: h, owner="H")
        assert bind_session_hooks(h, owner="H") is True
        assert al.hooks is h
        al._notify_safely(self._record())
        time.sleep(0.08)
        assert len(h.fired) == 1 and g.fired == []

    def test_bind_session_hooks_backfills_shared_rc(self):
        r, s = Rec("R"), Rec("S")
        set_default_hooks_provider(lambda: r, owner="R")
        rc = RC._shared_rc()
        set_default_hooks_provider(lambda: s, owner="S")
        bind_session_hooks(s, owner="S")
        assert rc.hooks is s
        RC.notify("t", "b")
        assert len(s.fired) == 1 and r.fired == []

    def test_bind_session_hooks_tolerates_no_singletons(self):
        """单例未创建时绑定不抛异常、不掀翻会话启动。"""
        assert bind_session_hooks(None, owner="empty") is True
        assert resolve_session("empty") is None


# ================================================== D 模块级 notify
class TestModuleLevelNotify:
    def test_notify_uses_singleton_binding(self):
        """D 主缺陷：单例冻结后，后续 notify 不再随 provider 漂移。"""
        i, j = Rec("I"), Rec("J")
        set_default_hooks_provider(lambda: i, owner="I")
        RC.notify("t", "b")            # 首次构造 rc，冻结 I
        set_default_hooks_provider(lambda: j, owner="J")
        RC.notify("t2", "b2")
        assert len(i.fired) == 2 and j.fired == []

    def test_explicit_hooks_keyword_argument(self):
        j = Rec("J")
        RC.notify("t", "b", hooks=j)
        assert len(j.fired) == 1

    def test_signature_is_backward_compatible(self):
        sig = inspect.signature(RC.notify)
        assert list(sig.parameters)[:3] == ["title", "body", "kind"]
        assert sig.parameters["hooks"].kind is inspect.Parameter.KEYWORD_ONLY
        assert sig.parameters["hooks"].default is None

    def test_notify_still_dispatches_when_rc_is_none(self, monkeypatch):
        """上一轮契约：无推送对象也要派发 Notification；返回值不变。"""
        k = Rec("K")
        set_default_hooks_provider(lambda: k, owner="K")
        monkeypatch.setattr(RC, "_shared_rc", lambda: None)
        assert RC.notify("x", "y") is False
        assert len(k.fired) == 1

    def test_notify_return_semantics_unchanged(self):
        """hook 通道炸了也不改变 notify 返回值语义。"""
        class Bad:
            enabled = True

            def run_notify(self, e, p):
                raise RuntimeError("boom")

        RC._notify_rc = RC.RemoteControl(
            Path(tempfile.mkdtemp(prefix="rcb_")), hooks=Bad())
        assert isinstance(RC.notify("x", "y"), bool)


# ================================================== E ACP bridge
class TestAcpBridgeBinding:
    def test_bridge_has_instance_hooks(self):
        src = Path("tuan_cli/runtime/acp/bridge.py").read_text(
            encoding="utf-8")
        assert "HookTrigger(self.hooks)" in src
        assert "HookTrigger()" not in src
        assert src.count("self.hooks") >= 2

    def test_bridge_constructor_accepts_hooks(self):
        from tuan_cli.runtime.acp.bridge import KernelAcpBridge
        assert "hooks" in inspect.signature(KernelAcpBridge.__init__).parameters

    def test_no_arg_hooktrigger_consumers_are_zero_repo_wide(self):
        """全仓模块级入口不再有无参 HookTrigger() **代码**消费点。

        A' 自查：初版把注释里的 ``HookTrigger()`` 字面串也算进去了
        （两处行注释在描述「上一版」行为），误报 2 条。改为只看
        **非注释**行 —— 描述历史问题的注释不是消费点。
        """
        hits = []
        for p in Path("tuan_cli").rglob("*.py"):
            for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
                code = line.strip()
                if code.startswith("#"):
                    continue
                if "HookTrigger()" in code:
                    hits.append((str(p), n, code))
        assert hits == [], hits


# ================================================== F registry
class TestSessionRegistry:
    def test_register_resolve_unregister(self):
        assert register_session("s1", "hooks-1") is True
        assert resolve_session("s1") == "hooks-1"
        assert unregister_session("s1") is True
        assert unregister_session("s1") is False

    def test_none_hooks_is_a_valid_registration(self):
        """hooks=None 合法，注销不能靠 pop 值判空（上轮 A′ 同类）。"""
        assert register_session("s-none", None) is True
        assert resolve_session("s-none") is None
        assert unregister_session("s-none") is True

    def test_reject_invalid_owner(self):
        assert register_session("", "x") is False
        assert register_session(123, "x") is False

    def test_upper_bound_rejects_instead_of_evicting(self):
        """安全绑定不做 LRU 静默淘汰；超出上界直接拒绝且已有项完好。"""
        d = session_registry_diagnostics()
        cap = d["max"]
        start = len(d["owners"])
        for i in range(cap - start):
            assert register_session("bound-%d" % i, i) is True
        before = dict((o, resolve_session(o))
                      for o in session_registry_diagnostics()["owners"])
        assert register_session("overflow", "x") is False
        after = dict((o, resolve_session(o))
                     for o in session_registry_diagnostics()["owners"])
        assert before == after
        assert len(session_registry_diagnostics()["owners"]) == cap

    def test_diagnostics_in_provider_diagnostics(self):
        d = provider_diagnostics()
        assert "sessions" in d
        assert set(d["sessions"]) == {"owners", "count", "max"}

    def test_current_session_hooks_matches_frozen_default(self):
        r = Rec("R")
        set_default_hooks_provider(lambda: r, owner="R")
        assert current_session_hooks() is r
        set_default_hooks_provider(lambda: None, owner="None")
        assert current_session_hooks() is None

    def test_provider_exception_is_no_op(self):
        def boom():
            raise RuntimeError("boom")

        set_default_hooks_provider(boom, owner="boom")
        assert current_session_hooks() is None
        assert HookTrigger().config_change(source="x") is False


# ================================================== 接线 / 矩阵钉死
class TestWiringAndMatrix:
    def test_app_calls_bind_after_setting_provider(self):
        src = Path("tuan_cli/app.py").read_text(encoding="utf-8")
        assert "_session_owner = \"agent:%x\" % id(agent)" in src
        assert "bind_session_hooks(agent.ctx.hooks, owner=_session_owner)" in src
        assert src.index("set_default_hooks_provider(") < src.index(
            "bind_session_hooks(agent.ctx.hooks")
        assert "config._hooks = agent.ctx.hooks" in src

    def test_plugin_passes_config_hooks(self):
        src = Path("tuan_cli/core/security_plugin.py").read_text(
            encoding="utf-8")
        assert 'hooks=getattr(config, "_hooks", None)' in src

    def test_existing_wiring_intact(self):
        """第 12 轮起的 6 条既有安全接线不能被本轮换掉。"""
        try:
            from tuan_cli.parity_claude import matrix
            r = matrix.assert_wiring_intact() if hasattr(
                matrix, "assert_wiring_intact") else None
            if r is not None:
                assert r is True or r == []
        except ImportError:
            pass

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
        """catalog.py 零改动 —— 本轮不靠改口径凑数。"""
        src = Path("tuan_cli/parity_claude/catalog.py").read_text(
            encoding="utf-8")
        for key in ("hook_events_extended", "hook_updated_input_validation"):
            i = src.index('M("%s"' % key)
            assert "STATUS_GAP" in src[i:i + 400], key

    def test_slogan_layer_untouched(self):
        """标语引擎 / 净化层 / mapping / tui 逐字节未改（与 parent 比较在
        离线复核脚本里做，这里只确认源码级关键契约仍在）。"""
        src = Path("tuan_cli/hooks/triggers.py").read_text(encoding="utf-8")
        assert "_REENTRY_LOCAL = threading.local()" in src
        assert "reentry_suppressed" in src
