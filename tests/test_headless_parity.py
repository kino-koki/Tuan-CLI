"""Claude Code CLI 行为对标补齐测试 (本分片负责的 3 项真实缺口)。

覆盖:
1. `--output-format stream-json` —— 消息级事件流 (system/init → assistant → user → result)。
2. `--append-system-prompt` / `--append-user-prompt` —— CLI 追加提示词 (CI 场景)。
3. `--session-id` —— 指定会话 ID。
"""

from __future__ import annotations

import io
import json
from types import SimpleNamespace

import pytest


# --------------------------------------------------------------------- 替身 (与 test_headless_print.py 同构)

class _FakeConfig:
    def __init__(self, data=None):
        self.data = data or {"mode": {"default": "standard"}}

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
    """记录 run 入参 + 暴露 _system_prompt/messages 供追加提示词断言。"""

    def __init__(self, answer="最终回答文本"):
        self.answer = answer
        self.total_usage = {"prompt_tokens": 11, "completion_tokens": 7}
        self.ctx = SimpleNamespace(
            allowed_tools=None, plan_mode=False, hooks=None,
            ledger=None, checkpoint_store=None,
        )
        self.plan_mode = False
        self._system_prompt = "BASE_SYSTEM_PROMPT"
        self.messages: list = []
        self.calls: list[dict] = []

    def run(self, task, stream=True, on_token=None, on_reason=None,
            on_tool=None, on_tool_result=None, on_error=None,
            session_id=None, max_iterations=None):
        self.calls.append({"task": task, "session_id": session_id})
        if on_token:
            on_token(self.answer)
        return self.answer

    def _estimate_total_cost(self):
        return 0.0


