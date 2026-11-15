"""韧性可观测性 CLI 命令 (差异化独特能力)。

Claude Code 只有 ``--max-turns`` / ``--max-cost`` 之类的硬限制, 没有任何
**运行时韧性状态**的暴露面。Tuan-CLI 的 ``core.resilience`` 实现了
RateLimiter → RetryPolicy → CircuitBreaker → Failover 四层防线, 但它们的
运行时状态 (熔断是否触发、限流参数、故障转移历史) 此前只能在 REPL 的
``/status`` 里看到, 一旦进程退出就丢失。

本命令把四层韧性的完整状态暴露为可查询的 CLI:
- ``tuan resilience status``  四层防线实时状态 (熔断/限流/重试/故障转移)
- ``tuan resilience history`` 跨会话故障转移历史 (持久化到 ~/.tuan/failover_history.jsonl)
- ``tuan resilience config``  韧性相关配置 (retry/rate_limit/circuit_breaker/failover)

用法::

    tuan resilience status    四层防线实时状态
    tuan resilience history   故障转移历史 (最近 N 次, 跨会话)
    tuan resilience config    韧性配置项 (只读, 含默认值覆盖)
"""

from __future__ import annotations

import json
import sys
from typing import Any, Dict, List

from ..config import Config
from ._ui_singleton import console


# ---------------------------------------------------------------- 配置键提取

def _cfg_retry(config: Any) -> Dict[str, Any]:
    """重试策略配置。"""
    return {
        "max_retries": int(config.get("agent.max_retries", 3) or 0),
        "backoff": float(config.get("agent.retry_backoff", 2.0) or 0.0),
        "jitter": float(config.get("agent.retry_jitter", 0.3) or 0.0),
        "retry_on": [int(x) for x in (config.get("agent.retry_on", []) or [])],
    }


def _cfg_ratelimit(config: Any) -> Dict[str, Any]:
    """限流配置。"""
    rl = config.get("model.rate_limit", {}) or {}
    if isinstance(rl, dict):
        return {
            "enabled": bool(rl.get("enabled", False)),
            "max_rpm": int(rl.get("max_rpm", 0) or 0),
            "max_concurrent": int(rl.get("max_concurrent", 1) or 1),
        }
    return {"enabled": False, "max_rpm": 0, "max_concurrent": 1}


def _cfg_breaker(config: Any) -> Dict[str, Any]:
    """熔断器配置。"""
    cb = config.get("circuit_breaker", {}) or {}
    if isinstance(cb, dict):
        return {
            "enabled": bool(cb.get("enabled", False)),
            "failure_threshold": int(cb.get("failure_threshold", 5) or 5),
            "cooldown": float(cb.get("cooldown", 30.0) or 30.0),
            "success_threshold": int(cb.get("success_threshold", 1) or 1),
        }
    return {"enabled": False, "failure_threshold": 5, "cooldown": 30.0, "success_threshold": 1}


def _cfg_failover(config: Any) -> Dict[str, Any]:
    """故障转移配置。"""
    fo = config.get("model.failover", {}) or {}
    fallbacks = config.get("model.fallbacks", []) or []
    if isinstance(fo, dict):
        return {
            "enabled": bool(fo.get("enabled", True)),
            "sticky_seconds": float(fo.get("sticky_seconds", 120.0) or 120.0),
            "fallbacks": [str(f) for f in fallbacks],
        }
    return {"enabled": True, "sticky_seconds": 120.0, "fallbacks": [str(f) for f in fallbacks]}


# ---------------------------------------------------------------- 实时状态

def _runtime_status() -> Dict[str, Any]:
    """从 Agent 的内核构建器拿韧性运行时状态 (无 Agent 时降级为配置态)。"""
    from ..core.resilience import AgentResilience
    from ..app import build_kernel

    kernel = build_kernel()
    res = AgentResilience(kernel.config if hasattr(kernel, "config") else Config(), kernel)
    return res.status()


# ---------------------------------------------------------------- 命令入口

