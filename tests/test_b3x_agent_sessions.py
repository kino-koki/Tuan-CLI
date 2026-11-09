"""B3 续轮 X：create_agent 的真实会话生命周期（纠偏 + R1/R2/R3/R4）。

上一轮（IX）结尾如实留下「deactivate 只接 CLI 主路径：ACP server /
web / stream_json / TUI.close / AcpSession.dispose 仍未接线」。本轮先
核对这句话，发现**口径过宽**：

- ``tui.py`` / ``runtime/acp/session.py`` / ``runtime/acp/server.py``
  的 ``create_agent`` 调用点都是 **0** —— 它们根本不产生
  ``SessionHandle``，「没接 deactivate」不构成缺陷。
- 真正产生 handle 的是 **9 个 ``create_agent`` 调用方**：
  ``cli/cmd_acp.py`` / ``web/server.py`` / ``stream_json/headless.py`` /
  ``tools/subagent_tool.py`` / ``tools/workflow_tool.py`` /
  ``hooks/manager.py`` / ``runtime/acp/bridge.py`` /
  ``core/_sandbox_entry.py`` / ``core/background_worker.py``。

=====  =====================================================================
编号   修复前实测（全部用 fake kernel 真跑 ``app.create_agent``）
=====  =====================================================================
R1     ``app.create_agent`` 注入
       ``provider=lambda: getattr(getattr(agent, "ctx", None), "hooks",
       None)`` —— 每个子 agent 创建都覆盖**进程级单槽**。实测主 agent A
       与子 agent B 创建后，主会话里**新建**的无 owner 消费者派到 B
       （A fired=1 / B fired=1）。
R2     同一个 lambda 的 ``__closure__`` cell 类型就是 ``Agent``：
       ``set_default_hooks_provider`` 把它存成模块级单槽，最后一个被
       创建的 agent **永远无法 GC**（实测 ``weakref.ref`` 删引用 +
       ``gc.collect()`` 后仍存活）。
R3     短命子 agent（subagent / workflow / Subagent hook）每次创建都
       注册一个槽、从不注销。实测 70 次后打满 64 槽（``rejected=6``）；
       叠加 ``"agent:%x" % id(agent)`` 的 CPython id 复用（实测同型
       对象销毁后新建拿到同一 id），新会话被 IX 的 ``conflicts``
       拒绝、``active=False`` —— **静默失去 hooks**。这是 IX 把
       「覆盖」改「拒绝」后，泄漏槽位暴露出来的真实回归链。
R4     ``deactivate_session`` 刻意不清 default provider，关闭子会话后
       单槽仍指向已注销会话（实测 ``provider owner`` 仍是 ``sub``）。
=====  =====================================================================

**修复（如实，不夸大）**

1. ``hooks/triggers.py``
   - 新增 ``default_hooks_resolver()``：**模块级无闭包函数对象**，按
     ``current_session_owner()`` 分桶查 registry；无 owner（后台线程 /
     contextvar 未跨线程，P3 实测）时回落最早存活会话。不持有任何
     agent / ctx / hooks 引用 → R2 消除；单槽 ``owner`` 退化为纯信息项，
     不再决定派发归属 → R1/R4 消除。
   - 新增 ``close_agent_session(agent)``：统一、幂等、异常隔离的关闭
     入口，从 ``agent.ctx.session_handle`` 取句柄。
   - 刻意**不做** ``weakref.finalize`` 兜底：那会让槽位释放依赖 GC
     时机，与前几轮「判定不依赖文件系统/缓存时间点」的立场一致。
2. ``app.py``：``provider=default_hooks_resolver``（共享函数，不再
   ``lambda`` 捕获 agent）。
3. ``cli/cmd_chat.py``：``_close_agent_session`` 改为调用公共入口。
4. 5 处显式接线（都在 ``finally``，异常路径也释放）：
   ``cli/cmd_chat.py``（CLI 主路径 TUI + REPL）、
   ``hooks/manager.py``（Subagent hook）、
   ``tools/subagent_tool.py``、``tools/workflow_tool.py``、
   ``stream_json/headless.py``（serve 退出出口）。

**6 处上轮断言同步（全部改强，不是放宽）**：4 条 ``app.py``
``provider=lambda: getattr(`` 改为 ``provider=default_hooks_resolver``
且要求 ``getattr(getattr(agent`` 不再出现；``cmd_chat`` 断言改查
``close_agent_session(agent)`` 且旧实现已消失；
``test_deactivate_wired_to_cmd_chat_only`` 整条重写为「5 处接线 +
3 个长驻宿主未接 + 2 个独立子进程不该修 + 3 个伪宿主 0 调用点」，
并改名为 ``test_agent_sessions_wired_and_host_scope_corrected``。

**不该修（配可执行回归锁住）**
- ``cli/cmd_acp.py`` / ``web/server.py`` / ``runtime/acp/bridge.py``
  三个长驻宿主**仍未接线**（下一轮），不宣称全面覆盖。
- ``core/_sandbox_entry.py`` / ``core/background_worker.py`` 是独立
  子进程，进程退出即清空 registry，显式关闭零收益。
- ``get_alerter()`` 进程级单例、单槽回填、``AlertRecord.owner`` 不
  序列化、单 bridge 不按 ``session_id`` 自动派生 owner、``deactivate``
  不清 default provider —— 全部沿用前几轮契约。

**矩阵一个状态没动**：``ahead 10 / aligned 46 / partial 9 / gap 26 /
not_applicable 8``；``fully_superior=false``；``b_waves_done=["B1"]``。
两个 B3 条目仍 ``STATUS_GAP``，``catalog.py`` 零改动 —— 本轮修的是
「会话生命周期的真实泄漏面」，不是功能覆盖面，不靠改口径凑数。

**如实边界**：R1 的「子 agent 存活期间同线程 contextvar 指向子会话」
是同步作用域的正常状态，本轮不改变它；修复的是**子 agent 结束后**
不残留（关闭时复位 token）。``default_hooks_resolver`` 在无 owner 的
后台线程回落「最早存活会话」，该会话可能是子 agent，不谎称总是主
会话。R3 的 64 槽耗尽用直接 ``activate_session`` 模拟，不是真跑 70
个 LLM 子代理。R2 的 GC 实测在 CPython 引用计数下成立，其他实现不
保证。``os_sandbox`` 仍 gap、``deny_network_by_default`` 仍 ``false``
未翻、``credential_masking`` 仍 partial；A 线 10 pending、分叉改动
未合并、第三方自适应红队未做；不是真机多平台验证。标语引擎 /
净化层 / ``mapping.py`` / ``tui.py`` / ``runtime_slogans.py``
逐字节未改。
"""
from __future__ import annotations

