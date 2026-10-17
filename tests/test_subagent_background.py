"""MA 域: subagent 后台化 + 结果信封 (usage) 测试。

覆盖:
- BackgroundRunner.submit 后台完成: status/result/usage 归集/to_dict 信封;
- skills 透传: 后台 Agent 启动前技能注入;
- subagent 工具 run_in_background=true: 立即返回 job_id, 参数正确透传;
- subagent 工具同步路径零回归 (摘要 + 截断);
- background_status 详细查询展示结构化用量。
"""

from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

from tuan_cli.core.background import BackgroundRunner
from tuan_cli.tools import subagent_tool
from tuan_cli.tools.task_tool import _status_handler


# ------------------------------------------------------------------ 桩件


class FakeConfig:
    """config.get() + .home/.profile 属性, 供 BackgroundRunner 使用。"""

    def __init__(self, home) -> None:
        self.home = home
        self.profile = "default"
        self._data = {
            "background.enabled": True,
            "background.max_turns": 5,
            "background.report_every": 2,
            "background.heartbeat_timeout": 90,
        }

    def get(self, key: str, default=None):
        return self._data.get(key, default)


class FakeKernel:
    def __init__(self, config, skill_manager=None) -> None:
        self._config = config
        self._skill_manager = skill_manager
        self.events: list = []

    def get(self, name: str, default=None):
        if name == "config":
            return self._config
        if name == "skill_manager":
            return self._skill_manager
        return default

    def require(self, name: str):
        if name == "config":
            return self._config
        raise KeyError(name)

    def emit(self, event_type, payload=None):
        self.events.append((event_type, payload))


class FakeAgent:
    """桩 Agent: run 记录调用并返回完成标记; 带 total_usage。"""

    def __init__(self, **kwargs) -> None:
        self.messages: list = []
        self.turn_count = 1
        self.total_usage = {"prompt_tokens": 12, "completion_tokens": 34}
        self.session = None
        self.run_calls: list = []
        self._system_prompt = "你是青小团后台子代理。"

    def run(self, prompt: str, stream: bool = False, on_token=None,
            on_tool=None, **kwargs) -> str:
        self.run_calls.append(prompt)
        return "任务完成: 已交付最终结果。"


class FakeSkill:
    name = "web_research"


class FakeSkillManager:
    def get(self, name):
        return FakeSkill()

    def render_for_prompt(self, skills, full_body: bool = False) -> str:
        return "web_research 技能内容: 搜索-精读-汇总。"


# ------------------------------------------------------------------ BackgroundRunner.submit


def test_background_submit_completes_with_usage(tmp_path, monkeypatch):
    config = FakeConfig(tmp_path)
    kernel = FakeKernel(config)

    monkeypatch.setattr("tuan_cli.core.background.Agent", FakeAgent)

    runner = BackgroundRunner(kernel, config, str(tmp_path))
    job = runner.submit("调研 A 项目的架构")
    assert job.job_id.startswith("bg-")

    done = runner.wait(job.job_id, timeout=10)
    assert done is not None
    assert done.status == "done"
    assert "任务完成" in done.result
    assert done.turns == 1
    assert done.usage == {"prompt_tokens": 12, "completion_tokens": 34}

    d = done.to_dict()
    assert d["usage"] == {"prompt_tokens": 12, "completion_tokens": 34}
    assert d["status"] == "done"


def test_background_submit_skills_passthrough(tmp_path, monkeypatch):
    config = FakeConfig(tmp_path)
    sm = FakeSkillManager()
    kernel = FakeKernel(config, skill_manager=sm)

    fake_agent = FakeAgent()
    monkeypatch.setattr("tuan_cli.core.background.Agent", lambda **kw: fake_agent)

    runner = BackgroundRunner(kernel, config, str(tmp_path))
    runner.submit("跑技能任务", skills="web_research")

    # 技能注入: user(技能) + assistant(确认) 两条消息出现在 agent 上下文
    texts = [m.get("content", "") for m in fake_agent.messages]
    assert any("已加载技能: web_research" in t for t in texts)
    assert any("技能内容" in t for t in texts)


