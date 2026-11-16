"""HTTP 层: ThreadingHTTPServer + 请求处理器 (路由 / SSE / 静态资源 / 会话循环)。"""

from .frontend import FRONTEND_HTML
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, cast
from urllib.parse import urlparse, parse_qs
import json
import queue
import subprocess
import threading
import time
import uuid

from ._common import (
    _ACTIVE_CHAT,
    _ASSET_CACHE,
    _ASSET_DIR,
    _SESSIONS,
    _SESSIONS_LOCK,
    _SSE_HEARTBEAT_SEC,
    _list_dir,
    _resolve_in_workspace,
    _sse,
    analyze_command,
    render_share_html,
    web_strings,
)

import logging
log = logging.getLogger(__name__)

if TYPE_CHECKING:
    # server.py 在运行期导入本模块 (handler), 这里只在类型检查期反向引用其 WebServer。
    from .server import WebServer


class _WebHTTPServer(ThreadingHTTPServer):
    """绑定 WebServer owner, 供 handler 经 self.server.owner 访问配置。"""

    def __init__(self, addr: Any, owner: "WebServer") -> None:
        super().__init__(addr, _WebHandler)
        self.owner = owner


class _WebHandler(BaseHTTPRequestHandler):

    # SSE 每事件只有几十字节: Nagle 算法会把小包攒到 "有未确认数据" 才发,
    # 与 delayed-ACK 叠加后每个事件平白多出 ~40ms 停顿 (Windows 上尤其明显),
    # 长回复就是数百次卡顿 —— 表现为"响应极其慢/一顿一顿的"。关掉它。
    disable_nagle_algorithm = True

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
        # owner 由 _WebHTTPServer.__init__ 注入; BaseServer 静态类型上没有该属性。
        return cast("WebServer", getattr(self.server, "owner"))

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
        except Exception as exc:  # noqa: BLE001
            log.debug("_WebHandler._read_body(): 非致命异常已忽略(设计内降级, 不改控制流): %s", exc)
            return {}

    def log_message(self, fmt: str, *args: Any) -> None:  # 静默访问日志
        pass

    # ---------------- routes ----------------
    def _serve_asset(self, name: str) -> None:
        """静态资源 (官方 Kimi 设计系统 CSS 等)。读一次缓存, 断网可用。"""
        if "/" in name or "\\" in name or ".." in name:
            self._text(404, "not found", "text/plain; charset=utf-8")
            return
        cached = _ASSET_CACHE.get(name)
        if cached is None:
            fp = _ASSET_DIR / name
            if not fp.is_file():
                self._text(404, "not found", "text/plain; charset=utf-8")
                return
            cached = fp.read_bytes()
            _ASSET_CACHE[name] = cached
        ctype = "text/css; charset=utf-8" if name.endswith(".css") else "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(cached)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(cached)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        if path.startswith("/assets/"):
            self._serve_asset(path[len("/assets/"):])
            return
        if path == "/" or path == "/index.html":
            self._text(200, FRONTEND_HTML, "text/html; charset=utf-8")
            return
        if path == "/api/sessions":
            with _SESSIONS_LOCK:
                items = [{"id": s["id"], "title": s["title"], "created": s["created"],
                          "forked_from": s.get("forked_from"),
                          "messages": len(s.get("messages") or [])}
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
            me = self._owner.mode_effort()
            self._json(200, {"ok": True,
                             "model": self._owner.model_label,
                             "workspace": self._owner.workspace,
                             "engine": self._owner.engine_label,
                             "mode": me["mode"],
                             "effort": me["effort"],
                             "git": self._owner.git_status(),
                             "trust": self._owner.trust_status(),
                             "insecure_binding": self._owner.insecure_binding,
                             "i18n": web_strings(),
                             "security": self._owner.security_info()})
            return
        if path == "/api/git":
            self._json(200, {"ok": True, **self._owner.git_status()})
            return
        if path == "/api/trust":
            self._json(200, {"ok": True, **self._owner.trust_status()})
            return
        if path == "/api/slash":
            self._json(200, {"ok": True, "commands": self._owner.slash_commands()})
            return
        if path == "/api/config":
            self._json(200, self._owner.config_snapshot())
            return
        if path == "/api/files":
            qs = parse_qs(parsed.query)
            rel = (qs.get("path") or [""])[0]
            target = _resolve_in_workspace(self._owner.workspace, rel)
            if target is None:
                self._json(400, {"ok": False, "error": "path outside workspace"})
                return
            if not target.is_dir():
                self._json(404, {"ok": False, "error": "not a directory"})
                return
            base = Path(self._owner.workspace or ".").resolve()
            self._json(200, {"ok": True, "path": rel,
                             "entries": _list_dir(base, target)})
            return
        if path == "/api/file":
            qs = parse_qs(parsed.query)
            rel = (qs.get("path") or [""])[0]
            target = _resolve_in_workspace(self._owner.workspace, rel)
            if target is None:
                self._json(400, {"ok": False, "error": "path outside workspace"})
                return
            if not target.is_file():
                self._json(404, {"ok": False, "error": "not a file"})
                return
            try:
                raw = target.read_bytes()[:262144]  # 上限 256KB, 防止拖垮浏览器
            except (OSError, PermissionError) as exc:
                self._json(500, {"ok": False, "error": str(exc)})
                return
            if b"\x00" in raw[:2048]:
                self._json(200, {"ok": True, "path": rel, "binary": True,
                                 "content": "", "size": target.stat().st_size})
                return
            self._json(200, {"ok": True, "path": rel, "binary": False,
                             "content": raw.decode("utf-8", errors="replace"),
                             "size": target.stat().st_size})
            return
        if path == "/api/diff":
            self._json(200, {"ok": True, "diff": self._owner.git_diff()})
            return
        if path == "/api/context":
            self._json(200, {"ok": True, **self._owner.context_info()})
            return
        if path == "/api/mcp":
            self._json(200, {"ok": True, "servers": self._owner.mcp_status()})
            return
        if path == "/api/plugins":
            self._json(200, self._owner.plugins_snapshot())
            return
        if path == "/api/security":
            self._json(200, {"ok": True, **self._owner.security_detail()})
            return
        if path == "/api/share":
            qs = parse_qs(parsed.query)
            sid = (qs.get("session") or [""])[0]
            with _SESSIONS_LOCK:
                s = _SESSIONS.get(sid)
                snap = dict(s) if s else None
            if snap is None:
                self._json(404, {"ok": False, "error": "session not found"})
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Disposition",
                             f'inline; filename="tuan-session-{sid}.html"')
            self.send_header("Content-Length",
                             str(len(render_share_html(snap).encode("utf-8"))))
            self.end_headers()
            self.wfile.write(render_share_html(snap).encode("utf-8"))
            return
        if path == "/api/settings":
            # T-2.6: 读取 Web UI 用户偏好 (任意键, 前端分片据此做引擎同步)
            self._json(200, {"ok": True, "settings": self._owner.settings_snapshot()})
            return
        # ============== Desktop Agent 增强端点 ==============
        if path == "/api/skills":
            self._json(200, {"ok": True, "skills": self._owner.skills_list()})
            return
        if path == "/api/router/status":
            self._json(200, {"ok": True, **self._owner.router_status()})
            return
        if path == "/api/agents/registry":
            self._json(200, {"ok": True, "agents": self._owner.agents_registry_list()})
            return
        if path == "/api/screenshot":
            self._json(200, self._owner.take_screenshot())
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
        if path == "/api/shell":
            self._shell()
            return
        if path == "/api/sessions/fork":
            self._fork()
            return
        if path == "/api/approve":
            body = self._read_body()
            ok = self._owner.resolve_approval(
                str(body.get("id") or ""), str(body.get("decision") or "deny"))
            self._json(200, {"ok": ok})
            return
        if path == "/api/plugins/toggle":
            body = self._read_body()
            res = self._owner.toggle_plugin(
                str(body.get("kind") or ""), str(body.get("name") or ""),
                bool(body.get("enabled")))
            self._json(200 if res.get("ok") else 400, res)
            return
        if path == "/api/mode":
            body = self._read_body()
            if "mode" in body and body["mode"]:
                res = self._owner.apply_mode(body["mode"])
            elif "effort" in body and body["effort"]:
                res = self._owner.apply_effort(body["effort"])
            else:
                res = {"ok": False, "error": "缺少 mode 或 effort 参数"}
            self._json(200 if res.get("ok") else 400, res)
            return
        if path == "/api/trust":
            body = self._read_body()
            res = self._owner.set_trust_level(str(body.get("level") or ""))
            self._json(200 if res.get("ok") else 400, res)
            return
        if path == "/api/config/set":
            body = self._read_body()
            res = self._owner.apply_setting(str(body.get("key") or ""), body.get("value"))
            self._json(200 if res.get("ok") else 400, res)
            return
        if path == "/api/config/model":
            body = self._read_body()
            res = self._owner.apply_model(str(body.get("provider") or ""),
                                          str(body.get("model") or ""),
                                          str(body.get("api_key") or ""),
                                          str(body.get("base_url") or ""),
                                          str(body.get("api_key_env") or ""))
            self._json(200 if res.get("ok") else 400, res)
            return
        if path == "/api/config/apikey":
            body = self._read_body()
            res = self._owner.apply_apikey(str(body.get("env") or ""),
                                           str(body.get("key") or ""))
            self._json(200 if res.get("ok") else 400, res)
            return
        if path == "/api/settings":
            # T-2.6: 接受设置 JSON 对象, 任意键合并存储并落盘 (重启后保留)
            body = self._read_body()
            if not isinstance(body, dict) or not body:
                self._json(400, {"ok": False, "error": "settings 必须是非空 JSON 对象"})
                return
            self._owner.apply_settings(body)
            self._json(200, {"ok": True, "settings": self._owner.settings_snapshot()})
            return
        # ============== Desktop Agent 增强端点 (POST) ==============
        if path == "/api/skills":
            body = self._read_body()
            action = (body.get("action") or "save").strip()
            if action == "save":
                res = self._owner.skill_save(
                    str(body.get("name") or ""),
                    str(body.get("description") or ""),
                    str(body.get("body") or ""),
                )
                self._json(200 if res.get("ok") else 400, res)
            elif action == "delete":
                res = self._owner.skill_delete(str(body.get("name") or ""))
                self._json(200 if res.get("ok") else 400, res)
            elif action == "search":
                skills_res = self._owner.skill_search(
                    str(body.get("query") or ""),
                    int(body.get("limit") or 5),
                )
                self._json(200, {"ok": True, "skills": skills_res})
            elif action == "read":
                res = self._owner.skill_read(str(body.get("name") or ""))
                self._json(200 if res.get("ok") else 404, res)
            else:
                self._json(400, {"ok": False, "error": f"unknown action: {action}"})
            return
        if path == "/api/dispatch":
            body = self._read_body()
            res = self._owner.dispatch_agent(
                instruction=str(body.get("instruction") or ""),
                agent=str(body.get("agent") or ""),
                skills=list(body.get("skills") or []),
                timeout=int(body.get("timeout") or 180),
                exclude_tools=list(body.get("exclude_tools") or []),
            )
            self._json(200 if res.get("ok") else 500, res)
            return
        if path == "/api/mcp":
            body = self._read_body()
            action = (body.get("action") or "status").strip()
            if action == "toggle":
                res = self._owner.mcp_toggle(
                    str(body.get("name") or ""),
                    bool(body.get("enabled")),
                )
                self._json(200 if res.get("ok") else 400, res)
            elif action == "connect":
                res = self._owner.mcp_connect(str(body.get("name") or ""))
                self._json(200 if res.get("ok") else 400, res)
            else:
                self._json(400, {"ok": False, "error": f"unknown action: {action}"})
            return
        # Computer Use: OCR (接收 base64 图片)
        if path == "/api/ocr":
            body = self._read_body()
            b64 = str(body.get("base64") or "")
            if not b64:
                self._json(400, {"ok": False, "error": "base64 必填"})
                return
            res = self._owner.run_ocr(b64)
            self._json(200 if res.get("ok") else 400, res)
            return
        self._json(404, {"ok": False, "error": "not found"})

    # ---------------- 工作区 shell (! 执行) ----------------
    def _shell(self) -> None:
        """执行 shell 命令 —— **先过安全引擎**, 高危需前端显式批准。

        这是 Web 侧与 CLI 共用同一条安全口径的地方: 引擎返回 block / critical / high
        时不直接执行, 而是把 risk·reasons·blast_radius·suggestions 回给前端,
        由用户在审批弹窗里 allow / deny。
        """
        body = self._read_body()
        command = (body.get("command") or "").strip()
        if not command:
            self._json(400, {"ok": False, "error": "empty command"})
            return
        approved = bool(body.get("approved"))
        verdict = analyze_command(command)
        # v0.4: 多维风险向量 + 执行域决策 (审批弹窗可见"危险在哪一类/要不要沙箱")
        try:
            from .ext.risk_vector import assess as _risk_assess
            from .ext.sandbox import decide_execution_tier as _decide

            rv = _risk_assess(command, safety_score=verdict)
            decision = _decide(rv, self._owner.kernel.get("config") if self._owner.kernel else None,
                               force_deny=bool(verdict.get("block")))
            verdict["risk_vector"] = rv.to_dict()
            verdict["execution"] = {"action": decision.action, "tier": int(decision.tier),
                                    "backend": decision.backend, "reason": decision.reason}
            risky = bool(verdict.get("block")) or verdict.get("risk") in ("critical", "high") \
                or decision.action in ("ask", "deny")
        except Exception:  # noqa: BLE001 - 向量评估失败不阻断原判定
            risky = bool(verdict.get("block")) or verdict.get("risk") in ("critical", "high")
        if risky and not approved:
            self._json(200, {"ok": True, "needs_approval": True,
                             "command": command, "verdict": verdict})
            return
        timeout = int(body.get("timeout") or 60)
        try:
            proc = subprocess.run(  # noqa: S602 - 命令经安全引擎评估 + 用户审批
                command, shell=True, cwd=self._owner.workspace,
                capture_output=True, text=True, timeout=max(1, min(timeout, 600)),
                errors="replace",
            )
            out = (proc.stdout or "") + (proc.stderr or "")
            self._json(200, {"ok": True, "needs_approval": False, "verdict": verdict,
                             "exit": proc.returncode, "output": out[:40000],
                             "truncated": len(out) > 40000})
        except subprocess.TimeoutExpired:
            self._json(200, {"ok": True, "needs_approval": False, "verdict": verdict,
                             "exit": -1, "output": f"[超时] 命令超过 {timeout}s 未结束"})
        except Exception as exc:  # noqa: BLE001
            self._json(200, {"ok": True, "needs_approval": False, "verdict": verdict,
                             "exit": -1, "output": f"[错误] {exc}"})

    # ---------------- 会话分支 (fork) ----------------
    def _fork(self) -> None:
        """从某条会话 (可指定切点) 分叉出一条新会话, 原会话不受影响。"""
        body = self._read_body()
        sid = str(body.get("session") or "")
        with _SESSIONS_LOCK:
            src = _SESSIONS.get(sid)
            if src is None:
                self._json(404, {"ok": False, "error": "session not found"})
                return
            msgs = src.get("messages") or []
            upto = body.get("upto")
            if isinstance(upto, int) and -1 <= upto < len(msgs):
                msgs = msgs[: upto + 1]
            new_id = uuid.uuid4().hex[:12]
            title = (src.get("title") or "会话") + " · 分支"
            _SESSIONS[new_id] = {
                "id": new_id, "title": title[:60], "created": int(time.time()),
                "messages": json.loads(json.dumps(msgs, ensure_ascii=False)),
                "agent": None, "lock": threading.Lock(), "forked_from": sid,
            }
            self._owner.save_sessions()
        self._json(200, {"ok": True, "id": new_id, "title": title[:60],
                         "messages": len(msgs)})

    def do_DELETE(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/api/sessions":
            qs = parse_qs(parsed.query)
            sid = (qs.get("session") or [""])[0]
            if not sid:
                # T-3.6: 不带 session 参数 = 删除全部会话 (前端侧栏"清空全部"入口)
                with _SESSIONS_LOCK:
                    count = len(_SESSIONS)
                    _SESSIONS.clear()
                    self._owner.save_sessions()
                self._json(200, {"ok": True, "deleted": count})
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
            # 防抖落盘: 全量序列化所有会话 (含历史 parts) 在大会话下要数百毫秒,
            # 同步做会直接推迟首 token。1s 后合并落一次; 回合结束仍有同步保存。
            self._owner.save_sessions_soon()
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
        # 有序片段流 (text / tool / reason): 前端据此把工具块内联到正文中,
        # 并随会话一起落盘 —— 否则重开历史时工具调用会整体丢失。
        parts: List[Dict[str, Any]] = []
        last_tool: Dict[str, Any] = {}

        def on_token(t: str) -> None:
            if parts and parts[-1].get("type") == "text":
                parts[-1]["text"] += t
            else:
                parts.append({"type": "text", "text": t})
            q.put(("delta", t))

        def on_tool(name: str, args: Any) -> None:
            part: Dict[str, Any] = {"type": "tool", "name": name, "args": (args or "")[:400], "out": ""}
            parts.append(part)
            last_tool["p"] = part
            q.put(("tool", {"name": name, "args": (args or "")[:400]}))

        def on_tool_result(name: str, out: str) -> None:
            cur = last_tool.get("p")
            if isinstance(cur, dict):
                cur["out"] = (out or "")[:800]
            q.put(("tool_result", {"name": name, "out": (out or "")[:800]}))

        def on_reason(text: str) -> None:
            if parts and parts[-1].get("type") == "reason":
                parts[-1]["text"] += text
            else:
                parts.append({"type": "reason", "text": text})
            q.put(("reason", text))

        def on_error(err: str) -> None:
            q.put(("error", {"message": err}))

        def _run() -> None:
            _ACTIVE_CHAT[threading.get_ident()] = q
            try:
                with s["lock"]:
                    agent.run(message, stream=True,
                              on_token=on_token, on_tool=on_tool,
                              on_tool_result=on_tool_result,
                              on_reason=on_reason, on_error=on_error)
            except Exception as exc:  # noqa: BLE001
                q.put(("error", {"message": str(exc)}))
            finally:
                _ACTIVE_CHAT.pop(threading.get_ident(), None)

        self.wfile.write(_sse("session", {"id": session_id}).encode("utf-8"))
        self.wfile.flush()

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()
        text_parts: List[str] = []
        last_write = time.monotonic()
        try:
            while thread.is_alive() or not q.empty():
                try:
                    kind, data = q.get(timeout=0.3)
                except queue.Empty:
                    # 心跳: 思考期 (推理模型静默可达分钟级) 没有任何事件的间隙,
                    # 周期性写 SSE 注释行。客户端解析器忽略无 event:/data: 的注释,
                    # 但代理/中间层见到字节流动就不会因空闲而掐断连接 —— 这是
                    # "长思考后连接被切断、回复莫名中断" 的直接防线。
                    if time.monotonic() - last_write >= _SSE_HEARTBEAT_SEC:
                        self.wfile.write(b": hb\n\n")
                        self.wfile.flush()
                        last_write = time.monotonic()
                    continue
                if kind == "delta":
                    text_parts.append(data)
                self.wfile.write(_sse(kind, data).encode("utf-8"))
                self.wfile.flush()
                last_write = time.monotonic()
        except Exception:  # noqa: BLE001 - 客户端断开 (关闭标签页/断网):
            # 写失败即浏览器不在了。立即取消本轮生成, 否则 agent 会把整轮
            # 跑完, 白烧 token 且占着会话锁堵住后续消息 ("容易中断" 的成因之一)。
            try:
                agent.cancel()
            except Exception as exc:  # noqa: BLE001
                log.warning("_WebHandler._chat(): 非致命异常已忽略(设计内降级, 不改控制流): %s", exc)
                pass
            return
        self.wfile.write(_sse("done", {"text": "".join(text_parts)}).encode("utf-8"))
        self.wfile.flush()

        with _SESSIONS_LOCK:
            tools = [
                {"name": p.get("name", ""), "args": p.get("args", ""), "out": p.get("out", "")}
                for p in parts
                if p.get("type") == "tool"
            ]
            s["messages"].append({
                "role": "assistant",
                "content": "".join(text_parts),
                "tools": tools,
                "parts": parts,
            })
            self._owner.save_sessions()
            # T-5.2: 本轮结束后检查预算用量, 达阈值则告警 (内部已去重, 不阻塞)
            self._owner.check_budget_alert(session_id)
