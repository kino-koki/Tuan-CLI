"""``tuan setup`` / ``tuan bench`` / ``tuan open`` 的单元测试 (cmd_setup.py)。

不依赖交互式 input, 通过 monkeypatch mock build_kernel / input。
覆盖:
1. ``cmd_setup --skip`` 跳过路径 + ``TUAN_SKIP_SETUP=1`` 环境变量
2. 纯助手函数: persist_api_key、_ask_choice、_save_api_key、_ask_api_key
3. _setup_blank: 仅创建目录骨架, 不动模型配置
4. _setup_quick / _setup_full: 供应商选完写配置
5. cmd_bench 缺 API Key 时的 fail-fast
6. cmd_open: 文件不存在 / 路径解析
"""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from tuan_cli.cli import cmd_setup as S


# ============================================================ args 构造


def _args(**kw) -> SimpleNamespace:
    """构造 cmd_setup 的 args namespace (仅填测试关心的字段)。"""
    base = dict(skip=False, quick=False, target="")
    base.update(kw)
    return SimpleNamespace(**base)


# ============================================================ skip 路径


class TestSkipPath:
    """C-1.6: --skip / TUAN_SKIP_SETUP=1 快速跳过向导。"""

    def test_skip_flag(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr(S, "mark_onboarding_done", lambda: None, raising=False)
        import tuan_cli.cli.cmd_onboarding as OB

        called = []

        def fake_mark() -> None:
            called.append(1)

        monkeypatch.setattr(OB, "mark_onboarding_done", fake_mark)
        rc = S.cmd_setup(_args(skip=True))
        assert rc == 0
        assert called == [1]

    def test_skip_env_var(self, tmp_path, monkeypatch) -> None:
        import tuan_cli.cli.cmd_onboarding as OB

        called = []
        monkeypatch.setattr(OB, "mark_onboarding_done", lambda: called.append(1))
        monkeypatch.setenv("TUAN_SKIP_SETUP", "1")
        rc = S.cmd_setup(_args(skip=False))
        assert rc == 0
        assert called == [1]

    def test_skip_never_raises_on_mark_failure(self, monkeypatch) -> None:
        import tuan_cli.cli.cmd_onboarding as OB

        def boom() -> None:
            raise RuntimeError("disk full")

        monkeypatch.setattr(OB, "mark_onboarding_done", boom)
        rc = S.cmd_setup(_args(skip=True))
        assert rc == 0  # 标记写失败不影响跳过语义


# ============================================================ 纯助手函数


class TestPersistApiKey:
    """persist_api_key 幂等覆盖, 不累积重复行。"""

    def test_write_then_overwrite(self, tmp_path) -> None:
        from tuan_cli.config import persist_api_key

        p = persist_api_key("TEST_KEY_A", "first", home=tmp_path)
        assert p == tmp_path / ".env"
        assert "TEST_KEY_A=first" in p.read_text(encoding="utf-8")

        persist_api_key("TEST_KEY_A", "second", home=tmp_path)
        text = p.read_text(encoding="utf-8")
        assert "TEST_KEY_A=second" in text
        assert "TEST_KEY_A=first" not in text
        # 只有一行 TEST_KEY_A
        lines = [ln for ln in text.splitlines() if ln.startswith("TEST_KEY_A=")]
        assert len(lines) == 1

    def test_rejects_env_name_with_equals(self, tmp_path) -> None:
        from tuan_cli.config import persist_api_key

        # env 名含 "=" 视为非法 (防注入)
        with pytest.raises(Exception):
            persist_api_key("A=B", "x", home=tmp_path)


class TestAskChoice:
    """_ask_choice 默认值 + 非法输入回落。"""

    def test_valid_choice(self, monkeypatch) -> None:
        monkeypatch.setattr("builtins.input", lambda p="": "yolo")
        assert S._ask_choice(">", ["standard", "yolo"], "standard") == "yolo"

    def test_default_on_empty(self, monkeypatch) -> None:
        monkeypatch.setattr("builtins.input", lambda p="": "")
        assert S._ask_choice(">", ["standard", "yolo"], "standard") == "standard"

    def test_default_on_eof(self, monkeypatch) -> None:
        def raise_eof(p=""):
            raise EOFError

        monkeypatch.setattr("builtins.input", raise_eof)
        assert S._ask_choice(">", ["standard", "yolo"], "standard") == "standard"

    def test_invalid_falls_back(self, monkeypatch) -> None:
        monkeypatch.setattr("builtins.input", lambda p="": "not-a-mode")
        assert S._ask_choice(">", ["standard", "yolo"], "standard") == "standard"


# ============================================================ _setup_blank


class TestSetupBlank:
    """_setup_blank 只建目录骨架, 不写模型配置。"""

    def test_blank_creates_home(self, monkeypatch) -> None:
        calls = []

        class FakeCfg:
            def ensure_home(self) -> None:
                calls.append("ensure_home")

        monkeypatch.setattr(S.console, "print", lambda *a, **k: None)
        rc = S._setup_blank(FakeCfg())
        assert rc == 0
        assert calls == ["ensure_home"]


# ============================================================ _setup_quick / full


class FakeConfig:
    """记录 set_user 调用的假 config。"""

    def __init__(self) -> None:
        self.data: dict = {}
        self._home_created = False

    def set_user(self, key: str, value) -> None:
        self.data[key] = value

    def get(self, key: str, default=None):
        return self.data.get(key, default)

    def ensure_home(self) -> None:
        self._home_created = True

    def api_key(self) -> str:
        return self.data.get("api_key", "")


class TestSetupQuick:
    """_setup_quick: 供应商选完 -> 写 provider/model 配置。"""

    def test_writes_config(self, monkeypatch) -> None:
        monkeypatch.setattr(S.console, "print", lambda *a, **k: None)
        # 选第一个内置供应商, 并跳过 key 输入
        monkeypatch.setattr(S, "_pick_setup_provider",
                            lambda: ("deepseek", "deepseek-chat",
                                     "https://api.deepseek.com/v1", ""))
        cfg = FakeConfig()
        rc = S._setup_quick(cfg)
        assert rc == 0
        assert cfg.data["model.provider"] == "deepseek"
        assert cfg.data["model.model"] == "deepseek-chat"
        assert cfg.data["model.base_url"] == "https://api.deepseek.com/v1"

    def test_cancel_returns_zero(self, monkeypatch) -> None:
        monkeypatch.setattr(S.console, "print", lambda *a, **k: None)
        monkeypatch.setattr(S, "_pick_setup_provider", lambda: None)
        rc = S._setup_quick(FakeConfig())
        assert rc == 0


class TestSetupFull:
    """_setup_full: 在 quick 基础上增加 mode/effort/温度/max_tokens。"""

    def test_writes_full_config(self, monkeypatch) -> None:
        monkeypatch.setattr(S.console, "print", lambda *a, **k: None)
        monkeypatch.setattr(S, "_pick_setup_provider",
                            lambda: ("ollama", "llama3.1", "", ""))
        monkeypatch.setattr("builtins.input",
                            lambda p="": {"mode": "yolo", "effort": "medium",
                                          "temp": "0.5", "mt": "4096"}.get(
                                              p[:20].lower(), "0.5"))
        # 沙箱选项选 2 (仅审批, 不写 security.sandbox.enabled=True)
        monkeypatch.setattr(S, "_ask_sandbox_setup", lambda cfg: None)
        cfg = FakeConfig()
        rc = S._setup_full(cfg)
        assert rc == 0
        assert cfg.data["model.provider"] == "ollama"
        assert cfg.data["mode.default"] in ("standard", "yolo")
        assert "model.temperature" in cfg.data
        assert "model.max_tokens" in cfg.data


# ============================================================ cmd_bench


class TestBenchFailFast:
    """cmd_bench 缺 API Key 时 fail-fast, 不发起网络调用。"""

    def test_no_api_key_short_circuits(self, monkeypatch) -> None:
        monkeypatch.setattr(S.console, "print", lambda *a, **k: None)
        cfg = FakeConfig()  # api_key() == ""
        kernel = SimpleNamespace(require=lambda name: cfg if name == "config" else None)
        monkeypatch.setattr(S, "build_kernel", lambda *a, **k: kernel)
        args = SimpleNamespace(bench_cmd="cache", rounds=3, task="ping")
        rc = S.cmd_bench(args)
        assert rc == 1

    def test_no_subcommand_noop(self, monkeypatch) -> None:
        monkeypatch.setattr(S.console, "print", lambda *a, **k: None)
        rc = S.cmd_bench(SimpleNamespace(bench_cmd=None))
        assert rc == 0


# ============================================================ cmd_open


class TestCmdOpen:
    """cmd_open: 文件定位 (不存在/相对/绝对路径)。"""

    def test_no_target_shows_usage(self, monkeypatch) -> None:
        printed = []
        monkeypatch.setattr(S.console, "print", lambda msg, *a, **k: printed.append(str(msg)))
        rc = S.cmd_open(_args(target=""))
        assert rc == 1
        assert "用法" in printed[0]

    def test_nonexistent_file(self, monkeypatch, tmp_path) -> None:
        monkeypatch.setattr(S.console, "print", lambda *a, **k: None)
        rc = S.cmd_open(_args(target=str(tmp_path / "no_such_file.py")))
        assert rc == 1

    def test_existing_file_calls_open_in_editor(self, monkeypatch, tmp_path) -> None:
        f = tmp_path / "x.py"
        f.write_text("print('hi')\n", encoding="utf-8")
        monkeypatch.setattr(S.console, "print", lambda msg, *a, **k: None)
        opened = []
        import tuan_cli.tools.code as code

        monkeypatch.setattr(code, "_open_in_editor",
                            lambda path, line, editor: opened.append((path, line, editor)) or "ok")
        kernel = SimpleNamespace(
            require=lambda name: SimpleNamespace(get=lambda k, d="": ""))
        monkeypatch.setattr(S, "build_kernel", lambda *a, **k: kernel)
        rc = S.cmd_open(_args(target=f"{f}:42"))
        assert rc == 0
        assert len(opened) == 1
        assert opened[0][1] == 42

    def test_invalid_line_number(self, monkeypatch, tmp_path) -> None:
        monkeypatch.setattr(S.console, "print", lambda *a, **k: None)
        f = tmp_path / "y.py"
        f.write_text("x\n", encoding="utf-8")
        rc = S.cmd_open(_args(target=f"{f}:not-a-number"))
        assert rc == 1
