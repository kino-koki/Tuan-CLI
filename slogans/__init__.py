"""Tuan 标语库 — spinner / 加载屏 / 空闲位 / 完成提示的短句取用。

构成:

- ``universal``  300 条通用英文 (10 场景 × 30), 所有语种的公共底座
- ``locales``    10 语种 × 50 条本地化, 按场景分组
- ``extra``      6 个产品特有场景 (模型切换 / 预算告警 / 后台任务 / 配对 / 记忆写入)
- ``picker``     取词器: 上下文映射、回退链、避重窗口、频率节制

最小用法::

    from tuan_cli.ui.slogans import pick, for_state, SloganPicker

    pick("thinking")                     # 跟随当前界面语言
    pick("bg.progress", lang="ja")       # 指定语种
    for_state("WORKING")                 # 按 mascot 状态取

    picker = SloganPicker(min_interval=5.0)   # 长任务 spinner
    picker.pick("thinking")                   # 5 秒内不换词

回退链: 本语种池 -> 通用英文池 -> 硬编码兜底。缺译永不抛异常、永不返回空串。

接入点建议 (与现有 5 态对应):
    ``ui/repl.py``   ``repl.thinking`` -> ``for_state("THINKING")``
    ``ui/splash.py`` 启动横幅          -> ``pick("startup")``
    ``undo`` 成功提示                  -> ``pick("undo")``
    ``cmd.exit`` 退出语                -> ``pick("signoff")``
    后台任务                           -> ``pick("bg.progress")``
不要动: 安全拦截的结构化告警 (那是降级, 不是优化)。
"""

from __future__ import annotations

from . import extra, picker, universal
from .picker import (  # noqa: F401
    CONTEXTS,
    EXTRA_CONTEXTS,
    MIN_INTERVAL_S,
    STATE_MAP,
    SloganPicker,
    for_state,
    pick,
    pool,
)

__all__ = [
    "pick", "for_state", "pool", "SloganPicker",
    "CONTEXTS", "EXTRA_CONTEXTS", "STATE_MAP", "MIN_INTERVAL_S",
    "universal", "extra", "picker",
]


def stats() -> dict[str, int]:
    """池规模自检: 通用 300 / 扩展通用 60 / 本地化 10 × 50。"""
    from .locales import LANGUAGES, groups  # noqa: PLC0415

    out = {
        "universal": universal.count(),
        "extra": extra.count(),
        "locales": sum(len(v) for code in LANGUAGES for v in groups(code).values()),
    }
    out["total"] = out["universal"] + out["extra"] + out["locales"]
    return out
