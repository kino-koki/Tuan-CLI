"""测试: 五模式能力矩阵（§5）allow/deny 判定。"""

from __future__ import annotations

import pytest

from tuan_cli.modes.policy import ModePolicy, get_mode_policy


# =====================================================================
# 基础能力矩阵
# =====================================================================


def test_chat_mode_all_disabled():
    """闲聊 (L0): 文件/Shell/MCP/网络全部物理禁用，仅对话+记忆沙箱+TTS。"""
    p = get_mode_policy("chat")
    assert not p.file_write_allowed()
    assert not p.shell_allowed()
    assert not p.mcp_allowed()
    assert not p.network_allowed()
    assert p.memory_write_allowed()  # 沙箱写入
    assert p.tts_allowed()  # TTS 输出
    # 工具白名单仅包含记忆相关
    tools = p.tool_allowlist()
    assert "memory_read" in tools
    assert "memory_note_append" in tools
    assert "run_shell" not in tools
    assert "write_file" not in tools


def test_collaboration_mode_shell_disabled():
    """协同 (L2): Shell 禁用，工作区读写 + 审计。"""
    p = get_mode_policy("collaboration")
    assert not p.shell_allowed()
    assert p.file_write_allowed()
    assert p.mcp_allowed()  # 仅办公类白名单
    assert p.network_allowed()
    assert p.memory_write_allowed()
    assert p.tts_allowed()
    # 工具白名单包含文件操作
    tools = p.tool_allowlist()
    assert "read_file" in tools
    assert "write_file" in tools
    assert "edit_file" in tools
    assert "run_shell" not in tools


def test_gantong_mode_l3():
    """感通 (L3): 全能力，Shell 受限白名单。"""
    p = get_mode_policy("gantong")
    assert p.shell_allowed()
    assert p.file_write_allowed()
    assert p.mcp_allowed()
    assert p.network_allowed()
    assert p.memory_write_allowed()
    assert p.tts_allowed()
    tools = p.tool_allowlist()
    assert "run_shell" in tools
    assert "write_file" in tools


def test_lingma_mode_l3():
    """灵码 (L3): 代码开发 + Shell + 审计 + 沙箱。"""
    p = get_mode_policy("lingma")
    assert p.shell_allowed()
    assert p.file_write_allowed()
    assert p.mcp_allowed()
    assert p.network_allowed()
    assert p.memory_write_allowed()
    assert p.tts_allowed()
    tools = p.tool_allowlist()
    assert "run_shell" in tools
    assert "write_file" in tools


def test_boundless_mode_l4_desktop():
    """无界 (L4) 桌面: 全能力。"""
    p = get_mode_policy("boundless", platform="desktop")
    assert p.shell_allowed()
    assert p.file_write_allowed()
    assert p.mcp_allowed()
    assert p.network_allowed()
    assert p.memory_write_allowed()
    assert p.tts_allowed()
    tools = p.tool_allowlist()
    assert "run_shell" in tools
    assert "write_file" in tools
    assert "web_fetch" in tools


# =====================================================================
# 平台特化策略（§5.6）
# =====================================================================


def test_boundless_on_android_all_disabled():
    """无界在 Android 物理禁用全部能力。"""
    p = get_mode_policy("boundless", platform="android")
    assert not p.shell_allowed()
    assert not p.mcp_allowed()
    assert not p.network_allowed()
    assert not p.file_write_allowed()
    assert not p.memory_write_allowed()
    assert p.tts_allowed()  # TTS 输出通道不受禁用牵连
    tools = p.tool_allowlist()
    assert len(tools) == 0  # 全部工具禁用


def test_boundless_on_ios_restricted():
    """无界在 iOS: Shell/MCP/文件写入禁用，网络/记忆受限。"""
    p = get_mode_policy("boundless", platform="ios")
    assert not p.shell_allowed()
    assert not p.mcp_allowed()
    assert not p.file_write_allowed()
    assert p.network_allowed()  # 受限但允许
    assert p.memory_write_allowed()  # 受限但允许
    assert p.tts_allowed()


def test_boundless_on_web_restricted():
    """无界在 Web: Shell/MCP/文件写入禁用。"""
    p = get_mode_policy("boundless", platform="web")
    assert not p.shell_allowed()
    assert not p.mcp_allowed()
    assert not p.file_write_allowed()
    assert p.network_allowed()
    assert p.memory_write_allowed()
    assert p.tts_allowed()


