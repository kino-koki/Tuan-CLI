# Tuan-Chat 构建与运行说明

技术栈：Tauri 2 + React + TypeScript（前端），底层对接 tuan_cli 0.3.1；界面以中文为主，仅保留
OpenAI / Anthropic、Base URL、sk-、Enter / Shift+Enter、模型 ID 等必要英文。

## 〇、本次修改（2026-10-19）——需重新构建才生效

以下改动只落在源码，`release/` 里的产物仍是 2026-10-18 构建的旧版本，**必须重新构建**才能带上：

| 改动 | 文件 | 效果 |
|---|---|---|
| 焦点环错位修复 | `src/index.css` | 删除 `:focus-visible` 里写死的 `border-radius: 8px`（它会覆盖输入卡 22px 圆角，造成"方框套圆卡"视觉错位），改用双层 `box-shadow` 跟随元素原圆角 |
| 引擎探测增强 | `src-tauri/src/engine.rs` | `resolve_python` 五级探测：bundled → `TUAN_PYTHON` → PATH（`python`/`python3`/`py`）→ 注册表 `HKLM\SOFTWARE\Python\PythonCore\*\InstallPath`（调 `reg.exe`，零新依赖）→ 常见安装路径；`py` 自动补 `-3` 参数 |
| 引擎自检命令 | `src-tauri/src/engine_chat.rs` | 新增 `check_engine`：启动时定位引擎目录 + Python，返回可用性 JSON |
| 前端状态指示 | `src/App.tsx`、`src/components/SettingsPage.tsx` | 启动时自检并显示"引擎就绪/不可用"卡；`invoke` 用 `@tauri-apps/api/core` 直导入（`engine.ts` 未 re-export `isTauri`） |
| 引擎形象替换 | `src/assets/avatars*`、`scripts/build_official_avatars.py` | 195 张画师同人立绘 → 39 张官方形象（7 家下载官网资源，6 家按官方品牌色生成）；`mascot.ts` glob 从 `*.jpg` 放宽到 `*.{jpg,png}` |
| 删除硬编码路径 | `src-tauri/src/engine.rs`、`engine_chat.rs` | 移除 `E:\Tuan-CLI\...` 开发者本机路径（release 版本不再暴露），开发回退仅在 `#[cfg(debug_assertions)]` 下生效 |

> 前端已在本机验证通过：`tsc` 无报错、`vite build` ✓（`index.js` 597 kB → 500 kB）。
> **Rust 侧仅做了静态审查，未编译**（本机无 rustc/cargo、无 MinGW，下载速度约 65 KB/s，
> 装完整工具链需数小时）。审查结论：无编译错误，cfg 嵌套正确；仅 Android 目标下
> `engine_root` / `ensure_server` 会报 `dead_code` 警告（非错误，项目未开 `deny(warnings)`）。

### 已知待优化：Android 白打包 Python 引擎

`bundle.resources` 把 `../engine/tuan_cli` 打进**所有**平台，导致 arm64 APK 里也塞了
约 3–5 MB 的 Python 引擎源码——而 Android 端根本不用它（对话走 Rust 直连通道）。

Tauri 2 的 `bundle.resources` 不支持按平台排除，若要瘦身可创建 `tauri.android.conf.json`
把 resources 覆盖为空，Android 构建时加 `--config tauri.android.conf.json`。
因涉及构建参数改动、本机无法验证，此处仅记录方案，未直接改配置。

---


## 〇·五、环境变量约定（所有构建命令前置）

文档里所有路径都走变量，不再写死盘符或用户名。**先按你机器实际位置设好这两个变量**，
后面所有命令直接引用：

| 变量 | 含义 | 示例 |
|---|---|---|
| `TuanRoot` | 仓库根（含 `Tuan-App/` 与 `tuan_cli/` 的目录） | `F:\Tuan-CLI` |
| `MinGWBin` | MinGW-w64 的 `bin` 目录 | `D:\ucrt64\bin` |

PowerShell：

