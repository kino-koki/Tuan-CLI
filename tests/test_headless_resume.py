"""Headless `tuan run --resume` 续会话测试 (对标 Claude Code `claude -p --resume <id>`)。

审计发现缺口: headless 的两条入口里, `tuan chat --print` 早已接入 --resume
(见 cmd_chat._prepare_agent), 但专用 headless 子命令 `tuan run` (cmd_run) 没有
--resume/--continue —— CI/CD 多步流水线无法在无 TUI 下续上一轮会话。
本次补齐后, `tuan run --resume [id|编号|latest]` 先恢复历史上下文再跑一轮。

本测试证明:
- parser: run --resume <id> / --continue / 省略值(=latest) 都正确落位 args.resume;
- cmd_run: 传入 --resume 时调用 _resume_session; 恢复失败 → 退出码 1;
  恢复成功 → 带历史上下文正常跑一轮, 退出码 0。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest


# ---------------------------------------------------------------- parser 层

def test_run_resume_parser_flag():
    """`tuan run --resume abc123` 解析到 args.resume='abc123'。"""
    from tuan_cli.cli.parser import build_parser
    p = build_parser()
    a = p.parse_args(["run", "--resume", "abc123", "做个任务"])
    assert a.resume == "abc123"


def test_run_resume_alias_continue():
    """`--continue` 是 --resume 的别名。"""
    from tuan_cli.cli.parser import build_parser
    p = build_parser()
    a = p.parse_args(["run", "--continue", "latest", "任务"])
    assert a.resume == "latest"


def test_run_resume_omitted_value_defaults_to_latest():
    """`tuan run 任务 --resume` (resume 置末尾, 不带值) → 续最近一个会话 (const='latest')。"""
    from tuan_cli.cli.parser import build_parser
    p = build_parser()
    # resume 放在 task 之后且不带值 → nargs='?' 取 const='latest'
    a = p.parse_args(["run", "任务", "--resume"])
    assert a.resume == "latest"
    assert a.task == "任务"


def test_run_resume_explicit_equals_form():
    """`tuan run --resume=latest 任务` 显式等号形式同样可用。"""
    from tuan_cli.cli.parser import build_parser
    p = build_parser()
    a = p.parse_args(["run", "--resume=latest", "任务"])
    assert a.resume == "latest"
    assert a.task == "任务"


def test_run_without_resume_is_none():
    """不带 --resume 时 args.resume 为 None (不触发恢复)。"""
    from tuan_cli.cli.parser import build_parser
    p = build_parser()
    a = p.parse_args(["run", "-p", "任务"])
    assert a.resume is None


# ---------------------------------------------------------------- cmd_run 接线层

class _FakeConfig:
    def __init__(self):
        self.data = {"mode": {"default": "standard"}}

    def get(self, key, default=None):
        node = self.data
        for part in key.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def set_user(self, key, value):
        node = self.data
        parts = key.split(".")
        for p in parts[:-1]:
            node = node.setdefault(p, {})
        node[parts[-1]] = value

    @property
    def mode(self):
        return self.get("mode.default", "standard")


class _FakeKernel:
    def __init__(self, config=None):
        self._config = config or _FakeConfig()

    def require(self, name):
        if name == "config":
            return self._config
        raise KeyError(name)

    def get(self, name, default=None):
        return default


class _FakeAgent:
    def __init__(self, answer="继续上一轮的收尾结果"):
        self.answer = answer
        self.total_usage = {}
        self.ctx = SimpleNamespace(
            allowed_tools=None, plan_mode=False, hooks=None,
            ledger=None, checkpoint_store=None,
        )
        self.plan_mode = False
        self.calls = []
        self.resumed_messages = 0

    def run(self, task, stream=True, on_token=None, on_reason=None,
            on_tool=None, on_tool_result=None, on_error=None,
            session_id=None, max_iterations=None):
        self.calls.append(task)
        if on_token:
            on_token(self.answer)
        return self.answer

    def _estimate_total_cost(self):
        return 0.0


def _make_args(**kw):
    base = dict(
        task="继续完成",
        bare=False, print_mode=True, output_format="text",
        yes=False, mode=None, permission_mode=None, effort=None, model=None,
        workspace=None, allowed_tools=None, max_cost=0.0, max_turns=0,
        no_stream=False, bg=False, json_schema=None, json_schema_strict=False,
        json_schema_retries=3, resume=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)


@pytest.fixture
def patched_run(monkeypatch):
    from tuan_cli.cli import cmd_agents
    monkeypatch.setattr(cmd_agents, "build_kernel", lambda *a, **k: _FakeKernel())
    monkeypatch.setattr(cmd_agents, "create_agent", lambda kernel, workspace: _FakeAgent())
    monkeypatch.setattr(cmd_agents, "seed_builtin_skills", lambda *a, **k: 0)
    return cmd_agents


def test_cmd_run_resume_failure_returns_nonzero(patched_run, monkeypatch, capsys):
    """--resume 指向不存在的会话 → _resume_session 返回 None → 退出码 1。"""
    monkeypatch.setattr("tuan_cli.cli.cmd_chat._resume_session",
                        lambda agent, arg: None)
    args = _make_args(resume="no-such-session-xyz")
    rc = patched_run.cmd_run(args)
    assert rc == 1
    err = capsys.readouterr().err
    assert "无法恢复会话" in err


def test_cmd_run_resume_success_runs_one_turn(patched_run, monkeypatch, capsys):
    """--resume 恢复成功 → 正常跑一轮, 退出码 0, 且确实调用过 _resume_session。"""
    called = {}

    def fake_resume(agent, arg):
        called["arg"] = arg
        agent.resumed_messages = 5  # 模拟恢复了 5 条历史消息
        return "/fake/session.jsonl"

    monkeypatch.setattr("tuan_cli.cli.cmd_chat._resume_session", fake_resume)
    args = _make_args(resume="latest")
    rc = patched_run.cmd_run(args)
    assert rc == 0
    assert called.get("arg") == "latest"
    out = capsys.readouterr().out
    assert "继续上一轮的收尾结果" in out
