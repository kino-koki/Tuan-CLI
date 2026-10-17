"""记忆系统缺口补齐回归 (round3/group_memory)。

本文件专门守护「审计#4 记忆内容安全: 敏感信息落盘前脱敏」这一真实缺口:
记忆是跨会话、最易被复制/同步的持久产物, 此前 store / memory_notes 的所有写入口
都把原始文本(含可能的 API Key / Token / 密码 / Bearer / sk-* / JWT)直接落盘,
而项目内 security_auditor / security_bus / mcp 审计链路早已统一走
core.security_utils.redact_sensitive。本文件证明: 记忆落盘前已接入同一脱敏原语。
"""
from __future__ import annotations

from pathlib import Path

from tuan_cli.memory.memory_notes import MemoryNotesStore
from tuan_cli.memory.store import MemoryStore

# 各类敏感样例 (覆盖 redact_sensitive 的主要正则分支)
SK_KEY = "sk-abcdef1234567890xyz"
BEARER = "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.payload.sig"
JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozj3JK-Yxyz"
ENV_LINE = "DEEPSEEK_API_KEY=sk-0987654321abcdef"
KV_SECRET = "password=Hunter2_secret_value"


# ------------------------------------------------------------------ append_memory

def test_append_memory_redacts_sk_key(tmp_path: Path) -> None:
    """append_memory 把 sk-* 密钥抹成 [REDACTED] 再写 MEMORY.md 与 FTS。"""
    store = MemoryStore(tmp_path, fts_enabled=True)
    store.append_memory(f"本项目部署密钥是 {SK_KEY}", section="参考")
    disk = store.read_memory()
    assert SK_KEY not in disk, "原始 sk- 密钥绝不能落盘"
    assert "[REDACTED]" in disk
    # FTS 索引里也不应残留原始密钥
    hits = store.search("部署密钥")
    assert all(SK_KEY not in h["content"] for h in hits)


def test_append_memory_redacts_bearer_and_env(tmp_path: Path) -> None:
    """Bearer token 与 KEY=value 环境变量赋值同样脱敏。"""
    store = MemoryStore(tmp_path, fts_enabled=False)
    store.append_memory(f"调用样例 Authorization: {BEARER}; {ENV_LINE}")
    disk = store.read_memory()
    assert "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" not in disk
    assert "sk-0987654321abcdef" not in disk
    assert "[REDACTED]" in disk


def test_append_memory_keeps_normal_fact(tmp_path: Path) -> None:
    """非敏感记忆内容必须原样保留, 不能被脱敏误伤。"""
    store = MemoryStore(tmp_path, fts_enabled=False)
    store.append_memory("用户偏好用 pytest 做单测", section="偏好")
    disk = store.read_memory()
    assert "用户偏好用 pytest 做单测" in disk
    assert "[REDACTED]" not in disk


# ------------------------------------------------------------------ add_auto_memory

def test_add_auto_memory_redacts_secret(tmp_path: Path) -> None:
    """自动记忆写入前脱敏: 含密钥的参考事实不能原样进 FTS/标签库。"""
    store = MemoryStore(tmp_path, fts_enabled=True)
    new_id = store.add_auto_memory(
        f"生产库连接串 password=Hunter2_secret_value 见备注", kind="reference"
    )
    assert new_id is not None
    hits = store.search_by_kind("reference")
    assert hits, "应写入一条脱敏后的 reference 记忆"
    stored = hits[0]["content"]
    assert "Hunter2_secret_value" not in stored, "密码取值不能落进记忆库"
    assert "[REDACTED]" in stored


# ------------------------------------------------------------------ update_user

def test_update_user_redacts_value(tmp_path: Path) -> None:
    """用户画像字段值脱敏: value 里的密钥不写进 USER.md。"""
    store = MemoryStore(tmp_path, fts_enabled=False)
    store.update_user("deploy_token", SK_KEY)
    disk = store.read_user()
    assert SK_KEY not in disk
    assert "[REDACTED]" in disk


# ------------------------------------------------------------------ MemoryNotesStore

def test_memory_notes_write_redacts(tmp_path: Path, tuan_home: Path) -> None:
    """项目记忆笔记 write() 整体覆盖时脱敏。"""
    notes = MemoryNotesStore(home=tuan_home, workspace=str(tmp_path))
    notes.write(f"# 笔记\n数据库密码 {KV_SECRET}\n")
    assert "Hunter2_secret_value" not in notes.read()
    assert "[REDACTED]" in notes.read()


def test_memory_notes_append_redacts(tmp_path: Path, tuan_home: Path) -> None:
    """项目记忆笔记 append() 追加时脱敏, 且不影响已有正常内容。"""
    notes = MemoryNotesStore(home=tuan_home, workspace=str(tmp_path))
    notes.append("用户偏好用 tabs")
    notes.append(f"密钥记录 {JWT}")
    text = notes.read()
    assert "用户偏好用 tabs" in text
    # JWT 三段都不应落盘
    assert "eyJzdWIiOiIxMjM0NTY3ODkw" not in text


def test_memory_notes_append_keeps_normal_text(tmp_path: Path, tuan_home: Path) -> None:
    """普通笔记不被脱敏误伤。"""
    notes = MemoryNotesStore(home=tuan_home, workspace=str(tmp_path))
    notes.append("项目约定: 提交前跑 ruff")
    assert "项目约定: 提交前跑 ruff" in notes.read()
    assert "[REDACTED]" not in notes.read()
