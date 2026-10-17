"""共享原子写工具 —— 状态文件的崩溃一致性。

任何需要持久化且可能被进程重启后重新读取的状态文件
(白名单 / 信任标记 / 完整性快照 / 队列 / 规则等) 都应通过
``atomic_write_text`` 落盘: 同目录唯一临时文件 + fsync + os.replace,
崩溃或异常时目标文件要么是旧版本要么是新版本, 绝不留下半截内容。
"""

from __future__ import annotations

import os
import stat
import tempfile
from pathlib import Path


def atomic_write_text(path: str | os.PathLike[str], content: str,
                      *, preserve_mode: bool = True) -> None:
    """原子写文本文件。

    - 临时文件与目标同目录 (保证 os.replace 在同一文件系统内)。
    - 写入后 fsync, 再 os.replace 原子替换。
    - preserve_mode=True 时保留目标既有权限位 (如可执行位); 新文件用
      默认 0644 & umask。
    - 任何失败都会清理临时文件并重新抛出, 目标保持原样。
    """
    p = Path(path)
    directory = p.parent
    directory.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{p.name}.", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
            fh.flush()
            os.fsync(fh.fileno())
        if preserve_mode and p.exists():
            try:
                os.chmod(tmp, stat.S_IMODE(p.stat().st_mode))
            except OSError:
                pass
        os.replace(tmp, p)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
