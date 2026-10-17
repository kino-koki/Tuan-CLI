---
name: 精确代码编辑
description: 用 edit_file 做精准外科手术式编辑，而非重写整个文件。覆盖替换/插入/删除/重命名的实战技法
tags: [code-editing, precise-edit, refactor, modify]
priority: 10
updated_at: 0
use_count: 0
---

# 精确代码编辑

Claude Code 级别的代码编辑 = 精准定位 + 最小改动 + 验证闭环。

## 核心原则

**只动该动的，不动不该动的。** 一次编辑只解决一个问题。

## 编辑策略

### 1. 替换 (最常用)

用 `edit_file` 的 old_string/new_string 做精确替换：
- old_string 必须是文件中**唯一**出现的字符串（含缩进和换行）
- 如果匹配到多处，缩小 old_string 范围（多包含上下文）
- 不要在 new_string 里"顺便"改别的东西

```
# ✅ 正确: 精确匹配一个函数
edit_file("path/to/file.py",
    old_string="def process(data):\n    return data * 2",
    new_string="def process(data: List[str]) -> List[str]:\n    return [d * 2 for d in data]")

# ❌ 错误: 一次改太多，review 看不出改了啥
edit_file("path/to/file.py",
    old_string="整个文件内容...",
    new_string="重写后的内容...")
```

### 2. 插入 (在指定位置添加代码)

```
edit_file("path/to/file.py",
    old_string="def existing_func():\n    pass",
    new_string="def existing_func():\n    # 新增: 参数校验\n    if not data:\n        raise ValueError('data cannot be empty')\n    pass")
```

### 3. 删除 (移除代码块)

```
edit_file("path/to/file.py",
    old_string="# TODO: 这段代码已经不需要了\n    legacy_function()\n    ",
    new_string="")
```

### 4. 重命名 (全局替换)

先用 `find_references` 搜索所有引用，再逐个替换：
```
# 1. 搜索
find_references("old_name", file_pattern="*.py")
# 2. 逐文件替换 (注意: 每个文件只替换该文件中的引用)
```

## 编辑前检查清单

- [ ] 读过目标文件，理解上下文
- [ ] old_string 在文件中**唯一**匹配
- [ ] new_string 保持了原有的缩进风格
- [ ] 没有"顺手"改别的东西
- [ ] 改完后 `run_tests` 验证

## 常见陷阱

1. **缩进不一致**: Python 文件中 tabs vs spaces 混用，old_string 的缩进必须与文件一致
2. **行尾空格**: 复制粘贴可能带入不可见的尾部空格
3. **编码问题**: 文件可能是 UTF-8 with BOM，edit_file 会保持原编码
4. **大文件编辑**: 超过 500 行的文件，优先用 grep/find 定位再精确编辑，不要读整个文件

## 与 Claude Code 对标

| Claude Code | 青小团 | 说明 |
|---|---|---|
| `Edit` tool | `edit_file` | 精确替换 |
| `Write` tool | `write_file` | 创建/覆盖文件 |
| `Read` tool | `read_file` | 读取文件 (带行号) |
| `MultiEdit` | 多次 `edit_file` | 同一文件多次编辑 |

核心差异: Claude Code 的 Edit 要求 old_string 唯一匹配，青小团的 edit_file 同理。**这是防止误改的安全机制。**
