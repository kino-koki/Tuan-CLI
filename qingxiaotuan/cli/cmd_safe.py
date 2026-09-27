"""qxt safe —— 安全总入口 (整合白名单 / 本地黑名单减负 / 状态 / 更新)。

把原先分散的 ``qxt security`` 与 ``qxt whitelist`` 收敛为一个简洁入口, 降低上手难度:

  qxt safe                      安全总览 (等同 status)
  qxt safe status               安全系统状态 + 审计概览
  qxt safe list                 列出白名单
  qxt safe allow <命令>         把命令加入白名单 (用户在本地自主添加)
  qxt safe deny <命令>          从白名单移除
  qxt safe blacklist            列出内置黑名单模式 (标注已减负)
  qxt safe reduce <关键字>      抑制匹配关键字的黑名单模式 (本地减负)
  qxt safe restore <关键字>     恢复被抑制的黑名单模式
  qxt safe update               更新安全策略 (月度检查)
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..config.loader import home_dir
from ._ui_singleton import console


def _repo_root() -> Path:
    # 定位仓库根 (qingxiaotuan/cli/cmd_safe.py -> 根)
    return Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------- 分发入口

def cmd_safe(args) -> int:
    """安全总入口命令。"""
    safe_cmd = getattr(args, "safe_cmd", None) or "status"

    if safe_cmd == "status":
        return _cmd_status()
    elif safe_cmd == "list":
        return _cmd_whitelist_list()
    elif safe_cmd == "allow":
        return _cmd_whitelist_add(args)
    elif safe_cmd == "deny":
        return _cmd_whitelist_remove(args)
    elif safe_cmd == "blacklist":
        return _cmd_blacklist()
    elif safe_cmd == "reduce":
        return _cmd_reduce(args)
    elif safe_cmd == "restore":
        return _cmd_restore(args)
    elif safe_cmd == "bench":
        return _cmd_bench(args)
    elif safe_cmd == "report":
        return _cmd_report(args)
    elif safe_cmd == "suggest":
        return _cmd_suggest(args)
    else:
        console.print(f"[red]未知子命令: {safe_cmd}[/red]")
        console.print("可用: status / list / allow / deny / blacklist / reduce / restore / update / bench / report")
        return 1


# ---------------------------------------------------------------- 状态总览

def _cmd_status() -> int:
    """安全系统状态 + 审计概览。"""
    console.print("\n[bold]=== 青小团 · 安全总览 ===[/bold]\n")

    # 白名单
    try:
        from ..core.whitelist import WhitelistManager
        wl = WhitelistManager()
        entries = wl.list()
        console.print(f"[bold]白名单[/bold]: {len(entries)} 条 (存储于 {wl._path})")
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]白名单读取失败: {exc}[/red]")

    # 黑名单减负
    try:
        from ..core import blacklist_override
        suppressed = blacklist_override.list_suppressed()
        if suppressed:
            console.print(f"[bold]黑名单减负[/bold]: 已抑制 {len(suppressed)} 个关键字 -> "
                          f"{', '.join(suppressed)}")
        else:
            console.print("[bold]黑名单减负[/bold]: 未启用 (内置黑名单全部生效)")
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]黑名单减负读取失败: {exc}[/red]")

    # 安全引擎
    try:
        from ..ext.safety_engine import SafetyEngine
        methods = SafetyEngine().list_methods()
        console.print(f"[bold]安全引擎[/bold]: v{methods.get('version', '?')} "
                      f"能力 {', '.join(methods.get('capabilities', []))}")
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]安全引擎读取失败: {exc}[/red]")

    # 审计概览
    try:
        from ..core.security_bus import get_security_bus
        bus = get_security_bus()
        stats = bus.get_stats()
        console.print(f"[bold]审计[/bold]: 累计 {stats.get('total_events', 0)} 条事件 "
                      f"(critical {stats.get('by_severity', {}).get('critical', 0)})")
        console.print(f"    落盘: {bus._persist_path or '(未持久化, 仅内存)'}")
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]审计读取失败: {exc}[/red]")

    # 月度更新
    try:
        from ..ext.security_policy import check_monthly_update
        upd = check_monthly_update()
        if upd.get("due"):
            console.print(f"[yellow]⚠️ {upd.get('message', '安全策略待更新')}[/yellow]")
        else:
            console.print(f"[green]✓ {upd.get('message', '安全策略已是最新')}[/green]")
    except Exception as exc:  # noqa: BLE001
        console.print(f"[dim]更新检查跳过: {exc}[/dim]")

    console.print("\n[dim]完整明细: qxt safe blacklist / qxt safe list / qxt safe update[/dim]")
    return 0


# ---------------------------------------------------------------- 白名单 (用户在本地自主添加)

def _cmd_whitelist_list() -> int:
    try:
        from ..core.whitelist import WhitelistManager
        wl = WhitelistManager()
        entries = wl.list()
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]白名单读取失败: {exc}[/red]")
        return 1

    if not entries:
        console.print("[yellow]白名单为空 (用 qxt safe allow <命令> 添加)[/yellow]")
        return 0

    console.print(f"\n[bold]白名单条目 ({len(entries)} 个):[/bold]\n")
    for i, entry in enumerate(entries, 1):
        cmd = entry.get("command", "")
        desc = entry.get("description", "")
        console.print(f"  {i:2d}. {cmd:<20s} {desc}")
    return 0


def _cmd_whitelist_add(args) -> int:
    command = getattr(args, "command", None)
    if not command:
        console.print("[red]用法: qxt safe allow <命令>[/red]")
        return 1
    description = getattr(args, "description", "") or "用户本地自主添加"

    try:
        from ..ext.safety_engine import is_redline
        from ..core.whitelist import WhitelistManager
        if is_redline(command):
            console.print(f"[red]红线命令无法加入白名单: {command}[/red]")
            return 1
        wl = WhitelistManager()
        if wl.add(command, description):
            console.print(f"[green]已加入白名单: {command}[/green]")
        else:
            console.print(f"[yellow]已在白名单中: {command}[/yellow]")
        return 0
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]添加失败: {exc}[/red]")
        return 1


def _cmd_whitelist_remove(args) -> int:
    command = getattr(args, "command", None)
    if not command:
        console.print("[red]用法: qxt safe deny <命令>[/red]")
        return 1
    try:
        from ..core.whitelist import WhitelistManager
        wl = WhitelistManager()
        if wl.remove(command):
            console.print(f"[green]已从白名单移除: {command}[/green]")
        else:
            console.print(f"[yellow]不在白名单中: {command}[/yellow]")
        return 0
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]移除失败: {exc}[/red]")
        return 1


# ---------------------------------------------------------------- 本地黑名单减负

def _cmd_blacklist() -> int:
    """列出内置黑名单模式库, 标注哪些已被用户本地抑制。"""
    try:
        from ..core import blacklist_override
        from ..ext.safety_engine import SafetyEngine
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]黑名单读取失败: {exc}[/red]")
        return 1

    engine = SafetyEngine()
    levels = [
        ("CRITICAL (致命)", engine.CRITICAL_PATTERNS),
        ("HIGH (高危)", engine.HIGH_PATTERNS),
        ("MEDIUM (中危)", engine.MEDIUM_PATTERNS),
    ]

    console.print("\n[bold]内置黑名单模式库[/bold] (label 关键字可被 qxt safe reduce 本地抑制)\n")
    idx = 0
    for title, patterns in levels:
        console.print(f"[bold]{title}[/bold]: {len(patterns)} 条")
        for _pattern, label in patterns:
            idx += 1
            if blacklist_override.is_suppressed(label):
                console.print(f"  [dim]{idx:3d}. [已减负] {label}[/dim]")
            else:
                console.print(f"  {idx:3d}. {label}")
        console.print("")

    suppressed = blacklist_override.list_suppressed()
    if suppressed:
        console.print(f"[yellow]当前已抑制关键字 ({len(suppressed)}): {', '.join(suppressed)}[/yellow]")
        console.print("[dim]恢复: qxt safe restore <关键字>[/dim]")
    else:
        console.print("[dim]尚未抑制任何模式。减负示例: qxt safe reduce dd[/dim]")
    return 0


def _cmd_reduce(args) -> int:
    keyword = getattr(args, "keyword", None)
    if not keyword:
        console.print("[red]用法: qxt safe reduce <关键字>[/red]")
        console.print("[dim]关键字会按 label 子串匹配, 例如: dd / format / shutdown / docker[/dim]")
        return 1
    try:
        from ..core import blacklist_override
        if blacklist_override.suppress(keyword):
            console.print(f"[green]已抑制匹配 '{keyword}' 的黑名单模式 (本地生效)[/green]")
            console.print("[dim]查看影响: qxt safe blacklist  |  撤销: qxt safe restore "
                          f"{keyword}[/dim]")
            return 0
        console.print(f"[yellow]关键字 '{keyword}' 已处于抑制状态, 无需重复操作[/yellow]")
        return 0
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]抑制失败: {exc}[/red]")
        return 1


def _cmd_restore(args) -> int:
    keyword = getattr(args, "keyword", None)
    if not keyword:
        console.print("[red]用法: qxt safe restore <关键字>[/red]")
        return 1
    try:
        from ..core import blacklist_override
        if blacklist_override.release(keyword):
            console.print(f"[green]已恢复匹配 '{keyword}' 的黑名单模式 (重新生效)[/green]")
            return 0
        console.print(f"[yellow]关键字 '{keyword}' 未被抑制, 无需恢复[/yellow]")
        return 0
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]恢复失败: {exc}[/red]")
        return 1


# ---------------------------------------------------------------- 策略更新

def _cmd_update() -> int:
    console.print("\n[bold]=== 安全策略更新 ===[/bold]\n")
    try:
        from ..ext.security_policy import check_monthly_update, record_monthly_update
        status = check_monthly_update()
        if not status.get("due"):
            console.print(f"[green]✓ {status.get('message', '已是最新')}[/green]")
            console.print("[dim]无需更新[/dim]")
            return 0
        console.print(f"[yellow]{status.get('message', '有待更新项')}[/yellow]")
        record_monthly_update()
        console.print("[green]✓ 已记录更新时间[/green]")
        console.print("\n[bold]更新步骤:[/bold]")
        console.print("  1. 检查新发现的攻击模式")
        console.print("  2. 更新 _CRITICAL_PATTERNS / _HIGH_PATTERNS / _MEDIUM_PATTERNS")
        console.print("  3. 运行测试确认无回归 (pytest tests/)")
        console.print("  4. 更新 CHANGELOG.md 与 SECURITY.md")
        return 0
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]更新检查失败: {exc}[/red]")
        return 1


# ---------------------------------------------------------------- 安全替代建议

def _cmd_suggest(args) -> int:
    """对一条命令给出命令感知的安全替代建议 (交互式查询)。"""
    command = args.command
    from ..ext.safety_engine import SafetyEngine

    scored = SafetyEngine().score({"command": command, "type": "shell"})
    console.print(f"\n[bold]命令:[/bold] {command}")
    console.print(f"[bold]风险:[/bold] {scored['risk']} (score {scored['score']})"
                  f"{'  [red]将被拦截[/red]' if scored['block'] else ''}")
    if scored["reasons"]:
        console.print("[bold]命中理由:[/bold]")
        for r in scored["reasons"]:
            console.print(f"  [yellow]• {r}[/yellow]")
    console.print("\n[bold]安全替代建议:[/bold]")
    sugs = scored["suggestions"]
    if not sugs:
        console.print("  [green]✓ 未发现需要替代的危险形态[/green]")
    else:
        for i, s in enumerate(sugs, 1):
            console.print(f"  {i}. {s}")
    return 0


# ---------------------------------------------------------------- 安全基准 (一键复现)

def _cmd_bench(args) -> int:
    """一键复现安全基准: 对抗样本 + PowerShell + 绕过矩阵, 汇总为可引用报告。

    第三方可用同一条命令在本仓库复现安全数字 (不依赖网络, 不调用模型)。
    """
    root = _repo_root()
    bench_dir = root / "bench"
    py = sys.executable
    quick = bool(getattr(args, "quick", False))
    count = 2000 if quick else 10000
    out_arg = getattr(args, "out", None)
    check = bool(getattr(args, "check", False))
    full = bool(getattr(args, "full", False))
    if out_arg:
        out_path = Path(out_arg)
    elif quick:
        # quick 自检绝不覆盖全量存档 (全量数字才是宣传口径 / CI 门禁参照):
        # 原实现仅在 check 时走此分支, 单独 --quick 会误覆盖 security-bench.json。
        out_path = bench_dir / "security-bench.quick.json"
    else:
        out_path = bench_dir / "security-bench.json"

    # --check 固定与全量存档 (bench/security-bench.json) 对比
    ref_path = bench_dir / "security-bench.json"
    prev_archive: dict[str, Any] | None = None
    if (check or full) and ref_path.exists():
        try:
            prev_archive = json.loads(ref_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            prev_archive = None

    console.print(f"\n[bold]=== 青小团 · 安全基准 (一键复现) ===[/bold]\n")
    console.print(f"[dim]引擎: 本仓库代码 + 当前 Python 运行时 ({py})\n[/dim]")

    results: dict[str, Any] = {}

    # 1) 对抗样本基准 (bash/通用命令)
    tmp10k = bench_dir / f".run_tmp_10k_{os.getpid()}.json"
    console.print(f"[bold]1/3 对抗样本基准[/bold] ({count} 条, 随机种子 20260906, 可复现)...")
    try:
        r1 = subprocess.run(
            [py, str(bench_dir / "safety_bench_10k.py"),
             "--count", str(count), "--seed", "20260906", "--out", str(tmp10k)],
            capture_output=True, text=True, timeout=600,
        )
        if tmp10k.exists():
            data = json.loads(tmp10k.read_text(encoding="utf-8"))
            results["adversarial"] = data
            console.print(f"  [green]✓ 拦截召回 {data.get('block_recall')}%  "
                          f"标记召回 {data.get('flag_catch')}%  误杀率 {data.get('false_positive_rate')}%  "
                          f"绕过 {data.get('bypass')}[/green]")
        else:
            console.print(f"[red]✗ 对抗基准无输出: {r1.stderr[-500:]}[/red]")
            results["adversarial"] = {"error": (r1.stderr or "")[-500:]}
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]✗ 对抗基准失败: {exc}[/red]")
        results["adversarial"] = {"error": str(exc)}
    finally:
        if tmp10k.exists():
            tmp10k.unlink()

    # 2) PowerShell 基准 (脚本固定写 ps_safety_result.json)
    ps_json = bench_dir / "ps_safety_result.json"
    console.print("[bold]2/3 PowerShell 基准[/bold] (5000 条: 危险 2300 / 安全 2700)...")
    try:
        r2 = subprocess.run(
            [py, str(bench_dir / "bench_powershell_safety.py")],
            capture_output=True, text=True, timeout=600,
        )
        if ps_json.exists():
            data = json.loads(ps_json.read_text(encoding="utf-8"))
            results["powershell"] = data
            ps_acc = data.get("accuracy", data.get("correct_rate"))
            if isinstance(ps_acc, (int, float)) and ps_acc <= 1:
                ps_acc = round(ps_acc * 100, 2)
            console.print(f"  [green]✓ 正确率 {ps_acc}%  "
                          f"漏放 {data.get('fn', 0)}  误杀 {data.get('fp', 0)}[/green]")
        else:
            console.print(f"[red]✗ PS 基准无输出: {r2.stderr[-500:]}[/red]")
            results["powershell"] = {"error": (r2.stderr or "")[-500:]}
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]✗ PS 基准失败: {exc}[/red]")
        results["powershell"] = {"error": str(exc)}

    # 3) 绕过矩阵 (手工对抗载荷 + 后果级断言)
    tmp_bypass = bench_dir / f".run_tmp_bypass_{os.getpid()}.json"
    console.print("[bold]3/3 绕过矩阵[/bold] (手工对抗载荷 + 灾难后果级断言)...")
    try:
        r3 = subprocess.run(
            [py, str(bench_dir / "bypass_matrix.py"), "--json-out", str(tmp_bypass)],
            capture_output=True, text=True, timeout=600,
        )
        if tmp_bypass.exists():
            data = json.loads(tmp_bypass.read_text(encoding="utf-8"))
            results["bypass_matrix"] = data
            disaster = "100%" if data.get("all_disaster_blocked") else "存在漏拦"
            console.print(f"  [green]✓ 绕过 {data.get('bypass')}  误杀 {data.get('false_pos')}  "
                          f"灾难类别拦截: {disaster}[/green]")
        else:
            console.print(f"[red]✗ 绕过矩阵无输出: {r3.stderr[-500:]}[/red]")
            results["bypass_matrix"] = {"error": (r3.stderr or "")[-500:]}
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]✗ 绕过矩阵失败: {exc}[/red]")
        results["bypass_matrix"] = {"error": str(exc)}
    finally:
        if tmp_bypass.exists():
            tmp_bypass.unlink()

    # 引擎版本
    try:
        from ..ext.safety_engine import SafetyEngine
        methods = SafetyEngine().list_methods()
        results["engine"] = {"version": methods.get("version"), "capabilities": methods.get("capabilities")}
    except Exception:  # noqa: BLE001
        results["engine"] = {"version": None, "capabilities": []}

    results["generated_at"] = datetime.now(timezone.utc).isoformat()
    results["seed"] = 20260906
    results["quick"] = quick
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    console.print(f"\n[green]✓ 汇总已写入: {out_path}[/green]")
    console.print("[dim]引用于 README 时注明: 复现命令 qxt safe bench (或第三方直接跑 bench/ 下脚本)[/dim]")

    rc = 0
    if check:
        if prev_archive is None:
            console.print("[yellow]⚠ --check: 未找到可对比的存档 (先不带 --check 跑一次生成基准)[/yellow]")
        else:
            problems = _check_no_regression(results, prev_archive)
            if problems:
                console.print("[red]✗ 数字回归门禁未通过:[/red]")
                for msg in problems:
                    console.print(f"  [red]• {msg}[/red]")
                console.print("[dim]提示: 代码改动让安全指标变差了 — 先修复再提交, 不要用新数字覆盖存档掩盖回归[/dim]")
                rc = 1
            else:
                console.print("[green]✓ 数字回归门禁通过 (与存档一致或更好)[/green]")
    if full and prev_archive is not None:
        _render_drift_report(results, prev_archive)
    elif full:
        console.print("[yellow]⚠ --full: 未找到可对比的存档 (先不带 --full 跑一次生成基准)[/yellow]")
    return rc


_DRIFT_FIELDS = [
    ("adversarial", "block_recall", "拦截召回%", 1),
    ("adversarial", "flag_catch", "标记召回%", 1),
    ("adversarial", "false_positive_rate", "误杀率%", 1),
    ("adversarial", "bypass", "绕过", 0),
    ("powershell", "accuracy", "正确率%", 1),
    ("powershell", "fn", "漏放", 0),
    ("powershell", "fp", "误杀", 0),
    ("bypass_matrix", "bypass", "绕过", 0),
    ("bypass_matrix", "false_pos", "误杀", 0),
]

def _render_drift_report(new: dict[str, Any], ref: dict[str, Any]) -> None:
    """输出本跑 vs 存档的数字漂移表: 旧值→新值→Δ, 显著变差标红。"""
    console.print("\n[bold]── 数字漂移报告 (本跑 vs 存档) ──[/bold]")
    console.print("[dim]口径: 存档 = " + str(ref.get("generated_at", "?"))[:19] + "; 本跑 = " + str(new.get("generated_at", "?"))[:19] + "[/dim]")
    rows = []
    for section, key, label, nd in _DRIFT_FIELDS:
        old_v = (ref.get(section) or {}).get(key)
        new_v = (new.get(section) or {}).get(key)
        if old_v is None or new_v is None:
            continue
        if isinstance(old_v, (int, float)) and isinstance(new_v, (int, float)):
            delta = new_v - old_v
            if nd == 1 and abs(old_v) <= 1:  # 比例转百分数 (0.x -> x.x%)
                old_v, new_v, delta = old_v * 100, new_v * 100, delta * 100
            delta_s = f"{delta:+.2f}"
            worse = delta > 0 if key in ("false_positive_rate", "false_pos", "fp", "fn", "bypass") else delta < 0
        else:
            delta_s, worse = "n/a", False
        rows.append((section + "." + key, f"{old_v}", f"{new_v}", delta_s, worse))
    if not rows:
        console.print("  (无可对比字段)")
        return
    w1 = max(len(r[0]) for r in rows)
    w2 = max(len(r[1]) for r in rows)
    w3 = max(len(r[2]) for r in rows)
    console.print(f"  {'指标':<{w1}}  {'存档':>{w2}}  {'本跑':>{w3}}  Δ")
    for name, old_s, new_s, delta_s, worse in rows:
        marker = "  [red]▲ 变差[/red]" if worse else ""
        console.print(f"  {name:<{w1}}  {old_s:>{w2}}  {new_s:>{w3}}  {delta_s:<8}{marker}")
    console.print("[dim]注: 误杀/漏放/绕过上升、召回下降均标红; fail-closed 优先, 误杀小幅上升可接受。[/dim]")


def _check_no_regression(new: dict[str, Any], ref: dict[str, Any]) -> list[str]:
    """对比新结果与存档, 返回安全指标变差的清单 (空列表 = 无回归)。"""
    problems: list[str] = []

    adv_n = new.get("adversarial") or {}
    adv_r = ref.get("adversarial") or {}
    if adv_n and adv_r:
        nr, rr = adv_n.get("block_recall"), adv_r.get("block_recall")
        if isinstance(nr, (int, float)) and isinstance(rr, (int, float)) and nr < rr - 1e-9:
            problems.append(f"对抗样本 拦截召回 {nr}% < 存档 {rr}%")
        nb, rb = adv_n.get("bypass"), adv_r.get("bypass")
        if isinstance(nb, int) and isinstance(rb, int) and nb > rb:
            problems.append(f"对抗样本 绕过 {nb} > 存档 {rb}")
        nfp, rfp = adv_n.get("false_positive_rate"), adv_r.get("false_positive_rate")
        if isinstance(nfp, (int, float)) and isinstance(rfp, (int, float)) and nfp > rfp + 1.0:
            problems.append(f"对抗样本 误杀率 {nfp}% 较存档 {rfp}% 上升超过 1 个百分点")

    ps_n = new.get("powershell") or {}
    ps_r = ref.get("powershell") or {}
    if ps_n and ps_r:
        for k, label in (("fn", "漏放"), ("fp", "误杀")):
            nv, rv = ps_n.get(k), ps_r.get(k)
            if isinstance(nv, int) and isinstance(rv, int) and nv > rv:
                problems.append(f"PowerShell {label} {nv} > 存档 {rv}")

    bm_n = new.get("bypass_matrix") or {}
    bm_r = ref.get("bypass_matrix") or {}
    if bm_n and bm_r:
        nb, rb = bm_n.get("bypass"), bm_r.get("bypass")
        if isinstance(nb, int) and isinstance(rb, int) and nb > rb:
            problems.append(f"绕过矩阵 绕过 {nb} > 存档 {rb}")
        if bm_r.get("all_disaster_blocked") and not bm_n.get("all_disaster_blocked"):
            problems.append("绕过矩阵 灾难意图类别不再全部拦截")
    return problems


def _git_head_short(root: Path) -> str | None:
    """取仓库当前提交短哈希 (用于报告与数字绑定)。"""
    try:
        r = subprocess.run(["git", "-C", str(root), "rev-parse", "--short", "HEAD"],
                           capture_output=True, text=True, timeout=10)
        out = (r.stdout or "").strip()
        return out or None
    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------------- 安全报告 (HTML)

def _cmd_report(args) -> int:
    """生成自包含 HTML 安全报告 (宣传 / 审计 / 交接用)。"""
    root = _repo_root()
    bench_dir = root / "bench"
    out_arg = getattr(args, "out", None)
    out_path = Path(out_arg) if out_arg else root / "security-report.html"
    release = bool(getattr(args, "release", False))

    bench_data: dict[str, Any] = {}
    for candidate in (bench_dir / "security-bench.json", bench_dir / "safety_10k_result_current.json",
                      bench_dir / "safety_10k_result.json", bench_dir / "safety_50k_result.json"):
        if candidate.exists():
            try:
                bench_data = json.loads(candidate.read_text(encoding="utf-8"))
                break
            except Exception:  # noqa: BLE001
                continue

    # ---- 状态采集 (全部容错) ----
    state: dict[str, Any] = {}
    try:
        from ..core.whitelist import WhitelistManager
        wl = WhitelistManager()
        state["whitelist_count"] = len(wl.list())
    except Exception:  # noqa: BLE001
        state["whitelist_count"] = None
    try:
        from ..core import blacklist_override
        state["suppressed"] = blacklist_override.list_suppressed()
    except Exception:  # noqa: BLE001
        state["suppressed"] = []
    try:
        from ..ext.safety_engine import SafetyEngine
        state["engine"] = SafetyEngine().list_methods()
    except Exception:  # noqa: BLE001
        state["engine"] = {}
    try:
        from ..core.security_bus import get_security_bus
        bus = get_security_bus()
        state["audit"] = bus.get_stats()
        state["audit_path"] = bus._persist_path
    except Exception:  # noqa: BLE001
        state["audit"] = {}
        state["audit_path"] = None
    try:
        from ..core.sandbox_provider import SandboxProvider
        sandbox = SandboxProvider.create("local")
        state["sandbox_available"] = sandbox.is_available()
        state["sandbox_name"] = sandbox.name
    except Exception:  # noqa: BLE001
        state["sandbox_available"] = None
        state["sandbox_name"] = None
    try:
        from ..harden.crypto_provider import get_crypto_provider
        provider = get_crypto_provider()
        state["crypto_backend"] = provider.name
    except Exception:  # noqa: BLE001
        state["crypto_backend"] = None

    state["commit"] = _git_head_short(root)
    state["release"] = release
    html = _render_security_report_html(bench_data, state)
    out_path.write_text(html, encoding="utf-8")
    console.print(f"\n[green]✓ 安全报告已生成: {out_path}[/green]")
    console.print("[dim]浏览器打开即可查看 / 分享[/dim]")
    return 0


def _render_security_report_html(bench: dict[str, Any], state: dict[str, Any]) -> str:
    """渲染自包含 HTML 安全报告 (无外链, 内联 CSS, 含基准可视化)。"""
    engine = state.get("engine") or {}
    engine_v = engine.get("version") or "?"
    capabilities = "、".join(engine.get("capabilities") or []) or "—"

    whitelist_n = state.get("whitelist_count")
    whitelist_s = "—" if whitelist_n is None else f"{whitelist_n} 条"
    suppressed = state.get("suppressed") or []
    suppressed_s = "未启用 (内置黑名单全部生效)" if not suppressed else f"已抑制 {len(suppressed)} 个: {', '.join(suppressed)}"

    audit = state.get("audit") or {}
    audit_n = audit.get("total_events", 0)
    audit_crit = (audit.get("by_severity") or {}).get("critical", 0)

    sandbox_s = ("可用" if state.get("sandbox_available") else "不可用") if state.get("sandbox_available") is not None else "—"
    sandbox_name = state.get("sandbox_name") or "—"

    commit = state.get("commit")
    commit_s = f" · 对应提交 <code>{commit}</code>" if commit else ""
    release = bool(state.get("release"))
    badge = "RELEASE" if release else "安全优先"

    # 基准数字 (兼容 10k / 50k / 汇总三种结构)
    adv = bench.get("adversarial") or bench
    adv_total = adv.get("total")
    adv_block = adv.get("block_recall")
    adv_flag = adv.get("flag_catch")
    adv_fp = adv.get("false_positive_rate")
    adv_bypass = adv.get("bypass")
    adv_precision = adv.get("allow_precision")
    ps = bench.get("powershell") or {}
    ps_total = ps.get("total")
    ps_acc = ps.get("accuracy") or ps.get("correct_rate")
    if isinstance(ps_acc, (int, float)) and ps_acc <= 1:
        ps_acc = round(ps_acc * 100, 2)
    ps_fn = ps.get("fn", 0)
    ps_fp = ps.get("fp", 0)
    bm = bench.get("bypass_matrix") or {}
    bm_total = bm.get("total")
    bm_bypass = bm.get("bypass")
    bm_fp = bm.get("false_pos")
    bm_disaster = bm.get("all_disaster_blocked")

    rows = []
    rows.append(("安全引擎", f"v{engine_v} · {capabilities}"))
    rows.append(("白名单", whitelist_s))
    rows.append(("黑名单减负", suppressed_s))
    rows.append(("审计事件", f"{audit_n} 条 (critical {audit_crit})"))
    rows.append(("审计落盘", state.get("audit_path") or "未持久化"))
    rows.append(("沙箱后端", f"{sandbox_name} ({sandbox_s})"))
    rows.append(("加密后端", state.get("crypto_backend") or "—"))
    rows_html = "".join(f"<tr><td class='k'>{k}</td><td>{v}</td></tr>" for k, v in rows)

    # ---- 基准可视化 (确定性 CSS 条形, 无外链) ----
    viz_cards = []
    if adv_total is not None:
        bv = adv_block if isinstance(adv_block, (int, float)) else 0
        fpv = adv_fp if isinstance(adv_fp, (int, float)) else 0
        green_w = max(0.0, min(100.0, float(bv))) if bv <= 100 else 100.0
        fp_w = max(0.0, min(100.0, float(fpv)))
        fp_seg = f"<i style='width:{fp_w:.2f}%;background:#e65100'></i>" if fp_w > 0 else ""
        viz_cards.append(f"""<div class="viz">
  <div class="viz-h"><span>对抗样本基准 <em>{adv_total} 条</em></span><span class="viz-v">拦截召回 {bv}% · 误杀率 {fpv}%</span></div>
  <div class="bar"><i style="width:{green_w:.2f}%;background:#2e7d32"></i>{fp_seg}</div>
  <div class="viz-legend"><span><i class="dot g"></i>拦截召回 {bv}%</span><span><i class="dot o"></i>误杀率 {fpv}%</span><span>绕过 {adv_bypass}</span></div>
