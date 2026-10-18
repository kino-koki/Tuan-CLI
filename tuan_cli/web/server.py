# -*- coding: utf-8 -*-
"""青小团 Web 界面 (DeepSeek-harness 风格本地工作台)。

标准库实现 (http.server + SSE), 零新增依赖 —— 与"离线优先 / 可审计"叙事一致:
- 每个会话一个 Agent 实例 (复用 create_agent, 独立消息历史)
- 流式输出走 SSE (on_token / on_tool / on_tool_result / on_reason / on_error)
- 线程锁串行化执行 (个人本地工具, 一个进程同时跑一轮)
- 无外链 CDN, 前端全部内联 (断网可用)
- 会话磁盘持久化 (<workspace>/.tuan/web_sessions.json, 重启不丢)
"""
from __future__ import annotations

import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urlparse, parse_qs

from .frontend import FRONTEND_HTML

_ASSET_DIR = Path(__file__).resolve().parent / "assets"
_ASSET_CACHE: Dict[str, bytes] = {}  # 读一次缓存, 静态资源体积小但读盘更省

# 回环地址白名单: /api/* 全部**无鉴权**, 因此服务只应绑在本机回环上。
# 与 CLI 的四道闸门同一条逻辑 —— 默认收紧, 越界必须显式且被明确告知。
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost", ""})


def is_loopback(host: str) -> bool:
    """判断绑定地址是否为本机回环 (127.0.0.0/8、::1、localhost)。"""
    h = (host or "").strip().lower()
    if h in _LOOPBACK_HOSTS:
        return True
    return h.startswith("127.")


def non_loopback_warning(host: str, port: int) -> str:
    """非回环绑定的醒目警告文本 (供 CLI / 嵌入场景统一输出)。"""
    return (
        "\n"
        "  ⚠️  安全警告: Web 工作台绑定在非回环地址 {host}:{port}\n"
        "      /api/* 接口**没有鉴权** —— 同一网络内的任何人都能读写你的会话、\n"
        "      执行 shell 命令、访问工作区文件。\n"
        "      仅在你完全信任该网络时才这么做; 否则请用默认的 127.0.0.1。\n"
    ).format(host=host, port=port)

_SESSIONS: Dict[str, Dict[str, Any]] = {}
_SESSIONS_LOCK = threading.RLock()  # 嵌套获取 (save_sessions 在会话锁内落盘)

# 待审批的危险操作: {request_id: {"event": Event, "result": bool}}
_APPROVALS: Dict[str, Dict[str, Any]] = {}
#: SSE 心跳间隔 (秒): 无事件间隙超过该值就写一行注释, 防代理掐断空闲连接。
_SSE_HEARTBEAT_SEC = 10.0

_APPROVALS_LOCK = threading.Lock()

# 当前正在跑的对话轮 → 其 SSE 事件队列 (按线程标识索引)。
# agent.run 的 on_* 回调与 confirm 回调都跑在同一个 worker 线程上,
# 因此用 thread ident 就能把"审批请求"推给正确的那条 SSE 流。
_ACTIVE_CHAT: Dict[int, "queue.Queue[tuple[str, Any]]"] = {}


def _sse(kind: str, data: Any) -> str:
    return f"event: {kind}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


# ---------------------------------------------------------------- 安全引擎 (懒加载单例)
_SAFETY_ENGINE: Any = None


def safety_engine() -> Any:
    """懒加载安全引擎单例 (score() 返回 risk/block/reasons/blast_radius/suggestions)。"""
    global _SAFETY_ENGINE
    if _SAFETY_ENGINE is None:
        from ..ext.safety_engine import SafetyEngine

        _SAFETY_ENGINE = SafetyEngine()
    return _SAFETY_ENGINE


def analyze_command(command: str) -> Dict[str, Any]:
    """对 shell 命令做安全评估 (与 CLI 同一引擎, 同一口径)。"""
    try:
        return safety_engine().score({"command": command, "type": "shell"}) or {}
    except Exception as exc:  # noqa: BLE001
        return {"risk": "unknown", "score": 0, "block": False,
                "reasons": [f"安全评估不可用: {exc}"], "suggestions": [],
                "blast_radius": {"files": [], "services": [], "data": []}}


def _resolve_in_workspace(workspace: str, rel: str) -> Optional[Path]:
    """把相对路径解析到工作区内; 越界 (../ 逃逸) 返回 None。

    Web 接口按设计只服务**本工作区**: 任何绝对路径或向上穿越一律拒绝,
    与 CLI 的路径护栏同一条逻辑。
    """
    base = Path(workspace or ".").resolve()
    raw = (rel or "").strip().replace("\\", "/")
    if raw.startswith("/") or (len(raw) > 1 and raw[1] == ":"):
        return None
    try:
        p = (base / raw).resolve()
    except (OSError, ValueError):
        return None
    try:
        p.relative_to(base)
    except ValueError:
        return None
    return p


_SKIP_DIRS = frozenset({".git", "__pycache__", "node_modules", ".venv", "venv",
                        ".mypy_cache", ".pytest_cache", ".ruff_cache", "dist", "build"})


def _md_to_html(text: str) -> str:
    """极简 Markdown → HTML (用于分享页的服务端渲染; 先转义再处理标记, 防注入)。"""
    import html as _html

    def inline(s: str) -> str:
        s = _html.escape(s or "")
        s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
        s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)
        s = re.sub(r"\[([^\]]+)\]\((https?://[^\s)]+)\)",
                   r'<a href="\2" target="_blank" rel="noopener">\1</a>', s)
        return s

    out: List[str] = []
    i = 0
    lines = (text or "").split("\n")
    while i < len(lines):
        t = lines[i].strip()
        if t.startswith("```"):
            buf = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                buf.append(lines[i]); i += 1
            i += 1
            out.append("<pre><code>" + _html.escape("\n".join(buf)) + "</code></pre>")
            continue
        if not t:
            i += 1; continue
        hm = re.match(r"^(#{1,4})\s+(.*)$", t)
        if hm:
            lv = len(hm.group(1))
            out.append(f"<h{lv}>{inline(hm.group(2))}</h{lv}>"); i += 1; continue
        if t.startswith("- ") or t.startswith("* "):
            ul = []
            while i < len(lines) and re.match(r"^\s*[-*]\s+", lines[i]):
                ul.append("<li>" + inline(re.sub(r"^\s*[-*]\s+", "", lines[i])) + "</li>")
                i += 1
            out.append("<ul>" + "".join(ul) + "</ul>"); continue
        out.append("<p>" + inline(t) + "</p>"); i += 1
    return "\n".join(out)


