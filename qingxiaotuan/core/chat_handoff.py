"""Chat 层 —— 会话交接 (handoff) 机制 (四层边界 · 第二层)。

理念: "Chat 层 = 对话太长时及时交接"。
一个会话越长, 上下文越贵、越容易跑偏; 与其硬撑到压缩丢信息, 不如主动开一个
新会话, 把关键上下文 (目标 / 已完成 / 待办 / 关键文件 / 决策) 压成摘要带过去。

流程:
1. 上下文阈值检测: 会话 token 数超过 chat.auto_handoff_threshold (默认 0.8 × 模型窗口)
   时自动提示交接;
2. 生成当前会话摘要 (优先 LLM 压缩; 无 LLM 时走启发式规则摘要);
3. 创建新会话, 摘要作为系统提示注入;
4. 旧会话标记 archived, 新会话继承项目级记忆/配置 (Project 层);
5. 输出交接报告: 旧会话 ID → 新会话 ID + 摘要预览。

配置项:
- chat.handoff_enabled (默认 true)
- chat.auto_handoff_threshold (默认 0.8)
"""

from __future__ import annotations

import json
import re
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, cast


@dataclass
class HandoffReport:
    """交接报告。"""

    old_session_id: str
    new_session_id: str
    summary: str
    archived: bool = True
    project_id: str = ""
    created_at: float = 0.0

    def preview(self, n: int = 300) -> str:
        return self.summary[:n] + ("…" if len(self.summary) > n else "")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "old_session_id": self.old_session_id,
            "new_session_id": self.new_session_id,
            "archived": self.archived,
            "project_id": self.project_id,
            "summary": self.summary,
        }


# ------------------------------------------------------------ 阈值检测


def should_handoff(
    estimated_tokens: int,
    model_max_tokens: int,
    threshold: float = 0.8,
) -> bool:
    """上下文是否达到交接阈值 (纯函数, 便于测试)。

    estimated_tokens: 当前会话估算 token 数
    model_max_tokens: 模型上下文窗口上限
    threshold:        比例阈值 (默认 0.8 = 80%)
    """
    if model_max_tokens <= 0:
        return False
    return estimated_tokens >= model_max_tokens * threshold


# ------------------------------------------------------------ 摘要生成

_FILE_PATTERN = re.compile(
    r"(?:[A-Za-z]:[\\/])?(?:[\w.\-]+[\\/])*[\w.\-]+\.(?:py|md|js|ts|jsx|tsx|json|yaml|yml|"
    r"txt|toml|cfg|ini|html|css|sh|ps1|go|rs|java|c|cpp|h)"
)


def build_summary(
    messages: List[Dict[str, Any]],
    generate_fn: Optional[Callable[[str], str]] = None,
) -> str:
    """生成会话交接摘要。

    messages: 当前会话的消息列表 ({"role": ..., "content": ...})。
    generate_fn: 可选的 LLM 摘要函数 (prompt: str) -> str;
                 为 None 时走启发式规则摘要 (零成本, 测试/无网环境用)。
    """
    if generate_fn is not None:
        try:
            transcript = "\n".join(
                f"[{m.get('role', '?')}] {str(m.get('content', ''))[:500]}"
                for m in messages[-40:]
            )
            prompt = (
                "请把以下对话压缩成一份交接摘要, 供新会话无缝接手。严格分四节输出:\n"
                "## 目标\n## 已完成\n## 待办\n## 关键文件与决策\n\n"
                f"对话记录:\n{transcript}"
            )
            out = generate_fn(prompt)
            if out and out.strip():
                return out.strip()
        except Exception:  # noqa: BLE001
            pass
    return _heuristic_summary(messages)


def _heuristic_summary(messages: List[Dict[str, Any]]) -> str:
    """启发式摘要: 不调 LLM, 从消息里提取目标/已完成/待办/关键文件。"""
    users = [
        str(m.get("content", ""))
        for m in messages
        if m.get("role") == "user" and m.get("content")
    ]
    assistants = [
        str(m.get("content", ""))
        for m in messages
        if m.get("role") == "assistant" and m.get("content")
    ]

    # 目标 = 第一条用户消息
    goal = users[0].strip()[:300] if users else "(未记录)"
    # 待办 = 最后一条用户消息
    pending = users[-1].strip()[:300] if len(users) > 1 else "(无新的待办)"
    # 已完成 = 最后一条助手回复的前 300 字
    done = assistants[-1].strip()[:300] if assistants else "(尚无产出)"
    # 关键文件: 全文里出现过的路径去重
    text = "\n".join(users + assistants)
    files = []
    for match in _FILE_PATTERN.findall(text):
        if match not in files and len(match) < 80:
            files.append(match)
    files_str = ", ".join(files[:10]) if files else "(未涉及具体文件)"

    return (
        "## 目标\n" + goal + "\n\n"
        "## 已完成\n" + done + "\n\n"
        "## 待办\n" + pending + "\n\n"
        "## 关键文件与决策\n涉及文件: " + files_str + "\n"
        "(本摘要由启发式规则生成; 开启模型后可用 LLM 生成更准确的交接摘要)"
    )


