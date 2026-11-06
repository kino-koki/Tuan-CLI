"""Codex TUI 上游规格（事实层）：规模、组件树、布局常量、键位规格解析。

本模块**只记录可从上源码直接核验的事实**，不含任何 Rust 源码，也不含
Tuan 的实现决策（那些在 ``matrix.py`` / ``keymap.py`` / ``i18n.py``）。

核验方式（本会话实际执行）：
  - 下载 ``openai/codex`` main 分支 tarball（19 MB, commit 2c502d8）；
  - 完整解出 ``codex-rs/tui/`` 全部文件；
  - 从 ``lib.rs`` 的 ``mod`` 声明提取 165 个顶层模块；
  - 从 ``keymap.rs::built_in_defaults`` 提取默认键位；
  - 从 ``config/src/tui_keymap.rs`` 提取键位规格规范化规则；
  - 从 ``ui_consts.rs`` / ``bottom_pane/*`` 提取布局常量。

**口径更正**：上一轮文档写的「567 个 .rs / 约 24.7 万行」来自一次不完整的
sparse 解压（只解出 1135 个文件）。完整解压后的真实规模见 ``SCALE``。
所有引用了旧数字的位置都已同步修正 —— 不把低估当事实留着。

许可：Apache-2.0。归属与许可全文见仓库根目录 ``NOTICE`` 第 9 条与
``THIRD_PARTY_LICENSES/``。本文件记录的是功能性事实（模块名、常量值、
键位表），不是逐字复制的表达性内容。
"""
from __future__ import annotations

from typing import Dict, FrozenSet, Tuple

# ---------------------------------------------------------------- 规模事实
SCALE: Dict[str, object] = {
    "upstream": "openai/codex",
    "ref": "main (tarball commit 2c502d8)",
    "crate": "codex-rs/tui (codex-tui)",
    "language": "Rust",
    "render_stack": ("ratatui", "crossterm", "tokio"),
    "top_level_modules": 165,
    "rs_files": 1216,              # tui/src 下 .rs，不含 .snap 快照
    "rs_lines": 492414,            # 上述 .rs 的总行数
    "snapshot_files_skipped": 1491,
    "files_extracted": 1232,
    "license": "Apache-2.0",
}

# ---------------------------------------------------------------- 组件树
# 165 个顶层模块，按功能域分组。分组是 Tuan 侧的组织方式，模块名本身
# 逐字来自上游 lib.rs 的 mod 声明，可用于自动核销。
MODULE_GROUPS: Dict[str, Tuple[str, ...]] = {
    "core_app": (
        "app", "app_backtrack", "app_command", "app_event", "app_event_sender",
        "app_info", "chatwidget", "tui", "cli", "ui_tree", "render", "style",
        "motion", "system_motion", "color", "thread_color", "width", "wrapping",
        "line_truncation", "live_wrap", "resize_reflow_cap",
    ),
    "input_keymap": (
        "keymap", "keymap_setup", "key_hint", "footer_hint", "shortcut_help", "vim_search", "activation_key_guard",
        "copy_input_guard", "custom_terminal", "terminal_program_status",
        "terminal_hyperlinks", "terminal_palette", "terminal_probe",
        "terminal_size_telemetry", "terminal_title",
        "terminal_visualization_instructions", "screen_reader", "tooltips",
    ),
    "bottom_pane": (
        "bottom_pane", "pager_overlay", "status", "status_indicator_widget",
        "notifications", "turn_tip", "goal_display", "goal_files",
        "empty_state_animation", "pets", "daybreak",
    ),
    "approval_permissions": (
        "approval_events", "permission_discovery", "security_setup",
        "resume_permissions", "auto_review_denials",
        "app_server_approval_conversions",
    ),
    "history_transcript": (
        "history_cell", "insert_history", "branch_summary", "thread_transcript",
        "transcript_image", "transcript_mode", "transcript_reflow",
        "transcript_view", "text_selection", "text_formatting", "markdown",
        "markdown_render", "markdown_stream", "markdown_text_merge", "markdown_copy",
        "clipboard_copy", "clipboard_html", "clipboard_paste", "table_detect",
    ),
    "session_startup": (
        "session_resume", "session_start", "session_state", "session_log",
        "session_lock", "session_archive_commands", "session_queue_commands",
        "startup_draft", "startup_error", "startup_hooks_review",
        "startup_orchestration", "startup_preflight", "startup_presentation",
        "startup_recovery", "onboarding", "local_chatgpt_auth",
        "managed_new_thread_defaults", "named_session_lookup", "resume_picker",
        "unarchive_prompt", "projectless", "local_settings", "cwd_prompt",
        "workspace_command", "workspace_messages",
    ),
    "tools_exec": (
        "exec_cell", "exec_command", "get_git_diff", "diff_model", "diff_render",
        "tool_output", "inline_visualization", "rendered_selection",
        "dynamic_tools", "dynamic_tools_mcp", "managed_worktree_tools",
        "managed_worktree_tool_specs", "worktree_browser", "worktree_startup",
        "hooks_rpc", "ide_context", "git_action_directives",
    ),
    "mcp_agents": (
        "multi_agents", "task_mentions", "mention_codec", "skills_helpers",
        "slash_command", "user_prompt", "assistant_directives",
        "temporary_structured_request", "public_widgets",
    ),
    "config_models": (
        "config_panel", "config_update", "collaboration_modes", "debug_config",
        "experimental_features", "model_catalog", "model_migration",
        "service_tier_resolution", "subscription", "token_usage",
        "oss_selection", "npm_registry", "backend_banners", "backend_id",
        "additional_dirs", "version",
    ),
    "updates_analytics": (
        "analytics", "update_action", "update_prompt", "update_versions",
        "updates", "updates_cache", "version", "clock_format",
    ),
    "streaming_async": (
        "streaming", "async_question_reply", "approval_events",
        "app_server_connection", "app_server_session",
    ),
    "external_editor": (
        "external_editor", "external_agent_config_migration", "file_search",
    ),
    "daemon": ("daemon_recovery", "daemon_startup", "daemon_telemetry"),
    "infra": (
        "approval_events", "app_server_connection", "app_server_session",
        "app", "ui_consts", "tests",
    ),
    "misc": (
        "backend_banners", "backend_id", "collaboration_modes", "debug_config",
        "public_widgets", "theme_picker", "sidebar_chooser", "sidebar_tab_strip",
        "windows_sandbox", "worktree_startup",
    ),
}

