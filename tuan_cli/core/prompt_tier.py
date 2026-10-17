"""提示词分层 (Prompt Tier) —— 按模型上下文窗口规模选择注入预算。

待办4: 上下文小于 1M 的模型读「小型」提示词, 上下文大于 1M 的模型读「大」提示词。

为什么需要分层
--------------
系统提示里钉着的内容 (技能快照 / 记忆笔记 / 项目指令 / 代码库地图 / 长期记忆) 都是
**常驻成本**: 每一轮都为它们付费。对 8k/32k 窗口的模型, 这些常驻段会吃掉大部分预算,
还没开始干活上下文就告急; 而 1M 级窗口的模型完全承受得起完整注入。

因此提示词本身应当「按模型能力伸缩」, 而不是所有模型共用一份固定模板。

分档规则
--------
::python

    resolve_prompt_tier(window, threshold) -> "compact" if window < threshold else "full"

- ``compact`` (小型提示词): 收紧所有注入预算 —— 少注入技能、短记忆笔记、更小指令文件、
  不钉代码库地图、长期记忆只留最关键的一段。
- ``full`` (大提示词): 放开预算, 上限远高于内置默认值, 对用户配置**完全透明**
  (即: 与历史行为逐字节一致)。

阈值默认 ``1_000_000`` token, 由配置 ``prompt.context_tier_threshold`` 覆盖。

上下文窗口推断优先级
--------------------
1. 配置 ``model.context_window`` 显式声明 (``> 0`` 即采信) —— 用户最清楚自己网关的真实限额。
2. 模型名显式尺寸后缀与已知长上下文家族 (``-256k`` / ``-1m`` / ``-200k`` / ``fable`` …)。
3. 供应商级默认窗口 (下表)。
4. 兜底 128k (绝大多数通用端点的常见默认)。

预算语义
--------
每档是一组**注入预算上限 (cap)**; 实际生效值 = ``min(用户配置值, 该档上限)``。
只收紧、不放大: 用户显式调小的配置永远优先, 分层绝不会把用户的限制偷偷放宽。

两层开关 (``prompt.tier`` = ``auto`` | ``compact`` | ``full``)
------------------------------------------------------------
1. **预算分层** (动态段): 始终生效。auto 按上下文窗口自动定档, 控制技能数、
   记忆笔记行数、项目指令文件字节数、长期记忆长度、是否钉代码库地图。
2. **SOUL 换档** (稳定前缀): 仅显式 ``compact`` / ``full`` 生效, 见 resolve_soul_tier。
   auto 不换 SOUL —— 避免默认把所有人从 ``SOUL.md`` + 规范段换成另一份模板。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional, Tuple

# ============================================================ 档位常量

COMPACT: str = "compact"
FULL: str = "full"
TIER_NAMES: Tuple[str, str] = (COMPACT, FULL)

#: 分档阈值: 窗口 >= 此值的模型拿 full 档, 小于此值的拿 compact 档。
DEFAULT_CONTEXT_TIER_THRESHOLD: int = 1_000_000

#: 完全无法推断时的兜底窗口 (保守, 宁可拿 compact 也不冒溢出风险)。
DEFAULT_CONTEXT_WINDOW: int = 128 * 1024

#: ``prompt.tier`` 默认值: 按上下文窗口自动定档。
DEFAULT_TIER: str = "auto"

#: 供应商级默认上下文窗口 (与 TUI 底栏展示口径保持一致)。
PROVIDER_CONTEXT_WINDOWS: Dict[str, int] = {
    "deepseek": 128 * 1024,
    "moonshot": 128 * 1024,
    "kimi": 128 * 1024,
    "anthropic": 200_000,
    "claude": 200_000,
    "openai": 200_000,
    "gpt": 200_000,
    "gemini": 1_000_000,
    "google": 1_000_000,
    "grok": 256 * 1024,
    "xai": 256 * 1024,
    "mistral": 128 * 1024,
    "openrouter": 200_000,
    "siliconflow": 128 * 1024,
    "qwen": 128 * 1024,
    "dashscope": 128 * 1024,
    "aliyun": 128 * 1024,
    "zhipu": 128 * 1024,
    "doubao": 256 * 1024,
    "volcengine": 256 * 1024,
    "groq": 128 * 1024,
    "github": 128 * 1024,
    "ollama": 32 * 1024,
}

# 模型名显式标注尺寸的写法: -256k / -128k / -1m / _200k …
_SUFFIX_SIZE_RE = re.compile(r"[-_](\d{2,4})k$")
_SUFFIX_M_RE = re.compile(r"[-_](\d)m$")


# ============================================================ 上下文窗口推断

def _window_from_model_name(model: str) -> Optional[int]:
    """从模型名字面提取窗口尺寸; 提取不到返回 None。

    覆盖写法: ``doubao-1.5-pro-256k`` → 256k, ``glm-4-plus-1m`` → 1M,
    ``gpt-4o-200k`` → 200k。Anthropic Fable 系列默认 1M 窗口, 单独处理。
    """
    m = (model or "").lower()
    if not m:
        return None
    if "fable" in m:
        return 1_000_000
    suf = _SUFFIX_SIZE_RE.search(m)
    if suf:
        return int(suf.group(1)) * 1024
    suf_m = _SUFFIX_M_RE.search(m)
    if suf_m:
        return int(suf_m.group(1)) * 1_000_000
    return None


def _window_from_provider(provider: str) -> int:
    """按供应商取默认窗口; 别名归一 (aliyun → qwen), 未知落到兜底值。"""
    prov = (provider or "").lower()
    if prov in ("aliyun", "dashscope"):
        prov = "qwen"
    for key, win in PROVIDER_CONTEXT_WINDOWS.items():
        if key and key in prov:
            return win
    return DEFAULT_CONTEXT_WINDOW


def infer_context_window(
    model: str = "",
    provider: str = "",
    configured: Any = None,
) -> int:
    """推断当前模型的上下文窗口 (token)。

    优先级: 配置显式值 (>0) > 模型名尺寸后缀/家族 > 供应商默认 > 128k 兜底。
    永不返回非正数 —— 调用方可安全拿它做阈值比较。
    """
    try:
        val = int(configured) if configured is not None else 0
    except (TypeError, ValueError):
        val = 0
    if val > 0:
        return val
    named = _window_from_model_name(model)
    if named is not None:
        return named
    return _window_from_provider(provider)


# ============================================================ 分档

def resolve_prompt_tier(
    context_window: int,
    threshold: int = DEFAULT_CONTEXT_TIER_THRESHOLD,
    tier: Optional[str] = None,
) -> str:
    """按上下文窗口定档, 允许 ``tier`` 强制覆盖。

    - ``tier`` 为 ``compact`` / ``full`` 时直接采信 (用户实测后的手动定档)。
    - ``tier`` 为 ``auto``/空/未知时按窗口与阈值判定。
    - ``threshold`` <= 0 视为无效, 回退默认阈值 (避免误配置把所有模型打成 compact)。
    """
    key = (tier or "").strip().lower()
    if key in TIER_NAMES:
        return key
    thr = int(threshold) if threshold and int(threshold) > 0 else DEFAULT_CONTEXT_TIER_THRESHOLD
    win = int(context_window) if context_window and int(context_window) > 0 else DEFAULT_CONTEXT_WINDOW
    return COMPACT if win < thr else FULL


# ============================================================ 预算

@dataclass(frozen=True)
class PromptBudget:
    """一档提示词注入预算: 各常驻段的**上限** (cap), 不是配额。

    实际生效值 = min(用户配置值, 上限)。所以 full 档的上限取到远高于默认值,
    用户配置原样通过; compact 档则逐项收紧。
    """

    #: 注入的技能快照条数上限 (activation=always 的技能不受限, 由渲染层保底)。
    skill_limit: int = 2
    #: MEMORY.md 注入行数上限。
    memory_notes_max_lines: int = 100
    #: 单个项目指令文件字节上限。
    project_doc_max_bytes: int = 12288
    #: 长期记忆 (FTS5 结构化) 注入字符上限。
    long_memory_max_chars: int = 800

    def apply_caps(
        self,
        skill_limit: int,
        memory_notes_max_lines: int,
        project_doc_max_bytes: int,
        long_memory_max_chars: int,
    ) -> Tuple[int, int, int, int]:
        """把用户配置值与本档上限取 min, 返回收紧后的四元组。

        只管「量」的收紧, 不管「有没有」—— 代码库地图是否注入由
        ``context.pin_codebase`` 单独决定 (那是用户的显式开关, 分层不越权代劳)。
        """
        return (
            max(0, min(int(skill_limit), self.skill_limit)),
            max(0, min(int(memory_notes_max_lines), self.memory_notes_max_lines)),
            max(0, min(int(project_doc_max_bytes), self.project_doc_max_bytes)),
            max(0, min(int(long_memory_max_chars), self.long_memory_max_chars)),
        )


#: 各档默认预算。full 档上限远超内置默认值, 保证 full == 历史行为。
DEFAULT_TIER_BUDGETS: Dict[str, PromptBudget] = {
    COMPACT: PromptBudget(
        skill_limit=2,
        memory_notes_max_lines=100,
        project_doc_max_bytes=12288,
        long_memory_max_chars=800,
    ),
    FULL: PromptBudget(
        skill_limit=16,
        memory_notes_max_lines=500,
        project_doc_max_bytes=131072,
        long_memory_max_chars=4000,
    ),
}


def budget_for_tier(
    tier: str,
    budgets: Optional[Mapping[str, PromptBudget]] = None,
) -> PromptBudget:
    """取某档预算; 未知档位回退 full (宁多勿少, 与历史行为一致)。

    自定义 budgets 只覆盖它声明的档位, 未声明的档位用内置默认补齐,
    因此「只配 compact」也不会让 full 档查表失败。
    """
    table = budgets if budgets else DEFAULT_TIER_BUDGETS
    merged: Dict[str, PromptBudget] = dict(DEFAULT_TIER_BUDGETS)
    for key, value in table.items():
        name = str(key).strip().lower()
        if name in TIER_NAMES and isinstance(value, PromptBudget):
            merged[name] = value
    key = (tier or "").strip().lower()
    return merged.get(key, merged[FULL])


def _cfg_get(config: Any, dotted: str, default: Any = None) -> Any:
    """鸭子类型读点路径配置: 支持嵌套 Mapping / Config 点路径两种形态。

    - 嵌套 Mapping (普通 dict): 按 ``a.b.c`` 逐级下钻。
    - 真实 Config 类: 调 ``config.get(dotted)`` (它自己实现点路径解析)。
    两者互不干扰 —— 先判嵌套 Mapping, 避免 dict.get("a.b") 直接返回 default
    从而永远读不到嵌套值。
    """
    if config is None:
        return default
    if isinstance(config, Mapping) and "." in dotted:
        node: Any = config
        for part in dotted.split("."):
            if isinstance(node, Mapping) and part in node:
                node = node[part]
            else:
                return default
        return default if node is None else node
    getter = getattr(config, "get", None)
    if callable(getter):
        try:
            val = getter(dotted)
            return default if val is None else val
        except Exception:  # noqa: BLE001 - 配置对象形态各异, 读失败走默认
            pass
    return default


def budgets_from_config(config: Any) -> Optional[Dict[str, PromptBudget]]:
    """把 ``prompt.tiers`` 配置解析为 ``{档位: PromptBudget}``。

    配置缺字段时该档沿用内置默认值逐字段补齐, 保证半配置也不会产生残缺预算。
    返回 None 表示无有效配置 (调用方回退 DEFAULT_TIER_BUDGETS)。
    """
    table = _cfg_get(config, "prompt.tiers")
    if not isinstance(table, Mapping):
        return None
    out: Dict[str, PromptBudget] = {}
    for tier_name, fields in table.items():
        key = str(tier_name).strip().lower()
        if key not in TIER_NAMES or not isinstance(fields, Mapping):
            continue
        base = DEFAULT_TIER_BUDGETS[key]
        kwargs = {
            "skill_limit": _as_int(fields.get("skill_limit"), base.skill_limit),
            "memory_notes_max_lines": _as_int(
                fields.get("notes_max_lines", fields.get("memory_notes_max_lines")),
                base.memory_notes_max_lines),
            "project_doc_max_bytes": _as_int(fields.get("project_doc_max_bytes"),
                                             base.project_doc_max_bytes),
            "long_memory_max_chars": _as_int(fields.get("long_memory_max_chars"),
                                             base.long_memory_max_chars),
        }
        out[key] = PromptBudget(**kwargs)
    return out or None


def _as_int(value: Any, default: int) -> int:
    """尽力把配置值转成非负 int, 失败或负数回退默认。"""
    try:
        n = int(value)
    except (TypeError, ValueError):
        return default
    return max(0, n)


def resolve_soul_tier(
    config: Any = None,
    *,
    tier: Optional[str] = None,
) -> str:
    """决定稳定前缀是否切换到「内置档位 SOUL」(SOUL_COMPACT.md / SOUL_FULL.md)。

    语义分两层, 避免默认行为突变:
    - ``prompt.tier == "auto"`` (默认): 返回 ``""`` —— 只做**预算分层**
      (收紧动态段的技能数 / 笔记行数 / 指令文件字节 / 长期记忆长度),
      稳定前缀仍用 ``SOUL.md`` + 各规范段逐字节拼装, 与历史完全一致。
    - ``prompt.tier == "compact"`` / ``"full"`` (显式): 返回该档位名 ——
      稳定前缀改用内置档位 SOUL (compact ≈1.3K 字 / full ≈26K 字, 自包含全部规范),
      预算同步切换到对应档。

    也就是说: 「小型提示词 / 大提示词」的**自动**伸缩由预算分层承担 (安全、可回退);
    要彻底换掉整份系统提示词, 用显式 compact/full 主动选择。
    """
    want = (tier or _cfg_get(config, "prompt.tier", DEFAULT_TIER) or DEFAULT_TIER)
    key = str(want).strip().lower()
    return key if key in TIER_NAMES else ""


def resolve_prompt_budget(
    config: Any = None,
    *,
    model: str = "",
    provider: str = "",
    context_window: Optional[int] = None,
    tier: Optional[str] = None,
    budgets: Optional[Mapping[str, PromptBudget]] = None,
) -> Tuple[str, int, PromptBudget]:
    """一站式解析: 返回 ``(档位名, 推断窗口, 该档预算)``。

    供 Agent / 测试共用。config 可空 (纯参数调用), 此时完全依赖显式参数。
    """
    cfg_window = _cfg_get(config, "model.context_window")
    window = infer_context_window(
        model or _cfg_get(config, "model.model", "") or "",
        provider or _cfg_get(config, "model.provider", "") or "",
        configured=cfg_window if cfg_window is not None else context_window,
    )
    thr = int(_cfg_get(config, "prompt.context_tier_threshold", DEFAULT_CONTEXT_TIER_THRESHOLD)
              or DEFAULT_CONTEXT_TIER_THRESHOLD)
    want_tier = (tier or _cfg_get(config, "prompt.tier", DEFAULT_TIER) or DEFAULT_TIER)
    resolved = resolve_prompt_tier(window, thr, want_tier)
    table = budgets if budgets is not None else budgets_from_config(config)
    return resolved, window, budget_for_tier(resolved, table)
