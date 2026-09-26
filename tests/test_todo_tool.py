"""TodoWrite 持久化工具测试 —— 对标 Claude Code 的 TodoWrite。

验证:
- todo_write 创建任务清单并落盘到 <workspace>/.qxt/todo.json;
- todo_list 列出当前任务与进度;
- 状态更新 (pending/in_progress/completed) 后进度正确;
- 新 Agent/全新 ctx 进入同一工作区时, todo_list 从磁盘恢复 (跨调用持久化)。
"""

from qingxiaotuan.app import build_kernel
from qingxiaotuan.core.agent import Agent
from qingxiaotuan.tools.todo_tool import todo_file_path


def _make_agent(tmp_path):
    kernel = build_kernel()
    config = kernel.require("config")
    agent = Agent(kernel=kernel, config=config, workspace=str(tmp_path))
    return kernel.require("tool_registry"), agent


def test_todo_write_creates_tasks(tmp_path, qxt_home):
    reg, agent = _make_agent(tmp_path)
    out = reg.get("todo_write").handler(agent.ctx, todos=[
        {"content": "第一步", "status": "in_progress"},
        {"content": "第二步", "status": "pending"},
    ])
    assert "已更新" in out
    assert todo_file_path(tmp_path).exists()
    assert agent.ctx.todos and agent.ctx.todos[0]["content"] == "第一步"


def test_todo_list_returns_tasks(tmp_path, qxt_home):
    reg, agent = _make_agent(tmp_path)
    reg.get("todo_write").handler(agent.ctx, todos=[
        {"content": "写测试用例", "status": "completed"},
    ])
    out = reg.get("todo_list").handler(agent.ctx)
    assert "写测试用例" in out
    assert "进度" in out


def test_todo_update_status(tmp_path, qxt_home):
    reg, agent = _make_agent(tmp_path)
    reg.get("todo_write").handler(agent.ctx, todos=[
        {"content": "任务A", "status": "in_progress"},
        {"content": "任务B", "status": "pending"},
    ])
    # 全量覆盖: 把任务A 标为完成
    reg.get("todo_write").handler(agent.ctx, todos=[
        {"content": "任务A", "status": "completed"},
        {"content": "任务B", "status": "pending"},
    ])
    out = reg.get("todo_list").handler(agent.ctx)
    assert "1/2" in out


def test_todo_persists_across_calls(tmp_path, qxt_home):
    kernel = build_kernel()
    config = kernel.require("config")
    reg = kernel.require("tool_registry")
    agent1 = Agent(kernel=kernel, config=config, workspace=str(tmp_path))
    reg.get("todo_write").handler(agent1.ctx, todos=[
        {"content": "跨会话保留的任务", "status": "in_progress"},
    ])
    # 新 Agent / 全新 ctx: 内存态为空, 应从 .qxt/todo.json 恢复
    agent2 = Agent(kernel=kernel, config=config, workspace=str(tmp_path))
    assert agent2.ctx.todos is None
    out = reg.get("todo_list").handler(agent2.ctx)
    assert "跨会话保留的任务" in out
