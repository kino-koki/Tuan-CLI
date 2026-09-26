"""Project 层 —— 项目级持久化上下文 / 工作区隔离 (四层边界 · 第一层)。

理念 (对标 B 站 BV1j3YL6oEvs): "Project 层 = 长期工作的固定办公室"。
每个工作目录 (项目) 拥有独立的 ``.qxt/``:

    <workspace>/.qxt/
        config.yaml      项目级配置 (覆盖用户默认配置)
        goal.json        当前项目目标
        memory.db        项目级记忆 (SQLite, 与全局记忆隔离)
        sessions.json    项目会话索引 (哪些会话属于这个项目)
        snapshots/       Rewind 快照 (见 core/rewind.py)
        subagents/       子代理独立工作目录
        worktrees/       git worktree 实验目录

隔离语义:
- 不同目录的 qxt 会话**不共享**记忆 / 配置 / 会话列表 (project.isolation_enabled=true);
- 已有 ``.qxt/`` 目录的项目自动识别, 无需重复 ``qxt project init``;
- 全局项目索引在 ``~/.qingxiaotuan/projects.json``, 供 ``qxt project list`` 列举。
"""

from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..config import home_dir


QXT_MD_TEMPLATE = """# 项目说明 (QXT.md)

> 青小团每次进入本目录都会读这份文件。写清楚这个项目是干什么的、
> 怎么跑测试、有哪些约定, Agent 就不用每次重新问你。

## 项目概述
(这个项目解决什么问题? 主要技术栈?)

## 常用命令
- 安装:
- 跑测试:
- 构建:
- 启动:

## 目录结构
(关键目录各放什么)

## 约定 / 注意事项
(代码风格、提交规范、不要碰的目录……)
"""


@dataclass
class ProjectInfo:
    """当前项目信息。"""

    project_id: str
    path: str
    created_at: float
    session_count: int = 0
    memory_count: int = 0
    goal: str = ""
    initialized: bool = True


