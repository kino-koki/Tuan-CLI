"""`tuan obs` —— 可观测性与成本归因 (第 49 个独特功能)。

Claude Code 的成本/缓存命中率是黑盒: 你看不到会话累计花费、DeepSeek 前缀
缓存命中率、token 构成。Tuan-CLI 的 AgentObservability + agent_helpers
(core/observability.py, core/agent_helpers.py) 把 usage 估算为成本与缓存命中率,
本命令把这些指标从会话历史**重建** (跨进程可观测):

    tuan obs status                    # 可观测性状态 (启用 + trace_id + usage 事件)
    tuan obs cost                      # 从会话 JSONL 重建累计成本 (USD)
    tuan obs cache                     # DeepSeek 前缀缓存命中率
    tuan obs cost --session <id>       # 指定会话 (默认最新)
    tuan obs cost --json               # 机器可读 (CI 成本归因)

差异化价值:
- 跨进程成本归因: 从会话 JSONL 的 usage 事件重建 total_usage, 任何进程都能
  看到历史会话的真实花费 (Claude Code 黑盒)。
- 缓存命中率透明: DeepSeek 前缀缓存 hit/miss 构成可见, 指导 prompt 复用。
- token 构成审计: prompt/completion/cache 分布一目了然。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, Optional

from ..config import home_dir
from ..ui.plain_console import console


def _resolve_session_file(sid: str) -> Optional[Path]:
    """按会话 ID (可前缀) 解析会话 jsonl 文件; 空取最新。"""
    sessions_dir = Path(home_dir()) / "sessions"
    if not sessions_dir.is_dir():
        return None
    if sid:
        files = sorted(sessions_dir.glob(f"{sid}*.jsonl"))
        return files[0] if files else None
    files = sorted(sessions_dir.glob("*.jsonl"),
                   key=lambda f: f.stat().st_mtime, reverse=True)
    return files[0] if files else None


def _reconstruct_usage(path: Path) -> Dict[str, int]:
    """从会话 JSONL 的 usage 事件重建 total_usage (跨进程可观测)。

    每条 usage 事件形如 {"type": "usage", "delta": {prompt_tokens, ...}}:
    token 计数嵌套在 delta 里。聚合为总量; 同时兼容顶层平铺格式。
    """
    total: Dict[str, int] = {}
    if not path.exists():
        return total
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception as exc:  # noqa: BLE001
                log.debug("_reconstruct_usage(): 非致命异常已忽略(设计内降级, 不改控制流): %s", exc)
                continue
            if not isinstance(rec, dict) or rec.get("type") != "usage":
                continue
            # token 计数在 delta 嵌套 (真实格式); 顶层平铺 (兼容)
            delta = rec.get("delta")
            source = delta if isinstance(delta, dict) else rec
            for k, v in source.items():
                if k in ("ts", "type", "event", "session_id", "turn"):
                    continue
                if isinstance(v, (int, float)) and k.endswith("tokens"):
                    total[k] = int(total.get(k, 0) + v)
    return total


def _cmd_obs_status(args: Any, json_mode: bool) -> int:
    """obs status: 可观测性状态。"""
    from ..core.observability import AgentObservability

    home = Path(home_dir())
    obs = AgentObservability({"observability.enabled": True}, home=home)
    status = obs.status()
    # 补全: 最近会话的 usage 事件数 (跨进程)
    session = getattr(args, "session", "") or ""
    sf = _resolve_session_file(session)
    usage_events = 0
    if sf:
        usage_events = _count_usage_events(sf)

    if json_mode:
        sys.stdout.write(json.dumps({
            "status": status,
            "session": str(sf) if sf else None,
            "usage_events": usage_events,
        }, ensure_ascii=False, indent=2) + "\n")
        return 0

    console.print("[bold]可观测性状态[/bold]")
    console.print(f"  启用: {'是' if status.get('enabled') else '否'}  "
                  f"trace_id: {status.get('trace_id') or '(无)'}")
    console.print(f"  会话: {sf if sf else '(无)'}")
    console.print(f"  usage 事件: {usage_events}")
    console.print("\n提示: tuan obs cost 看累计成本; tuan obs cache 看缓存命中率")
    return 0


def _count_usage_events(path: Path) -> int:
    """统计会话文件里的 usage 事件数。"""
    n = 0
    try:
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                if '"type": "usage"' in line:
                    n += 1
    except OSError:
        pass
    return n


def _cmd_obs_cost(args: Any, json_mode: bool) -> int:
    """obs cost: 从会话 JSONL 重建累计成本 (跨进程)。"""
    from ..core.agent_helpers import estimate_total_cost
    from ..config import Config

    session = getattr(args, "session", "") or ""
    sf = _resolve_session_file(session)
    if sf is None:
        console.print("[dim]无会话文件 (运行 `tuan chat` 产生会话)[/dim]")
        return 0
    usage = _reconstruct_usage(sf)
    try:
        cfg: Any = Config()
    except Exception:  # noqa: BLE001
        cfg = {}
    cost = estimate_total_cost(cfg, usage)
    if json_mode:
        sys.stdout.write(json.dumps({
            "session": str(sf),
            "cost_usd": round(cost, 6),
            "usage": usage,
        }, ensure_ascii=False, indent=2) + "\n")
        return 0
    console.print(f"[bold]会话成本[/bold] ({sf.name})")
    console.print(f"  累计: [cyan]${cost:.6f}[/cyan] USD")
    if usage:
        console.print(f"  token: prompt={usage.get('prompt_tokens', 0)}  "
                      f"completion={usage.get('completion_tokens', 0)}")
    else:
        console.print("  [dim](该会话无 usage 事件)[/dim]")
    console.print("\n提示: tuan obs cache 看 DeepSeek 前缀缓存命中率")
    return 0


def _cmd_obs_cache(args: Any, json_mode: bool) -> int:
    """obs cache: DeepSeek 前缀缓存命中率 (跨进程重建)。"""
    from ..core.agent_helpers import cache_hit_rate

    session = getattr(args, "session", "") or ""
    sf = _resolve_session_file(session)
    if sf is None:
        console.print("[dim]无会话文件[/dim]")
        return 0
    usage = _reconstruct_usage(sf)
    rate = cache_hit_rate(usage)
    hit = usage.get("prompt_cache_hit_tokens", 0)
    miss = usage.get("prompt_cache_miss_tokens", 0)
    if json_mode:
        sys.stdout.write(json.dumps({
            "session": str(sf),
            "cache_hit_rate": rate,
            "cache_hit_tokens": hit,
            "cache_miss_tokens": miss,
        }, ensure_ascii=False, indent=2) + "\n")
        return 0
    console.print(f"[bold]前缀缓存命中率[/bold] ({sf.name})")
    if rate is None:
        console.print("  [dim](无缓存数据; DeepSeek 模型才产生 hit/miss)[/dim]")
        return 0
    pct = rate * 100
    bar = "█" * int(rate * 20) + "░" * (20 - int(rate * 20))
    console.print(f"  命中率: [cyan]{pct:.1f}%[/cyan]  {bar}")
    console.print(f"  hit={hit}  miss={miss}  (DeepSeek 前缀缓存)")
    return 0


def cmd_obs(args: Any) -> int:
    """`tuan obs` 入口: 可观测性与成本归因。"""
    sub = getattr(args, "obs_cmd", None) or "status"
    json_mode = bool(getattr(args, "json", False))

    if sub == "cost":
        return _cmd_obs_cost(args, json_mode)
    if sub == "cache":
        return _cmd_obs_cache(args, json_mode)
    # 默认 status
    return _cmd_obs_status(args, json_mode)


# 注册本模块的命令函数到全局注册表
from .parser import _register_command  # noqa: E402

import logging
log = logging.getLogger(__name__)

_register_command("cmd_obs", ".cmd_obs")
