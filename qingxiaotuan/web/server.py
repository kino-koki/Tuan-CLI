# -*- coding: utf-8 -*-
"""青小团 Web 界面 (DeepSeek-harness 风格本地工作台)。

标准库实现 (http.server + SSE), 零新增依赖 —— 与"离线优先 / 可审计"叙事一致:
- 每个会话一个 Agent 实例 (复用 create_agent, 独立消息历史)
- 流式输出走 SSE (on_token / on_tool / on_tool_result / on_reason / on_error)
- 线程锁串行化执行 (个人本地工具, 一个进程同时跑一轮)
- 无外链 CDN, 前端全部内联 (断网可用)
- 会话磁盘持久化 (<workspace>/.qxt/web_sessions.json, 重启不丢)
"""
from __future__ import annotations

import json
import queue
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urlparse, parse_qs

from .frontend import FRONTEND_HTML

_SESSIONS: Dict[str, Dict[str, Any]] = {}
_SESSIONS_LOCK = threading.RLock()  # 嵌套获取 (save_sessions 在会话锁内落盘)


def _sse(kind: str, data: Any) -> str:
    return f"event: {kind}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _serializable(s: Dict[str, Any]) -> Dict[str, Any]:
    """去掉运行期字段 (agent/lock), 供持久化与列表展示。"""
    return {
        "id": s["id"],
        "title": s["title"],
        "created": s["created"],
        "messages": s["messages"],
    }


class _WebHTTPServer(ThreadingHTTPServer):
    """绑定 WebServer owner, 供 handler 经 self.server.owner 访问配置。"""

    def __init__(self, addr: Any, owner: "WebServer") -> None:
        super().__init__(addr, _WebHandler)
        self.owner = owner