def _make_args(**kw):
    base = dict(
        task="写一个问候",
        bare=False,
        print_mode=False,
        output_format="text",
        yes=False,
        mode=None,
        permission_mode=None,
        effort=None,
        model=None,
        workspace=None,
        allowed_tools=None,
        max_cost=0.0,
        max_turns=0,
        no_stream=False,
        bg=False,
        json_schema=None,
        resume=None,
        append_system_prompt=None,
        append_user_prompt=None,
        session_id=None,
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


# ===================================================================== 1. parser 暴露新 flag

def test_run_parser_exposes_parity_flags():
    """parser: run 子命令接受 stream-json / append-* / --session-id。"""
    from tuan_cli.cli.parser import build_parser
    p = build_parser()
    a = p.parse_args([
        "run", "任务",
        "--output-format", "stream-json",
        "--append-system-prompt", "始终用 JSON 回答",
        "--append-user-prompt", "请附引用",
        "--session-id", "ci-pipeline-step-3",
    ])
    assert a.func == "cmd_run"
    assert a.output_format == "stream-json"
    assert a.append_system_prompt == "始终用 JSON 回答"
    assert a.append_user_prompt == "请附引用"
    assert a.session_id == "ci-pipeline-step-3"


# ===================================================================== 2. stream-json emitter 事件序列

def test_stream_json_emitter_event_sequence():
    """_StreamJsonEmitter: init → assistant[text+tool_use] → user[tool_result] → result。"""
    from tuan_cli.cli.cmd_agents import _StreamJsonEmitter

    buf = io.StringIO()
    em = _StreamJsonEmitter(sink=buf, session_id="sid-1", cwd="/w", model="m1")
    em.on_reason("想想...")
    em.on_token("你好")
    em.on_tool("read_file", '{"path": "a.txt"}')
    em.on_tool_result("read_file", "文件内容")
    em.on_token("，世界")
    em.finish("stop", {"prompt_tokens": 11, "completion_tokens": 7})

    objs = [json.loads(ln) for ln in buf.getvalue().splitlines() if ln.strip()]
    types = [o["type"] for o in objs]

    # 首事件 system/init 携带元信息
    assert types[0] == "system"
    assert objs[0]["subtype"] == "init"
    assert objs[0]["session_id"] == "sid-1"
    assert objs[0]["cwd"] == "/w"

    # 中间出现 assistant 与 user 消息事件
    assert "assistant" in types
    assert "user" in types
    # 末事件 result
    assert types[-1] == "result"
    assert objs[-1]["subtype"] == "success"
    assert objs[-1]["usage"]["prompt_tokens"] == 11

    # assistant 消息是 Anthropic 风格 message (role + content blocks)
    asst = next(o for o in objs if o["type"] == "assistant")
    assert asst["message"]["role"] == "assistant"
    block_types = [b["type"] for b in asst["message"]["content"]]
    assert "tool_use" in block_types
    tu = next(b for b in asst["message"]["content"] if b["type"] == "tool_use")
    assert tu["name"] == "read_file"
    assert tu["input"] == {"path": "a.txt"}

    # user 消息承载 tool_result
    usr = next(o for o in objs if o["type"] == "user")
    tr = usr["message"]["content"][0]
    assert tr["type"] == "tool_result"
    assert tr["tool_use_id"] == tu["id"]


def test_stream_json_end_to_end(patched_run, capsys):
    """cmd_run --output-format stream-json: stdout 全是合法 JSON 消息事件, 末为 result。"""
    args = _make_args(output_format="stream-json")
    rc = patched_run.cmd_run(args)
    assert rc == 0
    out = capsys.readouterr().out
    objs = [json.loads(ln) for ln in out.splitlines() if ln.strip()]
    assert objs, "stream-json 至少应输出事件行"
    assert objs[0]["type"] == "system"
    assert objs[-1]["type"] == "result"
    assert objs[-1]["subtype"] == "success"


# ===================================================================== 3. append-system-prompt / append-user-prompt

def test_append_system_prompt_injected(patched_run, monkeypatch):
    """--append-system-prompt: 追加文本落到 agent._system_prompt。"""
    captured = {}

    class _SpyAgent(_FakeAgent):
        def run(self, *a, **k):
            captured["system"] = self._system_prompt
            return super().run(*a, **k)

    monkeypatch.setattr(patched_run, "create_agent", lambda kernel, workspace: _SpyAgent())
    args = _make_args(append_system_prompt="始终用 JSON 输出")
    rc = patched_run.cmd_run(args)
    assert rc == 0
    assert "BASE_SYSTEM_PROMPT" in captured["system"]
    assert "始终用 JSON 输出" in captured["system"]


def test_append_user_prompt_appended_to_task(patched_run, monkeypatch):
    """--append-user-prompt: 追加文本拼到任务末尾后再交给 agent.run。"""
    captured = {}

    class _SpyAgent(_FakeAgent):
        def run(self, *a, **k):
            captured["task"] = k.get("task") or (a[0] if a else "")
            return super().run(*a, **k)

    monkeypatch.setattr(patched_run, "create_agent", lambda kernel, workspace: _SpyAgent())
    args = _make_args(task="总结这个仓库", append_user_prompt="请附 3 条引用")
    rc = patched_run.cmd_run(args)
    assert rc == 0
    assert captured["task"].startswith("总结这个仓库")
    assert "请附 3 条引用" in captured["task"]


# ===================================================================== 4. --session-id 透传

def test_session_id_passed_to_agent(patched_run):
    """--session-id: 指定的会话 ID 原样传给 agent.run(session_id=...)。"""
    agent = _FakeAgent()
    # 直接替换 create_agent 返回我们持有引用的实例
    patched_run.create_agent = lambda kernel, workspace: agent  # type: ignore[attr-defined]
    args = _make_args(session_id="my-ci-run-42")
    rc = patched_run.cmd_run(args)
    assert rc == 0
    assert agent.calls, "agent.run 应被调用"
    assert agent.calls[0]["session_id"] == "my-ci-run-42"


def test_session_id_default_when_absent(patched_run):
    """未指定 --session-id 时: 仍生成非空会话 ID (时间戳+随机)。"""
    agent = _FakeAgent()
    patched_run.create_agent = lambda kernel, workspace: agent  # type: ignore[attr-defined]
    args = _make_args()
    rc = patched_run.cmd_run(args)
    assert rc == 0
    sid = agent.calls[0]["session_id"]
    assert sid and isinstance(sid, str)
