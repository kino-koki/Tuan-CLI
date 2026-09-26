"""/init 项目引导测试 —— 对标 Claude Code 的 /init。

验证:
- 空项目中自动生成 QXT.md;
- Python 项目 (pyproject.toml + tests/) 被正确识别, 内容含 pytest;
- QXT.md 已存在时默认不覆盖 (返回"未覆盖"提示, 原文不变)。
"""

from qingxiaotuan.cli.cmd_slash_init import (
    detect_project,
    render_qxt_md,
    write_qxt_md,
)


def test_init_generates_qxt_md(tmp_path):
    msg = write_qxt_md(tmp_path)
    assert (tmp_path / "QXT.md").exists()
    assert "QXT.md" in msg


def test_init_detects_python(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname = 'demo'\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    info = detect_project(tmp_path)
    assert "python" in info["languages"]
    md = render_qxt_md(info)
    assert "pytest" in md


def test_init_prompts_on_existing(tmp_path):
    (tmp_path / "QXT.md").write_text("KEEP-ME-ORIGINAL", encoding="utf-8")
    msg = write_qxt_md(tmp_path, force=False)
    assert "未覆盖" in msg
    assert (tmp_path / "QXT.md").read_text(encoding="utf-8") == "KEEP-ME-ORIGINAL"
