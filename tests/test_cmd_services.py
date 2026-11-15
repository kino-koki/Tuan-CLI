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

from types import SimpleNamespace

import pytest

from tuan_cli.cli import cmd_services as S


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
        monkeypatch.setattr(S, "build_kernel",
                            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
        monkeypatch.setattr(S.console, "print", lambda *a, **k: None)
        rc = S.cmd_plugin(SimpleNamespace())
        assert rc == 1

    def test_normal_render(self, monkeypatch) -> None:
        kernel = SimpleNamespace(
            plugins={
                "config": SimpleNamespace(provides=["config"]),
                "mcp": SimpleNamespace(provides=[]),
            },
            services=SimpleNamespace(services=["service1", "service2"]),
        )
        monkeypatch.setattr(S, "build_kernel", lambda *a, **k: kernel)
        printed = []
        monkeypatch.setattr(S.console, "print",
                            lambda msg, *a, **k: printed.append(str(msg)))
        rc = S.cmd_plugin(SimpleNamespace())
        assert rc == 0
        text = "\n".join(printed)
        assert "插件列表" in text
        assert "config" in text
        assert "mcp" in text
        # services 渲染
        assert "service1" in text

    def test_provides_dash_when_empty(self, monkeypatch) -> None:
        kernel = SimpleNamespace(
            plugins={"mcp": SimpleNamespace(provides=[])},
            services=SimpleNamespace(services=[]),
        )
        monkeypatch.setattr(S, "build_kernel", lambda *a, **k: kernel)
        printed = []
        monkeypatch.setattr(S.console, "print",
                            lambda msg, *a, **k: printed.append(str(msg)))
        S.cmd_plugin(SimpleNamespace())
        text = "\n".join(printed)
        # 空 provides 用 "-" 占位
        assert "-" in text


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
