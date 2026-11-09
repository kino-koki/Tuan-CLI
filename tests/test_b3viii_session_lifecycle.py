"""B3 续轮 VIII：会话生命周期收口 + 跨线程 owner 句柄化。

上两轮把「派发归属」从单槽 provider 推到 owner 分桶，但留了三处
**生命周期/线程边界**没处理。本轮一点广度没扩，只把这条线挖到底。

=====  =====================================================================
编号   修复前实测
=====  =====================================================================
P1     ``unregister_session`` 在生产代码里**零调用点**（只有定义与
       ``__init__`` 导出）。registry 只增不减，占满 64 槽后
       ``bind_session_hooks(..., owner=NEW)`` 返回 **False**，而
       ``app.py`` 完全不检查返回值 —— 第 65 个会话的
       ``HookTrigger(owner=NEW).config_change()`` 静默 no-op。
P2     ``set_session_owner`` 设完从不复位；同线程复用（CLI 循环、
       ACP server 长驻、测试）时，第二个会话构造失败后 owner 仍是
       第一个会话的值（实测残留 = True）。
P3     ``contextvars.ContextVar`` **不跨** executor 线程（主线程
       ``"ctx-main"`` / ``ThreadPoolExecutor`` 线程 ``None``，实测）。
       ``KernelAcpBridge`` 原先在 ``ask_user`` 里**运行时**读
       ``current_session_owner()``，而权限回调 / ``_AcpUIHandle``
       跑在 executor 线程 —— owner 解析退化为实例冻结 hooks。
P4     ``_bump_owner_miss`` **锁外**读 ``len()`` / ``in``、锁内写入，
       是 TOCTOU。GIL 下本次未稳定复现越界（与前几轮「加锁是消除
       对 GIL 实现细节的依赖」同口径）。上界语义也含糊：实际最多
       ``_MAX_MISS_KEYS`` 个具体 owner + 1 个 ``<other>`` = 65。
P5     ``bind_session_hooks`` docstring 写「回填 **3** 个模块级单例」，
       但 ``for`` 元组里一直只有 2 个（``_global_alerter`` /
       ``_notify_rc``）；ACP bridge 是 per-agent 实例，不是模块级单例。
=====  =====================================================================

**不该修（配可执行回归锁住）**
- ``get_alerter()`` 仍是进程级单例（改成多实例会引入文件竞争、
  重复 bus 订阅、端口冲突）—— 前两轮已锁 ``x is y``，本轮不动。
- ``bind_session_hooks`` 的单槽回填仍在、``AlertRecord.owner`` 仍不进
  ``to_dict()``、单 bridge 不按 ``session_id`` 自动派生 owner。

**修复（如实，不夸大）**

1. ``hooks/triggers.py``：新增 ``SessionHandle`` /
   ``activate_session(owner=, hooks=, provider=)`` /
   ``deactivate_session(handle)``。四个动作（注入 provider、绑定
   contextvar、注册 registry、回填单例）收成一个入口，返回携带
   **复位 token** 的句柄；``deactivate`` 注销 registry + 复位
   contextvar。注册被拒新增 ``rejected`` 计数并进
   ``provider_diagnostics()`` —— **可见，不再静默**。
2. ``app.py``：改用 ``activate_session``；把 ``session_owner`` 与
   ``session_handle`` 显式挂到 ``agent.ctx``；``active=False`` 时
   ``logger.warning``，不静默退化到单槽绑定。
3. ``runtime/acp/bridge.py``：新增构造参数 ``owner`` 与
   ``_resolve_owner()``，优先级 **显式 owner > agent.ctx.session_owner
   > current_session_owner()**。前两者跨线程稳定，不依赖 contextvar；
   ``ask_user`` 改用它。仍**不**按 session_id 自动派生。
4. ``_bump_owner_miss`` 整个判定收进锁内，docstring 明确 65 语义。
5. ``bind_session_hooks`` docstring 口径改成「2 个」。

**三条上轮断言同步（全部改强，不是放宽）**：
``test_app_backfills_config_hooks_and_passes_owner`` /
``test_app_calls_bind_after_setting_provider`` /
``test_app_sets_session_owner_after_bind`` 从「检查分散调用与顺序」
改为「检查单一入口 + ctx 挂载 + active 失败可见 + 生命周期 API 导出 +
旧分散调用已消失」；``test_bridge_supports_owner_without_auto_mapping``
补上 ``_resolve_owner`` 与显式句柄断言。

**矩阵一个状态没动**：``ahead 10 / aligned 46 / partial 9 / gap 26 /
not_applicable 8``；``fully_superior=false``；``b_waves_done=["B1"]``。
两个 B3 条目仍 ``STATUS_GAP``，``catalog.py`` 零改动 —— 本轮修的是
「会话生命周期与线程边界」，不是功能覆盖面，不靠改口径凑数。

**如实边界**：``deactivate_session`` **没有接到所有宿主**（项目里没有
统一的 agent close 钩子），只提供 API + ``agent.ctx.session_handle``
供宿主调用；未调用的长跑进程仍会占满 64 槽，但现在 ``rejected`` 可见、
``app.py`` 会 warning，不再静默。``deactivate`` 刻意**不清** default
provider（清掉会打断仍在运行的其他会话）。标语引擎 / 净化层 /
``mapping.py`` / ``tui.py`` / ``runtime_slogans.py`` 逐字节未改。
"""
from __future__ import annotations