# ------------------------------------------------------------ 交接编排


class ChatHandoff:
    """会话交接器 (每个工作区一份)。"""

    def __init__(self, workspace: str | Path, config: Any = None) -> None:
        self.workspace = Path(workspace)
        self.config = config
        self.qxt_dir = self.workspace / ".qxt"
        self.qxt_dir.mkdir(parents=True, exist_ok=True)
        self.enabled = self._cfg("chat.handoff_enabled", True)
        self.threshold = float(self._cfg("chat.auto_handoff_threshold", 0.8))

    def _cfg(self, key: str, default: Any) -> Any:
        if self.config is None:
            return default
        try:
            return self.config.get(key, default)
        except Exception:  # noqa: BLE001
            return default

    def maybe_prompt(self, estimated_tokens: int, model_max_tokens: int) -> bool:
        """自动提示判定: 是否该提醒用户交接。"""
        if not self.enabled:
            return False
        return should_handoff(estimated_tokens, model_max_tokens, self.threshold)

    def auto_handoff_if_needed(
        self,
        estimated_tokens: int,
        model_max_tokens: int,
        old_session_id: str,
        messages: List[Dict[str, Any]],
        generate_fn: Optional[Callable[[str], str]] = None,
        project_id: str = "",
    ) -> Optional[HandoffReport]:
        """超阈值时**自动执行交接** (而非仅提示), 返回交接报告; 未达阈值 / 未开启返回 None。

        与 :meth:`maybe_prompt` 的区别: ``maybe_prompt`` 只提醒用户手动 ``/handoff``;
        本方法在达到阈值时**直接调用 :meth:`handoff` 完成交班** (生成摘要 → 开新会话 →
        旧会话归档 → 落谱系), 由 CLI 层把报告打印到 UI。

        双重开关:
        - ``chat.handoff_enabled`` (本类 ``self.enabled``) 交接总开关;
        - ``chat.auto_handoff_enabled`` (默认 ``true``) 是否「自动执行」而非仅提示。

        任一关闭 / 未达阈值 / 模型窗口未知时返回 None, 不做任何副作用。
        """
        if not self.enabled:
            return None
        if not bool(self._cfg("chat.auto_handoff_enabled", True)):
            return None
        if not should_handoff(estimated_tokens, model_max_tokens, self.threshold):
            return None
        return self.handoff(
            old_session_id, messages, generate_fn=generate_fn, project_id=project_id
        )

    def handoff(
        self,
        old_session_id: str,
        messages: List[Dict[str, Any]],
        generate_fn: Optional[Callable[[str], str]] = None,
        project_id: str = "",
    ) -> HandoffReport:
        """执行一次交接: 生成摘要 → 开新会话 → 旧会话归档 → 落交接记录。"""
        summary = build_summary(messages, generate_fn=generate_fn)
        new_session_id = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
        report = HandoffReport(
            old_session_id=old_session_id,
            new_session_id=new_session_id,
            summary=summary,
            archived=True,
            project_id=project_id,
            created_at=time.time(),
        )
        self._record(report)
        return report

    def _record(self, report: HandoffReport) -> None:
        """把交接记录落到 .qxt/handoffs.json (谱系可查)。"""
        f = self.qxt_dir / "handoffs.json"
        try:
            data = (
                json.loads(f.read_text(encoding="utf-8"))
                if f.exists()
                else {"handoffs": []}
            )
        except (OSError, json.JSONDecodeError):
            data = {"handoffs": []}
        data.setdefault("handoffs", []).append(report.to_dict())
        tmp = f.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(f)

    def list_handoffs(self) -> List[Dict[str, Any]]:
        f = self.qxt_dir / "handoffs.json"
        if not f.exists():
            return []
        try:
            return cast(
                List[Dict[str, Any]],
                json.loads(f.read_text(encoding="utf-8")).get("handoffs", []),
            )
        except (OSError, json.JSONDecodeError):
            return []
