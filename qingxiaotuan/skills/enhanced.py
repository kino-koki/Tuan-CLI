"""增强技能架构 —— 借鉴 Claude Code「提到才激活」但更强。

Claude Code 的 SKILL.md 是「提到才激活」: 用户/Agent 提到某个 skill 名字时,
系统把 SKILL.md 内容注入 prompt。这很轻量, 但有三个局限:
  1. 被动: 必须有人提到才能激活, 无法根据任务上下文主动注入
  2. 无依赖: 多个 skill 之间不能声明依赖关系
  3. 无条件: 不区分语言/项目类型/文件类型

青小团增强架构:
  四种激活模式 (activation):
    lazy    — 仅当显式提到 skill 名时激活 (对标 CC)
    auto    — 任务上下文匹配 triggers 时自动注入 (CC 没有)
    always  — 始终注入系统提示 (如安全规则)
    proactive — 上下文分析后主动注入, 甚至不需要用户提到 (更强)

  声明式 frontmatter:
    ---
    name: test-healer
    version: 2
    description: 自动修复测试失败
    activation: auto           # lazy | auto | always | proactive
    triggers:                  # auto/proactive 模式的匹配条件
      - pytest
      - test fail
      - tests broken
    provides:                  # 本 skill 提供的能力 (供依赖图)
      - test-repair
      - error-diagnosis
    requires:                  # 需要的能力 (自动注入依赖 skill)
      - error-diagnosis
    conditions:                # 附加激活条件
      languages: [python]     # 仅 Python 项目
      file_types: [*.py]      # 仅含 .py 文件时
      project_types: [pytest] # 仅 pytest 项目
    priority: 80               # 0-100, 越高越先注入
    scope: session             # session | project | global
    ---

  依赖图解析:
    1. 收集所有候选 skill (匹配 triggers 或 explicit mention)
    2. 解析 requires → 自动注入被依赖的 skill (递归)
    3. 拓扑排序 + priority 排序
    4. 去重后注入系统提示

  条件评估:
    - languages: 检测工作区中的文件扩展名 (.py→python, .ts→typescript 等)
    - file_types: glob 匹配工作区文件
    - project_types: 检测项目标记文件 (package.json→node, pyproject.toml→python 等)
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, FrozenSet, List, Optional, Set

_FRONT_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)

# 语言标记 → 文件扩展名映射
_LANG_EXTS = {
    "python": {".py"},
    "typescript": {".ts", ".tsx"},
    "javascript": {".js", ".jsx"},
    "go": {".go"},
    "rust": {".rs"},
    "java": {".java"},
    "c": {".c", ".h"},
    "cpp": {".cpp", ".hpp", ".cc"},
    "ruby": {".rb"},
    "php": {".php"},
    "shell": {".sh", ".bash", ".zsh"},
}

# 项目标记文件 → project_type 映射
_PROJECT_MARKERS = {
    "pyproject.toml": "python",
    "setup.py": "python",
    "requirements.txt": "python",
    "package.json": "node",
    "tsconfig.json": "node",
    "Cargo.toml": "rust",
    "go.mod": "go",
    "Gemfile": "ruby",
    "composer.json": "php",
    "Makefile": "make",
    "CMakeLists.txt": "cmake",
}


@dataclass
class SkillMeta:
    """增强 Skill 元数据: 声明式 frontmatter 解析结果。"""

    name: str
    description: str = ""
    body: str = ""
    path: Optional[Path] = None
    version: int = 1
    activation: str = "lazy"  # lazy | auto | always | proactive
    triggers: List[str] = field(default_factory=list)
    provides: List[str] = field(default_factory=list)
    requires: List[str] = field(default_factory=list)
    priority: int = 50  # 0-100
    scope: str = "session"  # session | project | global
    use_count: int = 0
    updated_at: float = 0.0

    # 条件
    languages: List[str] = field(default_factory=list)
    file_types: List[str] = field(default_factory=list)
    project_types: List[str] = field(default_factory=list)

    @property
    def is_auto(self) -> bool:
        return self.activation in ("auto", "proactive")

    @property
    def is_always(self) -> bool:
        return self.activation == "always"

    @property
    def is_proactive(self) -> bool:
        return self.activation == "proactive"


@dataclass
class ActivationContext:
    """激活上下文: 评估 skill 激活条件所需的信息。"""

    task_text: str = ""
    workspace: str = "."
    mentioned_skills: Set[str] = field(default_factory=set)
    detected_languages: Set[str] = field(default_factory=set)
    detected_project_types: Set[str] = field(default_factory=set)
    detected_files: List[str] = field(default_factory=list)


class EnhancedSkillManager:
    """增强技能管理器: 声明式能力 + 依赖图 + 条件激活。

    向后兼容旧版 SkillManager 的 save/load/list_all/search 方法,
    同时提供:
      - activate_skills(): 按上下文激活 skill 并解析依赖
      - resolve_dependencies(): 依赖图拓扑排序
      - evaluate_conditions(): 条件评估
    """

    def __init__(self, home: Path, memory_store=None) -> None:
        self.dir = home / "skills"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.memory = memory_store
        self._cache: Dict[str, SkillMeta] = {}
        self._cache_time: float = 0

    # ============================================================ 读写 (兼容旧版)

    def save(self, name: str, description: str, body: str, **kwargs) -> SkillMeta:
        """保存技能。同名覆盖 + use_count 递增。"""
        from .manager import SkillManager
        slug = re.sub(r"[^a-z0-9\-]+", "-", name.lower()).strip("-") or "skill"
        path = self.dir / f"{slug}.md"
        old = self.load(slug)
        use_count = (old.use_count + 1) if old else 0

        # 生成增强 frontmatter
        activation = kwargs.get("activation", "lazy")
        triggers = kwargs.get("triggers", [])
        provides = kwargs.get("provides", [])
        requires = kwargs.get("requires", [])
        priority = kwargs.get("priority", 50)
        scope = kwargs.get("scope", "session")
        languages = kwargs.get("languages", [])
        file_types = kwargs.get("file_types", [])
        project_types = kwargs.get("project_types", [])

        # 如果没有显式 triggers, 从 description 自动提取关键词
        if not triggers and activation in ("auto", "proactive"):
            triggers = self._extract_triggers(description + " " + body)

        text = (
            "---\n"
            f"name: {name}\n"
            f"description: {description}\n"
            f"version: {old.version + 1 if old else 1}\n"
            f"activation: {activation}\n"
            f"triggers: {triggers}\n"
            f"provides: {provides}\n"
            f"requires: {requires}\n"
            f"priority: {priority}\n"
            f"scope: {scope}\n"
            f"use_count: {use_count}\n"
            f"updated_at: {int(time.time())}\n"
        )
        if languages:
            text += f"languages: {languages}\n"
        if file_types:
            text += f"file_types: {file_types}\n"
        if project_types:
            text += f"project_types: {project_types}\n"
        text += "---\n\n" + body.strip() + "\n"

        path.write_text(text, encoding="utf-8")
        self._invalidate_cache()
        if self.memory:
            self.memory.index("skill", f"{name}: {description}\n{body}", source=path.name)
        return self.load(slug) or SkillMeta(name=name, description=description, body=body.strip(), path=path)

    def load(self, slug: str) -> Optional[SkillMeta]:
        path = self.dir / f"{slug}.md"
        if not path.exists():
            return None
        return self._parse(path)

    def _parse(self, path: Path) -> SkillMeta:
        text = path.read_text(encoding="utf-8")
        meta: Dict[str, Any] = {}
        m = _FRONT_RE.match(text)
        body = text
        if m:
            for line in m.group(1).splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    meta[k.strip()] = v.strip()
            body = text[m.end():]

        # 解析列表字段 (YAML 简单列表: "[a, b]" 或 "a, b")
        def _parse_list(val: str) -> List[str]:
            if not val:
                return []
            val = val.strip()
            if val.startswith("[") and val.endswith("]"):
                return [x.strip().strip("'\"") for x in val[1:-1].split(",") if x.strip()]
            return [x.strip() for x in val.split(",") if x.strip()]

        return SkillMeta(
            name=meta.get("name", path.stem),
            description=meta.get("description", ""),
            body=body.strip(),
            path=path,
            version=int(meta.get("version", 1) or 1),
            activation=meta.get("activation", "lazy"),
            triggers=_parse_list(meta.get("triggers", "")),
            provides=_parse_list(meta.get("provides", "")),
            requires=_parse_list(meta.get("requires", "")),
            priority=int(meta.get("priority", 50) or 50),
            scope=meta.get("scope", "session"),
            use_count=int(meta.get("use_count", 0) or 0),
            updated_at=float(meta.get("updated_at", 0) or 0),
            languages=_parse_list(meta.get("languages", "")),
            file_types=_parse_list(meta.get("file_types", "")),
            project_types=_parse_list(meta.get("project_types", "")),
        )

    def list_all(self) -> List[SkillMeta]:
        now = time.monotonic()
        if self._cache and now - self._cache_time < 10.0:
            return list(self._cache.values())
        skills = {}
        for p in sorted(self.dir.glob("*.md")):
            try:
                s = self._parse(p)
                skills[s.name] = s
            except Exception:
                pass
        self._cache = skills
        self._cache_time = now
        return list(skills.values())

    def _invalidate_cache(self) -> None:
        self._cache.clear()
        self._cache_time = 0

    # ============================================================ 激活 (新增核心)

    def activate_skills(
        self,
        ctx: ActivationContext,
        explicit_mentions: Optional[List[str]] = None,
    ) -> List[SkillMeta]:
        """根据上下文激活 skill, 解析依赖, 返回最终注入列表。

        激活流程:
        1. 收集候选 skill:
           - always: 始终激活
           - lazy: 仅当 explicit_mentions 包含 skill 名
           - auto: triggers 匹配 task_text
           - proactive: triggers 匹配 + 条件满足
        2. 解析 requires 依赖 (递归注入被依赖 skill)
        3. 拓扑排序 + priority 排序
        4. 去重
        """
        all_skills = {s.name: s for s in self.list_all()}
        mentions = set(explicit_mentions or ctx.mentioned_skills)
        activated: Dict[str, SkillMeta] = {}

        # Phase 1: 基础激活
        for name, skill in all_skills.items():
            if skill.is_always:
                activated[name] = skill
                continue
            if name in mentions:
                activated[name] = skill
                continue
            if skill.activation in ("auto", "proactive"):
                if self._triggers_match(skill.triggers, ctx.task_text):
                    if self._evaluate_conditions(skill, ctx):
                        activated[name] = skill
                        continue
            if skill.is_proactive:
                if self._evaluate_conditions(skill, ctx):
                    activated[name] = skill

        # Phase 2: 依赖解析 (递归)
        resolved = set()
        queue = list(activated.keys())
        while queue:
            name = queue.pop(0)
            if name in resolved:
                continue
            resolved.add(name)
            skill = all_skills.get(name)  # type: ignore[assignment]  # 键必然存在且非 None
            if not skill:
                continue
            for req in skill.requires:
                if req not in resolved:
                    # 查找提供该能力的 skill
                    provider = self._find_provider(req, all_skills)
                    if provider and provider.name not in activated:
                        activated[provider.name] = provider
                        queue.append(provider.name)

        # Phase 3: 排序 (priority desc, 然后 name asc)
        result = sorted(
            activated.values(),
            key=lambda s: (-s.priority, s.name),
        )

        return result

    def _triggers_match(self, triggers: List[str], task_text: str) -> bool:
        """检查 triggers 是否匹配任务文本。"""
        if not triggers:
            return False
        task_lower = task_text.lower()
        return any(t.lower() in task_lower for t in triggers)

    def _evaluate_conditions(self, skill: SkillMeta, ctx: ActivationContext) -> bool:
        """评估 skill 的附加条件。"""
        # 语言条件
        if skill.languages:
            if not any(lang in ctx.detected_languages for lang in skill.languages):
                return False
        # 项目类型条件
        if skill.project_types:
            if not any(pt in ctx.detected_project_types for pt in skill.project_types):
                return False
        # 文件类型条件 (glob 匹配)
        if skill.file_types:
            import fnmatch
            matched = any(
                fnmatch.fnmatch(f, pat)
                for f in ctx.detected_files
                for pat in skill.file_types
            )
            if not matched:
                return False
        return True

    def _find_provider(self, capability: str, skills: Dict[str, SkillMeta]) -> Optional[SkillMeta]:
        """查找提供指定能力的 skill (按 priority 排序取最高的)。"""
        providers = [
            s for s in skills.values()
            if capability in s.provides
        ]
        if not providers:
            return None
        providers.sort(key=lambda s: -s.priority)
        return providers[0]

    # ============================================================ 上下文检测

    def detect_context(self, workspace: str) -> ActivationContext:
        """自动检测工作区上下文: 语言、项目类型、文件列表。"""
        ctx = ActivationContext(workspace=workspace)

        # 检测项目标记文件
        for marker, project_type in _PROJECT_MARKERS.items():
            if (Path(workspace) / marker).exists():
                ctx.detected_project_types.add(project_type)

        # 检测语言 (通过文件扩展名)
        try:
            import subprocess
            result = subprocess.run(
                ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
                capture_output=True, text=True, timeout=3, cwd=workspace,
            )
            files = result.stdout.strip().splitlines() if result.returncode == 0 else []
        except Exception:
            files = []
            try:
                for root, dirs, fnames in os.walk(workspace):
                    dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("node_modules", "__pycache__")]
                    for f in fnames:
                        files.append(os.path.relpath(os.path.join(root, f), workspace))
                        if len(files) >= 200:
                            break
                    if len(files) >= 200:
                        break
            except Exception:
                pass

        ctx.detected_files = files[:200]
        for f in files:
            ext = Path(f).suffix.lower()
            for lang, exts in _LANG_EXTS.items():
                if ext in exts:
                    ctx.detected_languages.add(lang)

        return ctx

    # ============================================================ 触发词提取

    @staticmethod
    def _extract_triggers(text: str) -> List[str]:
        """从文本中自动提取触发关键词。"""
        # 简单 TF 提取: 长度 > 3 的词, 去停用词
        stops = {
            "the", "and", "for", "that", "this", "with", "from", "are", "was",
            "have", "has", "can", "will", "not", "but", "all", "any", "its",
            "的", "是", "在", "了", "有", "不", "这", "个", "就", "也",
            "一个", "我们", "可以", "使用", "进行", "通过",
        }
        words = re.findall(r"[\w\u4e00-\u9fff]{3,}", text.lower())
        freq: Dict[str, int] = {}
        for w in words:
            if w not in stops:
                freq[w] = freq.get(w, 0) + 1
        # 取频率最高的 5 个词作为 triggers
        top = sorted(freq.items(), key=lambda x: -x[1])[:5]
        return [w for w, _ in top]

    # ============================================================ 渲染

    def render_for_prompt(self, skills: List[SkillMeta]) -> str:
        """把激活的 skill 渲染为系统提示注入文本。"""
        if not skills:
            return ""
        parts = ["## 已激活技能 (来自过往经验, 优先复用并按需改进)\n"]
        for s in skills:
            tag = f"[{s.activation}]"
            parts.append(f"### {s.name} {tag}\n{s.description}\n\n{s.body}")
        return "\n\n".join(parts)

    def render_catalog(self) -> str:
        """渲染所有 skill 的目录 (供 /skills 命令使用)。"""
        skills = self.list_all()
        if not skills:
            return "暂无技能。使用 skill_save 工具保存可复用的方法。"
        lines = ["可用技能:\n"]
        for s in sorted(skills, key=lambda x: (-x.priority, x.name)):
            act_tag = f" ({s.activation})" if s.activation != "lazy" else ""
            deps = f" ← {', '.join(s.requires)}" if s.requires else ""
            lines.append(f"  {s.name}{act_tag} — {s.description}{deps}")
        return "\n".join(lines)
