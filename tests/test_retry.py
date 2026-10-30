"""RetryPolicy / RateLimiter / CircuitBreaker / 错误分类 —— 韧性组件核心。

注入 sleep/rng/clock, 避免任何真等待; 用带 status_code 的假异常走分类分支。
"""
from __future__ import annotations

import threading
import time

import pytest

from tuan_cli.core.errors import (
    AuthError,
    ConfigError,
    ModelError,
    NetworkError,
    ProviderError,
)
from tuan_cli.core.retry import (
    MAX_BACKOFF_WAIT,
    CircuitBreaker,
    CircuitOpen,
    RateLimiter,
    RetryPolicy,
    StreamInterrupted,
    classify_error,
    is_fatal_error,
    retry_after_seconds,
)


# ------------------------------------------------------------ 假异常

class FakeStatusError(Exception):
    """带 HTTP 状态码的异常, 供分类分支。"""

    def __init__(self, status_code: int, message: str = "boom") -> None:
        super().__init__(message)
        self.status_code = status_code


class FakeResponse:
    def __init__(self, headers: dict) -> None:
        self.headers = headers


class FakeRespExc(Exception):
    def __init__(self, headers: dict) -> None:
        super().__init__("resp")
        self.response = FakeResponse(headers)


def _no_sleep(seconds: float) -> None:  # noqa: ARG001
    pass


def _no_rng(lo: float, hi: float) -> float:  # noqa: ARG001
    return 0.0


# ------------------------------------------------------------ 错误分类

def test_classify_error_plain_exception_other():
    assert classify_error(Exception("x")) == ("other", None)


def test_classify_error_rate_limit_by_status():
    assert classify_error(FakeStatusError(429)) == ("rate_limit", 429)


def test_classify_error_rate_limit_by_message():
    # 分类优先级: rate_limit 优先于 server —— status 500 + 文案命中限流 → rate_limit
    assert classify_error(FakeStatusError(500, "too many requests")) == ("rate_limit", 500)


def test_classify_error_auth():
    assert classify_error(FakeStatusError(401)) == ("auth", 401)
    assert classify_error(FakeStatusError(403)) == ("auth", 403)


def test_classify_error_server():
    assert classify_error(FakeStatusError(503)) == ("server", 503)


def test_classify_error_timeout_by_status():
    assert classify_error(FakeStatusError(408)) == ("timeout", 408)


def test_classify_error_timeout_by_message():
    # 有 status_code 属性才委托分类; status=0 + 文案命中 timeout → timeout (兜底 408)
    assert classify_error(FakeStatusError(0, "read timeout")) == ("timeout", 408)
    # 有 500 状态码会被 server 分支抢先
    assert classify_error(FakeStatusError(500, "read timeout")) == ("server", 500)


def test_classify_error_other_status():
    assert classify_error(FakeStatusError(400, "bad")) == ("other", 400)


# ------------------------------------------------------------ is_fatal_error

def test_is_fatal_error_tuan_cli_kinds():
    assert is_fatal_error(ConfigError("x")) is True
    assert is_fatal_error(ModelError("x")) is True
    assert is_fatal_error(AuthError("x")) is True
    assert is_fatal_error(ProviderError("x")) is False
    assert is_fatal_error(NetworkError("x")) is False


def test_is_fatal_error_config_markers():
    assert is_fatal_error(Exception("未配置 api key")) is True
    assert is_fatal_error(Exception("请运行 `tuan setup` 完成配置")) is True
    assert is_fatal_error(Exception("api key 未配置")) is True


def test_is_fatal_error_false_for_other():
    assert is_fatal_error(Exception("connection reset by peer")) is False


# ------------------------------------------------------------ retry_after_seconds

def test_retry_after_seconds_parses():
    assert retry_after_seconds(FakeRespExc({"retry-after": "3.5"})) == 3.5
    assert retry_after_seconds(FakeRespExc({"Retry-After": "2"})) == 2.0


def test_retry_after_seconds_none_cases():
    assert retry_after_seconds(Exception("x")) is None
    assert retry_after_seconds(FakeRespExc({"retry-after": "abc"})) is None
    assert retry_after_seconds(FakeRespExc({})) is None


# ------------------------------------------------------------ RetryPolicy.wait_for

