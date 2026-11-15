"""cmd_skills 单元测试 —— 技能/组件工坊 CLI。"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from tuan_cli.cli import cmd_skills as P


def _args(**kw) -> SimpleNamespace:
    base = dict(skills_action=None, name=None, craft_mode=False)
    base.update(kw)
    return SimpleNamespace(**base)


def _entry(name="foo", version="1.0.0", tags=None):
    return SimpleNamespace(name=name, version=version, tags=tags or [],
                           description="a skill", path=f"skills/{name}", kind="skill")


@pytest.fixture(autouse=True)
def _patch(monkeypatch, tmp_path):
    monkeypatch.setattr(P.console, "print", lambda *a, **k: None)
    monkeypatch.setattr(P, "_user_skills_dir", lambda: tmp_path / "skills")
    monkeypatch.setattr(P, "_user_craft_dir", lambda: tmp_path / "craft")
    monkeypatch.setattr(P, "_builtin_dir", lambda: tmp_path / "builtin")


# ============================================================ _list_remote


class TestListRemote:
    def test_empty(self, monkeypatch):
        monkeypatch.setattr(P.registry, "list_skills", lambda: [])
        assert P._list_remote(_args()) == 0

    def test_with_entries(self, monkeypatch):
        monkeypatch.setattr(P.registry, "list_skills",
                            lambda: [_entry("a"), _entry("b", tags=["ml"])])
        assert P._list_remote(_args()) == 0


# ============================================================ _install_one


class TestInstallOne:
    def test_no_name(self, monkeypatch):
        assert P._install_one(_args(name=None)) == 2

    def test_found_in_registry(self, monkeypatch, tmp_path):
        monkeypatch.setattr(P.registry, "list_skills", lambda: [_entry("x")])
        monkeypatch.setattr(P.registry, "install", lambda entry, dest: True)
        assert P._install_one(_args(name="x")) == 0

    def test_not_found_fallback(self, monkeypatch):
        monkeypatch.setattr(P.registry, "list_skills", lambda: [])
        monkeypatch.setattr(P.registry, "install", lambda entry, dest: True)
        monkeypatch.setattr(P.registry, "RegistryEntry",
                            lambda **kw: SimpleNamespace(**kw))
        assert P._install_one(_args(name="custom")) == 0

    def test_install_fails(self, monkeypatch):
        monkeypatch.setattr(P.registry, "list_skills", lambda: [_entry("x")])
        monkeypatch.setattr(P.registry, "install", lambda entry, dest: False)
        assert P._install_one(_args(name="x")) == 1


# ============================================================ _update_one


class TestUpdateOne:
    def test_no_name(self, monkeypatch):
        assert P._update_one(_args(name=None)) == 2

    def test_removes_old(self, monkeypatch, tmp_path):
        dest = tmp_path / "skills" / "x"
        dest.mkdir(parents=True)
        (dest / "f.txt").write_text("old")
        monkeypatch.setattr(P.registry, "list_skills", lambda: [_entry("x")])
        monkeypatch.setattr(P.registry, "install", lambda entry, dest: True)
        assert P._update_one(_args(name="x")) == 0
        assert not dest.exists() or not (dest / "f.txt").exists()


# ============================================================ _remove_one


class TestRemoveOne:
    def test_no_name(self, monkeypatch):
        assert P._remove_one(_args(name=None)) == 2

    def test_not_found(self, monkeypatch, tmp_path):
        assert P._remove_one(_args(name="ghost")) == 1

    def test_removes(self, monkeypatch, tmp_path):
        dest = tmp_path / "skills" / "x"
        dest.mkdir(parents=True)
        assert P._remove_one(_args(name="x")) == 0
        assert not dest.exists()


# ============================================================ _pull_all


class TestPullAll:
    def test_empty(self, monkeypatch):
        monkeypatch.setattr(P.registry, "list_skills", lambda: [])
        assert P._pull_all(_args()) == 1

    def test_success(self, monkeypatch):
        monkeypatch.setattr(P.registry, "list_skills",
                            lambda: [_entry("a"), _entry("b")])
        monkeypatch.setattr(P.registry, "install", lambda entry, dest: True)
        assert P._pull_all(_args()) == 0

    def test_skip_existing(self, monkeypatch, tmp_path):
        (tmp_path / "skills" / "a").mkdir(parents=True)
        monkeypatch.setattr(P.registry, "list_skills", lambda: [_entry("a")])
        monkeypatch.setattr(P.registry, "install", lambda entry, dest: True)
        assert P._pull_all(_args()) == 0

    def test_partial_fail(self, monkeypatch):
        monkeypatch.setattr(P.registry, "list_skills",
                            lambda: [_entry("a"), _entry("b")])
        monkeypatch.setattr(P.registry, "install",
                            lambda entry, dest: entry.name == "a")
        assert P._pull_all(_args()) == 1


# ============================================================ _list_installed


class TestListInstalled:
    def test_mgr_fail(self, monkeypatch):
        monkeypatch.setattr(P, "_find_skill_manager", lambda: None)
        assert P._list_installed(_args()) == 1

    def test_empty(self, monkeypatch):
        mgr = SimpleNamespace(list_all=lambda: [])
        monkeypatch.setattr(P, "_find_skill_manager", lambda: mgr)
        assert P._list_installed(_args()) == 0

    def test_with_skills(self, monkeypatch):
        skills = [SimpleNamespace(name="s1", origin="user", version="1.0", path="/x")]
        mgr = SimpleNamespace(list_all=lambda: skills)
        monkeypatch.setattr(P, "_find_skill_manager", lambda: mgr)
        assert P._list_installed(_args()) == 0

    def test_list_all_raises(self, monkeypatch):
        mgr = SimpleNamespace(list_all=lambda: (_ for _ in ()).throw(RuntimeError("x")))
        monkeypatch.setattr(P, "_find_skill_manager", lambda: mgr)
        assert P._list_installed(_args()) == 1


# ============================================================ _clear_cache


class TestClearCache:
    def test_ok(self, monkeypatch):
        called = []
        monkeypatch.setattr(P.registry, "clear_cache", lambda: called.append(1))
        assert P._clear_cache(_args()) == 0
        assert called == [1]


# ============================================================ _seed_builtin


class TestSeedBuiltin:
    def test_no_builtin(self, monkeypatch, tmp_path):
        monkeypatch.setattr(P, "_builtin_dir", lambda: tmp_path / "nope")
        assert P._seed_builtin(_args()) == 0

    def test_empty_builtin(self, monkeypatch, tmp_path):
        (tmp_path / "builtin").mkdir()
        monkeypatch.setattr(P, "_builtin_dir", lambda: tmp_path / "builtin")
        assert P._seed_builtin(_args()) == 0

    def test_seeds_new(self, monkeypatch, tmp_path):
        builtin = tmp_path / "builtin"
        skill = builtin / "my_skill"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text("# skill")
        monkeypatch.setattr(P, "_builtin_dir", lambda: builtin)
        assert P._seed_builtin(_args()) == 0
        assert (tmp_path / "skills" / "my_skill" / "SKILL.md").exists()

    def test_skips_existing(self, monkeypatch, tmp_path):
        builtin = tmp_path / "builtin"
        skill = builtin / "my_skill"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text("# new")
        dest = tmp_path / "skills" / "my_skill"
        dest.mkdir(parents=True)
        (dest / "SKILL.md").write_text("# old")
        monkeypatch.setattr(P, "_builtin_dir", lambda: builtin)
        assert P._seed_builtin(_args()) == 0
        assert (dest / "SKILL.md").read_text() == "# old"


# ============================================================ craft


class TestCraftList:
    def test_empty(self, monkeypatch):
        monkeypatch.setattr(P.registry, "list_craft", lambda: [])
        assert P._craft_list(_args()) == 0

    def test_with_entries(self, monkeypatch):
        monkeypatch.setattr(P.registry, "list_craft", lambda: [_entry("c1")])
        assert P._craft_list(_args()) == 0


class TestCraftInstall:
    def test_no_name(self, monkeypatch):
        assert P._craft_install(_args(name=None)) == 2

    def test_ok(self, monkeypatch):
        monkeypatch.setattr(P.registry, "list_craft", lambda: [_entry("c1")])
        monkeypatch.setattr(P.registry, "install", lambda entry, dest: True)
        assert P._craft_install(_args(name="c1")) == 0

    def test_not_found_fallback(self, monkeypatch):
        monkeypatch.setattr(P.registry, "list_craft", lambda: [])
        monkeypatch.setattr(P.registry, "install", lambda entry, dest: True)
        monkeypatch.setattr(P.registry, "RegistryEntry",
                            lambda **kw: SimpleNamespace(**kw))
        assert P._craft_install(_args(name="custom")) == 0

    def test_fail(self, monkeypatch):
        monkeypatch.setattr(P.registry, "list_craft", lambda: [_entry("c1")])
        monkeypatch.setattr(P.registry, "install", lambda entry, dest: False)
        assert P._craft_install(_args(name="c1")) == 1


# ============================================================ cmd_skills dispatch


class TestCmdSkillsDispatch:
    def _patch_registry(self, monkeypatch):
        monkeypatch.setattr(P.registry, "list_skills", lambda: [])
        monkeypatch.setattr(P.registry, "list_craft", lambda: [])
        monkeypatch.setattr(P.registry, "clear_cache", lambda: None)

    def test_default_list(self, monkeypatch):
        self._patch_registry(monkeypatch)
        assert P.cmd_skills(_args()) == 0

    def test_installed(self, monkeypatch):
        monkeypatch.setattr(P, "_find_skill_manager", lambda: None)
        assert P.cmd_skills(_args(skills_action="installed")) == 1

    def test_install_no_name(self, monkeypatch):
        self._patch_registry(monkeypatch)
        assert P.cmd_skills(_args(skills_action="install")) == 2

    def test_remove_no_name(self, monkeypatch):
        assert P.cmd_skills(_args(skills_action="remove")) == 2

    def test_pull(self, monkeypatch):
        self._patch_registry(monkeypatch)
        assert P.cmd_skills(_args(skills_action="pull")) == 1

    def test_cache(self, monkeypatch):
        self._patch_registry(monkeypatch)
        assert P.cmd_skills(_args(skills_action="cache")) == 0

    def test_seed(self, monkeypatch, tmp_path):
        monkeypatch.setattr(P, "_builtin_dir", lambda: tmp_path / "nope")
        assert P.cmd_skills(_args(skills_action="seed")) == 0

    def test_unknown(self, monkeypatch):
        assert P.cmd_skills(_args(skills_action="bogus")) == 2

    def test_craft_list(self, monkeypatch):
        self._patch_registry(monkeypatch)
        assert P.cmd_skills(_args(skills_action="craft-list")) == 0

    def test_craft_install(self, monkeypatch):
        self._patch_registry(monkeypatch)
        assert P.cmd_skills(_args(skills_action="craft-install")) == 2

    def test_craft_mode_via_flag(self, monkeypatch):
        self._patch_registry(monkeypatch)
        assert P.cmd_skills(_args(skills_action="list", craft_mode=True)) == 0
