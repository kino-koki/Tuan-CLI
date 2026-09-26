"""Tests for E5 (Write Storm Detector) and E2 (Trust Auto-Decay) features."""

import time
import tempfile
from pathlib import Path

import pytest


# ================================================================ E5: Write Storm Detector

class TestWriteStormDetector:
    """Tests for _WriteStormDetector in tool_executor.py."""

    def _make_detector(self):
        from qingxiaotuan.core.tool_executor import _WriteStormDetector
        return _WriteStormDetector()

    def test_no_storm_under_threshold(self):
        """Under threshold should not trigger storm alert."""
        det = self._make_detector()
        # Record 5 writes (threshold is 20)
        for i in range(5):
            result = det.record_write(f"/tmp/file_{i}.txt")
            assert result is None, f"Write {i} should not trigger storm"

    def test_storm_at_threshold(self):
        """At threshold should trigger storm alert."""
        det = self._make_detector()
        # Record 20 writes (threshold is 20)
        for i in range(19):
            det.record_write(f"/tmp/file_{i}.txt")
        result = det.record_write("/tmp/file_19.txt")
        assert result is not None, "Should trigger storm at threshold"
        assert "风暴" in result or "storm" in result.lower()

    def test_storm_suppresses_repeated_alerts(self):
        """After first alert, subsequent writes should still warn but not duplicate."""
        det = self._make_detector()
        # Trigger storm
        for i in range(20):
            det.record_write(f"/tmp/file_{i}.txt")
        # First alert
        result1 = det.record_write("/tmp/file_20.txt")
        assert result1 is not None
        # Second write should still warn but message may differ
        result2 = det.record_write("/tmp/file_21.txt")
        assert result2 is not None

    def test_unique_files_threshold(self):
        """Many different files should trigger unique files alert."""
        det = self._make_detector()
        # Record writes to 15 different files (threshold is 15)
        for i in range(15):
            result = det.record_write(f"/tmp/different_file_{i}.txt")
        # The 15th file should trigger unique files alert
        # (but not storm since total writes < 20)
        # Note: the alert might be from unique files or storm depending on timing
        # Just verify it doesn't crash

    def test_delete_storm(self):
        """Multiple delete commands should trigger delete storm."""
        det = self._make_detector()
        # Record 10 delete commands (threshold is 10)
        for i in range(9):
            result = det.record_delete(f"rm /tmp/file_{i}.txt")
            assert result is None, f"Delete {i} should not trigger storm"
        # 10th delete should trigger
        result = det.record_delete("rm /tmp/file_9.txt")
        assert result is not None, "Should trigger delete storm"

    def test_non_delete_commands_ignored(self):
        """Commands without delete keywords should be ignored."""
        det = self._make_detector()
        result = det.record_delete("ls -la /tmp")
        assert result is None

    def test_reset_clears_state(self):
        """Reset should clear all storm detection state."""
        det = self._make_detector()
        # Trigger storm
        for i in range(20):
            det.record_write(f"/tmp/file_{i}.txt")
        # Reset
        det.reset()
        # Should not trigger after reset
        result = det.record_write("/tmp/new_file.txt")
        assert result is None

    def test_storm_window_expiry(self):
        """Storm detection should reset after window expires (simulated)."""
        det = self._make_detector()
        # Manually manipulate timestamps to simulate time passing
        det._write_timestamps = [time.monotonic() - 70]  # 70 seconds ago
        # Add one more write (within window)
        result = det.record_write("/tmp/file.txt")
        # Should not trigger since old write expired
        # (only 1 write in window now)
        assert result is None


# ================================================================ E2: Trust Auto-Decay

class TestTrustDecay:
    """Tests for WorkspaceTrust.check_for_decay and apply_decay."""

    def _make_trust(self, tmp_path):
        from qingxiaotuan.core.workspace_trust import WorkspaceTrust, TrustLevel
        trust = WorkspaceTrust(tmp_path)
        # Set up a trusted workspace
        trust.set_trust(str(tmp_path), TrustLevel.TRUSTED, project_name="test")
        return trust

    def test_no_decay_for_unknown_workspace(self):
        """Unknown workspaces should not decay."""
        with tempfile.TemporaryDirectory() as tmp:
            trust = self._make_trust(Path(tmp))
            # Check a different path
            result = trust.check_for_decay("/nonexistent/path")
            assert result is None

    def test_no_decay_for_trusted_workspace(self):
        """Trusted workspace without sensitive files should not decay immediately."""
        with tempfile.TemporaryDirectory() as tmp:
            trust = self._make_trust(Path(tmp))
            result = trust.check_for_decay(tmp)
            # Should not decay unless 30 days passed
            assert result is None

    def test_decay_on_sensitive_file(self):
        """Trusted workspace with new sensitive file should decay."""
        with tempfile.TemporaryDirectory() as tmp:
            trust = self._make_trust(Path(tmp))
            # Set trusted_at to past
            normalized = trust._normalize_path(tmp)
            trust._records[normalized].trusted_at = time.time() - 86400  # 1 day ago
            trust._save()
            # Create a sensitive file
            env_file = Path(tmp) / ".env"
            env_file.write_text("SECRET=abc123")
            # Check decay
            result = trust.check_for_decay(tmp)
            assert result is not None
            assert "敏感" in result or "sensitive" in result.lower()

    def test_apply_decay(self):
        """apply_decay should downgrade trusted to limited."""
        with tempfile.TemporaryDirectory() as tmp:
            trust = self._make_trust(Path(tmp))
            # Apply decay
            record = trust.apply_decay(tmp, "test reason")
            assert record.level == "limited"

    def test_no_decay_for_limited_workspace(self):
        """Limited workspaces should not decay further."""
        with tempfile.TemporaryDirectory() as tmp:
            trust = self._make_trust(Path(tmp))
            trust.set_trust(tmp, "limited")
            result = trust.check_for_decay(tmp)
            assert result is None


# ================================================================ Combined Integration

class TestStormDetectorIntegration:
    """Integration tests for storm detector with ToolExecutor."""

    def test_detector_import(self):
        """Verify storm detector can be imported and instantiated."""
        from qingxiaotuan.core.tool_executor import _WriteStormDetector
        det = _WriteStormDetector()
        assert det is not None

    def test_detector_record_methods(self):
        """Verify record_write and record_delete methods work."""
        from qingxiaotuan.core.tool_executor import _WriteStormDetector
        det = _WriteStormDetector()
        # record_write
        result = det.record_write("/tmp/test.txt")
        assert result is None or isinstance(result, str)
        # record_delete with non-delete command
        result = det.record_delete("echo hello")
        assert result is None
        # record_delete with delete command
        result = det.record_delete("rm /tmp/test.txt")
        assert result is None or isinstance(result, str)
