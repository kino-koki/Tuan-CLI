# 青小团 QXT — VS Code 扩展

> 把 [青小团 Agent CLI](https://github.com/your-org/qingxiaotuan) 接进 VS Code：在侧边栏里和 Agent 对话、看它流式输出、观察它调用工具、批准它做危险操作。

![badge](https://img.shields.io/badge/license-MIT-green)
![vscode](https://img.shields.io/badge/vscode-%5E1.80.0-blue)
![node](https://img.shields.io/badge/node-%3E%3D22-brightgreen)

---

## 1. 功能介绍

| 模块 | 说明 |
| --- | --- |
| 侧边栏 Agent 对话 | 深色主题 Webview，顶部模型/会话条，中间消息流，底部输入框。用户消息右对齐浅色气泡，Agent 消息左对齐深色卡片。 |
| 流式输出 | Agent 文本以打字机效果逐字显示；思考过程（`agent_thought_chunk`）折叠在灰色块里，点击展开。 |
| 工具调用卡片 | Agent 消息内联工具调用卡片，可折叠；显示工具名 + 参数摘要 + 状态图标（⏳ 运行中 / ✅ 完成 / ❌ 失败）+ 耗时；展开看完整参数与结果。 |
| 行内 diff 预览 | 代码编辑类工具（`edit_file` / `write_to_file` / `str_replace_based_edit_tool` 等）完成后，在对应编辑器里加绿色高亮装饰。 |
| 权限确认 | 危险操作弹出 VS Code 模态框（同时 Webview 内也有按钮）：**Approve Once / Approve Always / Deny**。 |
| MCP 状态面板 | 侧边栏底部树视图，列出从 `initialize.tools` 聚合出的 MCP server 与工具数。 |
| 工具调用历史 | 第二个树视图，最近 50 条工具调用，展开看参数/结果/错误。 |

## 2. 设计参考（Claude Code / Qoder）

本扩展的视觉与交互刻意对齐两款业界标杆产品：

- **配色**：深色底（`#1e1e1e` / `#252526`），强调色用青小团品牌青绿 `#00d4aa` / `#4ec9b0`，**避免 heavy indigo / purple**。
- **布局**：参考 Claude Code 侧边栏——顶部窄条放模型名，中间滚动消息流，底部固定输入区；消息气泡左右对齐区分角色。
- **工具卡片**：参考 Qoder——工具调用以"内联小卡片"嵌入 Agent 消息流，默认折叠只显示 `工具名 + 参数摘要 + 状态图标`，展开才看完整 payload；状态用图标而不是文字，节省纵向空间。
- **diff 预览**：参考 Claude Code 的 inline diff——编辑类工具完成后，直接在原编辑器里用绿/红行背景高亮，而不是强制打开双栏 diff。
- **权限**：参考 Claude Code 的权限三按钮——`Approve / Approve Always / Deny`，危险操作不静默放行。
- **流式**：打字机效果 + 末尾光标 `▍`；思考块折叠，避免长推理打断阅读主线。

## 3. 目录结构

```
ide/vscode/
├── package.json           # VS Code 扩展清单（contributes / commands / configuration）
├── tsconfig.json          # strict, ES2022, commonjs
├── .gitignore
├── media/
│   └── icon.svg           # Activity Bar 图标
├── src/
│   ├── extension.ts        # 入口：注册视图、命令、启停 ACP 子进程
│   ├── types.ts            # ACP 消息类型定义（与 qingxiaotuan/acp/protocol.py 对齐）
│   ├── acpClient.ts        # spawn `qxt acp`，NDJSON-RPC 读写，事件分发
│   ├── chatProvider.ts     # 聊天流数据模型：消息列表、流式 delta 累积、工具调用状态
│   ├── sidebarPanel.ts     # WebviewViewProvider：渲染对话流（内联 HTML/CSS/JS）
│   ├── diffPreview.ts      # TextEditorDecorationType：行内 diff 装饰
│   ├── toolCallView.ts     # 工具调用历史 TreeDataProvider
│   ├── permissionDialog.ts # 权限确认模态框
│   └── mcpStatus.ts        # MCP 服务器状态 TreeDataProvider
└── README.md
```

## 4. ACP 通信架构

扩展本身**不实现任何 Agent 逻辑**，所有智能都在 `qxt acp` 子进程里。通信是 stdio 上的 NDJSON-JSON-RPC：

```
┌─────────────────────────┐         stdin (JSON-RPC 请求)        ┌──────────────────────────┐
│  VS Code Extension      │  ───────────────────────────────────▶ │  qxt acp 子进程 (Python)  │
│  (TypeScript, 本工程)  │                                       │  qingxiaotuan/acp/server  │
│                         │  ◀─────────────────────────────────── │                          │
│  - AcpClient            │         stdout (NDJSON 通知)         │  - Agent 业务循环          │
│  - ChatProvider         │   session/update, task/update        │  - 工具执行                │
│  - SidebarPanel (Web)   │                                       │  - 权限握手                │
└─────────────────────────┘                                       └──────────────────────────┘
```

**方法（扩展 → 子进程）**：`initialize` / `prompt` / `update` / `cancel` / `shutdown`。
**通知（子进程 → 扩展）**：
- `session/update`：`initialized`、`available_commands_update`、`agent_message_chunk`（流式文本）、`agent_thought_chunk`（推理）、`tool_call`、`tool_call_update`、`permission_request`、`permission_update`。
- `task/update`：`running` / `completed` / `failed`。
**权限回执**：扩展收到 `permission_request` 后，回 `update`（`type=permission_response, decision=approve_once|approve_always|reject`）。

## 5. 安装与构建

前置：Node.js ≥ 22（开发环境已验证 v22.23.2 / npm 10.9.8），且 `qxt` 已在 PATH 中（或在 VS Code 设置里改 `qingxiaotuan.command`）。

```powershell
cd "E:\Qingxiaotuan Agent CLI\ide\vscode"
npm install
npx tsc --noEmit        # 类型检查，零错误即通过
npx tsc                 # 编译到 out/
```

打包成 `.vsix`：

```powershell
npx @vscode/vsce package
# 产物：qingxiaotuan-vscode-<version>.vsix
```

> 如果 `vsce package` 因为网络（拉 marketplace metadata）失败，至少 `npx tsc --noEmit` 通过即可视为开发就绪；打包可在联网环境重试，或直接用 `Extension Development Host`（F5）调试。

在 VS Code 里安装：
```powershell
code --install-extension qingxiaotuan-vscode-0.2.017.vsix
```

## 6. 使用说明

1. 在 VS Code 里打开你的项目根目录（工作区根目录会作为 Agent 的 cwd）。
2. 左侧 Activity Bar 点青小团图标，打开侧边栏。
3. 第一次激活会自动 `qxt acp`；看到顶部出现模型名即连接成功。
4. 在底部输入框输入任务，`Enter` 发送，`Shift+Enter` 换行。
5. Agent 跑起来后：
   - 流式文本逐字出现；
   - 工具调用以内联卡片展示，点卡片头展开参数/结果；
   - 遇到危险操作会弹模态框，选 Approve / Deny。
6. 顶部工具栏图标：`+` 新建对话、`■` 取消当前任务、`⟳` 重启会话。

## 7. 设置项

| 配置 | 默认 | 说明 |
| --- | --- | --- |
| `qingxiaotuan.command` | `qxt` | 启动 ACP 的可执行文件；PATH 里没有就填绝对路径或 `python`。 |
| `qingxiaotuan.args` | `["acp"]` | 启动参数。 |
| `qingxiaotuan.cwd` | （空） | Agent 工作目录；留空用 workspace 根。 |
| `qingxiaotuan.enableInlineDiff` | `true` | 是否在编辑器里显示行内 diff 装饰。 |
| `qingxiaotuan.approveAlways` | `false` | 实验性：自动批准所有工具（不推荐）。 |

## 8. 已知限制 / Roadmap

- 当前 ACP 上报的工具参数/结果是截断后的纯文本，行内 diff 只能做"文件级高亮"占位；等服务端推结构化 edit 事件后升级为真正的 unified diff。
- MCP 状态依赖 `initialize.tools[].source` 字段；旧版 server 没带时全部归到 `qxt builtin`。
- 重启会话目前通过"Reload Window"实现；后续改为原地 respawn 子进程。

## 9. License

MIT，与主项目一致。
