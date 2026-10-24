"""模式能力策略 —— 能力矩阵（§5）。

每个模式定义一组能力开关：
    - tool_allowlist: 工具白名单
    - shell_allowed / mcp_allowed / network_allowed / file_write_allowed
    - memory_write_allowed / tts_allowed

平台特化策略（§5.6）: boundless 在 Android 物理禁用，
Web/iOS 部分能力受限，桌面平台无限制。
"""

from __future__ import annotations

from typing import Any, Dict, Set

from .registry import (
    BOUNDLESS_PLATFORM_RESTRICTIONS,
    MODE_REGISTRY,
    get_mode_meta,
)


class ModePolicy:
    """模式能力策略。

    根据模式 ID + 平台，提供各能力的 allow/deny 判定。
    boundless 在非桌面平台会应用物理禁用策略。
    """

    def __init__(self, mode_id: str, platform: str = "desktop") -> None:
        meta = get_mode_meta(mode_id)
        self._mode_id: str = meta["id"]
        self._platform: str = platform.lower()
        self._capabilities: Dict[str, Any] = dict(meta["capabilities"])

    # ------------------------------------------------------------------
    # 平台特化辅助
    # ------------------------------------------------------------------

    @property
    def mode_id(self) -> str:
        return self._mode_id

    @property
    def platform(self) -> str:
        return self._platform

    def with_platform(self, platform: str) -> "ModePolicy":
        """切换平台并重新计算能力（返回自身以支持链式调用）。"""
        self._platform = platform.lower()
        return self

    def _apply_platform(self, cap_name: str, default: bool) -> bool:
        """对 boundless 应用平台特化限制。"""
        if self._mode_id != "boundless":
            return default
        restrictions = BOUNDLESS_PLATFORM_RESTRICTIONS.get(self._platform, {})
        if cap_name in restrictions:
            return restrictions[cap_name]
        return default

    # ------------------------------------------------------------------
    # 能力查询
    # ------------------------------------------------------------------

    def tool_allowlist(self) -> Set[str]:
        """返回该模式下允许的工具名称集合。"""
        tools = self._capabilities.get("tools", [])
        # boundless 在非桌面平台时移除物理禁用的工具
        if self._mode_id == "boundless" and self._platform == "android":
            return set()
        return set(tools)

    def shell_allowed(self) -> bool:
        """Shell 执行是否允许。"""
        return self._apply_platform("shell", self._capabilities.get("shell", False))

    def mcp_allowed(self) -> bool:
        """MCP 工具调用是否允许。"""
        return self._apply_platform("mcp", self._capabilities.get("mcp", False))

    def network_allowed(self) -> bool:
        """网络访问是否允许。"""
        return self._apply_platform("network", self._capabilities.get("network", False))

    def file_write_allowed(self) -> bool:
        """文件写入是否允许。"""
        return self._apply_platform("file_write", self._capabilities.get("file_write", False))

    def memory_write_allowed(self) -> bool:
        """记忆写入是否允许（闲聊为沙箱写入，非桌面平台受限）。"""
        return self._apply_platform("memory_write", self._capabilities.get("memory_write", False))

    def tts_allowed(self) -> bool:
        """TTS 输出是否允许（闲聊允许，不受其他禁用牵连）。"""
        return self._capabilities.get("tts", False)

    # ------------------------------------------------------------------
    # 辅助
    # ------------------------------------------------------------------

    def capabilities_summary(self) -> Dict[str, Any]:
        """返回能力摘要字典（供 mode show 打印）。"""
        return {
            "mode": self._mode_id,
            "platform": self._platform,
            "shell": self.shell_allowed(),
            "mcp": self.mcp_allowed(),
            "network": self.network_allowed(),
            "file_write": self.file_write_allowed(),
            "memory_write": self.memory_write_allowed(),
            "tts": self.tts_allowed(),
            "tools_count": len(self.tool_allowlist()),
        }


def get_mode_policy(mode_id: str, platform: str = "desktop") -> ModePolicy:
    """工厂函数：创建指定模式 + 平台的能力策略实例。

    参数:
        mode_id: 模式 ID（支持别名）。
        platform: 平台标识（desktop/windows/mac/linux/android/ios/web）。

    返回:
        ModePolicy 实例。
    """
    return ModePolicy(mode_id, platform=platform)
