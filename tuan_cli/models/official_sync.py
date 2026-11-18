"""联网同步各供应商官方模型清单 (本地能力, 仅官方渠道, 每周 1 次)。

设计:
- 只拉取各供应商官方的 ``/v1/models`` OpenAI 兼容端点 (官方渠道, 不抓第三方聚合)。
- 复用 ``ecosystem.registry._fetch_json(url, ttl_seconds)`` —— sha1 缓存键 + 过期
  降级到缓存, 天然满足「每周 1 次」: TTL 设 7 天, 未到期直接命中缓存不联网。
- 失败 (空/None) 跳过该供应商, 保留本地既有清单, 绝不覆盖为空。
- 结果合并写进 local_catalog 的 ``model_lists``, 保持旧 ``|free/|paid`` 标注。
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from . import local_catalog

WEEK_SECONDS = 7 * 86400
DEFAULT_TTL = WEEK_SECONDS


def _now_iso() -> str:
    """当前本地时间 ISO 字符串 (与 local_catalog 写盘格式一致)。"""
    return datetime.now().astimezone().isoformat(timespec="seconds")

# 各供应商官方模型清单端点 (OpenAI 兼容 GET /v1/models)。
# parse: 点路径 —— 首段 'models'/'data' 取列表, 各元素取其 'id' (纯 str 直接收)。
OFFICIAL_MODEL_ENDPOINTS: Dict[str, Dict[str, str]] = {
    "liquid": {"url": "https://api.liquid.ai/v1/models", "parse": "models[].id"},
    "sakana": {"url": "https://api.sakana.ai/v1/models", "parse": "data[].id"},
    "thinkingmachines": {"url": "https://api.tm.ink/v1/models", "parse": "data[].id"},
    "aionlabs": {"url": "https://api.aionlabs.ai/v1/models", "parse": "data[].id"},
    "xiaomi-mimo": {"url": "https://api.xiaomimimo.com/v1/models", "parse": "data[].id"},
}


def _parse_models(data: Any, spec: Dict[str, str]) -> List[str]:
    """按 spec["parse"] 的点路径归一化成模型 ID 列表。

    支持两种形式:
    - ``<list_key>[].id``  (如 ``models[].id`` / ``data[].id``): 取该 key 的列表,
      每个 dict 元素取其 ``id`` 字段 (纯 str 元素直接收)。
    - ``<list_key>[]``  (如 ``data[]``): 该 key 直接是纯字符串列表。
    无法解析返回空列表。
    """
    if not isinstance(data, dict):
        return []
    parse = spec.get("parse", "")
    if parse.endswith("[]"):
        list_key = parse[:-2]
        field: Optional[str] = None
    elif "[]." in parse:
        list_key, field = parse.split("[].", 1)
    else:
        return []

    arr = data.get(list_key)
    if not isinstance(arr, list):
        # 官方端点响应 schema 不一: 指定 key 缺失时尝试其他已知清单键
        # (如 data[].id 端点实际返回 {"models": [...]})。两者都缺失才视为空。
        for alt_key in ("models", "data"):
            if alt_key != list_key and isinstance(data.get(alt_key), list):
                arr = data[alt_key]
                break
    if not isinstance(arr, list):
        return []

    ids: List[str] = []
    for item in arr:
        if isinstance(item, str) and item:
            ids.append(item)
        elif field is not None and isinstance(item, dict):
            mid = item.get(field)
            if isinstance(mid, str) and mid:
                ids.append(mid)
    return ids


def _parse_ts(value: Any) -> Optional[float]:
    """把 local_catalog.generated_at (ISO 字符串或已解析) 归一成 epoch 秒; 失败返回 None。"""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except (ValueError, TypeError):
            return None
    return None


def is_stale(*, home: Any = None, max_age: float = DEFAULT_TTL) -> bool:
    """距上次联网同步是否已超过 max_age (默认 7 天)。

    读 local_catalog 的 ``last_online_sync`` 字段 (由 ``sync_models_online`` 写入);
    无该字段则回退 ``generated_at``。无目录/无法解析视为过期。
    ``max_age<=0`` 恒 True (强制)。
    """
    if max_age <= 0:
        return True
    cat = local_catalog.load_catalog(home)
    if not cat:
        return True
    ts = _parse_ts(cat.get("last_online_sync"))
    if ts is None:
        ts = _parse_ts(cat.get("generated_at"))
    if ts is None:
        return True
    return (time.time() - ts) > max_age


def _merge_models(existing: Optional[List[str]], new_ids: List[str]) -> List[str]:
    """新清单与旧清单合并: 新模型优先, 旧条目保留其 |free/|paid 标注。"""
    label_map: Dict[str, str] = {}
    if existing:
        for item in existing:
            if "|" in item:
                mid, label = item.rsplit("|", 1)
                label_map[mid] = label
    out: List[str] = []
    seen: set = set()
    for mid in new_ids:
        if mid in seen:
            continue
        seen.add(mid)
        label = label_map.get(mid, "paid")
        out.append(f"{mid}|{label}")
    # 旧清单里存在但新清单已消失的模型保留 (避免误删, 官方偶尔临时下架)
    if existing:
        for item in existing:
            mid = item.split("|")[0]
            if mid not in seen:
                out.append(item)
    return out


def sync_models_online(*, home: Any = None, ttl_seconds: float = DEFAULT_TTL,
                       force: bool = False) -> Dict[str, Any]:
    """拉取各官方端点并合并进本地目录。返回 {provider: (ok, n, error)}。

    ``force=True`` 忽略 TTL 缓存 (用极短 TTL 强制联网)。任一供应商失败则跳过,
    保留既有清单, 不影响其他供应商。
    """
    from ..ecosystem import registry

    effective_ttl = 1 if force else ttl_seconds
    results: Dict[str, Dict[str, Any]] = {}
    changed = 0

    for provider, spec in OFFICIAL_MODEL_ENDPOINTS.items():
        url = spec["url"]
        try:
            data = registry._fetch_json(url, ttl_seconds=int(effective_ttl))
        except Exception as exc:  # noqa: BLE001
            results[provider] = {"ok": False, "count": 0, "error": f"请求失败: {exc}"}
            continue
        if not isinstance(data, dict):
            results[provider] = {"ok": False, "count": 0, "error": "响应非对象"}
            continue
        ids = _parse_models(data, spec)
        if not ids:
            results[provider] = {"ok": False, "count": 0, "error": "解析为空, 保留既有清单"}
            continue

        local = local_catalog.load_catalog(home)
        if local is None:
            local = local_catalog.export_catalog()
        existing = (local.get("model_lists") or {}).get(provider)
        merged = _merge_models(existing if isinstance(existing, list) else None, ids)
        local.setdefault("model_lists", {})[provider] = merged
        local["last_online_sync"] = _now_iso()
        local_catalog.write_catalog(local, home)
        changed += 1
        results[provider] = {"ok": True, "count": len(ids), "error": ""}

    results["_summary"] = {
        "attempted": len(OFFICIAL_MODEL_ENDPOINTS),
        "ok": sum(1 for r in results.values() if r.get("ok")),
        "changed": changed,
        "ts": time.time(),
    }
    return results
