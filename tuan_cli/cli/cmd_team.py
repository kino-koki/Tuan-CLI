"""tuan team —— 团组 (TeamGroup) CLI 入口 (v0.4.2)。

纯本地团队管理命令行: 创建团组、加成员、登记供应商凭证 (只存指纹)、
签发/验证/撤销授权、查看审计、导出跨机邀请令牌。全部操作纯本地落盘
(<workspace>/.tuan/team_group.json + team_audit.jsonl), 无云端中转。

对齐 goal: 100 人上限 / key 所有者验证 / TTL≤90天 / 远程+局域网互通。
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from ..config import home_dir
from ..core.team_agents import CoordinatorError, WorkerSpec, load_team_coordinator
from ..core.team_group import (
    MAX_GRANT_DAYS,
    MAX_MEMBERS,
    TeamGroupError,
    TeamGroupStore,
    load_team_group,
)
from ..core.team_security import load_team_security
from ._ui_singleton import console
from .parser import _register_command


def _store(args: Any) -> TeamGroupStore:
    ws = str(getattr(args, "workspace", None) or home_dir())
    return load_team_group(ws)


def _security(args: Any) -> Any:
    return load_team_security(_store(args))


def _ok(data: Any) -> int:
    print(json.dumps(data, ensure_ascii=False, indent=2))
    return 0


def _err(exc: Exception) -> int:
    console.print(f"[red]✗ {exc}[/red]")
    return 1


# ------------------------------------------------------------------ 子命令

def _cmd_create(args: Any) -> int:
    store = _store(args)
    try:
        g = store.create_group(args.name, args.owner, owner_name=args.owner)
    except TeamGroupError as exc:
        return _err(exc)
    if args.json:
        return _ok({"ok": True, "group": store.export_public()})
    console.print(f"[green]✓ 团组已创建: {g.name}[/green]")
    console.print(f"  id: {g.group_id}")
    console.print(f"  团主: {g.owner}")
    console.print(f"  上限: {MAX_MEMBERS} 人")
    return 0


def _cmd_show(args: Any) -> int:
    store = _store(args)
    snap = store.export_public()
    if not snap.get("created"):
        console.print("[dim]团组未创建 (用 tuan team create 创建)[/dim]")
        return 1
    if args.json:
        out = dict(snap)
        out["members"] = store.list_members(include_revoked=True)
        out["providers"] = store.list_providers()
        out["grants"] = store.list_grants()
        return _ok(out)
    console.print(f"[bold]团组: {snap['name']}[/bold] ({snap['group_id']})")
    console.print(f"  团主: {snap['owner']}")
    console.print(f"  成员: {snap['member_count']}/{snap['max_members']}")
    provs = store.list_providers()
    if provs:
        console.print(f"  供应商: {', '.join(p['provider_id'] for p in provs)}")
    grants = [g for g in store.list_grants() if not g.get("revoked")]
    if grants:
        console.print(f"  活跃授权: {len(grants)} 条")
    return 0


def _cmd_add_member(args: Any) -> int:
    store = _store(args)
    try:
        info = store.add_member(args.member_id, args.display_name or "",
                                role=args.role, actor=args.actor)
    except TeamGroupError as exc:
        return _err(exc)
    if args.json:
        return _ok({"ok": True, "member": info})
    console.print(f"[green]✓ 成员已加入: {info['member_id']} ({info['role']})[/green]")
    return 0


def _cmd_register(args: Any) -> int:
    """团主登记供应商凭证 (只存指纹, 原文留在本机环境变量)。"""
    store = _store(args)
    try:
        group = store.group
        entry = store.register_provider_key(args.provider_id, args.fingerprint,
                                            owner=args.owner or (group.owner if group else ""))
    except TeamGroupError as exc:
        return _err(exc)
    if args.json:
        return _ok({"ok": True, "provider": entry})
    console.print(f"[green]✓ 供应商已登记: {entry['provider_id']}[/green]")
    console.print("  [dim]原文 key 留在本机, 团组内只流转签名授权[/dim]")
    return 0


def _cmd_issue(args: Any) -> int:
    store = _store(args)
    models = [m.strip() for m in (args.models or "").split(",") if m.strip()] or None
    try:
        grant = store.issue_grant(args.provider_id, args.member, args.days,
                                  model_scope=models, owner=args.owner)
    except TeamGroupError as exc:
        return _err(exc)
    if args.json:
        return _ok({"ok": True, "grant": grant})
    console.print(f"[green]✓ 授权已签发: {grant['grant_id']}[/green]")
    console.print(f"  供应商: {grant['provider']} → 成员: {grant['member']}")
    console.print(f"  时限: {grant['days']} 天 (≤{MAX_GRANT_DAYS})")
    if grant["scope"]["models"]:
        console.print(f"  模型范围: {', '.join(grant['scope']['models'])}")
    return 0


def _cmd_verify(args: Any) -> int:
    """使用前验证 (验签+TTL+scope, fail-closed)。"""
    store = _store(args)
    try:
        verdict = store.verify_grant(args.grant_id, args.provider_id, model=args.model)
    except TeamGroupError as exc:
        return _err(exc)
    if args.json:
        return _ok({"ok": True, "verdict": verdict})
    console.print(f"[green]✓ 授权有效: {verdict['grant_id']}[/green]")
    console.print(f"  成员 {verdict['member']} → 供应商 {verdict['provider']}")
    return 0


def _cmd_revoke_grant(args: Any) -> int:
    store = _store(args)
    try:
        store.revoke_grant(args.grant_id, actor=args.actor)
    except TeamGroupError as exc:
        return _err(exc)
    if args.json:
        return _ok({"ok": True})
    console.print(f"[green]✓ 授权已撤销: {args.grant_id}[/green]")
    return 0


def _cmd_revoke_member(args: Any) -> int:
    store = _store(args)
    try:
        store.revoke_member(args.member_id, actor=args.actor)
    except TeamGroupError as exc:
        return _err(exc)
    if args.json:
        return _ok({"ok": True})
    console.print(f"[green]✓ 成员已移除 (连带撤销其授权): {args.member_id}[/green]")
    return 0


def _cmd_audit(args: Any) -> int:
    store = _store(args)
    records = store.read_audit(limit=args.limit)
    if args.json:
        return _ok({"ok": True, "count": len(records), "audit": records})
    if not records:
        console.print("[dim]无审计记录[/dim]")
        return 0
    console.print(f"[bold]团组审计[/bold] (最近 {len(records)} 条)")
    for r in records:
        ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(r.get("ts", 0)))
        detail = r.get("detail") or {}
        brief = " ".join(f"{k}={v}" for k, v in detail.items() if k != "model") or "-"
        console.print(f"  [dim]{ts}[/dim] [cyan]{r['action']}[/cyan] ({r.get('actor','')}) {brief}")
    return 0


def _cmd_invite(args: Any) -> int:
    """导出跨机邀请令牌 (远程/局域网加入)。含 secret, 通过安全信道分享。"""
    store = _store(args)
    try:
        tok = store.export_invite(days_valid=args.days)
    except TeamGroupError as exc:
        return _err(exc)
    if args.json:
        return _ok({"ok": True, "invite": tok})
    console.print(f"[bold]团组邀请令牌[/bold] (有效期 {args.days} 天)")
    console.print(json.dumps(tok, ensure_ascii=False, indent=2))
    console.print("[yellow]⚠ 含 secret, 仅通过安全信道 (面对面/加密传输) 分享[/yellow]")
    return 0


def _cmd_import_invite(args: Any) -> int:
    """校验邀请令牌结构 + 有效期。"""
    try:
        tok = json.loads(args.token)
        meta = TeamGroupStore.import_invite(tok)
    except (ValueError, TeamGroupError) as exc:
        return _err(exc)
    if args.json:
        return _ok({"ok": True, "meta": meta})
    console.print(f"[green]✓ 邀请有效[/green]")
    console.print(f"  团组: {meta['name']} ({meta['group_id']})")
    console.print(f"  团主: {meta['owner']}")
    return 0


def _cmd_rotate(args: Any) -> int:
    """轮换团组密钥 (owner, 重签所有活跃授权)。"""
    sec = _security(args)
    try:
        r = sec.rotate_secret(actor=args.actor, grace_days=args.grace_days)
    except TeamGroupError as exc:
        return _err(exc)
    if args.json:
        return _ok({"ok": True, "rotation": r})
    console.print(f"[green]✓ 密钥已轮换[/green]")
    console.print(f"  重签授权: {r['resigned_grants']} 条")
    console.print(f"  宽限至: {time.strftime('%Y-%m-%d %H:%M', time.localtime(r['grace_until']))}")
    console.print("  [yellow]⚠ 旧邀请令牌已失效, 需重新邀请[/yellow]")
    return 0


def _cmd_challenge(args: Any) -> int:
    """下发一次性 challenge (敏感操作前验证持有团组密钥)。"""
    sec = _security(args)
    try:
        ch = sec.issue_challenge(ttl_seconds=args.ttl)
    except TeamGroupError as exc:
        return _err(exc)
    if args.json:
        return _ok({"ok": True, "challenge": ch})
    console.print(f"[bold]Challenge[/bold] (TTL {args.ttl}s)")
    console.print(f"  id: {ch['challenge_id']}")
    console.print(f"  challenge: {ch['challenge']}")
    console.print("  [dim]用 HMAC-SHA256(challenge, 团组密钥) 应答[/dim]")
    return 0


def _cmd_dispatch(args: Any) -> int:
    """Agent-of-Agents: 从 JSON 文件读取 workers 并并行派发。"""
    try:
        spec = json.loads(Path(args.plan).read_text(encoding="utf-8"))
        goal = spec.get("goal", "")
        workers = [WorkerSpec(
            worker_id=w["worker_id"], capability=w["capability"],
            prompt=w.get("prompt", ""), provider=w.get("provider"),
            model=w.get("model"), member=w.get("member"),
            nonce=w.get("nonce"), meta=w.get("meta") or {},
        ) for w in spec.get("workers", [])]
    except (ValueError, OSError, KeyError) as exc:
        return _err(ValueError(f"计划文件无效: {exc}"))
    sec = _security(args)
    coord = load_team_coordinator(sec)
    try:
        report = coord.dispatch(goal, workers, actor=args.actor)
    except (TeamGroupError, CoordinatorError) as exc:
        return _err(exc)
    if args.json:
        return _ok({"ok": True, "report": report.to_dict()})
    console.print(f"[bold]协调报告[/bold] goal={goal}")
    console.print(f"  总计 {report.total} | 成功 {report.ok} | "
                  f"失败 {report.failed} | 跳过 {report.skipped}")
    console.print(f"  耗时 {report.duration_ms}ms")
    for r in report.results:
        mark = {"ok": "green", "failed": "red", "skipped": "yellow"}.get(r.status, "dim")
        console.print(f"  [{mark}]●[/{mark}] {r.worker_id} ({r.capability}) "
                      f"{r.status} {r.error or ''}")
    return 0 if report.failed == 0 else 1


# ------------------------------------------------------------------ 分发

def cmd_team(args: Any) -> int:
    """team 主入口: 分发到子命令。"""
    sub = getattr(args, "team_cmd", None) or "show"
    dispatch = {
        "create": _cmd_create,
        "show": _cmd_show,
        "add-member": _cmd_add_member,
        "register": _cmd_register,
        "issue": _cmd_issue,
        "verify": _cmd_verify,
        "revoke-grant": _cmd_revoke_grant,
        "revoke-member": _cmd_revoke_member,
        "audit": _cmd_audit,
        "invite": _cmd_invite,
        "import-invite": _cmd_import_invite,
        "rotate": _cmd_rotate,
        "challenge": _cmd_challenge,
        "dispatch": _cmd_dispatch,
    }
    fn = dispatch.get(sub)
    if fn is None:
        console.print(f"[red]未知 team 子命令: {sub}[/red]")
        return 1
    return fn(args)


_register_command("cmd_team", ".cmd_team")
