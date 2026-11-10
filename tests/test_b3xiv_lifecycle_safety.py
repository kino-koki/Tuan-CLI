"""B3 续轮 XIV｜接线之后的失败闭合与 payload 脱敏（先实测复现）。

XIII 把 13 个事件接到真实生产点。本轮真跑又抓出 7 个缺陷，全是
「装了 hook 反而不安全」这一类：

- F1 owner 未注册 / F2 provider 抛异常 → ``no_hooks`` 静默放行，
  ``emit_preventable`` 返回 False，可预防动作照做。B3 VII 的
  「owner 拼错 fail-closed」和本模块 docstring 写的「决策类沿用 B1
  fail-closed」在新模块里一条都没接。
- F3 脏 payload（在 try 之外 dict()）/ F4 恶意 event ``__str__`` →
  emit 抛异常，生产触发点 ``except Exception: pass`` 吞掉 → 又放行。
- F5 真起 command hook 把 stdin 原样落盘：``ghp_`` 明文 + OSC 8 / RLO
  原样进第三方子进程。
- F6 hook stdout 的 reason 原样进 ``LifecycleOutcome``。
- F7 四个可预防触发点的兜底 ``pass`` 吞掉注入异常，todo 仍写入、
  ``set_model`` 仍切换、压缩仍发生。

本文件每个缺陷都配**端到端真跑**回归；「不该修」的对照也逐条锁住。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from tuan_cli.hooks import exit_semantics as XS
from tuan_cli.hooks import lifecycle as LC
from tuan_cli.hooks import manager as HM
from tuan_cli.hooks import triggers as TR

PY = sys.executable
SECRET = "ghp_FAKE_SECRET_VALUE_FOR_REPRO_ONLY"
SECRET_REAL = "ghp_" + "A" * 36          # 真实 classic PAT 字符形态
OSC = "\x1b]8;;https://evil.example\x07"
RLO = "\u202e"
ZWSP = "\u200b"


class _Kernel:
    def get(self, n, d=None):
        return d

    def emit(self, t, p=None):
        pass

    def on(self, *a, **k):
        pass


@pytest.fixture
def env(tmp_path):
    log = tmp_path / "stdin.jsonl"
    scripts = tmp_path / "hooks"
    scripts.mkdir()

    def make(name, stdout="{}", rc=0, dump_stdin=True):
        p = scripts / (name + ".py")
        p.write_text(
            "import sys\n"
            "d=sys.stdin.read()\n"
            + ("open(%r,'a').write(d.replace('\\n','\\\\n')+'\\n')\n"
               % str(log) if dump_stdin else "")
            + "sys.stdout.write(%r)\n" % stdout
            + "sys.exit(%d)\n" % rc, encoding="utf-8")
        return {"command": [PY, str(p)]}

    def mgr(block):
        return HM.HookManager({"hooks": dict(block)}, kernel=_Kernel())

    TR.set_default_hooks_provider(None)
    LC.reset_stats()
    yield SimpleNamespace(tmp=tmp_path, log=log, make=make, mgr=mgr)
    TR.set_default_hooks_provider(None)
    LC.reset_stats()


def _stdin_rows(env):
    if not env.log.exists():
        return []
    return [json.loads(x) for x in env.log.read_text(
        encoding="utf-8", errors="replace").splitlines() if x.strip()]


# ================================================== F1 / F2 失败闭合
class TestFailClosed:
    def test_f1_owner_not_registered_blocks_preventable(self, env):
        m = env.mgr({"enabled": True, "WorktreeRemove": [env.make("wr")]})
        TR.set_default_hooks_provider(lambda: m)
        o = LC.emit("WorktreeRemove", {"name": "x"},
                    owner="session-that-does-not-exist")
        assert o.blocked is True
        assert o.source == "owner_not_registered"
        assert LC.emit_preventable(
            "WorktreeRemove", {"name": "x"},
            owner="session-that-does-not-exist") is True
        assert LC.stats()["owner_not_registered"] >= 2
        assert LC.stats()["fail_closed"] >= 2
        # 拼错 owner 绝不派到 default 会话的 hook
        assert _stdin_rows(env) == []

    def test_f1_owner_dirty_type_is_not_provider_error(self, env):
        o = LC.emit("PreCompact", {"hot_entries": 9}, owner=123)
        assert o.blocked is True
        assert o.source == "owner_not_registered"
        assert LC.stats()["provider_error"] == 0

    def test_f1_notify_owner_miss_does_not_block_but_does_not_dispatch(self, env):
        m = env.mgr({"enabled": True, "CwdChanged": [env.make("cc")]})
        TR.set_default_hooks_provider(lambda: m)
        o = LC.emit("CwdChanged", {"cwd": "/x"}, owner="missing-owner")
        assert o.blocked is False
        assert o.fired is False
        assert o.source == "owner_not_registered"
        assert _stdin_rows(env) == []

    def test_f2_provider_error_blocks_preventable(self, env):
        def boom():
            raise RuntimeError("provider exploded")
        TR.set_default_hooks_provider(boom)
        o = LC.emit("PreCompact", {"hot_entries": 9})
        assert o.blocked is True
        assert o.source == "provider_error"
        assert LC.emit_preventable("PreCompact", {"hot_entries": 9}) is True
        assert LC.stats()["provider_error"] >= 2

    def test_f2_no_hooks_still_allows(self, env):
        """对照：确实没配 hook 是唯一允许放行的分支（既有契约零变化）。"""
        assert LC.emit_preventable("PreCompact", {"hot_entries": 9}) is False
        assert LC.stats()["noop_no_hooks"] >= 1
        assert LC.stats()["fail_closed"] == 0

    def test_f2_normal_block_still_works(self, env):
        m = env.mgr({"enabled": True, "PreCompact": [
            env.make("pc", '{"decision":"block","reason":"no"}')]})
        o = LC.emit("PreCompact", {"hot_entries": 9}, hooks=m)
        assert o.blocked is True and o.source == "explicit"


# ================================================== F3 / F4 / F9 永不抛异常
class TestNeverRaises:
    @pytest.mark.parametrize("dirty", [
        "not-a-dict", 123, ["a", "b"], object(), b"bytes", 3.5])
    def test_f3_dirty_payload_never_raises(self, env, dirty):
        m = env.mgr({"enabled": True, "PreCompact": [env.make("pc")]})
        o = LC.emit("PreCompact", dirty, hooks=m)
        assert o.blocked is True
        assert o.source == "payload_rejected"
        assert LC.stats()["payload_rejected"] >= 1
        assert _stdin_rows(env) == []      # 脏 payload 绝不出站

    def test_f3_notify_dirty_payload_no_raise(self, env):
        m = env.mgr({"enabled": True, "CwdChanged": [env.make("cc")]})
        o = LC.emit("CwdChanged", ["bad"], hooks=m)
        assert o.fired is False and o.blocked is False
        assert o.source == "payload_rejected"

    def test_f4_evil_event_str_raises_no_longer_breaks_emit(self, env):
        class Evil:
            def __str__(self):
                raise RuntimeError("str exploded")
        o = LC.emit(Evil(), {})
        assert o.event == "<invalid-event>"
        assert o.source == "unknown_event"
        assert LC.stats()["unknown_event"] == 1

    def test_f9_prevent_dirty_type_falls_back_to_truth_table(self, env):
        m = env.mgr({"enabled": True, "PreCompact": [env.make("pc")]})
        sem = XS.semantics_for("PreCompact")
        o = LC.emit("PreCompact", {"hot_entries": 9}, hooks=m,
                    prevent="false")
        assert o.preventable is bool(sem and sem.blocks_on_exit2)
        assert isinstance(o.preventable, bool)

    def test_emit_never_raises_when_manager_explodes(self, env):
        class BadMgr:
            enabled = True

            def run_event(self, *a, **k):
                raise RuntimeError("run_event exploded")

            def run_notify(self, *a, **k):
                raise RuntimeError("run_notify exploded")
        o = LC.emit("PreCompact", {"hot_entries": 9}, hooks=BadMgr())
        assert o.blocked is True and o.source == "error"
        n = LC.emit("CwdChanged", {"cwd": "/x"}, hooks=BadMgr())
        assert n.fired is False and n.source == "error"
        assert LC.stats()["errors_swallowed"] == 2


# ================================================== F5 / F6 净化出口
class TestSanitization:
    def test_f5_real_subprocess_stdin_has_no_secret_or_control_chars(self, env):
        m = env.mgr({"enabled": True,
                     "PermissionDenied": [env.make("pd")],
                     "TaskCreated": [env.make("tc")],
                     "CwdChanged": [env.make("cc")]})
        LC.emit("PermissionDenied", {
            "tool_name": "shell",
            "reason": "用户未批准 " + SECRET + OSC + RLO + ZWSP,
            "safety_advice": SECRET_REAL}, hooks=m)
        LC.emit("TaskCreated", {"task": {
            "id": "a", "content": "key=" + SECRET + OSC,
            "status": "pending"}}, hooks=m)
        LC.emit("CwdChanged", {
            "cwd": "/tmp/" + SECRET_REAL, "previous": "/x"}, hooks=m)
        rows = _stdin_rows(env)
        assert len(rows) == 3
        flat = json.dumps(rows, ensure_ascii=False)
        assert SECRET not in flat
        assert SECRET_REAL not in flat
        assert OSC not in flat and RLO not in flat and ZWSP not in flat
        assert "evil.example" not in flat
        assert "[REDACTED]" in flat          # 脱敏留痕，不是整串删掉
        assert LC.stats()["sanitized_fields"] >= 3

    def test_f5_semantic_fields_preserved(self, env):
        m = env.mgr({"enabled": True, "TaskCreated": [env.make("tc")]})
        LC.emit("TaskCreated", {"task": {
            "id": "a", "content": "写单测", "status": "pending"}}, hooks=m)
        row = _stdin_rows(env)[0]
        assert row["hook_event_name"] == "TaskCreated"
        assert row["task"]["id"] == "a"
        assert row["task"]["content"] == "写单测"
        assert row["task"]["status"] == "pending"

    def test_f5_nested_bounded_and_non_serializable(self, env):
        class Evil:
            def __str__(self):
                raise RuntimeError("no str")
        deep = {"a": {"b": {"c": {"d": {"e": {"f": {"g": {"h": {"i": "x"}}}}}}}}}
        pl, n = LC._sanitize_payload({
            "deep": deep, "big": [SECRET_REAL] * 200,
            "raw": b"\x00\x1b", "nan": float("nan"),
            "obj": Evil(), "set": {1, 2, 3}})
        assert n >= 5
        s = json.dumps(pl, ensure_ascii=False)
        assert SECRET_REAL not in s
        assert "\x1b" not in s
        assert "<Evil>" in s and "<bytes:2>" in s
        assert "<non-finite-float>" in s
        assert "<已截断" in s or "<100" in s or "省略" in s

    def test_f6_hook_reason_sanitized(self, env):
        m = env.mgr({"enabled": True, "PreCompact": [
            env.make("pc", json.dumps({
                "decision": "block",
                "reason": "BLOCKED" + OSC + RLO + ZWSP + SECRET_REAL + "END"},
                ensure_ascii=False), dump_stdin=False)]})
        o = LC.emit("PreCompact", {"hot_entries": 9}, hooks=m)
        assert o.blocked is True
        assert o.reason.startswith("BLOCKED") and o.reason.endswith("END")
        assert OSC not in o.reason and RLO not in o.reason
        assert ZWSP not in o.reason and SECRET_REAL not in o.reason
        assert "[REDACTED]" in o.reason

    def test_clean_str_is_idempotent(self):
        s = "x" + SECRET_REAL + OSC + RLO
        once = LC._clean_str(s)
        assert LC._clean_str(once) == once

    def test_validate_runs_real_sanitization_check(self):
        assert LC.validate() == []
        for key in ("owner_not_registered", "provider_error",
                    "payload_rejected", "sanitized_fields", "fail_closed"):
            assert key in LC.stats()


# ================================================== F7 生产触发点兜底
class TestProductionTriggerFailClosed:
    def _inject(self, monkeypatch):
        def boom(*a, **k):
            raise RuntimeError("injected emit failure")
        monkeypatch.setattr(LC, "emit_preventable", boom)

    def test_f7_todo_does_not_write(self, env, monkeypatch):
        from tuan_cli.tools.base import ToolContext
        from tuan_cli.tools.todo_tool import _todo_write_handler
        self._inject(monkeypatch)
        ctx = ToolContext(kernel=_Kernel(), workspace=str(env.tmp))
        out = _todo_write_handler(ctx, todos=[
            {"id": "a", "content": "x", "status": "pending"}])
        assert not getattr(ctx, "todos", None)
        assert "fail-closed" in out

    def test_f7_set_model_does_not_switch(self, env, monkeypatch):
        from tuan_cli.runtime.acp.bridge import KernelAcpBridge
        self._inject(monkeypatch)
        br = KernelAcpBridge(make_agent=lambda: None)
        br.set_model("s1", "gpt-new")
        assert getattr(br, "_model", None) != "gpt-new"

    def test_f7_compact_does_not_happen(self, env, monkeypatch):
        from tuan_cli.arch.context import TieredContext
        self._inject(monkeypatch)
        c = TieredContext(budget_tokens=60, hot_capacity=2)
        for _ in range(8):
            c.add("user", "x" * 100)
        assert c.compactions == 0
        assert len(c.hot) > c.hot_capacity      # 如实超预算

    def test_f7_worktree_remove_refuses_real_git(self, env, monkeypatch):
        from tuan_cli.core.worktree_layer import WorktreeLayer, WorktreeError
        repo = env.tmp / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=repo,
                       capture_output=True, timeout=15)
        subprocess.run(["git", "-c", "user.email=a@b", "-c", "user.name=a",
                        "commit", "--allow-empty", "-qm", "i"], cwd=repo,
                       capture_output=True, timeout=15)
        w = WorktreeLayer(str(repo))
        w.create("probe")
        self._inject(monkeypatch)
        with pytest.raises(WorktreeError) as ei:
            w.remove("probe")
        assert "fail-closed" in str(ei.value)
        listed = subprocess.run(["git", "worktree", "list"], cwd=repo,
                                capture_output=True, text=True, timeout=15)
        assert "probe" in listed.stdout       # 真的没移除

    def test_notify_trigger_keeps_swallowing(self, env, monkeypatch):
        """不该修：通知类动作已发生，不该因 hook 通道异常回滚。"""
        from tuan_cli.cli.cmd_slash_claude import cmd_cd

        def boom(*a, **k):
            raise RuntimeError("notify exploded")
        monkeypatch.setattr(LC, "emit", boom)
        old = os.getcwd()
        agent = SimpleNamespace(ctx=SimpleNamespace(workspace=str(env.tmp)))
        try:
            cmd_cd(agent, str(env.tmp))
            assert os.getcwd() == str(env.tmp)
        finally:
            os.chdir(old)


# ================================================== 矩阵 / 深度证据
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

    def test_two_b3_entries_still_gap(self):
        from pathlib import Path
        src = Path("tuan_cli/parity_claude/catalog.py").read_text(
            encoding="utf-8")
        for key in ("hook_events_extended", "hook_updated_input_validation"):
            i = src.index('M("%s"' % key)
            assert "STATUS_GAP" in src[i:i + 400], key

    def test_xiii_wired_still_13(self):
        c = LC.coverage()
        assert c["wired_this_round"] == 13
        assert c["official"] == 33
        assert c["not_wired"] == 1
        assert LC.validate() == []
