"""codedev.retrieval —— 确定性代码检索（ContextForge）。

设计目标（非 loop）：
    弱模型循环一亿次也成不了 Opus。真正拉开差距的是「模型每次调用时, 手里有没有
    刚好相关的代码」。本模块在**不调用任何模型**的前提下, 用 AST 解析 + 倒排索引 +
    (可选的) 调用图邻居, 把一个自然语言任务检索成「最该看的那几个符号 + 它们的片段 +
    相关的调用上下文」, 打包成可直接注入 prompt 的 context pack。

成本特征：
    - 纯本地 AST 解析 + 字符串索引, 零网络、零 token。
    - 一次任务通常 1 次检索 = O(文件数) 的本地解析（毫秒级）, 远低于多轮试错。
    - 这是把「弱模型 + 20% 成本上限」拉到 CC+Opus 档位的第一杠杆。

中文友好：内置一份「开发术语 中文→英文」映射, 让「实现登录功能」也能命中 login 符号。
"""

from __future__ import annotations

import ast
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

# --------------------------------------------------------------------------- #
# 索引构建
# --------------------------------------------------------------------------- #

# 默认跳过的目录 / 文件（与 gitignore 的常见大块保持一致）
DEFAULT_SKIP_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv", "env",
    ".tox", ".mypy_cache", ".pytest_cache", "dist", "build",
    ".idea", ".vscode", "target", "bin", "obj", ".ruff_cache",
}
DEFAULT_SKIP_FILES = {".pyc", ".pyo", ".so", ".o", ".a", ".dll", ".exe"}
SUPPORTED_SUFFIXES = {".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs", ".java"}

STOPWORDS = {
    "the", "a", "an", "of", "to", "and", "or", "in", "on", "for", "with", "is",
    "are", "be", "by", "from", "as", "at", "it", "this", "that", "we", "you",
    "i", "do", "does", "done", "make", "implement", "add", "create", "update",
    "fix", "use", "using", "function", "class", "method", "please", "need",
    "should", "want", "how", "can", "will", "the", "my", "our", "their",
}

# 中文开发术语 → 英文关键词（帮助中文任务命中英文符号名）
ZH_TO_EN = {
    "登录": "login", "登出": "logout", "注销": "logout", "注册": "register signup",
    "认证": "auth authenticate", "授权": "authorize permission", "权限": "permission",
    "用户": "user", "密码": "password", "令牌": "token", "密钥": "secret key",
    "会话": "session", "缓存": "cache", "数据库": "database db", "表": "table model",
    "模型": "model", "视图": "view", "路由": "route router", "接口": "api endpoint",
    "请求": "request", "响应": "response", "错误": "error", "异常": "exception",
    "日志": "log logging", "配置": "config configuration", "测试": "test",
    "验证": "validate validation", "解析": "parse parser", "序列化": "serialize",
    "上传": "upload", "下载": "download", "导出": "export", "导入": "import",
    "支付": "payment", "订单": "order", "消息": "message", "队列": "queue",
    "任务": "task job", "调度": "schedule", "文件": "file", "图片": "image",
    "邮件": "email mail", "通知": "notify notification",
    # 运算/代码动作 (中文任务描述 → 符号名检索)
    "加法": "add sum", "减法": "sub subtract", "乘法": "mul multiply",
    "除法": "div divide", "求和": "sum total", "排序": "sort order",
    "搜索": "search find query", "查找": "find lookup", "替换": "replace",
    "合并": "merge combine", "拆分": "split", "转换": "convert transform",
    "创建": "create new make", "删除": "delete remove", "更新": "update",
    "读取": "read load", "写入": "write save", "修复": "fix repair",
}

_CAMEL_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")


def _split_ident(name: str) -> List[str]:
    """把 camelCase / snake_case / PascalCase 拆成小写 token 列表。"""
    parts = _CAMEL_RE.sub(" ", name).split()
    out: List[str] = []
    for p in parts:
        out.extend(t for t in p.split("_") if t)
    return [t.lower() for t in out if t]


