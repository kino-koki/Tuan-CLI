"""功能4: 技能治理命令测试 (audit / consolidate / lint)。

覆盖:
  - audit 报告包含僵尸技能标记与元数据不全标记
  - consolidate 检测相似技能
  - consolidate dry-run 不修改文件
  - lint 检查 frontmatter 合法性
  - lint 检查正文结构
"""

from __future__ import annotations

import time
from pathlib import Path

from qingxiaotuan.skills.manager import SkillManager
from qingxiaotuan.skills.governance import audit, consolidate, lint


def _write(p: Path, text: str):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def test_audit_flags_zombie_and_incomplete(tmp_path: Path):
    home = tmp_path / "home"
    mgr = SkillManager(home)
    # 僵尸技能: 30 天前更新且 use_count=0
    old = time.time() - 40 * 86400
    _write(home / "skills" / "zombie.md",
           f"---\nname: Zombie\ndescription: 一个僵尸技能的完整描述文字\n"
           f"tags: old\nupdated_at: {int(old)}\nuse_count: 0\n---\nbody\n")
    # 元数据不全: 缺 tags
    _write(home / "skills" / "thin.md",
           "---\nname: Thin\ndescription: 缺标签的技能描述\n---\nbody\n")
    rows = {r.slug: r for r in audit(mgr)}
    assert rows["zombie"].is_zombie is True
    assert rows["thin"].incomplete is True
    assert rows["thin"].use_count == 0


def test_consolidate_detects_similar(tmp_path: Path):
    home = tmp_path / "home"
    mgr = SkillManager(home)
    _write(home / "skills" / "refactor-a.md",
           "---\nname: RefactorA\ndescription: 重构 Python 代码, 拆分长函数, 清理坏味道\n"
           "tags: refactoring, clean-code, python\n---\nbody A\n")
    _write(home / "skills" / "refactor-b.md",
           "---\nname: RefactorB\ndescription: 重构 Python 代码, 拆分长函数, 清理坏味道\n"
           "tags: refactoring, clean-code, python\n---\nbody B\n")
    props = consolidate(mgr, dry_run=True, threshold=0.7)
    assert props, "两个高度相似的技能应被检测到"
    slugs = {props[0].keeper.slug, props[0].loser.slug}
    assert slugs == {"refactor-a", "refactor-b"}


def test_consolidate_dry_run_does_not_modify(tmp_path: Path):
    home = tmp_path / "home"
    mgr = SkillManager(home)
    _write(home / "skills" / "x.md",
           "---\nname: X\ndescription: 相似技能 X 的完整描述文字内容\n"
           "tags: same, tags, here\n---\nBODYX\n")
    _write(home / "skills" / "y.md",
           "---\nname: Y\ndescription: 相似技能 Y 的完整描述文字内容\n"
           "tags: same, tags, here\n---\nBODYY\n")
    before_x = (home / "skills" / "x.md").read_text(encoding="utf-8")
    before_y = (home / "skills" / "y.md").read_text(encoding="utf-8")
    consolidate(mgr, dry_run=True, threshold=0.5)
    after_x = (home / "skills" / "x.md").read_text(encoding="utf-8")
    after_y = (home / "skills" / "y.md").read_text(encoding="utf-8")
    assert before_x == after_x
    assert before_y == after_y  # dry-run 不删 loser


def test_consolidate_apply_merges_user_skill(tmp_path: Path):
    home = tmp_path / "home"
    mgr = SkillManager(home)
    _write(home / "skills" / "keep.md",
           "---\nname: Keep\ndescription: 保留技能的完整描述文字内容并且更长一些\n"
           "tags: mergeable, tags, set, extra\nuse_count: 3\n---\nKEEP BODY\n")
    _write(home / "skills" / "drop.md",
           "---\nname: Drop\ndescription: 被合并技能的完整描述文字内容\n"
           "tags: mergeable, tags, set\n---\nDROP BODY\n")
    props = consolidate(mgr, dry_run=False, threshold=0.5)
    assert props
    # keeper 描述更长且 use_count 更高, 应保留; loser 被删
    assert props[0].keeper.slug == "keep"
    assert not (home / "skills" / "drop.md").exists()
    keeper = mgr.load("keep")
    assert "DROP BODY" in keeper.body


def test_lint_detects_frontmatter_issues(tmp_path: Path):
    home = tmp_path / "home"
    mgr = SkillManager(home)
    _write(home / "skills" / "bad.md",
           "---\nname: Bad\ndescription: 短\ntags: \n---\n没有步骤\n")
    issues = lint(mgr, "bad")
    assert any("description" in i for i in issues)
    assert any("tags" in i for i in issues)


def test_lint_detects_body_structure(tmp_path: Path):
    home = tmp_path / "home"
    mgr = SkillManager(home)
    _write(home / "skills" / "nosteps.md",
           "---\nname: NoSteps\ndescription: 一个没有有序步骤的技能描述文字\n"
           "tags: demo\n---\n随便写写, 没有编号步骤\n")
    issues = lint(mgr, "nosteps")
    assert any("步骤" in i for i in issues)


def test_lint_clean_skill_no_issues(tmp_path: Path):
    home = tmp_path / "home"
    mgr = SkillManager(home)
    _write(home / "skills" / "good.md",
           "---\nname: Good\ndescription: 一个结构完整、描述充分的好技能\n"
           "tags: demo, testing\nactivation: lazy\n---\n"
           "1. 第一步收集上下文\n2. 第二步执行修改\n3. 第三步验证结果\n")
    assert lint(mgr, "good") == []
