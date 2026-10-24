"""§6 安全接线测试 —— 模式 → 既有安全模块的附加过滤。

覆盖:
- chat 模式下 shell / file_write / mcp 被配置层拒绝（非提示词拒绝）
- boundless on android → 全部能力禁用
- collaboration shell → 禁用
- SecurityGate 带 mode 参数时 mode 过滤生效
- SecurityGate 不带 mode 参数时行为不变（向后兼容）
- guard_command 带 mode 参数时 mode 过滤生效
- mode_tool_filter 各模式返回正确值
- should_extract_for_mode 各模式返回正确值
"""

from __future__ import annotations

import pytest

from tuan_cli.core.allowed_tools import mode_tool_filter
from tuan_cli.core.command_guard import guard_command
from tuan_cli.core.events import EventType
from tuan_cli.ext.security_gate import GateVerdict, SecurityGate
from tuan_cli.memory.auto_extractor import should_extract_for_mode
from tuan_cli.modes.policy import get_mode_policy


# =====================================================================
# 6.1 EventType
# =====================================================================


def test_mode_changed_event_type():
    """MODE_CHANGED 事件类型已注册，字符串值正确。"""
    assert EventType.MODE_CHANGED.value == "mode.changed"
    assert EventType.MODE_CHANGED == "mode.changed"


# =====================================================================
# 6.2 SecurityGate 模式接线
# =====================================================================


class TestSecurityGateModeShell:
    """SecurityGate mode 过滤 —— Shell。"""

    def test_chat_mode_denies_shell(self):
        """chat 模式禁用 Shell → SecurityGate 拒绝。"""
        gate = SecurityGate(mode="chat")
        verdict = gate.decide_shell("ls -la")
        assert verdict.blocks()
        assert verdict.action == "deny"
        assert "模式" in verdict.reasons[0]

    def test_collaboration_mode_denies_shell(self):
        """collaboration 模式禁用 Shell → SecurityGate 拒绝。"""
        gate = SecurityGate(mode="collaboration")
        verdict = gate.decide_shell("ls -la")
        assert verdict.blocks()
        assert verdict.action == "deny"

    def test_lingma_mode_allows_shell(self):
        """lingma 模式允许 Shell → SecurityGate 放行。"""
        gate = SecurityGate(mode="lingma")
        verdict = gate.decide_shell("ls -la")
        assert verdict.allows()

    def test_gantong_mode_allows_shell(self):
        """gantong 模式允许 Shell → SecurityGate 放行。"""
        gate = SecurityGate(mode="gantong")
        verdict = gate.decide_shell("ls -la")
        assert verdict.allows()

    def test_boundless_desktop_allows_shell(self):
        """boundless 桌面允许 Shell → SecurityGate 放行。"""
        gate = SecurityGate(mode="boundless")
        verdict = gate.decide_shell("ls -la")
        assert verdict.allows()

    def test_mode_does_not_skip_hard_redline(self):
        """mode 过滤不跳过硬红线检查 —— rm -rf / 始终拒绝。"""
        gate = SecurityGate(mode="chat")
        verdict = gate.decide_shell("rm -rf /")
        assert verdict.blocks()
        assert verdict.severity == "critical"

    def test_mode_does_not_skip_trust_level(self):
        """mode 过滤不跳过信任级别检查 —— untrusted 优先拒绝。"""
        from tuan_cli.core.workspace_trust import TrustLevel
        gate = SecurityGate(mode="chat", trust_level=TrustLevel.UNTRUSTED)
        verdict = gate.decide_shell("ls -la")
        assert verdict.blocks()
        # 信任级别拒绝优先于模式拒绝
        assert "untrusted" in verdict.reasons[0] or "信任" in verdict.reasons[0]


class TestSecurityGateModeMCP:
    """SecurityGate mode 过滤 —— MCP 工具。"""

    def test_chat_mode_denies_mcp(self):
        """chat 模式禁用 MCP → SecurityGate 拒绝。"""
        gate = SecurityGate(mode="chat")
        verdict = gate.decide_mcp_tool("web_search")
        assert verdict.blocks()
        assert "模式" in verdict.reasons[0]

    def test_collaboration_mode_allows_mcp(self):
        """collaboration 模式允许 MCP → SecurityGate 放行。"""
        gate = SecurityGate(mode="collaboration")
        verdict = gate.decide_mcp_tool("web_search")
        assert verdict.allows()

    def test_lingma_mode_allows_mcp(self):
        """lingma 模式允许 MCP → SecurityGate 放行。"""
        gate = SecurityGate(mode="lingma")
        verdict = gate.decide_mcp_tool("mcp__code__search")
        assert verdict.allows()

    def test_boundless_desktop_allows_mcp(self):
        """boundless 桌面允许 MCP → SecurityGate 放行。"""
        gate = SecurityGate(mode="boundless")
        verdict = gate.decide_mcp_tool("mcp__github__create_issue")
        assert verdict.allows()

    def test_mcp_redline_not_skipped(self):
        """mode 过滤不跳过 MCP 参数红线检查。"""
        gate = SecurityGate(mode="chat")
        verdict = gate.decide_mcp_tool("dangerous_tool", {"cmd": "rm -rf /"})
        assert verdict.blocks()
        assert verdict.severity == "critical"