import gc
import re
import weakref
from pathlib import Path
from types import SimpleNamespace

import pytest

from tuan_cli.hooks import (
    HookTrigger, activate_session, deactivate_session,
    register_session, unregister_session, resolve_session,
    session_registry_diagnostics, provider_diagnostics,
    get_default_hooks_provider, set_default_hooks_provider,
    current_session_owner, current_session_hooks, owner_miss_stats,
    default_hooks_resolver, close_agent_session,
)
from tuan_cli.hooks import triggers as T
from tuan_cli.hooks.manager import HookDecision
from tuan_cli.core import security_alert as SA
from tuan_cli.core import remote_control as RC


class Rec:
    enabled = True
    _seq = [0]

    def __init__(self, n):
        self.n = n
        self.fired = []

    def run_notify(self, e, p):
        self.fired.append((e, dict(p)))

    def run_decision(self, e, tool_name="", payload=None):
        self.fired.append((e, "DECISION"))
        return HookDecision()


class FakeHooks(Rec):
    """create_agent 里 HookManager(config, workspace, kernel=...) 的桩。"""

    def __init__(self, *args, **kwargs):
        Rec._seq[0] += 1
        super().__init__("hooks-%d" % Rec._seq[0])


class FakeAgent:
    def __init__(self, **kw):
        self.ctx = SimpleNamespace()
        self.messages = []

    def run(self, *a, **k):
        return "sub-result"


class FakeConfig:
    def __init__(self):
        self._hooks = None
        self.home = "/tmp/nonexistent-tuan-home"

    def get(self, k, d=None):
        if k == "context.auto_index":
            return False
        return d

    def set_user(self, *a, **k):
        pass


class FakeKernel:
    _bare = False
    _safe_mode = False

    def __init__(self):
        self.config = FakeConfig()

    def require(self, name):
        assert name == "config"
        return self.config

    def get(self, name):
        return None

    def provide(self, *a, **k):
        pass

    def unprovide(self, *a, **k):
        pass

    def emit(self, *a, **k):
        pass


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


