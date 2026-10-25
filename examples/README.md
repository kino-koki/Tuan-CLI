# Examples（示例集）

> 新手 10 分钟跑通路径：三个示例覆盖项目三大卖点——**安全拦截**、**生态互操作**、**离线自托管**。
> 全部示例**不需要 API Key、不需要网络**（示例 3 仅在接入 Ollama 后才有完整输出）。

| 示例 | 卖点 | 运行 | 前置条件 |
|---|---|---|---|
| [`safety_demo.py`](safety_demo.py) | 安全引擎四道闸门的第一道：静态评分 | `python examples/safety_demo.py` | 无 |
| [`ecosystem_scan.py`](ecosystem_scan.py) | 探测 Claude Code / Hermes 资产（只读） | `python examples/ecosystem_scan.py` | 无（未安装对方 CLI 属正常） |
| [`offline_ollama.py`](offline_ollama.py) | 完全离线 + 本地模型 | `python examples/offline_ollama.py` | 可选：Ollama / llama.cpp |

## 快速开始

```bash
# 1. 克隆仓库并安装（开发模式）
git clone <repo-url> && cd tuan-cli
python -m venv .venv && .venv\Scripts\activate
pip install -e ".[dev]"

# 2. 跑第一个示例（零依赖、零网络）
python examples/safety_demo.py

# 3. 跑通后回到主文档
tuan setup && tuan "你好，介绍一下自己"
```

## 示例 1：安全引擎演示（推荐最先跑）

`safety_demo.py` 直接调用内置安全引擎，对 6 条有代表性的命令做静态评分：

- `rm -rf /` → 硬红线，**永不自动执行**（YOLO 模式也拦）
- `git push --force` → 关键级，多阶段确认
- `curl | sh` → 高危，给出安全替代建议
- 良性开发命令 → `none`，**零确认零打扰**

预期看到命中原因（pattern label）与影响面（blast radius）。想复现完整基准：

```bash
tuan safe bench          # 约 4 分钟，全量 10k + 5k + 2497 绕过矩阵 + 6k 真实使用
tuan safe bench --quick  # 约 30 秒快速自检
tuan safe report         # 生成可分享的 HTML 安全报告
```

## 示例 2：生态互操作探测（只读）

`ecosystem_scan.py` 调用 `tuan ecosystem scan`，探测本机 Claude Code / Hermes
已积累的技能、命名 Agent、记忆、SOUL 与 MCP 配置——**不重复造生态，直接复用**。
探测本身只读；双向搬运命令见脚本输出。

## 示例 3：离线模型

`offline_ollama.py` 调用 `tuan models local` 探测本机 Ollama / llama.cpp。
接入后：

```bash
tuan models set ollama qwen2.5:7b   # 选择本地模型
tuan                                # 完全离线对话
```

## 贡献

新增示例请遵循：可复现（不依赖网络/密钥，依赖则标注前置条件）、输出自解释、
代码有中文注释。示例本身也是 `docs/GOOD_FIRST_ISSUES.md` 的维护对象之一。
