"""headless 权限闸门测试 —— 非 bypassPermissions 模式必须 fail-closed。

背景: stream-json 模式没有交互终端, 也没有 control_request RPC 可回问壳。
旧实现是「往 stderr 打一行提示然后 return True 放行」, 等于把权限护栏做成了
摆设 —— 用户以为在检查权限, 实际什么都没拦。这里钉死 fail-closed 语义。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tuan_cli.stream_json.headless import HeadlessConfig, HeadlessDriver


def _confirm(cfg):
    return HeadlessDriver(cfg)._make_confirm()


def test_bypass_permissions_allows_without_anything():
    """bypassPermissions 是显式全放行, 行为不变。"""
    ask = _confirm(HeadlessConfig(permission_mode="bypassPermissions"))
    assert ask("delete /tmp/x") is True


def test_default_mode_fails_closed_by_default():
    """默认模式没有交互终端 → 必须拒绝, 不能放行。"""
    ask = _confirm(HeadlessConfig(permission_mode="default"))
    assert ask("delete /tmp/x") is False


def test_plan_mode_fails_closed():
    ask = _confirm(HeadlessConfig(permission_mode="plan"))
    assert ask("write_file src/a.py") is False


def test_accept_edits_mode_fails_closed():
    ask = _confirm(HeadlessConfig(permission_mode="acceptEdits"))
    assert ask("edit_file src/a.py") is False


def test_fail_closed_reports_to_stderr(capfd):
    """拒绝时必须在 stderr 说明原因与两条可行路径, 不能静默拒绝。"""
    ask = _confirm(HeadlessConfig(permission_mode="default"))
    assert ask("run_shell rm -rf /tmp/demo") is False
    err = capfd.readouterr().err
    assert "权限请求被拒绝" in err
    assert "run_shell rm -rf /tmp/demo" in err
    assert "permission_mode" in err
    assert "bypassPermissions" in err


def test_fail_closed_can_be_disabled_for_shell_side_gatekeeping():
    """壳侧已自行把关时, fail_closed_on_permission=False 恢复旧的放行行为。"""
    ask = _confirm(HeadlessConfig(
        permission_mode="default",
        fail_closed_on_permission=False,
    ))
    assert ask("edit_file src/a.py") is True


def test_legacy_mode_still_writes_stderr_notice(capfd):
    ask = _confirm(HeadlessConfig(
        permission_mode="plan",
        fail_closed_on_permission=False,
    ))
    assert ask("edit_file src/a.py") is True
    assert "放行" in capfd.readouterr().err
