"""模型故障转移测试 (Failover) —— 主供应商故障时自动切到备用供应商。

验证:
- 主模型失败 → 备用供应商被调用, 本轮任务不中断;
- sticky 窗口: 备用成功后窗口内直接走备用, 主模型不再被重复打;
- 备用也失败 → 抛出主异常 (贴近根因);
- 鉴权失败 (4xx) → 不转移 (配置问题而非宕机);
- 主模型已输出部分 token 再失败 → 不转移 (避免重复输出);
- 用户热切换模型 (model.switched) → sticky/缓存失效。
"""

import time

import pytest

from qingxiaotuan.core.resilience import AgentResilience
from qingxiaotuan.app import build_kernel
from qingxiaotuan.models.base import ModelAdapter, ModelResponse, ModelCapabilities


class FailingModel(ModelAdapter):
    """主模型: 每次 chat 都抛错。"""

    name = "failing"

    def __init__(self, exc=RuntimeError("上游 500")):
        self._exc = exc
        self.calls = 0

    capabilities = ModelCapabilities(tool_calling=True, function_calling=True)

    def chat(self, messages, tools=None, stream=False, on_token=None, **kwargs):
        self.calls += 1
        raise self._exc


class OkModel(ModelAdapter):
    """备用模型: 固定返回成功。"""

    name = "ok"

    def __init__(self, content="备用成功"):
        self.content = content
        self.calls = 0

    capabilities = ModelCapabilities(tool_calling=True, function_calling=True)

    def chat(self, messages, tools=None, stream=False, on_token=None, **kwargs):
        self.calls += 1
        if stream and on_token:
            on_token(self.content)
        return ModelResponse(content=self.content)


class AuthError(RuntimeError):
    """模拟鉴权失败 (openai 风格, 带 status_code)。"""

    status_code = 401


def _make_resilience(qxt_home, monkeypatch, **env_keys):
    kernel = build_kernel()
    config = kernel.require("config")
    config.data.setdefault("model", {})["provider"] = "deepseek"
    config.data["model"]["model"] = "deepseek-chat"
    for name, value in env_keys.items():
        monkeypatch.setenv(name, value)
    res = AgentResilience(config, kernel)
    return kernel, config, res


def _fake_fallback(res, fallback):
    """注入固定的备用适配器 (跳过真实候选构建, 专注转移流程)。"""
    res._build_fallback_adapter = lambda primary: {
        "provider": "qwen", "model": "qwen-plus", "adapter": fallback,
    }


def test_failover_switches_to_secondary(tmp_path, qxt_home, monkeypatch):
    kernel, config, res = _make_resilience(qxt_home, monkeypatch, DASHSCOPE_API_KEY="sk-test")
    primary = FailingModel()
    fallback = OkModel()
    _fake_fallback(res, fallback)

    result = res.chat_with_retry(primary, [{"role": "user", "content": "hi"}],
                                 [], stream=False)

    assert result.content == "备用成功"
    assert primary.calls == 3  # 重试预算(3次)耗尽后才转移
    assert fallback.calls == 1
    assert res._failover_count == 1
    assert res._sticky is not None
    assert res._sticky["provider"] == "qwen"
    # sticky 窗口内: 再调用直接走备用, 主模型不再被打
    res.chat_with_retry(primary, [{"role": "user", "content": "hi2"}], [], stream=False)
    assert primary.calls == 3
    assert fallback.calls == 2


def test_failover_raises_primary_when_fallback_also_fails(tmp_path, qxt_home, monkeypatch):
    kernel, config, res = _make_resilience(qxt_home, monkeypatch, DASHSCOPE_API_KEY="sk-test")
    primary = FailingModel(exc=RuntimeError("primary down"))
    _fake_fallback(res, FailingModel(exc=RuntimeError("fallback down")))

    with pytest.raises(RuntimeError, match="primary down"):
        res.chat_with_retry(primary, [{"role": "user", "content": "hi"}], [], stream=False)


