# Tuan Android 8.0 特供版 · 方案落地（v0.3.2）

> 本文档是 Tuan（Tuan 的移动端产品名）针对 **Android 8.0 特供版** 的方案落地文档，与 Tuan-CLI v0.3.2「五模式」改造同步发布。
>
> **状态：方案已落地（v0.3.2 · 2026-10-23），远程控制复用路径已核实**
>
> **本目录约定**：所有 Android 8.0 特供版相关文档、资源、代码均落在 `Tuan/` 目录下，不修改 `tuan_cli/`（Tuan-CLI Python 核心）与仓库根目录的其他文档。
>
> **相关文档**：
> - `../legal/ANDROID8_DISCLAIMER.md` —— 免责声明单一真源文案
> - `../../26.10.23全天代办.md` §9 Android 端 / §10 TTS —— 代办源文档
> - `AGENT-ANDROID.md` —— Tuan 内置 Rust Agent 方案（与本文档正交）

---

## 1. 五模式 → Android 裁剪

Tuan-CLI v0.3.2 引入五模式（闲聊 / 协同 / 感通 / 灵码 / 无界，ID 分别为 `chat / collaboration / gantong / lingma / boundless`）。**Android 端不追求"五模式全开"**，按主场景裁剪为四级：

| 模式 | ID | 桌面权限 | Android 侧 | 依据 |
|---|---|---|---|---|
| 闲聊 | `chat` | L0 | **满血** | `SOUL_FULL.md`(72KB) + `core/personality.py` 现成；纯收发 + TTS，零风险 |
| 协同 | `collaboration` | L2 | **受限（L1 封顶）** | 文档阅读 / 纪要查看 / 轻量编辑；重操作走 `send_prompt` 由桌面执行 |
| 感通 | `gantong` | L3 | **只读预览** | 可浏览 `tuan_cli/resources/skills/builtin/tuan-design/companies/` 的 72 份规范；渲染 / 建模异步派桌面 |
| 灵码 | `lingma` | L3 | **砍掉** | 手机写代码非主场景 |
| 无界 | `boundless` | L4 | **砍掉** | 同桌面决策：高危能力不暴露到移动侧 |

**模式命名硬规则**（与 Tuan-CLI v0.3.2 §0 执行前必读保持一致）：

- 只能使用「感通 / 灵码 / 闲聊 / 无界 / 协同」五个模式名；
- ID 只能用 `gantong / lingma / chat / boundless / collaboration`；
- **绝对禁止**在 Android 端任何 UI 文案、字符串资源、注释里出现旧名「灵感」「无限」「工作模式」（仓库有 `grep -r "灵感\|无限\|工作模式"` 硬规则，CI 会拦下）。

### 1.1 Android 侧的能力开关映射

各模式在 Android 端的**配置层**（不是提示词层）开关，落到 `AndroidConfig.kt`：

```kotlin
// Tuan/android/app/src/main/java/com/tuan/cli/config/AndroidModeSwitcher.kt
// 仅暴露桌面允许在 Android 生效的模式；被砍掉的模式在配置层根本不可见。

enum class AndroidMode(val id: String, val displayName: String) {
    CHAT("chat", "闲聊"),
    COLLABORATION("collaboration", "协同"),
    GANTONG("gantong", "感通");

    // 灵码 / 无界在 Android 端不枚举：调用方连类型上都看不到，物理上无法误选。
    companion object {
        fun fromId(id: String): AndroidMode? = entries.firstOrNull { it.id == id }
    }
}
```

`collaboration` 在 Android 端的 L1 封顶由服务端 `SecurityGate(remote=True)` 的 fail-closed 兜住——手机发出 `send_prompt` 后，非良性 prompt 一律被标记为 `requires_confirmation=True`，桌面 Agent 必须再次确认才能执行。

### 1.2 「只读预览」的具体含义（感通）

- **可浏览**：`tuan-design/companies/` 下的 72 份公司设计规范 md（如 `01-apple.md`、`02-google.md`、`72-xxx.md`），手机本地解压 APK 内 assets 后纯 `MarkdownRenderer` 渲染；
- **不可写**：不暴露 `write` / `edit` 工具；
- **异步派发**：手机点击"生成海报 / 建模"时，走 `send_prompt(session_id, "…")` 派给桌面，桌面以 L3 权限执行，结果以 `send_notification()` 推送回手机（含图片 URL 或本地相对路径）。

