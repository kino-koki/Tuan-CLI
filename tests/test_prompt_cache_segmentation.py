"""测试 system prompt 稳定前缀 / 动态后缀显式分段 (P0, 对标 Claude Code prompt cache 分段)。

验证:
- stable 段在 git 状态/记忆变化时逐字节一致 (可安全做 prompt cache);
- dynamic 段在 git 状态变化时确实变化 (不应跨轮缓存);
- build_system_prompt 兼容入口 == stable + dynamic 拼接;
- system_prompt_stable_hash / system_prompt_dynamic_hash 正确性。
"""
from pathlib import Path

from qingxiaotuan.core import prompts


class TestStablePrefix:
    def test_stable_byte_identical_across_git_change(self, monkeypatch, tmp_path, qxt_home):
        """git 上下文被 monkeypatch 成不同值时, stable 段必须逐字节不变。"""
        s1 = prompts.build_system_prompt_stable(qxt_home, str(tmp_path))
        monkeypatch.setattr(prompts, "_get_git_context", lambda ws: "Branch=FEATURE_X DirtyFiles=99")
        s2 = prompts.build_system_prompt_stable(qxt_home, str(tmp_path))
        assert s1 == s2, "stable 段不应随 git 状态变化"

    def test_stable_byte_identical_across_memory_change(self, tmp_path, qxt_home):
        """stable 段不接收 memory_store, 记忆变化不影响它。"""
        s1 = prompts.build_system_prompt_stable(qxt_home, str(tmp_path))
        # 不构造任何 memory_store —— stable 签名本就不含它, 两次调用结果一致
        s2 = prompts.build_system_prompt_stable(qxt_home, str(tmp_path))
        assert s1 == s2

    def test_stable_contains_identity_and_rules(self, tmp_path, qxt_home):
        """稳定段应含身份/行为准则/各规范段。"""
        s = prompts.build_system_prompt_stable(qxt_home, str(tmp_path))
        assert "准则" in s
        assert "安全提醒" in s
        assert "技能使用" in s
        # 缺失 SOUL.md 时用回退文案
        assert "青小团" in s

    def test_stable_mentions_memory_note_tool(self, tmp_path, qxt_home):
        """稳定段应指示 Agent 用 memory_note_append 写笔记。"""
        s = prompts.build_system_prompt_stable(qxt_home, str(tmp_path))
        assert "memory_note_append" in s
        assert "MEMORY.md" in s


class TestDynamicSuffix:
    def test_dynamic_changes_with_git(self, monkeypatch, tmp_path, qxt_home):
        """git 上下文变化时, dynamic 段必须变化 (不缓存)。"""
        monkeypatch.setattr(prompts, "_get_git_context", lambda ws: "Branch=main DirtyFiles=0")
        d1 = prompts.build_system_prompt_dynamic(qxt_home, str(tmp_path))
        monkeypatch.setattr(prompts, "_get_git_context", lambda ws: "Branch=dev DirtyFiles=5")
        d2 = prompts.build_system_prompt_dynamic(qxt_home, str(tmp_path))
        assert d1 != d2, "dynamic 段应随 git 状态变化"
        assert "Branch=dev" in d2

    def test_dynamic_contains_env_and_git(self, monkeypatch, tmp_path, qxt_home):
        monkeypatch.setattr(prompts, "_get_git_context", lambda ws: "Branch=main")
        d = prompts.build_system_prompt_dynamic(qxt_home, str(tmp_path))
        assert "环境:" in d
        assert "Git:" in d

    def test_dynamic_injects_memory_notes(self, tmp_path, qxt_home):
        """dynamic 段应注入 MEMORY.md 笔记内容。"""
        ws = tmp_path / "proj"
        ws.mkdir()
        from qingxiaotuan.memory.memory_notes import MemoryNotesStore
        store = MemoryNotesStore(home=qxt_home, workspace=str(ws))
        store.append("用户偏好: 测试一律用 pytest")
        d = prompts.build_system_prompt_dynamic(qxt_home, str(ws))
        assert "用户偏好: 测试一律用 pytest" in d

    def test_dynamic_notes_disabled(self, tmp_path, qxt_home):
        ws = tmp_path / "proj2"
        ws.mkdir()
        from qingxiaotuan.memory.memory_notes import MemoryNotesStore
        MemoryNotesStore(home=qxt_home, workspace=str(ws)).append("不应被注入的笔记")
        d = prompts.build_system_prompt_dynamic(qxt_home, str(ws), memory_notes_enabled=False)
        assert "不应被注入的笔记" not in d


class TestCompatibilityEntry:
    def test_build_system_prompt_equals_stable_plus_dynamic(self, tmp_path, qxt_home):
        """兼容入口返回 stable + '\n\n' + dynamic 拼接。"""
        full = prompts.build_system_prompt(qxt_home, str(tmp_path))
        stable = prompts.build_system_prompt_stable(qxt_home, str(tmp_path))
        dynamic = prompts.build_system_prompt_dynamic(qxt_home, str(tmp_path))
        assert full == stable + "\n\n" + dynamic

    def test_cache_flag_changes_nothing_observable(self, tmp_path, qxt_home):
        """cache_stable_prefix 开关不改变拼接结果 (仅边界声明)。"""
        a = prompts.build_system_prompt(qxt_home, str(tmp_path), cache_stable_prefix=True)
        b = prompts.build_system_prompt(qxt_home, str(tmp_path), cache_stable_prefix=False)
        assert a == b


class TestHashes:
    def test_stable_hash_deterministic(self):
        assert prompts.system_prompt_stable_hash("same") == prompts.system_prompt_stable_hash("same")

    def test_dynamic_hash_deterministic(self):
        assert prompts.system_prompt_dynamic_hash("same") == prompts.system_prompt_dynamic_hash("same")

    def test_stable_and_dynamic_hashes_distinct(self):
        """同输入下 stable 与 dynamic 哈希必须可区分 (边界前缀不同)。"""
        assert prompts.system_prompt_stable_hash("x") != prompts.system_prompt_dynamic_hash("x")

    def test_hash_changes_with_content(self):
        assert prompts.system_prompt_stable_hash("a") != prompts.system_prompt_stable_hash("b")
