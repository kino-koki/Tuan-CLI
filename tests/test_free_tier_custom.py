"""免费层扩充 + setup/models 自定义入口 回归测试 (离线)。

验证:
- 真·免费 (不绑卡) 供应商的档位标注与数量下限 (>= 10 家);
- Z.AI 已移出免费层 —— 它与 BigModel/zhipu 同属智谱一家, 不该占两个名额;
- router 的零成本档位能估算出"免费";
- tuan setup 的"自定义 (OpenAI 兼容端点)"与"只看免费层"入口。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tuan_cli.models.provider_catalog import (
    ALL_PROVIDERS, PROVIDER_CATEGORIES, free_providers, get_provider,
    get_provider_models,
)
from tuan_cli.models.router import estimate_cost
from tuan_cli.cli.cmd_setup import _pick_setup_provider


def test_free_tier_has_at_least_ten_providers():
    """真·免费 (不花钱、不绑卡即可跑通) 的供应商应 >= 10 家。"""
    free = free_providers()
    assert len(free) >= 10, f"免费层仅 {len(free)} 家: {[p.name for p in free]}"
    for p in free:
        assert p.free_tier is True
        assert p.tier == "free"
        assert p.base_url


def test_zai_removed_from_free_tier():
    """Z.AI 是智谱国际站 (与 BigModel/zhipu 同一厂商), 不应再列为免费层。"""
    zai = get_provider("zai")
    assert zai is not None
    assert zai.free_tier is False
    assert zai.tier == "cheap"
    assert zai.category != "免费层"
    free_names = {p.name for p in PROVIDER_CATEGORIES.get("免费层", [])}
    assert "zai" not in free_names


def test_zhipu_is_the_china_free_one():
    """国内免费档由 zhipu (BigModel) 承担, 而非其国际站 zai。"""
    zhipu = get_provider("zhipu")
    assert zhipu is not None
    assert zhipu.free_tier is True and zhipu.tier == "free"


def test_tier_labels_are_valid_enum():
    """tier 取值必须是 free|cheap|standard, 且 free <=> free_tier。"""
    for p in ALL_PROVIDERS:
        assert p.tier in ("free", "cheap", "standard"), f"{p.name} 非法档位 {p.tier!r}"
        assert (p.tier == "free") == bool(p.free_tier), f"{p.name} tier/free_tier 不一致"


def test_tier_rank_orders_free_cheapest_first():
    assert get_provider("gemini").tier_rank < get_provider("deepseek").tier_rank
    assert get_provider("deepseek").tier_rank < get_provider("openai").tier_rank


def test_agnes_in_free_tier_category():
    """Agnes AI 归入"免费层"分类, 模型全部带 |free 标注。"""
    free_names = {p.name for p in PROVIDER_CATEGORIES.get("免费层", [])}
    assert "agnes-ai" in free_names
    p = get_provider("agnes-ai")
    assert p.free_tier is True and p.category == "免费层"
    for m in get_provider_models("agnes-ai"):
        assert m.endswith("|free"), f"agnes-ai 出现非免费标注: {m}"


def test_zai_default_model():
    p = get_provider("zai")
    assert p.model == "glm-4.5-flash"


def test_free_models_estimate_zero_cost():
    """零成本档位: 估算成本应返回 0 或"免费"。"""
    for provider, model in (("agnes-ai", "agnes-2.0-flash"), ("zai", "glm-4.5-flash")):
        cost = estimate_cost(provider, model, 1000, 500)
        assert cost == 0.0, f"{provider}/{model} 应为 0 成本, 实际 {cost}"


def test_setup_custom_gateway_flow(monkeypatch):
    """setup 向导选"13. 自定义"时, 手填 provider/base_url/模型/密钥环境变量。"""
    inputs = iter([
        "13",          # 自定义选项
        "my-gateway",  # 供应商名
        "https://api.example.com/v1",
        "my-model",
        "MY_GATEWAY_API_KEY",
    ])
    monkeypatch.setattr("builtins.input", lambda *a, **k: next(inputs))
    result = _pick_setup_provider()
    assert result == ("my-gateway", "my-model", "https://api.example.com/v1", "MY_GATEWAY_API_KEY")


def test_setup_custom_cancel_on_missing_base_url(monkeypatch):
    """自定义流程缺 base_url 时应取消返回 None。"""
    inputs = iter([
        "13",
        "gw",
        "",  # base_url 为空
    ])
    monkeypatch.setattr("builtins.input", lambda *a, **k: next(inputs))
    assert _pick_setup_provider() is None


def test_setup_pick_builtin_preset(monkeypatch):
    """setup 向导选内置预设 (如 1=deepseek) 仍走模型选择流程。"""
    inputs = iter(["1", "1"])  # 分类 1 -> deepseek 第 1 个模型
    monkeypatch.setattr("builtins.input", lambda *a, **k: next(inputs))
    provider, model, base_url, env = _pick_setup_provider()
    assert provider == "deepseek"
    assert base_url.startswith("https://")
    assert env == "DEEPSEEK_API_KEY"


def test_sensenova_in_china_mainstream():
    """商汤日日新 SenseNova 应归入"中国主流"分类, Token Plan 端点。"""
    p = get_provider("sensenova")
    assert p is not None
    assert p.category == "中国主流"
    assert p.base_url.startswith("https://token.sensenova.cn/")
    assert p.model == "sensenova-6.8-flash-lite"
    cn = {x.name for x in PROVIDER_CATEGORIES.get("中国主流", [])}
    assert "sensenova" in cn
    models = get_provider_models("sensenova")
    assert models
    assert any(m.endswith("|free") for m in models)  # flash-lite 有 Token Plan 免费额度


def test_every_provider_in_a_category_still_holds():
    all_names = {p.name for p in ALL_PROVIDERS}
    grouped = {p.name for group in PROVIDER_CATEGORIES.values() for p in group}
    assert grouped == all_names


def test_setup_free_tier_filter_entry(monkeypatch):
    """setup 向导输入 f 应切到"只看免费层"并可选到免费供应商。"""
    free = free_providers()
    assert free, "免费层不应为空"
    inputs = iter(["f", "1", "1"])  # f 切免费层 -> 第 1 家 -> 第 1 个模型
    monkeypatch.setattr("builtins.input", lambda *a, **k: next(inputs))
    provider, model, base_url, env = _pick_setup_provider()
    assert provider == free[0].name
    assert base_url.startswith("https://")
    assert env


def test_setup_free_tier_filter_cancel(monkeypatch):
    """免费层子菜单输入非法编号时应安全返回 (不抛异常)。"""
    inputs = iter(["f", "abc"])
    monkeypatch.setattr("builtins.input", lambda *a, **k: next(inputs))
    assert _pick_setup_provider() is None