class ProjectLayer:
    """项目层: 管理一个工作目录的 .qxt/ 结构。"""

    DIR_NAME = ".qxt"

    def __init__(self, workspace: str | Path, config: Any = None) -> None:
        self.workspace = Path(workspace).resolve()
        self.dir = self.workspace / self.DIR_NAME
        self.config = config
        # 配置项 project.isolation_enabled (默认 true)
        self.isolation_enabled = self._cfg("project.isolation_enabled", True)

    def _cfg(self, key: str, default: Any) -> Any:
        if self.config is None:
            return default
        try:
            return self.config.get(key, default)
        except Exception:  # noqa: BLE001
            return default

    # ------------------------------------------------------------ 检测 / 初始化

    @classmethod
    def detect(cls, workspace: str | Path) -> bool:
        """该目录是否已经是一个 qxt 项目 (有 .qxt/project.json)。"""
        return (Path(workspace) / cls.DIR_NAME / "project.json").exists()

    def exists(self) -> bool:
        return self.dir.exists() and (self.dir / "project.json").exists()

    def init(self, force: bool = False) -> ProjectInfo:
        """在当前目录初始化 .qxt 项目结构 (幂等)。

        已存在时不重复初始化 (直接返回已有信息); ``force=True`` 才重建骨架。
        """
        if self.exists() and not force:
            return self.info()

        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / "snapshots").mkdir(exist_ok=True)
        (self.dir / "subagents").mkdir(exist_ok=True)
        (self.dir / "worktrees").mkdir(exist_ok=True)

        project_id = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
        created_at = time.time()
        meta = {
            "project_id": project_id,
            "path": str(self.workspace),
            "created_at": created_at,
        }
        self._write_json(self.dir / "project.json", meta)
        self._write_json(self.dir / "goal.json", {"goal": "", "updated_at": created_at})
        self._write_json(self.dir / "sessions.json", {"project_id": project_id, "sessions": []})
        # 项目级配置骨架 (yaml 注释占位)
        cfg_file = self.dir / "config.yaml"
        if not cfg_file.exists():
            cfg_file.write_text(
                "# 项目级配置 (覆盖全局用户配置)\n# 示例:\n# model:\n#   effort: high\n",
                encoding="utf-8",
            )
        # memory.db 占位 (实际由 MemoryStore 在隔离开启时使用)
        (self.dir / "memory.db").touch(exist_ok=True)
        # QXT.md 模板 (不覆盖已有)
        qxt_md = self.workspace / "QXT.md"
        if not qxt_md.exists():
            qxt_md.write_text(QXT_MD_TEMPLATE, encoding="utf-8")

        self._register_global(meta)
        return self.info()

    # ------------------------------------------------------------ 信息

    def info(self) -> ProjectInfo:
        """读取当前项目信息。未初始化时返回 initialized=False。"""
        if not self.exists():
            return ProjectInfo(project_id="", path=str(self.workspace), created_at=0.0,
                               initialized=False)
        meta = self._read_json(self.dir / "project.json")
        goal = self._read_json(self.dir / "goal.json")
        sessions = self._read_json(self.dir / "sessions.json")
        return ProjectInfo(
            project_id=meta.get("project_id", ""),
            path=str(self.workspace),
            created_at=float(meta.get("created_at", 0.0)),
            session_count=len(sessions.get("sessions", []) or []),
            memory_count=self._memory_count(),
            goal=str(goal.get("goal", "") or ""),
            initialized=True,
        )

    def _memory_count(self) -> int:
        """项目记忆条数: 读 memory.db 的 user 表行数 (best-effort, 损坏返回 0)。"""
        db = self.dir / "memory.db"
        if not db.exists() or db.stat().st_size == 0:
            return 0
        try:
            import sqlite3
            con = sqlite3.connect(str(db))
            try:
                return int(con.execute("SELECT COUNT(*) FROM memories").fetchone()[0])
            finally:
                con.close()
        except Exception:  # noqa: BLE001
            return 0

    def attach_session(self, session_id: str, task: str = "") -> None:
        """把一个会话登记到本项目的会话索引 (交接/新会话时调用)。"""
        f = self.dir / "sessions.json"
        data = self._read_json(f) if f.exists() else {"sessions": []}
        data.setdefault("project_id", self.info().project_id)
        data.setdefault("sessions", []).append({
            "session_id": session_id,
            "task": task[:200],
            "ts": time.time(),
        })
        self._write_json(f, data)

    # ------------------------------------------------------------ 全局索引

    def _index_file(self) -> Path:
        return home_dir() / "projects.json"

    def _register_global(self, meta: Dict[str, Any]) -> None:
        """把项目登记到全局索引 ~/.qingxiaotuan/projects.json。"""
        f = self._index_file()
        f.parent.mkdir(parents=True, exist_ok=True)
        try:
            data = self._read_json(f) if f.exists() else {"projects": []}
        except Exception:  # noqa: BLE001
            data = {"projects": []}
        items = data.setdefault("projects", [])
        items = [p for p in items if p.get("path") != str(self.workspace)]
        items.append({
            "project_id": meta["project_id"],
            "path": str(self.workspace),
            "created_at": meta["created_at"],
        })
        self._write_json(f, {"projects": items})

    def list_projects(self) -> List[Dict[str, Any]]:
        """列出已知项目 (从全局索引读, 顺带核对目录是否还在)。"""
        f = self._index_file()
        if not f.exists():
            return []
        data = self._read_json(f)
        out = []
        for p in data.get("projects", []):
            p = dict(p)
            p["exists"] = Path(p.get("path", "")).exists()
            out.append(p)
        return out

    # ------------------------------------------------------------ 隔离判定

    def project_memory_dir(self) -> Path:
        """隔离模式下项目级记忆应落在哪里 (给 MemoryStore 用)。"""
        return self.dir

    # ------------------------------------------------------------ 小工具

    @staticmethod
    def _read_json(path: Path) -> Dict[str, Any]:
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            return {}

    @staticmethod
    def _write_json(path: Path, data: Dict[str, Any]) -> None:
        tmp = path.with_suffix(path.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        tmp.replace(path)
