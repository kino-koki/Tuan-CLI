# -*- coding: utf-8 -*-
"""Web 工作台的 GitHub 登录会话存储 (WebAuthStore) + Cookie 编解码。

安全模型 (本地单机工具, 与 web_sessions.json 同一威胁边界):
  * 会话文件落盘到 ``<workspace>/.tuan/web_auth.json``, 只存当前用户的 token。
    这是**本机明文**文件 —— 与 web_sessions.json / web_settings.json 一致, 假定
    只有本机当前用户能读 (不做加密; 加密对本机单用户场景无实际增益)。
  * session id 高熵 (secrets.token_urlsafe(32)), 比较用 hmac.compare_digest 防时序。
  * 过期会话读时即删 (fail-closed)。
  * token 绝不打日志、绝不出现在任何 /api 返回体里。
"""
from __future__ import annotations

import hmac
import json
import logging
import secrets
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

log = logging.getLogger(__name__)

# 会话有效期 (秒): ~7 天。与 GitHub 设备流 token TTL 无关, 这里管的是本地 cookie 生命周期。
SESSION_TTL_SEC = 7 * 24 * 3600

COOKIE_NAME = "tuan_session"


class WebAuthStore:
    """session-id → 身份(+token) 的磁盘持久化字典 (线程安全, 原子写盘)。"""

    def __init__(self, auth_file: Path) -> None:
        self._auth_file = auth_file
        self._lock = threading.RLock()
        self._sessions: Dict[str, Dict[str, Any]] = {}
        self._load()

    # ---------------- 磁盘 ----------------
    def _load(self) -> None:
        try:
            if not self._auth_file.exists():
                return
            data = json.loads(self._auth_file.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                with self._lock:
                    self._sessions = {k: v for k, v in data.items()
                                      if isinstance(k, str) and isinstance(v, dict)}
        except Exception:  # noqa: BLE001 - 读失败按空会话处理, 不影响服务启动
            with self._lock:
                self._sessions = {}

    def _save(self) -> None:
        """原子写盘 (tmp + rename)；失败记 ERROR 日志 —— 静默丢盘会让
        用户以为已登录、重启后才发现会话丢失，必须留证据。"""
        try:
            self._auth_file.parent.mkdir(parents=True, exist_ok=True)
            with self._lock:
                snapshot = {sid: dict(rec) for sid, rec in self._sessions.items()}
            tmp = self._auth_file.with_suffix(".tmp")
            tmp.write_text(json.dumps(snapshot, ensure_ascii=False, indent=1),
                           encoding="utf-8")
            tmp.replace(self._auth_file)
        except Exception as exc:  # noqa: BLE001
            log.error("web_auth.json 写盘失败 (会话将在重启后丢失): %s", exc)

    # ---------------- 会话生命周期 ----------------
    def create_session(self, identity: Dict[str, Any], token: str) -> str:
        """新建会话, 返回随机 session-id。identity 至少含 login/id/avatar_url。"""
        sid = secrets.token_urlsafe(32)
        now = int(time.time())
        rec = {
            "login": str(identity.get("login") or ""),
            "id": identity.get("id") if isinstance(identity.get("id"), int) else 0,
            "name": str(identity.get("name") or ""),
            "avatar_url": str(identity.get("avatar_url") or ""),
            "created_at": now,
            "expires_at": now + SESSION_TTL_SEC,
            # 本地文件, 仅当前用户自己用 (发起 GitHub API 调用); 不打日志不外泄。
            "token": token,
        }
        with self._lock:
            self._sessions[sid] = rec
        self._save()
        return sid

    def verify_session(self, cookie_value: Optional[str]) -> Optional[Dict[str, Any]]:
        """校验 cookie 里的 session-id, 返回**不含 token** 的身份 dict, 无效/过期 → None。"""
        if not cookie_value:
            return None
        sid = cookie_value.strip()
        if not sid:
            return None
        with self._lock:
            rec = self._sessions.get(sid)
            if rec is None:
                return None
            if int(rec.get("expires_at") or 0) <= int(time.time()):
                # 过期: 读时即删, 防堆积。
                del self._sessions[sid]
                dirty = True
            else:
                dirty = False
        if dirty:
            self._save()
            return None
        # 返回体不含 token —— 上层只拿得到展示用的身份字段。
        return {
            "login": rec.get("login") or "",
            "id": rec.get("id") or 0,
            "name": rec.get("name") or "",
            "avatar_url": rec.get("avatar_url") or "",
        }

    def get_token(self, cookie_value: Optional[str]) -> Optional[str]:
        """取某会话的 GitHub token (供服务端发起 API 调用), 无效 → None。"""
        if not cookie_value:
            return None
        sid = cookie_value.strip()
        with self._lock:
            rec = self._sessions.get(sid)
            if rec is None or int(rec.get("expires_at") or 0) <= int(time.time()):
                return None
            return rec.get("token") or None

    def delete_session(self, cookie_value: Optional[str]) -> None:
        """删除会话 (登出)。"""
        if not cookie_value:
            return
        sid = cookie_value.strip()
        with self._lock:
            if sid in self._sessions:
                del self._sessions[sid]
                self._save()

    def delete_all(self) -> int:
        """清空全部会话 (返回删除条数)。"""
        with self._lock:
            n = len(self._sessions)
            self._sessions.clear()
        if n:
            self._save()
        return n


# ================================================================ Cookie 编解码

def parse_session_cookie(cookie_header: Optional[str]) -> Optional[str]:
    """从请求的 ``Cookie:`` 头里取出 tuan_session 的值 (无则 None)。

    手写解析而非 http.cookies: 只关心我们自己的一个键, 避免对畸形 header 抛异常。
    """
    if not cookie_header:
        return None
    for part in cookie_header.split(";"):
        if "=" not in part:
            continue
        name, _, value = part.partition("=")
        if name.strip() == COOKIE_NAME:
            return value.strip() or None
    return None


def build_set_cookie_header(session_id: str, secure: bool,
                            max_age: int = SESSION_TTL_SEC) -> str:
    """构造 ``Set-Cookie`` 响应头。

    HttpOnly (JS 读不到, 防 XSS 偷会话) + SameSite=Lax (防 CSRF) + Path=/;
    Secure 仅在 https 请求下加 (本地默认 http://127.0.0.1 不能加, 否则浏览器拒收)。
    """
    parts = [
        f"{COOKIE_NAME}={session_id}",
        "Path=/",
        "HttpOnly",
        "SameSite=Lax",
        f"Max-Age={max_age}",
    ]
    if secure:
        parts.append("Secure")
    return "; ".join(parts)


def build_clear_cookie_header(secure: bool) -> str:
    """构造登出时的 ``Set-Cookie`` (Max-Age=0 让浏览器立即删除)。"""
    parts = [f"{COOKIE_NAME}=", "Path=/", "HttpOnly", "SameSite=Lax", "Max-Age=0"]
    if secure:
        parts.append("Secure")
    return "; ".join(parts)


def cookie_matches(a: Optional[str], b: Optional[str]) -> bool:
    """恒定时间比较两个 session-id, 防时序侧信道 (hmac.compare_digest)。"""
    if not a or not b:
        return False
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


__all__ = [
    "WebAuthStore",
    "SESSION_TTL_SEC",
    "COOKIE_NAME",
    "parse_session_cookie",
    "build_set_cookie_header",
    "build_clear_cookie_header",
    "cookie_matches",
]
