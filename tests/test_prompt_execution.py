# -*- coding: utf-8 -*-
"""执行协议段 + SKILL 注入语义测试。

覆盖本轮两处增强:
1. 提示词超越层 —— 稳定前缀新增「执行协议」段 (工具理由化/上下文预算/验证闭环/
   副作用自检/不确定性分级/审计友好), 与操作纪律互补且逐字节稳定 (cache 友好);
2. SKILL 注入完善 —— activation=always 技能保底注入 (不受 top-N 热度排序挤占);
   auto/lazy/proactive 只给注册表条目 (正文按需 skill_read); 注入段带激活档标记
   与决策规则; always 正文有行数预算。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from qingxiaotuan.core.prompts import (
    build_system_prompt,
    build_system_prompt_dynamic,
    build_system_prompt_stable,
    system_prompt_stable_hash,
)
from qingxiaotuan.skills.manager import Skill, SkillManager

_PROTOCOL_MARKERS = (
    "## 执行协议",
    "工具调用理由化",
    "上下文预算",
    "验证闭环",
    "副作用自检",
    "不确定性分级",
    "审计友好",
)


def _skill(name: str, activation: str, priority: int = 0, use_count: int = 0,
           body: str = "守则正文", triggers=None, desc: str = "") -> Skill:
    return Skill(
        name=name,
        description=desc or f"{name} 描述",
        body=body,
        path=Path(f"{name}.md"),
        priority=priority,
        use_count=use_count,
        activation=activation,
        triggers=triggers or [],
        short_description=f"{name} 短描述",
    )


class _FakeSkillManager:
    """最小鸭子类型: 只实现 list_all / render_for_prompt。"""

    def __init__(self, skills, renderer=None):
        self._skills = skills
        self._renderer = renderer

    def list_all(self):
        return list(self._skills)

    def render_for_prompt(self, skills):
        if self._renderer is not None:
            return self._renderer(skills)
        return SkillManager(Path(".")).render_for_prompt(skills)


# ============================================================ 执行协议段

@pytest.mark.parametrize("marker", _PROTOCOL_MARKERS)
def test_stable_prefix_contains_execution_protocol(qxt_home, marker: str) -> None:
    """稳定前缀包含执行协议全部章节。"""
    stable = build_system_prompt_stable(qxt_home)
    assert marker in stable


def test_full_prompt_contains_execution_protocol(qxt_home, tmp_path) -> None:
    """完整系统提示包含执行协议, 且六条组合齐全。"""
    prompt = build_system_prompt(qxt_home, str(tmp_path))
    assert "## 执行协议" in prompt
    assert "不为「显得忙碌」重复调用" in prompt
    assert "验证失败先诊断根因再修" in prompt
    assert "/audit /impact 可追溯" in prompt


def test_protocol_hash_stable_across_calls(qxt_home) -> None:
    """执行协议加入后 stable 段仍逐字节稳定 (prompt cache 边界不破坏)。"""
    h1 = system_prompt_stable_hash(build_system_prompt_stable(qxt_home))
    h2 = system_prompt_stable_hash(build_system_prompt_stable(qxt_home))
    assert h1 == h2


def test_soul_md_contains_execution_protocol() -> None:
    """SOUL.md 与代码内执行协议章节一致 (单一事实源可对齐)。"""
    import os

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, "qingxiaotuan", "resources", "SOUL.md"), encoding="utf-8") as f:
        soul_text = f.read()
    assert "## 执行协议" in soul_text
    assert "工具调用理由化" in soul_text
    assert "验证闭环" in soul_text
    assert "审计友好" in soul_text


# ============================================================ SKILL 注入语义

def test_always_skill_not_squeezed_by_priority(qxt_home, tmp_path) -> None:
    """always 技能 priority 再低也保底注入, 不被高热度 lazy 技能挤出 top-N。"""
    always = _skill("always-guard", "always", priority=0, use_count=0,
                    body="常驻守则: 任何情况下遵守。")
    hot1 = _skill("hot-lazy-1", "lazy", priority=100, use_count=99)
    hot2 = _skill("hot-lazy-2", "lazy", priority=99, use_count=88)
    hot3 = _skill("hot-lazy-3", "lazy", priority=98, use_count=77)
    hot4 = _skill("hot-lazy-4", "lazy", priority=97, use_count=66)
    mgr = _FakeSkillManager([hot1, hot2, hot3, hot4, always])

    prompt = build_system_prompt_dynamic(
        qxt_home, str(tmp_path), skill_manager=mgr, skill_limit=3)
    assert "always-guard" in prompt          # always 技能进注入
    assert "常驻守则" in prompt              # always 正文注入
    assert "hot-lazy-1" in prompt            # 最高热度 lazy 也进
    # top-N 之外的 lazy 只出现为名称 (注册表) 或不出现 —— 不注入正文
    assert "hot-lazy-4" not in prompt        # 第 4 个被挤出


def test_auto_skill_registry_entry_without_body(qxt_home, tmp_path) -> None:
    """auto 技能只给注册表条目 (含激活档标记), 正文不无条件注入。"""
    auto = _skill("auto-fmt", "auto", priority=90, body="AUTO 正文不应出现")
    lazy = _skill("lazy-help", "lazy", body="LAZY 正文不应出现")
    mgr = _FakeSkillManager([auto, lazy])

    prompt = build_system_prompt_dynamic(
        qxt_home, str(tmp_path), skill_manager=mgr, skill_limit=3)
    assert "auto-fmt" in prompt
    assert "AUTO 正文不应出现" not in prompt   # 正文按需加载
    assert "lazy-help" in prompt
    assert "LAZY 正文不应出现" not in prompt


def test_render_has_activation_tags_and_decision_rule() -> None:
    """注册表条目带激活档标记, 尾部有决策规则。"""
    skills = [_skill("a", "always", body="A 正文"), _skill("b", "lazy"),
              _skill("c", "auto", body="C 正文")]
    rendered = SkillManager(Path(".")).render_for_prompt(skills)
    assert "(a, always)" in rendered
    assert "(b, lazy)" in rendered
    assert "(c, auto)" in rendered
    assert "决策规则" in rendered
    assert "正文已注入" in rendered
    assert "C 正文" not in rendered          # auto 正文不入
    assert "A 正文" in rendered              # always 正文入


def test_render_full_body_for_explicit_load() -> None:
    """显式加载场景 (子代理预加载指定技能) full_body=True 时渲染完整正文。"""
    skills = [_skill("c", "auto", body="C 正文")]
    rendered = SkillManager(Path(".")).render_for_prompt(skills, full_body=True)
    assert "C 正文" in rendered


def test_always_body_capped_at_line_budget() -> None:
    """always 正文超过行数预算时截断并提示 (防上下文膨胀)。"""
    long_body = "\n".join(f"第{i}行" for i in range(80))
    s = _skill("long-always", "always", body=long_body)
    rendered = SkillManager(Path(".")).render_for_prompt([s])
    assert "第0行" in rendered
    assert "第79行" not in rendered
    assert "正文过长已截断" in rendered