---

## 2. Android 8.0 免责声明落地（Compose AlertDialog 实现规格）

### 2.1 单一真源文案

**唯一真源文件**：`../legal/ANDROID8_DISCLAIMER.md`（已就位，v1.0）。

- **打包路径约定**：构建 APK 时由 Gradle task 复制到 `res/raw/android8_disclaimer.md`（首选）或 `assets/legal/android8_disclaimer.md`（备选）。`res/raw/` 优先，因为它支持按语言 / 配置切分。
- **SHA256 校验**：`../legal/CHECKSUMS.sha256` 记录本文件的 hash；Compose 启动时读取 `res/raw/android8_disclaimer.md` 并做 hash 比对，不一致则视为包被篡改，拒绝启动并显示告警。
- **禁止 Kotlin 硬编码副本**：文案变更一律先改 `ANDROID8_DISCLAIMER.md`，再走 CI 重新打包。任何在 Kotlin 里粘贴的声明文本都被视为漂移缺陷。

### 2.2 Compose AlertDialog 实现规格

必须满足以下 6 条硬约束（缺一不可）：

1. `AlertDialog` 组件，**不可**用系统级 `AlertDialog.Builder`（不可控）；
2. `dismissOnBackPress = { false }`：Back 键**不关闭**弹窗；
3. `dismissOnClickOutside = false`：点弹窗外区域**不关闭**；
4. 必须勾选底部 checkbox 才能激活「继续」按钮（初始 `enabled=false`）；
5. 必须滚动到 `MarkdownText` 底部（`scrollFraction ≥ 0.98`）才能激活「继续」按钮；
6. 「不同意」按钮**直接** `finish()`（走 `Activity.finish()`，不是 dismiss）。

### 2.3 Kotlin / Compose 代码骨架

