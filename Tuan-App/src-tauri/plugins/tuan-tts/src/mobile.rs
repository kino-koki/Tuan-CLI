//! Android 侧实现：把 tts_speak / tts_stop 转发给 Kotlin 插件。

use tauri::plugin::PluginHandle;
use tauri::Runtime;

/// 请求 Kotlin 侧朗读文本。返回 Ok 表示命令已派发（异步朗读）。
pub fn speak<R: Runtime>(app: tauri::AppHandle<R>, text: String, lang: String) -> Result<(), String> {
    let plugin: PluginHandle<R> = app.plugin("tuan-tts").map_err(|e| e.to_string())?;
    plugin
        .invoke(
            "speak",
            { "text": text, "lang": lang },
            |_| Ok(()),
        )
        .map_err(|e| e.to_string())
}

/// 请求 Kotlin 侧停止朗读。
pub fn stop<R: Runtime>(app: tauri::AppHandle<R>) -> Result<(), String> {
    let plugin: PluginHandle<R> = app.plugin("tuan-tts").map_err(|e| e.to_string())?;
    plugin.invoke("stop", {}, |_| Ok(())).map_err(|e| e.to_string())
}