def test_wait_for_exponential_backoff_no_jitter():
    p = RetryPolicy(backoff=2.0, jitter=0.0, rng=_no_rng, sleep=_no_sleep)
    assert p.wait_for(1, "other", Exception()) == 2.0
    assert p.wait_for(2, "other", Exception()) == 4.0
    assert p.wait_for(3, "other", Exception()) == 8.0


def test_wait_for_rate_limit_respects_retry_after():
    p = RetryPolicy(backoff=2.0, jitter=0.0, rng=_no_rng, sleep=_no_sleep)
    assert p.wait_for(1, "rate_limit", FakeRespExc({"retry-after": "7"})) == 7.0


def test_wait_for_rate_limit_no_header_falls_back_to_exponential():
    p = RetryPolicy(backoff=2.0, jitter=0.0, rng=_no_rng, sleep=_no_sleep)
    assert p.wait_for(2, "rate_limit", Exception()) == 4.0


def test_wait_for_jitter_added():
    p = RetryPolicy(backoff=2.0, jitter=0.5,
                    rng=lambda lo, hi: 0.3, sleep=_no_sleep)
    assert p.wait_for(1, "other", Exception()) == 2.3


def test_wait_for_capped_at_max_backoff():
    p = RetryPolicy(backoff=100.0, jitter=0.0, rng=_no_rng, sleep=_no_sleep)
    assert p.wait_for(3, "other", Exception()) == MAX_BACKOFF_WAIT


# ------------------------------------------------------------ RetryPolicy.call

def test_call_success_first_try():
    calls = []
    p = RetryPolicy(max_retries=3, sleep=_no_sleep, rng=_no_rng)
    r = p.call(lambda: calls.append(1) or "ok")
    assert r == "ok"
    assert len(calls) == 1


def test_call_retries_then_success():
    calls = []
    sleeps = []
    p = RetryPolicy(max_retries=3, sleep=sleeps.append, rng=_no_rng)

    def fn():
        calls.append(1)
        if len(calls) == 1:
            raise ConnectionError("reset")
        return "ok"

    assert p.call(fn) == "ok"
    assert len(calls) == 2
    assert len(sleeps) == 1  # 第 1 次失败后等待一次


def test_call_exhausts_retries_raises_runtime_error():
    calls = []
    sleeps = []
    p = RetryPolicy(max_retries=3, sleep=sleeps.append, rng=_no_rng)

    def fn():
        calls.append(1)
        raise ConnectionError("always down")

    with pytest.raises(RuntimeError) as ei:
        p.call(fn)
    assert len(calls) == 3
    assert len(sleeps) == 2
    assert isinstance(ei.value.__cause__, ConnectionError)


def test_call_stream_interrupted_not_retried():
    calls = []
    p = RetryPolicy(max_retries=3, sleep=_no_sleep, rng=_no_rng)

    def fn():
        calls.append(1)
        raise StreamInterrupted("broke mid-stream")

    with pytest.raises(StreamInterrupted):
        p.call(fn)
    assert len(calls) == 1  # 不重试


def test_call_fatal_error_not_retried_preserves_type():
    calls = []
    p = RetryPolicy(max_retries=3, sleep=_no_sleep, rng=_no_rng)

    def fn():
        calls.append(1)
        raise ConfigError("missing key")

    with pytest.raises(ConfigError):
        p.call(fn)
    assert len(calls) == 1


def test_call_auth_raises_runtime_error():
    p = RetryPolicy(max_retries=3, sleep=_no_sleep, rng=_no_rng)
    with pytest.raises(RuntimeError) as ei:
        p.call(lambda: (_ for _ in ()).throw(FakeStatusError(401)))
    assert "鉴权失败" in str(ei.value)


def test_call_status_not_in_retry_on_not_retried():
    calls = []
    p = RetryPolicy(max_retries=3, sleep=_no_sleep, rng=_no_rng)

    def fn():
        calls.append(1)
        raise FakeStatusError(400, "bad request")

    with pytest.raises(RuntimeError):
        p.call(fn)
    assert len(calls) == 1


def test_call_status_in_retry_on_retried():
    calls = []
    sleeps = []
    p = RetryPolicy(max_retries=3, sleep=sleeps.append, rng=_no_rng)

    def fn():
        calls.append(1)
        if len(calls) == 1:
            raise FakeStatusError(500, "server error")
        return "ok"

    assert p.call(fn) == "ok"
    assert len(calls) == 2
    assert len(sleeps) == 1