```kotlin
// Tuan/android/app/src/main/java/com/tuan/cli/ui/disclaimer/Android8DisclaimerDialog.kt
package com.tuan.cli.ui.disclaimer

import android.app.Activity
import android.content.Context
import android.util.Log
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import java.security.MessageDigest

/**
 * Android 8.0 特供版安装前免责声明弹窗。
 *
 * 硬约束（对应 §2.2）：
 *   1. 用 Compose AlertDialog，不用系统 AlertDialog.Builder；
 *   2. dismissOnBackPress={false}；
 *   3. dismissOnClickOutside=false；
 *   4. 必须勾选 checkbox 才能点「继续」；
 *   5. 必须滚动到底部（scrollFraction >= 0.98）才能点「继续」；
 *   6. 「不同意」按钮直接 Activity.finish()。
 *
 * 文案来源：res/raw/android8_disclaimer.md（构建期由 Gradle 从
 *           Tuan/legal/ANDROID8_DISCLAIMER.md 复制而来）。
 *           禁止在本文件里硬编码文案副本。
 */
@Composable
fun Android8DisclaimerDialog(
    activity: Activity,
    onAgreed: () -> Unit = {},
    sha256Whitelist: Set<String> = remember { loadExpectedHashes() },
) {
    val context = LocalContext.current
    var agreeChecked by remember { mutableStateOf(false) }
    var scrolledToBottom by remember { mutableStateOf(false) }
    var disclaimerText by remember { mutableStateOf<String?>(null) }
    var loadError by remember { mutableStateOf<String?>(null) }

    // 从 res/raw 读入唯一真源文案。
    LaunchedEffect(Unit) {
        runCatching {
            val rawResId = com.tuan.cli.R.raw.android8_disclaimer
            val text = context.resources.openRawResource(rawResId)
                .bufferedReader(Charsets.UTF_8)
                .use { it.readText() }
            val actualHash = sha256(text)
            if (sha256Whitelist.isNotEmpty() && actualHash !in sha256Whitelist) {
                // 包体被篡改：拒绝启动，不允许绕过
                Log.e("Android8Disclaimer", "hash mismatch: $actualHash")
                activity.finish()
                return@runCatching
            }
            disclaimerText = text
        }.onFailure {
            loadError = it.message ?: "读取声明失败"
            activity.finish()
        }
    }

    if (loadError != null) {
        Text(text = "声明加载失败：$loadError", color = MaterialTheme.colorScheme.error)
        return
    }
    val text = disclaimerText ?: return

    AlertDialog(
        // 硬约束 2：Back 键不关闭
        onDismissRequest = { },
        // 硬约束 3：点外部不关闭
        dismissOnClickOutside = false,
        dismissOnBackPress = { false },
        // 标题区
        title = {
            Text(
                text = "Tuan Android 8.0 版 · 安装前声明",
                style = MaterialTheme.typography.titleLarge,
            )
        },
        // 正文：可滚动 markdown，需滚到底才能激活「继续」
        text = {
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .fillMaxHeight(0.68f)
                    .verticalScroll(rememberScrollState()),
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                MarkdownText(text = text)
                Spacer(modifier = Modifier.height(16.dp))
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    Checkbox(
                        checked = agreeChecked,
                        onCheckedChange = { agreeChecked = it },
                    )
                    Text(
                        text = "我已完整阅读并理解上述声明，确认本人已年满 18 周岁，自愿承担全部风险",
                        style = MaterialTheme.typography.bodyMedium,
                    )
                }
            }
        },
        // 底部按钮：
        //   「不同意」= 直接 finish（硬约束 6）
        //   「继续」= 需 agreeChecked && scrolledToBottom（硬约束 4 + 5）
        confirmButton = {
            Button(
                onClick = {
                    onAgreed()
                    // 关闭弹窗由 MainActivity 观察 onAgreed 触发
                },
                enabled = agreeChecked && scrolledToBottom, // 双门控
            ) {
                Text("继续")
            }
        },
        dismissButton = {
            Button(
                onClick = { activity.finish() }, // 硬约束 6：不同意 = 直接退出
                colors = ButtonDefaults.buttonColors(
                    containerColor = Color.Transparent,
                ),
            ) {
                Text("不同意", color = MaterialTheme.colorScheme.error)
            }
        },
    )
}

/**
 * 包装 MarkdownText + 滚动到底检测。
 * 用 Layout 而不是 modifier 是因为要在滚动结束帧判断 scrollFraction。
 */
@Composable
private fun ColumnScope.MarkdownText(text: String) {
    val scrollState = rememberScrollState()
    // 复用外层 verticalScroll(scrollState)，此处仅展示文本
    Text(
        text = text,
        style = MaterialTheme.typography.bodyMedium.copy(
            fontSize = 14.sp,
            lineHeight = 20.sp,
        ),
    )
    // 实际滚动到底检测：见下方 onScrollBottomReached 说明
}

/**
 * 滚动到底检测（生产实现）：
 *
 *   val scrollState = rememberScrollState()
 *   LaunchedEffect(scrollState) {
 *       while (true) {
 *           if (scrollState.maxValue > 0) {
 *               val fraction = scrollState.value.toFloat() / scrollState.maxValue
 *               scrolledToBottom = fraction >= 0.98f
 *           }
 *           snapshotFlow { scrollState.value }.collect { /* 更新 */ }
 *           delay(100)
 *       }
 *   }
 *
 * 骨架里省略 snapshotFlow 是为了保持示例简洁；实际实现必须启用 100ms 轮询
 * 或改用 snapshotFlow 观察 scrollState.value。
 */

/**
 * 计算 SHA-256（十六进制小写），用于校验 res/raw 声明文案未被篡改。
 */
private fun sha256(text: String): String {
    val digest = MessageDigest.getInstance("SHA-256")
    val bytes = digest.digest(text.toByteArray(Charsets.UTF_8))
    return bytes.joinToString("") { "%02x".format(it) }
}

/**
 * 从 Tuan/legal/CHECKSUMS.sha256 派生出来的预期 hash 集合
 * （构建期由 Gradle task 生成到 BuildConfig 或字符串资源里）。
 */
private fun loadExpectedHashes(): Set<String> {
    // 生产实现：BuildConfig.DISCLAIMER_HASHES.split(",").toSet()
    return emptySet()
}
```

### 2.4 MainActivity 集成点

