"""Fable5 接入 + 前端设计技能 + 提到才读 回归测试。"""

from pathlib import Path

from qingxiaotuan.skills import SkillManager
from qingxiaotuan.core.prompts import build_system_prompt
from qingxiaotuan.tui.tui import QxtTUI
from qingxiaotuan.runtime.contract import GenerateOptions
from qingxiaotuan.runtime.providers.anthropic import AnthropicChatProvider

BUILTIN_DIR = Path(__file__).resolve().parents[1] / "qingxiaotuan" / "resources" / "skills" / "builtin"


# ---------------------------------------------------------------- 前端设计技能

def test_frontend_design_builtin_skill_exists():
    """内置 frontend-design 技能存在, frontmatter 完整可解析, 前端标签映射可命中。"""
    path = BUILTIN_DIR / "frontend-design.md"
    assert path.exists(), "frontend-design.md 必须随包分发"
    mgr = SkillManager(Path("."))  # 仅用 _parse, 不落盘
    skill = mgr._parse(path)
    assert skill.name == "前端设计语言先行"
    assert "frontend-design" in skill.tags
    assert skill.activation == "lazy"
    assert skill.priority >= 6
    assert "设计语言" in skill.body
    # 提到才读: 触发词表非空
    assert skill.triggers


def test_frontend_design_tag_activation(qxt_home):
    """前端/设计类任务能激活内置 frontend-design 技能 (标签映射命中)。"""
    mgr = SkillManager(qxt_home)
    src = BUILTIN_DIR / "frontend-design.md"
    dest = mgr.dir / "frontend-design.md"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    for q in ["帮我设计一个登录页", "做一个前端页面", "重构这个 UI 界面"]:
        hits = mgr.activate_for_task(q)
        assert hits, f"任务 {q!r} 应激活前端设计技能"
        assert any("frontend-design" in s.tags for s in hits)


# ---------------------------------------------------------------- 提到才读渲染

def test_render_prompt_registry_mode(qxt_home):
    """render_for_prompt 注册表模式: lazy 技能只渲染目录, always 技能渲染全文。"""
    mgr = SkillManager(qxt_home)
    mgr.save("Lazy Skill", "lazy 技能描述", "LONG_BODY_LAZY_XYZ")
    lazy = mgr.load("lazy-skill")
    assert lazy is not None
    rendered = mgr.render_for_prompt([lazy])
    assert "可复用技能" in rendered  # 兼容既有断言
    assert "LONG_BODY_LAZY_XYZ" not in rendered  # lazy: 正文不注入
    assert "lazy 技能描述" in rendered

    always = mgr.save("Always Skill", "always 技能描述", "ALWAYS_BODY_XYZ")
    always.activation = "always"
    rendered2 = mgr.render_for_prompt([always])
    assert "ALWAYS_BODY_XYZ" in rendered2  # always: 全文注入


# ---------------------------------------------------------------- Fable5 接入

def test_tui_fable_context_window_1m():
    """Claude Fable 5 系列在 TUI 底栏按 1M 上下文计算。"""
    tui = QxtTUI.__new__(QxtTUI)
    assert tui._model_context_window("anthropic", "claude-fable-5") == 1_000_000
    assert tui._model_context_window("anthropic", "anthropic/claude-fable-latest") == 1_000_000
    # 非 fable 模型不受影响
    assert tui._model_context_window("anthropic", "claude-sonnet-4-20250514") == 200_000


def test_anthropic_thinking_effort_body():
    """Anthropic provider 支持 thinking effort (Fable 5 深度控制, provider 实例属性)。"""
    prov = AnthropicChatProvider(api_key="test-key", model="claude-fable-5")
    prov.thinking_effort = "high"
    body = prov._build_body("sys", [], [], GenerateOptions())
    assert body["thinking"] == {"type": "enabled", "effort": "high"}
    # 未指定 effort 时不下发 thinking 参数 (保持旧行为)
    prov2 = AnthropicChatProvider(api_key="test-key", model="claude-fable-5")
    body2 = prov2._build_body("sys", [], [], GenerateOptions())
    assert "thinking" not in body2


# ---------------------------------------------------------------- 提示词注入

def test_system_prompt_skill_guidance(qxt_home):
    """系统提示词包含技能使用规范 (提到才读)。"""
    prompt = build_system_prompt(qxt_home, "C:\\proj")
    assert "提到才读" in prompt
    assert "skill_read" in prompt
    assert "skill_save" in prompt


def test_fallback_identity_has_design_view(qxt_home):
    """无 SOUL.md 时兜底身份包含技能按需加载与前端设计观。"""
    prompt = build_system_prompt(qxt_home, "C:\\proj")
    assert "前端/UI 时先定设计语言" in prompt
