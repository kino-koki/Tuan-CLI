"""compact 后存活表 (对标 Claude Code 的「压缩后从磁盘重注入」契约)。

/doc 或上下文压缩 (/compact) 后, 对话历史会被摘要折叠, 但下列状态**不依赖对话历史**,
必须能从磁盘 / 配置 / 服务重新发现。本模块提供只读自检: 给定 home + workspace,
逐项检查这些状态在磁盘上是否可重建, 输出结构化报告。

对应文档: docs/compact_survival_guide.md
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List, Optional

from ...core.prompts import _discover_project_instructions
from ...memory.memory_notes import MemoryNotesStore, project_slug


@dataclass
class SurvivalItem:
    """单个存活状态检查项。"""
    name: str            # 状态名 (中文)
    source: str          # 重建来源 (磁盘路径 / 服务名)
    ok: bool             # 是否可从磁盘重建
    detail: str = ""     # 补充说明


def _exists(p: Path) -> bool:
    try:
        return p.exists()
    except OSError:
        return False


def check_survival_items(
    home: Path,
    workspace: str,
    config: Any = None,
    memory_store: Any = None,
    skill_manager: Any = None,
) -> List[SurvivalItem]:
    """逐项检查 compact 后必须重建的状态。只读, 不修改任何文件。"""
    home = Path(home)
    ws = Path(workspace)
    items: List[SurvivalItem] = []

    # 1. SOUL.md 身份: home/SOUL.md 存在即从磁盘读; 不存在则用内置回退文案 (仍可用)。
    soul = home / "SOUL.md"
    items.append(SurvivalItem(
        name="SOUL 身份",
        source=str(soul),
        ok=True,  # 总有回退文案, 不会缺失
        detail="存在" if _exists(soul) else "缺失, 使用内置回退文案",
    ))

    # 2. 分层项目指令: 重新发现 QXT.md / AGENTS.md / CLAUDE.md
    proj = _discover_project_instructions(workspace, home=home)
    items.append(SurvivalItem(
        name="项目指令",
        source="QXT.md/AGENTS.md/CLAUDE.md (分层发现)",
        ok=True,
        detail=f"发现 {proj.count('# ') } 段指令" if proj else "未发现项目指令文件 (正常)",
    ))

    # 3. MEMORY.md 笔记: projects/<slug>/memory/MEMORY.md
    notes = MemoryNotesStore(home=home, workspace=workspace)
    items.append(SurvivalItem(
        name="MEMORY.md 记忆笔记",
        source=str(notes.path),
        ok=True,
        detail=f"{notes.line_count()} 行" if _exists(notes.path) else "无笔记 (新建项目正常)",
    ))

    # 4. FTS5 长期记忆: memory_store 服务可用即代表可 recall_context 召回。
    fts_ok = memory_store is not None and hasattr(memory_store, "search")
    items.append(SurvivalItem(
        name="FTS5 长期记忆",
        source="memory_store 服务 (recall_context)",
        ok=fts_ok,
        detail="可用" if fts_ok else "服务未注入, 压缩后不会自动召回结构化记忆",
    ))

    # 5. Git 上下文: 工作区 .git
    git_dir = ws / ".git"
    items.append(SurvivalItem(
        name="Git 上下文",
        source=str(git_dir),
        ok=_exists(git_dir),
        detail="可重新获取分支/commit/dirty" if _exists(git_dir) else "非 git 仓库",
    ))

    # 6. 技能注册表: skill_manager 服务可用。
    skill_ok = skill_manager is not None
    items.append(SurvivalItem(
        name="技能注册表",
        source="skill_manager 服务",
        ok=skill_ok,
        detail="可重新列举技能快照" if skill_ok else "服务未注入",
    ))

    # 7. TodoWrite: workspace/.qxt/todo.json
    todo = ws / ".qxt" / "todo.json"
    items.append(SurvivalItem(
        name="TodoWrite 任务清单",
        source=str(todo),
        ok=_exists(todo),
        detail="可从磁盘恢复" if _exists(todo) else "无持久化 todo (本会话内任务可能需重建)",
    ))

    # 8. Goal 状态: workspace/.qxt/goal.json
    goal = ws / ".qxt" / "goal.json"
    items.append(SurvivalItem(
        name="Goal 目标进度",
        source=str(goal),
        ok=_exists(goal),
        detail="可从磁盘恢复步骤进度" if _exists(goal) else "无进行中的 goal",
    ))

    # 9. 输出风格 / 语言: config 服务可用。
    cfg_ok = config is not None
    items.append(SurvivalItem(
        name="输出风格 / 语言",
        source="config 服务",
        ok=cfg_ok,
        detail="可从配置恢复" if cfg_ok else "配置未注入, 使用默认",
    ))

    return items


def build_survival_report(
    home: Path,
    workspace: str,
    config: Any = None,
    memory_store: Any = None,
    skill_manager: Any = None,
) -> str:
    """生成可读的 compact 存活检查报告 (多行文本)。"""
    items = check_survival_items(home, workspace, config, memory_store, skill_manager)
    lines = [
        "== compact 存活检查报告 ==",
        f"home={home}",
        f"workspace={workspace}  (project_slug={project_slug(workspace)})",
        "",
    ]
    for it in items:
        mark = "[OK]" if it.ok else "[!!]"
        lines.append(f"{mark} {it.name}")
        lines.append(f"     来源: {it.source}")
        lines.append(f"     说明: {it.detail}")
    missing = [it.name for it in items if not it.ok]
    lines.append("")
    if missing:
        lines.append(f"需关注 {len(missing)} 项: {', '.join(missing)}")
    else:
        lines.append("全部关键状态均可从磁盘/服务重建, compact 安全。")
    return "\n".join(lines)
