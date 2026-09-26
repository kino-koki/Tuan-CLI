# -*- coding: utf-8 -*-
"""CLI 层测试: qxt safe bench / qxt safe report (一键复现安全基准 + HTML 报告)。"""
from __future__ import annotations

import json
import types
from pathlib import Path

from qingxiaotuan.cli import cmd_safe
from qingxiaotuan.cli import parser as cli_parser


def _run_parse(argv: list[str]):
    return cli_parser.build_parser().parse_args(argv)


def test_parser_registers_safe_bench():
    args = _run_parse(["safe", "bench"])
    assert args.func == "cmd_safe"
    assert args.safe_cmd == "bench"
    assert args.quick is False


def test_parser_registers_safe_bench_quick_and_out():
    args = _run_parse(["safe", "bench", "--quick", "--out", "x.json"])
    assert args.safe_cmd == "bench"
    assert args.quick is True
    assert args.out == "x.json"


def test_parser_registers_safe_report():
    args = _run_parse(["safe", "report", "--out", "r.html"])
    assert args.safe_cmd == "report"
    assert args.out == "r.html"


def test_render_security_report_html_contains_numbers_and_no_external():
    bench = {
        "adversarial": {"total": 10000, "block_recall": 100.0, "flag_catch": 100.0,
                        "false_positive_rate": 1.87, "bypass": 0},
        "powershell": {"total": 5000, "accuracy": 1.0, "fn": 0, "fp": 0},
        "bypass_matrix": {"total": 1083, "bypass": 0, "false_pos": 1, "all_disaster_blocked": True},
    }
    state = {
        "engine": {"version": "1.1.0-python", "capabilities": ["risk_scoring", "command_analysis"]},
        "whitelist_count": 14, "suppressed": [], "audit": {"total_events": 0, "by_severity": {"critical": 0}},
        "audit_path": "/tmp/audit.jsonl", "sandbox_available": True, "sandbox_name": "local",
        "crypto_backend": "software",
    }
    html = cmd_safe._render_security_report_html(bench, state)
    assert "<title>青小团 · 安全状态报告</title>" in html
    assert "10000 条" in html
    assert "100.0%" in html and "1.87%" in html
    assert "灾难类别拦截: 100%" in html
    assert "software" in html
    assert "http://" not in html and "https://" not in html  # 自包含, 无外链
    assert "https://cdn" not in html


def test_cmd_report_writes_html(tmp_path, monkeypatch):
    # 用仓库现成的基准汇总驱动报告生成 (不重跑基准)
    root = cmd_safe._repo_root()
    bench_json = root / "bench" / "security-bench.json"
    if not bench_json.exists():
        bench_json.write_text(json.dumps({
            "adversarial": {"total": 10000, "block_recall": 100.0, "flag_catch": 100.0,
                            "false_positive_rate": 1.87, "bypass": 0},
            "powershell": {"total": 5000, "accuracy": 1.0, "fn": 0, "fp": 0},
            "bypass_matrix": {"total": 1083, "bypass": 0, "false_pos": 1, "all_disaster_blocked": True},
        }), encoding="utf-8")
    out = tmp_path / "report.html"
    args = types.SimpleNamespace(out=str(out))
    rc = cmd_safe._cmd_report(args)
    assert rc == 0
    assert out.exists()
    body = out.read_text(encoding="utf-8")
    assert "安全状态报告" in body
    assert "10000 条" in body


def test_cmd_bench_quick_with_fake_runners(tmp_path, monkeypatch):
    """mock 子进程, 验证三套件调度 + 汇总 JSON 结构 + 临时文件清理。"""
    calls: list[list[str]] = []
    root = cmd_safe._repo_root()
    ps_json = root / "bench" / "ps_safety_result.json"

    def fake_run(cmd: list[str], **kw) -> types.SimpleNamespace:
        calls.append(cmd)
        script = str(cmd[1]).replace("\\", "/")
        if "safety_bench_10k" in script:
            out_idx = cmd.index("--out")
            Path(cmd[out_idx + 1]).write_text(json.dumps({
                "total": 2000, "block_recall": 100.0, "flag_catch": 100.0,
                "false_positive_rate": 0.81, "bypass": 0}), encoding="utf-8")
        elif "bypass_matrix" in script:
            out_idx = cmd.index("--json-out")
            Path(cmd[out_idx + 1]).write_text(json.dumps({
                "total": 1083, "bypass": 0, "false_pos": 1, "all_disaster_blocked": True}),
                encoding="utf-8")
        elif "bench_powershell_safety" in script:
            # 脚本真实产物已在 bench/ 存在 (本轮已跑), 此处不再写
            pass
        return types.SimpleNamespace(stderr="", stdout="")

    monkeypatch.setattr(cmd_safe.subprocess, "run", fake_run)
    out = tmp_path / "agg.json"
    args = types.SimpleNamespace(quick=True, out=str(out))
    rc = cmd_safe._cmd_bench(args)
    assert rc == 0
    # 三个脚本都被调度
    scripts = [str(c[1]).replace("\\", "/") for c in calls]
    assert any("safety_bench_10k" in s for s in scripts)
    assert any("bench_powershell_safety" in s for s in scripts)
    assert any("bypass_matrix" in s for s in scripts)
    # 汇总结构
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["seed"] == 20260906
    assert data["quick"] is True
    assert data["adversarial"]["total"] == 2000
    assert data["bypass_matrix"]["bypass"] == 0
    # 临时文件已清理
    leftovers = list((root / "bench").glob(".run_tmp_*"))
    assert leftovers == []
    # ps 基准 JSON 未被覆盖为假数据 (不依赖 fake_run 写入)
    assert ps_json.exists()


