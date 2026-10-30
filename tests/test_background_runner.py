"""BackgroundRunner 主路径单元测试 —— 后台自主任务 (submit/resume/wait/parallel/status)。

覆盖 `core/background.py` 中未被现有 test_background_* 触及的纯逻辑:
- submit 主路径 (enabled 开关 / 元数据落盘 / 线程驱动)
- _drive 完成判定 (is_done) / 轮次上限 / 异常→failed / 取消提前退出
- resume 语义 (running 拒绝 / 不存在返回 None / 清历史 / 续作驱动)
- wait / get / list_jobs / submit_parallel / status_all / prune_finished
- _sanitize_resume_messages 清洗规则
- submit_background / wait_for_job 便捷函数
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from tuan_cli.core import background as bg
from tuan_cli.core.background import (
    BackgroundRunner,
    _sanitize_resume_messages,
    submit_background,
    wait_for_job,
)
from tuan_cli.memory.sessions import SessionStore


# ------------------------------------------------------------------ 辅助桩

class _Cfg:
    """极简 config: get 走 dict, 提供 home / workspace / profile。"""

    def __init__(self, home, workspace=None, values=None):
        self.home = home
        self.workspace = str(workspace or home)
        self.profile = "default"
        self._v = dict(values or {})

    def get(self, key, default=None):
        return self._v.get(key, default)


class _Kernel:
    def __init__(self, home, config=None):
        self._home = home
        self._sm = None
        self._cfg = config or _Cfg(home)

    def get(self, name):
        if name == "skill_manager":
            return self._sm
        return None

    def require(self, name):
        if name == "config":
            return self._cfg
        raise KeyError(name)


class _StubAgent:
    """受控 Agent 替身: run 按脚本返回, 记录调用, 支持 turn_count/total_usage/ctx。"""

    def __init__(self, script, system_prompt="[system]", max_turns=50):
        self._script = list(script)
        self._system_prompt = system_prompt
        self._i = 0
        self.messages = []
        self.turn_count = 0
        self.total_usage = {"prompt_tokens": 100, "completion_tokens": 50}
        self.ctx = type("_Ctx", (), {"chain_depth": 0})()
        self.session = None
        self.calls = []

    def run(self, prompt, stream=False, on_token=None, on_tool=None):
        self.calls.append({"prompt": prompt, "stream": stream,
                           "on_token": on_token, "on_tool": on_tool})
        self.turn_count += 1
        if self._i < len(self._script):
            out = self._script[self._i]
            self._i += 1
        else:
            out = "(脚本耗尽)"
        if on_token:
            on_token(out)
        return out


def _make_runner(tmp_path, values=None, workspace=None):
    home = Path(tmp_path) / ".tuan"
    home.mkdir(parents=True, exist_ok=True)
    cfg = _Cfg(home, workspace=workspace, values=values)
    return BackgroundRunner(_Kernel(home), cfg, str(workspace or home))


# ------------------------------------------------------------------ 构造隔离

def test_submit_disabled_raises(tmp_path):
    runner = _make_runner(tmp_path, values={"background.enabled": False})
    with pytest.raises(RuntimeError):
        runner.submit("do it")


def test_submit_drives_to_done(tmp_path, monkeypatch):
    """完成标记 → 一轮即 done, 状态/结果/usage 正确落盘。"""
    runner = _make_runner(tmp_path)
    stub = _StubAgent(["任务完成"])
    monkeypatch.setattr(bg, "Agent", lambda **kw: stub)
    job = runner.submit("整理周报")
    assert job.job_id.startswith("bg-")
    runner.wait(job.job_id, timeout=5)
    assert job.status == "done"
    assert job.result == "任务完成"
    assert job.usage == {"prompt_tokens": 100, "completion_tokens": 50}
    # 会话流应记录 start/done
    recs = [json.loads(l) for l in job.store.file.read_text(encoding="utf-8").splitlines() if l.strip()]
    types = [r.get("type") for r in recs]
    assert "job.start" in types
    assert "job.done" in types


def test_submit_hits_turn_limit_without_done(tmp_path, monkeypatch):
    """无完成标记 → 轮次上限后 done (exhausted), result 为最后输出, 跑满轮次。"""
    runner = _make_runner(tmp_path, values={"background.max_turns": 3})
    stub = _StubAgent(["继续干活", "继续干活", "继续干活"])
    monkeypatch.setattr(bg, "Agent", lambda **kw: stub)
    job = runner.submit("loop forever")
    runner.wait(job.job_id, timeout=5)
    assert job.status == "done"
    assert job.result == "继续干活"
    assert job.turns == 3
    assert len(stub.calls) == 3


def test_submit_exception_marks_failed(tmp_path, monkeypatch):
    runner = _make_runner(tmp_path)
    class _Boom(_StubAgent):
        def run(self, prompt, stream=False, on_token=None, on_tool=None):
            raise ValueError("model down")
    monkeypatch.setattr(bg, "Agent", lambda **kw: _Boom([]))
    job = runner.submit("crash")
    runner.wait(job.job_id, timeout=5)
    assert job.status == "failed"
    assert "ValueError" in (job.error or "")


def test_submit_cancel_returns_early(tmp_path, monkeypatch):
    """cancelled 状态 → _drive 首轮检查立即返回, run 不再被调用。

    纯同步构造 (不经 submit 起线程), 避免线程竞态导致首轮已进入 run。
    """
    runner = _make_runner(tmp_path)
    stub = _StubAgent(["任务完成"])
    monkeypatch.setattr(bg, "Agent", lambda **kw: stub)
    home = Path(tmp_path) / ".tuan"
    store = SessionStore(home)
    job = bg.BackgroundJob(job_id="bg-cancel", task="will be cancelled",
                           started_at=time.time(), thread=None, store=store)
    job.status = "cancelled"
    # 用 _drive 同步验证首轮检查退出
    runner._drive(job, stub, store, "will be cancelled", False, None, 50, 5)
    assert stub.calls == []


# ------------------------------------------------------------------ resume

def test_resume_nonexistent_returns_none(tmp_path):
    runner = _make_runner(tmp_path)
    assert runner.resume("bg-nope", "继续") is None


def test_resume_running_returns_same_job(tmp_path, monkeypatch):
    runner = _make_runner(tmp_path)
    stub = _StubAgent([])
    monkeypatch.setattr(bg, "Agent", lambda **kw: stub)
    job = runner.submit("running")
    # 手动置 running (模拟仍在跑)
    job.status = "running"
    again = runner.resume(job.job_id, "继续")
    assert again is job


def test_resume_finished_reuses_context(tmp_path, monkeypatch):
    """续作已完成任务: 历史清洗后预置到新 agent, 状态重置 running, 驱动到完成。"""
    runner = _make_runner(tmp_path)
    stub1 = _StubAgent(["任务完成"])
    monkeypatch.setattr(bg, "Agent", lambda **kw: stub1)
    job = runner.submit("先做一次")
    runner.wait(job.job_id, timeout=5)
    assert job.status == "done"

    stub2 = _StubAgent(["【已完成】"])
    monkeypatch.setattr(bg, "Agent", lambda **kw: stub2)
    resumed = runner.resume(job.job_id, "追加任务")
    assert resumed is job
    runner.wait(job.job_id, timeout=5)
    assert job.status == "done"
    # 新 agent 拿到预置的系统提示 + 清洗后的历史
    assert any(m.get("role") == "system" for m in stub2.messages)
    # 首轮 prompt 是追加任务本身
    assert stub2.calls[0]["prompt"] == "追加任务"


def test_resume_skips_tool_and_toolcall_messages(tmp_path, monkeypatch):
    """历史清洗: tool / tool_calls / 空 content 全部剥掉。"""
    runner = _make_runner(tmp_path)
    stub1 = _StubAgent(["任务完成"])
    monkeypatch.setattr(bg, "Agent", lambda **kw: stub1)
    job = runner.submit("seed")
    runner.wait(job.job_id, timeout=5)
    # 手动注入脏记录 (load_messages 只读 user/assistant/tool 且含 message 键)
    job.store.append("tool", {"message": {"role": "tool", "content": "tool result"}})
    job.store.append("assistant", {"message": {"role": "assistant", "content": "x",
                                               "tool_calls": [{"id": "c"}]}})
    job.store.append("user", {"message": {"role": "user", "content": "  "}})
    job.store.append("user", {"message": {"role": "user", "content": "真实问题"}})
    stub2 = _StubAgent(["【已完成】"])
    monkeypatch.setattr(bg, "Agent", lambda **kw: stub2)
    resumed = runner.resume(job.job_id, "继续")
    runner.wait(job.job_id, timeout=5)
    user_contents = [m["content"] for m in stub2.messages if m.get("role") == "user"]
    assert "真实问题" in user_contents
    assert "tool result" not in user_contents


# ------------------------------------------------------------------ 查询 / 聚合

def test_get_and_list_and_prune(tmp_path, monkeypatch):
    runner = _make_runner(tmp_path)
    stub = _StubAgent(["任务完成"])
    monkeypatch.setattr(bg, "Agent", lambda **kw: stub)
    j1 = runner.submit("a")
    j2 = runner.submit("b")
    runner.wait(j1.job_id, timeout=5)
    runner.wait(j2.job_id, timeout=5)
    got = runner.get(j1.job_id)
    assert got is not None and got.job_id == j1.job_id
    ids = [j.job_id for j in runner.list_jobs()]
    assert j1.job_id in ids and j2.job_id in ids
    # 内存里的已结束任务可被 prune 掉
    removed = runner.prune_finished()
    assert removed >= 1
    assert j1.job_id not in runner._jobs  # 已从内存移除
    # list_jobs 仍从落盘 manifest + 内存合并 (无 manifest 时只有内存, 已空)
    remaining = [j.job_id for j in runner.list_jobs()]
    assert j1.job_id not in remaining


def test_submit_parallel_skips_blank(tmp_path, monkeypatch):
    runner = _make_runner(tmp_path)
    stub = _StubAgent(["任务完成"])
    monkeypatch.setattr(bg, "Agent", lambda **kw: stub)
    jobs = runner.submit_parallel(["x", "", "  ", "y"])
    assert len(jobs) == 2
    assert all(j.job_id.startswith("bg-") for j in jobs)
    runner.wait(jobs[0].job_id, timeout=5)
    runner.wait(jobs[1].job_id, timeout=5)


def test_status_all_aggregates(tmp_path, monkeypatch):
    runner = _make_runner(tmp_path)
    stub = _StubAgent(["任务完成"])
    monkeypatch.setattr(bg, "Agent", lambda **kw: stub)
    j = runner.submit("only")
    runner.wait(j.job_id, timeout=5)
    snap = runner.status_all()
    assert snap["total"] >= 1
    assert snap["by_status"].get("done", 0) >= 1
    assert snap["jobs"][0]["job_id"] == j.job_id


def test_wait_nonexistent_returns_none(tmp_path):
    runner = _make_runner(tmp_path)
    assert runner.wait("bg-nope") is None


def test_wait_timeout_returns_job(tmp_path, monkeypatch):
    """超时等待: thread.join(timeout) 到期返回 job, 不抛。"""
    runner = _make_runner(tmp_path)
    stub = _StubAgent(["继续"])  # 无完成标记, 但 max_turns 兜底
    monkeypatch.setattr(bg, "Agent", lambda **kw: stub)
    job = runner.submit("slow")
    out = runner.wait(job.job_id, timeout=0.01)
    assert out is job


# ------------------------------------------------------------------ 清洗函数

def test_sanitize_resume_messages_drops_tool_and_calls():
    msgs = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "ok"},
        {"role": "tool", "content": "result"},
        {"role": "assistant", "content": "with calls", "tool_calls": [{"id": "1"}]},
        {"role": "user", "content": ""},
        {"role": "user", "content": None},
        {"role": "assistant", "content": "tail"},
    ]
    out = _sanitize_resume_messages(msgs)
    assert out == [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "ok"},
        {"role": "assistant", "content": "tail"},
    ]


def test_sanitize_resume_messages_max_items():
    msgs = [{"role": "user", "content": f"m{i}"} for i in range(50)]
    out = _sanitize_resume_messages(msgs, max_items=10)
    assert len(out) == 10
    assert out[-1]["content"] == "m49"


def test_sanitize_resume_messages_nonpositive_keeps_all():
    msgs = [{"role": "user", "content": "a"}, {"role": "user", "content": "b"}]
    assert len(_sanitize_resume_messages(msgs, max_items=0)) == 2


# ------------------------------------------------------------------ 便捷函数

def test_submit_background_detached_path(tmp_path, monkeypatch):
    """submit_detached 成功 → 返回 job_id (通过 monkeypatch 拦截 subprocess)."""
    runner = _make_runner(tmp_path)
    monkeypatch.setattr(bg, "BackgroundRunner", lambda *a, **k: runner)
    monkeypatch.setattr(runner, "submit_detached", lambda task, yolo=False: {"job_id": "bg-detached"})
    assert submit_background(_Kernel(tmp_path), object(), "x", str(tmp_path)) == "bg-detached"


def test_submit_background_reraises_without_fallback(tmp_path, monkeypatch):
    runner = _make_runner(tmp_path)
    monkeypatch.setattr(bg, "BackgroundRunner", lambda *a, **k: runner)
    def _boom(task, yolo=False):
        raise RuntimeError("no detached")
    monkeypatch.setattr(runner, "submit_detached", _boom)
    # allow_thread_fallback 默认 False → 上浮
    with pytest.raises(RuntimeError):
        submit_background(_Kernel(tmp_path), object(), "x", str(tmp_path))


def test_submit_background_thread_fallback(tmp_path, monkeypatch):
    cfg = _Cfg(Path(tmp_path) / ".tuan", values={"background.allow_thread_fallback": True})
    kernel = _Kernel(tmp_path, config=cfg)
    runner = _make_runner(tmp_path, values={"background.allow_thread_fallback": True})
    monkeypatch.setattr(bg, "BackgroundRunner", lambda *a, **k: runner)
    def _boom(task, yolo=False):
        raise RuntimeError("no detached")
    monkeypatch.setattr(runner, "submit_detached", _boom)
    stub = _StubAgent(["任务完成"])
    monkeypatch.setattr(bg, "Agent", lambda **kw: stub)
    job_id = submit_background(kernel, object(), "x", str(tmp_path))
    assert job_id.startswith("bg-")
    runner.wait(job_id, timeout=5)


def test_wait_for_job_missing(tmp_path):
    out = wait_for_job(_Kernel(tmp_path), "bg-nope")
    assert "未找到" in out