import concurrent.futures
import inspect
import threading
from pathlib import Path

import pytest

from tuan_cli.hooks import (
    HookTrigger, set_default_hooks_provider, bind_session_hooks,
    register_session, unregister_session, resolve_session,
    session_registry_diagnostics, set_session_owner, reset_session_owner,
    current_session_owner, owner_miss_stats, provider_diagnostics,
    activate_session, deactivate_session, SessionHandle,
)
from tuan_cli.hooks import triggers as T
from tuan_cli.hooks.manager import HookDecision
from tuan_cli.core import security_alert as SA
from tuan_cli.core import remote_control as RC


class Rec:
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
    def clean():
        SA._global_alerter = None
        RC._notify_rc = None
        for o in list(session_registry_diagnostics()["owners"]):
            unregister_session(o)
        T._OWNER_MISSES.clear()
        T._SESSION_REJECTIONS = 0
        set_default_hooks_provider(None)

    clean()
    yield
    clean()


# ================================================== P1 上界与可见性
class TestRegistryLifecycle:
    def test_exhausting_64_slots_is_now_visible(self):
        """P1 主缺陷：第 65 个会话注册被拒，但 rejected 计数可见。"""
        for i in range(64):
            assert register_session("old-%d" % i, Rec()) is True
        d0 = session_registry_diagnostics()
        assert d0["count"] == 64 and d0["rejected"] == 0
        r = Rec("NEW")
        assert bind_session_hooks(r, owner="session-NEW") is False
        d1 = session_registry_diagnostics()
        assert d1["rejected"] == 1
        assert "session_rejections" in provider_diagnostics()
        assert provider_diagnostics()["session_rejections"] == 1

    def test_deactivate_frees_the_slot(self):
        """生命周期：注销后新会话可以注册成功。"""
        for i in range(64):
            assert register_session("p-%d" % i, Rec()) is True
        assert register_session("p-new", Rec()) is False
        assert unregister_session("p-0") is True
        assert register_session("p-new", Rec()) is True

    def test_activate_deactivate_roundtrip(self):
        """activate 注册 + 绑定 contextvar，deactivate 全部复位。"""
        r = Rec("R")
        h = activate_session(
            owner="sess-1", hooks=r,
            provider=lambda: r,
        )
        assert isinstance(h, SessionHandle)
        assert h.active is True and h.owner == "sess-1"
        assert h.token is not None
        assert current_session_owner() == "sess-1"
        assert resolve_session("sess-1") is r
        HookTrigger(owner="sess-1").config_change(source="x")
        assert len(r.fired) == 1
        assert deactivate_session(h) is True
        assert current_session_owner() is None
        assert resolve_session("sess-1") is None

    def test_activate_sets_provider(self):
        r = Rec("R")
        h = activate_session(owner="sess-p", hooks=r, provider=lambda: r)
        try:
            from tuan_cli.hooks import get_default_hooks_provider
            assert get_default_hooks_provider()() is r
            assert provider_diagnostics()["owner"] == "sess-p"
        finally:
            deactivate_session(h)

    def test_activate_without_provider(self):
        r = Rec("R")
        h = activate_session(owner="sess-np", hooks=r)
        try:
            assert h.active is True
            assert current_session_owner() == "sess-np"
        finally:
            deactivate_session(h)

    def test_activate_reports_rejection(self):
        for i in range(64):
            register_session("full-%d" % i, Rec())
        h = activate_session(owner="full-new", hooks=Rec())
        assert h.active is False
        assert session_registry_diagnostics()["rejected"] == 1
        # 句柄仍可安全 deactivate（注销失败返回 False，不抛）
        assert deactivate_session(h) is False

    def test_deactivate_none_and_foreign_handle(self):
        assert deactivate_session(None) is False
        assert deactivate_session(object()) is False

    def test_deactivate_does_not_clear_provider(self):
        """如实边界：刻意不清 default provider，避免打断其他会话。"""
        r = Rec("R")
        h = activate_session(owner="sess-keep", hooks=r,
                             provider=lambda: r)
        deactivate_session(h)
        from tuan_cli.hooks import get_default_hooks_provider
        assert get_default_hooks_provider() is not None


