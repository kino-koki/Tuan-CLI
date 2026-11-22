"""external_dispatch agent 工具 —— 把 tuan_cli/agents 调度层暴露给 Agent 会话。

`tuan dispatch` CLI (tuan_cli/cli/cmd_dispatch.py) 背后的 Agent-of-Agents 子系统
(tuan_cli/agents/: 9 家本地代理适配器 + router 路由器 + discovery 探测器) 此前
只有 CLI / WebSocket 入口; 本工具把它接入 Agent 工具面, 让模型在会话内直接
探测本机代理、预览路由决策、或把任务真实派给某个外部 CLI 编码代理。

三个操作 (op):
- list    (默认) 只读: 逐行列出本机发现的外部代理与可用性;
- route   路由决策: dry_run=True (默认) 只解析「会派给谁 + 命令预览」, 不执行;
          dry_run=False 真实派活 —— 经 adapter.run() 启动外部代理子进程
          (与 cmd_dispatch._run_task 同一执行路径, 超时取 tools.dispatch.timeout_sec);
- status  调度子系统摘要: 探测数量 / 默认路由代理 / 配置路径 / 超时。

安全口径: dry_run=False 会真实启动外部代理进程 (外部副作用), 必须显式传入;
默认 dry-run 只读预览。插件名用 tools.external_dispatch —— tools.dispatch 已被
dispatch_tasks 子代理工具 (tuan_cli/tools/dispatch.py DispatchPlugin) 占用,
同内核重复注册会抛 PluginError, 故错开命名。
"""

from __future__ import annotations

import asyncio
import logging
import shlex
import threading
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

from ..core.kernel import Kernel, Plugin
from ..tools.base import Tool, ToolContext, string_prop

log = logging.getLogger(__name__)

_VALID_OPS = ("list", "route", "status")
_VALID_MODES = ("chat", "collaboration", "gantong", "lingma", "boundless")
_DEFAULT_TIMEOUT = 600  # 与 `tuan dispatch` CLI 的 --timeout 默认一致

_EMPTY_HINT = (
    "本机未发现任何受支持的外部代理 (可用 0 家)。"
    "请先安装任一受支持代理: claude / codex / dsh / kimi-code / hermes / "
    "gemini / aider / qwen-code / doubao。"
    "查看探测详情可运行 `tuan dispatch status`; 代理列表面板见 `tuan agents`; "
    "调度协议文档: docs/TUAN-DISPATCH-PROTOCOL.md。"
)


# ================================================================ 辅助

def _cfg_of(ctx: ToolContext) -> Optional[Any]:
    """从工具上下文取内核配置服务 (缺失时返回 None, 不抛异常)。"""
    kernel = getattr(ctx, "kernel", None)
    if kernel is None:
        return None
    try:
        return kernel.get("config")
    except Exception as exc:  # noqa: BLE001 - 配置服务不可用时按无配置降级
        log.debug("dispatch_tool._cfg_of(): 非致命异常已忽略(设计内降级, 不改控制流): %s", exc)
        return None