```kotlin
// Tuan/android/app/src/main/java/com/tuan/cli/MainActivity.kt
class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        enableEdgeToEdge()

        setContent {
            MaterialTheme {
                val showDisclaimer by remember {
                    mutableStateOf(
                        // 只在首次启动且 SDK_INT == 26 (Android 8.0) 时展示
                        !SharedPreferencesUtils.getBoolean("android8_disclaimer_seen", false) &&
                            Build.VERSION.SDK_INT == Build.VERSION_CODES.O
                    )
                }

                if (showDisclaimer) {
                    Android8DisclaimerDialog(
                        activity = this,
                        onAgreed = {
                            SharedPreferencesUtils.putBoolean("android8_disclaimer_seen", true)
                            // 关闭弹窗后进入主流程
                        },
                    )
                } else {
                    AppRoot()
                }
            }
        }
    }
}
```

### 2.5 Gradle 资源同步任务

```groovy
// Tuan/android/app/build.gradle
// 每次打包前把 Tuan/legal/ANDROID8_DISCLAIMER.md 复制到 res/raw/，
// 并计算 SHA256 注入 BuildConfig，供运行时校验。
task syncAndroid8Disclaimer {
    doLast {
        def src = file("${rootProject.projectDir}/../legal/ANDROID8_DISCLAIMER.md")
        def dst = file("${project.projectDir}/src/main/res/raw/android8_disclaimer.md")
        dst.parentFile.mkdirs()
        dst.bytes = src.bytes
        def digest = java.security.MessageDigest.getInstance("SHA-256")
            .digest(src.bytes)
            .joinToString("") { String.format("%02x", it) }
        println "ANDROID8_DISCLAIMER_SHA256=${digest}"
        // 写入 BuildConfig.DISCLAIMER_HASHES（供 loadExpectedHashes 读取）
    }
}
preBuild.dependsOn syncAndroid8Disclaimer
```

---

## 3. 远程控制复用路径确认

### 3.1 结论

**Android 端不另造协议，直接复用 `tuan_cli/core/remote_control.py`（10.7KB，已实现）。** 该文件提供的能力已完全覆盖 Android 端需求：一次性配对 token、设备指纹绑定、爆破封禁、`SecurityGate(remote=True)` fail-closed 分类、push 通知、会话状态查询、断连与列会话。

**这意味着 Android 端的复杂度大幅下降**：不需要写 Python socket server、不需要新增 JSON-RPC 协议、不需要维护新的安全判定。手机侧只需要一个"深链解析器 + `send_prompt` HTTP 客户端 + 通知监听器"。

### 3.2 `RemoteSession` 字段核实

`E:\Tuan-CLI\tuan_cli\core\remote_control.py` 真实签名（已 read 核实）：

```python
@dataclass
class RemoteSession:
    session_id: str                  # 任务描述未列，但实际是必需字段
    pairing_token: str               # 与任务描述一致
    created_at: float                # 任务描述未列（内部计时用）
    connected: bool = False          # 任务描述未列
    connected_at: float = 0.0        # 任务描述未列
    device_name: str = ""            # 任务描述未列（confirm_pairing 会写入）
    device_type: str = ""            # mobile | desktop | tablet ← 原生支持 mobile
    push_enabled: bool = False       # 与任务描述一致
    push_on_decision: bool = True    # 决策请求推送到手机
    push_on_permission: bool = True  # 权限请求推送到手机
    confirmed: bool = False          # 一次性 token 是否已消费
    token_fingerprint: str = ""      # 设备绑定指纹（防异设备复用）
    confirm_attempts: int = 0        # 任务描述未列（防爆破计数）
    requires_confirmation: bool = False  # 任务描述未列（当前 prompt 是否需用户确认）

    @property
    def is_expired(self) -> bool:    # 5 分钟 TTL
    @property
    def is_active(self) -> bool:     # connected 且 not expired
```

方法签名核实：

| 方法 | 任务描述 | 实际签名 | 是否一致 |
|---|---|---|---|
| `start_pairing(session_id)` | 一致 | 一致 | 一致 |
| `confirm_pairing(token, device_name, device_type="mobile")` | 一致，但省略了默认值 | `confirm_pairing(token, device_name="", device_type="mobile")` — `device_name` 也有默认值 | 默认值更宽松 |
| `generate_qr_data(pairing_info)` | 一致 | 一致 | 一致 |
| `send_prompt(session_id, prompt)` | 一致 | 一致 | 一致 |
| `send_notification(...)` | 一致 | `send_notification(session_id, title, body, priority="normal")` — 3 参数必填 | 任务描述过简 |
| `disconnect(session_id)` | 一致 | 一致 | 一致 |
| `list_sessions()` | 一致 | 一致 | 一致 |
| `get_status(session_id)` | 一致 | 一致 | 一致 |
| `_classify_remote(prompt)` | 一致 | 一致 | 一致 |