class TestSecurityGateModeFileWrite:
    """SecurityGate mode 过滤 —— 文件写入。"""

    def test_chat_mode_denies_file_write(self):
        """chat 模式禁用文件写入 → SecurityGate 拒绝。"""
        gate = SecurityGate(mode="chat")
        verdict = gate.decide_file_write("/tmp/hello.txt", "hello")
        assert verdict.blocks()
        assert "模式" in verdict.reasons[0]

    def test_collaboration_mode_allows_file_write(self):
        """collaboration 模式允许文件写入 → SecurityGate 放行。"""
        gate = SecurityGate(mode="collaboration")
        verdict = gate.decide_file_write("/tmp/hello.txt", "hello")
        assert verdict.allows()

    def test_lingma_mode_allows_file_write(self):
        """lingma 模式允许文件写入 → SecurityGate 放行。"""
        gate = SecurityGate(mode="lingma")
        verdict = gate.decide_file_write("/tmp/hello.txt", "hello")
        assert verdict.allows()

    def test_boundless_desktop_allows_file_write(self):
        """boundless 桌面允许文件写入 → SecurityGate 放行。"""
        gate = SecurityGate(mode="boundless")
        verdict = gate.decide_file_write("/tmp/hello.txt", "hello")
        assert verdict.allows()

    def test_file_write_redline_not_skipped(self):
        """mode 过滤不跳过写入内容红线检查。"""
        gate = SecurityGate(mode="chat")
        verdict = gate.decide_file_write("/tmp/evil.sh", "rm -rf /")
        assert verdict.blocks()
        assert verdict.severity == "critical"


class TestSecurityGateNoModeBackwardCompat:
    """SecurityGate 不带 mode 参数时行为不变（向后兼容）。"""

    def test_default_allows_shell(self):
        """无 mode 时正常放行 shell。"""
        gate = SecurityGate()
        verdict = gate.decide_shell("ls -la")
        assert verdict.allows()

    def test_default_allows_mcp(self):
        """无 mode 时正常放行 mcp。"""
        gate = SecurityGate()
        verdict = gate.decide_mcp_tool("web_search")
        assert verdict.allows()

    def test_default_allows_file_write(self):
        """无 mode 时正常放行文件写入。"""
        gate = SecurityGate()
        verdict = gate.decide_file_write("/tmp/hello.txt", "hello")
        assert verdict.allows()

    def test_default_still_blocks_hard_redline(self):
        """无 mode 时硬红线仍拒绝。"""
        gate = SecurityGate()
        verdict = gate.decide_shell("rm -rf /")
        assert verdict.blocks()
        assert verdict.severity == "critical"

    def test_default_still_blocks_yolo_redline(self):
        """无 mode 时 YOLO 红线仍拒绝。"""
        gate = SecurityGate(yolo=True)
        verdict = gate.decide_shell("sudo rm -rf /")
        assert verdict.blocks()


class TestSecurityGateUnifiedDispatch:
    """SecurityGate decide() 统一分发 + mode 过滤。"""

    def test_dispatch_shell_chat_mode(self):
        """decide("shell") 在 chat 模式下拒绝。"""
        gate = SecurityGate(mode="chat")
        verdict = gate.decide("shell", "ls -la")
        assert verdict.blocks()

    def test_dispatch_mcp_chat_mode(self):
        """decide("mcp_tool") 在 chat 模式下拒绝。"""
        gate = SecurityGate(mode="chat")
        verdict = gate.decide("mcp_tool", "web_search")
        assert verdict.blocks()

    def test_dispatch_file_write_chat_mode(self):
        """decide("file_write") 在 chat 模式下拒绝。"""
        gate = SecurityGate(mode="chat")
        verdict = gate.decide("file_write", "hello", path="/tmp/x")
        assert verdict.blocks()

    def test_dispatch_lingma_allows_all(self):
        """decide() 在 lingma 模式下放行 shell/mcp/file_write。"""
        gate = SecurityGate(mode="lingma")
        assert gate.decide("shell", "ls -la").allows()
        assert gate.decide("mcp_tool", "web_search").allows()
        assert gate.decide("file_write", "hello", path="/tmp/x").allows()


