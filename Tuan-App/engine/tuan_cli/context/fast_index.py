"""FastFileIndex —— 极速代码地图 / 快速文件定位 (速度主线 A)。

借鉴 Claude Code / Freebuff / Codebuff 编码 Agent 的工程做法:
本地代码地图 + 快速定位相关文件 + 省 token 不读全文。

设计要点:
- 持久化增量索引: 缓存到 ``<workspace>/.tuan/fastindex/index.json``,
  原子写 (先写 .tmp 再 os.replace), 重启后可直接恢复。
- 以 (mtime_ns, size) 为文件指纹; ``build()`` 只重扫指纹变化的文件
  (新增 / 修改 / 删除均正确同步), 未变文件只 stat 不读内容。
- 每个文件只存轻量元信息: relpath / lang / size / loc / mtime /
  top-symbols / 首行片段 —— 绝不把全文塞进索引, 省 token。
- 符号提取直接复用 ``tuan_cli/ext/index_engine.py`` 的 ``_extract_symbols``,
  不重复造轮子; 跳过目录复用 ``context/indexer.py`` 的 ``_SKIP_DIRS``。

API (冻结签名, pick_files 工具与后续 /context 类功能依赖):
    build(force=False)        -> BuildStats   # 增量: 只重扫指纹变化的文件
    find(pattern, limit=20)  -> list[dict]   # 文件名/路径子串
    rank(keywords, limit=10)  -> list[(path, score, reason_str)]
    related(path, limit=5)    -> list[(path, reason_str)]  # 按 import 引用边
    stats()                   -> dict
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple

from ..ext.index_engine import _LANG_MAP, _extract_symbols
from .indexer import _SKIP_DIRS

# 单文件超过此体积 (2MB) 只记元信息, 不读全文提取符号, 防止超大文件拖慢索引。
_MAX_FILE_BYTES = 2 * 1024 * 1024
# 每个文件记录的顶层符号上限, 控制索引体积。
_MAX_SYMBOLS = 50
# 索引自身缓存目录名 (相对 workspace)。
_CACHE_DIR = ".tuan"
_CACHE_NAME = "fastindex"

# rank 加权: 符号命中 3 / 文件名(路径)命中 2 / 首行片段命中 1。
_W_SYMBOL = 3
_W_PATH = 2
_W_HEAD = 1

# Python import / from 语句提取 (只取模块名, 忽略相对导入)。
_IMPORT_RE = re.compile(r"^\s*(?:from\s+([\w.]+)\s+import|import\s+([\w.]+))")


@dataclass
class BuildStats:
    """一次 build() 的结果统计 (同时用于测试断言「未变文件不被重扫」)。"""
    file_count: int        # 索引内文件总数
    added: int             # 新增文件数
    rebuilt: int           # 指纹变化而重新读取/解析内容的文件数
    unchanged: int         # 指纹未变、仅 stat 跳过的文件数
    removed: int           # 磁盘上已删除而从索引移除的文件数
    walked: int            # 磁盘上扫描到的文件总数
    elapsed: float         # 本次 build 耗时 (秒)


class FastFileIndex:
    """持久化、增量的快速文件定位索引。"""

    def __init__(self, workspace: str, max_files: int = 500,
                 max_loc: int = 500_000) -> None:
        self.workspace = str(workspace)
        self.max_files = max_files
        self.max_loc = max_loc
        self._root = Path(self.workspace)
        self._cache_dir = self._root / _CACHE_DIR / _CACHE_NAME
        self._index_path = self._cache_dir / "index.json"
        self._entries: Dict[str, dict] = {}
        self._loaded = False
        self.last_build: BuildStats | None = None
        # 构造即从磁盘缓存恢复 (若有), 做到「重启后可恢复」开箱可用。
        self._load()

    # ------------------------------------------------------------------ 持久化

    def _load(self) -> None:
        """从磁盘缓存恢复索引 (失败则空索引)。"""
        self._loaded = True
        try:
            with open(self._index_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            entries = data.get("entries", {})
            # 只接受 dict 结构, 损坏缓存安全降级为空。
            if isinstance(entries, dict):
                self._entries = {k: v for k, v in entries.items()
                                if isinstance(v, dict) and "relpath" in v}
        except (OSError, ValueError):
            self._entries = {}

    def _save(self) -> None:
        """原子写: 先写 .tmp 再 os.replace, 避免中途崩溃留下坏索引。"""
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        tmp = str(self._index_path) + ".tmp"
        data = {"version": 1, "entries": self._entries}
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, str(self._index_path))

    # ------------------------------------------------------------------ 扫描

    def _read_entry(self, rel: str, full: Path, st: os.stat_result) -> dict:
        """读取单个文件并构造索引条目; 超大文件只记元信息。"""
        ext = Path(rel).suffix.lower()
        lang = _LANG_MAP.get(ext, "other")
        entry: dict = {
            "relpath": rel, "lang": lang, "size": st.st_size,
            "mtime": st.st_mtime, "mtime_ns": st.st_mtime_ns,
            "loc": 0, "symbols": [], "head": "",
        }
        if st.st_size > _MAX_FILE_BYTES:
            return entry  # 大文件: 只记元信息, 不读全文
        try:
            content = full.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return entry
        entry["loc"] = sum(1 for _ in content.splitlines())
        try:
            names, _details = _extract_symbols(content, lang)
        except Exception:  # noqa: BLE001  符号提取失败不影响索引本体
            names = []
        entry["symbols"] = list(names)[:_MAX_SYMBOLS]
        for line in content.splitlines():
            s = line.strip()
            if s:
                entry["head"] = s[:80]  # 首行片段 (前 80 字符)
                break
        return entry

    def build(self, force: bool = False) -> BuildStats:
        """增量构建 / 更新索引。

        force=True 时丢弃内存与磁盘缓存全量重建; 否则只重扫指纹
        (mtime_ns + size) 变化的文件, 并同步删除已不存在的条目。
        """
        t0 = time.perf_counter()
        if force:
            self._entries = {}
            self._loaded = True
        elif not self._loaded:
            self._load()

        added = rebuilt = unchanged = removed = walked = 0
        seen: set = set()
        if self._root.is_dir():
            for cur, dirs, files in os.walk(self._root):
                # 跳过噪声目录 (依赖 / 产物 / 缓存), 并跳过索引自身缓存目录。
                dirs[:] = [d for d in dirs
                           if d not in _SKIP_DIRS and d != _CACHE_DIR]
                for fname in files:
                    full = Path(cur) / fname
                    try:
                        st = full.stat()
                    except OSError:
                        continue
                    rel = full.relative_to(self._root).as_posix()
                    walked += 1
                    seen.add(rel)
                    old = self._entries.get(rel)
                    # 指纹未变 → 不读内容, 直接复用旧条目。
                    if (not force and old is not None
                            and old.get("size") == st.st_size
                            and old.get("mtime_ns") == st.st_mtime_ns):
                        unchanged += 1
                        continue
                    # 超出文件上限且是新文件 → 不收录 (但仍计入 seen, 避免误判删除)。
                    if old is None and len(self._entries) >= self.max_files:
                        continue
                    self._entries[rel] = self._read_entry(rel, full, st)
                    if old is None:
                        added += 1
                    else:
                        rebuilt += 1

        # 同步删除: 磁盘上已不存在的条目从索引移除。
        for rel in [r for r in self._entries if r not in seen]:
            del self._entries[rel]
            removed += 1

        self._save()
        stats = BuildStats(
            file_count=len(self._entries), added=added, rebuilt=rebuilt,
            unchanged=unchanged, removed=removed, walked=walked,
            elapsed=round(time.perf_counter() - t0, 4),
        )
        self.last_build = stats
        return stats

    # ------------------------------------------------------------------ 查询

    def find(self, pattern: str, limit: int = 20) -> List[dict]:
        """按文件名 / 路径子串检索, 返回命中条目 (按路径排序)。"""
        pat = (pattern or "").lower()
        hits = [e for e in self._entries.values() if pat in e["relpath"].lower()]
        hits.sort(key=lambda e: e["relpath"])
        return hits[:limit]

    def rank(self, keywords: List[str], limit: int = 10) -> List[Tuple[str, int, str]]:
        """按关键词给文件打分排序。

        权重: 关键词命中顶层符号 +3, 命中文件名/路径 +2, 命中首行片段 +1。
        返回 [(relpath, score, reason_str)], reason 为一句中文理由。
        """
        if isinstance(keywords, str):
            keywords = [keywords]
        kws = [k.strip().lower() for k in (keywords or []) if k and str(k).strip()]
        scored: List[Tuple[str, int, str]] = []
        for rel, e in self._entries.items():
            score = 0
            sym_hits: List[str] = []
            path_hit = False
            head_hit = False
            rel_low = rel.lower()
            head_low = e.get("head", "").lower()
            for kw in kws:
                for sym in e.get("symbols", []):
                    if kw in sym.lower():
                        score += _W_SYMBOL
                        sym_hits.append(sym)
                if kw in rel_low:
                    score += _W_PATH
                    path_hit = True
                if kw in head_low:
                    score += _W_HEAD
                    head_hit = True
            if score > 0:
                scored.append((rel, score, self._reason(kws, sym_hits, path_hit, head_hit)))
        scored.sort(key=lambda x: (-x[1], x[0]))
        return scored[:limit]

    @staticmethod
    def _reason(kws: List[str], sym_hits: List[str],
                path_hit: bool, head_hit: bool) -> str:
        """生成一句中文打分理由。"""
        parts: List[str] = []
        if sym_hits:
            uniq = list(dict.fromkeys(sym_hits))[:3]
            extra = " 等" if len(set(sym_hits)) > len(uniq) else ""
            parts.append(f"含符号 {'/'.join(uniq)}{extra}")
        hit_kws = "、".join(kws) if kws else ""
        tail_bits = []
        if path_hit:
            tail_bits.append("路径名")
        if head_hit:
            tail_bits.append("首行片段")
        tail = f"命中关键词 {hit_kws}" + (f" ({'+'.join(tail_bits)})" if tail_bits else "")
        parts.append(tail)
        return "，".join(parts)

    def related(self, path: str, limit: int = 5) -> List[Tuple[str, str]]:
        """按 import/from 引用边找相关文件。

        解析目标文件的 import / from 语句得到模块名, 在索引里找模块对应的
        文件 (简单字符串匹配: foo.bar → foo/bar.py 或 foo/bar/__init__.py)。
        返回 [(relpath, reason_str)]。
        """
        rel = self._to_rel(path)
        if rel not in self._entries:
            return []
        full = self._root / rel
        try:
            content = full.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return []
        # 收集被 import 的模块名 (忽略相对导入)。
        modules: List[str] = []
        for line in content.splitlines():
            m = _IMPORT_RE.match(line)
            if not m:
                continue
            mod = (m.group(1) or m.group(2) or "").strip(".")
            if mod and not mod.startswith("."):
                # import a, b 只取第一个; from x import y 已取到 x。
                modules.append(mod.split(" as ")[0])
        modules = list(dict.fromkeys(modules))

        # 预计算每个条目的「点式模块名」。
        def to_mod(r: str) -> str:
            stem = r[:-3] if r.endswith(".py") else Path(r).stem
            return stem.replace("/", ".")

        results: List[Tuple[str, str]] = []
        seen_outr: set = set()
        for mod in modules:
            for r2 in self._entries:
                if r2 == rel or r2 in seen_outr:
                    continue
                m2 = to_mod(r2)
                if m2 == mod or m2.startswith(mod + "."):
                    seen_outr.add(r2)
                    results.append((r2, f"import 模块 {mod} 对应此文件"))
        return results[:limit]

    def _to_rel(self, path: str) -> str:
        """把传入路径 (相对/绝对) 规约为索引内的 posix 相对路径。"""
        p = Path(path)
        if not p.is_absolute():
            p = self._root / p
        try:
            return p.resolve().relative_to(self._root.resolve()).as_posix()
        except OSError:
            return path.replace("\\", "/")

    # ------------------------------------------------------------------ 统计

    def stats(self) -> dict:
        """返回索引规模 / 语言分布 / 最近一次 build 情况。"""
        by_lang: Dict[str, int] = {}
        total_loc = 0
        for e in self._entries.values():
            by_lang[e["lang"]] = by_lang.get(e["lang"], 0) + 1
            total_loc += e.get("loc", 0)
        return {
            "workspace": self.workspace,
            "file_count": len(self._entries),
            "total_loc": total_loc,
            "by_lang": by_lang,
            "max_files": self.max_files,
            "cache_path": str(self._index_path),
            "last_build": (self.last_build.__dict__ if self.last_build else None),
        }