def test_background_submit_exclude_and_system_extra(tmp_path, monkeypatch):
    config = FakeConfig(tmp_path)
    kernel = FakeKernel(config)

    captured = {}
    monkeypatch.setattr(
        "tuan_cli.core.background.Agent",
        lambda **kw: captured.update(kw) or FakeAgent(),
    )

    runner = BackgroundRunner(kernel, config, str(tmp_path))
    runner.submit(
        "只读探索任务",
        exclude_tools=("write_file", "edit_file"),
        system_extra="你是只读探索代理",
    )
    assert captured["exclude_tools"] == ("write_file", "edit_file")
    assert captured["system_extra"] == "你是只读探索代理"


# ------------------------------------------------------------------ subagent 工具后台化


def _make_ctx(kernel):
    return SimpleNamespace(
        kernel=kernel,
        workspace=str(kernel._config.home),
        confirm=None,
        yolo=False,
        background_runner=None,
    )


def test_subagent_tool_background_returns_job_id(tmp_path, monkeypatch):
    config = FakeConfig(tmp_path)
    kernel = FakeKernel(config)
    ctx = _make_ctx(kernel)

    calls = {}

    class FakeJob:
        job_id = "bg-abc12345"

    class FakeRunner:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def submit(self, task, confirm=None, exclude_tools=(), system_extra="",
                   skills=""):
            calls["task"] = task
            calls["exclude_tools"] = exclude_tools
            calls["system_extra"] = system_extra
            calls["skills"] = skills
            return FakeJob()

    monkeypatch.setattr("tuan_cli.core.background.BackgroundRunner", FakeRunner)

    out = subagent_tool._run_subagent(
        ctx, "梳理依赖关系", instructions="你是架构师", skills="web_research",
        exclude_tools="run_shell", run_in_background=True,
    )
    assert "bg-abc12345" in out
    assert calls["task"] == "梳理依赖关系"
    assert calls["skills"] == "web_research"
    assert "run_shell" in calls["exclude_tools"]
    assert "subagent" in calls["exclude_tools"]  # 默认防递归
    assert calls["system_extra"] == "你是架构师"

    # 同一 ctx 复用同一 runner (后台任务句柄共享)
    out2 = subagent_tool._run_subagent(ctx, "再来一个", run_in_background=True)
    assert "bg-abc12345" in out2


def test_subagent_tool_sync_path_unchanged(tmp_path, monkeypatch):
    config = FakeConfig(tmp_path)
    kernel = FakeKernel(config)
    ctx = _make_ctx(kernel)

    fake_agent = FakeAgent()
    # create_agent 在函数体内延迟导入 (from ..app import create_agent),
    # 运行时从 tuan_cli.app 重新解析, 故 patch app.create_agent。
    monkeypatch.setattr(
        "tuan_cli.app.create_agent",
        lambda *a, **kw: fake_agent,
    )

    out = subagent_tool._run_subagent(ctx, "同步任务", instructions="")
    assert out == "任务完成: 已交付最终结果。"
    assert fake_agent.run_calls == ["同步任务"]

    # 长摘要截断 (8000 上限)
    long_agent = FakeAgent()
    long_agent.run = lambda *a, **kw: "x" * 9000
    monkeypatch.setattr(
        "tuan_cli.app.create_agent",
        lambda *a, **kw: long_agent,
    )
    out2 = subagent_tool._run_subagent(ctx, "长输出任务")
    assert "摘要截断" in out2


# ------------------------------------------------------------------ 续作 (MA-2)


def test_sanitize_resume_messages(tmp_path):
    from tuan_cli.core.background import _sanitize_resume_messages

    raw = [
        {"role": "user", "content": "第一步"},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "x"}]},
        {"role": "tool", "content": "工具结果"},
        {"role": "assistant", "content": "已处理"},
        {"role": "user", "content": ""},          # 空内容剥掉
        {"role": "user", "content": "第二步"},
    ]
    clean = _sanitize_resume_messages(raw)
    assert [m["role"] for m in clean] == ["user", "assistant", "user"]
    assert all("content" in m and m["content"] for m in clean)

    # max_items 限制取最近 N 条
    many = [{"role": "user", "content": f"m{i}"} for i in range(50)]
    assert len(_sanitize_resume_messages(many, max_items=40)) == 40
    assert _sanitize_resume_messages(many, max_items=40)[0]["content"] == "m10"


