# -*- coding: utf-8 -*-
"""qxt bench vs-claude —— 同任务集「Tuan-CLI vs Claude Code」双跑对比基准。

目标: 用同一组软件工程任务 (bench/tasks.yaml), 在隔离工作区里分别用
Tuan-CLI (`qxt run -p`) 与 Claude Code (`claude -p --output-format json`)
headless 执行, 然后以同一验收脚本判定通过/失败, 输出
成功率 / 耗时 / 成本 对比 —— 作为「超越 Claude Code」的可验证证据。

Claude 侧网络不可用时的处理:
- 先探测 `claude -p` 是否真的能完成一轮调用 (解析 terminal_reason);
- 若 api_error / ECONNRESET / 无登录 → 本轮 claude 侧标记 unavailable,
  报告如实说明「当前网络/登录态下 Claude Code 不可用」, 不假装对比过;
- 配置好可用端点后 (如代理/Anthropic 订阅) 重跑即出完整对比。

用法:
  python bench/vs_claude.py                    # 双跑全部任务
  python bench/vs_claude.py --task fix_bug     # 只跑单个
  python bench/vs_claude.py --qxt .venv/Scripts/qxt.exe
  python bench/vs_claude.py --model deepseek/deepseek-chat
  python bench/vs_claude.py --claude "claude"  # claude 可执行文件/别名
  python bench/vs_claude.py --dry              # 只校验框架/任务/报告, 不真正调用模型
  python bench/vs_claude.py --no-html          # 只出 md + json, 不出 html
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from run import Task, load_tasks, _run_check

ROOT = Path(__file__).resolve().parent
TASKS_FILE = ROOT / "tasks.yaml"

# Claude Code headless 固定参数: JSON 输出 / 跳过权限确认 (基准要让对方放手做完,
# 权限拒绝次数在 json 里有记录, 报告会展示)。注意: 老版本 claude 不支持
# --no-input, 统一用 stdin=DEVNULL 避免等待输入。
CLAUDE_BASE = ["-p", "--output-format", "json",
               "--dangerously-skip-permissions", "--max-turns", "80"]


@dataclass
class SideResult:
    side: str            # qxt | claude
    task_id: str
    passed: bool
    elapsed: float
    cost_usd: Optional[float] = None
    note: str = ""


@dataclass
class TaskResult:
    task_id: str
    qxt: SideResult
    claude: Optional[SideResult]   # claude 侧 unavailable 时为 None


# ---------------------------------------------------------------- 单侧执行

def _run_side(task: Task, cmd: List[str], cwd: Path, timeout: int) -> tuple[float, int, str]:
    """执行 agent 命令, 返回 (耗时, 退出码, stdout+stderr 尾部)。"""
    t0 = time.time()
    try:
        proc = subprocess.run(
            cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout,
            env={**os.environ, "QXT_HOME": str(cwd / ".qxt-home")},
            errors="replace", stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired:
        return float(timeout), -1, "超时"
    elapsed = time.time() - t0
    tail = (proc.stderr or "")[-2000:]
    if not tail and proc.stdout:
        tail = proc.stdout[-2000:]
    return elapsed, proc.returncode, tail


def _fresh_workspace(task: Task) -> Path:
    work = Path(tempfile.mkdtemp(prefix=f"vs-{task.id}-"))
    for rel, content in task.files.items():
        p = work / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    return work


def run_qxt(task: Task, qxt: str, model: Optional[str], dry: bool = False) -> SideResult:
    work = _fresh_workspace(task)
    try:
        if dry:
            # 仅校验框架: 验收脚本能正常跑起来 (不崩溃) 即框架 OK, 不要求通过
            try:
                proc = subprocess.run(task.check, cwd=work, shell=True,
                                      capture_output=True, text=True, timeout=120)
                note = f"check 退出码={proc.returncode} (dry 不要求通过)"
                return SideResult("qxt", task.id, True, 0.0, None, note)
            except Exception as exc:  # noqa: BLE001
                return SideResult("qxt", task.id, False, 0.0, None, f"框架异常: {exc}")
        cmd = [qxt, "run", "-p", task.instruction]
        if model:
            cmd += ["--model", model]
        elapsed, rc, tail = _run_side(task, cmd, work, task.timeout)
        if rc != 0:
            return SideResult("qxt", task.id, False, elapsed, None,
                              f"qxt 退出码 {rc}\n{tail[-1200:]}")
        ok, err = _run_check(task, work)
        return SideResult("qxt", task.id, ok, elapsed, None,
                          "" if ok else err[-1200:])
    except Exception as exc:  # noqa: BLE001
        return SideResult("qxt", task.id, False, 0.0, None, str(exc))
    finally:
        shutil.rmtree(work, ignore_errors=True)


def run_claude(task: Task, claude: str) -> SideResult:
    """跑 Claude Code 侧, 解析 JSON 输出里的 result / 成本 / 权限拒绝。"""
    resolved = _resolve_claude(claude)
    if resolved is None:
        return SideResult("claude", task.id, False, 0.0, None,
                          f"claude 命令不存在: {claude}")
    work = _fresh_workspace(task)
    try:
        cmd = [resolved, *CLAUDE_BASE, task.instruction]
        elapsed, rc, tail = _run_side(task, cmd, work, task.timeout)
        if rc != 0:
            return SideResult("claude", task.id, False, elapsed, None,
                              f"claude 退出码 {rc}\n{tail[-1200:]}")
        # 解析最后一行 JSON (--output-format json 的 result 对象)
        cost: Optional[float] = None
        note = ""
        lines = [ln for ln in tail.splitlines() if ln.strip().startswith("{")]
        if lines:
            try:
                data = json.loads(lines[-1])
                cost = float(data.get("total_cost_usd") or 0)
                reason = data.get("terminal_reason", "")
                denials = data.get("permission_denials") or []
                if reason and reason != "done":
                    note += f"terminal_reason={reason}; "
                if denials:
                    note += f"权限拒绝 {len(denials)} 次; "
            except (ValueError, TypeError):
                note += f"json 解析失败; {tail[-300:]}"
        ok, err = _run_check(task, work)
        if ok:
            note += "验收通过"
        return SideResult("claude", task.id, ok, elapsed, cost,
                          note if note else err[-1200:])
    except Exception as exc:  # noqa: BLE001
        return SideResult("claude", task.id, False, 0.0, None, str(exc))
    finally:
        shutil.rmtree(work, ignore_errors=True)


# ---------------------------------------------------------------- 可用性探测

def _resolve_claude(claude: str) -> Optional[str]:
    """解析 claude 实际可执行路径 (Windows npm shim 是 .ps1/.cmd, 需显式解析)。"""
    found = shutil.which(claude)
    if found:
        return found
    for cand in (f"{claude}.cmd", f"{claude}.exe", "claude.cmd", "claude.exe"):
        f = shutil.which(cand)
        if f:
            return f
    return None


def probe_claude(claude: str) -> tuple[bool, str]:
    """探测 claude -p 是否真能完成一轮调用。返回 (可用, 原因)。"""
    resolved = _resolve_claude(claude)
    if resolved is None:
        return False, f"claude 命令不存在 (已尝试 {claude} / .cmd / .exe; 请用 --claude 指定真实路径)"
    try:
        proc = subprocess.run(
            [resolved, "-p", "reply exactly ok", "--output-format", "json",
             "--max-turns", "1"],
            capture_output=True, text=True, timeout=180, errors="replace",
            stdin=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        return False, f"claude 命令不存在: {claude}"
    except subprocess.TimeoutExpired:
        return False, "claude -p 探测超时 (180s)"
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip().startswith("{")]
    if not lines:
        return False, f"claude 无 JSON 输出 (exit={proc.returncode})\n{proc.stderr[-300:]}"
    try:
        data = json.loads(lines[-1])
    except ValueError:
        return False, "claude 输出无法解析"
    reason = data.get("terminal_reason", "")
    result = data.get("result", "")
    if reason in ("done", "stop_sequence"):
        return True, "探测通过"
    if reason == "api_error":
        return False, f"API 错误: {result} (当前网络/登录态无法稳定访问 Anthropic API)"
    return False, f"异常终止: reason={reason} result={result}"


# ---------------------------------------------------------------- 报告

def render_md(results: List[TaskResult], probe_note: str, model: Optional[str]) -> str:
    lines: List[str] = []
    lines.append("# Tuan-CLI vs Claude Code 同任务对比基准")
    lines.append("")
    lines.append(f"- 任务集: `bench/tasks.yaml` ({len(results)} 个任务)")
    lines.append(f"- 判定: 同一验收脚本, 退出码 0 = 通过")
    lines.append(f"- qxt 侧模型: {model or '(默认配置)'}")
    lines.append(f"- Claude 侧: {probe_note}")
    lines.append("")
    lines.append("| 任务 | Tuan-CLI 通过 | Tuan-CLI 耗时(s) | Claude 通过 | Claude 耗时(s) | Claude 成本($) | 备注 |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- |")
    for r in results:
        q = r.qxt
        if r.claude:
            c = r.claude
            c_pass, c_el, c_cost = "✅" if c.passed else "❌", f"{c.elapsed:.0f}", f"{c.cost_usd or 0:.4f}"
        else:
            c_pass, c_el, c_cost = "—", "—", "—"
        note = (c.note[:60] if r.claude and c.note else q.note[:60])
        lines.append(
            f"| {r.task_id} | {'✅' if q.passed else '❌'} | {q.elapsed:.0f} | "
            f"{c_pass} | {c_el} | {c_cost} | {note} |"
        )
    lines.append("")
    q_win = sum(1 for r in results if r.qxt.passed)
    c_win = sum(1 for r in results if r.claude and r.claude.passed)
    lines.append(f"**通过率: Tuan-CLI {q_win}/{len(results)} · Claude Code {c_win}/{len(results)}**")
    lines.append("")
    lines.append("> 口径说明: 结果只对「当前环境/当前模型配置/当前任务集」负责;")
    lines.append("> Claude 侧不可用 (—) 表示该轮未完成真实对比, 已如实标注原因。")
    return "\n".join(lines)


def render_html(results: List[TaskResult], probe_note: str, model: Optional[str]) -> str:
    import html as h

    def esc(s: str) -> str:
        return h.escape(s, quote=True)

    rows = ""
    for r in results:
        q = r.qxt
        c = r.claude
        q_pass = "PASS" if q.passed else "FAIL"
        q_tone = "ok" if q.passed else "bad"
        if c:
            c_pass = "PASS" if c.passed else "FAIL"
            c_tone = "ok" if c.passed else "bad"
            c_el = f"{c.elapsed:.0f}"
            c_cost = f"{c.cost_usd or 0:.4f}"
            c_note = esc(c.note[:70])
        else:
            c_pass = "N/A"
            c_tone = "soft"
            c_el = "—"
            c_cost = "—"
            c_note = esc(probe_note[:70])
        rows += f"""<tr>
      <td class="mono">{esc(r.task_id)}</td>
      <td><span class="chip {q_tone}">{q_pass}</span></td>
      <td>{q.elapsed:.0f}</td>
      <td><span class="chip {c_tone}">{c_pass}</span></td>
      <td>{c_el}</td>
      <td class="mono">{c_cost}</td>
      <td class="mut">{c_note}</td>
    </tr>"""
    q_win = sum(1 for r in results if r.qxt.passed)
    c_win = sum(1 for r in results if r.claude and r.claude.passed)
    total = len(results)
    q_pct = f"{q_win / total * 100:.0f}" if total else "0"
    c_pct = f"{c_win / total * 100:.0f}" if total else "0"
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Tuan-CLI vs Claude Code 对比基准</title>
<style>
  :root {{ --bg:#0f1520; --card:#171f2e; --line:#2a3650; --tx:#e8eef8; --mut:#8ea0bd;
          --ok:#3ddc97; --bad:#ff5d6c; --info:#4da3ff; --soft:#ffd166; }}
  * {{ box-sizing:border-box; margin:0; padding:0; }}
  body {{ background:var(--bg); color:var(--tx); font:14px/1.6 "Segoe UI",system-ui,sans-serif; padding:32px 20px; }}
  .wrap {{ max-width:1080px; margin:0 auto; }}
  header {{ text-align:center; margin-bottom:24px; }}
  h1 {{ font-size:26px; letter-spacing:.5px; }}
  .sub {{ color:var(--mut); margin-top:6px; font-size:13px; }}
  .cards {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(200px,1fr)); gap:14px; margin:20px 0; }}
  .card {{ background:var(--card); border:1px solid var(--line); border-radius:14px; padding:18px 16px; }}
  .card .num {{ font-size:28px; font-weight:700; }}
  .card .cap {{ color:var(--mut); font-size:12px; margin-top:4px; }}
  table {{ width:100%; border-collapse:collapse; background:var(--card); border:1px solid var(--line); border-radius:14px; overflow:hidden; }}
  th,td {{ padding:10px 12px; text-align:left; border-bottom:1px solid var(--line); }}
  th {{ color:var(--mut); font-size:12px; text-transform:uppercase; letter-spacing:.5px; }}
  .chip {{ display:inline-block; padding:2px 10px; border-radius:999px; font-size:12px; font-weight:700; }}
  .ok {{ background:rgba(61,220,151,.15); color:var(--ok); }}
  .bad {{ background:rgba(255,93,108,.15); color:var(--bad); }}
  .soft {{ background:rgba(255,209,102,.12); color:var(--soft); }}
  .mono {{ font-family:ui-monospace,Consolas,monospace; }}
  .mut {{ color:var(--mut); font-size:12px; }}
  .note {{ color:var(--mut); font-size:12px; margin-top:18px; }}
</style>
</head>
<body><div class="wrap">
<header><h1>Tuan-CLI vs Claude Code 同任务对比基准</h1>
<div class="sub">任务集 bench/tasks.yaml · 同一验收脚本判定 · qxt 模型: {esc(model or '默认配置')} · Claude 侧: {esc(probe_note)}</div></header>
<div class="cards">
  <div class="card"><div class="num">{q_win}/{total}</div><div class="cap">Tuan-CLI 通过率 {q_pct}%</div></div>
  <div class="card"><div class="num">{c_win}/{total}</div><div class="cap">Claude Code 通过率 {c_pct}%</div></div>
  <div class="card"><div class="num">{total}</div><div class="cap">任务总数</div></div>
</div>
<table>
<thead><tr><th>任务</th><th>Tuan-CLI</th><th>耗时(s)</th><th>Claude</th><th>耗时(s)</th><th>成本($)</th><th>备注</th></tr></thead>
<tbody>{rows}</tbody>
</table>
<p class="note">口径: 结果只对「当前环境 / 当前模型配置 / 当前任务集」负责; Claude 侧 N/A 表示该轮未完成真实对比 (网络/登录不可用), 已如实标注原因。</p>
</div></body></html>"""