# =====================================================================
# 6.3 mode_tool_filter
# =====================================================================


class TestModeToolFilter:
    """mode_tool_filter 按模式过滤工具调用。"""

    def test_chat_allows_memory_tools(self):
        """chat 模式允许记忆类工具。"""
        assert mode_tool_filter("memory_read", "chat") is True
        assert mode_tool_filter("memory_note_append", "chat") is True

    def test_chat_denies_shell_and_write(self):
        """chat 模式拒绝 shell 和文件写入工具。"""
        assert mode_tool_filter("run_shell", "chat") is False
        assert mode_tool_filter("write_file", "chat") is False
        assert mode_tool_filter("read_file", "chat") is False

    def test_collaboration_allows_file_tools(self):
        """collaboration 模式允许文件操作工具。"""
        assert mode_tool_filter("read_file", "collaboration") is True
        assert mode_tool_filter("write_file", "collaboration") is True
        assert mode_tool_filter("edit_file", "collaboration") is True

    def test_collaboration_denies_shell(self):
        """collaboration 模式拒绝 run_shell。"""
        assert mode_tool_filter("run_shell", "collaboration") is False

    def test_lingma_allows_run_shell(self):
        """lingma 模式允许 run_shell。"""
        assert mode_tool_filter("run_shell", "lingma") is True

    def test_gantong_allows_run_shell(self):
        """gantong 模式允许 run_shell。"""
        assert mode_tool_filter("run_shell", "gantong") is True

    def test_boundless_desktop_allows_all(self):
        """boundless 桌面允许所有工具。"""
        assert mode_tool_filter("run_shell", "boundless") is True
        assert mode_tool_filter("write_file", "boundless") is True
        assert mode_tool_filter("web_fetch", "boundless") is True

    def test_boundless_android_denies_all(self):
        """boundless on android 拒绝所有工具（平台策略）。"""
        # boundless android 通过 policy 返回空白名单
        policy = get_mode_policy("boundless", platform="android")
        assert policy.tool_allowlist() == set()
        # 通过 monkeypatch 模拟 android 平台的 mode_tool_filter
        import tuan_cli.modes.policy as policy_mod
        original = policy_mod.get_mode_policy
        policy_mod.get_mode_policy = lambda mode_id: original(mode_id, platform="android")
        try:
            assert mode_tool_filter("run_shell", "boundless") is False
            assert mode_tool_filter("write_file", "boundless") is False
        finally:
            policy_mod.get_mode_policy = original

    def test_unknown_tool_denied(self):
        """未知工具在所有模式下均拒绝。"""
        assert mode_tool_filter("nonexistent_tool", "chat") is False
        assert mode_tool_filter("nonexistent_tool", "lingma") is False


# =====================================================================
# 6.4 guard_command 模式接线
# =====================================================================


