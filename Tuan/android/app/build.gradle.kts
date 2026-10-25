// app 模块构建配置
// Tuan-Chat Native: 手机远程调度桌面 Agent-of-Agents
plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
    alias(libs.plugins.kotlin.compose)
    alias(libs.plugins.kotlin.serialization)
}

android {
    namespace = "com.tuan.chat"
    compileSdk = 34

    defaultConfig {
        applicationId = "com.tuan.chat"
        minSdk = 26          // Android 8.0 特供版: 最低 26
        targetSdk = 34
        versionCode = 1
        versionName = "0.3.2-alpha"
    }

    buildTypes {
        release {
            isMinifyEnabled = false  // MVP 阶段不混淆, 便于调试
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }
    buildFeatures {
        compose = true
    }
}

dependencies {
    // Compose BOM: 统一管理 Compose 版本
    implementation(platform(libs.androidx.compose.bom))
    implementation(libs.androidx.activity.compose)
    implementation(libs.androidx.compose.ui)
    implementation(libs.androidx.compose.ui.graphics)
    implementation(libs.androidx.compose.ui.tooling.preview)
    implementation(libs.androidx.compose.material3)
    implementation(libs.androidx.compose.foundation)
    implementation(libs.androidx.lifecycle.runtime.compose)
    implementation(libs.androidx.lifecycle.viewmodel.compose)

    // WebSocket + JSON
    implementation(libs.okhttp)
    implementation(libs.kxserial.json)
    implementation(libs.coroutines.core)

    debugImplementation(libs.androidx.compose.ui.tooling)
}
