"""技能桥接层 —— 在 qxt / Claude Code / Hermes 之间双向搬运技能。

三方的技能都是 Markdown + frontmatter 的 ``SKILL.md`` 开放标准 (agentskills.io /
Claude Code Agent Skills), 因此可以无损互读:

- **导入**: 扫描 Claude Code (``.claude/skills``、``~/.claude/skills``) 与 Hermes
  (``~/.hermes/skills``、profiles) 的技能文件/目录包, 交给 ``SkillManager.import_skill``
  落到 qxt 用户级 ``<home>/skills/``。
- **导出**: 把 qxt 用户级技能写成**可移植目录包** ``<dest>/<slug>/SKILL.md``,
  该形态同时被 Claude Code 与 Hermes 原生识别。

本模块纯函数、可测: 只做发现与文件搬运, 不触碰 Agent 运行时。
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

from ..core import atomicio  # noqa: F401  (保持与项目原子写工具同源)
from .detect import EcosystemProbe

# 导出时保留给其它生态的可移植 frontmatter 键 (qxt 专有键不写, 避免噪音)。
_PORTABLE_KEYS = ("name", "description", "version", "tags", "activation", "triggers")


@dataclass
class SkillImportResult:
    imported: List[str] = field(default_factory=list)
    skipped: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


def find_skill_files(dirs: List[Path]) -> List[Path]:
    """扫描目录列表, 返回所有技能入口文件 (SKILL.md 或 <slug>.md)。"""
    out: List[Path] = []
    seen: set = set()
    for d in dirs:
        if not d.is_dir():
            continue
        # 目录型技能包: <dir>/<slug>/SKILL.md
        for child in sorted(d.iterdir()):
            if not child.is_dir():
                continue
            skill_md = child / "SKILL.md"
            if skill_md.exists() and child.name not in seen:
                seen.add(child.name)
                out.append(skill_md)
        # 单文件技能: <dir>/<slug>.md (SKILL.md 本身不属于单文件技能)
        for md in sorted(d.glob("*.md")):
            if md.name == "SKILL.md" or md.stem in seen:
                continue
            seen.add(md.stem)
            out.append(md)
    return out


def import_skills(
    skill_manager: object,
    probe: EcosystemProbe,
    *,
    sources: Tuple[str, ...] = ("claude_code", "hermes"),
) -> SkillImportResult:
    """把 Claude Code / Hermes 的技能导入 qxt 用户级技能库。

    skill_manager: 带 ``import_skill(Path)`` 的 SkillManager 实例 (鸭子类型)。
    sources: 只导入指定来源 (claude_code | hermes | 两者)。
    """
    result = SkillImportResult()
    if "claude_code" in sources:
        for f in find_skill_files(probe.claude_skills_dirs):
            _import_one(skill_manager, f, result)
    if "hermes" in sources:
        for f in find_skill_files(probe.hermes_skills_dirs):
            _import_one(skill_manager, f, result)
    return result


def _import_one(skill_manager: object, src: Path, result: SkillImportResult) -> None:
    try:
        imported = skill_manager.import_skill(src)  # type: ignore[attr-defined]
        if imported is not None:
            result.imported.append(imported.name)
        else:
            result.skipped.append(str(src))
    except Exception as exc:  # noqa: BLE001 - 单技能失败不阻断整体
        result.errors.append(f"{src.name}: {exc}")


def _portable_frontmatter(skill: object) -> str:
    """从 qxt Skill 对象提取可移植 frontmatter (跳过 qxt 专有计数字段)。"""
    lines = ["---"]
    for key in _PORTABLE_KEYS:
        val = getattr(skill, key, None)
        if val in (None, "", 0, False, ()):
            continue
        if isinstance(val, (list, tuple)):
            text = ", ".join(str(v) for v in val)
        elif isinstance(val, bool):
            text = "true" if val else "false"
        else:
            text = str(val)
        lines.append(f"{key}: {text}")
    lines.append("---")
    lines.append("")
    return "\n".join(lines)


def export_skills(skill_manager: object, dest_dir: Path) -> SkillImportResult:
    """把 qxt 用户级技能导出为可移植目录包到 dest_dir。

    目标形态: ``<dest>/<slug>/SKILL.md`` —— Claude Code 的 ``.claude/skills`` 与
    Hermes 的 ``~/.hermes/skills`` 均原生识别这一形态。
    """
    result = SkillImportResult()
    try:
        skills = skill_manager.list_all()  # type: ignore[attr-defined]
    except Exception as exc:  # noqa: BLE001
        result.errors.append(f"读取技能失败: {exc}")
        return result
    user_skills = [s for s in skills if getattr(s, "origin", "") == "user"]
    for s in user_skills:
        slug = skill_manager.slugify(s.name)  # type: ignore[attr-defined]
        pkg_dir = dest_dir / slug
        try:
            pkg_dir.mkdir(parents=True, exist_ok=True)
            target = pkg_dir / "SKILL.md"
            text = _portable_frontmatter(s) + f"{s.body.strip()}\n"
            atomicio.atomic_write_text(target, text)
            result.imported.append(slug)
        except Exception as exc:  # noqa: BLE001
            result.errors.append(f"{slug}: {exc}")
    return result


__all__ = ["SkillImportResult", "find_skill_files", "import_skills", "export_skills"]
