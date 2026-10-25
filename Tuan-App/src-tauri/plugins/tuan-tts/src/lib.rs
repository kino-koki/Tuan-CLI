//! tuan-tts：Android 系统原生 TTS 桥。
//!
//! 桌面端 TTS 由引擎内置 MOSS-TTS-Nano 承担（web /api/tts/*，完全本地）；
//! Android 无法安装 PyTorch，无法跑 MOSS，本插件把系统 TextToSpeech
//! 桥接为 Tauri 命令 tts_speak / tts_stop。
//!
//! 注意：本文件按 Tauri v2 官方插件模板书写，需在装有 Rust + Android SDK
//! 的环境编译验证（见 plugins/tuan-tts/README.md）。

use tauri::{plugin::Builder, Runtime};

#[cfg(mobile)]
mod mobile;

#[cfg(mobile)]
pub use mobile::*;

/// 注册本插件：`Builder::new("tuan-tts")` 注册命令，供 AppHandle.plugin() 调用。
pub fn init<R: Runtime>() -> tauri::plugin::TauriPlugin<R> {
    Builder::new("tuan-tts")
        .invoke_handler(tauri::generate_handler![speak, stop])
        .build()
}

/// 前端 invoke('tts_speak', { text, lang }) → Android 原生 TTS 朗读。
#[tauri::command]
fn speak<R: Runtime>(app: tauri::AppHandle<R>, text: String, lang: String) -> Result<(), String> {
    #[cfg(mobile)]
    {
        mobile::speak(app, text, lang)
    }
    #[cfg(not(mobile))]
    {
        Err("tuan-tts speak is only available on Android".into())
    }
}

/// 前端 invoke('tts_stop') → 停止当前朗读（可选命令，未接入时前端已兜底）。
#[tauri::command]
fn stop<R: Runtime>(app: tauri::AppHandle<R>) -> Result<(), String> {
    #[cfg(mobile)]
    {
        mobile::stop(app)
    }
    #[cfg(not(mobile))]
    {
        Err("tuan-tts stop is only available on Android".into())
    }
}