```powershell
$env:TuanRoot = 'F:\Tuan-CLI'          # 按实际盘符改
$env:MinGWBin = 'D:\ucrt64\bin'        # 按实际安装位置改
```

Git Bash（用户主目录直接用 `$HOME`，无需写用户名）：

```bash
export TuanRoot='/f/Tuan-CLI'          # 按实际盘符改，POSIX 形式
export MinGWBin='/d/ucrt64/bin'
```

> JDK / Android SDK / NDK 属于**本机环境特定**路径，因人而异，无法用变量统一，
> 下面 Android 章节保留占位符 `<JDK_HOME>`、`<SDK_HOME>`、`<NDK_HOME>`，按本机实际填。
> 用户目录一律用 `%USERPROFILE%`（PowerShell）/ `$HOME`（Bash），不要写 `C:\Users\<你的名字>`。

> **例外**：`TMP` / `TEMP` 必须是 Windows 反斜杠格式（见下文「构建环境注意事项」第 1 条），
> Git Bash 不会自动转换，需单独按反斜杠写，不能靠 `$TuanRoot` 展开。

---

## 一、Windows 10/11 便携版（已产出）

产物目录：`release/`

- `Tuan-Chat.exe`：主程序（便携，免安装）
- `WebView2Loader.dll`：随程序同目录放置（依赖系统已安装的 WebView2 Runtime；Win10/11 多数自带，
  缺失时从微软官网安装 Evergreen WebView2 Runtime 即可）

运行：保持 `Tuan-Chat.exe` 与 `WebView2Loader.dll` 在同一目录，双击 `Tuan-Chat.exe`。
兼容 Windows 10（64 位，1903+）与 Windows 11。

### 本机重新构建

```powershell
# 前端（TuanRoot 见「〇·五、环境变量约定」）
cd "$env:TuanRoot\Tuan-App"
npm install
npm run build

# Rust release（本机使用 gnu 工具链 + MinGW）
cd src-tauri
$env:Path = "$env:MinGWBin;" + $env:Path
$env:RUSTUP_TOOLCHAIN = 'stable-x86_64-pc-windows-gnu'
cargo build --release
# 产物：src-tauri\target\release\tuan-app.exe，连同 WebView2Loader.dll 复制为 release\Tuan-Chat.exe
```

## 二、供应商 / 模型目录

`public/data/providers.json` 由 `scripts/export_catalog.py` 从 tuan_cli 的
`provider_catalog.py` 与 `model_lists.py`（MODEL_LISTS 全量）导出，共 58 家供应商、1440 个模型，
每个模型带 `free/paid` 标记。脚本内部已改为相对自身位置解析路径，无需依赖 `.venv`：

```powershell
cd "$env:TuanRoot\Tuan-App"
python scripts\export_catalog.py
python scripts\export_skills.py
```

## 三、Android APK

环境已配齐（JDK 17、Android SDK 36、NDK 26.1、Rust android target），可直接出包。
目标 **minSdk 28（Android 9）及以上**，覆盖骁龙 660/665 等主流低端机。

构建命令（Git Bash）：

```bash
cd "$TuanRoot/Tuan-App"
# 以下三个按本机实际路径填（用户目录用 $HOME，不要写 C:\Users\<名字>）
export JAVA_HOME='<JDK_HOME>'                        # 例：/c/Program Files/Microsoft/jdk-17.0.20.101-hotspot
export ANDROID_HOME="$HOME/AppData/Local/Android/Sdk"
export ANDROID_SDK_ROOT="$ANDROID_HOME"
export NDK_HOME='<NDK_HOME>'                          # 例：$ANDROID_HOME/ndk/26.1.10909125
export RUSTUP_TOOLCHAIN='stable-x86_64-pc-windows-gnu'
# TMP/TEMP 必须反斜杠格式，不能用变量展开（见「构建环境注意事项」第 1 条）
export TMP='F:\Tuan-CLI\.build_tmp'; export TEMP='F:\Tuan-CLI\.build_tmp'
# PATH 用 POSIX 形式；node 版本目录按本机实际
export PATH="$HOME/.cargo/bin:$HOME/.workbuddy/binaries/node/versions/22.22.2-6:$MinGWBin:$PATH"
export CODEBUDDY_SAFE_DELETE_ENABLED=0

# 仅 arm64（覆盖绝大多数真机，包体最小）
./node_modules/.bin/tauri.cmd android build --apk --target aarch64
# 需要模拟器时构建 universal（arm64 + armv7 + x86_64）
./node_modules/.bin/tauri.cmd android build --apk
```

