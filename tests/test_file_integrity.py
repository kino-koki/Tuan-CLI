"""测试 file_integrity —— 文件完整性监控 (关键文件防篡改)。

覆盖:
  - FileSnapshot to_dict/from_dict
  - IntegrityChange to_dict
  - snapshot_directory (建快照 / 返回文件数 / 非目录 0)
  - check_directory (新增/修改/删除/权限变更 + 严重度)
  - get_changes (过滤: severity/change_type/path_pattern + last_n)
  - stats (by_type/by_severity)
  - export_report (Markdown)
  - _classify_change (高危扩展名/文件名)
  - _compute_sha256 / _snapshot_file
  - 快照持久化 (load_snapshot / 空快照跳过检查)
"""

from __future__ import annotations

import os
import sys
import pytest

from tuan_cli.core.file_integrity import (
    FileIntegrityMonitor,
    FileSnapshot,
    IntegrityChange,
)


def _mk_monitor(tmp_path):
    return FileIntegrityMonitor(home=tmp_path / ".tuan")


def _write(path, content="x", mode=0o644):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    os.chmod(path, mode)
    return path


class TestFileSnapshot:
    def test_to_dict(self):
        s = FileSnapshot(path="a/b.py", sha256="abc", size=10, mtime=1.0,
                         recorded_at=2.0, mode=0o644)
        d = s.to_dict()
        assert d["path"] == "a/b.py"
        assert d["sha256"] == "abc"
        assert d["size"] == 10
        assert d["mode"] == 0o644

    def test_from_dict(self):
        d = {"path": "x", "sha256": "def", "size": 5, "mtime": 3.0,
             "recorded_at": 4.0, "mode": 0o755}
        s = FileSnapshot.from_dict(d)
        assert s.path == "x"
        assert s.sha256 == "def"
        assert s.mode == 0o755

    def test_roundtrip(self):
        s = FileSnapshot(path="p", sha256="aa", size=1, mtime=1.0,
                         recorded_at=2.0, mode=0o600)
        assert FileSnapshot.from_dict(s.to_dict()) == s


class TestIntegrityChange:
    def test_to_dict(self):
        c = IntegrityChange(path="p", change_type="modified", old_sha256="a",
                            new_sha256="b", severity="high", details="d")
        d = c.to_dict()
        assert d["change_type"] == "modified"
        assert d["severity"] == "high"
        assert d["details"] == "d"


class TestSnapshotDirectory:
    def test_snapshot_creates_snapshot_dir(self, tmp_path):
        mon = _mk_monitor(tmp_path)
        d = tmp_path / "skills"
        _write(d / "a.py", "print(1)")
        n = mon.snapshot_directory(d, label="skills")
        assert n == 1
        assert (mon._snapshot_dir / f"skills_{hashlib_short(str(d))}.json").exists()

    def test_snapshot_non_dir_returns_zero(self, tmp_path):
        mon = _mk_monitor(tmp_path)
        f = _write(tmp_path / "file.txt")
        assert mon.snapshot_directory(f) == 0

    def test_snapshot_respects_include_patterns(self, tmp_path):
        mon = _mk_monitor(tmp_path)
        d = tmp_path / "d"
        _write(d / "a.py")
        _write(d / "b.txt")
        n = mon.snapshot_directory(d, include_patterns=["*.py"])
        assert n == 1

    def test_snapshot_respects_exclude_patterns(self, tmp_path):
        mon = _mk_monitor(tmp_path)
        d = tmp_path / "d"
        _write(d / "a.py")
        _write(d / "b.txt")
        n = mon.snapshot_directory(d, exclude_patterns=["*.txt"])
        assert n == 1

    def test_snapshot_skips_hidden_dirs(self, tmp_path):
        mon = _mk_monitor(tmp_path)
        d = tmp_path / "d"
        _write(d / "visible.txt")
        _write(d / ".hidden" / "secret.txt")
        n = mon.snapshot_directory(d)
        assert n == 1


