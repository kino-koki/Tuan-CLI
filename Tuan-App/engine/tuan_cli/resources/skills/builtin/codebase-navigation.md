---
name: 代码库导航
description: 快速理解和导航陌生代码库的方法：入口追踪/依赖分析/模块拆解/热点定位
activation: auto
triggers: 代码库, codebase, 导航, 理解代码, 阅读代码
provides: codebase-navigation
suggests: code-architect, tuan-code
priority: 78
tags: [architecture, codebase, navigation, reading-code, understanding]
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

## 快速上手陌生代码库（实战方法论）

> 以下内容源自原 `architecture-reading` 技能，已合并至本技能。

别从 main 第一行开始读，那是蜗牛路线。先建地图，再钻脉络。

### 1. 看全貌（30 秒）
- `codebase_map`：目录结构 + 各语言规模 + 关键文件入口。
- 读 README / 文档 / 入口文件，搞清楚「这东西是干嘛的、谁在用」。

### 2. 找主脉络（5 分钟）
- 入口在哪？请求/数据从哪进、到哪出？（Web 看路由，CLI 看 main/argparse，库看 public API）
- 顺一条最典型的调用链走一遍：A 调 B 调 C，画在脑里。一条链通，全库通一半。

### 3. 抓关键抽象
- 找核心数据结构/领域模型（名字常是 User/Order/Node/Engine 这类）。
- 找横切关注点：配置、日志、错误、IO 封装在哪。

### 4. 用工具别用眼睛
- `find_symbol` 定位定义，`find_references` 看谁依赖它——改之前先摸清影响面。
- `git_status` / `git log` 看近期在动哪、为什么动（commit message 是免费的决策记录）。

### 5. 安全下手
- 改前先跑一次 `run_tests` 建立基线（红的是本来就红，不是你弄的）。
- 小步改、小步验证；每动一个公共符号，`find_references` 复查调用方。
- 有歧义先问，别替作者猜意图——README 和注释没说的，可能藏在某个历史 issue 里。