def _tokenize(text: str) -> List[str]:
    toks: List[str] = []
    for raw in _TOKEN_RE.findall(text.lower()):
        # 还原中文映射里可能带空格的英文短语
        toks.append(raw)
    # 中文：逐词查表
    for zh, en in ZH_TO_EN.items():
        if zh in text:
            toks.extend(en.split())
    # 去停用词 + 拆标识符
    out: List[str] = []
    for t in toks:
        if t in STOPWORDS:
            continue
        out.extend(_split_ident(t))
    return [t for t in out if t and t not in STOPWORDS]


@dataclass
class Symbol:
    name: str
    kind: str                 # function | class | method | const
    file: str                 # 相对路径
    start: int                # 1-indexed 起始行
    end: int                  # 1-indexed 结束行
    doc: str = ""
    refs: Set[str] = field(default_factory=set)   # 该符号引用到的名字（含导入）
    tokens: Set[str] = field(default_factory=set)  # 检索用 token 集合

    def score(self, qtokens: Set[str]) -> float:
        if not qtokens:
            return 0.0
        name_tokens = set(_split_ident(self.name))
        # 名字命中权重最高（弱模型最需「同名函数」）
        name_hit = len(qtokens & name_tokens) * 3.0
        # doc / 引用命中
        doc_hit = len(qtokens & self.tokens) * 1.0
        ref_hit = len(qtokens & self.refs) * 0.5
        return name_hit + doc_hit + ref_hit


@dataclass
class RetrievalHit:
    symbol: Symbol
    score: float
    snippet: str             # 带行号的代码片段
    neighbors: List[Symbol]  # 调用图邻居（被谁调用 / 调用了谁）


@dataclass
class RetrievalResult:
    query: str
    hits: List[RetrievalHit]
    files_scanned: int
    symbols_indexed: int
    elapsed_ms: float

    def pack(self, with_neighbors: bool = True) -> str:
        """把检索结果渲染成可直接塞进 prompt 的 context pack。"""
        if not self.hits:
            return "(检索未命中相关代码, 任务可能是全新模块)"
        lines: List[str] = []
        lines.append(f"# 相关代码上下文（检索自 {self.files_scanned} 个文件, "
                     f"{self.symbols_indexed} 个符号, 耗时 {self.elapsed_ms:.0f}ms）")
        for i, h in enumerate(self.hits, 1):
            s = h.symbol
            lines.append(f"\n## [{i}] {s.kind} `{s.name}`  @ {s.file}:{s.start}")
            if s.doc:
                lines.append(f"# doc: {s.doc.strip().splitlines()[0][:200]}")
            lines.append("```")
            lines.append(h.snippet)
            lines.append("```")
            if with_neighbors and h.neighbors:
                nb = ", ".join(f"{n.name}@{n.file}:{n.start}" for n in h.neighbors[:4])
                lines.append(f"# 关联: {nb}")
        return "\n".join(lines)