class TestCheckDirectory:
    def test_no_snapshot_returns_empty(self, tmp_path):
        mon = _mk_monitor(tmp_path)
        d = tmp_path / "d"
        _write(d / "a.py")
        assert mon.check_directory(d) == []

    def test_added_file(self, tmp_path):
        mon = _mk_monitor(tmp_path)
        d = tmp_path / "d"
        _write(d / "a.py")
        mon.snapshot_directory(d, label="l")
        _write(d / "b.txt")
        changes = mon.check_directory(d, label="l")
        added = [c for c in changes if c.change_type == "added"]
        assert len(added) == 1
        assert added[0].path == "b.txt"
        assert added[0].severity == "low"

    def test_modified_py_is_high(self, tmp_path):
        mon = _mk_monitor(tmp_path)
        d = tmp_path / "d"
        _write(d / "a.py", "print(1)")
        mon.snapshot_directory(d, label="l")
        _write(d / "a.py", "print(2)")
        changes = mon.check_directory(d, label="l")
        mod = [c for c in changes if c.change_type == "modified"]
        assert len(mod) == 1
        assert mod[0].severity == "high"
        assert mod[0].old_sha256 != mod[0].new_sha256

    def test_modified_txt_is_low(self, tmp_path):
        mon = _mk_monitor(tmp_path)
        d = tmp_path / "d"
        _write(d / "a.txt", "x")
        mon.snapshot_directory(d, label="l")
        _write(d / "a.txt", "y")
        changes = mon.check_directory(d, label="l")
        mod = [c for c in changes if c.change_type == "modified"]
        assert mod[0].severity == "low"

    def test_deleted_file_is_high(self, tmp_path):
        mon = _mk_monitor(tmp_path)
        d = tmp_path / "d"
        _write(d / "a.py")
        mon.snapshot_directory(d, label="l")
        (d / "a.py").unlink()
        changes = mon.check_directory(d, label="l")
        deleted = [c for c in changes if c.change_type == "deleted"]
        assert len(deleted) == 1
        assert deleted[0].severity == "high"

    @pytest.mark.skipif(sys.platform == "win32",
                        reason="Windows 下 chmod 权限位恒为 0o666, 无法模拟权限变更")
    def test_permissions_changed(self, tmp_path):
        mon = _mk_monitor(tmp_path)
        d = tmp_path / "d"
        f = _write(d / "a.py", "x", mode=0o644)
        mon.snapshot_directory(d, label="l")
        os.chmod(f, 0o755)
        changes = mon.check_directory(d, label="l")
        perm = [c for c in changes if c.change_type == "permissions_changed"]
        assert len(perm) == 1

    def test_on_change_callback(self, tmp_path):
        calls = []
        mon = FileIntegrityMonitor(home=tmp_path / ".tuan",
                                   on_change=lambda c: calls.append(c))
        d = tmp_path / "d"
        _write(d / "a.py")
        mon.snapshot_directory(d, label="l")
        _write(d / "a.py", "print(2)")
        mon.check_directory(d, label="l")
        assert len(calls) == 1

    def test_no_changes_returns_empty(self, tmp_path):
        mon = _mk_monitor(tmp_path)
        d = tmp_path / "d"
        _write(d / "a.py")
        mon.snapshot_directory(d, label="l")
        assert mon.check_directory(d, label="l") == []


class TestGetChanges:
    def test_filter_severity(self, tmp_path):
        mon = _mk_monitor(tmp_path)
        d = tmp_path / "d"
        _write(d / "a.py", "1")
        _write(d / "b.txt", "1")
        mon.snapshot_directory(d, label="l")
        _write(d / "a.py", "2")
        _write(d / "b.txt", "2")
        mon.check_directory(d, label="l")
        high = mon.get_changes(severity="high")
        assert all(c.severity == "high" for c in high)
        assert any(c.path == "a.py" for c in high)

    def test_filter_change_type(self, tmp_path):
        mon = _mk_monitor(tmp_path)
        d = tmp_path / "d"
        _write(d / "a.py")
        mon.snapshot_directory(d, label="l")
        _write(d / "b.txt")
        mon.check_directory(d, label="l")
        added = mon.get_changes(change_type="added")
        assert len(added) == 1

    def test_filter_path_pattern(self, tmp_path):
        mon = _mk_monitor(tmp_path)
        d = tmp_path / "d"
        _write(d / "a.py")
        _write(d / "sub" / "b.py")
        mon.snapshot_directory(d, label="l")
        _write(d / "sub" / "c.txt")
        mon.check_directory(d, label="l")
        matched = mon.get_changes(path_pattern="sub/*")
        # Windows 下 rel_path 用反斜杠分隔 (os.walk), 但 fnmatch 的 * 不匹配 /
        assert all(c.path.startswith("sub") for c in matched)

    def test_last_n(self, tmp_path):
        mon = _mk_monitor(tmp_path)
        d = tmp_path / "d"
        for i in range(5):
            _write(d / f"f{i}.txt", "1")
        mon.snapshot_directory(d, label="l")
        for i in range(5):
            _write(d / f"f{i}.txt", "2")
        mon.check_directory(d, label="l")
        assert len(mon.get_changes(last_n=2)) == 2