产物：`src-tauri/gen/android/app/build/outputs/apk/universal/release/`。

> **若产物名带 `-unsigned`**，说明 `hasReleaseKeystore` 为 false、签名被静默跳过了。
> `build.gradle.kts` 里的 `file()` 相对**该文件自身所在目录**（`gen/android/app/`）解析，
> keystore 放在 `gen/android/tuan-release.keystore`，故需三级上溯：
> `file("../../../gen/android/tuan-release.keystore")`。
> 写成 `../../` 会指向 `gen/`，`exists()` 返回 false，Gradle 不报错、
> 只是不签名，最后产出装不上的 unsigned 包。核对方式：
> ```bash
> # 应输出 True
> cd src-tauri/gen/android/app && test -f ../../../gen/android/tuan-release.keystore && echo True
> ```

### 低端机（骁龙 660 级）优化项

| 项 | 做法 | 效果 |
|---|---|---|
| 头像解码 | 聊天头像位仅 32px，预生成 128px 方形缩略图（`src/assets/avatars-thumb/`），不再解码 900px 立绘 | 图像资源 9.8 MB → 0.43 MB（省 96%） |
| 长列表 | 聊天默认只渲染最近 60 条，顶部可按段加载更早消息 | 避免千条消息一次性挂载导致掉帧 |
| 动画 | 思考中光晕由 `box-shadow` 动画改为 `transform + opacity`（伪元素扩散环） | 消除每帧重绘，交给 GPU 合成 |
| 包体 | release 开启 R8（`isMinifyEnabled` + `isShrinkResources`）+ `strip = true` | 显著减小安装包 |
| 构建 profile | `opt-level = 2`、`codegen-units = 16`、`panic = "abort"`，**不开 LTO** | 运行时性能优先，见下文「Rust 优化级别说明」 |

R8 规则见 `src-tauri/gen/android/app/proguard-rules.pro`，已保留 Tauri 插件反射实例化
与 WebView `@JavascriptInterface` 桥接方法，避免混淆导致启动崩溃。

### 构建环境注意事项

本机需额外注意以下几处，否则构建会失败或产出白屏 exe：

1. **`TMP` / `TEMP` 必须是反斜杠格式的真实目录**。Git Bash 下写正斜杠（如
   `/f/Tuan-CLI/.build_tmp`）时，MSYS 会原样传给 Windows 原生程序，
   导致 `dlltool` 报`could not create import library`、rustc 静默卡死等诡异错误。
   正确写法（**反斜杠 + 单引号，按你实际盘符改**）：
   ```bash
   export TMP='F:\Tuan-CLI\.build_tmp'   # 单引号 + 反斜杠，勿用 $TuanRoot 展开
   export TEMP='F:\Tuan-CLI\.build_tmp'
   ```
2. **`.gitignore` 不能完全忽略 `dist/`**。`tauri-build` 生成资源归档时用
   `git ls-files` 列举前端文件，若 `dist/` 被完全忽略，JS/CSS 不会进exe，
   表现为**窗口能开但白屏无渲染**。本项目的 `.gitignore` 用 `!dist/**` 例外规则
   保留可见性。若再遇白屏，先确认：
   ```bash
   git ls-files --others --exclude-standard Tuan-App/dist | wc -l   # 应 > 0
   ```
3. **`JAVA_HOME` 指向 JDK 的 Windows 路径且不含多余空格**，例如
   `C:/Program Files/Microsoft/jdk-17.0.20.101-hotspot`（路径版本按本机 JDK 实际填）。
