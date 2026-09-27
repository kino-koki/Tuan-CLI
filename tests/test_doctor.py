"""`qxt doctor` 诊断命令测试 (qingxiaotuan/cli/cmd_doctor.py)。

覆盖:
- 干净环境诊断通过 / 仅有警告时退出码 1
- 故意写坏技能 frontmatter, doctor 能指出具体文件与问题
- 配置语法错误检测
- --json 输出格式
- --fix 修复可修复问题 (补 frontmatter / 建目录)
- 退出码: 0=全部通过, 1=仅警告, 2=有错误
"""

import json
import sys
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from qingxiaotuan.cli import cmd_doctor
from qingxiaotuan.cli import commands


# ------------------------------------------------------------------ 辅助

def _write_config(home: Path, text: str) -> Path:
    home.mkdir(parents=True, exist_ok=True)
    p = home / "config.yaml"
    p.write_text(text, encoding="utf-8")
    return p


# ------------------------------------------------------------------ 正常环境

def test_clean_env_warns_no_config_returns_0(tmp_path, monkeypatch):
    """干净环境 (无 config) -> 有提示性警告 (未配置), 退出码 0。"""
    monkeypatch.setenv("QXT_HOME", str(tmp_path / "home"))
    findings = cmd_doctor.run_checks(tmp_path)
    # 无 config.yaml -> config 分类至少一条 warn
    cfg = [f for f in findings if f["category"] == "config"]
    assert any(f["status"] == "warn" for f in cfg)
    # 退出码: 警告不算故障, 仅有错误才非零 -> 0
    assert cmd_doctor._exit_code(findings) == 0


def test_valid_config_no_error(tmp_path, monkeypatch):
    """合法 config.yaml + 必填字段 -> config 分类无 error。"""
    monkeypatch.setenv("QXT_HOME", str(tmp_path / "home"))
    home = tmp_path / "home"
    _write_config(home, "model:\n  provider: deepseek\n  model: deepseek-chat\n")
    findings = cmd_doctor.run_checks(tmp_path, home=home)
    cfg = [f for f in findings if f["category"] == "config"]
    assert not any(f["status"] == "error" for f in cfg), cfg
    assert any("语法合法" in f["message"] for f in cfg)


# ------------------------------------------------------------------ 配置语法错误

def test_config_syntax_error_detected(tmp_path, monkeypatch):
    """config.yaml 语法错误 -> error, 且提到行号/问题。"""
    monkeypatch.setenv("QXT_HOME", str(tmp_path / "home"))
    home = tmp_path / "home"
    # 故意的 YAML 语法错误: 缩进错乱 + 未闭合冒号
    _write_config(home, "model:\n  provider: deepseek\n  model: [unclosed\n")
    findings = cmd_doctor.run_checks(tmp_path, home=home)
    errs = [f for f in findings if f["category"] == "config" and f["status"] == "error"]
    assert errs, findings
    assert "语法错误" in errs[0]["message"]
    assert cmd_doctor._exit_code(findings) == 2


# ------------------------------------------------------------------ 技能 frontmatter

def test_broken_skill_frontmatter_reported(tmp_path, monkeypatch):
    """故意写坏技能 frontmatter (缺 name/description), doctor 能指出文件。"""
    monkeypatch.setenv("QXT_HOME", str(tmp_path / "home"))
    home = tmp_path / "home"
    (home / "skills").mkdir(parents=True)
    bad = home / "skills" / "bad-one.md"
    # 有 frontmatter 但缺 name/description
    bad.write_text(
        "---\nupdated_at: 123\n---\n# 正文\n一些内容\n", encoding="utf-8")
    findings = cmd_doctor.run_checks(tmp_path, home=home)
    sk = [f for f in findings if f["category"] == "skills" and "bad-one" in f["message"]]
    assert sk, findings
    assert any("缺少必填字段" in f["message"] for f in sk)
    assert sk[0]["status"] == "error"
    assert sk[0]["fixable"] is True
    assert cmd_doctor._exit_code(findings) == 2


def test_skill_missing_frontmatter_is_error(tmp_path, monkeypatch):
    """技能 .md 完全没有 frontmatter -> error。"""
    monkeypatch.setenv("QXT_HOME", str(tmp_path / "home"))
    home = tmp_path / "home"
    (home / "skills").mkdir(parents=True)
    (home / "skills" / "nofm.md").write_text("# 纯正文\n没有 frontmatter\n", encoding="utf-8")
    findings = cmd_doctor.run_checks(tmp_path, home=home)
    errs = [f for f in findings if f["category"] == "skills" and f["status"] == "error"]
    assert errs and "nofm" in errs[0]["message"]