# ---------------------------------------------------------------- 第三轮: 门禁 / RELEASE

def test_parser_registers_bench_check():
    args = _run_parse(["safe", "bench", "--check"])
    assert args.safe_cmd == "bench"
    assert args.check is True


def test_parser_registers_report_release():
    args = _run_parse(["safe", "report", "--release", "--out", "r.html"])
    assert args.safe_cmd == "report"
    assert args.release is True


def test_check_no_regression_ok_when_equal_or_better():
    ref = {
        "adversarial": {"block_recall": 100.0, "false_positive_rate": 1.87, "bypass": 0},
        "powershell": {"fn": 0, "fp": 0},
        "bypass_matrix": {"bypass": 0, "all_disaster_blocked": True},
    }
    new = {
        "adversarial": {"block_recall": 100.0, "false_positive_rate": 1.5, "bypass": 0},
        "powershell": {"fn": 0, "fp": 0},
        "bypass_matrix": {"bypass": 0, "all_disaster_blocked": True},
    }
    assert cmd_safe._check_no_regression(new, ref) == []


def test_check_no_regression_detects_bypass():
    ref = {"adversarial": {"block_recall": 100.0, "bypass": 0},
           "powershell": {"fn": 0, "fp": 0},
           "bypass_matrix": {"bypass": 0, "all_disaster_blocked": True}}
    new = {"adversarial": {"block_recall": 100.0, "bypass": 1},
           "powershell": {"fn": 0, "fp": 0},
           "bypass_matrix": {"bypass": 0, "all_disaster_blocked": True}}
    problems = cmd_safe._check_no_regression(new, ref)
    assert any("绕过" in m for m in problems)


def test_check_no_regression_detects_disaster_break():
    ref = {"bypass_matrix": {"bypass": 0, "all_disaster_blocked": True}}
    new = {"bypass_matrix": {"bypass": 0, "all_disaster_blocked": False}}
    problems = cmd_safe._check_no_regression(new, ref)
    assert any("灾难" in m for m in problems)


def test_check_no_regression_tolerates_small_fp_rise():
    ref = {"adversarial": {"block_recall": 100.0, "false_positive_rate": 1.87, "bypass": 0}}
    new = {"adversarial": {"block_recall": 100.0, "false_positive_rate": 2.0, "bypass": 0}}
    assert cmd_safe._check_no_regression(new, ref) == []


def test_check_no_regression_flags_big_fp_rise():
    ref = {"adversarial": {"block_recall": 100.0, "false_positive_rate": 1.87, "bypass": 0}}
    new = {"adversarial": {"block_recall": 100.0, "false_positive_rate": 3.5, "bypass": 0}}
    problems = cmd_safe._check_no_regression(new, ref)
    assert any("误杀率" in m for m in problems)


def test_git_head_short_returns_hex_or_none():
    root = cmd_safe._repo_root()
    commit = cmd_safe._git_head_short(root)
    if commit is not None:
        assert len(commit) >= 7 and all(c in "0123456789abcdef" for c in commit)


def test_quick_check_does_not_overwrite_full_archive(tmp_path, monkeypatch):
    """--quick --check 且未指定 --out: 结果写 .quick.json, 不覆盖全量存档。"""
    root = cmd_safe._repo_root()
    bench_dir = root / "bench"
    # 临时替换存档避免污染仓库 (用 monkeypatch 指向 tmp)
    tmp_archive = tmp_path / "security-bench.json"
    tmp_archive.write_text(json.dumps({
        "adversarial": {"total": 10000, "block_recall": 100.0, "false_positive_rate": 1.87, "bypass": 0},
        "powershell": {"fn": 0, "fp": 0},
        "bypass_matrix": {"bypass": 0, "all_disaster_blocked": True},
    }), encoding="utf-8")
    # fake 子进程
    def fake_run(cmd: list[str], **kw) -> types.SimpleNamespace:
        script = str(cmd[1]).replace("\\", "/")
        if "safety_bench_10k" in script:
            out_idx = cmd.index("--out")
            Path(cmd[out_idx + 1]).write_text(json.dumps({
                "total": 2000, "block_recall": 100.0, "flag_catch": 100.0,
                "false_positive_rate": 0.81, "bypass": 0}), encoding="utf-8")
        elif "bypass_matrix" in script:
            out_idx = cmd.index("--json-out")
            Path(cmd[out_idx + 1]).write_text(json.dumps({
                "total": 1083, "bypass": 0, "false_pos": 1, "all_disaster_blocked": True}),
                encoding="utf-8")
        return types.SimpleNamespace(stderr="", stdout="")

    monkeypatch.setattr(cmd_safe.subprocess, "run", fake_run)
    # 把 ref 指向 tmp 存档
    monkeypatch.setattr(cmd_safe, "_repo_root", lambda: tmp_path)
    # 需要 bench 目录存在且 ps 结果可读
    (tmp_path / "bench").mkdir(exist_ok=True)
    (tmp_path / "bench" / "ps_safety_result.json").write_text(json.dumps(
        {"total": 5000, "accuracy": 1.0, "fn": 0, "fp": 0}), encoding="utf-8")

    args = types.SimpleNamespace(quick=True, check=True, out=None)
    rc = cmd_safe._cmd_bench(args)
    assert rc == 0
    # 全量存档未被覆盖
    assert json.loads(tmp_archive.read_text(encoding="utf-8"))["adversarial"]["total"] == 10000
    # quick 结果在独立文件
    quick_json = tmp_path / "bench" / "security-bench.quick.json"
    assert quick_json.exists()
    assert json.loads(quick_json.read_text(encoding="utf-8"))["adversarial"]["total"] == 2000