# ================================================== P2 contextvar 复位
class TestContextvarReset:
    def test_token_is_reset_not_leaked(self):
        tok = set_session_owner("sess-A")
        try:
            assert current_session_owner() == "sess-A"
        finally:
            reset_session_owner(tok)
        assert current_session_owner() is None

    def test_second_session_failure_does_not_leave_stale_owner(self):
        """P2：用 activate/deactivate 后，失败路径不再残留 owner。"""
        h = activate_session(owner="sess-A", hooks=Rec())
        try:
            deactivate_session(h)
            # 第二个会话「构造失败」：没有 set，也没有残留
            try:
                raise RuntimeError("agent B 构造失败")
            except Exception:
                pass
            assert current_session_owner() is None
        finally:
            deactivate_session(h)   # 幂等，重复调用不掀翻

    def test_deactivate_is_idempotent(self):
        h = activate_session(owner="idem", hooks=Rec())
        assert deactivate_session(h) is True
        assert deactivate_session(h) is False
        assert current_session_owner() is None

    def test_reset_foreign_context_token_is_no_op(self):
        box = []

        def make():
            box.append(set_session_owner("foreign"))

        th = threading.Thread(target=make)
        th.start()
        th.join()
        reset_session_owner(box[0])
        assert current_session_owner() is None