# ---------------------------------------------------------------- main

def main() -> int:
    ap = argparse.ArgumentParser(description="Tuan-CLI vs Claude Code 双跑对比基准")
    ap.add_argument("--tasks", type=Path, default=TASKS_FILE)
    ap.add_argument("--task", help="只跑指定 id 的任务")
    ap.add_argument("--qxt", default="qxt", help="qxt 可执行文件路径")
    ap.add_argument("--model", default=None, help="qxt 侧模型 (provider/model)")
    ap.add_argument("--claude", default="claude", help="claude 可执行文件/别名")
    ap.add_argument("--skip-probe", action="store_true", help="跳过 Claude 可用性探测 (强制逐任务双跑)")
    ap.add_argument("--dry", action="store_true", help="只校验框架/任务/报告生成, 不真正调用模型")
    ap.add_argument("--no-html", action="store_true", help="不生成 HTML 报告")
    ap.add_argument("--json", action="store_true", help="stdout 输出 JSON 而非表格")
    args = ap.parse_args()

    tasks = load_tasks(args.tasks)
    if args.task:
        tasks = [t for t in tasks if t.id == args.task]
    if not tasks:
        raise SystemExit("没有可跑的任务")

    # Claude 可用性探测 (不可用则整体标记, 不再逐任务浪费时间)
    claude_ok = False
    probe_note = ""
    if args.dry:
        claude_ok, probe_note = False, "dry 模式: 未探测"
    elif not args.skip_probe:
        claude_ok, probe_note = probe_claude(args.claude)
    else:
        claude_ok, probe_note = True, "已跳过探测"

    results: List[TaskResult] = []
    for t in tasks:
        q_res = run_qxt(t, args.qxt, args.model, dry=args.dry)
        c_res = run_claude(t, args.claude) if (claude_ok and not args.dry) else None
        results.append(TaskResult(t.id, q_res, c_res))

    if args.json:
        payload = {
            "probe_note": probe_note,
            "claude_available": claude_ok,
            "tasks": [
                {
                    "task_id": r.task_id,
                    "qxt": vars(r.qxt),
                    "claude": vars(r.claude) if r.claude else None,
                }
                for r in results
            ],
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"{'任务':<22}{'Tuan-CLI':<10}{'耗时(s)':<10}{'Claude':<10}{'耗时(s)':<10}备注")
        print("-" * 76)
        for r in results:
            q = r.qxt
            if r.claude:
                c = r.claude
                c_cell = "PASS" if c.passed else "FAIL"
                c_el = f"{c.elapsed:.1f}"
            else:
                c_cell = "N/A"
                c_el = "—"
            note = (r.claude.note[:36] if r.claude and r.claude.note else q.note[:36])
            print(f"{r.task_id:<22}{'PASS' if q.passed else 'FAIL':<10}{q.elapsed:<10.1f}"
                  f"{c_cell:<10}{c_el:<10}{note}")
        print("-" * 76)
        q_win = sum(1 for r in results if r.qxt.passed)
        c_win = sum(1 for r in results if r.claude and r.claude.passed)
        print(f"通过率: Tuan-CLI {q_win}/{len(results)} · Claude Code {c_win}/{len(results)}")
        if args.dry:
            print("\n[dry 模式] 仅校验框架/任务/报告: 未真实调用任何模型端点。")
        if not claude_ok:
            print(f"\n[注意] Claude 侧不可用: {probe_note}")

    # 落盘报告 (md + json + html)
    ROOT.mkdir(exist_ok=True)
    md = render_md(results, probe_note, args.model)
    (ROOT / "vs_report.md").write_text(md, encoding="utf-8")
    payload = {
        "probe_note": probe_note,
        "claude_available": claude_ok,
        "tasks": [
            {"task_id": r.task_id, "qxt": vars(r.qxt),
             "claude": vars(r.claude) if r.claude else None}
            for r in results
        ],
    }
    (ROOT / "vs_report.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    if not args.no_html:
        (ROOT / "vs_report.html").write_text(
            render_html(results, probe_note, args.model), encoding="utf-8")
    print(f"\n报告已写入: bench/vs_report.md / vs_report.json"
          + (" / vs_report.html" if not args.no_html else ""))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