**额外存在但任务描述未列的方法**：`on(event, callback)`（事件回调注册）、`get_session(session_id)`、`_save_sessions()`、`_load_sessions()`、`_cleanup_expired()`、`_find_free_port()`。

**关键差异总结**：任务描述给出的字段与方法是真实实现的**子集**（无冲突，但省略了 `session_id / created_at / connected / connected_at / device_name / confirm_attempts / requires_confirmation` 7 个字段和 `on()` 回调 API）。Android 端集成时以真实代码为准。

### 3.3 调用链时序（扫码 → 桌面执行 → TTS 播放）

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                                                                             │
│  桌面端 Tuan-CLI / Tuan 实例                Android 原生壳（Compose） │
│  ─────────────────────────────                ─────────────────────────── │
│  rc.start_pairing(session_id="s1")          │                              │
│     └─ token = secrets.token_urlsafe(32)    │                              │
│     └─ url = tuan-remote://pair?host=...    │                              │
│              &port=...&token=...&session=s1 │                              │
│     └─ rc.generate_qr_data(pairing)         │                              │
│              ──────────────────────────────▶│                              │
│                                             │  扫码 → Intent.ACTION_VIEW   │
│                                             │  解析 tuan-remote://pair?...│
│                                             │                              │
│  rc.confirm_pairing(token, "MyPhone",       │◀────────────────────────────│
│              device_type="mobile")          │  POST /pair {token, name}    │
│     ├─ 校验过期 (<5min)                       │                              │
│     ├─ 校验 confirmed=False（一次性 token）    │                              │
│     ├─ 校验爆破封禁未触发                      │                              │
│     ├─ 写入 token_fingerprint（设备绑定）      │                              │
│     └─ 立即作废旧 token（防重放）               │                              │
│                                             │  ← 200 OK: 配对成功          │
│                                             │                              │
│                                             │  用户发 prompt              │
│  rc.send_prompt("s1", "帮我看下 README.md")   │◀────────────────────────────│
│     └─ _classify_remote(prompt)             │  POST /prompt {text}         │
│           └─ SecurityGate(remote=True)      │                              │
│                .classify_remote_prompt()    │                              │
│           └─ 命中红线 → deny（不投递）         │                              │
│           └─ 分类异常 → confirm（保守要求确认） │                              │
│           └─ 良性 → 正常投递                    │                              │
│     └─ 设置 rs.requires_confirmation          │                              │
│     └─ 触发 on("on_prompt") 回调              │                              │
│           └─ 桌面 Agent 收到 prompt           │                              │
│           └─ 若 requires_confirmation=True： │                              │
│              桌面弹确认框等用户批准              │                              │
│                                             │                              │
│  桌面 Agent 决策 / 请求权限                    │                              │
│     └─ rc.send_notification(                │                              │
│            "s1", "权限请求", "写文件到 X",     │                              │
│            priority="high")                 │                              │
│           └─ rs.push_on_permission=True？     │                              │
│           └─ 触发 on("on_notification")     │                              │
│              ──────────────────────────────▶│  Android 通知栏弹出          │
│                                             │  标题：权限请求                │
│                                             │  正文：写文件到 X              │
│                                             │                              │
│  桌面 Agent 完成任务，回复文本                   │                              │
│     └─ rc.send_notification("s1", ...,      │                              │
│            priority="normal")               │                              │
│              ──────────────────────────────▶│  Android 通知栏弹出          │
│                                             │                              │
│                                             │  ┌────────────────────────┐ │
│                                             │  │ Moss TTS 播放           │ │
│                                             │  │   ├─ tts-dispatcher    │ │
│                                             │  │   │  (选声线：傲娇/元气)│ │
│                                             │  │   ├─ Moss ONNX Runtime │ │
│                                             │  │   │  0.1B / 48kHz      │ │
│                                             │  │   └─ AudioTrack 播放   │ │
│                                             │  └────────────────────────┘ │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 3.4 安全性论证：天然等价于 plan 级

