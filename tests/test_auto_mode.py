"""Auto Mode (对标 Claude Code) 接线回归测试。

覆盖三类路径:
1. 主路径 PermissionPolicy.decide(tool, args, auto_classifier=...):
   - 安全操作 (read_file) 自动批准
   - 敏感/危险操作 (run_shell 危险命令, delete_file) 仍需确认
   - 硬红线 (rm -rf /) 仍由内置加固拒绝 (分类器 auto_approve 不放行)
   - 分类器异常 fail-safe 回退常规决策
2. AutoModeClassifier 本身: 按风险等级分级
3. 备用策略链 runtime.tools.permission.AutoModeApprovePolicy:
   - AUTO 模式 + 安全操作 -> APPROVE
   - AUTO 模式 + 危险操作 -> ASK
   - 非 AUTO 模式 -> 不干预 (None)
"""

import pytest

from tuan_cli.core.auto_mode import AutoModeClassifier, RiskLevel
from tuan_cli.tools.permissions import PermissionDecision, PermissionPolicy


# ------------------------------------------------------------------ 简单工具桩

class _Tool:
    def __init__(self, name: str) -> None:
        self.name = name


# ------------------------------------------------------------------ 主路径

def test_auto_mode_safe_tool_auto_approves():
    """Auto 模式: 只读工具自动批准。"""
    policy = PermissionPolicy(config=None)
    decision = policy.decide(
        _Tool("read_file"), {"path": "/tmp/a.txt"},
        auto_classifier=AutoModeClassifier(),
    )
    assert decision.action == "allow"
    assert "Auto 模式自动批准" in decision.reason


def test_auto_mode_dangerous_shell_needs_confirm():
    """Auto 模式: 危险 shell 命令需确认。"""
    policy = PermissionPolicy(config=None)
    decision = policy.decide(
        _Tool("run_shell"), {"command": "rm -rf /tmp/important"},
        auto_classifier=AutoModeClassifier(),
    )
    assert decision.action == "confirm"
    assert "Auto 模式分类器要求确认" in decision.reason


def test_auto_mode_delete_file_needs_confirm():
    """Auto 模式: delete_file 为 HIGH 风险, 需确认。"""
    policy = PermissionPolicy(config=None)
    decision = policy.decide(
        _Tool("delete_file"), {"path": "/tmp/x"},
        auto_classifier=AutoModeClassifier(),
    )
    assert decision.action == "confirm"


def test_auto_mode_redline_never_auto_approved():
    """硬红线 (rm -rf /) 即使分类器自动批准, 也由内置加固拒绝。"""
    policy = PermissionPolicy(config=None)
    decision = policy.decide(
        _Tool("run_shell"), {"command": "rm -rf /"},
        auto_classifier=AutoModeClassifier(),
    )
    # 内置加固 (长命令/FD/PS 等) 在分类器之前; 硬红线最终走 deny。
    assert decision.action in {"confirm", "deny"}


def test_auto_mode_classifier_exception_failsafe():
    """分类器抛异常时回退常规决策 (fail-safe), 不崩溃。"""

    class _Boom:
        def assess(self, tool_name, args):
            raise RuntimeError("classifier boom")

    policy = PermissionPolicy(config=None)
    # 无 yolo 时, run_shell 常规路径 -> confirm; read_file 常规路径 -> 非拒绝
    decision = policy.decide(_Tool("read_file"), {"path": "/tmp/a"},
                             auto_classifier=_Boom())
    assert decision.action in {"allow", "confirm"}


def test_auto_mode_no_classifier_uses_regular_path():
    """未传分类器时走常规决策 (不因 auto 参数缺失而报错)。"""
    policy = PermissionPolicy(config=None)
    decision = policy.decide(_Tool("read_file"), {"path": "/tmp/a"})
    assert decision.action in {"allow", "confirm"}


# ------------------------------------------------------------------ 不越级护栏
# AutoModeClassifier 自带正则远弱于 ext.safety_engine: 下列命令被分类器误判 LOW
# (auto_approve=True), 若 decide() 在分类器命中时直接 return allow, 会先于下游
# _hardening_confirm 越级放行安全引擎判定的红线命令。护栏必须把它们的 auto_approve
# 兜底降级为 confirm —— 倒数第二道防线不可越级放行。


