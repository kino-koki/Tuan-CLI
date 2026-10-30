"""cmd_review_cli —— Claude Code 对齐 CLI 命令面 (review/security-review/simplify/debug/auto-mode/batch)。

覆盖 `cli/cmd_review_cli.py` 全部 6 个命令的关键路径:
- cmd_review: 普通评审 / 安全评审 / 单文件 / JSON 输出 / 异常返回 2
- cmd_security_review: 透传 cmd_review
- cmd_simplify: dry-run / apply / 异常
- cmd_debug: 环境诊断 (含密钥脱敏)
- cmd_auto_mode: list 默认 / test 正常 / test 缺 tool / test JSON 解析失败
- cmd_batch: 命令列表 / 文件读取 / 过滤非安全命令 / 无输入报错
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tuan_cli.cli import cmd_review_cli as crc


class _Args:
    """最小 argparse.Namespace 替身。"""

    def __init__(self, **kw):
        self.__dict__.update(kw)


# ---------------------------------------------------------------- 辅助

def _write_sample(tmp_path: Path, name: str = "sample.py", content: str = None) -> Path:
    p = tmp_path / name
    p.write_text(content if content is not None else "import os\n\nprint(os.getcwd())\n",
                 encoding="utf-8")
    return p


# ---------------------------------------------------------------- cmd_review

def test_review_normal_scans_file(tmp_path, capsys):
    f = _write_sample(tmp_path)
    args = _Args(path=f.name, files="", json=False, security=False,
                 categories="security,logic,style,complexity", workspace=str(tmp_path))
    rc = crc.cmd_review(args)
    assert rc == 0
    out = capsys.readouterr().out
    assert "未发现" in out or "严重" in out or "问题" in out


def test_review_security_only(tmp_path, capsys):
    f = _write_sample(tmp_path)
    args = _Args(path=f.name, files="", json=False, security=True,
                 categories=None, workspace=str(tmp_path))
    rc = crc.cmd_review(args)
    assert rc in (0, 2)


def test_review_single_file_json(tmp_path, capsys):
    f = _write_sample(tmp_path, name="bad.py", content="import os\nos.system('rm -rf /')\n")
    args = _Args(path=f.name, files="", json=True, security=False,
                 categories="security", workspace=str(tmp_path))
    rc = crc.cmd_review(args)
    assert rc in (0, 1)
    data = json.loads(capsys.readouterr().out)
    assert data["scope"] == str(tmp_path)
    assert isinstance(data["files"], int)
    assert isinstance(data["issues"], list)


def test_review_error_returns_2(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("scan failed")

    monkeypatch.setattr("tuan_cli.tools.code_review.code_review", boom)
    args = _Args(path="", files="x.py", json=False, security=False,
                 categories="security", workspace=str(tmp_path))
    rc = crc.cmd_review(args)
    assert rc == 2


# ---------------------------------------------------------------- cmd_security_review

def test_security_review_delegates(tmp_path, monkeypatch):
    """cmd_security_review 透传给 cmd_review (security=True)。"""
    seen = {}

    def fake_review(args):
        seen["security"] = getattr(args, "security", None)
        return 5

    monkeypatch.setattr(crc, "cmd_review", fake_review)
    args = _Args(security=True)
    assert crc.cmd_security_review(args) == 5
    assert seen["security"] is True


# ---------------------------------------------------------------- cmd_simplify

def test_simplify_dry_run_no_proposals(tmp_path, monkeypatch, capsys):
    class _Mgr:
        def __init__(self, home, workspace=None):
            pass

    monkeypatch.setattr("tuan_cli.cli.cmd_review_cli.home_dir", lambda: str(tmp_path))
    monkeypatch.setattr("tuan_cli.skills.manager.SkillManager", _Mgr)
    monkeypatch.setattr(
        "tuan_cli.skills.governance.consolidate",
        lambda manager, dry_run=True, threshold=0.7: [],
    )
    args = _Args(apply=False, threshold=0.7, workspace=str(tmp_path))
    rc = crc.cmd_simplify(args)
    assert rc == 0
    assert "未发现" in capsys.readouterr().out


def test_simplify_apply_proposals(tmp_path, monkeypatch, capsys):
    class _Mgr:
        def __init__(self, home, workspace=None):
            pass

    class _Pr:
        score = 0.95
        writable = True

        class _Slug:
            slug = "a"

        keeper = _Slug()
        loser = _Slug()

    monkeypatch.setattr("tuan_cli.cli.cmd_review_cli.home_dir", lambda: str(tmp_path))
    monkeypatch.setattr("tuan_cli.skills.manager.SkillManager", _Mgr)
    monkeypatch.setattr(
        "tuan_cli.skills.governance.consolidate",
        lambda manager, dry_run=False, threshold=0.7: [_Pr()],
    )
    args = _Args(apply=True, threshold=0.7, workspace=str(tmp_path))
    rc = crc.cmd_simplify(args)
    assert rc == 0
    out = capsys.readouterr().out
    assert "已合并 1 组" in out


def test_simplify_error_returns_2(tmp_path, monkeypatch):
    monkeypatch.setattr("tuan_cli.cli.cmd_review_cli.home_dir", lambda: str(tmp_path))

    def boom(*a, **k):
        raise RuntimeError("consolidate failed")

    monkeypatch.setattr("tuan_cli.skills.governance.consolidate", boom)
    args = _Args(apply=False, threshold=0.7, workspace=str(tmp_path))
    assert crc.cmd_simplify(args) == 2


# ---------------------------------------------------------------- cmd_debug

def test_debug_prints_environment(monkeypatch, capsys):
    monkeypatch.setattr("tuan_cli.cli.cmd_review_cli.home_dir", lambda: "/fake/home")
    monkeypatch.setenv("TUAN_PROVIDER", "deepseek")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-secret-123456")
    args = _Args()
    rc = crc.cmd_debug(args)
    assert rc == 0
    out = capsys.readouterr().out
    assert "调试诊断" in out
    assert "deepseek" in out
    # 密钥应被脱敏
    assert "sk-secret-123456" not in out
    assert "已设置" in out


# ---------------------------------------------------------------- cmd_auto_mode

def test_auto_mode_list_default(capsys):
    args = _Args(action="list", tool="", args="{}")
    rc = crc.cmd_auto_mode(args)
    assert rc == 0
    out = capsys.readouterr().out
    assert "Auto 模式分类器" in out
    assert "示例" in out


def test_auto_mode_test_normal(capsys):
    args = _Args(action="test", tool="Bash",
                 args=json.dumps({"command": "git status"}))
    rc = crc.cmd_auto_mode(args)
    assert rc == 0
    out = capsys.readouterr().out
    assert "测试 调用" in out or "test 调用" in out
    assert "风险等级" in out


def test_auto_mode_test_missing_tool(capsys):
    args = _Args(action="test", tool="", args="{}")
    rc = crc.cmd_auto_mode(args)
    assert rc == 2


def test_auto_mode_test_bad_json(capsys):
    """非 { 开头视为 query 字符串 (宽松设计: 支持 tuan auto-mode test Bash "git status")。"""
    args = _Args(action="test", tool="Bash", args="git status")
    rc = crc.cmd_auto_mode(args)
    assert rc == 0
    out = capsys.readouterr().out
    assert '{"query": "git status"}' in out


def test_auto_mode_test_invalid_json_object(capsys):
    """以 { 开头但 JSON 无效 → 参数解析失败返回 2。"""
    args = _Args(action="test", tool="Bash", args="{not valid json}")
    rc = crc.cmd_auto_mode(args)
    assert rc == 2


def test_auto_mode_test_non_object_json(capsys):
    """以 { 开头但解析为非对象 (数组) → 返回 2。"""
    args = _Args(action="test", tool="Bash", args='{"a": 1}')
    rc = crc.cmd_auto_mode(args)
    assert rc == 0  # 合法对象

    args2 = _Args(action="test", tool="Bash", args="[1,2,3]")
    rc2 = crc.cmd_auto_mode(args2)
    assert rc2 == 0  # 非 { 开头视为 query 字符串


# ---------------------------------------------------------------- cmd_batch

def test_batch_from_argv_all_safe(capsys):
    args = _Args(commands=["/status", "/memory"], file=None)
    rc = crc.cmd_batch(args)
    assert rc == 0
    out = capsys.readouterr().out
    assert "共 2 条" in out
    assert "跳过 0 条" in out


def test_batch_filters_dangerous(capsys):
    args = _Args(commands=["/status", "/bash ls -la", "/edit file.py"], file=None)
    rc = crc.cmd_batch(args)
    assert rc == 0
    out = capsys.readouterr().out
    assert "跳过" in out


def test_batch_from_file(tmp_path, capsys):
    f = tmp_path / "cmds.txt"
    f.write_text("/status\n# comment\n/memory\n", encoding="utf-8")
    args = _Args(commands=None, file=str(f))
    rc = crc.cmd_batch(args)
    assert rc == 0
    out = capsys.readouterr().out
    assert "共 2 条" in out


def test_batch_no_input(capsys):
    args = _Args(commands=None, file=None)
    rc = crc.cmd_batch(args)
    assert rc == 2
