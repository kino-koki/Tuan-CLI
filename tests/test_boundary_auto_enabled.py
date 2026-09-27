"""四层边界「默认自动生效」测试。

覆盖改造目标:
- Project 层: 会话启动后 ``.qxt/`` 自动存在 (ensure_project_context);
- Chat 层: 超阈值时自动执行交接 (auto_handoff_if_needed), 而非仅提示;
- Subagent 层: should_isolate_task 启发式;
- Worktree 层: detect_parallel_intent 启发式 + 非 git 仓库优雅跳过;
- bare 模式 / 配置开关 的短路行为。

全部使用临时目录 (tmp_path / qxt_home), 不污染真实工作区。
"""

from __future__ import annotations

from qingxiaotuan.core.boundary_auto import (
    auto_create_parallel_worktree,
    detect_parallel_intent,
    ensure_project_context,
    should_isolate_task,
    try_run_isolated,
)
from qingxiaotuan.core.chat_handoff import ChatHandoff


class Cfg:
    """鸭子类型配置 (与 tests/test_chat_handoff.py 同风格)。"""

    def __init__(self, **data):
        self.data = data

    def get(self, k, d=None):
        return self.data.get(k, d)


# ------------------------------------------------------------ 1. Project 层自动初始化

def test_ensure_project_context_creates_qxt(tmp_path, qxt_home):
    """新会话启动后, .qxt/ 应自动存在 (无需手动 qxt project init)。"""
    ws = tmp_path / "proj"
    ws.mkdir()
    assert not (ws / ".qxt").exists()
    info = ensure_project_context(ws)
    assert info.initialized is True
    assert info.project_id
    assert (ws / ".qxt" / "project.json").exists()


def test_ensure_project_context_idempotent(tmp_path, qxt_home):
    """重复启动会话不重复初始化 (project_id 不变)。"""
    ws = tmp_path / "proj"
    ws.mkdir()
    i1 = ensure_project_context(ws)
    i2 = ensure_project_context(ws)
    assert i1.project_id == i2.project_id


def test_ensure_project_context_respects_off_switch(tmp_path, qxt_home):
    """project.auto_init=false 时不创建目录。"""
    ws = tmp_path / "plain"
    ws.mkdir()
    info = ensure_project_context(ws, config=Cfg(**{"project.auto_init": False}))
    assert info.initialized is False
    assert not (ws / ".qxt").exists()


# ------------------------------------------------------------ 2. Chat 层: 超阈值自动交接

def test_auto_handoff_triggers_when_over_threshold(tmp_path):
    """超阈值时 auto_handoff_if_needed 应直接执行交接 (返回报告), 而非仅提示。"""
    handoff = ChatHandoff(tmp_path)
    messages = [
        {"role": "user", "content": "写一个登录模块"},
        {"role": "assistant", "content": "已完成 login.py"},
    ]
    # 900/1000 = 90% > 默认阈值 80%
    report = handoff.auto_handoff_if_needed(900, 1000, "old-sess-1", messages)
    assert report is not None
    assert report.old_session_id == "old-sess-1"
    assert report.new_session_id != "old-sess-1"
    assert report.summary  # 非空摘要
    # 交接谱系落盘
    records = handoff.list_handoffs()
    assert len(records) == 1
    assert records[0]["new_session_id"] == report.new_session_id


def test_auto_handoff_none_below_threshold(tmp_path):
    """未达阈值不交接。"""
    handoff = ChatHandoff(tmp_path)
    report = handoff.auto_handoff_if_needed(100, 1000, "old-1", [])
    assert report is None
    assert handoff.list_handoffs() == []


def test_auto_handoff_respects_disable_switch(tmp_path):
    """chat.auto_handoff_enabled=false 时即使超阈值也不自动执行。"""
    cfg = Cfg(**{"chat.auto_handoff_enabled": False})
    handoff = ChatHandoff(tmp_path, config=cfg)
    report = handoff.auto_handoff_if_needed(9999, 1000, "old-1", [])
    assert report is None


# ------------------------------------------------------------ 3. Subagent 层: 重任务启发式

def test_should_isolate_task_heuristic():
    # 普通短任务: 不隔离
    assert should_isolate_task("帮我看看这个报错") is False
    # 多任务并行关键词: 隔离
    assert should_isolate_task("请同时处理前端和后端两件事") is True
    assert should_isolate_task("这几个脚本要并行跑") is True
    assert should_isolate_task("分别调研三个竞品") is True
    assert should_isolate_task("独立跑一个性能压测") is True
    assert should_isolate_task("另外再补一份文档") is True
    # 长任务 (>500 字符): 隔离
    assert should_isolate_task("整理一下 " + "x" * 600) is True


def test_try_run_isolated_short_circuits():
    """短任务 / bare / 关闭开关: 不触发真实子代理 (返回 None, 回退主会话)。"""
    # 短任务: 不触发
    assert try_run_isolated(object(), "短任务一句话") is None
    # bare 模式跳过
    assert try_run_isolated(object(), "同时做 A 和 B", bare=True) is None
    # 关闭开关跳过 (即使是重任务)
    cfg = Cfg(**{"subagent.auto_isolate": False})
    assert try_run_isolated(object(), "同时做 A 和 B", config=cfg) is None


# ------------------------------------------------------------ 4. Worktree 层: 并行实验启发式

def test_detect_parallel_intent_heuristic():
    assert detect_parallel_intent("帮我实现登录页") is None
    # 方案 A / 方案 B 对比
    assert detect_parallel_intent("试一下方案 A 和方案 B 哪个好") == "experiment-1"
    # 两种方式
    assert detect_parallel_intent("两种方式都跑一下看结果") == "experiment-1"
    # 另一种思路
    assert detect_parallel_intent("要不试一下另一种思路") == "experiment-1"
    # 自定义 counter
    assert detect_parallel_intent("对比两个方案", counter=2) == "experiment-2"


def test_auto_create_parallel_worktree_non_git_skips_gracefully(tmp_path):
    """非 git 仓库: 优雅跳过 (返回 None, 不报错)。"""
    ws = tmp_path / "notrepo"
    ws.mkdir()
    info = auto_create_parallel_worktree(ws, "对比方案 A 和 B", config=None, bare=False)
    assert info is None


def test_auto_create_parallel_worktree_bare_skips(tmp_path):
    """bare 模式: 即使是 git 仓库也跳过 (评测可复现)。"""
    # 非 git 仓库 + bare 双重保险, 直接 None
    assert auto_create_parallel_worktree(tmp_path, "对比两个方案", bare=True) is None
