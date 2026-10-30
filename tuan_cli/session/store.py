"""会话持久化门面 (C-4.1) —— ~/.tuan/sessions/<id>.jsonl。

底层存储复用 ``memory.sessions.SessionStore`` (append-only JSONL 事件流,
已带并发锁 / 恢复 / 导出 / 分叉能力); 本模块只暴露 CLI 契约要求的门面函数,
避免在 cmd_sessions.py / parser 里重复实现「按 id 找文件 / 删文件 / 读历史」。

会话 ID 形如 ``20261025-143012-ab12cd`` (时间戳 + 短哈希), 天然按时间排序。
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Dict, List, Optional

from ..config import home_dir
from ..memory.sessions import SessionStore


def sessions_dir() -> Path:
    """会话目录 (~/.tuan/sessions), 不存在时创建。"""
    d = home_dir() / "sessions"
    d.mkdir(parents=True, exist_ok=True)
    return d


def create_store(meta: Optional[Dict[str, object]] = None) -> SessionStore:
    """开启一个新会话存储 (新 JSONL 文件)。

    meta 非空时在首行写 session.meta (供标题/后台徽标识别)。
    """
    store = SessionStore(home_dir())
    if meta:
        store.rotate(meta=dict(meta))
    return store


def list_recent(limit: int = 20) -> List[Path]:
    """列出最近 N 个会话文件 (按修改时间倒序)。"""
    d = sessions_dir()
    files = [p for p in d.glob("*.jsonl")]
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return files[:limit]


def resolve_session(target: str) -> Optional[Path]:
    """按目标解析会话文件:

    - "latest" / "" -> 最近一个;
    - 纯数字 -> 按列表序号 (1 起);
    - 其它 -> 会话 ID 前缀匹配 (含 .jsonl 后缀容错)。
    找不到返回 None。
    """
    if target in ("latest", "last", ""):
        recent = list_recent(1)
        return recent[0] if recent else None

    files = list_recent(200)
    if target.isdigit() and 1 <= int(target) <= len(files):
        return files[int(target) - 1]

    stem = target[:-6] if target.endswith(".jsonl") else target
    for p in files:
        if p.stem == stem or p.stem.startswith(stem):
            return p
    return None


def remove_session(target: str, *, all_sessions: bool = False,
                   yes: bool = False) -> int:
    """删除会话。返回删除条数。

    - all_sessions=True: 清空整个会话目录;
    - 否则按 resolve_session 解析目标删除单个。
    """
    if all_sessions:
        files = list_recent(10 ** 9)
        for p in files:
            try:
                p.unlink()
            except OSError:
                pass
        return len(files)

    path = resolve_session(target)
    if path is None:
        return 0
    try:
        path.unlink()
        return 1
    except OSError:
        return 0


def load_history(path: Path) -> List[Dict[str, object]]:
    """从会话文件重建消息历史 (user/assistant 列表, 不含 system)。"""
    return SessionStore.load_messages(path)


def session_title(path: Path) -> str:
    """取会话可读标题 (meta.task 或首条 user 消息)。"""
    return SessionStore.peek_title(path) or "(无标题)"


def session_age_str(path: Path) -> str:
    """相对时间展示 (刚刚 / N 分钟前 / N 小时前 / 绝对时间)。"""
    delta = time.time() - path.stat().st_mtime
    if delta < 60:
        return "刚刚"
    if delta < 3600:
        return f"{int(delta // 60)} 分钟前"
    if delta < 86400:
        return f"{int(delta // 3600)} 小时前"
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(path.stat().st_mtime))
