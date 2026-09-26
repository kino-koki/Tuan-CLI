"""共享原子写工具测试: 崩溃一致性 / 无残留 / 权限保留。"""

from __future__ import annotations

import json
import os

import pytest

from qingxiaotuan.core.atomicio import atomic_write_text


def _tmp_leftovers(directory) -> list:
    return [p.name for p in directory.iterdir() if p.name.endswith(".tmp")]


def test_basic_write_and_read(tmp_path):
    target = tmp_path / "sub" / "nested" / "data.json"
    atomic_write_text(target, '{"a": 1}')
    assert json.loads(target.read_text(encoding="utf-8")) == {"a": 1}
    # 目录自动创建 + 无临时文件残留
    assert _tmp_leftovers(tmp_path / "sub" / "nested") == []


def test_overwrite_leaves_no_tmp(tmp_path):
    target = tmp_path / "f.txt"
    atomic_write_text(target, "v1")
    atomic_write_text(target, "v2")
    assert target.read_text(encoding="utf-8") == "v2"
    assert _tmp_leftovers(tmp_path) == []


def test_overwrite_preserves_existing_mode(tmp_path):
    if os.name == "nt":
        pytest.skip("POSIX 权限位在 Windows 上无意义")
    target = tmp_path / "run.sh"
    target.write_text("#!/bin/sh\n", encoding="utf-8")
    target.chmod(0o755)
    atomic_write_text(target, "#!/bin/sh\necho v2\n")
    assert target.stat().st_mode & 0o111 != 0


def test_unicode_content_roundtrip(tmp_path):
    target = tmp_path / "u.json"
    atomic_write_text(target, '{"你好": "青小团"}')
    assert json.loads(target.read_text(encoding="utf-8")) == {"你好": "青小团"}


def test_unwritable_dir_raises_and_cleans_tmp(tmp_path, monkeypatch):
    """写入失败时重新抛出异常, 且不留临时文件。"""
    target = tmp_path / "data.txt"

    def boom(*_a, **_k):
        raise OSError("disk full")

    monkeypatch.setattr("qingxiaotuan.core.atomicio.os.replace", boom)
    with pytest.raises(OSError):
        atomic_write_text(target, "x")
    assert not target.exists()
    assert _tmp_leftovers(tmp_path) == []


def test_written_through_workspace_trust_and_message_bus(tmp_path):
    """workspace_trust / message_bus 的落盘走原子写, 无 .tmp 残留。"""
    from qingxiaotuan.core.message_bus import MessageBus
    from qingxiaotuan.core.workspace_trust import WorkspaceTrust, TrustLevel

    home = tmp_path / "home"
    wt = WorkspaceTrust(home)
    wt.set_trust(str(tmp_path), TrustLevel.TRUSTED)
    assert _tmp_leftovers(home) == []
    assert (home / "workspace_trust.json").exists()

    bus = MessageBus(home=home, ttl=600)
    bus.register("sess-1", {"model": "test"})
    bus.heartbeat("sess-1")
    assert _tmp_leftovers(home / "messages" / "sessions") == []
    assert (home / "messages" / "sessions" / "sess-1.json").exists()
