"""B3 续轮 V：接线**之后**的第二层 —— 写盘成败、重入递归、分类真值、串台可见性。

上一轮把 5 个扩展事件接上了生产触发点。本轮不扩广度，只问一句：
**「接上之后，它会不会在错误的时候派发 / 派发到错误的会话 / 无限派发？」**

=====  =====================================================================
编号   实测结果（修复前）
=====  =====================================================================
C1     ``Config.set_user`` 把 ``user_config_path`` 指向一个目录 →
       ``dump_yaml`` 内部 ``os.replace`` 抛 ``IsADirectoryError`` 并**吞掉**，
       返回 None；``set_user`` 照旧派发 ``ConfigChange``。实测磁盘上
       **没有文件**，hook 却收到「配置已变更」。这与上一轮在
       ``ManagedSettings.reload`` 写下的「失败不派发，否则外部 hook 会
       误以为配置已生效」**直接矛盾**。
C2     in-process hook 的 ``run_notify`` 里再调 ``Config.set_user`` →
       实测递归 **247 层**，且 ``dump_yaml`` 把 ``RecursionError`` 也吞掉：
       stderr 出现「配置写入失败 ... maximum recursion depth exceeded」，
       但每一层仍继续派发，既不报错也不停止。
C3     上一轮的 ``test_event_classification_not_mixed`` 只检查
       ``triggers.py`` 自己的字符串，**没有**核对 ``manager.py`` 的真实
       ``_NOTIFY_EVENTS`` / ``_DECISION_EVENTS`` 集合 —— 若引擎把
       Elicitation 归成 notify，刚接的触发点会静默失效而测试全绿。
C4     两次 ``set_default_hooks_provider(A)/(B)`` 之后，先用 A 构造的
       ``HookTrigger`` 派发 **A 零触发、B 收到 A 的事件** —— 进程级
       provider 是单会话假设，多会话静默串台。
C5/C6  Notification payload 含正文但不含配置 value；``delete_user``
       返回 False 时不派发。这两条上一轮已正确，**不该修**，本轮只锁住。
=====  =====================================================================

**修复（如实，不夸大）**

- ``dump_yaml`` 拆出单一实现 ``_dump_yaml_impl``，新增
  ``dump_yaml_checked`` 如实返回落盘成败；**``dump_yaml`` 仍返回 None、
  仍吞异常，行为逐值不变**（全仓既有调用方忽略返回值）。
  ``Config.set_user/delete_user`` 只在 ``ok`` 时派发，并暴露
  ``last_write_persisted`` 供诊断。刻意**不回读比对值**：safe_dump /
  safe_load 的序列化差异会造成假阴性，且会引入「判定依赖文件系统
  时间点」的缓存 —— 与前几轮拒绝给活性判定加文件系统缓存同一理由。
- ``HookTrigger`` 加 **thread-local 重入守卫**：同线程同事件重入，
  通知类直接跳过并计数，决策类 **fail-closed** 返回
  ``failure_kind="reentry_suppressed"``（绝不返回空决策放行，否则
  递归会变成安全绕过）。``try/finally`` 清理，异常后同事件仍可派发。
  跨进程 command hook **不需要**守卫：子进程不继承父进程 thread-local，
  天然不会形成这条递归链 —— 如实标注，不夸大覆盖面。
- ``app.py`` 把 ``config._hooks`` **显式回填**为本会话 hooks：Config
  构造最早、生命周期最长，此前只能靠全局 fallback，是 C4 的主链路。
  ``/worktree`` 与 ``ask_user`` 上一轮已显式传 hooks。模块级
  ``remote_control.notify`` / ``SecurityAlerter`` 后台线程仍用全局
  fallback —— **串台未被消除，只变成可诊断**（``provider_diagnostics()``
  暴露 owner / generation / overrides）。真正多会话隔离需上游给这些
  模块级入口显式传 owner，本轮不改 5 个子系统签名以免把接线变脆。

**矩阵一个状态没动**：``aligned 46 / partial 9 / gap 26``、
``fully_superior=false``、``b_waves_done=["B1"]``；两个 B3 条目仍
``STATUS_GAP``。``catalog.py`` **本轮零改动** —— 它的 note 没说错，
只是没提本轮的正确性修复，不为了让文档变长去碰它。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from tuan_cli.config.loader import Config, dump_yaml, dump_yaml_checked
from tuan_cli.hooks import (
    HookTrigger, set_default_hooks_provider, get_default_hooks_provider,
    provider_diagnostics, HOOK_EVENTS,
)
from tuan_cli.hooks.manager import HookDecision, _NOTIFY_EVENTS, _DECISION_EVENTS

PY = sys.executable


class Rec:
    """最小 in-process hook：记录派发，不执行子进程。"""

    enabled = True

    def __init__(self, name: str = "r"):
        self.name = name
        self.fired: list = []

    def run_notify(self, event, payload):
        self.fired.append((event, dict(payload)))

    def run_decision(self, event, tool_name="", payload=None):
        self.fired.append((event, dict(payload or {})))
        return HookDecision()


@pytest.fixture(autouse=True)
def _reset_provider():
    set_default_hooks_provider(None)
    yield
    set_default_hooks_provider(None)


def _cfg(tmp_path: Path, hooks=None, name: str = "config.yaml") -> Config:
    c = Config(bare=True, hooks=hooks)
    c.home = tmp_path
    c.user_config_path = tmp_path / name
    return c


def _diag_delta(before: dict, kind: str) -> int:
    return provider_diagnostics()["reentry"][kind] - before["reentry"][kind]


# ================================================== C1 写盘成败
class TestWritePersistence:
    def test_failed_write_does_not_dispatch_configchange(self, tmp_path):
        """C1 主缺陷：磁盘没写成，绝不告诉 hook「配置已生效」。"""
        (tmp_path / "a_directory").mkdir()
        r = Rec()
        c = _cfg(tmp_path, r, "a_directory")
        c.set_user("demo.key", 99)
        assert not (tmp_path / "a_directory" / "config.yaml").exists()
        assert c.last_write_persisted is False
        assert r.fired == [], "写盘失败不该派发 ConfigChange"
        # 内存视图仍更新（既有行为，本轮不扩大改动面）
        assert c.get("demo.key") == 99

    def test_successful_write_dispatches(self, tmp_path):
        r = Rec()
        c = _cfg(tmp_path, r)
        c.set_user("demo.key", 7)
        assert c.last_write_persisted is True
        assert (tmp_path / "config.yaml").exists()
        assert [e for e, _ in r.fired] == ["ConfigChange"]
        assert r.fired[0][1]["key"] == "demo.key"
        assert r.fired[0][1]["origin"] == "set_user"

    def test_delete_only_dispatches_when_persisted(self, tmp_path):
        r = Rec()
        c = _cfg(tmp_path, r)
        c.set_user("x.y", 1)
        r.fired.clear()
        assert c.delete_user("x.y") is True
        assert c.last_write_persisted is True
        assert [e for e, _ in r.fired] == ["ConfigChange"]
        assert r.fired[0][1]["origin"] == "delete_user"
        # 删除不存在的键：不派发（上一轮契约）
        r.fired.clear()
        assert c.delete_user("no.such.key") is False
        assert r.fired == []

    def test_failed_delete_does_not_dispatch(self, tmp_path, monkeypatch):
        """删除命中、但写盘未落盘时不派发。

        A′ 自查：初版把 ``user_config_path`` 直接指向目录，结果
        ``_load_yaml`` 先读不到 ``x.y``，``delete_user`` 走的是
        「键不存在 → return False」分支，根本没走到写盘。改用
        monkeypatch 让写盘出口如实返回 False，才真正覆盖目标分支。
        set_user 的写盘失败由 C1 那个真实目录用例覆盖。
        """
        r = Rec()
        c = _cfg(tmp_path, r)
        c.set_user("x.y", 1)
        r.fired.clear()
        monkeypatch.setattr(
            "tuan_cli.config.loader.dump_yaml_checked",
            lambda *a, **k: False)
        assert c.delete_user("x.y") is True
        assert c.last_write_persisted is False
        assert r.fired == [], "删除未落盘不该派发 ConfigChange"

    def test_dump_yaml_behavior_is_byte_for_byte_unchanged(self, tmp_path):
        """既有出口仍返回 None、仍吞异常 —— 全仓调用方零感知。"""
        assert dump_yaml({"a": 1}, tmp_path / "ok.yaml") is None
        assert (tmp_path / "ok.yaml").exists()
        bad = tmp_path / "dir"
        bad.mkdir()
        assert dump_yaml({"a": 1}, bad) is None  # 不抛

    def test_checked_exit_reports_success_and_failure(self, tmp_path):
        assert dump_yaml_checked({"a": 1}, tmp_path / "ok.yaml") is True
        bad = tmp_path / "dir"
        bad.mkdir()
        assert dump_yaml_checked({"a": 1}, bad) is False

    def test_no_value_in_configchange_payload(self, tmp_path):
        """C5：ConfigChange 只带 key/source/origin，绝不把配置值送进 hook。"""
        r = Rec()
        c = _cfg(tmp_path, r)
        c.set_user("api.key", "ghp-should-not-leak")
        payload = r.fired[0][1]
        assert set(payload) == {"source", "key", "origin"}
        assert "ghp-should-not-leak" not in json.dumps(payload)

    def test_single_implementation_no_duplicated_write_logic(self):
        src = Path("tuan_cli/config/loader.py").read_text(encoding="utf-8")
        assert src.count("tempfile.mkstemp(") == 1
        assert "def _dump_yaml_impl(" in src
        assert "def dump_yaml_checked(" in src
        assert "dump_yaml(cfg, self.user_config_path)" not in src


# ================================================== C2 重入守卫
class TestReentryGuard:
    def test_notify_reentry_is_suppressed(self, tmp_path):
        """C2 主缺陷：in-process hook 里再写配置，只派发 1 次。"""
        before = provider_diagnostics()

        class Loop:
            enabled = True

            def __init__(self):
                self.n = 0

            def run_notify(self, event, payload):
                self.n += 1
                self.cfg.set_user("loop.x", self.n)  # 无限递归尝试

        loop = Loop()
        c = _cfg(tmp_path, loop, "loop.yaml")
        loop.cfg = c
        c.set_user("loop.x", 0)
        assert loop.n == 1
        assert c.last_write_persisted is True
        assert _diag_delta(before, "notify_suppressed") == 1

    def test_decision_reentry_fails_closed(self):
        """决策类重入绝不返回空决策放行 —— 否则递归变成安全绕过。"""
        before = provider_diagnostics()

        class Loop:
            enabled = True

            def __init__(self):
                self.n = 0
                self.trigger = None

            def run_decision(self, event, tool_name="", payload=None):
                self.n += 1
                return self.trigger.worktree_create(
                    name="inner", path="p", branch="b")

        loop = Loop()
        t = HookTrigger(loop)
        loop.trigger = t
        d = t.worktree_create(name="outer", path="p", branch="b")
        assert loop.n == 1
        assert d.block is True
        assert d.failure_kind == "reentry_suppressed"
        assert _diag_delta(before, "decision_suppressed") == 1

    def test_guard_is_released_after_exception(self):
        """try/finally 清理：hook 抛异常后，同事件仍可正常派发。"""
        class Flaky(Rec):
            def __init__(self):
                super().__init__()
                self.n = 0

            def run_notify(self, event, payload):
                self.n += 1
                if self.n == 1:
                    raise RuntimeError("first call fails")
                self.fired.append((event, dict(payload)))

        h = Flaky()
        t = HookTrigger(h)
        assert t.config_change(source="1") is False
        assert t.config_change(source="2") is True
        assert [p["source"] for _, p in h.fired] == ["2"]

    def test_different_threads_are_not_suppressed(self):
        """thread-local 而非全局 set：并发同事件是合法的。"""
        before = provider_diagnostics()

        class Slow(Rec):
            def run_notify(self, event, payload):
                import time
                time.sleep(0.05)
                super().run_notify(event, payload)

        h = Slow()
        results = []

        def worker(i):
            results.append(HookTrigger(h).config_change(source=str(i)))

        ts = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        assert all(results)
        assert len(h.fired) == 4
        assert _diag_delta(before, "notify_suppressed") == 0

    def test_cross_process_command_hook_has_no_inherited_threadlocal(self):
        """如实边界：command hook 是独立进程，不继承父线程 thread-local。

        这**不是**靠守卫保证的，而是进程边界天然成立。子进程里
        ``Config.set_user`` 没有注入 default provider，因此不会回环。
        """
        td = Path(tempfile.mkdtemp(prefix="b3v_child_"))
        script = (
            "import sys,os;sys.path.insert(0,os.environ['B3V_ROOT']);"
            "from pathlib import Path;"
            "from tuan_cli.config.loader import Config;"
            "c=Config(bare=True);"
            "c.home=Path(os.environ['B3V_HOME']);"
            "c.user_config_path=c.home/'child.yaml';"
            "c.set_user('child.key',1);"
            "print('CHILD_OK',c.last_write_persisted)"
        )
        # A′ 自查：初版给 c.home / user_config_path 赋值 str，
        # _load_yaml 调 path.exists() 直接 AttributeError。用 Path。
        env = dict(os.environ,
                   B3V_ROOT=str(Path(__file__).resolve().parents[1]),
                   B3V_HOME=str(td))
        p = subprocess.run([PY, "-c", script], capture_output=True,
                           text=True, timeout=60, env=env)
        assert p.returncode == 0, p.stderr
        assert "CHILD_OK True" in p.stdout
        assert (td / "child.yaml").exists()
        import shutil
        shutil.rmtree(td, ignore_errors=True)

    def test_reentry_stats_are_information_only(self):
        """计数是信息项，不参与任何裁决（与 evicted_total 同一处理）。"""
        d = provider_diagnostics()
        assert set(d["reentry"]) == {"notify_suppressed", "decision_suppressed"}
        assert isinstance(d["generation"], int)
        assert isinstance(d["overrides"], int)


# ================================================== C3 分类真值
class TestClassificationTruth:
    def test_triggers_classification_matches_manager_constants(self):
        """上一轮只查 triggers.py 字符串；这里核对引擎的真实集合。"""
        mapping = {
            "ConfigChange": "notify", "Notification": "notify",
            "WorktreeCreate": "decision", "Elicitation": "decision",
            "ElicitationResult": "decision",
        }
        for event, kind in mapping.items():
            if kind == "notify":
                assert event in _NOTIFY_EVENTS, event
                assert event not in _DECISION_EVENTS, event
            else:
                assert event in _DECISION_EVENTS, event
                assert event not in _NOTIFY_EVENTS, event
        src = Path("tuan_cli/hooks/triggers.py").read_text(encoding="utf-8")
        assert 'self._notify("ConfigChange"' in src
        assert 'self._notify("Notification"' in src
        for e in ("WorktreeCreate", "Elicitation", "ElicitationResult"):
            assert e in src

    def test_event_table_still_15(self):
        assert len(HOOK_EVENTS) == 15


# ================================================== C4 串台可见 + 显式绑定
class TestProviderDiagnostics:
    def test_overrides_are_visible_not_silent(self):
        """C4：**B3 续轮 VI 已修** —— 构造时冻结后 A 的 trigger 不再漂到 B。

        断言同步（改强，不是放宽）：上一轮这里如实锁住「串台仍存在」；
        本轮 HookTrigger 构造时冻结，同一场景变成 A 收到、B 零。
        ``overrides`` 仍须可见 —— 覆盖本身仍是诊断项，只是不再能
        改变已构造 trigger 的归属。
        """
        a, b = Rec("A"), Rec("B")
        set_default_hooks_provider(lambda: a, owner="session-A")
        t_a = HookTrigger()
        set_default_hooks_provider(lambda: b, owner="session-B")
        HookTrigger()
        t_a.config_change(source="from-A")
        assert len(a.fired) == 1 and b.fired == []
        d = provider_diagnostics()
        assert d["owner"] == "session-B"
        assert d["generation"] >= 2
        assert d["overrides"] >= 1
        assert d["installed"] is True

    def test_explicit_hooks_never_uses_global_provider(self):
        """app.py 回填 config._hooks 的契约：显式绑定不受覆盖影响。"""
        a, b = Rec("A"), Rec("B")
        set_default_hooks_provider(lambda: b, owner="session-B")
        HookTrigger(a).config_change(source="explicit-A")
        assert len(a.fired) == 1 and b.fired == []

    def test_config_explicit_hooks_wins(self, tmp_path):
        """Config 显式注入 hooks 时，default provider 完全不参与。"""
        a, b = Rec("A"), Rec("B")
        set_default_hooks_provider(lambda: b, owner="session-B")
        c = _cfg(tmp_path, a)
        c.set_user("x.y", 1)
        assert len(a.fired) == 1 and b.fired == []

    def test_app_backfills_config_hooks_and_passes_owner(self):
        """源码级断言：app.py 显式回填 + owner + **生命周期**（B3 续轮 VIII）。

        断言同步（改强）：VI 检查分散的 provider/bind 调用与顺序；VIII
        把四步收进 ``activate_session`` 并返回**可关闭句柄**，故改为
        检查单一入口、ctx 显式挂载、``active`` 失败可见，以及
        ``deactivate_session`` 已导出。顺序仍须保持 provider 先激活。
        """
        src = Path("tuan_cli/app.py").read_text(encoding="utf-8")
        assert "config._hooks = agent.ctx.hooks" in src
        assert '_session_owner = "agent:%x" % id(agent)' in src
        assert "activate_session(" in src
        assert "provider=default_hooks_resolver" in src
        # B3 续轮 X（R2）：共享无闭包 provider，app.py 不得再捕获 agent
        assert "getattr(getattr(agent" not in src
        assert "from .hooks.triggers import activate_session, default_hooks_resolver" in src
        assert "ctx=agent.ctx" in src   # IX：事务化挂载
        assert "agent.ctx.session_owner =" not in src
        assert "agent.ctx.session_handle = _handle" not in src
        assert "if not _handle.active:" in src   # 注册被拒不能静默
        import tuan_cli.hooks as pkg
        assert hasattr(pkg, "activate_session")
        assert hasattr(pkg, "deactivate_session")
        assert hasattr(pkg, "SessionHandle")
        # 顺序：provider 注入在会话激活**内部**完成，不再有分散调用。
        # 只看代码行：历史注释里仍写着 set_default_hooks_provider(A)/(B)。
        code = "\n".join(l.strip() for l in src.splitlines()
                          if not l.strip().startswith("#"))
        assert "set_default_hooks_provider(" not in code
        assert "bind_session_hooks(agent.ctx.hooks" not in code

    def test_provider_api_is_exported(self):
        import tuan_cli.hooks as pkg
        assert hasattr(pkg, "provider_diagnostics")
        assert get_default_hooks_provider() is None

    def test_module_level_notify_is_now_instance_bound(self):
        """**B3 续轮 VI 已修、VII 再补 owner 分桶**：模块级入口不再现场读全局。

        断言同步（改强）：VI 断言「实例级绑定」；VII 在此基础上再加
        **按 owner 分桶**解析（并发会话互不覆盖）与**后台线程显式携带
        owner**（contextvar 不跨线程）。无参 ``HookTrigger()`` 消费点
        仍为 0。
        """
        src = Path("tuan_cli/core/remote_control.py").read_text(
            encoding="utf-8")
        assert "_trig.notification(" in src
        assert 'getattr(_rc, "hooks", None)' in src
        assert "HookTrigger(owner=_owner)" in src
        assert "resolve_session(_owner)" in src
        assert "HookTrigger(_h)" in src
        assert "current_session_owner" in src
        assert "HookTrigger().notification(" not in src
        src2 = Path("tuan_cli/core/security_alert.py").read_text(
            encoding="utf-8")
        assert "_trig.notification(" in src2
        assert "HookTrigger(owner=_owner)" in src2
        assert "HookTrigger(self.hooks)" in src2
        # O4: 后台线程靠记录显式携带 owner（用 getattr 兼容旧记录）
        assert 'getattr(record, "owner", "")' in src2
        assert "owner=_owner" in src2
        assert "owner: str = \"\"" in src2
        assert "HookTrigger().notification(" not in src2
        src3 = Path("tuan_cli/runtime/acp/bridge.py").read_text(
            encoding="utf-8")
        assert "HookTrigger(self.hooks)" in src3
        assert "HookTrigger(owner=_o)" in src3
        assert "HookTrigger()" not in src3


# ================================================== 不该修 / 矩阵钉死
class TestNotChangedOnPurpose:
    def test_notification_payload_field_set(self):
        r = Rec()
        HookTrigger(r).notification(
            title="T", body="BODY", kind="info", severity="high",
            source="x")
        assert set(r.fired[0][1]) == {
            "title", "message", "kind", "severity", "source"}

    def test_no_hooks_is_still_strict_no_op(self):
        assert HookTrigger().config_change(source="x") is False
        assert HookTrigger().worktree_create(
            name="n", path="p", branch="b").block is False

    def test_hook_channel_failure_does_not_break_config_write(self, tmp_path):
        """hook 通道炸了，Config.set_user 仍必须写成功。"""
        class Bad:
            enabled = True

            def run_notify(self, e, p):
                raise RuntimeError("boom")

        c = _cfg(tmp_path, Bad())
        c.set_user("demo.value", 7)
        assert c.get("demo.value") == 7
        assert c.last_write_persisted is True

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
        """本轮 catalog.py 零改动 —— note 没说错，不为了文档变长去碰它。"""
        src = Path("tuan_cli/parity_claude/catalog.py").read_text(
            encoding="utf-8")
        for key in ("hook_events_extended", "hook_updated_input_validation"):
            i = src.index('M("%s"' % key)
            assert "STATUS_GAP" in src[i:i + 400], key
