"""``tuan services`` CLI 的单元测试 (cmd_services.py)。

服务管理命令的 dispatch 层。覆盖:
1. build_kernel: 惰性转发到 app.build_kernel
2. __getattr__: 已知子模块转发 / 未知 AttributeError
3. cmd_plugin: build_kernel 失败 / 正常渲染 / provides 空
4. cmd_skill: 未知子命令 / build 失败不 panic (通过 mock SkillManager)
5. cmd_memory: list / search

通过 monkeypatch 打桩 build_kernel / SkillManager / MemoryStore, 避免真实启动内核。
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from tuan_cli.cli import cmd_services as S

# DSH 原生插件 bundle 源目录 (含 node_modules 依赖)
BUNDLE_DIR = r"G:\Tuan-CLI-Official\plugins\tuan-skills-bundle"


# ============================================================ build_kernel


class TestBuildKernel:
    def test_forwards_to_app(self, monkeypatch) -> None:
        called = {}

        def fake_build(*a, **k):
            called["a"] = a
            called["k"] = k
            return "KERNEL"

        import tuan_cli.app as app
        monkeypatch.setattr(app, "build_kernel", fake_build)
        rc = S.build_kernel("x", profile="y")
        assert rc == "KERNEL"
        assert called["a"] == ("x",)
        assert called["k"] == {"profile": "y"}


# ============================================================ __getattr__


class TestGetattr:
    def test_unknown_raises(self) -> None:
        with pytest.raises(AttributeError):
            _ = S.nonexistent_symbol_xyz

    def test_lazy_forwards_known(self, monkeypatch) -> None:
        # 通过注入 fake submodule 验证 importlib 路径 (直接改父包属性, 因真实模块已缓存)
        import types
        import tuan_cli.cli as pkg
        fake = types.SimpleNamespace(cmd_cron=lambda *a, **k: "CRON")
        monkeypatch.setattr(pkg, "cmd_cron", fake.cmd_cron, raising=False)
        assert callable(S.cmd_cron)


# ============================================================ cmd_plugin


class TestCmdPlugin:
    def test_build_failure(self, monkeypatch) -> None:
        # 新契约: handler 经 _get_plugin_manager 惰性构建 PluginManager;
        # 初始化失败须返回 1 而非崩溃。
        def boom(*a, **k):
            raise RuntimeError("boom")
        monkeypatch.setattr(S, "_get_plugin_manager", boom)
        monkeypatch.setattr(S.console, "print", lambda *a, **k: None)
        rc = S.cmd_plugin(SimpleNamespace())
        assert rc == 1

    def test_normal_render(self, monkeypatch) -> None:
        from pathlib import Path as _P

        def make_plugin(name, version="1.0.0", fmt="dsh_json",
                        enabled=True, desc="d"):
            return SimpleNamespace(
                manifest=SimpleNamespace(
                    name=name, version=version, format=fmt,
                    description=desc,
                ),
                enabled=enabled, path=_P("/tmp/x"),
            )

        class FakeMgr:
            plugins_dir = _P("/tmp/plugins")

            def list_plugins(self):
                return [make_plugin("config"), make_plugin("mcp")]

            def check_dsh_version(self):
                return "0.2.0"

        monkeypatch.setattr(S, "_get_plugin_manager", lambda *a, **k: FakeMgr())
        printed = []
        monkeypatch.setattr(S.console, "print",
                            lambda msg, *a, **k: printed.append(str(msg)))
        rc = S.cmd_plugin(SimpleNamespace())
        assert rc == 0
        text = "\n".join(printed)
        assert "config" in text
        assert "mcp" in text
        # DSH 版本行
        assert "0.2.0" in text

    def test_empty_list(self, monkeypatch) -> None:
        from pathlib import Path as _P

        class FakeMgr:
            plugins_dir = _P("/tmp/plugins")

            def list_plugins(self):
                return []

            def check_dsh_version(self):
                return None

        monkeypatch.setattr(S, "_get_plugin_manager", lambda *a, **k: FakeMgr())
        printed = []
        monkeypatch.setattr(S.console, "print",
                            lambda msg, *a, **k: printed.append(str(msg)))
        rc = S.cmd_plugin(SimpleNamespace())
        assert rc == 0
        text = "\n".join(printed)
        # 空列表提示
        assert "没有插件" in text

    def test_install_with_config_ok(self, monkeypatch, tmp_path) -> None:
        """tuan plugin install --config 合法: rc=0 且持久化 cordis.config.json。"""
        from tuan_cli.skills.plugin_sdk import PluginManager

        plugins_dir = tmp_path / "plugins"
        pm = PluginManager(plugins_dir)
        monkeypatch.setattr(S, "_get_plugin_manager", lambda *a, **k: pm)
        printed = []
        monkeypatch.setattr(S.console, "print",
                            lambda msg, *a, **k: printed.append(str(msg)))
        rc = S.cmd_plugin(SimpleNamespace(
            plugin_cmd="install",
            source=str(BUNDLE_DIR),
            name=None,
            config='{"rank": 42}',
        ))
        assert rc == 0
        cfg = plugins_dir / "tuan-skills-bundle" / "cordis.config.json"
        assert cfg.exists()
        import json
        assert json.loads(cfg.read_text(encoding="utf-8")).get("rank") == 42

    def test_install_with_bad_config_rejected(self, monkeypatch, tmp_path) -> None:
        """tuan plugin install --config 非法: rc=1 且目录清理。"""
        from tuan_cli.skills.plugin_sdk import PluginManager

        plugins_dir = tmp_path / "plugins"
        pm = PluginManager(plugins_dir)
        monkeypatch.setattr(S, "_get_plugin_manager", lambda *a, **k: pm)
        printed = []
        monkeypatch.setattr(S.console, "print",
                            lambda msg, *a, **k: printed.append(str(msg)))
        rc = S.cmd_plugin(SimpleNamespace(
            plugin_cmd="install",
            source=str(BUNDLE_DIR),
            name=None,
            config='{"rank": "bad"}',
        ))
        assert rc == 1
        assert not (plugins_dir / "tuan-skills-bundle").exists()

    def test_install_with_invalid_json_rejected(self, monkeypatch, tmp_path) -> None:
        """tuan plugin install --config 非法 JSON: rc=1。"""
        from tuan_cli.skills.plugin_sdk import PluginManager

        plugins_dir = tmp_path / "plugins"
        pm = PluginManager(plugins_dir)
        monkeypatch.setattr(S, "_get_plugin_manager", lambda *a, **k: pm)
        printed = []
        monkeypatch.setattr(S.console, "print",
                            lambda msg, *a, **k: printed.append(str(msg)))
        rc = S.cmd_plugin(SimpleNamespace(
            plugin_cmd="install",
            source=str(BUNDLE_DIR),
            name=None,
            config="not-json",
        ))
        assert rc == 1


# ============================================================ cmd_skill


class TestCmdSkill:
    def _skill(self, name="s1", desc="描述", origin="builtin", uses=3):
        return SimpleNamespace(
            ui_name=name, slug=name, origin=origin, use_count=uses,
            short_description=desc, description=desc, body="正文",
            default_prompt="", path="/tmp/x",
        )

    def test_list_empty(self, monkeypatch, tmp_path) -> None:
        import tuan_cli.cli.cmd_services as S

        class FakeMgr:
            def __init__(self, *a, **k):
                pass

            def list_all(self):
                return []

        monkeypatch.setattr(S, "SkillManager", FakeMgr)
        monkeypatch.setattr(S.console, "print", lambda *a, **k: None)
        rc = S.cmd_skill(SimpleNamespace(skill_cmd="list", profile="default",
                                         patch=None, cwd=str(tmp_path)))
        assert rc == 0

    def test_list_with_skills(self, monkeypatch, tmp_path) -> None:
        import tuan_cli.cli.cmd_services as S

        class FakeMgr:
            def __init__(self, *a, **k):
                pass

            def list_all(self):
                return [self._sk]

            _sk = SimpleNamespace(
                ui_name="s1", origin="builtin", use_count=3,
                short_description="d", description="dd",
            )

        monkeypatch.setattr(S, "SkillManager", FakeMgr)
        monkeypatch.setattr(S.console, "print", lambda *a, **k: None)
        rc = S.cmd_skill(SimpleNamespace(skill_cmd="list", profile="default",
                                         patch=None, cwd=str(tmp_path)))
        assert rc == 0

    def test_show_existing(self, monkeypatch, tmp_path) -> None:
        import tuan_cli.cli.cmd_services as S

        class FakeMgr:
            def __init__(self, *a, **k):
                pass

            def load(self, name):
                return SimpleNamespace(
                    ui_name="showme", slug="showme", origin="builtin",
                    description="d", body="# body", default_prompt="p",
                )

        monkeypatch.setattr(S, "SkillManager", FakeMgr)
        monkeypatch.setattr(S.console, "print", lambda *a, **k: None)
        rc = S.cmd_skill(SimpleNamespace(skill_cmd="show", name="showme",
                                         profile="default", patch=None,
                                         cwd=str(tmp_path)))
        assert rc == 0

    def test_show_missing(self, monkeypatch, tmp_path) -> None:
        import tuan_cli.cli.cmd_services as S

        class FakeMgr:
            def __init__(self, *a, **k):
                pass

            def load(self, name):
                return None

        monkeypatch.setattr(S, "SkillManager", FakeMgr)
        printed = []
        monkeypatch.setattr(S.console, "print",
                            lambda msg, *a, **k: printed.append(str(msg)))
        rc = S.cmd_skill(SimpleNamespace(skill_cmd="show", name="nope",
                                         profile="default", patch=None,
                                         cwd=str(tmp_path)))
        assert rc == 0
        assert any("不存在" in p for p in printed)

    def test_unknown_subcommand(self, monkeypatch, tmp_path) -> None:
        import tuan_cli.cli.cmd_services as S

        class FakeMgr:
            def __init__(self, *a, **k):
                pass

        monkeypatch.setattr(S, "SkillManager", FakeMgr)
        printed = []
        monkeypatch.setattr(S.console, "print",
                            lambda msg, *a, **k: printed.append(str(msg)))
        rc = S.cmd_skill(SimpleNamespace(skill_cmd="bogus", profile="default",
                                         patch=None, cwd=str(tmp_path)))
        assert rc == 1
        assert any("未知" in p for p in printed)


# ============================================================ cmd_memory


class TestCmdMemory:
    def test_list(self, monkeypatch, tmp_path) -> None:
        import tuan_cli.cli.cmd_services as S

        class FakeStore:
            def __init__(self, home):
                pass

            def get_stats(self):
                return {"memory_lines": 5, "user_lines": 2,
                        "fts_entries": 10, "tag_entries": 3}

        monkeypatch.setattr(S, "MemoryStore", FakeStore)
        monkeypatch.setattr(S.console, "print", lambda *a, **k: None)
        rc = S.cmd_memory(SimpleNamespace(memory_cmd="list", profile="default",
                                          patch=None))
        assert rc == 0

    def test_search(self, monkeypatch, tmp_path) -> None:
        import tuan_cli.cli.cmd_services as S

        class FakeStore:
            def __init__(self, home):
                pass

            def search(self, q):
                return [f"result-{q}-{i}" for i in range(15)]

        monkeypatch.setattr(S, "MemoryStore", FakeStore)
        printed = []
        monkeypatch.setattr(S.console, "print",
                            lambda msg, *a, **k: printed.append(str(msg)))
        rc = S.cmd_memory(SimpleNamespace(memory_cmd="search", query="hello",
                                          profile="default", patch=None))
        assert rc == 0
        # 只显示前 10 条
        assert len([p for p in printed if "result-hello" in p]) == 10

    def test_no_subcommand(self, monkeypatch, tmp_path) -> None:
        import tuan_cli.cli.cmd_services as S

        class FakeStore:
            def __init__(self, home):
                pass

        monkeypatch.setattr(S, "MemoryStore", FakeStore)
        monkeypatch.setattr(S.console, "print", lambda *a, **k: None)
        rc = S.cmd_memory(SimpleNamespace(memory_cmd=None, profile="default",
                                          patch=None))
        assert rc == 0


# ============================================================ DSH 原生 info


class TestPluginCmdInfoDsh:
    """tuan plugin info 对 DSH 原生插件展示完整契约 (inject 依赖/Config 字段/入口/技能)。"""

    @pytest.mark.skipif(not (Path(BUNDLE_DIR) / "lib" / "index.js").exists(),
                        reason="缺少 tuan-skills-bundle 原生插件")
    def test_info_shows_dsh_contract(self, capsys) -> None:
        from pathlib import Path
        from tuan_cli.skills.plugin_sdk import PluginManager

        pm = PluginManager(Path(BUNDLE_DIR).parent)
        rc = S._plugin_cmd_info(pm, "tuan-skills-bundle")
        out = capsys.readouterr().out
        assert rc == 0
        assert "DSH 原生: tuan-skills-bundle" in out
        # inject 依赖解析结果
        assert "inject 依赖:" in out
        assert "skills" in out
        # Config schema 字段类型
        assert "Config 字段:" in out
        assert "providerName:string" in out
        assert "rank:number" in out
        # 入口路径
        assert "入口:" in out
        assert "index.js" in out
        # 技能全量
        assert "DSH Provider 技能 (97)" in out
        # observeHostMutation 接线自检
        assert "host mutation 观测:" in out
        assert "✓" in out

    def test_info_host_mutation_not_wired_for_market(self, tmp_path, capsys) -> None:
        """市场型插件 (无原生入口) 不展示 host mutation 接线自检。"""
        from pathlib import Path
        from tuan_cli.skills.plugin_sdk import PluginManager

        pm = PluginManager(tmp_path)
        plugin_dir = tmp_path / "plain-plugin"
        plugin_dir.mkdir()
        (plugin_dir / "plugin.json").write_text(
            '{"name":"plain-plugin","version":"1.0.0","skills":[]}', encoding="utf-8")
        pm._scan()  # 手动扫描, 使 get_plugin 能找到目录中的插件
        rc = S._plugin_cmd_info(pm, "plain-plugin")
        out = capsys.readouterr().out
        assert rc == 0
        assert "host mutation 观测" not in out

    def test_info_shows_persisted_config(self, tmp_path, capsys) -> None:
        """install --config 持久化的 cordis.config.json 在 info 中展示为生效配置。"""
        from pathlib import Path
        from tuan_cli.skills.plugin_sdk import PluginManager

        pm = PluginManager(tmp_path)
        pm.install_from_directory(Path(BUNDLE_DIR), name="tuan-skills-bundle",
                                  config={"rank": 88})
        rc = S._plugin_cmd_info(pm, "tuan-skills-bundle")
        out = capsys.readouterr().out
        assert rc == 0
        assert "生效配置:" in out
        assert "88" in out

    @pytest.mark.skipif(not (Path(BUNDLE_DIR) / "lib" / "index.js").exists(),
                        reason="缺少 tuan-skills-bundle 原生插件")
    def test_patch_applies_to_target(self, tmp_path, capsys) -> None:
        """tuan plugin patch: 读取 cordis.patch.yml 并应用到目标 services 段。"""
        from pathlib import Path
        from tuan_cli.skills.plugin_sdk import PluginManager

        pm = PluginManager(Path(BUNDLE_DIR).parent)
        target = tmp_path / "cordis.yml"
        args = SimpleNamespace(name="tuan-skills-bundle", target=str(target), config=None)
        rc = S._plugin_cmd_patch(pm, args)
        out = capsys.readouterr().out
        assert rc == 0
        assert "patch 已应用" in out
        assert "tuan-skills-bundle" in out
        import yaml
        doc = yaml.safe_load(target.read_text(encoding="utf-8"))
        assert doc["services"][0]["id"] == "tuan-skills-bundle"
        assert doc["services"][0]["config"]["rank"] == 300
