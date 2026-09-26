"""`!` shell 快捷模式测试 —— 对标 Claude Code Week 26 的 `!` shell mode。

验证:
- `!命令` 不经 LLM 直接执行 shell 并返回输出;
- 执行结果作为带标记消息注入 agent.messages, 下一轮上下文可见;
- 危险命令 (rm -rf) 仍受安全护栏拦截, `!` 不是豁免通道。
"""

from qingxiaotuan.app import build_kernel
from qingxiaotuan.cli.cmd_bang import run_bang_command, split_bang_command
from qingxiaotuan.core.agent import Agent


def _make_agent(tmp_path, qxt_home):
    kernel = build_kernel()
    config = kernel.require("config")
    return Agent(kernel=kernel, config=config, workspace=str(tmp_path),
                 confirm=lambda _p: True)


def test_split_bang_command():
    assert split_bang_command("!echo hello") == "echo hello"
    assert split_bang_command("! pwd") == "pwd"
    assert split_bang_command("！echo hi") == "echo hi"


def test_bang_command_executes(tmp_path, qxt_home):
    agent = _make_agent(tmp_path, qxt_home)
    out = run_bang_command(agent, "!echo hello", display=False)
    assert "hello" in out


def test_bang_result_injected(tmp_path, qxt_home):
    agent = _make_agent(tmp_path, qxt_home)
    before = len(agent.messages)
    run_bang_command(agent, "!echo marker-42", display=False)
    new_msgs = agent.messages[before:]
    assert any("marker-42" in str(m.get("content", "")) for m in new_msgs)


def test_bang_dangerous_blocked(tmp_path, qxt_home):
    agent = _make_agent(tmp_path, qxt_home)
    out = run_bang_command(agent, "!rm -rf /", display=False)
    assert "已拦截" in out
