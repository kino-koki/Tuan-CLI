"""会话持久化门面包 (C-4)。

对外契约:
- ``tuan_cli.session.store`` 提供 ``create_store / list_recent / remove_session /
  resolve_session / load_history`` 等纯函数接口;
- 底层委托既有 ``memory.sessions.SessionStore`` (JSONL append-only 事件流),
  本包只做「薄门面 + CLI 友好参数解析」, 不重复实现存储逻辑。
"""

from .store import (
    create_store,
    list_recent,
    remove_session,
    resolve_session,
    load_history,
    sessions_dir,
)

__all__ = [
    "create_store",
    "list_recent",
    "remove_session",
    "resolve_session",
    "load_history",
    "sessions_dir",
]
