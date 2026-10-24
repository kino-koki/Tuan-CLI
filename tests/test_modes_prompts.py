"""测试: 五模式提示词装配器（§4.6 提示词验收）。

覆盖:
    - 五模式各输出三份非空提示词
    - 锚点校验: 感通含 "72 份" 或 "companies"; 灵码含 "不承诺";
      闲聊含 "物理禁用"; 无界含 "硬红线"; 协同含 "草稿"
    - 全文检索旧名 "灵感"/"无限"/"工作模式" → 0 命中（旧名不出现）
    - 无效模式 ID 抛出 ValueError
    - 历史三档别名 (standard/yolo/plan) 全部仍可解析
"""
from __future__ import annotations

import re

import pytest

from tuan_cli.modes.prompts import ModePrompts, build_mode_prompts
from tuan_cli.modes.registry import MODE_IDS


def _blob(prompts: ModePrompts) -> str:
    """将三件套拼接为单一字符串，便于全文检索。"""
    return "\n".join([prompts.system, prompts.memory, prompts.guard])


# 旧名检索规则：
#   "灵感"  —— 旧名（感通模式曾用名），提示词中应以 "感通" 出现，不得含 "灵感"。
#   "无限"  —— 旧名（无界模式曾用名）。提示词含 "无限制"（不等于无限制），
#              此为常见汉语词，非旧模式名；用负向先行断言排除 "无限制" 误命中。
#   "工作模式" —— 旧名（泛指），提示词中不得出现。
_LEGACY_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("灵感", re.compile(r"灵感")),
    ("无限", re.compile(r"无限(?!制)")),
    ("工作模式", re.compile(r"工作模式")),
)


# =====================================================================
# 五模式各输出三份非空提示词
# =====================================================================


@pytest.mark.parametrize("mode_id", list(MODE_IDS))
def test_each_mode_yields_three_nonempty_prompts(mode_id: str) -> None:
    """五模式各输出三份非空提示词。"""
    prompts = build_mode_prompts(mode_id)
    assert isinstance(prompts, ModePrompts), f"{mode_id}: 非 ModePrompts"
    assert prompts.system and prompts.system.strip(), f"{mode_id}: system 空"
    assert prompts.memory and prompts.memory.strip(), f"{mode_id}: memory 空"
    assert prompts.guard and prompts.guard.strip(), f"{mode_id}: guard 空"


# =====================================================================
# 锚点校验
# =====================================================================


def test_gantong_anchor_72_companies() -> None:
    """感通 (gantong) 锚点: 含 "72 份" 或 "companies"。"""
    blob = _blob(build_mode_prompts("gantong"))
    assert "72 份" in blob or "companies" in blob, "感通锚点缺失"


def test_lingma_anchor_no_promise() -> None:
    """灵码 (lingma) 锚点: 含 "不承诺"。"""
    blob = _blob(build_mode_prompts("lingma"))
    assert "不承诺" in blob, "灵码锚点缺失"


def test_chat_anchor_physical_disabled() -> None:
    """闲聊 (chat) 锚点: 含 "物理禁用"。"""
    blob = _blob(build_mode_prompts("chat"))
    assert "物理禁用" in blob, "闲聊锚点缺失"


def test_boundless_anchor_hardline() -> None:
    """无界 (boundless) 锚点: 含 "硬红线"。"""
    blob = _blob(build_mode_prompts("boundless"))
    assert "硬红线" in blob, "无界锚点缺失"


def test_collaboration_anchor_draft() -> None:
    """协同 (collaboration) 锚点: 含 "草稿"。"""
    blob = _blob(build_mode_prompts("collaboration"))
    assert "草稿" in blob, "协同锚点缺失"


# =====================================================================
# 旧名全文检索 → 0 命中
# =====================================================================


@pytest.mark.parametrize("mode_id", list(MODE_IDS))
def test_no_legacy_names_in_prompts(mode_id: str) -> None:
    """全文检索旧名 "灵感"/"无限"/"工作模式" → 0 命中。

    "无限" 使用负向先行断言排除 "无限制"（boundless 提示词含
    "不等于无限制"，属常见汉语词，非旧模式名）。
    """
    blob = _blob(build_mode_prompts(mode_id))
    for label, pattern in _LEGACY_PATTERNS:
        assert not pattern.search(blob), f"{mode_id}: 提示词中出现旧名 {label!r}"


# =====================================================================
# 无效模式 ID → ValueError
# =====================================================================


def test_invalid_mode_id_raises_valueerror() -> None:
    """无效模式 ID 抛出 ValueError。"""
    with pytest.raises(ValueError):
        build_mode_prompts("does-not-exist")


def test_invalid_mode_id_message_mentions_mode() -> None:
    """错误信息应提示未知模式，便于定位。"""
    with pytest.raises(ValueError, match="未知模式"):
        build_mode_prompts("turbo")


# =====================================================================
# 历史三档别名仍可通过装配器解析
# =====================================================================


@pytest.mark.parametrize(
    "alias,expected_mode",
    [
        ("standard", "collaboration"),
        ("yolo", "boundless"),
        ("plan", "chat"),
    ],
)
def test_legacy_aliases_resolve(alias: str, expected_mode: str) -> None:
    """历史三档别名 (standard/yolo/plan) 全部仍可解析。"""
    prompts = build_mode_prompts(alias)
    assert isinstance(prompts, ModePrompts)
    # 别名解析后应与目标模式内容一致
    direct = build_mode_prompts(expected_mode)
    assert prompts.system == direct.system
    assert prompts.memory == direct.memory
    assert prompts.guard == direct.guard