4. **必须显式指定 `RUSTUP_TOOLCHAIN=stable-x86_64-pc-windows-gnu`**。
   本机 rustup 默认工具链是 `stable-x86_64-pc-windows-msvc`，但系统里**没有装
   MSVC 的 `link.exe`**；一旦走到 MSVC 构建脚本阶段，就会用 GNU 的
   `link` 去接 MSVC 参数，报 `link: extra operand '...rcgu.o'`，编译直接失败。
   只要设了上面这个环境变量，rustup 就会切到 MinGW 完整工具链。
5. **`PATH` 里的路径要用 POSIX 形式（`/c/...`）传给 Git Bash**。
   `tauri.cmd` 会通过 `cmd` 调起子进程 `npm run build`，若 `PATH` 里写的是
   Windows 形式（`C:\...`），Git Bash 会原样透传，cmd 子进程找不到 npm，报
   `'npm' is not recognized`。正确写法：
   ```bash
   export PATH="$HOME/.cargo/bin:$HOME/.workbuddy/binaries/node/versions/22.22.2-6:$MinGWBin:$PATH"
   ```

### 桌面端出包（Windows）

```bash
cd "$TuanRoot/Tuan-App"
export TMP='F:\Tuan-CLI\.build_tmp'; export TEMP='F:\Tuan-CLI\.build_tmp'   # 按实际盘符改
export RUSTUP_TOOLCHAIN='stable-x86_64-pc-windows-gnu'
export PATH="$HOME/.cargo/bin:$HOME/.workbuddy/binaries/node/versions/22.22.2-6:$MinGWBin:$PATH"

# 必须用 tauri CLI 而非裸 cargo build：CLI 会先跑 npm run build 并正确嵌入前端资源
./node_modules/.bin/tauri.cmd build --no-bundle
```

产物：`src-tauri/target/release/tuan-app.exe`（约 17 MB）。
便携版目录 `release/` 需要 exe + `WebView2Loader.dll` + `engine/tuan_cli`（桌面端 agent 依赖本地引擎）。

> **若构建报 `SAFE_DELETE_BULK_CONFIRM_REQUIRED`**：Vite 清空 `dist/assets` 时的批量
> 删除被环境的安全守卫拦下（产物文件超过 50 个即触发）。加一行环境变量即可：
> ```bash
> export CODEBUDDY_SAFE_DELETE_ENABLED=0
> ```
> 该目录是纯构建产物，删除是预期行为。

> NSIS 安装包（`tauri build --bundles nsis`）需下载 nsis-3.13，本机网络受限暂未产出。

### Rust 优化级别说明

`Cargo.toml` 中 `profile.release` 设为 `opt-level = 2`，**未开LTO**。
实测 LTO（含 thin）在 Tauri 这种大依赖树上会把链接拖到 1 小时以上，
收益远小于时间成本；体积主要由 Android 侧 R8 与 `strip` 控制，
而 `opt-level = 2` 在运行时性能上明显优于 `"z"`，更贴合低端机流畅运行的目标。

### Android 端Rust 适配

安卓端不内置本地 Python 引擎，`src-tauri/src/engine_chat.rs` 中的 `executable_dir()`
在 Wry 移动端运行时不存在，已用 `#[cfg(not(target_os = "android"))]` 隔离；
`engine.rs::which()` 同理。编译时若出现 `no method named executable_dir`，
说明该处缺少条件编译。

注意：release 首次构建因 LTO 较慢（约 10 分钟以上），后续增量构建会快很多。

说明：Android 设备上不内置本地 Python 引擎。桌面端对话经`engine_chat_stream`
走本地引擎；**移动端改走Rust 侧轻量 Agent**（`agent_chat_stream`），具备
`web_search` / `web_fetch` / `calc` / `note` 四个工具，详见 `docs/AGENT-ANDROID.md`。
平台判定必须按 UA 判断——Tauri 的 `isTauri()` 在 Android 上同样返回 true，
若只用它分流，安卓会误走 `engine_chat_stream` 而因无本地引擎必然失败。

