"""测试项目指令文件大小上限 (A2 补充, 对标 Codex project_doc_max_bytes)。

验证:
- 小文件正常注入;
- 大文件截断并带提示;
- 配置可调整上限。
"""

from pathlib import Path

from qingxiaotuan.core.prompts import (
    DEFAULT_PROJECT_DOC_MAX_BYTES,
    _discover_project_instructions,
)


class TestSmallFile:
    def test_small_file_injected_fully(self, tmp_path, qxt_home):
        ws = tmp_path / "repo"
        ws.mkdir()
        (ws / ".git").mkdir()  # 自成 git 根, 隔离仓库外/内 tmp 位置差异
        (ws / "QXT.md").write_text("本项目用 pytest。", encoding="utf-8")
        out = _discover_project_instructions(str(ws), home=qxt_home)
        assert "本项目用 pytest" in out
        assert "文件过大已截断" not in out

    def test_default_limit_is_32k(self):
        assert DEFAULT_PROJECT_DOC_MAX_BYTES == 32768


class TestLargeFile:
    def _make_large(self, ws: Path, size: int) -> Path:
        (ws / ".git").mkdir()  # 自成 git 根: _project_chain 在 ws 处即止,
        # 不会沿父目录上溯到外层真实仓库的 QXT.md, 保证计数精确
        f = ws / "QXT.md"
        # 用纯 ASCII 内容保证字节数 == 字符数, 便于精确控制
        f.write_text("x" * size, encoding="utf-8")
        return f

    def test_large_file_truncated_with_hint(self, tmp_path, qxt_home):
        ws = tmp_path / "bigrepo"
        ws.mkdir()
        self._make_large(ws, 10_000)
        out = _discover_project_instructions(str(ws), home=qxt_home, max_bytes=1000)
        assert "文件过大已截断" in out
        # 截断后正文不应包含全部 10000 个字符
        assert out.count("x") < 10_000

    def test_truncated_content_under_limit(self, tmp_path, qxt_home):
        ws = tmp_path / "bigrepo2"
        ws.mkdir()
        self._make_large(ws, 50_000)
        out = _discover_project_instructions(str(ws), home=qxt_home, max_bytes=2048)
        # 正文 x 数量应 <= 2048 (外加标题/提示)
        assert out.count("x") <= 2048

    def test_configurable_limit_disables_truncation(self, tmp_path, qxt_home):
        """调大上限后, 原本会被截断的文件完整注入。"""
        ws = tmp_path / "bigrepo3"
        ws.mkdir()
        self._make_large(ws, 3000)
        out = _discover_project_instructions(str(ws), home=qxt_home, max_bytes=100_000)
        assert out.count("x") == 3000
        assert "文件过大已截断" not in out

    def test_zero_limit_means_no_cap(self, tmp_path, qxt_home):
        """max_bytes <= 0 表示不限制。"""
        ws = tmp_path / "bigrepo4"
        ws.mkdir()
        self._make_large(ws, 3000)
        out = _discover_project_instructions(str(ws), home=qxt_home, max_bytes=0)
        assert out.count("x") == 3000
