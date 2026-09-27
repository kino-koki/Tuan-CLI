"""测试 compact 后存活契约 (P0, 对标 Claude Code 压缩后从磁盘重注入)。

验证:
- 压缩后重建的 system prompt 仍包含 SOUL 身份 / 项目指令 / MEMORY.md;
- build_survival_report 输出包含各状态检查项;
- MemoryNotesStore / 项目指令在重建入口被正确注入。
"""
from pathlib import Path

from qingxiaotuan.core import prompts
from qingxiaotuan.memory.memory_notes import MemoryNotesStore
from qingxiaotuan.runtime.session.compact_survival import (
    build_survival_report,
    check_survival_items,
)


class TestRebuildAfterCompact:
    def test_rebuilt_prompt_contains_soul_identity(self, tmp_path, qxt_home):
        """压缩后从磁盘重建的稳定段必须含 SOUL 身份。"""
        stable = prompts.build_system_prompt_stable(qxt_home, str(tmp_path))
        assert "青小团" in stable
        # 新协议要点也应在 (回退文案含思考预算/错误处理)
        assert "思考预算" in stable
        assert "错误处理" in stable

    def test_rebuilt_prompt_contains_project_instructions(self, tmp_path, qxt_home):
        ws = tmp_path / "repo"
        ws.mkdir()
        (ws / "QXT.md").write_text("本项目测试用 pytest, 提交前跑全量。", encoding="utf-8")
        dynamic = prompts.build_system_prompt_dynamic(qxt_home, str(ws))
        assert "本项目测试用 pytest" in dynamic

    def test_rebuilt_prompt_contains_memory_notes(self, tmp_path, qxt_home):
        ws = tmp_path / "repo2"
        ws.mkdir()
        MemoryNotesStore(home=qxt_home, workspace=str(ws)).append("用户纠正: 命名用 snake_case")
        dynamic = prompts.build_system_prompt_dynamic(qxt_home, str(ws))
        assert "用户纠正: 命名用 snake_case" in dynamic


class TestSurvivalReport:
    def test_report_contains_all_state_items(self, tmp_path, qxt_home):
        ws = tmp_path / "reportproj"; ws.mkdir()
        report = build_survival_report(qxt_home, str(ws))
        for keyword in ("SOUL", "项目指令", "MEMORY.md", "Git", "技能",
                        "TodoWrite", "Goal", "输出风格"):
            assert keyword in report, f"报告缺少状态项: {keyword}"

    def test_report_lists_nine_items(self, tmp_path, qxt_home):
        ws = tmp_path / "reportproj2"; ws.mkdir()
        items = check_survival_items(qxt_home, str(ws))
        names = [it.name for it in items]
        assert len(items) == 9
        assert "SOUL 身份" in names
        assert "MEMORY.md 记忆笔记" in names
        assert "TodoWrite 任务清单" in names
        assert "Goal 目标进度" in names

    def test_report_marks_available_services(self, tmp_path, qxt_home):
        """传入 mock memory_store / skill_manager 时对应项标记 ok。"""
        ws = tmp_path / "reportproj3"; ws.mkdir()

        class _Store:
            def search(self, *a, **k):
                return []

        class _Skills:
            pass

        items = {it.name: it for it in check_survival_items(
            qxt_home, str(ws), config=object(), memory_store=_Store(), skill_manager=_Skills())}
        assert items["FTS5 长期记忆"].ok is True
        assert items["技能注册表"].ok is True
        assert items["输出风格 / 语言"].ok is True

    def test_verify_cli_entry_exists(self):
        """`qxt compact --verify` 子命令已注册 (parser 可解析)。"""
        from qingxiaotuan.cli.parser import build_parser
        parser = build_parser()
        args = parser.parse_args(["compact", "--verify"])
        assert getattr(args, "verify") is True
        assert getattr(args, "func") == "cmd_compact"
