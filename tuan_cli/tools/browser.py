"""浏览器工具插件: 内置 Browser Use (MIT) —— 让模型像人一样驱动真实浏览器。

Browser Use <https://github.com/browser-use> 是一个 MIT 许可的开源浏览器 agent 库:
用 CDP (Chrome DevTools Protocol) 驱动 Chromium, 把页面的 HTML 与截图喂给 LLM,
由 LLM 逐步决定下一步动作 (导航 / 点击 / 输入 / 滚动 / 提取), 直到任务完成。

为什么是它而不是 web_fetch:
- web_fetch 只能拿到静态 HTML, 打不开登录态 / JS 渲染 / 需要点击才出现的页面;
- 浏览器工具能跑 JS、截图、按坐标点击, 覆盖「帮我打开这个后台截图给我看」这类需求。

健壮性要点 (工具层契约: 工具崩溃绝不能炸 Agent 循环):
- 依赖是可选 extra, 未安装时每个 handler 都返回安装指引而不是抛异常;
- Chromium 未安装时给出 `uvx browser-use install` 的明确提示;
- 默认关闭 Browser Use 的匿名遥测 (ANONYMIZED_TELEMETRY=false);
- 所有异常被捕获, 统一返回可读的错误字符串;
- SSRF 防护沿用 web.py 的内网地址段黑名单。
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..core.kernel import Kernel, Plugin
from .base import Tool, ToolContext, string_prop
from .web import _check_ssrf

# ---------------------------------------------------------------- 常量

INSTALL_HINT = (
    "浏览器工具需要可选依赖 browser-use (MIT): "
    "运行 `pip install tuan-cli[browser]` 安装, 再执行 `uvx browser-use install` "
    "下载 Chromium。"
)

MAX_REPORT = 12_000       # 返回给模型的报告上限, 防止撑爆上下文
MAX_SCREENSHOTS = 6       # 只回报最近的几张截图, 避免刷屏
DEFAULT_TIMEOUT = 240     # 单任务超时 (秒)


# ---------------------------------------------------------------- 依赖探测

def browser_use_available() -> bool:
    """browser-use 包是否可导入 (惰性判定, 不触发其重量级初始化)。"""
    try:
        import importlib.util  # noqa: SIM107
        return importlib.util.find_spec("browser_use") is not None
    except Exception:  # noqa: BLE001
        return False


def chromium_available() -> bool:
    """本机是否装好了 Chromium / Chrome (Browser Use 默认走自己的 Chromium 安装)。"""
    for name in ("google-chrome", "google-chrome-stable", "chrome", "chromium", "msedge"):
        if shutil.which(name):
            return True
    # Windows 常见固定路径
    for p in (
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    ):
        if Path(p).exists():
            return True
    return False


def chromium_install_hint() -> str:
    if os.name == "nt":
        return (
            "未发现 Chromium/Chrome。浏览器工具需要一个 Chromium 内核浏览器。"
            "推荐: `uvx browser-use install` (由 Browser Use 自行下载并管理)。"
        )
    return (
        "未发现 Chromium/Chrome。浏览器工具需要一个 Chromium 内核浏览器。"
        "推荐: `uvx browser-use install`; 或 `sudo apt-get install -y chromium`。"
    )


def _preflight() -> Optional[str]:
    """两个前置条件的合并检查。通过返回 None, 否则返回给用户看的错误信息。"""
    if not browser_use_available():
        return INSTALL_HINT
    if not chromium_available():
        return chromium_install_hint()
    return None


# ---------------------------------------------------------------- 同步/异步桥

def _run_async(coro: Any, timeout: float) -> Any:
    """在独立线程里跑一个协程, 让同步工具 handler 也能用 asyncio 库。

    不能直接 asyncio.run(): Tauri/Web 后端所在线程可能已经有事件循环在跑,
    同一线程再 asyncio.run 会抛 RuntimeError。放到新线程就两边都安全。
    """
    result: Dict[str, Any] = {}

    def _worker() -> None:
        try:
            result["value"] = asyncio.run(coro)
        except BaseException as exc:  # noqa: BLE001 - 要把真实原因带回主线程
            result["error"] = exc

    t = threading.Thread(target=_worker, name="browser-task", daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        raise TimeoutError(f"浏览器任务超时 ({timeout:.0f}s)")
    if "error" in result:
        raise result["error"]
    return result.get("value")


# ---------------------------------------------------------------- LLM 选择

def _make_llm(spec: str) -> Any:
    """按配置字符串构造 Browser Use 的 LLM 客户端。

    支持:
      auto            -> 按环境变量顺序挑 (browser-use > openai > anthropic > google)
      browser-use[:model]
      openai[:model]
      anthropic[:model]
      google[:model]
    全部导入失败时抛 RuntimeError, 由调用方转成用户可读提示。
    """
    spec = (spec or "auto").strip().lower()
    family, _, model = spec.partition(":")

    def _bump(name: Any, model_arg: Optional[str]) -> Any:
        kwargs: Dict[str, Any] = {}
        if model_arg:
            kwargs["model"] = model_arg
        try:
            return name(**kwargs)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"初始化 LLM {family!r} 失败: {exc}") from exc

    # 逐个探测: 每个客户端可能各自缺失, 不能一把梭导入。
    try:
        from browser_use.llm.browser_use.chat import ChatBrowserUse
    except Exception:  # noqa: BLE001
        ChatBrowserUse = None
    try:
        from browser_use.llm.openai.chat import ChatOpenAI
    except Exception:  # noqa: BLE001
        ChatOpenAI = None
    try:
        from browser_use.llm.anthropic.chat import ChatAnthropic
    except Exception:  # noqa: BLE001
        ChatAnthropic = None
    try:
        from browser_use.llm.google.chat import ChatGoogle
    except Exception:  # noqa: BLE001
        ChatGoogle = None

    try:
        if family == "browser-use":
            if ChatBrowserUse is None:
                raise RuntimeError("ChatBrowserUse 不可用, 请升级 browser-use")
            return _bump(ChatBrowserUse, model or "browser-use")
        if family == "openai":
            if ChatOpenAI is None or not os.environ.get("OPENAI_API_KEY"):
                raise RuntimeError("需要 OPENAI_API_KEY")
            return _bump(ChatOpenAI, model or "gpt-4.1-mini")
        if family == "anthropic":
            if ChatAnthropic is None or not os.environ.get("ANTHROPIC_API_KEY"):
                raise RuntimeError("需要 ANTHROPIC_API_KEY")
            return _bump(ChatAnthropic, model or "claude-sonnet-4-0")
        if family == "google":
            if ChatGoogle is None or not os.environ.get("GOOGLE_API_KEY"):
                raise RuntimeError("需要 GOOGLE_API_KEY")
            return _bump(ChatGoogle, model or "gemini-2.0-flash")
    except RuntimeError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"未知 LLM 配置 {family!r}: {exc}") from exc

    # auto: 按环境变量顺序挑一个能用的
    tried: List[str] = []
    if ChatBrowserUse is not None and os.environ.get("BROWSER_USE_API_KEY"):
        return ChatBrowserUse()
    tried.append("browser-use(BROWSER_USE_API_KEY)")
    if ChatOpenAI is not None and os.environ.get("OPENAI_API_KEY"):
        return ChatOpenAI(model="gpt-4.1-mini")
    tried.append("openai(OPENAI_API_KEY)")
    if ChatAnthropic is not None and os.environ.get("ANTHROPIC_API_KEY"):
        return ChatAnthropic(model="claude-sonnet-4-0")
    tried.append("anthropic(ANTHROPIC_API_KEY)")
    if ChatGoogle is not None and os.environ.get("GOOGLE_API_KEY"):
        return ChatGoogle(model="gemini-2.0-flash")
    tried.append("google(GOOGLE_API_KEY)")
    raise RuntimeError(
        "未找到可用的浏览器 LLM 凭据。已尝试: " + ", ".join(tried)
        + "。请设置其中一个环境变量, 或在配置里写 tools.browser.llm="
        "openai:模型名 / anthropic:模型名 / google:模型名 / browser-use:模型名。"
    )


# ---------------------------------------------------------------- 会话缓存

# 同一进程内复用浏览器会话, 避免每次工具调用都冷启动 Chromium (~2s)。
_sessions: Dict[str, Any] = {}
_session_lock = threading.Lock()


def _session_key(headless: bool) -> str:
    return "headless" if headless else "headed"


def _get_session(cfg: Dict[str, Any], headless: bool, ctx: Optional[ToolContext]) -> Any:
    with _session_lock:
        key = _session_key(headless)
        if key in _sessions:
            return _sessions[key]

        from browser_use import Browser  # noqa: PLC0415 - 重量级, 延后导入

        kwargs: Dict[str, Any] = {
            "headless": bool(headless),
            "accept_downloads": False,          # 默认不接下载, 避免在用户目录里乱写文件
            "highlight_elements": False,        # 截图给人看时不要带元素编号高亮
            "minimum_wait_page_load_time": float(cfg.get("tools.browser.wait", 0.5)),
            "wait_for_network_idle_page_load_time": float(cfg.get("tools.browser.idle_wait", 1.0)),
        }
        # SSRF 防护: 拦截内网地址
        blocked = cfg.get("tools.browser.blocked_domains") or []
        if blocked:
            kwargs["prohibited_domains"] = list(blocked)
        allowed = cfg.get("tools.browser.allowed_domains")
        if allowed:
            kwargs["allowed_domains"] = list(allowed)

        browser = Browser(**kwargs)
        _sessions[key] = browser
        return browser


def _drop_sessions() -> int:
    with _session_lock:
        n = len(_sessions)
        _sessions.clear()
    return n


# ---------------------------------------------------------------- 报告格式化

def _rel(path: str, workspace: str) -> str:
    """把绝对路径转成相对工作区的路径, 便于前端直接展示。

    输入必须 resolve: Windows 上 "/w/shot.png" 解析成 "\\w\\shot.png" (根目录相对
    当前盘), 与 resolve 后的 workspace 不同根, relative_to 会直接失败。
    """
    try:
        ap = Path(path).resolve()
        wp = Path(workspace or ".").resolve()
        return str(ap.relative_to(wp))
    except Exception:  # noqa: BLE001
        return str(path)


def _format_report(history: Any, ctx: Optional[ToolContext]) -> str:
    """把 AgentHistoryList 压成一段模型可读的文本报告。"""
    ws = getattr(ctx, "workspace", "") if ctx is not None else ""
    lines: List[str] = []

    try:
        final = history.final_result()
    except Exception:  # noqa: BLE001
        final = None
    try:
        done = history.is_done()
        ok = history.is_successful()
    except Exception:  # noqa: BLE001
        done, ok = False, None

    lines.append(
        "状态: " + ("成功完成" if done and (ok is not False) else "未正常完成 (达到步数上限或出错)")
    )
    try:
        lines.append(f"步数: {history.number_of_steps()}")
    except Exception:  # noqa: BLE001
        pass

    try:
        urls = [u for u in (history.urls() or []) if u]
    except Exception:  # noqa: BLE001
        urls = []
    if urls:
        lines.append("访问过的页面:")
        for u in urls[-10:]:
            lines.append(f"  - {u}")

    try:
        errs = [e for e in (history.errors() or []) if e]
    except Exception:  # noqa: BLE001
        errs = []
    if errs:
        lines.append("遇到的错误:")
        for e in errs[-5:]:
            lines.append(f"  - {str(e)[:200]}")

    if final:
        lines.append("")
        lines.append("提取结果:")
        lines.append(str(final)[:8000])

    try:
        shots = [s for s in (history.screenshot_paths() or []) if s]
    except Exception:  # noqa: BLE001
        shots = []
    if shots:
        lines.append("")
        lines.append("截图 (最近几张):")
        for s in shots[-MAX_SCREENSHOTS:]:
            lines.append(f"  - {_rel(s, ws)}")

    return "\n".join(lines)[:MAX_REPORT]


# ---------------------------------------------------------------- 工具实现

def browser_task(
    task: str,
    ctx: ToolContext,
    max_steps: int = 20,
    headless: bool = True,
    use_vision: str = "auto",
    initial_url: Optional[str] = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> str:
    """让 LLM 自主驱动浏览器完成任务 (核心能力)。"""
    err = _preflight()
    if err:
        return err
    if not task or not str(task).strip():
        return "缺少 task 参数: 请描述要浏览器完成的任务。"

    cfg: Dict[str, Any] = {}
    try:
        k = getattr(ctx, "kernel", None)
        if k is not None:
            c = k.get("config")
            if c is not None:
                cfg = dict(c) if hasattr(c, "keys") else {}
    except Exception:  # noqa: BLE001
        cfg = {}

    # SSRF 防护: initial_url 不能指向内网
    if initial_url:
        blocked = _check_ssrf(str(initial_url), allow_loopback=bool(
            cfg.get("tools.browser.allow_loopback", False)
        ))
        if blocked:
            return f"SSRF 防护拦截: {blocked}"

    timeout = float(timeout or cfg.get("tools.browser.timeout", DEFAULT_TIMEOUT))
    max_steps = max(1, min(int(max_steps or 20), 60))
    spec = str(cfg.get("tools.browser.llm", "auto"))
    headed = bool(cfg.get("tools.browser.headless", True) is False) or (not headless)

    try:
        llm = _make_llm(spec)
        browser = _get_session(cfg, not headed, ctx)
    except Exception as exc:  # noqa: BLE001
        return f"初始化浏览器失败: {exc}"

    from browser_use import Agent  # noqa: PLC0415

    kwargs: Dict[str, Any] = dict(
        task=str(task).strip(),
        llm=llm,
        browser=browser,
        max_steps=max_steps,
        use_vision=(use_vision or "auto"),
        calculate_cost=bool(cfg.get("tools.browser.calculate_cost", False)),
    )
    if initial_url:
        # 任务文本里没写 URL 时, 直接用 initial_actions 先打开页面, 省掉一轮 LLM 决策
        kwargs["initial_actions"] = [{"navigate": {"url": str(initial_url)}}]
    agent = Agent(**kwargs)

    try:
        history = _run_async(agent.run(), timeout)
    except TimeoutError:
        return f"浏览器任务超时 ({timeout:.0f}s), 已中止。可用 timeout 参数放宽。"
    except Exception as exc:  # noqa: BLE001
        return f"浏览器任务执行失败: {exc}"

    report = _format_report(history, ctx)
    return report or "(浏览器返回了空报告)"


def browser_status(ctx: ToolContext) -> str:
    """浏览器工具的健康检查 (依赖 / Chromium / 当前会话)。"""
    cfg: Dict[str, Any] = {}
    try:
        k = getattr(ctx, "kernel", None)
        if k is not None:
            c = k.get("config")
            if c is not None:
                cfg = dict(c) if hasattr(c, "keys") else {}
    except Exception:  # noqa: BLE001
        cfg = {}

    bu = browser_use_available()
    cr = chromium_available()
    lines = [
        "浏览器工具状态",
        f"  browser-use 包 : {'可用' if bu else '未安装 -> ' + INSTALL_HINT}",
        f"  Chromium       : {'已找到' if cr else '未找到 -> ' + chromium_install_hint()}",
        f"  配置 LLM       : {cfg.get('tools.browser.llm', 'auto')}",
        f"  headless       : {cfg.get('tools.browser.headless', True)}",
        f"  超时(秒)       : {cfg.get('tools.browser.timeout', DEFAULT_TIMEOUT)}",
        f"  活跃会话       : {', '.join(sorted(_sessions)) or '无'}",
    ]
    if not bu and not cr:
        return "\n".join(lines[:2]) + "\n  -> 先装依赖再试。"
    return "\n".join(lines)


def browser_close(ctx: ToolContext) -> str:
    """关闭所有浏览器会话, 释放 Chromium 进程。"""
    n = _drop_sessions()
    if n == 0:
        return "已关闭 0 个浏览器会话 (本来就没有活跃会话)。"
    return f"已关闭 {n} 个浏览器会话。"


# ---------------------------------------------------------------- 插件

class BrowserPlugin(Plugin):
    """Browser Use 集成: 让模型能打开真实网页、截图、提取内容。"""

    name = "tools.browser"
    requires = ["tool_registry"]

    def activate(self, kernel: Kernel) -> None:
        config = kernel.get("config")
        enabled = config.get("tools.browser.enabled", True) if config else True
        if not enabled:
            return

        # 关闭 Browser Use 的匿名遥测 (PostHog)。桌面工具不应向第三方上报使用数据。
        os.environ.setdefault("ANONYMIZED_TELEMETRY", "false")

        registry = kernel.require("tool_registry")
        registry.register(Tool(
            name="browser_task",
            description=(
                "用真实浏览器 (Chromium, 内置 Browser Use) 自主完成网页任务: "
                "打开页面、点击、填表、滚动、截图、提取内容。"
                "适合需要 JS 渲染、登录态或多次交互的网页; 只想抓静态文本请用 web_fetch。"
                "返回访问过的 URL、提取结果、截图路径。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "task": string_prop("要浏览器完成的任务, 越具体越好, 例如: 打开 example.com 并把首页标题和前三条新闻摘出来"),
                    "initial_url": string_prop("可选, 先直接打开这个 URL (http/https), 省掉一轮决策"),
                    "max_steps": {"type": "integer", "description": "最多执行多少步 (1-60, 默认 20)"},
                    "use_vision": {"type": "string", "description": "截图视觉模式: auto/true/false"},
                    "headless": {"type": "boolean", "description": "无头模式 (默认 true, 不弹出窗口)"},
                    "timeout": {"type": "number", "description": f"超时秒数 (默认 {DEFAULT_TIMEOUT})"},
                },
                "required": ["task"],
            },
            handler=lambda task, ctx, **kw: browser_task(task, ctx, **kw),
            group="browser", read_only=False, dangerous=False,
        ))
        registry.register(Tool(
            name="browser_status",
            description="检查浏览器工具是否就绪: browser-use 依赖、Chromium、当前活跃会话。",
            parameters={"type": "object", "properties": {}},
            handler=browser_status, group="browser", read_only=True,
        ))
        registry.register(Tool(
            name="browser_close",
            description="关闭所有浏览器会话并释放 Chromium 进程。",
            parameters={"type": "object", "properties": {}},
            handler=browser_close, group="browser", read_only=False,
        ))
