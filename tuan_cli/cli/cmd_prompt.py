"""`tuan prompt` —— 提示词分层诊断 (第 40 个独特功能)。

提示词分层 (Prompt Tier) 是按模型上下文窗口选择「注入预算 + SOUL 档位」的机制:
模型窗口 < 128k 走 compact 档 (收紧技能/记忆/指令/长期记忆预算, 读 SOUL_COMPACT.md),
窗口 >= 128k 走 full 档 (完整预算, 读 SOUL_FULL.md)。这部分成本是**常驻的**:
系统提示里钉着的内容每一轮都付费, 小窗口模型必须收紧, 大窗口模型可以放开。

Claude Code 没有「提示词预算可观测性」—— 它不告诉用户当前模型被分到哪一档、
每段预算上限是多少、为什么。本命令把 prompt_tier 的决策逻辑暴露到 CLI, 让用户
能回答「我的模型当前拿的是哪档提示词、预算上限多少、SOUL 是哪份」:

  tuan prompt tier                          # 当前模型的分档诊断
  tuan prompt tier --model qwen-plus        # 指定模型名 (自动推断窗口)
  tuan prompt tier --provider deepseek      # 指定供应商
  tuan prompt tier --window 32000           # 显式窗口 (最精确)
  tuan prompt tier --tier compact           # 强制档位 (用户手动定档)
  tuan prompt tier --json                   # 机器可读

本命令不导入 app 链, 保持毫秒级启动。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Optional

from ..config import Config
from ..ui.plain_console import console
from ..core.prompt_tier import (
    COMPACT,
    FULL,
    TIER_NAMES,
    DEFAULT_CONTEXT_WINDOW,
    LARGE_CONTEXT_WINDOW_MIN,
    infer_context_window,
    resolve_prompt_tier,
    resolve_prompt_budget,
    resolve_soul_tier,
    budget_for_tier,
    budgets_from_config,
    PROVIDER_CONTEXT_WINDOWS,
)


def _human_window(n: int) -> str:
    """把 token 数格式化为人类可读 (如 131072 -> '128k')。"""
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n // 1024}k" if n % 1024 == 0 else f"{n / 1024:.1f}k"
    return str(n)


def _soul_file_for(tier: str) -> str:
    """返回该档对应的 SOUL 提示词文件名。"""
    return "SOUL_COMPACT.md" if tier == COMPACT else "SOUL_FULL.md"


def _render_tier(tier: str, window: int, budget: Any, soul: str, json_mode: bool,
                 model: str, provider: str, threshold: int, forced: bool) -> int:
    """渲染单档诊断。"""
    if json_mode:
        sys.stdout.write(json.dumps({
            "model": model,
            "provider": provider,
            "context_window": window,
            "context_window_human": _human_window(window),
            "tier": tier,
            "tier_label": "紧凑 (小上下文)" if tier == COMPACT else "完整 (大上下文)",
            "large_context_threshold": LARGE_CONTEXT_WINDOW_MIN,
            "threshold": threshold,
            "forced": forced,
            "is_large_context": window >= LARGE_CONTEXT_WINDOW_MIN,
            "budget": {
                "skill_limit": budget.skill_limit,
                "memory_notes_max_lines": budget.memory_notes_max_lines,
                "project_doc_max_bytes": budget.project_doc_max_bytes,
                "long_memory_max_chars": budget.long_memory_max_chars,
            },
            "soul_tier": soul,
            "soul_file": _soul_file_for(soul) if soul else "(由 agent 按窗口联动)",
        }, ensure_ascii=False, indent=2) + "\n")
        return 0

    color = "cyan" if tier == COMPACT else "green"
    console.print("\n[bold]=== 提示词分层诊断 (Prompt Tier) ===[/bold]\n")
    console.print(f"  模型: [bold]{model or '(未配置)'}[/bold]  "
                  f"[dim]provider={provider or '(未配置)'}[/dim]")
    console.print(f"  推断上下文窗口: [bold]{_human_window(window)}[/bold] token "
                  f"({window:,})")
    console.print(f"  大上下文下界: {_human_window(LARGE_CONTEXT_WINDOW_MIN)} token  "
                  f"[dim]({LARGE_CONTEXT_WINDOW_MIN:,})[/dim]")
    console.print(f"  分档阈值: {_human_window(threshold)} token")
    console.print(f"\n  分档: [{color}]{tier}[/{color}]"
                  f"  ({'紧凑: 收紧注入预算' if tier == COMPACT else '完整: 放开预算'})"
                  + ("  [dim](手动强制档位)[/dim]" if forced else ""))
    console.print(f"  大上下文模型: {'是' if window >= LARGE_CONTEXT_WINDOW_MIN else '否'}")

    console.print("\n  [bold]该档注入预算上限[/bold] (实际生效值 = min(用户配置, 上限))")
    console.print(f"    技能快照条数:   {budget.skill_limit}")
    console.print(f"    记忆笔记行数:   {budget.memory_notes_max_lines}")
    console.print(f"    项目指令字节:   {budget.project_doc_max_bytes:,} B")
    console.print(f"    长期记忆字符:   {budget.long_memory_max_chars:,}")

    if soul:
        console.print(f"\n  SOUL 档位: [bold]{soul}[/bold] → {_soul_file_for(soul)}")
    else:
        console.print(f"\n  SOUL 档位: [dim]auto (由 agent 按窗口联动)[/dim] "
                      f"→ {_soul_file_for(tier)} (窗口 {_human_window(window)})")

    console.print("\n[dim]说明: 分档只收紧不放大; 用户显式调小的配置永远优先。"
                  "窗口 <128k 的模型拿 compact 档, 否则 full 档。[/dim]")
    return 0


def cmd_prompt(args: Any) -> int:
    """提示词分层诊断入口。"""
    config = Config(profile=getattr(args, "profile", "default"),
                    patch_file=getattr(args, "patch", None))
    sub = getattr(args, "prompt_cmd", None) or "tier"

    if sub != "tier":
        console.print(f"[red]未知子命令: {sub}[/red]")
        console.print("可用: tier")
        return 1

    # -- 参数优先级: 显式 > 配置 --
    model = getattr(args, "model", None) or str(config.get("model.model", "") or "")
    provider = getattr(args, "provider", None) or str(config.get("model.provider", "") or "")
    explicit_window = getattr(args, "window", None)
    explicit_tier = getattr(args, "tier", None)
    json_mode = bool(getattr(args, "json", False))

    # 诊断目标是否为当前模型 (未显式指定 model/provider/window 时, 才用配置窗口)
    diagnosing_current = not (
        getattr(args, "model", None)
        or getattr(args, "provider", None)
        or explicit_window is not None
    )
    cfg_window = config.get("model.context_window")
    if cfg_window is not None and diagnosing_current:
        try:
            cfg_window = int(cfg_window)
        except (TypeError, ValueError):
            cfg_window = None
    else:
        cfg_window = None  # 显式诊断时忽略当前模型窗口, 防止覆盖

    window = infer_context_window(
        model, provider,
        configured=explicit_window if explicit_window is not None else cfg_window,
    )

    threshold_cfg = config.get("prompt.context_tier_threshold")
    try:
        threshold = int(threshold_cfg) if threshold_cfg else None
    except (TypeError, ValueError):
        threshold = None

    resolved = resolve_prompt_tier(
        window,
        threshold=threshold if threshold is not None else window,  # 兜底: 默认阈值
        tier=explicit_tier,
    )
    # 用真实阈值重算 (resolve_prompt_tier 内部已处理 <=0 回退)
    from ..core.prompt_tier import DEFAULT_CONTEXT_TIER_THRESHOLD
    thr = threshold if threshold and threshold > 0 else DEFAULT_CONTEXT_TIER_THRESHOLD

    # 预算: 配置覆盖 + 档位
    budgets = budgets_from_config(config)
    budget = budget_for_tier(resolved, budgets)
    soul = resolve_soul_tier(config, tier=explicit_tier)

    forced = explicit_tier in TIER_NAMES
    return _render_tier(resolved, window, budget, soul, json_mode,
                        model, provider, thr, forced)