def _run_async(coro: Any, timeout: float) -> Any:
    """在独立线程里跑一个协程, 让同步工具 handler 也能用 asyncio 库。

    不能直接 asyncio.run(): Agent 事件循环所在线程可能已经有事件循环在跑,
    同一线程再 asyncio.run 会抛 RuntimeError。放到新线程就两边都安全
    (与 tuan_cli/tools/browser.py 的同步/异步桥同一手法)。
    """
    result: Dict[str, Any] = {}

    def _worker() -> None:
        try:
            result["value"] = asyncio.run(coro)
        except BaseException as exc:  # noqa: BLE001 - 要把真实原因带回主线程
            result["error"] = exc

    t = threading.Thread(target=_worker, name="external-dispatch", daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        raise TimeoutError(f"外部派活操作超时 ({timeout:.0f}s)")
    if "error" in result:
        raise result["error"]
    return result.get("value")


def _as_bool(v: Any, default: bool = False) -> bool:
    """宽容解析布尔参数 (模型可能传 true/"true"/1 等形态)。"""
    if v is None:
        return default
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in ("1", "true", "yes", "on", "y")


def _dispatch_timeout(cfg: Any, override: Any = None) -> int:
    """执行超时 (秒): 显式参数 > config tools.dispatch.timeout_sec > 600。"""
    if override is not None and str(override).strip() not in ("", "0"):
        try:
            return max(1, int(override))
        except (TypeError, ValueError):
            pass
    try:
        v = cfg.get("tools.dispatch.timeout_sec", _DEFAULT_TIMEOUT) if cfg is not None else _DEFAULT_TIMEOUT
        return max(1, int(v))
    except Exception as exc:  # noqa: BLE001 - 配置损坏时回退默认
        log.debug("dispatch_tool._dispatch_timeout(): 非致命异常已忽略(设计内降级, 不改控制流): %s", exc)
        return _DEFAULT_TIMEOUT


def _new_task(ctx: ToolContext, prompt: str, agent: str, mode: str,
              cwd: Optional[str], timeout_sec: int) -> Any:
    """构造 TaskRequest (与 cmd_dispatch._new_task 同一数据模型)。"""
    from ..agents.base import TaskRequest

    return TaskRequest(
        id=uuid.uuid4().hex[:8],
        prompt=prompt,
        agent=agent or "auto",
        mode=mode or "chat",
        cwd=cwd or (getattr(ctx, "workspace", None) or None),
        timeout_sec=int(timeout_sec),
    )


def _badge(info: Any) -> str:
    """健康状态徽标 (与 cmd_dispatch._status_badge 同口径, 纯文本)。"""
    if not info.healthy:
        return "✗ 未安装"
    if info.score >= 100:
        return "✓ 已验证"
    if info.score >= 70:
        return "✓ 就绪"
    return "! 疑似同名"


def _discover() -> List[Any]:
    """并行探测本机全部代理 (复用 tuan dispatch 的 discovery 入口)。"""

    async def _go() -> List[Any]:
        from ..agents.discovery import discover_agents

        return await discover_agents()

    infos: List[Any] = _run_async(_go(), timeout=120)
    return infos


# ================================================================ op: list

def _op_list(ctx: ToolContext, **_: Any) -> str:
    """只读: 逐行列出本机发现的外部代理与可用性。"""
    infos = _discover()
    from ..agents.adapters import ADAPTERS

    online = sum(1 for i in infos if i.healthy)
    lines: List[str] = [f"【外部代理清单】共 {len(infos)} 家, 可用 {online} 家"]
    for info in infos:
        inst = ADAPTERS.get(info.id)
        cmds = "/".join(inst.command) if inst else "-"
        line = f"  {_badge(info)}  {info.name} ({info.id})  命令 {cmds}"
        if info.version:
            line += f"  版本 {info.version}"
        if info.healthy and info.reason:
            line += f"  [{info.reason}]"
        lines.append(line)
    if online == 0:
        lines.append(f"[dispatch] {_EMPTY_HINT}")
    else:
        lines.append("提示: op=route 可把任务派给其中一家 (默认 dry-run 预览, 不执行)。")
    return "\n".join(lines)


# ================================================================ op: route

async def _execute_task(task: Any, adapter: Any) -> Tuple[int, str, str]:
    """真实执行任务: 消费 adapter.run() 事件流并收集文本输出。

    与 `tuan dispatch run` (cmd_dispatch._run_task) 的执行路径一致:
    adapter.run() 流式产出 AgentEvent (底层为外部 CLI 子进程), 超时按
    task.timeout_sec 逐事件控制。返回 (exit_code, 汇总文本, 结束状态)。
    测试经 monkeypatch 本函数注入假 runner, 不 spawn 任何外部进程。
    """
    from ..agents.base import EventType

    async def _approve(approval_id: str) -> str:
        # 工具/CLI 场景无交互审批通道: 与 tuan dispatch run 相同, 按低风险自动放行
        return "allow" if task.auto_approve_low_risk else "deny"

    texts: List[str] = []
    deadline = time.monotonic() + task.timeout_sec
    agen = adapter.run(task, approve_callback=_approve)
    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise asyncio.TimeoutError
            # wait_for 只能包协程: 逐事件取, 天然支持流式超时
            ev = await asyncio.wait_for(agen.__anext__(), timeout=remaining)
            if ev.kind == EventType.TEXT:
                texts.append(str(ev.data.get("text", "")))
            elif ev.kind == EventType.ERROR:
                texts.append(f"[error] {ev.data.get('message', '')}")
            elif ev.kind == EventType.DONE:
                status = str(ev.data.get("status", "?"))
                code = int(ev.data.get("exit_code", 0 if status == "ok" else 1))
                return code, "\n".join(texts), status
    except asyncio.TimeoutError:
        return 124, "\n".join(texts), "timeout"
    except StopAsyncIteration:
        # 适配器未按契约产出 DONE: 按失败收尾, 不假装成功
        return 1, "\n".join(texts), "error"
    finally:
        # 确定性关闭生成器 (子进程 reap + 临时文件清理)
        try:
            aclose = getattr(agen, "aclose", None)
            if aclose is not None:
                await aclose()
        except Exception as exc:  # noqa: BLE001
            log.debug("dispatch_tool._execute_task(): 非致命异常已忽略(设计内降级, 不改控制流): %s", exc)


def _op_route(ctx: ToolContext, task: Any = "", agent: Any = None,
              dry_run: Any = None, mode: Any = "chat", cwd: Any = None,
              timeout: Any = None, **_: Any) -> str:
    """路由决策: dry_run=True 只预览 (默认); dry_run=False 真实派活。"""
    prompt = str(task or "").strip()
    if not prompt:
        return "[dispatch] route 需要非空任务描述 (task 参数)"
    mode = str(mode or "chat")
    if mode not in _VALID_MODES:
        return f"[dispatch] 未知 mode: {mode!r} (可用: {'/'.join(_VALID_MODES)})"
    agent_id = str(agent or "auto").strip() or "auto"

    from ..agents import discovery  # noqa: F401 - 确保适配器已注册 (幂等)
    from ..agents.adapters import ADAPTERS

    if agent_id != "auto" and agent_id not in ADAPTERS:
        return (f"[dispatch] 未知代理: {agent_id!r} "
                f"(可用: {', '.join(sorted(ADAPTERS))}; 省略 agent 参数则自动路由)")

    cfg = _cfg_of(ctx)
    timeout_sec = _dispatch_timeout(cfg, timeout)
    t = _new_task(ctx, prompt, agent_id, mode, cwd, timeout_sec)

    async def _decide() -> Dict[str, Any]:
        from ..agents.router import route_explain

        return await route_explain(t)

    ex = _run_async(_decide(), timeout=120)
    if not ex.get("agent"):
        err = str(ex.get("error") or "无可用代理")
        if "NO_AGENT_AVAILABLE" in err:
            return "[dispatch] 路由失败: " + _EMPTY_HINT
        return f"[dispatch] 路由失败: {err}"

    chosen = ADAPTERS[ex["agent"]]

    async def _preview() -> list:
        return await chosen.build_command(t)

    cmd = _run_async(_preview(), timeout=30)
    cmd_str = shlex.join([str(c) for c in cmd])

    if _as_bool(dry_run, True):
        cand = sorted((r for r in ex.get("candidates", []) if r.get("healthy")),
                      key=lambda r: (-r.get("weight", 1), -r.get("score", 0)))
        cand_txt = ", ".join(
            f"{r['id']}(权重{r.get('weight', 1)}/健康{r.get('score', 0)})"
            for r in cand[:3]) or "无"
        return "\n".join([
            "【外部派活·预览】(dry-run, 未执行)",
            f"任务: {prompt}",
            f"选中: {chosen.display_name} ({chosen.id}) · mode={mode}",
            f"命令: {cmd_str}",
            f"超时: {timeout_sec}s · 工作目录: {t.cwd or '(进程默认)'}",
            f"候选: {cand_txt}",
            "提示: 确认执行请传 dry_run=false (将真实启动外部代理进程)。",
        ])

    # 真实派活: 复用路由决策选出的适配器 (与 router.route 同一选择逻辑),
    # 执行走 _execute_task —— 即 cmd_dispatch._run_task 的 adapter.run 事件流。
    t0 = time.time()

    async def _run() -> Tuple[int, str, str]:
        return await _execute_task(t, chosen)

    code, out, status = _run_async(_run(), timeout=timeout_sec + 60)
    elapsed = time.time() - t0
    head = [
        "【外部派活·完成】",
        f"代理: {chosen.display_name} ({chosen.id}) · mode={mode}",
        f"状态: {status} (exit={code}) · 耗时 {elapsed:.1f}s · 超时 {timeout_sec}s",
    ]
    if status != "ok":
        head.append("注意: 外部代理未正常结束, 输出仅供参考。")
    body = out.strip() or "(无输出)"
    if len(body) > 2000:
        body = body[:2000] + "…(输出已截断)"
    return "\n".join(head) + "\n输出:\n" + body


# ================================================================ op: status

def _op_status(ctx: ToolContext, **_: Any) -> str:
    """调度子系统摘要: 探测数量 / 默认路由代理 / 配置路径 / 超时。"""
    infos = _discover()
    online = sum(1 for i in infos if i.healthy)
    verified = sum(1 for i in infos if i.healthy and i.score >= 100)
    cfg = _cfg_of(ctx)

    lines: List[str] = [
        "【外部派活状态】",
        f"探测代理: {len(infos)} 家 (可用 {online}, 版本校验通过 {verified})",
    ]

    async def _advise() -> Dict[str, Any]:
        from ..agents.base import TaskRequest
        from ..agents.router import route_explain

        return await route_explain(TaskRequest(id="advise", prompt="", mode="chat"))

    try:
        # 默认路由建议 (与 tuan dispatch status 的 auto 提示同口径)
        ex = _run_async(_advise(), timeout=120)
        lines.append(f"默认路由 (mode=chat): {ex.get('agent') or '无可用代理'}")
    except Exception as exc:  # noqa: BLE001 - 建议失败不影响状态主输出
        log.debug("dispatch_tool._op_status(): 非致命异常已忽略(设计内降级, 不改控制流): %s", exc)
        lines.append("默认路由 (mode=chat): 探测失败")

    if cfg is not None:
        lines.append(f"配置目录: {getattr(cfg, 'home', '-')}")
        lines.append(f"配置文件: {getattr(cfg, 'user_config_path', '-')}")
    lines.append(f"执行超时: {_dispatch_timeout(cfg)}s (tools.dispatch.timeout_sec)")
    lines.append("CLI 入口: `tuan dispatch status|route|run`; 本工具: op=list|route|status")
    if online == 0:
        lines.append(f"[dispatch] {_EMPTY_HINT}")
    return "\n".join(lines)


# ================================================================ 分发入口

def _dispatch_handler(ctx: ToolContext, op: str = "list", **kw: Any) -> str:
    """external_dispatch 工具入口: 按 op 分发; 任何异常降级为 '[dispatch] ...' 文本。"""
    try:
        op_key = str(op or "list").strip().lower()
        if op_key == "list":
            return _op_list(ctx, **kw)
        if op_key == "route":
            return _op_route(ctx, **kw)
        if op_key == "status":
            return _op_status(ctx, **kw)
        return f"[dispatch] 未知 op: {op!r} (可用: {'/'.join(_VALID_OPS)})"
    except Exception as exc:  # noqa: BLE001 - 工具层兜底, 不向 Agent 循环抛原始异常
        log.warning("external_dispatch op=%s 执行失败: %s", op, exc)
        return f"[dispatch] {op} 执行失败: {type(exc).__name__}: {exc}"


# ================================================================ 插件注册

class DispatchToolPlugin(Plugin):
    """把 tuan_cli/agents 调度层注册为名为 ``external_dispatch`` 的 Agent 工具。"""

    # 注意: 插件名不能用 tools.dispatch —— 该名已被 dispatch_tasks 的
    # DispatchPlugin (tuan_cli/tools/dispatch.py) 占用, 重复注册会 PluginError。
    name = "tools.external_dispatch"
    provides: List[str] = []
    requires = ["tool_registry"]

    def activate(self, kernel: Kernel) -> None:
        config = kernel.get("config")
        if config is not None and not config.get("tools.dispatch.enabled", True):
            return

        registry = kernel.require("tool_registry")
        registry.register(Tool(
            name="external_dispatch",
            description=(
                "外部代理调度 (Agent-of-Agents): 探测本机安装的 CLI 编码代理"
                " (claude-code/codex/dsh/kimi-code/hermes/gemini/aider/qwen-code/doubao),"
                " 预览任务路由, 或把任务真实派给某个外部代理执行。"
                " op=list 列出代理与可用性 (默认); op=route 派活"
                " (dry_run=true 默认只预览选中代理与命令, dry_run=false 才真实执行"
                " —— 会启动外部代理子进程); op=status 查看调度子系统状态。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "op": {
                        "type": "string",
                        "enum": list(_VALID_OPS),
                        "description": "操作: list=代理清单(默认); route=路由/派活; status=子系统状态",
                    },
                    "task": string_prop("route 用: 要派给外部代理的任务描述 (必填)"),
                    "agent": string_prop(
                        "route 用: 目标代理 id (如 claude-code / codex / dsh / hermes);"
                        " 省略则由路由器按模式权重自动选择"),
                    "dry_run": {
                        "type": "boolean",
                        "description": "route 用: 仅预览不执行 (默认 true);"
                                       " false 会真实启动外部代理子进程",
                    },
                    "mode": {
                        "type": "string",
                        "enum": list(_VALID_MODES),
                        "description": "route 用: 路由模式 (chat/collaboration/gantong/lingma/boundless), 默认 chat",
                    },
                    "cwd": string_prop("route 用: 外部代理工作目录 (默认当前会话工作区)"),
                    "timeout": {
                        "type": "integer",
                        "description": "route 用: 超时秒数 (默认 tools.dispatch.timeout_sec=600)",
                    },
                },
                "required": [],
            },
            handler=_dispatch_handler,
            group="tools",
        ))
