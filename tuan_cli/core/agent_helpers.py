"""Agent 辅助功能 —— 从 Agent 主类拆出的纯函数/无状态逻辑。

- summarize_messages: 上下文压缩时的消息摘要提取
- should_nudge / build_nudge_prompt: 技能蒸馏 (Hermes 闭环) 触发判断
- ChunkFlusher: 流式 token 分片合并落盘 (防每 delta 同步写盘拖慢输出)
- estimate_total_cost / cache_hit_rate: 用量/成本估算
- build_verify_config: 编码验证闭环配置构建
"""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any, Dict, List, Optional, Set

log = logging.getLogger(__name__)


# ===================================================================== 上下文摘要

def summarize_messages(messages: List[Dict[str, Any]]) -> str:
    """从旧消息中提取结构化关键信息, 用于上下文压缩。

    规则提取 (不依赖 LLM, 避免递归调用):
    - 用户指令/目标 (user 消息中的核心意图)
    - 工具调用中涉及的文件路径
    - 工具调用的执行结果摘要 (成功/失败)
    - assistant 回复中的关键结论
    """
    goals: list[str] = []
    files_seen: set[str] = set()
    tool_actions: list[str] = []
    conclusions: list[str] = []

    for m in messages:
        role = m.get("role", "")
        content = m.get("content") or ""
        if isinstance(content, list):
            content = " ".join(str(p) for p in content)
        content = str(content)

        if role == "user" and content.strip():
            line = content.strip().split("\n")[0][:120]
            if line and line not in goals:
                goals.append(line)

        elif role == "assistant":
            for tc in m.get("tool_calls", []) or []:
                fn = tc.get("function", {})
                name = fn.get("name", "")
                args_str = fn.get("arguments", "")
                if name in ("read_file", "write_file", "edit_file", "str_replace", "open_file"):
                    try:
                        args = json.loads(args_str) if isinstance(args_str, str) else args_str
                        path = args.get("path", "")
                        if path and path not in files_seen:
                            files_seen.add(path)
                            tool_actions.append(f"{name}({path})")
                    except (json.JSONDecodeError, AttributeError):
                        pass
                elif name == "run_terminal_command":
                    try:
                        args = json.loads(args_str) if isinstance(args_str, str) else args_str
                        cmd = args.get("command", "")[:80]
                        if cmd:
                            tool_actions.append(f"$ {cmd}")
                    except (json.JSONDecodeError, AttributeError):
                        pass
                elif name == "code_search":
                    try:
                        args = json.loads(args_str) if isinstance(args_str, str) else args_str
                        pattern = args.get("pattern", "")[:60]
                        if pattern:
                            tool_actions.append(f"search({pattern})")
                    except (json.JSONDecodeError, AttributeError):
                        pass
            if content.strip():
                tail = content.strip()[-200:]
                if tail and tail not in conclusions:
                    conclusions.append(tail)

    parts: list[str] = []
    if goals:
        parts.append("用户目标: " + "; ".join(goals[-3:]))
    if files_seen:
        parts.append("涉及文件: " + ", ".join(sorted(files_seen)[:8]))
    if tool_actions:
        parts.append("操作: " + "; ".join(tool_actions[-6:]))
    if conclusions:
        parts.append("结论: " + conclusions[-1][:200])
    if not parts:
        flat = " ".join(
            f"{m.get('role', '?')}: {str(m.get('content', ''))[:80]}"
            for m in messages[-10:] if m.get("content")
        )
        return flat[:400] if flat else "(无可提取的结构化信息)"
    return "\n".join(parts)[:500]


# ===================================================================== 技能蒸馏 nudge

SKILL_NUDGE = (
    "[系统提醒] 任务已推进数轮。请自查: 本次使用的方法是否具有通用性、值得在未来复用?"
    "如果是, 请用 skill_save 将其蒸馏为技能 (或改进已有的同名技能), 然后继续完成任务。"
    "如果不值得, 忽略本提醒继续即可, 不要回复本提醒。"
)


def should_nudge(turn_count: int, interval: int) -> bool:
    """判断是否应该触发技能蒸馏提醒。"""
    return interval > 0 and turn_count > 0 and turn_count % interval == 0


# ===================================================================== 流式分片合并落盘

class ChunkFlusher:
    """token 分片合并落盘器。

    背景: ``Agent._prepare_run`` 给 on_token 套了"增量落盘"包装 —— 每个
    delta 都同步 ``open()+write()+flush()`` 一次会话 JSONL。流式输出速度
    下这等于在输出线程上挂了个磁盘瓶颈 (Windows 每次毫秒级), 长回复越流
    越卡, 用户观感即"模型响应极其慢/一顿一顿的"。

    本类把相邻 delta 攒起来, 满足任一条件才真正落一次盘:
      - 累计 >= ``max_chars`` 个字符 (默认 128);
      - 距上次落盘 >= ``max_interval`` 秒 (默认 0.15, 流暂停时立即冲掉)。
    语义不变: chunk 事件仍是同一文本流的顺序分片, 回放时 ``"".join``
    结果与逐 delta 落盘完全一致。

    线程安全: 单输出线程 add + 任意线程 flush 均可。
    """

    def __init__(self, sink: Any, max_chars: int = 128,
                 max_interval: float = 0.15) -> None:
        self._sink = sink
        self._max_chars = max(1, int(max_chars))
        self._max_interval = max(0.01, float(max_interval))
        self._buf: List[str] = []
        self._len = 0
        self._last = time.monotonic()
        self._lock = threading.Lock()

    def add(self, delta: str) -> None:
        if not delta:
            return
        now = time.monotonic()
        with self._lock:
            self._buf.append(delta)
            self._len += len(delta)
            due = self._len >= self._max_chars or (now - self._last) >= self._max_interval
        if due:
            self.flush()

    def flush(self) -> None:
        with self._lock:
            if not self._buf:
                return
            text = "".join(self._buf)
            self._buf = []
            self._len = 0
            self._last = time.monotonic()
        try:
            self._sink(text)
        except Exception as exc:  # noqa: BLE001 - 落盘失败不应打断输出流
            log.debug("ChunkFlusher 落盘失败: %s", exc)


# ===================================================================== 用量/成本

def estimate_total_cost(config: Any, total_usage: Dict[str, int]) -> float:
    """估算当前会话总花费 (USD)。"""
    try:
        from ..models.router import estimate_cost
        provider = config.get("model.provider", "")
        model = config.get("model.model", "")
        return estimate_cost(
            provider, model,
            total_usage.get("prompt_tokens", 0),
            total_usage.get("completion_tokens", 0),
        ) or 0.0
    except Exception:  # noqa: BLE001
        return 0.0


def cache_hit_rate(total_usage: Dict[str, int]) -> Optional[float]:
    """DeepSeek 前缀缓存命中率: hit / (hit + miss)。无数据返回 None。"""
    hit = total_usage.get("prompt_cache_hit_tokens", 0)
    miss = total_usage.get("prompt_cache_miss_tokens", 0)
    total = hit + miss
    if total <= 0:
        return None
    return hit / total


# ===================================================================== 验证闭环配置

def detect_verify_write_tools(tool_calls: List[Dict[str, Any]]) -> bool:
    """检测一批工具调用中是否包含写操作。"""
    WRITE = {"write_file", "edit_file", "delete_file", "move_file", "delete_dir"}
    names = {tc.get("function", {}).get("name") for tc in tool_calls if isinstance(tc, dict)}
    return bool(names & WRITE)
