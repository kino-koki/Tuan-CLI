"""FastFileIndex 与 pick_files 工具测试 (速度主线 A)。

覆盖: 增量正确性 (新增/修改/删除后索引同步且未变文件不被重扫)、
指纹失效、rank 排序与理由文本、related 引用边、持久化恢复、
噪声目录跳过、原子写无残留、pick_files 工具注册进 registry 且可用。
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from tuan_cli.config import Config
from tuan_cli.context.fast_index import FastFileIndex
from tuan_cli.core.kernel import Kernel
from tuan_cli.tools import PickerPlugin, ToolRegistryPlugin
from tuan_cli.tools.base import ToolContext


def _mk(root: Path, rel: str, content: str) -> Path:
    """在 root 下写一个文件 (自动建父目录), 返回路径。"""
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return p


# ------------------------------------------------------------------ 增量正确性

def test_incremental_unchanged_files_not_rerescan(tmp_path):
    """未变文件不被重扫: 二次 build rebuilt==0。"""
    _mk(tmp_path, "a.py", "def Alpha():\n    pass\n")
    _mk(tmp_path, "b.py", "class Beta:\n    pass\n")
    idx = FastFileIndex(str(tmp_path))
    s1 = idx.build()
    assert s1.file_count == 2 and s1.added == 2
    s2 = idx.build()
    assert s2.rebuilt == 0 and s2.added == 0 and s2.unchanged == 2


def test_add_file_synced(tmp_path):
    _mk(tmp_path, "a.py", "def Alpha():\n    pass\n")
    idx = FastFileIndex(str(tmp_path))
    idx.build()
    _mk(tmp_path, "c.py", "def Gamma():\n    pass\n")
    s = idx.build()
    assert s.added == 1 and s.rebuilt == 0
    assert idx.find("c.py"), "新文件应可被 find 命中"


def test_modify_only_rerescans_changed_one(tmp_path):
    _mk(tmp_path, "a.py", "def Alpha():\n    pass\n")
    _mk(tmp_path, "b.py", "class Beta:\n    pass\n")
    idx = FastFileIndex(str(tmp_path))
    idx.build()
    # 只改 a.py (内容变长 → size 变化触发指纹失效)
    _mk(tmp_path, "a.py", "def Alpha():\n    return 1  # changed\n")
    s = idx.build()
    assert s.rebuilt == 1 and s.added == 0 and s.removed == 0


def test_delete_file_removed(tmp_path):
    _mk(tmp_path, "a.py", "def Alpha():\n    pass\n")
    _mk(tmp_path, "b.py", "class Beta:\n    pass\n")
    idx = FastFileIndex(str(tmp_path))
    idx.build()
    (tmp_path / "a.py").unlink()
    s = idx.build()
    assert s.removed == 1
    assert not idx.find("a.py")
    assert idx.stats()["file_count"] == 1


def test_fingerprint_invalidation_on_touch(tmp_path):
    """指纹失效: 内容不变但 mtime 被刷新 → 必须重扫该文件。"""
    p = _mk(tmp_path, "a.py", "def Alpha():\n    pass\n")
    idx = FastFileIndex(str(tmp_path))
    idx.build()
    future = time.time() + 10
    os.utime(p, (future, future))  # 只动 mtime, 不改内容
    s = idx.build()
    assert s.rebuilt == 1, "mtime 变化应使指纹失效并重扫该文件"


# ------------------------------------------------------------------ 查询

def test_rank_order_and_reason(tmp_path):
    _mk(tmp_path, "auth.py", "def login_timeout_retry():\n    pass\n")
    _mk(tmp_path, "util.py", "def helper():\n    pass\n")
    idx = FastFileIndex(str(tmp_path))
    idx.build()
    hits = idx.rank(["login_timeout_retry"], limit=5)
    assert hits, "应有命中"
    path, score, reason = hits[0]
    assert path == "auth.py" and score > 0
    assert "含符号" in reason and "login_timeout_retry" in reason
    assert all(h[0] != "util.py" for h in hits), "无关文件不应出现"
    assert len(hits[0]) == 3  # (path, score, reason) 三元组


def test_related_import_edges(tmp_path):
    _mk(tmp_path, "pkg/core.py", "def CoreService():\n    pass\n")
    _mk(tmp_path, "pkg/app.py", "from pkg.core import CoreService\n\nclass App:\n    pass\n")
    idx = FastFileIndex(str(tmp_path))
    idx.build()
    rels = idx.related("pkg/app.py")
    assert "pkg/core.py" in [r[0] for r in rels]


def test_find_substring(tmp_path):
    _mk(tmp_path, "src/handlers/auth_handler.py", "def h():\n    pass\n")
    _mk(tmp_path, "src/utils.py", "def u():\n    pass\n")
    idx = FastFileIndex(str(tmp_path))
    idx.build()
    hits = idx.find("auth_handler")
    assert len(hits) == 1 and hits[0]["relpath"].endswith("auth_handler.py")


# ------------------------------------------------------------------ 持久化 / 目录跳过 / 原子写

def test_persistence_across_instances(tmp_path):
    _mk(tmp_path, "a.py", "def Alpha():\n    pass\n")
    FastFileIndex(str(tmp_path)).build()
    cache = tmp_path / ".tuan" / "fastindex" / "index.json"
    assert cache.exists(), "索引应持久化到 .tuan/fastindex/index.json"
    data = json.loads(cache.read_text(encoding="utf-8"))
    assert "a.py" in data["entries"]

    # 新实例: 从磁盘恢复, 且再次 build 不重扫
    idx2 = FastFileIndex(str(tmp_path))
    assert idx2.stats()["file_count"] == 1
    s = idx2.build()
    assert s.rebuilt == 0 and s.unchanged == 1


def test_skip_noise_dirs(tmp_path):
    _mk(tmp_path, "real.py", "def Real():\n    pass\n")
    _mk(tmp_path, "node_modules/dep.js", "function Dep(){}")
    _mk(tmp_path, ".git/config", "[core]\n")
    _mk(tmp_path, "__pycache__/x.pyc", "binary")
    idx = FastFileIndex(str(tmp_path))
    idx.build()
    paths = [e["relpath"] for e in idx.find("", limit=100)]
    assert "real.py" in paths
    assert not any("node_modules" in p for p in paths)
    assert not any(p.startswith(".git") for p in paths)
    assert not any("__pycache__" in p for p in paths)


def test_atomic_write_no_tmp_leftover(tmp_path):
    _mk(tmp_path, "a.py", "def Alpha():\n    pass\n")
    FastFileIndex(str(tmp_path)).build()
    d = tmp_path / ".tuan" / "fastindex"
    assert (d / "index.json").exists()
    assert not (d / "index.json.tmp").exists(), "原子写不应残留 .tmp"


# ------------------------------------------------------------------ pick_files 工具

def test_registered_in_builtin_plugins():
    from tuan_cli.tools import builtin_tool_plugins
    names = [type(p).__name__ for p in builtin_tool_plugins()]
    assert "PickerPlugin" in names


def test_pick_files_tool_registered_and_dispatch(tmp_path):
    _mk(tmp_path, "auth.py", "def login_timeout_retry():\n    pass\n")
    k = Kernel()
    k.provide("config", Config(), owner="test")
    k.register(ToolRegistryPlugin())
    k.register(PickerPlugin())
    k.activate_all()
    reg = k.require("tool_registry")

    t = reg.get("pick_files")
    assert t is not None
    assert t.read_only is True
    assert t.parameters["required"] == ["task"]
    # schema 合法 (OpenAI function 形式)
    assert t.schema()["type"] == "function"
    assert t.schema()["function"]["name"] == "pick_files"

    ctx = ToolContext(kernel=k, workspace=str(tmp_path))
    out = reg.dispatch("pick_files",
                       json.dumps({"task": "login_timeout_retry 登录重试"}), ctx)
    assert "auth.py" in out
    assert "未读全文" in out  # 明确提示省 token
