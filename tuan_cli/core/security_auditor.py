"""安全审计溯源器 (Security Auditor) —— 每条安全决策带完整 provenance, 审计日志 AEAD 加密落盘。

核心理念:
1. **决策链追溯**: 每条安全决策记录完整链路 —— 谁(来源模块)在什么条件下(输入上下文)
   做了什么决策(action/severity)、基于什么证据(reasons/features)、触发了什么后果。
2. **AEAD 加密落盘**: 审计日志用 AES-GCM 加密后写入磁盘, 防止篡改/泄露。
   密钥由 PBKDF2 从主密码派生, 每条日志独立 nonce, 支持追加写 (每条独立加密)。
3. **防篡改链**: 每条日志包含前一条的 HMAC (类似区块链), 任何篡改都会导致链断裂。
4. **可查询**: 内存中保留最近 N 条明文, 支持按类型/严重度/时间范围/来源查询。
5. **与 SecurityEventBus 集成**: 自动订阅总线事件, 写入审计日志。

与现有模块的关系:
- SecurityEventBus: 实时事件流 (内存 + 明文 JSONL), 本模块在其之上加 AEAD 加密 + provenance
- SecurityGate: 裁决入口, 本模块在其输出上加审计记录
- audit/store.py: 工具调用审计, 本模块是安全决策审计 (更高层级)

用法::

    auditor = SecurityAuditor(
        home=Path("~/.tuan"),
        passphrase="user-master-password",  # 可选, 缺省用设备指纹
    )

    # 记录安全决策 (自动加密落盘)
    record = auditor.record(
        module="security_gate",
        action="deny",
        severity="critical",
        input_summary="rm -rf /tmp/demo",
        reasons=["命中致命红线 (文件系统/OS 级毁灭操作)"],
        context={"trust_level": "trusted", "yolo": False},
    )

    # 查询审计日志
    records = auditor.query(severity="critical", last_n=50)

    # 验证日志完整性 (防篡改)
    integrity = auditor.verify_integrity()
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import struct
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from .security_utils import redact_nested, redact_sensitive
from .audit_correlation import AuditCorrelator

log = logging.getLogger(__name__)


# ============================================================ 审计记录

@dataclass
class AuditRecord:
    """一条安全审计记录 —— 完整 provenance。"""
    seq: int                              # 全局递增序号
    ts: float                             # 时间戳
    module: str                           # 决策来源模块 (security_gate/safety_engine/classifier/...)
    action: str                           # allow / confirm / deny
    severity: str                         # none / low / medium / high / critical
    input_summary: str                    # 输入摘要 (命令/参数/内容, 截断到 500 字符)
    reasons: List[str] = field(default_factory=list)  # 决策理由
    context: Dict[str, Any] = field(default_factory=dict)  # 决策上下文 (trust_level/yolo/...)
    features: Dict[str, Any] = field(default_factory=dict)  # 分类器特征 (如有)
    session_id: str = ""                  # 所属会话
    agent_id: str = ""                    # Agent 标识
    prev_hash: str = ""                   # 前一条记录的 HMAC (防篡改链)
    record_hash: str = ""                 # 本条记录的 HMAC

    def to_dict(self) -> Dict[str, Any]:
        return {
            "seq": self.seq, "ts": self.ts, "module": self.module,
            "action": self.action, "severity": self.severity,
            "input_summary": self.input_summary, "reasons": self.reasons,
            "context": self.context, "features": self.features,
            "session_id": self.session_id, "agent_id": self.agent_id,
            "prev_hash": self.prev_hash, "record_hash": self.record_hash,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "AuditRecord":
        return cls(
            seq=d.get("seq", 0), ts=d.get("ts", 0.0),
            module=d.get("module", ""), action=d.get("action", ""),
            severity=d.get("severity", ""),
            input_summary=d.get("input_summary", ""),
            reasons=d.get("reasons", []),
            context=d.get("context", {}),
            features=d.get("features", {}),
            session_id=d.get("session_id", ""),
            agent_id=d.get("agent_id", ""),
            prev_hash=d.get("prev_hash", ""),
            record_hash=d.get("record_hash", ""),
        )

    def compute_hash(self, key: bytes) -> str:
        """计算本条记录的 HMAC (不含 record_hash 字段本身)。"""
        payload = {
            "seq": self.seq, "ts": self.ts, "module": self.module,
            "action": self.action, "severity": self.severity,
            "input_summary": self.input_summary, "reasons": self.reasons,
            "context": self.context, "features": self.features,
            "session_id": self.session_id, "agent_id": self.agent_id,
            "prev_hash": self.prev_hash,
        }
        data = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()
        return hmac.new(key, data, hashlib.sha256).hexdigest()


# ============================================================ AEAD 加密层

# AEAD 加密层已下沉到 harden.crypto_provider 的可插拔 CryptoProvider
# (SoftwareProvider: AES-GCM 优先/CTR+HMAC 回退; GmsslProvider: 国密 SM4; HsmProvider: 硬件)。
# SecurityAuditor 通过 get_crypto_provider() 选后端, seal_raw/open_raw 与旧 _AeadCrypto 字节级兼容。


# =========================================================== SecurityAuditor

# 模块级重入深度 (跨实例共享): 多个 auditor 实例会订阅**同一个全局总线**,
# A 实例的关联告警 → bus.emit → B 实例.record → B 的关联告警 → A.record …
# 会形成**跨实例**自循环。per-instance 的 threadlocal 拦不住这种链
# (每个新实例的 depth 都从 0 起算), 故改为**模块级**共享: 任意线程在
# 任意实例的 record() 里时, 其它实例的重入只记证据、不再触发关联分析。
_AUDIT_REENTRANT = threading.local()


class SecurityAuditor:
    """安全审计溯源器 —— AEAD 加密审计日志 + 防篡改链 + 完整 provenance。"""

    # 内存中保留最近 N 条明文记录 (查询用)
    _IN_MEMORY_LIMIT = 2000

    def __init__(
        self,
        home: Optional[Path] = None,
        passphrase: Optional[str] = None,
        session_id: str = "",
        agent_id: str = "",
        crypto_provider: str = "software",
    ):
        self._home = Path(home) if home else Path.home() / ".tuan"
        self._session_id = session_id
        self._agent_id = agent_id
        self._seq_counter = 0
        self._prev_hash = ""
        # RLock 而非 Lock: record() → _publish_correlation_alerts() → bus.emit()
        # → _on_security_event() → record() 是同线程重入路径, 非重入锁会死锁。
        self._lock = threading.RLock()

        # 重入深度守卫: 见模块级 _AUDIT_REENTRANT (跨实例共享 —— 多实例订阅
        # 同一全局总线时, per-instance 守卫拦不住跨实例自循环)。
        self._reentrant_depth = threading.local()

        # 内存缓冲 (最近 N 条明文, 查询用)
        self._buffer: List[AuditRecord] = []

        # E4: 审计关联合并 / 跨会话异常检测 (纯观测, 不参与裁决)
        self._correlator = AuditCorrelator()

        # 密钥派生 (用于防篡改链的 HMAC, 与加密后端共用同一主密钥)
        self._crypto_key = self._derive_key(passphrase)

        # 可插拔加密后端: 默认 software (AES-GCM/CTR-HMAC); gmssl=国密 SM4; hsm=硬件(不适用流式日志时降级)
        # seal_raw/open_raw 与旧 _AeadCrypto 字节级兼容, 既有审计日志仍可读。
        self._provider = self._resolve_provider(crypto_provider)

        # 审计日志路径
        self._log_dir = self._home / "audit"
        self._log_dir.mkdir(parents=True, exist_ok=True)
        self._chmod_600(self._log_dir)
        self._log_file = self._log_dir / "security_audit.aead"
        # 持久写句柄: 避免每条审计记录都 open/close (高并发审计时的系统调用开销)。
        # 惰性打开; 写失败时关闭并回落到逐条打开。
        self._log_fh = None
        self._last_fsync = 0.0

        # 加载已有记录的序号和 prev_hash
        self._load_existing()
        # E4: 历史重放 -> 跨会话检测能跨越进程重启, 而不只限于本次运行
        try:
            self._correlator.replay(list(self._buffer))
        except Exception as exc:  # noqa: BLE001
            log.warning("审计关联历史重放失败: %s", exc)

    @staticmethod
    def _resolve_provider(name: str) -> Any:
        """解析加密后端; 依赖缺失或不适用时降级到 software 并明确告警 (绝不静默)。"""
        from ..harden.crypto_provider import get_crypto_provider
        try:
            return get_crypto_provider(name)
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "审计加密后端 %r 不可用 (%s); 降级到 software 后端。", name, exc
            )
            return get_crypto_provider("software")

    @property
    def algorithm(self) -> str:
        """当前加密后端名 + 算法, 如 'software/aes-gcm' / 'gmssl/sm4-ctr-hmac-sm3'。"""
        return f"{self._provider.name}/{self._provider.algorithm}"

    @staticmethod
    def _chmod_600(path: Any) -> None:
        """收紧审计目录/文件权限 (POSIX 0600; Windows 上尽力而为, 失败静默)。"""
        try:
            if os.name == "nt":
                import stat
                if hasattr(os.stat(path), "st_attr"):
                    return  # 尊重平台既有 ACL
                os.chmod(path, stat.S_IREAD | stat.S_IWRITE)
            else:
                os.chmod(path, 0o600)
        except OSError:
            pass

    def _derive_key(self, passphrase: Optional[str]) -> bytes:
        """从密码派生加密密钥。"""
        if passphrase:
            salt = b"tuan-security-auditor-v1"
            return hashlib.pbkdf2_hmac("sha256", passphrase.encode(), salt, 100000)
        # 无密码时用设备指纹 (hostname + username + home 路径)。
        # 注意: `hasattr(os, "getlogin")` 为 True 不代表能调 —— 无控制终端的
        # CI / 容器 / systemd 服务里 os.getlogin() 会抛 OSError, 旧实现因此让
        # 整个审计器 (含 E4 关联层) 初始化失败。这里只作为 best-effort 输入。
        try:
            user = os.getlogin()
        except (OSError, AttributeError):
            user = (os.environ.get("USER") or os.environ.get("USERNAME")
                    or os.environ.get("LOGNAME") or "unknown")
        try:
            host = os.uname().nodename  # type: ignore[attr-defined]
        except (AttributeError, OSError):
            host = (os.environ.get("COMPUTERNAME")
                    or os.environ.get("HOSTNAME") or "unknown")
        # 指纹格式保持与旧实现完全一致: 若加入 home 路径, 所有此前用默认
        # 设备指纹加密的审计日志将永久无法解密 (破坏性变更, 绝不这么做)。
        fingerprint = f"{user}@{host}"
        return hashlib.pbkdf2_hmac("sha256", fingerprint.encode(), b"tuan-audit-device", 100000)

    def _load_existing(self) -> None:
        """加载已有审计日志, 恢复序号和 prev_hash。"""
        if not self._log_file.exists():
            return
        try:
            with open(self._log_file, "rb") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        raw = base64.b64decode(line)
                        plaintext = self._provider.open_raw(raw, self._crypto_key)
                        data = json.loads(plaintext)
                        rec = AuditRecord.from_dict(data)
                        if rec.seq > self._seq_counter:
                            self._seq_counter = rec.seq
                        self._prev_hash = rec.record_hash or ""
                        # 保留最近 N 条在内存
                        self._buffer.append(rec)
                        if len(self._buffer) > self._IN_MEMORY_LIMIT:
                            self._buffer = self._buffer[-self._IN_MEMORY_LIMIT:]
                    except Exception as exc:  # noqa: BLE001 - 单行损坏跳过, 不中断恢复
                        log.warning("审计恢复: 跳过无法解析的记录行: %s", exc)
                        continue
        except Exception as exc:
            log.warning("审计日志恢复失败, 以当前状态继续: %s", exc)

    # ---------------------------------------------------------- 写入

    def record(
        self,
        module: str,
        action: str,
        severity: str,
        input_summary: str,
        reasons: Optional[List[str]] = None,
        context: Optional[Dict[str, Any]] = None,
        features: Optional[Dict[str, Any]] = None,
    ) -> AuditRecord:
        """记录一条安全决策, AEAD 加密落盘, 返回记录。"""
        # 同线程重入守卫: 计数当前线程在 record 里的嵌套深度。
        # 最外层 (depth==1) 才做关联分析并 emit; 重入层 (depth>1, 来自
        # 自己总线订阅的回调) 跳过关联分析, 从源头切断 record→emit→
        # _on_security_event→record 的自循环。
        # 跨实例重入守卫: 计数当前线程在 record 里的嵌套深度 (模块级共享 ——
        # 多个 auditor 实例订阅同一全局总线时, per-instance 守卫拦不住
        # A 实例的关联告警触发 B 实例 record 的跨实例自循环)。
        depth = getattr(_AUDIT_REENTRANT, "n", 0) + 1
        _AUDIT_REENTRANT.n = depth
        try:
            return self._record_impl(
                module, action, severity, input_summary,
                reasons, context, features, do_correlation=(depth == 1),
            )
        finally:
            _AUDIT_REENTRANT.n = depth - 1

    def _record_impl(
        self,
        module: str,
        action: str,
        severity: str,
        input_summary: str,
        reasons: Optional[List[str]] = None,
        context: Optional[Dict[str, Any]] = None,
        features: Optional[Dict[str, Any]] = None,
        do_correlation: bool = True,
    ) -> AuditRecord:
        """record 的实际实现 (与公开 record 分离以便重入守卫包裹)。"""
        with self._lock:
            self._seq_counter += 1
            rec = AuditRecord(
                seq=self._seq_counter,
                ts=time.time(),
                module=module,
                action=action,
                severity=severity,
                input_summary=redact_sensitive(input_summary)[:500],
                reasons=[redact_sensitive(r) for r in (reasons or [])],
                context=redact_nested(context or {}),
                features=redact_nested(features or {}),
                session_id=self._session_id,
                agent_id=self._agent_id,
                prev_hash=self._prev_hash,
            )

            # 计算本条 HMAC (用于下一条的 prev_hash)
            rec.record_hash = rec.compute_hash(self._crypto_key)
            self._prev_hash = rec.record_hash

            # 内存缓冲
            self._buffer.append(rec)
            if len(self._buffer) > self._IN_MEMORY_LIMIT:
                self._buffer = self._buffer[-self._IN_MEMORY_LIMIT:]

            # AEAD 加密落盘
            self._append_encrypted(rec)

            # E4: 关联分析放在写盘之后、且整体 try/except —— 观测层绝不能
            # 影响审计写入或上游安全裁决。告警只发到已存在的全局事件总线。
            # do_correlation=False (同线程重入层) 时跳过, 切断自循环递归。
            if do_correlation:
                try:
                    alerts = self._correlator.assess(rec)
                    if alerts:
                        self._publish_correlation_alerts(alerts)
                except Exception as exc:  # noqa: BLE001
                    log.warning("审计关联失败 (不影响裁决): %s", exc)

            return rec

    def _append_encrypted(self, rec: AuditRecord) -> None:
        """AEAD 加密并追加写入审计日志。"""
        try:
            data = json.dumps(rec.to_dict(), ensure_ascii=False).encode()
            encrypted = self._provider.seal_raw(data, self._crypto_key)
            line = base64.b64encode(encrypted) + b"\n"
            fh = self._log_fh
            if fh is None:
                created = not self._log_file.exists()
                fh = open(self._log_file, "ab")
                self._log_fh = fh
                if created:
                    self._chmod_600(self._log_file)
            fh.write(line)
            fh.flush()
            # fsync 降频 (5s): write+flush 已满足「进程退出前已落盘」; 逐条
            # fsync 在慢盘上会把审计密集场景拖过超时线 (实测)。
            now = time.time()
            if now - self._last_fsync > 5.0:
                os.fsync(fh.fileno())
                self._last_fsync = now
        except Exception as exc:
            # 写失败: 关闭持久句柄 (下次写入重新打开), 不让坏句柄卡死审计链。
            self._close_log_fh()
            log.warning("审计日志写入失败: %s", exc)

    def _close_log_fh(self) -> None:
        """关闭持久审计写句柄 (写失败/实例清理时)。"""
        fh, self._log_fh = self._log_fh, None
        try:
            if fh is not None:
                fh.close()
        except Exception as exc:
            log.debug("审计日志句柄关闭失败: %s", exc)

    @staticmethod
    def _publish_correlation_alerts(alerts: List[Any]) -> None:
        """把聚合告警发到**已存在**的全局事件总线 (不主动创建, 避免副作用)。"""
        try:
            from . import security_bus
            bus = getattr(security_bus, "_global_bus", None)
            if bus is None:
                return
            for a in alerts:
                bus.emit(security_bus.SecurityEvent(
                    event_type="security.correlation",
                    timestamp=a.last_ts,
                    payload=a.to_dict(),
                    source="audit_correlator",
                    severity=a.severity,
                ))
        except Exception as exc:  # noqa: BLE001
            log.warning("关联告警推送失败 (不影响裁决): %s", exc)

    # ---------------------------------------------------------- E4 关联查询

    def recent_alerts(self, limit: int = 50) -> List[Dict[str, Any]]:
        """最近的聚合告警 (给 `tuan harden status` / SIEM 导出消费)。"""
        return [a.to_dict() for a in self._correlator.recent_alerts(limit)]

    def correlation_stats(self) -> Dict[str, Any]:
        return self._correlator.stats()

    # ---------------------------------------------------------- 查询

    def query(
        self,
        *,
        module: Optional[str] = None,
        action: Optional[str] = None,
        severity: Optional[str] = None,
        since: Optional[float] = None,
        until: Optional[float] = None,
        last_n: int = 100,
    ) -> List[AuditRecord]:
        """查询审计记录 (从内存缓冲)。"""
        with self._lock:
            results = list(self._buffer)

        if module:
            results = [r for r in results if r.module == module]
        if action:
            results = [r for r in results if r.action == action]
        if severity:
            results = [r for r in results if r.severity == severity]
        if since:
            results = [r for r in results if r.ts >= since]
        if until:
            results = [r for r in results if r.ts <= until]

        return results[-last_n:]

    def count(self, *, severity: Optional[str] = None) -> int:
        """统计记录数。"""
        with self._lock:
            if severity:
                return sum(1 for r in self._buffer if r.severity == severity)
            return len(self._buffer)

    def stats(self) -> Dict[str, Any]:
        """审计统计。"""
        with self._lock:
            records = list(self._buffer)
        actions: Dict[str, int] = {}
        severities: Dict[str, int] = {}
        modules: Dict[str, int] = {}
        for r in records:
            actions[r.action] = actions.get(r.action, 0) + 1
            severities[r.severity] = severities.get(r.severity, 0) + 1
            modules[r.module] = modules.get(r.module, 0) + 1
        return {
            "total": len(records),
            "by_action": actions,
            "by_severity": severities,
            "by_module": modules,
            "algorithm": self.algorithm,
            "log_file": str(self._log_file),
            "correlation": self._correlator.stats(),
        }

    # ---------------------------------------------------------- 完整性验证

    def verify_integrity(self) -> Dict[str, Any]:
        """验证审计日志的防篡改链完整性 (全量磁盘重放, 不依赖内存缓冲)。

        逐条从磁盘解密重放: 每条记录的 prev_hash 必须等于前一条的 record_hash,
        且每条记录的 record_hash 必须与其内容匹配。任何一条无法解密即判定损坏。
        """
        records: List[AuditRecord] = []
        try:
            with open(self._log_file, "rb") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        raw = base64.b64decode(line)
                        plaintext = self._provider.open_raw(raw, self._crypto_key)
                        data = json.loads(plaintext)
                        records.append(AuditRecord.from_dict(data))
                    except Exception as exc:  # noqa: BLE001
                        log.warning("审计链校验: 第 %d 条记录无法解密 (文件损坏或被篡改): %s",
                                    len(records) + 1, exc)
                        return {
                            "valid": False,
                            "checked": len(records),
                            "message": f"存在无法解密的记录 (第 {len(records) + 1} 条, 文件损坏或被篡改)",
                        }
        except OSError as exc:
            return {"valid": False, "checked": 0, "message": f"审计日志不可读: {exc}"}

        if not records:
            return {"valid": True, "checked": 0, "message": "审计日志为空"}

        for i, rec in enumerate(records):
            expected = rec.compute_hash(self._crypto_key)
            if rec.record_hash != expected:
                return {
                    "valid": False,
                    "checked": i + 1,
                    "broken_at_seq": rec.seq,
                    "message": f"记录 seq={rec.seq} 内容哈希不匹配 (被篡改)",
                }
            if i > 0 and rec.prev_hash != records[i - 1].record_hash:
                return {
                    "valid": False,
                    "checked": i + 1,
                    "broken_at_seq": rec.seq,
                    "message": f"防篡改链在 seq={rec.seq} 处断裂",
                }

        return {
            "valid": True,
            "checked": len(records),
            "message": f"全部 {len(records)} 条记录完整性校验通过",
        }

    # ---------------------------------------------------------- 导出

    def export_markdown(self, last_n: int = 50) -> str:
        """导出为 Markdown 格式的审计报告。"""
        records = self.query(last_n=last_n)
        lines = [
            "# 安全审计报告",
            "",
            f"- 算法: {self.algorithm}",
            f"- 总记录数: {self.count()}",
            f"- 本报告包含最近 {len(records)} 条记录",
            "",
        ]

        # 按严重度分组
        by_severity: Dict[str, List[AuditRecord]] = {}
        for r in records:
            by_severity.setdefault(r.severity, []).append(r)

        for sev in ["critical", "high", "medium", "low", "none"]:
            recs = by_severity.get(sev, [])
            if not recs:
                continue
            lines.append(f"## {sev.upper()} ({len(recs)} 条)")
            lines.append("")
            for r in recs:
                ts_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(r.ts))
                lines.append(f"### [{ts_str}] {r.module} → {r.action}")
                lines.append(f"- 输入: `{r.input_summary[:200]}`")
                if r.reasons:
                    lines.append(f"- 理由: {'; '.join(r.reasons[:3])}")
                if r.context:
                    lines.append(f"- 上下文: {json.dumps(r.context, ensure_ascii=False)[:200]}")
                lines.append("")

        return "\n".join(lines)

    def export_json(self, last_n: int = 100) -> str:
        """导出为 JSON 格式。"""
        records = self.query(last_n=last_n)
        return json.dumps(
            {"stats": self.stats(), "records": [r.to_dict() for r in records]},
            ensure_ascii=False, indent=2,
        )

    # ---------------------------------------------------------- 与 SecurityEventBus 集成

    def subscribe_bus(self, bus: Any) -> None:
        """订阅 SecurityEventBus, 自动将安全事件写入审计日志。"""
        def _on_security_event(event: Any) -> None:
            # 映射 SecurityEvent → AuditRecord
            severity_map = {
                "critical": "critical", "high": "high",
                "medium": "medium", "low": "low", "info": "none",
            }
            action_map = {
                "security.command.blocked": "deny",
                "security.command.allowed": "allow",
                "security.command.confirmed": "confirm",
                "security.redline.hit": "deny",
                "security.redline.hard_hit": "deny",
                "security.network.blocked": "deny",
                "security.network.confirmed": "confirm",
                "security.mcp.injection": "deny",
                "security.classifier.deny": "deny",
                "security.classifier.confirm": "confirm",
                "security.sandbox.blocked": "deny",
                "security.sandbox.isolated": "isolate",
                "security.sandbox.confirmed": "confirm",
            }
            self.record(
                module=event.source or "security_bus",
                action=action_map.get(event.event_type, "allow"),
                severity=severity_map.get(event.severity, "none"),
                input_summary=str(event.payload.get("command", ""))[:500],
                reasons=[event.payload.get("reason", "")] if event.payload.get("reason") else [],
                context={"event_type": event.event_type, "bus_timestamp": event.timestamp},
            )

        bus.on("*", _on_security_event)
        log.debug("SecurityAuditor 已订阅 SecurityEventBus")
