"""Codex TUI 默认键位表 + 运行时解析（本地等价实现）。

逐值来自上游 ``codex-rs/tui/src/keymap.rs::built_in_defaults()`` 与
``codex-rs/config/src/tui_keymap.rs``。这不是 Rust 源码复制，而是把
**可核验的功能事实**（哪个动作绑哪个键、解析优先级、冲突规则）用 Python
独立实现，供 Tuan TUI 对齐使用。

对齐 ``keymap.rs`` 模块头声明的 4 条职责：
1. 确定性优先级（context -> global fallback -> built-in defaults）；
2. 把规范化键位串解析成绑定；
3. 强制唯一性，同一个键不能在同一输入路径触发多个动作；
4. 返回带配置路径与下一步建议的可读错误。

非职责（同样对齐上游）：不决定某屏幕该跑哪个动作、不持久化配置。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from .upstream_spec import spec_identity, normalize_key_spec, KeySpecError

# ---------------------------------------------------------------- 固定键位
# 上游把这些视为不可重绑的保留键（见 keymap/voice_tests.rs:
# ("ctrl-c", "fixed.interrupt_or_quit")）。本地化也不改，保证行为一致。
FIXED_BINDINGS: Dict[str, str] = {
    "ctrl-c": "fixed.interrupt_or_quit",
}

# ---------------------------------------------------------------- 默认键位表
# 结构: context -> action -> 绑定元组。空元组 = 上游未绑定该动作。
# 每个串都经过 normalize_key_spec() 校验，保证与上游规范化结果一致。
CODEX_DEFAULT_BINDINGS: Dict[str, Dict[str, Tuple[str, ...]]] = {
    "app": {
        "open_agents": (),
        "open_transcript": ("ctrl-t",),
        "find_transcript": ("f3",),
        "select_transcript": (),
        "focus_activity": ("f4",),
        "open_warnings": ("f2",),
        "open_external_editor": ("ctrl-g",),
        "copy": ("ctrl-o",),
        "clear_terminal": ("ctrl-l",),
        "toggle_vim_mode": (),
        "toggle_fast_mode": (),
        "toggle_raw_output": ("alt-r",),
        "toggle_side_conversation": ("ctrl-/",),
    },
    "chat": {
        "open_presets": (),
        "toggle_voice": ("f8",),
        "toggle_voice_mute": ("f9",),
        "interrupt_turn": ("esc",),
        "decrease_reasoning_effort": ("alt-,", "shift-down"),
        "increase_reasoning_effort": ("alt-.", "shift-up"),
        "previous_permission_mode": (),
        "next_permission_mode": (),
        "edit_queued_message": ("shift-left", "alt-up"),
        "prompt_stack_back": ("shift-right", "alt-down"),
        "skip_question": ("ctrl-]",),
    },
    "composer": {
        "submit": ("enter",),
        "queue": ("tab",),
        "toggle_shortcuts": ("?", "shift-?"),
        "history_search_previous": ("ctrl-r",),
        "history_search_next": ("ctrl-s",),
    },
    "editor": {
        "insert_newline": ("ctrl-j", "ctrl-m", "enter", "shift-enter", "alt-enter"),
        "move_left": ("left", "ctrl-b"),
        "move_right": ("right", "ctrl-f"),
        "move_up": ("up", "ctrl-p"),
        "move_down": ("down", "ctrl-n"),
        "move_word_left": ("alt-b", "alt-left", "ctrl-left"),
        "move_word_right": ("alt-f", "alt-right", "ctrl-right"),
        "move_line_start": ("home", "ctrl-a", "super-left"),
        "move_line_end": ("end", "ctrl-e", "super-right"),
        "delete_backward": ("backspace", "shift-backspace"),
        "kill_line_end": ("ctrl-k",),
        "yank": ("ctrl-y",),
    },
    "approval": {
        # 上游 approval_overlay.rs 的选项键位。上一轮 Tuan 用 y/n/s/1/2/3，
        # 本轮改为与 Codex 一致，旧键位保留为「本地化兼容别名」。
        "open_fullscreen": (),
        "open_thread": ("o",),
        "approve": ("y",),
        "approve_for_session": ("a",),
        "approve_for_prefix": ("p",),
        "deny": ("d",),
        "decline": ("esc", "n"),
        "cancel": ("c",),
    },
    "list": {
        "move_up": ("up", "k"),
        "move_down": ("down", "j"),
        "move_left": ("left", "ctrl-h"),
        "move_right": ("right", "ctrl-l"),
        "page_up": ("page-up", "ctrl-b"),
        "page_down": ("page-down", "ctrl-f"),
        "jump_top": ("home",),
        "jump_bottom": ("end",),
        "accept": ("enter",),
        "cancel": ("esc",),
    },
    "pager": {
        "scroll_up": ("up", "k"),
        "scroll_down": ("down", "j"),
        "page_up": ("page-up",),
        "page_down": ("page-down",),
        "half_page_up": ("ctrl-u",),
        "half_page_down": ("ctrl-d",),
        "jump_top": ("home",),
        "jump_bottom": ("end",),
        "close": ("q", "ctrl-c"),
        "close_transcript": ("ctrl-t",),
        "find": ("f3", "/"),
    },
    "agents": {
        "resume": ("o",),
        "search": ("f3", "/"),
        "new_task": ("n",),
        "new_worktree": ("w",),
        "fork": ("f",),
        "rename": ("r",),
        "stop": ("x",),
        "archive": ("a",),
        "delete": ("backspace",),
        "hide": ("h",),
        "toggle_pin": ("p",),
        "toggle_grouping": ("g",),
    },
}

# 本地化策略：键位保持与 Codex **完全相同**（这是「完全相同」最可验证的
# 一部分），本地化只作用于文案、模型、路径、配色、审批作用域语义。
TUAN_KEYMAP_OVERRIDES: Dict[str, Dict[str, Tuple[str, ...]]] = {}


class KeymapConflict(ValueError):
    """键位冲突：同一输入路径上一键多动作，或占用保留键。"""


def _normalize_binding(raw: str, *, path: str) -> str:
    try:
        return spec_identity(raw)
    except KeySpecError as exc:
        raise KeymapConflict(f"{path}: {exc}") from exc


@dataclass
class RuntimeKeymap:
    """完全解析后的键位快照（对齐上游 ``RuntimeKeymap``）。

    构造后即已应用：规范化、context 覆盖、global 回退、显式解绑、
    唯一性校验。调用方不应再保留旧快照，否则提示与处理器会漂移。
    """

    bindings: Dict[str, Dict[str, Tuple[str, ...]]] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)

    # ------------------------------------------------------------ 构造
    @classmethod
    def defaults(cls) -> "RuntimeKeymap":
        return cls.from_config({})

    @classmethod
    def from_config(cls, overrides: Optional[Mapping[str, Mapping[str, object]]] = None,
                    *, strict: bool = True) -> "RuntimeKeymap":
        """按 context -> global -> defaults 优先级解析。

        ``overrides`` 形如 ``{"composer": {"submit": ["ctrl-enter"]}}``。
        值语义（对齐上游 ``KeybindingsSpec`` 三态）：
          - 键不存在        -> 用回退/默认；
          - ``[]`` / None   -> **显式解绑**（不等同于「未配置」）；
          - 字符串或列表    -> 自定义绑定。
        ``global`` 段的条目作为所有 context 的次级回退（仅对上游支持
        global fallback 的动作生效；这里对所有同名动作生效，行为可核验）。
        """
        ov = dict(overrides or {})
        global_ov = dict(ov.pop("global", {}) or {})
        merged: Dict[str, Dict[str, object]] = {
            ctx: dict(actions) for ctx, actions in CODEX_DEFAULT_BINDINGS.items()
        }
        # 本地化覆盖（当前为空表，保留接口）
        for ctx, actions in TUAN_KEYMAP_OVERRIDES.items():
            merged.setdefault(ctx, {}).update(
                {k: list(v) for k, v in actions.items()})

        errors: List[str] = []
        for ctx, actions in list(merged.items()):
            ctx_ov = dict(ov.get(ctx, {}) or {})
            ctx_ov_original = set(ctx_ov)
            global_ov_original = set(global_ov)
            for action in list(actions.keys()):
                if action in ctx_ov:
                    raw = ctx_ov.pop(action)
                elif action in global_ov:
                    raw = global_ov[action]
                else:
                    raw = actions[action]
                path = f"tui.keymap.{ctx}.{action}"
                if raw is None:
                    merged[ctx][action] = ()
                    continue
                if isinstance(raw, str):
                    raws: Sequence[object] = [raw]
                elif isinstance(raw, (list, tuple)):
                    raws = list(raw)
                else:
                    errors.append(f"{path}: 绑定值必须是字符串、字符串列表或 null。")
                    raws = []
                normalized = tuple(
                    _normalize_binding(str(x), path=path) for x in raws)
                # 保留键只约束「用户覆盖」：上游 built_in_defaults 里
                # pager.close 本身就绑了 ctrl-c，那是内置事实，不是冲突。
                custom = (action in ctx_ov_original) or (action in global_ov_original)
                if custom:
                    for b in normalized:
                        if b in FIXED_BINDINGS:
                            errors.append(
                                f"{path}: `{b}` 为保留键 ({FIXED_BINDINGS[b]})，"
                                f"不可通过配置重绑。")
                merged[ctx][action] = normalized
            for unknown in ctx_ov:
                errors.append(
                    f"tui.keymap.{ctx}.{unknown}: 未知动作（上游为 deny_unknown_fields）。")
        for unknown in global_ov:
            if not any(unknown in acts for acts in merged.values()):
                errors.append(f"tui.keymap.global.{unknown}: 未知动作。")
        for ctx, actions in ov.items():
            if ctx not in merged:
                errors.append(f"tui.keymap.{ctx}: 未知 context。")

        resolved = cls(
            bindings={c: {a: tuple(v) for a, v in acts.items()}
                      for c, acts in merged.items()},
            errors=errors,
        )
        conflicts = resolved.validate_conflicts()
        if strict and (errors or conflicts):
            raise KeymapConflict("; ".join(errors + conflicts))
        resolved.errors = errors + conflicts
        return resolved

    # ------------------------------------------------------------ 校验
    def validate_conflicts(self) -> List[str]:
        """同一 context 内一键多动作 + 保留键占用（对齐上游职责 3）。"""
        problems: List[str] = []
        for ctx, actions in self.bindings.items():
            owner: Dict[str, str] = {}
            for action, binds in actions.items():
                for b in binds:
                    if b in owner and owner[b] != action:
                        problems.append(
                            f"tui.keymap.{ctx}: `{b}` 同时绑定到 "
                            f"{owner[b]} 与 {action}。")
                    else:
                        owner[b] = action
        return problems

    # ------------------------------------------------------------ 查询
    def bindings_for(self, context: str, action: str) -> Tuple[str, ...]:
        return self.bindings.get(context, {}).get(action, ())

    def primary_hint(self, context: str, action: str) -> Optional[str]:
        """UI 提示用主绑定：声明顺序的第一个（对齐上游 ``KeybindingsSpec::specs``）。"""
        binds = self.bindings_for(context, action)
        return binds[0] if binds else None

    def resolve(self, context: str, key_spec: str) -> Optional[str]:
        """把一次按键解析成该 context 下的动作名（非职责 1 由调用方负责）。"""
        try:
            key = normalize_key_spec(key_spec)
        except KeySpecError:
            return None
        if key in FIXED_BINDINGS:
            return FIXED_BINDINGS[key]
        for action, binds in self.bindings.get(context, {}).items():
            if key in binds:
                return action
        return None

    def coverage(self) -> Dict[str, object]:
        total = sum(len(a) for a in CODEX_DEFAULT_BINDINGS.values())
        bound = sum(1 for acts in self.bindings.values()
                    for b in acts.values() if b)
        return {
            "contexts": len(self.bindings),
            "actions": total,
            "actions_with_binding": bound,
            "fixed_bindings": dict(FIXED_BINDINGS),
            "conflicts": len(self.validate_conflicts()),
        }


def codex_approval_hints() -> Dict[str, str]:
    """供审批卡片直接消费的 Codex 主绑定提示。"""
    km = RuntimeKeymap.defaults()
    keys = ("approve", "approve_for_session", "approve_for_prefix",
            "deny", "decline", "cancel", "open_thread")
    return {k: km.primary_hint("approval", k) or "" for k in keys}
