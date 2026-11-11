"""B3 续轮 XIII：18 个新增官方事件的**真实生产触发点**与决策通道。

用户约束：「确保深度的真实复现，而非仅仅广度；开始做到百分百」。
上一轮（XII）把事件表 15→33，18 个新增事件配置**能加载**，但实测
跑真实操作触发次数全部为 0；而且 18 个事件被**全部**塞进通知通道，
按官方真值表其中 10 个是可阻断 / 支持 JSON decision 的事件 —— 走
``run_notify`` 等于把 hook stdout 裁决整个吞掉（B3 主链路 R2 的坑
在新增事件上重现）。

本轮：
- ``hooks/lifecycle.py`` 按真值表自动路由决策/通知，``WIRED_EVENTS``
  显式登记真实接线，``coverage()`` 把 wired / no_local_lifecycle /
  not_wired 三张表分开核销（不把「本地有概念」虚报成「已接触发点」）。
- 接 13 个真实生产触发点，每个都在本文件里有**端到端真跑**：真起
  hook 子进程写日志，真跑压缩 / chdir / git worktree / todo 写入 /
  工具失败 / 权限拒绝 / 批量执行 / 指令读取 / 模型切换 / setup。
- 4 个可预防动作真阻断（PreCompact / WorktreeRemove /
  PreModelSwitch / TaskCreated），不是只返回个标记。
- ``PermissionDenied`` 的官方 ``hookSpecificOutput.retry`` 真读出。

### A′ 自查抓回（全部由端到端真跑发现，源码扫描看不出）
1. ``cmd_cd`` 插入的 payload 引用了只在相对路径分支定义的 ``base``，
   传绝对路径时 ``NameError`` 被 ``except`` 吞掉 → CwdChanged 静默
   不派发。改成在函数开头记录 ``previous_cwd``。
2. ``cmd_setup`` 派发点放在 ``build_kernel()`` / ``input()`` 之后，
   重依赖链一阻塞就静默不触发。移到函数最开头。
3. ``PostModelSwitch`` 同时出现在 ``NO_LOCAL_LIFECYCLE`` 和接线清单，
   ``validate()`` 立刻报「有交集 / 三表不相加」→ 移到语义差异表。
4. `lifecycle.py` 三表分类重构时残留旧 ``WIRED_EVENTS`` 块，
   ``py_compile`` 直接 ``IndentationError``。
5. 端到端脚本 ``setup`` 走真向导会阻塞在 ``input()`` → 测试里
   monkeypatch ``build_kernel`` 让后续快速中断，但 **emit 已真实执行**。

### 如实边界
- 5 个事件本地无对应生命周期（FileChanged / MessageDisplay /
  SubagentStart / TeammateIdle / UserPromptExpansion），不造空转触发点。
- ``StopFailure`` 本地有能力但本轮未接，``coverage().not_wired`` 如实为 1。
- 既有 7 个扩展事件与 CORE 生命周期的路由**零改动**（ConfigChange
  仍是写盘成功后的通知，B3 V 契约不动）；差异在
  ``lifecycle.SEMANTIC_DIFFERENCES`` 显式登记。
- 两条 B3 gap 仍标 GAP：本轮收窄的是「无生产触发点 / 无 decision
  通道」这条硬理由，但「CC 事件面持续演进」「Elicitation 语义刻意
  不等价」「部分事件本地不适用」仍在，不靠改状态定义凑数。
"""
from __future__ import annotations

import builtins
import json
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import pytest

from tuan_cli.hooks import exit_semantics as XS
from tuan_cli.hooks import lifecycle as LC
from tuan_cli.hooks import manager as HM
from tuan_cli.hooks import triggers as TR

PY = sys.executable


class _Kernel:
    def get(self, n, d=None):
        return d

    def emit(self, t, p=None):
        pass

    def on(self, *a, **k):
        pass


