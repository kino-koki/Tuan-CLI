"""``tuan fastindex`` CLI 的单元测试 (cmd_fastindex.py)。

持久化快速文件索引只读体检。覆盖:
1. _resolve_workspace: 显式 / TUAN_WORKSPACE / cwd
2. _index_path / _load: 缺失 / 损坏 / 正常 / 非 dict
3. _entries: 过滤非 dict
4. _max_by: 空列表 / 正常最大
5. stats 子命令: 未初始化 / 有数据 / JSON
6. files 子命令: 空索引 / 排名 / limit / JSON

通过 monkeypatch tmp_path + 写真实 index.json, 不依赖 cwd。
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tuan_cli.cli import cmd_fastindex as P


def _args(**kw) -> SimpleNamespace:
    base = dict(fastindex_cmd=None, workspace=None, json=False, limit=0)
    base.update(kw)
    return SimpleNamespace(**base)


def _write_index(ws: Path, entries: dict, version="v1") -> Path:
    p = ws / ".tuan" / "fastindex" / "index.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"version": version, "entries": entries}),
                 encoding="utf-8")
    return p


def _entry(lang="python", loc=100, size=2048, symbols=None, relpath="x.py",
           head="import os"):
    return {"lang": lang, "loc": loc, "size": size,
            "symbols": symbols or ["foo", "bar"], "relpath": relpath, "head": head}


class TestResolveWorkspace:
    def test_explicit(self) -> None:
        rc = P._resolve_workspace("/tmp/ws/x")
        assert rc == Path("/tmp/ws/x").resolve()

    def test_env_var(self, monkeypatch) -> None:
        monkeypatch.setenv("TUAN_WORKSPACE", "/tmp/env/ws")
        rc = P._resolve_workspace(None)
        assert rc == Path("/tmp/env/ws").resolve()

    def test_cwd_fallback(self, monkeypatch) -> None:
        monkeypatch.delenv("TUAN_WORKSPACE", raising=False)
        rc = P._resolve_workspace(None)
        assert rc == Path.cwd().resolve()


class TestLoad:
    def test_missing(self, tmp_path) -> None:
        assert P._load(tmp_path / "nope.json") is None

    def test_corrupt(self, tmp_path) -> None:
        p = tmp_path / "x.json"
        p.write_text("{not valid", encoding="utf-8")
        assert P._load(p) is None

    def test_non_dict(self, tmp_path) -> None:
        p = tmp_path / "x.json"
        p.write_text("[1,2,3]", encoding="utf-8")
        assert P._load(p) is None

    def test_no_entries_key(self, tmp_path) -> None:
        p = tmp_path / "x.json"
        p.write_text('{"version": "v1"}', encoding="utf-8")
        assert P._load(p) is None

    def test_valid(self, tmp_path) -> None:
        p = tmp_path / "x.json"
        p.write_text('{"version": "v1", "entries": {}}', encoding="utf-8")
        data = P._load(p)
        assert data is not None
        assert data["version"] == "v1"


class TestEntries:
    def test_filters_non_dict(self) -> None:
        data = {"entries": {"a": _entry(), "b": "not-dict", "c": 42}}
        out = P._entries(data)
        assert len(out) == 1

    def test_empty(self) -> None:
        assert P._entries({"entries": {}}) == []


class TestMaxBy:
    def test_empty(self) -> None:
        r = P._max_by([], lambda e: 0)
        assert r == {"relpath": "-", "value": 0.0}

    def test_finds_max(self) -> None:
        entries = [_entry(symbols=["a"]), _entry(symbols=["a", "b", "c"])]
        r = P._max_by(entries, lambda e: len(e.get("symbols", [])))
        assert r["value"] == 3


# ============================================================ stats 子命令


class TestStats:
    def test_uninitialized(self, monkeypatch, tmp_path, capsys) -> None:
        monkeypatch.setattr(P, "_resolve_workspace", lambda raw: tmp_path)
        rc = P.cmd_fastindex(_args())
        out = capsys.readouterr().out
        assert rc == 0
        assert "未初始化" in out

    def test_with_data(self, monkeypatch, tmp_path, capsys) -> None:
        _write_index(tmp_path, {
            "a.py": _entry(relpath="a.py", loc=100, size=2048, symbols=["f", "g"]),
            "b.py": _entry(relpath="b.py", lang="js", loc=50, size=1024, symbols=["h"]),
        })
        monkeypatch.setattr(P, "_resolve_workspace", lambda raw: tmp_path)
        rc = P.cmd_fastindex(_args())
        out = capsys.readouterr().out
        assert rc == 0
        assert "2" in out  # 文件数
        assert "python" in out
        assert "js" in out

    def test_json_output(self, monkeypatch, tmp_path, capsys) -> None:
        _write_index(tmp_path, {
            "a.py": _entry(loc=100, size=2048, symbols=["f"]),
        })
        monkeypatch.setattr(P, "_resolve_workspace", lambda raw: tmp_path)
        rc = P.cmd_fastindex(_args(json=True))
        data = json.loads(capsys.readouterr().out)
        assert rc == 0
        assert data["initialized"] is True
        assert data["file_count"] == 1
        assert data["total_loc"] == 100
        assert data["total_symbols"] == 1
        assert data["by_lang"]["python"] == 1


# ============================================================ files 子命令


class TestFiles:
    def test_empty_index(self, monkeypatch, tmp_path) -> None:
        monkeypatch.setattr(P, "_resolve_workspace", lambda raw: tmp_path)
        monkeypatch.setattr(P.console, "print", lambda *a, **k: None)
        rc = P.cmd_fastindex(_args(fastindex_cmd="files"))
        assert rc == 0

    def test_ranking_by_symbols(self, monkeypatch, tmp_path) -> None:
        _write_index(tmp_path, {
            "a.py": _entry(relpath="a.py", symbols=["x"]),
            "b.py": _entry(relpath="b.py", symbols=["x", "y", "z"]),
            "c.py": _entry(relpath="c.py", symbols=["x", "y"]),
        })
        monkeypatch.setattr(P, "_resolve_workspace", lambda raw: tmp_path)
        printed = []
        monkeypatch.setattr(P.console, "print",
                            lambda msg, *a, **k: printed.append(str(msg)))
        rc = P.cmd_fastindex(_args(fastindex_cmd="files"))
        assert rc == 0
        text = "\n".join(printed)
        # b.py (3 符号) 应排在 c.py (2) 和 a.py (1) 之前
        i_b = text.find("b.py")
        i_c = text.find("c.py")
        i_a = text.find("a.py")
        assert 0 <= i_b < i_c < i_a

    def test_limit(self, monkeypatch, tmp_path, capsys) -> None:
        _write_index(tmp_path, {
            f"f{i}.py": _entry(relpath=f"f{i}.py", symbols=["x"] * (5 - i % 3))
            for i in range(10)
        })
        monkeypatch.setattr(P, "_resolve_workspace", lambda raw: tmp_path)
        rc = P.cmd_fastindex(_args(fastindex_cmd="files", limit=3, json=True))
        data = json.loads(capsys.readouterr().out)
        assert rc == 0
        assert len(data["items"]) == 3

    def test_json_output(self, monkeypatch, tmp_path, capsys) -> None:
        _write_index(tmp_path, {
            "a.py": _entry(relpath="a.py", lang="python", loc=42, size=1024, symbols=["f"]),
        })
        monkeypatch.setattr(P, "_resolve_workspace", lambda raw: tmp_path)
        rc = P.cmd_fastindex(_args(fastindex_cmd="files", json=True))
        data = json.loads(capsys.readouterr().out)
        assert rc == 0
        assert data["initialized"] is True
        assert data["items"][0]["relpath"] == "a.py"
        assert data["items"][0]["symbols"] == 1

    def test_uninitialized(self, monkeypatch, tmp_path, capsys) -> None:
        monkeypatch.setattr(P, "_resolve_workspace", lambda raw: tmp_path)
        rc = P.cmd_fastindex(_args(fastindex_cmd="files", json=True))
        data = json.loads(capsys.readouterr().out)
        assert rc == 0
        assert data["initialized"] is False
        assert data["items"] == []
