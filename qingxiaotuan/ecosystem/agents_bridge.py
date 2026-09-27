"""命名 Agent 桥接层 —— 与 Claude Code 的 ``.claude/agents/*.md`` 双向同步。

qxt 的命名 Agent (``agents_registry``) 与 Claude Code 子代理使用**同一种格式**:
Markdown + frontmatter (``name`` / ``description`` / ``tools`` / ``model`` / 正文即系统提示),
且 qxt 运行期已把项目 ``.claude/agents`` 与用户 ``~/.claude/agents`` 纳入三层发现。
本层补上**显式管理**: 把 Claude Code 的子代理落一份到 qxt 用户级 (随 qxt 主目录迁移),
或把 qxt 用户级 Agent 导出到项目 ``.claude/agents`` 供 Claude Code 直接调用。

Hermes 没有对应的 agents 目录约定 (其对应物是 Bot Mode, 形态不同), 因此
agents 桥接只面向 Claude Code —— 这是双生态里唯一同构的部分。
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

from ..core.agents_registry import parse_agent_md


@dataclass
class AgentBridgeResult:
    imported: List[str] = field(default_factory=list)
    exported: List[str] = field(default_factory=list)
    skipped: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


def import_claude_agents(
    claude_agents_dirs: List[Path],
    qxt_agents_dir: Path,
    *,
    overwrite: bool = False,
) -> AgentBridgeResult:
    """把 Claude Code 子代理复制到 qxt 用户级 agents 目录。

    只复制能解析出 name 的合法定义; 同名且不 overwrite 时跳过。
    """
    result = AgentBridgeResult()
    try:
        qxt_agents_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        result.errors.append(f"创建 {qxt_agents_dir}: {exc}")
        return result

    seen: set = set()
    for d in claude_agents_dirs:
        if not d.is_dir():
            continue
        for md in sorted(d.glob("*.md")):
            try:
                text = md.read_text(encoding="utf-8")
                spec = parse_agent_md(text, source_kind="import", source_path=str(md))
            except OSError as exc:
                result.errors.append(f"{md.name}: {exc}")
                continue
            if not spec.name:
                result.skipped.append(md.name)
                continue
            if spec.name in seen:
                continue
            seen.add(spec.name)
            dst = qxt_agents_dir / f"{spec.name}.md"
            if dst.exists() and not overwrite:
                result.skipped.append(spec.name)
                continue
            try:
                shutil.copyfile(md, dst)
                result.imported.append(spec.name)
            except OSError as exc:
                result.errors.append(f"{spec.name}: {exc}")
    return result


def export_to_claude(
    qxt_agents_dir: Path,
    claude_project_agents: Path,
    *,
    overwrite: bool = False,
) -> AgentBridgeResult:
    """把 qxt 用户级 Agent 导出到项目 ``.claude/agents`` 供 Claude Code 调用。"""
    result = AgentBridgeResult()
    if not qxt_agents_dir.is_dir():
        result.errors.append(f"qxt agents 目录不存在: {qxt_agents_dir}")
        return result
    try:
        claude_project_agents.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        result.errors.append(f"创建 {claude_project_agents}: {exc}")
        return result

    for md in sorted(qxt_agents_dir.glob("*.md")):
        try:
            text = md.read_text(encoding="utf-8")
            spec = parse_agent_md(text, source_kind="user", source_path=str(md))
        except OSError as exc:
            result.errors.append(f"{md.name}: {exc}")
            continue
        if not spec.name:
            result.skipped.append(md.name)
            continue
        dst = claude_project_agents / f"{spec.name}.md"
        if dst.exists() and not overwrite:
            result.skipped.append(spec.name)
            continue
        try:
            shutil.copyfile(md, dst)
            result.exported.append(spec.name)
        except OSError as exc:
            result.errors.append(f"{spec.name}: {exc}")
    return result


__all__ = ["AgentBridgeResult", "import_claude_agents", "export_to_claude"]
