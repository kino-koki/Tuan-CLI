"""B2: Chat 交接测试 —— 阈值检测、交接流程 (mock LLM 摘要)、新会话继承。"""

from __future__ import annotations

import json

from qingxiaotuan.core.chat_handoff import (
    ChatHandoff,
    build_summary,
    should_handoff,
)


def test_should_handoff_threshold():
    assert should_handoff(700, 1000, 0.8) is False
    assert should_handoff(800, 1000, 0.8) is True
    assert should_handoff(900, 1000, 0.8) is True
    assert should_handoff(0, 0, 0.8) is False  # 未知窗口不触发


def test_build_summary_heuristic_extracts_sections(tmp_path):
    messages = [
        {"role": "user", "content": "目标: 给 CLI 加 CSV 导出功能"},
        {"role": "assistant", "content": "已实现导出模块 exporter.py"},
        {"role": "user", "content": "待办: 补单测"},
    ]
    s = build_summary(messages)
    assert "## 目标" in s
    assert "## 已完成" in s
    assert "## 待办" in s
    assert "exporter.py" in s  # 从对话中提取出的关键文件


def test_build_summary_with_llm_override():
    calls = []

    def fake_llm(prompt: str) -> str:
        calls.append(prompt)
        return "## 目标\n做测试\n## 已完成\n无\n## 待办\n无"

    messages = [{"role": "user", "content": "hi"}]
    s = build_summary(messages, generate_fn=fake_llm)
    assert "做测试" in s
    assert calls and "交接" in calls[0]  # 确实调用了 LLM


def test_handoff_flow(tmp_path):
    handoff = ChatHandoff(tmp_path)
    messages = [
        {"role": "user", "content": "写一个登录模块"},
        {"role": "assistant", "content": "已完成 login.py 初版"},
    ]
    report = handoff.handoff("old-session-1", messages, project_id="proj-1")
    assert report.old_session_id == "old-session-1"
    assert report.new_session_id != "old-session-1"
    assert report.archived is True
    assert report.summary  # 非空摘要
    # 交接记录落盘 (.qxt/handoffs.json)
    records = handoff.list_handoffs()
    assert len(records) == 1
    assert records[0]["old_session_id"] == "old-session-1"
    assert records[0]["new_session_id"] == report.new_session_id


def test_maybe_prompt_threshold_config(tmp_path):
    class Cfg:
        def __init__(self):
            self.data = {"chat.handoff_enabled": True, "chat.auto_handoff_threshold": 0.5}
        def get(self, k, d=None):
            return self.data.get(k, d)
    h = ChatHandoff(tmp_path, config=Cfg())
    assert h.threshold == 0.5
    assert h.maybe_prompt(600, 1000) is True   # 60% > 50%
    assert h.maybe_prompt(400, 1000) is False  # 40% < 50%


def test_handoff_disabled(tmp_path):
    class Cfg:
        def get(self, k, d=None):
            return {"chat.handoff_enabled": False}.get(k, d)
    h = ChatHandoff(tmp_path, config=Cfg())
    assert h.maybe_prompt(9999, 1000) is False