def cmd_resilience(args: Any) -> int:
    """``tuan resilience`` 顶层分发。"""
    sub = getattr(args, "resilience_cmd", None) or "status"
    json_mode = bool(getattr(args, "json", False))

    if sub == "status":
        return _resilience_status(json_mode)
    if sub == "history":
        return _resilience_history(args, json_mode)
    if sub == "config":
        return _resilience_config(json_mode)
    if sub == "breaker":
        return _resilience_breaker(args, json_mode)
    if sub == "limiter":
        return _resilience_limiter(args, json_mode)
    if sub == "classify":
        return _resilience_classify(args, json_mode)

    console.print("[red]未知子命令:[/red] %s (可用: status / history / config / breaker / limiter / classify)" % sub)
    return 1


def _resilience_status(json_mode: bool) -> int:
    """四层防线实时状态。"""
    try:
        rs = _runtime_status()
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]韧性状态获取失败: {exc}[/red]")
        return 1

    if json_mode:
        sys.stdout.write(json.dumps(rs, ensure_ascii=False, indent=2) + "\n")
        return 0

    br = rs.get("circuit_breaker", {}) or {}
    rl = rs.get("rate_limiter", {}) or {}
    rt = rs.get("retry", {}) or {}
    fo = rs.get("failover", {}) or {}

    console.print("\n[bold]=== 韧性状态 (四层防线) ===[/bold]\n")

    # 熔断器
    if br.get("enabled"):
        state = br.get("state", "closed")
        if state == "closed":
            console.print(f"[green]✓ 熔断器[/green]: 正常 (closed, "
                          f"阈值 {br.get('failure_threshold')} / 冷却 {br.get('cooldown')}s)")
        elif state == "half_open":
            console.print(f"[yellow]◐ 熔断器[/yellow]: 探测中 (half_open, "
                          f"阈值 {br.get('failure_threshold')} / 冷却 {br.get('cooldown')}s)")
        else:
            console.print(f"[red]✗ 熔断器[/red]: 已熔断 (open, "
                          f"冷却 {br.get('cooldown')}s, 连续失败 {br.get('failures', 0)})")
    else:
        console.print("[dim]• 熔断器: 未启用 (circuit_breaker.enabled=false)[/dim]")

    # 限流
    if rl.get("active"):
        conc = f" / 并发<={rl.get('max_concurrent')}" if rl.get("max_concurrent") else ""
        console.print(f"[green]✓ 限流[/green]: 已启用 (<={rl.get('max_rpm')} req/min{conc})")
    else:
        console.print("[dim]• 限流: 未启用 (model.rate_limit.enabled=false)[/dim]")

    # 重试
    console.print(f"[bold]重试[/bold]: <={rt.get('max_retries', 0)} 次 · "
                  f"退避 {rt.get('backoff', 0)}s · 重试图谱 {rt.get('retry_on', [])}")

    # 故障转移
    if fo.get("active"):
        console.print(f"[yellow]◐ 故障转移[/yellow]: 已切到备用 {fo.get('target')} "
                      f"(sticky {fo.get('sticky_seconds')}s) — 已触发 {fo.get('count', 0)} 次")
    elif fo.get("enabled"):
        console.print(f"[green]✓ 故障转移[/green]: 已启用 (sticky {fo.get('sticky_seconds')}s) "
                      f"— 累计 {fo.get('count', 0)} 次")
    else:
        console.print("[dim]• 故障转移: 未启用 (model.failover.enabled=false)[/dim]")

    console.print("\n[dim]提示: tuan resilience history 看跨会话转移记录; "
                  "tuan resilience config 看配置[/dim]")
    return 0


