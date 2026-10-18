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


class TestBuiltinUpgradeSync:
    """内置技能升级必须能落到用户目录, 但绝不能覆盖用户的自行修改。

    历史行为是「同名不覆盖」, 导致用户目录里的副本永久遮蔽 builtin 层
    (manager._discover 先到先得) —— 我们在仓库里修 bug / 加章节, 用户端毫无感知。
    现改为按内容指纹区分: 未被用户改动 → 刷新; 被改过 → 原样保留。
    """

    def test_upgrade_refreshes_unmodified_builtin(self, tuan_home):
        import hashlib
        import json

        from tuan_cli.config import Config
        from tuan_cli.app import seed_builtin_skills, _sha256
        from tuan_cli.skills.manager import _BUILTIN_DIR

        config = Config()
        seed_builtin_skills(config)  # 首次播种

        dest = tuan_home / "skills" / "commit-and-pr-flow.md"
        manifest_path = tuan_home / "skills" / ".builtin-skills.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        # 构造「dest 是旧版内置内容, 清单记录旧版指纹, 源是新版」
        old = b"---\nname: OLD\n---\n\n# old\n"
        dest.write_bytes(old)
        manifest["commit-and-pr-flow.md"] = hashlib.sha256(old).hexdigest()
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

        n = seed_builtin_skills(config)
        assert n == 1, "未被用户改动的内置技能应被刷新"
        assert "安全提交与 PR 流程" in dest.read_text(encoding="utf-8")
        assert json.loads(manifest_path.read_text(encoding="utf-8"))["commit-and-pr-flow.md"] \
            == _sha256(_BUILTIN_DIR / "commit-and-pr-flow.md")

    def test_user_edit_is_never_overwritten(self, tuan_home):
        """用户改动后, 清单里仍是**播种时**的指纹 (用户不会去改清单),
        因此 dest 指纹与清单不符即判定为用户改动, 必须跳过刷新。"""
        from tuan_cli.config import Config
        from tuan_cli.app import seed_builtin_skills

        config = Config()
        seed_builtin_skills(config)   # 此时清单 = 源指纹

        dest = tuan_home / "skills" / "commit-and-pr-flow.md"
        dest.write_bytes(b"MY OWN EDIT\n")   # 用户改写; 清单不动

        n = seed_builtin_skills(config)
        assert n == 0, "用户改过的技能绝不能被覆盖"
        assert dest.read_text(encoding="utf-8").strip() == "MY OWN EDIT"

    def test_manifest_written_on_first_seed(self, tuan_home):
        from tuan_cli.config import Config
        from tuan_cli.app import seed_builtin_skills

        seed_builtin_skills(Config())
        mf = tuan_home / "skills" / ".builtin-skills.json"
        assert mf.exists(), "首次播种应写出指纹清单"
        import json
        assert len(json.loads(mf.read_text(encoding="utf-8"))) >= 8

    def test_no_builtin_skill_contains_emoji(self, tuan_home):
        """技能库自身必须零 emoji —— 否则与「零 emoji」硬规则自相矛盾,
        且模型读到技能里的 emoji 会被示范。"""
        from tuan_cli.core.output_sanitize import has_emoji
        from tuan_cli.skills.manager import _BUILTIN_DIR

        offenders = [
            str(p.relative_to(_BUILTIN_DIR))
            for p in sorted(_BUILTIN_DIR.rglob("*.md"))
            if has_emoji(p.read_text(encoding="utf-8"))
        ]
        assert not offenders, f"技能文件含 emoji: {offenders}"

    def test_force_refresh_overwrites_with_backup(self, tuan_home):
        """force=True 用内置版本覆盖全部同名技能, 且必须先备份。"""
        from tuan_cli.config import Config
        from tuan_cli.app import seed_builtin_skills

        config = Config()
        seed_builtin_skills(config)

        dest = tuan_home / "skills" / "commit-and-pr-flow.md"
        dest.write_bytes(b"STALE COPY\n")

        n = seed_builtin_skills(config, force=True)
        assert n >= 1
        assert "安全提交与 PR 流程" in dest.read_text(encoding="utf-8")

        backups = [p for p in (tuan_home / "skills").glob(".backup-*/commit-and-pr-flow.md")]
        assert backups, "force 覆盖前应留备份"
        assert backups[0].read_text(encoding="utf-8").strip() == "STALE COPY"

    def test_legacy_install_adopts_baseline(self, tuan_home):
        """无清单的老安装: 首次登记基线后, 内置再升级应能刷新。"""
        import hashlib
        import json

        from tuan_cli.config import Config
        from tuan_cli.app import seed_builtin_skills

        config = Config()
        seed_builtin_skills(config)
        dest = tuan_home / "skills" / "commit-and-pr-flow.md"
        mf = tuan_home / "skills" / ".builtin-skills.json"

        # 模拟老安装: 删掉清单, 并把 dest 换成"旧版内置"内容
        stale = b"---\nname: X\n---\n\n# stale\n"
        dest.write_bytes(stale)
        mf.unlink()

        seed_builtin_skills(config)                       # 登记基线
        m = json.loads(mf.read_text(encoding="utf-8"))
        assert m["commit-and-pr-flow.md"] == hashlib.sha256(stale).hexdigest()
        assert dest.read_bytes() == stale, "登记基线阶段不得改写内容"

        # 下一轮: 基线已登记, 用户又没动过, 而内置内容与基线不同 → 刷新到内置版。
        # 这正是老安装"补齐内置改进"想要的最终结果。
        n = seed_builtin_skills(config)
        assert n == 1
        assert "安全提交与 PR 流程" in dest.read_text(encoding="utf-8")

        # 再之后完全幂等
        assert seed_builtin_skills(config) == 0
