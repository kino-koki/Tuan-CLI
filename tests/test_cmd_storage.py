"""``tuan storage`` CLI 的单元测试 (cmd_storage.py)。

纯只读磁盘占用报表。覆盖:
1. _fmt_size: B/KB/MB/GB/TB 各档
2. _get_home: 显式 home / None 走 home_dir()
3. _subsystem_scan: 空目录 / 多子系统按体积降序
4. overview: 空报表 / JSON / 正常渲染
5. top: JSON / 限制 N / 空目录
6. tree: 子系统不存在 / 下钻文件 / 超 30 截断提示
7. 分发入口: 未知子命令
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tuan_cli.cli import cmd_storage as S


def _args(**kw) -> SimpleNamespace:
    base = dict(storage_cmd=None, home=None, json=False, n=20, subsystem=None)
    base.update(kw)
    return SimpleNamespace(**base)


def _mk(home: Path, rel: str, size: int) -> None:
    p = home / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"x" * size)


# ============================================================ _fmt_size


class TestFmtSize:
    def test_bytes(self) -> None:
        assert S._fmt_size(0) == "0 B"
        assert S._fmt_size(512) == "512 B"

    def test_kb(self) -> None:
        assert S._fmt_size(1024) == "1.0 KB"
        assert S._fmt_size(2048) == "2.0 KB"

    def test_mb(self) -> None:
        assert S._fmt_size(1024 * 1024) == "1.0 MB"

    def test_gb(self) -> None:
        assert S._fmt_size(1024 ** 3) == "1.0 GB"

    def test_tb_capped(self) -> None:
        # 超过 TB 也封顶在 TB
        assert S._fmt_size(1024 ** 4 * 10) == "10.0 TB"


# ============================================================ _get_home


class TestGetHome:
    def test_explicit_home(self) -> None:
        rc = S._get_home("/tmp/some/path")
        assert rc == Path("/tmp/some/path").resolve()

    def test_explicit_tilde(self) -> None:
        rc = S._get_home("~/x")
        assert str(rc).startswith(str(Path.home()))


# ============================================================ _subsystem_scan


class TestSubsystemScan:
    def test_empty_dir(self, tmp_path) -> None:
        assert S._subsystem_scan(tmp_path) == []

    def test_nonexistent_dir(self, tmp_path) -> None:
        assert S._subsystem_scan(tmp_path / "missing") == []

    def test_sorted_desc(self, tmp_path) -> None:
        _mk(tmp_path, "small/a.txt", 10)
        _mk(tmp_path, "big/a.txt", 1000)
        _mk(tmp_path, "mid/a.txt", 100)
        rows = S._subsystem_scan(tmp_path)
        names = [r["subsystem"] for r in rows]
        assert names == ["big", "mid", "small"]
        assert all("human" in r for r in rows)

    def test_skips_files(self, tmp_path) -> None:
        (tmp_path / "loose.txt").write_text("x", encoding="utf-8")
        rows = S._subsystem_scan(tmp_path)
        assert rows == []


# ============================================================ overview


class TestOverview:
    def test_empty_report(self, monkeypatch, tmp_path) -> None:
        monkeypatch.setattr(S, "_get_home", lambda h: tmp_path)
        rc = S._cmd_storage_overview(_args())
        assert rc == 0

    def test_json_output(self, monkeypatch, tmp_path, capsys) -> None:
        _mk(tmp_path, "sessions/a.jsonl", 100)
        monkeypatch.setattr(S, "_get_home", lambda h: tmp_path)
        rc = S._cmd_storage_overview(_args(json=True))
        data = json.loads(capsys.readouterr().out)
        assert rc == 0
        assert data["total_files"] == 1
        assert data["subsystems"][0]["subsystem"] == "sessions"

    def test_normal_render(self, monkeypatch, tmp_path) -> None:
        _mk(tmp_path, "checkpoints/x.bin", 500)
        monkeypatch.setattr(S, "_get_home", lambda h: tmp_path)
        monkeypatch.setattr(S.console, "print", lambda *a, **k: None)
        rc = S._cmd_storage_overview(_args())
        assert rc == 0


# ============================================================ top


class TestTop:
    def test_empty(self, monkeypatch, tmp_path) -> None:
        monkeypatch.setattr(S, "_get_home", lambda h: tmp_path)
        monkeypatch.setattr(S.console, "print", lambda *a, **k: None)
        rc = S._cmd_storage_top(_args(storage_cmd="top"))
        assert rc == 0

    def test_limit_n(self, monkeypatch, tmp_path) -> None:
        for i in range(10):
            _mk(tmp_path, f"sub/f{i}.txt", 100 + i)
        monkeypatch.setattr(S, "_get_home", lambda h: tmp_path)
        rc = S._cmd_storage_top(_args(storage_cmd="top", n=3))
        assert rc == 0

    def test_json_sorted(self, monkeypatch, tmp_path, capsys) -> None:
        _mk(tmp_path, "a/big.bin", 1000)
        _mk(tmp_path, "b/small.bin", 5)
        monkeypatch.setattr(S, "_get_home", lambda h: tmp_path)
        rc = S._cmd_storage_top(_args(storage_cmd="top", json=True))
        data = json.loads(capsys.readouterr().out)
        assert rc == 0
        assert data[0]["bytes"] == 1000
        assert data[1]["bytes"] == 5


# ============================================================ tree


class TestTree:
    def test_missing_subsystem(self, monkeypatch, tmp_path, capsys) -> None:
        monkeypatch.setattr(S, "_get_home", lambda h: tmp_path)
        rc = S._cmd_storage_tree(_args(storage_cmd="tree", subsystem="nope"))
        out = capsys.readouterr().out
        assert rc == 1
        assert "不存在" in out

    def test_missing_subsystem_arg(self, monkeypatch, tmp_path) -> None:
        rc = S._cmd_storage_tree(_args(storage_cmd="tree", subsystem=None))
        assert rc == 1

    def test_drill_down(self, monkeypatch, tmp_path) -> None:
        _mk(tmp_path, "sessions/x.jsonl", 500)
        _mk(tmp_path, "sessions/y.jsonl", 100)
        monkeypatch.setattr(S, "_get_home", lambda h: tmp_path)
        monkeypatch.setattr(S.console, "print", lambda *a, **k: None)
        rc = S._cmd_storage_tree(_args(storage_cmd="tree", subsystem="sessions"))
        assert rc == 0

    def test_empty_subsystem(self, monkeypatch, tmp_path) -> None:
        (tmp_path / "empty").mkdir()
        monkeypatch.setattr(S, "_get_home", lambda h: tmp_path)
        monkeypatch.setattr(S.console, "print", lambda *a, **k: None)
        rc = S._cmd_storage_tree(_args(storage_cmd="tree", subsystem="empty"))
        assert rc == 0

    def test_over_30_truncation(self, monkeypatch, tmp_path) -> None:
        for i in range(35):
            _mk(tmp_path, f"sub/f{i:02}.txt", 100 - i)
        monkeypatch.setattr(S, "_get_home", lambda h: tmp_path)
        printed = []
        monkeypatch.setattr(S.console, "print",
                            lambda msg, *a, **k: printed.append(str(msg)))
        rc = S._cmd_storage_tree(_args(storage_cmd="tree", subsystem="sub"))
        assert rc == 0
        assert any("另有" in p for p in printed)


# ============================================================ 分发入口


class TestDispatcher:
    def test_default_overview(self, monkeypatch, tmp_path) -> None:
        monkeypatch.setattr(S, "_get_home", lambda h: tmp_path)
        monkeypatch.setattr(S.console, "print", lambda *a, **k: None)
        rc = S.cmd_storage(_args(storage_cmd=None))
        assert rc == 0

    def test_unknown_subcommand(self, monkeypatch, capsys) -> None:
        rc = S.cmd_storage(_args(storage_cmd="bogus"))
        out = capsys.readouterr().out
        assert rc == 1
        assert "未知子命令" in out

    def test_dispatches_top(self, monkeypatch, tmp_path) -> None:
        monkeypatch.setattr(S, "_get_home", lambda h: tmp_path)
        monkeypatch.setattr(S.console, "print", lambda *a, **k: None)
        rc = S.cmd_storage(_args(storage_cmd="top"))
        assert rc == 0

    def test_dispatches_tree(self, monkeypatch, tmp_path) -> None:
        (tmp_path / "sub").mkdir()
        _mk(tmp_path, "sub/x.txt", 10)
        monkeypatch.setattr(S, "_get_home", lambda h: tmp_path)
        monkeypatch.setattr(S.console, "print", lambda *a, **k: None)
        rc = S.cmd_storage(_args(storage_cmd="tree", subsystem="sub"))
        assert rc == 0
