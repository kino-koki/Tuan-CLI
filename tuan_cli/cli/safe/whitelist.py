"""tuan safe · 白名单 / 黑名单与状态概览子命令。

覆盖: list / allow / deny / check / blacklist / reduce / restore / update / suggest。
这些命令只改「本地信任名单」, 不参与执行期裁决。
"""
from __future__ import annotations

import logging
from typing import Any

from .._ui_singleton import console



log = logging.getLogger(__name__)
def _cmd_whitelist_list() -> int:
    try:
        from ...core.whitelist import WhitelistManager
        wl = WhitelistManager()
        entries = wl.list()
    except Exception as exc:  # noqa: BLE001
        log.debug("安全路径 fallback 降级: %s", exc)
        console.print(f"[red]白名单读取失败: {exc}[/red]")
        return 1

    if not entries:
        console.print("[yellow]白名单为空 (用 tuan safe allow <命令> 添加)[/yellow]")
        return 0

    console.print(f"\n[bold]白名单条目 ({len(entries)} 个):[/bold]\n")
    for i, entry in enumerate(entries, 1):
        cmd = entry.get("command", "")
        desc = entry.get("description", "")
        console.print(f"  {i:2d}. {cmd:<20s} {desc}")
    return 0


def _cmd_whitelist_add(args: Any) -> int:
    command = getattr(args, "command", None)
    if not command:
        console.print("[red]用法: tuan safe allow <命令>[/red]")
        return 1
    description = getattr(args, "description", "") or "用户本地自主添加"

    try:
        from ...ext.safety_engine import is_redline
        from ...core.whitelist import WhitelistManager
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
        log.debug("安全路径 fallback 降级: %s", exc)
        console.print(f"[red]添加失败: {exc}[/red]")
        return 1


def _cmd_whitelist_remove(args: Any) -> int:
    command = getattr(args, "command", None)
    if not command:
        console.print("[red]用法: tuan safe deny <命令>[/red]")
        return 1
    try:
        from ...core.whitelist import WhitelistManager
        wl = WhitelistManager()
        if wl.remove(command):
            console.print(f"[green]已从白名单移除: {command}[/green]")
        else:
            console.print(f"[yellow]不在白名单中: {command}[/yellow]")
        return 0
    except Exception as exc:  # noqa: BLE001
        log.debug("安全路径 fallback 降级: %s", exc)
        console.print(f"[red]移除失败: {exc}[/red]")
        return 1


def _cmd_whitelist_check(args: Any) -> int:
    """白名单/红线判定 (第 74 个独特功能: 预先确认命令的免确认执行)。

    差异化价值: Claude Code 的免确认白名单是黑箱 —— 你只能加/删, 不知道某条
    命令执行时到底会不会被白名单放过 (前缀匹配/通配符/红线否决都在内部)。
    本命令把 `WhitelistManager.is_whitelisted` 的判定暴露为**可预先查询**:
    回答「这条命令会不会免确认执行」「命中哪条白名单条目」「是否被红线否决」,
    让用户在执行前就知道该命令的确认策略。

      tuan safe check "npm test"          # 白名单判定
      tuan safe check "rm -rf /"          # 红线否决 (无论白名单)
      tuan safe check "git push" --json   # 机器可读
    """
    command = getattr(args, "command", None)
    if not command:
        console.print("[red]用法: tuan safe check <命令> [--json][/red]")
        return 1
    json_mode = bool(getattr(args, "json", False))

    try:
        from ...ext.safety_engine import is_redline
        from ...core.whitelist import WhitelistManager
        wl = WhitelistManager()
        entry = wl.matched_entry(command)
        allowed = entry is not None
        matched = entry["command"] if entry else None
        redline = is_redline(command)
    except Exception as exc:  # noqa: BLE001
        log.debug("安全路径 fallback 降级: %s", exc)
        console.print(f"[red]判定失败: {exc}[/red]")
        return 1

    if json_mode:
        import sys as _sys
        _sys.stdout.write(__import__("json").dumps({
            "command": command,
            "whitelisted": bool(allowed),
            "matched": matched or None,
            "redline": bool(redline),
            "verdict": ("deny" if redline else ("allow" if allowed else "confirm")),
        }, ensure_ascii=False, indent=2) + "\n")
        return 0 if (allowed and not redline) else 1

    console.print(f"\n[bold]命令确认策略 · {command}[/bold]\n")
    if redline:
        console.print("[red][bold]✗ 红线否决[/bold][/red]  "
                      "该命令命中安全红线, 即使白名单也绝不执行 (硬阻断)")
        console.print("  [dim]提示: 红线命令无法通过 tuan safe allow 加入白名单[/dim]")
        return 1
    if allowed:
        console.print("[green][bold]✓ 白名单命中[/bold][/green]  "
                      "该命令将免确认执行")
        if matched:
            console.print(f"  [dim]命中条目: {matched}[/dim]")
    else:
        console.print("[yellow][bold]⚠ 需确认[/bold][/yellow]  "
                      "该命令不在白名单, 执行前会请求用户确认")
    console.print("\n[dim]判定: is_whitelisted + 红线否决 (与执行期同一逻辑)[/dim]")
    return 0 if (allowed and not redline) else 1