class _WebHandler(BaseHTTPRequestHandler):

    # ---------------- helpers ----------------
    def _json(self, code: int, payload: Any) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    @property
    def _owner(self) -> "WebServer":
        return self.server.owner  # type: ignore[no-any-return, attr-defined]

    def _text(self, code: int, text: str, ctype: str = "text/plain; charset=utf-8") -> None:
        body = text.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> Dict[str, Any]:
        length = int(self.headers.get("Content-Length", 0) or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:  # noqa: BLE001
            return {}

    def log_message(self, fmt: str, *args: Any) -> None:  # 静默访问日志
        pass

    # ---------------- routes ----------------
    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/" or path == "/index.html":
            self._text(200, FRONTEND_HTML, "text/html; charset=utf-8")
            return
        if path == "/api/sessions":
            with _SESSIONS_LOCK:
                items = [{"id": s["id"], "title": s["title"], "created": s["created"]}
                         for s in _SESSIONS.values()]
            items.sort(key=lambda x: x["created"], reverse=True)
            self._json(200, {"ok": True, "sessions": items})
            return
        if path == "/api/history":
            qs = parse_qs(parsed.query)
            sid = (qs.get("session") or [""])[0]
            with _SESSIONS_LOCK:
                s = _SESSIONS.get(sid)
            if s is None:
                self._json(404, {"ok": False, "error": "session not found"})
                return
            self._json(200, {"ok": True, "messages": s["messages"]})
            return
        if path == "/api/info":
            self._json(200, {"ok": True,
                             "model": self._owner.model_label,
                             "workspace": self._owner.workspace,
                             "engine": self._owner.engine_label,
                             "security": self._owner.security_info()})
            return
        self._json(404, {"ok": False, "error": "not found"})

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/api/chat":
            self._chat()
            return
        if path == "/api/stop":
            self._owner.cancel_current()
            self._json(200, {"ok": True})
            return
        if path == "/api/sessions/clear":
            body = self._read_body()
            sid = body.get("session") or ""
            with _SESSIONS_LOCK:
                s = _SESSIONS.get(sid)
                if s is None:
                    self._json(404, {"ok": False, "error": "session not found"})
                    return
                s["messages"] = []
                self._owner.save_sessions()
            self._json(200, {"ok": True})
            return
        if path == "/api/sessions/rename":
            body = self._read_body()
            sid = body.get("session") or ""
            title = (body.get("title") or "").strip()[:60]
            if not title:
                self._json(400, {"ok": False, "error": "empty title"})
                return
            with _SESSIONS_LOCK:
                s = _SESSIONS.get(sid)
                if s is None:
                    self._json(404, {"ok": False, "error": "session not found"})
                    return
                s["title"] = title
                self._owner.save_sessions()
            self._json(200, {"ok": True, "title": title})
            return
        self._json(404, {"ok": False, "error": "not found"})

    def do_DELETE(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/api/sessions":
            qs = parse_qs(parsed.query)
            sid = (qs.get("session") or [""])[0]
            if not sid:
                self._json(400, {"ok": False, "error": "missing session"})
                return
            with _SESSIONS_LOCK:
                if sid not in _SESSIONS:
                    self._json(404, {"ok": False, "error": "session not found"})
                    return
                del _SESSIONS[sid]
                self._owner.save_sessions()
            self._json(200, {"ok": True})
            return
        self._json(404, {"ok": False, "error": "not found"})

    # ---------------- chat (SSE) ----------------
    def _chat(self) -> None:
        body = self._read_body()
        message = (body.get("message") or "").strip()
        if not message:
            self._json(400, {"ok": False, "error": "empty message"})
            return
        session_id = body.get("session") or str(uuid.uuid4().hex[:12])
        with _SESSIONS_LOCK:
            s = _SESSIONS.get(session_id)
            if s is None:
                s = {"id": session_id, "title": message[:28], "created": int(time.time()),
                     "messages": [], "agent": None, "lock": threading.Lock()}
                _SESSIONS[session_id] = s
            s["messages"].append({"role": "user", "content": message, "tools": []})
            self._owner.save_sessions()
        agent = s["agent"]

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()

        # 获得会话 agent (kernel 单例懒构建)
        if agent is None:
            try:
                agent = self._owner.make_agent()
                with _SESSIONS_LOCK:
                    s["agent"] = agent
            except Exception as exc:  # noqa: BLE001
                self.wfile.write(_sse("error", {"message": f"Agent 构建失败: {exc}"}).encode("utf-8"))
                self.wfile.write(_sse("done", {"text": ""}).encode("utf-8"))
                self.wfile.flush()
                return

        q: "queue.Queue[tuple[str, Any]]" = queue.Queue()

        def on_token(t: str) -> None:
            q.put(("delta", t))

        def on_tool(name: str, args: Any) -> None:
            q.put(("tool", {"name": name, "args": (args or "")[:400]}))

        def on_tool_result(name: str, out: str) -> None:
            q.put(("tool_result", {"name": name, "out": (out or "")[:800]}))

        def on_reason(text: str) -> None:
            q.put(("reason", text))

        def on_error(err: str) -> None:
            q.put(("error", {"message": err}))

        def _run() -> None:
            try:
                with s["lock"]:
                    agent.run(message, stream=True,
                              on_token=on_token, on_tool=on_tool,
                              on_tool_result=on_tool_result,
                              on_reason=on_reason, on_error=on_error)
            except Exception as exc:  # noqa: BLE001
                q.put(("error", {"message": str(exc)}))

        self.wfile.write(_sse("session", {"id": session_id}).encode("utf-8"))
        self.wfile.flush()

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()
        text_parts: List[str] = []
        while thread.is_alive() or not q.empty():
            try:
                kind, data = q.get(timeout=0.3)
            except queue.Empty:
                continue
            if kind == "delta":
                text_parts.append(data)
            self.wfile.write(_sse(kind, data).encode("utf-8"))
            self.wfile.flush()
        self.wfile.write(_sse("done", {"text": "".join(text_parts)}).encode("utf-8"))
        self.wfile.flush()

        with _SESSIONS_LOCK:
            s["messages"].append({"role": "assistant", "content": "".join(text_parts), "tools": []})
            self._owner.save_sessions()


class WebServer:
    """本地 Web 工作台服务。"""

    def __init__(self, kernel: Any, workspace: str, host: str = "127.0.0.1",
                 port: int = 8090, model_label: str = "", engine_label: str = "") -> None:
        self.kernel = kernel
        self.workspace = workspace
        self.host = host
        self.port = port
        self.model_label = model_label or "qxt"
        self.engine_label = engine_label or "qingxiaotuan"
        self._cancel: Optional[threading.Event] = None
        self._make_agent_fn = None
        self._httpd: Optional[ThreadingHTTPServer] = None
        self._session_file = Path(workspace or ".") / ".qxt" / "web_sessions.json"
        self.load_sessions()

    # ---------------- 会话持久化 ----------------
    def load_sessions(self) -> int:
        """启动时从磁盘加载历史会话 (重启不丢)。返回加载条数。"""
        try:
            if not self._session_file.exists():
                return 0
            data = json.loads(self._session_file.read_text(encoding="utf-8"))
            loaded = 0
            with _SESSIONS_LOCK:
                for sid, s in data.items():
                    if not isinstance(s, dict) or "id" not in s:
                        continue
                    s.setdefault("agent", None)
                    s.setdefault("lock", threading.Lock())
                    _SESSIONS[sid] = s
                    loaded += 1
            return loaded
        except Exception:  # noqa: BLE001
            return 0

    def save_sessions(self) -> None:
        """把会话快照写盘 (<workspace>/.qxt/web_sessions.json)。"""
        try:
            self._session_file.parent.mkdir(parents=True, exist_ok=True)
            with _SESSIONS_LOCK:
                data = {sid: _serializable(s) for sid, s in _SESSIONS.items()}
            tmp = self._session_file.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
            tmp.replace(self._session_file)
        except Exception:  # noqa: BLE001
            pass

    # ---------------- 安全状态面板 ----------------
    def security_info(self) -> Dict[str, Any]:
        """读取安全基准存档 (bench/security-bench.json), 供前端展示。"""
        bench = Path(self.workspace or ".") / "bench" / "security-bench.json"
        try:
            if not bench.exists():
                return {"available": False}
            data = json.loads(bench.read_text(encoding="utf-8"))
            return {"available": True, "benchmark": data}
        except Exception:  # noqa: BLE001
            return {"available": False}

    # ---------------- 运行 ----------------
    def make_agent(self):
        if self._make_agent_fn is not None:
            return self._make_agent_fn()
        from ..app import create_agent

        agent = create_agent(self.kernel, self.workspace)
        return agent

    def set_agent_factory(self, fn) -> None:
        """注入 agent 工厂 (测试/外部装配用)。"""
        self._make_agent_fn = fn

    def cancel_current(self) -> None:
        ev = self._cancel
        if ev is not None:
            ev.set()
        try:
            with _SESSIONS_LOCK:
                agents = [s.get("agent") for s in _SESSIONS.values()]
            for a in agents:
                if a is not None and hasattr(a, "cancel"):
                    a.cancel()
        except Exception:  # noqa: BLE001
            pass

    def serve_forever(self, banner: Optional[Callable[[str, str, str], None]] = None) -> None:
        self._httpd = _WebHTTPServer((self.host, self.port), self)
        self.port = self._httpd.server_address[1]  # 端口 0 → 实际分配
        url = f"http://{self.host}:{self.port}"
        if banner is not None:
            # 嵌入场景 (TUI /web): 横幅走回调 (如 ui 桥接), 避免 print 打爆全屏界面
            banner(url, self.workspace, self.model_label)
        else:
            print(f"  青小团 Web 工作台已启动: {url}")
            print(f"  工作区: {self.workspace}  ·  模型: {self.model_label}")
            print("  按 Ctrl+C 停止服务")
        try:
            self._httpd.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            self._httpd.server_close()
