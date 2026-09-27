"""技能管理器: 加载 / 保存 / 检索 / 渲染 / 热度追踪 / 多仓库发现。

对标 Claude Code / Codex 的 Skills 子系统:
- 技能 = Markdown + frontmatter (SKILL.md 开放标准), 支持单文件与目录型技能包
- 同名保存 = refine (Hermes 语义): use_count 递增, 内容更新
- 原子写入 (临时文件 + os.replace): 崩溃不损坏磁盘技能
- 检索: 任务关键词 → 语义标签映射 + 名称/描述/内容打分 + 热度加权
- notify_used(): 技能被实际采用时热度自增, 让高频技能自然浮出

多仓库技能发现 (v0.2.017, 对标 Codex/Claude Code 可移植性):
  按优先级从高到低合并多个技能目录, 同名技能高优先级覆盖低优先级:
    1. 项目级: <workspace>/.qxt/skills/, <workspace>/.agents/skills/
       (生态: <workspace>/.claude/skills/, 即 Claude Code 项目技能)
    2. 用户级: <home>/skills/, <home>/.agents/skills/
       (生态: ~/.claude/skills/, ~/.hermes/skills/ 及其 profiles, 随 ecosystem.* 开关)
    3. 额外级: 配置 skills.extra_dirs 列出的目录
    4. 内置级: qingxiaotuan/resources/skills/builtin/
  写入始终落到用户级 <home>/skills/ (同名 refine 语义不变)。

frontmatter 超集 (v0.2.017, 对齐 Codex/Claude Code 开放标准):
  除 qxt 自有字段外, 识别并存储:
    display_name:                UI 展示名 (区别于文件名 slug)
    short_description:           ≤80 字简短描述 (列表视图)
    default_prompt:              /skill-name 无参数时的默认任务
    policy.allow_implicit_invocation:  是否允许隐式调用 (布尔)
  写入时输出全部字段, 旧文件完全向后兼容。
"""

from __future__ import annotations

import math
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_FRONT_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)

# 内置技能目录 (包内资源)
_BUILTIN_DIR = Path(__file__).resolve().parent.parent / "resources" / "skills" / "builtin"

# 僵尸技能判定: 超过该天数未使用且 use_count=0 视为僵尸
ZOMBIE_DAYS = 30


@dataclass
class Skill:
    """一个可复用技能: frontmatter 元数据 + Markdown 正文。"""

    name: str
    description: str
    body: str
    path: Path
    updated_at: float = 0.0
    use_count: int = 0
    tags: List[str] = field(default_factory=list)   # 语义标签: ["debugging", "python"]
    priority: int = 0                                # 越高越先注入
    # 扩展元数据 (向后兼容: 旧文件缺省即默认值)
    version: int = 1
    activation: str = "lazy"                         # lazy | auto | always | proactive
    triggers: List[str] = field(default_factory=list)
    source: str = "manual"                           # manual | self-improve | auto-distill
    # ---- frontmatter 超集 (Codex/Claude Code 开放标准) ----
    display_name: str = ""                            # UI 展示名
    short_description: str = ""                        # 列表视图简短描述
    default_prompt: str = ""                         # 无参数斜杠命令时的默认任务
    allow_implicit: bool = False                     # policy.allow_implicit_invocation
    # ---- 多仓库来源 (不写入 frontmatter, 仅内存标注) ----
    origin: str = "user"                              # project | user | builtin | extra

    @property
    def slug(self) -> str:
        """技能 slug (取文件名 stem; 目录型技能包取目录名)。"""
        if self.path.name == "SKILL.md":
            return self.path.parent.name
        return self.path.stem

    @property
    def ui_name(self) -> str:
        """UI 展示名: display_name 优先, 否则 name。"""
        return self.display_name or self.name

    @property
    def ui_description(self) -> str:
        """列表/注册表描述: short_description 优先, 否则 description。"""
        return self.short_description or self.description