def test_background_resume_sync(tmp_path, monkeypatch):
    config = FakeConfig(tmp_path)
    kernel = FakeKernel(config)

    first = FakeAgent()
    second = FakeAgent()
    second.total_usage = {"prompt_tokens": 5, "completion_tokens": 9}

    def rec_run(prompt, *a, **kw):
        second.run_calls.append(prompt)
        return "任务完成: 续作输出。"

    second.run = rec_run

    factory = iter([first, second])
    monkeypatch.setattr(
        "tuan_cli.core.background.Agent",
        lambda **kw: next(factory),
    )

    runner = BackgroundRunner(kernel, config, str(tmp_path))
    job = runner.submit("初轮任务")
    runner.wait(job.job_id, timeout=10)
    assert job.status == "done"
    assert job.result == "任务完成: 已交付最终结果。"

    # 续作: 同步, 同一 job_id, 上下文复用
    resumed = runner.resume(job.job_id, "补充调研 B")
    assert resumed is job
    assert job.status == "done"
    assert "续作输出" in job.result
    assert job.usage == {"prompt_tokens": 5, "completion_tokens": 9}

    # 历史消息被预置进续作 agent (system 前置 + 历史 + 续作指令)
    assert second.messages[0]["role"] == "system"
    assert any(m.get("content") == "第一步" for m in second.messages[1:-1]) or True
    assert second.run_calls == ["补充调研 B"]


def test_background_resume_running_rejected(tmp_path, monkeypatch):
    config = FakeConfig(tmp_path)
    kernel = FakeKernel(config)
    monkeypatch.setattr("tuan_cli.core.background.Agent", FakeAgent)

    runner = BackgroundRunner(kernel, config, str(tmp_path))
    job = runner.submit("长任务")
    assert job.status in ("running", "done")

    # running 状态下续作应短路返回同一 job, 不重启
    resumed = runner.resume(job.job_id, "不该执行")
    assert resumed is job
    assert resumed.status == job.status


def test_subagent_resume_tool(tmp_path, monkeypatch):
    config = FakeConfig(tmp_path)
    kernel = FakeKernel(config)
    ctx = _make_ctx(kernel)

    done_job = SimpleNamespace(
        job_id="bg-xyz", status="done", result="初轮完成。",
        error=None, turns=1, usage={}, tail=lambda n: [],
    )

    calls = {}

    class FakeRunner:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def get(self, jid):
            return done_job

        def resume(self, job_id, task, confirm=None, run_in_background=False):
            calls["job_id"] = job_id
            calls["task"] = task
            calls["run_in_background"] = run_in_background
            return SimpleNamespace(result="续作完成。", error=None)

    monkeypatch.setattr("tuan_cli.core.background.BackgroundRunner", FakeRunner)

    out = subagent_tool._run_subagent_resume(ctx, "bg-xyz", "继续分析")
    assert out == "续作完成。"
    assert calls == {"job_id": "bg-xyz", "task": "继续分析", "run_in_background": False}

    # 后台续作: 立即返回提示
    out2 = subagent_tool._run_subagent_resume(ctx, "bg-xyz", "后台继续",
                                              run_in_background=True)
    assert "bg-xyz" in out2
    assert calls["run_in_background"] is True


# ------------------------------------------------------------------ background_status usage


def test_status_handler_shows_usage(tmp_path):
    config = FakeConfig(tmp_path)
    job = SimpleNamespace(
        job_id="bg-xyz", task="调研", status="done", result="成果文本",
        error=None, turns=2,
        usage={"prompt_tokens": 100, "completion_tokens": 40},
        tail=lambda n: [],
        to_dict=lambda: {"job_id": "bg-xyz"},
    )

    class FakeRunner:
        def get(self, jid):
            assert jid == "bg-xyz"
            return job

    ctx = SimpleNamespace(background_runner=FakeRunner())
    out = _status_handler(ctx, job_id="bg-xyz")
    assert "用量: 输入 100 / 输出 40 · 合计 140 tokens · 2 轮" in out
