"""模型响应缓存 (C-5.5) —— 相同 prompt 命中后直接返回, 不重复打模型。

用途:
- 离线/弱网场景下, 对重复问题直接命中缓存秒回 (<100ms 目标);
- 在线场景下也能省重复调用费用 (用户反复问同一个问题)。

存储:
- 落在 ``~/.tuan/cache/responses.json``, 结构为 {key: {"value": ..., "ts": ...}};
- TTL 默认 1 小时 (契约 C-5.5);
- 进程内锁保证并发 append 安全; 文件损坏自动清空重建, 绝不阻断主流程。
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

#: 默认缓存有效期 (秒) —— 契约 C-5.5 固定 1 小时
DEFAULT_TTL = 3600.0


class ResponseCache:
    """按 (provider, model, 规范化 prompt) 缓存模型最终文本响应。"""

    def __init__(self, path: Optional[Path] = None, ttl: float = DEFAULT_TTL) -> None:
        self.ttl = ttl
        if path is None:
            try:
                from ..config import home_dir

                path = home_dir() / "cache" / "responses.json"
            except Exception:  # noqa: BLE001 - 兜底用临时目录
                path = Path.home() / ".tuan" / "cache" / "responses.json"
        self.path = Path(path)
        self._lock = threading.Lock()
        self._mem: Dict[str, Dict[str, Any]] = {}
        self._loaded = False

    # ------------------------------------------------------------ 内部 IO
    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        try:
            if self.path.exists():
                data = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    self._mem = data
        except Exception:  # noqa: BLE001 - 损坏缓存直接重建
            self._mem = {}

    def _flush(self) -> None:
        """把内存缓存写回磁盘 (失败静默: 内存命中仍可用)。"""
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._mem, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.path)
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------ 键生成
    @staticmethod
    def make_key(provider: str, model: str, prompt: str) -> str:
        """生成缓存键: provider + model + prompt 的规范化哈希。"""
        norm = f"{provider}|{model}|{prompt.strip()}"
        return hashlib.sha1(norm.encode("utf-8")).hexdigest()

    # ------------------------------------------------------------ 读写
    def get(self, provider: str, model: str, prompt: str) -> Optional[str]:
        """命中返回缓存的文本响应; 未命中/过期返回 None。"""
        key = self.make_key(provider, model, prompt)
        with self._lock:
            self._ensure_loaded()
            entry = self._mem.get(key)
            if not entry:
                return None
            ts = float(entry.get("ts", 0.0))
            if time.time() - ts > self.ttl:
                # 过期: 惰性删除
                self._mem.pop(key, None)
                self._flush()
                return None
            value = entry.get("value")
            return value if isinstance(value, str) else None

    def set(self, provider: str, model: str, prompt: str, response: str) -> None:
        """写入一条缓存 (线程安全, 落盘失败不影响内存)。"""
        key = self.make_key(provider, model, prompt)
        with self._lock:
            self._ensure_loaded()
            self._mem[key] = {"value": response, "ts": time.time()}
            self._flush()

    def clear(self) -> int:
        """清空全部缓存, 返回清除条数。"""
        with self._lock:
            self._ensure_loaded()
            n = len(self._mem)
            self._mem.clear()
            self._flush()
            return n


#: 进程级单例 (router / agent 直接取用, 无需到处传参)
_singleton: Optional[ResponseCache] = None
_singleton_lock = threading.Lock()


def get_cache() -> ResponseCache:
    """获取全局响应缓存单例。"""
    global _singleton
    if _singleton is None:
        with _singleton_lock:
            if _singleton is None:
                _singleton = ResponseCache()
    return _singleton
