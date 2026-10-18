"""内置技能 seed / 发现 测试 (离线)。"""

from tuan_cli.app import build_kernel, seed_builtin_skills
from tuan_cli.config import Config
from tuan_cli.skills.manager import SkillManager, _BUILTIN_DIR


def test_builtin_skills_seeded_on_build(tuan_home):
    build_kernel()  # 首次启动触发 seed
    skills_dir = tuan_home / "skills"
    names = {p.name for p in skills_dir.glob("*.md")}
    for expected in [
        "frontend-mastery.md", "frontend-design.md",
        "anthropomorphic-comments.md", "code-review-checklist.md",
        "systematic-debugging.md", "test-driven-dev.md",
        "architecture-reading.md", "safe-refactor.md",
        "security-hardening.md", "api-design.md",
    ]:
        assert expected in names, f"缺失内置技能: {expected}"


def test_seed_is_idempotent(tuan_home):
    config = Config()
    config.ensure_home()  # 只建目录, 不 seed
    n1 = seed_builtin_skills(config)
    n2 = seed_builtin_skills(config)  # 同名不覆盖, 第二次应为 0
    assert n1 >= 8
    assert n2 == 0


def test_seeded_skill_loadable(tuan_home):
    kernel = build_kernel()
    manager = kernel.require("skill_manager")
    skill = manager.load("anthropomorphic-comments")
    assert skill is not None
    assert "AI 腔" in skill.body


class _NoEcosystem:
    """把生态级技能源 (Claude Code / Hermes) 全部关掉, 保证发现只落在内置层。"""

    def get(self, key, default=None):
        if str(key).startswith("ecosystem."):
            return False
        return default


def test_packaged_builtins_discovered(tmp_path, monkeypatch):
    """目录型技能包以 <pkg>/SKILL.md 为清单被发现, 而非 <pkg>/<name>.md。"""
    monkeypatch.delenv("HERMES_HOME", raising=False)
    mgr = SkillManager(tmp_path / ".tuan", config=_NoEcosystem())
    found = mgr._discover()
    assert found["tuan-code"][0].name == "SKILL.md", found["tuan-code"][0]
    assert found["tuan-design"][0].name == "SKILL.md", found["tuan-design"][0]
    assert found["tuan-novels"][0].name == "Tuan-novels.md"
    assert found["tuan-code"][1] == "builtin"
    assert mgr.load("tuan-design") is not None


def test_packaged_builtins_paths_resolve():
    """清单里的相对引用必须按技能包根解析成立 —— 清单与资源必须同层。

    历史回归: 清单曾放在 builtin/ 根而资源在 tuan-code/ 下,
    导致 references/、companies/ 全部指向不存在的路径。
    """
    layout = {
        "tuan-code": [
            "SKILL.md", "README.md",
            "references/index.md", "references/01-systems-foundations.md",
            "references/06-from-zero-to-ship.md", "scripts/preflight.py",
        ],
        "tuan-design": ["SKILL.md", "companies/index.md"],
    }
    for pkg, entries in layout.items():
        pkg_dir = _BUILTIN_DIR / pkg
        assert pkg_dir.is_dir(), f"缺少技能包: {pkg}"
        for rel in entries:
            assert (pkg_dir / rel).exists(), f"{pkg}: 清单引用的路径不存在 {rel}"

    # 被删除的 novels 资源库不应再有残留引用
    novels_dir = _BUILTIN_DIR / "novels"
    assert not novels_dir.exists(), "novels/ 已随拆解库下线, 不应再存在"
    for md in _BUILTIN_DIR.rglob("*.md"):
        text = md.read_text(encoding="utf-8")
        assert "novels/" not in text, f"{md.name} 仍引用已删除的 novels/"
