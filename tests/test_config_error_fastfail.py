"""P0 回归: 配置类错误应快速失败且渲染 C-2 友好模板, 且不触发故障转移。

回归背景:
- 旧实现把「缺 API Key / 配置损坏 / 模型不存在」当作瞬时错误, 按指数退避重试
  3 次 (~18s) 才失败, 观感是「卡住十几秒然后报错」。
- 模型错误在 LoopProvider 主循环路径未渲染 C-2 固定友好模板, 只给用户一坨
  原始异常信息。
- 配置类错误还会错误地触发「故障转移」, 白跑备用供应商。
"""

import time

from tuan_cli.core import errors
from tuan_cli.core.retry import RetryPolicy, is_fatal_error
from tuan_cli.core.loop_provider import _render_model_error


def test_is_fatal_error_classifies_business_kinds():
    assert is_fatal_error(errors.ConfigError("缺 key")) is True
    assert is_fatal_error(errors.AuthError("无效 key")) is True
    assert is_fatal_error(errors.ModelError("无此模型")) is True
    # 瞬时错误不应判为 fatal (仍需重试)
    assert is_fatal_error(errors.NetworkError("连不上")) is False
    assert is_fatal_error(RuntimeError("抖动")) is False


def test_fatal_error_no_retry_no_delay():
    """配置错误必须立即失败: 不重试、不退避等待。"""
    policy = RetryPolicy(max_retries=3, backoff=2.0, jitter=0.0, sleep=lambda s: None)
    calls = {"n": 0}

    def boom():
        calls["n"] += 1
        raise errors.ConfigError("未配置 API Key。请运行 tuan setup")

    t0 = time.monotonic()
    try:
        policy.call(boom, label="模型")
    except errors.ConfigError:
        pass
    elapsed = time.monotonic() - t0
    assert calls["n"] == 1, "配置错误不应被重试"
    assert elapsed < 1.0, f"配置错误应 <1s 失败, 实际 {elapsed:.2f}s"


def test_friendly_render_for_config_error():
    e = errors.ConfigError("未配置 API Key")
    tmpl = errors.friendly_for(e)
    assert tmpl is not None
    assert tmpl.kind == "config"
    rendered = _render_model_error(e)
    assert rendered.startswith("❌ "), "业务错误应渲染为 C-2 友好模板"


def test_render_model_error_falls_back_to_raw_for_plain_exc():
    assert _render_model_error(RuntimeError("抖动")) == "抖动"


def test_should_failover_skips_business_errors():
    """配置/鉴权/模型类错误绝不故障转移 (换谁都一样失败, 转移只会掩盖根因)。"""
    import tuan_cli.core.resilience as res

    class _Cfg:
        def get(self, key, default=None):
            return default

    class _Stub:
        failover_enabled = True
        config = _Cfg()

    stub = _Stub()
    assert res.AgentResilience._should_failover(stub, errors.ConfigError("缺 key")) is False
    assert res.AgentResilience._should_failover(stub, errors.AuthError("无效")) is False
    assert res.AgentResilience._should_failover(stub, errors.ModelError("无模型")) is False
    # 纯网络抖动仍允许转移
    assert res.AgentResilience._should_failover(stub, errors.NetworkError("连不上")) is True


def test_agent_run_config_error_fast_fail_and_friendly(tmp_path, tuan_home):
    """端到端: agent.run 遇到配置错误, on_error 收到友好模板, 且快速失败。"""
    from tuan_cli.core.agent import Agent
    from tuan_cli.app import build_kernel
    from tuan_cli.models.base import ModelAdapter

    class ConfigErrorModel(ModelAdapter):
        name = "cfg-err"

        def chat(self, messages, tools=None, stream=False, on_token=None, **kwargs):
            raise errors.ConfigError("未配置 API Key。请运行 tuan setup")

    kernel = build_kernel()
    config = kernel.require("config")
    config.data.setdefault("agent", {})["max_retries"] = 3
    kernel.unprovide("model_adapter")
    kernel.provide("model_adapter", ConfigErrorModel(), owner="test")
    agent = Agent(kernel=kernel, config=config, workspace=str(tmp_path), confirm=lambda _p: True)

    errors_list = []
    t0 = time.monotonic()
    out = agent.run("hi", stream=False, on_error=lambda m: errors_list.append(m))
    elapsed = time.monotonic() - t0

    assert any(m.startswith("❌") for m in errors_list), f"on_error 应收到友好模板: {errors_list}"
    assert "模型错误" in out, "answer 协议前缀仍保留"
    assert elapsed < 3.0, f"配置错误应快速失败, 实际 {elapsed:.2f}s"
