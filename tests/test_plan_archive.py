"""Plan 模式计划存档测试 (对标 Claude Code Plan Mode: 计划产物可存档/可恢复)。

审计发现缺口: exit_plan_mode 此前只把计划文本回灌对话, 不落盘 —— 计划不可存档、
跨会话不可恢复。本次补齐后, 退出 Plan 模式时把经确认的实施计划原子写入
`<workspace>/.tuan/plan.md`, 并发出 plan_mode.saved 事件。

本测试证明:
- exit_plan_handler 把完整计划文本写进 .tuan/plan.md;
- 文件内容含计划正文 + 存档头, 可被后续会话/审计读取;
- 空 plan 仍被拒绝 (不写盘);
- 写盘失败 (workspace 无效) 静默降级, 不阻断退出 Plan 模式。
"""

from __future__ import annotations

import os

from tuan_cli.tools.base import ToolContext
from tuan_cli.tools.session_tools import (
    _archive_plan,
    _enter_plan_handler,
    _exit_plan_handler,
)


class _FakeKernel:
    """最小内核桩: 记录 emit 事件, get() 返回 None。"""

    def __init__(self):
        self.events = []

    def get(self, _name, default=None):
        return default

    def emit(self, name, payload=None):
        self.events.append((name, payload))


def _ctx(tmp_path, plan_mode: bool = False) -> ToolContext:
    return ToolContext(
        kernel=_FakeKernel(), workspace=str(tmp_path), plan_mode=plan_mode,
    )


# ------------------------------------------------------------------ 存档行为

def test_exit_plan_archives_plan_to_disk(tmp_path):
    """退出 Plan 模式并提交计划 → .tuan/plan.md 落盘, 含计划正文。"""
    ctx = _ctx(tmp_path, plan_mode=True)
    plan_text = "1. 修改 auth.py 增加过期校验\n2. 补充单测 test_auth_expiry"
    out = _exit_plan_handler(ctx, plan=plan_text)

    # 退出成功且回灌了计划
    assert "实施计划" in out
    assert ctx.plan_mode is False

    # 计划文件落盘
    plan_file = tmp_path / ".tuan" / "plan.md"
    assert plan_file.exists(), "计划应被存档到 .tuan/plan.md"
    content = plan_file.read_text(encoding="utf-8")
    assert plan_text in content
    assert "已确认实施计划" in content

    # 发出了存档事件
    assert any(name == "plan_mode.saved" for name, _ in ctx.kernel.events)


def test_empty_plan_rejected_no_disk(tmp_path):
    """空 plan 被拒绝, 不写盘、不退出 Plan 模式。"""
    ctx = _ctx(tmp_path, plan_mode=True)
    out = _exit_plan_handler(ctx, plan="   ")
    assert out.startswith("[错误]")
    assert ctx.plan_mode is True, "计划为空时不应退出 Plan 模式"
    assert not (tmp_path / ".tuan").exists() or not (tmp_path / ".tuan" / "plan.md").exists()


def test_archive_atomic_and_readable(tmp_path):
    """存档文件可被直接读取 (恢复用), 且不残留 .tmp 临时文件。"""
    ctx = _ctx(tmp_path)
    plan_text = "重构调度器: 抽出 Scheduler 接口, 替换两处直连实现。"
    path = _archive_plan(ctx, plan_text)
    assert path.endswith(os.path.join(".tuan", "plan.md"))
    on_disk = tmp_path / ".tuan" / "plan.md"
    assert on_disk.read_text(encoding="utf-8").endswith(plan_text + "\n")
    # 无残留临时文件
    assert not (tmp_path / ".tuan" / "plan.md.tmp").exists()


def test_archive_bad_workspace_degrades_silently():
    """workspace 为空/无效时, 存档静默失败但不抛异常 (不阻断主流程)。"""
    ctx = ToolContext(kernel=_FakeKernel(), workspace="", plan_mode=False)
    out = _archive_plan(ctx, "任意计划")
    assert out == ""


def test_enter_exit_roundtrip_resets_flag(tmp_path):
    """enter→exit 一轮: plan_mode 先 True 后 False, 且退出时存档。"""
    ctx = _ctx(tmp_path, plan_mode=False)
    _enter_plan_handler(ctx)
    assert ctx.plan_mode is True
    _exit_plan_handler(ctx, plan="步骤 A → 步骤 B")
    assert ctx.plan_mode is False
    assert (tmp_path / ".tuan" / "plan.md").exists()
