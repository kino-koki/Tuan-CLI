"""tuan session 子命令分发完整性回归。

此前 argparse 注册了 compare / trend / events / wire / query / sourcer / digest
以及 trajectory 的 analyze / timeline / fork / snapshots, 但 cmd_session 分发
未覆盖 —— 全部静默落入"用法"输出且 rc=0 (比 harden 的 rc=1 更隐蔽, 易被 CI
漏检)。本测试固化:
  1. 每个注册的 session_cmd 都可在 cmd_session 分发到 (不再落用法错误);
  2. trajectory 的 analyze / timeline / fork / snapshots 不再静默降级为 show;
  3. 关键命令的核心行为正确。
"""
from __future__ import annotations

import contextlib
import io
import json
import pathlib
import sys
import tempfile
import time

import pytest

_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from tuan_cli.cli import cmd_session  # noqa: E402
from tuan_cli.config import home_dir  # noqa: E402


class _NS:
    pass


def _make_session_dir(tmp_path, n: int = 2) -> pathlib.Path:
    """构造 n 个非空会话文件, 返回 sessions 目录。"""
    sess = tmp_path / "sessions"
    sess.mkdir(parents=True, exist_ok=True)
    for i in range(n):
        sid = f"20260101-00000{i}-abc{i}def"
        with open(sess / f"{sid}.jsonl", "w", encoding="utf-8") as f:
            f.write(json.dumps({"ts": time.time() - i * 100,
                                "type": "session.meta",
                                "task": f"任务{i}", "started_at": time.time()}) + "\n")
            f.write(json.dumps({"ts": time.time(), "type": "user",
                                "message": {"role": "user", "content": f"你好{i}"}}) + "\n")
            f.write(json.dumps({"ts": time.time(), "type": "assistant",
                                "message": {"role": "assistant", "content": f"回复{i}"}}) + "\n")
            f.write(json.dumps({"ts": time.time(), "type": "tool_call",
                                "name": "read_file", "status": "ok"}) + "\n")
    return sess


def _run(session_cmd: str, tmp_path, **kwargs) -> tuple[int, str, str]:
    """构造 args namespace 并调用 cmd_session (home 指向 tmp_path)。"""
    ns = _NS()
    ns.session_cmd = session_cmd
    for key, val in kwargs.items():
        setattr(ns, key, val)
    # 用 tmp_path 覆盖 home, 让会话文件可被发现
    out = io.StringIO()
    err = io.StringIO()
    original = cmd_session.home_dir
    try:
        cmd_session.home_dir = lambda: pathlib.Path(tmp_path)
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = cmd_session.cmd_session(ns)
    finally:
        cmd_session.home_dir = original
    return rc, out.getvalue(), err.getvalue()


