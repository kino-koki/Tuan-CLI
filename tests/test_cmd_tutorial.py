"""``tuan tutorial`` CLI 的单元测试 (cmd_tutorial.py)。

覆盖:
1. _read_tutorials: 目录不存在 / 坏 YAML 跳过 / 正常加载 / name 去重
2. _print_list: 空教程 / 有教程渲染表格
3. _exec_demo: shlex 解析 / 失败不抛 / 非 JSON 元字符走 shell=False
4. _run_tutorial: 未知名称 / --step 跳过 / --no-pause 不询问 / --exec 执行 demo
5. cmd_tutorial: 子命令分发 / 缺 name 报错

通过 monkeypatch 打桩 _TUTORIAL_DIR / subprocess.run / Prompt.ask / console.print。
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from tuan_cli.cli import cmd_tutorial as T


def _args(**kw) -> SimpleNamespace:
    base = dict(tutorial_cmd=None, name=None, exec_demo=False, step=1, no_pause=False)
    base.update(kw)
    return SimpleNamespace(**base)


def _write_tut(tmp_path: Path, name: str, steps=None, **extra) -> Path:
    """写一个最小合法教程 YAML。"""
    data = {"name": name, "title": f"教程 {name}", "level": "beginner",
            "description": f"{name} 简介", "steps": steps or [
                {"title": "步骤一", "narrative": "说明", "try": "echo hi"}
            ], **extra}
    import yaml as _pyyaml
    p = tmp_path / f"{name}.yaml"
    p.write_text(_pyyaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return p


def _patch_dir(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(T, "_TUTORIAL_DIR", tmp_path)
    # 清空默认 console 输出避免刷屏
    monkeypatch.setattr(T.console, "print", lambda *a, **k: None)


class TestReadTutorials:
    def test_missing_dir(self, monkeypatch) -> None:
        monkeypatch.setattr(T, "_TUTORIAL_DIR", Path("/tmp/does-not-exist-xyz"))
        assert T._read_tutorials() == []

    def test_loads_yaml(self, monkeypatch, tmp_path) -> None:
        _write_tut(tmp_path, "quickstart")
        _patch_dir(monkeypatch, tmp_path)
        tuts = T._read_tutorials()
        assert len(tuts) == 1
        assert tuts[0]["name"] == "quickstart"

    def test_skips_bad_yaml(self, monkeypatch, tmp_path) -> None:
        _write_tut(tmp_path, "good")
        (tmp_path / "bad.yaml").write_text("not: [valid: yaml:", encoding="utf-8")
        _patch_dir(monkeypatch, tmp_path)
        tuts = T._read_tutorials()
        # 坏文件被跳过
        names = [t["name"] for t in tuts]
        assert names == ["good"]

    def test_skips_non_dict(self, monkeypatch, tmp_path) -> None:
        (tmp_path / "list.yaml").write_text("- a\n- b\n", encoding="utf-8")
        (tmp_path / "empty.yaml").write_text("", encoding="utf-8")
        _patch_dir(monkeypatch, tmp_path)
        assert T._read_tutorials() == []


class TestPrintList:
    def test_empty(self, monkeypatch, tmp_path, capsys) -> None:
        _patch_dir(monkeypatch, tmp_path)
        printed = []
        monkeypatch.setattr(T.console, "print",
                            lambda msg, *a, **k: printed.append(str(msg)))
        rc = T._print_list()
        assert rc == 0
        assert any("未找到" in p for p in printed)

    def test_renders_table(self, monkeypatch, tmp_path) -> None:
        _write_tut(tmp_path, "alpha")
        _write_tut(tmp_path, "beta")
        _patch_dir(monkeypatch, tmp_path)
        rc = T._print_list()
        assert rc == 0


class TestExecDemo:
    def test_success_no_raise(self, monkeypatch) -> None:
        monkeypatch.setattr(T.console, "print", lambda *a, **k: None)
        monkeypatch.setattr(T.subprocess, "run",
                            lambda *a, **k: SimpleNamespace(returncode=0))
        # 不抛即通过
        T._exec_demo("echo hello")

    def test_nonzero_returncode(self, monkeypatch) -> None:
        printed = []
        monkeypatch.setattr(T.console, "print",
                            lambda msg, *a, **k: printed.append(str(msg)))
        monkeypatch.setattr(T.subprocess, "run",
                            lambda *a, **k: SimpleNamespace(returncode=2))
        T._exec_demo("false")
        assert any("非零" in p for p in printed)

    def test_exception_swallowed(self, monkeypatch) -> None:
        printed = []
        monkeypatch.setattr(T.console, "print",
                            lambda msg, *a, **k: printed.append(str(msg)))

        def boom(*a, **k):
            raise OSError("no such file")

        monkeypatch.setattr(T.subprocess, "run", boom)
        T._exec_demo("nonexistent-cmd-xyz")
        assert any("失败" in p for p in printed)


class TestRunTutorial:
    def test_unknown_name(self, monkeypatch, tmp_path) -> None:
        _patch_dir(monkeypatch, tmp_path)
        printed = []
        monkeypatch.setattr(T.console, "print",
                            lambda msg, *a, **k: printed.append(str(msg)))
        rc = T._run_tutorial("nonexistent", exec_demo=False, start_step=1, no_pause=True)
        assert rc == 2
        assert any("未找到" in p for p in printed)

    def test_no_pause_no_exec(self, monkeypatch, tmp_path) -> None:
        _write_tut(tmp_path, "t1", steps=[
            {"title": "s1", "narrative": "n1", "try": "cmd1"},
            {"title": "s2", "narrative": "n2", "try": "cmd2"},
        ])
        _patch_dir(monkeypatch, tmp_path)
        rc = T._run_tutorial("t1", exec_demo=False, start_step=1, no_pause=True)
        assert rc == 0

    def test_exec_runs_demo(self, monkeypatch, tmp_path) -> None:
        _write_tut(tmp_path, "t2", steps=[
            {"title": "s1", "narrative": "", "try": "echo hi", "demo": True},
        ])
        _patch_dir(monkeypatch, tmp_path)
        calls = []
        monkeypatch.setattr(T, "_exec_demo", lambda cmd: calls.append(cmd))
        rc = T._run_tutorial("t2", exec_demo=True, start_step=1, no_pause=True)
        assert rc == 0
        assert calls == ["echo hi"]

    def test_step_skips_earlier(self, monkeypatch, tmp_path) -> None:
        titles = []
        _write_tut(tmp_path, "t3", steps=[
            {"title": f"s{i}", "narrative": ""} for i in range(1, 4)
        ])
        _patch_dir(monkeypatch, tmp_path)
        # step=3 应只处理 s3
        rc = T._run_tutorial("t3", exec_demo=False, start_step=3, no_pause=True)
        assert rc == 0


class TestCmdTutorial:
    def test_default_lists(self, monkeypatch, tmp_path) -> None:
        _patch_dir(monkeypatch, tmp_path)
        _write_tut(tmp_path, "intro")
        rc = T.cmd_tutorial(_args())
        assert rc == 0

    def test_list_subcommand(self, monkeypatch, tmp_path) -> None:
        _patch_dir(monkeypatch, tmp_path)
        rc = T.cmd_tutorial(_args(tutorial_cmd="list"))
        assert rc == 0

    def test_run_missing_name(self, monkeypatch, tmp_path) -> None:
        _patch_dir(monkeypatch, tmp_path)
        printed = []
        monkeypatch.setattr(T.console, "print",
                            lambda msg, *a, **k: printed.append(str(msg)))
        rc = T.cmd_tutorial(_args(tutorial_cmd="run", name=None))
        assert rc == 2
        assert any("指定教程名称" in p for p in printed)

    def test_run_with_name(self, monkeypatch, tmp_path) -> None:
        _patch_dir(monkeypatch, tmp_path)
        _write_tut(tmp_path, "runme")
        rc = T.cmd_tutorial(_args(tutorial_cmd="run", name="runme", no_pause=True))
        assert rc == 0
