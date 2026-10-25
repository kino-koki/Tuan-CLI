# Tuan 桌面端更新日志

## 版本策略 (Version Policy)
- **一月一大更新**: 主版本号 `+0.1` (如 0.3.x → 0.4.0), 承载新模块/架构级改动。
- **每周一小更新**: 补丁号 `+0.0.1` (如 0.3.1 → 0.3.2), 承载修复/小功能/依赖治理。

## [0.3.4] - 2026-10-25 (小更新 · UI/UX 完全对齐 Claude Code 桌面端)

### UI/UX: 色板完全对齐 Claude 官方
- **浅色主题** → Claude.ai 暖奶油系: 主底 `#f4f1ea`、侧栏 `#ece8df`、边框 `#e0dcd2`、
  正文 `#37352f`、输入/浮层 `#fbf9f4`; 品牌橙回归官方陶土橘 `#d97757` (hover `#b0522f`)。
- **深色主题** → Claude Code 终端暖炭: 主底 `#201f1c`、侧栏 `#1a1917`、hover/输入 `#2b2826`;
  品牌橙深色档提亮 `#e5987c` (hover `#eda184`), 与固定深炭状态栏 (`#201f1c`) 形成一体。
- 终端/代码块底色统一 `#1f1e1c`; 圆角全面收敛到 Claude 小圆角规范
  (输入卡 22→14px、卡片 16→12px、原生控件 10→8px)。

### UI/UX: 消息形态对齐 Claude
- 助手回复 `.reply-card` 去卡片化: 透明无边框, 文字直接排入消息流
  (Claude Code "终端输出"质感; 代码块/表格/引用仍保留自己的色块)。
- 用户消息气泡圆角 2xl→xl, 思考中提示 chip 同步小圆角。
- 全站组件硬编码色清零 (SettingsPage logo 块/checkbox 改 token 引用);
  TTS 状态圆点保留 Claude 官方色板 (绿 `#4c9a6e` / 琥珀 `#e0896a` / 红 `#f08a7d`)。

## [0.3.3] - 2026-10-25 (小更新 · UI/UX 专项)

### UI/UX: OpenHarmony 开源字体
- 全站字体切换为 **HarmonyOS Sans SC** (OpenHarmony 官方开源字体, Apache-2.0 免费商用):
  本地自托管 woff2 三字重 (Regular/Medium/Bold, @font-face 100–900), 断网可用, 不引任何外链;
  许可见 `public/fonts/LICENSE_Fonts.txt`。

### UI/UX: 内置 Agent 浏览器 (轻量开源方案)
- 侧栏新增「浏览器」入口 (资源组) + 全新 BrowsePage:
  多标签页、地址栏快捷搜索 (空格即 Bing 搜索)、前进/后退/刷新、书签/最近浏览/历史全部本地存储;
- **阅读模式**: iframe 被 X-Frame-Options 拒绝的站点, 一键切「阅读」由本地引擎抓取正文,
  可**复制为 Markdown** 或发到对话 (为 Agent 使用设计, 非完整浏览器);
- 引擎新增 `/api/fetch` 代理端点 (纯标准库 urllib + HTMLParser 正文提取, 零新增依赖,
  2MB/12s 上限, 仅 http/https 防 SSRF)。

### UI/UX: 深浅色与风格
- 全站深浅色巡检: 新增组件全部复用 `:root/.dark` token, 切换主题零硬编码色;
  终端/代码块/状态栏保留 Claude Code 官方固定深炭语义 (不随主题反转)。
- TUI 清理: 删除并行遗留的 Ctrl+↑/↓ 重复绑定 (恢复 ↑/↓ 历史 + Shift+PgUp/PgDn 回卷)。

## [0.3.2] - 2026-10-25 (小更新)

### 新增: 4 个独有模块 (多数 Agent 尚无对应物)
- **隐私文件防护罩 (Privacy Shield)** — 引擎 `ext/privacy_shield.py`: 读文件前拦截
  `.tuanignore`/内置规则命中的隐私文件 (`.env`、密钥、`*待办*`、日志等), 返回
  `[隐私屏蔽]`, 内容不进模型上下文; 与 `.gitignore` 防提交双保险。
- **Slash 宏 (Slash Macros)** — 引擎 `cli/cmd_slash_mac.py`: `/mac add <名> <命令1>;<命令2>`
  把高频命令序列存成宏, `/mac run <名>` 一键执行; 用户级 + 项目级双存储。
- **上下文预算仪表 (Context Budget Gauge)** — 前端 `platform/context.ts` + 状态栏:
  `ctx N%` 细进度条实时显示当前会话 token 占用 (est.), ≥70% 橙 / ≥90% 红 / 溢出提示,
  提醒 `/compact`。
- **语音协警 (Voice Copilot)** — 前端 `platform/voiceCopilot.ts`: 授权/完成/出错时
  本地 TTS 播报短提示, 防抖防吵, 设置页可开关。

### TUI 完善
- 删除 Ctrl+↑/↓ (反人类操作); ↑/↓ 直接翻上下文历史 (Claude Code 同款),
  斜杠面板打开时游走命令菜单; 回卷保留 Shift+PgUp/PgDn + 滚轮。

### 依赖精简 (-78% ≈ 80%)
- 引擎外部核心依赖 9 → 2 项 (`rich` + `prompt_toolkit`; `tomli` 仅 py<3.11 条件);
  httpx/openai/typing_extensions 0 引用移除, pyyaml→`_yaml.py`,
  pydantic→`_config_model.py`, cryptography→`crypto_engine.py` 纯 Python fallback。

### 配置 / 隐私
- `.gitignore` 新增隐私段, 防开发中/隐私文件 (代办等) 上传;
- 新增 `.tuanignore` 运行时规则 (引擎 Privacy Shield 联动);
- 核查: 两仓库均无待办/隐私文件入库。

### 人体工学 (承接 0.3.1)
- 侧栏折叠偏好持久化 (⌘B / 侧栏按钮写入 localStorage, 跨会话保持)。

## [0.3.1] - 2026-10-23
- 引擎整体替换为最新 Tuan-CLI 根版 (镜像 + 修剪定制 + 深度融入), 保留本地 TTS 专属模块;
- 目录改名 Tuan-App → Tuan, 全局旧名称统一; 独立 git 仓库;
- 本地 MOSS-TTS-Nano 语音播报 (14 官方音色 + 专属音色注册 + 10 语言)。
