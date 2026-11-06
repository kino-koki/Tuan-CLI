"""E2 / E5 加固回归: 证明「已实现的安全能力真的接进了主链路」。

背景:
- E2 的 check_for_decay/apply_decay 此前只被测试调用, CLI(cmd_chat) 与
  Web(web/server.trust_status) 都直接读 record.level, 衰减从未生效。
- E2 旧实现把所有扫描异常 `except: pass -> None`, 等于「无法校验就放行」。
- E5 的「不同文件数」按会话累计, 一旦触发就永久告警, 与 60 秒滑动窗口矛盾。
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from tuan_cli.core.workspace_trust import TrustLevel, WorkspaceTrust


# ------------------------------------------------------------------ E2 主链路
class TestTrustDecayWiring:
    def _trusted(self, tmp_path: Path) -> WorkspaceTrust:
        wt = WorkspaceTrust(tmp_path / "home")
        wt.set_trust(str(tmp_path / "ws"), TrustLevel.TRUSTED, project_name="demo")
        return wt

    def test_check_trust_auto_decays_on_new_sensitive_file(self, tmp_path):
        """主链路: 只调 check_trust 就应该降级, 无需外部再调 check_for_decay。"""
        ws = tmp_path / "ws"
        ws.mkdir()
        wt = self._trusted(tmp_path)
        path = str(ws)

        assert wt.check_trust(path) == TrustLevel.TRUSTED
        (ws / ".env").write_text("SECRET=abc", encoding="utf-8")
        # 绕过 2 秒节流, 模拟真实会话中稍后的一次检查
        wt._decay_checked.clear()
        assert wt.check_trust(path) == TrustLevel.LIMITED

    def test_unchanged_workspace_keeps_trust(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        (ws / "main.py").write_text("print(1)\n", encoding="utf-8")
        wt = self._trusted(tmp_path)
        wt._decay_checked.clear()
        # 普通源码改动不应触发衰减 (指纹只看敏感面 + 顶层目录)
        (ws / "main.py").write_text("print(2)\n", encoding="utf-8")
        assert wt.check_trust(str(ws)) == TrustLevel.TRUSTED

    def test_git_config_change_decays(self, tmp_path):
        ws = tmp_path / "ws"
        (ws / ".git").mkdir(parents=True)
        wt = self._trusted(tmp_path)
        (ws / ".git" / "config").write_text("[remote \"origin\"]\n", encoding="utf-8")
        wt._decay_checked.clear()
        assert wt.check_trust(str(ws)) == TrustLevel.LIMITED

    def test_new_top_level_directory_decays(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        wt = self._trusted(tmp_path)
        (ws / "new_pkg").mkdir()
        wt._decay_checked.clear()
        assert wt.check_trust(str(ws)) == TrustLevel.LIMITED

    def test_scan_failure_fails_closed(self, tmp_path):
        """无法校验工作区 -> 降级, 绝不静默当作无变化。"""
        ws = tmp_path / "ws"
        ws.mkdir()
        wt = self._trusted(tmp_path)
        import shutil
        shutil.rmtree(ws)
        wt._decay_checked.clear()
        assert wt.check_trust(str(ws)) == TrustLevel.LIMITED
        info = wt.get_project_info(str(ws))
        assert "fail-closed" in info["decay_reason"]

    def test_legacy_record_without_fingerprint_builds_baseline(self, tmp_path):
        """老版本记录 (无 fingerprint) 只补建基线, 不每次启动都误报降级。"""
        ws = tmp_path / "ws"
        ws.mkdir()
        wt = WorkspaceTrust(tmp_path / "home")
        from tuan_cli.core.workspace_trust import TrustRecord
        normalized = wt._normalize_path(str(ws))
        wt._records[normalized] = TrustRecord(
            path=normalized, level=TrustLevel.TRUSTED,
            trusted_at=time.time(), last_used=time.time(),
        )
        wt._save()
        assert wt.check_trust(str(ws)) == TrustLevel.TRUSTED
        assert wt._records[normalized].fingerprint
        wt._decay_checked.clear()
        assert wt.check_trust(str(ws)) == TrustLevel.TRUSTED

    def test_decay_reason_exposed_to_ui_and_web(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        wt = self._trusted(tmp_path)
        (ws / "id_rsa").write_text("PRIVATE KEY", encoding="utf-8")
        wt._decay_checked.clear()
        info = wt.get_project_info(str(ws))
        assert info["trust_level"] == TrustLevel.LIMITED
        assert info["decay_reason"]
        assert info["decayed_at"] > 0

    def test_reconfirm_restores_trust_and_clears_reason(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        wt = self._trusted(tmp_path)
        (ws / ".env").write_text("A=1", encoding="utf-8")
        wt._decay_checked.clear()
        assert wt.check_trust(str(ws)) == TrustLevel.LIMITED
        wt.set_trust(str(ws), TrustLevel.TRUSTED)
        assert wt.check_trust(str(ws)) == TrustLevel.TRUSTED
        assert wt.get_project_info(str(ws))["decay_reason"] == ""

    def test_time_decay_after_30_days(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        wt = self._trusted(tmp_path)
        normalized = wt._normalize_path(str(ws))
        wt._records[normalized].last_used = time.time() - 31 * 86400
        wt._save()
        wt._decay_checked.clear()
        assert wt.check_trust(str(ws)) == TrustLevel.LIMITED

    def test_limited_and_unknown_are_not_decayed(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        wt = WorkspaceTrust(tmp_path / "home")
        wt.set_trust(str(ws), TrustLevel.LIMITED)
        wt._decay_checked.clear()
        assert wt.check_trust(str(ws)) == TrustLevel.LIMITED
        assert wt.check_trust(str(tmp_path / "never")) == TrustLevel.UNKNOWN

    def test_active_workspace_does_not_time_decay(self, tmp_path):
        """活跃工作区的 last_used 由 check_trust 维护, 不会被误判过期。"""
        ws = tmp_path / "ws"
        ws.mkdir()
        wt = self._trusted(tmp_path)
        normalized = wt._normalize_path(str(ws))
        # 模拟"很久以前确认过, 但一直在用": 每次 check 都会刷新 last_used
        wt._records[normalized].last_used = time.time() - 29 * 86400
        wt._save()
        wt._decay_checked.clear()
        assert wt.check_trust(str(ws)) == TrustLevel.TRUSTED
        assert wt._records[normalized].last_used > time.time() - 5
        # 再推进 2 天: 若没有接线, 累计已超 31 天会误降级
        wt._records[normalized].last_used = time.time() - 29 * 86400
        wt._save()
        wt._decay_checked.clear()
        assert wt.check_trust(str(ws)) == TrustLevel.TRUSTED

    def test_persisted_fields_survive_reload(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        home = tmp_path / "home"
        wt = self._trusted(tmp_path)
        rec = wt._records[wt._normalize_path(str(ws))]
        assert rec.fingerprint
        wt2 = WorkspaceTrust(home)
        assert wt2._records[wt._normalize_path(str(ws))].fingerprint == rec.fingerprint


# ------------------------------------------------------------------ E5 窗口
class TestWriteStormWindow:
    def _det(self):
        from tuan_cli.core.tool_executor import _WriteStormDetector
        return _WriteStormDetector()

    def test_unique_file_count_is_windowed(self, monkeypatch):
        """15 个不同文件触发告警后, 窗口过期应自动恢复 (旧实现会永久告警)。"""
        import tuan_cli.core.tool_executor as te
        now = [1000.0]
        monkeypatch.setattr(te._time, "monotonic", lambda: now[0])
        det = self._det()
        last = None
        for i in range(15):
            last = det.record_write(f"/tmp/f{i}.txt")
        assert last is not None and "不同文件" in last
        # 推进到窗口之外
        now[0] += te._STORM_WINDOW_SECONDS + 1
        assert det.record_write("/tmp/after.txt") is None

    def test_alert_flag_resets_after_window(self, monkeypatch):
        import tuan_cli.core.tool_executor as te
        now = [2000.0]
        monkeypatch.setattr(te._time, "monotonic", lambda: now[0])
        det = self._det()
        for i in range(20):
            det.record_write(f"/tmp/f{i}.txt")
        now[0] += te._STORM_WINDOW_SECONDS + 1
        # 窗口外恢复: 不应再走"继续写操作"的抑制分支
        assert det.record_write("/tmp/after.txt") is None

    def test_message_reports_real_window(self, monkeypatch):
        """旧文案把「写操作次数」误写成「秒数」。"""
        import tuan_cli.core.tool_executor as te
        now = [3000.0]
        monkeypatch.setattr(te._time, "monotonic", lambda: now[0])
        det = self._det()
        msg = None
        for i in range(20):
            msg = det.record_write(f"/tmp/f{i}.txt")
        assert msg is not None
        assert f"{te._STORM_WINDOW_SECONDS:.0f} 秒内" in msg
        assert "20 秒内写操作达 20 次" not in msg

    def test_reset_still_clears_all_state(self, monkeypatch):
        import tuan_cli.core.tool_executor as te
        now = [4000.0]
        monkeypatch.setattr(te._time, "monotonic", lambda: now[0])
        det = self._det()
        for i in range(15):
            det.record_write(f"/tmp/f{i}.txt")
        det.reset()
        assert det._write_events == []
        assert det._written_files == {}
        assert det.record_write("/tmp/new.txt") is None
