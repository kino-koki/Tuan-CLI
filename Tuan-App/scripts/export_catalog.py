"""把 tuan_cli 内置供应商目录与全量模型清单导出为前端静态 JSON。"""
import json
import sys
from pathlib import Path

# 基于脚本自身位置解析，避免写死盘符/绝对路径：
#   scripts/ -> Tuan-App/ -> Tuan-CLI/（仓库根）
# sys.path 需指向仓库根，这样 `import tuan_cli` 才能解析到 <ROOT>/tuan_cli/。
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tuan_cli.models.provider_catalog import ALL_PROVIDERS  # noqa: E402
from tuan_cli.models.model_lists import MODEL_LISTS  # noqa: E402


def parse_models(raw):
    out = []
    for item in raw or []:
        parts = str(item).split("|")
        mid = parts[0].strip()
        if not mid:
            continue
        tag = parts[1].strip().lower() if len(parts) > 1 else "paid"
        out.append({"id": mid, "free": tag == "free"})
    return out


out = []
for p in ALL_PROVIDERS:
    raw = MODEL_LISTS.get(p.name) or p.recommended_models
    models = parse_models(raw)
    out.append({
        "name": p.name,
        "baseUrl": p.base_url,
        "defaultModel": p.model,
        "apiKeyEnv": p.api_key_env,
        "desc": p.desc,
        "tier": p.tier,
        "freeTier": p.free_tier,
        "region": p.region,
        "category": p.category,
        "models": models,
        "docsUrl": p.docs_url,
        "keyHint": p.key_hint,
        "format": "anthropic" if p.name == "anthropic" else "openai",
    })

target = Path(__file__).resolve().parents[1] / "public" / "data" / "providers.json"
target.parent.mkdir(parents=True, exist_ok=True)
target.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
total = sum(len(x["models"]) for x in out)
print(f"wrote {len(out)} providers, {total} models -> {target}")