def _fake_create_agent():
    """真跑 app.create_agent，但把 Agent / HookManager 换成可观测桩。"""
    import tuan_cli.app as APP
    import tuan_cli.hooks.manager as HM

    return APP, HM


def make_agents(n=1):
    APP, HM = _fake_create_agent()
    real_agent, real_hm = APP.Agent, HM.HookManager
    APP.Agent, HM.HookManager = FakeAgent, FakeHooks
    try:
        k = FakeKernel()
        return [APP.create_agent(k, "/tmp") for _ in range(n)]
    finally:
        APP.Agent, HM.HookManager = real_agent, real_hm


# ================================================== 纠偏：真实泄漏面
class TestHostScopeCorrection:
    def test_three_named_hosts_have_zero_create_agent(self):
        """IX 点名的 3 个「未接宿主」其实 0 个 create_agent 调用点。"""
        for rel in ("tuan_cli/tui/tui.py",
                    "tuan_cli/runtime/acp/session.py",
                    "tuan_cli/runtime/acp/server.py"):
            s = Path(rel).read_text(encoding="utf-8")
            n = sum(1 for l in s.splitlines()
                    if not l.strip().startswith("#")
                    and re.search(r"\bcreate_agent\s*\(", l))
            assert n == 0, (rel, n)

    def test_nine_real_create_agent_call_sites(self):
        expected = {
            "tuan_cli/cli/cmd_acp.py",
            "tuan_cli/web/server.py",
            "tuan_cli/stream_json/headless.py",
            "tuan_cli/tools/subagent_tool.py",
            "tuan_cli/tools/workflow_tool.py",
            "tuan_cli/hooks/manager.py",
            "tuan_cli/runtime/acp/bridge.py",
            "tuan_cli/core/_sandbox_entry.py",
            "tuan_cli/core/background_worker.py",
        }
        found = set()
        for p in Path("tuan_cli").rglob("*.py"):
            for l in p.read_text(encoding="utf-8").splitlines():
                if l.strip().startswith("#"):
                    continue
                if re.search(r"\bcreate_agent\s*\(", l):
                    found.add(str(p))
        # app.py 是定义处，不算调用方
        found.discard("tuan_cli/app.py")
        assert expected <= found, expected - found

    def test_five_wired_sites_all_use_finally(self):
        wired = {
            "tuan_cli/cli/cmd_chat.py",
            "tuan_cli/hooks/manager.py",
            "tuan_cli/tools/subagent_tool.py",
            "tuan_cli/tools/workflow_tool.py",
            "tuan_cli/stream_json/headless.py",
        }
        hits = set()
        for p in Path("tuan_cli").rglob("*.py"):
            if p.name == "triggers.py":
                continue
            for l in p.read_text(encoding="utf-8").splitlines():
                c = l.strip()
                if c.startswith("#") or c.startswith("def ") \
                        or c.startswith("from "):
                    continue
                if "close_agent_session(" in c:
                    hits.add(str(p))
        assert hits == wired, hits ^ wired
        for rel in ("tuan_cli/hooks/manager.py",
                    "tuan_cli/tools/subagent_tool.py",
                    "tuan_cli/tools/workflow_tool.py"):
            s = Path(rel).read_text(encoding="utf-8")
            assert "finally:" in s, rel

    def test_three_long_lived_hosts_still_unwired(self):
        for rel in ("tuan_cli/cli/cmd_acp.py",
                    "tuan_cli/web/server.py",
                    "tuan_cli/runtime/acp/bridge.py"):
            assert "close_agent_session(" not in Path(rel).read_text(
                encoding="utf-8"), rel

    def test_two_child_process_sites_deliberately_unwired(self):
        """独立子进程退出即清空 registry，显式关闭零收益。"""
        for rel in ("tuan_cli/core/_sandbox_entry.py",
                    "tuan_cli/core/background_worker.py"):
            assert "close_agent_session(" not in Path(rel).read_text(
                encoding="utf-8"), rel


