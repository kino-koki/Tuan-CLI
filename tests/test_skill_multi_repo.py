"""功能2: 技能加载器多仓库兼容 .agents/skills/ 测试。

覆盖:
  - 多目录技能发现 (project/user/builtin)
  - 同名覆盖优先级 (project > user > builtin)
  - 目录型技能包 (<dir>/SKILL.md) 加载
  - 额外目录配置 skills.extra_dirs
  - list 标注来源 origin
"""

from __future__ import annotations

from pathlib import Path

from qingxiaotuan.skills.manager import SkillManager


def _write(p: Path, text: str):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def test_multi_dir_discovery(tmp_path: Path):
    """用户级与项目级技能都应被发现。"""
    home = tmp_path / "home"
    ws = tmp_path / "ws"
    _write(home / "skills" / "user-only.md",
           "---\nname: UserOnly\ndescription: 用户级技能, 用于演示多目录发现\n---\nbody\n")
    _write(ws / ".agents" / "skills" / "proj-only.md",
           "---\nname: ProjOnly\ndescription: 项目级技能, 来自 .agents/skills\n---\nbody\n")
    mgr = SkillManager(home, workspace=ws)
    names = {s.slug: s.origin for s in mgr.list_all()}
    assert "user-only" in names
    assert "proj-only" in names
    assert names["user-only"] == "user"
    assert names["proj-only"] == "project"


def test_same_name_priority_project_over_user(tmp_path: Path):
    """同名技能: 项目级覆盖用户级。"""
    home = tmp_path / "home"
    ws = tmp_path / "ws"
    _write(home / "skills" / "dup.md",
           "---\nname: Dup\ndescription: 用户级版本\n---\nUSER VERSION\n")
    _write(ws / ".qxt" / "skills" / "dup.md",
           "---\nname: Dup\ndescription: 项目级版本\n---\nPROJECT VERSION\n")
    mgr = SkillManager(home, workspace=ws)
    s = mgr.load("dup")
    assert s is not None
    assert s.origin == "project"
    assert "PROJECT VERSION" in s.body


def test_directory_skill_package_load(tmp_path: Path):
    """目录型技能包 <dir>/SKILL.md 应被加载。"""
    home = tmp_path / "home"
    pkg = home / "skills" / "my-pkg"
    _write(pkg / "SKILL.md",
           "---\nname: MyPkg\ndescription: 一个带脚本资源的目录型技能包\n---\n# 正文\n步骤\n")
    _write(pkg / "helper.py", "print(1)\n")
    mgr = SkillManager(home)
    s = mgr.load("my-pkg")
    assert s is not None
    assert s.path.name == "SKILL.md"
    assert s.slug == "my-pkg"


def test_extra_dirs_config(tmp_path: Path):
    """skills.extra_dirs 配置的额外目录应被发现。"""
    home = tmp_path / "home"
    extra = tmp_path / "extra"
    _write(extra / "extra-skill.md",
           "---\nname: ExtraSkill\ndescription: 来自额外目录的技能\n---\nbody\n")

    class _Cfg:
        def __init__(self):
            self.home = home
        def get(self, key, default=None):
            if key == "skills.extra_dirs":
                return [str(extra)]
            return default

    mgr = SkillManager(home, config=_Cfg())
    slugs = {s.slug: s.origin for s in mgr.list_all()}
    assert "extra-skill" in slugs
    assert slugs["extra-skill"] == "extra"


def test_builtin_discovered_without_workspace(tmp_path: Path):
    """无 workspace 时仍能发现内置技能 (origin=builtin)。"""
    home = tmp_path / "home"
    mgr = SkillManager(home)
    origins = {s.slug: s.origin for s in mgr.list_all()}
    # 内置技能目录存在, 至少能发现一批 builtin
    assert origins, "应发现内置技能"
    assert "frontend-design" in origins
    assert origins["frontend-design"] == "builtin"


def test_import_skill_from_path(tmp_path: Path):
    """import_skill 应把外部技能拷到用户级。"""
    home = tmp_path / "home"
    src = tmp_path / "claude-skill"
    _write(src / "SKILL.md",
           "---\nname: ClaudeStyle\ndescription: 从 Claude Code 生态来的技能包\n---\n# 内容\n")
    mgr = SkillManager(home)
    s = mgr.import_skill(src)
    assert s is not None
    assert (home / "skills" / "claudestyle" / "SKILL.md").exists()
