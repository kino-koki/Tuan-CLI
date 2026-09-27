"""Rewind —— 会话时间线回溯 (快照 / 回退)。

理念 (对标 Claude Code Rewind / Cursor time-travel):
- 在每次用户输入**之前**自动保存一份会话快照 (messages + 元信息) 到
  ``<workspace>/.qxt/snapshots/<timestamp>.json``;
- 用户说错话 / 跑偏方向时, 用 ``/rewind`` 回退到上一个快照, 丢弃之后的对话,
  而不用 `/clear` 把整段历史清空;
- 快照数量轮转: 只保留最近 ``rewind.max_snapshots`` 个 (默认 20, 可配置)。

设计原则:
- **不改内核**: 本模块只操作一个普通的 messages 列表 (原位替换 ``messages[:] = ...``),
  由 REPL/TUI 输入处理层在用户输入前调用 ``RewindManager.snapshot()``,
  回退时同样由斜杠命令层调 ``RewindManager.restore()``;
- 快照内容是 messages 的深拷贝, 与运行中的 Agent 互不影响;
- CLI 层 ``qxt rewind <session_id>`` 用于离线回退指定会话的 jsonl 事件流。
"""

from __future__ import annotations

import copy
import json
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, cast


class RewindError(Exception):
    """Rewind 相关错误 (无快照 / 索引越界 / 会话文件损坏)。"""


@dataclass
class SnapshotInfo:
    """一条快照的元信息 (list 用)。"""

    index: int          # 在全部快照中的序号 (0 = 最早, -1/最大 = 最新)
    ts: float
    reason: str
    session_id: str
    message_count: int
    event_count: int
    path: Path

    def as_row(self) -> Dict[str, Any]:
        return {
            "index": self.index,
            "time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.ts)),
            "reason": self.reason,
            "session_id": self.session_id,
            "messages": self.message_count,
            "events": self.event_count,
        }


class RewindManager:
    """会话快照管理器 (每个工作区一份, 落在 .qxt/snapshots/)。"""

    def __init__(
        self,
        workspace: str | Path,
        max_snapshots: Optional[int] = None,
        config: Any = None,
    ) -> None:
        self.workspace = Path(workspace)
        self.snapshot_dir = self.workspace / ".qxt" / "snapshots"
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        if max_snapshots is None:
            # 配置项 rewind.max_snapshots (默认 20); config 可为 None (测试)
            if config is not None:
                try:
                    max_snapshots = int(config.get("rewind.max_snapshots", 20))
                except Exception:  # noqa: BLE001
                    max_snapshots = 20
            else:
                max_snapshots = 20
        self.max_snapshots = max(1, int(max_snapshots))
        self._lock = threading.Lock()

    # ------------------------------------------------------------ 快照写入

    def snapshot(
        self,
        messages: List[Dict[str, Any]],
        reason: str = "user_input",
        session_id: str = "",
        event_count: int = 0,
    ) -> Path:
        """在用户输入前保存一份快照。返回快照文件路径。

        messages: 当前会话的 messages 列表 (深拷贝保存, 之后的修改不影响快照)。
        reason:   触发原因 (user_input / manual / handoff / restore ...), list 时展示。
        event_count: 会话 jsonl 当前事件行数 (CLI 层离线回退用, 运行时可不传)。
        """
        ts = time.time()
        data = {
            "ts": ts,
            "reason": reason,
            "session_id": session_id,
            "event_count": int(event_count or 0),
            "message_count": len(messages or []),
            "messages": copy.deepcopy(messages or []),
        }
        fname = (
            time.strftime("%Y%m%d-%H%M%S", time.localtime(ts))
            + "-" + uuid.uuid4().hex[:6] + ".json"
        )
        path = self.snapshot_dir / fname
        tmp = path.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        tmp.replace(path)
        with self._lock:
            self._rotate()
        return path

    def _rotate(self) -> None:
        """轮转: 只保留最近 max_snapshots 个快照, 多余的最旧快照删除。"""
        files = sorted(self.snapshot_dir.glob("*.json"), key=lambda p: p.stat().st_mtime)
        while len(files) > self.max_snapshots:
            old = files.pop(0)
            try:
                old.unlink()
            except OSError:
                pass

    # ------------------------------------------------------------ 列举 / 回退

    def list_snapshots(self) -> List[SnapshotInfo]:
        """按时间从早到晚列出全部快照 (index 0 = 最早)。"""
        files = sorted(self.snapshot_dir.glob("*.json"), key=lambda p: p.stat().st_mtime)
        out: List[SnapshotInfo] = []
        for i, p in enumerate(files):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except (OSError, json.JSONDecodeError):
                continue
            out.append(SnapshotInfo(
                index=i,
                ts=float(data.get("ts", p.stat().st_mtime)),
                reason=str(data.get("reason", "user_input")),
                session_id=str(data.get("session_id", "")),
                message_count=int(data.get("message_count", 0)),
                event_count=int(data.get("event_count", 0)),
                path=p,
            ))
        return out

    def _load(self, info: SnapshotInfo) -> Dict[str, Any]:
        with open(info.path, "r", encoding="utf-8") as f:
            return cast(Dict[str, Any], json.load(f))

    def restore(self, messages: List[Dict[str, Any]], index: int = -1) -> int:
        """把 messages 原位替换为指定快照的内容 (丢弃之后的对话)。

        index: 快照序号 (0=最早, -1=最新, 即 `/rewind` 默认行为=回退一个快照)。
               注意语义: `-1` 是**最新**快照; `/rewind` (不带参数) 应回退到
               **上一个**快照, 即最新快照的前一个, 由调用方传 -2。
        返回恢复后的消息条数。
        """
        snaps = self.list_snapshots()
        if not snaps:
            raise RewindError("没有可用快照 (还没有任何可回退的对话)")
        try:
            target = snaps[index]
        except IndexError:
            raise RewindError(
                f"快照索引越界: 共 {len(snaps)} 个快照, 可用序号 0~{len(snaps)-1}"
            ) from None
        data = self._load(target)
        messages[:] = copy.deepcopy(data.get("messages", []))
        return len(messages)

    def restore_previous(self, messages: List[Dict[str, Any]]) -> int:
        """`/rewind` 无参语义: 回退到上一个快照 (最新快照的前一个)。

        自动快照是在"用户输入前"保存的, 所以最新快照通常就是当前轮开始前的状态;
        回退一步 = 丢掉最新这次快照之后刚说的话, 回到它的前一个稳定点。
        若只有一个快照, 则回到该快照 (清空之后的内容)。
        """
        snaps = self.list_snapshots()
        if not snaps:
            raise RewindError("没有可用快照 (还没有任何可回退的对话)")
        idx = -2 if len(snaps) >= 2 else -1
        return self.restore(messages, idx)