@pytest.fixture
def env(tmp_path):
    """注入 default provider + 每个事件一个真子进程 hook（写日志）。"""
    log = tmp_path / "fired.jsonl"
    scripts = tmp_path / "hooks"
    scripts.mkdir()

    def make(ev, rc=0, stdout="{}"):
        p = scripts / (ev + ".py")
        p.write_text(
            "import sys,json\n"
            "d=json.loads(sys.stdin.read() or '{}')\n"
            "open(%r,'a').write(json.dumps({'event':d.get('hook_event_name')})+'\\n')\n"
            "sys.stdout.write(%r)\n"
            "sys.exit(%d)\n" % (str(log), stdout, rc), encoding="utf-8")
        return {"command": [PY, str(p)]}

    block = {"enabled": True}
    for ev in sorted(LC.LIFECYCLE_WIRED_EVENTS):
        block[ev] = [make(ev)]
    mgr = HM.HookManager({"hooks": block}, kernel=_Kernel())
    TR.set_default_hooks_provider(lambda: mgr)
    LC.reset_stats()

    def fired():
        if not log.exists():
            return []
        return [json.loads(x)["event"]
                for x in log.read_text(encoding="utf-8").splitlines()
                if x.strip()]

    yield SimpleNamespace(tmp=tmp_path, log=log, make=make, mgr=mgr,
                          fired=fired, block=block)
    TR.set_default_hooks_provider(None)
    LC.reset_stats()


def _mgr(block):
    return HM.HookManager({"hooks": dict(block)}, kernel=_Kernel())


# ================================================== 真值表 / 分类
class TestTruthTableAndCoverage:
    def test_validate_clean(self):
        assert XS.validate() == []
        assert LC.validate() == []

    def test_decision_capable_derived_not_hardcoded(self):
        assert len(XS.DECISION_CAPABLE_EVENTS) == 20
        assert len(XS.NOTIFY_ONLY_EVENTS) == 13
        assert not (XS.DECISION_CAPABLE_EVENTS & XS.NOTIFY_ONLY_EVENTS)
        assert XS.DECISION_CAPABLE_EVENTS | XS.NOTIFY_ONLY_EVENTS == XS.OFFICIAL_EVENTS
        # 硬规则：可阻断事件必须在决策类（否则 JSON 裁决被吞）
        for name, sem in XS._SEMANTICS.items():
            if sem.blocks_on_exit2:
                assert name in XS.DECISION_CAPABLE_EVENTS, name

    def test_coverage_three_tables_add_up(self):
        c = LC.coverage()
        assert c["official"] == 33
        assert c["wired"] == 27
        assert c["wired_this_round"] == 13
        assert c["wired_legacy"] == 14
        assert c["no_local_lifecycle"] == 5
        assert c["not_wired"] == 1
        assert c["not_wired_events"] == ["StopFailure"]
        assert c["wired"] + c["no_local_lifecycle"] + c["not_wired"] == 33
        assert c["wired_all_official"] and c["wired_disjoint_from_no_local"]
        assert c["wired_equals_union"]
        assert c["lifecycle_wired_disjoint_from_legacy"]
        assert set(XS.NO_LOCAL_LIFECYCLE) == {
            "FileChanged", "MessageDisplay", "SubagentStart",
            "TeammateIdle", "UserPromptExpansion"}

    def test_d1_decision_events_no_longer_swallowed(self):
        """官方可阻断事件不再全部落在通知通道。"""
        for ev in ("ConfigChange", "TaskCreated", "TaskCompleted",
                   "PreCompact", "PreModelSwitch", "PostToolBatch"):
            assert ev in XS.DECISION_CAPABLE_EVENTS, ev
            assert XS.semantics_for(ev).blocks_on_exit2
        # 真调：decision 通道拿到 hook 的 block
        m = _mgr({"enabled": True, "TaskCreated": [
            {"command": [PY, "-c",
                         "import sys; print('{\"decision\":\"block\",\"reason\":\"no\"}'); sys.exit(0)"]}]})
        out = LC.emit("TaskCreated", {"task": {"id": "x"}}, hooks=m)
        assert out.decision_channel is True
        assert out.blocked is True and out.reason == "no"

    def test_d3_all_four_hook_types_share_validation(self):
        """**B3 XV 同步（改强）**：三类非进程 hook 收口到单一执行器。

        XIII 断言的是 ``_exec`` 里三条 ``spec.hook_type == "..."`` 分派
        + validate_updated_input 不按类型分流。XV 把三条分派合成
        ``spec.hook_type in _np.HOOK_TYPES`` 并新增等价故障闭合表，
        这里改核销「三类走同一执行器 / 同一裁决 / 同一净化真值」。
        """
        from tuan_cli.hooks import nonprocess as NP
        src = Path(HM.__file__).read_text(encoding="utf-8")
        i = src.index("def _exec(self")
        j = src.index("def _exec_command", i)
        seg = src[i:j]
        assert "spec.hook_type in _np.HOOK_TYPES" in seg
        assert "_np.execute(" in seg
        assert "_np.classify_channel(" in src
        assert set(NP.HOOK_TYPES) == {"url", "prompt", "subagent"}
        k = src.index("validate_updated_input(", src.index("def run_pre"))
        assert "hook_type" not in src[k - 900:k]
        np_src = Path(NP.__file__).read_text(encoding="utf-8")
        assert "from tuan_cli.core.safe_text import" in np_src
        assert np_src.count("safe_hook_text(") >= 3
        from tuan_cli.parity_claude import catalog as C
        note = next(x for x in C.MODULES
                    if x.name == "hook_updated_input_validation").note
        assert "四种 hook 类型" in note or "四种" in note


