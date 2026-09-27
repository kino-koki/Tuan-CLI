"""记忆与人格桥接层 —— 与 Hermes Agent 的 MEMORY.md / USER.md / SOUL.md 互通。

Hermes 的记忆是两只有上限的纯文本文件, 条目以 ``§`` 分隔:
- ``MEMORY.md`` (上限 2200 字符): Agent 的环境事实 / 约定 / 经验;
- ``USER.md``   (上限 1375 字符): 用户画像 (偏好 / 沟通风格 / 期望);
- ``SOUL.md``   : 实例级人格 (身份 / 语气 / 铁律), 位于 ``~/.hermes/SOUL.md``。

qxt 的记忆文件同样位于 ``<home>/memories/MEMORY.md`` 与 ``USER.md`` (Hermes 风格
布局), 且 qxt 运行期已把 SOUL.md 作为系统提示的首段。本模块负责:

- **导入**: 把 Hermes 的 MEMORY.md / USER.md 条目并入 qxt 记忆 (去重后追加),
  SOUL.md 复制为 qxt 的 SOUL.md (存在时不覆盖, 除非 force)。
- **导出**: 把 qxt 记忆写成 Hermes 可读的 ``§`` 分隔文件 (带字符预算警告),
  把 qxt 身份/人格导出为 SOUL.md。

纯函数 + 显式路径注入, 可测。
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from ..core import atomicio

# Hermes 记忆字符预算 (官方文档值)
HERMES_MEMORY_LIMIT = 2200
HERMES_USER_LIMIT = 1375
_SECTION_SEP = "\n§\n"


@dataclass
class MemoryImportResult:
    memory_added: List[str] = field(default_factory=list)
    user_added: List[str] = field(default_factory=list)
    memory_skipped: List[str] = field(default_factory=list)
    soul_copied: bool = False
    soul_error: str = ""
    errors: List[str] = field(default_factory=list)


def parse_hermes_entries(text: str) -> List[str]:
    """把 Hermes 记忆文件拆成条目列表 (按 ``§`` 分隔, 去空)。

    条目可能是多行的; 每条独立成句, 结尾无分隔符。
    """
    if not text:
        return []
    out = []
    for chunk in text.split(_SECTION_SEP):
        chunk = chunk.strip()
        # 去掉 Hermes 的头部说明行 (header: "MEMORY (your personal notes) [...]")
        lines = [ln for ln in chunk.splitlines() if ln.strip() and not ln.startswith("MEMORY") and not ln.startswith("USER")]
        if lines:
            out.append("\n".join(lines))
    return out


def import_hermes_memory(
    memory_store: object,
    hermes_memories_dirs: List[Path],
    *,
    force_soul: bool = False,
    hermes_home: Optional[Path] = None,
    qxt_home: Optional[Path] = None,
) -> MemoryImportResult:
    """把 Hermes 记忆并入 qxt (去重: 已在 qxt 的条目跳过)。

    memory_store: 带 ``read_memory/read_user/append_memory`` 的 MemoryStore 实例。
    hermes_home/qxt_home 用于 SOUL.md 搬运 (可省略)。
    """
    result = MemoryImportResult()
    if not hermes_memories_dirs:
        return result

    existing_m = (memory_store.read_memory() or "") if hasattr(memory_store, "read_memory") else ""
    existing_u = (memory_store.read_user() or "") if hasattr(memory_store, "read_user") else ""

    def _not_exists(existing: str, entry: str) -> bool:
        head = entry.splitlines()[0][:40] if entry.splitlines() else entry[:40]
        return head not in existing

    for d in hermes_memories_dirs:
        mem_file = d / "MEMORY.md"
        if mem_file.exists():
            try:
                for entry in parse_hermes_entries(mem_file.read_text(encoding="utf-8")):
                    if _not_exists(existing_m, entry):
                        try:
                            line = memory_store.append_memory(entry, section="事实")  # type: ignore[attr-defined]
                            result.memory_added.append(entry.splitlines()[0][:60])
                            existing_m += line
                        except Exception as exc:  # noqa: BLE001
                            result.errors.append(f"追加记忆失败: {exc}")
                    else:
                        result.memory_skipped.append(entry.splitlines()[0][:40])
            except Exception as exc:  # noqa: BLE001
                result.errors.append(f"读取 {mem_file}: {exc}")

        user_file = d / "USER.md"
        if user_file.exists():
            try:
                for entry in parse_hermes_entries(user_file.read_text(encoding="utf-8")):
                    if _not_exists(existing_u, entry):
                        try:
                            line = memory_store.update_user(  # type: ignore[attr-defined]
                                "hermes", entry
                            )
                            result.user_added.append(entry.splitlines()[0][:60])
                            existing_u += line
                        except Exception as exc:  # noqa: BLE001
                            result.errors.append(f"更新用户画像失败: {exc}")
            except Exception as exc:  # noqa: BLE001
                result.errors.append(f"读取 {user_file}: {exc}")

    # ---- SOUL.md 搬运 (Hermes → qxt) ----
    if hermes_home is not None and qxt_home is not None:
        src_soul = hermes_home / "SOUL.md"
        dst_soul = Path(qxt_home) / "SOUL.md"
        if src_soul.exists():
            if dst_soul.exists() and not force_soul:
                result.soul_error = "qxt SOUL.md 已存在 (用 --force 覆盖)"
            else:
                try:
                    shutil.copyfile(src_soul, dst_soul)
                    result.soul_copied = True
                except OSError as exc:
                    result.soul_error = str(exc)
    return result


@dataclass
class MemoryExportResult:
    memory_chars: int = 0
    user_chars: int = 0
    memory_over: bool = False
    user_over: bool = False
    target: str = ""
    errors: List[str] = field(default_factory=list)


def export_to_hermes(
    memory_store: object,
    hermes_home: Path,
    *,
    profile: Optional[str] = None,
) -> MemoryExportResult:
    """把 qxt 记忆导出为 Hermes 可读文件 (``§`` 分隔)。

    目标: ``<hermes_home>/memories/MEMORY.md`` 与 ``USER.md``
    (或 ``profiles/<profile>/memories/``)。超预算时仍写入但标注 over 供警告。
    """
    result = MemoryExportResult()
    target = Path(hermes_home)
    if profile:
        target = target / "profiles" / profile
    mem_dir = target / "memories"
    try:
        mem_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        result.errors.append(f"创建 {mem_dir}: {exc}")
        return result

    mem_text = (memory_store.read_memory() or "").strip() if hasattr(memory_store, "read_memory") else ""
    user_text = (memory_store.read_user() or "").strip() if hasattr(memory_store, "read_user") else ""

    # qxt 的记忆文件是 "- [date] (section) fact" 行式, Hermes 用 § 分隔条目:
    # 直接复用原文本 (Hermes 能读任意 markdown), 并把空行分隔归一为 §。
    normalized_m = _normalize_sections(mem_text)
    normalized_u = _normalize_sections(user_text)
    result.memory_chars = len(normalized_m)
    result.user_chars = len(normalized_u)
    result.memory_over = result.memory_chars > HERMES_MEMORY_LIMIT
    result.user_over = result.user_chars > HERMES_USER_LIMIT
    try:
        atomicio.atomic_write_text(mem_dir / "MEMORY.md", normalized_m)
        atomicio.atomic_write_text(mem_dir / "USER.md", normalized_u)
        result.target = str(mem_dir)
    except OSError as exc:
        result.errors.append(str(exc))
    return result


def _normalize_sections(text: str) -> str:
    """把条目之间的空行归一为 Hermes 的 § 分隔。"""
    if not text.strip():
        return ""
    lines = [ln for ln in text.splitlines()]
    out: List[str] = []
    blank_run = 0
    for ln in lines:
        if ln.strip() == "":
            blank_run += 1
            if blank_run == 1 and out:
                out.append("")
        else:
            blank_run = 0
            out.append(ln.strip())
    # 连续空行压缩为单个 §
    body = "\n".join(out)
    while "\n\n\n" in body:
        body = body.replace("\n\n\n", "\n\n")
    return body.strip()


__all__ = [
    "MemoryImportResult", "MemoryExportResult",
    "parse_hermes_entries", "import_hermes_memory", "export_to_hermes",
    "HERMES_MEMORY_LIMIT", "HERMES_USER_LIMIT",
]
