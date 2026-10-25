package com.tuan.chat.tts

import android.app.Activity
import android.speech.tts.TextToSpeech
import android.speech.tts.UtteranceProgressListener
import app.tauri.plugin.InvokeRequest
import app.tauri.plugin.InvokeResponseCallback
import app.tauri.plugin.JSObject
import app.tauri.plugin.Plugin
import app.tauri.plugin.PluginHandle
import java.util.Locale
import java.util.concurrent.CountDownLatch

/**
 * Android 系统原生 TTS 桥（无 PyTorch 的本地语音方案）。
 *
 * 命令：
 *  - speak(text, lang)  朗读文本，lang 形如 "zh-CN" / "en-US" / "ja-JP"
 *  - stop()             停止当前朗读
 */
class TuanTtsPlugin(private val activity: Activity) : Plugin(activity) {

    private var tts: TextToSpeech? = null
    private val ready = CountDownLatch(1)

    init {
        tts = TextToSpeech(activity.applicationContext) { status ->
            if (status == TextToSpeech.SUCCESS) ready.countDown()
        }
    }

    override fun call(
        plugin: PluginHandle,
        method: String,
        request: InvokeRequest,
        callback: InvokeResponseCallback
    ) {
        when (method) {
            "speak" -> {
                val text = request.getString("text")?.trim()
                val lang = request.getString("lang") ?: "zh-CN"
                if (text.isNullOrEmpty()) {
                    callback.invoke(JSObject().put("ok", false).put("error", "empty text"))
                    return
                }
                val engine = tts
                if (engine == null) {
                    callback.invoke(JSObject().put("ok", false).put("error", "tts not initialized"))
                    return
                }
                val locale = parseLocale(lang)
                try {
                    ready.await() // 等引擎就绪（最多约 200ms~1s）
                    engine.language = locale
                    engine.speak(text, TextToSpeech.QUEUE_FLUSH, null, "tuan-tts-" + System.nanoTime())
                    callback.invoke(JSObject().put("ok", true))
                } catch (e: Exception) {
                    callback.invoke(JSObject().put("ok", false).put("error", e.message ?: e.toString()))
                }
            }
            "stop" -> {
                tts?.stop()
                callback.invoke(JSObject().put("ok", true))
            }
            else -> callback.invoke(JSObject().put("ok", false).put("error", "unknown method: $method"))
        }
    }

    private fun parseLocale(lang: String): Locale {
        val parts = lang.split("-")
        return if (parts.size >= 2) {
            Locale(parts[0], parts[1].uppercase())
        } else {
            Locale(lang)
        }
    }

    override fun onDestroy() {
        tts?.shutdown()
        tts = null
        super.onDestroy()
    }
}
