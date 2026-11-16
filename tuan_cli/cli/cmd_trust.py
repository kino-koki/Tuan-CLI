"""工作区信任管理 CLI 命令 —— 「信任边界」差异化能力。

Claude Code 没有「工作区信任」概念: 任何目录打开即被代理完全访问。
Tuan-CLI 把「这个工作区可信吗」作为一等公民, 用 L1 信任滤网裁决
工具/命令的放行或拒 (fail-closed)。

承载 ``tuan trust`` 子命令及其辅助函数:
- cmd_trust: 查看/设置/移除工作区信任, 审计信任决策
- _trust_status: 列出受信工作区 + 信任级别 + 指纹
- _trust_check: 检查某路径的信任裁决 (含衰减提示)
- _trust_set: 标记工作区 trusted/limited/untrusted
- _trust_remove: 撤销信任
- _trust_cleanup: 清理过期信任 (>90 天未用)

路由: ``tuan_cli/cli/commands.py::_CMD_SOURCES`` 将 cmd_trust 指向本模块。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from ..config.loader import home_dir
from ._ui_singleton import console
import logging

log = logging.getLogger(__name__)


def cmd_trust(args: Any) -> int:
    """tuan trust 入口: 查看/设置/移除工作区信任。"""
    sub = getattr(args, "trust_cmd", None) or "status"
    path = getattr(args, "path", None)
    level = getattr(args, "level", None)
    name = getattr(args, "name", "")
    all_ = bool(getattr(args, "all", False))
    try:
        from ..core.workspace_trust import TrustLevel, WorkspaceTrust
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]信任管理器初始化失败: {exc}[/red]")
        return 1

    trust = WorkspaceTrust(home=Path(home_dir()))

    # --- check: 裁决某路径 ---
    if sub == "check":
        if not path:
            console.print("[red]用法: tuan trust check <路径>[/red]")
            return 1
        p = Path(path).expanduser().resolve()
        level_out = trust.check_trust(str(p))
        _render_level(level_out)
        info = trust.get_project_info(str(p))
        if info.get("decay_reason"):
            console.print(f"[yellow]衰减提示: {info['decay_reason']}[/yellow]")
        console.print(f"[dim]指纹: {info.get('fingerprint', '-')}[/dim]"
                      f"[dim]  最近使用: {info.get('last_used', '-')}[/dim]")
        return 0

    # --- set: 设置信任 ---
    if sub == "set":
        if not path:
            console.print("[red]用法: tuan trust set <路径> <trusted|limited|untrusted>[/red]")
            return 1
        p = Path(path).expanduser().resolve()
        rec = trust.set_trust(str(p), level or "trusted", project_name=name)
        console.print(f"[green]✓ 已标记 {rec.path} → {rec.level}[/green]")
        return 0

    # --- remove: 撤销 ---
    if sub == "remove":
        if not path:
            console.print("[red]用法: tuan trust remove <路径>[/red]")
            return 1
        p = Path(path).expanduser().resolve()
        ok = trust.remove(str(p))
        console.print(f"[green]✓ 已移除 {p}[/green]" if ok else f"[dim]未找到: {p}[/dim]")
        return 0

    # --- cleanup: 清理过期 ---
    if sub == "cleanup":
        n = trust.cleanup()
        console.print(f"[green]✓ 已清理 {n} 条过期信任[/green]")
        return 0

    # --- export: 导出信任策略 (团队共享) ---
    if sub == "export":
        return _trust_export(trust, _opt_str(getattr(args, "file", None)))

    # --- import: 导入信任策略 (建立同一边界) ---
    if sub == "import":
        return _trust_import(trust, _opt_str(getattr(args, "file", None)),
                             bool(getattr(args, "overwrite", False)))

    # --- matrix: L1 信任滤网动作矩阵 (fail-closed 透明度) ---
    if sub == "matrix":
        return _trust_matrix(bool(getattr(args, "json", False)))

    # --- audit: 信任决策审计 ---
    if sub == "audit":
        return _trust_audit(trust, bool(getattr(args, "json", False)))

    # --- decay: 信任衰减检测/强制衰减/时间戳刷新 (第 63 个独特功能) ---
    if sub == "decay":
        return _trust_decay(trust, path, bool(getattr(args, "json", False)),
                            bool(getattr(args, "force", False)),
                            bool(getattr(args, "touch", False)))

    # --- status (默认): 列出受信工作区 ---
    _trust_status(trust, all_)
    return 0


def _trust_decay(trust: Any, path: Optional[str], json_mode: bool,
                 force: bool, touch: bool) -> int:
    """信任衰减维护面 (第 63 个独特功能)。

    暴露 check_for_decay / apply_decay / update_last_used:
    - 默认「衰减检测」: 对受信工作区做敏感面指纹比对 + 超期检查, 报告是否
      需要衰减及原因 (不自动改状态, 供用户决策);
    - --force「强制衰减」: 立即执行衰减 trusted→limited 并留审计原因;
    - --touch「刷新时间戳」: 更新 last_used (确认仍在使用, 避免超期误衰减)。

    Claude Code 无工作区信任, 更无衰减维护入口 —— 纯差异化。
    """
    import json
    import sys

    # -- 强制衰减 --
    if force:
        if not path:
            console.print("[red]用法: tuan trust decay <路径> --force[/red]")
            return 1
        p = Path(path).expanduser().resolve()
        reason = (
            f"手动强制衰减 (运维/用户触发, {datetime.now().strftime('%Y-%m-%d %H:%M')})"
        )
        rec = trust.apply_decay(str(p), reason)
        if json_mode:
            sys.stdout.write(json.dumps({
                "path": str(p), "level": rec.level,
                "decayed_at": rec.decayed_at, "reason": rec.decay_reason,
            }, ensure_ascii=False, indent=2) + "\n")
            return 0
        console.print(f"[yellow]◐ 已强制衰减 {rec.path}[/yellow]")
        console.print(f"    级别 → [yellow]{rec.level}[/yellow]")
        console.print(f"    原因: [dim]{rec.decay_reason}[/dim]")
        return 0

    # -- 刷新时间戳 --
    if touch:
        if not path:
            console.print("[red]用法: tuan trust decay <路径> --touch[/red]")
            return 1
        p = Path(path).expanduser().resolve()
        trust.update_last_used(str(p))
        if json_mode:
            sys.stdout.write(json.dumps({"path": str(p), "touched": True},
                                        ensure_ascii=False, indent=2) + "\n")
            return 0
        console.print(f"[green]✓ 已刷新使用时间戳: {p}[/green]")
        console.print("  [dim](下次衰减检查将从现在重新计 90 天窗口)[/dim]")
        return 0

    # -- 默认: 衰减检测 (全部受信工作区, 或指定路径) --
    import time as _t

    def _check_one(p: str) -> Dict[str, Any]:
        reason = trust.check_for_decay(p)
        return {"path": p, "needs_decay": reason is not None,
                "reason": reason}

    if path:
        p = Path(path).expanduser().resolve()
        results = [_check_one(str(p))]
    else:
        results = [_check_one(r.path) for r in trust.list_trusted()
                   if r.level == "trusted"]

    if json_mode:
        sys.stdout.write(json.dumps({
            "checked": len(results),
            "needs_decay": sum(1 for r in results if r["needs_decay"]),
            "results": results,
        }, ensure_ascii=False, indent=2) + "\n")
        return 0

    if not results:
        console.print("[dim]无受信工作区可检测 (trust set <路径> trusted 先标记)[/dim]")
        return 0
    console.print("\n[bold]=== 信任衰减检测 ===[/bold]\n")
    console.print(f"  检测 {len(results)} 个受信工作区\n")
    for r in results:
        mark = "[yellow]◐ 需衰减[/yellow]" if r["needs_decay"] else "[green]✓ 健康[/green]"
        console.print(f"  {mark}  {r['path']}")
        if r["reason"]:
            console.print(f"      [dim]原因: {r['reason'][:90]}[/dim]")
    needs = sum(1 for r in results if r["needs_decay"])
    if needs:
        console.print(f"\n[yellow]→ {needs} 个工作区需要衰减[/yellow]")
        console.print("[dim]执行: tuan trust decay <路径> --force 立即降级; "
                      "--touch 确认仍在使用[/dim]")
    else:
        console.print("\n[green]→ 全部受信工作区敏感面一致、未超期[/green]")
    return 0


def _opt_str(v: Any) -> Optional[str]:
    """argparse 的 Optional[str] 清洗 (None → None, 其余 → str)。"""
    if v is None:
        return None
    return str(v)


def _trust_export(trust: Any, out_file: Optional[str]) -> int:
    """导出信任策略为可移植 JSON (团队共享 / CI 建立同一边界)。"""
    import json
    import sys

    policy = trust.export_policy()
    text = json.dumps(policy, ensure_ascii=False, indent=2) + "\n"
    if out_file:
        try:
            Path(out_file).write_text(text, encoding="utf-8")
            console.print(
                f"[green]✓ 已导出 {len(policy['entries'])} 条信任策略 → {out_file}[/green]"
            )
        except OSError as exc:
            console.print(f"[red]导出失败: {exc}[/red]")
            return 1
    else:
        sys.stdout.write(text)
    return 0


def _trust_import(trust: Any, in_file: Optional[str], overwrite: bool) -> int:
    """导入信任策略 (建立与团队一致的信任边界)。"""
    import json

    if not in_file:
        console.print("[red]用法: tuan trust import <策略.json> [--overwrite][/red]")
        return 1
    p = Path(in_file).expanduser().resolve()
    if not p.exists():
        console.print(f"[red]策略文件不存在: {p}[/red]")
        return 1
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        console.print(f"[red]策略文件解析失败: {exc}[/red]")
        return 1
    result = trust.import_policy(data, overwrite=overwrite)
    console.print(f"[green]✓ 已导入 {result.get('imported', 0)} 条[/green] "
                  f"([dim]跳过 {result.get('skipped', 0)} / "
                  f"无效 {result.get('invalid', 0)}[/dim])")
    if result.get("invalid", 0):
        console.print(
            f"[yellow]提示: {result['invalid']} 条无效 (路径空或级别非法), 已忽略[/yellow]"
        )
    return 0


def _trust_matrix(json_mode: bool) -> int:
    """L1 信任滤网动作矩阵 (fail-closed 透明度)。

    展示「信任级别 × 动作 → 裁决」的完整语义, 让用户清楚每个级别放行什么、
    拒绝什么。Claude Code 无「工作区信任」概念, 这是纯差异化能力。
    """
    import json
    import sys

    from ..core.workspace_trust import (
        TrustLevel,
        consult_for_shell,
        is_action_allowed,
    )

    levels = [TrustLevel.TRUSTED, TrustLevel.LIMITED,
              TrustLevel.UNTRUSTED, TrustLevel.UNKNOWN]
    actions = ["read", "plan", "write", "edit", "run_shell", "task"]
    matrix = []
    for lv in levels:
        row: Dict[str, Any] = {"level": lv}
        for act in actions:
            allowed = is_action_allowed(lv, act)
            row[act] = "allow" if allowed else "deny"
        matrix.append(row)

    # shell 裁决单独一列 (consult_for_shell 有 confirm 语义)
    shell_rows = []
    for lv in levels:
        act, reason = consult_for_shell(lv, "npm test")
        shell_rows.append({"level": lv, "shell": act, "reason": reason})

    if json_mode:
        sys.stdout.write(json.dumps({
            "levels": levels,
            "actions": actions,
            "matrix": matrix,
            "shell_rules": shell_rows,
            "note": "fail-closed: 未知/非预期级别一律拒绝; "
                    "shell 额外经 consult_for_shell (allow/confirm/deny)",
        }, ensure_ascii=False, indent=2) + "\n")
        return 0

    console.print("\n[bold]=== L1 信任滤网动作矩阵 ===[/bold]")
    console.print("[dim](fail-closed: 未知/非预期级别一律拒绝)[/dim]\n")

    lv_label = {TrustLevel.TRUSTED: "受信", TrustLevel.LIMITED: "受限",
                TrustLevel.UNTRUSTED: "不信任", TrustLevel.UNKNOWN: "未知"}
    act_label = {"read": "读", "plan": "规划", "write": "写", "edit": "改",
                 "run_shell": "shell", "task": "任务"}

    header = "  " + " " * 10
    for act in actions:
        header += f"  {act_label[act]:^5}"
    console.print(header)
    for row in matrix:
        lv = row["level"]
        color = {"trusted": "green", "limited": "yellow",
                 "untrusted": "red", "unknown": "dim"}.get(lv, "dim")
        line = f"  [{color}]{lv_label[lv]:^6}[/{color}] "
        for act in actions:
            mark = "✓" if row[act] == "allow" else "✗"
            mcolor = "green" if row[act] == "allow" else "red"
            line += f" [{mcolor}]{mark:^5}[/{mcolor}]"
        console.print(line)

    console.print("\n[bold]shell 额外裁决[/bold] (consult_for_shell)")
    for sr in shell_rows:
        color = {"allow": "green", "confirm": "yellow", "deny": "red"}.get(sr["shell"], "dim")
        console.print(f"  {sr['level']:<10} → [{color}]{sr['shell']}[/{color}]  "
                      f"[dim]({sr['reason']})[/dim]")

    console.print("\n[dim]说明: trusted 仍受 safety 引擎约束; "
                  "limited 仅放行只读类动作; untrusted 一律拒绝[/dim]")
    return 0


def _trust_audit(trust: Any, json_mode: bool) -> int:
    """信任决策审计: 级别分布 + 衰减情况 + 敏感面指纹。

    让「信任边界」可观测: 有多少工作区、各级别多少、多少正在衰减、
    敏感面指纹是否变化。Claude Code 无对应概念。
    """
    import json
    import sys

    records = trust.list_trusted()
    dist: Dict[str, int] = {lv: 0 for lv in
                            ("trusted", "limited", "untrusted", "unknown")}
    decayed = 0
    for rec in records:
        lv = rec.level if rec.level in dist else "unknown"
        dist[lv] += 1
        if rec.decay_reason or rec.decayed_at:
            decayed += 1

    # 最近衰减记录
    decaying = []
    for rec in records:
        if rec.decay_reason:
            decaying.append({
                "path": rec.path,
                "reason": rec.decay_reason,
                "level": rec.level,
                "trust_count": rec.trust_count,
            })

    if json_mode:
        sys.stdout.write(json.dumps({
            "total": len(records),
            "distribution": dist,
            "decayed": decayed,
            "decaying": decaying,
            "trusted_paths": [{"path": r.path, "level": r.level,
                               "trust_count": r.trust_count}
                              for r in records],
        }, ensure_ascii=False, indent=2) + "\n")
        return 0

    console.print("\n[bold]=== 信任决策审计 ===[/bold]\n")
    console.print(f"  已记录工作区: [bold]{len(records)}[/bold] 个")
    parts = []
    for lv in ("trusted", "limited", "untrusted", "unknown"):
        parts.append(f"{lv}={dist.get(lv, 0)}")
    console.print("  级别分布: " + "  ".join(parts))
    console.print(f"  正在衰减: [yellow]{decayed}[/yellow] 个"
                  + (" (敏感面指纹变化或超期)" if decayed else ""))
    if decaying:
        console.print("\n  [bold]衰减明细:[/bold]")
        for d in decaying[:8]:
            console.print(f"    [yellow]◐[/yellow] {d['path']}  "
                          f"[dim]({d['level']}, 原因: {d['reason'][:50]})[/dim]")
    console.print("\n[dim]说明: 衰减 = 指纹变化或 >90 天未用, 自动降级为需重新确认; "
                  "cleanup 清理过期[/dim]")
    return 0


def _render_level(level: str) -> None:
    """按信任级别着色显示。"""
    color = {"trusted": "green", "limited": "yellow", "untrusted": "red",
             "unknown": "dim"}.get(level, "dim")
    label = {"trusted": "受信", "limited": "受限", "untrusted": "不信任",
             "unknown": "未知"}.get(level, level)
    console.print(f"[{color}]{level}[/{color}]  ({label})")


def _trust_status(trust: Any, all_: bool) -> None:
    """列出受信工作区 + 信任级别 + 指纹 (默认); --all 连 untrusted 也列出。"""
    console.print("\n[bold]=== 工作区信任 ===[/bold]\n")
    records = trust.list_trusted()
    if not records:
        console.print("[dim]暂无受信工作区 (首次打开目录时交互式询问)[/dim]")
        console.print("[dim]用法: tuan trust check <路径> 裁决 / set <路径> <级别> 标记[/dim]")
        return

    for rec in records:
        if rec.level == "untrusted" and not all_:
            continue
        _render_level(rec.level)
        console.print(f"    [dim]{rec.path}[/dim]")
        if rec.project_name:
            console.print(f"    [dim]  项目: {rec.project_name}[/dim]")
        console.print(f"    [dim]  指纹: {rec.fingerprint[:24]}…[/dim]")
        try:
            ts = datetime.fromtimestamp(rec.last_used).strftime("%Y-%m-%d")
            console.print(f"    [dim]  最近使用: {ts}[/dim]")
        except Exception as exc:  # noqa: BLE001
            log.warning("trust 命令辅助操作失败(不影响主流程): %s", exc)
            pass

    console.print("\n[dim]统计: " + ", ".join(
        f"{lv}={sum(1 for r in records if r.level == lv)}"
        for lv in ("trusted", "limited", "untrusted")
    ) + "[/dim]")
    console.print("[dim]提示: --all 连不信任工作区也列出; "
                  "cleanup 清理 >90 天未用的过期信任[/dim]")
