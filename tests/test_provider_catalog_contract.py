"""Provider 目录契约测试 —— 内置供应商预设的结构完整性。

契约面 (见 docs/ROADMAP.md 阶段一):
- 必填字段非空: name / base_url / model / api_key_env / desc
- api_key_env 符合环境变量命名规范 (大写下划线)
- tier ∈ {free, cheap, standard}; region ∈ {cn, global}
- free_tier=True 的预设必须标 tier="free" (语义一致)
- 有 recommended_models 时, model 必须是清单第一项 (含 |free/|paid 标注时的 ID 部分)
- base_url 必须 http(s); 本地部署预设应指向 localhost
- 索引一致: ALL_PROVIDER_NAMES / PROVIDER_BY_NAME / FREE_TIER_NAMES 与 ALL_PROVIDERS 对齐

回归价值: 目录漂移 (缺字段/重复/命名乱/档位矛盾) 是模型无关工具的头号维护问题,
这组断言让「加一个供应商」成为有契约的动作。
"""

import re

import pytest

from tuan_cli.models.provider_catalog import (
    ALL_PROVIDER_NAMES,
    ALL_PROVIDERS,
    FREE_TIER_NAMES,
    PROVIDER_BY_NAME,
    PROVIDER_CATEGORIES,
)

ENV_NAME_RE = re.compile(r"[A-Z][A-Z0-9_]{2,}")
LOCALHOST_HINTS = ("localhost", "127.0.0.1", "0.0.0.0", "0.0.0.0:0")


def test_catalog_nonempty_and_deduped():
    """目录非空, 且按 name 去重后无重复 (去重逻辑保留首现)。"""
    assert len(ALL_PROVIDERS) >= 50, "内置供应商目录不应低于 50 条"
    names = [p.name for p in ALL_PROVIDERS]
    assert len(names) == len(set(names)), "存在重复的 provider name"


def test_required_fields_nonempty():
    """name/base_url/model/api_key_env/desc 五个必填字段全部非空。"""
    for p in ALL_PROVIDERS:
        for field in ("name", "base_url", "model", "api_key_env", "desc"):
            assert getattr(p, field), f"{p.name} 缺失必填字段 {field}"


def test_api_key_env_naming():
    """api_key_env 必须是规范的环境变量名 (大写下划线, 至少 3 字符)。"""
    for p in ALL_PROVIDERS:
        assert ENV_NAME_RE.fullmatch(p.api_key_env), \
            f"{p.name} 的 api_key_env 不规范: {p.api_key_env!r}"


def test_tier_and_region_enum():
    """tier/region 必须是枚举值; tier_rank 与 TIER_ORDER 对齐。"""
    from tuan_cli.models.provider_catalog import TIER_ORDER
    for p in ALL_PROVIDERS:
        assert p.tier in TIER_ORDER, f"{p.name} tier 非法: {p.tier!r}"
        assert p.region in ("cn", "global", ""), f"{p.name} region 非法: {p.region!r}"
        assert p.tier_rank == TIER_ORDER[p.tier]


def test_free_tier_consistency():
    """free_tier=True 表示注册即用、无需绑卡 —— 必须同时标 tier=free。"""
    for p in ALL_PROVIDERS:
        if p.free_tier:
            assert p.tier == "free", f"{p.name} free_tier=True 但 tier={p.tier!r}"
    # FREE_TIER_NAMES 必须与 free_tier 标志完全一致
    assert FREE_TIER_NAMES == frozenset(p.name for p in ALL_PROVIDERS if p.free_tier)


def test_default_model_matches_recommended_list():
    """有推荐模型清单时, 默认 model 必须是清单第一项 (|free/|paid 标注取 ID 部分)。"""
    for p in ALL_PROVIDERS:
        if p.recommended_models:
            first_id = p.recommended_models[0].split("|")[0]
            assert p.model == first_id, \
                f"{p.name} 默认模型 {p.model!r} != 清单首项 {first_id!r}"


def test_base_url_http_and_localhost_for_local():
    """base_url 必须 http(s); 本地部署预设应指向本机端点。"""
    for p in ALL_PROVIDERS:
        assert p.base_url.startswith(("http://", "https://")), \
            f"{p.name} base_url 非 http(s): {p.base_url!r}"
        if p.category == "本地部署":
            assert any(h in p.base_url for h in LOCALHOST_HINTS), \
                f"本地部署 {p.name} base_url 未指向本机: {p.base_url!r}"


def test_indexes_consistent():
    """名称/索引集合与 ALL_PROVIDERS 对齐 (重复或漏建会在这里炸)。"""
    assert ALL_PROVIDER_NAMES == [p.name for p in ALL_PROVIDERS]
    assert set(PROVIDER_BY_NAME.keys()) == set(ALL_PROVIDER_NAMES)
    for p in ALL_PROVIDERS:
        assert PROVIDER_BY_NAME[p.name] is p, f"{p.name} 索引未指向同一预设对象"


def test_categories_well_formed():
    """分类汇总与预设实际分类一致; 空分类落入「其他」。"""
    rebuilt: dict[str, list] = {}
    for p in ALL_PROVIDERS:
        rebuilt.setdefault(p.category or "其他", []).append(p.name)
    assert set(PROVIDER_CATEGORIES.keys()) == set(rebuilt.keys())
    for cat, presets in PROVIDER_CATEGORIES.items():
        assert [x.name for x in presets] == rebuilt[cat], f"分类 {cat} 成员不一致"


def test_known_core_providers_present():
    """最常被引用的核心供应商必须存在 (防目录误删)。"""
    for name in ("deepseek", "qwen", "zhipu", "moonshot", "openai", "anthropic",
                 "ollama", "llamacpp"):
        assert name in ALL_PROVIDER_NAMES, f"核心供应商 {name} 缺失"
