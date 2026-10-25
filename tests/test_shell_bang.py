"""`!` shell 快捷模式测试 —— 对标 Claude Code Week 26 的 `!` shell mode。

验证:
- `!命令` 不经 LLM 直接执行 shell 并返回输出;
- 执行结果作为带标记消息注入 agent.messages, 下一轮上下文可见;
- 危险命令 (rm -rf) 仍受安全护栏拦截, `!` 不是豁免通道。
"""

from tuan_cli.app import build_kernel
from tuan_cli.cli.cmd_bang import run_bang_command, split_bang_command
from tuan_cli.core.agent import Agent


def _make_agent(tmp_path, tuan_home):
    kernel = build_kernel()
    config = kernel.require("config")
    return Agent(kernel=kernel, config=config, workspace=str(tmp_path),
                 confirm=lambda _p: True)


def test_split_bang_command():
    assert split_bang_command("!echo hello") == "echo hello"
    assert split_bang_command("! pwd") == "pwd"
    assert split_bang_command("！echo hi") == "echo hi"


def test_bang_command_executes(tmp_path, tuan_home):
    agent = _make_agent(tmp_path, tuan_home)
    out = run_bang_command(agent, "!echo hello", display=False)
    assert "hello" in out


def test_bang_result_injected(tmp_path, tuan_home):
    agent = _make_agent(tmp_path, tuan_home)
    before = len(agent.messages)
    run_bang_command(agent, "!echo marker-42", display=False)
    new_msgs = agent.messages[before:]
    assert any("marker-42" in str(m.get("content", "")) for m in new_msgs)


def test_bang_dangerous_blocked(tmp_path, tuan_home):
    """无确认通道时, 危险命令必须 fail-closed 被拦截。

    注意: 不能给 agent 传 confirm=lambda _p: True —— 那等于模拟用户显式同意,
    而 run_shell 的硬红线设计是「不自动执行, 但有人确认时可人工放行」, 于是命令
    会真的跑起来 (Windows 下 rm 不存在, 表现为 "'rm' is not recognized")。
    本用例测的是安全保证本身: 没有人在场时绝不允许执行。
    """
    kernel = build_kernel()
    config = kernel.require("config")
    agent = Agent(kernel=kernel, config=config, workspace=str(tmp_path),
                  confirm=None)
    out = run_bang_command(agent, "!rm -rf /", display=False)
    assert "已拦截" in out


def test_bang_dangerous_confirmed_proceeds(tmp_path, tuan_home):
    """有确认通道且用户显式放行时, 硬红线可人工放行 (设计如此, 非豁免通道)。"""
    kernel = build_kernel()
    config = kernel.require("config")
    agent = Agent(kernel=kernel, config=config, workspace=str(tmp_path),
                  confirm=lambda _p: True)
    out = run_bang_command(agent, "!echo confirmed-ok", display=False)
    assert "confirmed-ok" in out