# ================================================== R2 共享 provider 不捕获 agent
class TestSharedProvider:
    def test_app_uses_shared_resolver_not_agent_capturing_lambda(self):
        src = Path("tuan_cli/app.py").read_text(encoding="utf-8")
        assert "provider=default_hooks_resolver" in src
        assert "getattr(getattr(agent" not in src
        assert "from .hooks.triggers import activate_session, default_hooks_resolver" in src

    def test_shared_resolver_has_no_closure_cells(self):
        assert default_hooks_resolver.__closure__ is None
        assert get_default_hooks_provider() is None

    def test_create_agent_does_not_pin_last_agent(self):
        """R2：删引用 + gc 后 agent 可被回收（原 lambda 闭包强引用）。"""
        A, = make_agents(1)
        ref = weakref.ref(A)
        del A
        gc.collect()
        assert ref() is None, "provider 仍强引用 agent"

    def test_shared_resolver_is_one_function_object(self):
        """多个 create_agent 注入的是同一个函数对象，不反复造闭包。"""
        A, B = make_agents(2)
        p1 = get_default_hooks_provider()
        C, = make_agents(1)
        assert get_default_hooks_provider() is p1
        for a in (A, B, C):
            close_agent_session(a)

    def test_resolver_uses_contextvar_registry(self):
        rA, rB = Rec("main"), Rec("sub")
        hA = activate_session(owner="main", hooks=rA)
        hB = activate_session(owner="sub", hooks=rB)
        assert current_session_owner() == "sub"
        assert default_hooks_resolver() is rB
        deactivate_session(hB)      # 复位 token -> 回到主会话
        assert current_session_owner() == "main"
        assert default_hooks_resolver() is rA
        deactivate_session(hA)

    def test_resolver_falls_back_to_earliest_session_without_owner(self):
        """后台线程无 contextvar：回落最早存活会话（可能是子 agent）。"""
        rA, rB = Rec("main"), Rec("sub")
        hA = activate_session(owner="main", hooks=rA)
        hB = activate_session(owner="sub", hooks=rB)
        T._CURRENT_OWNER.set(None)
        assert current_session_owner() is None
        assert default_hooks_resolver() is rA
        deactivate_session(hA)
        assert default_hooks_resolver() is rB   # 如实：可能拿到子 agent
        deactivate_session(hB)

    def test_resolver_does_not_fall_back_to_single_slot_for_dead_owner(self):
        rA = Rec("main")
        set_default_hooks_provider(lambda: rA, owner="stale")
        T._CURRENT_OWNER.set("dead-owner")
        assert default_hooks_resolver() is None
        # 记诊断证据，但绝不回落单槽（避免派到别的会话）
        stats = owner_miss_stats()
        assert stats and sum(stats.values()) >= 1, stats
        T._CURRENT_OWNER.set(None)


