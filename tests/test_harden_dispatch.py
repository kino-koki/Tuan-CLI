"""tuan harden 子命令分发完整性回归。

此前 argparse 注册了 audit-archive / crypto-selftest / suggest 三个子命令,
但 cmd_harden 分发未覆盖, 全部落入"用法"错误 (rc=1) —— 注册入口与
分发脱节。本测试固化:
  1. 每个注册的 harden_cmd 都可在 cmd_harden 分发到 (不再落用法错误);
  2. 三个新命令的核心行为正确 (建议/自检/归档体检)。
"""
from __future__ import annotations

import io
import json
import os
import pathlib
import sys
import tempfile
import contextlib

import pytest

_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from tuan_cli.cli import cmd_harden  # noqa: E402


class _NS:
    pass


def _run(cmd: str, **kwargs) -> tuple[int, str, str]:
    ns = _NS()
    ns.harden_cmd = cmd
    ns.command = kwargs.get("command", "rm -rf /tmp")
    ns.commands = kwargs.get("commands")
    ns.provider = kwargs.get("provider", "auto")
    ns.out = kwargs.get("out")
    ns.all = kwargs.get("all", True)
    ns.dir = kwargs.get("dir")
    ns.format = kwargs.get("format", "jsonl")
    ns.from_ = kwargs.get("from_")
    ns.push = kwargs.get("push")
    ns.egress_cidr = kwargs.get("egress_cidr", ["10.0.0.0/8"])
    ns.one_way = kwargs.get("one_way", False)
    ns.verify = kwargs.get("verify", False)
    out = io.StringIO()
    err = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = cmd_harden.cmd_harden(ns)
    return rc, out.getvalue(), err.getvalue()


class TestHardenDispatchReachability:
    """注册的 harden_cmd 必须全部可分发 (0 死命令)。"""

    @pytest.mark.parametrize(
        "cmd",
        ["audit-export", "audit-archive", "sbom", "crypto-provider",
         "crypto-selftest", "network-check", "repro-lock", "suggest", "status"],
    )
    def test_registered_cmds_dispatchable(self, cmd: str):
        """每个合法 harden_cmd 都不再落入"用法"错误分支。"""
        rc, out, err = _run(cmd)
        combined = out + err
        assert "用法: tuan harden" not in combined, f"{cmd} 落入用法错误分支"


class TestSuggest:
    def test_dangerous_command_gets_alternatives(self):
        rc, out, _ = _run("suggest", command="rm -rf /")
        assert rc == 0
        assert "安全替代建议" in out
        assert "递归强制删除" in out or "递归删除" in out
        assert "mv" in out or "ls" in out

    def test_unknown_command_graceful(self):
        rc, out, _ = _run("suggest", command="echo hello")
        assert rc == 0
        assert "未命中安全替代规则" in out

    def test_missing_command_usage(self):
        rc, out, _ = _run("suggest", command="")
        assert rc == 2
        assert "用法" in out


class TestCryptoSelftest:
    def test_software_backend_selftest_ok(self):
        rc, out, _ = _run("crypto-selftest")
        assert rc == 0
        assert "crypto-selftest" in out
        assert "软件" in out or "software" in out
        assert "seal/open OK" in out
        assert "篡改拒绝 OK" in out


class TestAuditArchive:
    def test_nonexistent_dir_graceful(self):
        rc, out, _ = _run("audit-archive", dir="Z:/no-such-dir-xyz")
        assert rc == 0
        assert "不存在" in out or "为空" in out

    def test_archive_with_events(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = pathlib.Path(tmp) / "audit_export.jsonl"
            recs = [
                {"severity": "high", "ts": 1700000000.0, "event_type": "x"},
                {"severity": "medium", "ts": 1700000100.0, "event_type": "y"},
                {"severity": "high", "ts": 1700000200.0, "event_type": "z"},
            ]
            p.write_text("\n".join(json.dumps(r) for r in recs), encoding="utf-8")
            rc, out, _ = _run("audit-archive", dir=tmp)
            assert rc == 0
            assert "事件总数" in out
            assert "3" in out
            assert "'high': 2" in out
            assert "时间跨度" in out
