"""人设系统 (Personality System) 单元测试。

覆盖:
- 10 种人设定义完整性
- 从 USER.md 提取人设名
- 从 config 读取人设名
- 自动分配人设 (确定性)
- 人设渲染文本块
- 无效人设名回退
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from tuan_cli.core.personality import (
    PERSONALITIES,
    PERSONALITY_BY_NAME,
    PERSONALITY_BY_KEY,
    PERSONALITY_NAMES,
    Personality,
    get_personality_info,
    list_personalities,
    render_personality_block,
    resolve_personality,
    _extract_personality_from_user,
    _validate_or_default,
    _auto_assign,
)


# ============================================================ 人设定义完整性

class TestPersonalityDefinitions:
    """验证 10 种人设定义的完整性。"""

    def test_exactly_ten_personalities(self):
        assert len(PERSONALITIES) == 10

    def test_unique_names(self):
        names = [p.name for p in PERSONALITIES]
        assert len(set(names)) == 10, "人设名必须唯一"

    def test_unique_keys(self):
        keys = [p.key for p in PERSONALITIES]
        assert len(set(keys)) == 10, "人设 key 必须唯一"

    def test_required_fields(self):
        for p in PERSONALITIES:
            assert p.name, "name 不能为空"
            assert p.key, "key 不能为空"
            assert p.tagline, "tagline 不能为空"
            assert len(p.tone) >= 2, "tone 至少 2 个"
            assert len(p.behaviors) >= 2, "behaviors 至少 2 个"
            assert len(p.catchphrases) >= 2, "catchphrases 至少 2 个"
            assert len(p.block) > 50, "block 不能太短"

    def test_lookup_by_name(self):
        for p in PERSONALITIES:
            assert PERSONALITY_BY_NAME[p.name] is p

    def test_lookup_by_key(self):
        for p in PERSONALITIES:
            assert PERSONALITY_BY_KEY[p.key] is p

    def test_personality_names_list(self):
        assert len(PERSONALITY_NAMES) == 10
        for name in PERSONALITY_NAMES:
            assert name in PERSONALITY_BY_NAME

    def test_get_personality_info(self):
        info = get_personality_info("专业")
        assert info["name"] == "专业"
        assert info["key"] == "professional"
        assert "tone" in info
        assert "behaviors" in info
        assert "catchphrases" in info

    def test_list_personalities(self):
        lst = list_personalities()
        assert len(lst) == 10
        for item in lst:
            assert "name" in item
            assert "key" in item


# ============================================================ 人设提取

class TestPersonalityExtraction:
    """测试从 USER.md 提取人设名。"""

    def test_extract_chinese_key(self):
        text = "# USER.md\n- Name: Alice\n- 人设: 专业"
        assert _extract_personality_from_user(text) == "专业"

    def test_extract_english_key(self):
        text = "# USER.md\n- Name: Alice\n- Personality: energetic"
        assert _extract_personality_from_user(text) == "energetic"

    def test_extract_without_bullet(self):
        text = "# USER.md\n人设: 傲娇"
        assert _extract_personality_from_user(text) == "傲娇"

    def test_extract_with_bullet(self):
        text = "# USER.md\n* 人设: 温柔"
        assert _extract_personality_from_user(text) == "温柔"

    def test_extract_with_chinese_colon(self):
        text = "# USER.md\n- 人设：幽默"
        assert _extract_personality_from_user(text) == "幽默"

    def test_extract_with_english_colon(self):
        text = "# USER.md\n- 人设: 毒舌"
        assert _extract_personality_from_user(text) == "毒舌"

    def test_extract_invalid_returns_none(self):
        text = "# USER.md\n- Name: Alice\n- Notes: hello"
        assert _extract_personality_from_user(text) is None

    def test_extract_empty_returns_none(self):
        assert _extract_personality_from_user("") is None

    def test_extract_no_user_section_returns_none(self):
        text = "# USER.md\n- Name: Alice"
        assert _extract_personality_from_user(text) is None


# ============================================================ 人设验证

class TestPersonalityValidation:
    """测试人设名验证和回退。"""

    def test_valid_name(self):
        assert _validate_or_default("专业") == "专业"
        assert _validate_or_default("元气") == "元气"
        assert _validate_or_default("傲娇") == "傲娇"

    def test_valid_key(self):
        assert _validate_or_default("professional") == "专业"
        assert _validate_or_default("energetic") == "元气"

    def test_case_insensitive_key(self):
        assert _validate_or_default("PROFESSIONAL") == "专业"

    def test_fuzzy_match(self):
        assert _validate_or_default("专业模式") == "专业"
        assert _validate_or_default("元气少女") == "元气"

    def test_invalid_falls_back(self):
        assert _validate_or_default("不存在的") == "专业"
        assert _validate_or_default("") == "专业"
        assert _validate_or_default("random") == "专业"


# ============================================================ 自动分配

class TestAutoAssign:
    """测试自动分配人设。"""

    def test_auto_assign_deterministic(self):
        """同一调用返回同一结果 (确定性)。"""
        r1 = _auto_assign()
        r2 = _auto_assign()
        assert r1 == r2

    def test_auto_assign_valid(self):
        name = _auto_assign()
        assert name in PERSONALITY_NAMES

    def test_auto_assign_is_one_of_ten(self):
        names = [_auto_assign() for _ in range(100)]
        # 确定性分配, 所以 100 次都是同一个
        assert len(set(names)) == 1


# ============================================================ 人设解析

class TestPersonalityResolution:
    """测试 resolve_personality 的优先级逻辑。"""

    def test_from_user_md(self):
        """USER.md 中的人设优先。"""
        class MockStore:
            def read_user(self):
                return "# USER.md\n- 人设: 傲娇"

        class MockConfig:
            def get(self, key, default=None):
                return default

        result = resolve_personality(config=MockConfig(), memory_store=MockStore())
        assert result == "傲娇"

    def test_from_config_when_no_user(self):
        """USER.md 无人设时, 从 config 读取。"""
        class MockStore:
            def read_user(self):
                return "# USER.md\n- Name: Alice"

        class MockConfig:
            def get(self, key, default=None):
                if key == "agent.personality":
                    return "温柔"
                return default

        result = resolve_personality(config=MockConfig(), memory_store=MockStore())
        assert result == "温柔"

    def test_user_md_overrides_config(self):
        """USER.md 人设优先于 config。"""
        class MockStore:
            def read_user(self):
                return "# USER.md\n- 人设: 幽默"

        class MockConfig:
            def get(self, key, default=None):
                if key == "agent.personality":
                    return "毒舌"
                return default

        result = resolve_personality(config=MockConfig(), memory_store=MockStore())
        assert result == "幽默"

    def test_auto_assign_when_no_source(self):
        """无 USER.md 无 config 时自动分配。"""
        class MockStore:
            def read_user(self):
                return ""

        class MockConfig:
            def get(self, key, default=None):
                return default

        result = resolve_personality(config=MockConfig(), memory_store=MockStore())
        assert result in PERSONALITY_NAMES

    def test_none_inputs(self):
        """所有输入为 None 时自动分配。"""
        result = resolve_personality(config=None, memory_store=None)
        assert result in PERSONALITY_NAMES


# ============================================================ 人设渲染

class TestPersonalityRendering:
    """测试人设文本块渲染。"""

    def test_render_valid(self):
        block = render_personality_block("专业")
        assert "人设: 专业" in block
        assert len(block) > 50

    def test_render_all_ten(self):
        for name in PERSONALITY_NAMES:
            block = render_personality_block(name)
            assert f"人设: {name}" in block
            assert len(block) > 50

    def test_render_invalid_falls_back(self):
        block = render_personality_block("不存在的")
        assert "人设: 专业" in block

    def test_render_key(self):
        """英文 key 也能渲染。"""
        block = render_personality_block("energetic")
        assert "人设: 元气" in block


# ============================================================ 集成测试

class TestPersonalityIntegration:
    """测试人设系统与其他模块的集成。"""

    def test_personality_block_format(self):
        """人设块应以 ## 开头, 包含语气和行为特征。"""
        block = render_personality_block("元气")
        assert block.startswith("## 人设:")
        assert "元气" in block

    def test_personality_not_too_long(self):
        """人设块不应过长 (节省上下文预算)。"""
        for name in PERSONALITY_NAMES:
            block = render_personality_block(name)
            assert len(block) < 500, f"人设 {name} 过长: {len(block)} chars"

    def test_personality_contains_tone(self):
        """人设块应包含语气描述。"""
        for p in PERSONALITIES:
            block = render_personality_block(p.name)
            # 至少一个语气词应出现在 block 中
            tone_words = p.tone
            assert any(word in block for word in tone_words), \
                f"人设 {p.name} 的 block 未包含任何语气词"