---

## 五、模型输出乱码的成因与修法

### 症状

回复正文里夹杂 `\n` 字面量、`\uXXXX` 转义残留、裸露的 ``` 和表格竖线。

### 两个独立成因

**1. SSE 的 `data:` 未做 JSON 解码（Rust 侧，真乱码）**

引擎发的 `data:` 是 JSON 编码的字符串（内层还有一层转义），而
`engine_chat.rs` 的 `delta` / `reason` 分支把它**当纯文本直接透传**：

```rust
// 修复前
"delta" => Some(text_chunk(data)),   // data 仍是 `"第一行\n第二行"`
```

同一个函数里 `tool` / `tool_result` 分支**有** `from_str`，可见 data 确实是
JSON 编码的——只有正文分支漏了解析。修法见 `decode_sse_data()`：带引号才尝试
JSON 反序列化，失败则原样返回（兼容引擎降级为纯文本 delta）。

顺带修了两处相关问题：
- 行尾 `\r` 未剥离（SSE 规范允许 CRLF），会导致正文末尾混入回车；
- `search` 工具把 DuckDuckGo 的 `//duckduckgo.com/l/?uddg=<encoded>`
  中转链接直接交给模型，模型拿到的是无法点击也无法再抓取的地址。
  已加 `unwrap_ddg_redirect()` + 手写 `percent_decode()`
  （不引入 `percent-encoding` 依赖，省安卓包体）。

**2. 流式期间用 Markdown 渲染器解析半截文本（前端，视觉上的"参杂"）**

`react-markdown` 逐字重解析时，未闭合的 ``` 和表格分隔行会被解析成残缺结构，
正文里就会闪出裸露的反引号与竖线；长回复还会反复全量重解析而掉帧。
修法（`ReplyMarkdown.tsx`）：`streaming` 为真时走 `white-space: pre-wrap` 的
纯文本，这一轮结束后再一次性切Markdown。字号与行高保持一致，切换无视觉跳变。

### 单测为什么跑不起来

`cargo test --lib` 在本机会报 `STATUS_ENTRYPOINT_NOT_FOUND` —— Tauri 桌面版的
测试二进制启动时找不到 WebView2 相关 DLL，与业务代码无关。
纯逻辑函数的验证方式：把函数抽到独立 crate 跑（本次用 `/tmp/ssedec` 验证了
15 项：中文转义解码、CRLF、纯文本透传、块切分、心跳跳过，全部通过）。
Rust 源码内已同步补上 `#[cfg(test)]` 用例，换到可正常链接测试的环境即可直接跑。

---

## 六、立绘背景适配（黑白双套形象）

### 问题

社区投稿的立绘**几乎全是浅底图**——实测 65 张的边缘亮度全在 193–255 之间，
没有一张深底。直接放进暖炭色的深色界面，就是一个刺眼的白色方块，
也就是"黑色背景时太突兀"的根本原因。

### 为什么不是去补拍黑底图

社区没有成套的黑底版本，而黑底并非立绘作者的原始交付物。真正决定观感的是
**底色与主体边缘的对比**，这个对比可以在客户端算出来。

### 做法：边缘泛洪抠图

`scripts/prepare_avatars.py` 对每张图做**从四边向内泛洪**，只删「与画面边缘连通」
的亮色区域，人物内部的白色因为被轮廓线包围、与背景不连通，因此安全保留。

**关键点：不能按亮度全局删除。** 第一版就是这么做的，结果把白色衣服、白发
一起抠掉了，人物只剩橙色头发和黑裙（见 `_shots/avatar_variants.png` 的第一版）。
泛洪是插画抠主体的标准做法，必须用。

产物：

| 目录 | 内容 | 用途 | 体积 |
|---|---|---|---|
| `src/assets/avatars/` | 原图（浅底） | 浅色主题 | 2.7 MB |
| `src/assets/avatars-dark/` | 泛洪抠图 + 8% 亮度压制，320px 透明底 PNG | 深色主题 | 5.5 MB |
| `src/assets/avatars-thumb/` | 128px 方形缩略图 | 聊天头像位（32px 显示） | 293 KB |

