"""白名单管理器回归测试 —— 加载过滤 / 原子写 / 红线拒绝 / 匹配语义。"""

from __future__ import annotations

import json
import os

import pytest

from qingxiaotuan.core.whitelist import (
    WhitelistManager, get_warning_level, make_confirm_token, MultiStageConfirm,
)


# ---------------------------------------------------------------- 加载健壮性

def test_load_filters_malformed_entries(tmp_path):
    """畸形条目 (缺 command/description) 在加载时被过滤, 不炸后续匹配。"""
    (tmp_path / "whitelist.json").write_text(
        json.dumps({"version": 1, "entries": [
            {"command": "okcmd", "description": "ok"},
            {"command": "nokey"},           # 缺 description
            {"description": "nocmd"},        # 缺 command
            "not-a-dict",                     # 非 dict
            None,
        ]}), encoding="utf-8")
    wm = WhitelistManager(tmp_path)
    cmds = [e["command"] for e in wm.list()]
    assert "okcmd" in cmds
    assert "nokey" not in cmds
    assert "nocmd" not in cmds
    # 默认白名单已合并
    assert any(e["command"] == "ls" for e in wm.list())
    # 畸形条目不导致匹配异常
    assert wm.is_whitelisted("okcmd -a") is True
    assert wm.is_whitelisted("ls -la") is True


def test_load_missing_file_uses_defaults(tmp_path):
    wm = WhitelistManager(tmp_path)
    assert any(e["command"] == "grep" for e in wm.list())


# ---------------------------------------------------------------- 原子写

def test_save_is_atomic_no_tmp_leftover(tmp_path):
    wm = WhitelistManager(tmp_path)
    assert wm.add("echo hello", "测试命令") is True
    # 磁盘上只有正式文件, 无残留临时文件
    leftovers = [p.name for p in tmp_path.iterdir() if p.name.endswith(".tmp")]
    assert leftovers == []
    data = json.loads((tmp_path / "whitelist.json").read_text(encoding="utf-8"))
    assert data["version"] == 1
    assert any(e["command"] == "echo hello" for e in data["entries"])
    # 重新加载仍可见 (落盘成功)
    wm2 = WhitelistManager(tmp_path)
    assert wm2.is_whitelisted("echo hello world") is True


# ---------------------------------------------------------------- 红线拒绝

def test_add_rejects_redline(tmp_path):
    wm = WhitelistManager(tmp_path)
    assert wm.add("rm -rf /") is False
    assert wm.add("git push --force origin main") is False
    assert wm.is_whitelisted("rm -rf /") is False


# ---------------------------------------------------------------- 匹配语义

def test_match_complete_and_prefix(tmp_path):
    wm = WhitelistManager(tmp_path)
    assert wm.is_whitelisted("ls") is True
    assert wm.is_whitelisted("ls -la /tmp") is True
    assert wm.is_whitelisted("git status --short") is True
    # 大小写不敏感
    assert wm.is_whitelisted("LS -la") is True
    # 部分前缀不命中 (防止 "l" 匹配 "ls")
    assert wm.is_whitelisted("l") is False
    assert wm.is_whitelisted("cat") is True


def test_remove_and_clear(tmp_path):
    wm = WhitelistManager(tmp_path)
    assert wm.add("echo hi") is True
    assert wm.remove("echo hi") is True
    assert wm.is_whitelisted("echo hi") is False
    n_default = len(wm.list())
    wm.clear()
    assert len(wm.list()) == n_default  # 保留默认条目


# ---------------------------------------------------------------- 确认码

def test_confirm_token_distinct_alphabet():
    seen = set(make_confirm_token(64))
    # 仅使用去混淆字母表 (无 0/O/1/I)
    assert not (seen & set("0O1I"))
    assert len(make_confirm_token(4)) == 4


def test_warning_level_classification():
    assert get_warning_level("rm -rf /") == 5
    assert get_warning_level("shutdown now") == 5
    assert get_warning_level("git reset --hard HEAD") == 3
    assert get_warning_level("ls -la") == 0


def test_multistage_confirm_fail_closed_non_tty(monkeypatch):
    """无确认回调且非交互终端 → fail-closed 拒绝 (无人值守场景)。"""
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    mc = MultiStageConfirm(confirm_fn=None, min_interval=0)
    assert mc.confirm("rm -rf /", warning_level=5) is False
