"""提示词分层 (Prompt Tier) 测试 —— 按模型上下文窗口规模选择注入预算 (待办4)。

验证:
- infer_context_window: 配置显式值 > 模型名尺寸后缀/家族 > 供应商默认 > 128k 兜底;
  特别覆盖 ``-1m`` 后缀必须解析为 1_000_000 (旧 TUI 实现误判为 256k);
- resolve_prompt_tier: 阈值两侧分档、强制覆盖、非法阈值回退;
- PromptBudget.apply_caps: 只收紧不放大, 用户调小的值永远优先;
- budget_for_tier / budgets_from_config: 未知档位回退 full, 半配置逐字段补齐;
- resolve_prompt_budget: 端到端配置解析;
- Agent 集成: 小上下文模型 → compact 档 (收紧注入预算 + 只读 SOUL_COMPACT.md);
  大上下文模型 (>=128k) → full 档 (注入预算放开 + 读 SOUL_FULL.md 完整提示词);
  代码库地图是否注入只由 context.pin_codebase 决定, 分层不越权代劳;
- resolve_soul_tier: auto 不换 SOUL (agent 层按窗口联动定档), 显式 compact/full 才换内置档位 SOUL。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tuan_cli.core import prompt_tier
from tuan_cli.core.prompt_tier import (
    COMPACT,
    DEFAULT_CONTEXT_TIER_THRESHOLD,
    FULL,
    PromptBudget,
    budget_for_tier,
    budgets_from_config,
    infer_context_window,
    resolve_prompt_budget,
    resolve_prompt_tier,
    resolve_soul_tier,
)


# ============================================================ 内置资源目录解析

class TestResolveResourcesDir:
    """_RESOURCES_DIR 必须解析到真实存在的目录, 且 SOUL.md 在其内。

    回归: 旧实现把 importlib.resources 返回的 MultiplexedPath 直接 Path() 包裹,
    Windows 下 is_dir() 误报 False, 导致 _load_builtin_soul 永远读不到
    SOUL_FULL.md / SOUL_COMPACT.md, 所有大上下文模型实际都退化成兜底文案。
    """

    def test_resources_dir_exists_and_has_soul(self):
        from tuan_cli.config.defaults import _RESOURCES_DIR

        assert _RESOURCES_DIR.is_dir(), (
            f"_RESOURCES_DIR={_RESOURCES_DIR} 不是有效目录, "
            "SOUL_FULL.md / SOUL_COMPACT.md 将无法加载"
        )
        assert (_RESOURCES_DIR / "SOUL.md").exists(), "resources 目录缺少 SOUL.md"
        assert (_RESOURCES_DIR / "SOUL_FULL.md").exists(), "resources 目录缺少 SOUL_FULL.md"
        assert (_RESOURCES_DIR / "SOUL_COMPACT.md").exists(), "resources 目录缺少 SOUL_COMPACT.md"

    def test_load_builtin_soul_full_not_empty(self):
        """大上下文模型应实际拿到 SOUL_FULL.md 内容 (而非空串/兜底)。"""
        from tuan_cli.core.prompts import _load_builtin_soul

        full = _load_builtin_soul("full")
        compact = _load_builtin_soul("compact")
        assert len(full) > 10_000, f"SOUL_FULL.md 加载结果异常短: {len(full)} 字"
        assert "SOUL_FULL" in full or "青小团" in full, "SOUL_FULL 内容未包含预期的身份声明"
        assert len(compact) > 1_000, f"SOUL_COMPACT.md 加载结果异常短: {len(compact)} 字"

    def test_large_window_model_gets_soul_full_in_prompt(self):
        """端到端: 200k 窗口模型的系统提示词应包含 SOUL_FULL 开头。"""
        import copy
        from tuan_cli.config.defaults import DEFAULT_CONFIG
        from tuan_cli.config.loader import Config
        from tuan_cli.core.prompts import build_system_prompt_stable
        from tuan_cli.core.prompt_tier import resolve_prompt_budget, COMPACT, FULL

        cfg = Config.__new__(Config)
        cfg.profile = "default"
        cfg.bare = True
        cfg.home = Path(__file__).parent.parent / ".scratch"
        cfg.data = copy.deepcopy(DEFAULT_CONFIG)
        cfg.data["model"] = {"provider": "anthropic", "model": "claude-sonnet-4",
                             "context_window": 200_000}

        tier, _win, _budget = resolve_prompt_budget(cfg)
        soul_tier = tier if tier in (COMPACT, FULL) else ""
        assert soul_tier == FULL, f"200k 窗口应解析为 full 档, 实际 {soul_tier}"

        prompt = build_system_prompt_stable(
            home=cfg.home, reply_language="zh-CN", user_mode=False, tier=soul_tier,
        )
        assert prompt.startswith("# SOUL_FULL"), (
            "200k 窗口模型的系统提示词应以 SOUL_FULL.md 开头, "
            f"实际第一行: {prompt.splitlines()[0][:60]!r}"
        )


# ============================================================ 窗口推断

class TestInferContextWindow:
    def test_explicit_config_wins_over_model_name(self):
        """网关有自定义限额时, 配置值优先 (如 Azure 截断到 32k)。"""
        assert infer_context_window("glm-4-plus-1m", "zhipu", configured=32 * 1024) == 32 * 1024

    def test_model_name_suffix_k(self):
        assert infer_context_window("doubao-1.5-pro-256k", "volcengine") == 256 * 1024
        assert infer_context_window("glm-4-128k", "zhipu") == 128 * 1024

    def test_model_name_suffix_1m_is_one_million(self):
        """回归: 旧 TUI 实现把 ``-1m`` 误判成 256k, 这里钉死正确语义。"""
        assert infer_context_window("glm-4-plus-1m", "zhipu") == 1_000_000
        assert infer_context_window("gpt-4o-1m", "openai") == 1_000_000

    def test_model_name_suffix_multiple_m(self):
        assert infer_context_window("model-2m", "any") == 2_000_000

    def test_fable_family_is_1m(self):
        assert infer_context_window("claude-fable-5", "anthropic") == 1_000_000
        assert infer_context_window("anthropic/claude-fable-latest", "anthropic") == 1_000_000

    def test_provider_defaults(self):
        assert infer_context_window("deepseek-chat", "deepseek") == 128 * 1024
        assert infer_context_window("claude-sonnet-4-20250514", "anthropic") == 200_000
        assert infer_context_window("gemini-2.5-pro", "gemini") == 1_000_000
        assert infer_context_window("qwen2.5-72b", "aliyun") == 128 * 1024

    def test_unknown_provider_falls_back_to_128k(self):
        assert infer_context_window("my-custom-model", "my-gateway") == 128 * 1024

    def test_never_returns_non_positive(self):
        assert infer_context_window("", "", configured=0) > 0
        assert infer_context_window("", "", configured=-5) > 0
        assert infer_context_window("", "", configured="bogus") > 0


# ============================================================ 分档

class TestResolvePromptTier:
    def test_below_threshold_is_compact(self):
        """128k 起即为大上下文 (full); 低于 128k 才是 compact。"""
        assert resolve_prompt_tier(32 * 1024) == COMPACT
        assert resolve_prompt_tier(64 * 1024) == COMPACT
        assert resolve_prompt_tier(128 * 1024 - 1) == COMPACT
        # 128k 整 (含) 即大上下文模型
        assert resolve_prompt_tier(128 * 1024) == FULL
        assert resolve_prompt_tier(200_000) == FULL

    def test_above_threshold_is_full(self):
        assert resolve_prompt_tier(1_000_000) == FULL
        assert resolve_prompt_tier(2_000_000) == FULL

    def test_threshold_is_inclusive_boundary(self):
        """恰好等于阈值即视为大上下文 (>= 阈值拿 full)。"""
        assert resolve_prompt_tier(DEFAULT_CONTEXT_TIER_THRESHOLD) == FULL
        assert resolve_prompt_tier(DEFAULT_CONTEXT_TIER_THRESHOLD - 1) == COMPACT

    def test_forced_tier_override(self):
        assert resolve_prompt_tier(32 * 1024, tier="full") == FULL
        assert resolve_prompt_tier(1_000_000, tier="compact") == COMPACT
        assert resolve_prompt_tier(32 * 1024, tier=" FULL ") == FULL

    def test_auto_and_unknown_tier_do_not_override(self):
        """auto/未知档位不覆盖按窗口的判定: 128k 仍算大上下文。"""
        assert resolve_prompt_tier(128 * 1024, tier="auto") == FULL
        assert resolve_prompt_tier(128 * 1024, tier="banana") == FULL
        assert resolve_prompt_tier(32 * 1024, tier="auto") == COMPACT
        assert resolve_prompt_tier(32 * 1024, tier="banana") == COMPACT
        assert resolve_prompt_tier(1_000_000, tier="") == FULL

    def test_invalid_threshold_falls_back_to_default(self):
        """阈值 <= 0 视为无效 —— 回退默认 (128k 下界), 而非误打成 compact。"""
        assert resolve_prompt_tier(128 * 1024, threshold=0) == FULL
        assert resolve_prompt_tier(128 * 1024, threshold=-100) == FULL
        assert resolve_prompt_tier(32 * 1024, threshold=0) == COMPACT

    def test_custom_threshold(self):
        assert resolve_prompt_tier(200_000, threshold=100_000) == FULL
        assert resolve_prompt_tier(200_000, threshold=300_000) == COMPACT


# ============================================================ 预算

class TestPromptBudgetCaps:
    def test_compact_shrinks_defaults(self):
        """compact 档收紧内置默认值。"""
        budget = budget_for_tier(COMPACT)
        got = budget.apply_caps(
            skill_limit=3, memory_notes_max_lines=200,
            project_doc_max_bytes=32768, long_memory_max_chars=1500)
        assert got == (2, 100, 12288, 800)

    def test_full_is_transparent(self):
        """full 档上限远高于默认值 → 用户配置原样通过 (历史行为)。"""
        budget = budget_for_tier(FULL)
        got = budget.apply_caps(
            skill_limit=3, memory_notes_max_lines=200,
            project_doc_max_bytes=32768, long_memory_max_chars=1500)
        assert got == (3, 200, 32768, 1500)

    def test_caps_only_shrink_never_inflate(self):
        """用户显式调小的值永远优先, 分层绝不偷偷放宽。"""
        budget = budget_for_tier(FULL)
        got = budget.apply_caps(
            skill_limit=1, memory_notes_max_lines=10,
            project_doc_max_bytes=1024, long_memory_max_chars=200)
        assert got == (1, 10, 1024, 200)

    def test_clamps_non_positive_inputs(self):
        budget = budget_for_tier(COMPACT)
        got = budget.apply_caps(
            skill_limit=-5, memory_notes_max_lines=-1,
            project_doc_max_bytes=0, long_memory_max_chars=-9)
        assert got[0] == 0
        assert got[1] == 0
        assert got[2] == 0
        assert got[3] == 0

    def test_tier_budget_only_carries_amount_caps(self):
        """分层只管「注入多少」(四个数量上限), 不决定「注入什么」。

        是否注入代码库地图属于用户的显式开关 (context.pin_codebase),
        分层不越权代劳 —— 否则模型会在用户不知情时少看一整块内容。
        """
        import dataclasses
        fields = {f.name for f in dataclasses.fields(budget_for_tier(COMPACT))}
        assert fields == {
            "skill_limit", "memory_notes_max_lines",
            "project_doc_max_bytes", "long_memory_max_chars",
        }


class TestBudgetForTier:
    def test_unknown_tier_falls_back_to_full(self):
        assert budget_for_tier("nonsense") == budget_for_tier(FULL)
        assert budget_for_tier(None) == budget_for_tier(FULL)

    def test_partial_custom_table_merges_with_defaults(self):
        """只配 compact 时, full 档仍能从内置默认取到 (不 KeyError)。"""
        custom = {"compact": PromptBudget(skill_limit=1)}
        assert budget_for_tier(COMPACT, custom).skill_limit == 1
        assert budget_for_tier(FULL, custom) == budget_for_tier(FULL)


class TestBudgetsFromConfig:
    def test_none_without_config(self):
        assert budgets_from_config(None) is None

    def test_partial_entry_fills_from_defaults(self):
        cfg = {
            "prompt": {
                "tiers": {
                    "compact": {"skill_limit": 1},
                }
            }
        }
        table = budgets_from_config(cfg)
        assert table is not None
        compact = table[COMPACT]
        assert compact.skill_limit == 1
        # 未配字段沿用内置默认
        assert compact.memory_notes_max_lines == prompt_tier.DEFAULT_TIER_BUDGETS[COMPACT].memory_notes_max_lines

    def test_unknown_fields_are_ignored_not_fatal(self):
        """旧配置里残留的 pin_codebase 字段不应让解析崩溃 (只是被忽略)。"""
        cfg = {"prompt": {"tiers": {"compact": {"pin_codebase": True}}}}
        assert budgets_from_config(cfg)[COMPACT].skill_limit == prompt_tier.DEFAULT_TIER_BUDGETS[COMPACT].skill_limit

    def test_notes_max_lines_alias(self):
        """配置里用 notes_max_lines (与 memory.notes_max_lines 对齐) 作为别名。"""
        cfg = {"prompt": {"tiers": {"compact": {"notes_max_lines": 33}}}}
        assert budgets_from_config(cfg)[COMPACT].memory_notes_max_lines == 33

    def test_non_mapping_and_unknown_tier_are_ignored(self):
        cfg = {"prompt": {"tiers": {"weird": {"skill_limit": 1}}}}
        assert budgets_from_config(cfg) is None
        cfg2 = {"prompt": {"tiers": "oops"}}
        assert budgets_from_config(cfg2) is None


# ============================================================ 端到端解析

class TestResolvePromptBudget:
    def test_small_model_gets_compact(self):
        """低于 128k 的窗口才拿 compact 档。

        deepseek-chat 推断出的窗口正好是 128k, 按现行口径 (128k 起即大上下文)
        属于 full —— 所以这里显式声明 32k 来表达「小模型」语义。
        """
        cfg = {"model": {"provider": "deepseek", "model": "deepseek-chat",
                         "context_window": 32 * 1024}}
        tier, window, budget = resolve_prompt_budget(cfg)
        assert tier == COMPACT
        assert window == 32 * 1024
        assert budget == prompt_tier.DEFAULT_TIER_BUDGETS[COMPACT]

    def test_128k_model_is_large_context(self):
        """128k 恰好是大上下文下界 → full 档。"""
        cfg = {"model": {"provider": "deepseek", "model": "deepseek-chat"}}
        tier, window, _ = resolve_prompt_budget(cfg)
        assert window == 128 * 1024
        assert tier == FULL

    def test_large_model_gets_full(self):
        tier, window, budget = resolve_prompt_budget(
            None, model="claude-fable-5", provider="anthropic")
        assert tier == FULL
        assert window == 1_000_000
        assert budget == prompt_tier.DEFAULT_TIER_BUDGETS[FULL]

    def test_forced_tier_via_config(self):
        cfg = {
            "model": {"provider": "deepseek", "model": "deepseek-chat"},
            "prompt": {"tier": "full"},
        }
        tier, window, budget = resolve_prompt_budget(cfg)
        assert tier == FULL
        assert budget == prompt_tier.DEFAULT_TIER_BUDGETS[FULL]

    def test_config_window_override_drives_tier(self):
        """网关把 1M 模型截断到 32k 时, 应老实落到 compact 档。"""
        cfg = {
            "model": {"provider": "zhipu", "model": "glm-4-plus-1m", "context_window": 32768},
            "prompt": {"tier": "auto"},
        }
        tier, window, _ = resolve_prompt_budget(cfg)
        assert tier == COMPACT
        assert window == 32768

    def test_custom_threshold_via_config(self):
        cfg = {
            "model": {"provider": "anthropic", "model": "claude-sonnet-4-20250514"},
            "prompt": {"tier": "auto", "context_tier_threshold": 100_000},
        }
        tier, window, _ = resolve_prompt_budget(cfg)
        assert tier == FULL
        assert window == 200_000

    def test_configured_budgets_are_honored(self):
        cfg = {
            "model": {"provider": "deepseek", "model": "deepseek-chat",
                      "context_window": 32 * 1024},
            "prompt": {"tier": "auto", "tiers": {"compact": {"skill_limit": 5}}},
        }
        tier, _, budget = resolve_prompt_budget(cfg)
        assert tier == COMPACT
        assert budget.skill_limit == 5

    def test_invalid_tier_string_falls_back_to_auto(self):
        cfg = {"model": {"provider": "deepseek", "model": "deepseek-chat",
                         "context_window": 32 * 1024},
               "prompt": {"tier": "banana"}}
        tier, _, _ = resolve_prompt_budget(cfg)
        assert tier == COMPACT


# ============================================================ SOUL 换档

class TestResolveSoulTier:
    """两层开关: auto 只收缩预算, 显式 compact/full 才换用内置档位 SOUL。"""

    def test_auto_returns_empty_so_stable_prefix_is_legacy(self):
        assert resolve_soul_tier({"prompt": {"tier": "auto"}}) == ""
        assert resolve_soul_tier({}) == ""
        assert resolve_soul_tier(None) == ""

    def test_explicit_tiers_are_returned_as_given(self):
        assert resolve_soul_tier({"prompt": {"tier": "compact"}}) == "compact"
        assert resolve_soul_tier({"prompt": {"tier": "FULL"}}) == "full"

    def test_unknown_tier_string_is_ignored(self):
        assert resolve_soul_tier({"prompt": {"tier": "banana"}}) == ""

    def test_explicit_arg_overrides_config(self):
        assert resolve_soul_tier({"prompt": {"tier": "auto"}}, tier="compact") == "compact"

    def test_auto_does_not_swap_soul_in_agent(self, tmp_path, tuan_home):
        """auto 档下稳定前缀仍按历史方式从 SOUL.md + 规范段拼装。"""
        from tuan_cli.core.prompts import build_system_prompt_stable

        cfg = {"prompt": {"tier": "auto"}}
        agent = TestAgentTierIntegration()._agent(tmp_path, tuan_home,
                                                 provider="deepseek",
                                                 model="deepseek-chat",
                                                 context_window=32768)
        agent._soul_tier = resolve_soul_tier(cfg)
        prompt = agent._build_system()
        legacy = build_system_prompt_stable(agent.config.home, agent.workspace, tier="")
        # 稳定段的开头必须与「不传 tier」逐字节一致 (没有换成档位专用 SOUL)
        assert prompt.startswith(legacy.split("\n\n")[0][:60])
        assert "(Full Tier)" not in prompt
        assert "(Compact Tier)" not in prompt

    def test_explicit_compact_uses_bundled_soul(self, tmp_path, tuan_home):
        """显式 compact → 稳定前缀改用内置 SOUL_COMPACT.md, 并跳过额外规范段。"""
        agent = TestAgentTierIntegration()._agent(tmp_path, tuan_home,
                                                 provider="deepseek",
                                                 model="deepseek-chat",
                                                 context_window=32768)
        agent.config.set_user("prompt.tier", "compact")
        agent._soul_tier = resolve_soul_tier(agent.config)
        assert agent._soul_tier == "compact"
        prompt = agent._build_system()
        # 档位 SOUL 以**首行标题**标识 (SOUL_COMPACT.md / SOUL_FULL.md)。
        # 不能用 "SOUL_FULL.md" not in prompt 这类全文包含判断 —— 两个档位正文
        # 里互相引用了对方的文件名, 会恒真失败。
        first_line = prompt.splitlines()[0]
        assert first_line.startswith("# SOUL_COMPACT.md")
        assert len(prompt) < 20_000

    def test_explicit_full_uses_bundled_soul(self, tmp_path, tuan_home):
        """显式 full → 稳定前缀改用内置 SOUL_FULL.md (自包含全部规范)。"""
        agent = TestAgentTierIntegration()._agent(tmp_path, tuan_home,
                                                 provider="anthropic",
                                                 model="claude-fable-5",
                                                 context_window=1_000_000)
        agent.config.set_user("prompt.tier", "full")
        agent._soul_tier = resolve_soul_tier(agent.config)
        assert agent._soul_tier == "full"
        prompt = agent._build_system()
        # 同上: 判定首行标题, 不用全文包含 (两档正文互相引用对方文件名)。
        first_line = prompt.splitlines()[0]
        assert first_line.startswith("# SOUL_FULL.md")
        assert len(prompt) > 20_000

    def test_auto_large_window_reads_soul_full(self, tmp_path, tuan_home):
        """回归 (2026-10-18): auto 档 + 大上下文模型 (>=128k) 必须读 SOUL_FULL.md。

        旧行为: auto + full 预算档返回 "" (SOUL.md + 规范段, ~11K 字), 大模型只拿到
        一份阉割版提示词。现口径: 128k 以上即大上下文模型, 读 SOUL_FULL.md 完整提示词。
        """
        agent = TestAgentTierIntegration()._agent(tmp_path, tuan_home,
                                                 provider="sensenova",
                                                 model="sensenova-6.8-flash-lite",
                                                 context_window=0)
        # 无显式窗口 → 供应商未知 → 兜底 128k → full 档
        assert agent.context_window == 128 * 1024
        assert agent.prompt_tier == FULL
        # agent 层联动 (不是直接调 resolve_soul_tier —— 那个函数对 auto 仍返回 "")
        assert agent._soul_tier == "full"
        prompt = agent._system_prompt
        assert prompt.splitlines()[0].startswith("# SOUL_FULL.md")
        assert len(prompt) > 20_000

    def test_auto_small_window_reads_soul_compact(self, tmp_path, tuan_home):
        """auto 档 + 小上下文模型 (<128k) 只读 SOUL_COMPACT.md (小模型专属提示词)。"""
        agent = TestAgentTierIntegration()._agent(tmp_path, tuan_home,
                                                 provider="deepseek",
                                                 model="deepseek-chat",
                                                 context_window=32 * 1024)
        assert agent.prompt_tier == COMPACT
        assert agent._soul_tier == "compact"
        assert agent._system_prompt.splitlines()[0].startswith("# SOUL_COMPACT.md")


# ============================================================ Agent 集成

class TestAgentTierIntegration:
    def _agent(self, tmp_path, tuan_home, indexer=None, **model):
        from tuan_cli.app import build_kernel
        from tuan_cli.core.agent import Agent
        from tuan_cli.models.base import ModelAdapter, ModelResponse

        kernel = build_kernel()
        config = kernel.require("config")
        for key, value in model.items():
            config.set_user(f"model.{key}", value)

        class M(ModelAdapter):
            name = "m"
            def chat(self, messages, tools=None, stream=False, on_token=None, **kwargs):
                return ModelResponse(content="ok")

        kernel.unprovide("model_adapter")
        kernel.provide("model_adapter", M(), owner="test")
        return Agent(kernel=kernel, config=config, workspace=str(tmp_path),
                     confirm=lambda _p: True, indexer=indexer)

    @staticmethod
    def _fake_indexer():
        """提供一个最小假 indexer, 让代码库地图构建路径真的被走到。"""
        class _Map:
            @staticmethod
            def map_text():
                return "# 代码地图\nsrc/a.py"
        class _Idx:
            def build(self):
                return _Map()
        return _Idx()

    def test_small_window_yields_compact_tier(self, tmp_path, tuan_home):
        agent = self._agent(tmp_path, tuan_home, provider="deepseek",
                            model="deepseek-chat", context_window=32768)
        assert agent.prompt_tier == COMPACT
        assert agent.context_window == 32768
        # compact 档: 四个注入预算逐项收紧
        assert agent._effective_prompt_limits() == (2, 100, 12288, 800)

    def test_compact_tier_still_pins_codebase_map(self, tmp_path, tuan_home):
        """compact 档只收紧「量」, 不因分层偷偷移除代码库地图。"""
        agent = self._agent(tmp_path, tuan_home, indexer=self._fake_indexer(),
                            provider="deepseek", model="deepseek-chat",
                            context_window=32768)
        # 代码库地图改为后台构建 (不阻塞启动), 这里先等其完成再断言
        agent.await_codebase_index(timeout=2.0)
        assert agent.prompt_tier == COMPACT
        assert agent._codebase_map == "# 代码地图\nsrc/a.py"
        assert "代码地图" in agent._system_prompt

    def test_user_can_still_disable_codebase_map(self, tmp_path, tuan_home):
        """context.pin_codebase 是唯一开关, 分层不接管它。"""
        agent = self._agent(tmp_path, tuan_home, indexer=self._fake_indexer(),
                            provider="deepseek", model="deepseek-chat",
                            context_window=32768)
        agent.config.set_user("context.pin_codebase", False)
        assert agent._effective_prompt_limits() == (2, 100, 12288, 800)

    def test_large_window_yields_full_tier_and_legacy_budget(self, tmp_path, tuan_home):
        agent = self._agent(tmp_path, tuan_home, provider="anthropic",
                            model="claude-fable-5", context_window=1_000_000)
        assert agent.prompt_tier == FULL
        assert agent.context_window == 1_000_000
        # full 档 == 历史行为: 用户配置原样通过
        assert agent._effective_prompt_limits() == (3, 200, 32768, 1500)

    def test_tier_only_shrinks_user_budgets(self, tmp_path, tuan_home):
        """用户把预算调得比 compact 还小时, 用户值优先。"""
        kernel_agent = self._agent(tmp_path, tuan_home, provider="deepseek",
                                   model="deepseek-chat", context_window=32768)
        kernel_agent.config.set_user("skills.inject_limit", 1)
        kernel_agent.config.set_user("memory.notes_max_lines", 10)
        (skill_limit, notes_lines, _d, _l) = kernel_agent._effective_prompt_limits()
        assert skill_limit == 1
        assert notes_lines == 10

    def test_forced_full_uses_full_budget(self, tmp_path, tuan_home):
        agent = self._agent(tmp_path, tuan_home, provider="deepseek",
                            model="deepseek-chat", context_window=32768)
        agent.config.set_user("prompt.tier", "full")
        tier, window, budget = agent._resolve_prompt_tier()
        assert tier == FULL
        assert budget == prompt_tier.DEFAULT_TIER_BUDGETS[FULL]

    def test_full_tier_prompt_matches_builder_with_same_limits(self, tmp_path, tuan_home):
        """核心不变量: agent 的 system 提示 == build_system_prompt 输出 (同一预算下)。"""
        from tuan_cli.core.prompts import build_system_prompt

        agent = self._agent(tmp_path, tuan_home, provider="anthropic",
                            model="claude-fable-5", context_window=1_000_000)
        (skill_limit, notes_lines, doc_bytes, long_mem) = (
            agent._effective_prompt_limits()
        )
        expected = build_system_prompt(
            home=agent.config.home, workspace=agent.workspace,
            memory_store=agent.kernel.get("memory_store"),
            skill_manager=agent.kernel.get("skill_manager"),
            skill_limit=skill_limit,
            codebase_map=agent._codebase_map,
            reply_language=agent.config.get("language", "") or "zh-CN",
            output_style=agent.config.get("ui.output_style", "default"),
            cache_stable_prefix=agent.config.get("prompt.cache_stable_prefix", True),
            memory_notes_enabled=agent.config.get("memory.notes_enabled", True),
            memory_notes_max_lines=notes_lines,
            project_doc_max_bytes=doc_bytes,
            long_memory_max_chars=long_mem,
            user_mode=agent.user_mode,
            tier=agent._soul_tier,
        )
        assert agent._build_system() == expected
