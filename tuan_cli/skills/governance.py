"""技能治理 —— 对标 Kimi Code 的 sub-skill.review / sub-skill.consolidate。

三个纯函数能力 (CLI 与斜杠命令共用):
  - audit():       审计全部技能, 标记僵尸技能与元数据不全
  - consolidate(): 检测相似技能并提议合并 (默认 dry-run, 不改盘)
  - lint():        检查单个技能的 frontmatter 合法性与正文结构

设计原则:
  - 只读优先: audit/lint 永不改盘; consolidate 默认 dry_run=True。
  - 写保护: 内置 (builtin) 与项目级 (project) 技能只读, 合并时只动用户级文件。
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from .manager import ZOMBIE_DAYS, Skill, SkillManager

_LINK_RE = re.compile(r"\[[^\]]+\]\(([^)]+)\)")


@dataclass
class AuditRow:
    slug: str
    name: str
    origin: str
    use_count: int
    days_idle: float
    is_zombie: bool
    incomplete: bool
    valid: bool

    def as_dict(self) -> Dict[str, object]:
        return {
            "slug": self.slug, "name": self.name, "origin": self.origin,
            "use_count": self.use_count, "days_idle": round(self.days_idle, 1),
            "is_zombie": self.is_zombie, "incomplete": self.incomplete, "valid": self.valid,
        }


def _days_idle(s: Skill) -> float:
    if s.updated_at <= 0:
        # 从未记录更新时间: 按 use_count 判定 (0 视为长期僵尸候选)
        return float(ZOMBIE_DAYS + 1) if s.use_count == 0 else 0.0
    return max(0.0, (time.time() - s.updated_at) / 86400.0)


def audit(manager: SkillManager) -> List[AuditRow]:
    """审计全部技能: 僵尸 + 元数据不全 + frontmatter 合法性。"""
    rows: List[AuditRow] = []
    for s in manager.list_all():
        idle = _days_idle(s)
        zombie = idle >= ZOMBIE_DAYS and s.use_count == 0
        incomplete = (not s.description.strip()) or (not s.tags)
        valid = bool(s.name.strip())
        rows.append(AuditRow(
            slug=s.slug, name=s.name, origin=s.origin,
            use_count=s.use_count, days_idle=idle,
            is_zombie=zombie, incomplete=incomplete, valid=valid,
        ))
    return rows


# 来源优先级 (高 = 合并时保留)
_ORIGIN_RANK = {"project": 3, "user": 2, "extra": 1, "builtin": 0}


def _tokens(text: str) -> set:
    """简单分词: 英文单词 + CJK 单字 (中文无空格, 按字集合算重叠)。"""
    en = set(re.findall(r"[a-z0-9]+", text.lower()))
    cjk = set(re.findall(r"[一-鿿]", text))
    return en | cjk


def similarity(a: Skill, b: Skill) -> float:
    """两个技能的相似度: 标签 Jaccard 0.6 权重 + 名称/描述 token 重叠 0.4 权重。"""
    ta, tb = set(a.tags), set(b.tags)
    if ta or tb:
        tag_j = len(ta & tb) / max(1, len(ta | tb))
    else:
        tag_j = 0.0
    na = _tokens(a.name + " " + a.description + " " + a.short_description)
    nb = _tokens(b.name + " " + b.description + " " + b.short_description)
    if na or nb:
        tok = len(na & nb) / max(1, len(na | nb))
    else:
        tok = 0.0
    return 0.6 * tag_j + 0.4 * tok


@dataclass
class MergeProposal:
    keeper: Skill
    loser: Skill
    score: float
    writable: bool   # loser 是否为可写的用户级技能


def consolidate(
    manager: SkillManager,
    dry_run: bool = True,
    threshold: float = 0.7,
) -> List[MergeProposal]:
    """检测相似技能对, 返回合并提议。

    - 每对里来源优先级高者保留 (keeper), 低者并入 (loser)。
    - dry_run=True (默认): 只报告, 不改盘。
    - dry_run=False: 把 loser 正文追加进 keeper, 并删除 loser 文件
      (仅当 loser 是用户级 origin=='user' 时才删; 只读技能只报告不删)。
    """
    skills = manager.list_all()
    proposals: List[MergeProposal] = []
    seen = set()
    for i in range(len(skills)):
        for j in range(i + 1, len(skills)):
            a, b = skills[i], skills[j]
            if a.slug == b.slug:
                continue
            sc = similarity(a, b)
            if sc < threshold:
                continue
            def _keep_key(s):
                return (_ORIGIN_RANK.get(s.origin, 0), s.use_count,
                        len(s.description), len(s.tags))
            if _keep_key(a) >= _keep_key(b):
                keeper, loser = a, b
            else:
                keeper, loser = b, a
            key = (keeper.slug, loser.slug)
            if key in seen:
                continue
            seen.add(key)
            writable = loser.origin == "user"
            proposals.append(MergeProposal(keeper=keeper, loser=loser,
                                           score=round(sc, 3), writable=writable))
            if not dry_run and writable:
                _do_merge(manager, keeper, loser)
    return proposals


def _do_merge(manager: SkillManager, keeper: Skill, loser: Skill) -> None:
    """执行合并: loser 正文追加到 keeper, 删除 loser 文件。"""
    merged_body = keeper.body.rstrip() + f"\n\n---\n\n> 合并自相似技能 `{loser.slug}`:\n\n" + loser.body.strip() + "\n"
    manager.save(keeper.name, keeper.description, merged_body,
                 tags=keeper.tags, activation=keeper.activation,
                 triggers=keeper.triggers, priority=keeper.priority,
                 source=keeper.source)
    # 删除 loser 文件 (用户级, 直接在 manager.dir 下)
    loser_path: Path = manager.dir / f"{manager.slugify(loser.slug)}.md"
    if loser_path.exists():
        try:
            loser_path.unlink()
        except OSError:
            pass


def lint(manager: SkillManager, slug: str) -> List[str]:
    """检查单个技能: frontmatter 合法性 + 正文结构 + 链接有效性。返回问题列表。"""
    issues: List[str] = []
    s = manager.load(slug)
    if s is None:
        return [f"技能不存在: {slug}"]
    if not s.name.strip():
        issues.append("frontmatter 缺少 name")
    if len(s.description.strip()) < 10:
        issues.append("description 过短 (<10 字), 影响检索命中")
    if not s.tags:
        issues.append("缺少 tags 标签, 语义检索无法命中")
    if s.activation not in ("lazy", "auto", "always", "proactive"):
        issues.append(f"activation={s.activation!r} 非法, 应为 lazy/auto/always/proactive")
    # 正文结构: 至少 3 个步骤
    step_count = 0
    for line in s.body.splitlines():
        if re.match(r"^\d+[\.、)]\s", line.strip()):
            step_count += 1
    if step_count < 3:
        issues.append(f"正文步骤不足 (检测到 {step_count} 个有序步骤, 建议 ≥3)")
    # 链接有效性 (仅相对路径文件链接)
    for link in _LINK_RE.findall(s.body):
        if link.startswith(("http://", "https://", "mailto:")):
            continue
        target = (s.path.parent / link).resolve() if s.path.parent else None
        if target is not None and not target.exists():
            issues.append(f"相对链接不存在: {link}")
    return issues
