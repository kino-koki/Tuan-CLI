#!/usr/bin/env python3
"""扫描 .git 全部对象, 按内容特征找回 tests/test_platform_portability.py。"""
from __future__ import annotations

import sys
from pathlib import Path

from dulwich.object_format import DEFAULT_OBJECT_FORMAT
from dulwich.pack import load_pack_index
from dulwich.repo import Repo

REPO = Repo("F:/Tuan-CLI")
GIT = Path("F:/Tuan-CLI/.git")
OUT = Path("F:/Tuan-CLI/tests/test_platform_portability.py")

MARKERS = [b"csrutil", b"kextload", b"/etc/shadow", b"test_platform_portability"]


def main() -> int:
    idx_files = list(GIT.glob("objects/pack/*.idx"))
    print(f"pack idx files: {[p.name for p in idx_files]}")
    shas = []
    for idx_path in idx_files:
        idx = load_pack_index(str(idx_path), DEFAULT_OBJECT_FORMAT)
        n = len(idx)
        print(f"{idx_path.name}: {n} objects")
        shas.extend(idx)
    # 去重
    seen = set()
    uniq = []
    for s in shas:
        if s not in seen:
            seen.add(s)
            uniq.append(s)
    print(f"total unique shas: {len(uniq)}")

    candidates = []
    blobs = 0
    for i, sha in enumerate(uniq):
        try:
            obj = REPO[sha]
        except Exception:
            continue
        if obj.type_name != b"blob":
            continue
        blobs += 1
        data = obj.data
        if len(data) < 2000:
            continue
        hits = [m for m in MARKERS if m in data]
        # 测试模块特征: import pytest + 足够多的 def test_, 且不像 markdown 文档
        n_tests = data.count(b"def test_")
        looks_like_doc = (b"\n## " in data[:4000]) or (b"# [" in data[:2000])
        if (b"import pytest" in data and n_tests >= 50 and not looks_like_doc
                and len(data) < 300000 and b"csrutil" in data):
            candidates.append((len(data), sha, hits + [f"tests={n_tests}"]))
        if i % 20000 == 0:
            print(f"  scanned {i}...", flush=True)
    print(f"blobs scanned: {blobs}; candidates: {len(candidates)}")
    for size, sha, hits in sorted(candidates, reverse=True)[:10]:
        print(f"  {sha.hex()} size={size} markers={[h.decode() for h in hits]}")
    if candidates:
        size, sha, _ = sorted(candidates, reverse=True)[0]
        data = REPO[sha].data
        print("---- candidate head ----")
        print(data[:400].decode("utf-8", "replace"))
        print("---- candidate tail ----")
        print(data[-200:].decode("utf-8", "replace"))
        if b"import pytest" not in data[:2000]:
            print("REFUSED: head lacks 'import pytest' — not restoring")
            return 1
        OUT.write_bytes(data)
        print(f"restored {OUT} ({len(data)} bytes from {sha.hex()})")
        return 0
    print("NO CANDIDATE FOUND")
    return 1


if __name__ == "__main__":
    sys.exit(main())
