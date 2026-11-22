"""模型/供应商目录的本地数据层 —— 让 58 家供应商与模型清单可以在本地更新。

设计:
- 内置目录 (provider_catalog.ALL_PROVIDERS / model_lists.MODEL_LISTS) 是代码兜底;
- `tuan models update` 把内置最新清单合并写进用户数据目录的 models_catalog.json
  (TUAN_HOME/models_catalog.json, 默认 ~/.tuan/), 之后所有清单类命令
  优先读本地文件 —— 用户/第三方可以在本地 JSON 里增改供应商与模型, 无需改代码;
- 合并规则 (refresh): 内置为基线, 本地文件里不在内置中的条目 (用户自建)
  全部保留, 同名条目以本地为准; 升级包后跑一次 update 即可把内置新增补进来。

全程离线、无网络、无 API key 依赖, 纯本地文件操作。
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .model_lists import MODEL_LISTS
from .provider_catalog import ALL_PROVIDERS

# 本地目录文件名
CATALOG_FILENAME = "models_catalog.json"

# schema 版本: 数据结构不兼容时递增, 加载时校验
SCHEMA_VERSION = 1


def catalog_file(home: Optional[Path] = None) -> Path:
    """本地目录 JSON 路径。home 缺省时用 TUAN_HOME 或 ~/.tuan。"""
    base = home or _default_home()
    return base / CATALOG_FILENAME


def _default_home() -> Path:
    override = os.environ.get("TUAN_HOME")
    if override:
        return Path(override)
    return Path.home() / ".tuan"


# ---------------------------------------------------------------- 内置导出

def export_catalog() -> Dict[str, Any]:
    """把内置供应商目录 + 模型清单序列化为可落盘的 dict。"""
    providers = []
    for p in ALL_PROVIDERS:
        providers.append({
            "name": p.name,
            "base_url": p.base_url,
            "model": p.model,
            "api_key_env": p.api_key_env,
            "desc": p.desc,
            "tier": p.tier,
            "free_tier": p.free_tier,
            "region": p.region,
            "category": p.category,
            "recommended_models": p.recommended_models,
            "docs_url": p.docs_url,
            "key_hint": p.key_hint,
        })
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": "",  # 由写盘时填充
        "providers": providers,
        "model_lists": {k: list(v) for k, v in MODEL_LISTS.items()},
    }


# ---------------------------------------------------------------- 读写

def load_catalog(home: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    """读本地目录; 文件缺失 / schema 无效 / JSON 损坏时返回 None (调用方回退内置)。

    只读, 不修文件 —— 损坏时静默回退, 由 `tuan models update` 重建。
    """
    path = catalog_file(home)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("schema_version") != SCHEMA_VERSION:
        return None
    if not isinstance(data.get("providers"), list):
        return None
    return data


def write_catalog(data: Dict[str, Any], home: Optional[Path] = None) -> Path:
    """原子写本地目录 (tmp + rename), 返回写入路径。

    ``generated_at`` 只在调用方未提供时才盖章 —— 写盘原语不得篡改调用方
    显式构造的时间戳 (is_stale 依赖它判断目录新旧)。
    """
    path = catalog_file(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(data)
    if not payload.get("generated_at"):
        payload["generated_at"] = _now_iso()
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(tmp, path)
    return path


def _now_iso() -> str:
    import datetime
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


# ---------------------------------------------------------------- 合并

def merge_catalog(builtin: Dict[str, Any], local: Dict[str, Any]) -> Dict[str, Any]:
    """以内置为基线合并本地目录: 本地新增保留, 同名条目本地优先。

    - providers: 按 name 去重; 内置全部在内, 本地同名覆盖, 本地新增追加。
    - model_lists: 按 provider 键; 内置全部在内, 本地同键覆盖, 本地新键追加。
    """
    merged = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": "",
        "providers": [],
        "model_lists": {},
    }

    builtin_providers = {p["name"]: p for p in builtin.get("providers", [])}
    local_providers = {p["name"]: p for p in local.get("providers", []) if isinstance(p, dict)}
    # 内置全部 + 本地新增 (同名已由本地覆盖)
    seen: Dict[str, Any] = {}
    for p in builtin.get("providers", []):
        seen[p.get("name")] = p
    for name, p in local_providers.items():
        seen[name] = p
    merged["providers"] = list(seen.values())

    bl = builtin.get("model_lists") or {}
    ll = local.get("model_lists") or {}
    lists: Dict[str, List[str]] = {k: list(v) for k, v in bl.items()}
    for k, v in ll.items():
        if isinstance(v, list):
            lists[k] = list(v)
    merged["model_lists"] = lists
    return merged


# ---------------------------------------------------------------- 自定义供应商

# 自定义供应商的分类标签 (一等公民, 独立于内置 A-G 分区)
CUSTOM_PROVIDER_CATEGORY = "自定义供应商"
DEFAULT_CUSTOM_API_KEY_ENV = "CUSTOM_API_KEY"


def add_custom_provider(entry: Any, *, home: Optional[Path] = None) -> Dict[str, Any]:
    """把自定义供应商持久化进本地目录 (一等公民)。

    复用 ``ports.oauth.custom_registry.CustomRegistryProviderEntry`` (含 .id/.api/
    .env/.models); 也接受任意带 name/api 的简易对象。构造的 provider dict 带
    ``custom=True`` 标记 —— ``merge_catalog`` 保证本地新增保留、同名本地优先,
    后续 ``refresh_catalog`` 不会用内置基线冲掉它。返回写入的 provider dict。
    """
    local = load_catalog(home)
    if local is None:
        local = export_catalog()

    provider_id = str(getattr(entry, "id", None) or getattr(entry, "name", "") or "custom")
    base_url = str(getattr(entry, "api", "") or "")
    model_entries = getattr(entry, "models", None) or {}
    env_list = getattr(entry, "env", None) or []
    env_name = (env_list[0] if isinstance(env_list, list) and env_list and isinstance(env_list[0], str)
                else DEFAULT_CUSTOM_API_KEY_ENV)
    display_name = str(getattr(entry, "name", "") or provider_id)

    model_ids: List[str] = []
    for m in model_entries.values() if hasattr(model_entries, "values") else model_entries:
        mid = getattr(m, "id", m) if not isinstance(m, str) else m
        if isinstance(mid, str) and mid:
            model_ids.append(mid)
    default_model = model_ids[0] if model_ids else ""

    provider_dict = {
        "name": provider_id,
        "base_url": base_url,
        "model": default_model,
        "api_key_env": env_name,
        "desc": f"自定义供应商 {display_name} (api.json)",
        "tier": "cheap",
        "free_tier": False,
        "region": "global",
        "category": CUSTOM_PROVIDER_CATEGORY,
        "recommended_models": list(model_ids),
        "docs_url": "",
        "key_hint": "",
        "custom": True,
    }

    providers = [p for p in local.get("providers", []) if not (isinstance(p, dict) and p.get("name") == provider_id)]
    providers.append(provider_dict)
    local["providers"] = providers

    model_lists = local.setdefault("model_lists", {})
    model_lists[provider_id] = list(model_ids)

    write_catalog(local, home)
    return provider_dict


def refresh_catalog(home: Optional[Path] = None) -> Tuple[int, int]:
    """把内置最新清单合并进本地目录并写盘。返回 (供应商数, 模型数)。"""
    local = load_catalog(home)
    builtin = export_catalog()
    if local is None:
        merged = builtin
    else:
        merged = merge_catalog(builtin, local)
    write_catalog(merged, home)
    return catalog_summary(merged)


def catalog_summary(data: Dict[str, Any]) -> Tuple[int, int]:
    """返回 (供应商数, 模型数)。"""
    n_prov = len(data.get("providers") or [])
    n_models = sum(len(v) for v in (data.get("model_lists") or {}).values())
    return n_prov, n_models


def diff_catalog(home: Optional[Path] = None) -> Dict[str, Any]:
    """内置 vs 本地: 统计本地缺失/过期的条目 (仅报告, 不写盘)。"""
    local = load_catalog(home)
    builtin = export_catalog()
    if local is None:
        return {
            "local_exists": False,
            "missing_providers": len(builtin.get("providers") or []),
            "missing_models": sum(len(v) for v in (builtin.get("model_lists") or {}).values()),
        }
    merged = merge_catalog(builtin, local)
    n_b = catalog_summary(builtin)
    n_m = catalog_summary(merged)
    return {
        "local_exists": True,
        "missing_providers": max(0, n_m[0] - n_b[0]),
        "missing_models": max(0, n_m[1] - n_b[1]),
        "total_providers": n_m[0],
        "total_models": n_m[1],
    }


# ---------------------------------------------------------------- 后台

def refresh_in_background(home: Optional[Path] = None, on_done: Any = None) -> threading.Thread:
    """后台线程执行 refresh, 不阻塞调用方。返回线程句柄。"""
    t = threading.Thread(target=_run_refresh, args=(home, on_done), daemon=True)
    t.start()
    return t


def _run_refresh(home: Any, on_done: Any) -> None:
    try:
        n_p, n_m = refresh_catalog(home)
        if on_done is not None:
            on_done(n_p, n_m)
    except Exception as exc:  # noqa: BLE001 - 后台失败只回传, 不冒泡
        if on_done is not None:
            on_done(-1, -1, error=str(exc))
