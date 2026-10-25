"""C-5.5 响应缓存单测 (tuan_cli/models/cache.py, TTL 1h)。"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tuan_cli.models.cache import ResponseCache


def test_set_get_roundtrip(tmp_path):
    c = ResponseCache(path=tmp_path / "c.json")
    assert c.get("deepseek", "m1", "你好") is None
    c.set("deepseek", "m1", "你好", "这是回答")
    assert c.get("deepseek", "m1", "你好") == "这是回答"


def test_key_isolation(tmp_path):
    """不同 provider/model/prompt 不互相命中。"""
    c = ResponseCache(path=tmp_path / "c.json")
    c.set("deepseek", "m1", "问题A", "回答A")
    assert c.get("groq", "m1", "问题A") is None
    assert c.get("deepseek", "m2", "问题A") is None
    assert c.get("deepseek", "m1", "问题B") is None


def test_ttl_expiry(tmp_path):
    """过期条目返回 None。"""
    c = ResponseCache(path=tmp_path / "c.json", ttl=0.2)
    c.set("p", "m", "q", "a")
    assert c.get("p", "m", "q") == "a"
    time.sleep(0.25)
    assert c.get("p", "m", "q") is None


def test_clear(tmp_path):
    c = ResponseCache(path=tmp_path / "c.json")
    c.set("p", "m", "q", "a")
    assert c.clear() == 1
    assert c.get("p", "m", "q") is None