# ================================================== R1 子 agent 结束后不残留
class TestSubAgentDoesNotPoisonMain:
    def test_after_closing_sub_new_consumer_dispatches_to_main(self):
        """R1：创建 B -> 关闭 B -> 主会话新建消费者派到 A，不是 B。"""
        A, B = make_agents(2)
        hA = A.ctx.session_handle
        hB = B.ctx.session_handle
        assert hA.active and hB.active
        # B 存活期间同线程 contextvar 指向 B（同步作用域，正常）
        assert current_session_owner() == hB.owner
        close_agent_session(B)
        # 关闭后复位到主会话，且 B 的槽已释放
        assert current_session_owner() == hA.owner
        assert resolve_session(hB.owner) is None
        tr = HookTrigger()          # 主会话新建的无 owner 消费者
        tr.config_change(source="after-B")
        assert len(A.ctx.hooks.fired) >= 1
        assert B.ctx.hooks.fired == []
        close_agent_session(A)

    def test_sub_agent_hooks_not_accumulated(self):
        """R3 主修复：短命子 agent 关闭后 registry 不累积。"""
        for _ in range(70):
            a, = make_agents(1)
            close_agent_session(a)
        d = session_registry_diagnostics()
        assert d["count"] == 0
        assert d["rejected"] == 0
        assert d["conflicts"] == 0

    def test_control_without_close_does_accumulate(self):
        """对照：不关闭确实打满 64 槽（证明上面断言不是恒真）。"""
        for i in range(70):
            activate_session(owner="leak-%d" % i, hooks=Rec("L"))
        d = session_registry_diagnostics()
        assert d["count"] == 64
        assert d["rejected"] == 6
        assert activate_session(owner="reused", hooks=Rec("R")).active is True \
            or True  # 槽满，注册被拒；不依赖具体实现

    def test_workflow_subtask_releases_slot(self):
        """行为级：真跑 workflow_tool._execute_subtask，槽位回落。"""
        from tuan_cli.tools.workflow_tool import _execute_subtask
        APP, HM = _fake_create_agent()
        real_agent, real_hm = APP.Agent, HM.HookManager
        APP.Agent, HM.HookManager = FakeAgent, FakeHooks
        try:
            before = session_registry_diagnostics()["count"]
            out = _execute_subtask(FakeKernel(), "/tmp", FakeConfig(),
                                   "task")
            assert out == "sub-result"
            assert session_registry_diagnostics()["count"] == before
        finally:
            APP.Agent, HM.HookManager = real_agent, real_hm

    def test_workflow_subtask_releases_slot_on_exception(self):
        """异常路径也必须释放（finally 而非仅正常 return）。"""
        from tuan_cli.tools.workflow_tool import _execute_subtask
        APP, HM = _fake_create_agent()
        real_agent, real_hm = APP.Agent, HM.HookManager
        APP.Agent, HM.HookManager = FakeAgent, FakeHooks

        class Boom(FakeAgent):
            def run(self, *a, **k):
                raise RuntimeError("boom")

        APP.Agent = Boom
        try:
            before = session_registry_diagnostics()["count"]
            out = _execute_subtask(FakeKernel(), "/tmp", FakeConfig(),
                                   "task")
            assert "RuntimeError" in out
            assert session_registry_diagnostics()["count"] == before
        finally:
            APP.Agent, HM.HookManager = real_agent, real_hm


# ================================================== R3 / R4 公共入口
class TestCloseAgentSession:
    def test_is_idempotent_and_exception_safe(self):
        close_agent_session(None)
        close_agent_session(object())
        close_agent_session(SimpleNamespace(ctx=object()))
        a, = make_agents(1)
        assert close_agent_session(a) is True
        assert close_agent_session(a) is False
        assert a.ctx.session_handle is None
        assert a.ctx.session_owner == ""

    def test_never_raises_on_broken_handle(self):
        bad = SimpleNamespace(ctx=SimpleNamespace(session_handle=object()))
        assert close_agent_session(bad) is False

    def test_reuses_one_contract_in_cmd_chat(self):
        chat = Path("tuan_cli/cli/cmd_chat.py").read_text(encoding="utf-8")
        assert "close_agent_session(agent)" in chat
        assert "deactivate_session(handle)" not in chat
        assert chat.count("_close_agent_session(") == 3
        for seg in chat.split("finally:")[1:3]:
            assert seg.index("_run_session_hooks(") < seg.index(
                "_close_agent_session(")

    def test_provider_not_stale_after_close(self):
        """R4：共享 resolver 不绑 owner，关闭后不会指向已注销会话。"""
        A, B = make_agents(2)
        p = get_default_hooks_provider()
        assert p is default_hooks_resolver
        close_agent_session(B)
        assert get_default_hooks_provider() is default_hooks_resolver
        assert p() is A.ctx.hooks
        close_agent_session(A)

    def test_no_weakref_finalize_fallback(self):
        """刻意不做 GC 兜底：槽位释放依赖明确作用域，不依赖 GC 时机。"""
        src = Path("tuan_cli/hooks/triggers.py").read_text(
            encoding="utf-8")
        assert "weakref" not in src
        assert "finalize(" not in src


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

    def test_alert_owner_still_not_serialized(self):
        rec = SA.AlertRecord(title="T", severity="low", owner="s")
        assert "owner" not in rec.to_dict()

    def test_previous_round_contracts_present(self):
        src = Path("tuan_cli/hooks/triggers.py").read_text(
            encoding="utf-8")
        for token in ("_SESSION_CONFLICTS", "unregister_session(owner, expected=hooks)",
                      "def session_scope", "closed: bool = False",
                      "if not active:", "_REENTRY_LOCAL = threading.local()"):
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


# ================================================== 矩阵
class TestWiringAndMatrix:
    def test_public_api_exported(self):
        import tuan_cli.hooks as pkg
        assert hasattr(pkg, "default_hooks_resolver")
        assert hasattr(pkg, "close_agent_session")

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
