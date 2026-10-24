"""agent_loop_fusion.py —— Agent 主循环增强: 续跑上限提升 + 瞬时错误重试。

默认行为:
- 续跑: 原生每轮 user 输入默认最多 ``agent.max_iterations`` (默认 20) 步;
  未显式指定时, 用 ``fusion.agent_loop_max_iterations`` (默认 40) 作为更高上限,
  让复杂任务在一轮对话里自动续跑更多步 (对齐 kernel ``continuation`` 语义);
  显式值始终优先。
- 瞬时错误重试: ``retry_step`` 以指数退避重试「瞬时」异常 (网络抖动/超时/限流),
  非瞬时异常直接上抛。

纯函数 + 配置驱动, 可独立单测, 不依赖任何外部 LLM/网络。
"""

from __future__ import annotations

import time
from typing import Any, Callable, Optional

# 瞬时错误判定用的关键字 (对齐 kernel step_retry 的 transient 分类思路)。
_TRANSIENT_KEYWORDS = (
    "timeout", "timed out", "rate limit", "429", "503", "502", "504",
    "temporarily", "try again", "reset by peer", "connection", "connectionreset",
    "broken pipe", "econn", "socket", "network", "deadline", "throttl",
)


def classify_transient(exc: BaseException) -> bool:
    """判定异常是否为「可重试的瞬时错误」(网络抖动/超时/限流等)。"""
    if isinstance(exc, (TimeoutError, ConnectionError, ConnectionResetError,
                        BrokenPipeError)):
        return True
    text = f"{type(exc).__name__}: {exc}".lower()
    return any(k in text for k in _TRANSIENT_KEYWORDS)


def retry_step(
    fn: Callable[[], Any],
    *,
    max_retries: int = 3,
    backoff_base: float = 0.5,
    is_transient: Callable[[BaseException], bool] = classify_transient,
) -> Any:
    """以指数退避重试瞬时错误的步骤执行 (kernel step_retry 的同步等价物)。

    - 全部 ``max_retries`` 次仍失败则上抛最后一次异常。
    - 任一非瞬时异常立即上抛 (不重试)。
    """
    last: Optional[BaseException] = None
    for attempt in range(max(1, max_retries)):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001
            last = exc
            if attempt == max_retries - 1:
                break
            if not is_transient(exc):
                raise
            time.sleep(backoff_base * (2 ** attempt))
    assert last is not None
    raise last


def resolve_max_iterations(config: Any, explicit: Optional[int] = None) -> int:
    """解析主循环每轮迭代上限。

    优先级 (高 → 低):

    1. ``explicit`` —— 调用方 (如 ``Agent.run(max_iterations=...)``) 显式指定, 最高优先。
    2. ``agent.max_iterations`` —— **用户可见的正式配置键**。``config/loader.py`` 默认 50,
       ``config/validate.py`` 校验取值 1..200, ``tuan chat --max-turns`` 写入的就是它,
       ``/config`` 展示的也是它。它必须在这里生效, 否则用户设置会被静默忽略。
    3. ``fusion.agent_loop_max_iterations`` —— 内部续跑旋钮 (默认 40), 仅在前两项都
       没配置时兜底, 让复杂任务在缺省状态下仍能自动续跑更多步。

    历史缺陷: 本函数早期只读 ``fusion.agent_loop_max_iterations``, 完全不查
    ``agent.max_iterations`` —— 结果是 ``tuan chat --max-turns 100`` 写了配置却不生效,
    主循环一律按 40 步掐断。
    """
    if explicit is not None:
        return int(explicit)
    for key in ("agent.max_iterations", "fusion.agent_loop_max_iterations"):
        raw = config.get(key, None)
        if isinstance(raw, bool):
            continue
        if isinstance(raw, (int, float)) and float(raw) > 0:
            return int(raw)
        if isinstance(raw, str):
            try:
                v = float(raw.strip())
            except ValueError:
                continue
            if v > 0:
                return int(v)
    return 40


def should_continue(iteration: int, max_iterations: int) -> bool:
    """续跑谓词: 是否还能继续下一步。"""
    return iteration < max_iterations


__all__ = [
    "classify_transient",
    "retry_step",
    "resolve_max_iterations",
    "should_continue",
]
