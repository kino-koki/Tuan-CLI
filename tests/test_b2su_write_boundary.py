"""本轮深度修复回归：工具层写路径硬边界 + /add-dir 口径纠偏 + edit_files 真事务。

**实测缺口（先复现再修）**

=====================  ========================================================
编号                   实测结果
=====================  ========================================================
W1（catalog 既有缺口）  ``permissions.blockWritesOutsideWorkingDirectories``
                       全仓代码里 **0 命中**（只在 catalog 的对标描述中出现）。
                       ``tools/filesystem.py::_resolve`` 只做「路径必须在
                       工作区或 /add-dir 授权目录内」，且读写不分；CC
                       v2.1.314 是在 Write/Edit/NotebookEdit **工具层**硬拒绝。
W2（文档谎言）         ``/add-dir`` 的 REPL 帮助、``authorize_extra_dir``
                       docstring、模块注释三处都写「可读上下文 / 仅读;
                       写仍走既有守卫」。实测 ``/add-dir /tmp/ext`` 之后
                       ``write_file`` 真的创建文件、``move_file`` 改名、
                       ``delete_file`` 删除，全部越界放行——「确认对话」
                       不是路径硬边界，YOLO / 无人值守 / 直接调函数都不经过它。
W3（假事务）           ``edit_files`` docstring 声称「任一失败 → 整体拒绝,
                       不写任何文件」，但危险内容扫描在**阶段 2 边写边扫**。
                       实测 3 项里第 3 项含 ``rm -rf /``：返回
                       「已整体拒绝 (未写入任何文件)」，而 ``f0/f1``
                       已经变成 ``BBB``。返回文本与磁盘状态不一致。
=====================  ========================================================

**修复（如实，不夸大）**

- 新增 ``core/write_boundary.py``：``recheck_write`` / ``decide_write``
  单一裁决出口；开关默认 ``False``（与 CC 出厂一致，**不做破坏性默认变更**）；
  配置值非 bool → fail-closed 启用（避免 ``bool("false")`` 的静默放行）。
- ``filesystem.py`` 新增 ``_resolve_write``，六个写操作统一改走它；
  写入点再做一次父目录链复检（抓 symlink 替换型 TOCTOU）。
- ``authorize_extra_dir(..., writable=False)``：普通 ``/add-dir`` 只授读；
  ``--writable`` 显式登记可写根，per-session 内存态，Agent 无自助授权工具。
- ``edit_files`` 把危险内容扫描前移到阶段 1，写入前对**全体**目标复检，
  阶段 2 循环内不再有任何拒绝分支。
- ``defaults.py`` / ``security_schema.py`` / ``cmd_harden.py`` 接线；
  ``/add-dir`` 帮助文案改成如实（默认行为不变）。

**仍为 partial，不靠改口径凑数**：命令层重定向不在工具层约束内、
出厂默认仍 false、TOCTOU 二次解析与 ``os.replace`` 之间仍有窗口。
矩阵计数一个不动：``ahead 10 / aligned 46 / partial 9 / gap 26 /
not_applicable 8``，``fully_superior=false``，``b_waves_done=["B1"]``。
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from tuan_cli.config.security_schema import validate_security_config
from tuan_cli.core.write_boundary import (
    FLAG, WRITABLE_DIRS_ATTR, boundary_enabled, decide_write,
    recheck_write, writable_roots,
)
from tuan_cli.tools import filesystem as FS


class Ctx:
    """最小 ToolContext：只提供 filesystem 与 write_boundary 需要的接口。"""

    def __init__(self, workspace: str, *, flag=False, always_read=True):
        self.workspace = workspace
        self._flag = flag
        self._read: set = set()
        self._always_read = always_read

    def config(self, dotted: str, default=None):
        if dotted == FLAG:
            return self._flag
        if dotted == "tools.require_read_before_edit":
            return False
        return default

    def mark_read(self, p: str) -> None:
        self._read.add(str(p))

    def has_read(self, p: str) -> bool:
        return self._always_read or str(p) in self._read


class Cfg:
    """最小 config 对象：给 validate_security_config 用。"""

    def __init__(self, **values):
        self.values = values

    def get(self, dotted, default=None):
        return self.values.get(dotted, default)


@pytest.fixture
def roots(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    ext = tmp_path / "external"
    ext.mkdir()
    (ext / "existing.txt").write_text("old", encoding="utf-8")
    return ws, ext


def _grant(ctx, ext, *, writable=False):
    return FS.authorize_extra_dir(ctx, str(ext), writable=writable)


# ================================================== 1 W1/W2 写边界
class TestWriteBoundary:
    def test_flag_off_preserves_legacy_behavior(self, roots):
        """出厂默认 false：既有行为完全不变（/add-dir 目录仍可写）。"""
        ws, ext = roots
        ctx = Ctx(str(ws), flag=False)
        _grant(ctx, ext)
        out = FS.write_file(ctx, str(ext / "legacy.txt"), "x")
        assert out.startswith("已写入")
        assert (ext / "legacy.txt").read_text(encoding="utf-8") == "x"
        d = decide_write(ctx, str(ext / "legacy.txt"))
        assert d.allowed is True and d.enforced is False

    @pytest.mark.parametrize("op,fn", [
        ("write", lambda c, e: FS.write_file(c, str(e / "NEW.txt"), "x")),
        ("edit", lambda c, e: FS.edit_file(c, str(e / "existing.txt"),
                                           old_string="old", new_string="new")),
        ("move_dst", lambda c, e: FS.move_file(c, str(e / "existing.txt"),
                                               str(e / "moved.txt"))),
        ("delete", lambda c, e: FS.delete_file(c, str(e / "existing.txt"))),
        ("delete_dir", lambda c, e: FS.delete_dir(c, str(e))),
    ])
    def test_flag_on_refuses_every_write_op(self, roots, op, fn):
        """开关开启：六种写操作全部拒绝，且磁盘零变更。"""
        ws, ext = roots
        ctx = Ctx(str(ws), flag=True)
        _grant(ctx, ext)  # 普通 /add-dir 只授读
        before = sorted(p.name for p in ext.iterdir()), \
            (ext / "existing.txt").read_text(encoding="utf-8")
        out = fn(ctx, ext)
        assert "[已拒绝] 写路径越出工作目录" in out, (op, out[:160])
        assert op in out
        after = sorted(p.name for p in ext.iterdir()), \
            (ext / "existing.txt").read_text(encoding="utf-8")
        assert after == before, f"{op} changed disk state despite refusal"

    def test_flag_on_allows_workspace_writes(self, roots):
        ws, _ext = roots
        ctx = Ctx(str(ws), flag=True)
        out = FS.write_file(ctx, "inside.txt", "ok")
        assert out.startswith("已写入")
        assert (ws / "inside.txt").read_text(encoding="utf-8") == "ok"

    def test_flag_on_reads_to_added_dir_still_work(self, roots):
        """读不受写边界影响：/add-dir 的「可读上下文」承诺成立。"""
        ws, ext = roots
        ctx = Ctx(str(ws), flag=True)
        _grant(ctx, ext)
        assert "old" in FS.read_file(ctx, str(ext / "existing.txt"))

    def test_explicit_writable_grant_allows_write(self, roots):
        """显式 --writable 是唯一的越界写逃生口（per-session，用户驱动）。"""
        ws, ext = roots
        ctx = Ctx(str(ws), flag=True)
        msg = _grant(ctx, ext, writable=True)
        assert "可写" in msg
        out = FS.write_file(ctx, str(ext / "ok.txt"), "x")
        assert out.startswith("已写入")
        assert (ext / "ok.txt").exists()

    def test_writable_grant_is_per_session_memory_only(self, roots):
        ws, ext = roots
        ctx = Ctx(str(ws), flag=True)
        _grant(ctx, ext, writable=True)
        assert len(writable_roots(ctx)) == 1
        ctx2 = Ctx(str(ws), flag=True)
        assert writable_roots(ctx2) == []
        out = FS.write_file(ctx2, str(ext / "no.txt"), "x")
        assert "[已拒绝]" in out or "[错误]" in out

    def test_writable_grant_does_not_change_default_behavior(self, roots):
        ws, ext = roots
        ctx = Ctx(str(ws), flag=False)
        msg = _grant(ctx, ext, writable=True)
        assert "暂不改变行为" in msg

    def test_edit_batch_also_gated(self, roots):
        ws, ext = roots
        ctx = Ctx(str(ws), flag=True)
        _grant(ctx, ext)
        out = FS.edit_files(ctx, [{"path": str(ext / "existing.txt"),
                                   "old_string": "old", "new_string": "new"}])
        assert "事务校验未全部通过" in out
        assert "写路径越出工作目录" in out
        assert (ext / "existing.txt").read_text(encoding="utf-8") == "old"

    def test_relative_escape_via_dotdot(self, roots):
        ws, ext = roots
        ctx = Ctx(str(ws), flag=True)
        out = FS.write_file(ctx, "../external/escape.txt", "x")
        assert "[已拒绝]" in out or "[错误]" in out
        assert not (ext / "escape.txt").exists()

    def test_parent_symlink_swap_is_caught(self, roots, tmp_path):
        """TOCTOU 二次复检：_resolve 之后把父目录换成指向外部的 symlink。"""
        ws, ext = roots
        ctx = Ctx(str(ws), flag=True)
        target = ws / "sub" / "file.txt"
        # 用 recheck_write 直接模拟：resolved 仍在工作区内，但父目录已被换链
        (ws / "sub").mkdir()
        (ws / "sub").rmdir()
        (ws / "sub").symlink_to(ext, target_is_directory=True)
        err = recheck_write(ctx, target, op="write")
        assert err is not None
        assert "TOCTOU" in err or "越出可写根" in err


# ================================================== 2 配置健壮性
class TestConfigRobustness:
    @pytest.mark.parametrize("bad", ["true", "false", 1, 0, [], {}])
    def test_malformed_flag_fails_closed(self, roots, bad):
        """拼错成字符串/数字 → 按 fail-closed 启用，绝不静默放行。"""
        ws, ext = roots
        ctx = Ctx(str(ws), flag=bad)
        enabled, note = boundary_enabled(ctx)
        assert enabled is True
        assert "fail-closed" in note
        d = decide_write(ctx, str(ext / "x.txt"))
        assert d.allowed is False and d.enforced is True

    def test_missing_flag_means_default_off(self, roots):
        ws, _ = roots
        ctx = Ctx(str(ws), flag=None)
        enabled, note = boundary_enabled(ctx)
        assert enabled is False and note == ""

    def test_schema_rejects_non_bool(self):
        errors, _ = validate_security_config(
            Cfg(**{FLAG: "true"}))
        assert any("类型错误" in e and FLAG in e for e in errors)

    def test_schema_warns_when_enabled(self):
        errors, warnings = validate_security_config(Cfg(**{FLAG: True}))
        assert errors == []
        assert any("行为变更" in w and "仅读" in w for w in warnings)

    def test_schema_default_is_not_a_downgrade(self):
        errors, warnings = validate_security_config(Cfg())
        assert not any(FLAG in e for e in errors)
        assert not any("安全降级" in w and FLAG in w for w in warnings)

    def test_defaults_contains_flag_false(self):
        from tuan_cli.config.defaults import DEFAULT_CONFIG
        assert DEFAULT_CONFIG["permissions"][
            "blockWritesOutsideWorkingDirectories"] is False

    def test_harden_probe_uses_same_fail_closed_logic(self):
        from tuan_cli.cli.cmd_harden import _CfgProbe
        assert boundary_enabled(_CfgProbe(True))[0] is True
        assert boundary_enabled(_CfgProbe(False))[0] is False
        assert boundary_enabled(_CfgProbe("typo"))[0] is True


# ================================================== 3 W3 真事务
class TestEditFilesTransaction:
    def test_dangerous_third_item_leaves_zero_files_changed(self, tmp_path):
        """实测旧行为：f0/f1 已变 BBB 却返回「未写入任何文件」。"""
        ws = tmp_path / "ws"
        ws.mkdir()
        for i in range(3):
            (ws / f"f{i}.txt").write_text("AAA", encoding="utf-8")
        ctx = Ctx(str(ws))
        items = [{"path": f"f{i}.txt", "old_string": "AAA",
                  "new_string": "BBB" if i < 2 else "rm -rf /"}
                 for i in range(3)]
        out = FS.edit_files(ctx, items)
        assert "事务校验未全部通过" in out
        assert "包含危险内容" in out
        contents = [(f.name, f.read_text(encoding="utf-8"))
                    for f in sorted(ws.glob("f*.txt"))]
        assert contents == [("f0.txt", "AAA"), ("f1.txt", "AAA"),
                            ("f2.txt", "AAA")], contents

    def test_all_clean_items_commit(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        for i in range(3):
            (ws / f"f{i}.txt").write_text("AAA", encoding="utf-8")
        ctx = Ctx(str(ws))
        items = [{"path": f"f{i}.txt", "old_string": "AAA",
                  "new_string": "BBB"} for i in range(3)]
        out = FS.edit_files(ctx, items)
        assert "事务成功" in out
        assert all((ws / f"f{i}.txt").read_text(encoding="utf-8") == "BBB"
                   for i in range(3))

    def test_mid_transaction_write_boundary_change_refuses_all(self, tmp_path):
        """阶段 1 之后、写入之前父目录被换链 → 整体拒绝且零落盘。"""
        ws, ext = tmp_path / "ws", tmp_path / "ext"
        ws.mkdir(); ext.mkdir()
        (ws / "sub").mkdir()
        (ws / "sub" / "a.txt").write_text("AAA", encoding="utf-8")
        (ws / "sub" / "b.txt").write_text("AAA", encoding="utf-8")
        ctx = Ctx(str(ws), flag=True)
        items = [{"path": "sub/a.txt", "old_string": "AAA", "new_string": "BBB"},
                 {"path": "sub/b.txt", "old_string": "AAA", "new_string": "BBB"}]
        # 让复检在阶段 1 之后发生：直接 patch recheck_write，
        # 第一次（阶段 1 经 _resolve_write）放行，全体写入前复检时拒绝。
        calls = {"n": 0}
        real_check = FS.recheck_write

        def _flaky(ctx_, p, *, op="write"):
            calls["n"] += 1
            if calls["n"] >= 3:  # 阶段 2 前的全体复检
                return "[已拒绝] 模拟 symlink 替换"
            return real_check(ctx_, p, op=op)

        with patch.object(FS, "recheck_write", _flaky):
            out = FS.edit_files(ctx, items)
        assert "写入前复检失败" in out
        assert "未写入任何文件" in out
        assert (ws / "sub" / "a.txt").read_text(encoding="utf-8") == "AAA"

    def test_stage2_has_no_rejection_branch(self):
        """源码级：阶段 2 循环里不再有 `return` 拒绝分支。"""
        import inspect
        src = inspect.getsource(FS.edit_files)
        i = src.index("阶段 2")
        tail = src[i:]
        assert "事务已整体拒绝" not in tail
        assert "return (f\"[已拒绝]" not in tail


# ================================================== 4 不该修的判定
class TestNotChangedOnPurpose:
    def test_read_paths_unaffected(self, roots):
        ws, ext = roots
        ctx = Ctx(str(ws), flag=True)
        _grant(ctx, ext)
        assert "old" in FS.read_file(ctx, str(ext / "existing.txt"))
        assert "existing.txt" in FS.list_dir(ctx, str(ext))

    def test_diff_preview_is_read_only_and_unaffected(self, roots):
        ws, ext = roots
        ctx = Ctx(str(ws), flag=True)
        _grant(ctx, ext)
        out = FS.diff_preview(ctx, str(ext / "existing.txt"),
                              old_string="old", new_string="new")
        assert "diff" in out.lower() or "old" in out
        assert (ext / "existing.txt").read_text(encoding="utf-8") == "old"

    def test_no_direct_resolve_left_in_write_ops(self):
        """源码级单一出口：六个写函数体内不再直接调 ``_resolve(ctx, ...``。

        ``move_file`` 的**源**仍走 `_resolve`（读裁决），所以只检查目标部分。
        """
        import inspect
        for name in ("write_file", "edit_file", "delete_file",
                     "delete_dir", "edit_files"):
            src = inspect.getsource(getattr(FS, name))
            assert "p = _resolve(ctx, path)" not in src, name
        mv = inspect.getsource(FS.move_file)
        assert "d, err = _resolve_write(ctx, dst" in mv
        assert "s = _resolve(ctx, src)" in mv  # 源是读，保持

    def test_artifact_and_worktree_write_inside_workspace_fixed_paths(self):
        """如实边界：这两个模块不走 _resolve，但写的是 workspace/.tuan/...
        内部固定路径，不是用户提供的任意路径。用源码扫描锁住结论。"""
        root = Path(FS.__file__).resolve().parent.parent
        art = (root / "tools/artifact_tool.py").read_text(encoding="utf-8")
        wt = (root / "core/worktree_layer.py").read_text(encoding="utf-8")
        assert 'workspace / ".tuan" / "artifacts"' in art
        assert 'self.workspace / ".tuan" / "worktrees"' in wt

    def test_system_critical_dirs_still_refused_for_add_dir(self, tmp_path):
        ws = tmp_path / "ws"; ws.mkdir()
        ctx = Ctx(str(ws), flag=True)
        out = FS.authorize_extra_dir(ctx, "/etc", writable=True)
        assert "拒绝授权系统关键目录" in out
        assert writable_roots(ctx) == []

    def test_agent_has_no_self_grant_tool(self):
        """Agent 不能自助授权可写根：工具表里没有 add_dir。"""
        names = [t for t in dir(FS) if t.startswith("authorize")]
        assert names == ["authorize_extra_dir"]
        import inspect
        assert "writable" in inspect.signature(FS.authorize_extra_dir).parameters


# ================================================== 5 矩阵自洽
class TestMatrixHonesty:
    def test_counts_unchanged(self):
        from tuan_cli.parity_claude import matrix, evidence
        assert matrix.validate() == []
        assert evidence.verify_evidence() == []
        s = matrix.summary()
        # 纯深度修复：工具层能力补齐但命令层未覆盖、默认仍 off，
        # 所以状态仍是 partial —— 不把修好的侧门包装成进度。
        assert s["by_status"] == {
            "ahead": 10, "aligned": 46, "partial": 9,
            "gap": 26, "not_applicable": 8}
        assert s["gaps"] == 26
        assert s["fully_superior"] is False
        assert s["b_waves_done"] == ["B1"]
        assert s["superiority_criteria"]["external_adaptive_red_team"] is False

    def test_catalog_note_no_longer_claims_missing_tool_layer(self):
        from pathlib import Path
        src = Path("tuan_cli/parity_claude/catalog.py").read_text(
            encoding="utf-8")
        i = src.index('M("block_writes_outside_wd"')
        window = src[i:i + 1400]
        assert "工具层硬约束待补" not in window
        assert "core/write_boundary.py" in window
        assert "仍为 partial" in window