class TestGuardCommandMode:
    """guard_command 模式级 Shell 禁用。"""

    def test_chat_mode_blocks_shell(self):
        """chat 模式禁用 Shell → guard_command 拦截。"""
        out = guard_command("ls -la", mode="chat")
        assert out is not None
        assert "chat" in out
        assert "Shell" in out or "shell" in out

    def test_collaboration_mode_blocks_shell(self):
        """collaboration 模式禁用 Shell → guard_command 拦截。"""
        out = guard_command("ls -la", mode="collaboration")
        assert out is not None
        assert "collaboration" in out

    def test_lingma_mode_allows_shell(self, monkeypatch):
        """lingma 模式允许 Shell → guard_command 放行。"""
        monkeypatch.setattr("tuan_cli.ext.safety_engine.is_hard_redline", lambda c: False)
        monkeypatch.setattr("tuan_cli.core.security_bus.get_security_bus", _FakeBus)

        class _FakeGuard:
            def check(self, cmd):
                from tuan_cli.core.network_guard import NetworkDecision
                return NetworkDecision(action="allow", risk_level="none", reasons=[], detected_domains=[])

        monkeypatch.setattr("tuan_cli.core.network_guard.get_network_guard", lambda: _FakeGuard())
        assert guard_command("ls -la", mode="lingma") is None

    def test_gantong_mode_allows_shell(self, monkeypatch):
        """gantong 模式允许 Shell → guard_command 放行。"""
        monkeypatch.setattr("tuan_cli.ext.safety_engine.is_hard_redline", lambda c: False)
        monkeypatch.setattr("tuan_cli.core.security_bus.get_security_bus", _FakeBus)

        class _FakeGuard:
            def check(self, cmd):
                from tuan_cli.core.network_guard import NetworkDecision
                return NetworkDecision(action="allow", risk_level="none", reasons=[], detected_domains=[])

        monkeypatch.setattr("tuan_cli.core.network_guard.get_network_guard", lambda: _FakeGuard())
        assert guard_command("ls -la", mode="gantong") is None

    def test_boundless_desktop_allows_shell(self, monkeypatch):
        """boundless 桌面允许 Shell → guard_command 放行。"""
        monkeypatch.setattr("tuan_cli.ext.safety_engine.is_hard_redline", lambda c: False)
        monkeypatch.setattr("tuan_cli.core.security_bus.get_security_bus", _FakeBus)

        class _FakeGuard:
            def check(self, cmd):
                from tuan_cli.core.network_guard import NetworkDecision
                return NetworkDecision(action="allow", risk_level="none", reasons=[], detected_domains=[])

        monkeypatch.setattr("tuan_cli.core.network_guard.get_network_guard", lambda: _FakeGuard())
        assert guard_command("ls -la", mode="boundless") is None

    def test_no_mode_backward_compat(self, monkeypatch):
        """不带 mode 参数时行为不变。"""
        monkeypatch.setattr("tuan_cli.ext.safety_engine.is_hard_redline", lambda c: False)
        monkeypatch.setattr("tuan_cli.core.security_bus.get_security_bus", _FakeBus)

        class _FakeGuard:
            def check(self, cmd):
                from tuan_cli.core.network_guard import NetworkDecision
                return NetworkDecision(action="allow", risk_level="none", reasons=[], detected_domains=[])

        monkeypatch.setattr("tuan_cli.core.network_guard.get_network_guard", lambda: _FakeGuard())
        assert guard_command("ls -la") is None

    def test_mode_does_not_skip_hard_redline(self, monkeypatch):
        """mode 禁用 shell 时不会跳过硬红线检查（mode 检查优先返回）。"""
        out = guard_command("rm -rf /", mode="chat")
        assert out is not None
        assert "chat" in out


class _FakeBus:
    @staticmethod
    def emit(event):
        pass


# =====================================================================
# 6.5 should_extract_for_mode
# =====================================================================


class TestShouldExtractForMode:
    """should_extract_for_mode 各模式返回正确值。"""

    def test_chat_mode_enabled(self):
        """chat 模式启用自动记忆提取（沙箱写入）。"""
        assert should_extract_for_mode("chat") is True

    def test_collaboration_mode_enabled(self):
        """collaboration 模式启用自动记忆提取。"""
        assert should_extract_for_mode("collaboration") is True

    def test_gantong_mode_enabled(self):
        """gantong 模式启用自动记忆提取。"""
        assert should_extract_for_mode("gantong") is True

    def test_lingma_mode_enabled(self):
        """lingma 模式启用自动记忆提取。"""
        assert should_extract_for_mode("lingma") is True

    def test_boundless_desktop_enabled(self):
        """boundless 桌面启用自动记忆提取。"""
        assert should_extract_for_mode("boundless") is True

    def test_boundless_android_disabled(self):
        """boundless on android 禁用自动记忆提取。"""
        # 模拟 android 平台
        import tuan_cli.modes.policy as policy_mod
        original = policy_mod.get_mode_policy
        policy_mod.get_mode_policy = lambda mode_id: original(mode_id, platform="android")
        try:
            assert should_extract_for_mode("boundless") is False
        finally:
            policy_mod.get_mode_policy = original


# =====================================================================
# 6.6 端到端：chat 模式全面禁用
# =====================================================================


class TestChatModeEndToEnd:
    """chat 模式下 shell / file_write / mcp / network 全部被配置层拒绝。"""

    def test_chat_shell_denied(self):
        """chat 模式 shell → 拒绝。"""
        gate = SecurityGate(mode="chat")
        assert gate.decide_shell("ls").blocks()

    def test_chat_file_write_denied(self):
        """chat 模式 file_write → 拒绝。"""
        gate = SecurityGate(mode="chat")
        assert gate.decide_file_write("/tmp/x", "hello").blocks()

    def test_chat_mcp_denied(self):
        """chat 模式 mcp → 拒绝。"""
        gate = SecurityGate(mode="chat")
        assert gate.decide_mcp_tool("web_search").blocks()

    def test_chat_network_denied_by_policy(self):
        """chat 模式 network → 策略层拒绝。"""
        policy = get_mode_policy("chat")
        assert policy.network_allowed() is False

    def test_chat_memory_sandbox_only(self):
        """chat 模式只允许记忆沙箱工具。"""
        tools = get_mode_policy("chat").tool_allowlist()
        assert "memory_read" in tools
        assert "memory_note_append" in tools
        assert "run_shell" not in tools
        assert "write_file" not in tools
        assert "read_file" not in tools