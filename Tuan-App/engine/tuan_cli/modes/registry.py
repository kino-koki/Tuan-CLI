"""五模式注册表 —— ID → 元数据的单一来源。

模式体系（§3 五模式完整切换 + §5 能力矩阵）：
    感通 (gantong)     L3 高成本/不可逆二次确认，官方多模态
    灵码 (lingma)      L3 代码开发，Shell + 审计 + 沙箱
    闲聊 (chat)        L0 受限陪伴，仅对话与记忆沙箱
    无界 (boundless)   L4 全能力，桌面白名单，Android 物理禁用
    协同 (collaboration) L2 工作区读写 + 审计，Shell 禁用

历史三档别名（standard/yolo/plan）全部保留为别名（MODE_ALIASES），
通过 get_mode_meta 统一解析，不丢失向后兼容性。
"""

from __future__ import annotations

from typing import Any, Dict, Tuple

# =====================================================================
# 常量
# =====================================================================

MODE_IDS: Tuple[str, ...] = (
    "gantong",
    "lingma",
    "chat",
    "boundless",
    "collaboration",
)

MODE_NAMES: Dict[str, str] = {
    "gantong": "感通",
    "lingma": "灵码",
    "chat": "闲聊",
    "boundless": "无界",
    "collaboration": "协同",
}

MODE_LEVELS: Dict[str, str] = {
    "chat": "L0",
    "collaboration": "L2",
    "gantong": "L3",
    "lingma": "L3",
    "boundless": "L4",
}

MODE_RISK: Dict[str, str] = {
    "chat": "低",
    "collaboration": "中",
    "gantong": "高",
    "lingma": "高",
    "boundless": "极高",
}

# 历史三档别名映射（旧名 → 新 ID）
MODE_ALIASES: Dict[str, str] = {
    "standard": "collaboration",
    "yolo": "boundless",
    "plan": "chat",
}

# 权限等级数值序（用于比较升级/降级）
_LEVEL_ORDER: Dict[str, int] = {
    "L0": 0, "L1": 1, "L2": 2, "L3": 3, "L4": 4,
}

# =====================================================================
# 完整注册表
# =====================================================================

# 每个模式的 capabilities 字典描述该模式允许的基础能力。
# tool_allowlist 列出该模式下模型可调用的高权限工具名称子集。
# platform_restrictions 描述 boundless 在非桌面平台的物理禁用策略（§5.6）。

