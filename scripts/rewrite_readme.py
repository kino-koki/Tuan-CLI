"""README.md 品牌重写: Claude Code 引擎叙事 -> 青小团引擎 + Tuan-Chat。"""

from __future__ import annotations

from pathlib import Path

P = Path(r"E:\Qingxiaotuan Agent CLI\claude-desktop-app\README.md")
text = P.read_text(encoding="utf-8")

REPL = [
    ("# Claude Desktop App", "# Tuan-Chat"),
    ("**把 Claude Code 的开源引擎套上 claude.ai 的前端——一个能接任意 API 的桌面版 Claude。**",
     "**基于青小团（Qingxiaotuan）纯 Python 引擎的桌面 AI 助手——Tuan-Chat。**"),
    ("手头有 Claude 中转站 API？想像 claude.ai 网页版那样跟 Claude 聊天，不想折腾纯净外卡 / 外号 / 住宅 IP？这个项目就是为你准备的。",
     "Tuan-Chat 是一个桌面版 AI 助手：对话体验友好，同时保留完整 agent 能力（读写文件、跑命令、网页搜索、Skills、Projects）。底层是青小团引擎——纯 Python 实现，模型无关，可接任意兼容 API。"),
    ('<img src="public/favicon.png" alt="Claude Desktop App" width="100" />',
     '<img src="public/favicon.png" alt="Tuan-Chat" width="100" />'),
    ("Claude Code 本身强得离谱，但只能在命令行里当\"打工人\"用——它的系统提示词是为编程任务写的，不适合当成日常对话助手。",
     "命令行 agent 工具能力强大，但只能在终端里当\"打工人\"用——系统提示词为编程任务设计，不适合日常对话助手场景。"),
    ("claude.ai 网页版体验顶级，但国内用户几乎用不了：注册要纯净国外信用卡、纯净国外手机号、住宅 IP，缺一个就封号。",
     "大型模型的网页版体验顶级，但许多用户访问成本高、稳定性差，也难把 agent 能力（工具调用、上下文管理）搬到聊天界面里。"),
    ("所以大部分国内程序员的状况是：手里有 Claude 中转站 API → 只能在 Claude Code CLI 里编程用 → 想聊天只能退回 Gemini / GPT → 体验差 Claude 一截。",
     "大部分开发者的状况是：手里有各种模型 API → 只能在 CLI 里编程用 → 想聊天只能退回网页版 → 聊天体验与 agent 能力无法兼得。"),
    ("**这个项目把 Claude Code 的开源引擎套上了 claude.ai 几乎一模一样的前端**。结果就是：",
     "**Tuan-Chat 把青小团引擎的完整 agent 能力，搬进了日常对话体验**。结果就是："),
    ("- 拿你手里的中转站 API，像 claude.ai 一样跟 Claude 聊天\n- 同时拥有 Claude Code 原生的全部 agent 能力（读写文件、跑命令、上下文管理、网页搜索、Skills、Projects 等）\n- 不要外卡、不要外号、不要住宅 IP、不怕封号",
     "- 拿你手里的任意模型 API（DeepSeek、Qwen、GLM、GPT、中转站等），直接在桌面端聊天\n- 同时拥有青小团引擎的全部 agent 能力（读写文件、跑命令、上下文管理、网页搜索、Skills、Projects 等）\n- 纯 Python 引擎，本地运行，数据自己掌控"),
    ("- 🎨 **界面 1:1 还原 claude.ai**——深色模式、流式输出、thinking 块折叠、工具卡片、Artifacts 面板、Projects 知识库，基本体验跟官方完全对齐",
     "- 🎨 **桌面级对话体验**——深色模式、流式输出、thinking 块折叠、工具卡片、Artifacts 面板、Projects 知识库"),
    ("- 🔌 **任意模型接入**——内置 Anthropic ↔ OpenAI 格式双向代理，能接 Claude 中转站、Qwen、DeepSeek、GLM、GPT、Gemini，只要对方兼容 OpenAI 或 Anthropic 格式",
     "- 🔌 **任意模型接入**——内置 OpenAI ↔ Anthropic 格式双向代理，能接 DeepSeek、Qwen、GLM、GPT、中转站，只要对方兼容 OpenAI 或 Anthropic 格式"),
    ("- 🛠️ **完整 agent 能力**——读写文件、执行命令、网页搜索、多轮工具调用、上下文压缩，全套 Claude Code 原生工具",
     "- 🛠️ **完整 agent 能力**——读写文件、执行命令、网页搜索、多轮工具调用、上下文压缩，全部由青小团 Python 引擎提供"),
    ("- 🧠 **Claude 原生对话风格**——保留了 claude.ai 的说话节奏和深度，不是 Claude Code 的\"干练打工人\"腔调",
     "- 🧠 **对话与工程兼备**——聊天风格的回应与果断的工程执行，青小团引擎系统提示词原生支持"),
    ("- 消息编辑 / 重新生成 / 上下文回退（基于 Claude Code 原生 `--resume-session-at`）",
     "- 消息编辑 / 重新生成 / 上下文回退（基于引擎原生 `--resume-session-at`）"),
    ("│ Claude Code 引擎        │\n│ (engine/, Bun 运行)     │",
     "│ 青小团引擎              │\n│ (Python, stream-json)   │"),
    ("(Claude / Qwen / GPT ...)", "(DeepSeek / Qwen / GPT ...)"),
    ("| 引擎 | Claude Code（TypeScript，Bun 运行） |",
     "| 引擎 | 青小团（纯 Python） |"),
    ("**依赖**：[Node.js 20+](https://nodejs.org)、[Bun](https://bun.sh)（Windows 上 Claude Code 引擎还需要 [Git Bash](https://git-scm.com/downloads)）",
     "**依赖**：[Node.js 20+](https://nodejs.org)、Python 3.10+（Windows 下如需 Git Bash 相关工具请自行安装）"),
    ("- 改 `engine/src/` 源码不用 rebuild，下次 spawn 引擎时自动生效",
     "- 改青小团引擎源码不用 rebuild，下次 spawn 引擎时自动生效"),
]

for old, new in REPL:
    if old in text:
        text = text.replace(old, new)
    else:
        print(f"WARN 未命中: {old[:50]!r}")

P.write_text(text, encoding="utf-8")
print("README 品牌重写完成")
