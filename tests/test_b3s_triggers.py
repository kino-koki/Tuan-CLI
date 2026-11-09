"""B3 续轮回归：5 个扩展事件的**生产触发点** + 决策语义 + 旁路契约。

=====  =====================================================================
编号   实测结果（修复前）
=====  =====================================================================
R1     上一轮 5 个扩展事件全部注册成功（``len(m._specs)==5``），但跑真实
       操作 ``Config.set_user`` / ``WorktreeLayer.create`` /
       ``_ask_user_handler`` / ``remote_control.notify`` 之后 hook 实际
       触发 **0 次**；全仓源码扫描 5 个派发点 **0 命中**。配置能加载、
       引擎能裁决，但没有任何生产代码调用它们。
R2     ``tuan hooks test --event PermissionRequest`` 走
       ``run_session`` → ``run_notify``，被上一轮的
       ``decision_event_misrouted`` 拒绝且静默不执行 —— CLI 测试入口对
       4 个决策类扩展事件全部失效（实测 audit 里只有一条 misrouted）。
R3     ``cmd_hooks.py`` 的 ``run_pre(tool, payload, dangerous=True)``
       不传 schema，手动测试入口的改参只走保守子集。
R4     上一轮给 ``arch/execution.py::ToolCall`` 加了 ``tool_schema``，
       但全仓**没有生产构造方**（只有测试构造 ``ToolPipeline``）；
       而且强行传 ``tool_schema=`` 会让老式 hook mock 的
       ``run_pre(name, args)`` 抛 ``TypeError``，实测 1 条既有测试失败。
=====  =====================================================================

**修复（如实，不夸大）**

- 新增 ``hooks/triggers.py``：5 个事件收敛成单一 ``HookTrigger`` 出口，
  通知类走 ``run_notify``、决策类走 ``run_decision``；无 hooks 严格
  no-op；用户显式配了 hook 但通道炸了 → **fail-closed**。
- 生产接线：``Config.set_user/delete_user`` 与
  ``ManagedSettings.reload`` → ConfigChange；
  ``WorktreeLayer.create/create_agent_worktree`` → WorktreeCreate（**可拒绝**）；
  ``_ask_user_handler`` + ACP ``ask_user`` → Elicitation / ElicitationResult
  （**可取消 / 作废，但绝不代答、绝不覆盖用户答案**）；
  ``remote_control.notify`` + ``SecurityAlerter`` 后台线程 → Notification。
  ``app.py`` 注入 default provider 给没有 ``agent.ctx`` 的子系统。
- ``cmd_hooks`` 决策类改走 ``run_decision``、``run_pre`` 传 schema；
  ``ToolPipeline`` 加 ``schema_resolver`` 且**只在有 schema 时**传关键字
  （兼容老式 mock，修 R4）。

**如实边界 / 矩阵**：``aligned 46 / partial 9 / gap 26``、
``fully_superior=false``、``b_waves_done=["B1"]`` **一个没动**。
两个 B3 catalog 条目仍 ``STATUS_GAP``：官方 hooks 参考的事件面远大于
7 个、CC exit-code-2 → decline 未实现、Elicitation 语义刻意不等价、
``ToolPipeline`` 无生产构造方。新增回归把计数逐项钉死。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from tuan_cli.hooks import (
    HookManager, HookTrigger, set_default_hooks_provider,
    get_default_hooks_provider, HOOK_EVENTS,
)

PY = sys.executable
EVENTS = ["ConfigChange", "WorktreeCreate", "Elicitation",
          "ElicitationResult", "Notification"]


class RecordingKernel:
    def __init__(self):
        self.events = []

    def get(self, name, default=None):
        return default

    def emit(self, topic, payload=None):
        self.events.append((topic, payload or {}))

    def on(self, *a, **k):
        pass

    def statuses(self):
        return [p.get("status", "") for t, p in self.events
                if t == "hook.executed"]


def _writer_hook(log: Path, obj: dict | None = None) -> dict:
    """把收到的 stdin JSON 追加到 log，再输出 obj（默认 '{}'）。"""
    payload = json.dumps(obj or {}, ensure_ascii=False)
    script = (
        "import json,sys,os,pathlib;"
        "d=json.loads(sys.stdin.read() or '{}');"
        "pathlib.Path(os.environ['B3S_LOG']).open('a',encoding='utf-8')"
        ".write(json.dumps(d,ensure_ascii=False)+'\\n');"
        "print(json.dumps(" + repr(json.loads(payload)) + ",ensure_ascii=False))"
    )
    return {"command": [PY, "-c", script]}


def _manager(log: Path, overrides: dict | None = None,
             kernel=None) -> HookManager:
    block = {"enabled": True, **{e: [_writer_hook(log)] for e in EVENTS}}
    block.update(overrides or {})
    return HookManager({"hooks": block}, workspace=str(log.parent),
                       kernel=kernel or RecordingKernel())


@pytest.fixture(autouse=True)
def _clean_provider():
    """每个用例前后都清掉 default provider，避免跨用例污染。"""
    set_default_hooks_provider(None)
    yield
    set_default_hooks_provider(None)


def _records(log: Path):
    if not log.exists():
        return []
    return [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines()
            if x.strip()]


# ================================================== 1 HookTrigger 单元
class TestTriggerUnit:
    def test_no_hooks_is_strict_no_op(self, tmp_path):
        t = HookTrigger()
        assert t.config_change(source="x") is False
        assert t.notification(title="x") is False
        for d in (t.worktree_create(name="n", path="p", branch="b"),
                  t.elicitation(question="q"),
                  t.elicitation_result(answer="a")):
            assert d.block is False
            assert d.reason == ""

    def test_explicit_hooks_beats_default_provider(self, tmp_path):
        calls = []

        class H:
            enabled = True
            def run_notify(self, e, p): calls.append(("explicit", e))
            def run_decision(self, e, tool_name="", payload=None):
                calls.append(("explicit", e)); return None

        class Default:
            enabled = True
            def run_notify(self, e, p): calls.append(("default", e))
            def run_decision(self, e, tool_name="", payload=None):
                calls.append(("default", e)); return None

        set_default_hooks_provider(lambda: Default())
        t = HookTrigger(H())
        t.config_change(source="x")
        t.worktree_create(name="n", path="p", branch="b")
        assert [c[0] for c in calls] == ["explicit", "explicit"]

    def test_default_provider_is_used_when_no_explicit(self, tmp_path):
        calls = []

        class H:
            enabled = True
            def run_notify(self, e, p): calls.append(e)

        set_default_hooks_provider(lambda: H())
        assert HookTrigger().config_change(source="x") is True
        assert calls == ["ConfigChange"]
        assert get_default_hooks_provider() is not None

    def test_provider_exception_is_treated_as_no_hooks(self):
        def boom(): raise RuntimeError("provider down")
        set_default_hooks_provider(boom)
        assert HookTrigger().config_change(source="x") is False
        assert HookTrigger().worktree_create(
            name="n", path="p", branch="b").block is False

    def test_notify_exception_never_raises(self):
        class H:
            enabled = True
            def run_notify(self, e, p): raise RuntimeError("hook exploded")
        assert HookTrigger(H()).notification(title="x") is False

    def test_decision_channel_exception_fails_closed(self):
        """用户显式配了 hook 但裁决通道炸了 → block，不放行。"""
        class H:
            enabled = True
            def run_decision(self, e, tool_name="", payload=None):
                raise RuntimeError("decision exploded")
        d = HookTrigger(H()).worktree_create(name="n", path="p", branch="b")
        assert d.block is True
        assert d.failure_kind == "trigger_error"
        assert "RuntimeError" in d.reason

    def test_legacy_mock_without_run_decision_fails_closed(self):
        class OldMock:
            enabled = True
            def run_notify(self, e, p): pass
        d = HookTrigger(OldMock()).elicitation(question="q")
        assert d.block is True and d.failure_kind == "trigger_error"

    def test_run_decision_returning_none_fails_closed(self):
        class H:
            enabled = True
            def run_decision(self, e, tool_name="", payload=None): return None
        assert HookTrigger(H()).elicitation_result(answer="a").block is True

    def test_disabled_hooks_is_no_op(self):
        class H:
            enabled = False
            def run_notify(self, e, p): raise AssertionError("must not run")
            def run_decision(self, e, tool_name="", payload=None):
                raise AssertionError("must not run")
        assert HookTrigger(H()).config_change(source="x") is False
        assert HookTrigger(H()).worktree_create(
            name="n", path="p", branch="b").block is False


# ================================================== 2 五个事件端到端真的触发
class TestEndToEndTriggers:
    def test_five_events_fire_on_real_operations(self, tmp_path, monkeypatch):
        log = tmp_path / "fired.jsonl"
        monkeypatch.setenv("B3S_LOG", str(log))
        m = _manager(log)
        set_default_hooks_provider(lambda: m)

        # --- ConfigChange: 真实 Config.set_user ---
        from tuan_cli.config.loader import Config
        c = Config(bare=True, hooks=m)
        c.home = tmp_path
        c.user_config_path = tmp_path / "config.yaml"
        c.set_user("demo.value", 42)
        c.delete_user("demo.value")

        # --- WorktreeCreate: 真 git repo，hook 输出 {} 不阻断 ---
        ws = tmp_path / "repo"; ws.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=ws, check=True,
                       capture_output=True)
        subprocess.run(["git", "config", "user.email", "t@t.local"], cwd=ws,
                       check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "t"], cwd=ws,
                       check=True, capture_output=True)
        (ws / "seed.txt").write_text("x", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=ws, check=True,
                       capture_output=True)
        subprocess.run(["git", "commit", "-qm", "init"], cwd=ws, check=True,
                       capture_output=True)
        from tuan_cli.core.worktree_layer import WorktreeLayer
        WorktreeLayer(ws, hooks=m).create("probe")

        # --- Elicitation + ElicitationResult: 真实 ask_user handler ---
        from tuan_cli.tools.session_tools import _ask_user_handler
        seen = []

        class UI:
            def ask_user(self, q, opts):
                seen.append((q, list(opts)))
                return "是"

        out = _ask_user_handler(
            SimpleNamespace(ui=UI(), hooks=m),
            question="要继续吗?", options=["是", "否"])
        assert "用户回答: 是" in out

        # --- Notification: 真实 remote_control.notify ---
        from tuan_cli.core import remote_control
        monkeypatch.setattr(remote_control, "_shared_rc", lambda: None)
        remote_control.notify("探针", "正文", kind="info")

        recs = _records(log)
        fired = [r.get("hook_event_name") for r in recs]
        print("\n  fired:", fired)
        for e in EVENTS:
            assert e in fired, f"{e} 仍未触发；实际={fired}"
        assert len(seen) == 1  # 提问确实发生了（hook 没有代答）

        # payload 字段抽查
        cc = next(r for r in recs if r["hook_event_name"] == "ConfigChange")
        assert cc["key"] == "demo.value" and cc["source"] == "user_config"
        wc = next(r for r in recs if r["hook_event_name"] == "WorktreeCreate")
        assert wc["name"] == "probe"
        er = next(r for r in recs if r["hook_event_name"] == "ElicitationResult")
        assert er["answer"] == "是" and er["action"] == "accept"
        nt = next(r for r in recs if r["hook_event_name"] == "Notification")
        assert nt["title"] == "探针" and nt["message"] == "正文"

    def test_configchange_also_fires_on_managed_reload(self, tmp_path,
                                                       monkeypatch):
        log = tmp_path / "reload.jsonl"
        monkeypatch.setenv("B3S_LOG", str(log))
        m = _manager(log)
        from tuan_cli.config.managed import ManagedSettings
        ms = ManagedSettings(tmp_path, hooks=m)
        ms.reload()
        recs = [r for r in _records(log)
                if r.get("hook_event_name") == "ConfigChange"]
        assert len(recs) == 1
        assert recs[0]["origin"] == "reload"

    def test_notification_does_not_change_notify_return_value(self, tmp_path,
                                                              monkeypatch):
        log = tmp_path / "n.jsonl"
        monkeypatch.setenv("B3S_LOG", str(log))
        m = _manager(log)
        set_default_hooks_provider(lambda: m)
        from tuan_cli.core import remote_control
        monkeypatch.setattr(remote_control, "_shared_rc", lambda: None)
        assert remote_control.notify("t", "b") is False
        assert any(r["hook_event_name"] == "Notification"
                   for r in _records(log))


# ================================================== 3 决策类语义（不代答）
class TestDecisionSemantics:
    def _deny_hook(self, log: Path) -> dict:
        return _writer_hook(log, {"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": "策略禁止"}})

    def test_worktree_create_deny_blocks_before_any_fs_change(
            self, tmp_path, monkeypatch):
        log = tmp_path / "d.jsonl"
        monkeypatch.setenv("B3S_LOG", str(log))
        mgr = HookManager({"hooks": {
            "enabled": True,
            "WorktreeCreate": [self._deny_hook(log)]}},
            workspace=str(tmp_path), kernel=RecordingKernel())
        ws = tmp_path / "repo"; ws.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=ws, check=True,
                       capture_output=True)
        from tuan_cli.core.worktree_layer import WorktreeLayer, WorktreeError
        with pytest.raises(WorktreeError) as ei:
            WorktreeLayer(ws, hooks=mgr).create("blocked")
        assert "WorktreeCreate Hook 阻断" in str(ei.value)
        assert "策略禁止" in str(ei.value)
        assert not (ws / ".tuan" / "worktrees").exists(), \
            "拒绝后不该创建任何目录"
        assert log.exists()  # hook 确实执行了

    def test_elicitation_deny_cancels_question_without_asking(
            self, tmp_path, monkeypatch):
        log = tmp_path / "e.jsonl"
        monkeypatch.setenv("B3S_LOG", str(log))
        mgr = HookManager({"hooks": {
            "enabled": True,
            "Elicitation": [self._deny_hook(log)]}},
            workspace=str(tmp_path), kernel=RecordingKernel())
        from tuan_cli.tools.session_tools import _ask_user_handler
        seen = []

        class UI:
            def ask_user(self, q, opts):
                seen.append(q); return "是"

        out = _ask_user_handler(SimpleNamespace(ui=UI(), hooks=mgr),
                                question="继续?", options=["是"])
        assert "取消提问" in out and "策略禁止" in out
        assert seen == [], "block 后绝不能还去问用户"
        assert not any(r["hook_event_name"] == "ElicitationResult"
                       for r in _records(log))

    def test_elicitation_result_deny_voids_answer(self, tmp_path,
                                                  monkeypatch):
        log = tmp_path / "er.jsonl"
        monkeypatch.setenv("B3S_LOG", str(log))
        block = {"enabled": True,
                 "Elicitation": [_writer_hook(log)],
                 "ElicitationResult": [self._deny_hook(log)]}
        mgr = HookManager({"hooks": block}, workspace=str(tmp_path),
                          kernel=RecordingKernel())
        from tuan_cli.tools.session_tools import _ask_user_handler

        class UI:
            def ask_user(self, q, opts): return "是"

        out = _ask_user_handler(SimpleNamespace(ui=UI(), hooks=mgr),
                                question="继续?", options=["是"])
        assert "作废本次回答" in out
        assert "用户回答: 是" not in out

    def test_hook_allow_does_not_become_the_answer(self, tmp_path,
                                                   monkeypatch):
        """CC 允许 Elicitation hook 代答；Tuan 刻意不等价 —— 模型不能自问自答。"""
        log = tmp_path / "a.jsonl"
        monkeypatch.setenv("B3S_LOG", str(log))
        mgr = HookManager({"hooks": {
            "enabled": True,
            "Elicitation": [_writer_hook(log, {"hookSpecificOutput": {
                "permissionDecision": "allow",
                "permissionDecisionReason": "我想替用户回答"}})]}},
            workspace=str(tmp_path), kernel=RecordingKernel())
        from tuan_cli.tools.session_tools import _ask_user_handler

        class UI:
            def ask_user(self, q, opts): return "用户真的选了否"

        out = _ask_user_handler(SimpleNamespace(ui=UI(), hooks=mgr),
                                question="继续?", options=["是", "否"])
        assert "用户真的选了否" in out
        assert "我想替用户回答" not in out

    def test_worktree_create_hook_failure_fails_closed(self, tmp_path):
        """hook 二进制不存在 → B1 fail-closed → 拒绝创建。"""
        mgr = HookManager({"hooks": {
            "enabled": True,
            "WorktreeCreate": [{"command": ["missing_hook_binary_b3s_xyz"]}]}},
            workspace=str(tmp_path), kernel=RecordingKernel())
        ws = tmp_path / "repo"; ws.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=ws, check=True,
                       capture_output=True)
        from tuan_cli.core.worktree_layer import WorktreeLayer, WorktreeError
        with pytest.raises(WorktreeError) as ei:
            WorktreeLayer(ws, hooks=mgr).create("x")
        assert "WorktreeCreate Hook 阻断" in str(ei.value)
        assert "spawn_error" in str(ei.value)


# ================================================== 4 不该修 / 契约边界
class TestNotChangedOnPurpose:
    def test_headless_downgrade_does_not_fire_elicitation_result(
            self, tmp_path, monkeypatch):
        """没有真实用户响应 → 不派发 ElicitationResult（如实）。"""
        log = tmp_path / "h.jsonl"
        monkeypatch.setenv("B3S_LOG", str(log))
        m = _manager(log)
        from tuan_cli.tools.session_tools import _ask_user_handler
        out = _ask_user_handler(SimpleNamespace(ui=None, hooks=m),
                                question="继续?", options=["是"])
        assert "无法交互" in out
        fired = [r["hook_event_name"] for r in _records(log)]
        assert "Elicitation" in fired
        assert "ElicitationResult" not in fired

    def test_no_hooks_keeps_legacy_behavior(self, tmp_path):
        """没配 hooks 时 ask_user / Config / notify 行为零变化。"""
        from tuan_cli.tools.session_tools import _ask_user_handler

        class UI:
            def ask_user(self, q, opts): return "原样答案"
        out = _ask_user_handler(SimpleNamespace(ui=UI(), hooks=None),
                                question="继续?")
        assert "用户回答: 原样答案" in out

    def test_hook_channel_failure_does_not_break_config_write(self, tmp_path):
        """Config.set_user 必须仍然写成功，即使 hook 通道炸了。"""
        class Bad:
            enabled = True
            def run_notify(self, e, p): raise RuntimeError("boom")
        from tuan_cli.config.loader import Config
        c = Config(bare=True, hooks=Bad())
        c.home = tmp_path
        c.user_config_path = tmp_path / "config.yaml"
        c.set_user("demo.value", 7)
        assert c.get("demo.value") == 7

    def test_event_classification_not_mixed(self):
        """通知类走 run_notify、决策类走 run_decision —— 上一轮 R2 的坑。"""
        src = Path("tuan_cli/hooks/triggers.py").read_text(encoding="utf-8")
        assert 'self._notify("ConfigChange"' in src
        assert 'self._notify("Notification"' in src
        assert '"WorktreeCreate",' in src
        assert 'self._decide(\n            "Elicitation",' in src
        assert 'self._decide(\n            "ElicitationResult",' in src


# ================================================== 5 旁路 / CLI 接线
class TestSidePaths:
    def test_cmd_hooks_routes_decision_events(self):
        src = Path("tuan_cli/cli/cmd_hooks.py").read_text(encoding="utf-8")
        assert 'mgr.run_decision(event, tool_name=tool,' in src
        assert 'elif event in ("PermissionRequest", "WorktreeCreate",' in src
        assert "mgr.run_session(event" not in src

    def test_cmd_hooks_passes_schema(self):
        src = Path("tuan_cli/cli/cmd_hooks.py").read_text(encoding="utf-8")
        assert "tool_schema=schema" in src
        assert "保守子集 (enforced=False)" in src

    def test_tool_pipeline_keeps_legacy_mock_compatible(self):
        """R4：老式 run_pre(name, args) 不接受 tool_schema，无 schema 时不传。"""
        from tuan_cli.arch.execution import ToolPipeline, ToolCall, LoopContext
        calls = []

        class FakeHooks:
            def run_pre(self, name, args):
                calls.append((name, args)); raise PermissionError("blocked")

        p = ToolPipeline(hooks=FakeHooks())
        out = p.run(ToolCall(name="write", args={}), LoopContext(goal="t"))
        assert out.ok is False and "hook-pre-blocked" in out.error
        assert calls == [("write", {})]

    def test_tool_pipeline_resolver_supplies_schema(self):
        from tuan_cli.arch.execution import ToolPipeline, ToolCall, LoopContext
        seen = {}

        class FakeHooks:
            def run_pre(self, name, args, tool_schema=None):
                seen["schema"] = tool_schema
                return SimpleNamespace(block=False, reason="", args=None)

        schema = {"type": "object", "properties": {"path": {"type": "string"}},
                  "required": ["path"]}
        p = ToolPipeline(hooks=FakeHooks(), schema_resolver=lambda n: schema)
        p.run(ToolCall(name="write", args={}), LoopContext(goal="t"))
        assert seen["schema"] is schema

    def test_tool_pipeline_has_no_production_constructor(self):
        """如实边界：ToolPipeline 只在测试里构造，schema_resolver 是契约补齐。"""
        hits = [str(f) for f in Path("tuan_cli").rglob("*.py")
                if "ToolPipeline(" in f.read_text(encoding="utf-8",
                                                  errors="replace")]
        assert hits == []

    def test_app_injects_default_provider(self):
        """**B3 续轮 VIII 同步（改强）**：provider 注入收进 activate_session。

        B3 两轮前这里检查分散的 ``set_default_hooks_provider`` 与单行
        lambda；VIII 把四步合成 ``activate_session(owner=, hooks=,
        provider=)`` 并返回可关闭句柄。断言改为：入口、provider 参数、
        ctx 显式挂载、``active`` 失败可见；lambda 仍 must 存在（换成
        多行写法后按 token 检查）。
        """
        src = Path("tuan_cli/app.py").read_text(encoding="utf-8")
        assert "activate_session(" in src
        assert "provider=lambda: getattr(" in src
        assert 'getattr(agent, "ctx", None)' in src
        assert "hooks=agent.ctx.hooks" in src
        assert "agent.ctx.session_handle = _handle" in src
        assert "if not _handle.active:" in src


# ================================================== 6 矩阵自洽（一个不动）
class TestMatrixHonesty:
    def test_counts_unchanged(self):
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

    def test_two_b3_entries_still_gap(self):
        """5 个触发点接上了，但两个条目仍 GAP —— 不靠改口径凑数。"""
        src = Path("tuan_cli/parity_claude/catalog.py").read_text(
            encoding="utf-8")
        for key in ("hook_events_extended", "hook_updated_input_validation"):
            i = src.index('M("%s"' % key)
            assert "STATUS_GAP" in src[i:i + 400], key
        assert "5 个触发点" in src or "触发点已接" in src

    def test_event_table_still_15(self):
        assert len(HOOK_EVENTS) == 15