def _cmd_blacklist() -> int:
    """列出内置黑名单模式库, 标注哪些已被用户本地抑制。"""
    try:
        from ...core import blacklist_override
        from ...ext.safety_engine import SafetyEngine
    except Exception as exc:  # noqa: BLE001
        log.debug("安全路径 fallback 降级: %s", exc)
        console.print(f"[red]黑名单读取失败: {exc}[/red]")
        return 1

    engine = SafetyEngine()
    levels = [
        ("CRITICAL (致命)", engine.CRITICAL_PATTERNS),
        ("HIGH (高危)", engine.HIGH_PATTERNS),
        ("MEDIUM (中危)", engine.MEDIUM_PATTERNS),
    ]

    console.print("\n[bold]内置黑名单模式库[/bold] (label 关键字可被 tuan safe reduce 本地抑制)\n")
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
        console.print("[dim]恢复: tuan safe restore <关键字>[/dim]")
    else:
        console.print("[dim]尚未抑制任何模式。减负示例: tuan safe reduce dd[/dim]")
    return 0


def _cmd_reduce(args: Any) -> int:
    keyword = getattr(args, "keyword", None)
    if not keyword:
        console.print("[red]用法: tuan safe reduce <关键字>[/red]")
        console.print("[dim]关键字会按 label 子串匹配, 例如: dd / format / shutdown / docker[/dim]")
        return 1
    try:
        from ...core import blacklist_override
        if blacklist_override.suppress(keyword):
            console.print(f"[green]已抑制匹配 '{keyword}' 的黑名单模式 (本地生效)[/green]")
            console.print("[dim]查看影响: tuan safe blacklist  |  撤销: tuan safe restore "
                          f"{keyword}[/dim]")
            return 0
        console.print(f"[yellow]关键字 '{keyword}' 已处于抑制状态, 无需重复操作[/yellow]")
        return 0
    except Exception as exc:  # noqa: BLE001
        log.debug("安全路径 fallback 降级: %s", exc)
        console.print(f"[red]抑制失败: {exc}[/red]")
        return 1


def _cmd_restore(args: Any) -> int:
    keyword = getattr(args, "keyword", None)
    if not keyword:
        console.print("[red]用法: tuan safe restore <关键字>[/red]")
        return 1
    try:
        from ...core import blacklist_override
        if blacklist_override.release(keyword):
            console.print(f"[green]已恢复匹配 '{keyword}' 的黑名单模式 (重新生效)[/green]")
            return 0
        console.print(f"[yellow]关键字 '{keyword}' 未被抑制, 无需恢复[/yellow]")
        return 0
    except Exception as exc:  # noqa: BLE001
        log.debug("安全路径 fallback 降级: %s", exc)
        console.print(f"[red]恢复失败: {exc}[/red]")
        return 1


def _cmd_update() -> int:
    console.print("\n[bold]=== 安全策略更新 ===[/bold]\n")
    try:
        from ...ext.security_policy import check_monthly_update, record_monthly_update
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
        log.debug("安全路径 fallback 降级: %s", exc)
        console.print(f"[red]更新检查失败: {exc}[/red]")
        return 1


def _cmd_suggest(args: Any) -> int:
    """对一条命令给出命令感知的安全替代建议 (交互式查询)。"""
    command = args.command
    from ...ext.safety_engine import SafetyEngine

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
