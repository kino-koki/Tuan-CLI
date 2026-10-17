"""文件读写极速化基准 (read_files 并行读 / edit_files 事务写)。

对照 Freebuff / Codebuff 的工程做法:
- 读: 串行 N 次 read_file 往返  vs  一次 read_files 并行拿回;
- 写: 串行 N 次 edit_file 往返  vs  一次 edit_files 事务;
- 额外度量: edit_files 校验失败时的"回滚时长" (本应极快 —— 因为一个字节都没写)。

用法:
  python bench/fast_io_bench.py                # 默认 N=20, 文件 ~8KB
  python bench/fast_io_bench.py --n 40 --size 16
输出: 控制台摘要 + bench/fast_io_bench.json (JSON)。

说明: 本地 SSD 上的收益主要来自"省掉 N 次工具往返的 dispatch 管线开销"
(权限/缓存/hooks/schema), 而非磁盘吞吐; 这正是 Agent 场景下 read_files 的核心价值。
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tuan_cli.core.kernel import Kernel  # noqa: E402
from tuan_cli.config import Config  # noqa: E402
from tuan_cli.tools import ToolRegistryPlugin, builtin_tool_plugins  # noqa: E402
from tuan_cli.tools.base import ToolContext  # noqa: E402


def _build_ctx(workspace: Path):
    """构造与生产一致的内核 + 只读/写工具上下文。"""
    k = Kernel()
    k.provide("config", Config(), owner="bench")
    k.register(ToolRegistryPlugin())
    for p in builtin_tool_plugins():
        if p.name == "tools.filesystem":
            k.register(p)
    k.activate_all()
    ctx = ToolContext(kernel=k, workspace=str(workspace), confirm=lambda _p: True)
    return k, k.require("tool_registry"), ctx


def _gen_files(workspace: Path, n: int, size_kb: int) -> list[str]:
    """生成 n 个文本文件, 返回相对路径列表。"""
    paths = []
    line = "".join(f"L{i:03d} the quick brown fox jumps over the lazy dog\n" for i in range(16))
    block = line * max(1, size_kb // 1)
    for i in range(n):
        rel = f"file_{i:03d}.txt"
        (workspace / rel).write_text(f"# file {i}\n" + block, encoding="utf-8")
        paths.append(rel)
    return paths


def _reset_contents(workspace: Path, paths: list[str]) -> None:
    """把每个文件的标记词复位为可被替换的原值 (每次 edit 对照前重建)。"""
    for i, rel in enumerate(paths):
        (workspace / rel).write_text(f"# file {i}\nMARKER_ORIGINAL line\n", encoding="utf-8")


def _ms(fn) -> tuple[float, object]:
    """计时执行, 返回 (毫秒, fn 返回值)。"""
    start = time.perf_counter()
    ret = fn()
    return (time.perf_counter() - start) * 1000.0, ret


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=20, help="生成文件数 (默认 20)")
    ap.add_argument("--size", type=int, default=8, help="每文件 KB (默认 8)")
    ap.add_argument("--repeat", type=int, default=3, help="每组取最快一次 (默认 3)")
    args = ap.parse_args()

    workspace = Path(tempfile.mkdtemp(prefix="fastio_bench_"))
    k, reg, ctx = _build_ctx(workspace)
    paths = _gen_files(workspace, args.n, args.size)

    # 预热 (首次 dispatch 的惰性初始化不计入冷启动)
    reg.dispatch("read_file", json.dumps({"path": paths[0]}), ctx)

    # ---- (a) 读: 串行 read_file x N  vs  read_files 并行 ----
    def serial_read() -> float:
        best = float("inf")
        for _ in range(args.repeat):
            t, _ = _ms(lambda: [reg.dispatch("read_file", json.dumps({"path": p}), ctx) for p in paths])
            best = min(best, t)
        return best

    def parallel_read() -> float:
        best = float("inf")
        for _ in range(args.repeat):
            t, _ = _ms(lambda: reg.dispatch("read_files", json.dumps({"paths": paths}), ctx))
            best = min(best, t)
        return best

    serial_read_ms = serial_read()
    parallel_read_ms = parallel_read()

    # ---- (b) 写: 串行 edit_file x N  vs  edit_files 一次事务 ----
    items = [{"path": p, "old_string": "MARKER_ORIGINAL", "new_string": "MARKER_EDITED"} for p in paths]

    def serial_edit() -> float:
        _reset_contents(workspace, paths)
        # 守卫要求先读
        reg.dispatch("read_files", json.dumps({"paths": paths}), ctx)
        best = float("inf")
        for _ in range(args.repeat):
            _reset_contents(workspace, paths)
            t, _ = _ms(lambda: [
                reg.dispatch("edit_file", json.dumps(
                    {"path": p, "old_string": "MARKER_ORIGINAL", "new_string": "MARKER_EDITED"}), ctx)
                for p in paths
            ])
            best = min(best, t)
        return best

    def transaction_edit() -> float:
        best = float("inf")
        for _ in range(args.repeat):
            _reset_contents(workspace, paths)
            t, out = _ms(lambda: reg.dispatch("edit_files", json.dumps({"items": items}), ctx))
            assert "事务成功" in out, out[:200]
            best = min(best, t)
        return best

    serial_edit_ms = serial_edit()
    transaction_edit_ms = transaction_edit()

    # ---- (c) 校验失败回滚时长: 故意塞一个不匹配的 old, 度量整体拒绝的耗时 ----
    def rollback_time() -> float:
        _reset_contents(workspace, paths)
        bad_items = items + [{"path": paths[-1], "old_string": "DOES_NOT_EXIST_XX", "new_string": "x"}]
        best = float("inf")
        for _ in range(args.repeat):
            t, out = _ms(lambda: reg.dispatch("edit_files", json.dumps({"items": bad_items}), ctx))
            assert "整体拒绝" in out, out[:200]
            best = min(best, t)
        # 断言零变化
        for p in paths:
            assert "MARKER_ORIGINAL" in (workspace / p).read_text(encoding="utf-8")
        return best

    rollback_ms = rollback_time()

    result = {
        "n_files": args.n,
        "size_kb_each": args.size,
        "serial_read_ms": round(serial_read_ms, 2),
        "parallel_read_ms": round(parallel_read_ms, 2),
        "read_speedup": round(serial_read_ms / parallel_read_ms, 2) if parallel_read_ms else None,
        "serial_edit_ms": round(serial_edit_ms, 2),
        "transaction_edit_ms": round(transaction_edit_ms, 2),
        "edit_speedup": round(serial_edit_ms / transaction_edit_ms, 2) if transaction_edit_ms else None,
        "transaction_rollback_ms": round(rollback_ms, 2),
        "workspace": str(workspace),
    }

    out_json = ROOT / "bench" / "fast_io_bench.json"
    out_json.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    print("=" * 60)
    print(f"文件读写极速化基准  (N={args.n}, 每文件 ~{args.size}KB)")
    print("-" * 60)
    print(f"读  串行 read_file x{args.n}: {result['serial_read_ms']:>9.1f} ms")
    print(f"读  并行 read_files      : {result['parallel_read_ms']:>9.1f} ms   "
          f"(加速 {result['read_speedup']}x)")
    print(f"写  串行 edit_file x{args.n}: {result['serial_edit_ms']:>9.1f} ms")
    print(f"写  事务 edit_files       : {result['transaction_edit_ms']:>9.1f} ms   "
          f"(加速 {result['edit_speedup']}x)")
    print(f"写  校验失败整体回滚      : {result['transaction_rollback_ms']:>9.1f} ms   (零落盘)")
    print("-" * 60)
    print(f"JSON 已写出: {out_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