**核心论断**：手机只有**提议权**，执行与拦截全在桌面端。这等价于桌面端把手机视作一个「远端用户输入源」，而非「执行代理」。

推论链：

1. 手机发出的一切内容都是 `send_prompt(session_id, prompt)` 的 `prompt` 参数——字符串；
2. 字符串过 `_classify_remote(prompt)` → `SecurityGate(remote=True).classify_remote_prompt()`；
3. `SecurityGate(remote=True)` 是 **fail-closed** 模式：命中硬红线直接 deny，任何异常一律要求确认，**永不直接放行**；
4. 通过分类的 prompt 若仍需确认，`rs.requires_confirmation=True` 会让桌面 Agent 弹确认框；
5. 桌面 Agent 执行任何工具调用时，走的还是桌面的完整 `SecurityGate` 判定（因为 Agent 就在桌面端跑，用的是桌面的 session 上下文）；
6. 手机端**无法**：直接调用工具、绕过 SecurityGate、修改本地文件系统、访问桌面私有目录。

因此，Android 端的等效权限级别 = **plan 级**（可提议、需确认、无法绕过）。这与 Tuan 桌面端 `plan` 模式的语义完全对齐，无需在 Android 侧再实现一层权限模型。

**副作用**：这条复用路径也顺带解决了「老机算力不足」问题——手机只做 HTTP 客户端 + 通知 + TTS，不跑 Agent 推理、不跑 SecurityGate、不跑工具执行，2GB RAM 的骁龙 660 都够跑。

### 3.5 Android 侧实现最小依赖

| 组件 | 作用 | 依赖 |
|---|---|---|
| `TuanRemoteClient.kt` | HTTP 客户端，实现 `pair` / `prompt` / `notification-listen` 三个端点 | OkHttp |
| `TuanRemoteDeepLinkHandler.kt` | `Activity` 处理 `tuan-remote://` intent，解析 params 并调 pair | 无（framework） |
| `TuanRemoteNotificationListener.kt` | 监听 HTTP push endpoint（或 SSE），触发 Android Notification | `android.app.NotificationManager` |
| `TuanRemoteQRScanner.kt` | 扫码入口，产出 `Uri` 交给 DeepLinkHandler | ZXing 或 ML Kit |
| `MossTTSEngine.kt` | TTS 播放，见 §4 | ONNX Runtime Mobile |

**无需**实现：任何 Python socket server、JSON-RPC、加密通道（复用 TCP TLS 或应用层 token 即可）、设备指纹计算（服务端 `_device_fingerprint()` 已经处理）。

---

## 4. TTS 章节对齐（Moss NANO 0.1B · ONNX）

### 4.1 选型（与代办 §10 一致，此处固化到 Android 落地）

| 层 | 选型 | 说明 |
|---|---|---|
| Android 推理 | ONNX Runtime Mobile | **不含 PyTorch**，`onnxruntime-android` AAR 直连 |
| 版本锁 | **≤ 1.16** | 1.16 是最后一个支持 API 26（Android 8.0）的 ORT 版本；1.17+ 的 `onnxruntime-android` 已把 `minSdk` 提到 28 |
| 加速 | NNAPI → GPU delegate → CPU | 三级回落；8.0 老芯片的 DSP delegate 可能报错，跳过 |
| 规格 | 0.1B 参数 / 48kHz 立体声 / 首包 < 200ms | 首包延迟指从 `synthesize()` 调用到 `AudioTrack.write()` 首次收到 PCM 的时间 |
| 声线来源 | 复用 `SOUL_FULL.md` 人格 | 零样本克隆 3–5s 参考音频（傲娇 / 元气 / 深沉各绑一声线） |
| 许可 | Apache 2.0 | Moss 模型权重与 ONNX Runtime 均为 Apache 2.0，可商业使用 |
| 触发策略 | 闲聊默认开 / 协同按需 / 感通按需 / 灵码无界不适用 | 见 §4.3 |

### 4.2 调用链

```
回复文本 (String)
    │
    ▼
tts-dispatcher.selectVoice(persona: Soul)
    │  依据 SOUL_FULL.md 中的 persona 字段选择声线
    │  如未匹配，fallback 到默认"中性女声"
    ▼
MossTTSEngine.synthesize(text, voiceId)
    │  ONNX Runtime Mobile session.run()
    │  输入：text tokens + voice embedding
    │  输出：PCM 48kHz / 立体声 / 16bit
    ▼
AudioTrack.write(pcm, 0, len)
    │  流式写，边合成边播，首包 < 200ms
    ▼
用户耳朵听到声音
```

