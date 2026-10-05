# -*- coding: utf-8 -*-
"""操作纪律段测试: 检索/引用/拒绝与信任/记忆负面规则/工件判定。

设计参考: 2026 年公开讨论的 Anthropic Fable 5 系统提示词泄露物所体现的
分层策略引擎思路 —— 但本项目只借鉴理念并用自研表达, 测试同时断言
「不含泄露原文特征」, 防止将来误粘贴版权内容。
"""
from __future__ import annotations

import pytest

from qingxiaotuan.core.prompts import (
    _FALLBACK_SOUL,
    build_system_prompt,
    build_system_prompt_stable,
    system_prompt_stable_hash,
)

_DISCIPLINE_MARKERS = ("检索纪律", "引用纪律", "拒绝与信任", "记忆负面规则", "工件判定")


@pytest.mark.parametrize("marker", _DISCIPLINE_MARKERS)
def test_stable_prefix_contains_discipline_sections(qxt_home, marker: str) -> None:
    """稳定前缀包含全部操作纪律章节。"""
    stable = build_system_prompt_stable(qxt_home)
    assert marker in stable


def test_full_prompt_contains_discipline(qxt_home, tmp_path) -> None:
    """完整系统提示 (stable+dynamic) 包含操作纪律。"""
    prompt = build_system_prompt(qxt_home, str(tmp_path))
    assert "## 操作纪律" in prompt
    assert "不逐字粘贴" in prompt
    assert "gaslight" in prompt


def test_stable_hash_is_stable_across_calls(qxt_home) -> None:
    """操作纪律加入后 stable 段仍逐字节稳定 (prompt cache 边界不破坏)。"""
    h1 = system_prompt_stable_hash(build_system_prompt_stable(qxt_home))
    h2 = system_prompt_stable_hash(build_system_prompt_stable(qxt_home))
    assert h1 == h2


def test_fallback_soul_summarizes_discipline() -> None:
    """SOUL.md 缺失时兜底身份也带操作纪律总纲。"""
    assert "操作纪律" in _FALLBACK_SOUL
    assert "引用必改写并注明来源" in _FALLBACK_SOUL
    # 既有断言保护: 历史关键句不得被覆盖
    assert "前端/UI 时先定设计语言" in _FALLBACK_SOUL
    assert "技能按需加载" in _FALLBACK_SOUL


def test_no_verbatim_leak_of_fable_prompt(qxt_home, tmp_path) -> None:
    """防误贴: 提示词不含泄露原文的结构特征与专用标签。"""
    prompt = build_system_prompt(qxt_home, str(tmp_path))
    for forbidden in (
        "antml:cite",
        "budget:token_budget",
        "claude_behavior",
        "<memory_system>",
        "critical_child_safety_instructions",
    ):
        assert forbidden not in prompt


def test_soul_md_matches_discipline_sections() -> None:
    """SOUL.md 与代码内纪律段章节命名一致 (单一事实源可对齐)。"""
    import os

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, "qingxiaotuan", "resources", "SOUL.md"), encoding="utf-8") as f:
        soul_text = f.read()
    assert "检索纪律" in soul_text
    assert "引用纪律" in soul_text
    assert "拒绝与信任" in soul_text
    assert "记忆负面规则" in soul_text
    assert "工件判定" in soul_text
    assert "不复制任何原文" in soul_text