MODE_REGISTRY: Dict[str, Dict[str, Any]] = {
    # ---- 闲聊 (L0) ----
    "chat": {
        "id": "chat",
        "name": "闲聊",
        "level": "L0",
        "risk": "低",
        "description": "受限陪伴模式，仅对话与记忆沙箱，文件/Shell/MCP/网络物理禁用",
        "loop": {"enabled": False, "max_iterations": 1},
        "capabilities": {
            "tools": [
                "memory_read",
                "memory_note_append",
            ],
            "shell": False,
            "mcp": False,
            "network": False,
            "file_write": False,
            "memory_write": True,
            "tts": True,
        },
    },

    # ---- 协同 (L2) ----
    "collaboration": {
        "id": "collaboration",
        "name": "协同",
        "level": "L2",
        "risk": "中",
        "description": "工作区读写 + 审计；Shell 禁用；MCP 仅办公类白名单（文档转换/日历/项目看板）",
        "loop": {"enabled": True, "max_iterations": 6},
        "capabilities": {
            "tools": [
                "read_file", "write_file", "edit_file",
                "list_files", "glob", "move_file", "delete_file",
                "memory_read", "memory_note_append",
                "web_search", "web_fetch",
            ],
            "shell": False,
            "mcp": True,
            "network": True,
            "file_write": True,
            "memory_write": True,
            "tts": True,
        },
    },

    # ---- 感通 (L3) ----
    "gantong": {
        "id": "gantong",
        "name": "感通",
        "level": "L3",
        "risk": "高",
        "description": "官方多模态 + 认证 MCP + 文件读写 + 审计；Shell 受限白名单",
        "loop": {"enabled": True, "max_iterations": 20},
        "capabilities": {
            "tools": [
                "read_file", "write_file", "edit_file",
                "list_files", "glob", "move_file", "delete_file",
                "run_shell",
                "memory_read", "memory_note_append",
                "web_search", "web_fetch",
            ],
            "shell": True,
            "mcp": True,
            "network": True,
            "file_write": True,
            "memory_write": True,
            "tts": True,
        },
    },

    # ---- 灵码 (L3) ----
    "lingma": {
        "id": "lingma",
        "name": "灵码",
        "level": "L3",
        "risk": "高",
        "description": "代码开发 + Shell + 审计 + 沙箱；MCP 代码白名单（代码搜索/CI-CD/依赖检查/单测执行）",
        "loop": {"enabled": True, "max_iterations": 20},
        "capabilities": {
            "tools": [
                "read_file", "write_file", "edit_file",
                "list_files", "glob", "move_file", "delete_file",
                "run_shell",
                "memory_read", "memory_note_append",
                "web_search", "web_fetch",
            ],
            "shell": True,
            "mcp": True,
            "network": True,
            "file_write": True,
            "memory_write": True,
            "tts": True,
        },
    },

    # ---- 无界 (L4) ----
    "boundless": {
        "id": "boundless",
        "name": "无界",
        "level": "L4",
        "risk": "极高",
        "description": "全能力但需平台白名单 + 二次确认 + 审计 + 快照；Android 物理禁用",
        "loop": {"enabled": True, "max_iterations": 30},
        "capabilities": {
            "tools": [
                "read_file", "write_file", "edit_file",
                "list_files", "glob", "move_file", "delete_file",
                "run_shell",
                "memory_read", "memory_note_append",
                "web_search", "web_fetch",
            ],
            "shell": True,
            "mcp": True,
            "network": True,
            "file_write": True,
            "memory_write": True,
            "tts": True,
        },
    },
}

# boundless 在各平台的物理禁用/受限策略（§5.6）
# 键: 平台名, 值: {能力名: 是否允许}
BOUNDLESS_PLATFORM_RESTRICTIONS: Dict[str, Dict[str, bool]] = {
    # Android 物理禁用全部能力
    "android": {
        "shell": False,
        "mcp": False,
        "network": False,
        "file_write": False,
        "memory_write": False,
    },
    # iOS 受限/禁用
    "ios": {
        "shell": False,
        "mcp": False,
        "file_write": False,
    },
    # Web 受限/禁用
    "web": {
        "shell": False,
        "mcp": False,
        "file_write": False,
    },
    # 桌面平台无限制
    "desktop": {},
    "windows": {},
    "mac": {},
    "linux": {},
}

# 桌面平台白名单（boundless 仅允许在桌面平台启用）
DESKTOP_PLATFORMS: frozenset[str] = frozenset({"desktop", "windows", "mac", "linux"})


def level_order(level: str) -> int:
    """将权限等级字符串转为可比较的整数。未知等级返回 -1。"""
    return _LEVEL_ORDER.get(level, -1)


def resolve_mode_id(mode_id: str) -> str:
    """解析模式 ID（含别名），返回标准 ID。

    参数:
        mode_id: 模式 ID 或别名 (如 "standard" / "yolo" / "plan")。

    返回:
        标准模式 ID（如 "collaboration" / "boundless" / "chat"）。

    异常:
        ValueError: 未知模式 ID。
    """
    resolved = MODE_ALIASES.get(mode_id, mode_id)
    if resolved not in MODE_REGISTRY:
        raise ValueError(
            f"未知模式 ID: {mode_id!r} (可选: {'/'.join(MODE_IDS)}; "
            f"别名: {'/'.join(MODE_ALIASES.keys())})"
        )
    return resolved


def get_mode_meta(mode_id: str) -> Dict[str, Any]:
    """获取模式元数据（含别名解析）。

    参数:
        mode_id: 模式 ID 或别名。

    返回:
        模式元数据字典（包含 id, name, level, risk, description, loop, capabilities）。

    异常:
        ValueError: 未知模式 ID。
    """
    resolved = resolve_mode_id(mode_id)
    return MODE_REGISTRY[resolved]
