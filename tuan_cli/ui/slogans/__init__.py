"""Tuan 标语库 — spinner / 加载屏 / 空闲位 / 完成提示的短句取用。

构成:

- ``universal``     300 条通用英文 (10 场景 × 30), 所有语种的公共底座
- ``locales``       10 语种 × 50 条本地化, 按场景分组
- ``extra``         6 个产品特有场景 (模型切换 / 预算告警 / 后台任务 / 配对 / 记忆写入)
- ``extra_locales`` 补齐 8 语种 × 6 场景 = 240 条, 消除跨语种英文泄漏
- ``picker``        取词器: 上下文映射、回退链、避重窗口、频率节制
- ``mapping``       **一一对应表**: 事件 ↔ 上下文 ↔ 每条标语, 含全量审计
                    (11 项运行时不变量、O(1) 索引含净化后索引、
                     按会话分域且 LRU 有界的留痕、错误双层留痕、
                     不可反查即 fail-closed、连续 miss 自愈、
                     日志字段与 owner 统一净化 (先清理后截断、
                     OSC/CSI 允许 ESC+ 引导、owner 有界摘要)
                     且严格幂等、注入时钟严格校验且合法 0 不被吞、
                     LRU 被动淘汰留脱敏痕 + reason 摘要 +
                     累计证据、桶内裁剪留痕 + 累计决策数、
                     注入时钟贯穿淘汰痕的可回放、
                     event 类型守卫 + 非字符串 owner 固定隔离桶
                     与脱敏类型证据；净化层本轮零改动)

最小用法 (生产接线请走事件驱动入口)::

    from tuan_cli.ui.slogans.mapping import pick_for_event, audit

    assert audit().ok                       # 每个标语都要对应的
    pick_for_event("tool.exploring")        # 事件 -> 上下文 -> 净化后的标语

兼容旧调用::

    from tuan_cli.ui.slogans import pick, for_state, SloganPicker

    pick("thinking")                        # 跟随当前界面语言
    for_state("WORKING")                    # 按 mascot 状态取
    p = SloganPicker(min_interval=5.0)     # 长任务 spinner 节制换词

回退链: 本语种池 -> 通用英文池 -> 硬编码兜底。缺译永不抛异常、永不返回空串;
但 ``mapping.pick_for_event`` 对**未知事件**抛异常, 绝不静默飘一句无关联的
``idle`` 标语 —— 那是「没有对应的标语被渲染」。

安全边界 (用户库设计稿原文「不要动: 安全拦截的结构化告警 (那是降级,
不是优化)」): ``mapping.SECURITY_EVENTS`` 里的事件一律返回空文案,
结构化告警不会被俏皮话替换或稀释。

包位置说明: 本包**必须**位于 ``tuan_cli/ui/slogans/``。仓库根目录还留有
一个历史同名包 ``slogans/``, 它现在只是薄兼容垫片 (re-export), 不再是
第二份词库 —— 避免两套数据各自漂移。
"""

from __future__ import annotations

from . import extra, extra_locales, picker, universal
from .picker import (  # noqa: F401
    CONTEXTS,
    EXTRA_CONTEXTS,
    MIN_INTERVAL_S,
    STATE_MAP,
    SloganPicker,
    for_state,
    pick,
    pick_strict,
    pick_local_first,
    pool,
    pool_entries,
)

__all__ = [
    "pick", "pick_strict", "pick_local_first", "for_state", "pool", "pool_entries", "SloganPicker",
    "CONTEXTS", "EXTRA_CONTEXTS", "STATE_MAP", "MIN_INTERVAL_S",
    "universal", "extra", "extra_locales", "picker", "stats",
]


def stats() -> dict[str, int]:
    """池规模自检: 通用 300 / 扩展通用 60 / 本地化 500 / 补池 240 / 空组与长句修补 8。"""
    from .locales import LANGUAGES, groups, patches  # noqa: PLC0415

    out = {
        "universal": universal.count(),
        "extra": extra.count(),
        "locales": sum(len(v) for code in LANGUAGES for v in groups(code).values()),
        "extra_locales": extra_locales.count(),
        "locale_patches": patches.count(),
    }
    out["total"] = sum(out.values())
    return out