class CodeIndex:
    """项目级符号索引（确定性, 无模型）。"""

    def __init__(self) -> None:
        self.symbols: List[Symbol] = []
        self._by_file: Dict[str, List[Symbol]] = {}
        self._name_index: Dict[str, List[int]] = {}   # 小写名字 → symbol 下标
        self._inv: Dict[str, List[int]] = {}          # token → symbol 下标
        self.root: Optional[str] = None
        self.files_scanned = 0
        self._file_meta: Dict[str, float] = {}        # rel → mtime (磁盘缓存指纹)

    # ------------------------------------------------------------------ 构建
    def build(self, root: str | Path, skip_dirs: Optional[Set[str]] = None) -> "CodeIndex":
        root = Path(root)
        self.root = str(root)
        skip = (skip_dirs or DEFAULT_SKIP_DIRS)
        for path in self._iter_files(root, skip):
            self._index_file(root, path)
        return self

    def _iter_files(self, root: Path, skip: Set[str]):
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in skip]
            for fn in filenames:
                if Path(fn).suffix in SUPPORTED_SUFFIXES and fn not in DEFAULT_SKIP_FILES:
                    yield Path(dirpath) / fn

    def _index_file(self, root: Path, path: Path) -> None:
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:  # noqa: BLE001
            return
        self.files_scanned += 1
        rel = str(path.relative_to(root))
        try:
            self._file_meta[rel] = path.stat().st_mtime
        except OSError:
            self._file_meta[rel] = 0.0
        suffix = path.suffix.lower()
        if suffix == ".py":
            self._index_py(rel, text)
        elif suffix in (".rs",):
            self._index_rust(rel, text)
        elif suffix in (".go",):
            self._index_go(rel, text)
        else:
            self._index_jslike(rel, text)

    def _register(self, sym: Symbol) -> None:
        idx = len(self.symbols)
        self.symbols.append(sym)
        self._by_file.setdefault(sym.file, []).append(sym)
        for n in _split_ident(sym.name):
            self._name_index.setdefault(n, []).append(idx)
        for t in sym.tokens:
            self._inv.setdefault(t, []).append(idx)

    def _index_py(self, rel: str, text: str) -> None:
        try:
            tree = ast.parse(text)
        except SyntaxError:
            return
        lines = text.splitlines()
        module_imports: Set[str] = set()

        def _collect_refs(node: ast.AST) -> Set[str]:
            refs: Set[str] = set()
            for n in ast.walk(node):
                if isinstance(n, ast.Name):
                    refs.add(n.id)
                elif isinstance(n, ast.Attribute):
                    refs.add(n.attr)
            return refs

        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                for a in node.names:
                    module_imports.add(a.asname or a.name.split(".")[0])

        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                self._emit_py(rel, node, lines, module_imports, prefix="")

        # 类内方法
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                for sub in node.body:
                    if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        self._emit_py(rel, sub, lines, module_imports, prefix=f"{node.name}.")

    def _emit_py(self, rel, node, lines, imports: Set[str], prefix: str) -> None:
        name = prefix + node.name
        start, end = getattr(node, "lineno", 1), getattr(node, "end_lineno", 1)
        doc = ast.get_docstring(node) or ""
        refs = set(imports)
        refs |= {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}
        refs |= {n.attr for n in ast.walk(node) if isinstance(n, ast.Attribute)}
        toks: Set[str] = set(_split_ident(name))
        toks |= set(_tokenize(doc))
        toks |= {x for d in refs for x in _split_ident(d)}
        kind = "class" if isinstance(node, ast.ClassDef) else "method" if prefix else "function"
        self._register(Symbol(name, kind, rel, start, end, doc, refs, toks))

    def _index_jslike(self, rel: str, text: str) -> None:
        lines = text.splitlines()
        pat = re.compile(
            r"(?:export\s+)?(?:async\s+)?function\s+([A-Za-z0-9_]+)"
            r"|(?:export\s+)?class\s+([A-Za-z0-9_]+)"
            r"|(?:const|let|var)\s+([A-Za-z0-9_]+)\s*="
            r"|(?:export\s+)?(?:async\s+)?function\s*\*\s*([A-Za-z0-9_]+)"
        )
        for m in pat.finditer(text):
            name = next(g for g in m.groups() if g)
            start = text[:m.start()].count("\n") + 1
            # 简单向下取 40 行作为片段边界
            end = min(start + 40, len(lines))
            doc = ""
            if start > 1 and lines[start - 2].strip().startswith("//"):
                doc = lines[start - 2].strip().lstrip("/ ").strip()
            toks = set(_split_ident(name)) | set(_tokenize(doc))
            kind = "class" if "class" in m.group(0) else "function"
            self._register(Symbol(name, kind, rel, start, end, doc, set(), toks))

    def _index_rust(self, rel: str, text: str) -> None:
        """Rust: fn / struct / enum / trait / impl / pub mod / type alias."""
        lines = text.splitlines()
        pat = re.compile(
            r"(?:pub\s+)?(?:async\s+)?fn\s+([A-Za-z0-9_]+)"
            r"|(?:pub\s+)?struct\s+([A-Za-z0-9_]+)"
            r"|(?:pub\s+)?enum\s+([A-Za-z0-9_]+)"
            r"|(?:pub\s+)?trait\s+([A-Za-z0-9_]+)"
            r"|(?:pub\s+)?type\s+([A-Za-z0-9_]+)"
            r"|(?:pub\s+)?mod\s+([A-Za-z0-9_]+)"
        )
        for m in pat.finditer(text):
            name = next(g for g in m.groups() if g)
            start = text[:m.start()].count("\n") + 1
            end = min(start + 40, len(lines))
            doc = ""
            if start > 1 and lines[start - 2].strip().startswith("///"):
                doc = lines[start - 2].strip().lstrip("/ ").strip()
            toks = set(_split_ident(name)) | set(_tokenize(doc))
            kind = "function" if "fn" in m.group(0) else "class"
            self._register(Symbol(name, kind, rel, start, end, doc, set(), toks))
        # impl 块内的方法
        impl_pat = re.compile(r"impl(?:<[^>]*>)?\s+\w+\s*")
        fn_in_impl = re.compile(r"(?:pub\s+)?(?:async\s+)?fn\s+([A-Za-z0-9_]+)")
        for impl_m in impl_pat.finditer(text):
            impl_start = text[:impl_m.start()].count("\n") + 1
            brace_start = text.find('{', impl_m.end())
            if brace_start == -1:
                continue
            # 匹配嵌套大括号: { ... { ... } ... }
            depth = 1
            i = brace_start + 1
            while i < len(text) and depth > 0:
                if text[i] == '{':
                    depth += 1
                elif text[i] == '}':
                    depth -= 1
                i += 1
            brace_end = i
            impl_body = text[brace_start:brace_end]
            # 从 impl 行提取类型名: impl Foo<Bar> → Foo
            impl_words = impl_m.group().split()
            impl_name = impl_words[-1].split('<')[0] if impl_words else "?"
            for fn_m in fn_in_impl.finditer(impl_body):
                fn_name = fn_m.group(1)
                fn_line = impl_start + impl_body[:fn_m.start()].count("\n")
                end = min(fn_line + 30, len(lines))
                doc = ""
                if fn_line > 1 and lines[fn_line - 2].strip().startswith("///"):
                    doc = lines[fn_line - 2].strip().lstrip("/ ").strip()
                full_name = f"{impl_name}.{fn_name}"
                toks = set(_split_ident(full_name)) | set(_tokenize(doc))
                self._register(Symbol(full_name, "method", rel, fn_line, end, doc, set(), toks))

    def _index_go(self, rel: str, text: str) -> None:
        """Go: func / type struct / type interface / package-level const/var."""
        lines = text.splitlines()
        func_pat = re.compile(r"func\s+(?:\([^)]+\)\s+)?([A-Za-z0-9_]+)")
        type_pat = re.compile(r"type\s+([A-Za-z0-9_]+)\s+(struct|interface)")
        for m in func_pat.finditer(text):
            name = m.group(1)
            start = text[:m.start()].count("\n") + 1
            end = min(start + 40, len(lines))
            doc = ""
            if start > 1 and lines[start - 2].strip().startswith("//"):
                doc = lines[start - 2].strip().lstrip("/ ").strip()
            toks = set(_split_ident(name)) | set(_tokenize(doc))
            self._register(Symbol(name, "function", rel, start, end, doc, set(), toks))
        for m in type_pat.finditer(text):
            name = m.group(1)
            start = text[:m.start()].count("\n") + 1
            end = min(start + 40, len(lines))
            doc = ""
            if start > 1 and lines[start - 2].strip().startswith("//"):
                doc = lines[start - 2].strip().lstrip("/ ").strip()
            toks = set(_split_ident(name)) | set(_tokenize(doc))
            self._register(Symbol(name, "class", rel, start, end, doc, set(), toks))

    # ------------------------------------------------------------------ 检索
    def retrieve(self, query: str, top_k: int = 8, ctx_lines: int = 6,
                 include_neighbors: bool = True) -> RetrievalResult:
        t0 = time.time()
        qtoks = set(_tokenize(query))
        if not qtoks:
            # 整句都没拆出 token（纯标点等）：退化为按文件列表返回
            qtoks = set(_split_ident(query)) or {"main"}

        scored: List[Tuple[float, int]] = []
        for idx, sym in enumerate(self.symbols):
            s = sym.score(qtoks)
            if s > 0:
                scored.append((s, idx))
        scored.sort(key=lambda x: x[0], reverse=True)
        scored = scored[: top_k * 3]  # 候选放大, 后面按文件去重

        hits: List[RetrievalHit] = []
        seen_files: Set[str] = set()
        for score, idx in scored:
            if len(hits) >= top_k:
                break
            sym = self.symbols[idx]
            # 同一文件取前 2 个, 保证多样性
            cnt = sum(1 for h in hits if h.symbol.file == sym.file)
            if cnt >= 2 and sym.file in seen_files:
                continue
            seen_files.add(sym.file)
            snippet = self._snippet(sym, ctx_lines)
            neighbors = self._neighbors(sym) if include_neighbors else []
            hits.append(RetrievalHit(sym, score, snippet, neighbors))

        elapsed = (time.time() - t0) * 1000
        return RetrievalResult(
            query=query, hits=hits, files_scanned=self.files_scanned,
            symbols_indexed=len(self.symbols), elapsed_ms=elapsed,
        )

    def _snippet(self, sym: Symbol, ctx_lines: int) -> str:
        try:
            path = Path(self.root or "") / sym.file
            lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        except Exception:  # noqa: BLE001
            return ""
        lo = max(1, sym.start - ctx_lines)
        hi = min(len(lines), sym.end + ctx_lines)
        out: List[str] = []
        for ln in range(lo, hi + 1):
            out.append(f"{ln:>5} | {lines[ln - 1]}")
        return "\n".join(out)

    def _neighbors(self, sym: Symbol, max_n: int = 4) -> List[Symbol]:
        """关联符号：优先返回「引用了该符号名字」的其它符号（调用图邻居）,
        不足时用同文件模块内符号补齐（弱模型最需看到同模块上下文）。"""
        out: List[Symbol] = []
        sym_tokens = set(_split_ident(sym.name))
        for other in self.symbols:
            if other is sym:
                continue
            if sym_tokens & other.refs:
                out.append(other)
        # 同文件模块内符号（排除自身）作为补充关联
        for other in self.symbols:
            if other is sym or other.file != sym.file:
                continue
            if other not in out:
                out.append(other)
            if len(out) >= max_n:
                break
        return out[:max_n]

    # ------------------------------------------------------------------ 增量更新

    def update_incremental(self, root: str | Path, skip_dirs: Optional[Set[str]] = None) -> int:
        """增量更新索引: 只重新索引变更/新增的文件, 跳过未变化的文件。

        返回新增/更新的符号数。适合频繁调用 (如 DevLoop 每轮验证后刷新)。
        """
        root = Path(root)
        if self.root is None or str(root.resolve()) != str(Path(self.root).resolve()):
            # 根目录变了, 做全量重建
            self.build(root, skip_dirs)
            return len(self.symbols)
        skip = skip_dirs or DEFAULT_SKIP_DIRS
        updated = 0
        current_files: Set[str] = set()
        for path in self._iter_files(root, skip):
            rel = str(path.relative_to(root))
            current_files.add(rel)
            try:
                cur_mtime = path.stat().st_mtime
            except OSError:
                continue
            prev_mtime = self._file_meta.get(rel)
            if prev_mtime is not None and cur_mtime == prev_mtime:
                continue  # 文件未变化, 跳过
            # 文件变化或新增: 移除旧符号, 重新索引
            self._remove_file_symbols(rel)
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except Exception:  # noqa: BLE001
                continue
            self.files_scanned += 1
            self._file_meta[rel] = cur_mtime
            suffix = path.suffix.lower()
            if suffix == ".py":
                self._index_py(rel, text)
            elif suffix in (".rs",):
                self._index_rust(rel, text)
            elif suffix in (".go",):
                self._index_go(rel, text)
            else:
                self._index_jslike(rel, text)
            updated += 1
        # 检测已删除的文件
        deleted = set(self._file_meta.keys()) - current_files
        for rel in deleted:
            self._remove_file_symbols(rel)
            del self._file_meta[rel]
            updated += 1
        return updated

    def _remove_file_symbols(self, rel: str) -> None:
        """移除指定文件的所有符号, 并重建内存索引。"""
        removed_list = self._by_file.pop(rel, [])
        if not removed_list:
            return
        removed_ids = set(id(s) for s in removed_list)
        # 重建符号列表和倒排索引
        new_symbols = [s for s in self.symbols if id(s) not in removed_ids]
        self.symbols = new_symbols
        self._name_index.clear()
        self._inv.clear()
        self._by_file.clear()
        for idx, sym in enumerate(self.symbols):
            self._by_file.setdefault(sym.file, []).append(sym)
            for n in _split_ident(sym.name):
                self._name_index.setdefault(n, []).append(idx)
            for t in sym.tokens:
                self._inv.setdefault(t, []).append(idx)

    # ------------------------------------------------------------------ 磁盘缓存

    def is_fresh(self, root: str | Path) -> bool:
        """校验磁盘索引对当前工作区是否新鲜 (root 相同 + 已索引文件 mtime 未变)。"""
        root = Path(root)
        if self.root is None or str(root.resolve()) != str(Path(self.root).resolve()):
            return False
        for rel, mtime in self._file_meta.items():
            try:
                cur = (root / rel).stat().st_mtime
            except OSError:
                return False
            if cur != mtime:
                return False
        return True

    def to_dict(self) -> Dict[str, Any]:
        """序列化 (不含派生索引, 加载时重建)。"""
        return {
            "version": 1,
            "root": self.root,
            "files_scanned": self.files_scanned,
            "file_meta": dict(sorted(self._file_meta.items())),
            "symbols": [
                {"name": s.name, "kind": s.kind, "file": s.file,
                 "start": s.start, "end": s.end, "doc": s.doc,
                 "refs": sorted(s.refs), "tokens": sorted(s.tokens)}
                for s in self.symbols
            ],
        }

    def save(self, path: str | Path) -> bool:
        """原子写索引缓存到磁盘。"""
        import json
        from pathlib import Path as _P

        try:
            target = _P(path)
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_suffix(".tmp")
            tmp.write_text(
                json.dumps(self.to_dict(), ensure_ascii=False),
                encoding="utf-8",
            )
            tmp.replace(target)
            return True
        except Exception:  # noqa: BLE001
            return False

    @classmethod
    def load(cls, path: str | Path) -> Optional["CodeIndex"]:
        """从磁盘加载索引; 失败/版本不符返回 None。"""
        import json

        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return None
        if not isinstance(data, dict) or data.get("version") != 1:
            return None
        idx = cls()
        idx.root = data.get("root")
        idx.files_scanned = int(data.get("files_scanned", 0))
        meta = data.get("file_meta") or {}
        idx._file_meta = {k: float(v) for k, v in meta.items()}
        for item in data.get("symbols") or []:
            sym = Symbol(
                name=item["name"], kind=item.get("kind", "symbol"),
                file=item["file"], start=int(item.get("start", 1)),
                end=int(item.get("end", 1)), doc=item.get("doc", ""),
                refs=set(item.get("refs") or []),
                tokens=set(item.get("tokens") or []),
            )
            idx._register(sym)
        return idx


    def stats(self) -> Dict[str, Any]:
        return {
            "files_scanned": self.files_scanned,
            "symbols_indexed": len(self.symbols),
            "root": self.root,
        }