</div>""")
    if ps_total is not None:
        pv = ps_acc if isinstance(ps_acc, (int, float)) else 0
        pv = max(0.0, min(100.0, float(pv)))
        viz_cards.append(f"""<div class="viz">
  <div class="viz-h"><span>PowerShell 基准 <em>{ps_total} 条</em></span><span class="viz-v">正确率 {pv}%</span></div>
  <div class="bar"><i style="width:{pv:.2f}%;background:#1565c0"></i></div>
  <div class="viz-legend"><span><i class="dot b"></i>正确率 {pv}%</span><span>漏放 {ps_fn}</span><span>误杀 {ps_fp}</span></div>
</div>""")
    if bm_total is not None:
        bmv = 100.0 if bm_disaster else 0.0
        viz_cards.append(f"""<div class="viz">
  <div class="viz-h"><span>绕过矩阵 <em>{bm_total} 载荷</em></span><span class="viz-v">灾难意图类别拦截 {bmv:g}%</span></div>
  <div class="bar"><i style="width:{bmv:.2f}%;background:{'#2e7d32' if bm_disaster else '#e65100'}"></i></div>
  <div class="viz-legend"><span><i class="dot {'g' if bm_disaster else 'o'}"></i>灾难类别拦截 {bmv:g}%</span><span>绕过 {bm_bypass}</span><span>误杀 {bm_fp}</span></div>
