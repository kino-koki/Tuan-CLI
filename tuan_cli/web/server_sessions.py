"""WebServer 的会话 / 设置持久化 mixin (磁盘 JSON, 重启不丢)。"""

from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
import json
import threading

from ._common import (
    _SESSIONS,
    _SESSIONS_LOCK,
    _SETTINGS_LOCK,
    _serializable,
)

import logging
log = logging.getLogger(__name__)


class ServerSessionsMixin:
    # ---- 跨 mixin 共享实例状态 (纯声明; 由 WebServer.__init__ 初始化) ----
    _save_timer: Optional[threading.Timer]
    _session_file: Path
    _settings_file: Path

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
        except Exception as exc:  # noqa: BLE001
            log.debug("ServerSessionsMixin.load_sessions(): 非致命异常已忽略(设计内降级, 不改控制流): %s", exc)
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
        except Exception as exc:  # noqa: BLE001
            log.warning("ServerSessionsMixin.save_sessions(): 非致命异常已忽略(设计内降级, 不改控制流): %s", exc)
            pass


    # ---------------- Web UI 设置持久化 (T-2.6) ----------------
    def load_settings(self) -> None:
        """启动时从磁盘加载 Web UI 用户偏好; 读失败按空设置处理, 不影响服务启动。"""
        try:
            if not self._settings_file.exists():
                return
            data = json.loads(self._settings_file.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                self._settings = data
        except Exception:  # noqa: BLE001
            self._settings = {}


    def save_settings(self) -> None:
        """把 Web UI 用户偏好原子写盘 (<workspace>/.tuan/web_settings.json)。"""
        try:
            self._settings_file.parent.mkdir(parents=True, exist_ok=True)
            with _SETTINGS_LOCK:
                data = dict(self._settings)
            tmp = self._settings_file.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
            tmp.replace(self._settings_file)
        except Exception as exc:  # noqa: BLE001
            log.warning("ServerSessionsMixin.save_settings(): 非致命异常已忽略(设计内降级, 不改控制流): %s", exc)
            pass


    def settings_snapshot(self) -> Dict[str, Any]:
        """当前 Web UI 用户偏好快照 (/api/settings GET 返回体)。"""
        with _SETTINGS_LOCK:
            return dict(self._settings)


    def apply_settings(self, values: Dict[str, Any]) -> None:
        """合并写入 Web UI 用户偏好: 任意键均接受并存储, 随后落盘持久化。"""
        with _SETTINGS_LOCK:
            self._settings.update(values)
        self.save_settings()


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