def test_auth_failure_does_not_failover(tmp_path, qxt_home, monkeypatch):
    kernel, config, res = _make_resilience(qxt_home, monkeypatch, DASHSCOPE_API_KEY="sk-test")
    primary = FailingModel(exc=AuthError("401 Unauthorized"))
    fallback = OkModel()
    _fake_fallback(res, fallback)

    with pytest.raises(RuntimeError):
        res.chat_with_retry(primary, [{"role": "user", "content": "hi"}], [], stream=False)
    assert fallback.calls == 0
    assert res._failover_count == 0


def test_partial_tokens_do_not_failover(tmp_path, qxt_home, monkeypatch):
    kernel, config, res = _make_resilience(qxt_home, monkeypatch, DASHSCOPE_API_KEY="sk-test")

    class PartialThenFail(ModelAdapter):
        capabilities = ModelCapabilities(tool_calling=True)

        def chat(self, messages, tools=None, stream=False, on_token=None, **kwargs):
            if on_token:
                on_token("部分输出")  # 先吐 token 再挂
            raise RuntimeError("mid-stream error")

    fallback = OkModel()
    _fake_fallback(res, fallback)
    with pytest.raises(RuntimeError):
        res.chat_with_retry(PartialThenFail(), [{"role": "user", "content": "hi"}],
                            [], stream=True)
    assert fallback.calls == 0


def test_model_switched_clears_sticky(tmp_path, qxt_home, monkeypatch):
    kernel, config, res = _make_resilience(qxt_home, monkeypatch, DASHSCOPE_API_KEY="sk-test")
    primary = FailingModel()
    fallback = OkModel()
    _fake_fallback(res, fallback)

    res.chat_with_retry(primary, [{"role": "user", "content": "hi"}], [], stream=False)
    assert res._sticky is not None

    # 用户热切换模型 → 内核广播 model.switched → sticky 失效
    kernel.emit("model.switched", {"provider": "qwen", "model": "qwen-plus"})
    assert res._sticky is None
    assert res._fallback_cache == {}


def test_build_fallback_adapter_picks_configured_provider(tmp_path, qxt_home, monkeypatch):
    """真实候选逻辑: 只选已配置密钥的供应商, 排除当前供应商, 缓存复用。"""
    kernel, config, res = _make_resilience(qxt_home, monkeypatch,
                                           DASHSCOPE_API_KEY="sk-qwen",
                                           ZHIPU_API_KEY="sk-zhipu")
    primary = OkModel()

    info1 = res._build_fallback_adapter(primary)
    assert info1 is not None
    assert info1["provider"] in ("qwen", "zhipu")
    assert info1["provider"] != "deepseek"

    info2 = res._build_fallback_adapter(primary)
    assert info2 is info1  # 缓存复用


def test_no_candidate_no_failover(tmp_path, qxt_home, monkeypatch):
    """没有任何已配置密钥的备用供应商 → 不转移, 原样抛主异常。"""
    kernel, config, res = _make_resilience(qxt_home, monkeypatch)
    primary = FailingModel()

    with pytest.raises(RuntimeError, match="上游 500"):
        res.chat_with_retry(primary, [{"role": "user", "content": "hi"}], [], stream=False)


def test_failover_disabled_via_config(tmp_path, qxt_home, monkeypatch):
    kernel = build_kernel()
    config = kernel.require("config")
    config.data.setdefault("model", {})["provider"] = "deepseek"
    config.data["model"]["model"] = "deepseek-chat"
    config.data.setdefault("model", {})["failover"] = {"enabled": False}
    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-test")
    res = AgentResilience(config, kernel)
    primary = FailingModel()
    fallback = OkModel()
    _fake_fallback(res, fallback)

    with pytest.raises(RuntimeError):
        res.chat_with_retry(primary, [{"role": "user", "content": "hi"}], [], stream=False)
    assert fallback.calls == 0


def test_status_reports_failover(tmp_path, qxt_home, monkeypatch):
    kernel, config, res = _make_resilience(qxt_home, monkeypatch, DASHSCOPE_API_KEY="sk-test")
    status = res.status()
    assert status["failover"]["enabled"] is True
    assert status["failover"]["count"] == 0
    assert status["failover"]["active"] is False