# 上面分组里为了可读性放了少量占位/重复项；权威清单用这一份：
TOP_LEVEL_MODULES: FrozenSet[str] = frozenset({
    "activation_key_guard", "additional_dirs", "analytics", "app", "app_backtrack",
    "app_command", "app_event", "app_event_sender", "app_info",
    "app_server_approval_conversions", "app_server_connection", "app_server_session",
    "approval_events", "assistant_directives", "async_question_reply",
    "auto_review_denials", "backend_banners", "backend_id", "bottom_pane",
    "branch_summary", "chatwidget", "cli", "clipboard_copy", "clipboard_html",
    "clipboard_paste", "clock_format", "collaboration_modes", "color",
    "config_panel", "config_update", "copy_input_guard", "custom_terminal",
    "daybreak", "experimental_features", "markdown_copy", "permission_discovery",
    "pets", "security_setup", "worktree_browser", "assistant_directives",
    "cwd_prompt", "debug_config", "diff_model", "diff_render", "dynamic_tools",
    "dynamic_tools_mcp", "empty_state_animation", "exec_cell", "exec_command",
    "external_agent_config_migration", "external_editor", "file_search",
    "get_git_diff", "git_action_directives", "goal_display", "goal_files",
    "history_cell", "hooks_rpc", "ide_context", "inline_visualization",
    "insert_history", "managed_worktree_tool_specs", "managed_worktree_tools",
    "terminal_program_status", "footer_hint", "key_hint", "keymap", "keymap_setup",
    "line_truncation", "live_wrap", "local_settings", "rendered_selection",
    "local_chatgpt_auth", "managed_new_thread_defaults", "markdown",
    "markdown_render", "markdown_stream", "markdown_text_merge", "mention_codec",
    "model_catalog", "model_migration", "motion", "multi_agents",
    "named_session_lookup", "notifications", "npm_registry", "onboarding",
    "oss_selection", "pager_overlay", "projectless", "public_widgets", "render",
    "resize_reflow_cap", "resume_permissions", "resume_picker", "screen_reader",
    "service_tier_resolution", "session_archive_commands", "session_lock",
    "session_log", "session_queue_commands", "session_resume", "session_start",
    "session_state", "shortcut_help", "sidebar_chooser", "sidebar_tab_strip",
    "skills_helpers", "slash_command", "startup_draft", "startup_error",
    "startup_hooks_review", "startup_orchestration", "startup_preflight",
    "startup_presentation", "startup_recovery", "status", "status_indicator_widget",
    "streaming", "style", "subscription", "system_motion", "task_mentions",
    "temporary_structured_request", "terminal_hyperlinks", "terminal_palette",
    "terminal_probe", "terminal_size_telemetry", "terminal_title",
    "terminal_visualization_instructions", "text_formatting", "text_selection",
    "theme_picker", "thread_color", "thread_transcript", "token_usage",
    "tool_output", "tooltips", "transcript_image", "transcript_mode",
    "transcript_reflow", "transcript_view", "tui", "turn_tip", "ui_consts",
    "ui_tree", "unarchive_prompt", "update_action", "update_prompt",
    "update_versions", "updates", "updates_cache", "user_prompt", "version",
    "vim_search", "width", "windows_sandbox", "workspace_command",
    "workspace_messages", "wrapping", "table_detect", "daemon_recovery",
    "daemon_startup", "daemon_telemetry", "tests",
    "worktree_startup",
})

