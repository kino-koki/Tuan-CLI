"""定时任务存储 —— Hermes cron 的极简版。

任务存放在 ~/.tuan/cron/jobs.json:
    {"id", "name", "prompt", "interval_minutes", "last_run", "enabled"}
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
import uuid
from datetime import datetime as _dt
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import schedule as _cron_schedule
from .schedule import CronParseError


class CronStore:
    def __init__(self, home: Path) -> None:
        self.dir = home / "cron"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.file = self.dir / "jobs.json"
        # _read + _write 是非原子的读改写序列。多线程并发 add / remove 会:
        # 1) 读回同一个过期列表 → 后写覆盖前写, 任务丢失;
        # 2) 同时 os.replace 同一目标 → Windows 上 PermissionError, 任务丢失。
        # 实测: 100 次并发 add 100 个 job, 最终只保留 22 个。
        # 必须用 RLock 串行化所有读改写对。
        self._lock = threading.RLock()

    def _read(self) -> List[Dict[str, Any]]:
        if not self.file.exists():
            return []
        try:
            return json.loads(self.file.read_text(encoding="utf-8"))  # type: ignore[no-any-return]
        except json.JSONDecodeError:
            # 损坏: 备份后返回空, 避免后续写覆盖丢失原始数据。
            try:
                self.file.replace(self.file.with_suffix(".corrupted.bak"))
            except OSError:
                pass
            return []

    def _write(self, jobs: List[Dict[str, Any]]) -> None:
        """临时文件 + 原子替换写入, 崩溃不留下半截 jobs.json。"""
        self.dir.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix="jobs.", suffix=".tmp", dir=self.dir)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(jobs, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, self.file)
        finally:
            try:
                Path(temp_name).unlink()
            except FileNotFoundError:
                pass

    def add(self, name: str, prompt: str, interval_minutes: int,
            schedule: Optional[str] = None) -> Dict[str, Any]:
        """新增任务。

        - ``interval_minutes``: 每隔 N 分钟执行一次 (旧语义, 兼容);
        - ``schedule``: 可选, 标准 5 字段 cron 表达式 (如 ``"0 9 * * 1-5"``)。
          传入后优先按 cron 排期判定到期, 忽略 ``interval_minutes``。
          非法表达式直接抛 ``CronParseError``, 不写入半条坏数据。
        """
        # 提前校验 cron 表达式, 非法则不写盘 (fail-fast)
        sched_obj = None
        if schedule:
            sched_obj = _cron_schedule.parse(schedule)  # 非法抛 CronParseError
        with self._lock:
            jobs = self._read()
            job = {
                "id": uuid.uuid4().hex[:8],
                "name": name,
                "prompt": prompt,
                "interval_minutes": interval_minutes,
                "last_run": 0,
                "enabled": True,
                # 仅在使用 cron 排期时落盘该字段; 旧数据无此键也兼容
            }
            if sched_obj is not None:
                job["schedule"] = sched_obj.raw
            jobs.append(job)
            self._write(jobs)
        return job

    def remove(self, job_id: str) -> bool:
        with self._lock:
            jobs = self._read()
            kept = [j for j in jobs if j["id"] != job_id]
            self._write(kept)
        return len(kept) != len(jobs)

    def get(self, job_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            for j in self._read():
                if j["id"] == job_id:
                    return j
            return None

    def set_enabled(self, job_id: str, enabled: bool) -> bool:
        with self._lock:
            jobs = self._read()
            found = False
            for j in jobs:
                if j["id"] == job_id:
                    j["enabled"] = enabled
                    found = True
            if found:
                self._write(jobs)
        return found

    def update(self, job_id: str, **fields: Any) -> bool:
        with self._lock:
            jobs = self._read()
            found = False
            for j in jobs:
                if j["id"] == job_id:
                    for k, v in fields.items():
                        if v is not None:
                            j[k] = v
                    found = True
            if found:
                self._write(jobs)
        return found

    def list(self) -> List[Dict[str, Any]]:
        with self._lock:
            return self._read()

    def due(self) -> List[Dict[str, Any]]:
        now = time.time()
        now_dt = _dt.fromtimestamp(now)
        with self._lock:
            due: List[Dict[str, Any]] = []
            for j in self._read():
                # 畸形条目 (手工编辑/旧版本残留缺字段) 绝不能让整轮调度崩掉:
                # 缺字段 / 类型非法 / 未启用 的条目一律跳过。
                if not j.get("enabled"):
                    continue

                cron_expr = j.get("schedule")
                if cron_expr:
                    # ---- cron 排期语义: 最近一次命中分钟 > last_run 即到期 ----
                    try:
                        sched = _cron_schedule.parse(cron_expr)
                    except (CronParseError, ValueError):
                        continue  # 历史坏数据: 跳过, 不炸整轮
                    fired = sched.last_fire(now_dt)
                    if fired is None:
                        continue
                    if fired.timestamp() > j.get("last_run", 0):
                        due.append(j)
                    continue

                # ---- 旧 interval 语义 ----
                interval = j.get("interval_minutes")
                # 0 是合法语义 (每个 tick 都触发); 只拒绝非数字 / bool 伪装数字。
                if isinstance(interval, bool) or not isinstance(interval, (int, float)):
                    continue
                if now - j.get("last_run", 0) >= interval * 60:
                    due.append(j)
            return due

    def mark_run(self, job_id: str) -> None:
        with self._lock:
            jobs = self._read()
            for j in jobs:
                if j["id"] == job_id:
                    j["last_run"] = time.time()
            self._write(jobs)