def test_good_skill_passes(tmp_path, monkeypatch):
    """合法技能 frontmatter -> ok。"""
    monkeypatch.setenv("QXT_HOME", str(tmp_path / "home"))
    home = tmp_path / "home"
    (home / "skills").mkdir(parents=True)
    (home / "skills" / "good.md").write_text(
        "---\nname: good\ndescription: 一个好技能\n---\n# 正文\n内容\n", encoding="utf-8")
    findings = cmd_doctor.run_checks(tmp_path, home=home)
    oks = [f for f in findings if f["category"] == "skills" and f["status"] == "ok" and "good" in f["message"]]
    assert oks


# ------------------------------------------------------------------ --fix

def test_fix_adds_missing_frontmatter(tmp_path, monkeypatch):
    """--fix 给缺 name/description 的技能补上占位字段, 且状态转为已修复。"""
    monkeypatch.setenv("QXT_HOME", str(tmp_path / "home"))
    home = tmp_path / "home"
    (home / "skills").mkdir(parents=True)
    bad = home / "skills" / "fixme.md"
    bad.write_text("---\nupdated_at: 1\n---\n正文\n", encoding="utf-8")
    findings = cmd_doctor.run_checks(tmp_path, home=home, fix=True)
    fixed = [f for f in findings if f.get("fixed") and "fixme" in f["message"]]
    assert fixed, findings
    # 物理文件已被补字段
    text = bad.read_text(encoding="utf-8")
    assert "name:" in text and "description:" in text


def test_fix_creates_missing_dirs(tmp_path, monkeypatch):
    """--fix 创建缺失的 home/skills 目录。"""
    monkeypatch.setenv("QXT_HOME", str(tmp_path / "home"))
    home = tmp_path / "home"  # 故意不存在
    assert not home.exists()
    cmd_doctor.run_checks(tmp_path, home=home, fix=True)
    assert (home / "skills").is_dir()


# ------------------------------------------------------------------ --json

def test_json_output_format(tmp_path, monkeypatch, capsys):
    """--json 输出合法 JSON, 含 version/exit_code/summary/findings。"""
    monkeypatch.setenv("QXT_HOME", str(tmp_path / "home"))
    args = mock.Mock(workspace=str(tmp_path), fix=False, json=True, network=False)
    code = commands.cmd_doctor(args)
    assert code in (0, 1, 2)
    payload = json.loads(capsys.readouterr().out)
    assert payload["exit_code"] == code
    assert {"ok", "warn", "error"} <= set(payload["summary"].keys())
    assert isinstance(payload["findings"], list)
    assert payload["findings"], "findings 不应为空"


# ------------------------------------------------------------------ 项目指令

def test_project_doc_size_warning(tmp_path, monkeypatch):
    """QXT.md 超过 32KB -> warn。"""
    monkeypatch.setenv("QXT_HOME", str(tmp_path / "home"))
    (tmp_path / "QXT.md").write_text("# x\n" + ("a" * (40 * 1024)), encoding="utf-8")
    findings = cmd_doctor.run_checks(tmp_path, home=tmp_path / "home")
    warns = [f for f in findings if f["category"] == "project" and f["status"] == "warn"]
    assert any("32KB" in w["message"] for w in warns)


def test_project_doc_non_utf8_warning(tmp_path, monkeypatch):
    """非 UTF-8 项目指令 -> warn。"""
    monkeypatch.setenv("QXT_HOME", str(tmp_path / "home"))
    # GBK 编码字节流 (中文常见), UTF-8 解码会失败
    (tmp_path / "AGENTS.md").write_bytes("中文内容".encode("gbk"))
    findings = cmd_doctor.run_checks(tmp_path, home=tmp_path / "home")
    warns = [f for f in findings if f["category"] == "project" and f["status"] == "warn"]
    assert any("UTF-8" in w["message"] for w in warns)


# ------------------------------------------------------------------ 退出码语义

def test_exit_code_semantics(tmp_path, monkeypatch):
    """0=全通过或仅警告, 2=有错误 (警告不算故障)。"""
    monkeypatch.setenv("QXT_HOME", str(tmp_path / "home"))
    home = tmp_path / "home"
    home.mkdir(parents=True)

    # 全 ok 的 findings 手工构造验证 _exit_code
    assert cmd_doctor._exit_code([{"status": "ok"}]) == 0
    assert cmd_doctor._exit_code([{"status": "ok"}, {"status": "warn"}]) == 0
    assert cmd_doctor._exit_code([{"status": "warn"}, {"status": "error"}]) == 2


def test_error_exit_code_2_via_cli(tmp_path, monkeypatch, capsys):
    """有错误时 CLI 退出码为 2。"""
    monkeypatch.setenv("QXT_HOME", str(tmp_path / "home"))
    home = tmp_path / "home"
    (home / "skills").mkdir(parents=True)
    (home / "skills" / "broken.md").write_text("---\nupdated_at: 1\n---\nx\n", encoding="utf-8")
    args = mock.Mock(workspace=str(tmp_path), fix=False, json=False, network=False)
    assert commands.cmd_doctor(args) == 2
