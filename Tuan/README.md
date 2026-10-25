# Tuan（Tauri 重建版）

保留原界面视觉设计，实现从零重写的 Tauri + React + TypeScript 客户端；底层对接 Tuan-CLI（`tuan_cli`）引擎。旧套壳实现不复制、不残留。

## 目录
- `src/`：React/TS 前端（设计令牌见 `src/index.css`、`tailwind.config.js`）
- `engine/tuan_cli/`：随包携带的最新 Tuan-CLI 引擎源码（0.3.1）
- `src-tauri/`：Rust/Tauri 壳
  - `src/engine.rs`：tuan_cli 解释器定位、启动、限时就绪等待（崩溃/提前关闭立即报错，杜绝“永久超时”）
  - `src/store.rs`：供应商配置 JSON 持久化
  - Android 路径以 `#[cfg(target_os = "android")]` 预留，代码级支持，设备联调单独进行

## 已实现
- 侧边栏导航、新对话、聊天流（OpenAI 兼容 SSE）、模型/供应商选择
- 设置：供应商增删改、API 格式切换（OpenAI 兼容 / Anthropic）、获取模型、密钥显隐
- 聊天列表（搜索/重命名/删除）、项目空间（创建/删除）、个性化（技能/连接器标签页）、成品空态
- 中文界面，自有代码无 Claude/套壳品牌残留，仅保留 Anthropic 协议格式这一接口类型

## 本机构建环境（Windows GNU 工具链）
本机缺 Windows SDK（MSVC 无法链接），已改用 MinGW GCC（`D:\ucrt64\bin`）+ Rust gnu 工具链：
```powershell
$env:Path = 'D:\ucrt64\bin;' + $env:Path
$env:RUSTUP_TOOLCHAIN = 'stable-x86_64-pc-windows-gnu'
npm install
npm run build
cd src-tauri; cargo build --release
```

## 产物
- 便携版：`release/Tuan.exe`（同目录需保留 `WebView2Loader.dll`；目标机需有 WebView2 运行时，Win10/11 通常自带）
- NSIS 安装包：本机无法从 GitHub 下载 nsis-3.13.zip（连接被拒），在可访问 GitHub 的环境执行
  `npx tauri build --bundles nsis` 即可产出安装器。

## Android（代码级支持，待设备联调）
本机无 JDK / Android SDK，未出包。代码已预留 android 分支；装好 SDK/JDK 后：
```
npx tauri android init
npx tauri android build
```
设备端本地引擎适配在 `engine.rs` 的 android 分支补齐。

## API 格式
设置中支持 `OpenAI 兼容` 与 `Anthropic` 两种格式（仅协议接口类型）。

## 后续迭代（全功能对齐）
连接器目录与授权、技能编写/导入、研究编排、成品运行时面板、对话附件与代码执行等模块按同一设计继续补齐。
