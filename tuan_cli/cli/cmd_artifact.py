"""artifact 命令 —— Artifact 产物只读枚举 (第 110 个独特功能)。

artifact 工具 (tools/artifact_tool.py) 把 markdown 渲染为自包含 HTML
产物, 落盘到 ``<workspace>/.tuan/artifacts/<标题>_<时间戳>.html``, 只保留
最近 20 个 (写路径自动清理)。此前该目录**只写不读**: 用户无法看到已
生成过哪些产物、各标题是什么、多大、何时生成, 也无法在不开浏览器时
预览内容首行。对比 image_gen 有 ``list_generated`` 只读面, artifact 侧
无对应物 —— 此缺口是差异化价值所在。

差异化价值: Claude Code 的 Artifacts 是隐式生成的私有页面, 用户没有
"列出已生成产物"的只读视图。本命令枚举 artifacts 目录 (glob + stat,
纯只读), 不调用 _create_artifact / _cleanup_old_artifacts (写路径),
也不 mkdir。

  tuan artifact list [--workspace DIR] [--limit N] [--json]   # 枚举产物
  tuan artifact show <文件名> [--workspace DIR]               # 提取正文首行预览
"""

from __future__ import annotations

import html
import json
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from ._ui_singleton import console
from .parser import _register_command


def _resolve_workspace(raw: Optional[str]) -> Path:
    if raw:
        return Path(raw).expanduser().resolve()
    env = os.environ.get("TUAN_WORKSPACE")
    if env:
        return Path(env).expanduser().resolve()
    return Path.cwd().resolve()


def _artifacts_dir(workspace: Path) -> Path:
    return workspace / ".tuan" / "artifacts"


def _title_from_name(name: str) -> str:
    """从文件名反推标题: <标题>_<时间戳>.html → 标题 (去尾时间戳)。"""
    stem = Path(name).stem
    m = re.match(r"^(.*)_(\d{8}_\d{6})$", stem)
    if m:
        return m.group(1)
    return stem


def _preview(path: Path, max_chars: int = 90) -> str:
    """提取 HTML 正文的纯文本首行 (只读, 不解析完整)。"""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "(不可读)"
    # 去 <script>/<style> 块, 再剥标签, 取首个非空文本行
    text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_chars] if text else "(空)"


def _row(path: Path) -> Dict[str, Any]:
    st = path.stat()
    return {
        "file": path.name,
        "title": _title_from_name(path.name),
        "size_bytes": st.st_size,
        "mtime": st.st_mtime,
        "iso": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(st.st_mtime)),
        "preview": _preview(path),
    }


def cmd_artifact(args: Any) -> int:
    """Artifact 产物只读枚举 (第 110 个独特功能, 纯只读)。"""
    sub = getattr(args, "artifact_cmd", None) or "list"
    json_mode = bool(getattr(args, "json", False))
    workspace = _resolve_workspace(getattr(args, "workspace", None))
    adir = _artifacts_dir(workspace)

    if sub == "list":
        if not adir.is_dir():
            if json_mode:
                print(json.dumps({"workspace": str(workspace),
                                  "artifacts_dir": str(adir),
                                  "initialized": False, "items": []},
                                 ensure_ascii=False, indent=2))
                return 0
            console.print("[dim]Artifacts 目录未初始化 (尚无产物; "
                          "用 /artifacts 或 artifact 工具生成后自动建立)[/dim]")
            return 0
        rows = [_row(p) for p in sorted(adir.glob("*.html"),
                                        key=lambda p: p.stat().st_mtime, reverse=True)]
        limit = int(getattr(args, "limit", 0) or 0)
        if limit and len(rows) > limit:
            rows = rows[:limit]
        if json_mode:
            print(json.dumps({"workspace": str(workspace),
                              "artifacts_dir": str(adir),
                              "initialized": True, "items": rows},
                             ensure_ascii=False, indent=2))
            return 0
        console.print(f"[bold]=== Artifact 产物 · {adir} ===[/bold]\n")
        if not rows:
            console.print("  [dim](空)[/dim]")
            return 0
        total_bytes = sum(r["size_bytes"] for r in rows)
        console.print(f"  {len(rows)} 个产物 · 共 {total_bytes/1024:.1f} KB\n")
        for r in rows:
            console.print(f"  [bold]{r['title']}[/bold]")
            console.print(f"      {r['file']} · {r['size_bytes']/1024:.1f} KB · {r['iso']}")
            if r["preview"]:
                console.print(f"      [dim]{r['preview'][:70]}[/dim]")
        return 0

    elif sub == "show":
        name = getattr(args, "file", None)
        if not name:
            console.print("[red]缺少文件名: tuan artifact show <文件名>[/red]")
            return 1
        target = (adir / name).resolve()
        if not target.is_file() or not str(target).startswith(str(adir.resolve())):
            console.print(f"[red]产物不存在: {name}[/red]")
            return 1
        r = _row(target)
        if json_mode:
            print(json.dumps(r, ensure_ascii=False, indent=2))
            return 0
        console.print(f"[bold]{r['title']}[/bold]")
        console.print(f"  {r['file']} · {r['size_bytes']/1024:.1f} KB · {r['iso']}")
        console.print(f"\n  {r['preview']}")
        console.print("\n[dim]完整产物用浏览器打开: " +
                      str(target).replace("\\", "/") + "[/dim]")
        return 0

    else:
        console.print(f"[red]未知子命令: {sub}[/red]")
        console.print("可用: list / show")
        return 1


_register_command("cmd_artifact", ".cmd_artifact")
