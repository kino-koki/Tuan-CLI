"""B3 续轮 IX：会话激活事务化 + owner 冲突拒绝 + ABA 防护 + 宿主接线。

上一轮（VIII）把会话生命周期收成 ``activate_session`` /
``deactivate_session``，并如实留下三条边界：``deactivate`` 没接到
所有宿主、注册被拒「可见但 provider 可能已被切换」、``SessionHandle``
无关闭标记。本轮一点广度没扩，只把这条线挖到底。

=====  =====================================================================
编号   修复前实测
=====  =====================================================================
Q1     ``activate_session`` **先切 provider 再注册**。占满 64 槽后第 65
       个会话注册返回 False，但 ``set_default_hooks_provider`` 已经切到
       新会话 —— 老会话里尚未回填 hooks 的无 owner 消费者
       ``HookTrigger()`` 从此派到被拒会话（实测 A fired=0 / NEW fired=1）。
Q1b    ``bind_session_hooks`` 无论注册成功与否都继续回填两个模块级
       单例。实测注册失败时 ``_global_alerter.hooks`` 被改成**被拒会话**
       的 hooks —— Q1 污染的隐藏面。
Q2     owner 用 ``"agent:%x" % id(agent)``，CPython 里 ``id`` 会被新对象
       复用（实测同型对象销毁后新建拿到同一 id）。旧
       ``_SESSIONS[owner] = hooks`` **静默覆盖**先建会话的桶；且先建
       会话的旧句柄 ``deactivate`` 会删掉后建会话（ABA，实测
       ``resolve_session -> None``）。
Q3     ``bind_session_hooks`` 中途抛异常时 provider 已切、contextvar 已
       设、却没有句柄可复位 —— 实测 ``current_session_owner`` 泄漏
       ``"sess-boom"`` 且 ``provider_diagnostics()["owner"]`` 已被改。
Q4     ``deactivate_session`` 不清 ``agent.ctx`` 上的 ``session_owner`` /
       ``session_handle``。实测关闭后
       ``bridge._resolve_owner()`` 仍返回**已注销**的 owner。
Q5     ``SessionHandle`` 是 frozen、无 ``closed`` 标记，重复
       ``deactivate`` 只能靠「registry 里还有没有 key」反推。
Q6     ``deactivate_session`` 在生产代码里**零调用点**（只有定义与
       ``__init__`` 导出），registry 只增不减。
=====  =====================================================================

**修复（如实，不夸大）**

1. ``hooks/triggers.py``：把 **registry 注册**作为唯一事务边界。
   - ``bind_session_hooks`` 注册失败立即 ``return False``，**不回填单例**。
   - ``activate_session`` 改为：先 ``bind``（成功才回填）→ 失败/异常
     返回 ``active=False, closed=True`` 句柄，**零全局副作用** → 成功
     才注入 provider、绑定 contextvar、把 owner/handle 挂到 ``ctx``；
     阶段 2 自身异常则精确回滚刚注册的槽并复位 token。
   - ``register_session`` 对**已存在 owner 一律拒绝**（不再覆盖）并
     计数 ``conflicts``；``unregister_session(owner, *, expected=)``
     仅在桶里仍是同一 hooks 对象时删除（ABA 防护，不传则旧语义）。
   - ``SessionHandle`` 改为可变 dataclass，新增 ``hooks`` / ``ctx`` /
     ``closed``；``deactivate_session`` 检查 ``closed``、精确注销、
     仅当 ``ctx.session_handle is handle`` 时清理 ctx 残留。
   - 新增 ``session_scope(...)`` 上下文管理器（异常安全自动关闭）。
2. ``app.py``：改为 ``activate_session(..., ctx=agent.ctx)``，删掉手动
   挂载（失败路径不再留脏 ctx）。
3. ``cli/cmd_chat.py``：新增 ``_close_agent_session(agent)``，在**两个**
   SessionEnd finally 中 ``_run_session_hooks`` 之后调用 —— CLI 主路径
   的 TUI 分支与普通 REPL 分支都接上 ``deactivate_session``。

**六条上轮断言同步（全部改强，不是放宽）**：
``test_app_uses_activate_and_checks_active`` /
``test_app_calls_bind_after_setting_provider`` /
``test_app_backfills_config_hooks_and_passes_owner`` /
``test_app_injects_default_provider`` 改为检查 ``ctx=agent.ctx`` 入参
且 app.py 不再手动挂载；``test_app_sets_session_owner_after_bind``
改为检查事务化顺序 ``bind < provider < set_owner`` 与失败早返回；
``test_diagnostics_in_provider_diagnostics`` 补 ``conflicts``；
``test_deactivate_not_wired_to_all_hosts_is_documented`` 改为
「cmd_chat 恰好 1 处宿主接线 + 其余宿主逐一锁住未接」；
``test_lifecycle_api_exported`` 补 ``session_scope``；
``test_session_registry_rejected_is_documented`` 补 ``conflicts``。

**不该修（配可执行回归锁住）**
- ``get_alerter()`` 仍是进程级单例（多实例会引入文件竞争、重复 bus
  订阅、端口冲突）—— 前几轮已锁 ``x is y``。
- 单 bridge 不按 ``session_id`` 自动派生 owner。
- ``deactivate`` 刻意**不清** default provider（清掉会打断仍在运行的
  其他会话）。
- ``AlertRecord.owner`` 仍不进 ``to_dict()``。
- ACP server / web / stream_json / TUI.close / AcpSession.dispose
  **仍未接线**，本轮只接 CLI 主路径，如实不宣称全面覆盖。

**矩阵一个状态没动**：``ahead 10 / aligned 46 / partial 9 / gap 26 /
not_applicable 8``；``fully_superior=false``；``b_waves_done=["B1"]``。
两个 B3 条目仍 ``STATUS_GAP``，``catalog.py`` 零改动 —— 本轮修的是
「会话激活的事务性与生命周期收尾」，不是功能覆盖面，不靠改口径凑数。

**如实边界**：Q3 的异常路径是**注入故障**（monkeypatch bind 抛错），
不是线上已观测异常；Q2 的 id 复用是 CPython 实现特性实测，用「同
owner 字符串」模拟，不声称线上一定发生；Q4 修的是「归属信息残留」，
未对应已观测派发错误（bridge 的 ``ask_user`` 会先
``resolve_session(_o) is not None`` 校验）。事务化顺序变更是**行为
变更**：注册失败不再切 provider、不再回填单例、ctx 不留脏值。
``os_sandbox`` 仍 gap、``deny_network_by_default`` 仍 ``false`` 未翻、
``credential_masking`` 仍 partial；A 线 10 pending、分叉改动未合并、
第三方自适应红队未做；不是真机多平台验证。标语引擎 / 净化层 /
``mapping.py`` / ``tui.py`` / ``runtime_slogans.py`` 逐字节未改。
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from tuan_cli.hooks import (
    HookTrigger, get_default_hooks_provider, set_default_hooks_provider,
    bind_session_hooks, register_session, unregister_session,
    resolve_session, session_registry_diagnostics,
    current_session_owner, provider_diagnostics,
    activate_session, deactivate_session, session_scope, SessionHandle,
)
from tuan_cli.hooks import triggers as T
from tuan_cli.hooks.manager import HookDecision
from tuan_cli.core import security_alert as SA
from tuan_cli.core import remote_control as RC


class Rec:
    enabled = True

    def __init__(self, n):
        self.n = n
        self.fired = []

    def run_notify(self, e, p):
        self.fired.append((e, dict(p)))

    def run_decision(self, e, tool_name="", payload=None):
        self.fired.append((e, "DECISION"))
        return HookDecision()


@pytest.fixture(autouse=True)
def _reset():
    def clean():
        SA._global_alerter = None
        RC._notify_rc = None
        with T._SESSION_LOCK:
            T._SESSIONS.clear()
            T._SESSION_REJECTIONS = 0
            T._SESSION_CONFLICTS = 0
        T._OWNER_MISSES.clear()
        set_default_hooks_provider(None)
        T._CURRENT_OWNER.set(None)

    clean()
    yield
    clean()


def fill(n=64, prefix="f"):
    for k in range(n):
        assert register_session("%s-%d" % (prefix, k), Rec("f%d" % k))


# ================================================== Q1 注册失败污染 provider
class TestRejectionIsTransactional:
    def test_q1_rejected_session_does_not_switch_provider(self):
        """Q1 主缺陷：第 65 个会话注册被拒，但 provider 曾已切到它。"""
        recA = Rec("A")
        hA = activate_session(owner="sess-A", hooks=recA,
                              provider=lambda: recA)
        assert hA.active is True
        assert get_default_hooks_provider()().n == "A"
        # 填满剩余 63 槽
        fill(63, "filler")
        assert session_registry_diagnostics()["count"] == 64
        recNEW = Rec("NEW")
        hNEW = activate_session(owner="sess-NEW", hooks=recNEW,
                                provider=lambda: recNEW)
        assert hNEW.active is False
        d = provider_diagnostics()
        assert d["session_rejections"] == 1
        # 事务化后：provider 仍属于老会话 A，绝不落到被拒会话
        assert d["owner"] == "sess-A"
        assert get_default_hooks_provider()().n == "A"
        tr = HookTrigger()              # 老会话里尚未回填 hooks 的消费者
        tr.config_change(source="from-A")
        assert len(recA.fired) == 1 and recNEW.fired == []
        deactivate_session(hA)

    def test_q1b_rejected_session_does_not_backfill_singletons(self):
        """Q1b：注册失败仍把 _global_alerter.hooks 改成被拒会话。"""
        alerter = Rec("alerter-old")
        SA._global_alerter = alerter
        fill(64)
        new = Rec("NEW")
        assert bind_session_hooks(new, owner="sess-NEW") is False
        # 零副作用：连属性都不该被设置（上一版会设成 NEW 的 hooks）
        assert not hasattr(alerter, "hooks"), "注册失败却回填了单例"
        assert provider_diagnostics()["session_rejections"] == 1
        # 对照：注册成功时确实会回填，证明上面这条断言不是恒真
        assert unregister_session("f-0") is True
        assert bind_session_hooks(new, owner="sess-NEW") is True
        assert alerter.hooks is new

    def test_rejected_handle_is_closed_and_safe_to_deactivate(self):
        fill(64)
        h = activate_session(owner="rejected", hooks=Rec("R"))
        assert h.active is False and h.closed is True
        assert deactivate_session(h) is False
        assert resolve_session("rejected") is None

    def test_rejected_session_leaves_no_contextvar(self):
        fill(64)
        activate_session(owner="rejected2", hooks=Rec("R2"),
                         provider=lambda: Rec("R2"))
        assert current_session_owner() is None

    def test_rejected_session_leaves_no_ctx_residue(self):
        fill(64)
        ctx = SimpleNamespace()
        h = activate_session(owner="rejected3", hooks=Rec("R3"), ctx=ctx)
        assert h.active is False
        assert getattr(ctx, "session_owner", None) is None
        assert getattr(ctx, "session_handle", None) is None


# ================================================== Q2 冲突拒绝 + ABA
class TestOwnerConflictAndABA:
    def test_cpython_id_is_reused(self):
        """Q2 前提实测：同型对象销毁后新建会拿到同一 id。"""
        class Dummy:
            pass
        a = Dummy()
        ida = id(a)
        del a
        b = Dummy()
        assert ida == id(b)

    def test_same_owner_is_rejected_not_overwritten(self):
        r1, r2 = Rec("first"), Rec("second")
        h1 = activate_session(owner="agent:deadbeef", hooks=r1)
        h2 = activate_session(owner="agent:deadbeef", hooks=r2)
        assert h1.active is True
        assert h2.active is False and h2.closed is True
        assert resolve_session("agent:deadbeef") is r1
        d = provider_diagnostics()
        assert d["session_conflicts"] >= 1
        assert d["sessions"]["conflicts"] >= 1

    def test_old_handle_cannot_delete_rebuilt_session(self):
        """ABA：旧句柄不得删掉同名重建的桶。"""
        r1, r2 = Rec("first"), Rec("second")
        h1 = activate_session(owner="same", hooks=r1)
        deactivate_session(h1)                     # 正常关闭
        h2 = activate_session(owner="same", hooks=r2)
        assert h2.active is True
        # 旧句柄重复关闭：expected 不匹配（或 closed 已置位）→ 不删
        assert deactivate_session(h1) is False
        assert resolve_session("same") is r2
        deactivate_session(h2)

    def test_unregister_expected_semantics(self):
        r1, r2 = Rec("r1"), Rec("r2")
        assert register_session("k", r1) is True
        assert unregister_session("k", expected=r2) is False
        assert resolve_session("k") is r1
        assert unregister_session("k", expected=r1) is True
        assert resolve_session("k") is None
        # 不传 expected 保持旧语义
        register_session("k2", r1)
        assert unregister_session("k2") is True

    def test_conflict_does_not_count_as_capacity_rejection(self):
        r1 = Rec("r1")
        register_session("dup", r1)
        assert register_session("dup", Rec("r2")) is False
        d = session_registry_diagnostics()
        assert d["conflicts"] >= 1 and d["rejected"] == 0


# ================================================== Q3 异常路径
class TestBindExceptionIsTransactional:
    def test_bind_exception_leaves_no_provider_or_contextvar(self):
        orig = T.bind_session_hooks

        def boom(*a, **kw):
            raise RuntimeError("回填单例炸了")

        T.bind_session_hooks = boom
        try:
            h = activate_session(owner="sess-boom", hooks=Rec("boom"),
                                 provider=lambda: Rec("boom"))
        finally:
            T.bind_session_hooks = orig
        assert h.active is False and h.closed is True
        assert current_session_owner() is None
        assert provider_diagnostics()["owner"] is None
        assert get_default_hooks_provider() is None
        assert resolve_session("sess-boom") is None

    def test_bind_exception_does_not_touch_ctx(self):
        ctx = SimpleNamespace()
        orig = T.bind_session_hooks
        T.bind_session_hooks = lambda *a, **kw: (_ for _ in ()).throw(
            RuntimeError("boom"))
        try:
            h = activate_session(owner="sess-boom2", hooks=Rec("R"), ctx=ctx)
        finally:
            T.bind_session_hooks = orig
        assert h.active is False
        assert getattr(ctx, "session_owner", None) is None

    def test_stage2_exception_rolls_back_registration(self):
        """阶段 2（set_session_owner）抛错 → 精确回滚刚注册的槽。"""
        orig = T.set_session_owner

        def boom(owner):
            raise RuntimeError("contextvar 炸了")

        T.set_session_owner = boom
        try:
            h = activate_session(owner="sess-stage2", hooks=Rec("R2"),
                                 provider=lambda: Rec("R2"))
        finally:
            T.set_session_owner = orig
        assert h.active is False and h.closed is True
        assert resolve_session("sess-stage2") is None
        assert current_session_owner() is None


# ================================================== Q4 ctx 清理
class TestCtxCleanup:
    def test_deactivate_clears_own_ctx_residue(self):
        ctx = SimpleNamespace()
        h = activate_session(owner="sess-ctx", hooks=Rec("R"), ctx=ctx)
        assert ctx.session_owner == "sess-ctx"
        assert ctx.session_handle is h
        assert deactivate_session(h) is True
        assert ctx.session_owner == ""
        assert ctx.session_handle is None
        from tuan_cli.runtime.acp.bridge import KernelAcpBridge
        br = KernelAcpBridge()
        br._agent = SimpleNamespace(ctx=ctx)
        assert br._resolve_owner() is None    # 不再返回已注销 owner

    def test_deactivate_does_not_clear_new_sessions_ctx(self):
        """Q4 ABA：ctx 已挂新会话句柄时，旧关闭不得清掉它。"""
        ctx = SimpleNamespace()
        h1 = activate_session(owner="old", hooks=Rec("old"), ctx=ctx)
        # 模拟同 ctx 上又挂了新会话（未经 activate，直接模拟）
        h2 = SessionHandle(owner="new", token=None, active=True,
                           hooks=Rec("new"), ctx=ctx)
        ctx.session_owner = "new"
        ctx.session_handle = h2
        assert deactivate_session(h1) is True      # 精确注销 old 桶
        assert ctx.session_owner == "new"          # 新会话信息未被清
        assert ctx.session_handle is h2


# ================================================== Q5 closed 标记
class TestHandleClosedFlag:
    def test_handle_fields(self):
        h = activate_session(owner="sess-f", hooks=Rec("F"))
        assert {"owner", "token", "active", "hooks", "ctx",
                "closed"} <= set(h.__dataclass_fields__)
        assert h.closed is False
        assert deactivate_session(h) is True
        assert h.closed is True
        assert deactivate_session(h) is False

    def test_inactive_handle_is_preclosed(self):
        fill(64)
        h = activate_session(owner="nope", hooks=Rec("N"))
        assert h.closed is True
        assert deactivate_session(h) is False


# ================================================== session_scope
class TestSessionScope:
    def test_scope_auto_deactivates(self):
        r = Rec("R")
        with session_scope(owner="scoped", hooks=r,
                           provider=lambda: r) as h:
            assert h.active is True
            assert resolve_session("scoped") is r
            HookTrigger(owner="scoped").config_change(source="x")
            assert len(r.fired) == 1
        assert resolve_session("scoped") is None
        assert h.closed is True
        assert current_session_owner() is None

    def test_scope_deactivates_on_exception(self):
        r = Rec("R")
        with pytest.raises(RuntimeError):
            with session_scope(owner="scoped2", hooks=r):
                raise RuntimeError("boom")
        assert resolve_session("scoped2") is None

    def test_scope_yields_inactive_handle_when_full(self):
        fill(64)
        with session_scope(owner="scoped3", hooks=Rec("R")) as h:
            assert h.active is False and h.closed is True
        assert provider_diagnostics()["session_rejections"] >= 1


# ================================================== Q6 宿主接线
class TestHostWiring:
    def test_cmd_chat_closes_after_session_end(self):
        src = Path("tuan_cli/cli/cmd_chat.py").read_text(encoding="utf-8")
        assert "_close_agent_session(" in src
        assert src.count("_close_agent_session(") == 3  # 1 定义 + 2 调用
        assert "deactivate_session(handle)" in src
        # 两个 finally 中，钩子在注销之前
        for seg in src.split("finally:")[1:3]:
            assert seg.index("_run_session_hooks(") < seg.index(
                "_close_agent_session(")

    def test_close_agent_session_is_exception_safe(self):
        """外来 agent / 无 handle / 已关闭句柄都不得掀翻 CLI 退出。"""
        from tuan_cli.cli.cmd_chat import _close_agent_session
        _close_agent_session(None)
        _close_agent_session(object())
        r = Rec("R")
        h = activate_session(owner="host", hooks=r)
        deactivate_session(h)
        _close_agent_session(SimpleNamespace(ctx=SimpleNamespace(
            session_handle=h)))

    def test_close_agent_session_actually_frees_slot(self):
        from tuan_cli.cli.cmd_chat import _close_agent_session
        fill(63, "other")
        r = Rec("host")
        h = activate_session(owner="host2", hooks=r)
        assert session_registry_diagnostics()["count"] == 64
        agent = SimpleNamespace(ctx=SimpleNamespace(session_handle=h))
        _close_agent_session(agent)
        assert resolve_session("host2") is None
        assert session_registry_diagnostics()["count"] == 63

    def test_other_hosts_still_not_wired(self):
        """如实边界：只有 CLI 主路径接了，其余宿主未接。"""
        for rel in ("tuan_cli/runtime/acp/server.py",
                    "tuan_cli/runtime/acp/session.py",
                    "tuan_cli/web/server.py",
                    "tuan_cli/stream_json/headless.py",
                    "tuan_cli/tui/tui.py"):
            assert "deactivate_session(" not in Path(rel).read_text(
                encoding="utf-8"), rel


# ================================================== 不该修
class TestNotFixedOnPurpose:
    def test_get_alerter_still_process_singleton(self):
        import shutil
        import tempfile
        h1 = Path(tempfile.mkdtemp(prefix="h1_"))
        h2 = Path(tempfile.mkdtemp(prefix="h2_"))
        try:
            assert SA.get_alerter(home=h1) is SA.get_alerter(home=h2)
        finally:
            shutil.rmtree(h1, ignore_errors=True)
            shutil.rmtree(h2, ignore_errors=True)

    def test_deactivate_still_keeps_default_provider(self):
        r = Rec("R")
        h = activate_session(owner="keep", hooks=r, provider=lambda: r)
        deactivate_session(h)
        assert get_default_hooks_provider() is not None
        assert get_default_hooks_provider()() is r

    def test_alert_owner_still_not_serialized(self):
        rec = SA.AlertRecord(title="T", severity="low", owner="s")
        assert "owner" not in rec.to_dict()

    def test_previous_round_contracts_present(self):
        src = Path("tuan_cli/hooks/triggers.py").read_text(
            encoding="utf-8")
        for token in ("_REENTRY_LOCAL = threading.local()",
                      "reentry_suppressed", "_MAX_SESSIONS = 64",
                      "owner_not_registered", "_UNSET = object()",
                      "_SESSION_REJECTIONS"):
            assert token in src, token

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


# ================================================== 接线 / 矩阵
class TestWiringAndMatrix:
    def test_app_passes_ctx_to_activate(self):
        src = Path("tuan_cli/app.py").read_text(encoding="utf-8")
        assert "ctx=agent.ctx" in src
        assert "activate_session(" in src
        assert "if not _handle.active:" in src
        assert "agent.ctx.session_owner =" not in src
        assert "agent.ctx.session_handle = _handle" not in src

    def test_transactional_order_in_activate(self):
        src = Path("tuan_cli/hooks/triggers.py").read_text(
            encoding="utf-8")
        i = src.index("def activate_session(")
        body = src[i:src.index("def deactivate_session(")]
        assert body.index("bind_session_hooks(") < body.index(
            "set_default_hooks_provider(")
        assert body.index("set_default_hooks_provider(") < body.index(
            "set_session_owner(")
        assert "if not active:" in body
        assert "unregister_session(owner, expected=hooks)" in body

    def test_bind_returns_early_on_failed_registration(self):
        src = Path("tuan_cli/hooks/triggers.py").read_text(
            encoding="utf-8")
        i = src.index("def bind_session_hooks(")
        body = src[i:src.index("@dataclass")]
        assert body.index("if not ok:") < body.index(
            '("security_alert"')
        assert "return False" in body

    def test_lifecycle_api_includes_scope(self):
        import tuan_cli.hooks as pkg
        assert hasattr(pkg, "session_scope")
        assert hasattr(pkg, "SessionHandle")

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