class SkillManager:
    """基础技能管理器: 磁盘读写 + 语义检索 + 多仓库发现。"""

    def __init__(self, home: Path, memory_store=None,
                 workspace: Optional[Path] = None,
                 config: Any = None) -> None:
        self.home = Path(home)
        self.dir = self.home / "skills"          # 写入目标: 用户级
        self.dir.mkdir(parents=True, exist_ok=True)
        self.memory = memory_store                # 可选: 同步进 FTS 索引
        self.workspace = Path(workspace) if workspace else None
        self.config = config
        self._search_dirs = self._build_search_dirs()

    # ------------------------------------------------------------- 多仓库目录

    def _build_search_dirs(self) -> List[Tuple[Path, str]]:
        """按优先级从高到低构建技能搜索目录列表: [(path, origin), ...]。"""
        dirs: List[Tuple[Path, str]] = []
        # 1. 项目级 (最高优先级)
        if self.workspace is not None:
            dirs.append((self.workspace / ".qxt" / "skills", "project"))
            dirs.append((self.workspace / ".agents" / "skills", "project"))
        # 2. 用户级 (写入目标也在这一层)
        dirs.append((self.home / "skills", "user"))
        dirs.append((self.home / ".agents" / "skills", "user"))
        # 2.5 生态级: Claude Code / Hermes Agent 本机技能 (随 ecosystem.* 开关发现;
        #     目录不存在时 _discover 自动跳过 —— 这是"直接使用对方生态积累"的运行时通道)
        cc_enabled, hermes_enabled, hermes_home = True, True, ""
        if self.config is not None:
            try:
                cc_enabled = bool(self.config.get("ecosystem.claude_code.enabled", True))
                hermes_enabled = bool(self.config.get("ecosystem.hermes.enabled", True))
                hermes_home = str(self.config.get("ecosystem.hermes.home", "") or "")
            except Exception:  # noqa: BLE001 - 配置损坏时按默认开启
                pass
        if cc_enabled:
            if self.workspace is not None:
                dirs.append((self.workspace / ".claude" / "skills", "project"))
            dirs.append((Path.home() / ".claude" / "skills", "user"))
        if hermes_enabled:
            if not hermes_home:
                hermes_home = os.environ.get("HERMES_HOME", "")
            hh = Path(hermes_home).expanduser() if hermes_home else Path.home() / ".hermes"
            dirs.append((hh / "skills", "user"))
            prof = hh / "profiles"
            if prof.is_dir():
                for prof_dir in sorted(prof.iterdir()):
                    if prof_dir.is_dir():
                        dirs.append((prof_dir / "skills", "user"))
        # 3. 额外级 (配置 skills.extra_dirs)
        extra: List[str] = []
        if self.config is not None:
            try:
                val = self.config.get("skills.extra_dirs", [])
                if isinstance(val, (list, tuple)):
                    extra = [str(p) for p in val]
            except Exception:
                extra = []
        for extra_str in extra:
            dirs.append((Path(extra_str), "extra"))
        # 4. 内置级 (最低优先级)
        if _BUILTIN_DIR.exists():
            dirs.append((_BUILTIN_DIR, "builtin"))
        return dirs

    def reload_dirs(self) -> None:
        """重新计算搜索目录 (工作区/配置变化后调用)。"""
        self._search_dirs = self._build_search_dirs()

    def _discover(self) -> Dict[str, Tuple[Path, str]]:
        """扫描所有搜索目录, 返回 slug → (path, origin) 的映射。

        同名技能按目录优先级取最高者 (先扫描的目录优先)。
        支持两种技能形态:
          - 单文件: <dir>/<slug>.md
          - 目录型技能包: <dir>/<slug>/SKILL.md (目录内可含脚本/资源)
        """
        found: Dict[str, Tuple[Path, str]] = {}
        for dpath, origin in self._search_dirs:
            if not dpath.is_dir():
                continue
            # 单文件技能
            for md in sorted(dpath.glob("*.md")):
                slug = self.slugify(md.stem)
                if slug not in found:
                    found[slug] = (md, origin)
            # 目录型技能包: <slug>/SKILL.md
            for child in sorted(dpath.iterdir()):
                if not child.is_dir():
                    continue
                if child.name.startswith("."):
                    continue  # 隐藏目录 (如 Claude 安装暂存 .xxx-stage-*) 不是技能包
                skill_md = child / "SKILL.md"
                if skill_md.exists():
                    slug = self.slugify(child.name)
                    if slug not in found:
                        found[slug] = (skill_md, origin)
        return found

    # ------------------------------------------------------------- 工具

    @staticmethod
    def slugify(name: str) -> str:
        """技能名 → 文件名 slug (与旧版规则完全一致)。"""
        return re.sub(r"[^a-z0-9\-]+", "-", name.lower()).strip("-") or "skill"

    # ------------------------------------------------------------- 读写

    def save(self, name: str, description: str, body: str, **kwargs) -> Skill:
        """保存 (或改进) 一个技能。同名覆盖 = refine 语义, use_count 递增。

        始终写入用户级 <home>/skills/<slug>.md。
        """
        slug = self.slugify(name)
        path = self.dir / f"{slug}.md"
        old = self.load(slug)
        use_count = (old.use_count + 1) if old else 0
        skill = Skill(
            name=name, description=description, body=body.strip(),
            path=path, updated_at=time.time(), use_count=use_count,
            tags=list(old.tags) if old else [],
            priority=old.priority if old else 0,
            version=(old.version + 1) if old else 1,
            activation=old.activation if old else "lazy",
            triggers=list(old.triggers) if old else [],
            source=old.source if old else "manual",
            display_name=old.display_name if old else "",
            short_description=old.short_description if old else "",
            default_prompt=old.default_prompt if old else "",
            allow_implicit=old.allow_implicit if old else False,
            origin="user",
        )
        # kwargs 可覆盖超集字段 (蒸馏器/导入器使用)
        for k in ("display_name", "short_description", "default_prompt", "activation",
                  "triggers", "tags", "priority", "source"):
            if k in kwargs:
                setattr(skill, k, kwargs[k])
        self._write(skill)
        if self.memory:
            self.memory.index("skill", f"{name}: {description}\n{body}", source=path.name)
        return skill

    def notify_used(self, slug: str) -> Optional[Skill]:
        """标记技能被实际采用: 热度自增并落盘 (对标 CC 的 use 计数)。

        注意: 内置/项目级技能只读, 热度计数仅在内存对象上递增, 不落盘。
        """
        skill = self.load(slug)
        if skill is None:
            return None
        skill.use_count += 1
        skill.updated_at = time.time()
        if skill.origin == "user":
            self._write(skill)
        return skill

    def _write(self, skill: Skill) -> None:
        """原子写入: 临时文件 + os.replace, 崩溃/中断不损坏原技能。

        输出 frontmatter 超集全部字段 (有值才写), 旧字段完全向后兼容。
        """
        lines = [
            "---",
            f"name: {skill.name}",
            f"description: {skill.description}",
            f"updated_at: {int(skill.updated_at)}",
            f"use_count: {skill.use_count}",
            f"version: {skill.version}",
            f"activation: {skill.activation}",
            f"priority: {skill.priority}",
            f"tags: {', '.join(skill.tags)}",
        ]
        if skill.triggers:
            lines.append(f"triggers: {', '.join(skill.triggers)}")
        if skill.source and skill.source != "manual":
            lines.append(f"source: {skill.source}")
        # ---- frontmatter 超集 (有值才输出) ----
        if skill.display_name:
            lines.append(f"display_name: {skill.display_name}")
        if skill.short_description:
            lines.append(f"short_description: {skill.short_description}")
        if skill.default_prompt:
            lines.append(f"default_prompt: {skill.default_prompt}")
        if skill.allow_implicit:
            lines.append("policy.allow_implicit_invocation: true")
        lines.append("---")
        lines.append("")
        text = "\n".join(lines) + f"{skill.body.strip()}\n"
        tmp = skill.path.with_name(skill.path.name + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, skill.path)

    def load(self, slug: str) -> Optional[Skill]:
        """按优先级从高到低查找技能, 返回第一个命中的。"""
        slug = self.slugify(slug)
        for dpath, origin in self._search_dirs:
            # 单文件
            f = dpath / f"{slug}.md"
            if f.exists():
                return self._parse(f, origin=origin)
            # 目录型技能包
            pkg = dpath / slug / "SKILL.md"
            if pkg.exists():
                return self._parse(pkg, origin=origin)
        return None

    def _parse(self, path: Path, origin: str = "user") -> Skill:
        text = path.read_text(encoding="utf-8")
        meta: Dict[str, str] = {}
        body = text
        m = _FRONT_RE.match(text)
        if m:
            raw_meta = m.group(1)
            # 先按行解析简单 key: value; 嵌套 policy.xxx 也按点号键直接收
            for line in raw_meta.splitlines():
                if ":" in line and not line.startswith(" "):
                    k, v = line.split(":", 1)
                    meta[k.strip()] = v.strip()
            body = text[m.end():]
        tags_raw = meta.get("tags", "")
        if tags_raw.startswith("["):
            # YAML 列表格式: ["tag1", "tag2"]
            tags = [t.strip().strip('"').strip("'") for t in tags_raw.strip("[]").split(",")]
        else:
            tags = [t.strip() for t in tags_raw.split(",") if t.strip()]
        triggers_raw = meta.get("triggers", "")
        triggers = [t.strip().strip('"').strip("'")
                    for t in re.split(r"[,\[\]\"']+", triggers_raw) if t.strip()]
        # policy.allow_implicit_invocation (Codex 风格点号键)
        implicit_raw = meta.get("policy.allow_implicit_invocation", "").lower()
        allow_implicit = implicit_raw in ("true", "1", "yes", "on")
        return Skill(
            name=meta.get("name", path.stem),
            description=meta.get("description", ""),
            body=body.strip(),
            path=path,
            updated_at=float(meta.get("updated_at", 0) or 0),
            use_count=int(meta.get("use_count", 0) or 0),
            tags=tags,
            priority=int(meta.get("priority", 0) or 0),
            version=int(meta.get("version", 1) or 1),
            activation=meta.get("activation", "lazy"),
            triggers=triggers,
            source=meta.get("source", "manual"),
            display_name=meta.get("display_name", ""),
            short_description=meta.get("short_description", ""),
            default_prompt=meta.get("default_prompt", ""),
            allow_implicit=allow_implicit,
            origin=origin,
        )

    def list_all(self) -> List[Skill]:
        """合并所有搜索目录的技能, 同名取最高优先级, 按热度/时间排序。"""
        skills: List[Skill] = []
        for slug, (path, origin) in self._discover().items():
            try:
                skills.append(self._parse(path, origin=origin))
            except Exception:
                continue
        return sorted(skills, key=lambda s: (s.use_count, s.updated_at), reverse=True)

    # ------------------------------------------------------------- 导入

    def import_skill(self, src: Path) -> Optional[Skill]:
        """从 Claude Code/Codex 技能目录或单个 SKILL.md 导入到用户级 skills/。

        src 可以是:
          - 一个 SKILL.md 文件 (或任意 .md 技能文件)
          - 一个目录型技能包 (内含 SKILL.md), 整个目录复制到 <home>/skills/<slug>/
        返回导入后的 Skill; 失败返回 None。
        """
        src = Path(src)
        if not src.exists():
            return None
        if src.is_dir():
            skill_md = src / "SKILL.md"
            if not skill_md.exists():
                return None
            meta = self._parse(skill_md, origin="import")
            slug = self.slugify(meta.name or src.name)
            dst_dir = self.dir / slug
            if dst_dir.exists():
                import shutil
                shutil.rmtree(dst_dir, ignore_errors=True)
            import shutil
            shutil.copytree(src, dst_dir)
            # 目录型技能包落到 <home>/skills/<slug>/SKILL.md
            return self._parse(dst_dir / "SKILL.md", origin="user")
        else:
            # 单文件: 读取 frontmatter 后走 save 写入
            meta = self._parse(src, origin="import")
            return self.save(meta.name, meta.description, meta.body,
                             display_name=meta.display_name,
                             short_description=meta.short_description,
                             default_prompt=meta.default_prompt,
                             tags=meta.tags, triggers=meta.triggers)

    # ------------------------------------------------------------- 语义检索 (提到才读)

    # 任务关键词 → 技能标签 的语义映射表
    # 当用户任务包含左侧关键词时, 右侧标签的技能被激活
    _TASK_TAG_MAP = {
        # 调试
        "bug": ["debugging", "troubleshooting"],
        "fix": ["debugging", "troubleshooting"],
        "error": ["debugging", "troubleshooting"],
        "crash": ["debugging"],
        "exception": ["debugging"],
        "调试": ["debugging"],
        "修复": ["debugging", "troubleshooting"],
        # 重构
        "refactor": ["refactoring", "clean-code"],
        "重构": ["refactoring", "clean-code"],
        "clean": ["refactoring", "clean-code"],
        "restructure": ["refactoring"],
        # 测试
        "test": ["testing", "tdd"],
        "测试": ["testing", "tdd"],
        "coverage": ["testing"],
        "pytest": ["testing"],
        "unittest": ["testing"],
        # 架构
        "architecture": ["architecture", "design-pattern"],
        "架构": ["architecture", "design-pattern"],
        "design": ["architecture", "design-pattern"],
        "设计": ["frontend-design", "architecture", "design-pattern"],
        "module": ["architecture"],
        "模块": ["architecture"],
        # 代码编辑
        "edit": ["code-editing", "precise-edit"],
        "编辑": ["code-editing"],
        "修改": ["code-editing"],
        "改代码": ["code-editing"],
        "write code": ["code-editing"],
        # 性能
        "performance": ["performance", "optimization"],
        "性能": ["performance", "optimization"],
        "优化": ["performance", "optimization"],
        "slow": ["performance"],
        "内存": ["performance", "memory"],
        "memory": ["performance", "memory"],
        # 安全
        "security": ["security", "hardening"],
        "安全": ["security", "hardening"],
        "vulnerability": ["security"],
        "注入": ["security"],
        "injection": ["security"],
        # API
        "api": ["api-design", "rest"],
        "接口": ["api-design"],
        "endpoint": ["api-design"],
        "路由": ["api-design", "routing"],
        # 数据库
        "database": ["database", "sql"],
        "数据库": ["database", "sql"],
        "sql": ["database", "sql"],
        "migration": ["database"],
        # Git
        "git": ["git", "version-control"],
        "commit": ["git"],
        "branch": ["git"],
        "merge": ["git"],
        "rebase": ["git"],
        # 前端设计 (设计语言先行: 先定设计语言再做独特视觉决策)
        "界面": ["frontend-design", "ui"],
        "页面": ["frontend-design", "ui"],
        "布局": ["frontend-design", "ui"],
        "视觉": ["frontend-design", "aesthetics"],
        "网站": ["frontend-design"],
        "网页": ["frontend-design"],
        "海报": ["frontend-design", "aesthetics"],
        "落地页": ["frontend-design"],
        "仪表盘": ["frontend-design", "ui"],
        "调色": ["frontend-design", "aesthetics"],
        "配色": ["frontend-design", "aesthetics"],
        "字体": ["frontend-design", "aesthetics"],
        "landing": ["frontend-design"],
        "ui design": ["frontend-design"],
        "dashboard": ["frontend-design", "ui"],
        # 前端
        "frontend": ["frontend", "ui"],
        "前端": ["frontend", "ui"],
        "react": ["frontend", "react"],
        "vue": ["frontend", "vue"],
        "css": ["frontend", "css"],
        "html": ["frontend"],
        # DevOps
        "deploy": ["devops", "deployment"],
        "部署": ["devops", "deployment"],
        "ci": ["devops", "ci-cd"],
        "cd": ["devops", "ci-cd"],
        "docker": ["devops", "container"],
        "kubernetes": ["devops", "k8s"],
        # 文档
        "document": ["documentation"],
        "文档": ["documentation"],
        "readme": ["documentation"],
        "docstring": ["documentation"],
        # 类型
        "type": ["typing", "type-safety"],
        "类型": ["typing"],
        "mypy": ["typing"],
        # 日志
        "log": ["logging", "observability"],
        "日志": ["logging"],
        "monitor": ["observability"],
    }

    def search(self, query: str, limit: int = 5) -> List[Skill]:
        """语义匹配检索: 任务描述 → 标签映射 + 关键词打分, 返回最相关的技能。

        匹配策略 (提到才读):
        1. 从任务描述中提取关键词, 通过 _TASK_TAG_MAP 映射到语义标签
        2. 标签匹配的技能获得高权重
        3. 名称/描述/内容的关键词匹配作为补充
        4. 优先级 (priority) 与使用频率作为加分项
        """
        terms = [t.lower() for t in re.split(r"\s+", query) if len(t) > 1]
        if not terms:
            return []

        # 1. 从任务描述提取语义标签
        task_tags: set = set()
        for term in terms:
            task_tags.update(self._TASK_TAG_MAP.get(term, []))
        # 也检查多词组合 (如 "code review" → review tag)
        # CJK 双字词 (设计/前端/界面...) 有实义, 允许子串命中;
        # ASCII 双字词 (ci/cd/ui) 仍按 len>=3 子串匹配, 避免误伤 build/guide 等词。
        query_lower = query.lower()

        def _substring_key_ok(k: str) -> bool:
            if len(k) >= 3:
                return True
            if len(k) >= 2 and any("一" <= ch <= "鿿" for ch in k):
                return True
            return False

        for key, tags in self._TASK_TAG_MAP.items():
            if _substring_key_ok(key) and key in query_lower:
                task_tags.update(tags)

        scored = []
        for skill in self.list_all():
            score = 0.0

            # 标签匹配 (最高权重: 5 分/命中)
            if task_tags and skill.tags:
                tag_hits = task_tags.intersection(set(skill.tags))
                score += len(tag_hits) * 5.0

            # 名称/描述匹配 (3 分/命中) —— 超集: short_description 也参与
            hay = f"{skill.name} {skill.description} {skill.short_description}".lower()
            score += sum(3.0 for t in terms if t in hay)

            # 内容匹配 (1 分/命中)
            body = skill.body.lower()
            score += sum(1.0 for t in terms if t in body)

            # 优先级加分
            score += skill.priority * 0.5

            # 使用频率加分 (对数缩放, 避免高频技能永远霸榜)
            score += math.log1p(skill.use_count) * 0.3

            if score > 0:
                scored.append((score, skill))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [s for _, s in scored[:limit]]

    def activate_for_task(self, task_hint: str, limit: int = 5) -> List[Skill]:
        """为特定任务激活最相关的技能 (提到才读的核心入口)。

        与 search() 的区别:
        - 如果任务与任何技能都不相关, 返回空列表 (不注入无关技能)
        - 标签匹配的技能优先于纯关键词匹配
        """
        results = self.search(task_hint, limit=limit)
        if not results and task_hint.strip():
            # 无匹配: 不注入无关技能 (避免 system prompt 膨胀)
            return []
        return results

    def render_for_prompt(self, skills: List[Skill]) -> str:
        """渲染技能上下文 —— 注册表模式 (提到才读, 防上下文膨胀)。

        - activation=always/auto 的技能: 渲染完整正文 (始终需要的操作守则);
        - 其余 (lazy/proactive): 只渲染注册表条目 (名称 + 描述 + 触发词),
          并提示相关时先用 skill_read 读取完整 SKILL.md —— 正文按需加载。
        - 描述优先用 short_description (超集字段), 否则用 description。
        """
        if not skills:
            return ""
        parts = ["## 可复用技能 (按需加载: 相关技能先用 skill_read 读取完整步骤再执行)"]
        for s in skills:
            desc = s.short_description or s.description
            entry = f"- **{s.ui_name}** ({s.slug}): {desc}"
            if s.triggers:
                entry += f" 触发: {', '.join(s.triggers[:6])}"
            if s.activation in ("always", "auto"):
                entry += f"\n\n{s.body}"
            parts.append(entry)
        return "\n\n".join(parts)
