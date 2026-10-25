# tuan-tts — Android 原生 TTS 桥（Rust 插件）

## 为什么需要它

**Android 无法安装 PyTorch**（无本地 Python 运行时、torch 不支持移动端），
因此 MOSS-TTS-Nano 完全本地合成在安卓上不可用。桌面端（Windows/macOS）
仍走引擎内置的 MOSS-TTS（`/api/tts/*`，完全本地、多音色、10 语言）。

安卓端的替代方案：**系统原生 TextToSpeech**（Google TTS / 各厂商 TTS 引擎），
同样完全离线、零 PyTorch 依赖。本插件把 `android.speech.tts.TextToSpeech`
桥接成 Tauri 命令 `tts_speak` / `tts_stop`，前端 `src/platform/tts.ts`
已在 Android 分支自动切换（原生桥 → speechSynthesis 兜底 → 静默失败）。

> 状态标注：本目录代码**未在本机编译验证**（本机无 Rust 工具链与 Android
> SDK/Gradle）。前端分发逻辑（tts.ts）已通过 `tsc` + `vite build` 全绿；
> 原生桥接入后即生效，接入前优雅降级，不会报错。

## 目录结构（接入后）

```
src-tauri/plugins/tuan-tts/
├── Cargo.toml            # 由 tauri 脚手架生成（见下）
├── src/
│   ├── lib.rs            # 命令注册 + init()
│   └── mobile.rs         # Android 侧：把命令转发给 Kotlin 插件
└── android/
    └── src/main/java/com/tuan/chat/tts/
        └── TuanTtsPlugin.kt   # Kotlin：调 android.speech.tts.TextToSpeech
```

## 接入步骤（在装有 Android 工具链的机器上执行一次）

```bash
cd src-tauri
# 1) 生成插件脚手架（crate + android 模块）
npx tauri plugin new tuan-tts
# 2) 把本目录 src/lib.rs、src/mobile.rs、TuanTtsPlugin.kt 的内容覆盖到脚手架对应位置
# 3) 在 src-tauri/src/lib.rs 注册插件：
#    mod tts;
#    ... .plugin(tts::init()) ...   # 在 Builder 链上追加
# 4) 在 src-tauri/tauri.conf.json 的 app.plugins 无特殊配置（命令级无权限要求）
# 5) 重新生成 android 工程并同步插件：
npx tauri android init
npx tauri plugin android add tuan-tts
# 6) 编译运行：
npx tauri android dev
```

## 能力边界（如实说明）

- 音色 = 系统 TTS 当前音色（Android 设置 → 文字转语音 中用户自己选的语音），
  Tuan-Chat 里的音色下拉在安卓端不生效（仅语言生效）。
- 10 语言映射：zh_CN/zh_TW/en/ja/ko/es/fr/de/pt_BR/ru →
  zh-CN/zh-TW/en-US/ja-JP/ko-KR/es-ES/fr-FR/de-DE/pt-BR/ru-RU。
- 引擎状态栏在安卓端显示「系统 TTS」。