class TestSessionDispatchReachability:
    """注册的 session_cmd 必须全部可分发 (0 死命令 / 0 静默降级)。"""

    @pytest.mark.parametrize(
        "cmd",
        ["list", "stats", "compare", "trend", "events", "wire", "query",
         "sourcer", "digest", "replay", "trajectory"],
    )
    def test_registered_cmd_dispatchable(self, cmd, tmp_path):
        sess = _make_session_dir(tmp_path)
        sid = sess.glob("*.jsonl").__next__().stem
        base = {"session": sid}
        if cmd == "compare":
            base = {"session_a": sid, "session_b": sid}
        elif cmd in ("sourcer",):
            base = {"sourcer_cmd": "list", "session": sid}
        rc, out, err = _run(cmd, tmp_path, **base)
        assert "用法: tuan session" not in out, f"{cmd} 落入用法错误"
        # 这些命令应成功 (rc=0) 或带合理错误码; 关键是不落用法
        assert rc in (0, 1, 2)

    @pytest.mark.parametrize(
        "traj_cmd",
        ["analyze", "timeline", "fork", "snapshots"],
    )
    def test_trajectory_subcmd_no_longer_degrades_to_show(self, traj_cmd, tmp_path):
        sess = _make_session_dir(tmp_path)
        sid = sess.glob("*.jsonl").__next__().stem
        extra = {"session": sid, "at": 1, "label": "测试", "json": False}
        if traj_cmd == "analyze":
            extra["json"] = False
        rc, out, err = _run("trajectory", tmp_path, traj_cmd=traj_cmd, **extra)
        # 不再静默显示 show 的 "Trajectory" 摘要头
        assert "轨迹分析" not in out or traj_cmd == "analyze"
        if traj_cmd == "analyze":
            assert "总事件" in out, out

    def test_compare_behavior(self, tmp_path):
        sess = _make_session_dir(tmp_path)
        ids = sorted(p.stem for p in sess.glob("*.jsonl"))
        assert len(ids) >= 2
        rc, out, err = _run("compare", tmp_path, session_a=ids[0], session_b=ids[1])
        assert "跨会话差异对比" in out, out

    def test_events_behavior(self, tmp_path):
        sess = _make_session_dir(tmp_path)
        sid = sess.glob("*.jsonl").__next__().stem
        rc, out, err = _run("events", tmp_path, session=sid, kind=None, limit=30)
        assert "事件列表" in out, out

    def test_query_count_behavior(self, tmp_path):
        sess = _make_session_dir(tmp_path)
        sid = sess.glob("*.jsonl").__next__().stem
        rc, out, err = _run("query", tmp_path, session=sid, count=True,
                            kind=None, tag=None, since=None, until=None,
                            since_seq=0, until_seq=0, limit=1000)
        assert out.strip().isdigit(), out

    def test_wire_no_wirefile_ok(self, tmp_path):
        _make_session_dir(tmp_path)
        rc, out, err = _run("wire", tmp_path, session=None, json=False)
        # 无 wire.jsonl 时应优雅返回 0 而非崩溃
        assert rc in (0, 1), out

    def test_sourcer_fork_get_replay_resume_chain(self, tmp_path):
        """sourcer 子命令 fork→get→replay→resume 全链可达且行为正确。"""
        sess = _make_session_dir(tmp_path)
        sid = sess.glob("*.jsonl").__next__().stem
        # fork (在序号 1 分叉)
        rc, out, err = _run("sourcer", tmp_path, sourcer_cmd="fork",
                            session=sid, at=1, reason="回归", json=True)
        assert rc == 0, out
        fork_id = json.loads(out)["fork_id"]
        assert fork_id.startswith("fork-")
        # list
        rc, out, err = _run("sourcer", tmp_path, sourcer_cmd="list",
                            session=sid, json=True)
        assert rc == 0, out
        forks = json.loads(out)
        assert any(f["fork_id"] == fork_id for f in forks), out
        # get
        rc, out, err = _run("sourcer", tmp_path, sourcer_cmd="get",
                            session=sid, fork_id=fork_id, json=True)
        assert rc == 0, out
        assert json.loads(out)["fork_id"] == fork_id
        # replay
        rc, out, err = _run("sourcer", tmp_path, sourcer_cmd="replay",
                            session=sid, fork_id=fork_id, to_seq=0, json=True)
        assert rc == 0, out
        assert isinstance(json.loads(out), list)
        # resume
        rc, out, err = _run("sourcer", tmp_path, sourcer_cmd="resume",
                            session=sid, fork_id=fork_id, json=True)
        assert rc == 0, out
        assert isinstance(json.loads(out), list)

    def test_trajectory_analyze_timeline_fork_snapshots_chain(self, tmp_path):
        """trajectory 子命令 analyze/timeline/fork/snapshots 全链可达。"""
        sess = _make_session_dir(tmp_path)
        sid = sess.glob("*.jsonl").__next__().stem
        # analyze
        rc, out, err = _run("trajectory", tmp_path, traj_cmd="analyze",
                            session=sid, json=True)
        assert rc == 0, out
        stats = json.loads(out)
        assert stats["total_events"] >= 3, out
        # timeline
        rc, out, err = _run("trajectory", tmp_path, traj_cmd="timeline",
                            session=sid, limit=50, json=True)
        assert rc == 0, out
        assert isinstance(json.loads(out), list)
        # fork
        rc, out, err = _run("trajectory", tmp_path, traj_cmd="fork",
                            session=sid, at=1, label="回归", json=True)
        assert rc == 0, out
        assert json.loads(out)["events"] >= 1
        # snapshots
        rc, out, err = _run("trajectory", tmp_path, traj_cmd="snapshots",
                            json=True)
        assert rc == 0, out
        assert isinstance(json.loads(out), list)
