"""audit_query 工具真实接入回归测试。

此前 auditstore 只有 CLI 入口 (cmd_auditstore.py), Agent 工具面缺失。
本文件验证 `audit_query` 工具注册后, Agent 可以只读查询内核审计归档
(stats/recent/query), 底层走真 AuditStore 链路; 空归档时友好降级。
"""

from pathlib import Path

import pytest

from tuan_cli.app import build_kernel
from tuan_cli.core.agent import Agent
from tuan_cli.audit.store import AuditStore


def _make_ctx(tmp_path):
    kernel = build_kernel()
    config = kernel.require("config")
    agent = Agent(kernel=kernel, config=config, workspace=str(tmp_path),
                  confirm=lambda _p: True)
    return kernel, agent


def _seed(kernel):
    """用真实 AuditStore 写入路径 (store.log) 播种三条事件。"""
    home = Path(kernel.require("config").home)
    store = AuditStore(home=home)
    store.log("tool.executed", {"tool": "run_shell", "cmd": "echo hi"})
    store.log("model.call", {"model": "deepseek-chat", "tokens": 100})
    store.log("tool.executed", {"tool": "read_file", "path": "a.py"})
    return home


# ------------------------------------------------------------------ 注册

def test_audit_query_registered(tuan_home):
    kernel = build_kernel()
    names = {t.name for t in kernel.require("tool_registry").tools}
    assert "audit_query" in names, "audit_query 工具未接入 Agent 工具面"


# ------------------------------------------------------------------ stats

def test_stats_on_seeded_store(tmp_path, tuan_home):
    kernel, agent = _make_ctx(tmp_path)
    _seed(kernel)
    out = kernel.require("tool_registry").get("audit_query").handler(
        agent.ctx, op="stats")
    assert "总事件 3" in out
    assert "tool.executed" in out and "model.call" in out
    assert "audit.log" in out


# ------------------------------------------------------------------ recent

def test_recent_lists_events_with_limit(tmp_path, tuan_home):
    kernel, agent = _make_ctx(tmp_path)
    _seed(kernel)
    handler = kernel.require("tool_registry").get("audit_query").handler
    out = handler(agent.ctx, op="recent", limit=2)
    lines = [l for l in out.splitlines() if l.startswith("#")]
    assert len(lines) == 2
    out_all = handler(agent.ctx, op="recent")
    assert "deepseek-chat" in out_all  # payload 摘要可见
    out_f = handler(agent.ctx, op="recent", type="tool.executed")
    assert out_f.count("tool.executed") >= 2 and "model.call" not in out_f


# ------------------------------------------------------------------ query

def test_query_by_type_and_keyword(tmp_path, tuan_home):
    kernel, agent = _make_ctx(tmp_path)
    _seed(kernel)
    handler = kernel.require("tool_registry").get("audit_query").handler
    out = handler(agent.ctx, op="query", type="tool.executed")
    assert "审计查询结果 2 条" in out
    out_kw = handler(agent.ctx, op="query", keyword="deepseek")
    assert "1 条" in out_kw and "model.call" in out_kw
    out_none = handler(agent.ctx, op="query", keyword="不存在的词")
    assert "查询无结果" in out_none
    # 归档已初始化时, 未知 op 与非法 limit 得到明确错误提示
    assert "未知 op" in handler(agent.ctx, op="nope")
    assert "limit 非法" in handler(agent.ctx, op="recent", limit="abc")


# ------------------------------------------------------------------ 边界

def test_empty_store_friendly(tmp_path, tuan_home, monkeypatch):
    kernel, agent = _make_ctx(tmp_path)
    # 空归档场景: 把工具的 home 指向一个确定没有 audit.log 的目录
    # (build_kernel 的审计插件可能在启动时已写入事件, 不能依赖真实 home)。
    import tuan_cli.tools.audit_tool as audit_tool
    monkeypatch.setattr(audit_tool, "_home", lambda ctx: tmp_path / "noaudit")
    handler = kernel.require("tool_registry").get("audit_query").handler
    # 归档未初始化时, 任何 op 都先得到友好降级提示 (纯只读, 不建目录)
    assert "未初始化" in handler(agent.ctx, op="stats")
    assert "未初始化" in handler(agent.ctx, op="recent")
    assert "未初始化" in handler(agent.ctx, op="nope")
