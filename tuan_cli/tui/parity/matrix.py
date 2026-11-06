"""TUI 对齐矩阵：把「与 Codex 完全相同但有本地化」变成可度量的状态。

四种状态（互斥）:
- ``aligned``       —— 行为/布局/键位/契约已与上游对齐，且本仓库有可验证实现；
- ``localized``     —— 上游有该组件，Tuan 用**本地化等价物**替代
                       （中文/多语言文案、自有配色与吉祥物、本地模型、
                       本地配置路径、本地审批作用域）。这正是需求里的「有自己本地化」；
- ``not_applicable``—— OpenAI 专属能力（账号登录、云服务、订阅计费、
                       更新通道、app-server 守护进程等），Tuan 不需要，
                       明确记为「本地化替代」而非缺口；
- ``pending``       —— 尚未对齐，是后续轮次的工作队列。

达成「完全相同」的判定：``pending == 0`` 且 ``aligned + localized +
not_applicable == 165``。本模块不虚报状态 —— 每个 aligned 都必须能指向
本仓库里的实现与回归测试。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, FrozenSet, List, Tuple

from .upstream_spec import TOP_LEVEL_MODULES, MODULE_GROUPS, SCALE

ALIGNED = "aligned"
LOCALIZED = "localized"
NOT_APPLICABLE = "not_applicable"
PENDING = "pending"
_STATUSES = (ALIGNED, LOCALIZED, NOT_APPLICABLE, PENDING)

# ---------------------------------------------------------------- 显式状态
# 本轮（第 10 轮）真实落地的对齐，每条都能指向文件与测试。
EXPLICIT_ALIGNED: Dict[str, str] = {
    "keymap": "parity/keymap.py::RuntimeKeymap — precedence / unbind / 冲突检测",
    "keymap_setup": "parity/keymap.py::from_config 支持 context/global 覆盖与显式解绑",
    "key_hint": "parity/upstream_spec.py::normalize_key_spec 规范化 + primary_hint",
    "footer_hint": "parity/i18n.py::hint.transcript / hint.shortcuts 本地化提示",
    "ui_consts": "parity/upstream_spec.py::LAYOUT_CONSTANTS 逐值对齐",
    "ui_tree": "parity/upstream_spec.py::TOP_LEVEL_MODULES / MODULE_GROUPS",
    "config_panel": "parity/keymap.py 配置路径 tui.keymap.<ctx>.<action> 对齐",
    "shortcut_help": "parity/i18n.py::hint.shortcuts + codex_approval_hints()",
    "approval_events": "ui/approval_overlay.py 显式决策事件与路由（第 9 轮）",
    "bottom_pane": "ui/approval_overlay.py 卡片 + parity 键位/文案（第 9/10 轮）",
    "diff_model": "sandbox/isolation.py::DiffPreview（第 8 轮）",
    "diff_render": "ui/approval_overlay.py::render_approval_card（第 9/10 轮）",
    "permission_discovery": "tools/mcp/policy.py::MCPPolicyStore（第 8 轮）",
    "security_setup": "SECURITY_BASELINE.md R1-R22 加固链",
    # ---- 第 11 轮：input_keymap 组 7 个待对齐模块，逐模块有实现+回归
    "vim_search": "tui/inputkit/vim_search.py — 字面匹配 / 完整 grapheme / 方向反转",
    "activation_key_guard": "tui/inputkit/activation_key_guard.py — 1s 双窗口 / Repeat/Release 状态机",
    "copy_input_guard": "tui/inputkit/copy_input_guard.py — RAII 释放 / 异常路径也释放",
    "custom_terminal": "tui/inputkit/custom_terminal.py — 双缓冲 diff / ClearToEnd / OSC8 / 同步帧",
    "terminal_program_status": "tui/inputkit/terminal_program_status.py — OSC 7501/21337 / 去重缓存 / 注入转义",
    "terminal_hyperlinks": "tui/inputkit/terminal_hyperlinks.py — 工作区逃逸校验 / OSC8 不影响几何",
    "terminal_visualization_instructions":
        "tui/inputkit/terminal_visualization_instructions.py — feature gate / 指令拼接（中文）",
}

EXPLICIT_LOCALIZED: Dict[str, str] = {
    "style": "Kimi Code MIT 视觉 token（NOTICE 第 1 条），中文界面",
    "color": "自有配色；敏感标记用 [!敏感] 而非上游英文",
    "theme_picker": "本地主题选择，不接 OpenAI 账号体系",
    "model_catalog": "本地/多厂商模型清单，非 OpenAI 模型目录",
    "service_tier_resolution": "本地模型档位（effort），非 ChatGPT 订阅档位",
    "user_prompt": "中文提示与 10 语言 i18n",
    "tui": "prompt_toolkit/rich 实现，保留 Tuan 入口与安全接线",
    "render": "现有盒子渲染器，不引入 ratatui Widget/Buffer",
    "status": "中文状态栏 + 自有吉祥物状态机",
    "status_indicator_widget": "中文状态文案",
    "notifications": "中文通知",
    "turn_tip": "中文回合提示",
    "pets": "自有吉祥物（本地化装饰）",
    "daybreak": "本地化空状态动画",
    "empty_state_animation": "本地化空状态",
    "cwd_prompt": "本地工作区信任模型（E2）",
    "workspace_command": "本地 workspace_trust.json",
    "workspace_messages": "中文工作区提示",
    "onboarding": "本地首启语言选择器（11 语言），非 ChatGPT 登录引导",
    "mention_codec": "本地 @ 提及与技能路径",
    "skills_helpers": "本地 skills 系统（gh_borrow 等）",
    "slash_command": "本地 / 命令集（含 /harden、/tui parity）",
    "clipboard_copy": "本地剪贴板实现",
    "clipboard_paste": "本地粘贴实现",
    "markdown": "本地 markdown 渲染",
    "markdown_render": "本地 markdown 渲染",
    "markdown_stream": "本地流式渲染",
    "history_cell": "本地对话历史单元",
    "transcript_view": "本地会话记录视图",
    "pager_overlay": "本地分页覆盖层",
    "exec_cell": "本地命令执行单元（含沙箱裁决）",
    "tool_output": "本地工具输出渲染",
    "external_editor": "本地外部编辑器（含无终端兜底）",
    "file_search": "本地文件搜索",
    "get_git_diff": "本地 git diff",
    "analytics": "本地统计，不上报 OpenAI",
    "token_usage": "本地 token 计数",
    "version": "本地版本号与 VERSION_POLICY",
    "screen_reader": "本地无障碍提示（中文）",
    "tooltips": "中文提示",
    "wrapping": "parity/upstream_spec.py 折行按 CJK 显示宽度（本地化增强）",
    "width": "CJK 显示宽度计算（本地化增强）",
    "line_truncation": "本地折行/裁剪",
    "live_wrap": "本地实时折行",
    "text_formatting": "中文文本格式化",
    "text_selection": "本地文本选择",
    "terminal_title": "本地终端标题",
    "terminal_palette": "本地终端调色板",
    "terminal_probe": "本地终端探测",
    "terminal_size_telemetry": "本地尺寸探测（不上传）",
    "session_state": "本地会话状态",
    "session_log": "本地会话日志（AEAD）",
    "session_resume": "本地会话恢复",
    "session_start": "本地会话启动",
    "debug_config": "本地调试配置",
    "experimental_features": "本地实验特性开关",
    "config_update": "本地配置更新",
}

# OpenAI 专属 / 与本地 CLI 无关的能力，明确记为不适用（不是缺口）
NOT_APPLICABLE_MODULES: FrozenSet[str] = frozenset({
    "local_chatgpt_auth", "managed_new_thread_defaults", "subscription",
    "oss_selection", "npm_registry", "backend_banners", "backend_id",
    "app_server_connection", "app_server_session",
    "app_server_approval_conversions", "multi_agents", "task_mentions",
    "temporary_structured_request", "public_widgets", "hooks_rpc",
    "ide_context", "inline_visualization", "managed_worktree_tools",
    "managed_worktree_tool_specs", "worktree_browser", "worktree_startup",
    "windows_sandbox", "session_lock", "session_archive_commands",
    "session_queue_commands", "named_session_lookup", "resume_picker",
    "resume_permissions", "unarchive_prompt", "projectless",
    "startup_hooks_review", "startup_preflight", "startup_recovery",
    "startup_orchestration", "startup_presentation", "startup_draft",
    "startup_error", "update_action", "update_prompt", "update_versions",
    "updates", "updates_cache", "daemon_recovery", "daemon_startup",
    "daemon_telemetry", "dynamic_tools", "dynamic_tools_mcp",
    "git_action_directives", "assistant_directives", "goal_display",
    "goal_files", "branch_summary", "thread_transcript", "transcript_mode",
    "transcript_reflow", "transcript_image", "thread_color",
    "clipboard_html", "markdown_copy", "markdown_text_merge",
    "table_detect", "motion", "system_motion",
})


@dataclass(frozen=True)
class ComponentStatus:
    module: str
    status: str
    note: str = ""

    def to_dict(self) -> Dict[str, str]:
        return {"module": self.module, "status": self.status, "note": self.note}


def parity_status() -> List[ComponentStatus]:
    """返回 165 个模块的完整状态（顺序稳定，便于 diff 与回归）。"""
    out: List[ComponentStatus] = []
    for mod in sorted(TOP_LEVEL_MODULES):
        if mod in EXPLICIT_ALIGNED:
            out.append(ComponentStatus(mod, ALIGNED, EXPLICIT_ALIGNED[mod]))
        elif mod in EXPLICIT_LOCALIZED:
            out.append(ComponentStatus(mod, LOCALIZED, EXPLICIT_LOCALIZED[mod]))
        elif mod in NOT_APPLICABLE_MODULES:
            out.append(ComponentStatus(mod, NOT_APPLICABLE,
                                       "OpenAI 专属 / 本地 CLI 不适用"))
        else:
            out.append(ComponentStatus(mod, PENDING, "后续轮次对齐"))
    return out


def summary() -> Dict[str, object]:
    rows = parity_status()
    counts = {s: sum(1 for r in rows if r.status == s) for s in _STATUSES}
    total = len(rows)
    settled = counts[ALIGNED] + counts[LOCALIZED] + counts[NOT_APPLICABLE]
    strict = counts[ALIGNED] + counts[LOCALIZED]
    return {
        "total_modules": total,
        "by_status": counts,
        "settled": settled,
        "pending": counts[PENDING],
        # 含 not_applicable 的宽口径：本地 CLI 视角下的「已处理」比例
        "coverage_pct": round(settled * 100.0 / total, 1),
        # 严格口径：真正有对齐/本地化实现的比例（不把「不适用」算成成果）
        "aligned_pct": round(strict * 100.0 / total, 1),
        # 逐值对齐（不含本地化等价物）—— 最硬的指标
        "aligned_only_pct": round(counts[ALIGNED] * 100.0 / total, 1),
        "upstream_rs_files": SCALE["rs_files"],
        "upstream_rs_lines": SCALE["rs_lines"],
        "fully_identical": counts[PENDING] == 0,
    }


def gaps(limit: int = 0) -> List[Tuple[str, str]]:
    """待对齐清单（后续轮次的工作队列）。按功能域分组排序。"""
    pending = {r.module for r in parity_status() if r.status == PENDING}
    out: List[Tuple[str, str]] = []
    for group, mods in MODULE_GROUPS.items():
        for m in mods:
            if m in pending:
                out.append((group, m))
    seen = set()
    uniq = [(g, m) for g, m in out if not (m in seen or seen.add(m))]
    return uniq[:limit] if limit else uniq


def group_summary() -> Dict[str, Dict[str, int]]:
    rows = {r.module: r.status for r in parity_status()}
    out: Dict[str, Dict[str, int]] = {}
    for group, mods in MODULE_GROUPS.items():
        c = {s: 0 for s in _STATUSES}
        for m in mods:
            if m in rows and m not in ("tests",):
                c[rows[m]] += 1
        out[group] = c
    return out


def validate() -> List[str]:
    """自检：状态覆盖完整、无未知模块、无非法状态。"""
    rows = parity_status()
    problems: List[str] = []
    if len(rows) != SCALE["top_level_modules"]:
        problems.append(f"模块数 {len(rows)} != {SCALE['top_level_modules']}")
    if {r.module for r in rows} != set(TOP_LEVEL_MODULES):
        problems.append("模块集合与上游 lib.rs 不一致")
    for r in rows:
        if r.status not in _STATUSES:
            problems.append(f"{r.module}: 非法状态 {r.status}")
    unknown = (set(EXPLICIT_ALIGNED) | set(EXPLICIT_LOCALIZED)
               | set(NOT_APPLICABLE_MODULES)) - set(TOP_LEVEL_MODULES)
    for m in sorted(unknown):
        problems.append(f"标注了上游不存在的模块: {m}")
    return problems