def test_call_timeout_converges_early():
    """超时类错误按 max_timeout_retries 单独收敛, 不走到满额重试。"""
    calls = []
    sleeps = []
    p = RetryPolicy(max_retries=5, max_timeout_retries=2,
                    sleep=sleeps.append, rng=_no_rng)

    def fn():
        calls.append(1)
        raise FakeStatusError(408, "read timeout")

    with pytest.raises(RuntimeError):
        p.call(fn)
    assert len(calls) == 2  # 收敛于 2 次尝试, 而非 5 次
    assert len(sleeps) == 1


def test_call_emits_retry_event():
    events = []
    sleeps = []
    calls = []
    p = RetryPolicy(max_retries=3, sleep=sleeps.append, rng=_no_rng)

    def fn():
        calls.append(1)
        if len(calls) == 1:
            raise FakeStatusError(429, "rate limit")
        return "ok"

    p.call(fn, emit=lambda name, payload: events.append((name, payload)))
    assert events and events[0][0] == "model.retry"
    payload = events[0][1]
    assert payload["attempt"] == 1
    assert payload["kind"] == "rate_limit"
    assert payload["status"] == 429
    assert payload["wait"] >= 0
    assert "error" in payload


def test_call_rate_limit_notice():
    notices = []
    sleeps = []
    p = RetryPolicy(max_retries=3, sleep=sleeps.append, rng=_no_rng)
    with pytest.raises(RuntimeError):
        p.call(
            lambda: (_ for _ in ()).throw(FakeStatusError(429, "rate limit")),
            on_rate_limit_notice=notices.append,
        )
    assert notices and "限流" in notices[0]


def test_retry_policy_from_config():
    cfg = {
        "agent.max_retries": 5,
        "agent.retry_backoff": 3.0,
        "agent.retry_jitter": 0.1,
        "agent.retry_on": [500, 503],
        "agent.max_timeout_retries": 4,
    }
    p = RetryPolicy.from_config(cfg)
    assert p.max_retries == 5
    assert p.backoff == 3.0
    assert p.jitter == 0.1
    assert p.retry_on == {500, 503}
    assert p.max_timeout_retries == 4


# ------------------------------------------------------------ RateLimiter

def test_rate_limiter_inactive_when_zero():
    rl = RateLimiter(0, 0, sleep=_no_sleep, clock=time.monotonic)
    assert rl.active is False
    rl.acquire()  # 不限速不限并发, 直接通过
    rl.release()


def test_rate_limiter_token_bucket_blocks_second():
    """rate=1/min: 第一次通过, 第二次需等令牌回填。"""
    now = [0.0]

    def clock():
        return now[0]

    def sleep(s):
        now[0] += s

    rl = RateLimiter(max_requests_per_minute=1, sleep=sleep, clock=clock)
    assert rl.active is True
    rl.acquire()  # tokens=1 -> 0, 立即返回
    rl.acquire()  # tokens=0 -> 等待 60s 回填
    # 第二次 acquire 成功, 说明 sleep 推进时钟后令牌回填
    assert now[0] >= 60.0


def test_rate_limiter_refills_over_time():
    now = [0.0]

    def clock():
        return now[0]

    def sleep(s):
        now[0] += s

    rl = RateLimiter(max_requests_per_minute=60, sleep=sleep, clock=clock)
    rl.acquire()  # 60 -> 59
    now[0] += 1.0  # 1s 后回填 1 个
    rl.acquire()  # 不阻塞 (59+1=60 -> 59)
    rl.acquire()  # 59 -> 58
    rl.acquire()  # 58 -> 57


def test_rate_limiter_concurrent_semaphore():
    rl = RateLimiter(max_requests_per_minute=0, max_concurrent=1,
                     sleep=_no_sleep, clock=time.monotonic)
    assert rl.active is True
    rl.acquire()  # 占用唯一槽位
    done = threading.Event()

    def worker():
        rl.acquire()
        done.set()
        rl.release()

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    assert not done.wait(0.2)  # 第二个请求被信号量阻塞
    rl.release()  # 释放槽位 -> 线程得以进入
    assert done.wait(2.0)
    t.join(2.0)


def test_rate_limiter_from_config_disabled():
    rl = RateLimiter.from_config({})
    assert rl.active is False


