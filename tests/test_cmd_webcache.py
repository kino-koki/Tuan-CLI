"""``tuan webcache`` CLI 的单元测试 (cmd_webcache.py)。

纯只读体检命令。覆盖:
1. 缓存目录不存在 -> 空报表
2. 空目录 -> (空)提示
3. 正常条目: 新鲜 / 过期 / 损坏三类
4. JSON 模式输出
5. --top N 截断
6. 禁用模式 (network.search_cache_dir 为空串)

通过 monkeypatch 打桩 _resolve_cache_dir / _ttl / home_dir, 不写真实家目录。
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from tuan_cli.cli import cmd_webcache as P


def _args(**kw) -> SimpleNamespace:
    base = dict(top=0, json=False, cache_cmd=None, dry_run=False)
    base.update(kw)
    return SimpleNamespace(**base)


def _write(cache_dir: Path, name: str, *, ts: float, query: str = "q",
           results: int = 3, raw: str = None) -> Path:
    p = cache_dir / name
    if raw is not None:
        p.write_text(raw, encoding="utf-8")
    else:
        p.write_text(json.dumps({
            "ts": ts, "query": query,
            "results": [{"title": f"r{i}"} for i in range(results)],
        }, ensure_ascii=False), encoding="utf-8")
    return p


class TestWebcache:
    def test_no_cache_dir(self, monkeypatch, capsys) -> None:
        tmp = Path("/tmp/does-not-exist/webcache-test-xyz")
        monkeypatch.setattr(P, "_resolve_cache_dir", lambda home: tmp)
        rc = P.cmd_webcache(_args())
        out = capsys.readouterr().out
        assert rc == 0
        assert "0" in out or "(空)" in out or "无条目" in out

    def test_empty_dir(self, monkeypatch, tmp_path, capsys) -> None:
        monkeypatch.setattr(P, "_resolve_cache_dir", lambda home: tmp_path)
        rc = P.cmd_webcache(_args())
        out = capsys.readouterr().out
        assert rc == 0
        assert "0" in out

    def test_fresh_and_expired(self, monkeypatch, tmp_path, capsys) -> None:
        now = time.time()
        _write(tmp_path, "fresh.json", ts=now, query="python", results=5)
        _write(tmp_path, "old.json", ts=now - 999999, query="rust", results=2)
        monkeypatch.setattr(P, "_resolve_cache_dir", lambda home: tmp_path)
        monkeypatch.setattr(P, "_ttl", lambda: 21600.0)
        rc = P.cmd_webcache(_args())
        out = capsys.readouterr().out
        assert rc == 0
        assert "python" in out
        assert "rust" in out
        assert "新鲜" in out
        assert "过期" in out

    def test_corrupt_entry_marked(self, monkeypatch, tmp_path, capsys) -> None:
        now = time.time()
        _write(tmp_path, "bad.json", ts=now, raw="{not valid json")
        monkeypatch.setattr(P, "_resolve_cache_dir", lambda home: tmp_path)
        monkeypatch.setattr(P, "_ttl", lambda: 21600.0)
        rc = P.cmd_webcache(_args())
        out = capsys.readouterr().out
        assert rc == 0
        assert "损坏" in out

    def test_json_mode(self, monkeypatch, tmp_path, capsys) -> None:
        now = time.time()
        _write(tmp_path, "a.json", ts=now, query="go", results=4)
        _write(tmp_path, "b.json", ts=now - 10**6, query="zig", results=1)
        monkeypatch.setattr(P, "_resolve_cache_dir", lambda home: tmp_path)
        monkeypatch.setattr(P, "_ttl", lambda: 21600.0)
        rc = P.cmd_webcache(_args(json=True))
        out = capsys.readouterr().out
        assert rc == 0
        data = json.loads(out)
        assert data["total"] == 2
        assert data["fresh"] == 1
        assert data["expired"] == 1
        assert data["corrupt"] == 0
        assert data["total_results"] == 5
        assert "cache_dir" in data

    def test_top_n_truncation(self, monkeypatch, tmp_path, capsys) -> None:
        now = time.time()
        for i in range(5):
            _write(tmp_path, f"e{i}.json", ts=now, query=f"q{i}", results=1)
        monkeypatch.setattr(P, "_resolve_cache_dir", lambda home: tmp_path)
        monkeypatch.setattr(P, "_ttl", lambda: 21600.0)
        rc = P.cmd_webcache(_args(top=2))
        out = capsys.readouterr().out
        assert rc == 0
        assert "仅显示前 2" in out

    def test_disabled_mode(self, monkeypatch, tmp_path, capsys) -> None:
        disabled = tmp_path / "cache" / "web" / "_disabled"
        disabled.mkdir(parents=True)
        monkeypatch.setattr(P, "_resolve_cache_dir", lambda home: disabled)
        rc = P.cmd_webcache(_args())
        out = capsys.readouterr().out
        assert rc == 0
        assert "禁用" in out


class TestResolveCacheDir:
    """_resolve_cache_dir: 空串 -> 禁用目录; 默认 -> home/cache/web。"""

    def test_empty_string_disables(self, monkeypatch, tmp_path) -> None:
        import tuan_cli.config as _cfgmod

        class FakeCfg:
            def get(self, k, d=None):
                return ""

        monkeypatch.setattr(_cfgmod, "Config", lambda: FakeCfg())
        rc = P._resolve_cache_dir(tmp_path)
        assert rc.name == "_disabled"

    def test_default_falls_back_to_home(self, monkeypatch, tmp_path) -> None:
        import tuan_cli.config as _cfgmod

        class FakeCfg:
            def get(self, k, d=None):
                return d  # 走默认

        monkeypatch.setattr(_cfgmod, "Config", lambda: FakeCfg())
        rc = P._resolve_cache_dir(tmp_path)
        assert rc == (tmp_path / "cache" / "web").resolve()
