"""Tuan Dispatch WebSocket 服务端。

协议见 docs/TUAN-DISPATCH-PROTOCOL.md v1.0。

启动方式:
    python -m tuan_cli.web.dispatch_server --port 8788
    python -m tuan_cli.web.dispatch_server --host 0.0.0.0 --port 8788

设计要点:
- 使用 websockets 库 (纯 Python, 广泛可用)。
- 每个连接一个 handler task, 内部处理 hello / pair / dispatch / approval / cancel / ping。
- 配对码: 6 位纯数字随机码, TTL 60s。
- 任务并发: 单连接最多 1 个活跃任务 (MVP 简化), 后续可扩为多任务。
- 审批: approval_id -> asyncio.Event 表; 客户端 approval 响应时 set()。
- 审计: 所有 dispatch / approval 写入 ~/.tuan/audit/dispatch.jsonl。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import platform
import random
import string
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from tuan_cli.agents.base import AgentEvent, TaskRequest
from tuan_cli.agents.discovery import discover_agents
from tuan_cli.agents.router import route
from tuan_cli.version import __version__

# 桌面版本 (与 pyproject.toml 保持一致)
DESKTOP_VERSION = __version__
DESKTOP_BUILD = datetime.now().strftime("%Y%m%d")

# 配对码: 6 位纯数字
PAIR_CODE_LEN = 6
PAIR_TTL_SEC = 60

# 会话 TTL
SESSION_TTL_SEC = 3600

# 审计日志路径
AUDIT_DIR = Path.home() / ".tuan" / "audit"
AUDIT_FILE = AUDIT_DIR / "dispatch.jsonl"

# 品牌色: Claude 珊瑚色 (Anthropic 设计系统)
BRAND_COLOR = "#D97757"


# ===== 全局配对注册表 =====

# code -> {"created_at": float, "status": str, "agents_info": list, "session": DispatchSession}
_pairing_sessions: Dict[str, dict] = {}


def _gen_pair_code() -> str:
    """生成 6 位纯数字配对码。"""
    return f"{random.randint(0, 999999):06d}"


def _audit(event: dict) -> None:
    """写审计日志 (一行一条 JSON)。失败静默, 不影响主流程。"""
    try:
        AUDIT_DIR.mkdir(parents=True, exist_ok=True)
        with open(AUDIT_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")
    except Exception:
        pass


class DispatchSession:
    """一次 WebSocket 会话的状态。"""

    def __init__(self, ws: Any, pair_code: str, hostname: str) -> None:
        self.ws = ws
        self.pair_code = pair_code
        self.hostname = hostname
        self.session_id: Optional[str] = None
        self.paired_at: Optional[float] = None
        self.agents_info: List[Any] = []
        self.current_task_id: Optional[str] = None
        self.current_task_cancel: Optional[asyncio.Event] = None  # asyncio.Event for cancel
        self.approval_events: Dict[str, asyncio.Event] = {}
        self.approval_decisions: Dict[str, str] = {}
        self.connected_at = time.time()

    def is_paired(self) -> bool:
        return self.session_id is not None and (time.time() - (self.paired_at or 0)) < SESSION_TTL_SEC

    async def send(self, msg: dict) -> None:
        """发送消息 (异常时关闭连接)。"""
        try:
            await self.ws.send(json.dumps(msg, ensure_ascii=False))
        except Exception:
            pass


async def handle_connection(ws: Any) -> None:
    """处理手机 WebSocket 连接 (/tuan/dispatch/v1)。"""
    # 生成配对码
    pair_code = _gen_pair_code()
    session = DispatchSession(ws=ws, pair_code=pair_code, hostname=platform.node() or "unknown")

    # 探测代理
    session.agents_info = await discover_agents()
    agents_dict = [info.to_dict() for info in session.agents_info]

    # 注册配对会话
    _pairing_sessions[pair_code] = {
        "code": pair_code,
        "created_at": time.time(),
        "status": "active",
        "agents_info": agents_dict,
        "session": session,
    }

    # 发 hello 给手机
    await session.send({
        "type": "hello",
        "protocol": 1,
        "hostname": session.hostname,
        "version": DESKTOP_VERSION,
        "build": DESKTOP_BUILD,
        "auth_required": True,
        "pair_code": pair_code,
        "agents": agents_dict,
        "mode": "chat",
    })

    # TTL 倒计时
    async def _countdown() -> None:
        await asyncio.sleep(PAIR_TTL_SEC)
        info = _pairing_sessions.get(pair_code)
        if info and info["status"] == "active":
            info["status"] = "expired"
            _audit({"event": "pairing_expired", "code": pair_code, "time": time.time()})

    countdown_task = asyncio.create_task(_countdown())

    try:
        async for raw in ws:
            try:
                msg = json.loads(raw)
            except Exception:
                await session.send({"type": "error", "code": "BAD_JSON", "message": "invalid json"})
                continue

            msg_type = msg.get("type")

            if msg_type == "pair":
                if msg.get("code") == session.pair_code:
                    session.session_id = "s-" + pair_code + str(int(time.time()))
                    session.paired_at = time.time()
                    await session.send({
                        "type": "pair_ok",
                        "session": session.session_id,
                        "ttl": SESSION_TTL_SEC,
                    })
                    info = _pairing_sessions.get(pair_code)
                    if info:
                        info["status"] = "paired"
                    _audit({"event": "pair_ok", "session": session.session_id, "pair_code": pair_code, "time": time.time()})
                else:
                    await session.send({"type": "error", "code": "INVALID_PAIR_CODE", "message": "配对码错误"})
                    info = _pairing_sessions.get(pair_code)
                    if info:
                        info["status"] = "failed"
                    await ws.close(code=4401)
                    return

            elif msg_type == "ping":
                await session.send({"type": "pong"})

            elif msg_type == "list_agents":
                session.agents_info = await discover_agents()
                await session.send({
                    "type": "hello",
                    "protocol": 1,
                    "agents": [info.to_dict() for info in session.agents_info],
                })

            elif msg_type == "dispatch":
                if not session.is_paired():
                    await session.send({"type": "error", "code": "SESSION_EXPIRED", "message": "请先配对"})
                    continue
                if session.current_task_id:
                    await session.send({"type": "error", "code": "RATE_LIMITED", "message": "已有任务在执行"})
                    continue
                task_msg = msg.get("task", {})
                options = msg.get("options", {})
                task = TaskRequest(
                    id=task_msg.get("id", ""),
                    prompt=task_msg.get("prompt", ""),
                    agent=task_msg.get("agent", "auto"),
                    mode=task_msg.get("mode", "chat"),
                    cwd=task_msg.get("cwd"),
                    attachments=task_msg.get("attachments", []),
                    timeout_sec=options.get("timeout_sec", 600),
                    stream=options.get("stream", True),
                    language=options.get("language", "zh-CN"),
                    auto_approve_low_risk=options.get("auto_approve_low_risk", True),
                )
                session.current_task_id = task.id
                session.current_task_cancel = asyncio.Event()
                _audit({"event": "dispatch", "task_id": task.id, "agent": task.agent, "mode": task.mode, "time": time.time()})
                asyncio.create_task(_run_task(session, task))

            elif msg_type == "approval":
                approval_id = msg.get("approval_id", "")
                decision = msg.get("decision", "deny")
                session.approval_decisions[approval_id] = decision
                if approval_id in session.approval_events:
                    session.approval_events[approval_id].set()
                _audit({"event": "approval", "approval_id": approval_id, "decision": decision, "time": time.time()})

            elif msg_type == "cancel":
                task_id = msg.get("task_id", "")
                if session.current_task_cancel:
                    session.current_task_cancel.set()
                    await session.send({"type": "cancelled", "task_id": task_id})
                _audit({"event": "cancel", "task_id": task_id, "time": time.time()})

            else:
                await session.send({"type": "error", "code": "UNKNOWN_TYPE", "message": f"unknown type: {msg_type}"})

    except asyncio.CancelledError:
        pass
    except Exception as e:
        await session.send({"type": "error", "code": "INTERNAL", "message": str(e)})
    finally:
        countdown_task.cancel()
        info = _pairing_sessions.get(pair_code)
        if info:
            info["status"] = "closed"


async def _run_task(session: DispatchSession, task: TaskRequest) -> None:
    """执行任务: 路由 → 运行适配器 → 流式推事件。"""
    try:
        adapter, error = await route(task)
        if error:
            await session.send({"type": "event", "task_id": task.id, "seq": 1, "kind": "error", "data": {"message": error}})
            await session.send({"type": "event", "task_id": task.id, "seq": 2, "kind": "done", "data": {"status": "error"}})
            session.current_task_id = None
            return
        assert adapter is not None  # error 为空时 route 必返回有效 adapter

        await session.send({
            "type": "accepted",
            "task_id": task.id,
            "routed_to": adapter.id,
            "started_at": int(time.time()),
        })

        async def approve_callback(approval_id: str) -> str:
            evt = asyncio.Event()
            session.approval_events[approval_id] = evt
            await evt.wait()
            return session.approval_decisions.pop(approval_id, "deny")

        try:
            async def _run_with_timeout() -> None:
                seq = 0
                async for event in adapter.run(task, approve_callback=approve_callback):
                    seq += 1
                    event.seq = seq
                    event.task_id = task.id
                    if session.current_task_cancel and session.current_task_cancel.is_set():
                        break
                    await session.send(event.to_dict())

            await asyncio.wait_for(_run_with_timeout(), timeout=task.timeout_sec)
        except asyncio.TimeoutError:
            await session.send({"type": "event", "task_id": task.id, "seq": 9999, "kind": "done", "data": {"status": "timeout"}})
        except asyncio.CancelledError:
            await session.send({"type": "event", "task_id": task.id, "seq": 9999, "kind": "done", "data": {"status": "cancelled"}})
        finally:
            session.current_task_id = None
    except Exception as e:
        await session.send({"type": "event", "task_id": task.id, "seq": 1, "kind": "error", "data": {"message": str(e)}})
        await session.send({"type": "event", "task_id": task.id, "seq": 2, "kind": "done", "data": {"status": "error"}})
        session.current_task_id = None


def build_parser() -> argparse.ArgumentParser:
    """CLI 参数解析。"""
    p = argparse.ArgumentParser(prog="tuan-dispatch", description="Tuan Dispatch WebSocket 服务端")
    p.add_argument("--host", default="127.0.0.1", help="监听地址 (默认 127.0.0.1; 局域网需 0.0.0.0)")
    p.add_argument("--port", type=int, default=8788, help="WebSocket 端口 (默认 8788)")
    p.add_argument("--verbose", "-v", action="store_true", help="详细日志")
    return p


async def main_async(args: Any) -> None:
    """异步主入口。"""
    import websockets

    print(f"[tuan-dispatch] WebSocket : ws://{args.host}:{args.port}/tuan/dispatch/v1")
    print(f"[tuan-dispatch] 审计日志   : {AUDIT_FILE}")

    async with websockets.serve(handle_connection, args.host, args.port):
        if args.verbose:
            print(f"[tuan-dispatch] 运行中, 等待连接...")
        await asyncio.Future()


def main() -> int:
    """同步入口。"""
    args = build_parser().parse_args()
    try:
        asyncio.run(main_async(args))
    except KeyboardInterrupt:
        print("\n[tuan-dispatch] 已停止")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