def test_rate_limiter_from_config_enabled():
    rl = RateLimiter.from_config({
        "model.rate_limit.enabled": True,
        "model.rate_limit.max_requests_per_minute": 30,
        "model.rate_limit.max_concurrent": 2,
    })
    assert rl.rate == 30
    assert rl.active is True


# ------------------------------------------------------------ CircuitBreaker

def _mk_clock(now):
    return lambda: now[0]


def test_circuit_breaker_closed_passes_success():
    now = [0.0]
    cb = CircuitBreaker(failure_threshold=2, cooldown=30, clock=_mk_clock(now))
    assert cb.state == CircuitBreaker.CLOSED
    assert cb.call(lambda: "ok") == "ok"
    assert cb.state == CircuitBreaker.CLOSED
    assert cb.stats()["failures"] == 0


def test_circuit_breaker_trips_after_threshold():
    now = [0.0]
    cb = CircuitBreaker(failure_threshold=2, cooldown=30, clock=_mk_clock(now))
    for _ in range(2):
        with pytest.raises(RuntimeError):
            cb.call(lambda: (_ for _ in ()).throw(RuntimeError("down")))
    assert cb.state == CircuitBreaker.OPEN
    with pytest.raises(CircuitOpen):
        cb.call(lambda: "should not run")


def test_circuit_breaker_open_fast_fails_without_calling_fn():
    now = [0.0]
    cb = CircuitBreaker(failure_threshold=5, cooldown=30, clock=_mk_clock(now))
    cb.trip()
    called = []
    with pytest.raises(CircuitOpen):
        cb.call(lambda: called.append(1))
    assert called == []  # 熔断开启时根本不执行 fn


def test_circuit_breaker_half_open_success_closes():
    now = [0.0]
    cb = CircuitBreaker(failure_threshold=1, cooldown=10, success_threshold=1,
                        clock=_mk_clock(now))
    with pytest.raises(RuntimeError):
        cb.call(lambda: (_ for _ in ()).throw(RuntimeError("x")))
    assert cb.state == CircuitBreaker.OPEN
    now[0] = 11.0  # 冷却到期
    assert cb.call(lambda: "ok") == "ok"
    assert cb.state == CircuitBreaker.CLOSED


def test_circuit_breaker_half_open_failure_reopens():
    now = [0.0]
    cb = CircuitBreaker(failure_threshold=1, cooldown=10, clock=_mk_clock(now))
    with pytest.raises(RuntimeError):
        cb.call(lambda: (_ for _ in ()).throw(RuntimeError("x")))
    now[0] = 11.0
    with pytest.raises(RuntimeError):
        cb.call(lambda: (_ for _ in ()).throw(RuntimeError("x2")))
    assert cb.state == CircuitBreaker.OPEN
    assert cb.stats()["opened_at"] == 11.0  # 冷却计时重置


def test_circuit_breaker_trip_and_reset():
    now = [0.0]
    cb = CircuitBreaker(cooldown=30, clock=_mk_clock(now))
    cb.trip()
    assert cb.state == CircuitBreaker.OPEN
    assert cb.stats()["opened_at"] == 0.0
    cb.reset()
    assert cb.state == CircuitBreaker.CLOSED
    assert cb.stats() == {
        "state": CircuitBreaker.CLOSED, "failures": 0, "successes": 0,
        "opened_at": 0.0, "enabled": True,
    }


def test_circuit_breaker_disabled_passthrough():
    cb = CircuitBreaker(failure_threshold=1, cooldown=10, enabled=False)
    for _ in range(3):
        with pytest.raises(RuntimeError):
            cb.call(lambda: (_ for _ in ()).throw(RuntimeError("x")))
    assert cb.state == CircuitBreaker.CLOSED  # 永不熔断


def test_circuit_breaker_from_config_disabled():
    cb = CircuitBreaker.from_config({})
    assert cb.enabled is False


def test_circuit_breaker_from_config_enabled():
    cb = CircuitBreaker.from_config({
        "agent.circuit_breaker.enabled": True,
        "agent.circuit_breaker.failure_threshold": 3,
        "agent.circuit_breaker.cooldown": 5.0,
        "agent.circuit_breaker.success_threshold": 2,
    })
    assert cb.enabled is True
    assert cb.failure_threshold == 3
    assert cb.cooldown == 5.0
    assert cb.success_threshold == 2