# ------------------------------------------------------------------ CLI 离线回退

def rewind_session_file(
    session_file: str | Path,
    workspace: str | Path,
    index: Optional[int] = None,
    max_snapshots: Optional[int] = None,
) -> Dict[str, Any]:
    """CLI 层: 把指定会话的 jsonl 事件流截断到某个快照。

    策略: 在 workspace 的 .qxt/snapshots 里找 session_id 匹配的快照, 取其
    event_count, 把 session_file 重写为 "meta 头 + 前 event_count 条业务事件",
    并追加一条 ``rewind.applied`` 审计事件。

    返回 {"ok", "session_id", "kept_events", "removed_events", "snapshot_ts"}。
    """
    session_file = Path(session_file)
    if not session_file.exists():
        raise RewindError(f"会话文件不存在: {session_file}")
    session_id = session_file.stem

    mgr = RewindManager(workspace, max_snapshots=max_snapshots)
    snaps = [s for s in mgr.list_snapshots()
             if not s.session_id or s.session_id == session_id]
    if not snaps:
        raise RewindError(f"会话 {session_id} 没有可回退的快照")
    target = snaps[index if index is not None else -1]

    # 读原事件流
    records: List[Dict[str, Any]] = []
    with open(session_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    kept = target.event_count if target.event_count > 0 else _count_business_events(records)
    kept = min(kept, len(records))
    removed = len(records) - kept

    # 重写: 保留前 kept 条, 追加 rewind.applied
    out = records[:kept]
    out.append({
        "ts": time.time(),
        "type": "rewind.applied",
        "from_snapshot": str(target.path.name),
        "removed_events": removed,
    })
    tmp = session_file.with_suffix(".jsonl.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        for rec in out:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    tmp.replace(session_file)
    return {
        "ok": True,
        "session_id": session_id,
        "kept_events": kept,
        "removed_events": removed,
        "snapshot_ts": target.ts,
    }


def _count_business_events(records: List[Dict[str, Any]]) -> int:
    """统计业务事件数 (排除 session.meta / rewind.applied 等元事件)。"""
    skip = {"session.meta", "rewind.applied"}
    return sum(1 for r in records if r.get("type") not in skip)
