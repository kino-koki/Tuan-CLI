"""审计日志后端 —— 记录模型 / 工具 / 权限 / 任务生命周期事件, 支持过滤查询与敏感脱敏。

设计要点 (对标 Claude Code 的审计能力):
- 事件落盘为 JSONL (一行一条), 同时保留进程内环形缓冲供即时查询。
- 落盘前强制脱敏: API Key、token、密码、私钥等敏感字段绝不写明文。
- 通配订阅内核事件总线 ("*"), 不侵入各业务模块; 任何内核事件自动归档。
- 查询支持按类型 / 时间窗 / 关键词过滤, 返回结构化记录 (不暴露已脱敏原文)。
- 异常隔离: 审计写入失败只记日志, 绝不中断 Agent 主循环 (可观测性是"锦上添花")。
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger("tuan_cli.audit")

# 进程内环形缓冲上限: 防止超长会话无限占用内存。
MAX_BUFFER = 2000

# 审计日志轮转: 单文件超过 20MB 归档为 .1, 保留最多 5 个轮转文件。
# 防止审计日志无限增长 (长跑 agent 一天可写数百 MB)。
DEFAULT_ROTATE_BYTES = 20 * 1024 * 1024
DEFAULT_MAX_ROTATED_FILES = 5

# 需要脱敏的字段名。判定用「按分隔符切段后逐段精确匹配」, 不用 endswith:
# 旧的 `low.endswith("key")` 会把 monkey / turkey / donkey / hockey / monkeypatch
# 这类正常字段一律打成 ***, 审计日志就失去了存在意义 (CODE_REVIEW §4.11)。
#
# 两种命中方式:
# - 整名精确命中 (常见直写形式: "apikey" / "token" / "password" …)
# - 复合名末段命中 ("user_api_key" → 末段 "key"; "session_token" → 末段 "token")
#
# 刻意不收录 "session" / "keyid" 等: session_id、key_id 是关联用的标识符,
# 打码会让排障无从下手; 真正的会话凭据 (session_token / cookie) 仍会被末段规则拦下。
_SENSITIVE_EXACT = frozenset({
    "apikey", "accesskey", "secretkey",
    "token", "accesstoken", "refreshtoken", "idtoken", "jwt",
    "secret", "clientsecret",
    "password", "passwd", "pwd",
    "privatekey", "signingkey",
    "authorization", "auth", "bearer",
    "credential", "credentials",
    "cookie", "cookies", "setcookie",
})

_SENSITIVE_LAST_PART = frozenset({
    "key", "keys", "token", "tokens", "secret", "secrets",
    "password", "passwd", "pwd", "credential", "credentials",
    "cookie", "cookies", "authorization", "auth", "bearer",
})

# 分段用的分隔符: 下划线 / 连字符 / 空白 / 点 (如 "x.api.key")
_KEY_SPLIT_RE = re.compile(r"[-_\s.]+")

# 命令行/参数里可能泄露密钥的正则 (值侧兜底脱敏)。
_SENSITIVE_PATTERNS = (
    re.compile(r"(sk-[A-Za-z0-9]{8,})"),                          # OpenAI 风格
    re.compile(r"(AKIA[0-9A-Z]{16})"),                            # AWS
    re.compile(r"([Bb]earer\s+[A-Za-z0-9._-]{12,})"),             # Bearer token
    re.compile(r"([Aa]pi[_-]?[Kk]ey[\"'=:\s]+[A-Za-z0-9._-]{8,})"),
    re.compile(r"([Pp]assword[\"'=:\s]+[^\s\"']{6,})"),
)

_MASK = "***"


def _redact_text(text: str) -> str:
    """对自由文本做兜底脱敏: 命中密钥正则的部分打码。"""
    if not text:
        return text
    for pat in _SENSITIVE_PATTERNS:
        text = pat.sub(lambda m: m.group(1)[:5] + _MASK, text)
    return text


def _is_sensitive_key(key: str) -> bool:
    """判断字段名是否为敏感键。

    整名精确命中, 或按分隔符切段后末段命中。不做子串匹配, 避免误伤
    monkey / turkey / session_id / keyboard 这类正常字段。
    """
    raw = (key or "").strip()
    if not raw:
        return False
    flat = raw.replace("-", "").replace("_", "").replace(" ", "").lower()
    if flat in _SENSITIVE_EXACT or raw.lower() in _SENSITIVE_EXACT:
        return True
    parts = [p for p in _KEY_SPLIT_RE.split(raw) if p]
    if not parts:
        return False
    last = parts[-1].replace("-", "").replace(" ", "").lower()
    return last in _SENSITIVE_LAST_PART


def _redact_value(key: str, value: Any) -> Any:
    """按键名或内容判断是否敏感, 命中则返回脱敏串。"""
    if _is_sensitive_key(key):
        if value in (None, "", _MASK):
            return value
        return _MASK
    # 字符串值做正则兜底 (即便键名不敏感, 内容含密钥也脱敏)
    if isinstance(value, str):
        return _redact_text(value)
    return value


def redact(payload: Dict[str, Any]) -> Dict[str, Any]:
    """递归脱敏一个事件载荷, 返回新的脱敏副本 (不修改原对象)。"""
    if not isinstance(payload, dict):
        return payload
    out: Dict[str, Any] = {}
    for key, value in payload.items():
        if isinstance(value, dict):
            out[key] = redact(value)
        elif isinstance(value, list):
            out[key] = [
                redact(v) if isinstance(v, dict) else _redact_value(key, v)
                for v in value
            ]
        else:
            out[key] = _redact_value(key, value)
    return out


@dataclass
class AuditEvent:
    """一条审计记录。"""
    seq: int
    ts: float
    type: str
    payload: Dict[str, Any]
    raw: Dict[str, Any] = field(default_factory=dict)  # 脱敏前原文 (仅内存, 不落盘)

    def to_line(self) -> str:
        """落盘行: 仅含脱敏后的 payload。"""
        rec = {
            "seq": self.seq,
            "ts": self.ts,
            "iso": datetime.fromtimestamp(self.ts, tz=timezone.utc).isoformat(),
            "type": self.type,
            "payload": self.payload,
        }
        return json.dumps(rec, ensure_ascii=False, default=str)

    @staticmethod
    def from_line(line: str) -> "AuditEvent":
        rec = json.loads(line)
        return AuditEvent(
            seq=rec.get("seq", 0),
            ts=rec.get("ts", 0.0),
            type=rec.get("type", ""),
            payload=rec.get("payload", {}),
        )

    def matches(self, query: "AuditQuery") -> bool:
        return query.match(self)


@dataclass
class AuditQuery:
    """审计查询条件。"""
    types: Tuple[str, ...] = ()
    since: Optional[float] = None
    until: Optional[float] = None
    keyword: str = ""
    limit: int = 0  # >0 时仅返回最早的前 N 条 (0 = 不限)

    def match(self, ev: AuditEvent) -> bool:
        if self.types and ev.type not in self.types:
            return False
        if self.since is not None and ev.ts < self.since:
            return False
        if self.until is not None and ev.ts > self.until:
            return False
        if self.keyword:
            hay = f"{ev.type} {json.dumps(ev.payload, ensure_ascii=False, default=str)}".lower()
            if self.keyword.lower() not in hay:
                return False
        return True


class AuditStore:
    """审计日志存储: JSONL 持久化 + 进程内环形缓冲。"""

    def __init__(
        self,
        home: Path,
        enabled: bool = True,
        persist: bool = True,
        max_bytes: int = DEFAULT_ROTATE_BYTES,
        max_files: int = DEFAULT_MAX_ROTATED_FILES,
    ) -> None:
        self.dir = home / "audit"
        self.enabled = enabled
        self.persist = persist
        self.max_bytes = max(1024, int(max_bytes))
        self.max_files = max(1, int(max_files))
        self._buffer: List[AuditEvent] = []
        self._seq = 0
        self._lock = threading.Lock()
        self._path: Optional[Path] = None
        if self.persist and self.enabled:
            try:
                self.dir.mkdir(parents=True, exist_ok=True)
                self._path = self.dir / "audit.log"
            except OSError as exc:
                log.warning("审计目录创建失败 (降级为仅内存): %s", exc)
                self.persist = False
        # 进程重启后恢复最大 seq: 否则新 seq 1..N 与已落盘旧 seq 碰撞,
        # query() 按 seq 去重会静默吞掉重启后的新事件。
        self._seq = self._max_seq_on_disk()

    def _rotated_paths(self) -> List[Path]:
        """当前日志 + 全部轮转文件路径 (最新在前: 本体, .1, .2 ...)。"""
        if self._path is None:
            return []
        return [self._path] + [
            self._path.with_name(f"{self._path.name}.{i}")
            for i in range(1, self.max_files + 1)
        ]

    def _rotate_if_needed(self) -> None:
        """当前日志超过 max_bytes → 轮转归档。

        需在持锁状态下调用 (log 已持有 _lock)。轮转为标准日志运维:
        本体 → .1 → .2 ... → 最旧的 .N 删除, 保证磁盘占用有界。
        """
        if self._path is None or not self._path.exists():
            return
        try:
            if self._path.stat().st_size < self.max_bytes:
                return
            oldest = self._path.with_name(f"{self._path.name}.{self.max_files}")
            if oldest.exists():
                oldest.unlink()
            for i in range(self.max_files - 1, 0, -1):
                src = self._path.with_name(f"{self._path.name}.{i}")
                if src.exists():
                    src.rename(self._path.with_name(f"{self._path.name}.{i + 1}"))
            self._path.rename(self._path.with_name(f"{self._path.name}.1"))
            log.info("审计日志轮转: %s 超过 %.1fMB, 归档为 .1 (保留 %d 个轮转文件)",
                     self._path.name, self.max_bytes / 1024 / 1024, self.max_files)
        except OSError as exc:
            log.warning("审计日志轮转失败 (已忽略): %s", exc)

    def _max_seq_on_disk(self) -> int:
        """读盘恢复最大 seq (容忍损坏/半行, 覆盖全部轮转文件)。"""
        seq = 0
        if self._path is None:
            return seq
        for p in self._rotated_paths():
            if not p.exists():
                continue
            try:
                with p.open("r", encoding="utf-8") as fh:
                    for line in fh:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            rec = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        s = rec.get("seq")
                        if isinstance(s, int) and s > seq:
                            seq = s
            except OSError:
                pass
        return seq

    # ------------------------------------------------------------- 写入

    def log(self, event_type: str, payload: Dict[str, Any]) -> None:
        """记录一条审计事件 (自动脱敏 + 落盘 + 入缓冲)。"""
        if not self.enabled:
            return
        safe = redact(payload)
        with self._lock:
            self._seq += 1
            ev = AuditEvent(seq=self._seq, ts=time.time(),
                            type=event_type, payload=safe, raw=payload)
            self._buffer.append(ev)
            if len(self._buffer) > MAX_BUFFER:
                self._buffer.pop(0)
            if self.persist and self._path is not None:
                try:
                    with self._path.open("a", encoding="utf-8") as fh:
                        fh.write(ev.to_line() + "\n")
                    self._rotate_if_needed()
                except OSError as exc:  # noqa: BLE001
                    log.warning("审计落盘失败 (已忽略): %s", exc)

    # ------------------------------------------------------------- 查询

    def query(self, query: Optional[AuditQuery] = None) -> List[AuditEvent]:
        """按条件查询审计记录 (先查内存缓冲, 若启用持久化则合并落盘记录)。"""
        q = query or AuditQuery()
        with self._lock:
            buffered = [ev for ev in self._buffer if q.match(ev)]
        # 合并持久化记录 (落盘的可能比缓冲更全, 但缓冲更新); 去重键 (seq, ts)
        seen = {(b.seq, b.ts) for b in buffered}
        if self.persist and self._path is not None:
            for p in self._rotated_paths():
                if not p.exists():
                    continue
                try:
                    with p.open("r", encoding="utf-8") as fh:
                        for line in fh:
                            line = line.strip()
                            if not line:
                                continue
                            try:
                                ev = AuditEvent.from_line(line)
                            except json.JSONDecodeError:
                                continue
                            if q.match(ev) and (ev.seq, ev.ts) not in seen:
                                seen.add((ev.seq, ev.ts))
                                buffered.append(ev)
                except OSError:
                    continue
        buffered.sort(key=lambda e: e.ts)
        if q.limit and q.limit > 0:
            buffered = buffered[:q.limit]
        return buffered

    def recent(self, n: int = 20, types: Tuple[str, ...] = ()) -> List[AuditEvent]:
        q = AuditQuery(types=types) if types else AuditQuery()
        return self.query(q)[-n:]

    def _iter_disk_events(self) -> List[AuditEvent]:
        """读取全部落盘记录 (含轮转文件, 解析失败的行跳过)。"""
        out: List[AuditEvent] = []
        if self.persist and self._path is not None:
            for p in self._rotated_paths():
                if not p.exists():
                    continue
                try:
                    with p.open("r", encoding="utf-8") as fh:
                        for line in fh:
                            line = line.strip()
                            if not line:
                                continue
                            try:
                                out.append(AuditEvent.from_line(line))
                            except json.JSONDecodeError:
                                continue
                except OSError:
                    continue
        return out

    def stats(self) -> Dict[str, Any]:
        """审计统计: 覆盖内存缓冲 + 落盘全量 (此前仅统计缓冲, 落盘后数字失真)。"""
        with self._lock:
            events = list(self._buffer)
            buffered_n = len(self._buffer)
        seen = {e.seq for e in events}
        for ev in self._iter_disk_events():
            if ev.seq not in seen:
                seen.add(ev.seq)
                events.append(ev)
        by_type: Dict[str, int] = {}
        for ev in events:
            by_type[ev.type] = by_type.get(ev.type, 0) + 1
        tss = sorted(e.ts for e in events)
        fmt_iso = lambda t: datetime.fromtimestamp(t, tz=timezone.utc).isoformat()
        return {
            "enabled": self.enabled,
            "persist": self.persist,
            "buffered": buffered_n,
            "total": len(events),
            "by_type": by_type,
            "oldest_iso": fmt_iso(tss[0]) if tss else None,
            "newest_iso": fmt_iso(tss[-1]) if tss else None,
        }

    def export(self, path, fmt: str = "jsonl",
               query: Optional[AuditQuery] = None) -> Dict[str, Any]:
        """导出审计记录到文件 (仅脱敏后 payload, 绝不含 raw 原文)。

        fmt: jsonl (默认, 一行一条) / json (数组) / csv (seq,ts,iso,type,payload_json)
        返回 {"path", "count", "fmt"}; 未知格式抛 ValueError。
        """
        fmt = (fmt or "").lower()
        if fmt not in ("jsonl", "json", "csv"):
            raise ValueError(f"不支持的导出格式: {fmt} (可选 jsonl/json/csv)")
        from tuan_cli.core.atomicio import atomic_write_text
        events = self.query(query)
        target = Path(path)
        if fmt == "csv":
            import csv
            import io
            buf = io.StringIO()
            writer = csv.writer(buf, lineterminator="\n")
            writer.writerow(["seq", "ts", "iso", "type", "payload_json"])
            for ev in events:
                iso = datetime.fromtimestamp(ev.ts, tz=timezone.utc).isoformat()
                writer.writerow([ev.seq, ev.ts, iso, ev.type,
                                 json.dumps(ev.payload, ensure_ascii=False)])
            atomic_write_text(target, buf.getvalue())
        elif fmt == "json":
            records = []
            for ev in events:
                records.append({
                    "seq": ev.seq, "ts": ev.ts,
                    "iso": datetime.fromtimestamp(ev.ts, tz=timezone.utc).isoformat(),
                    "type": ev.type, "payload": ev.payload,
                })
            atomic_write_text(target, json.dumps(records, ensure_ascii=False, indent=2))
        else:
            atomic_write_text(target, "".join(ev.to_line() + "\n" for ev in events))
        return {"path": str(target), "count": len(events), "fmt": fmt}

    def clear_buffer(self) -> None:
        with self._lock:
            self._buffer.clear()

    def close(self) -> None:
        """关闭审计存储: 停止接受新事件并释放缓冲 (幂等)。

        落盘按事件即时写入, 无后台缓冲可 flush; 关闭后 ``log()`` 直接短路,
        避免在已经逃逸对列关张引用后继续追加。
        """
        with self._lock:
            self.enabled = False
            self._buffer.clear()
            self._path = None