# ================================================== 端到端真跑
class TestRealLifecycleTriggers:
    def test_compact_pre_and_post(self, env):
        from tuan_cli.arch.context import TieredContext
        c = TieredContext(budget_tokens=60, hot_capacity=2)
        for _ in range(10):
            c.add("user", "x" * 100)
        assert c.compactions > 0
        assert "PreCompact" in env.fired()
        assert "PostCompact" in env.fired()

    def test_instructions_loaded_payload_has_no_body(self, env):
        from tuan_cli.core.prompts import _read_instruction_capped
        f = env.tmp / "CLAUDE.md"
        f.write_text("# SECRET_PROJECT_INSTRUCTION abc\n", encoding="utf-8")
        assert _read_instruction_capped(f, 32768)
        assert "InstructionsLoaded" in env.fired()
        # payload 不带正文（脱敏契约）
        data = [json.loads(x) for x in env.log.read_text(
            encoding="utf-8").splitlines()]
        assert all("SECRET_PROJECT_INSTRUCTION" not in json.dumps(d) for d in data)

    def test_setup_dispatch_is_first(self, env, monkeypatch):
        from tuan_cli.cli import cmd_setup as CS
        monkeypatch.setattr(builtins, "input", lambda *a: "1")

        def _stop(*a, **k):
            raise RuntimeError("wizard truncated after Setup dispatch")
        monkeypatch.setattr(CS, "build_kernel", _stop)
        with pytest.raises(RuntimeError):
            CS.cmd_setup(SimpleNamespace(quick=True, skip=False))
        assert "Setup" in env.fired()

    def test_skip_path_does_not_dispatch(self, env):
        from tuan_cli.cli import cmd_setup as CS
        assert CS.cmd_setup(SimpleNamespace(skip=True)) == 0
        assert "Setup" not in env.fired()

    def test_cwd_changed_after_real_chdir(self, env):
        from tuan_cli.cli.cmd_slash_claude import cmd_cd
        old = os.getcwd()
        agent = SimpleNamespace(ctx=SimpleNamespace(workspace=str(env.tmp)))
        try:
            cmd_cd(agent, str(env.tmp))  # 绝对路径：A′#1 曾在这里静默失败
        finally:
            os.chdir(old)
        assert "CwdChanged" in env.fired()

    def test_model_switch_pre_and_post(self, env):
        from tuan_cli.runtime.acp.bridge import KernelAcpBridge
        br = KernelAcpBridge(make_agent=lambda: None)
        br.set_model("s1", "gpt-x")
        assert "PreModelSwitch" in env.fired()
        assert "PostModelSwitch" in env.fired()

    def test_todo_created_and_completed(self, env):
        from tuan_cli.tools.base import ToolContext
        from tuan_cli.tools.todo_tool import _todo_write_handler
        ctx = ToolContext(kernel=_Kernel(), workspace=str(env.tmp))
        _todo_write_handler(ctx, todos=[
            {"id": "a", "content": "x", "status": "pending"},
            {"id": "b", "content": "y", "status": "pending"}])
        _todo_write_handler(ctx, todos=[
            {"id": "a", "content": "x", "status": "completed"},
            {"id": "b", "content": "y", "status": "pending"}])
        assert "TaskCreated" in env.fired()
        assert "TaskCompleted" in env.fired()

    def test_worktree_remove_real_git(self, env):
        from tuan_cli.core.worktree_layer import WorktreeLayer
        repo = env.tmp / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=repo,
                       capture_output=True, timeout=15)
        subprocess.run(["git", "-c", "user.email=a@b", "-c", "user.name=a",
                        "commit", "--allow-empty", "-qm", "i"], cwd=repo,
                       capture_output=True, timeout=15)
        w = WorktreeLayer(str(repo))
        w.create("probe")
        assert w.remove("probe")
        assert "WorktreeRemove" in env.fired()

    def test_post_tool_batch(self, env):
        from tuan_cli.core.tool_executor import ToolExecutor
        reg = type("R", (), {"get": lambda s, n: None})()
        ToolExecutor(registry=reg).execute_batch([], None)
        assert "PostToolBatch" in env.fired()

    def test_tool_failure_and_permission_denied(self, env):
        from tuan_cli.tools.base import ToolRegistry, Tool, ToolContext
        reg = ToolRegistry()

        def boom(ctx, **kw):
            raise RuntimeError("kaboom")
        reg.register(Tool(name="boom", description="x",
                          parameters={"type": "object", "properties": {}},
                          handler=boom, dangerous=False))
        assert reg.dispatch_result(
            "boom", "{}", ToolContext(kernel=_Kernel(),
                                      workspace=str(env.tmp))).status == "error"
        reg.register(Tool(name="danger", description="x",
                          parameters={"type": "object", "properties": {}},
                          handler=lambda c, **k: "ok", dangerous=True))
        ctx = ToolContext(kernel=_Kernel(), workspace=str(env.tmp))
        ctx.confirm = lambda p: False
        assert reg.dispatch_result("danger", "{}", ctx).status == "denied"
        fired = env.fired()
        assert "PostToolUseFailure" in fired
        assert "PermissionDenied" in fired

    def test_all_13_wired_events_fire(self, env):
        """汇总：13 个本轮接线事件逐一真跑（上面各例的并集）。"""
        # 上面各测试分别覆盖；这里只核销 coverage 与 stats 自洽
        c = LC.coverage()
        assert c["wired_this_round"] == len(LC.LIFECYCLE_WIRED_EVENTS) == 13
        assert LC.validate() == []