def _resilience_history(args: Any, json_mode: bool) -> int:
    """跨会话故障转移历史。"""
    from ..core.resilience import load_failover_history

    limit = int(getattr(args, "limit", 20) or 20)
    rows = load_failover_history(limit)
    if not rows:
        console.print("[dim]暂无故障转移历史 (主模型从未切换到备用供应商)[/dim]")
        return 0

    if json_mode:
        sys.stdout.write(json.dumps({"total": len(rows), "rows": rows},
                                    ensure_ascii=False, indent=2) + "\n")
        return 0

    console.print(f"\n[bold]=== 故障转移历史 (最近 {len(rows)} 次) ===[/bold]\n")
    for i, r in enumerate(rows, 1):
        ts = r.get("ts", 0)
        when = _fmt_ts(float(ts)) if ts else "?"
        from_p = r.get("from_provider", "?")
        from_m = r.get("from_model", "?")
        to_p = r.get("to_provider", "?")
        to_m = r.get("to_model", "?")
        reason = str(r.get("reason", ""))[:80]
        console.print(f"  {i:3d}. {when}  {from_p}/{from_m} → [green]{to_p}/{to_m}[/green]")
        if reason:
            console.print(f"        [dim]原因: {reason}[/dim]")
    console.print("\n[dim]说明: 每次主模型故障切换到备用供应商即记录一条; "
                  "sticky 窗口内直接走备用不再记录[/dim]")
    return 0


def _resilience_config(json_mode: bool) -> int:
    """韧性相关配置 (只读)。"""
    config = Config()

    payload = {
        "retry": _cfg_retry(config),
        "rate_limit": _cfg_ratelimit(config),
        "circuit_breaker": _cfg_breaker(config),
        "failover": _cfg_failover(config),
    }

    if json_mode:
        sys.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
        return 0

    console.print("\n[bold]=== 韧性配置 ===[/bold]\n")
    rt = payload["retry"]
    console.print(f"[bold]重试[/bold]: <={rt['max_retries']} 次 · 退避 {rt['backoff']}s · "
                  f"抖动 {rt['jitter']} · 重试图谱 {rt['retry_on']}")
    rl = payload["rate_limit"]
    console.print(f"[bold]限流[/bold]: {'启用' if rl['enabled'] else '禁用'} · "
                  f"<={rl['max_rpm']} req/min · 并发<={rl['max_concurrent']}")
    cb = payload["circuit_breaker"]
    console.print(f"[bold]熔断器[/bold]: {'启用' if cb['enabled'] else '禁用'} · "
                  f"阈值 {cb['failure_threshold']} 次 · 冷却 {cb['cooldown']}s · "
                  f"恢复需 {cb['success_threshold']} 次成功")
    fo = payload["failover"]
    console.print(f"[bold]故障转移[/bold]: {'启用' if fo['enabled'] else '禁用'} · "
                  f"sticky {fo['sticky_seconds']}s · 显式回退 {fo['fallbacks'] or '自动选择'}")
    console.print("\n[dim]修改: tuan config set agent.max_retries 5 / "
                  "tuan config set circuit_breaker.enabled true[/dim]")
    return 0


