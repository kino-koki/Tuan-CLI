"""端到端蒸馏闭环 —— 把"一次成功的多步任务"沉淀为可复用技能。

这是 qxt 技能系统的核心超越点 (对标 Claude Code 只有 memory 笔记、Kimi Code
只有人工 review/consolidate、Codex 无自动蒸馏):

  多步任务结束
      │  (≥ min_tool_calls 个工具调用, 且涉及可复用模式)
      ▼
  蒸馏提议 (DistillProposal: 名称 + 描述 + 正文草稿 + 标签)
      │  质量门控: 名称非空 / 描述≥10字 / 正文≥3步
      ▼
  用户确认 [y/n/编辑]  ── 否 ──► 丢弃
      │ 是
      ▼
  skill_save 写入用户级技能库 (source=auto-distill, 同名=refine)
      │
      ▼
  下次相似任务: activate_for_task 因标签匹配 + use_count 自动命中

配置项 (config.get):
  - self_improve.auto_propose    是否在任务结束后自动提议 (默认 true)
  - self_improve.min_tool_calls  触发提议所需最少工具调用数 (默认 3)

本模块只负责"提议→门控→确认"的纯逻辑, 不直接读 UI;
交互层 (斜杠命令 / REPL) 负责把 proposal 渲染给用户并把 y/n 回传。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, List, Optional

from ..skills.manager import Skill, SkillManager


@dataclass
class DistillProposal:
    """一条蒸馏提议: 等待用户确认的技能草稿。"""

    name: str
    description: str
    body: str
    tags: List[str] = field(default_factory=list)
    source_tools: List[str] = field(default_factory=list)
    task_summary: str = ""

    def render(self) -> str:
        """渲染给用户看的提议摘要。"""
        lines = [
            f"检测到可复用工作流, 建议存为技能:",
            f"  名称: {self.name}",
            f"  描述: {self.description}",
            f"  标签: {', '.join(self.tags)}",
            f"  来源工具: {', '.join(self.source_tools)}",
            f"  步骤数: {count_steps(self.body)}",
        ]
        return "\n".join(lines)


def count_steps(body: str) -> int:
    """数正文里的可执行步骤数 (有序列表项 或 二级步骤标题)。"""
    if not body:
        return 0
    n = 0
    for line in body.splitlines():
        s = line.strip()
        if re.match(r"^\d+[\.、)]\s", s):
            n += 1
        elif s.startswith("## 步骤") or re.match(r"^##\s*步骤", s):
            n += 1
    return n


def quality_gate(p: DistillProposal) -> bool:
    """蒸馏质量门控: 不满足则不提议。

    - 名称非空
    - 描述 ≥ 10 字
    - 正文 ≥ 3 个步骤
    """
    if not p.name or not p.name.strip():
        return False
    if len(p.description.strip()) < 10:
        return False
    if count_steps(p.body) < 3:
        return False
    return True


# 工具名 → 语义标签 (用于给蒸馏技能打标, 使其下次能被 activate_for_task 命中)
_TOOL_TAG_MAP = {
    "read_file": ["codebase-navigation"],
    "grep": ["codebase-navigation"],
    "glob": ["codebase-navigation"],
    "edit_file": ["code-editing", "precise-edit"],
    "write_file": ["code-editing"],
    "code_edit": ["code-editing", "precise-edit"],
    "run_tests": ["testing", "tdd"],
    "pytest": ["testing", "tdd"],
    "bash": ["devops"],
    "powershell": ["devops"],
    "git": ["git", "version-control"],
    "search": ["debugging", "troubleshooting"],
    "web_search": ["debugging"],
}


class DistillLoop:
    """蒸馏闭环状态机: 记录任务工具流, 任务结束时产出提议。"""

    def __init__(
        self,
        skill_manager: Optional[SkillManager] = None,
        config: Any = None,
        auto_propose: Optional[bool] = None,
        min_tool_calls: Optional[int] = None,
    ) -> None:
        self.manager = skill_manager
        get = config.get if config is not None else (lambda k, d=None: d)
        if auto_propose is None:
            auto_propose = bool(get("self_improve.auto_propose", True))
        if min_tool_calls is None:
            min_tool_calls = int(get("self_improve.min_tool_calls", 3) or 3)
        self.auto_propose = auto_propose
        self.min_tool_calls = min_tool_calls

        self.task_text: str = ""
        self.tool_calls: List[str] = []
        self.pending: Optional[DistillProposal] = None
        self.confirmed: List[DistillProposal] = []

    # ------------------------------------------------------------ 会话记录

    def start_task(self, task_text: str) -> None:
        """开始一个新任务: 清空工具流。"""
        self.task_text = task_text or ""
        self.tool_calls = []
        self.pending = None

    def record_tool_call(self, name: str, ok: bool = True) -> None:
        """记录一次工具调用 (失败调用也记录, 但只对成功模式蒸馏)。"""
        if ok and name:
            self.tool_calls.append(name)

    # ------------------------------------------------------------ 提议

    def build_proposal(self) -> Optional[DistillProposal]:
        """根据当前任务工具流构造提议草稿 (不做门控)。"""
        if len(self.tool_calls) < self.min_tool_calls:
            return None
        tools = list(dict.fromkeys(self.tool_calls))  # 保序去重
        # 从任务文本推导技能名: 取前 20 字做可读名 (slug 化在 save 时做)
        summary = (self.task_text or "多步任务").strip()
        name = summary[:24].rstrip("。，,. ") or "multi-step-workflow"
        # 描述: 概括工具序列
        description = (
            f"完成「{summary[:40]}」时沉淀的可复用工作流, "
            f"涉及 {len(tools)} 个工具的协作顺序"
        )
        # 正文: 按工具序列生成步骤草稿
        steps = [
            f"先理解任务目标, 用 {tools[0]} 收集上下文 (代码/文件/日志)",
        ]
        if len(tools) >= 2:
            steps.append(f"用 {tools[1]} 做核心修改/检索, 每步核对结果")
        if len(tools) >= 3:
            steps.append(f"用 {tools[2]} 验证效果 (测试/构建/对比)")
        steps.append("遇到失败时回退一步重试, 不要连续盲改")
        body = (
            f"# {name}\n\n"
            f"> 由 qxt 自动蒸馏自任务: {summary}\n\n"
            "## 推荐流程\n"
            + "\n".join(f"{i+1}. {s}" for i, s in enumerate(steps))
            + "\n"
        )
        # 标签: 工具映射 + 任务关键词粗提取
        tags: List[str] = []
        for t in tools:
            tags.extend(_TOOL_TAG_MAP.get(t.lower(), []))
        tags = list(dict.fromkeys(tags))
        return DistillProposal(
            name=name,
            description=description,
            body=body,
            tags=tags,
            source_tools=tools,
            task_summary=summary,
        )

    def maybe_propose(self) -> Optional[DistillProposal]:
        """任务结束时调用: 通过门控则返回提议 (并暂存为 pending), 否则 None。"""
        if not self.auto_propose:
            return None
        p = self.build_proposal()
        if p is None:
            return None
        if not quality_gate(p):
            return None
        self.pending = p
        return p

    # ------------------------------------------------------------ 确认

    def confirm(self, proposal: Optional[DistillProposal] = None) -> Optional[Skill]:
        """用户确认后写入技能库。同名 = refine (use_count 递增)。"""
        p = proposal or self.pending
        if p is None or self.manager is None:
            return None
        skill = self.manager.save(
            p.name, p.description, p.body,
            tags=p.tags, source="auto-distill",
        )
        self.confirmed.append(p)
        self.pending = None
        return skill

    def decline(self) -> None:
        """用户拒绝: 丢弃 pending 提议。"""
        self.pending = None
