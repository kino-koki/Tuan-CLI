"""五模式切换子系统 —— 感通/灵码/闲聊/无界/协同。"""

from .registry import (
    MODE_ALIASES,
    MODE_IDS,
    MODE_LEVELS,
    MODE_NAMES,
    MODE_REGISTRY,
    MODE_RISK,
    get_mode_meta,
    resolve_mode_id,
)
from .switcher import check_transition, current_mode, switch_mode
from .policy import ModePolicy, get_mode_policy

__all__ = [
    "MODE_IDS",
    "MODE_NAMES",
    "MODE_LEVELS",
    "MODE_RISK",
    "MODE_ALIASES",
    "MODE_REGISTRY",
    "get_mode_meta",
    "resolve_mode_id",
    "check_transition",
    "current_mode",
    "switch_mode",
    "ModePolicy",
    "get_mode_policy",
]
