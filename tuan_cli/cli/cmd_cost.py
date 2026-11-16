"""成本/使用审计 CLI 命令 —— 「成本可观测性」差异化能力。

Claude Code 只有 ``--max-cost`` 硬上限 (超过即停), 没有**历史审计**。
Tuan-CLI 把每次模型路由决策 (tuan models route) 记入 ``~/.tuan/cost_history.jsonl``,
本命令把这份历史变成可查询的成本/使用报告: 按天聚合、按模型聚合、按供应商聚合。

承载 ``tuan cost`` 子命令及其辅助函数:
- cmd_cost: 成本/使用审计入口
- _cost_report: 按天/模型/供应商聚合报告 (默认)
- _cost_last: 最近 N 条路由决策明细
- _cost_top: 最贵/最频繁的模型 Top-K
- _cost_json: 输出 JSON (CI / SIEM 可消费)

路由: ``tuan_cli/cli/commands.py::_CMD_SOURCES`` 将 cmd_cost 指向本模块。
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List

from ..config.loader import home_dir
from ._ui_singleton import console

import logging
log = logging.getLogger(__name__)


def _load_history() -> List[Dict[str, Any]]:
    """读取成本历史 (JSONL)。文件不存在返回空。"""
    hist = Path(home_dir()) / "cost_history.jsonl"
    if not hist.exists():
        return []
    rows: List[Dict[str, Any]] = []
    try:
        for line in hist.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception as exc:  # noqa: BLE001 - 坏行跳过
                log.debug("_load_history(): 非致命异常已忽略(设计内降级, 不改控制流): %s", exc)
                continue
    except Exception as exc:  # noqa: BLE001
        log.debug("_load_history(): 非致命异常已忽略(设计内降级, 不改控制流): %s", exc)
        return []
    return rows


def cmd_cost(args: Any) -> int:
    """tuan cost 入口: 成本/使用审计。"""
    sub = getattr(args, "cost_cmd", None) or "report"
    last_n = int(getattr(args, "last", 20) or 20)
    top_k = int(getattr(args, "top", 5) or 5)
    json_mode = bool(getattr(args, "json", False))

    rows = _load_history()
    if not rows:
        console.print("[dim]暂无成本历史 (先 tuan models route \"任务\" 产生路由决策)[/dim]")
        return 0

    if sub == "last":
        _cost_last(rows, last_n, json_mode)
        return 0
    if sub == "top":
        _cost_top(rows, top_k, json_mode)
        return 0
    if sub == "budget":
        _cost_budget(rows, json_mode)
        return 0
    if sub == "trend":
        days = int(getattr(args, "days", 14) or 14)
        _cost_trend(rows, days, json_mode)
        return 0
    if sub == "efficiency":
        _cost_efficiency(rows, json_mode)
        return 0
    if sub == "json":
        _cost_json(rows)
        return 0

    # 默认 report
    _cost_report(rows, json_mode)
    return 0


def _cost_report(rows: List[Dict[str, Any]], json_mode: bool) -> None:
    """按天/模型/供应商聚合报告 (默认)。

    区分两种记录 (差异化: 决策配额 vs 实际用量双口径):
    - kind=route 或缺失: 路由决策 (tuan models route 产生, 无 token)
    - kind=usage: 实际 token 消耗 (tuan chat 产生, 真实用量)
    """
    by_day: Counter[str] = Counter()
    by_model: Counter[str] = Counter()
    by_provider: Counter[str] = Counter()
    local_count = 0
    offline_count = 0
    total_diff = 0
    # usage 口径统计
    usage_rows = [r for r in rows if r.get("kind") == "usage"]
    route_rows = [r for r in rows if r.get("kind") != "usage"]
    total_tokens = sum(int(r.get("total_tokens", 0) or 0) for r in usage_rows)
    total_est_cost = sum(
        float(r.get("est_cost_usd", r.get("cost_usd", 0.0)) or 0.0)
        for r in usage_rows)

    for r in route_rows:
        day = (r.get("ts") or "")[:10] or "未知"
        by_day[day] += 1
        by_model[(r.get("provider") or "?") + "/" + (r.get("model") or "?")] += 1
        by_provider[r.get("provider") or "?"] += 1
        if r.get("local"):
            local_count += 1
        if r.get("offline"):
            offline_count += 1
        total_diff += int(r.get("difficulty") or 0)

    if json_mode:
        sys.stdout.write(json.dumps({
            "total": len(rows),
            "route_decisions": len(route_rows),
            "usage_records": len(usage_rows),
            "total_tokens": total_tokens,
            "total_est_cost_usd": round(total_est_cost, 6),
            "by_day": dict(by_day),
            "by_model": dict(by_model),
            "by_provider": dict(by_provider),
            "local_decisions": local_count,
            "offline_decisions": offline_count,
            "avg_difficulty": round(total_diff / len(route_rows), 1) if route_rows else 0,
        }, ensure_ascii=False, indent=2) + "\n")
        return

    console.print("\n[bold]=== 成本/使用审计 (决策配额 + 实际用量双口径) ===[/bold]\n")
    console.print(f"[bold]路由决策[/bold]: {len(route_rows)} 次 | "
                  f"[bold]实际用量记录[/bold]: {len(usage_rows)} 条")
    if usage_rows:
        console.print(f"[bold]实际 token[/bold]: {total_tokens:,} "
                      f"(估算 ${total_est_cost:.4f})")
    console.print(f"[bold]本地模型决策[/bold]: {local_count} "
                  f"([dim]{local_count * 100 // len(route_rows) if route_rows else 0}%[/dim])")
    console.print(f"[bold]离线决策[/bold]: {offline_count}")
    if route_rows:
        console.print(f"[bold]平均难度[/bold]: {total_diff / len(route_rows):.1f}")

    console.print("\n[bold]按天[/bold]")
    for day, n in sorted(by_day.items(), reverse=True):
        console.print(f"  [dim]{day}[/dim]  {n} 次")

    console.print("\n[bold]按模型[/bold]")
    for m, n in by_model.most_common(10):
        console.print(f"  {m}  {n} 次")

    console.print("\n[bold]按供应商[/bold]")
    for p, n in by_provider.most_common(10):
        console.print(f"  {p}  {n} 次")

    console.print("\n[dim]提示: tuan cost last 看明细 / top 看最热模型 / budget 看燃烧率 / --json 给 CI[/dim]")


def _cost_last(rows: List[Dict[str, Any]], last_n: int, json_mode: bool) -> None:
    """最近 N 条路由决策明细。"""
    tail = rows[-last_n:]
    if json_mode:
        sys.stdout.write(json.dumps(tail, ensure_ascii=False, indent=2) + "\n")
        return
    console.print(f"\n[bold]=== 最近 {len(tail)} 条路由决策 ===[/bold]\n")
    for r in reversed(tail):
        tag = "本地" if r.get("local") else ("离线" if r.get("offline") else "远程")
        console.print(f"  [dim]{r.get('ts', '-')}[/dim]  "
                      f"[{tag}] {r.get('provider')}/{r.get('model')}  "
                      f"难度 {r.get('difficulty')}")
        console.print(f"      [dim]{r.get('reason', '')}[/dim]")


def _cost_top(rows: List[Dict[str, Any]], top_k: int, json_mode: bool) -> None:
    """最热/最频繁的模型 Top-K。"""
    by_model = Counter(
        (r.get("provider") or "?") + "/" + (r.get("model") or "?") for r in rows
    )
    if json_mode:
        sys.stdout.write(json.dumps(
            dict(by_model.most_common(top_k)), ensure_ascii=False, indent=2) + "\n")
        return
    console.print(f"\n[bold]=== 最热模型 Top {top_k} ===[/bold]\n")
    for i, (m, n) in enumerate(by_model.most_common(top_k), 1):
        console.print(f"  {i:2d}. {m}  {n} 次")


def _cost_json(rows: List[Dict[str, Any]]) -> None:
    """原始 JSONL 转 JSON 数组 (SIEM / 流水线消费)。"""
    sys.stdout.write(json.dumps(rows, ensure_ascii=False, indent=2) + "\n")


def _cost_budget(rows: List[Dict[str, Any]], json_mode: bool) -> None:
    """预算燃烧率视图: 已用 / 剩余 / 趋势 (差异化: Claude Code 只有单次硬上限)。

    读取 ``router.budget_limit`` (USD), 结合成本历史估算:
    - 预算上限 (0=无限制);
    - 按天燃烧速率 (最近 N 天均值) 与按当前速率耗尽预算的预计天数;
    - 若已用超限 → 告警; 若按趋势将超限 → 预警。
    成本历史目前记录「路由决策次数」而非精确 token 费用, 因此这里给出的是
    「决策配额」口径的预算占用 —— 标注为估算, 路由决策记录不含 token。
    """
    try:
        from ..config.loader import Config  # noqa: PLC0415

        cfg = Config()
        router = cfg.get("router", {}) or {}
        budget = float(router.get("budget_limit") or 0.0)
    except Exception:  # noqa: BLE001
        budget = 0.0

    total_decisions = len(rows)
    # 按天聚合决策数
    by_day: Counter[str] = Counter()
    for r in rows:
        day = (r.get("ts") or "")[:10] or "未知"
        by_day[day] += 1
    days = sorted(by_day)
    recent_days = days[-7:]
    recent_count = sum(by_day[d] for d in recent_days)
    active_days = len(recent_days)
    daily_rate = recent_count / active_days if active_days else 0.0

    # 预算占用 (决策配额口径): budget 作为「预算内允许的决策数」不成立,
    # 故用比例表达: 若设了上限, 用 已用决策数 对比 上限×100 (假设每决策 1 分钱估算)。
    # 诚实: 这是「决策配额」而非精确费用。
    est_cost = total_decisions * 0.01  # 每决策按 $0.01 保守估算 (仅展示量级)
    spent_pct = (est_cost / budget * 100.0) if budget > 0 else 0.0
    remaining = max(budget - est_cost, 0.0)
    # 按当前日速率, 估算剩余天数 (预算内)
    daily_cost = daily_rate * 0.01
    days_left = (remaining / daily_cost) if (daily_cost > 0 and budget > 0) else None

    over = budget > 0 and est_cost > budget
    warning = (not over and budget > 0 and spent_pct >= 70.0)

    # --- 月底预测 (forecast): 最近 7 天日均速率外推到月底 ---
    from datetime import datetime as _dt
    today = _dt.now()
    days_in_month = 30  # 近似
    # 当月已过天数 (至少 1)
    days_elapsed = max(today.day, 1)
    days_remaining = max(days_in_month - days_elapsed, 0)
    forecast_month_end = total_decisions + daily_rate * days_remaining
    forecast_cost = forecast_month_end * 0.01
    forecast_over = budget > 0 and forecast_cost > budget

    if json_mode:
        sys.stdout.write(json.dumps({
            "budget_limit_usd": budget,
            "total_decisions": total_decisions,
            "est_cost_usd": round(est_cost, 4),
            "spent_pct": round(spent_pct, 1),
            "remaining_usd": round(remaining, 4),
            "daily_rate_decisions": round(daily_rate, 2),
            "days_left_at_rate": round(days_left, 1) if days_left is not None else None,
            "over_budget": over,
            "warning": warning,
            "forecast": {
                "days_elapsed": days_elapsed,
                "days_remaining": days_remaining,
                "month_end_decisions": round(forecast_month_end, 1),
                "month_end_cost_usd": round(forecast_cost, 4),
                "forecast_over_budget": forecast_over,
            },
        }, ensure_ascii=False, indent=2) + "\n")
        return

    console.print("\n[bold]=== 成本预算 · 燃烧率 ===[/bold]\n")
    if budget <= 0:
        console.print("[dim]未设置预算上限 (router.budget_limit=0 = 无限制)[/dim]")
        console.print("[dim]提示: tuan run --max-cost 0.5 设单次上限, 或 config 设 router.budget_limit[/dim]")
    else:
        console.print(f"[bold]预算上限[/bold]: ${budget:.2f}")
        console.print(f"[bold]已用 (估算)[/bold]: ${est_cost:.4f} "
                      f"({spent_pct:.1f}%)")
        console.print(f"[bold]剩余[/bold]: ${remaining:.4f}")
        console.print(f"[bold]决策数[/bold]: {total_decisions} 次 "
                      f"(最近{active_days}天日均 {daily_rate:.1f} 次/天)")
        if days_left is not None:
            console.print(f"[bold]按当前速率可撑[/bold]: ~{days_left:.1f} 天")
        if over:
            console.print(f"[red]✗ 已超预算上限! 建议降低模型档位或检查路由策略[/red]")
        elif warning:
            console.print(f"[yellow]⚠ 已用 {spent_pct:.0f}%, 接近预算上限[/yellow]")

    # 月底预测 (无预算上限也展示趋势)
    if daily_rate > 0:
        console.print(f"\n[bold]月底预测[/bold]: 预计 {days_remaining} 天后达 "
                      f"{forecast_month_end:.0f} 次决策 (约 ${forecast_cost:.4f})")
        if budget > 0 and forecast_over:
            console.print(f"[red]✗ 按当前速率将超预算 (预计 ${forecast_cost:.4f} > 上限 ${budget:.2f})[/red]")
        elif budget > 0:
            console.print(f"[green]✓ 按当前速率月底在预算内[/green]")

    console.print("\n[dim]口径: 每决策按 $0.01 保守估算, 展示量级而非精确费用; "
                  "精确费用需 token 计价 (见 --json 结构)。[/dim]")


def _cost_trend(rows: List[Dict[str, Any]], days: int, json_mode: bool) -> None:
    """成本历史趋势 ASCII 柱状图 (差异化: Claude Code 无任何可视化)。

    按天聚合路由决策数, 用 ASCII 柱状图直观呈现「哪天最活跃 / 是否放缓」,
    并把实际 token 用量 (kind=usage) 叠加为第二行, 形成双口径趋势。
    窗口默认最近 ``days`` 天 (含今天), 无数据的天显示为 0。
    """
    from datetime import datetime as _dt

    # 只保留最近 N 天的日期桶 (含今天)
    today = _dt.now()
    dates: List[str] = []
    for offset in range(days - 1, -1, -1):
        d = today - _dt.timedelta(days=offset) if hasattr(_dt, "timedelta") else None
        if d is None:
            # 兜底 (极老 Python): 手算
            from datetime import timedelta as _td
            d = today - _td(days=offset)
        dates.append(d.strftime("%Y-%m-%d"))

    dec: Dict[str, int] = {d: 0 for d in dates}
    tok: Dict[str, int] = {d: 0 for d in dates}
    for r in rows:
        day = (r.get("ts") or "")[:10]
        if day in dec:
            dec[day] += 1
            if r.get("kind") == "usage":
                tok[day] += int(r.get("total_tokens", 0) or 0)

    max_dec = max(dec.values()) if dec else 0
    max_tok = max(tok.values()) if tok else 0

    if json_mode:
        sys.stdout.write(json.dumps({
            "window_days": days,
            "by_day": [
                {"date": d, "decisions": dec[d], "tokens": tok[d]} for d in dates
            ],
            "max_decisions": max_dec,
            "max_tokens": max_tok,
        }, ensure_ascii=False, indent=2) + "\n")
        return

    console.print(f"\n[bold]=== 成本趋势 · 最近 {days} 天 ===[/bold]\n")

    if max_dec <= 0:
        console.print("[dim]窗口内无路由决策记录[/dim]")
        return

    # 柱高 10 行, 顶部标数值
    height = 10
    chart: List[str] = []
    for row in range(height, 0, -1):
        line_parts: List[str] = []
        for d in dates:
            v = dec[d]
            if v == 0:
                line_parts.append("  ")
            else:
                bar_h = max(1, int(round(v / max_dec * height)))
                line_parts.append("██" if bar_h >= row else "  ")
        # 数值行: 最高柱行标出峰值
        if row == height:
            peak_v = max_dec
            idx = next(i for i, d in enumerate(dates) if dec[d] == peak_v)
            line_parts[idx] = f"{peak_v:2d}" if peak_v < 100 else "##"
        chart.append("  " + "".join(line_parts))
    for ln in chart:
        console.print(ln)

    # 日期轴 (每周标一次, 避免拥挤)
    axis = []
    for i, d in enumerate(dates):
        if i % 3 == 0 or i == len(dates) - 1:
            axis.append(d[5:])  # MM-DD
        else:
            axis.append("     ")
    console.print("  " + "".join(axis))

    # 双口径: token 趋势 (若有)
    if max_tok > 0:
        console.print(f"\n[bold]实际 token 趋势[/bold] (仅 kind=usage 记录)")
        tok_line: List[str] = []
        for d in dates:
            v = tok[d]
            if v == 0:
                tok_line.append("·")
            else:
                bar_h = max(1, int(round(v / max_tok * 8)))
                tok_line.append("#" * bar_h + "." * (8 - bar_h))
        console.print("  " + "  ".join(tok_line))

    console.print(f"\n[dim]峰值 {max_dec} 次/天; "
                  f"窗口内共 {sum(dec.values())} 次决策; "
                  f"tuan cost budget 看燃烧率 / report 看聚合[/dim]")


def _cost_efficiency(rows: List[Dict[str, Any]], json_mode: bool) -> None:
    """成本效率归因 (差异化: Claude Code 无「每 token 单价」可观测性)。

    对 ``kind=usage`` 的实际用量记录, 按模型/供应商聚合 token 总量与估算费用,
    计算每 1k token 的成本 (``est_cost_usd / total_tokens * 1000``), 按效率
    排序 (最便宜在前)。这让用户一眼看出「同样 1k token, 谁最烧钱 / 谁最划算」,
    是成本可观测性 (tuan cost) 的最后一块拼图: report 看总量, trend 看趋势,
    efficiency 看单价。

    无 usage 记录时给出提示 (路由决策记录不含 token, 无法按单价换算)。
    """
    usage_rows = [r for r in rows if r.get("kind") == "usage"]
    if not usage_rows:
        if json_mode:
            sys.stdout.write(json.dumps({
                "usage_records": 0,
                "note": "无实际用量记录; tuan chat 产生 kind=usage 后才可归因",
            }, ensure_ascii=False, indent=2) + "\n")
        else:
            console.print("[dim]暂无实际用量记录, 无法归因单价; "
                          "先跑 tuan chat 产生 kind=usage, 或 tuan cost report 看总览[/dim]")
        return

    # 聚合: 模型级 + 供应商级 (key 用 provider/model 组合)
    agg: Dict[str, Dict[str, Any]] = {}
    for r in usage_rows:
        provider = r.get("provider") or "?"
        model = r.get("model") or "?"
        tokens = int(r.get("total_tokens", 0) or 0)
        cost = float(r.get("est_cost_usd", r.get("cost_usd", 0.0)) or 0.0)
        # 模型级 key
        mk = f"{provider}/{model}"
        for key, label in ((mk, model), (provider, provider)):
            bucket = agg.setdefault(key, {"label": label, "provider": provider,
                                          "model": model if key == mk else "",
                                          "tokens": 0.0, "cost": 0.0, "calls": 0.0})
            bucket["tokens"] += tokens
            bucket["cost"] += cost
            bucket["calls"] += 1

    # 计算每 1k token 成本 (tokens=0 视为无穷大, 排最后)
    efficiency: List[Dict[str, Any]] = []
    for ekey, eb in agg.items():
        etokens = float(eb["tokens"])
        ecost = float(eb["cost"])
        per1k = (ecost / etokens * 1000.0) if etokens > 0 else None
        efficiency.append({
            "key": ekey,
            "label": eb["label"],
            "provider": eb["provider"],
            "model": eb["model"],
            "calls": int(eb["calls"]),
            "total_tokens": int(etokens),
            "total_cost_usd": round(ecost, 6),
            "cost_per_1k": round(per1k, 6) if per1k is not None else None,
        })

    # 按每 1k 成本升序 (None 排最后)
    efficiency.sort(key=lambda e: (e["cost_per_1k"] is None, e["cost_per_1k"] or 0.0))

    if json_mode:
        sys.stdout.write(json.dumps({
            "usage_records": len(usage_rows),
            "rows": efficiency,
        }, ensure_ascii=False, indent=2) + "\n")
        return

    console.print("\n[bold]=== 成本效率归因 · 每 1k token 单价 ===[/bold]\n")
    console.print(f"[dim]基于 {len(usage_rows)} 条实际用量记录 (kind=usage); "
                  f"最低单价在前[/dim]\n")

    # 分隔模型级 / 供应商级 (key 含 "/" 是模型级)
    model_rows = [e for e in efficiency if e["model"]]
    provider_rows = [e for e in efficiency if not e["model"]]

    def _render_rows(title: str, rows_e: List[Dict[str, Any]]) -> None:
        if not rows_e:
            return
        console.print(f"[bold]{title}[/bold]")
        for i, e in enumerate(rows_e, 1):
            per1k = e["cost_per_1k"]
            cost_str = f"${per1k:.4f}/1k" if per1k is not None else "[dim]无 token 数据[/dim]"
            console.print(f"  {i:2d}. {e['label']:<32} "
                          f"{e['total_tokens']:>10,} tok  "
                          f"${e['total_cost_usd']:.4f}  "
                          f"{cost_str}  ({e['calls']} 次)")
        console.print("")

    _render_rows("按模型", model_rows)
    _render_rows("按供应商", provider_rows)

    if model_rows and model_rows[0]["cost_per_1k"] is not None:
        best = model_rows[0]
        worst = model_rows[-1] if model_rows[-1]["cost_per_1k"] is not None else None
        console.print(f"[green]最划算[/green]: {best['label']} "
                      f"(${best['cost_per_1k']:.4f}/1k)")
        if worst and worst["key"] != best["key"]:
            console.print(f"[yellow]最贵[/yellow]: {worst['label']} "
                          f"(${worst['cost_per_1k']:.4f}/1k)")

    console.print("\n[dim]提示: 单价=估算费用/token×1000; 低单价是路由偏好依据, "
                  "但需结合能力覆盖 (tuan models capabilities)[/dim]")
