"""网络连通性检测 (离线模式 C-5)。

供两处消费:
- ``tuan_cli.models.router`` 自动降级决策 (云端不通 -> 切本地模型);
- TUI 分片在状态栏渲染离线横幅 (调用 ``is_offline()`` 即可, 无需感知本模块细节)。

设计:
- 纯标准库 (urllib), 不引入 httpx/openai 依赖;
- 默认 3 秒超时判定离线 (契约 C-5.1);
- 进程内短期缓存 (默认 10s), 避免状态栏高频重 ping;
- 探测顺序: 当前配置的模型 base_url -> 公共兜底端点; 任一可达即视为在线。
"""

from __future__ import annotations

import os
import threading
import time
import urllib.error
import urllib.request
from typing import Dict, List, Optional

#: 默认探测超时 (秒), 契约 C-5.1 固定 3s
DEFAULT_TIMEOUT = 3.0

#: 进程内结果缓存 TTL (秒)。TUI 状态栏会高频轮询, 重 ping 必须节流。
_CACHE_TTL = 10.0

#: 公共兜底探测端点 (当前配置端点不可达时的最后判断依据)。
#: 选国内可达性高的地址, 避免「用户在国内、探测 google 被墙」造成误判离线。
_FALLBACK_URLS = (
    "https://www.baidu.com",
    "https://api.deepseek.com",
)

_lock = threading.Lock()
#: 缓存的检测结果 {"offline": bool, "checked_at": float, "via": str}
_cache: Dict[str, object] = {}


def _configured_base_url() -> Optional[str]:
    """从 ~/.tuan/config.yaml 读 model.base_url (不构建内核, 轻量)。

    读失败一律返回 None, 不影响兜底探测。
    """
    try:
        from ..config import home_dir

        cfg = home_dir() / "config.yaml"
        if not cfg.exists():
            return None
        from .. import _yaml as yaml

        data = yaml.safe_load(cfg.read_text(encoding="utf-8")) or {}
        model = data.get("model") or {}
        url = model.get("base_url")
        if isinstance(url, str) and url.startswith(("http://", "https://")):
            return url.rstrip("/")
    except Exception:  # noqa: BLE001 - 配置读取失败不阻断网络检测
        pass
    return None


def _probe(url: str, timeout: float) -> bool:
    """探测单个 URL 是否可达 (HEAD/GET 任意快速响应即视为在线)。"""
    try:
        req = urllib.request.Request(
            url,
            method="GET",
            headers={"User-Agent": "tuan-cli-network-check"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            # 只要拿到响应头就算通; 状态码不挑 (401/404 都证明网络可达)
            return resp.status < 500
    except urllib.error.HTTPError as exc:
        # HTTPError 也说明 TCP/TLS 已经打通 (只是业务状态码非 2xx)
        return exc.code < 500
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def probe_once(timeout: float = DEFAULT_TIMEOUT) -> Dict[str, object]:
    """执行一次真实探测 (绕过缓存), 返回结构化结果。

    返回::
        {"offline": bool, "checked_at": float, "via": str|None,
         "checked": [探测过的 URL 列表]}
    """
    urls: List[str] = []
    base = _configured_base_url()
    if base:
        urls.append(base)
    urls.extend(_FALLBACK_URLS)

    reach_via: Optional[str] = None
    for url in urls:
        if _probe(url, timeout):
            reach_via = url
            break

    result = {
        "offline": reach_via is None,
        "checked_at": time.time(),
        "via": reach_via,
        "checked": urls,
    }
    with _lock:
        _cache.clear()
        _cache.update(result)
    return result


def is_offline(timeout: float = DEFAULT_TIMEOUT, force: bool = False) -> bool:
    """当前是否处于离线状态。

    - 优先使用 10s 内的进程内缓存;
    - ``force=True`` 或缓存过期时重新探测;
    - TUI 状态栏/自动降级均应调用本函数, 不要自己裸 ping。
    """
    if os.environ.get("TUAN_OFFLINE") == "1":
        # 用户显式声明离线 (脚本/无网机房场景), 不做探测直接采信
        return True
    if not force:
        with _lock:
            cached_offline = _cache.get("offline")
            checked_at = _cache.get("checked_at", 0.0)
        if (
            isinstance(cached_offline, bool)
            and isinstance(checked_at, float)
            and time.time() - checked_at < _CACHE_TTL
        ):
            return cached_offline
    return bool(probe_once(timeout=timeout)["offline"])


def offline_status() -> Dict[str, object]:
    """带缓存的状态快照 (TUI 横幅渲染用)。

    返回与 :func:`probe_once` 同构的 dict; 无缓存时触发一次轻量探测。
    """
    with _lock:
        cached = dict(_cache)
    if cached:
        return cached
    return probe_once()


def reset_cache() -> None:
    """清空进程内缓存 (测试/网络恢复后强制重检用)。"""
    with _lock:
        _cache.clear()


def local_model_available() -> bool:
    """本机是否有可用的本地模型 (Ollama / llama.cpp)。

    供自动降级决策: 离线且有本地模型 -> 可切; 离线且无本地模型 -> 友好报错。
    """
    try:
        from ..models.offline import detect_local_models

        status = detect_local_models()
        if status.get("ollama", {}).get("available") and status["ollama"].get("models"):
            return True
        if status.get("llamacpp", {}).get("available") and status["llamacpp"].get("models"):
            return True
    except Exception:  # noqa: BLE001 - 探测失败按「无本地模型」处理
        pass
    return False
