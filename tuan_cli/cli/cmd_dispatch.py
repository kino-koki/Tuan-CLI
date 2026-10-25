"""`tuan dispatch` —— Agent-of-Agents 调度层独立命令。

调度层本体在 `tuan_cli/agents/` (5 家本地代理适配器 + 路由器 + 探测器),
此前只能通过 `python -m tuan_cli.web.dispatch_server` 的 WebSocket 使用;
本命令把它变成普通 CLI 入口, 不启动服务器也能判定与派活。

    tuan dispatch status [代理id]   探测本机 5 家本地代理 (默认子命令)
    tuan dispatch route <提示词>    dry-run: 打分明细, 不执行
    tuan dispatch run <提示词>      实际派活: 路由 → 流式执行 → 汇总
    tuan dispatch serve [--host H] [--port P]
                                   启动 WebSocket 调度服务器 (供手机/浏览器遥控)

全局: `--format json` 机器可读输出 (供 Tuan-Chat 与脚本消费);
`--mode` 五模式 (chat/collaboration/gantong/lingma/boundless)。

注意: `tuan agents` 已被多会话管理面板占用, 故调度层命令命名 dispatch,
与 README「Agent-of-Agents 调度层」及 docs/TUAN-DISPATCH-PROTOCOL.md 对齐。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
import uuid
from typing import List, Optional

from ._ui_singleton import console, ui
from ..agents.base import AgentInfo, EventType, TaskRequest
from ..ui.format import Table

_MODES = ("chat", "collaboration", "gantong", "lingma", "boundless")


def _new_task(prompt: str, args) -> TaskRequest:
    return TaskRequest(
        id=uuid.uuid4().hex[:8],
        prompt=prompt,
        agent=getattr(args, "agent", None) or "auto",
        mode=getattr(args, "mode", None) or "chat",
        cwd=getattr(args, "cwd", None),
        timeout_sec=int(getattr(args, "timeout", None) or 600),
    )


def _status_badge(info: AgentInfo) -> str:
    """健康状态徽标 (纯文本, 与项目 Table 一致): 已验证 / 就绪 / 疑似同名 / 未安装。"""
    if not info.healthy:
        return "✗ 未安装"
    if info.score >= 100:
        return "✓ 已验证"
    if info.score >= 70:
        return "✓ 就绪"
    return "! 疑似同名"


def _warn(text: str) -> None:
    console.print(f"  ! {text}", style="yellow")


def _muted(text: str) -> None:
    console.print(f"  {text}", style="dim")


def _dump(obj) -> None:
    """机器可读输出: 直写 stdout, 不经 console (避免任何装饰/高亮混入)。"""
    import sys

    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


# ---------------------------------------------------------------- status

async def _collect(args) -> List[AgentInfo]:
    from ..agents.discovery import discover_agents, probe_agent

    only = getattr(args, "agent_id", None)
    if only:
        return [await probe_agent(only)]
    return await discover_agents()


def _status_table(infos: List[AgentInfo]) -> Table:
    table = Table(title=f"Agent-of-Agents · 本机代理探测 ({len(infos)} 家)")
    table.add_column("代理")
    table.add_column("命令")
    table.add_column("状态")
    table.add_column("健康分", justify="right")
    table.add_column("版本")
    table.add_column("说明")
    for info in infos:
        from ..agents.adapters import ADAPTERS

        inst = ADAPTERS.get(info.id)
        cmds = "/".join(inst.command) if inst else "-"
        note = info.reason or (inst.description if inst else "")
        table.add_row(
            info.name,
            cmds,
            _status_badge(info),
            str(info.score),
            info.version or "—",
            note,
        )
    return table


def _cmd_status(args) -> int:
    from ..agents.discovery import summarize

    infos = asyncio.run(_collect(args))
    if getattr(args, "format", "text") == "json":
        _dump({"agents": [i.to_dict() for i in infos], "summary": summarize(infos)})
        return 0

    console.print(_status_table(infos))
    s = summarize(infos)
    console.print("")
    ui.info(f"在线 {s['online']}/{s['total']} (版本校验通过 {s['verified']} 家)")

    # auto 路由建议: 告诉用户当前模式下任务会派给谁
    from ..agents.router import route_explain

    mode = getattr(args, "mode", None) or "chat"
    ex = asyncio.run(route_explain(TaskRequest(id="advise", prompt="", mode=mode)))
    if ex["agent"]:
        ui.info(f"auto 路由 (mode={mode}) → {ex['agent']}")
    else:
        _warn(f"auto 路由不可用: {ex['error']}")
    if s["online"] == 0:
        _muted("提示: 安装任一受支持代理后即可派活 (claude / codex / dsh / kimi-code / hermes)")
    return 0 if s["online"] else 1


# ---------------------------------------------------------------- route (dry-run)

def _cmd_route(args) -> int:
    from ..agents.router import route_explain

    task = _new_task(args.prompt, args)
    ex = asyncio.run(route_explain(task))
    if getattr(args, "format", "text") == "json":
        _dump(ex)
        return 0 if ex["agent"] else 1

    table = Table(title=f"路由打分明细 (mode={task.mode})")
    table.add_column("代理")
    table.add_column("模式权重", justify="right")
    table.add_column("健康分", justify="right")
    table.add_column("可用")
    table.add_column("备注")
    for r in ex["candidates"]:
        mark = "← 选中" if r["selected"] else ""
        table.add_row(
            f"{r['name']} {mark}".strip(),
            str(r["weight"]),
            str(r["score"]),
            "✓" if r["healthy"] else "✗",
            r.get("reason") or "",
        )
    console.print(table)
    console.print("")
    if ex["agent"]:
        ui.success(f"将派给: {ex['agent']} (dry-run, 未执行)")
        return 0
    ui.error(f"无可用代理: {ex['error']}")
    return 1


# ---------------------------------------------------------------- run (实际派活)

async def _run_task(task: TaskRequest, verbose: bool) -> int:
    from ..agents.router import route

    adapter, err = await route(task)
    if adapter is None:
        ui.error(f"路由失败: {err}")
        return 1

    ui.info(f"派给 {adapter.display_name} ({adapter.id}) · mode={task.mode}")

    async def _approve(approval_id: str) -> str:
        # CLI 非交互: 打印审批请求并按 auto_approve_low_risk 决定。
        # 需要人工把关时用 WebSocket 调度服务器 (手机端弹审批卡)。
        decision = "allow" if task.auto_approve_low_risk else "deny"
        _warn(f"审批请求 [{approval_id}] → {decision} (CLI 模式)")
        return decision

    t0 = time.time()
    n_text = 0
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
                n_text += 1
                console.print(ev.data.get("text", ""))
            elif ev.kind == EventType.STDERR:
                _muted(f"[stderr] {ev.data.get('text', '')}")
            elif ev.kind == EventType.ERROR:
                ui.error(ev.data.get("message", "unknown error"))
            elif ev.kind == EventType.DONE:
                status = ev.data.get("status", "?")
                if status == "ok":
                    ui.success(f"完成 · {n_text} 段输出 · {time.time() - t0:.1f}s")
                    return 0
                ui.error(f"结束状态: {status} (exit={ev.data.get('exit_code', '?')})")
                return 1
    except asyncio.TimeoutError:
        ui.error(f"超时 ({task.timeout_sec}s), 任务已中止")
        return 1
    except StopAsyncIteration:
        # 适配器未按契约产出 DONE: 按异常收尾, 不假装成功
        ui.error("事件流意外结束 (缺少 done 事件)")
        return 1
    finally:
        # 确定性关闭生成器 (子进程 reap + 临时文件清理), 不留给 loop 关停钩子
        try:
            await agen.aclose()
        except Exception:
            pass
    return 1


def _cmd_run(args) -> int:
    task = _new_task(args.prompt, args)
    return asyncio.run(_run_task(task, verbose=not getattr(args, "format", "text") == "json"))


# ---------------------------------------------------------------- serve

def _cmd_serve(args) -> int:
    from ..web.dispatch_server import build_parser, main_async

    ws_args = build_parser().parse_args([
        "--host", getattr(args, "host", None) or "127.0.0.1",
        "--port", str(getattr(args, "port", None) or 8788),
    ])
    try:
        asyncio.run(main_async(ws_args))
    except KeyboardInterrupt:
        _muted("调度服务器已停止")
    return 0


# ---------------------------------------------------------------- 分发器

def cmd_dispatch(args: argparse.Namespace) -> int:
    """tuan dispatch 分发器。"""
    action = getattr(args, "dispatch_cmd", None) or "status"
    if action in ("status", "list", "ls"):
        return _cmd_status(args)
    if action == "route":
        return _cmd_route(args)
    if action == "run":
        return _cmd_run(args)
    if action == "serve":
        return _cmd_serve(args)
    console.print(f"未知子命令: {action} (可用: status/route/run/serve)")
    return 1
