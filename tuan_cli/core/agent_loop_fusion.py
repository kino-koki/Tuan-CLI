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
from pathlib import Path
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


def _is_user_set(config: Any, dotted: str) -> bool:
    """判断配置键是否由用户显式设置 (user/profile/patch/运行时叠加层), 而非内置默认。

    Config.data 是四层叠加视图, 无法直接区分来源; 通过读取原始配置层判断:
    - 若 config 有 .user_config_path / .home, 先查用户 YAML 层;
    - 运行时代码直接改 ``config.data[...]`` (测试/插件/CLI 注入) 时, 用户 YAML
      不含该键, 回退比较 data 视图值与内置默认 —— 不同则视为显式设置。
    """
    try:
        # 1. 用户层配置存在且含该键 → 用户显式设置
        ucp = getattr(config, "user_config_path", None)
        if ucp is not None:
            from ..config.loader import _load_yaml
            user_cfg = _load_yaml(Path(ucp)) if Path(ucp).exists() else {}
            node = user_cfg
            for key in dotted.split("."):
                if not isinstance(node, dict) or key not in node:
                    break
                node = node[key]
            else:
                return True
    except Exception:  # noqa: BLE001
        pass
    # 2. 回退: data 视图值 != 内置默认 → 运行时已覆盖 (代码/测试/CLI 注入)
    try:
        from ..config.defaults import DEFAULT_CONFIG
        def _deep_get(data: Any, path: str) -> Any:
            node = data
            for key in path.split("."):
                if not isinstance(node, dict):
                    return None
                node = node.get(key)
            return node
        cur = _deep_get(config.data, dotted) if hasattr(config, "data") else None
        default = _deep_get(DEFAULT_CONFIG, dotted)
        return bool(cur != default)
    except Exception:  # noqa: BLE001
        return False


def resolve_max_iterations(config: Any, explicit: Optional[int] = None) -> int:
    """解析主循环每轮迭代上限。

    优先级 (高 → 低):

    1. ``explicit`` —— 调用方 (如 ``Agent.run(max_iterations=...)``) 显式指定, 最高优先。
    2. ``agent.max_iterations`` —— **用户可见的正式配置键**。``config/loader.py`` 默认 30,
       ``config/validate.py`` 校验取值 1..200, ``tuan chat --max-turns`` 写入的就是它,
       ``/config`` 展示的也是它。它必须在这里生效, 否则用户设置会被静默忽略。
       **仅当用户显式设置时优先于 effort 档位** (否则 effort 档位无法体现)。
    3. ``agent.effort`` → ``effort_profiles.<level>.loop_max_iter`` —— 推理投入档位
       对应的迭代上限 (对标 Claude Code /effort 影响 continuation)。仅当用户未显式
       设置 ``agent.max_iterations`` 时生效, 让档位真正影响循环深度。
    4. ``fusion.agent_loop_max_iterations`` —— 内部续跑旋钮 (默认 40), 仅在前几项都
       没配置时兜底, 让复杂任务在缺省状态下仍能自动续跑更多步。
    """
    if explicit is not None:
        return int(explicit)
    # 2. 用户显式设置的 agent.max_iterations 最高优先 (默认值不盖过 effort 档位)
    if _is_user_set(config, "agent.max_iterations"):
        raw = config.get("agent.max_iterations", None)
        if isinstance(raw, (int, float)) and float(raw) > 0:
            return int(raw)
    # 3. effort 档位联动 (仅当未显式设置 max_iterations)
    effort = str(config.get("agent.effort", "high")).strip().lower()
    try:
        profile = config.get(f"agent.effort_profiles.{effort}", None) or {}
        if isinstance(profile, dict) and profile.get("loop_max_iter"):
            v = int(profile["loop_max_iter"])
            if v > 0:
                return v
    except Exception:  # noqa: BLE001
        pass
    # 4. 兜底
    for key in ("agent.max_iterations", "fusion.agent_loop_max_iterations"):
        raw = config.get(key, None)
        if isinstance(raw, bool):
            continue
        if isinstance(raw, (int, float)) and float(raw) > 0:
            return int(raw)
        if isinstance(raw, str):
            try:
                fv = float(raw.strip())
            except ValueError:
                continue
            if fv > 0:
                return int(fv)
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