@pytest.mark.parametrize("command", [
    "rsync --delete /x /etc",       # 目标端系统目录毁灭 (正则贪婪匹配不到)
    "killall -9 -1",                 # 向 PID=-1 发 KILL (整机崩溃)
    "dd if=/dev/zero of=/dev/sda",   # 直写裸磁盘
    "chmod -R 000 /",                # 权限全灭
    "truncate -s 0 /etc/passwd",     # 截断认证文件
    "mkfs.ext4 /dev/sdb",            # 格式化
    "vssadmin delete shadows /all",  # Windows 删卷影 (反勒索恢复)
    ":(){ :|:& };:",                 # fork bomb
])
def test_auto_approve_never_bypasses_engine_redline(command):
    """安全引擎判红线但 AutoMode 弱正则误判 auto_approve 的命令, 不得放行。"""
    from tuan_cli.ext.safety_engine import is_redline
    # 前置: 确认这些命令确实是安全引擎红线, 且分类器会误判为 auto_approve
    assert is_redline(command), f"测试前提失效: {command} 未被安全引擎判红线"
    assessment = AutoModeClassifier().assess("run_shell", {"command": command})
    if not assessment.auto_approve:
        pytest.skip("分类器已正确判高危, 非越级场景")
    # 护栏: decide() 必须把 auto_approve 降级为 confirm, 不能 return allow
    policy = PermissionPolicy(config=None)
    decision = policy.decide(
        _Tool("run_shell"), {"command": command},
        auto_classifier=AutoModeClassifier(),
    )
    assert decision.action != "allow", (
        f"自动决策越级放行安全引擎红线: {command}"
    )


def test_auto_approve_allows_benign_shell():
    """护栏不误伤: 良性 shell 命令在 Auto 模式下仍自动批准。"""
    policy = PermissionPolicy(config=None)
    for command in ("ls -la", "git status", "cat README.md"):
        decision = policy.decide(
            _Tool("run_shell"), {"command": command},
            auto_classifier=AutoModeClassifier(),
        )
        assert decision.action == "allow", f"良性命令被护栏误拦: {command}"


def test_auto_mode_no_yolo_confirm_redline_when_classifier_absent():
    """无 yolo、无分类器时, 内置加固 (超长命令) 仍走 confirm (常规路径不受 auto 影响)。"""
    policy = PermissionPolicy(config=None)
    decision = policy.decide(
        _Tool("run_shell"), {"command": "echo " + "x" * 20_000},
    )
    assert decision.action in {"confirm", "deny"}


# ------------------------------------------------------------------ 分类器本身

def test_classifier_safe_level():
    c = AutoModeClassifier()
    a = c.assess("read_file", {"path": "/tmp/a"})
    assert a.level == RiskLevel.SAFE
    assert a.auto_approve is True
    assert a.needs_confirm is False


def test_classifier_dangerous_shell_level():
    c = AutoModeClassifier()
    a = c.assess("run_shell", {"command": "sudo reboot"})
    assert a.level >= RiskLevel.HIGH
    assert a.needs_confirm is True


def test_classifier_delete_file_level():
    c = AutoModeClassifier()
    a = c.assess("delete_file", {"path": "/tmp/x"})
    assert a.level == RiskLevel.HIGH
    assert a.needs_confirm is True


# ------------------------------------------------------------------ 备用策略链

def _make_policy_ctx(tool_name: str, args: dict):
    from tuan_cli.runtime.tools.before_execute_event import BeforeToolExecuteEvent
    from tuan_cli.runtime.tools.contract import (
        ExecutableToolResult, RunnableToolExecution, ToolCall,
    )

    class _Exec:
        def __init__(self):
            self.description = f"Run {tool_name}"
            self.display = None
            self.accesses = []
            self.result = ExecutableToolResult(output="", is_error=False)
            self.resource_accesses = []

    class _ToolCall:
        def __init__(self):
            self.id = "call_1"
            self.name = tool_name
            self.arguments = args

    class _ExecResult:
        def __init__(self):
            self.output = ""
            self.is_error = False

    tool_call = _ToolCall()
    execution = _Exec()
    # 需要 tool_call.name / execution.accesses / execution.description
    execution.tool_call = tool_call
    return BeforeToolExecuteEvent(
        turn_id=1, signal=None, trace=None,
        tool_call=tool_call, tool_calls=[tool_call], tool=None,
        args=args, execution=execution,
    )


def test_auto_approve_policy_auto_mode_approves_safe():
    from tuan_cli.runtime.tools.permission import (
        AutoModeApprovePolicy, PermissionDecision as RtDecision,
        PermissionMode, _ModeHolder,
    )
    holder = _ModeHolder(PermissionMode.AUTO)
    policy = AutoModeApprovePolicy(holder)
    result = policy.evaluate(_make_policy_ctx("read_file", {"path": "/tmp/a"}))
    assert result is not None
    assert result.kind == RtDecision.APPROVE


def test_auto_approve_policy_auto_mode_asks_dangerous():
    from tuan_cli.runtime.tools.permission import (
        AutoModeApprovePolicy, PermissionDecision as RtDecision,
        PermissionMode, _ModeHolder,
    )
    holder = _ModeHolder(PermissionMode.AUTO)
    policy = AutoModeApprovePolicy(holder)
    result = policy.evaluate(_make_policy_ctx("run_shell", {"command": "sudo reboot"}))
    assert result is not None
    assert result.kind == RtDecision.ASK


def test_auto_approve_policy_non_auto_mode_noop():
    from tuan_cli.runtime.tools.permission import (
        AutoModeApprovePolicy, PermissionMode, _ModeHolder,
    )
    holder = _ModeHolder(PermissionMode.MANUAL)
    policy = AutoModeApprovePolicy(holder)
    result = policy.evaluate(_make_policy_ctx("read_file", {"path": "/tmp/a"}))
    assert result is None
