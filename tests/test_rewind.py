"""A2: Rewind 测试 —— 快照创建 / 回退 / list / to index / 最大快照数轮转 / CLI 离线回退。"""

from __future__ import annotations

import json
import time

import pytest

from qingxiaotuan.core.rewind import (
    RewindError,
    RewindManager,
    rewind_session_file,
)


def test_snapshot_creates_file(tmp_path):
    mgr = RewindManager(tmp_path)
    msgs = [{"role": "user", "content": "第一轮"}, {"role": "assistant", "content": "答1"}]
    path = mgr.snapshot(msgs, reason="user_input", session_id="sess-1")
    assert path.exists()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["message_count"] == 2
    assert data["reason"] == "user_input"
    assert data["session_id"] == "sess-1"
    assert len(data["messages"]) == 2


def test_snapshot_is_deep_copy(tmp_path):
    mgr = RewindManager(tmp_path)
    msgs = [{"role": "user", "content": "v1"}]
    mgr.snapshot(msgs, reason="user_input")
    msgs.append({"role": "assistant", "content": "v2"})
    snaps = mgr.list_snapshots()
    mgr.restore(msgs, 0)
    assert len(msgs) == 1  # 快照不受后续修改影响


def test_list_and_restore_previous(tmp_path):
    mgr = RewindManager(tmp_path)
    msgs = []
    for i in range(3):
        msgs = msgs + [{"role": "user", "content": f"第{i}轮"}]
        mgr.snapshot(msgs, reason="user_input")
    snaps = mgr.list_snapshots()
    assert len(snaps) == 3
    assert snaps[0].index == 0 and snaps[-1].index == 2

    # restore_previous: 3 个快照时回退到 index 1 (最新的前一个)
    cur = [{"role": "user", "content": f"第{i}轮"} for i in range(4)]
    n = mgr.restore_previous(cur)
    assert n == 2  # 回到第 2 条消息的快照 (index 1 有 2 条)


def test_restore_to_index(tmp_path):
    mgr = RewindManager(tmp_path)
    mgr.snapshot([{"role": "user", "content": "v1"}], reason="manual")
    mgr.snapshot([{"role": "user", "content": "v1"}, {"role": "assistant", "content": "v2"}],
                 reason="user_input")
    msgs = [{"role": "user", "content": "x"}] * 5
    n = mgr.restore(msgs, 0)
    assert n == 1
    assert msgs[0]["content"] == "v1"


def test_restore_empty_raises(tmp_path):
    mgr = RewindManager(tmp_path)
    with pytest.raises(RewindError):
        mgr.restore([], -1)


def test_rotate_max_snapshots(tmp_path):
    mgr = RewindManager(tmp_path, max_snapshots=3)
    for i in range(5):
        mgr.snapshot([{"role": "user", "content": f"m{i}"}], reason="user_input")
        time.sleep(0.01)
    files = list(mgr.snapshot_dir.glob("*.json"))
    assert len(files) == 3  # 只保留最近 3 个
    # 最早的 m0/m1 已被轮转删除, 剩下 m2/m3/m4
    contents = [json.loads(f.read_text(encoding="utf-8"))["messages"][0]["content"]
                for f in files]
    assert "m2" in contents and "m4" in contents and "m0" not in contents


def test_config_max_snapshots(tmp_path):
    class Cfg:
        def get(self, key, default=None):
            return {"rewind.max_snapshots": 2}.get(key, default)
    mgr = RewindManager(tmp_path, config=Cfg())
    assert mgr.max_snapshots == 2


def test_rewind_session_file(tmp_path):
    """CLI 离线回退: 会话 jsonl 截断到快照的 event_count。"""
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    sf = sessions / "20260101-090000-xyzxyz.jsonl"
    recs = [
        {"ts": 1.0, "type": "session.meta", "task": "t"},
        {"ts": 1.1, "type": "user", "message": {"content": "第一轮"}},
        {"ts": 1.2, "type": "assistant", "message": {"content": "答1"}},
        {"ts": 1.3, "type": "user", "message": {"content": "第二轮"}},
    ]
    sf.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in recs) + "\n",
                  encoding="utf-8")
    # 在 workspace 里拍一个快照 (event_count=3: meta + 2 条业务)
    mgr = RewindManager(tmp_path)
    mgr.snapshot([{"role": "user", "content": "第一轮"}],
                 reason="user_input", session_id="20260101-090000-xyzxyz",
                 event_count=3)
    result = rewind_session_file(sf, tmp_path)
    assert result["ok"] is True
    assert result["kept_events"] == 3
    assert result["removed_events"] == 1
    # 文件重写后末尾是 rewind.applied
    lines = sf.read_text(encoding="utf-8").strip().splitlines()
    assert json.loads(lines[-1])["type"] == "rewind.applied"
    # 第二轮 (最后一条 user) 已被丢弃
    body = "\n".join(lines)
    assert "第二轮" not in body