</div>""")
    viz_html = "".join(viz_cards) or "<p class='note'>尚未运行基准 — 执行 <code>qxt safe bench</code> 生成</p>"

    # ---- 汇总表 (机器可读口径) ----
    bench_rows = []
    if adv_total is not None:
        bench_rows.append(("<b>对抗样本基准</b>", f"{adv_total} 条", f"拦截召回 {adv_block}%", f"标记召回 {adv_flag}%", f"误杀率 {adv_fp}%", f"绕过 {adv_bypass}"))
    if ps_total is not None:
        bench_rows.append(("<b>PowerShell 基准</b>", f"{ps_total} 条", f"正确率 {ps_acc}%", "—", f"误杀 {ps_fp}", f"漏放 {ps_fn}"))
    if bm_total is not None:
        bm_disp = "100%" if bm_disaster else "存在漏拦"
        bench_rows.append(("<b>绕过矩阵</b>", f"{bm_total} 载荷", "—", f"灾难类别拦截: {bm_disp}", f"误杀 {bm_fp}", f"绕过 {bm_bypass}"))
    bench_body = "".join(
        f"<tr><td>{a}</td><td>{b}</td><td>{c}</td><td>{d}</td><td>{e}</td><td>{f}</td></tr>"
        for a, b, c, d, e, f in bench_rows
    ) or "<tr><td colspan='6'>尚未运行基准 — 执行 <code>qxt safe bench</code> 生成</td></tr>"

    generated = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
    release_note = ("<p class='note release-note'>本报告为 <b>RELEASE</b> 版: 数字、生成时间与对应提交三方绑定。"
                    "若代码发生变更, 请重跑 <code>qxt safe bench --check</code> 确认数字未回归后再发布。</p>"
                    if release else "")

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>青小团 · 安全状态报告</title>
<style>
  :root {{ color-scheme: light; }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: "Segoe UI", "Microsoft YaHei", system-ui, sans-serif; background: #f5f6f8; color: #1f2933; line-height: 1.6; padding: 24px; }}
  .wrap {{ max-width: 900px; margin: 0 auto; }}
  h1 {{ font-size: 24px; color: #0f4c81; margin-bottom: 4px; }}
  .sub {{ color: #5b6770; font-size: 13px; margin-bottom: 24px; }}
  .card {{ background: #fff; border-radius: 10px; box-shadow: 0 1px 4px rgba(0,0,0,.08); padding: 20px 24px; margin-bottom: 20px; }}
  h2 {{ font-size: 16px; color: #0f4c81; margin-bottom: 12px; border-left: 4px solid #0f4c81; padding-left: 10px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
  td {{ padding: 8px 10px; border-bottom: 1px solid #eef1f4; }}
  td.k {{ width: 140px; color: #5b6770; }}
  .badge {{ display: inline-block; background: #e8f5e9; color: #1b5e20; border-radius: 20px; padding: 2px 12px; font-size: 13px; font-weight: 600; }}
  .badge.release {{ background: #fff3e0; color: #e65100; }}
  .note {{ color: #7a8690; font-size: 12px; margin-top: 16px; }}
  .release-note {{ background: #fff8e1; border: 1px solid #ffcc80; border-radius: 6px; padding: 10px 12px; }}
  code {{ background: #f0f2f5; padding: 1px 6px; border-radius: 4px; font-size: 13px; }}
  .viz {{ margin: 14px 0; }}
  .viz-h {{ display: flex; justify-content: space-between; font-size: 14px; margin-bottom: 6px; }}
  .viz-h em {{ color: #7a8690; font-style: normal; font-size: 12px; margin-left: 6px; }}
  .viz-v {{ color: #1f2933; font-weight: 600; }}
  .bar {{ background: #eef1f4; border-radius: 6px; height: 12px; overflow: hidden; display: flex; }}
  .bar > i {{ display: block; height: 100%; }}
  .viz-legend {{ display: flex; gap: 18px; font-size: 12px; color: #5b6770; margin-top: 6px; }}
  .dot {{ display: inline-block; width: 10px; height: 10px; border-radius: 50%; margin-right: 4px; vertical-align: -1px; }}
  .dot.g {{ background: #2e7d32; }}
  .dot.o {{ background: #e65100; }}
  .dot.b {{ background: #1565c0; }}
</style>
</head>
<body>
<div class="wrap">
  <h1>青小团 · 安全状态报告</h1>
  <div class="sub">生成时间 {generated}{commit_s} · 引擎 v{engine_v} · <span class="badge{' release' if release else ''}">{badge}</span></div>

  <div class="card">
    <h2>安全系统状态</h2>
    <table>{rows_html}</table>
  </div>

  <div class="card">
    <h2>安全基准 (可复现)</h2>
    {viz_html}
    <table style="margin-top:16px">
      <tr><td><b>套件</b></td><td><b>规模</b></td><td><b>核心指标</b></td><td><b>后果断言</b></td><td><b>误杀</b></td><td><b>绕过</b></td></tr>
      {bench_body}
    </table>
    <p class="note">复现: 在本仓库执行 <code>qxt safe bench</code> (或 <code>bench/safety_bench_10k.py</code> + <code>bench/bench_powershell_safety.py</code> + <code>bench/bypass_matrix.py</code>), 全程本地、不依赖网络与模型。回归门禁: <code>qxt safe bench --check</code>。</p>
  </div>

  {release_note}
  <p class="note">本报告由 <code>qxt safe report</code> 生成, 反映生成时刻的本地安全状态。安全数字请以本仓库可复现基准为准。</p>
</div>
</body>
</html>"""