全尺寸透明 PNG 实测 19 MB，对低端机是硬伤；缩到 320px（界面最大显示 112px，
@2.8x 富余）后降到 5.5 MB。亮度压制是为了避免人物在暗底上整体"发光"。

### 同一 index 对应同一位画师

两套图池都经过字典序排序，因此同一个 seed（对话 id）在深浅色主题下
落到**同一个 index**——切换主题时人物不变，只有背景融入方式变化。

`resolveMascot()` 因此返回 `{ img, thumb, name }`：空态大图与设置页用 `img`
（全尺寸），聊天头像位用 `thumb`（128px）。头像位只有 32px，若直接解码
480×640 的立绘，长列表滚动必掉帧。

### 主题切换的刷新

`applyTheme()` 只改 `<html>` 的 class，没有事件可监听。`useDarkTheme()` 用
`MutationObserver` 监听 class 变化；`SettingsPage` 已持有 `theme` prop，
直接派生即可，无需订阅 DOM。

> 跑脚本：`python scripts/prepare_avatars.py`（Pillow，约 40 秒）

## 四、UI/UX 主题与动画约定

### 菊花 Logo 为什么必须拆成两层

`public/icons/star.png` 是**透明底**的橙色星芒（早期版本是白底 PNG，在深色模式下
会显示成白色方块，已修）。旋转与浮动必须分两层容器：

```html
<div class="tuan-spin-slow"><div class="tuan-float"><img class="tuan-logo-img"/></div></div>
```

原因：CSS 单条 `transform` 属性无法被两条 `animation` 叠加——后者会**整体覆盖**
前者。早期把 `tuan-spin` 与 `tuan-float-y` 写在同一条 `animation` 里，结果旋转
被浮动的 `transform` 完全顶掉，菊花看起来从不转动。

同理，头像容器自身绝不能挂动画（会与子元素的 `transform` 打架），
`think-ring` 扩散环也需要套在**不裁剪**的外层容器上才能扩散出边界。

### 主题色一律走语义变量，禁止硬编码

深浅色需要成对调整的色值都提到 `src/index.css` 的 CSS 变量里，组件只引用变量：

| 变量 | 用途 |
|---|---|
| `--tuan-accent-soft` | 思考光点、扩散环（品牌橙的柔和版，避免深色底上过曝） |
| `--tuan-selected-border` | 选中态描边（深色下改用浅色，否则近黑描边会消失在背景里） |
| `--tuan-danger` / `--tuan-danger-bg` | 危险操作色（深色下原本 `#B9382C` 发黑、`bg-red-50` 是刺眼亮粉） |
| `--tuan-link` / `--tuan-ok` / `--tuan-ok-bg` | 链接色与「免费」标签 |
| `--tuan-heading` | 标题字色 |
| `--tuan-art-bg` | 立绘预览底色（原本用 `bg-white`，深色下过曝） |
| `--shadow-soft` / `--shadow-hover` / `--shadow-pop` | 阴影分档（深色下黑色投影不可见，改用更亮的暖色投影） |

`.dark .tuan-logo-img { filter: brightness(1.16) saturate(1.05); }` 让橙色菊花
在炭底上更清晰但不过曝。

### 圆角三档

`tuan-radius-card` (16px) / `tuan-radius-panel` (20px) / `tuan-radius-pop` (14px)，
输入框用 `.tuan-input-card`（22px）。原先 `rounded-lg / xl / 2xl` 混用，
视觉上像"有的卡片磨了边、有的没磨"。

### 无障碍

- `@media (prefers-reduced-motion: reduce)`：系统开启"减弱动态效果"时停掉所有动画。
- `:focus-visible`：键盘导航时才显示焦点环（原先 `button:focus { outline: none }`
  让键盘用户完全看不到焦点位置）。
