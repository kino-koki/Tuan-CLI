"""Goal 模式引擎 —— 对标 Claude Code `/goal` 与 Kimi Code Goal。

与 ``core/agent_goal.py`` 的关系:
- ``agent_goal.GoalMixin`` 解决「目标文本 + YES/NO 复查」的最小闭环;
- 本模块是增强版 Goal 引擎: 目标拆解为 3~7 个子步骤、逐步验证、状态机、
  最大自动续轮数防死循环、持久化到 ``<workspace>/.qxt/goal.json``。

设计原则: 全部外部依赖 (LLM 调用、测试命令执行) 以可注入参数传入,
本模块不直接 import model/tool 层, 保证微内核下可独立测试、可被插件替换。

状态机:
    目标状态: pending -> in_progress -> done
                       或 -> failed (达到最大自动续轮数仍未完成)
    步骤状态: pending -> in_progress -> done
                                    或 -> failed
"""

from __future__ import annotations

import json
import logging
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

log = logging.getLogger(__name__)

# ----------------------------------------------------------------- 状态常量
PENDING = "pending"
IN_PROGRESS = "in_progress"
DONE = "done"
FAILED = "failed"

DEFAULT_MAX_AUTO_ITERATIONS = 10

# 步骤描述里出现这些关键词时, 优先用 runner 实际跑命令做确定性验证
_TEST_HINT_RE = re.compile(r"pytest|test|测试|lint|ruff|mypy|build|编译|构建", re.IGNORECASE)

