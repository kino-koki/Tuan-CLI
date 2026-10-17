"""密钥泄露扫描器测试 —— secret_scanner 规则命中/脱敏/目录扫描/总线集成。"""
from __future__ import annotations

from pathlib import Path

from tuan_cli.core.secret_scanner import (
    emit_findings,
    scan_directory,
    scan_file,
    scan_text,
    summarize,
)


# ------------------------------------------------------------ 规则命中

def test_detects_aws_key():
    txt = 'aws_key = "AKIAIOSFODNN7EXAMPLE"'
    findings = scan_text(txt)
    assert any(f.secret_type == "aws_access_key" for f in findings)


def test_detects_github_token():
    txt = 'token = "ghp_' + "a" * 30 + '"'
    findings = scan_text(txt)
    assert any(f.secret_type == "github_token" for f in findings)


def test_detects_openai_style_key():
    txt = 'OPENAI_API_KEY="sk-' + "x" * 30 + '"'
    findings = scan_text(txt)
    assert any(f.secret_type == "openai_style_key" for f in findings)


def test_detects_private_key_block():
    txt = "-----BEGIN RSA PRIVATE KEY-----\nMIIB...\n-----END RSA PRIVATE KEY-----"
    findings = scan_text(txt)
    assert any(f.secret_type == "private_key_block" for f in findings)


def test_detects_generic_assignment():
    txt = 'api_key = "abcd1234efgh5678ijkl"'
    findings = scan_text(txt)
    assert any(f.secret_type == "generic_api_key_assignment" for f in findings)


def test_detects_jwt():
    txt = "token: eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
    findings = scan_text(txt)
    assert any(f.secret_type == "jwt" for f in findings)


# ------------------------------------------------------------ 不误报 + 脱敏

def test_benign_text_no_findings():
    txt = "这是一段普通日志, 没有任何密钥。用户登录成功, id=42。"
    assert scan_text(txt) == []


def test_finding_masks_full_secret():
    """命中值只能看到前后缀, 不能把完整密钥写进结果 (防二次泄露)。"""
    secret = "sk-" + "z" * 40
    findings = scan_text(f'KEY="{secret}"')
    assert findings, "应命中"
    for f in findings:
        assert secret not in f.preview, "preview 不得包含完整密钥"
        assert "…" in f.preview or "***" in f.preview


def test_finding_has_remediation():
    findings = scan_text('AKIA' + "A" * 16)
    assert findings
    for f in findings:
        assert f.remediation, "每条发现必须带修复建议"
        assert f.line >= 1


# ------------------------------------------------------------ 文件/目录扫描

def test_scan_file_finds_secret(tmp_path: Path):
    f = tmp_path / "config.py"
    f.write_text('AWS_KEY="AKIA' + "B" * 16 + '"\n', encoding="utf-8")
    findings = scan_file(f)
    assert any(x.secret_type == "aws_access_key" for x in findings)


def test_scan_directory_skips_git_and_binary(tmp_path: Path):
    # 正常文件含密钥
    (tmp_path / "app.py").write_text('KEY="sk-' + "c" * 30 + '"\n', encoding="utf-8")
    # .git 目录里也藏一个密钥, 应被跳过
    gitdir = tmp_path / ".git"
    gitdir.mkdir()
    (gitdir / "config").write_text('KEY="ghp_' + "d" * 30 + '"\n', encoding="utf-8")
    # 二进制文件 (含 NUL) 应跳过
    binf = tmp_path / "blob.bin"
    binf.write_bytes(b"\x00\x01AKIA" + b"e" * 16)

    findings = scan_directory(tmp_path)
    types = [x.secret_type for x in findings]
    # 只扫到 app.py 里的 openai 风格 key
    assert "openai_style_key" in types
    # .git 与二进制里的密钥不应出现
    assert "github_token" not in types


# ------------------------------------------------------------ 总线集成

class _FakeBus:
    def __init__(self):
        self.events = []

    def emit(self, event):
        self.events.append(event)


def test_emit_findings_records_to_bus():
    findings = scan_text('AWS_KEY="AKIA' + "F" * 16 + '"')
    bus = _FakeBus()
    n = emit_findings(bus, findings)
    assert n >= 1
    assert bus.events, "高危发现应汇入总线"
    assert bus.events[0].event_type == "security.secret.leak"


def test_emit_findings_no_bus_is_safe():
    findings = scan_text('AWS_KEY="AKIA' + "G" * 16 + '"')
    assert emit_findings(None, findings) == 0  # bus 为 None 不抛


# ------------------------------------------------------------ 报告输出

def test_summarize_output():
    findings = scan_text('AWS_KEY="AKIA' + "H" * 16 + '"')
    report = summarize(findings)
    assert "密钥泄露" in report
    assert "建议" in report


def test_summarize_clean():
    assert "未发现" in summarize([])