# ================================================== P3 跨线程 owner 句柄
class TestCrossThreadOwner:
    def test_contextvar_does_not_cross_executor(self):
        """P3 实测：executor 线程拿不到主线程 owner。"""
        tok = set_session_owner("ctx-main")
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                got = ex.submit(current_session_owner).result(timeout=5)
            assert got is None
            assert current_session_owner() == "ctx-main"
        finally:
            reset_session_owner(tok)

    def test_bridge_resolves_owner_from_agent_ctx(self):
        """显式句柄跨线程稳定：agent.ctx.session_owner 优先。"""
        from tuan_cli.runtime.acp.bridge import KernelAcpBridge

        class Ctx:
            session_owner = "sess-ctx"

        class Agent:
            ctx = Ctx()

        b = KernelAcpBridge()
        b._agent = Agent()
        assert b._resolve_owner() == "sess-ctx"
        # 模拟 executor 线程读取（不依赖 contextvar）
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            assert ex.submit(b._resolve_owner).result(timeout=5) == "sess-ctx"

    def test_explicit_owner_wins_over_ctx(self):
        from tuan_cli.runtime.acp.bridge import KernelAcpBridge

        class Ctx:
            session_owner = "sess-ctx"

        class Agent:
            ctx = Ctx()

        b = KernelAcpBridge(owner="sess-explicit")
        b._agent = Agent()
        assert b._resolve_owner() == "sess-explicit"

    def test_fallback_to_contextvar_when_no_handle(self):
        from tuan_cli.runtime.acp.bridge import KernelAcpBridge
        tok = set_session_owner("sess-fallback")
        try:
            assert KernelAcpBridge()._resolve_owner() == "sess-fallback"
        finally:
            reset_session_owner(tok)

    def test_bridge_constructor_accepts_owner(self):
        from tuan_cli.runtime.acp.bridge import KernelAcpBridge
        sig = inspect.signature(KernelAcpBridge.__init__)
        assert "owner" in sig.parameters
        assert sig.parameters["owner"].default is None

    def test_ask_user_uses_resolve_owner(self):
        src = Path("tuan_cli/runtime/acp/bridge.py").read_text(
            encoding="utf-8")
        assert "_o = self._resolve_owner()" in src
        assert "def _resolve_owner(" in src
        # ask_user 主体里不再直接调用 current_session_owner()
        i = src.rindex("    async def ask_user")
        body = src[i:i + 1800]
        assert "current_session_owner()" not in body

    def test_no_auto_session_id_mapping(self):
        """如实边界：不按 session_id 自动派生 owner。"""
        src = Path("tuan_cli/runtime/acp/bridge.py").read_text(
            encoding="utf-8")
        assert "session_owner" in src          # 用显式 ctx 句柄
        assert "owner = self._session_id" not in src


# ================================================== P4 miss 统计
class TestOwnerMissStats:
    def test_bounded_with_other_bucket(self):
        """上界语义：最多 64 个具体 owner + 1 个 <other> = 65。"""
        for i in range(80):
            HookTrigger(owner="m-%d" % i).config_change(source="x")
        d = owner_miss_stats()
        assert len(d) <= 65
        assert "<other>" in d
        assert d["<other>"] >= 16

    def test_concurrent_bump_is_inside_lock(self):
        """P4：整个判定收进锁内；并发 24 线程不越界、不丢计数。"""
        barrier = threading.Barrier(24)

        def worker(i):
            barrier.wait()
            T._bump_owner_miss("c-%d" % i)

        ths = [threading.Thread(target=worker, args=(i,))
               for i in range(24)]
        for t in ths:
            t.start()
        for t in ths:
            t.join()
        d = owner_miss_stats()
        assert sum(d.values()) == 24
        assert len(d) == 24

    def test_bump_definition_is_lock_scoped(self):
        src = Path("tuan_cli/hooks/triggers.py").read_text(
            encoding="utf-8")
        i = src.index("def _bump_owner_miss")
        body = src[i:src.index("def owner_miss_stats")]
        assert body.index("with _SESSION_LOCK:") < body.index("key = owner")


