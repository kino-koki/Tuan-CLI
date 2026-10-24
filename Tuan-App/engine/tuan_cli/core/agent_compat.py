"""Agent 向后兼容属性层 —— 从 agent.py 提取的独立职责。

Agent 的韧性/可观测/路由状态自 v0.3 起分别落在 `_resilience` / `_obs` / `_router`
三个子组件上。但历史上这些属性直接挂在 Agent 实例上, 且测试常用 `Agent.__new__`
绕过 `__init__` 后直接赋值 (此时子组件不存在)。本模块把这些"组件转发 + fallback"
的兼容属性集中到一处, 让主类只保留编排逻辑。

用法:
    class Agent(CompatMixin, ...):
        pass
"""

from __future__ import annotations

from typing import Any, Optional, cast

from .retry import classify_error as _classify_error, retry_after_seconds as _retry_after_seconds


class CompatMixin:
    """向后兼容属性: 转发到子组件, 组件缺失时回退到实例 __dict__。

    测试可能用 Agent.__new__ 绕过 __init__, 直接设置这些属性。
    property 只在 __init__ 完成后生效; __new__ 绕过时仍可直接赋值。
    统一用 _get_fallback / _set_fallback 消除重复的 if/else 模式。
    """

    # 由 Agent.__init__ 注入的子组件; 类型标注仅为 IDE/类型检查提示
    _router: Any
    _resilience: Any
    _obs: Any

    def _get_fallback(self, component: str, attr: str, fallback_key: str):
        """从子组件读取属性, 组件不存在时回退到 __dict__ fallback。"""
        comp = self.__dict__.get(component)
        if comp is not None:
            return getattr(comp, attr)
        return self.__dict__.get(fallback_key)

    def _set_fallback(self, component: str, attr: str, fallback_key: str, value):
        """向子组件设置属性, 组件不存在时写入 __dict__ fallback。"""
        comp = self.__dict__.get(component)
        if comp is not None:
            setattr(comp, attr, value)
        else:
            self.__dict__[fallback_key] = value

    @property
    def _last_route(self):
        return self._router.last_route

    @_last_route.setter
    def _last_route(self, v):
        self._router.last_route = v

    @property
    def _model_switcher(self):
        return self._router._model_switcher

    @_model_switcher.setter
    def _model_switcher(self, v):
        self._router._model_switcher = v

    @property
    def _circuit_breaker(self):
        return self._get_fallback('_resilience', '_circuit_breaker', '_cb_fallback')

    @_circuit_breaker.setter
    def _circuit_breaker(self, v):
        self._set_fallback('_resilience', '_circuit_breaker', '_cb_fallback', v)

    @property
    def _rate_limiter(self):
        return self._get_fallback('_resilience', '_rate_limiter', '_rl_fallback')

    @_rate_limiter.setter
    def _rate_limiter(self, v):
        self._set_fallback('_resilience', '_rate_limiter', '_rl_fallback', v)

    @property
    def _telemetry(self):
        return self._get_fallback('_obs', 'telemetry', '_tel_fallback')

    @_telemetry.setter
    def _telemetry(self, v):
        self._set_fallback('_obs', '_telemetry', '_tel_fallback', v)

    @property
    def _telemetry_trace(self):
        return self._get_fallback('_obs', 'trace_id', '_trace_fallback')

    @_telemetry_trace.setter
    def _telemetry_trace(self, v):
        self._set_fallback('_obs', 'trace_id', '_trace_fallback', v)

    @property
    def retry_policy(self):
        return self._get_fallback('_resilience', 'retry_policy', 'retry_policy')

    @retry_policy.setter
    def retry_policy(self, v):
        self._set_fallback('_resilience', 'retry_policy', 'retry_policy', v)

    @property
    def max_retries(self) -> int:
        return cast(int, self._resilience.max_retries)

    @max_retries.setter
    def max_retries(self, v) -> None:
        self._resilience.max_retries = int(v)

    @property
    def retry_backoff(self) -> float:
        return cast(float, self._resilience.retry_backoff)

    @retry_backoff.setter
    def retry_backoff(self, v) -> None:
        self._resilience.retry_backoff = float(v)

    @property
    def retry_jitter(self) -> float:
        return cast(float, self._resilience.retry_jitter)

    @retry_jitter.setter
    def retry_jitter(self, v) -> None:
        self._resilience.retry_jitter = float(v)

    @property
    def retry_on(self) -> set:
        return cast(set, self._resilience.retry_on)

    @retry_on.setter
    def retry_on(self, v) -> None:
        self._resilience.retry_on = set(v)

    @staticmethod
    def _classify(exc: Exception):
        return _classify_error(exc)

    @staticmethod
    def _retry_after(exc: Exception) -> Optional[float]:
        return _retry_after_seconds(exc)
