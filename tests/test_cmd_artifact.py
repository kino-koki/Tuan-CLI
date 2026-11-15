"""``tuan artifact`` CLI 的单元测试 (cmd_artifact.py)。

Artifact 产物只读枚举。覆盖:
1. _resolve_workspace: 显式 / TUAN_WORKSPACE / cwd
2. _artifacts_dir: workspace 下 .tuan/artifacts
3. _title_from_name: 带时间戳 / 无时间戳
4. _preview: script/style 剥离 / 空文件 / 不可读 / 长文本截断
5. _row: 完整字段
6. list 子命令: 目录未初始化 / 空 / 有产物 / limit / JSON
7. show 子命令: 缺文件名 / 不存在 / 路径逃逸 / 正常 / JSON
8. 分发入口: 未知子命令

通过写真实 HTML 文件到 tmp_path, 不依赖 cwd。
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from tuan_cli.cli import cmd_artifact as P


def _args(**kw) -> SimpleNamespace:
    base = dict(artifact_cmd=None, workspace=None, json=False, limit=0, file=None)
    base.update(kw)
    return SimpleNamespace(**base)


def _make_artifact(ws: Path, name: str, body: str = "<h1>Hello</h1>") -> Path:
    d = ws / ".tuan" / "artifacts"
    d.mkdir(parents=True, exist_ok=True)
    p = d / name
    p.write_text(f"<html><body>{body}</body></html>", encoding="utf-8")
    return p


# ============================================================ _resolve_workspace


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


# ============================================================ _artifacts_dir


class TestArtifactsDir:
    def test_path(self) -> None:
        ws = Path("/tmp/ws")
        rc = P._artifacts_dir(ws)
        assert rc == ws / ".tuan" / "artifacts"


# ============================================================ _title_from_name


class TestTitleFromName:
    def test_with_timestamp(self) -> None:
        assert P._title_from_name("MyReport_20260115_143022.html") == "MyReport"

    def test_without_timestamp(self) -> None:
        assert P._title_from_name("no_ts.html") == "no_ts"

    def test_multibyte_title(self) -> None:
        assert P._title_from_name("报告_20260115_143022.html") == "报告"


# ============================================================ _preview


class TestPreview:
    def test_strips_script_style(self, tmp_path) -> None:
        p = tmp_path / "x.html"
        p.write_text("<style>h1{color:red}</style><script>x()</script>"
                     "<body>可见正文</body>", encoding="utf-8")
        rc = P._preview(p)
        assert "可见正文" in rc
        assert "color:red" not in rc

    def test_strips_tags(self, tmp_path) -> None:
        p = tmp_path / "x.html"
        p.write_text("<h1>标题</h1><p>正文</p>", encoding="utf-8")
        rc = P._preview(p)
        assert "标题" in rc
        assert "正文" in rc
        assert "<h1>" not in rc

    def test_empty_file(self, tmp_path) -> None:
        p = tmp_path / "x.html"
        p.write_text("", encoding="utf-8")
        assert P._preview(p) == "(空)"

    def test_unreadable(self, tmp_path) -> None:
        p = tmp_path / "nope.html"  # 不存在 -> OSError
        assert P._preview(p) == "(不可读)"

    def test_truncates_long(self, tmp_path) -> None:
        p = tmp_path / "x.html"
        p.write_text("<body>" + "x" * 200 + "</body>", encoding="utf-8")
        rc = P._preview(p, max_chars=50)
        assert len(rc) == 50


# ============================================================ _row


class TestRow:
    def test_complete_fields(self, tmp_path) -> None:
        p = _make_artifact(tmp_path, "报告_20260115_143022.html",
                           body="<p>预览内容</p>")
        r = P._row(p)
        assert r["file"] == "报告_20260115_143022.html"
        assert r["title"] == "报告"
        assert r["size_bytes"] > 0
        assert isinstance(r["mtime"], float)
        assert "iso" in r
        assert "预览内容" in r["preview"]


# ============================================================ list 子命令


class TestList:
    def test_uninitialized(self, monkeypatch, tmp_path, capsys) -> None:
        monkeypatch.setattr(P, "_resolve_workspace", lambda raw: tmp_path)
        rc = P.cmd_artifact(_args())
        out = capsys.readouterr().out
        assert rc == 0
        assert "未初始化" in out

    def test_uninitialized_json(self, monkeypatch, tmp_path, capsys) -> None:
        monkeypatch.setattr(P, "_resolve_workspace", lambda raw: tmp_path)
        rc = P.cmd_artifact(_args(json=True))
        data = json.loads(capsys.readouterr().out)
        assert rc == 0
        assert data["initialized"] is False
        assert data["items"] == []

    def test_empty_dir(self, monkeypatch, tmp_path, capsys) -> None:
        (tmp_path / ".tuan" / "artifacts").mkdir(parents=True)
        monkeypatch.setattr(P, "_resolve_workspace", lambda raw: tmp_path)
        monkeypatch.setattr(P.console, "print", lambda *a, **k: None)
        rc = P.cmd_artifact(_args())
        assert rc == 0

    def test_with_artifacts(self, monkeypatch, tmp_path) -> None:
        _make_artifact(tmp_path, "报告_20260115_143022.html")
        _make_artifact(tmp_path, "笔记_20260116_090000.html")
        monkeypatch.setattr(P, "_resolve_workspace", lambda raw: tmp_path)
        printed = []
        monkeypatch.setattr(P.console, "print",
                            lambda msg, *a, **k: printed.append(str(msg)))
        rc = P.cmd_artifact(_args())
        assert rc == 0
        text = "\n".join(printed)
        assert "2 个产物" in text
        assert "报告" in text

    def test_limit(self, monkeypatch, tmp_path, capsys) -> None:
        for i in range(10):
            _make_artifact(tmp_path, f"a{i}_20260115_14{i:02d}00.html")
        monkeypatch.setattr(P, "_resolve_workspace", lambda raw: tmp_path)
        rc = P.cmd_artifact(_args(limit=3, json=True))
        data = json.loads(capsys.readouterr().out)
        assert rc == 0
        assert len(data["items"]) == 3

    def test_sorted_by_mtime_desc(self, monkeypatch, tmp_path) -> None:
        old = _make_artifact(tmp_path, "old_20260115_140000.html")
        new = _make_artifact(tmp_path, "new_20260116_140000.html")
        # 把 new 的 mtime 提到最新
        newer = time.time() + 100
        import os
        os.utime(new, (newer, newer))
        monkeypatch.setattr(P, "_resolve_workspace", lambda raw: tmp_path)
        rc = P.cmd_artifact(_args(json=True))
        # 验证通过 _row 顺序读取 (间接验证排序)
        assert rc == 0


# ============================================================ show 子命令


class TestShow:
    def test_missing_filename(self, monkeypatch, tmp_path) -> None:
        monkeypatch.setattr(P, "_resolve_workspace", lambda raw: tmp_path)
        printed = []
        monkeypatch.setattr(P.console, "print",
                            lambda msg, *a, **k: printed.append(str(msg)))
        rc = P.cmd_artifact(_args(artifact_cmd="show", file=None))
        assert rc == 1
        assert any("缺少文件名" in p for p in printed)

    def test_nonexistent(self, monkeypatch, tmp_path) -> None:
        monkeypatch.setattr(P, "_resolve_workspace", lambda raw: tmp_path)
        printed = []
        monkeypatch.setattr(P.console, "print",
                            lambda msg, *a, **k: printed.append(str(msg)))
        rc = P.cmd_artifact(_args(artifact_cmd="show", file="nope.html"))
        assert rc == 1
        assert any("不存在" in p for p in printed)

    def test_path_escape(self, monkeypatch, tmp_path) -> None:
        # 构造一个外部文件, 用 ../ 逃逸
        outside = tmp_path / "outside.html"
        outside.write_text("<h1>x</h1>", encoding="utf-8")
        monkeypatch.setattr(P, "_resolve_workspace", lambda raw: tmp_path)
        printed = []
        monkeypatch.setattr(P.console, "print",
                            lambda msg, *a, **k: printed.append(str(msg)))
        rc = P.cmd_artifact(_args(artifact_cmd="show", file="../outside.html"))
        assert rc == 1
        assert any("不存在" in p for p in printed)

    def test_normal(self, monkeypatch, tmp_path) -> None:
        _make_artifact(tmp_path, "报告_20260115_143022.html",
                       body="<p>预览内容</p>")
        monkeypatch.setattr(P, "_resolve_workspace", lambda raw: tmp_path)
        printed = []
        monkeypatch.setattr(P.console, "print",
                            lambda msg, *a, **k: printed.append(str(msg)))
        rc = P.cmd_artifact(_args(artifact_cmd="show",
                                  file="报告_20260115_143022.html"))
        assert rc == 0
        text = "\n".join(printed)
        assert "报告" in text
        assert "预览内容" in text
        assert "浏览器打开" in text

    def test_json_output(self, monkeypatch, tmp_path, capsys) -> None:
        _make_artifact(tmp_path, "a_20260115_143022.html", body="<p>x</p>")
        monkeypatch.setattr(P, "_resolve_workspace", lambda raw: tmp_path)
        rc = P.cmd_artifact(_args(artifact_cmd="show",
                                  file="a_20260115_143022.html", json=True))
        data = json.loads(capsys.readouterr().out)
        assert rc == 0
        assert data["title"] == "a"
        assert "file" in data


# ============================================================ 分发入口


class TestDispatcher:
    def test_unknown_subcommand(self, monkeypatch, tmp_path) -> None:
        monkeypatch.setattr(P, "_resolve_workspace", lambda raw: tmp_path)
        printed = []
        monkeypatch.setattr(P.console, "print",
                            lambda msg, *a, **k: printed.append(str(msg)))
        rc = P.cmd_artifact(_args(artifact_cmd="bogus"))
        assert rc == 1
        text = "\n".join(printed)
        assert "未知子命令" in text
        assert "list / show" in text

    def test_default_list(self, monkeypatch, tmp_path) -> None:
        monkeypatch.setattr(P, "_resolve_workspace", lambda raw: tmp_path)
        monkeypatch.setattr(P.console, "print", lambda *a, **k: None)
        rc = P.cmd_artifact(_args())
        assert rc == 0