# ================================================== P5 口径
class TestDocstringHonesty:
    def test_bind_docstring_says_two_singletons(self):
        """**B3 续轮 IX 同步（改强）**：窗口扩大并补 Q1b 早返回。

        IX 在 ``ok`` 之后插入「注册失败立即 return False」与注释，
        两个单例元组后移；同时新增的早返回必须在回填**之前**。
        """
        src = Path("tuan_cli/hooks/triggers.py").read_text(
            encoding="utf-8")
        i = src.index("def bind_session_hooks")
        body = src[i:i + 1700]
        assert "**2** 个模块级单例" in body
        assert "回填 3 个模块级单例" not in body
        assert '("security_alert"' in body
        assert '("remote_control"' in body
        assert body.index("if not ok:") < body.index('("security_alert"')
        assert "return False" in body

    def test_session_registry_rejected_is_documented(self):
        """**B3 续轮 IX 补强**：新增 ``conflicts``（同 owner 拒绝）可见。"""
        src = Path("tuan_cli/hooks/triggers.py").read_text(
            encoding="utf-8")
        assert "_SESSION_REJECTIONS" in src
        assert '"rejected": _SESSION_REJECTIONS' in src
        assert "_SESSION_CONFLICTS" in src
        assert '"conflicts": _SESSION_CONFLICTS' in src


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

    def test_single_slot_backfill_still_present(self):
        src = Path("tuan_cli/hooks/triggers.py").read_text(
            encoding="utf-8")
        assert "inst.hooks = hooks" in src

    def test_alert_owner_not_serialized(self):
        r = SA.AlertRecord(title="T", severity="low", owner="sess-A")
        assert "owner" not in r.to_dict()

    def test_previous_round_contracts_present(self):
        src = Path("tuan_cli/hooks/triggers.py").read_text(
            encoding="utf-8")
        assert "_REENTRY_LOCAL = threading.local()" in src
        assert "reentry_suppressed" in src
        assert "_MAX_SESSIONS = 64" in src
        assert "owner_not_registered" in src
        assert "_UNSET = object()" in src


