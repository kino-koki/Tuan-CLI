"""Headless/CI 模式增强测试: -p/--print、--output-format json、--bare。

对标 Claude Code 的 `-p/--print` / `--bare` 与 Kimi Code 的 `--output-format stream-json`。
"""

from __future__ import annotations

import io
import json
import types
from types import SimpleNamespace

import pytest


# --------------------------------------------------------------------- 工具替身

class _FakeConfig:
    """最小 Config 替身: 只支持 get/set_user/mode。"""

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
    """记录 run 回调的 Agent 替身。"""

    def __init__(self, answer="你好, 这是回答"):
        self.answer = answer
        self.total_usage = {"prompt_tokens": 11, "completion_tokens": 7}
        self.ctx = SimpleNamespace(
            allowed_tools=None, plan_mode=False, hooks=None,
            ledger=None, checkpoint_store=None,
        )
        self.plan_mode = False
        self.calls = []

    def run(self, task, stream=True, on_token=None, on_reason=None,
            on_tool=None, on_tool_result=None, on_error=None,
            session_id=None, max_iterations=None):
        self.calls.append({"task": task, "stream": stream})
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
    )
    base.update(kw)
    return SimpleNamespace(**base)


@pytest.fixture
def patched_run(monkeypatch):
    """把 cmd_run 的内核/Agent 构建换成替身, 捕获 stdout/stderr。"""
    from qingxiaotuan.cli import cmd_agents

    monkeypatch.setattr(cmd_agents, "build_kernel", lambda *a, **k: _FakeKernel())
    monkeypatch.setattr(cmd_agents, "create_agent", lambda kernel, workspace: _FakeAgent())
    monkeypatch.setattr(cmd_agents, "seed_builtin_skills", lambda *a, **k: 0)
    return cmd_agents


# --------------------------------------------------------------------- 1. print 模式无装饰

def test_print_mode_no_tui_decoration(patched_run, capsys):
    """-p 模式 stdout 只有纯文本回答, 不含 rich 装饰/横幅/预算行。"""
    args = _make_args(print_mode=True, output_format="text")
    rc = patched_run.cmd_run(args)
    assert rc == 0
    out = capsys.readouterr().out
    # 纯文本回答应逐段写出
    assert "你好" in out
    # 不含 rich 控制台标记 / ANSI 转义 / 预算横幅 / 启动装饰
    assert "[" not in out or "你好" in out  # 回答本身不含方括号装饰
    assert "\x1b[" not in out, "不得含 ANSI 转义序列"
    assert "[预算]" not in out
    assert "启动失败" not in out


def test_print_mode_parser_flag():
    """parser: `qxt run -p` / `--print` 都能打开 print_mode, 默认 output_format=text。"""
    from qingxiaotuan.cli.parser import build_parser
    p = build_parser()
    a = p.parse_args(["run", "-p", "任务"])
    assert a.print_mode is True
    assert a.output_format == "text"
    b = p.parse_args(["run", "--print", "任务"])
    assert b.print_mode is True


# --------------------------------------------------------------------- 2. stdin 管道

def test_print_mode_stdin_pipe(monkeypatch):
    """stdin 非 tty 且任务为空时, 读取 stdin 内容作为任务输入。"""
    from qingxiaotuan.cli import cmd_agents

    fake_stdin = io.StringIO("把这段管道文本翻译成英文")
    fake_stdin.isatty = lambda: False  # type: ignore[attr-defined]
    monkeypatch.setattr("sys.stdin", fake_stdin)
    task = cmd_agents._read_stdin_task()
    assert task == "把这段管道文本翻译成英文"


def test_stdin_tty_not_read(monkeypatch):
    """stdin 是 tty 时不读取 (避免阻塞终端交互)。"""
    from qingxiaotuan.cli import cmd_agents

    class _TTY:
        def isatty(self):
            return True

        def read(self):
            raise AssertionError("tty 不应被读取")

    monkeypatch.setattr("sys.stdin", _TTY())
    assert cmd_agents._read_stdin_task() == ""


# --------------------------------------------------------------------- 3. NDJSON 输出

def test_output_format_json_events():
    """--output-format json: 每行一个合法 JSON, 含 text/finish 事件。"""
    from qingxiaotuan.cli.cmd_agents import _NDJsonEmitter

    buf = io.StringIO()
    em = _NDJsonEmitter(sink=buf)
    em.on_token("你好")
    em.on_token(", 世界")
    em.on_tool("read_file", '{"path": "a.txt"}')
    em.on_tool_result("read_file", "文件内容")
    em.on_reason("思考中...")
    em.finish("stop", {"prompt_tokens": 11, "completion_tokens": 7})

    lines = [ln for ln in buf.getvalue().splitlines() if ln.strip()]
    objs = [json.loads(ln) for ln in lines]  # 全部必须是合法 JSON
    types_seen = [o["type"] for o in objs]
    assert "text" in types_seen
    assert "finish" in types_seen
    assert "tool_call" in types_seen
    assert "tool_result" in types_seen
    assert "thinking" in types_seen
    finish = objs[-1]
    assert finish["type"] == "finish"
    assert finish["reason"] == "stop"
    assert finish["usage"]["prompt_tokens"] == 11


def test_output_format_json_end_to_end(patched_run, capsys):
    """cmd_run --output-format json: stdout 全是 NDJSON, 无纯文本混排。"""
    args = _make_args(output_format="json")
    rc = patched_run.cmd_run(args)
    assert rc == 0
    out = capsys.readouterr().out
    lines = [ln for ln in out.splitlines() if ln.strip()]
    assert lines, "json 模式至少应输出事件行"
    objs = [json.loads(ln) for ln in lines]
    types_seen = [o["type"] for o in objs]
    assert "text" in types_seen
    assert "finish" in types_seen
    # finish 必须是最后一行
    assert objs[-1]["type"] == "finish"


# --------------------------------------------------------------------- 4/5. --bare 纯净模式

def test_bare_mode_skips_user_config(qxt_home):
    """--bare 不加载用户级 config.yaml (仅内置默认)。"""
    from qingxiaotuan.config.loader import Config

    qxt_home.mkdir(parents=True, exist_ok=True)
    # 写入用户配置, 覆盖一个内置存在的键
    (qxt_home / "config.yaml").write_text(
        "model:\n  model: \"user-marker-model\"\n", encoding="utf-8")

    normal = Config()
    bare = Config(bare=True)
    # 非 bare: 读到用户配置
    assert normal.get("model.model") == "user-marker-model"
    # bare: 完全忽略用户配置
    assert bare.get("model.model") != "user-marker-model"
    assert getattr(bare, "bare", False) is True


def test_bare_kernel_skips_user_config_and_has_builtin_tools(qxt_home):
    """build_kernel(bare=True): 不读用户配置, 但内置工具仍注册。"""
    from qingxiaotuan.app import build_kernel

    qxt_home.mkdir(parents=True, exist_ok=True)
    (qxt_home / "config.yaml").write_text(
        "model:\n  model: \"user-marker-model\"\n"
        "skills:\n  auto_inject: true\n", encoding="utf-8")

    kernel = build_kernel(bare=True)
    config = kernel.require("config")
    # 用户配置未被叠加
    assert config.get("model.model") != "user-marker-model"
    # 自动注入关闭
    assert config.get("skills.auto_inject") is False
    assert config.get("memory.auto_inject") is False
    # 内置工具仍在
    registry = kernel.require("tool_registry")
    names = [t.name for t in registry.tools]
    assert len(names) >= 5, f"bare 模式仍应保留内置工具, 实际: {names[:10]}"