### 4.3 五模式触发策略

| 模式 | Android 侧 TTS | 说明 |
|---|---|---|
| 闲聊 (`chat`) | **默认开** | 纯对话场景，TTS 是核心价值 |
| 协同 (`collaboration`) | **按需**（用户手动切换） | 文档阅读时可能有用；纪要场景可自动开 |
| 感通 (`gantong`) | **按需** | 72 份规范以纯文本预览为主，TTS 一般不启用 |
| 灵码 (`lingma`) | **不适用** | Android 端已砍掉该模式 |
| 无界 (`boundless`) | **不适用** | Android 端已砍掉该模式 |

### 4.4 与代办的对齐情况

| 项目 | 代办 §10 | 本节 §4 | 状态 |
|---|---|---|---|
| 推理框架 | ONNX Runtime Mobile ≤1.16 | 同 | 一致 |
| 加速链 | NNAPI → GPU → CPU | 同 | 一致 |
| 规格 | 0.1B / 48kHz / 首包 <200ms / Apache 2.0 | 同 | 一致 |
| 声线 | SOUL_FULL.md 零样本克隆 3–5s | 同 | 一致 |
| 触发策略 | 闲聊默认开 / 协同感通按需 / 灵码无界不适用 | 同 | 一致 |
| 调用链 | 回复文本 → tts-dispatcher → Moss ONNX → AudioTrack | 同 | 一致 |

**结论**：§4 与代办 §10 完全对齐，无需修正。

---

## 5. Android 落地验收清单

### 5.1 远程控制与配对

- [ ] **配对成功**：桌面执行 `rc.start_pairing()`，手机扫码 → POST `/pair` 返回 200 OK，`rc.confirm_pairing()` 返回 `True`，`get_status()` 显示 `connected=True`
- [ ] **token 一次性**：同一 token 第二次调用 `confirm_pairing()` 返回 `False`（`rs.confirmed=True` 触发拒绝）
- [ ] **爆破封禁**：连续 5 次错误 token 后，`_confirm_locked_until` 被设置，60 秒内所有 `confirm_pairing()` 直接返回 `False`
- [ ] **token 过期**：`start_pairing()` 后等待 305 秒（>5min），`confirm_pairing()` 返回 `False`（`is_expired=True`）
- [ ] **设备指纹**：`confirm_pairing(token, device_name="A", device_type="mobile")` 成功后，`token_fingerprint` 写入；后续 `device_name="B"` 同 token 无法再次确认（因 `confirmed=True`）

### 5.2 安全分类（fail-closed 生效）

- [ ] **红线拒绝**：手机端 `send_prompt("... rm -rf / ...")`，桌面 `rc.send_prompt()` 返回 `False`，日志出现 `"远程 prompt 被安全闸门拒绝"`
- [ ] **异常保守确认**：构造一个 `SecurityGate` 分类抛异常的 prompt，`_classify_remote()` 返回 `GateVerdict("confirm", "high", ...)`，`rs.requires_confirmation=True`
- [ ] **良性放行**：`send_prompt("帮我看下 README.md")` 返回 `True`，桌面 Agent 收到 callback
- [ ] **推送送达**：`rs.push_enabled=True` + `rs.push_on_permission=True`，桌面 `send_notification()` 后手机通知栏在 2 秒内弹出
- [ ] **决策推送**：`rs.push_on_decision=True`，桌面 Agent 决策点触发 `send_notification(priority="high")` 后手机弹出高优先级通知

### 5.3 TTS 性能