# ================================================== 接线 / 矩阵
class TestWiringAndMatrix:
    def test_app_uses_activate_and_checks_active(self):
        """**B3 续轮 IX 同步（改强）**：ctx 改为事务化入参。

        VIII 由 app.py 手动把 owner/handle 挂到 ``agent.ctx``；IX 实测
        注册失败时这会造成 ctx 残留（Q4），故改由 ``activate_session``
        在**注册成功后**挂载、由 ``deactivate_session`` 精确清理。
        """
        src = Path("tuan_cli/app.py").read_text(encoding="utf-8")
        assert "activate_session(" in src
        assert "provider=default_hooks_resolver" in src
        assert "getattr(getattr(agent" not in src
        assert "hooks=agent.ctx.hooks" in src
        assert "ctx=agent.ctx" in src              # 事务化挂载
        assert "if not _handle.active:" in src
        assert "logger.warning(" in src
        assert "config._hooks = agent.ctx.hooks" in src
        # app.py 不再手动挂载（失败路径会留脏 ctx）
        assert "agent.ctx.session_owner =" not in src
        assert "agent.ctx.session_handle = _handle" not in src
        # 旧的分散调用已收进 activate_session（只看**代码行**：历史
        # 注释里仍写着 set_default_hooks_provider(A)/(B)，不算调用）
        code = "\n".join(l.strip() for l in src.splitlines()
                          if not l.strip().startswith("#"))
        assert "set_default_hooks_provider(" not in code
        assert "bind_session_hooks(agent.ctx.hooks" not in code
        assert "set_session_owner(_session_owner)" not in code

    def test_lifecycle_api_exported(self):
        """**B3 续轮 IX 补强**：新增 ``session_scope`` 上下文管理器。"""
        import tuan_cli.hooks as pkg
        for n in ("activate_session", "deactivate_session",
                  "SessionHandle", "session_scope"):
            assert hasattr(pkg, n), n

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

    def test_agent_sessions_wired_and_host_scope_corrected(self):
        """**B3 续轮 X 同步（改强 + 纠偏）**。

        IX 断言「只有 cmd_chat 1 处宿主接线，ACP server / web /
        stream_json / TUI.close 逐一锁住未接」。X 实测发现这个口径**过宽**：
        ``tui.py`` / ``runtime/acp/session.py`` / ``runtime/acp/server.py``
        的 ``create_agent`` 调用点都是 **0**，它们根本不是会话宿主，
        「没接 deactivate」不构成缺陷。真正产生 session handle 的是
        **9 个 create_agent 调用方**。

        X 把关闭逻辑上提成公共 ``close_agent_session``，并接上
        CLI 主路径 + 3 个高频短命子 agent + headless（共 5 处）。
        仍**不**宣称全部宿主已覆盖：cmd_acp / web / ACP bridge
        三个长驻宿主未接；两个独立子进程退出即清空，判定不该修。
        """
        import re

        src = Path("tuan_cli/app.py").read_text(encoding="utf-8")
        assert "ctx=agent.ctx" in src
        assert "provider=default_hooks_resolver" in src
        chat = Path("tuan_cli/cli/cmd_chat.py").read_text(
            encoding="utf-8")
        assert "_close_agent_session(" in chat
        assert "close_agent_session(agent)" in chat
        assert chat.count("_close_agent_session(") == 3  # 1 定义 + 2 调用
        assert "deactivate_session(handle)" not in chat
        # SessionEnd 钩子在注销**之前**（钩子还要用 ctx.hooks）
        for seg in chat.split("finally:")[1:3]:
            assert seg.index("_run_session_hooks(") < seg.index(
                "_close_agent_session(")

        # 公共入口已导出且只有一个定义
        init = Path("tuan_cli/hooks/__init__.py").read_text(
            encoding="utf-8")
        assert '"close_agent_session"' in init
        trig = Path("tuan_cli/hooks/triggers.py").read_text(
            encoding="utf-8")
        assert "def close_agent_session(" in trig
        assert "def default_hooks_resolver(" in trig

        # 5 处显式接线（排除定义 / import / 注释行）
        wired = {
            "tuan_cli/cli/cmd_chat.py",
            "tuan_cli/hooks/manager.py",
            "tuan_cli/tools/workflow_tool.py",
            "tuan_cli/tools/subagent_tool.py",
            "tuan_cli/stream_json/headless.py",
        }
        hits = set()
        for p in Path("tuan_cli").rglob("*.py"):
            if p.name == "triggers.py":
                continue
            for line in p.read_text(encoding="utf-8").splitlines():
                code = line.strip()
                if (code.startswith("#") or code.startswith("def ")
                        or code.startswith("from ")):
                    continue
                if "close_agent_session(" in code and \
                        not code.startswith("def "):
                    hits.add(str(p))
        assert hits == wired, (hits ^ wired)
        # 关闭必须在 finally 里（异常路径也释放）
        for rel in ("tuan_cli/hooks/manager.py",
                    "tuan_cli/tools/workflow_tool.py",
                    "tuan_cli/tools/subagent_tool.py"):
            s = Path(rel).read_text(encoding="utf-8")
            assert "finally:" in s and "close_agent_session(" in s, rel

        # 三个长驻宿主如实未接（下一轮）
        for rel in ("tuan_cli/cli/cmd_acp.py",
                    "tuan_cli/web/server.py",
                    "tuan_cli/runtime/acp/bridge.py"):
            assert "close_agent_session(" not in Path(rel).read_text(
                encoding="utf-8"), rel
        # 两个独立子进程：退出即清空，判定不该修（回归锁住）
        for rel in ("tuan_cli/core/_sandbox_entry.py",
                    "tuan_cli/core/background_worker.py"):
            assert "close_agent_session(" not in Path(rel).read_text(
                encoding="utf-8"), rel

        # 纠偏：上轮点名的三个「宿主」其实 0 个 create_agent 调用点
        for rel in ("tuan_cli/tui/tui.py",
                    "tuan_cli/runtime/acp/session.py",
                    "tuan_cli/runtime/acp/server.py"):
            s = Path(rel).read_text(encoding="utf-8")
            n = sum(1 for l in s.splitlines()
                    if not l.strip().startswith("#")
                    and re.search(r"\bcreate_agent\s*\(", l))
            assert n == 0, (rel, n)
            assert "deactivate_session(" not in s, rel
