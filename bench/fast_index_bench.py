# -*- coding: utf-8 -*-
"""fast_index_bench —— FastFileIndex 速度基准 (速度主线 A)。

对照组 vs 实验组耗时对比, 在临时目录生成几百个文件的测试树:
  (a) 朴素全量重扫 (每次都 walk+read+parse 全部文件)
      vs FastFileIndex.build 首次建索引 (冷启动)
  (b) 改 1 个文件后: 全量重建 (force=True, 无增量)
      vs FastFileIndex 增量更新 (只重扫指纹变化的 1 个文件)
  (c) rank 查询耗时 (关键词打分 top-N)

用法:
  python bench/fast_index_bench.py            # 跑全部, 输出 JSON + 控制台摘要
  python bench/fast_index_bench.py --n 500   # 指定文件数量

输出:
  - bench/fast_index_bench_result.json   (机器可读)
  - 控制台打印对照摘要
"""

from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path

# 让脚本既能从 bench/ 目录直接跑, 也能从项目根跑。
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tuan_cli.context.fast_index import FastFileIndex  # noqa: E402
from tuan_cli.ext.index_engine import _LANG_MAP, _extract_symbols  # noqa: E402


def gen_tree(root: Path, n: int) -> None:
    """在临时目录生成 n 个混合 (python/js) 源文件树。"""
    (root / "pkg" / "sub").mkdir(parents=True)
    (root / "tests").mkdir()
    py_tmpl = (
        '"""模块 {name} 自动生成。"""\n\n'
        "def {name}_main():\n"
        "    \"\"\"入口函数。\"\"\"\n"
        "    return {i}\n\n"
        "class {name}Handler:\n"
        "    def handle(self):\n"
        "        return {i} * 2\n"
    )
    js_tmpl = (
        "// {name}.js 自动生成\n"
        "function {name}Loader() {{ return {i}; }}\n"
        "class {name}Service {{ run() {{ return {i}; }} }}\n"
    )
    for i in range(n):
        name = f"mod_{i:04d}"
        if i % 2 == 0:
            p = root / "pkg" / f"{name}.py"
            p.write_text(py_tmpl.format(name=name, i=i), encoding="utf-8")
        else:
            p = root / "pkg" / "sub" / f"{name}.js"
            p.write_text(js_tmpl.format(name=name, i=i), encoding="utf-8")


def naive_full_scan(root: Path) -> float:
    """对照组: 朴素全量重扫 —— walk 全部文件, 逐个 read + 提取符号。

    模拟「没有增量索引」时每次都要做的全部工作。
    """
    t0 = time.perf_counter()
    total_loc = 0
    sym_count = 0
    for cur, dirs, files in __import__("os").walk(root):
        dirs[:] = [d for d in dirs if d not in
                   {".git", "node_modules", "__pycache__", ".venv", "venv", ".tuan"}]
        for fname in files:
            fp = Path(cur) / fname
            try:
                content = fp.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            total_loc += content.count("\n")
            lang = _LANG_MAP.get(fp.suffix.lower(), "other")
            names, _ = _extract_symbols(content, lang)
            sym_count += len(names)
    return time.perf_counter() - t0


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=400, help="测试文件数量")
    args = ap.parse_args()

    work = Path(tempfile.mkdtemp(prefix="tuan_fastbench_"))
    gen_tree(work, args.n)

    result: dict = {"file_count": args.n, "scenarios": {}}

    # (a) 冷启动: 朴素全量重扫 vs FastFileIndex 首次 build
    naive_cold = naive_full_scan(work)
    idx = FastFileIndex(str(work))
    cold = idx.build()
    result["scenarios"]["a_cold"] = {
        "naive_full_scan_sec": round(naive_cold, 4),
        "fastindex_first_build_sec": round(cold.elapsed, 4),
        "indexed_files": cold.file_count,
    }

    # (b) 改 1 个文件后: 增量更新 vs 全量重建。
    # 注意顺序: idx 的内存/缓存仍是「改前」指纹, 先测增量 (应只重扫 1 个),
    # 再 force 全量重建 (模拟无增量时每次都要做的全部工作)。
    victim = work / "pkg" / "mod_0000.py"
    victim.write_text(
        victim.read_text(encoding="utf-8") + "\n# 改动一行, 触发指纹变化\n",
        encoding="utf-8",
    )
    incr = idx.build()                                         # 增量
    full_rebuild = FastFileIndex(str(work)).build(force=True)  # 模拟无增量
    result["scenarios"]["b_after_one_edit"] = {
        "full_rebuild_sec": round(full_rebuild.elapsed, 4),
        "incremental_sec": round(incr.elapsed, 4),
        "incremental_rebuilt_files": incr.rebuilt,
        "incremental_unchanged_files": incr.unchanged,
        "speedup": round(full_rebuild.elapsed / max(incr.elapsed, 1e-6), 1),
    }

    # (c) rank 查询耗时 (取平均)
    q = ["mod_0050", "Handler", "Loader"]
    reps = 30
    t0 = time.perf_counter()
    for _ in range(reps):
        idx.rank(q, limit=10)
    rank_avg = (time.perf_counter() - t0) / reps
    result["scenarios"]["c_rank_query"] = {
        "keywords": q, "avg_sec": round(rank_avg, 5), "reps": reps,
    }

    out = ROOT / "bench" / "fast_index_bench_result.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    # 控制台摘要
    a = result["scenarios"]["a_cold"]
    b = result["scenarios"]["b_after_one_edit"]
    c = result["scenarios"]["c_rank_query"]
    print("=" * 60)
    print(f"FastFileIndex 速度基准  (文件数={args.n}, 临时目录={work})")
    print("-" * 60)
    print(f"(a) 冷启动建索引: 朴素全量重扫 {a['naive_full_scan_sec']:.4f}s "
          f"vs FastFileIndex {a['fastindex_first_build_sec']:.4f}s")
    print(f"(b) 改 1 文件后: 全量重建 {b['full_rebuild_sec']:.4f}s "
          f"vs 增量更新 {b['incremental_sec']:.4f}s "
          f"(仅重扫 {b['incremental_rebuilt_files']} 个, "
          f"跳过 {b['incremental_unchanged_files']} 个, 提速 ~{b['speedup']}x)")
    print(f"(c) rank 查询平均: {c['avg_sec']*1000:.2f} ms/次")
    print("-" * 60)
    print(f"JSON 结果已写入: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
