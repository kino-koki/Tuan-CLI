"""tuan harden —— 安全加固工具集命令行入口。

子命令
------
    tuan harden audit-export [--format cef|jsonl|syslog[,...]] [--from PATH] [--out DIR] [--push URL]
    tuan harden audit-archive [--dir DIR]
    tuan harden sbom [--out sbom.spdx.json]
    tuan harden crypto-provider
    tuan harden crypto-selftest
    tuan harden network-check --command "..." [--egress-cidr 10.0.0.0/8] [--one-way]
    tuan harden repro-lock [--out requirements.lock] [--verify]
    tuan harden suggest --command "..."

这些命令不声称"国防级/军工认证"; 它们把代码层「可对接、可验证、可审计」的安全能力做实。
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, List, cast

from ..harden import (
    AuditExporter,
    EgressRestrictedNetworkGuard,
    get_crypto_provider,
    available_providers,
    write_sbom,
    generate_sbom,
    generate_lock,
    verify_lock,
)
from ..core.security_bus import SecurityEvent


class _CfgProbe:
    """最小配置探针: 让 harden 审计复用 write_boundary 的 fail-closed 判定。

    ``boundary_enabled`` 调 ``ctx.config(dotted, default)``; 本类用固定值响应,
    供 ``tuan harden`` 校验「开关关闭/开启/类型非法」三种场景与裁决层逻辑一致。
    """

    def __init__(self, value: Any) -> None:
        self._value = value

    def config(self, dotted: str, default: Any = None) -> Any:
        from ..core.write_boundary import FLAG as _WB_FLAG
        if dotted == _WB_FLAG:
            return self._value
        return default


def _resolve_bus_log() -> Path:
    """解析安全事件默认落盘路径: 优先已存在且非空的候选文件, 否则回退到主路径。

    候选顺序 (同一 home 目录下两种文件名都覆盖):
      1. <home>/security-audit.jsonl        (交互式会话默认)
      2. <home>/audit/security_events.jsonl (内核安全插件默认)
    """
    try:
        from ..config import home_dir
        home = Path(home_dir())
    except Exception:
        home = Path.home() / ".tuan"
    candidates = [
        home / "security-audit.jsonl",
        home / "audit" / "security_events.jsonl",
    ]
    for p in candidates:
        try:
            if p.exists() and p.stat().st_size > 0:
                return p
        except OSError:
            continue
    # 都没有则回退到主路径, 由调用方给出明确报错
    return candidates[0]


def _audit_export(args: Any) -> int:
    fmts = []
    for part in (args.format or "jsonl").split(","):
        part = part.strip()
        if part:
            fmts.append(part)
    out_dir = args.out if getattr(args, "out", None) else None
    push = getattr(args, "push", None)
    src = getattr(args, "from_", None) or _resolve_bus_log()

    exporter = AuditExporter(formats=fmts, out_dir=out_dir, push_url=push)
    if not Path(src).exists():
        sys.stderr.write(
            f"[harden] 未找到安全事件源: {src}\n"
            f"        可加 --from PATH 指定 bus JSONL, 或先在一次会话中触发安全事件。\n"
        )
        return 1
    n = exporter.export_file(str(src))
    exporter.close()
    dest = out_dir or "stdout"
    print(f"[harden] 已导出 {n} 条安全事件 -> {dest} (格式: {','.join(fmts)})"
          + (f", 推送: {push}" if push else ""))
    return 0


def _sbom(args: Any) -> int:
    out = getattr(args, "out", None) or "sbom.spdx.json"
    data = generate_sbom()
    path = write_sbom(out)
    print(f"[harden] SBOM 已生成: {path}")
    print(f"         组件数: {len(data['packages'])} (含根组件), 依赖关系: {len(data['relationships'])}")
    print(f"         内容指纹: {__import__('tuan_cli.harden.sbom', fromlist=['sbom_hash']).sbom_hash(data)}")
    return 0


def _crypto_provider(args: Any) -> int:
    avail = available_providers()
    active = get_crypto_provider("auto").name
    print("[harden] 可用密码学后端:")
    for name in ("software", "gmssl", "hsm"):
        mark = "✓" if name in avail else "✗ (依赖缺失)"
        tag = " <- 默认激活" if name == active else ""
        print(f"  - {name:8s} {mark}{tag}")
    print("\n说明: software=本地 AES-GCM(优先)/CTR-HMAC(回退); gmssl=国密 SM4(需 pip install gmssl);")
    print("      hsm=硬件 HSM/PKCS#11(需实体设备与 python-pkcs11)。以上仅为算法/密钥后端可替换,")
    print("      不等同于国密产品认证或等保资质 —— 那是代码之外的合规流程。")
    return 0


def _network_check(args: Any) -> int:
    command = getattr(args, "command", None)
    if not command:
        sys.stderr.write("[harden] 请通过 --command \"...\" 传入待评估命令\n")
        return 1
    cidrs = list(getattr(args, "egress_cidr", None) or [])
    one_way = bool(getattr(args, "one_way", False))
    guard = EgressRestrictedNetworkGuard(egress_cidr_allow=cidrs, one_way_mode=one_way)
    decision = guard.check(command)
    print("[harden] 网络策略:")
    print("  " + str(guard.describe_policy()).replace(", ", ",\n   "))
    print(f"\n[harden] 命令: {command}")
    print(f"  裁决: action={decision.action} risk={decision.risk_level}")
    for r in decision.reasons:
        print(f"   - {r}")
    return 0 if decision.action != "deny" else 0  # 仅展示, 退出码 0


def _repro_lock(args: Any) -> int:
    if getattr(args, "verify", False):
        ok, diff = verify_lock(getattr(args, "out", None) or "requirements.lock")
        if ok:
            print("[harden] 依赖与锁文件一致, 无漂移。")
            return 0
        print("[harden] 检测到依赖漂移:")
        for d in diff:
            print("  - " + d)
        return 1
    path = generate_lock(getattr(args, "out", None) or "requirements.lock")
    print(f"[harden] 可复现锁已生成: {path}")
    return 0


def _status(args: Any) -> int:
    """展示当前加固态势: 加密后端 / 审计落盘 / SBOM / 网络策略。"""
    from ..harden import available_providers, get_crypto_provider
    from ..harden.sbom import generate_sbom

    avail = available_providers()
    active = get_crypto_provider("auto").name
    print("[harden] 加密后端:")
    print(f"  默认激活: {active}")
    for name in ("software", "gmssl", "hsm"):
        mark = "✓ 可用" if name in avail else "✗ 依赖缺失/不适用"
        print(f"  - {name:8s} {mark}")
    print("  (注: hsm 不适用于流式审计日志, 需实体设备且密钥不出卡; 选 hsm 时自动降级 software 并告警)")

    # 审计事件落盘
    try:
        from ..config import home_dir
        home = Path(home_dir())
    except Exception:
        home = Path.home() / ".tuan"
    for cand in (home / "security-audit.jsonl", home / "audit" / "security_events.jsonl"):
        if cand.exists():
            print(f"[harden] 安全事件落盘: {cand} ({cand.stat().st_size} 字节)")
            break
    else:
        print(f"[harden] 安全事件落盘: 暂无 (默认路径: {home}/security-audit.jsonl 或 {home}/audit/security_events.jsonl)")

    # SBOM
    try:
        data = generate_sbom()
        print(f"[harden] SBOM: 可生成, 组件 {len(data['packages'])} 个")
    except Exception as exc:  # noqa: BLE001
        print(f"[harden] SBOM: 生成失败 ({exc})")

    # 网络策略 (尽力读取配置, 失败不阻塞)
    try:
        from ..config import Config
        cfg = Config()
        net = cfg.get("security.network", {}) or {}
        cidrs = net.get("egress_cidr_allow", []) or []
        one_way = bool(net.get("one_way_mode", False))
        print(f"[harden] 网络策略: 出口CIDR白名单={cidrs or '未配置(不限制)'}, 单向模式={one_way}")
    except Exception:
        print("[harden] 网络策略: 未加载到配置 (可用 tuan harden network-check 单独评估)")

    # ------------------------------------------------------------------ 安全基线
    # 把文档里的"建议"变成可执行的态势检查: 关键降级项必须显式告警,
    # 避免"代码有开关、部署没开、文档却说已默认开启"的错觉。
    try:
        from ..config import Config
        from ..sandbox.backends import detect_backends
        cfg = Config()
        sb = cfg.get("sandbox", {}) or {}
        enforce = bool(sb.get("enforce_required", True))
        deny_net = bool((sb.get("resource", {}) or {}).get("deny_network_by_default", False))
        allowed = sb.get("allowed_domains", []) or []
        strong: List[str] = [cast(str, b["name"]) for b in detect_backends()
                  if b.get("available") and b.get("name") != "local"]
        print("[harden] 安全基线:")
        print(f"  - 无强后端时 fail-closed : {'OK 开启' if enforce else '!! 关闭 (会静默降级为裸执行)'}")
        print(f"  - 默认禁网               : {'OK 开启' if deny_net else '!! 关闭 (生产环境建议开启)'}")
        print(f"  - 出网域名白名单         : {allowed or '未配置 (不限制)'}")
        print(f"  - 可用强隔离后端         : {', '.join(strong) if strong else '无 (需隔离的执行将被拒绝)'}")
        issues = []
        if not enforce:
            issues.append("sandbox.enforce_required=false")
        if not deny_net:
            issues.append("sandbox.resource.deny_network_by_default=false")
        if not strong:
            issues.append("无 docker/bwrap/seatbelt 等强隔离后端")
        if issues:
            print("[harden] 基线待加固: " + "; ".join(issues))
            print("         生产/托管部署请在 config.yaml 的 sandbox: 段开启上述项, 并把整个")
            print("         进程放进一次性容器或 VM (见 SECURITY_BASELINE.md)。")
        else:
            print("[harden] 基线检查通过")
    except Exception as exc:  # noqa: BLE001
        print(f"[harden] 安全基线: 检查失败 ({exc})")

    # ------------------------------------------------------------------ E8 schema
    # 把「配置写错但规则表静默失效」变成可见的校验结果 (fail-closed 可观测性)。
    try:
        from ..config import Config
        from ..config.security_schema import validate_security_config
        sec_errors, sec_warnings = validate_security_config(Config())
        print("[harden] 安全配置 schema:")
        if sec_errors:
            for msg in sec_errors:
                print(f"  !! {msg}")
            print(f"  共 {len(sec_errors)} 项阻断性错误 (运行 tuan config validate 查看详情)")
        else:
            print("  结构校验: OK (无静默失效的规则/开关)")
        for msg in sec_warnings:
            print(f"  - {msg}")
    except Exception as exc:  # noqa: BLE001
        print(f"[harden] 安全配置 schema: 检查失败 ({exc})")
    return 0


def _suggest(args: Any) -> int:
    """给出危险命令的安全替代建议 (对接 safe_alternatives 规则库)。

    此前仅注册 argparse 入口但分发落"用法"错误; 现接入已有规则引擎。
    """
    from ..harden.safe_alternatives import suggest_safe_alternatives

    command = getattr(args, "command", None) or ""
    if not command:
        print("用法: tuan harden suggest --command \"<命令文本>\"")
        return 2
    hits = suggest_safe_alternatives(command)
    if not hits:
        print(f"[harden] 未命中安全替代规则: {command!r}")
        print("         (命令在规则库外; 建议人工复核风险后再执行)")
        return 0
    print(f"[harden] {command!r} 的 {len(hits)} 条安全替代建议:")
    for i, it in enumerate(hits, 1):
        print(f"  {i}. [{it['category']}] {it['replacement']}")
        print(f"     —— {it['why']}")
    return 0


def _crypto_selftest(args: Any) -> int:
    """对可用的 CryptoProvider 后端做加解密/HMAC/篡改检测自检。

    此前仅注册 argparse 入口但分发落"用法"错误; 现复用 crypto_provider 后端。
    fail-closed: 任一自检失败即整体失败 (rc=1), 不静默通过。
    """
    from ..harden.crypto_provider import available_providers, get_crypto_provider

    providers = available_providers() or ["software"]
    all_ok = True
    print(f"[harden] 可用 CryptoProvider 后端: {', '.join(providers)}")
    for name in providers:
        try:
            prov = get_crypto_provider(name)
            payload = b"tuan-crypto-selftest-payload-0123456789"
            passphrase = "selftest-passphrase"
            sealed = prov.seal(payload, passphrase)
            opened = prov.open(sealed, passphrase)
            if opened != payload:
                raise AssertionError(f"seal/open 往返不一致: {opened!r} != {payload!r}")
            # HMAC 恒定时间校验
            key = prov.random_token(32).encode()
            mac = prov.hmac_sign(payload, key)
            if not prov.hmac_verify(payload, key, mac):
                raise AssertionError("HMAC 校验失败")
            if prov.hmac_verify(b"tampered", key, mac):
                raise AssertionError("篡改数据竟通过 HMAC 校验")
            # 错误口令必须失败 (fail-closed)
            try:
                prov.open(sealed, "wrong-passphrase")
                raise AssertionError("错误口令未被拒绝")
            except ValueError:
                pass
            print(f"  - {name}: seal/open OK, HMAC OK, 篡改拒绝 OK, 错误口令拒绝 OK")
        except Exception as exc:  # noqa: BLE001
            all_ok = False
            print(f"  - {name}: 自检失败 -> {exc}")
    if not all_ok:
        print("[harden] crypto-selftest: 存在失败后端 (fail-closed)")
        return 1
    print("[harden] crypto-selftest: 全部后端自检通过")
    return 0


def _audit_archive(args: Any) -> int:
    """体检审计导出目录: 统计事件数/严重度分布/轮转/时间跨度/权限。

    此前仅注册 argparse 入口但分发落"用法"错误; 现扫描导出目录,
    让"日志在落盘但没人看"变成可观测的归档态势。
    """
    import glob
    import json
    import os
    from collections import Counter

    out_dir = getattr(args, "dir", None) or os.path.expanduser("~/.tuan/audit-export")
    if not os.path.isdir(out_dir):
        print(f"[harden] 审计导出目录不存在: {out_dir}")
        print("         (运行 `tuan harden audit-export --out <dir>` 生成后重试)")
        return 0
    files = sorted(glob.glob(os.path.join(out_dir, "audit_export.*")))
    if not files:
        print(f"[harden] 审计导出目录为空: {out_dir}")
        return 0
    total = 0
    sev_count: Counter[str] = Counter()
    timestamps: list[float] = []
    sizes: list[int] = []
    for path in files:
        size = os.path.getsize(path)
        sizes.append(size)
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    total += 1
                    try:
                        rec = json.loads(line)
                        sev_count[rec.get("severity", "info")] += 1
                        ts = rec.get("ts") or rec.get("timestamp")
                        if isinstance(ts, (int, float)):
                            timestamps.append(float(ts))
                    except (ValueError, TypeError):
                        sev_count["unparseable"] += 1
        except OSError as exc:  # noqa: PERF203
            print(f"  !! 读取 {path} 失败: {exc}")
    print(f"[harden] 审计归档体检: {out_dir}")
    print(f"  - 文件数        : {len(files)}")
    print(f"  - 事件总数      : {total}")
    if sev_count:
        print(f"  - 严重度分布    : {dict(sorted(sev_count.items()))}")
    if sizes:
        print(f"  - 总大小        : {sum(sizes) / 1024:.1f} KiB")
    if len(timestamps) >= 2:
        span = max(timestamps) - min(timestamps)
        if span >= 86400:
            print(f"  - 时间跨度      : {span / 86400:.1f} 天")
        elif span >= 3600:
            print(f"  - 时间跨度      : {span / 3600:.1f} 小时")
        else:
            print(f"  - 时间跨度      : {span / 60:.1f} 分钟")
    return 0


def cmd_harden(args: Any) -> int:
    cmd = getattr(args, "harden_cmd", None) or "status"
    if cmd == "audit-export":
        return _audit_export(args)
    if cmd == "audit-archive":
        return _audit_archive(args)
    if cmd == "sbom":
        return _sbom(args)
    if cmd == "crypto-provider":
        return _crypto_provider(args)
    if cmd == "crypto-selftest":
        return _crypto_selftest(args)
    if cmd == "network-check":
        return _network_check(args)
    if cmd == "repro-lock":
        return _repro_lock(args)
    if cmd == "suggest":
        return _suggest(args)
    if cmd == "status":
        return _status(args)
    sys.stderr.write(
        "用法: tuan harden <audit-export|audit-archive|sbom|crypto-provider|"
        "crypto-selftest|network-check|repro-lock|suggest|status>\n"
    )
    return 1
