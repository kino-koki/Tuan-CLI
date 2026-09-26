"""Agent 韧性组件 —— 从 Agent 拆出的独立模块。

职责:
- 带超时/重试/熔断的模型调用 (_chat_with_retry)
- 韧性状态查询 (resilience_status), 供 /status 展示
- 重试策略属性的兼容代理 (max_retries / retry_backoff 等)

三层防线:
  RateLimiter (令牌桶限流) → RetryPolicy (指数退避重试) → CircuitBreaker (熔断快失败)

拆出原因:
- Agent 中 _chat_with_retry + resilience_status + retry 属性代理合计 ~130 行,
  与 ReAct 主循环的职责边界模糊; 拆出后 Agent 只需组合 self._resilience = AgentResilience(...)
- DevLoop、Swarm Worker 等也需要韧性能力, 共享同一实现避免重复
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any, Callable, Dict, Optional

from .retry import RetryPolicy, RateLimiter, CircuitBreaker, classify_error

log = logging.getLogger(__name__)


class AgentResilience:
    """韧性组件: 三层防线封装 + 兼容代理。

    用法::

        res = AgentResilience(config, kernel)
        result = res.chat_with_retry(model, messages, tools, stream, on_token, on_reason)
        status = res.status()
    """

    def __init__(self, config: Any, kernel: Any) -> None:
        self.config = config
        self.kernel = kernel
        self.retry_policy = RetryPolicy.from_config(config)
        self._rate_limiter = RateLimiter.from_config(config)
        self._circuit_breaker = CircuitBreaker.from_config(config)

        # ---- 模型故障转移 (failover): 主供应商故障 → 切备用供应商, 保可用性 ----
        self.failover_enabled = bool(config.get("model.failover.enabled", True))
        # sticky 窗口: 备用成功后窗口内直接走备用, 不再重复打已故障的主模型
        self._sticky_seconds = float(config.get("model.failover.sticky_seconds", 120.0))
        # 备用候选缓存: (主 provider/model) → 备用适配器信息 (避免每次失败重建)
        self._fallback_cache: Dict[str, Any] = {}
        self._sticky: Optional[Dict[str, Any]] = None
        self._failover_count = 0
        # 备用调用只给 1 次重试 (原 + 1), 不给重试风暴
        self._fallback_retry = RetryPolicy(
            max_retries=min(self.retry_policy.max_retries, 2),
            backoff=self.retry_policy.backoff,
            jitter=self.retry_policy.jitter,
            retry_on=self.retry_policy.retry_on,
        )
        # 用户手动切换模型 (model.switched) → 清掉过期 sticky/缓存, 让新主模型直接接管
        on = getattr(kernel, "on", None)
        if on is not None:
            try:
                on("model.switched", self._on_model_switched)
            except Exception:  # noqa: BLE001
                pass

    # ------------------------------------------------------------ 故障转移

    def _on_model_switched(self, payload: Optional[Dict[str, Any]] = None) -> None:
        """用户热切换模型后, 旧的 sticky/缓存一律失效 (新主模型直接接管)。"""
        self._sticky = None
        self._fallback_cache.clear()

    def _refresh_sticky(self, model: Any) -> None:
        """主模型配置变化 (路由/热切换改了 provider/model) → 清 sticky。"""
        sticky = self._sticky
        if sticky is None:
            return
        cur_provider = self.config.get("model.provider")
        cur_model = self.config.get("model.model")
        if (sticky.get("from_provider") != cur_provider) or (sticky.get("from_model") != cur_model):
            self._sticky = None

    @staticmethod
    def _preset_tier(provider: str, model: str) -> int:
        """查当前 (provider, model) 在路由表中的档位 (1/2/3); 未知按 2 计。"""
        try:
            from ..models.router import MODEL_PRESETS
            tiers = [p.tier for p in MODEL_PRESETS if p.provider == provider and p.model == model]
            return max(tiers) if tiers else 2
        except Exception:  # noqa: BLE001
            return 2

    def _build_fallback_adapter(self, primary: Any) -> Optional[Dict[str, Any]]:
        """按候选顺序挑选备用供应商并构建适配器 (不改动用户配置, 线程安全)。

        候选规则:
        - 仅「已配置密钥」的供应商 (available_provider_names), 绝不切到无凭证端点;
        - 排除当前供应商 (同供应商所有模型通常同时故障);
        - 主模型有 vision 时, 优先候选也要有 vision (否则图片消息会静默失明);
        - 优先 tier >= 当前档位的候选 (不因故障转移降质), 无则退而求其次 (可用 > 完美);
        - 候选内按 (tier, 成本) 升序取最经济的。

        结果按 (主 provider/model) 缓存, 主模型不变则复用同一个备用适配器。
        """
        config = self.config
        cur_provider = config.get("model.provider")
        cur_model = config.get("model.model")
        key = f"{cur_provider}/{cur_model}"
        cached = self._fallback_cache.get(key)
        if cached is not None:
            return cached  # type: ignore[no-any-return]  # 缓存值来自 _resolve_fallback 的 Any
        try:
            from ..models.router import ModelRouter, MODEL_PRESETS
            if cur_provider == "anthropic":
                from ..models.anthropic import AnthropicAdapter as adapter_cls
            else:
                from ..models.openai_compat import OpenAICompatAdapter as adapter_cls  # type: ignore[assignment]  # 与 anthropic 分支同名 import
        except Exception:  # noqa: BLE001
            return None

        avail = set(ModelRouter.available_provider_names())
        avail.discard(cur_provider)
        if not avail:
            return None

        need_vision = bool(getattr(getattr(primary, "capabilities", None), "vision", False))
        candidates = [
            p for p in MODEL_PRESETS
            if p.provider in avail and (not need_vision or "vision" in p.capabilities)
        ]
        if not candidates:
            candidates = [p for p in MODEL_PRESETS if p.provider in avail]
        if not candidates:
            return None

        cur_tier = self._preset_tier(cur_provider, cur_model)
        same_or_higher = [p for p in candidates if p.tier >= cur_tier]
        pool = same_or_higher or candidates
        pool.sort(key=lambda p: (p.tier, p.cost_per_1k_input + p.cost_per_1k_output))
        fb = pool[0]

        api_key = os.environ.get(fb.api_key_env) or os.environ.get("QXT_API_KEY")
        adapter = adapter_cls(
            base_url=fb.base_url,
            model=fb.model,
            api_key=api_key,
            temperature=config.get("model.temperature", 0.7),
            max_tokens=config.get("model.max_tokens", 8192),
            timeout=config.get("model.timeout", 120),
            connect_timeout=config.get("model.connect_timeout", 10.0),
            read_timeout=float(config.get("model.read_timeout", 300.0)),
            prompt_cache=config.get("model.prompt_cache", True),
        )
        info = {"provider": fb.provider, "model": fb.model, "adapter": adapter}
        self._fallback_cache[key] = info
        return info

    def _call_fallback(
        self,
        fb: Dict[str, Any],
        messages: list,
        tools: list,
        stream: bool,
        on_token: Optional[Callable],
        on_reason: Optional[Callable],
        label: str,
    ) -> Any:
        """调用备用供应商 (限流 + 至多 1 次重试, 不套主模型熔断器)。"""
        adapter = fb["adapter"]
        fb_label = f"{label}→备用({fb['provider']}/{fb['model']})"
        self._rate_limiter.acquire()
        try:
            return self._fallback_retry.call(
                lambda: adapter.chat(
                    messages, tools=tools, stream=stream,
                    on_token=on_token, on_reason=on_reason,
                ),
                label=fb_label,
                emit=self.kernel.emit,
                on_rate_limit_notice=on_reason,
            )
        finally:
            self._rate_limiter.release()

    def _should_failover(self, exc: Exception) -> bool:
        """是否值得切备用: 可用性故障 (超时/网络/5xx/429/熔断) 才转移。

        鉴权失败 (4xx) 是配置问题而非供应商宕机, 转移会掩盖误配置且换谁都是
        401/403, 默认不转移 (model.failover.skip_auth 可关)。
        """
        if not self.failover_enabled:
            return False
        if self.config.get("model.failover.skip_auth", True):
            msg = str(exc)
            if "鉴权失败" in msg or "401" in msg or "403" in msg or "Authentication" in msg:
                return False
        return True

    def _failover(
        self,
        primary: Any,
        messages: list,
        tools: list,
        stream: bool,
        on_token: Optional[Callable],
        on_reason: Optional[Callable],
        label: str,
        primary_exc: Exception,
    ) -> Any:
        """主模型失败 → 切备用供应商完成本轮调用; 失败则抛出主异常 (贴近根因)。"""
        fb = self._build_fallback_adapter(primary)
        if fb is None:
            raise primary_exc
        try:
            result = self._call_fallback(fb, messages, tools, stream, on_token, on_reason, label)
        except Exception as exc:  # noqa: BLE001
            log.error("模型故障转移失败 (主 %s/%s 故障, 备用 %s/%s 也失败): %s",
                      self.config.get("model.provider"), self.config.get("model.model"),
                      fb["provider"], fb["model"], str(exc)[:160])
            raise primary_exc from exc

        self._failover_count += 1
        self._sticky = {
            "provider": fb["provider"], "model": fb["model"], "adapter": fb["adapter"],
            "from_provider": self.config.get("model.provider"),
            "from_model": self.config.get("model.model"),
            "until": time.monotonic() + self._sticky_seconds,
        }
        try:
            self.kernel.emit("model.failover", {
                "from_provider": self.config.get("model.provider"),
                "from_model": self.config.get("model.model"),
                "to_provider": fb["provider"],
                "to_model": fb["model"],
                "reason": str(primary_exc)[:160],
                "sticky_seconds": self._sticky_seconds,
            })
        except Exception:  # noqa: BLE001
            pass
        log.warning("模型故障转移: %s/%s → %s/%s (主模型故障: %s)",
                    self.config.get("model.provider"), self.config.get("model.model"),
                    fb["provider"], fb["model"], str(primary_exc)[:160])
        return result

    def chat_with_retry(
        self,
        model: Any,
        messages: list,
        tools: list,
        stream: bool,
        on_token: Optional[Callable] = None,
        on_reason: Optional[Callable] = None,
        label: str = "模型",
        fallback: bool = True,
    ) -> Any:
        """带超时/重试/熔断/故障转移的模型调用。

        韧性栈: RateLimiter(节流) + RetryPolicy(退避重试) + CircuitBreaker(熔断快失败)
        + Failover(主供应商宕机时切到已配置密钥的备用供应商)。
        """
        # 主模型配置变化 → 清 sticky (用户热切换 / 自动路由改模型后由新主直接接管)
        if fallback:
            self._refresh_sticky(model)

        # 主模型已输出部分 token 再失败 → 不转移 (重放会造成重复输出)
        tokens_emitted = [False]

        def _wrapped_on_token(t: str) -> None:
            tokens_emitted[0] = True
            if on_token is not None:
                on_token(t)

        def _attempt():
            self._rate_limiter.acquire()
            try:
                return self.retry_policy.call(
                    lambda: model.chat(
                        messages, tools=tools, stream=stream,
                        on_token=_wrapped_on_token, on_reason=on_reason,
                    ),
                    label=label,
                    emit=self.kernel.emit,
                    on_rate_limit_notice=on_reason,
                )
            finally:
                self._rate_limiter.release()

        # sticky 窗口内: 直接用备用 (主模型已知故障, 不重复打)
        sticky = self._sticky if fallback else None
        if sticky is not None and sticky.get("until", 0.0) > time.monotonic():
            try:
                return self._call_fallback(sticky, messages, tools, stream,
                                           on_token, on_reason, label)
            except Exception:  # noqa: BLE001
                self._sticky = None  # 备用也挂了 → 回到主路径 (主模型可能已恢复)
                log.debug("备用供应商调用失败, 回到主模型路径: %s", label)
        elif sticky is not None:
            # sticky 窗口过期: 清理, 回到主模型 (可能已恢复)
            self._sticky = None

        # 测试可能用 Agent.__new__ 跳过 __init__ (未设置 _circuit_breaker), 此时退化为直连
        breaker = getattr(self, "_circuit_breaker", None)
        try:
            if breaker is None:
                return _attempt()
            return breaker.call(_attempt, label=label)
        except Exception as exc:  # noqa: BLE001
            if (fallback and not tokens_emitted[0] and self._should_failover(exc)):
                return self._failover(model, messages, tools, stream,
                                      on_token, on_reason, label, exc)
            raise

    def status(self) -> Dict[str, Any]:
        """返回韧性组件 (熔断/限流/重试) 的运行状态, 供 /status 展示。"""
        breaker = self._circuit_breaker
        if breaker is None:
            breaker_state: Dict[str, Any] = {"enabled": False, "state": "closed"}
        else:
            breaker_state = breaker.stats()
            breaker_state.setdefault("failure_threshold", getattr(breaker, "failure_threshold", 0))
            breaker_state.setdefault("cooldown", getattr(breaker, "cooldown", 0.0))

        limiter = self._rate_limiter
        if limiter is None:
            limiter_info: Dict[str, Any] = {"active": False, "max_rpm": 0, "max_concurrent": 0}
        else:
            limiter_info = {
                "active": bool(getattr(limiter, "active", False)),
                "max_rpm": getattr(limiter, "rate", 0),
                "max_concurrent": getattr(limiter, "_max_concurrent", 0),
            }

        rp = self.retry_policy
        if rp is None:
            retry_info: Dict[str, Any] = {"max_retries": 0, "backoff": 0.0, "retry_on": []}
        else:
            retry_info = {
                "max_retries": getattr(rp, "max_retries", 0),
                "backoff": getattr(rp, "backoff", 0.0),
                "retry_on": sorted(getattr(rp, "retry_on", set())),
            }

        sticky = getattr(self, "_sticky", None)
        sticky_active = bool(sticky and sticky.get("until", 0.0) > time.monotonic())
        sticky_target = None
        if sticky_active and sticky:
            sticky_target = f"{sticky['provider']}/{sticky['model']}"
        failover_info: Dict[str, Any] = {
            "enabled": bool(getattr(self, "failover_enabled", False)),
            "count": int(getattr(self, "_failover_count", 0)),
            "active": sticky_active,
            "target": sticky_target,
            "sticky_seconds": float(getattr(self, "_sticky_seconds", 0.0)),
        }

        return {
            "circuit_breaker": breaker_state,
            "rate_limiter": limiter_info,
            "retry": retry_info,
            "failover": failover_info,
        }

    # ---- 兼容代理 (外部测试/调用方仍可读写 agent.max_retries 等) ----

    @property
    def max_retries(self) -> int:
        return self.retry_policy.max_retries

    @max_retries.setter
    def max_retries(self, v) -> None:
        self.retry_policy.max_retries = int(v)

    @property
    def retry_backoff(self) -> float:
        return self.retry_policy.backoff

    @retry_backoff.setter
    def retry_backoff(self, v) -> None:
        self.retry_policy.backoff = float(v)

    @property
    def retry_jitter(self) -> float:
        return self.retry_policy.jitter

    @retry_jitter.setter
    def retry_jitter(self, v) -> None:
        self.retry_policy.jitter = float(v)

    @property
    def retry_on(self) -> set:
        return self.retry_policy.retry_on

    @retry_on.setter
    def retry_on(self, v) -> None:
        self.retry_policy.retry_on = set(v)
