"""会话导出 zip —— 对标 Kimi Code 的 `kimi export`。

把单个会话 (jsonl 事件流) 打包成一个自包含 zip:
- ``session.jsonl``        原始事件流 (可回放/审计)
- ``manifest.json``         会话元信息 (id/标题/消息数/导出时间/文件清单)
- ``config_snapshot.json``  模型配置快照 (只含 provider/model/base_url, 不含密钥)
- ``files_manifest.json``   会话过程中产生/修改的文件清单 (write_file/edit_file/delete_file)
- ``summary.md``            人读摘要

CLI 用法: ``qxt session export <会话id|编号|latest> -o <output.zip>``。
"""

from __future__ import annotations

import datetime
import json
import zipfile
from pathlib import Path
from typing import Any, Dict, List


def _read_records(src: Path) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    try:
        for line in Path(src).read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except Exception:  # noqa: BLE001 - 损坏行跳过
                continue
    except OSError:
        pass
    return records


def export_session_zip(src: Path, dest: Path) -> Path:
    """把会话 ``src`` (.jsonl) 打包到 ``dest`` (.zip)。返回 zip 路径。"""
    src = Path(src)
    dest = Path(dest).expanduser()
    if dest.is_dir():
        dest = dest / (src.stem + ".zip")

    records = _read_records(src)

    msg_count = sum(
        1 for r in records
        if r.get("type") in ("user", "assistant") and "message" in r
    )

    title = ""
    files_written: List[str] = []
    for r in records:
        if not title and r.get("type") == "session.meta":
            title = str(r.get("task") or "")
        tool_name = r.get("name") or ""
        if tool_name in ("write_file", "edit_file", "delete_file"):
            args = r.get("arguments")
            p = args.get("path") if isinstance(args, dict) else None
            if p and p not in files_written:
                files_written.append(str(p))

    exported_at = datetime.datetime.now().isoformat(timespec="seconds")
    manifest = {
        "session_id": src.stem,
        "title": title,
        "message_count": msg_count,
        "event_count": len(records),
        "exported_at": exported_at,
        "source_file": src.name,
        "artifacts": [
            "session.jsonl", "manifest.json", "config_snapshot.json",
            "files_manifest.json", "summary.md",
        ],
    }

    # 配置快照 (密钥绝不导出)
    config_snapshot: Dict[str, Any] = {"note": "配置快照不可用"}
    try:  # 延迟构建内核: 纯导出场景不应拉起模型栈
        from ..app import build_kernel
        cfg = build_kernel().require("config")
        config_snapshot = {
            "provider": cfg.get("model.provider", ""),
            "model": cfg.get("model.model", ""),
            "base_url": cfg.get("model.base_url", ""),
            "note": "API 密钥已省略, 未导出",
        }
    except Exception:  # noqa: BLE001
        pass

    summary_lines = [
        f"# 会话导出: {src.stem}",
        "",
        f"- 标题: {title or '(无)'}",
        f"- 消息数: {msg_count}",
        f"- 事件数: {len(records)}",
        f"- 导出时间: {exported_at}",
        "",
        "## 会话中产生/修改的文件",
    ]
    summary_lines += [f"- {p}" for p in files_written] or ["- (无)"]

    dest.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(src, arcname="session.jsonl")
        zf.writestr("manifest.json",
                    json.dumps(manifest, ensure_ascii=False, indent=2))
        zf.writestr("config_snapshot.json",
                    json.dumps(config_snapshot, ensure_ascii=False, indent=2))
        zf.writestr("files_manifest.json",
                    json.dumps({"count": len(files_written), "files": files_written},
                               ensure_ascii=False, indent=2))
        zf.writestr("summary.md", "\n".join(summary_lines) + "\n")
    return dest
