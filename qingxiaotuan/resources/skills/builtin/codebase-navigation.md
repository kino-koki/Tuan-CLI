---
name: 代码库导航
description: 快速理解和导航陌生代码库的方法：入口追踪/依赖分析/模块拆解/热点定位
tags: [architecture, codebase, navigation, reading-code, understanding]
priority: 9
updated_at: 0
use_count: 0
---

# 代码库导航

> 理解代码库 = 知道"数据从哪来、到哪去、中间经过谁"。

## 快速摸清一个代码库

### Step 1: 找入口 (30 秒)

```bash
# 找 main 函数
grep -r "def main" --include="*.py" .
grep -r "entry_points" pyproject.toml

# 找 CLI 入口
grep -r "def cli\|def main\|if __name__" --include="*.py" .

# 找配置文件
ls *.toml *.yaml *.json .env* 2>/dev/null
```

### Step 2: 看目录结构 (1 分钟)

```
项目根/
├── src/ 或项目名/    # 核心代码
├── tests/            # 测试
├── docs/             # 文档
├── scripts/          # 脚本
└── 配置文件
```

每个子目录 = 一个模块/职责。看目录名就能猜功能。

### Step 3: 找核心数据流 (3 分钟)

```
1. 入口函数接收什么输入？
2. 输入经过哪些处理？
3. 最终产出什么输出？
4. 中间调用了哪些外部服务/数据库？
```

### Step 4: 找关键抽象 (5 分钟)

- **接口/协议**: `class XxxProtocol` / `ABC` / `Protocol`
- **注册表**: `registry` / `Registry` / `provider`
- **事件总线**: `emit` / `on` / `subscribe` / `handler`
- **工厂**: `create` / `build` / `factory`

## 常用搜索模式

```bash
# 找类定义
grep -r "^class " --include="*.py" .

# 找函数定义
grep -r "^def \|^    def " --include="*.py" .

# 找装饰器 (注册/钩子)
grep -r "@.*register\|@.*handler\|@.*hook" --include="*.py" .

# 找配置项
grep -r "config\.\|CONFIG\.\|get(" --include="*.py" . | head -20

# 找导入关系 (谁依赖谁)
grep -r "from.*import\|import " --include="*.py" file.py
```

## 理解模块职责

读一个模块时，先看：

1. **`__init__.py`** — 暴露了什么公共 API
2. **类/函数的 docstring** — 一句话说清职责
3. **类型注解** — 参数和返回值告诉你数据流
4. **异常处理** — 哪里会失败、怎么降级
5. **日志** — 关键决策点在哪

## 依赖分析

```bash
# 找谁调用了这个函数
grep -r "function_name" --include="*.py" .

# 找这个模块被谁导入
grep -r "from.*module_name import\|import module_name" --include="*.py" .

# 找循环依赖 (危险信号)
# 如果 A 导入 B，B 又导入 A，可能需要重构
```

## 代码异味 (快速识别)

| 信号 | 可能问题 |
|---|---|
| 文件超过 500 行 | 职责过多，需要拆分 |
| 函数超过 50 行 | 做了太多事，需要提取 |
| 嵌套超过 4 层 | 用 guard clause 提前返回 |
| 参数超过 5 个 | 用 dataclass/字典封装 |
| 重复代码 > 3 处 | 抽取公共函数 |
| `except Exception: pass` | 吞异常，隐藏 bug |

## 重构顺序

1. **先补测试** — 没有安全网就别动
2. **小步重构** — 每次只做一件事 (重命名 / 提取 / 消重复)
3. **每步验证** — 改完跑测试，红了立刻回退
4. **最后优化** — 结构清晰后再考虑性能