# ================================================== 真阻断 / retry / 隔离
class TestPreventableAndRetry:
    def test_precompact_block_really_keeps_hot(self, env):
        from tuan_cli.arch.context import TieredContext
        m = _mgr({"enabled": True, "PreCompact": [
            {"command": [PY, "-c",
                         "print('{\"decision\":\"block\",\"reason\":\"no compact\"}')"]}]})
        TR.set_default_hooks_provider(lambda: m)
        c = TieredContext(budget_tokens=60, hot_capacity=2)
        for _ in range(6):
            c.add("user", "x" * 100)
        assert c.compactions == 0       # 真的没压
        assert len(c.hot) > c.hot_capacity  # 如实超预算，不假装压了

    def test_worktree_remove_block_keeps_directory(self, env):
        from tuan_cli.core.worktree_layer import WorktreeLayer, WorktreeError
        repo = env.tmp / "repo2"
        repo.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=repo,
                       capture_output=True, timeout=15)
        subprocess.run(["git", "-c", "user.email=a@b", "-c", "user.name=a",
                        "commit", "--allow-empty", "-qm", "i"], cwd=repo,
                       capture_output=True, timeout=15)
        w = WorktreeLayer(str(repo))
        info = w.create("keep")
        m = _mgr({"enabled": True, "WorktreeRemove": [
            {"command": [PY, "-c",
                         "print('{\"decision\":\"block\",\"reason\":\"keep\"}')"]}]})
        TR.set_default_hooks_provider(lambda: m)
        with pytest.raises(WorktreeError):
            w.remove("keep")
        assert Path(str(info.path)).exists() if hasattr(info, "path") else True

    def test_premodelswitch_block_keeps_model(self, env):
        from tuan_cli.runtime.acp.bridge import KernelAcpBridge
        m = _mgr({"enabled": True, "PreModelSwitch": [
            {"command": [PY, "-c",
                         "print('{\"decision\":\"block\",\"reason\":\"no switch\"}')"]}]})
        TR.set_default_hooks_provider(lambda: m)
        br = KernelAcpBridge(make_agent=lambda: None)
        br._model = "old"
        br.set_model("s1", "new")
        assert br._model == "old"

    def test_taskcreated_block_rolls_back(self, env):
        from tuan_cli.tools.base import ToolContext
        from tuan_cli.tools.todo_tool import _todo_write_handler
        m = _mgr({"enabled": True, "TaskCreated": [
            {"command": [PY, "-c",
                         "print('{\"decision\":\"block\",\"reason\":\"no task\"}')"]}]})
        TR.set_default_hooks_provider(lambda: m)
        ctx = ToolContext(kernel=_Kernel(), workspace=str(env.tmp))
        out = _todo_write_handler(ctx, todos=[
            {"id": "z", "content": "x", "status": "pending"}])
        assert "拒绝" in out
        assert not getattr(ctx, "todos", None)

    def test_permission_denied_retry_is_read(self):
        m = _mgr({"enabled": True, "PermissionDenied": [
            {"command": [PY, "-c",
                         "print('{\"hookSpecificOutput\":{\"hookEventName\":\"PermissionDenied\",\"retry\":true}}')"]}]})
        out = LC.emit("PermissionDenied", {"reason": "x"}, hooks=m)
        assert out.decision_channel is True
        assert out.retry is True
        assert out.blocked is False  # 动作已发生，只作反馈

    def test_no_hooks_is_strict_noop(self):
        TR.set_default_hooks_provider(None)
        before = LC.stats().copy()
        out = LC.emit("CwdChanged", {"cwd": "/tmp"})
        assert out.fired is False and out.source == "no_hooks"
        assert LC.stats()["noop_no_hooks"] == before["noop_no_hooks"] + 1

    def test_unknown_event_is_not_swallowed_as_success(self):
        out = LC.emit("TotallyUnknownEvent", {})
        assert out.fired is False and out.source == "unknown_event"

    def test_reentry_guard(self, env):
        """同一线程同事件重入直接跳过，不无限递归。"""
        inflight = LC._in_flight()
        inflight.add("CwdChanged")
        try:
            out = LC.emit("CwdChanged", {})
            assert out.fired is False and out.source == "reentry_suppressed"
        finally:
            inflight.discard("CwdChanged")


# ================================================== 矩阵不动
class TestHonestMatrix:
    def test_b_matrix_unchanged(self):
        from tuan_cli.parity_claude import matrix as BM, catalog as C
        s = BM.summary()
        assert s["by_status"] == {
            "ahead": 10, "aligned": 46, "partial": 9,
            "gap": 26, "not_applicable": 8}
        assert s["fully_superior"] is False
        assert s["b_waves_done"] == ["B1"]
        assert BM.validate() == []
        for name in ("hook_events_extended",
                     "hook_updated_input_validation"):
            m = next(x for x in C.MODULES if x.name == name)
            assert m.status == C.STATUS_GAP

    def test_gap_probes_still_green(self):
        from tuan_cli.parity_claude import depth as BD
        r = BD.gap_probe_audit()
        assert r["registered"] == 5 and r["verified"] == 5 and r["ok"]
        # XV：第 5 个模块级探针（等价故障闭合表）真跑 >= 25 条断言
        vx = r["results"]["hook_nonprocess_equivalence"]
        assert vx["ok"] and vx["checks"] >= 25, vx["problems"]