_SHARE_TMPL = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} · TUAN 会话分享</title>
<style>
  body{{margin:0;background:#f9fbfc;color:#111;font:15px/1.75 -apple-system,
       "Segoe UI","Microsoft YaHei",sans-serif;padding:40px 16px}}
  .wrap{{max-width:760px;margin:0 auto}}
  .hd{{border-bottom:1px solid #e3e8ee;padding-bottom:14px;margin-bottom:24px}}
  .hd h1{{font-size:20px;margin:0 0 6px}}
  .hd .meta{{font-size:12px;color:#6b7680}}
  .m{{margin:0 0 18px}}
  .m .who{{font-size:12px;font-weight:600;margin-bottom:4px}}
  .m.user .who{{color:#0b62c4}}
  .m.asst .who{{color:#1783ff}}
  .m .body{{background:#fff;border:1px solid #e3e8ee;border-radius:12px;padding:12px 16px}}
  .m.user .body{{background:#f0f4f8}}
  .m .body pre{{background:#f5f5f5;border-radius:8px;padding:10px 12px;overflow-x:auto;
                font:12px/1.6 ui-monospace,Consolas,monospace}}
  .m .body code{{background:#eef1f4;border-radius:4px;padding:1px 5px;
                 font:12px ui-monospace,Consolas,monospace}}
  .tool{{font-size:12px;color:#4a5560;background:#f7f9fb;border:1px dashed #d5dde5;
         border-radius:8px;padding:6px 10px;margin:6px 0;word-break:break-all}}
  .ft{{margin-top:32px;font-size:11px;color:#9aa4ad;text-align:center}}
  a{{color:#1783ff;text-decoration:none}}
</style></head><body><div class="wrap">
<div class="hd"><h1>{title}</h1>
<div class="meta">TUAN 会话分享 · {meta}</div></div>
{content}
<div class="ft">由 Tuan-CLI (青小团) 生成 · 本页为静态快照, 不含任何运行能力</div>
</div></body></html>"""


def render_share_html(session: Dict[str, Any]) -> str:
    """把一条会话渲染成**自包含静态 HTML** (无 JS / 无外链 / 无鉴权信息)。

    用途: 会话分享 —— 保存或发给他人即可阅读, 打开不需要任何服务在跑。
    """
    title = session.get("title") or "未命名会话"
    msgs = session.get("messages") or []
    parts: List[str] = []
    for m in msgs:
        role = m.get("role")
        who = "你" if role == "user" else "TUAN"
        cls = "user" if role == "user" else "asst"
        body = _md_to_html(str(m.get("content") or ""))
        tools_html = ""
        for tc in (m.get("tools") or [])[:40]:
            tools_html += (
                f'<div class="tool">🛠 <b>{_html_escape(tc.get("name", ""))}</b> '
                f'{_html_escape(str(tc.get("args", ""))[:160])}'
                f'{(" → " + _html_escape(str(tc.get("out", ""))[:200])) if tc.get("out") else ""}</div>'
            )
        parts.append(f'<div class="m {cls}"><div class="who">{who}</div>'
                     f'{tools_html}<div class="body">{body}</div></div>')
    fork = session.get("forked_from")
    meta = f"{len(msgs)} 条消息 · 分支自 {fork}" if fork else f"{len(msgs)} 条消息"
    return _SHARE_TMPL.format(
        title=_html_escape(title), meta=_html_escape(meta),
        content="\n".join(parts),
    )


def _html_escape(s: Any) -> str:
    import html as _h
    return _h.escape(str(s or ""), quote=False)


def web_strings() -> Dict[str, str]:
    """取当前语言下所有 ``web.*`` 键, 供前端本地化 (与 CLI 共用同一份 locale)。"""
    try:
        import importlib

        from ..i18n import get_language

        code = (get_language() or "zh-CN").replace("-", "_")
        mod = importlib.import_module(f"tuan_cli.i18n.locales.{code}")
        tr = getattr(mod, "TRANSLATIONS", {}) or {}
        return {k: v for k, v in tr.items() if k.startswith("web.")}
    except Exception:  # noqa: BLE001
        return {}


def _list_dir(base: Path, target: Path, limit: int = 400) -> List[Dict[str, Any]]:
    """列目录 (目录优先, 跳过噪声目录), 返回 [{name,path,dir,size}]。"""
    out: List[Dict[str, Any]] = []
    try:
        entries = sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
    except (OSError, PermissionError):
        return out
    for e in entries[:limit]:
        if e.name in _SKIP_DIRS:
            continue
        try:
            is_dir = e.is_dir()
            size = 0 if is_dir else e.stat().st_size
        except (OSError, PermissionError):
            continue
        out.append({"name": e.name, "path": str(e.relative_to(base)).replace("\\", "/"),
                    "dir": is_dir, "size": size})
    return out


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
                                          str(body.get("api_key") or ""))
            self._json(200 if res.get("ok") else 400, res)
            return
        if path == "/api/config/apikey":
            body = self._read_body()
            res = self._owner.apply_apikey(str(body.get("env") or ""),
                                           str(body.get("key") or ""))
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
            decision = _decide(rv, self.kernel.get("config") if self.kernel else None,
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
            except Exception:  # noqa: BLE001
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


def _provider_model_ids(preset: Any) -> List[str]:
    """供应商的可选模型 ID 列表 (剥掉 model_lists 的 |free/|paid 标注)。

    目录里清单项写作 "kimi-k3|paid", 而配置/请求里必须是不带竖线的纯 ID ——
    Web 设置面板与 CLI 的 tuan model 共用这一口径 (见 cmd_model._strip_model_label)。
    """
    ids: List[str] = []
    for raw in list(getattr(preset, "recommended_models", None) or []) + [getattr(preset, "model", "")]:
        mid = str(raw).split("|", 1)[0].strip()
        if mid and mid not in ids:
            ids.append(mid)
    return ids


class WebServer:
    """本地 Web 工作台服务。"""

    def __init__(self, kernel: Any, workspace: str, host: str = "127.0.0.1",
                 port: int = 8090, model_label: str = "", engine_label: str = "") -> None:
        self.kernel = kernel
        self.workspace = workspace
        self.host = host
        self.port = port
        self.model_label = model_label or "tuan"
        self.engine_label = engine_label or "tuan_cli"
        # 是否绑在非回环地址 (接口无鉴权, 非回环 = 已告警的不安全部署)
        self.insecure_binding: bool = not is_loopback(host)
        # 热插拔状态 (Web 面板开关, 不落盘): 被关掉的工具 / 插件
        self._disabled_tools: set = set()
        self._disabled_plugins: set = set()
        self._cancel: Optional[threading.Event] = None
        self._make_agent_fn = None
        # Web 工作台内的模式/推理投入覆盖 (None = 跟随配置默认值)
        self._mode: Optional[str] = None
        self._effort: Optional[str] = None
        self._httpd: Optional[ThreadingHTTPServer] = None
        self._save_timer: Optional[threading.Timer] = None
        self._session_file = Path(workspace or ".") / ".tuan" / "web_sessions.json"
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
        """把会话快照写盘 (<workspace>/.tuan/web_sessions.json)。"""
        try:
            self._session_file.parent.mkdir(parents=True, exist_ok=True)
            with _SESSIONS_LOCK:
                data = {sid: _serializable(s) for sid, s in _SESSIONS.items()}
            tmp = self._session_file.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
            tmp.replace(self._session_file)
        except Exception:  # noqa: BLE001
            pass

    def save_sessions_soon(self, delay: float = 1.0) -> None:
        """防抖落盘: 合并短时间内的多次保存请求。

        全量序列化所有会话 (每条含 parts/工具输出) 在大会话下要数百毫秒;
        同步调用会直接推迟 SSE 首 token (用户观感: "发出去半天没反应")。
        这里只排一个定时器, 到点一次性落盘; 回合结束时仍有同步 save_sessions
        兜底, 防抖窗口内进程退出最多丢最后一两条用户消息。
        """
        with _SESSIONS_LOCK:
            if self._save_timer is not None:
                return  # 已有一场排队的落盘 (它会取到最新状态)
            timer = threading.Timer(delay, self._flush_sessions)
            timer.daemon = True
            self._save_timer = timer
            timer.start()

    def _flush_sessions(self) -> None:
        with _SESSIONS_LOCK:
            self._save_timer = None
        self.save_sessions()

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

    # 四道闸门 (与 ToolExecutor._security_gate_check 的实际顺序一致)
    _GATES = (
        {"name": "policy", "label": "策略引擎", "desc": "用户/组织策略 deny 规则"},
        {"name": "redline", "label": "硬红线", "desc": "不可逆破坏 / 编码混淆 / 解释器内联载荷"},
        {"name": "mcp_injection", "label": "MCP 注入扫描", "desc": "外部工具返回内容中的注入指令"},
        {"name": "shell_redline", "label": "Shell 硬红线", "desc": "命令级危险形态"},
        {"name": "write_gate", "label": "文件写闸门", "desc": "写入系统关键路径 / 越界路径"},
    )

    def security_detail(self) -> Dict[str, Any]:
        """安全真实信息 —— 把引擎实际产生的东西呈现出来, 而不只是一张静态卡片。

        内容: 基准数字 + 四道闸门清单 + 近期拦截记录 (从会话历史里提取被拒的工具调用)。
        """
        info = self.security_info()
        recent: List[Dict[str, Any]] = []
        try:
            with _SESSIONS_LOCK:
                for s in _SESSIONS.values():
                    for m in (s.get("messages") or []):
                        for p in (m.get("parts") or []):
                            if p.get("type") != "tool":
                                continue
                            out = str(p.get("out") or "")
                            if ("拦截" in out or "已拒绝" in out or "denied" in out.lower()):
                                recent.append({
                                    "session": s.get("title", ""),
                                    "tool": p.get("name", ""),
                                    "args": str(p.get("args") or "")[:200],
                                    "out": out[:300],
                                })
        except Exception:  # noqa: BLE001
            pass
        return {
            "available": bool(info.get("available")),
            "benchmark": info.get("benchmark"),
            "gates": list(self._GATES),
            "recent": recent[-20:],
        }

    # ---------------- 工作区 / 上下文 / MCP ----------------
    def git_diff(self) -> str:
        """工作区 git diff (只读)。非 git 仓库或 git 缺失时返回说明文本。"""
        try:
            proc = subprocess.run(  # noqa: S603 - 固定参数, 无用户输入拼接
                ["git", "diff", "--no-color", "--stat"], cwd=self.workspace,
                capture_output=True, text=True, timeout=20, errors="replace",
            )
            stat = (proc.stdout or "").strip()
            if not stat and proc.returncode != 0:
                return (proc.stderr or "非 git 仓库").strip()[:2000]
            full = subprocess.run(  # noqa: S603
                ["git", "diff", "--no-color"], cwd=self.workspace,
                capture_output=True, text=True, timeout=30, errors="replace",
            )
            body = (full.stdout or "")[:200000]
            return (stat + "\n\n" + body).strip() if stat else body
        except FileNotFoundError:
            return "未找到 git 可执行文件"
        except subprocess.TimeoutExpired:
            return "git diff 超时"
        except Exception as exc:  # noqa: BLE001
            return f"git diff 失败: {exc}"

    def context_info(self) -> Dict[str, Any]:
        """上下文与 token 用量 (按会话统计字符数并估算 token)。

        估算口径: 混合中英文按 ~3 字符/token (CJK 约 1.5, ASCII 约 4, 折中取 3);
        这是**估算**而非精确分词, 前端会明确标注为 est.
        """
        try:
            window = int(self.kernel.require("config").get("model.context_window", 128000)) \
                if self.kernel is not None else 128000
        except Exception:  # noqa: BLE001
            window = 128000
        sessions: List[Dict[str, Any]] = []
        with _SESSIONS_LOCK:
            for s in _SESSIONS.values():
                chars = 0
                for m in (s.get("messages") or []):
                    chars += len(str(m.get("content") or ""))
                    for p in (m.get("parts") or []):
                        chars += len(str(p.get("text") or "")) + len(str(p.get("out") or ""))
                sessions.append({"id": s["id"], "title": s.get("title", ""),
                                 "messages": len(s.get("messages") or []),
                                 "chars": chars, "est_tokens": chars // 3})
        sessions.sort(key=lambda x: x["est_tokens"], reverse=True)
        return {"window": window, "sessions": sessions[:20],
                "total_est_tokens": sum(s["est_tokens"] for s in sessions)}

    def mcp_status(self) -> List[Dict[str, Any]]:
        """已接入的 MCP server 状态。"""
        out: List[Dict[str, Any]] = []
        try:
            clients = self.kernel.get("mcp_clients") if self.kernel is not None else None
            if isinstance(clients, dict):
                for name, c in clients.items():
                    tools: List[str] = []
                    try:
                        tl = getattr(c, "tools", None)
                        if isinstance(tl, (list, tuple)):
                            tools = [getattr(t, "name", str(t)) for t in tl][:40]
                    except Exception:  # noqa: BLE001
                        pass
                    out.append({"name": str(name), "connected": True,
                                "tool_count": len(tools), "tools": tools})
            elif clients:
                out.append({"name": "mcp_clients", "connected": True, "tool_count": 0, "tools": []})
        except Exception:  # noqa: BLE001
            pass
        return out

    # ---------------- 插件 / 工具 热插拔 ----------------
    def plugins_snapshot(self) -> Dict[str, Any]:
        """可视化插件面板的数据: 工具 (按暴露分层分组) + 内核插件。

        两类都可热插拔 (无需重启、无需输命令):
          - 工具: 开关即从模型可见清单里排除/恢复 (走 Agent 的 exclude_tools);
          - 插件: 开关即调用内核的 activate / deactivate。
        """
        from ..tools.tiers import tier_of

        tools_items: List[Dict[str, Any]] = []
        try:
            reg = self.kernel.get("tool_registry") if self.kernel is not None else None
            if reg is not None:
                for t in sorted(reg.tools, key=lambda x: x.name):
                    if getattr(t, "hidden", False):
                        continue  # 隐藏别名不作为可选项 (它们只是兼容入口)
                    tools_items.append({
                        "name": t.name,
                        "desc": (t.description or "")[:160],
                        "tag": tier_of(t.name),
                        "enabled": t.name not in self._disabled_tools,
                        "locked": False,
                    })
        except Exception:  # noqa: BLE001
            pass

        plugin_items: List[Dict[str, Any]] = []
        try:
            plugins = self.kernel.plugins if self.kernel is not None else {}
            for name, p in sorted(plugins.items()):
                provides = list(getattr(p, "provides", []) or [])
                plugin_items.append({
                    "name": name,
                    "desc": f"v{getattr(p, 'version', '')} · 提供: {', '.join(provides) or '—'}",
                    "tag": f"{len(provides)} svc" if provides else "",
                    "enabled": name not in self._disabled_plugins,
                    "locked": False,
                })
        except Exception:  # noqa: BLE001
            pass

        return {"ok": True, "groups": [
            {"kind": "tool", "title": "工具", "items": tools_items},
            {"kind": "plugin", "title": "内核插件", "items": plugin_items},
        ]}

    def _unprovide_owned(self, owner: str) -> int:
        """摘掉某插件名下仍挂着的服务。

        内核里各插件的 `deactivate` 普遍只做自己的清理, 不会 unprovide 声明过的服务;
        若不兜底, 停用后再启用会直接报 `服务已被提供: xxx (by 自己)` ——
        热插拔就不可逆了。
        """
        svc = getattr(self.kernel, "services", None)
        owners = getattr(svc, "_service_owner", None)
        if not isinstance(owners, dict):
            return 0
        removed = 0
        for sname, own in list(owners.items()):
            # owner 匹配; 或 owner 缺失但服务名与插件同名 (常见约定: 插件提供同名服务)
            if own == owner or (not own and sname == owner):
                try:
                    self.kernel.unprovide(sname)
                    removed += 1
                except Exception:  # noqa: BLE001
                    pass
        return removed

    def toggle_plugin(self, kind: str, name: str, enabled: bool) -> Dict[str, Any]:
        """热插拔开关 (可逆)。返回 {ok, ...}。"""
        if kind == "tool":
            if enabled:
                self._disabled_tools.discard(name)
            else:
                self._disabled_tools.add(name)
            # 已建好的会话 agent 同步生效 (无需重建)
            try:
                with _SESSIONS_LOCK:
                    agents = [s.get("agent") for s in _SESSIONS.values()]
                for a in agents:
                    if a is not None:
                        a.exclude_tools = set(self._disabled_tools)
            except Exception:  # noqa: BLE001
                pass
            return {"ok": True, "kind": kind, "name": name, "enabled": enabled}
        if kind == "plugin":
            if self.kernel is None:
                return {"ok": False, "error": "kernel 不可用"}
            p = self.kernel.plugins.get(name)
            if p is None:
                return {"ok": False, "error": f"插件不存在: {name}"}
            try:
                if enabled:
                    # 先清掉上次停用可能残留的自有服务, 再激活 (保证可逆)
                    self._unprovide_owned(name)
                    p.activate(self.kernel)
                    self._disabled_plugins.discard(name)
                else:
                    p.deactivate(self.kernel)
                    self._unprovide_owned(name)
                    self._disabled_plugins.add(name)
            except Exception as exc:  # noqa: BLE001
                return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
            return {"ok": True, "kind": kind, "name": name, "enabled": enabled}
        return {"ok": False, "error": f"未知类型: {kind}"}

    # ---------------- 权限审批 (危险工具确认) ----------------
    def _ask_approval(self, prompt: str) -> bool:
        """危险操作确认回调: 向前端推审批弹窗并阻塞等待; 超时/无 UI → fail-closed 拒绝。"""
        q = _ACTIVE_CHAT.get(threading.get_ident())
        if q is None:
            return False  # 无 UI 上下文 → 默认拒绝 (fail-closed)
        req_id = uuid.uuid4().hex[:8]
        ev = threading.Event()
        with _APPROVALS_LOCK:
            _APPROVALS[req_id] = {"event": ev, "result": False}
        q.put(("approval", {"id": req_id, "prompt": str(prompt),
                            "verdict": analyze_command(str(prompt))}))
        got = ev.wait(timeout=300)
        with _APPROVALS_LOCK:
            rec = _APPROVALS.pop(req_id, None)
        return bool(rec and rec.get("result")) if got else False

    def resolve_approval(self, req_id: str, decision: str) -> bool:
        """前端审批结果回填 (allow / deny)。"""
        with _APPROVALS_LOCK:
            rec = _APPROVALS.get(req_id)
            if rec is None:
                return False
            rec["result"] = str(decision).lower() in ("allow", "yes", "true", "1")
            rec["event"].set()
        return True

    # ---------------- 模式 / 推理投入 / 工作区信任 / git / 斜杠命令 ----------------
    def _cfg(self):
        """取配置对象; 无 kernel 时返回 None (调用方自降级)。"""
        try:
            return self.kernel.require("config") if self.kernel is not None else None
        except Exception:  # noqa: BLE001
            return None

    def mode_effort(self) -> Dict[str, Any]:
        """当前生效模式 (standard/yolo/plan) 与推理投入 (low/medium/high)。

        优先级: Web 工作台里的手动覆盖 (self._mode) > 配置默认值。
        这是 /api/info 的 mode/effort 字段来源 —— 此前这两个字段从不下发,
        导致前端 t-mode / t-effort 两个 chip 永远是空的 (死 UI)。
        """
        cfg = self._cfg()
        if self._mode:
            mode = self._mode
        elif cfg is not None:
            try:
                mode = str(cfg.get("mode.default", "standard") or "standard")
            except Exception:  # noqa: BLE001
                mode = "standard"
        else:
            mode = "standard"
        if self._effort:
            effort = self._effort
        elif cfg is not None:
            try:
                effort = str(cfg.get("agent.effort", "high") or "high")
            except Exception:  # noqa: BLE001
                effort = "high"
        else:
            effort = "high"
        return {"mode": mode, "effort": effort}

    def apply_mode(self, mode: str) -> Dict[str, Any]:
        """设置运行模式并实时作用于当前所有会话 agent (以及后续新建的)。

        - plan: 只读规划模式 (agent.plan_mode=True, yolo=False)
        - yolo: 放权模式 (agent.yolo=True, plan_mode=False)
        - standard: 默认 (两者皆 False)
        同时把覆盖写回配置 (与 CLI _apply_mode_override 同口径, 不污染后续启动之外的状态)。
        """
        mode = str(mode or "").strip().lower()
        if mode not in ("standard", "yolo", "plan"):
            return {"ok": False, "error": f"未知模式: {mode}"}
        self._mode = mode
        cfg = self._cfg()
        if cfg is not None:
            try:
                cfg.data.setdefault("mode", {})["default"] = mode
            except Exception:  # noqa: BLE001
                pass
        pm = mode == "plan"
        yl = mode == "yolo"
        with _SESSIONS_LOCK:
            for s in _SESSIONS.values():
                a = s.get("agent")
                if a is None:
                    continue
                try:
                    a.plan_mode = pm
                    a.yolo = yl
                    if getattr(a, "ctx", None) is not None:
                        a.ctx.plan_mode = pm
                        a.ctx.yolo = yl
                    if hasattr(a, "effective_tool_set"):
                        a.effective_tool_set()
                except Exception:  # noqa: BLE001
                    pass
        return {"ok": True, "mode": mode, **self.mode_effort()}

    def apply_effort(self, effort: str) -> Dict[str, Any]:
        """设置推理投入档位 (low/medium/high), 实时作用于配置 (agent 运行期读取)。"""
        effort = str(effort or "").strip().lower()
        if effort not in ("low", "medium", "high"):
            return {"ok": False, "error": f"未知档位: {effort}"}
        self._effort = effort
        cfg = self._cfg()
        if cfg is not None:
            try:
                cfg.data.setdefault("agent", {})["effort"] = effort
            except Exception:  # noqa: BLE001
                pass
        return {"ok": True, "effort": effort, **self.mode_effort()}

    def git_status(self) -> Dict[str, Any]:
        """工作区 git 状态: 当前分支 + 是否有未提交改动 (供前端展示分支 chip)。

        非 git 仓库 / git 缺失时优雅降级 (branch=None, dirty=False)。
        """
        try:
            br = subprocess.run(  # noqa: S603 - 固定参数
                ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=self.workspace,
                capture_output=True, text=True, timeout=10, errors="replace",
            )
            branch = (br.stdout or "").strip()
            if br.returncode != 0 or not branch:
                branch = None
            st = subprocess.run(  # noqa: S603
                ["git", "status", "--porcelain"], cwd=self.workspace,
                capture_output=True, text=True, timeout=10, errors="replace",
            )
            dirty = bool(st.stdout and st.stdout.strip())
            return {"branch": branch, "dirty": dirty, "repo": branch is not None}
        except FileNotFoundError:
            return {"branch": None, "dirty": False, "repo": False}
        except subprocess.TimeoutExpired:
            return {"branch": None, "dirty": False, "repo": False}
        except Exception:  # noqa: BLE001
            return {"branch": None, "dirty": False, "repo": False}

    def trust_status(self) -> Dict[str, Any]:
        """工作区信任状态 (对标 CLI 的 WorkspaceTrust / TUI prompt_trust)。"""
        try:
            from ..config.loader import home_dir
            from ..core.workspace_trust import WorkspaceTrust
            wt = WorkspaceTrust(home_dir())
            return wt.get_project_info(self.workspace)
        except Exception:  # noqa: BLE001
            return {"path": self.workspace, "trust_level": "unknown",
                    "needs_confirmation": True}

    def set_trust_level(self, level: str) -> Dict[str, Any]:
        """设置工作区信任级别并持久化。level ∈ trusted/limited/untrusted。"""
        level = str(level or "").strip().lower()
        if level not in ("trusted", "limited", "untrusted"):
            return {"ok": False, "error": f"未知信任级别: {level}"}
        try:
            from ..config.loader import home_dir
            from ..core.workspace_trust import WorkspaceTrust
            wt = WorkspaceTrust(home_dir())
            rec = wt.set_trust(
                self.workspace, level,
                project_name=Path(self.workspace).name if self.workspace else "",
            )
            # 同步到已存在的会话 agent ctx (若已构建)
            lvl = "trusted" if level == "trusted" else (
                "untrusted" if level == "untrusted" else "limited")
            with _SESSIONS_LOCK:
                for s in _SESSIONS.values():
                    a = s.get("agent")
                    if a is not None and getattr(a, "ctx", None) is not None:
                        try:
                            setattr(a.ctx, "workspace_trust_level", lvl)
                        except Exception:  # noqa: BLE001
                            pass
            return {"ok": True, "level": level, **self.trust_status()}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    def slash_commands(self) -> List[Dict[str, str]]:
        """斜杠命令清单 (名称 + 描述), 供前端命令面板发现/补全 (与 TUI 共用同一权威清单)。"""
        try:
            from ..cli.cmd_slash import list_slash_commands, slash_command_meta
        except Exception:  # noqa: BLE001
            return []
        meta = slash_command_meta()
        out = []
        for name in list_slash_commands():
            out.append({"name": name, "desc": meta.get(name, "")})
        return out

    # ---------------- 设置 (对标 TUI 的 /config /model /permissions) ----------------
    # 通用标量设置: 前端据此渲染表单, 写回走 /api/config/set。
    # type: enum(下拉) / int(数字) / float(小数) / bool(开关) / list(逗号分隔文本) / string(文本)
    # min/max 与 config/validate.py 的 _RULES 同口径 —— Web 端写入前就拦住越界值,
    # 而不是等 `tuan config validate` 才报错。
    # sec 即前端左侧导航分组, 需与 frontend.py 的 SET_CATS 保持一致。
    _SETTINGS_META: List[Dict[str, Any]] = [
        # ---- 运行 ----
        {"sec": "运行", "key": "mode.default", "label": "运行模式", "type": "enum",
         "enum": ["standard", "plan", "yolo"], "hint": "plan=只读规划 / yolo=放权 / standard=默认"},
        {"sec": "运行", "key": "agent.effort", "label": "推理投入", "type": "enum",
         "enum": ["low", "medium", "high", "xhigh", "max"], "hint": "low 快省 / max 最深究"},
        {"sec": "运行", "key": "tools.exposure", "label": "工具暴露档位", "type": "enum",
         "enum": ["minimal", "standard", "full"], "hint": "传给模型的工具清单大小"},
        {"sec": "运行", "key": "agent.max_iterations", "label": "最大迭代轮数", "type": "int",
         "min": 1, "max": 200},
        {"sec": "运行", "key": "agent.max_retries", "label": "失败重试次数", "type": "int",
         "min": 0, "max": 10},
        {"sec": "运行", "key": "agent.auto_memory", "label": "自动记忆", "type": "bool"},
        {"sec": "运行", "key": "agent.show_reasoning", "label": "显示思考过程", "type": "bool"},
        {"sec": "运行", "key": "agent.personality", "label": "人设", "type": "string",
         "hint": "留空=默认; 对应 /personality set"},
        {"sec": "运行", "key": "agent.subagent_isolation", "label": "子代理隔离方式", "type": "enum",
         "enum": ["process", "thread"], "hint": "process=进程级沙箱 (推荐) / thread=线程软隔离"},
        {"sec": "运行", "key": "agent.subagent_max_workers", "label": "子代理并发上限", "type": "int",
         "min": 1, "max": 16},
        {"sec": "运行", "key": "agent.subagent_timeout", "label": "子代理超时 (秒)", "type": "int",
         "min": 5, "max": 3600},
        # ---- 模型参数 (供应商/模型本身在「模型与供应商」页签) ----
        {"sec": "模型参数", "key": "model.temperature", "label": "温度 temperature", "type": "float",
         "min": 0.0, "max": 2.0, "hint": "0=确定性 / 2=最发散"},
        {"sec": "模型参数", "key": "model.max_tokens", "label": "最大输出 tokens", "type": "int",
         "min": 1, "max": 1000000},
        {"sec": "模型参数", "key": "model.context_window", "label": "上下文窗口", "type": "int",
         "min": 0, "max": 10000000, "hint": "0=按模型名自动推断"},
        {"sec": "模型参数", "key": "model.stream", "label": "流式输出", "type": "bool"},
        {"sec": "模型参数", "key": "model.prompt_cache", "label": "提示词缓存", "type": "bool"},
        {"sec": "模型参数", "key": "model.timeout", "label": "请求超时 (秒)", "type": "int",
         "min": 1, "max": 600},
        {"sec": "模型参数", "key": "model.max_retries", "label": "API 重试次数", "type": "int",
         "min": 0, "max": 10},
        # ---- 上下文 ----
        {"sec": "上下文", "key": "context.keep_recent", "label": "保留最近消息数", "type": "int",
         "min": 1, "max": 100},
        {"sec": "上下文", "key": "context.budget_tokens", "label": "上下文预算 (tokens)", "type": "int",
         "min": 1000, "max": 2000000},
        {"sec": "上下文", "key": "context.compact_trigger", "label": "触发压缩的用量", "type": "int",
         "min": 1000, "max": 2000000},
        {"sec": "上下文", "key": "context.compact_strategy", "label": "压缩策略", "type": "enum",
         "enum": ["smart", "none"]},
        {"sec": "上下文", "key": "context.pin_codebase", "label": "固定代码库地图", "type": "bool"},
        {"sec": "上下文", "key": "context.auto_index", "label": "自动索引工作区", "type": "bool"},
        {"sec": "上下文", "key": "context.index_max_files", "label": "索引文件数上限", "type": "int",
         "min": 1, "max": 20000},
        # ---- 权限 ----
        {"sec": "权限", "key": "permissions.network.allow_domains", "label": "网络域名白名单",
         "type": "list", "hint": "逗号分隔; 空=不限制"},
        {"sec": "权限", "key": "permissions.shell.deny_patterns", "label": "Shell 拒绝模式",
         "type": "list", "hint": "逗号分隔的正则"},
        {"sec": "权限", "key": "security.network.blocked_domains", "label": "网络黑名单域名",
         "type": "list", "hint": "逗号分隔"},
        {"sec": "权限", "key": "security.network.deny_remote_exec", "label": "禁止远程执行", "type": "bool"},
        {"sec": "权限", "key": "security.network.deny_data_exfil", "label": "禁止数据外泄", "type": "bool"},
        {"sec": "权限", "key": "mode.yolo_require_confirm", "label": "yolo 仍需确认的操作",
         "type": "list", "hint": "逗号分隔的工具名; 对应 /permissions"},
        # ---- 沙箱 ----
        {"sec": "沙箱", "key": "sandbox.enabled", "label": "启用沙箱", "type": "bool"},
        {"sec": "沙箱", "key": "sandbox.backend", "label": "沙箱后端", "type": "enum",
         "enum": ["auto", "local", "docker", "landlock", "seatbelt", "jobobject"],
         "hint": "auto=按平台自动选择; local=不隔离"},
        {"sec": "沙箱", "key": "sandbox.deny_unknown_shell", "label": "拒绝未知 shell", "type": "bool"},
        {"sec": "沙箱", "key": "sandbox.enforce_required", "label": "强制必需沙箱", "type": "bool"},
        # ---- 验证与自治 ----
        {"sec": "验证与自治", "key": "verify.enabled", "label": "启用编码验证闭环", "type": "bool",
         "hint": "对应 /verify"},
        {"sec": "验证与自治", "key": "verify.auto", "label": "自动验证", "type": "bool"},
        {"sec": "验证与自治", "key": "verify.max_heal_rounds", "label": "最大自修复轮数", "type": "int",
         "min": 0, "max": 20},
        {"sec": "验证与自治", "key": "reflector.enabled", "label": "启用反思器", "type": "bool"},
        {"sec": "验证与自治", "key": "reflector.max_auto_fix", "label": "反思自动修复上限", "type": "int",
         "min": 0, "max": 20},
        {"sec": "验证与自治", "key": "loop.enabled", "label": "启用 devloop", "type": "bool"},
        {"sec": "验证与自治", "key": "loop.auto_test", "label": "devloop 自动测试", "type": "bool"},
        {"sec": "验证与自治", "key": "loop.max_iterations", "label": "devloop 最大轮数", "type": "int",
         "min": 1, "max": 200},
        {"sec": "验证与自治", "key": "goal.enabled", "label": "启用目标分解", "type": "bool",
         "hint": "对应 /goal"},
        {"sec": "验证与自治", "key": "goal.max_auto_iterations", "label": "目标自动迭代上限", "type": "int",
         "min": 1, "max": 200},
        # ---- 记忆 ----
        {"sec": "记忆", "key": "memory.fts_enabled", "label": "全文检索", "type": "bool"},
        {"sec": "记忆", "key": "memory.auto_extract", "label": "自动提取记忆", "type": "bool"},
        {"sec": "记忆", "key": "memory.recall_limit", "label": "召回条数", "type": "int",
         "min": 1, "max": 50},
        {"sec": "记忆", "key": "memory.notes_enabled", "label": "启用笔记", "type": "bool"},
        # ---- 技能与提示 ----
        {"sec": "技能与提示", "key": "skills.enabled", "label": "启用技能", "type": "bool"},
        {"sec": "技能与提示", "key": "skills.auto_inject", "label": "自动注入技能", "type": "bool"},
        {"sec": "技能与提示", "key": "skills.inject_limit", "label": "注入技能数上限", "type": "int",
         "min": 1, "max": 20},
        {"sec": "技能与提示", "key": "prompt.tier", "label": "提示词档位", "type": "enum",
         "enum": ["auto", "compact", "full"]},
        {"sec": "技能与提示", "key": "prompt.cache_stable_prefix", "label": "缓存稳定前缀", "type": "bool"},
        {"sec": "技能与提示", "key": "prompt.project_doc_max_bytes", "label": "项目文档上限 (字节)",
         "type": "int", "min": 1024, "max": 1048576},
        # ---- 网络 ----
        {"sec": "网络", "key": "network.search_engines", "label": "搜索引擎", "type": "list",
         "hint": "逗号分隔, 如 duckduckgo, bing"},
        {"sec": "网络", "key": "network.search_max_results", "label": "搜索结果上限", "type": "int",
         "min": 1, "max": 1000},
        {"sec": "网络", "key": "network.fetch_max_chars", "label": "抓取字符上限", "type": "int",
         "min": 1000, "max": 500000},
        {"sec": "网络", "key": "network.fetch_timeout", "label": "抓取超时 (秒)", "type": "int",
         "min": 1, "max": 300},
        # ---- MCP ----
        {"sec": "MCP", "key": "mcp.enabled", "label": "启用 MCP", "type": "bool",
         "hint": "服务器清单见 ~/.tuan/config.yaml 的 mcp.servers"},
        {"sec": "MCP", "key": "mcp.timeout", "label": "MCP 超时 (秒)", "type": "float",
         "min": 1.0, "max": 600.0},
        # ---- 路由 ----
        {"sec": "智能路由", "key": "router.enabled", "label": "启用智能路由", "type": "bool",
         "hint": "对应 /route"},
        {"sec": "智能路由", "key": "router.auto_switch", "label": "自动切换模型", "type": "bool"},
        {"sec": "智能路由", "key": "router.plan_execute", "label": "规划/执行分离", "type": "bool"},
        {"sec": "智能路由", "key": "router.budget_limit", "label": "预算上限 (0=不限)", "type": "float",
         "min": 0.0, "max": 100000.0},
        {"sec": "智能路由", "key": "router.escalate_on_stuck", "label": "卡住时升级模型", "type": "bool"},
        {"sec": "智能路由", "key": "router.stuck_threshold", "label": "卡住判定轮数", "type": "int",
         "min": 1, "max": 50},
        # ---- 后台 ----
        {"sec": "后台任务", "key": "background.enabled", "label": "启用后台任务", "type": "bool"},
        {"sec": "后台任务", "key": "background.max_turns", "label": "后台最大轮数", "type": "int",
         "min": 1, "max": 1000},
        {"sec": "后台任务", "key": "cron.enabled", "label": "启用定时任务", "type": "bool"},
        {"sec": "后台任务", "key": "cron.check_interval", "label": "定时检查间隔 (秒)", "type": "int",
         "min": 5, "max": 86400},
        # ---- 外观 ----
        {"sec": "外观", "key": "ui.show_token_usage", "label": "显示 token 用量", "type": "bool"},
        {"sec": "外观", "key": "ui.show_cost_report", "label": "显示花费报告", "type": "bool"},
        {"sec": "外观", "key": "ui.show_reflect_summary", "label": "显示反思摘要", "type": "bool"},
        {"sec": "外观", "key": "ui.output_style", "label": "输出风格", "type": "enum",
         "enum": ["default", "compact", "verbose"], "hint": "TUI 的输出密度"},
    ]

    @staticmethod
    def _coerce_setting(stype: str, value: Any, options: Any = None) -> Any:
        if stype == "int":
            return int(value)
        if stype == "float":
            return float(value)
        if stype == "bool":
            if isinstance(value, str):
                return value.strip().lower() in ("1", "true", "yes", "on")
            return bool(value)
        if stype == "list":
            if isinstance(value, list):
                return [str(x).strip() for x in value if str(x).strip()]
            return [x.strip() for x in re.split(r"[,\n]", str(value)) if x.strip()]
        if stype == "enum":
            allowed = [str(o) for o in (options or [])]
            v = str(value)
            if allowed and v not in allowed:
                raise ValueError(f"可选值: {' / '.join(allowed)}")
            return v
        return value

    def config_snapshot(self) -> Dict[str, Any]:
        """当前设置快照 (值 + 元数据 + 供应商/模型清单 + 已配置的密钥情况)。"""
        cfg = self._cfg()
        values: Dict[str, Any] = {}
        for s in self._SETTINGS_META:
            values[s["key"]] = cfg.get(s["key"]) if cfg is not None else None
        providers: List[Dict[str, Any]] = []
        try:
            from ..config.loader import read_api_key
            from ..models.provider_catalog import ALL_PROVIDERS
            home = None
            try:
                from ..config.loader import home_dir
                home = home_dir()
            except Exception:  # noqa: BLE001
                home = None
            for p in ALL_PROVIDERS:
                ids = _provider_model_ids(p)
                if not ids:
                    try:
                        from ..models.provider_catalog import get_provider_models
                        ids = list(get_provider_models(p.name))
                    except Exception:  # noqa: BLE001
                        ids = []
                # 免费/付费标注 (仅用于前端在模型名旁打标签)
                tags: Dict[str, str] = {}
                for raw in list(p.recommended_models or []):
                    mid, sep, tag = str(raw).partition("|")
                    if sep and tag.strip():
                        tags[mid.strip()] = tag.strip()
                env = p.api_key_env
                key_set = bool(env and (os.environ.get(env) or read_api_key(env, home)))
                providers.append({
                    "name": p.name, "desc": p.desc, "tier": p.tier, "region": p.region,
                    "free_tier": p.free_tier, "category": p.category, "docs_url": p.docs_url,
                    "key_hint": p.key_hint, "api_key_env": env, "key_set": key_set,
                    "base_url": p.base_url, "models": ids[:80], "tags": tags,
                })
        except Exception:  # noqa: BLE001
            pass
        model = {}
        if cfg is not None:
            model = {"provider": cfg.get("model.provider"), "model": cfg.get("model.model"),
                     "base_url": cfg.get("model.base_url"), "api_key_env": cfg.get("model.api_key_env")}
        return {"ok": True, "values": values, "meta": list(self._SETTINGS_META),
                "providers": providers, "model": model,
                "workspace": self.workspace, "engine": self.engine_label}

    def apply_setting(self, key: str, value: Any) -> Dict[str, Any]:
        """写入单个设置 (持久化到用户层 config.yaml, 并作用于当前会话)。"""
        meta = next((s for s in self._SETTINGS_META if s["key"] == key), None)
        if meta is None:
            return {"ok": False, "error": f"该设置项不允许在 Web 端修改: {key}"}
        cfg = self._cfg()
        if cfg is None:
            return {"ok": False, "error": "配置不可用"}
        try:
            coerced = self._coerce_setting(meta["type"], value, meta.get("enum"))
        except (ValueError, TypeError) as exc:
            return {"ok": False, "error": f"值类型错误: {exc}"}
        # 范围校验 (与 config/validate.py 同口径): 越界值直接拒, 不落盘
        lo, hi = meta.get("min"), meta.get("max")
        if isinstance(coerced, (int, float)) and not isinstance(coerced, bool):
            if lo is not None and coerced < lo:
                return {"ok": False, "error": f"取值过小: 最小 {lo}"}
            if hi is not None and coerced > hi:
                return {"ok": False, "error": f"取值过大: 最大 {hi}"}
        try:
            cfg.set_user(key, coerced)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        # 副作用: 模式/推理投入需实时翻转到会话 agent
        if key == "mode.default":
            self.apply_mode(str(coerced))
        elif key == "agent.effort":
            self.apply_effort(str(coerced))
        return {"ok": True, "key": key, "value": coerced}

    def apply_model(self, provider: str, model: str, api_key: str = "") -> Dict[str, Any]:
        """切换供应商/模型 (对标 CLI cmd_model), 可选同时写入 API Key。"""
        cfg = self._cfg()
        if cfg is None:
            return {"ok": False, "error": "配置不可用"}
        provider = str(provider or "").strip()
        model = str(model or "").strip()
        if not provider or not model:
            return {"ok": False, "error": "供应商与模型不能为空"}
        try:
            from ..models.provider_catalog import get_provider
        except Exception:  # noqa: BLE001
            get_provider = None  # type: ignore
        preset = get_provider(provider) if get_provider else None
        if preset is None:
            return {"ok": False, "error": f"未知供应商: {provider}"}
        # 模型名必须在目录内 (剥掉 |free/|paid 标注后比对), 防止把拼错的
        # 模型名写进配置, 却要到运行期发请求时才报错。
        known = _provider_model_ids(preset)
        if known and model not in known:
            return {"ok": False, "error": f"{provider} 没有模型 {model}"}
        try:
            cfg.set_user("model.provider", provider)
            cfg.set_user("model.model", model)
            if preset.base_url:
                cfg.set_user("model.base_url", preset.base_url)
            if preset.api_key_env:
                cfg.set_user("model.api_key_env", preset.api_key_env)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        env = preset.api_key_env or cfg.get("model.api_key_env")
        key_note = ""
        if api_key and env:
            os.environ[env] = api_key
            try:
                from ..config.loader import persist_api_key
                persist_api_key(env, api_key)
                key_note = f"已保存密钥 {env} (本次会话 + 重启均生效)"
            except Exception as exc:  # noqa: BLE001
                key_note = f"密钥仅本次会话生效 ({exc})"
        # 模型是运行期按 config 解析的, 无需重建会话; 这里只把新端点回显给前端
        return {"ok": True, "model": {"provider": provider, "model": model,
                "base_url": cfg.get("model.base_url"), "api_key_env": env}, "note": key_note}

    def apply_apikey(self, env: str, key: str) -> Dict[str, Any]:
        """设置 (key 非空) 或清除 (key 空) 某个供应商的 API Key。"""
        env = (env or "").strip()
        if not env or "=" in env:
            return {"ok": False, "error": f"非法的环境变量名: {env!r}"}
        try:
            from ..config.loader import persist_api_key, remove_api_key
            if key:
                os.environ[env] = key
                persist_api_key(env, key)
                return {"ok": True, "env": env, "set": True}
            os.environ.pop(env, None)
            remove_api_key(env)
            return {"ok": True, "env": env, "set": False}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    # ---------------- 运行 ----------------
    def make_agent(self):
        if self._make_agent_fn is not None:
            return self._make_agent_fn()
        from ..app import create_agent

        # 注入审批回调: 危险工具在 Web 端会弹 allow/ask/deny 弹窗而非静默执行
        # exclude_tools: 面板上被关掉的工具 (热插拔)
        agent = create_agent(self.kernel, self.workspace, confirm=self._ask_approval,
                             exclude_tools=tuple(sorted(self._disabled_tools)))
        # 应用 Web 工作台内的模式/推理投入覆盖 (若有)
        me = self.mode_effort()
        try:
            if me["mode"] == "plan":
                agent.plan_mode = True
                agent.yolo = False
            elif me["mode"] == "yolo":
                agent.plan_mode = False
                agent.yolo = True
            else:
                agent.plan_mode = False
                agent.yolo = False
            if getattr(agent, "ctx", None) is not None:
                agent.ctx.plan_mode = agent.plan_mode
                agent.ctx.yolo = agent.yolo
            if me["effort"] in ("low", "medium", "high"):
                self._cfg().data.setdefault("agent", {})["effort"] = me["effort"]
        except Exception:  # noqa: BLE001
            pass
        return agent

    def set_agent_factory(self, fn) -> None:
        """注入 agent 工厂 (测试/外部装配用)。"""
        self._make_agent_fn = fn

    def cancel_current(self) -> None:
        ev = self._cancel
        if ev is not None:
            ev.set()
        # 挂起的审批一律按"拒绝"结算, 否则被取消的回合会一直等审批而挂住
        with _APPROVALS_LOCK:
            for rec in _APPROVALS.values():
                rec["result"] = False
                rec["event"].set()
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
        # 非回环绑定: 接口无鉴权, 必须在控制台显著告警 (与 CLI 闸门同逻辑)。
        if not is_loopback(self.host):
            self.insecure_binding = True
            sys.stderr.write(non_loopback_warning(self.host, self.port))
            sys.stderr.flush()
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
            # 冲刷防抖定时器: 否则最后 1 秒内的消息可能没落盘
            t = self._save_timer
            if t is not None:
                t.cancel()
            self.save_sessions()
            self._httpd.server_close()
