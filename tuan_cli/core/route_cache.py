"""路由决策 memoization (内存级, 进程内 LRU)。

职责:
- 对同一 ``task_hash`` (任务文本哈希) 的重复路由请求直接命中缓存,
  避免在重试 / 子代理 / 多轮同任务场景下反复跑 :meth:`ModelRouter.decide`
  (含难度分类 + 预设查找 + 离线降级探测) 的开销。
- 仅做内存缓存, 无持久化; 进程退出即失效, 与 ResponseCache (落盘) 解耦。

设计约束:
- 缓存键是任务文本的 sha1, 不含 provider/model 当前状态 → 调用方需确认上下文
  未变 (典型场景: 同一 Agent 实例内重试 / 子代理继承任务文本)。
- 显式 ``None`` 决策同样被缓存 (调用方拿到 None 后仍走真路由)。
- LRU 上限 :data:`DEFAULT_MAXSIZE`, 与单 Agent 会话常见任务轮数同数量级。

用法::

    from tuan_cli.core.route_cache import (
        cached_route_lookup, cached_route_store, compute_task_hash,
    )

    h = compute_task_hash(task)
    decision = cached_route_lookup(h)
    if decision is None and not cached_route_contains(h):
        decision = router.decide(task, ...)
        cached_route_store(h, decision)
"""

from __future__ import annotations

import hashlib
import threading
from collections import OrderedDict
from typing import Any, Dict, Optional


#: 默认缓存槽位; 与单会话常见任务轮数同数量级
DEFAULT_MAXSIZE = 128


class _RouteCache:
    """线程安全的进程内 LRU, 允许缓存 ``None`` 值。"""

    def __init__(self, maxsize: int = DEFAULT_MAXSIZE) -> None:
        self._maxsize = maxsize
        self._data: "OrderedDict[str, Optional[Dict[str, Any]]]" = OrderedDict()
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0

    def get(self, key: str) -> "tuple[bool, Optional[Dict[str, Any]]]":
        """返回 ``(hit, decision)``。``hit`` 为 True 时 decision 可能为 None (显式缓存)。"""
        with self._lock:
            if key in self._data:
                self._data.move_to_end(key)
                self.hits += 1
                return True, self._data[key]
            self.misses += 1
            return False, None

    def put(self, key: str, decision: Optional[Dict[str, Any]]) -> None:
        """写入决策 (None 表示「已知无切换」, 也参与缓存)。"""
        with self._lock:
            self._data[key] = decision
            self._data.move_to_end(key)
            while len(self._data) > self._maxsize:
                self._data.popitem(last=False)

    def contains(self, key: str) -> bool:
        with self._lock:
            return key in self._data

    def invalidate(self, key: str) -> None:
        with self._lock:
            self._data.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()
            self.hits = 0
            self.misses = 0

    def info(self) -> Dict[str, int]:
        with self._lock:
            return {
                "size": len(self._data),
                "maxsize": self._maxsize,
                "hits": self.hits,
                "misses": self.misses,
            }


_GLOBAL_CACHE = _RouteCache()


def compute_task_hash(task: str) -> str:
    """计算任务文本的稳定哈希 (sha1, 用作缓存键)。

    规范化: 折叠连续空白 + strip, 让仅空白差异的等价措辞命中同一槽。
    """
    normalized = " ".join((task or "").split())
    return hashlib.sha1(
        normalized.encode("utf-8"), usedforsecurity=False
    ).hexdigest()


def cached_route_lookup(task_hash: str) -> Optional[Dict[str, Any]]:
    """按 task_hash 查缓存的路由决策。

    返回:
        命中时返回缓存的决策字典 (或显式缓存的 ``None``, 表示「已判定不切换」);
        未命中返回 ``None`` (调用方应跑真路由并回填)。要区分「显式缓存的 None」
        与「未命中」, 用 :func:`cached_route_contains`。
    """
    _hit, decision = _GLOBAL_CACHE.get(task_hash)
    return decision


def cached_route_contains(task_hash: str) -> bool:
    """判断 task_hash 是否已在缓存 (区分「显式 None」与「真未命中」)。"""
    return _GLOBAL_CACHE.contains(task_hash)


def cached_route_store(task_hash: str, decision: Optional[Dict[str, Any]]) -> None:
    """写入/更新路由决策缓存。decision 为 None 时缓存「已知无切换」。"""
    _GLOBAL_CACHE.put(task_hash, decision)


def cached_route_invalidate(task_hash: str) -> None:
    """显式失效一条缓存 (上下文已变化, 旧决策不可复用)。"""
    _GLOBAL_CACHE.invalidate(task_hash)


def cached_route_clear() -> None:
    """清空全部路由决策缓存 (测试用 / 全局上下文失效)。"""
    _GLOBAL_CACHE.clear()


def cache_info() -> Dict[str, int]:
    """返回命中/未命中/容量统计 (调试用)。"""
    return _GLOBAL_CACHE.info()
