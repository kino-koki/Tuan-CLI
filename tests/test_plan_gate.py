"""HK-1: Plan Mode 本地审批门测试。

覆盖:
- exit_plan_mode 在 plan_mode 下 + 用户拒绝 -> 阻止退出, 写操作仍拦截;
- 用户批准 -> 放行并标记 plan_approved;
- YOLO 模式跳过确认直接放行;
- plan_mode=False 时 exit_plan_mode 不受影响;
- 其他工具 (非 exit_plan_mode) 不受审批门影响。
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from tuan_cli.tools.base import Tool, ToolRegistry


def _make_tool() -> Tool:
    """构造与生产版 ``build_exit_plan_mode_tool()`` 同形的工具。

    注意: 必须声明 ``plan`` 属性 —— 分发管线 Stage 0 会丢弃 schema 未声明的
    参数, 若此处漏声明, ``plan`` 会被当作未知参数静默丢弃, 审批提示就再也
    拿不到计划摘要, 测试也就在验证一个不存在的场景。
    """
    return Tool(
        name="exit_plan_mode",
        description="退出计划模式",
        parameters={
            "type": "object",
            "properties": {"plan": {"type": "string", "description": "完整的实施计划 (必填)"}},
            "required": ["plan"],
        },
        handler=lambda ctx, **kw: "已退出计划模式",
        dangerous=False,
        read_only=True,
    )


def _make_registry() -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(_make_tool())
    return reg


def _make_ctx(plan_mode, confirm_cb=None, yolo=False):
    kernel = SimpleNamespace(
        get=lambda name, default=None: None,
        require=lambda name: SimpleNamespace(),
        emit=lambda *a, **kw: None,
    )
    return SimpleNamespace(
        plan_mode=plan_mode,
        yolo=yolo,
        confirm=confirm_cb,
        kernel=kernel,
        permissions=None,
        ledger=None,
        safety_advice=None,
        ui=None,
        on_auto_approve=None,
    )


def test_exit_plan_rejected_without_approval():
    reg = _make_registry()
    ctx = _make_ctx(plan_mode=True, confirm_cb=lambda prompt: False)
    res = reg.dispatch_result("exit_plan_mode", json.dumps({"plan": "改 x 文件"}), ctx)
    assert res.status == "denied"
    assert "计划未获批准" in res.content
    assert not getattr(ctx, "plan_approved", False)


def test_exit_plan_allowed_with_approval():
    reg = _make_registry()
    approved = []
    ctx = _make_ctx(plan_mode=True,
                    confirm_cb=lambda prompt: approved.append(prompt) or True)
    res = reg.dispatch_result("exit_plan_mode", json.dumps({"plan": "改 x 文件"}), ctx)
    assert res.status == "ok"
    assert ctx.plan_approved is True
    # 确认提示里包含计划内容
    assert "改 x 文件" in approved[0]


def test_exit_plan_yolo_skips_confirm():
    reg = _make_registry()
    ctx = _make_ctx(plan_mode=True, confirm_cb=None, yolo=True)
    res = reg.dispatch_result("exit_plan_mode", json.dumps({"plan": "计划"}), ctx)
    assert res.status == "ok"
    assert ctx.plan_approved is True


def test_exit_plan_headless_fails_closed():
    # 无 confirm 回调 (headless/CI): 拒绝, 不静默放行
    reg = _make_registry()
    ctx = _make_ctx(plan_mode=True, confirm_cb=None)
    res = reg.dispatch_result("exit_plan_mode", json.dumps({"plan": "计划"}), ctx)
    assert res.status == "denied"
    assert not getattr(ctx, "plan_approved", False)


def test_exit_plan_outside_plan_mode_untouched():
    reg = _make_registry()
    ctx = _make_ctx(plan_mode=False, confirm_cb=None)
    res = reg.dispatch_result("exit_plan_mode", json.dumps({"plan": "计划"}), ctx)
    assert res.status == "ok"  # 不在计划模式, 正常放行


def test_other_tool_unaffected_by_gate():
    reg = _make_registry()
    reg.register(Tool(name="read_file", description="读文件",
                      parameters={"type": "object", "properties": {}},
                      handler=lambda ctx, **kw: "内容", read_only=True))
    ctx = _make_ctx(plan_mode=True, confirm_cb=None)
    res = reg.dispatch_result("read_file", "{}", ctx)
    assert res.status == "ok"  # 读工具在 plan 模式正常放行
