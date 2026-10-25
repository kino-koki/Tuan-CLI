# Tuan Native Android

手机远程调度桌面 Agent-of-Agents 的 Android 原生客户端。

## 架构

详见 `E:\Tuan-CLI\docs\TUAN-CHAT-NATIVE-ARCHITECTURE.md` 与 `TUAN-DISPATCH-PROTOCOL.md`。

## 构建

### 前置要求
- Android Studio Hedgehog+ (2023.1.1+)
- JDK 17
- Android SDK 34

### 步骤
```bash
# 首次生成 Gradle wrapper (Android Studio 会自动生成, 也可手动):
cd E:\Tuan-CLI\Tuan\android
gradle wrapper --gradle-version 8.7

# 构建 Debug APK
./gradlew assembleDebug

# 产物
app/build/outputs/apk/debug/app-debug.apk
```

### 安装
```bash
adb install app/build/outputs/apk/debug/app-debug.apk
```

## 使用

1. 桌面端启动 dispatch server:
   ```bash
   cd E:\Tuan-CLI
   python -m tuan_cli.web.dispatch_server --port 8788
   ```
2. 手机启动 Tuan, 输入桌面 IP + 端口 + 配对码
3. 配对成功后选择代理 + 模式, 输入任务, 发送
4. 事件流实时显示, 需要审批时弹出审批按钮

## 网络要求

- 手机与桌面必须在同一局域网 (或桌面通过反向代理暴露 wss://)
- 桌面 `--host 0.0.0.0` 允许局域网访问 (默认仅 127.0.0.1)

## 兼容性

- Min SDK 26 (Android 8.0 Oreo)
- Target SDK 34 (Android 14)
- Kotlin 2.0, Compose BOM 2024.10, Material 3
- OkHttp 4.12 WebSocket, kotlinx-serialization JSON

## 依赖

- androidx.compose.* (UI)
- androidx.lifecycle.* (ViewModel)
- com.squareup.okhttp3:okhttp:4.12.0 (WebSocket)
- org.jetbrains.kotlinx:kxserial-json:1.6.3 (JSON)
- org.jetbrains.kotlinx:kxcoroutines-core:1.8.1 (协程)

## 后续迭代

- [ ] 前台服务保活 (当前后台会被系统回收)
- [ ] 多任务并发
- [ ] 任务历史 (本地 SQLite)
- [ ] wss/TLS 支持
- [ ] 推送通知 (审批请求)
- [ ] iOS 客户端 (SwiftUI)
