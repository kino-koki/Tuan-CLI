"""tuan safe · 威胁面扫描子命令。

覆盖: redteam / scan / integrity / guard / secrets / path / rules。
只做检测与建议; 真正的拦截在执行侧 (tools/shell.py + ext/security_gate.py)。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List

from ...config.loader import home_dir
from .._ui_singleton import console
from ._shared import _repo_root

import logging
log = logging.getLogger(__name__)


def _cmd_redteam(args: Any) -> int:
    """红队自检: 用内置对抗载荷验证安全引擎拦截率 (只读, 不执行任何危险命令)。

    复用 bench/bypass_matrix.py 的**手工对抗载荷** (灾难性意图断言), 这是
    安全引擎最硬的回归面 —— 不靠统计抽样, 而是一枚枚真实攻击命令逐一验证。

      tuan safe redteam                跑全部载荷并输出分级报告
      tuan safe redteam --list         只列出红队载荷分类 (不执行)
      tuan safe redteam --json         输出 JSON 汇总
      tuan safe redteam --category XX  只跑指定分类 (如 '破坏性命令')
    """
    list_only = bool(getattr(args, "list", False))
    json_mode = bool(getattr(args, "json", False))
    category = getattr(args, "category", None)

    bench_dir = _repo_root() / "bench"
    script = bench_dir / "bypass_matrix.py"
    if not script.exists():
        console.print(f"[red]红队载荷脚本缺失: {script}[/red]")
        console.print("[dim]提示: 在源码仓库内运行 (pip 包不含 bench/)[/dim]")
        return 1

    # --- 只列载荷 ---
    if list_only:
        try:
            import importlib.util as _ilu
            spec = _ilu.spec_from_file_location("tuan_bypass_matrix", script)
            if spec is None or spec.loader is None:
                raise RuntimeError("无法加载红队载荷模块")
            mod = _ilu.module_from_spec(spec)
            spec.loader.exec_module(mod)
            cases = mod.CASES  # list[tuple[payload, cat, expect, ctag]]
        except Exception as exc:  # noqa: BLE001
            console.print(f"[red]载荷加载失败: {exc}[/red]")
            return 1
        console.print("\n[bold]=== 红队载荷清单 ===[/bold]\n")
        by_cat: dict[str, int] = {}
        for c in cases:
            cat = c[1]
            by_cat[cat] = by_cat.get(cat, 0) + 1
        for cat in sorted(by_cat):
            console.print(f"  [bold]{cat}[/bold]: {by_cat[cat]} 例")
        console.print(f"\n[dim]共 {len(cases)} 条载荷; tuan safe redteam 逐个验证拦截率[/dim]")
        return 0

    # --- 跑载荷验证 ---
    import tempfile
    tmp_out = Path(tempfile.mktemp(suffix=".json", prefix="tuan_redteam_"))
    try:
        cmd = [sys.executable, str(script), "--json-out", str(tmp_out)]
        if category:
            # bypass_matrix 不支持 --category, 通过环境变量传递给脚本 (见下)
            import os as _os
            _os.environ["TUAN_REDTEAM_CATEGORY"] = category
        console.print(f"[bold]红队自检[/bold] 加载对抗载荷 → 验证拦截率...\n")
        r = subprocess.run(cmd, capture_output=True, text=True,
                           errors="replace", timeout=600)
        if not tmp_out.exists():
            console.print(f"[red]红队自检失败: {r.stderr[-500:] or r.stdout[-500:]}[/red]")
            return 1
        data = json.loads(tmp_out.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]红队自检异常: {exc}[/red]")
        return 1
    finally:
        try:
            tmp_out.unlink()
        except OSError:
            pass

    bypass = data.get("bypass", 0)
    false_pos = data.get("false_pos", 0)
    all_blocked = data.get("all_disaster_blocked", False)
    total = data.get("total", data.get("cases", 0))

    if json_mode:
        sys.stdout.write(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
        return 0

    console.print(f"\n[bold]=== 红队自检报告 ===[/bold]\n")
    console.print(f"  载荷总数      : {total}")
    console.print(f"  绕过          : [red]{bypass}[/red]")
    console.print(f"  误杀          : {false_pos}")
    console.print(f"  灾难意图全拦  : {'[green]✓ 是[/green]' if all_blocked else '[red]✗ 存在漏拦[/red]'}")

    # 分级结论
    if bypass == 0 and all_blocked:
        grade = "[green]A 级[/green] 所有对抗载荷被拦截, 灾难性意图 100% 覆盖"
    elif bypass <= 2:
        grade = "[yellow]B 级[/yellow] 少量绕过, 需人工复核 (见上方类别)"
    else:
        grade = "[red]C 级[/red] 存在可复现绕过, 修复前不建议放行高危操作"
    console.print(f"\n[bold]结论[/bold]: {grade}")
    console.print("[dim]提示: tuan safe bench --check 可对比存档数字是否回归; "
                  "--list 看载荷分类; --json 给 CI 消费[/dim]")
    return 0 if bypass == 0 else 1


def _cmd_scan(args: Any) -> int:
    """密钥泄露扫描: 纯本地扫描目录文本中的明文密钥, 给出修复建议。

    复用 core.secret_scanner (确定性正则, 不联网, 不依赖外部漏洞库), 把
    「仓库里是否躺着明文 API Key / 私钥」这个最常被忽略的安全缺口暴露出来:

      tuan safe scan [路径]           扫描目录 (默认当前目录)
      tuan safe scan --file F         只扫单个文件
      tuan safe scan --json           输出 JSON (CI / SIEM 可消费)
      tuan safe scan --max-files N    限制扫描文件数 (默认 2000)
      tuan safe scan --no-skip-dirs   不跳过 .git/node_modules 等 (慎用)
    """
    target = getattr(args, "path", None)
    single_file = getattr(args, "file", None)
    json_mode = bool(getattr(args, "json", False))
    max_files = int(getattr(args, "max_files", 2000) or 2000)
    no_skip = bool(getattr(args, "no_skip_dirs", False))

    try:
        from ...core.secret_scanner import (
            scan_directory, scan_file, summarize,
        )
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]密钥扫描器加载失败: {exc}[/red]")
        return 1

    # --- 单文件扫描 ---
    if single_file:
        p = Path(single_file).expanduser().resolve()
        if not p.is_file():
            console.print(f"[red]文件不存在: {p}[/red]")
            return 1
        findings = scan_file(p)
        if json_mode:
            sys.stdout.write(json.dumps(
                [f.to_dict() for f in findings], ensure_ascii=False, indent=2) + "\n")
            return 0
        console.print(f"\n[bold]=== 密钥扫描 · {p} ===[/bold]\n")
        console.print(summarize(findings))
        console.print(f"[dim]共扫描 1 个文件, 发现 {len(findings)} 处[/dim]")
        return 0 if not findings else 1

    # --- 目录扫描 (默认当前目录) ---
    root = Path(target).expanduser().resolve() if target else Path.cwd()
    if not root.is_dir():
        console.print(f"[red]目录不存在: {root}[/red]")
        return 1

    console.print(f"[bold]扫描密钥泄露[/bold] 目录: {root}")
    console.print(f"[dim]跳过目录: .git/node_modules/.venv 等 (--no-skip-dirs 可关)[/dim]")

    if no_skip:
        findings = scan_directory(root, skip_dirs=[], max_files=max_files)
    else:
        findings = scan_directory(root, max_files=max_files)
    n_files = min(
        sum(1 for _ in root.rglob("*") if _.is_file()), max_files)

    if json_mode:
        sys.stdout.write(json.dumps(
            [f.to_dict() for f in findings], ensure_ascii=False, indent=2) + "\n")
        return 0 if not findings else 1

    console.print("\n[bold]=== 密钥泄露扫描结果 ===[/bold]\n")
    console.print(summarize(findings))
    console.print(f"\n[dim]共扫描约 {n_files} 个文件, 发现 {len(findings)} 处疑似泄露; "
                  "--json 给 CI/SIEM 消费[/dim]")
    return 0 if not findings else 1


def _cmd_integrity(args: Any) -> int:
    """关键文件完整性监控: 对配置/脚本/技能目录建快照并检测篡改。

    复用 core.file_integrity (SHA-256 快照 + 变更分级 fail-closed), 把
    「配置/技能是否被未授权改动」这个应用层防篡改能力暴露给运维:

      tuan safe integrity                   查看变更历史 + 统计 (默认)
      tuan safe integrity snapshot DIR      对目录建快照 (label 可选)
      tuan safe integrity check DIR         对比快照检测变更
      tuan safe integrity check DIR --label 指定快照标签
      tuan safe integrity --report          导出 Markdown 报告
      tuan safe integrity --last N          最近 N 条变更 (默认 50)
      tuan safe integrity --severity X      按严重度过滤 (high/medium/low)
    """
    sub = getattr(args, "integrity_cmd", None) or "status"
    last_n = int(getattr(args, "last", 50) or 50)
    severity = getattr(args, "severity", None)
    label = getattr(args, "label", "")
    report = bool(getattr(args, "report", False))
    target = getattr(args, "target", None)

    try:
        from ...core.file_integrity import FileIntegrityMonitor
        monitor = FileIntegrityMonitor(home=Path(home_dir()))
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]完整性监控器初始化失败: {exc}[/red]")
        return 1

    # --- snapshot: 建快照 ---
    if sub == "snapshot":
        if not target:
            console.print("[red]用法: tuan safe integrity snapshot <目录> [--label X][/red]")
            return 1
        p = Path(target).expanduser().resolve()
        if not p.is_dir():
            console.print(f"[red]目录不存在: {p}[/red]")
            return 1
        console.print(f"[bold]建完整性快照[/bold] {p}  (label={label or '(无)'})")
        count = monitor.snapshot_directory(p, label=label)
        console.print(f"[green]✓ 已快照 {count} 个文件[/green] "
                      f"(基准: {home_dir()}/.integrity)")
        return 0

    # --- check: 检测变更 ---
    if sub == "check":
        if not target:
            console.print("[red]用法: tuan safe integrity check <目录> [--label X][/red]")
            return 1
        p = Path(target).expanduser().resolve()
        if not p.is_dir():
            console.print(f"[red]目录不存在: {p}[/red]")
            return 1
        console.print(f"[bold]检查完整性[/bold] {p}  (label={label or '(无)'})")
        changes = monitor.check_directory(p, label=label)
        if not changes:
            console.print("[green]✓ 无变更, 文件完好[/green]")
            return 0
        console.print(f"[red]✗ 检测到 {len(changes)} 处变更:[/red]")
        for c in changes:
            from datetime import datetime as _dt
            ts = _dt.fromtimestamp(c.detected_at).strftime("%Y-%m-%d %H:%M:%S")
            sev_color = {"high": "red", "medium": "yellow", "low": "dim"}.get(c.severity, "dim")
            console.print(f"  [{sev_color}]{c.severity.upper()}[/{sev_color}] "
                          f"{ts}  {c.change_type}: {c.path}  ({c.details or ''})")
        return 1

    # --- 默认: 变更历史 + 统计 ---
    console.print("\n[bold]=== 文件完整性监控 ===[/bold]\n")
    try:
        stats = monitor.stats()
        console.print(f"[bold]总变更数[/bold]: {stats.get('total_changes', 0)}")
        console.print(f"[bold]按类型[/bold]: {stats.get('by_type', {}) or '无'}")
        console.print(f"[bold]按严重度[/bold]: {stats.get('by_severity', {}) or '无'}")
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]统计读取失败: {exc}[/red]")

    if report:
        console.print("\n[bold]=== 完整性报告 (Markdown) ===[/bold]\n")
        sys.stdout.write(monitor.export_report(last_n) + "\n")
        return 0

    try:
        changes = monitor.get_changes(severity=severity, last_n=last_n)
        if changes:
            console.print(f"\n[bold]最近变更 (最近 {len(changes)} 条)[/bold]")
            for c in reversed(changes):
                from datetime import datetime as _dt
                ts = _dt.fromtimestamp(c.detected_at).strftime("%Y-%m-%d %H:%M:%S")
                sev_color = {"high": "red", "medium": "yellow", "low": "dim"}.get(c.severity, "dim")
                console.print(f"  [{sev_color}]{c.severity.upper()}[/{sev_color}] "
                              f"{ts}  {c.change_type}: {c.path}")
        else:
            console.print("\n[dim]暂无变更记录 (先 tuan safe integrity snapshot <目录> 建基准)[/dim]")
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]变更读取失败: {exc}[/red]")

    console.print("\n[dim]提示: snapshot <目录> 建基准 / check <目录> 检测变更; "
                  "--report 导出 Markdown[/dim]")
    return 0


def _cmd_guard(args: Any) -> int:
    """密钥拦截守卫: 阻断含明文密钥的提交/写入 (嵌入 pre-commit / CI)。

    差异化独特能力: Claude Code 没有「防密钥泄露的守门人」。本命令可嵌入
    git pre-commit hook 或 CI 流水线, 一旦暂存区/工作区出现明文 API Key 或私钥,
    即**阻断** (exit 非 0) 并给出修复建议, 把「密钥进了 git 历史」这个不可逆
    泄露挡在门外。

      tuan safe guard check [路径]     检查目录 (默认 .git 暂存区, 无 git 则当前目录)
      tuan safe guard check --stdin    检查 stdin 内容 (编辑器保存钩子用)
      tuan safe guard check --severity high   只拦 high (默认 high+medium)
      tuan safe guard allow <类型>      添加豁免类型 (如 aws_access_key)
      tuan safe guard status            查看守卫状态 (豁免列表 + 规则数)
      tuan safe guard init-hook         打印 git pre-commit hook 片段 (接入指引)
    """
    sub = getattr(args, "guard_cmd", None) or "status"
    target = getattr(args, "target", None)
    stdin_mode = bool(getattr(args, "stdin", False))
    severity = getattr(args, "severity", None)
    allow_type = getattr(args, "allow", None)

    try:
        from ...core.secret_scanner import scan_directory, scan_text
        from ...core.secret_scanner import _RULES
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]守卫初始化失败: {exc}[/red]")
        return 1

    # --- 豁免清单 (持久化 ~/.tuan/guard_allow.json) ---
    allow_file = Path(home_dir()) / "guard_allow.json"
    if not allow_file.exists():
        allow_file.write_text("[]", encoding="utf-8")

    def _load_allow() -> list[str]:
        try:
            raw = json.loads(allow_file.read_text(encoding="utf-8"))
            return [str(x) for x in raw] if isinstance(raw, list) else []
        except Exception as exc:  # noqa: BLE001
            log.debug("_load_allow(): 非致命异常已忽略(设计内降级, 不改控制流): %s", exc)
            return []

    def _save_allow(items: list[str]) -> None:
        allow_file.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")

    # --- allow: 加豁免 ---
    if sub == "allow":
        if not allow_type:
            console.print("[red]用法: tuan safe guard allow <类型>[/red]")
            return 1
        items = _load_allow()
        if allow_type not in items:
            items.append(allow_type)
            _save_allow(items)
        console.print(f"[green]✓ 已豁免类型 {allow_type}[/green] (当前 {len(items)} 项)")
        return 0

    # --- init-hook: 打印 hook 片段 ---
    if sub == "init-hook":
        console.print("[bold]# git pre-commit hook 接入指引 (写入 .git/hooks/pre-commit):[/bold]")
        console.print("#!/bin/sh")
        console.print("tuan safe guard check . || { echo '✗ 密钥泄露被拦截, 修复后重试'; exit 1; }")
        console.print("")
        console.print("[dim]提示: git config core.hooksPath .githooks 可让 hook 随仓库走[/dim]")
        return 0

    # --- status ---
    if sub == "status":
        allow_list = _load_allow()
        console.print("\n[bold]=== 密钥守卫状态 ===[/bold]\n")
        console.print(f"[bold]规则数[/bold]: {len(_RULES)} (类型: "
                      f"{', '.join(r.secret_type for r in _RULES)})")
        console.print(f"[bold]豁免类型[/bold]: {', '.join(allow_list) if allow_list else '(无)'}")
        console.print(f"[bold]豁免文件[/bold]: {allow_file}")
        console.print("\n[dim]用法: tuan safe guard check . 阻断含密钥的提交; "
                      "tuan safe guard allow <类型> 豁免某类[/dim]")
        return 0

    # --- check (默认行为) ---
    if sub != "check":
        console.print(f"[red]未知子命令: {sub}[/red] "
                      "(可用: check / allow / status / init-hook)")
        return 1

    allow_list = _load_allow()
    if stdin_mode:
        content = sys.stdin.read()
        findings = scan_text(content, path="<stdin>")
    elif target:
        p = Path(target).expanduser().resolve()
        if p.is_file():
            from ...core.secret_scanner import scan_file
            findings = scan_file(p)
        elif p.is_dir():
            findings = scan_directory(p, max_files=5000)
        else:
            console.print(f"[red]路径不存在: {p}[/red]")
            return 2
    else:
        # 默认: git 暂存区 (staged), 无 git 则当前目录
        import subprocess as _sp
        try:
            r = _sp.run(["git", "diff", "--cached", "--name-only", "-z"],
                        capture_output=True, text=True, timeout=15)
            if r.returncode == 0 and r.stdout:
                paths = [x for x in r.stdout.split("\0") if x]
                from ...core.secret_scanner import scan_file
                findings = []
                for fp in paths:
                    p = Path(fp)
                    if p.is_file() and p.stat().st_size < 5 * 1024 * 1024:
                        findings.extend(scan_file(p))
            else:
                findings = scan_directory(Path.cwd(), max_files=5000)
        except Exception:  # noqa: BLE001 - git 不可用回退当前目录
            findings = scan_directory(Path.cwd(), max_files=5000)

    # 过滤豁免 + 严重度
    cutoff = {"high": 1, "medium": 2, "low": 3}.get(severity or "medium", 2)
    sev_rank = {"high": 1, "medium": 2, "low": 3}
    blocked = [f for f in findings
               if f.secret_type not in allow_list
               and sev_rank.get(f.severity, 3) <= cutoff]

    if not blocked:
        console.print("[green]✓ 未发现密钥泄露[/green]")
        # 命中但被豁免的提示
        exempted = [f for f in findings if f.secret_type in allow_list]
        if exempted:
            console.print(f"[dim]  豁免类型命中 {len(exempted)} 处 (已放行)[/dim]")
        return 0

    console.print(f"[red]✗ 发现 {len(blocked)} 处密钥泄露, 已阻断:[/red]")
    for f in blocked:
        console.print(f"  [red]{f.severity.upper()}[/red] {f.description} "
                      f"{f.path or ''}:{f.line}  → {f.preview}")
        console.print(f"      [dim]修复: {f.remediation}[/dim]")
    console.print("\n[red]阻断: 请先移除/轮换上述密钥再提交。[/red]")
    console.print("[dim]  (确属误报可 tuan safe guard allow <类型> 豁免)[/dim]")

    # 汇入安全事件总线留痕
    try:
        from ...core.security_bus import SecurityEvent, get_security_bus
        get_security_bus().emit(SecurityEvent(
            event_type="guard.blocked",
            timestamp=time.time(),
            payload={"count": len(blocked)},
            source="cmd_safe.guard",
            severity="high",
        ))
    except Exception as exc:  # noqa: BLE001
        log.warning("_cmd_guard(): 非致命异常已忽略(设计内降级, 不改控制流): %s", exc)
        pass
    return 1


def _cmd_secrets(args: Any) -> int:
    """密钥暴露与轮换态势报告 (差异化: 凭据级暴露裁决, Claude Code 无)。

    回答三个运维问题:
      1. 哪些密钥载体文件存在明文凭据? (扫描 ~/.tuan 密钥载体 + 可选工作区)
      2. 当前配置的**在线凭据** (config/env 引用的) 是否落在明文里? (暴露=1)
      3. 轮换就绪度: 每个暴露凭据给出「轮换动作」结论。

      tuan safe secrets [--scope home|workspace|all] [--json]
        --scope   扫描范围 (默认 home=~/.tuan 密钥载体)
        --json    结构化输出 (CI/SIEM 消费)
    """
    scope = getattr(args, "scope", "home") or "home"
    json_mode = bool(getattr(args, "json", False))

    from ...core.secret_scanner import scan_file, scan_directory, SecretFinding

    home = Path(home_dir())
    # 密钥载体 (home 范围): 真实密钥文件, 不递归 skills/ 避免教学反例误报
    carriers = [
        home / ".env", home / ".env.local", home / ".env.production",
        home / "config.yaml", home / "credentials.json", home / "credentials.yaml",
        home / "secrets.json", home / "secrets.yaml",
    ]
    # 收集发现 (路径, 发现) —— 统一为 dict 形态
    findings: List[Dict[str, Any]] = []
    seen_paths: set[str] = set()

    def _as_dict(f: Any) -> Dict[str, Any]:
        if isinstance(f, dict):
            return f
        data = f.to_dict()  # SecretFinding 数据类
        return {k: v for k, v in data.items()}

    if scope in ("home", "all"):
        for carrier in carriers:
            if carrier.exists() and carrier.is_file():
                seen_paths.add(str(carrier))
                for sf in scan_file(carrier):
                    findings.append(_as_dict(sf))
    if scope in ("workspace", "all"):
        wroot = Path.cwd()
        # 跳过 home 目录 (避免重复); 扫描工作区文本文件
        for sf in scan_directory(wroot):
            d = _as_dict(sf)
            if str(Path(d.get("path", "")).resolve()).startswith(str(home.resolve())):
                continue
            findings.append(d)

    # 暴露严重度统计
    by_sev: Counter = Counter(fk.get("severity", "low") for fk in findings)
    high_n = by_sev.get("high", 0)
    medium_n = by_sev.get("medium", 0)
    low_n = by_sev.get("low", 0)

    # 在线凭据暴露判定: 取 config 引用/环境变量中的真实 key, 与发现脱敏前缀比对
    live_exposed: List[Dict[str, Any]] = []
    try:
        from ...config.loader import Config

        cfg = Config()
        env_name = cfg.get("model.api_key_env", "DEEPSEEK_API_KEY")
        live = os.environ.get(env_name) or os.environ.get("TUAN_API_KEY") or ""
        if live and len(live) >= 8:
            prefix = live[:4]
            suffix = live[-4:]
            seen_live: set[tuple[str, int]] = set()
            for fk in findings:
                preview = fk.get("preview", "")
                if preview.startswith(prefix) and preview.endswith(suffix) and len(preview) > 8:
                    key = (str(fk.get("path")), int(fk.get("line") or 0))
                    if key in seen_live:
                        continue
                    seen_live.add(key)
                    live_exposed.append({
                        "secret_type": fk.get("secret_type"),
                        "path": fk.get("path"),
                        "line": fk.get("line"),
                        "env": env_name,
                    })
    except Exception as exc:  # noqa: BLE001
        log.warning("_cmd_secrets(): 非致命异常已忽略(设计内降级, 不改控制流): %s", exc)
        pass

    exposed = bool(high_n or live_exposed)

    if json_mode:
        sys.stdout.write(json.dumps({
            "scope": scope,
            "scanned_carriers": sorted(seen_paths),
            "findings": findings,
            "by_severity": dict(by_sev),
            "live_credential_exposed": bool(live_exposed),
            "live_exposed": live_exposed,
            "verdict": "exposed" if exposed else "clean",
            "rotation_required": exposed,
        }, ensure_ascii=False, indent=2) + "\n")
        return 0 if not exposed else 2

    console.print("\n[bold]=== 密钥暴露与轮换态势 ===[/bold]\n")
    console.print(f"[bold]扫描范围[/bold]: {scope}  "
                  f"(载体 {len(seen_paths)} 个, 发现 {len(findings)} 处)")
    console.print(f"[bold]严重度分布[/bold]: high={high_n} medium={medium_n} low={low_n}")

    if live_exposed:
        console.print(f"\n[red][bold]!! 在线凭据暴露[/bold][/red] 当前配置的密钥 "
                      f"({live_exposed[0].get('env')}) 明文出现在:")
        for le in live_exposed:
            console.print(f"  - {le.get('path')}:{le.get('line')} ({le.get('secret_type')})")
        console.print("  [red]立即轮换: 吊销该 key 并重新注入 (tuan setup / ~/.tuan/.env)[/red]")

    if findings:
        console.print("\n[bold]发现明细[/bold]")
        for fk in findings[:20]:
            sev = fk.get("severity", "low")
            color = {"high": "red", "medium": "yellow", "low": "dim"}.get(sev, "dim")
            console.print(f"  [{color}]{sev:<6}[/{color}] {fk.get('description')} "
                          f"@ [dim]{fk.get('path')}:{fk.get('line')}[/dim]  ({fk.get('preview')})")
            if sev in ("high", "medium"):
                console.print(f"          [dim]→ {fk.get('remediation')}[/dim]")
        if len(findings) > 20:
            console.print(f"  [dim]… 还有 {len(findings) - 20} 处 (--json 看全量)[/dim]")

    if not exposed:
        console.print("\n[green]✓ 未发现暴露凭据; 轮换无需紧急执行[/green]")
    else:
        console.print("\n[red][bold]✗ 发现暴露/高危凭据, 需轮换[/bold][/red]")

    console.print("\n[dim]提示: tuan safe guard check 可接入 pre-commit 阻断; "
                  "tuan safe scan 做全目录扫描[/dim]")
    return 0 if not exposed else 2


def _cmd_path(args: Any) -> int:
    """路径安全校验: 检测 ../ 逃逸 / 符号链接逃逸 / 系统目录访问 / 敏感路径。

    tuan safe path <路径> [--action read|write|execute] [--workspace DIR] [--json]

    独特能力: Claude Code 无路径边界校验, 文件工具按用户目录直通;
    Tuan-CLI 用 L1 信任滤网做路径裁决 (fail-closed), 本命令把裁决暴露给用户。
    """
    path = getattr(args, "path", None)
    if not path:
        console.print("[red]用法: tuan safe path <路径> [--action read|write|execute] "
                      "[--workspace DIR] [--json][/red]")
        return 1
    action = getattr(args, "action", "read") or "read"
    workspace = getattr(args, "workspace", None)
    json_mode = bool(getattr(args, "json", False))

    try:
        from ...core.path_safety import get_path_safety
        safety = get_path_safety(workspace=workspace or "")
        v = safety.validate_path(path, action=action, workspace=workspace)
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]路径安全校验初始化失败: {exc}[/red]")
        return 1

    # 输出
    if json_mode:
        import json as _json
        sys.stdout.write(_json.dumps({
            "safe": v.safe, "denied": v.denied, "reason": v.reason,
            "risk_level": v.risk_level, "original_path": v.original_path,
            "resolved_path": v.resolved_path, "violations": list(v.violations),
            "action": action,
        }, ensure_ascii=False, indent=2) + "\n")
        return 0 if v.safe else 1

    status = "SAFE" if v.safe else ("DENIED" if v.denied else "WARN")
    color = "green" if v.safe else ("red" if v.denied else "yellow")
    console.print(f"\n[{color}][bold]{status}[/bold][/{color}]  "
                  f"action={action}")
    console.print(f"  [dim]原始路径: {v.original_path}[/dim]")
    console.print(f"  [dim]解析路径: {v.resolved_path or '-'}[/dim]")
    console.print(f"  [dim]风险等级: {v.risk_level}[/dim]")
    if v.violations:
        console.print(f"  [dim]违规: {', '.join(v.violations)}[/dim]")
    if v.reason:
        console.print(f"  [dim]原因: {v.reason}[/dim]")
    if v.safe:
        console.print("\n[green]✓ 路径安全, 可放行[/green]")
    elif v.denied:
        console.print("\n[red]✗ 已拒绝 (fail-closed)[/red]")
    else:
        console.print("\n[yellow]⚠ 有限制, 需谨慎[/yellow]")
    return 0 if v.safe else 1


def _cmd_rules(args: Any) -> int:
    """威胁规则透明化: 列出安全引擎的全部分级规则 (E1-E8)。

    独特能力: Claude Code 的安全规则不透明 (只给"被拦截"结果);
    Tuan-CLI 把 E1-E8 分级的完整威胁规则表暴露给用户,
    便于审计/评估/定制 (哪些命令会被拦, 为什么拦)。

    tuan safe rules [--level critical|high|medium|extreme] [--json] [--keyword 词]
                    [--for 命令]    # 反查: 这条命令会命中哪些规则
    """
    level = getattr(args, "level", None) or "all"
    json_mode = bool(getattr(args, "json", False))
    keyword = getattr(args, "keyword", None)
    for_cmd = getattr(args, "for_cmd", None) or getattr(args, "for", None)

    try:
        from ...ext.safety_patterns import (
            _CRITICAL_PATTERNS, _HIGH_PATTERNS,
            _MEDIUM_PATTERNS, _EXTREME_PATTERNS,
        )
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]规则加载失败: {exc}[/red]")
        return 1

    # 分级 → E 级映射 (E1=critical, E2=high, E3=medium, E4=extreme)
    groups = [
        ("E1 致命", _CRITICAL_PATTERNS, "red"),
        ("E2 高危", _HIGH_PATTERNS, "orange"),
        ("E3 中危", _MEDIUM_PATTERNS, "yellow"),
        ("E4 极端", _EXTREME_PATTERNS, "red"),
    ]

    # --- 反查模式: 给定一条命令, 找出它命中的所有规则 (独特: 规则透明化+可审计) ---
    if for_cmd:
        import re as _re
        hits: List[Dict[str, Any]] = []
        for label, pats, color in groups:
            for pat, desc in pats:
                try:
                    if _re.search(pat, for_cmd, _re.IGNORECASE):
                        hits.append({"level": label.split()[0], "pattern": pat,
                                     "desc": desc})
                except _re.error:
                    continue
        if json_mode:
            sys.stdout.write(json.dumps({
                "command": for_cmd,
                "hits": hits,
                "count": len(hits),
            }, ensure_ascii=False, indent=2) + "\n")
            return 0
        console.print(f"\n[bold]命令反查:[/bold] {for_cmd}")
        console.print(f"[bold]命中规则[/bold]: {len(hits)} 条\n")
        if not hits:
            console.print("  [green]✓ 未命中任何 E 级规则 (不保证安全, 但不在规则库内)[/green]")
        for h in hits:
            console.print(f"  [bold]{h['level']}[/bold]  {h['desc']}")
            console.print(f"    [dim]pattern: {h['pattern'][:70]}{'…' if len(h['pattern']) > 70 else ''}[/dim]")
        console.print("\n[dim]提示: --for 反查是只读审计, 不执行命令[/dim]")
        return 0

    if json_mode:
        import json as _json
        out = {}
        for label, pats, _c in groups:
            if level != "all" and label.split()[0].lower() != level.lower():
                continue
            items = [{"desc": d, "pattern": p} for p, d in pats]
            if keyword:
                kw = keyword.lower()
                items = [i for i in items if kw in i["desc"].lower()
                         or kw in i["pattern"].lower()]
            out[label.split()[0]] = items
        sys.stdout.write(_json.dumps(out, ensure_ascii=False, indent=2) + "\n")
        return 0

    console.print("\n[bold]=== 安全引擎威胁规则 (E1-E4 分级) ===[/bold]\n")
    total = 0
    for label, pats, color in groups:
        if level != "all" and label.split()[0].lower() != level.lower():
            continue
        tup_items = [(p, d) for p, d in pats]
        if keyword:
            kw = keyword.lower()
            tup_items = [(p, d) for p, d in tup_items
                         if kw in d.lower() or kw in p.lower()]
        console.print(f"[{color}][bold]{label}[/bold][/{color}]  ({len(tup_items)} 条)")
        for p, d in tup_items:
            console.print(f"  [dim]• {d}[/dim]")
            console.print(f"    [dim]{p[:70]}{'…' if len(p) > 70 else ''}[/dim]")
        total += len(tup_items)
    console.print(f"\n[bold]合计[/bold]: {total} 条规则")
    console.print("[dim]提示: --level E1 只看致命 / --keyword 筛选 / --json 给 CI[/dim]")
    return 0
