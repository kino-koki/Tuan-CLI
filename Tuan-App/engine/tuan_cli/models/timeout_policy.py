"""读超时策略 —— 三段式超时中 `read` 段的统一口径（单一真相源）。

背景（"模型老是超时"的真正原因）
--------------------------------
httpx 的 ``Timeout.read`` 在**流式**场景下的语义是「相邻两个分片之间的最大空闲
间隔」，不是整轮请求总时长。长上下文首字慢、思考型模型静默思考几十秒到数分钟都很
正常, 于是正确的读超时必须给到几百秒。

历史包袱: 早期青小团只有一档 ``timeout``（默认 120s）且直接当作 read 用, 用户
配置里因此**固化留下一批 ``read_timeout: 120``**。后来默认值升到 300s, 但
``deep_merge`` 语义是「用户配置覆盖默认值」, 于是这些**陈旧但合法**的 120 继续
生效 —— 代码里 ``config.get("model.read_timeout", 300.0)`` 的默认值永远轮不到,
表现就是「模型老是超时」, 且任何只想「升级默认值」的改动都治不好它。

对策
----
本模块把 read 超时收敛成一条策略并作为唯一入口:

1. **下限兜底**: 任何低于 ``MIN_READ_TIMEOUT`` 的配置值都抬到下限。低于 300s 的
   read 超时在实践中只会误杀长上下文/思考型模型, 没有任何收益 (想快速失败应该
   调 connect_timeout 或用 Ctrl+C), 因此直接兜底而非告警后放行。
2. **思考型模型放宽**: 命中思考型特征名则抬到 ``REASONING_READ_TIMEOUT`` (600s)。
3. **可观测**: 发生兜底/放宽时通过 ``tuan_cli.core.resilience`` 的日志说明原因,
   避免"配置被静默改写"的困惑。

用户显式配置的**更大**值一律尊重 —— 本模块只抬过低值, 不压低过高值。
"""

from __future__ import annotations

import logging
from typing import Any, Optional

log = logging.getLogger(__name__)

# read 超时下限 (秒)。低于此值只会在长上下文 / 思考型模型上误报超时。
MIN_READ_TIMEOUT: float = 300.0

# 思考型模型的分片空闲上限 (秒)。静默思考可能长达数分钟。
REASONING_READ_TIMEOUT: float = 600.0

# 思考型模型的模型名特征 (小写匹配)。
REASONING_HINTS: tuple = (
    "reasoner",
    "thinking",
    "deepseek-r1",
    "deepseek-reason",
    "o1",
    "o3",
    "gemini-2.0-flash-thinking",
    "gemini-2.5",
    "claude-thinking",
)


def is_reasoning_model(model_name: Optional[str]) -> bool:
    """按名称特征判定是否为静默思考时间较长的模型。"""
    name = (model_name or "").lower()
    return bool(name) and any(h in name for h in REASONING_HINTS)


def resolve_read_timeout(
    configured: Any,
    model_name: Optional[str] = None,
    *,
    min_timeout: float = MIN_READ_TIMEOUT,
    reasoning_timeout: float = REASONING_READ_TIMEOUT,
) -> float:
    """把配置里的 read_timeout 收敛为实际生效值。

    Args:
        configured: 配置原值 (可能是 None / 空串 / 陈旧的 120 / 用户自定义 900)。
        model_name: 当前模型名, 用于判定是否放宽到思考型上限。
        min_timeout: read 超时下限。
        reasoning_timeout: 思考型模型下限。

    Returns:
        实际生效的 read 超时 (秒), 保证 ``>= min_timeout``。
    """
    try:
        raw = float(configured)
    except (TypeError, ValueError):
        # None / "" / 非法值 → 用下限兜底
        raw = 0.0

    # 思考型模型的静默思考期本身就要几百秒, 因此**它的下限就是 reasoning_timeout**。
    # 顺序很关键: 若先按 min_timeout 返回, 陈旧配置 (如 120) 遇到 o3/reasoner 这类
    # 模型只会拿到 300 而错过 600 的放宽。
    floor = reasoning_timeout if is_reasoning_model(model_name) else min_timeout

    if raw < floor:
        if raw > 0:
            log.warning(
                "model.read_timeout=%.0fs 过低, 已兜底到 %.0fs —— "
                "read 超时是流式分片之间的最大空闲间隔而非整轮总时长, "
                "低值会让长上下文/思考型模型反复超时。如需快速失败请调 model.connect_timeout。",
                raw, floor,
            )
        return floor

    return raw