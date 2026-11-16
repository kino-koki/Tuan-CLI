"""Web 工作台共享底座: 常量、锁、SSE 与工具函数 (原 web/server.py 的模块级部分)。

会话/审批/活动轮次等全局状态都在这里, 各 mixin 以 ``from ._common import ...``
共享同一个对象 (只做原地变更, 不重新绑定), 因此跨模块看到的是同一份状态。
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

import logging
log = logging.getLogger(__name__)

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

# T-2.6: Web UI 用户偏好 (任意键) 读写锁 —— ThreadingHTTPServer 每请求一线程, 防并发写盘交错。
_SETTINGS_LOCK = threading.RLock()

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
        log.debug("analyze_command(): 非致命异常已忽略(设计内降级, 不改控制流): %s", exc)
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
    except Exception as exc:  # noqa: BLE001
        log.debug("web_strings(): 非致命异常已忽略(设计内降级, 不改控制流): %s", exc)
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
