---
name: 性能优化
description: 性能分析与优化的系统化方法：度量→定位→优化→验证，避免过早优化
tags: [performance, optimization, profiling, memory, speed]
priority: 8
updated_at: 0
use_count: 0
---

# 性能优化

> "过早优化是万恶之源" —— Knuth
> 但"完全不优化"是懒惰的借口。先度量，再优化。

## 三步法

### Step 1: 度量 (先有数据)

```bash
# Python: cProfile 瓶颈分析
python -m cProfile -s cumulative script.py

# Python: line_profiler 逐行分析
kernprof -l -v script.py

# Python: memory_profiler 内存分析
python -m memory_profiler script.py

# 通用: timeit 微基准
python -m timeit "sum(range(1000000))"
```

### Step 2: 定位 (找热点)

性能问题通常集中在 20% 的代码里：

| 类型 | 常见原因 | 排查工具 |
|---|---|---|
| CPU 密集 | 循环嵌套、重复计算、正则回溯 | cProfile, line_profiler |
| I/O 密集 | 串行网络请求、同步文件读写 | strace, lsof |
| 内存 | 大对象未释放、循环引用、缓存无限增长 | memory_profiler, tracemalloc |
| 启动慢 | 导入大量模块、初始化重型资源 | python -X importtime |

### Step 3: 优化 (对症下药)

#### CPU 优化
- **缓存**: `functools.lru_cache` 缓存纯函数结果
- **向量化**: NumPy/Pandas 替代纯 Python 循环
- **算法**: O(n²) → O(n log n) 通常比微优化有效 100 倍
- **并行**: `concurrent.futures` / `asyncio` 处理 I/O 密集任务

#### 内存优化
- **生成器**: `yield` 替代 `return list`，惰性计算
- **`__slots__`**: 大量实例的类用 `__slots__` 省内存
- **弱引用**: `weakref` 避免循环引用
- **流式处理**: 大文件逐行读，不要 `readlines()`

#### I/O 优化
- **连接池**: `httpx.Client` / `aiohttp.ClientSession` 复用连接
- **批处理**: 数据库批量 INSERT 替代逐条插入
- **异步**: `asyncio.gather()` 并发多个独立 I/O 操作
- **缓存层**: Redis/本地缓存减少重复查询

## 验证闭环

优化后必须验证：
1. **性能**: 同样的基准测试，确认提升
2. **正确性**: `run_tests` 全绿，没有引入回归
3. **可读性**: 优化后的代码仍然可理解，加注释说明为什么这样写

## 反模式

- ❌ 不度量就优化（凭感觉改）
- ❌ 优化了不可测量的差异（<5% 提升不值得改）
- ❌ 优化后不跑测试（引入 bug 得不偿失）
- ❌ 过度优化（牺牲可读性换取微小性能提升）
