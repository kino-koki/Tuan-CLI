"""测试文件型记忆笔记 MEMORY.md (P0, 对标 Claude Code projects/<slug>/memory/MEMORY.md)。

验证:
- 创建/读取/追加;
- 200 行超限检测;
- 原子写入 (不残留临时文件, 中断不损坏);
- project_slug 生成 (不同目录不同 slug);
- memory_note_append 工具调用追加笔记。
"""
from pathlib import Path

from qingxiaotuan.memory.memory_notes import (
    DEFAULT_MAX_LINES,
    MemoryNotesStore,
    project_slug,
)


class TestSlug:
    def test_slug_stable_for_same_path(self, tmp_path):
        ws = tmp_path / "proj"
        ws.mkdir()
        assert project_slug(str(ws)) == project_slug(str(ws))

    def test_slug_differs_for_different_dirs(self, tmp_path):
        a = tmp_path / "a"; a.mkdir()
        b = tmp_path / "b"; b.mkdir()
        assert project_slug(str(a)) != project_slug(str(b))

    def test_slug_is_short_hash(self, tmp_path):
        s = project_slug(str(tmp_path))
        assert len(s) == 8


class TestReadWrite:
    def test_empty_read_returns_empty(self, tmp_path, qxt_home):
        store = MemoryNotesStore(home=qxt_home, workspace=str(tmp_path))
        assert store.read() == ""
        assert store.line_count() == 0

    def test_write_then_read(self, tmp_path, qxt_home):
        store = MemoryNotesStore(home=qxt_home, workspace=str(tmp_path))
        store.write("# 笔记\n第一行\n")
        assert "第一行" in store.read()

    def test_append_adds_line(self, tmp_path, qxt_home):
        store = MemoryNotesStore(home=qxt_home, workspace=str(tmp_path))
        store.append("第一条偏好")
        store.append("第二条偏好")
        assert store.line_count() == 2
        assert "第一条偏好" in store.read()
        assert "第二条偏好" in store.read()

    def test_append_does_not_glue_lines(self, tmp_path, qxt_home):
        """追加时自动补换行, 不把新笔记粘在上一行尾巴上。"""
        store = MemoryNotesStore(home=qxt_home, workspace=str(tmp_path))
        store.write("只有一行没有换行结尾")
        store.append("新的一行")
        lines = store.lines()
        assert lines[-1] == "新的一行"
        assert lines[0] == "只有一行没有换行结尾"

    def test_search_keyword(self, tmp_path, qxt_home):
        store = MemoryNotesStore(home=qxt_home, workspace=str(tmp_path))
        store.append("用户偏好用 pytest")
        store.append("项目用 ruff 格式化")
        hits = store.search("pytest")
        assert len(hits) == 1
        assert "pytest" in hits[0]


class TestOverflow:
    def test_is_full_at_limit(self, tmp_path, qxt_home):
        store = MemoryNotesStore(home=qxt_home, workspace=str(tmp_path), max_lines=5)
        for i in range(5):
            store.append(f"line {i}")
        assert store.is_full() is True

    def test_not_full_below_limit(self, tmp_path, qxt_home):
        store = MemoryNotesStore(home=qxt_home, workspace=str(tmp_path), max_lines=5)
        store.append("only one")
        assert store.is_full() is False

    def test_default_limit_is_200(self):
        assert DEFAULT_MAX_LINES == 200


class TestAtomicWrite:
    def test_no_tmp_leftover_after_write(self, tmp_path, qxt_home):
        """写入后不应在 memory 目录残留 .tmp 临时文件。"""
        store = MemoryNotesStore(home=qxt_home, workspace=str(tmp_path))
        store.append("原子写入测试")
        tmps = list(store.dir.glob("*.tmp")) + list(store.dir.glob(".*.tmp"))
        assert tmps == [], f"残留临时文件: {tmps}"

    def test_write_overwrite_preserves_valid_content(self, tmp_path, qxt_home):
        store = MemoryNotesStore(home=qxt_home, workspace=str(tmp_path))
        store.append("旧内容")
        store.write("全新内容")
        assert "旧内容" not in store.read()
        assert "全新内容" in store.read()
        assert store.path.exists()


class TestNoteAppendTool:
    def _ctx(self, home: Path, workspace: str, enabled=True, max_lines=200):
        from qingxiaotuan.tools.memory_tool import memory_note_append

        class _Cfg:
            def __init__(self):
                self.home = home
                self._d = {"memory.notes_enabled": enabled, "memory.notes_max_lines": max_lines}

            def get(self, k, d=None):
                return self._d.get(k, d)

        class _Kernel:
            def __init__(self, cfg):
                self._cfg = cfg

            def require(self, name):
                return self._cfg

        class _Ctx:
            def __init__(self):
                self.kernel = _Kernel(_Cfg())
                self.workspace = workspace

        return _Ctx(), memory_note_append

    def test_tool_appends_note(self, tmp_path, qxt_home):
        ws = tmp_path / "toolproj"; ws.mkdir()
        ctx, fn = self._ctx(qxt_home, str(ws))
        out = fn(ctx, content="用户纠正: 不要用 camelCase")
        assert "已写入" in out
        store = MemoryNotesStore(home=qxt_home, workspace=str(ws))
        assert "不要用 camelCase" in store.read()

    def test_tool_warns_when_over_limit(self, tmp_path, qxt_home):
        ws = tmp_path / "toolproj2"; ws.mkdir()
        ctx, fn = self._ctx(qxt_home, str(ws), max_lines=2)
        fn(ctx, content="line1")
        fn(ctx, content="line2")
        out = fn(ctx, content="line3 超限")
        assert "超过上限" in out or "超过" in out

    def test_tool_disabled(self, tmp_path, qxt_home):
        ws = tmp_path / "toolproj3"; ws.mkdir()
        ctx, fn = self._ctx(qxt_home, str(ws), enabled=False)
        out = fn(ctx, content="不应写入")
        assert "已关闭" in out
        store = MemoryNotesStore(home=qxt_home, workspace=str(ws))
        assert store.read() == ""