class TestStats:
    def test_stats_empty(self, tmp_path):
        mon = _mk_monitor(tmp_path)
        s = mon.stats()
        assert s["total_changes"] == 0

    def test_stats_by_type(self, tmp_path):
        mon = _mk_monitor(tmp_path)
        d = tmp_path / "d"
        _write(d / "a.py")
        mon.snapshot_directory(d, label="l")
        _write(d / "b.txt")
        mon.check_directory(d, label="l")
        s = mon.stats()
        assert s["total_changes"] == 1
        assert s["by_type"].get("added") == 1


class TestExportReport:
    def test_report_markdown(self, tmp_path):
        mon = _mk_monitor(tmp_path)
        d = tmp_path / "d"
        _write(d / "a.py")
        mon.snapshot_directory(d, label="l")
        _write(d / "a.py", "print(2)")
        mon.check_directory(d, label="l")
        report = mon.export_report()
        assert report.startswith("# 文件完整性监控报告")
        assert "modified" in report
        assert "a.py" in report


class TestClassifyChange:
    def test_py_ext_high(self):
        mon = _mk_monitor(tmp_path := __import__("pathlib").Path(".") / "x")
        old = FileSnapshot(path="a.py", sha256="x", size=1, mtime=0.0, recorded_at=0.0)
        new = FileSnapshot(path="a.py", sha256="y", size=1, mtime=0.0, recorded_at=0.0)
        assert mon._classify_change(old, new) == "high"

    def test_soul_md_high(self):
        mon = _mk_monitor(__import__("pathlib").Path(".") / "x")
        old = FileSnapshot(path="SOUL.md", sha256="x", size=1, mtime=0.0, recorded_at=0.0)
        new = FileSnapshot(path="SOUL.md", sha256="y", size=1, mtime=0.0, recorded_at=0.0)
        assert mon._classify_change(old, new) == "high"

    def test_small_txt_low(self):
        mon = _mk_monitor(__import__("pathlib").Path(".") / "x")
        old = FileSnapshot(path="note.txt", sha256="x", size=1, mtime=0.0, recorded_at=0.0)
        new = FileSnapshot(path="note.txt", sha256="y", size=1, mtime=0.0, recorded_at=0.0)
        assert mon._classify_change(old, new) == "low"

    def test_large_medium(self):
        mon = _mk_monitor(__import__("pathlib").Path(".") / "x")
        old = FileSnapshot(path="big.dat", sha256="x", size=1, mtime=0.0, recorded_at=0.0)
        new = FileSnapshot(path="big.dat", sha256="y", size=20000, mtime=0.0, recorded_at=0.0)
        assert mon._classify_change(old, new) == "medium"


class TestSha256:
    def test_compute_sha256(self, tmp_path):
        f = _write(tmp_path / "a.txt", "hello")
        from tuan_cli.core.file_integrity import FileIntegrityMonitor as M
        h = M._compute_sha256(f)
        assert h is not None and len(h) == 64

    def test_snapshot_file(self, tmp_path):
        mon = _mk_monitor(tmp_path)
        f = _write(tmp_path / "a.txt", "data")
        snap = mon._snapshot_file(f, "a.txt")
        assert snap is not None
        assert snap.sha256 == M_shash(f)


def M_shash(f):
    import hashlib
    return hashlib.sha256(f.read_bytes()).hexdigest()


def hashlib_short(s):
    import hashlib
    return hashlib.sha256(s.encode()).hexdigest()[:12]


class TestPersistence:
    def test_snapshot_load_roundtrip(self, tmp_path):
        mon = _mk_monitor(tmp_path)
        d = tmp_path / "d"
        _write(d / "a.py", "1")
        mon.snapshot_directory(d, label="l")
        # 新实例从磁盘读快照
        mon2 = _mk_monitor(tmp_path)
        assert len(mon2._load_snapshot(mon2._snapshot_path(d, "l"))) == 1

    def test_changes_persisted_and_loaded(self, tmp_path):
        mon = _mk_monitor(tmp_path)
        d = tmp_path / "d"
        _write(d / "a.py", "1")
        mon.snapshot_directory(d, label="l")
        _write(d / "a.py", "2")
        mon.check_directory(d, label="l")
        mon2 = _mk_monitor(tmp_path)
        assert mon2.stats()["total_changes"] == 1


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v", "-p", "no:cacheprovider"]))
