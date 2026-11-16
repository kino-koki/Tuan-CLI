"""tuan safe · 安全基准与 HTML 报告子命令。

覆盖: bench (一键复现) / report (自包含 HTML), 以及漂移对比与回归门禁。
全程本地执行, 不依赖网络与模型。
"""
from __future__ import annotations

import json
import os
import platform
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .._ui_singleton import console
from ._shared import _repo_root

import logging
log = logging.getLogger(__name__)


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


def _bench_dir() -> Path:
    # 仓库根只有一处权威: ``cmd_safe._repo_root`` (它再转发给 ``_shared``)。
    #
    # 这里刻意用**调用期延迟导入**而不是模块级 ``from ._shared import _repo_root``:
    # 后者会让本模块与 cmd_safe 各自持有一份独立的名字绑定, 于是
    # ``monkeypatch.setattr(cmd_safe, "_repo_root", ...)`` 只影响 cmd_safe 内部,
    # 本模块照旧读真实仓库 —— 实测表现为 ``tuan safe bench --quick`` 把结果写进
    # 真实 bench/ 而不是被重定向的目录 (tests/test_cli_safe_bench_report.py 抓到)。
    # 延迟导入同时避免了 cmd_safe 在导入期就 import 本模块造成的循环导入。
    from .. import cmd_safe as _cs
    root = _cs._repo_root()
    bench_dir = root / "bench"
    if not bench_dir.is_dir():
        raise FileNotFoundError(
            f"找不到基准脚本目录: {bench_dir}。"
            f"pip 安装的包里没有 bench/, 请 git clone 仓库后设置 "
            f"环境变量 TUAN_REPO_ROOT=<仓库根> 再跑 tuan safe bench。")
    return bench_dir


def _bench_timeout(default: float) -> float:
    """单个基准子进程的等待上限 (秒)。

    环境变量 ``TUAN_SAFE_BENCH_TIMEOUT`` 可覆盖: 检测层在低配机 / 有并发
    负载时单条约 50ms, 10k 条就超过原先硬编码的 600s, 结果是"一条命令复现
    全部数字"在慢机上永远卡在 1/5（超时只丢弃等待结果, 不改变任何判定）。
    """
    raw = os.environ.get("TUAN_SAFE_BENCH_TIMEOUT", "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def _bench_fail_hint(exc: Exception) -> str:
    """把"超时"这一失败讲清楚: 是等待上限不够, 不是判定出错。"""
    if isinstance(exc, subprocess.TimeoutExpired):
        return (f"{exc}（这是单步等待上限, 可用环境变量 "
                f"TUAN_SAFE_BENCH_TIMEOUT=<秒> 提高, 慢机/并发负载建议 3600; "
                f"超时只丢弃本次结果, 不改变任何判定）")
    return str(exc)


def _bench_phase_adversarial(bench_dir: Path, py: str, count: int,
                             results: dict[str, Any]) -> None:
    """1/5 对抗样本基准 (bash/通用命令)。"""
    tmp = bench_dir / f".run_tmp_10k_{os.getpid()}.json"
    console.print(f"[bold]1/5 对抗样本基准[/bold] ({count} 条, 随机种子 20260906, 可复现)...")
    try:
        r1 = subprocess.run(
            [py, str(bench_dir / "safety_bench_10k.py"),
             "--count", str(count), "--seed", "20260906", "--out", str(tmp)],
            capture_output=True, text=True, errors="replace",
            timeout=_bench_timeout(1800),
        )
        if tmp.exists():
            data = json.loads(tmp.read_text(encoding="utf-8"))
            results["adversarial"] = data
            console.print(f"  [green]✓ 拦截召回 {data.get('block_recall')}%  "
                          f"标记召回 {data.get('flag_catch')}%  误杀率 {data.get('false_positive_rate')}%  "
                          f"绕过 {data.get('bypass')}[/green]")
        else:
            console.print(f"[red]✗ 对抗基准无输出: {r1.stderr[-500:]}[/red]")
            results["adversarial"] = {"error": (r1.stderr or "")[-500:]}
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]✗ 对抗基准失败: {_bench_fail_hint(exc)}[/red]")
        results["adversarial"] = {"error": str(exc)}
    finally:
        if tmp.exists():
            tmp.unlink()


