"""E4 回归: 审计关联合并 / 跨会话检测 / 导出轮转 / 历史重放。"""
from __future__ import annotations

import json
import os
import stat
import time
from pathlib import Path

import pytest

from tuan_cli.core.audit_correlation import (
    AuditCorrelator, fingerprint_of,
)
from tuan_cli.core.security_bus import SecurityEvent


# ------------------------------------------------------------------ helpers
def _rec(*, module="security_gate", action="deny", severity="high",
         reason="命中致命红线 (文件系统/OS 级毁灭操作)",
         summary="rm -rf /tmp/build-12345", session="s1", ts=None):
    return type("R", (), {
        "module": module, "action": action, "severity": severity,
        "reasons": [reason], "input_summary": summary,
        "session_id": session, "agent_id": "a1",
        "ts": ts if ts is not None else time.time(),
    })()


# ------------------------------------------------------------------ 指纹
class TestFingerprint:
    def test_same_attack_different_path_same_fingerprint(self):
        a = _rec(summary="rm -rf /tmp/build-12345")
        b = _rec(summary="rm -rf /tmp/build-99999")
        assert fingerprint_of(a) == fingerprint_of(b)

    def test_different_action_different_fingerprint(self):
        assert fingerprint_of(_rec(action="deny")) != fingerprint_of(_rec(action="allow"))

    def test_session_not_part_of_fingerprint(self):
        """跨会话检测的前提: session_id 不能进指纹。"""
        assert fingerprint_of(_rec(session="s1")) == fingerprint_of(_rec(session="s2"))

    def test_noise_normalization_hex_and_digits(self):
        assert fingerprint_of(_rec(summary="curl 0xDEADBEEF 123456")) == \
               fingerprint_of(_rec(summary="curl 0x12345678 987654"))


# ------------------------------------------------------------------ 关联器
class TestCorrelator:
    def test_burst_alert_at_threshold(self):
        c = AuditCorrelator(window_seconds=60, burst_threshold=5)
        alerts = []
        for _ in range(4):
            alerts += c.assess(_rec())
        assert alerts == []
        alerts += c.assess(_rec())
        assert any(a.kind == "burst" for a in alerts)
        burst = next(a for a in alerts if a.kind == "burst")
        assert burst.count >= 5 and burst.severity

    def test_burst_does_not_spam_every_event(self):
        c = AuditCorrelator(window_seconds=60, burst_threshold=3)
        seen = []
        for _ in range(10):
            seen += c.assess(_rec())
        assert sum(1 for a in seen if a.kind == "burst") == 1

    def test_cross_session_detection(self):
        c = AuditCorrelator(window_seconds=60, burst_threshold=99)
        c.assess(_rec(session="s1"))
        alerts = c.assess(_rec(session="s2"))
        assert any(a.kind == "cross_session" for a in alerts)
        a = next(x for x in alerts if x.kind == "cross_session")
        assert set(a.sessions) == {"s1", "s2"}
        assert a.severity == "critical"

    def test_same_session_repeats_are_not_cross_session(self):
        c = AuditCorrelator(window_seconds=60, burst_threshold=99)
        alerts = []
        for _ in range(5):
            alerts += c.assess(_rec(session="s1"))
        assert not any(a.kind == "cross_session" for a in alerts)

    def test_replay_enables_cross_process_cross_session(self):
        """历史重放: 上次进程里出现过的会话也能参与跨会话判定。"""
        old = AuditCorrelator(window_seconds=60, burst_threshold=99)
        old.assess(_rec(session="previous-process"))
        c = AuditCorrelator(window_seconds=60, burst_threshold=99)
        c.replay([_rec(session="previous-process")])
        alerts = c.assess(_rec(session="new-process"))
        assert any(a.kind == "cross_session" for a in alerts)

    def test_replay_does_not_emit_alerts(self):
        c = AuditCorrelator()
        assert c.replay([_rec() for _ in range(20)]) == 20
        assert c.recent_alerts() == []

    def test_severity_escalation(self):
        c = AuditCorrelator(window_seconds=60, burst_threshold=99)
        c.assess(_rec(severity="low"))
        alerts = c.assess(_rec(severity="critical"))
        assert any(a.kind == "severity_escalation" for a in alerts)

    def test_assess_never_raises_on_garbage(self):
        c = AuditCorrelator()
        assert c.assess(None) == []
        assert c.assess(object()) == []

    def test_stats_and_reset(self):
        c = AuditCorrelator(burst_threshold=2)
        c.assess(_rec()); c.assess(_rec())
        st = c.stats()
        assert st["window_events"] == 2 and st["alerts_total"] >= 1
        assert st["by_kind"]["burst"] >= 1
        c.reset()
        assert c.stats()["window_events"] == 0
        assert c.recent_alerts() == []

    def test_window_expiry(self):
        now = [1000.0]
        c = AuditCorrelator(window_seconds=10, burst_threshold=3,
                            now_fn=lambda: now[0])
        for _ in range(3):
            c.assess(_rec(ts=now[0]))
        now[0] += 20
        # 窗口过期后重新累计, 不应立刻再报 burst
        assert c.assess(_rec(ts=now[0])) == []

    def test_bounded_memory(self):
        c = AuditCorrelator(max_window_events=50, max_fingerprints=40)
        for i in range(200):
            c.assess(_rec(summary=f"cmd-{i}", session=f"s{i}"))
        assert c.stats()["window_events"] <= 50
        assert c.stats()["tracked_fingerprints"] <= 40


