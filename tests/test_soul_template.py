"""测试 SOUL.md 模板升级 (P0)。

验证:
- resources/SOUL.md 包含新增章节关键词 (思考预算/错误处理/模型自我认知/工作协议);
- prompts.py 内置回退文案包含思考预算与错误处理要点。
"""
from pathlib import Path

from qingxiaotuan.core import prompts

SOUL_PATH = (
    Path(__file__).resolve().parent.parent
    / "qingxiaotuan" / "resources" / "SOUL.md"
)


class TestSoulTemplate:
    def test_soul_file_exists(self):
        assert SOUL_PATH.exists()

    def test_soul_contains_thinking_budget_section(self):
        text = SOUL_PATH.read_text(encoding="utf-8")
        assert "思考预算" in text
        assert "20 步" in text

    def test_soul_contains_error_handling_section(self):
        text = SOUL_PATH.read_text(encoding="utf-8")
        assert "错误处理" in text
        assert "重试" in text

    def test_soul_contains_model_self_awareness(self):
        text = SOUL_PATH.read_text(encoding="utf-8")
        assert "模型自我认知" in text
        assert "token" in text.lower()

    def test_soul_contains_work_protocol(self):
        text = SOUL_PATH.read_text(encoding="utf-8")
        assert "工作协议" in text
        assert "验证" in text

    def test_soul_keeps_original_content(self):
        """不删除原有内容。"""
        text = SOUL_PATH.read_text(encoding="utf-8")
        assert "核心信条" in text
        assert "编码规范" in text
        assert "安全与伦理" in text


class TestFallbackSoul:
    def test_fallback_contains_thinking_budget(self, tmp_path):
        """home 下无 SOUL.md 时, 回退文案应含思考预算要点。"""
        empty_home = tmp_path / "no-soul"
        empty_home.mkdir()
        prompt = prompts.build_system_prompt_stable(empty_home, str(tmp_path))
        assert "思考预算" in prompt

    def test_fallback_contains_error_handling(self, tmp_path):
        empty_home = tmp_path / "no-soul2"
        empty_home.mkdir()
        prompt = prompts.build_system_prompt_stable(empty_home, str(tmp_path))
        assert "错误处理" in prompt
        assert "重试" in prompt

    def test_fallback_constant_exposes_keywords(self):
        assert "思考预算" in prompts._FALLBACK_SOUL
        assert "错误处理" in prompts._FALLBACK_SOUL
        assert "自我认知" in prompts._FALLBACK_SOUL
