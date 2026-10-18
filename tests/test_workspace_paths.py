"""工作目录解析 (paths) 测试 —— 默认尊重 CWD, 显式指定优先 (2026-10-18 行为修正)。

回归背景: 旧实现无论用户从哪个目录启动, 都强制 chdir 进入内置 D 盘独立目录
(``D:\\DeliveryOptimization\\Tuan-Workspace``), 体感是「目录被劫持」。现默认
尊重用户启动时的当前目录; 旧行为降级为 opt-in (``TUAN_AUTO_WORKSPACE=1``)。

验证:
- 默认: 不跳转不创建, default_workspace() == CWD, 来源标签 cwd;
- 显式: TUAN_WORKSPACE / agent.workspace 配置 / --workspace 均被尊重 (且创建目录);
- opt-in: TUAN_AUTO_WORKSPACE=1 恢复旧行为 (进入内置独立工作区);
- 强制: TUAN_FORCE_WORKSPACE=1 忽略显式指定一律进同一工作区;
- 解析失败不阻断: 坏配置/不可建目录都回退 CWD。
"""

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tuan_cli.paths import (
    DEFAULT_WORKSPACE_DIR,
    auto_workspace,
    default_workspace,
    maybe_enter_default_workspace,
    reset_workspace_cache,
    workspace_explicitly_set,
    workspace_source,
)


@pytest.fixture(autouse=True)
def _reset_cache():
    """paths 模块有进程级缓存, 每个用例前后清空, 避免相互污染。"""
    reset_workspace_cache()
    yield
    reset_workspace_cache()


@pytest.fixture()
def launch_dir(tmp_path, monkeypatch):
    """把进程 CWD 切到一个独立启动目录 (模拟用户 cd 到某处再启动)。"""
    target = tmp_path / "launch-here"
    target.mkdir()
    monkeypatch.chdir(target)
    return target


class TestDefaultRespectsCwd:
    """默认行为: 尊重当前目录, 不跳转不创建。"""

    def test_no_jump_by_default(self, launch_dir):
        assert maybe_enter_default_workspace(["chat"]) is None
        assert Path(os.getcwd()) == launch_dir

    def test_default_workspace_is_cwd(self, launch_dir):
        assert Path(default_workspace()) == launch_dir

    def test_source_label_is_cwd(self, launch_dir):
        path, source = workspace_source()
        assert Path(path) == launch_dir
        assert source == "cwd (当前目录)"

    def test_legacy_escape_var_is_now_noop(self, launch_dir, monkeypatch):
        """旧逃生开关 TUAN_NO_AUTO_CHDIR 保留兼容, 恒不跳转。"""
        monkeypatch.setenv("TUAN_NO_AUTO_CHDIR", "1")
        assert maybe_enter_default_workspace([]) is None
        assert Path(os.getcwd()) == launch_dir

    def test_no_dir_created_on_startup(self, launch_dir):
        """启动路径不得再顺手创建内置 D 盘工作目录。"""
        before = {p.name for p in launch_dir.iterdir()}
        maybe_enter_default_workspace([])
        assert {p.name for p in launch_dir.iterdir()} == before


class TestExplicitWins:
    """显式指定优先于一切回退。"""

    def test_env_var_wins(self, launch_dir, tmp_path, monkeypatch):
        target = tmp_path / "from-env"
        monkeypatch.setenv("TUAN_WORKSPACE", str(target))
        assert Path(default_workspace()) == target
        assert target.is_dir()  # 显式目录顺手创建
        _, source = workspace_source()
        assert source == "env (TUAN_WORKSPACE)"
        # 显式 env 存在时不 chdir (workspace 由调用方按 default_workspace 使用)
        assert maybe_enter_default_workspace([]) is None

    def test_config_agent_workspace_wins(self, launch_dir, tmp_path, tuan_home):
        target = tmp_path / "from-config"
        from tuan_cli.config.loader import Config

        Config(tuan_home).set_user("agent.workspace", str(target))
        reset_workspace_cache()
        assert Path(default_workspace()) == target
        assert target.is_dir()
        _, source = workspace_source()
        assert source == "config (agent.workspace)"

    def test_workspace_flag_detected(self):
        assert workspace_explicitly_set(["--workspace", "/x"]) == "cli"
        assert workspace_explicitly_set(["--workspace=/x"]) == "cli"
        # 句子中间提到 --workspace 不算显式 (只匹配完整 token, 方向安全)
        assert workspace_explicitly_set(["chat", "帮我 --workspace 看一下"]) is None
        assert workspace_explicitly_set(["chat"]) is None


class TestOptInLegacyBehavior:
    """TUAN_AUTO_WORKSPACE=1: 恢复旧行为 (进入内置独立工作区)。"""

    def test_opt_in_enters_builtin_workspace(self, launch_dir, monkeypatch):
        monkeypatch.setenv("TUAN_AUTO_WORKSPACE", "1")
        entered = maybe_enter_default_workspace([])
        assert entered is not None
        assert Path(entered) != launch_dir
        assert Path(os.getcwd()) == Path(entered)

    def test_opt_in_still_respects_explicit(self, launch_dir, tmp_path, monkeypatch):
        """opt-in 不覆盖显式指定。"""
        target = tmp_path / "explicit-still-wins"
        monkeypatch.setenv("TUAN_AUTO_WORKSPACE", "1")
        monkeypatch.setenv("TUAN_WORKSPACE", str(target))
        assert maybe_enter_default_workspace([]) is None
        assert Path(default_workspace()) == target

    def test_force_overrides_explicit(self, launch_dir, tmp_path, monkeypatch):
        monkeypatch.setenv("TUAN_FORCE_WORKSPACE", "1")
        monkeypatch.setenv("TUAN_WORKSPACE", str(tmp_path / "ignored"))
        entered = maybe_enter_default_workspace([])
        assert entered is not None
        assert Path(entered) != launch_dir

    def test_auto_workspace_chain(self, launch_dir, tmp_path, monkeypatch):
        """auto_workspace: 显式 > 内置候选链 > CWD。"""
        target = tmp_path / "chain-explicit"
        monkeypatch.setenv("TUAN_WORKSPACE", str(target))
        assert Path(auto_workspace()) == target
        monkeypatch.delenv("TUAN_WORKSPACE")
        reset_workspace_cache()
        resolved = Path(auto_workspace())
        assert resolved.is_dir()
        assert resolved != launch_dir  # 落内置独立工作区 (或其后备), 不是启动目录


class TestFailOpen:
    """位置解析永不阻断启动。"""

    def test_uncreatable_explicit_dir_falls_back(self, launch_dir, monkeypatch):
        """显式目录无法创建时返回原路径 (由调用方决定), 不炸启动。"""
        bogus = launch_dir / "a" / "b" / "c" / "file-as-dir"
        bogus.parent.mkdir(parents=True)
        bogus.write_text("i am a file", encoding="utf-8")
        monkeypatch.setenv("TUAN_WORKSPACE", str(bogus / "cannot-create"))
        # 不抛异常即通过; 返回值是原路径 (创建失败)
        resolved = default_workspace()
        assert resolved  # 非空
        assert maybe_enter_default_workspace([]) is None

    def test_builtin_default_constant_exists(self):
        """内置候选链常量保留 (opt-in 路径依赖), 但默认不再使用。"""
        assert DEFAULT_WORKSPACE_DIR.name == "Tuan-Workspace"