# ------------------------------------------------------------------ SecurityAuditor 接线
class TestAuditorWiring:
    def _auditor(self, tmp_path):
        from tuan_cli.core.security_auditor import SecurityAuditor
        return SecurityAuditor(home=tmp_path, passphrase="test-pass",
                               session_id="s1")

    def test_record_produces_alert_and_stats_exposes_it(self, tmp_path):
        a = self._auditor(tmp_path)
        for _ in range(6):
            a.record(module="security_gate", action="deny", severity="high",
                     input_summary="rm -rf /tmp/x", reasons=["致命红线"])
        assert a.recent_alerts()
        assert any(x["kind"] == "burst" for x in a.recent_alerts())
        assert "correlation" in a.stats()

    def test_cross_session_after_restart_with_replay(self, tmp_path):
        from tuan_cli.core.security_auditor import SecurityAuditor
        a1 = SecurityAuditor(home=tmp_path, passphrase="test-pass", session_id="s1")
        a1.record(module="m", action="deny", severity="high",
                  input_summary="payload", reasons=["红线"])
        a2 = SecurityAuditor(home=tmp_path, passphrase="test-pass", session_id="s2")
        a2.record(module="m", action="deny", severity="high",
                  input_summary="payload", reasons=["红线"])
        kinds = [x["kind"] for x in a2.recent_alerts()]
        assert "cross_session" in kinds, kinds

    def test_audit_chain_still_intact_with_correlation(self, tmp_path):
        a = self._auditor(tmp_path)
        for _ in range(3):
            a.record(module="m", action="deny", severity="high",
                     input_summary="x", reasons=["r"])
        assert a.verify_integrity().get("ok", a.verify_integrity().get("valid", True)) is not False


# ------------------------------------------------------------------ 导出轮转
class TestAuditExportRotation:
    def _exporter(self, tmp_path, **kw):
        from tuan_cli.harden.audit_export import AuditExporter
        return AuditExporter(formats=["jsonl"], out_dir=str(tmp_path), **kw)

    def _event(self, i):
        return SecurityEvent(event_type="security.command.blocked",
                             timestamp=float(i), payload={"n": i},
                             source="test", severity="high")

    def test_rotation_creates_backups(self, tmp_path):
        ex = self._exporter(tmp_path, max_bytes=300, backup_count=3)
        for i in range(30):
            ex.emit(self._event(i))
        ex.close()
        assert (tmp_path / "audit_export.jsonl").exists()
        assert (tmp_path / "audit_export.jsonl.1").exists()
        assert not (tmp_path / "audit_export.jsonl.4").exists()
        for p in tmp_path.glob("audit_export.jsonl*"):
            lines = [x for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]
            assert all(json.loads(x)["event_type"] for x in lines)

    def test_no_rotation_when_max_bytes_zero(self, tmp_path):
        ex = self._exporter(tmp_path, max_bytes=0)
        for i in range(20):
            ex.emit(self._event(i))
        ex.close()
        assert list(tmp_path.glob("audit_export.jsonl.*")) == []
        assert len((tmp_path / "audit_export.jsonl").read_text().splitlines()) == 20

    def test_backup_count_zero_keeps_only_current(self, tmp_path):
        ex = self._exporter(tmp_path, max_bytes=200, backup_count=0)
        for i in range(20):
            ex.emit(self._event(i))
        ex.close()
        assert list(tmp_path.glob("audit_export.jsonl.*")) == []

    def test_negative_params_rejected(self, tmp_path):
        from tuan_cli.harden.audit_export import AuditExporter
        with pytest.raises(ValueError):
            AuditExporter(out_dir=str(tmp_path), max_bytes=-1)
        with pytest.raises(ValueError):
            AuditExporter(out_dir=str(tmp_path), backup_count=-1)

    def test_export_file_also_rotates(self, tmp_path):
        src = tmp_path / "bus.jsonl"
        with src.open("w", encoding="utf-8") as f:
            for i in range(20):
                f.write(self._event(i).to_json() + "\n")
        ex = self._exporter(tmp_path, max_bytes=250, backup_count=2)
        n = ex.export_file(str(src))
        ex.close()
        assert n == 20
        assert (tmp_path / "audit_export.jsonl.1").exists()

    @pytest.mark.skipif(os.name == "nt", reason="POSIX 权限检查")
    def test_export_file_is_0600(self, tmp_path):
        ex = self._exporter(tmp_path)
        ex.emit(self._event(1))
        ex.close()
        mode = stat.S_IMODE((tmp_path / "audit_export.jsonl").stat().st_mode)
        assert mode & 0o077 == 0, oct(mode)
