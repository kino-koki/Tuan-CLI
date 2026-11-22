#!/usr/bin/env python3
"""从 .git 历史恢复 tests/test_platform_portability.py (一次性恢复脚本)。

背景: README/CHANGELOG/cmd_safe.py 都引用 tests/test_platform_portability.py
(第 5 安全套件, 274 载荷), 但当前工作树里该文件缺失, `tuan safe bench` 的
可移植性阶段因此 rc=4 假绿。本脚本用 dulwich 遍历全部提交, 找到最近一个
包含该路径的提交, 把 blob 原样写回工作树。
"""
from __future__ import annotations

import sys
from pathlib import Path

from dulwich.repo import Repo
from dulwich.walk import Walker

REPO = Repo("F:/Tuan-CLI")
TARGET = b"tests/test_platform_portability.py"
OUT = Path("F:/Tuan-CLI/tests/test_platform_portability.py")


def tree_lookup(tree_sha: bytes):
    """在树里逐级查找 TARGET, 命中返回 blob sha。"""
    parts = TARGET.split(b"/")
    cur = tree_sha
    for i, part in enumerate(parts):
        try:
            tree = REPO[cur]
        except KeyError:
            return None
        if tree.type_name != b"tree":
            return None
        found = None
        for _mode, name, sha in tree.items():
            if name == part:
                found = sha
                break
        if found is None:
            return None
        if i == len(parts) - 1:
            return found
        cur = found
    return None


def main() -> int:
    refs = REPO.get_refs()
    heads = [v for k, v in refs.items() if k.startswith(b"refs/heads/") or k == b"HEAD"]
    # 去重
    heads = list({h for h in heads})
    print(f"refs: {len(refs)}, branch heads: {len(heads)}")
    hits = []  # (commit_time, sha, subject)
    for head in heads:
        try:
            walker = Walker(REPO, [head])
            for entry in walker:
                commit = getattr(entry, "commit", entry)
                blob = tree_lookup(commit.tree)
                if blob is not None:
                    hits.append((commit.commit_time, commit.id, blob,
                                 commit.message.split(b"\n")[0][:70]))
        except Exception as exc:  # noqa: BLE001
            print(f"walk {head.hex()[:12]} failed: {exc}")
    if not hits:
        print("NOT FOUND in any commit")
        return 1
    hits.sort(reverse=True)
    newest_time, newest_commit, blob_sha, subject = hits[0]
    oldest = hits[-1]
    print(f"found in {len(hits)} commits; newest {newest_commit.hex()[:12]} "
          f"({newest_time}) subject={subject!r}")
    print(f"oldest hit commit {oldest[1].hex()[:12]} ({oldest[0]})")
    blob = REPO[blob_sha]
    data = blob.data
    OUT.write_bytes(data)
    print(f"restored {OUT} ({len(data)} bytes, blob {blob_sha.hex()[:12]})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