def _bench_phase_powershell(bench_dir: Path, py: str, results: dict[str, Any]) -> None:
    """2/5 PowerShell 基准 (脚本固定写 ps_safety_result.json)。"""
    ps_json = bench_dir / "ps_safety_result.json"
    console.print("[bold]2/5 PowerShell 基准[/bold] (5000 条: 危险 2300 / 安全 2700)...")
    try:
        r2 = subprocess.run(
            [py, str(bench_dir / "bench_powershell_safety.py")],
            capture_output=True, text=True, errors="replace",
            timeout=_bench_timeout(1200),
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
        console.print(f"[red]✗ PS 基准失败: {_bench_fail_hint(exc)}[/red]")
        results["powershell"] = {"error": str(exc)}


def _bench_phase_bypass(bench_dir: Path, py: str, results: dict[str, Any]) -> None:
    """3/5 绕过矩阵 (手工对抗载荷 + 后果级断言)。"""
    tmp = bench_dir / f".run_tmp_bypass_{os.getpid()}.json"
    console.print("[bold]3/5 绕过矩阵[/bold] (手工对抗载荷 + 灾难后果级断言)...")
    try:
        r3 = subprocess.run(
            [py, str(bench_dir / "bypass_matrix.py"), "--json-out", str(tmp)],
            capture_output=True, text=True, errors="replace",
            timeout=_bench_timeout(1200),
        )
        if tmp.exists():
            data = json.loads(tmp.read_text(encoding="utf-8"))
            results["bypass_matrix"] = data
            disaster = "100%" if data.get("all_disaster_blocked") else "存在漏拦"
            console.print(f"  [green]✓ 绕过 {data.get('bypass')}  误杀 {data.get('false_pos')}  "
                          f"灾难类别拦截: {disaster}[/green]")
        else:
            console.print(f"[red]✗ 绕过矩阵无输出: {r3.stderr[-500:]}[/red]")
            results["bypass_matrix"] = {"error": (r3.stderr or "")[-500:]}
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]✗ 绕过矩阵失败: {_bench_fail_hint(exc)}[/red]")
        results["bypass_matrix"] = {"error": str(exc)}
    finally:
        if tmp.exists():
            tmp.unlink()


def _bench_phase_realistic(bench_dir: Path, py: str, quick: bool,
                           results: dict[str, Any]) -> None:
    """4/5 真实使用场景基准 (随机种子, 良性主导, 报分布而非单点)。"""
    tmp = bench_dir / f".run_tmp_real_{os.getpid()}.json"
    real_seeds = 2 if quick else 4
    real_count = 600 if quick else 1500
    console.print(f"[bold]4/5 真实使用基准[/bold] ({real_seeds} 个独立随机种子 × "
                  f"{real_count} 条 = {real_seeds * real_count} 条, 良性主导)...")
    try:
        r4 = subprocess.run(
            [py, str(bench_dir / "realistic_usage_bench.py"),
             "--count", str(real_count), "--seeds", str(real_seeds),
             "--out", str(tmp), "--quiet"],
            capture_output=True, text=True, errors="replace",
            timeout=_bench_timeout(1800),
        )
        if tmp.exists():
            data = json.loads(tmp.read_text(encoding="utf-8"))
            results["realistic"] = data
            s = data.get("summary", {})
            fp = s.get("fp_hard_pct_of_allow") or {}
            rc = s.get("danger_block_recall_pct") or {}
            lat = s.get("latency_ms_per_cmd") or {}

            def _med(d: Any) -> str:  # noqa: ANN001
                return f"{d.get('median', 0):.2f}%" if d else "n/a"

            silent = s.get("danger_miss_silent_total", 0)
            silent_tag = "零静默放行" if silent == 0 else f"{silent} 条静默放行"
            console.print(
                f"  [green]✓ 硬拦误杀占良性 中位 {_med(fp)}  "
                f"真危险召回 中位 {_med(rc)}  "
                f"延迟 中位 {lat.get('median', 0):.1f} ms/条  "
                f"{silent_tag}[/green]")
        else:
            console.print(f"[red]✗ 真实使用基准无输出: {(r4.stderr or '')[-500:]}[/red]")
            results["realistic"] = {"error": (r4.stderr or "")[-500:]}
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]✗ 真实使用基准失败: {_bench_fail_hint(exc)}[/red]")
        results["realistic"] = {"error": str(exc)}
    finally:
        if tmp.exists():
            tmp.unlink()


def _bench_phase_portability(root: Path, py: str, results: dict[str, Any]) -> None:
    """5/5 跨平台可移植性: 用 pytest 跑 POSIX / Linux / macOS 载荷在本机的判定。"""
    console.print("[bold]5/5 跨平台可移植性[/bold] (POSIX/Linux/macOS 载荷在本机的判定)...")
    try:
        r5 = subprocess.run(
            [py, "-m", "pytest", str(root / "tests" / "test_platform_portability.py"),
             "-q", "--noconftest", "-p", "no:cacheprovider"],
            capture_output=True, text=True, errors="replace",
            timeout=_bench_timeout(600),
        )
        tail = (r5.stdout or "").strip().splitlines()[-3:]
        passed = failed = 0
        for ln in tail:
            m = re.search(r"(\d+) passed", ln)
            if m:
                passed = int(m.group(1))
            m2 = re.search(r"(\d+) failed", ln)
            if m2:
                failed = int(m2.group(1))
        results["portability"] = {
            "platform": platform.system(),
            "passed": passed,
            "failed": failed,
            "rc": r5.returncode,
            "note": (
                "在本机跑 POSIX/Linux/macOS 载荷, 证明检测层未混入平台相关逻辑; "
                "不代表已在 Linux/macOS 实机验证。"
            ),
        }
        if failed == 0:
            console.print(f"  [green]✓ {passed} 项载荷判定符合预期 "
                          f"(本平台 {platform.system()})[/green]")
        else:
            console.print(f"  [red]✗ {failed} 项判定偏离预期[/red]")
            for ln in tail:
                console.print(f"    [dim]{ln}[/dim]")
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]✗ 跨平台可移植性检查失败: {_bench_fail_hint(exc)}[/red]")
        results["portability"] = {"error": str(exc)}


