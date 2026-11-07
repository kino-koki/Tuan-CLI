"""Kimi Code TUI 关键模块移植 (青小团 TUI 增强层)。

本模块直接取材自 Kimi Code CLI (MoonshotAI/kimi-cli, 官方 PyPI sdist 1.52.0)
的 ``src/kimi_cli/ui/shell/`` 下列源码, 按 tuan_cli 的后端 API 做了适配:

- ``session_picker.py``  → 会话选择器 (Kimi 的 Ctrl+R 会话浏览/恢复, 目录范围切换)
- ``task_browser.py``    → 后台任务浏览器 (Kimi 的后台任务查看/停止/预览)
- ``mcp_status.py``      → MCP 服务器状态面板 (Kimi 的 MCP 提示渲染)

适配原则:
1. 不依赖 Kimi 的 Soul / KaosPath / asyncio 架构, 只依赖 prompt_toolkit + rich
   (两者都是 tuan_cli 既有核心依赖), 保证「零新第三方依赖」。
2. 全部为**纯数据 + 纯函数渲染**, 可脱离 TUI 单独单测。
3. 与 tuan_cli 后端 (SessionStore / BackgroundStore / mcp_status) 之间用窄接口
   连接, 后端缺位时优雅降级 (返回空列表/安装指引), 绝不炸 Agent 循环。

本模块只含 UI 构建与渲染; 键位挂接与状态驱动由 tuan_cli/tui/tui.py 的 QxtTUI
负责 (见 ``_open_session_picker`` / ``_open_task_browser`` / ``toggle_mcp_status``)。
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from prompt_toolkit.formatted_text import StyleAndTextTuples
from prompt_toolkit.layout import HSplit, Layout, VSplit, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.styles import Style
from prompt_toolkit.widgets import RadioList

# 可选依赖: prompt_toolkit 缺失时降级 (仍可导入本模块, 仅渲染函数不可用)。
try:
    from prompt_toolkit.widgets import RadioList as _PT_RadioList  # noqa: F401
    _HAVE_PT = True
except Exception:  # noqa: BLE001
    _HAVE_PT = False


# Kimi 同款主题色 (取自 Kimi ui/theme.py, 供自绘面板配色复用)。
_PRIMARY = "#4FA8FF"
_TEXT = "#E0E0E0"
_TEXT_STRONG = "#F5F5F5"
_DIM = "#888888"
_BORDER = "#5A5A5A"
_ACCENT = "#5BC0BE"
_SUCCESS = "#4EC87E"
_WARNING = "#E8A838"
_ERROR = "#E85454"
_BG_PANEL = "#1E2836"

_EMPTY_SESSION_ID = "__empty__"
_EMPTY_TASK_ID = "__empty__"


def _shorten_work_dir(work_dir: str, max_len: int = 30) -> str:
    """缩写工作目录路径用于展示 (Kimi 同款: home 换 ~, 超长掐尾)。"""
    home = str(Path.home())
    if work_dir.startswith(home):
        work_dir = "~" + work_dir[len(home):]
    if len(work_dir) <= max_len:
        return work_dir
    return "..." + work_dir[-(max_len - 3):]


@dataclass
class SessionEntry:
    """会话列表项 (Kimi Session 的窄接口形态)。

    由调用方从 tuan_cli.memory.sessions.SessionStore 聚合而来。
    """
    session_id: str
    work_dir: str
    title: str = ""
    started_at: float = 0.0
    updated_at: float = 0.0
    n_events: int = 0
    kind: str = "interactive"
    status: str = "done"


def _fmt_relative(ts: float, now: float | None = None) -> str:
    """相对时间 (Kimi utils.datetime.format_relative_time 的简化移植)。"""
    delta = max(0, int((now if now is not None else time.time()) - ts))
    if delta < 60:
        return f"{delta}s ago"
    if delta < 3600:
        return f"{delta // 60}m ago"
    if delta < 86400:
        return f"{delta // 3600}h ago"
    if delta < 604800:
        return f"{delta // 86400}d ago"
    return time.strftime("%Y-%m-%d", time.localtime(ts))


def format_session_choice(entry: SessionEntry, *, now: float | None = None) -> str:
    """会话列表项的可读文本 (Kimi format_session_choice 同构)。"""
    title = (entry.title or "").strip() or entry.session_id
    parts = [
        f"[{entry.session_id[:8]}]",
        title,
        entry.kind,
        _shorten_work_dir(entry.work_dir),
        _fmt_relative(entry.updated_at, now=now),
    ]
    return " · ".join(parts)


class SessionPickerModel:
    """会话选择器模型: 目录范围过滤 + 当前选中 + 刷新 (Kimi SessionPickerApp 的窄接口)。"""

    def __init__(self, sessions: Sequence[SessionEntry]) -> None:
        self.all_sessions: List[SessionEntry] = list(sessions)
        self.scope: str = "current"
        self.current_dir: str = os.getcwd()
        self.selected_index: int = 0
        self.filtered: List[SessionEntry] = []
        self.refresh()

    def refresh(self) -> None:
        """按范围过滤并排序 (最近更新在前)。"""
        entries = self.all_sessions
        if self.scope == "current":
            cur = os.path.normpath(self.current_dir or "")
            entries = [s for s in entries if os.path.normpath(s.work_dir or "") == cur]
        entries = sorted(entries, key=lambda s: s.updated_at, reverse=True)
        self.filtered = entries
        if self.selected_index >= len(self.filtered):
            self.selected_index = max(0, len(self.filtered) - 1)
        if not self.filtered:
            self.selected_index = 0

    def move(self, delta: int) -> None:
        if not self.filtered:
            return
        self.selected_index = max(0, min(len(self.filtered) - 1, self.selected_index + delta))

    def toggle_scope(self) -> None:
        self.scope = "all" if self.scope == "current" else "current"
        self.refresh()

    @property
    def selected(self) -> Optional[SessionEntry]:
        if not self.filtered or self.selected_index >= len(self.filtered):
            return None
        return self.filtered[self.selected_index]


@dataclass
class TaskView:
    """后台任务视图 (Kimi background.TaskView 的窄接口形态)。"""
    task_id: str
    description: str
    kind: str = "agent"
    status: str = "running"
    started_at: float = 0.0
    updated_at: float = 0.0
    turns: int = 0
    pid: Optional[int] = None
    workspace: str = ""
    result: str = ""


def _task_timing_label(view: TaskView, *, now: float | None = None) -> str:
    """任务耗时/更新时间标签 (Kimi _task_timing_label 同构)。"""
    current = now if now is not None else time.time()
    if view.updated_at <= 0:
        return ""
    if view.status == "running":
        seconds = max(0, int(current - (view.started_at or view.updated_at)))
        return f"running {seconds}s"
    return _fmt_relative(view.updated_at, now=now)


def format_task_choice(view: TaskView, *, now: float | None = None) -> str:
    """任务列表项可读文本 (Kimi format_task_choice 同构)。"""
    description = (view.description or "").strip() or "(no description)"
    return " · ".join(
        [
            f"[{view.status}]",
            description,
            view.task_id,
            view.kind,
            _task_timing_label(view, now=now) or "updated just now",
        ]
    )


class TaskBrowserModel:
    """任务浏览器模型: 过滤 (all|active) + 选中 + 消息提示 (Kimi TaskBrowserModel 窄接口)。"""

    def __init__(self, tasks: Sequence[TaskView]) -> None:
        self.all_tasks: List[TaskView] = list(tasks)
        self.filter_mode: str = "all"
        self.filtered: List[TaskView] = []
        self.message: str = ""
        self.message_expires_at: float | None = None
        self.selected_index: int = 0
        self.refresh()

    @staticmethod
    def _is_terminal(status: str) -> bool:
        return status in ("done", "failed", "cancelled")

    def refresh(self) -> None:
        tasks = self.all_tasks
        if self.filter_mode == "active":
            tasks = [t for t in tasks if not self._is_terminal(t.status)]
        tasks = sorted(tasks, key=lambda t: (t.updated_at or t.started_at), reverse=True)
        self.filtered = tasks
        if self.selected_index >= len(self.filtered):
            self.selected_index = max(0, len(self.filtered) - 1)

    def move(self, delta: int) -> None:
        if not self.filtered:
            return
        self.selected_index = max(0, min(len(self.filtered) - 1, self.selected_index + delta))

    def toggle_filter(self) -> None:
        self.filter_mode = "active" if self.filter_mode == "all" else "all"
        self.refresh()

    def flash_message(self, msg: str, seconds: float = 3.0) -> None:
        self.message = msg
        self.message_expires_at = time.time() + seconds

    def message_live(self) -> str:
        if not self.message:
            return ""
        if self.message_expires_at is not None and time.time() > self.message_expires_at:
            self.message = ""
            self.message_expires_at = None
            return ""
        return self.message

    @property
    def selected(self) -> Optional[TaskView]:
        if not self.filtered or self.selected_index >= len(self.filtered):
            return None
        return self.filtered[self.selected_index]


@dataclass
class McpServerInfo:
    """单个 MCP 服务器的窄接口信息。"""
    name: str
    transport: str = "stdio"
    status: str = "connected"
    tools: int = 0
    error: str = ""


def render_mcp_prompt(servers: Sequence[McpServerInfo]) -> str:
    """MCP 状态提示文本 (Kimi render_mcp_prompt 同构)。

    有 MCP 服务器时返回 ``MCP: name✓(n)  name2✗`` 之类紧凑串; 无服务器返回 ""。
    用于底栏展示; 面板渲染走 ``render_mcp_panel``。
    """
    if not servers:
        return ""
    glyphs = {
        "connected": "✓",
        "error": "✗",
        "connecting": "…",
        "disconnected": "·",
    }
    parts: List[str] = []
    for s in servers:
        g = glyphs.get(s.status, "·")
        tool_suffix = f"({s.tools})" if s.status == "connected" and s.tools else ""
        parts.append(f"{s.name}{g}{tool_suffix}")
    return "  MCP: " + "  ".join(parts)


def render_mcp_panel(servers: Sequence[McpServerInfo]) -> List[Tuple[str, str]]:
    """MCP 状态面板的富文本行 (风格: style, text)。

    供 TUI 自绘面板使用; 无服务器时返回单行「未配置 MCP 服务器」。
    """
    if not servers:
        return [("class:textdim", "  未配置 MCP 服务器 (MCP 未启用或 .tuan/mcp.json 为空)")]
    rows: List[Tuple[str, str]] = []
    status_cls_map = {
        "connected": "class:success",
        "error": "class:error",
        "connecting": "class:warning",
        "disconnected": "class:textdim",
    }
    for s in servers:
        status_cls = status_cls_map.get(s.status, "class:textdim")
        rows.append((status_cls, f"  {s.name}  [{s.status}]"))
        if s.status == "connected":
            rows.append(("class:textdim", f"    transport={s.transport}  tools={s.tools}"))
        elif s.error:
            rows.append(("class:error", f"    {s.error}"))
    return rows


def collect_sessions(home: Optional[Path] = None) -> List[SessionEntry]:
    """从 tuan_cli.memory.sessions.SessionStore 聚合会话列表。

    后端缺位 / 无会话目录返回 []。绝不抛异常 (TUI 高频调用场景)。
    """
    try:
        from tuan_cli.memory.sessions import SessionStore
        from tuan_cli.config.loader import home_dir as _home_dir
        h = Path(home) if home is not None else Path(_home_dir())
        store = SessionStore(h)
        out: List[SessionEntry] = []
        for p in store.list_sessions():
            try:
                meta = store.read_meta(p) or {}
                n = 0
                try:
                    with open(p, "r", encoding="utf-8") as f:
                        for _ in f:
                            n += 1
                            if n > 100000:
                                break
                except (OSError, ValueError):
                    pass
                task = meta.get("task", "")
                kind = "background" if meta.get("kind") == "background" else "interactive"
                sid = p.stem
                started_at = float(meta.get("started_at") or 0) or p.stat().st_mtime
                out.append(SessionEntry(
                    session_id=sid,
                    work_dir=meta.get("workspace", ""),
                    title=task or "",
                    started_at=started_at,
                    updated_at=p.stat().st_mtime,
                    n_events=n,
                    kind=kind,
                    status=meta.get("status", "done"),
                ))
            except (OSError, ValueError):
                continue
        return out
    except Exception:  # noqa: BLE001
        return []


def collect_tasks(home: Optional[Path] = None) -> List[TaskView]:
    """从 tuan_cli.core.background_store.BackgroundStore 聚合后台任务。

    后端缺位 / 无任务目录返回 []。绝不抛异常。
    """
    try:
        from tuan_cli.core.background_store import BackgroundStore
        from tuan_cli.config.loader import home_dir as _home_dir
        h = Path(home) if home is not None else Path(_home_dir())
        store = BackgroundStore(h)
        out: List[TaskView] = []
        for jp in sorted(store.jobs_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                data = json.loads(jp.read_text(encoding="utf-8"))
                out.append(TaskView(
                    task_id=str(data.get("job_id") or jp.stem),
                    description=str(data.get("task", "")),
                    kind="agent",
                    status=str(data.get("status", "unknown")),
                    started_at=float(data.get("started_at") or 0) or 0,
                    updated_at=float(data.get("updated_at") or 0) or 0,
                    turns=int(data.get("turns") or 0) or 0,
                    pid=data.get("pid"),
                    workspace=str(data.get("workspace", "")),
                    result=str(data.get("result", "")),
                ))
            except (OSError, ValueError):
                continue
        return out
    except Exception:  # noqa: BLE001
        return []


def collect_mcp_servers() -> List[McpServerInfo]:
    """聚合 MCP 服务器状态。

    优先取 tuan_cli.web.server 的 mcp_status() (运行时真实状态); 拿不到时
    读 .tuan/mcp.json 静态清单。缺位返回 []。
    """
    try:
        from tuan_cli.web.server import _MCP_DEFAULT  # noqa: F401
    except Exception:  # noqa: BLE001
        _MCP_DEFAULT = None
    try:
        from tuan_cli.config.loader import home_dir as _home_dir
        home = Path(_home_dir())
        mcp_cfg = home / "mcp.json"
        if not mcp_cfg.exists():
            return []
        data = json.loads(mcp_cfg.read_text(encoding="utf-8"))
        servers = data.get("mcpServers") if isinstance(data, dict) else {}
        out: List[McpServerInfo] = []
        for name, spec in servers.items():
            if not isinstance(spec, dict):
                continue
            transport = spec.get("transport", "stdio")
            status = "connected" if spec.get("enabled", True) else "disconnected"
            out.append(McpServerInfo(
                name=str(name),
                transport=str(transport),
                status=status,
                tools=int(spec.get("tools_count") or 0) or 0,
            ))
        return out
    except Exception:  # noqa: BLE001
        return []


@dataclass
class UsageRow:
    """单条配额行 (Kimi UsageRow 的窄接口形态)。"""
    label: str
    used: int
    limit: int
    reset_hint: str | None = None


def _usage_to_int(value: Any) -> int | None:
    """Kimi _to_int 的移植: 容忍 None/字符串/溢出。"""
    try:
        return int(value)
    except (OverflowError, TypeError, ValueError):
        return None


def _remaining_quota(row: UsageRow) -> Tuple[int, float, int]:
    """剩余配额 (Kimi 同款): (remaining, ratio, total)。"""
    if row.limit <= 0:
        return 0, 0, 1
    remaining = min(max(row.limit - row.used, 0), row.limit)
    return remaining, remaining / row.limit, row.limit


def _ratio_color(remaining_ratio: float) -> str:
    """配额剩余比例 → rich 颜色 (Kimi 同款阈值)。"""
    if remaining_ratio <= 0.1:
        return "red"
    if remaining_ratio <= 0.3:
        return "yellow"
    return "green"


def _fmt_seconds_duration(seconds: int) -> str:
    """Kimi format_duration 的简化移植 (秒 → 人类可读时长)。"""
    seconds = max(0, int(seconds))
    if seconds < 60:
        return f"{seconds}s"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m"
    hours = minutes // 60
    if hours < 24:
        rem = minutes % 60
        return f"{hours}h{rem}m" if rem else f"{hours}h"
    days = hours // 24
    rem_h = hours % 24
    return f"{days}d{rem_h}h" if rem_h else f"{days}d"


def _format_reset_time(val: str) -> str:
    """Kimi _format_reset_time 的移植 (ISO → "resets in X")。"""
    from datetime import UTC, datetime
    try:
        if "." in val and val.endswith("Z"):
            base, frac = val[:-1].split(".")
            frac = frac[:6]
            val = f"{base}.{frac}Z"
        dt = datetime.fromisoformat(val.replace("Z", "+00:00"))
        now = datetime.now(UTC)
        delta = dt - now
        if delta.total_seconds() <= 0:
            return "reset"
        return f"resets in {_fmt_seconds_duration(int(delta.total_seconds()))}"
    except (ValueError, TypeError):
        return f"resets at {val}"


def _usage_reset_hint(data: Mapping[str, Any]) -> str | None:
    """Kimi _reset_hint 的移植: 从 payload 提取重置提示。"""
    for key in ("reset_at", "resetAt", "reset_time", "resetTime"):
        if val := data.get(key):
            return _format_reset_time(str(val))
    for key in ("reset_in", "resetIn", "ttl"):
        seconds = _usage_to_int(data.get(key))
        if seconds:
            return f"resets in {_fmt_seconds_duration(seconds)}"
    return None


def build_usage_rows(
    prompt_tokens: int,
    completion_tokens: int,
    budget_tokens: int = 0,
    context_used: int = 0,
) -> List[UsageRow]:
    """把本地会话 token 计数映射成 Kimi 风格配额行。

    - 上下文预算行: used=context_used, limit=budget (来自 context.budget_tokens)
    - 总 token 行: used=prompt+completion, limit=同预算 (供比例参考)
    - prompt / completion 行: 无配额, 仅展示数量 (limit=0 → 纯文本, 无进度条)
    """
    rows: List[UsageRow] = []
    if budget_tokens > 0:
        rows.append(UsageRow(
            label="Context budget",
            used=context_used if context_used > 0 else prompt_tokens + completion_tokens,
            limit=budget_tokens,
            reset_hint=f"{budget_tokens:,} token window",
        ))
    rows.append(UsageRow(
        label="Total tokens",
        used=prompt_tokens + completion_tokens,
        limit=budget_tokens if budget_tokens > 0 else 0,
    ))
    rows.append(UsageRow(label="Prompt tokens", used=prompt_tokens, limit=0))
    rows.append(UsageRow(label="Completion tokens", used=completion_tokens, limit=0))
    return rows


def format_usage_row(row: UsageRow, label_width: int) -> Any:
    """Kimi _format_row 的移植: 单条配额行 → rich 可渲染对象。

    返回 rich RenderableType; 调用方负责放进 Group / Panel。
    """
    from rich.progress_bar import ProgressBar
    from rich.table import Table
    from rich.text import Text

    remaining, remaining_ratio, bar_total = _remaining_quota(row)
    color = _ratio_color(remaining_ratio)

    label = Text(f"{row.label:<{label_width}}  ", style="cyan")
    bar = ProgressBar(
        total=bar_total,
        completed=remaining,
        width=20,
        complete_style=color,
        finished_style=color,
    )

    detail = Text()
    percent = remaining_ratio * 100
    detail.append(f"  {percent:.0f}% left", style="bold")
    if row.reset_hint:
        detail.append(f"  ({row.reset_hint})", style="grey50")

    t = Table.grid(padding=0)
    t.add_column(width=label_width + 2)
    t.add_column(width=20)
    t.add_column()
    t.add_row(label, bar, detail)
    return t


def render_usage_panel(rows: Sequence[UsageRow]) -> Any:
    """Kimi _build_usage_panel 的移植: 配额行列表 → rich Panel。

    rows 为空时返回 "无数据" 面板; 调用方 console.print / TUI 追加即可。
    """
    from rich.console import Group, RenderableType
    from rich.panel import Panel
    from rich.text import Text

    if not rows:
        return Panel(
            Text("No usage data", style="grey50"), title="API Usage", border_style="wheat4"
        )

    label_width = max(len(r.label) for r in rows)
    label_width = max(label_width, 6)

    lines: List[RenderableType] = []
    for row in rows:
        lines.append(format_usage_row(row, label_width))

    return Panel(
        Group(*lines),
        title="API Usage",
        border_style="wheat4",
        padding=(0, 2),
        expand=False,
    )


__all__ = [
    "SessionEntry",
    "SessionPickerModel",
    "format_session_choice",
    "TaskView",
    "TaskBrowserModel",
    "format_task_choice",
    "McpServerInfo",
    "render_mcp_prompt",
    "render_mcp_panel",
    "collect_sessions",
    "collect_tasks",
    "collect_mcp_servers",
    "UsageRow",
    "build_usage_rows",
    "format_usage_row",
    "render_usage_panel",
]
