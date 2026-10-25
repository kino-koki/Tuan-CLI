# Tuan 桌面端更新日志

## 版本策略 (Version Policy)
- **一月一大更新**: 主版本号 `+0.1` (如 0.3.x → 0.4.0), 承载新模块/架构级改动。
- **每周一小更新**: 补丁号 `+0.0.1` (如 0.3.1 → 0.3.2), 承载修复/小功能/依赖治理。

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
