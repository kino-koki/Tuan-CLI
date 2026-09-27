"""功能3: frontmatter 超集兼容测试 (Codex/Claude Code 开放标准)。

覆盖:
  - 解析 display_name / short_description / default_prompt / policy.allow_implicit_invocation
  - 旧格式技能仍正常解析 (向后兼容)
  - 写入保留全部字段
  - render_for_prompt 优先 short_description
  - default_prompt 无参数斜杠命令时的取值
"""

from __future__ import annotations

from pathlib import Path

from qingxiaotuan.skills.manager import SkillManager


SUPERSET_MD = """---
name: test-skill
description: 这是一个用于验证 frontmatter 超集解析的测试技能
display_name: 测试技能
short_description: 简短描述, 用于列表视图
default_prompt: 帮我跑一遍完整的测试流程并汇总结果
policy.allow_implicit_invocation: true
tags: testing, demo
activation: auto
---

# 正文
1. 第一步
2. 第二步
3. 第三步
"""

LEGACY_MD = """---
name: legacy-skill
description: 旧格式技能, 只有基础字段
tags: legacy
updated_at: 1700000000
use_count: 5
---

旧正文
"""


def test_parse_superset_fields(tmp_path: Path):
    home = tmp_path / "home"
    mgr = SkillManager(home)
    p = home / "skills" / "test-skill.md"
    p.write_text(SUPERSET_MD, encoding="utf-8")
    s = mgr.load("test-skill")
    assert s is not None
    assert s.display_name == "测试技能"
    assert s.short_description == "简短描述, 用于列表视图"
    assert s.default_prompt == "帮我跑一遍完整的测试流程并汇总结果"
    assert s.allow_implicit is True
    # qxt 自有字段保留
    assert s.activation == "auto"
    assert "testing" in s.tags


def test_legacy_backward_compat(tmp_path: Path):
    home = tmp_path / "home"
    mgr = SkillManager(home)
    p = home / "skills" / "legacy-skill.md"
    p.write_text(LEGACY_MD, encoding="utf-8")
    s = mgr.load("legacy-skill")
    assert s is not None
    assert s.name == "legacy-skill"
    assert s.use_count == 5
    # 新字段缺省即默认值, 不报错
    assert s.display_name == ""
    assert s.short_description == ""
    assert s.default_prompt == ""
    assert s.allow_implicit is False


def test_write_preserves_all_fields(tmp_path: Path):
    home = tmp_path / "home"
    mgr = SkillManager(home)
    s = mgr.save("超集写入", "一个足够长的写入描述用于验证字段保留",
                 "正文内容足够长以通过门控检查\n1. 一\n2. 二\n3. 三\n",
                 display_name="展示名", short_description="简短",
                 default_prompt="默认任务", tags=["demo"])
    text = s.path.read_text(encoding="utf-8")
    assert "display_name: 展示名" in text
    assert "short_description: 简短" in text
    assert "default_prompt: 默认任务" in text
    # 重新读回
    s2 = mgr.load("超集写入")
    assert s2.display_name == "展示名"
    assert s2.default_prompt == "默认任务"


def test_render_prefers_short_description(tmp_path: Path):
    home = tmp_path / "home"
    mgr = SkillManager(home)
    p = home / "skills" / "rd.md"
    p.write_text(SUPERSET_MD, encoding="utf-8")
    s = mgr.load("rd")
    out = mgr.render_for_prompt([s])
    assert "简短描述, 用于列表视图" in out
    # display_name 用于展示
    assert "测试技能" in out


def test_default_prompt_used_when_no_args(tmp_path: Path):
    """无参数 /skill-name 时, 调用方应取 default_prompt 作为任务。"""
    home = tmp_path / "home"
    mgr = SkillManager(home)
    p = home / "skills" / "dp.md"
    p.write_text(SUPERSET_MD, encoding="utf-8")
    s = mgr.load("dp")
    # 模拟斜杠命令无参数: task 为空时回落到 default_prompt
    user_input = ""
    task = user_input.strip() or s.default_prompt
    assert task == "帮我跑一遍完整的测试流程并汇总结果"
