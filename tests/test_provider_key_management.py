"""API Key 与供应商管理: 换模型保留/删除原配置、/provider clear、.env 复用。"""

import os

import pytest

from qingxiaotuan.config import Config, persist_api_key, read_api_key


class _Chosen:
    """模拟供应商对象 (仅承载 .name / .api_key_env)。"""

    def __init__(self, name, api_key_env):
        self.name = name
        self.api_key_env = api_key_env


class _FakeAgent:
    registry = type("R", (), {"tools": []})()
    total_usage = {}
    kernel = None
    plan_mode = False
    messages = []

    def cache_hit_rate(self):
        return None


def _cfg_dual_key(qxt_home) -> Config:
    """把旧供应商配置写入 config + .env, 返回 Config。"""
    persist_api_key("DEEPSEEK_API_KEY", "sk-old")
    persist_api_key("MOONSHOT_API_KEY", "sk-ms")
    cfg = Config()
    cfg.set_user("model.provider", "deepseek")
    cfg.set_user("model.api_key_env", "DEEPSEEK_API_KEY")
    return cfg


def test_offer_keep_original_keeps_old_key(qxt_home, monkeypatch):
    """选 Y/回车: 保留旧供应商密钥 (文件不删、已有环境变量不删)。"""
    from qingxiaotuan.cli.cmd_chat import _offer_keep_original_config

    cfg = _cfg_dual_key(qxt_home)
    os.environ["DEEPSEEK_API_KEY"] = "sk-old"
    monkeypatch.setattr("builtins.input", lambda *a, **k: "y")
    _offer_keep_original_config(cfg, _Chosen("moonshot", "MOONSHOT_API_KEY"))
    assert read_api_key("DEEPSEEK_API_KEY") == "sk-old"
    assert os.environ.get("DEEPSEEK_API_KEY") == "sk-old"


def test_offer_keep_original_deletes_old_key(qxt_home, monkeypatch):
    """选 n: 删除旧供应商密钥 (文件 + 环境) 且不伤及新密钥。"""
    from qingxiaotuan.cli.cmd_chat import _offer_keep_original_config

    cfg = _cfg_dual_key(qxt_home)
    os.environ["DEEPSEEK_API_KEY"] = "sk-old"
    monkeypatch.setattr("builtins.input", lambda *a, **k: "n")
    _offer_keep_original_config(cfg, _Chosen("moonshot", "MOONSHOT_API_KEY"))
    assert read_api_key("DEEPSEEK_API_KEY") is None
    assert "DEEPSEEK_API_KEY" not in os.environ
    # 新供应商的密钥不受影响
    assert read_api_key("MOONSHOT_API_KEY") == "sk-ms"


def test_offer_keep_original_same_provider_skips_prompt(qxt_home, monkeypatch, capsys):
    """同供应商换模型时不弹保留/删除, 也不删除任何配置。"""
    from qingxiaotuan.cli.cmd_chat import _offer_keep_original_config

    cfg = _cfg_dual_key(qxt_home)
    monkeypatch.setattr("builtins.input", lambda *a, **k: "n")  # 不应被调用
    _offer_keep_original_config(cfg, _Chosen("deepseek", "DEEPSEEK_API_KEY"))
    assert read_api_key("DEEPSEEK_API_KEY") == "sk-old"


@pytest.mark.parametrize("cmd,env,expect_kept", [
    ("/provider clear", "DEEPSEEK_API_KEY", ["MOONSHOT_API_KEY"]),
    ("/provider clear MOONSHOT_API_KEY", "MOONSHOT_API_KEY", ["DEEPSEEK_API_KEY"]),
])
def test_provider_clear(qxt_home, capsys, cmd, env, expect_kept):
    """`/provider clear [ENV]` 从 .env 与当前环境删除指定密钥, 其他密钥不受影响。"""
    from qingxiaotuan.cli.cmd_slash import _handle_slash

    _cfg_dual_key(qxt_home)
    cfg = Config()
    assert _handle_slash(cmd, _FakeAgent(), cfg, os.getcwd()) is True
    assert read_api_key(env) is None
    assert env not in os.environ
    for kept in expect_kept:
        assert read_api_key(kept) is not None


def test_provider_set_then_clear_roundtrip(qxt_home, capsys):
    """set -> 可见/持久化 -> clear 后再 set 正常。"""
    from qingxiaotuan.cli.cmd_slash import _handle_slash

    cfg = Config()
    _handle_slash("/provider set DEEPSEEK_API_KEY sk-new", _FakeAgent(), cfg, os.getcwd())
    assert os.environ["DEEPSEEK_API_KEY"] == "sk-new"
    assert read_api_key("DEEPSEEK_API_KEY") == "sk-new"
    _handle_slash("/provider clear DEEPSEEK_API_KEY", _FakeAgent(), cfg, os.getcwd())
    assert read_api_key("DEEPSEEK_API_KEY") is None