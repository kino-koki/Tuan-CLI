"""effort 链路穿透测试: config.agent.effort -> ProviderConfig -> AnthropicChatProvider.thinking_effort。"""

from qingxiaotuan.config import Config
from qingxiaotuan.models.kernel_adapter import create_kernel_adapter
from qingxiaotuan.runtime.provider_service import ProviderConfig, build_provider
from qingxiaotuan.runtime.providers.anthropic import AnthropicChatProvider


def test_provider_config_effort_reaches_anthropic_provider():
    """ProviderConfig.effort 经 build_provider 注入 Anthropic provider.thinking_effort。"""
    cfg = ProviderConfig(type="anthropic", model="claude-fable-5",
                         api_key="test", effort="low")
    provider = build_provider(cfg)
    assert isinstance(provider, AnthropicChatProvider)
    assert provider.thinking_effort == "low"


def test_provider_config_effort_default_none():
    """未指定 effort 时保持旧行为 (None, 不下发 thinking 参数)。"""
    cfg = ProviderConfig(type="anthropic", model="claude-sonnet-4-20250514",
                         api_key="test")
    provider = build_provider(cfg)
    assert provider.thinking_effort is None


def test_kernel_adapter_reads_agent_effort(qxt_home):
    """create_kernel_adapter 从 config.agent.effort 读取并注入 provider。"""
    config = Config()
    config.ensure_home()
    config.set_user("agent.effort", "medium")
    config.set_user("model.provider", "anthropic")
    config.set_user("model.model", "claude-fable-5")
    adapter = create_kernel_adapter(config)
    assert adapter._provider.thinking_effort == "medium"


def test_kernel_adapter_default_effort_high(qxt_home):
    """未配置 effort 时默认 high (defaults.py 同款口径)。"""
    config = Config()
    config.ensure_home()
    config.set_user("model.provider", "anthropic")
    config.set_user("model.model", "claude-fable-5")
    adapter = create_kernel_adapter(config)
    assert adapter._provider.thinking_effort == "high"


def test_effort_survives_slash_set_roundtrip(qxt_home):
    """/effort 写入配置 -> adapter 重建 -> provider effort 生效 (闭环)。"""
    config = Config()
    config.ensure_home()
    config.set_user("agent.effort", "low")
    config.set_user("model.provider", "anthropic")
    config.set_user("model.model", "claude-fable-5")
    a1 = create_kernel_adapter(config)
    assert a1._provider.thinking_effort == "low"
    # 切换档位
    config.set_user("agent.effort", "high")
    a2 = create_kernel_adapter(config)
    assert a2._provider.thinking_effort == "high"
