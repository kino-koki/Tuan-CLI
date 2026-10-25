"""C-5 网络检测模块单测 (tuan_cli/core/network_check.py)。"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tuan_cli.core import network_check


def test_offline_env_override(monkeypatch):
    """TUAN_OFFLINE=1 时直接判离线, 不做真实探测。"""
    monkeypatch.setenv("TUAN_OFFLINE", "1")
    network_check.reset_cache()
    assert network_check.is_offline() is True


def test_cache_prevents_reprobe(monkeypatch):
    """10s 缓存期内第二次调用不应触发新探测 (用 URL 探测计数验证)。"""
    monkeypatch.delenv("TUAN_OFFLINE", raising=False)
    network_check.reset_cache()
    calls = {"n": 0}

    def fake_probe(url, timeout):
        calls["n"] += 1
        return True  # 任意端点通 -> 在线

    monkeypatch.setattr(network_check, "_probe", fake_probe)
    network_check.is_offline(timeout=1)
    network_check.is_offline(timeout=1)
    assert calls["n"] == 1, "缓存期内不应重复探测"


def test_force_reprobes(monkeypatch):
    """force=True 绕过缓存重新探测。"""
    monkeypatch.delenv("TUAN_OFFLINE", raising=False)
    network_check.reset_cache()
    calls = {"n": 0}

    def fake(timeout=3.0):
        calls["n"] += 1
        return {"offline": False, "checked_at": __import__("time").time(),
                "via": "x", "checked": []}

    monkeypatch.setattr(network_check, "probe_once", fake)
    network_check.is_offline(timeout=1)
    network_check.is_offline(timeout=1, force=True)
    assert calls["n"] == 2


def test_offline_status_shape():
    """offline_status 返回结构化快照。"""
    network_check.reset_cache()
    status = network_check.offline_status()
    assert "offline" in status
    assert "checked_at" in status