def _resilience_breaker(args: Any, json_mode: bool) -> int:
    """熔断器状态/统计/手动复位 (第 60 个独特功能: 熔断可观测与运维恢复)。

    暴露 ``CircuitBreaker.stats()/state/reset()``:
    - Claude Code 的韧性只有硬上限 (--max-turns/--max-cost), 熔断器开启后
      用户**无从知晓**为何请求变慢/失败, 也无从手动恢复;
    - Tuan-CLI 把熔断器的三态 (closed/open/half_open)、连续失败计数、开启
      时间戳暴露为可查询状态, 并提供 ``--reset`` 手动复位 (运维在确认上游
      恢复后可立即放行, 不必等冷却到期)。

      tuan resilience breaker            # 当前熔断器状态 + 统计
      tuan resilience breaker --reset    # 手动复位到 CLOSED (运维恢复)
      tuan resilience breaker --json     # 机器可读 (CI / 审计)
    """
    from ..core.retry import CircuitBreaker
    from ..config import Config

    config = Config()
    breaker = CircuitBreaker.from_config(config)

    do_reset = bool(getattr(args, "reset", False))
    stats = breaker.stats()

    if do_reset:
        breaker.reset()
        stats = breaker.stats()
        if json_mode:
            sys.stdout.write(json.dumps({
                "reset": True,
                "stats": stats,
            }, ensure_ascii=False, indent=2) + "\n")
            return 0
        console.print("[green]✓ 已手动复位熔断器到 CLOSED[/green]")
        console.print("  [dim]后续调用将正常放行; 连续失败达阈值会再次熔断[/dim]")
        return 0

    if json_mode:
        sys.stdout.write(json.dumps({
            "stats": stats,
            "threshold": {
                "failure": breaker.failure_threshold,
                "success": breaker.success_threshold,
                "cooldown": breaker.cooldown,
            },
        }, ensure_ascii=False, indent=2) + "\n")
        return 0

    console.print("\n[bold]=== 熔断器状态 ===[/bold]\n")
    state = stats.get("state", "closed")
    if state == "closed":
        console.print(f"  状态: [green]CLOSED[/green] (正常放行)")
    elif state == "half_open":
        console.print(f"  状态: [yellow]HALF_OPEN[/yellow] (冷却到期, 放行试探请求)")
    else:
        console.print(f"  状态: [red]OPEN[/red] (已熔断, 快速失败)")
    console.print(f"  连续失败: {stats.get('failures', 0)} "
                  f"(阈值 {breaker.failure_threshold})")
    console.print(f"  连续成功: {stats.get('successes', 0)} "
                  f"(恢复需 {breaker.success_threshold})")
    opened_at = stats.get("opened_at", 0)
    if opened_at and state != "closed":
        from datetime import datetime as _dt
        console.print(f"  开启时刻: {_dt.fromtimestamp(opened_at).strftime('%Y-%m-%d %H:%M:%S')}")
        console.print(f"  冷却窗口: {breaker.cooldown:.1f}s")
    if state == "open":
        console.print("\n[yellow]⚠ 熔断开启中: 调用被快速失败以保护故障上游[/yellow]")
        console.print("  [dim]确认上游恢复后, 用 --reset 立即放行, 或等冷却到期自动转 half_open[/dim]")
    else:
        console.print("\n[dim]确认上游异常时: 用 --reset 手动熔断恢复; "
                      "或 tuan resilience status 看四层防线[/dim]")
    return 0


def _resilience_limiter(args: Any, json_mode: bool) -> int:
    """限流器运行态快照 (第 71 个独特功能: 节流可观测)。

    差异化价值: Claude Code 只有 --max-cost/--max-turns 硬限制, 没有「发送前
    主动节流」的令牌桶, 更无从确认真实节流是否在发生。Tuan-CLI 的 RateLimiter
    用令牌桶控制每分钟请求数, 但此前只能看配置 (enabled/max_rpm), 无法确认真实
    运行态。本命令暴露 ``RateLimiter.snapshot()`` 的实时内部状态:
      - tokens: 当前剩余令牌 (>=1 可立即放行, <1 需等待补齐);
      - waiting: 累计因令牌不足而等待的次数 (区分「从未节流过」vs「真在节流」);
      - last_wait: 最近一次实际等待秒数;
      - in_flight: 当前并发在途请求数。

      tuan resilience limiter            # 限流器实时快照
      tuan resilience limiter --json     # 机器可读 (CI / 审计)
    """
    from ..core.retry import RateLimiter
    from ..config import Config

    config = Config()
    limiter = RateLimiter.from_config(config)
    snap = limiter.snapshot()

    if json_mode:
        sys.stdout.write(json.dumps(snap, ensure_ascii=False, indent=2) + "\n")
        return 0

    console.print("\n[bold]=== 限流器运行态 ===[/bold]\n")
    if not snap["active"]:
        console.print("[dim]• 限流器未启用 (model.rate_limit.enabled=false 或全 0)[/dim]")
        console.print("  [dim]配置: tuan config set model.rate_limit.enabled true / "
                      "model.rate_limit.max_requests_per_minute 10[/dim]")
        return 0

    console.print(f"[green]✓ 限流器已启用[/green]: <={snap['rate']} req/min · "
                  f"并发<={snap['max_concurrent']}")
    tokens = snap["tokens"]
    if tokens >= 1.0:
        console.print(f"  剩余令牌: [green]{tokens:.2f}[/green] (可立即放行)")
    else:
        console.print(f"  剩余令牌: [yellow]{tokens:.2f}[/yellow] (需等待补齐才放行)")
    console.print(f"  累计等待: {snap['waiting']} 次 "
                  f"· 最近等待 {snap['last_wait']}s")
    console.print(f"  在途请求: {snap['in_flight']} "
                  f"(并发上限 {snap['max_concurrent']})")
    if snap["waiting"] == 0:
        console.print("\n[dim]尚未因令牌不足等待过: 请求节奏未触到限流[/dim]")
    else:
        console.print("\n[yellow]⚠ 曾节流[/yellow]: 发送节奏已被令牌桶压低 "
                      "(免费层常见: 1 req/s)")
    return 0