# ---------------------------------------------------------------- 布局常量
# 逐值来自上游文件；注释保留上游语义，便于核销。
LAYOUT_CONSTANTS: Dict[str, object] = {
    "LIVE_PREFIX_COLS": 2,          # ui_consts.rs — 左侧 gutter/前缀列数
    "FOOTER_INDENT_COLS": 2,        # ui_consts.rs — 状态行对齐缩进
    "MAX_POPUP_ROWS": 8,            # bottom_pane/popup_consts.rs
    "MIN_LIST_WIDTH_FOR_SIDE": 40,  # bottom_pane/list_selection_view.rs
    "SIDE_CONTENT_GAP": 2,          # bottom_pane/list_selection_view.rs
    "MENU_SURFACE_HORIZONTAL_INSET": 4,  # bottom_pane/list_selection_view.rs
    "KEY_CHORD_TIMEOUT_MS": 1000,   # keymap/chords.rs — 两击和弦超时
    "MAX_KEY_CHORD_STROKES": 2,     # config/src/tui_keymap.rs
}

# ---------------------------------------------------------------- 键位规格规范化
# 对齐 config/src/tui_keymap.rs::normalize_keybinding_spec / _stroke / _name
_MODIFIER_ALIASES: Dict[str, str] = {
    "ctrl": "ctrl", "control": "ctrl",
    "alt": "alt", "option": "alt",
    "shift": "shift",
    "super": "super", "cmd": "super", "command": "super",
}
_MODIFIER_ORDER = ("ctrl", "alt", "shift", "super")
_KEY_ALIASES: Dict[str, str] = {
    "escape": "esc", "return": "enter", "spacebar": "space",
    "pgup": "page-up", "pageup": "page-up",
    "pgdn": "page-down", "pagedown": "page-down",
    "del": "delete",
}
_NAMED_KEYS: FrozenSet[str] = frozenset({
    "enter", "tab", "backspace", "esc", "delete", "up", "down", "left",
    "right", "home", "end", "page-up", "page-down", "space", "minus",
})


class KeySpecError(ValueError):
    """键位规格非法（与上游返回用户可读错误的行为一致）。"""


def normalize_key_stroke(raw: str) -> str:
    """规范化单键；输出顺序恒为 ``ctrl-alt-shift-super-<key>``。"""
    lower = raw.strip().lower()
    if not lower:
        raise KeySpecError(
            "键位不能为空，可用如 `ctrl-a` 或 `shift-enter`。")
    segments = [s for s in lower.split("-") if s]
    if not segments:
        raise KeySpecError(f"非法键位 `{raw}`，可用如 `ctrl-a`。")

    mods: Dict[str, bool] = {m: False for m in _MODIFIER_ORDER}
    key_segments: list[str] = []
    saw_key = False
    for seg in segments:
        canonical = _MODIFIER_ALIASES.get(seg)
        if not saw_key and canonical is not None:
            if mods[canonical]:
                raise KeySpecError(f"键位 `{raw}` 中修饰键重复。")
            mods[canonical] = True
            continue
        saw_key = True
        key_segments.append(seg)
    if not key_segments:
        raise KeySpecError(f"键位 `{raw}` 缺少主键，请补 `a`/`enter`/`page-down`。")
    if any(s in _MODIFIER_ALIASES for s in key_segments):
        raise KeySpecError(f"非法键位 `{raw}`：修饰键必须写在主键之前。")

    key_raw = "-".join(key_segments)
    key = _KEY_ALIASES.get(key_raw, key_raw)
    if len(key) == 1 and key.isascii() and key != "-" and \
            32 <= ord(key) < 127:
        pass  # 单字符可打印主键
    elif key in _NAMED_KEYS:
        pass
    elif key.startswith("f") and key[1:].isdigit() and 1 <= int(key[1:]) <= 12:
        pass
    else:
        raise KeySpecError(f"非法键位 `{raw}`：不支持的主键 `{key}`。")

    parts = [m for m in _MODIFIER_ORDER if mods[m]]
    parts.append(key)
    return "-".join(parts)


def normalize_key_spec(raw: str) -> str:
    """规范化键位规格（含 ``leader`` 前缀与两击和弦）。

    对齐上游 ``normalize_keybinding_spec``：和弦最多 2 击、
    ``leader`` 后必须跟一个键、逐击规范化后用空格连接。
    """
    strokes = raw.split()
    if not strokes:
        return normalize_key_stroke(raw)
    if len(strokes) > LAYOUT_CONSTANTS["MAX_KEY_CHORD_STROKES"]:
        raise KeySpecError(
            f"非法键位 `{raw}`：和弦最多 2 击（如 `ctrl-x ctrl-s`）。")
    if strokes[0].lower() == "leader":
        if len(strokes) != 2:
            raise KeySpecError(
                f"非法键位 `{raw}`：`leader` 后必须跟一个键（如 `leader c`）。")
        return "leader " + normalize_key_stroke(strokes[1])
    return " ".join(normalize_key_stroke(s) for s in strokes)


def spec_identity(raw: str) -> str:
    """用于冲突检测/去重：规范化后的唯一表示。"""
    return normalize_key_spec(raw)


def layout(name: str):
    """取布局常量（供 Tuan 渲染层使用，避免硬编码漂移）。"""
    try:
        return LAYOUT_CONSTANTS[name]
    except KeyError as exc:
        raise KeyError(f"未知 Codex 布局常量: {name}") from exc