# LLM 拆解提示词
_DECOMPOSE_PROMPT = (
    "你是一个任务拆解专家。请把下面这个目标拆成 3~7 个可执行的子步骤, "
    "按顺序列出, 每步要具体、可验证。\n"
    "只返回一个 JSON 字符串数组, 例如: [\"第一步\", \"第二步\"]。不要输出任何其他内容。\n"
    "目标: {goal}"
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _verify_command_for(step_desc: str) -> str:
    """根据步骤描述猜一个验证命令 (仅用于 runner 注入的测试/CI 场景)。"""
    d = step_desc.lower()
    if "ruff" in d or "lint" in d:
        return "ruff check ."
    if "mypy" in d or "typecheck" in d or "类型" in d:
        return "mypy ."
    return "python -m pytest -q"


def _parse_steps(text: str) -> List[str]:
    """把 LLM 返回解析成步骤列表。容忍 JSON 数组 / 编号列表两种形态。"""
    text = (text or "").strip()
    if not text:
        return []
    # 形态一: JSON 数组 (元素可能是字符串, 也可能是 {"step": "..."} / {"description": "..."})
    try:
        data = json.loads(text)
        if isinstance(data, list):
            steps: List[str] = []
            for item in data:
                if isinstance(item, str):
                    steps.append(item.strip())
                elif isinstance(item, dict):
                    for key in ("step", "description", "title", "task"):
                        if isinstance(item.get(key), str):
                            steps.append(item[key].strip())
                            break
            return [s for s in steps if s]
    except (json.JSONDecodeError, ValueError):
        pass
    # 形态二: 编号/项目符号列表
    steps = []
    for line in text.splitlines():
        line = line.strip()
        line = re.sub(r"^[\-\*\d\.\)]+\s*", "", line).strip()
        if line:
            steps.append(line)
    return steps


class GoalEngine:
    """Goal 引擎: 拆解 -> 逐步执行 -> 验证 -> 自动续轮, 直到目标达成。

    Args:
        workspace_dir: 工作区目录, 状态持久化到 ``<workspace_dir>/.qxt/goal.json``
        llm: 可选 LLM 调用 ``call(prompt: str) -> str``; 用于目标拆解与步骤验证。
             为 None 时拆解退化为按行/分号切分, 步骤验证不做 (保守视为未完成)。
        runner: 可选命令执行 ``call(cmd: str) -> (ok: bool, output: str)``;
                 步骤描述含测试/lint 关键词时优先用它做确定性验证。
        max_auto_iterations: 最大自动续轮数 (默认 10), 超出后目标标记 failed 并停止自动续轮。
        auto_continue: 是否在每轮结束后自动注入"继续推进"提示。
        enabled: Goal 引擎总开关。
    """

    def __init__(
        self,
        workspace_dir: str,
        *,
        llm: Optional[Callable[[str], str]] = None,
        runner: Optional[Callable[[str], Tuple[bool, str]]] = None,
        max_auto_iterations: int = DEFAULT_MAX_AUTO_ITERATIONS,
        auto_continue: bool = True,
        enabled: bool = True,
    ) -> None:
        self.workspace_dir = str(workspace_dir)
        self.llm = llm
        self.runner = runner
        self.max_auto_iterations = int(max_auto_iterations)
        self.auto_continue = bool(auto_continue)
        self.enabled = bool(enabled)
        self.state: Optional[Dict[str, Any]] = None
        self.load()

    # ------------------------------------------------------------ 持久化
    def _file_path(self) -> str:
        return os.path.join(self.workspace_dir, ".qxt", "goal.json")

    def load(self) -> None:
        """从磁盘恢复目标状态 (新会话续用); 文件缺失/损坏则视为无目标。"""
        path = self._file_path()
        if not os.path.isfile(path):
            self.state = None
            return
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, dict) and data.get("description") and isinstance(data.get("steps"), list):
                self.state = data
            else:
                self.state = None
        except Exception as exc:  # noqa: BLE001
            log.debug("goal.json 读取失败, 忽略: %s", exc)
            self.state = None

    def save(self) -> None:
        """原子写盘: 先写临时文件再替换, 避免半截 JSON。"""
        if self.state is None:
            return
        path = self._file_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(self.state, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, path)

    # ------------------------------------------------------------ 目标操作
    def set_goal(self, description: str) -> Dict[str, Any]:
        """设置目标: 生成目标 ID, 拆解为子步骤, 落盘。"""
        description = description.strip()
        steps = self._decompose(description)
        self.state = {
            "goal_id": uuid.uuid4().hex[:12],
            "description": description,
            "status": IN_PROGRESS,
            "iterations": 0,
            "created_at": _now(),
            "steps": [
                {"id": f"s{i + 1}", "description": s, "status": PENDING, "note": ""}
                for i, s in enumerate(steps)
            ],
        }
        # 第一步直接置为进行中
        if self.state["steps"]:
            self.state["steps"][0]["status"] = IN_PROGRESS
        self.save()
        log.info("Goal 已设置: %s (拆为 %d 步)", description[:80], len(steps))
        return self.state

    def _decompose(self, description: str) -> List[str]:
        """调用 LLM 拆解目标; 无 LLM / 解析失败时退化为启发式切分。"""
        if self.llm is not None:
            try:
                steps = _parse_steps(self.llm(_DECOMPOSE_PROMPT.format(goal=description)))
            except Exception as exc:  # noqa: BLE001
                log.debug("Goal 拆解 LLM 调用失败, 走启发式: %s", exc)
                steps = []
            if steps:
                # 规范: 3~7 步最理想; 超出截断, 不足保留
                return steps[:7]
        pieces = [p.strip(" -\t") for p in re.split(r"[\n;；]", description) if p.strip()]
        return pieces or [description]

    def clear(self) -> None:
        """清除目标并删除持久化文件。"""
        self.state = None
        try:
            path = self._file_path()
            if os.path.isfile(path):
                os.remove(path)
        except OSError as exc:  # noqa: BLE001
            log.debug("goal.json 删除失败: %s", exc)

    def status(self) -> Optional[Dict[str, Any]]:
        """返回当前目标状态 dict (只读视图); 无目标时 None。"""
        return self.state

    # ------------------------------------------------------------ 执行闭环
    def _open_step(self) -> Optional[Dict[str, Any]]:
        """返回第一个未完成的步骤。"""
        if not self.state:
            return None
        for step in self.state["steps"]:
            if step["status"] != DONE:
                return step
        return None

    def _verify_step(self, step: Dict[str, Any], response: str) -> bool:
        """验证当前步骤是否达成。

        优先级: 确定性 runner (测试/lint 类步骤) > LLM YES/NO 判定 > 保守 False。
        """
        desc = step.get("description", "")
        if self.runner is not None and _TEST_HINT_RE.search(desc):
            try:
                ok, _out = self.runner(_verify_command_for(desc))
                return bool(ok)
            except Exception as exc:  # noqa: BLE001
                log.debug("Goal 步骤验证命令执行失败: %s", exc)
                return False
        if self.llm is not None:
            try:
                prompt = (
                    "你是目标验收员。根据 Agent 的最新回复, 判断下面这个步骤是否已经完成。"
                    "只回答 YES 或 NO。\n"
                    f"步骤: {desc}\n"
                    f"最新回复:\n{response[:1500]}"
                )
                verdict = self.llm(prompt)
                return str(verdict).strip().upper().startswith("YES")
            except Exception as exc:  # noqa: BLE001
                log.debug("Goal 步骤 LLM 验证失败: %s", exc)
        return False

    def on_turn_complete(self, response: str = "") -> Optional[str]:
        """每轮对话结束后调用: 推进步骤验证, 返回需要追加给 Agent 的"继续推进"提示。

        Returns:
            None 表示无需续轮 (目标达成 / 无目标 / 开关关闭 / 已达轮数上限);
            非空字符串为要追加到 messages 的下一轮提示。
        """
        if not self.enabled or not self.auto_continue or self.state is None:
            return None
        if self.state.get("status") != IN_PROGRESS:
            return None

        self.state["iterations"] = int(self.state.get("iterations", 0)) + 1
        step = self._open_step()
        if step is None:
            self.state["status"] = DONE
            self.save()
            return None

        step["status"] = IN_PROGRESS
        prompt_step: Optional[Dict[str, Any]] = step
        if self._verify_step(step, response):
            step["status"] = DONE
            step["note"] = "已验证达成"
            nxt = self._open_step()
            if nxt is None:
                self.state["status"] = DONE
                self.save()
                return None
            # 当前步完成, 立即把下一步置为进行中, 续轮提示指向下一步
            nxt["status"] = IN_PROGRESS
            prompt_step = nxt

        if self.state["iterations"] >= self.max_auto_iterations:
            # 防死循环: 超过最大自动续轮数, 目标标记失败, 停止自动续轮
            self.state["status"] = FAILED
            step["note"] = step.get("note", "") + " | 已达最大自动续轮数, 停止推进"
            self.save()
            return None

        self.save()
        total = len(self.state["steps"])
        idx = self.state["steps"].index(prompt_step) + 1
        return (
            f"[Goal 模式] 目标尚未完成: {self.state['description']}\n"
            f"当前进度 第 {idx}/{total} 步: {prompt_step['description']}\n"
            f"请继续推进这一步, 完成后再自检; 不要放弃整个目标。"
        )

    # ------------------------------------------------------------ 展示
    def summary_lines(self) -> List[str]:
        """生成 /goal status 的展示行 (中文)。"""
        st = self.state
        if not st:
            return ["  (当前无目标)"]
        icon = {PENDING: "○", IN_PROGRESS: "▶", DONE: "✓", FAILED: "✗"}
        lines = [
            f"  目标 [{st.get('status', IN_PROGRESS)}]: {st.get('description', '')}",
            f"  目标 ID: {st.get('goal_id', '-')}    自动续轮: {st.get('iterations', 0)}/{self.max_auto_iterations}",
        ]
        for i, step in enumerate(st.get("steps", []), 1):
            mark = icon.get(step.get("status", PENDING), "?")
            note = f"  ({step['note']})" if step.get("note") else ""
            lines.append(f"    {mark} {i}. [{step.get('status', PENDING)}] {step.get('description', '')}{note}")
        return lines


__all__ = [
    "GoalEngine",
    "PENDING",
    "IN_PROGRESS",
    "DONE",
    "FAILED",
    "DEFAULT_MAX_AUTO_ITERATIONS",
]