def test_boundless_on_windows_no_restrictions():
    """无界在 Windows: 无平台限制。"""
    p = get_mode_policy("boundless", platform="windows")
    assert p.shell_allowed()
    assert p.mcp_allowed()
    assert p.file_write_allowed()
    assert p.network_allowed()
    assert p.memory_write_allowed()
    assert p.tts_allowed()


def test_boundless_on_mac_no_restrictions():
    """无界在 macOS: 无平台限制。"""
    p = get_mode_policy("boundless", platform="mac")
    assert p.shell_allowed()
    assert p.mcp_allowed()
    assert p.file_write_allowed()


def test_boundless_on_linux_no_restrictions():
    """无界在 Linux: 无平台限制。"""
    p = get_mode_policy("boundless", platform="linux")
    assert p.shell_allowed()
    assert p.mcp_allowed()
    assert p.file_write_allowed()


def test_boundless_platform_case_insensitive():
    """平台名称不区分大小写。"""
    p1 = get_mode_policy("boundless", platform="ANDROID")
    assert not p1.shell_allowed()

    p2 = get_mode_policy("boundless", platform="Android")
    assert not p2.shell_allowed()

    p3 = get_mode_policy("boundless", platform="android")
    assert not p3.shell_allowed()


# =====================================================================
# with_platform 链式调用
# =====================================================================


def test_with_platform_chain():
    """with_platform 应支持链式调用。"""
    p = get_mode_policy("boundless")
    p.with_platform("android")
    assert not p.shell_allowed()

    p.with_platform("desktop")
    assert p.shell_allowed()


def test_with_platform_case_insensitive():
    """with_platform 应不区分大小写。"""
    p = get_mode_policy("boundless")
    p.with_platform("IOS")
    assert not p.shell_allowed()

    p.with_platform("ios")
    assert not p.shell_allowed()


# =====================================================================
# 别名解析
# =====================================================================


def test_policy_accepts_alias():
    """ModePolicy 应支持别名模式 ID。"""
    p = get_mode_policy("standard")
    assert p.mode_id == "collaboration"

    p = get_mode_policy("yolo")
    assert p.mode_id == "boundless"

    p = get_mode_policy("plan")
    assert p.mode_id == "chat"


def test_invalid_mode_raises():
    """非法模式 ID 应抛 ValueError。"""
    with pytest.raises(ValueError):
        get_mode_policy("invalid")


# =====================================================================
# capabilities_summary
# =====================================================================


def test_capabilities_summary():
    """capabilities_summary 应返回完整摘要。"""
    p = get_mode_policy("collaboration")
    summary = p.capabilities_summary()
    assert summary["mode"] == "collaboration"
    assert summary["platform"] == "desktop"
    assert summary["shell"] is False
    assert summary["file_write"] is True
    assert "tools_count" in summary
    assert summary["tools_count"] > 0


def test_capabilities_summary_android():
    """Android 上 boundless 的能力摘要应反映全部禁用。"""
    p = get_mode_policy("boundless", platform="android")
    summary = p.capabilities_summary()
    assert summary["shell"] is False
    assert summary["mcp"] is False
    assert summary["network"] is False
    assert summary["file_write"] is False
    assert summary["memory_write"] is False
    assert summary["tools_count"] == 0


# =====================================================================
# 所有模式矩阵汇总
# =====================================================================


@pytest.mark.parametrize(
    "mode_id,expected",
    [
        ("chat", {"shell": False, "mcp": False, "network": False, "file_write": False, "memory_write": True, "tts": True}),
        ("collaboration", {"shell": False, "mcp": True, "network": True, "file_write": True, "memory_write": True, "tts": True}),
        ("gantong", {"shell": True, "mcp": True, "network": True, "file_write": True, "memory_write": True, "tts": True}),
        ("lingma", {"shell": True, "mcp": True, "network": True, "file_write": True, "memory_write": True, "tts": True}),
        ("boundless", {"shell": True, "mcp": True, "network": True, "file_write": True, "memory_write": True, "tts": True}),
    ],
)
def test_mode_capability_matrix(mode_id, expected):
    """五模式能力矩阵汇总验证。"""
    p = get_mode_policy(mode_id, platform="desktop")
    for cap, val in expected.items():
        method = getattr(p, f"{cap}_allowed")
        assert method() == val, f"{mode_id}.{cap} 期望 {val}，实际 {method()}"