def _bench_tail(results: dict[str, Any], out_path: Path, bench_dir: Path,
                quick: bool, check: bool, full: bool,
                prev_archive: dict[str, Any] | None) -> int:
    """汇总收尾: 引擎版本 + 平台标记 + 落盘 + check/full 门禁 + 时间序列存档。"""
    # 引擎版本
    try:
        from ...ext.safety_engine import SafetyEngine
        methods = SafetyEngine().list_methods()
        results["engine"] = {"version": methods.get("version"), "capabilities": methods.get("capabilities")}
    except Exception:  # noqa: BLE001
        results["engine"] = {"version": None, "capabilities": []}

    results["generated_at"] = datetime.now(timezone.utc).isoformat()
    results["seed"] = 20260906
    results["quick"] = quick
    results["platform"] = {
        "system": platform.system(),
        "release": platform.release(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "os_name": os.name,
        "note": (
            "基准仅在本平台实测。检测层为纯字符串正则, 跨平台行为由 "
            "tests/test_platform_portability.py 锁定; 归一化层的 "
            "os.path.realpath 是唯一平台相关分支。"
        ),
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    console.print(f"\n[green]✓ 汇总已写入: {out_path}[/green]")
    console.print(
        f"[dim]平台: {platform.system()} {platform.release()} / {platform.machine()} / "
        f"Python {platform.python_version()} —— 数字仅代表本平台实测[/dim]"
    )
    console.print("[dim]引用于 README 时注明: 复现命令 tuan safe bench (或第三方直接跑 bench/ 下脚本)[/dim]")

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


def _cmd_bench(args: Any) -> int:
    """一键复现安全基准: 对抗样本 + PowerShell + 绕过矩阵, 汇总为可引用报告。

    第三方可用同一条命令在本仓库复现安全数字 (不依赖网络, 不调用模型)。
    """
    json_mode = bool(getattr(args, "json", False))
    if json_mode:
        # 机器可读模式: 人类可读日志改走 stderr, stdout 只留汇总 JSON (CI 解析)。
        # 每个 CLI 进程只执行一个 safe 子命令, 重绑模块级 console 无副作用。
        global console
        console = console.__class__(stderr=True)
    try:
        bench_dir = _bench_dir()
    except FileNotFoundError as exc:
        console.print(f"[red]✗ {exc}[/red]")
        return 1
    root = bench_dir.parent
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
    _bench_phase_adversarial(bench_dir, py, count, results)
    _bench_phase_powershell(bench_dir, py, results)
    _bench_phase_bypass(bench_dir, py, results)
    _bench_phase_realistic(bench_dir, py, quick, results)
    _bench_phase_portability(root, py, results)

    rc = _bench_tail(results, out_path, bench_dir, quick, check, full, prev_archive)

    if json_mode:
        # 机器可读输出: stdout 只含汇总 JSON (一行, 可直接 jq/CI 消费)
        sys.stdout.write(json.dumps(results, ensure_ascii=False, indent=2) + "\n")
        if not quick:
            # 时间序列存档: CI 提交 bench/results/ 让安全数字可回看、可画趋势
            results_dir = bench_dir / "results"
            results_dir.mkdir(parents=True, exist_ok=True)
            ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            archive = results_dir / f"security-bench-{ts}.json"
            archive.write_text(json.dumps(results, ensure_ascii=False, indent=2),
                               encoding="utf-8")
            console.print(f"[green]✓ 时间序列存档: {archive}[/green]")
    return rc


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
                           capture_output=True, text=True, errors="replace", timeout=10)
        out = (r.stdout or "").strip()
        return out or None
    except Exception as exc:  # noqa: BLE001
        log.debug("_git_head_short(): 非致命异常已忽略(设计内降级, 不改控制流): %s", exc)
        return None


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
    viz_html = "".join(viz_cards) or "<p class='note'>尚未运行基准 — 执行 <code>tuan safe bench</code> 生成</p>"

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
    ) or "<tr><td colspan='6'>尚未运行基准 — 执行 <code>tuan safe bench</code> 生成</td></tr>"

    generated = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
    release_note = ("<p class='note release-note'>本报告为 <b>RELEASE</b> 版: 数字、生成时间与对应提交三方绑定。"
                    "若代码发生变更, 请重跑 <code>tuan safe bench --check</code> 确认数字未回归后再发布。</p>"
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
    <p class="note">复现: 在本仓库执行 <code>tuan safe bench</code> (或 <code>bench/safety_bench_10k.py</code> + <code>bench/bench_powershell_safety.py</code> + <code>bench/bypass_matrix.py</code>), 全程本地、不依赖网络与模型。回归门禁: <code>tuan safe bench --check</code>。</p>
  </div>

  {release_note}
  <p class="note">本报告由 <code>tuan safe report</code> 生成, 反映生成时刻的本地安全状态。安全数字请以本仓库可复现基准为准。</p>
</div>
</body>
</html>"""
