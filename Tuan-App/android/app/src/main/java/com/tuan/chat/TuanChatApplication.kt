package com.tuan.chat

import android.app.Application

/**
 * Tuan-Chat Native Application.
 *
 * 单一 Application 类, 不做全局初始化 (MVP 阶段无 DI 容器)。
 * 后续如需注入 (Hilt/Koin), 在此实现 Application 接口即可。
 */
class TuanChatApplication : Application() {
    override fun onCreate() {
        super.onCreate()
    }
}