def _fmt_ts(ts: float) -> str:
    """时间戳 → 可读字符串。"""
    try:
        from datetime import datetime
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
    except Exception:  # noqa: BLE001
        return str(ts)


def _resilience_classify(args: Any, json_mode: bool) -> int:
    """错误分类决策可观测 (第 79 个独特功能: 重试裁决预判).

    差异化价值: Claude Code 的重试是黑箱 —— 用户不知道「某类错误会不会被
    重试、重试多久、是不是立即失败」。Tuan-CLI 的 RetryPolicy 用三个纯函数
    做裁决: classify_error (分类) / is_fatal_error (是否致命, 致命则不重试) /
    retry_after_seconds (响应头 Retry-After 秒数)。本命令把它们暴露为可查询,
    用户可预判任意错误文案/类型会被如何处置:

      tuan resilience classify --error "未配置 api key"        # 致命: 不重试
      tuan resilience classify --error "连接超时" --type TimeoutError
      tuan resilience classify --error "429" --json            # 分类+延迟
    """
    from ..core.retry import classify_error, is_fatal_error, retry_after_seconds
    from ..core.errors import ConfigError, ModelError, AuthError

    error_text = getattr(args, "error", None) or ""
    error_type = getattr(args, "type", None) or "runtime"

    # 构造待测异常: 支持常见类型, 便于模拟真实错误
    type_map: Dict[str, type] = {
        "runtime": RuntimeError,
        "value": ValueError,
        "timeout": TimeoutError,
        "connection": ConnectionError,
        "keyerror": KeyError,
        "config": ConfigError,
        "model": ModelError,
        "auth": AuthError,
    }
    exc_cls = type_map.get(error_type.lower(), RuntimeError)
    try:
        exc: Exception = exc_cls(error_text)
    except TypeError:
        exc = exc_cls(error_text)

    kind, status = classify_error(exc)
    fatal = is_fatal_error(exc)
    retry_after = retry_after_seconds(exc)

    verdict = "致命 (不重试)" if fatal else "可重试"
    if json_mode:
        sys.stdout.write(json.dumps({
            "error": error_text,
            "type": error_type,
            "kind": kind,
            "status": status,
            "fatal": fatal,
            "retry_after": retry_after,
            "verdict": verdict,
        }, ensure_ascii=False, indent=2) + "\n")
        return 0

    console.print("\n[bold]=== 错误分类裁决 ===[/bold]\n")
    console.print(f"  错误: [dim]{error_text or '(空)'}[/dim]  (类型 {error_type})")
    console.print(f"  分类: [bold]{kind}[/bold]" + (f" · HTTP {status}" if status else ""))
    if fatal:
        console.print(f"  裁决: [red]{verdict}[/red]")
        console.print("  [dim]重试不可能成功: 配置/参数类错误应 <1s 立即失败, "
                      "而不是指数退避白等[/dim]")
    else:
        console.print(f"  裁决: [green]{verdict}[/green]")
        if retry_after:
            console.print(f"  Retry-After: [yellow]{retry_after:.1f}s[/yellow] "
                          "(服务器建议等待)")
        else:
            console.print("  [dim]无 Retry-After 头: 走 RetryPolicy 的指数退避[/dim]")
    console.print("\n[dim]说明: 与 RetryPolicy 同一套纯函数裁决, 可预判重试行为[/dim]")
    return 0