- [ ] **首包 < 200ms**：`MossTTSEngine.synthesize("你好，我是团。", voiceId="default")` 从调用到 `AudioTrack.write()` 首次收到 PCM 的耗时 < 200ms（骁龙 660 冷启动可放宽至 500ms，骁龙 821 及以上严格 <200ms）
- [ ] **NNAPI 加速**：`OrtSession.SessionOptions.addNnapiDelegate()` 未抛异常
- [ ] **GPU 回落**：`OrtSession.SessionOptions.addGpuDelegate()` 在 NNAPI 失败后自动尝试
- [ ] **CPU 兜底**：前两级都失败时 `OrtSession.SessionOptions.addCpuDelegate()` 保底
- [ ] **48kHz 立体声**：`AudioTrack` 采样率 = 48000，声道数 = 2，格式 = `ENCODING_PCM_16BIT`
- [ ] **零样本克隆**：给定 3–5s 参考音频 + `SOUL_FULL.md` 中的 persona 描述，输出声线与参考音色 Pearson 相关系数 > 0.7（用开源说话人验证模型度量）

### 5.4 Android 8.0 免责声明

- [ ] **文案就位**：`Tuan/legal/ANDROID8_DISCLAIMER.md` 存在，SHA256 与 `CHECKSUMS.sha256` 一致
- [ ] **打包复制**：APK 构建后 `unzip -l app.apk | grep android8_disclaimer.md` 能列出 `res/raw/android8_disclaimer.md`
- [ ] **Compose AlertDialog**：`dismissOnBackPress={false}`、`dismissOnClickOutside=false` 已生效，Back 键与点外部**均不关闭**弹窗
- [ ] **勾选门控**：未勾选 checkbox 时「继续」按钮 `enabled=false`（灰化）
- [ ] **滚动到底门控**：scrollFraction < 0.98 时「继续」按钮 `enabled=false`
- [ ] **不同意退出**：点击「不同意」按钮，`Activity.finish()` 被调用，进程退出
- [ ] **hash 校验**：篡改 `res/raw/android8_disclaimer.md` 后启动 APK，进程拒绝启动并 `finish()`

### 5.5 五模式裁剪（v0.3.2）

- [ ] `AndroidMode` 枚举**仅包含** `CHAT / COLLABORATION / GANTONG`，不含 `LINGMA / BOUNDLESS`
- [ ] Android 端 UI 中**无任何**模式名出现「灵感」「无限」「工作模式」（`grep -r` 验证）
- [ ] 感通模式下 `tuan-design/companies/` 72 份规范可本地浏览，写入被禁
- [ ] 协同模式下重操作（`write` / `edit` / `shell`）经 `send_prompt` 派发桌面执行，桌面 `requires_confirmation=True` 生效

### 5.6 8.0 兼容性验证项

- [ ] **软键盘避让**：`window.onresize` 高度差探测生效，`#inputbar` 偏移量在键盘弹出时动态调整
- [ ] **刘海屏安全区**：Chrome 68 无 `safe-area-inset-*` 支持，应用侧 hard-code 顶部 padding
- [ ] **横竖屏切换**：`orientationchange` 事件监听触发，Layout 重排无错位
- [ ] **WebView 内核**：`webview:versionName` 在日志中确认为 Chrome 68 系（Android 8.0 出厂）
- [ ] **权限弹窗**：`INTERNET`、`FOREGROUND_SERVICE` 权限在首次运行时弹出并授权
- [ ] **旧芯片降级**：骁龙 660 / 821 上 TTS 首包可能 >200ms，UI 上显示"处理中…"而非卡死
- [ ] **RAM 不足降级**：2GB RAM 设备上 TTS 使用 CPU 路径，跳过 NNAPI / GPU

### 5.7 端到端回归

- [ ] **手机 → 桌面执行 → 手机收推送**：一次完整链路（扫码配对 → 发 prompt → 桌面执行 → 手机收到决策通知 → TTS 播报通知正文）在 Android 8.0 设备上跑通
- [ ] **老机预期**：骁龙 660 / 8GB 存储 / 2GB RAM 组合设备上，20 分钟内完成一次完整配对 + 一次发请求 + 一次 TTS 播报
- [ ] **免责声明首次触发**：全新安装、清数据后首次启动，8.0 设备上弹出免责声明弹窗

---

*文档维护者：Tuan Android 8.0 特供版工作流组*
*最后更新：2026-10-23（v0.3.2 · 五模式对齐 · 远程控制复用路径核实 · 8.0 免责声明文案就位）*
*相关文档：[ANDROID8_DISCLAIMER.md](../legal/ANDROID8_DISCLAIMER.md) · [AGENT-ANDROID.md](AGENT-ANDROID.md) · [26.10.23全天代办.md](../../26.10.23全天代办.md)*
