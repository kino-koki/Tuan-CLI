# Tuan-CLI Android 原生运行方案

> 目标：让 Tuan-CLI 的 Agent 能力**在 Android 本地设备上以原生方式运行**——不依赖桌面 PC、不依赖浏览器、不依赖模拟器、不依赖云端中转。手机端既能调云端模型，也能跑量化后的本地 LLM。
>
> 文档版本：v1.0 · 2026-10-19 · 状态：方案评审

---

## 0. 一句话结论

**推荐分三阶段走"Termux → 混合应用 → Tauri Android"路径，用 6–9 个月把 Python 核心原封不动搬到手机**，不重写业务代码，只在边界层做适配。第一阶段（Termux PoC，2 周）就是价值验证。

三阶段的价值曲线：**阶段 1 交付真实可用的原生运行体验（Termux + pip），阶段 2 交付可上架的混合应用（Kotlin UI + Python 侧车），阶段 3 交付与桌面 Tuan-App 一致的 Tauri Android 应用。** 每阶段都能独立交付，不阻塞下一阶段。

---

## 1. 目标与非目标

### 1.1 目标（In Scope）

| 目标 | 验收标准 |
|---|---|
| G1 真原生运行 | Tuan-CLI 二进制/APK 在 Android 12+ 上无需 PC 参与启动 |
| G2 云端模型可用 | 通过系统 HTTP 栈调用 OpenAI/Anthropic/DeepSeek/Qwen 等 API |
| G3 本地 LLM 可选 | 通过 llama.cpp-Android 或 MediaPipe LLM 加载 GGUF/MLC 量化模型 |
| G4 完整 Agent 循环 | ReAct / Planner-Execute / DevLoop 三种主循环在手机上均可运行 |
| G5 安全红线不移除 | 危险命令拦截、事务账本、`/undo` 在 Android 上语义等价 |
| G6 文件系统可访问 | 通过 Android SAF（Storage Access Framework）或 Termux 内部目录访问用户代码 |
| G7 可分发 | APK 直发（GitHub Releases / F-Droid）；阶段 2 支持 Play Store 上架 |
| G8 包体积可控 | APK 全量 ≤ 200 MB；离线本地 LLM 模型不塞 APK，走用户下载 |

### 1.2 非目标（Out of Scope）

- ❌ **完全原生 Kotlin 重写**：几千行 Python 迁移到 Kotlin 需 8+ 人月，且失去与桌面 Tuan-CLI 的代码复用。
- ❌ **Tauri 1.x**：Android 支持从未 GA；只能走 Tauri 2.0。
- ❌ **Ollama on Android**：官方无 Android 支持，且需 Docker，Android 上无原生方案。
- ❌ **Play Store 首日首发**：Play Console 审核 + 合规文档需 1–2 月，阶段 1 与阶段 2 早期走 GitHub Releases sideload。
- ❌ **iOS**：不在本文档范围，但阶段 2 的 Kotlin→SwiftUI 迁移路径可复用（见 §8）。

---

## 2. 现状盘点（决定方案的关键约束）

### 2.1 Tuan-CLI 核心（Python）

```
Python:        3.10+（含 3.14）
核心依赖:      rich, httpx, prompt_toolkit, pyyaml, openai, pydantic v2, cryptography, typing_extensions
存储:          SQLite FTS5 + JSONL 事件流
加密:          AES-GCM（cryptography），含纯 Python CTR+HMAC 回退
CLI 入口:      tuan = tuan_cli.cli:main
包结构:        22 个核心子包 + 4 个插件目录
```

### 2.2 Tuan-App（Tauri 桌面壳）

```
位置:          F:\Tuan-CLI\Tuan-App\
技术栈:        Tauri 2.x + Rust 后端 + TypeScript/Vite 前端
已有产物:      Windows release/ 与 dist/
编译问题:      hs_err_pid*.log（JVM 崩溃日志，来自 Rust 编译期工具链）
Android 状态:  未启用（src-tauri/tauri.conf.json 未见 android 配置段）
```

### 2.3 平台敏感依赖分级

**⚠️ 关键发现**：`cryptography` 与 `pydantic` 是最难的两块骨头——它们都是 Rust 或 C 扩展。

| 依赖 | 原生扩展 | Android 打包难度 | 备注 |
|---|---|---|---|
| rich | 无 | ✅ 纯 Python | 终端输出库，Android Termux 兼容 |
| httpx | 无 | ✅ 纯 Python | 依赖 h11/httpcore 均纯 Python |
| prompt_toolkit | 无 | ✅ 纯 Python | 但依赖 curses 相关（Termux 可用） |
| pyyaml | 有 libyaml C 扩展 | ⚠️ 中等 | 有纯 Python 回退（PyYAML 的 C 扩展可选） |
| openai | 无 | ✅ 纯 Python | 依赖 httpx |
| pydantic | **pydantic-core（Rust）** | 🔴 困难 | Rust→Android NDK 交叉编译需 pydantic-core 官方支持 |
| cryptography | **Rust + OpenSSL** | 🔴 困难 | 需 OpenSSL for Android + Rust extension |

**结论**：Android 上最痛的两个依赖都是 Rust/C 扩展，必须依赖上游提供 Android wheel 或交叉编译方案。

### 2.4 Termux 环境现实（阶段 1 依赖）

- Termux 的包管理 (`pkg`) 已提供 `python`, `cryptography`, `pyyaml`, `numpy`, `scipy` 的 aarch64 预编译二进制。
- **但 `pydantic` 未在 Termux 官方仓库**——需要用 `pip install --only-binary=:all: pydantic`，看 PyPI 上是否有 `aarch64-linux-android` wheel（Pydantic 2.11+ 官方已提供 Android wheel）。
- Termux 的 shell 是 `/data/data/com.termux/files/usr/bin/bash`（bash 而非 sh），支持 bash 特性。

---

## 3. 六条路径对比

| 路径 | 真原生 | 代码复用 | 包体积 | 上架难度 | 上手成本 | 推荐度 |
|---|---|---|---|---|---|---|
| **A. Termux + pip** | ✅✅ 真原生 | 100% | 15–40 MB | 无法上架 | 用户会 Termux 才行 | ⭐⭐⭐⭐ 阶段 1 |
| **B. chrysalis-python-for-android 嵌入** | ✅ | 100% | 80–150 MB | 中等 | 中等（Python 运行时注入） | ⭐⭐⭐ 备选 |
| **C. PyOxidizer + Nuitka 打单二进制 + Kotlin UI** | ✅ | 100% | 100–180 MB | 中等 | 高（编译链复杂） | ⭐⭐ 备选 |
| **D. Tauri 2 Android + Python sidecar** | 半原生（WebView） | 100% | 80–120 MB + sidecar | 高（WebView + 沙箱） | 高（Tauri Android 尚不稳定） | ⭐⭐⭐⭐⭐ 阶段 3 |
| **E. Flutter + Rust 后端（重写核心）** | ✅ | 0% | 60–100 MB | 中等 | 极高（重写 8 人月） | ⭐ 不建议 |
| **F. Kotlin + Jetpack Compose + llama.cpp JNI** | ✅✅ 最原生 | 0% | 30–80 MB | 低 | 极高（重写 + LLM JNI） | ⭐⭐ 长期考虑 |

**核心判断**：
- 路径 A（Termux）是最诚实的"原生"，且**两周内可交付**。
- 路径 D（Tauri 2 Android）是与桌面 Tuan-App 一致的路径，但需要 Tauri Android 稳定化（当前 experimental → stable 需 3–6 个月）。
- 路径 E、F 是"放弃 Python"，短期不做。
- 路径 B、C 是折中，仅在 Tauri Android 卡住时启用。

---

## 4. 推荐路径：三阶段

```
阶段 1 (第 0-4 周)      阶段 2 (第 2-14 周)         阶段 3 (第 10-32 周)
┌─────────────────┐    ┌───────────────────────┐    ┌──────────────────────┐
│ Termux 原生 PoC  │ →  │ 混合应用 (Kotlin+Python) │ → │ Tauri 2 Android 生产 │
│                 │    │                       │    │                      │
│ pip install     │    │ Compose UI            │    │ WebView + Rust 后端   │
│ C 扩展预编译      │    │ Python sidecar (Unix   │    │ Python sidecar       │
│ LLM: MLC/llama  │    │ socket RPC)           │    │ 与阶段 2 共享 sidecar  │
│ 上架: F-Droid    │    │ 上架: GitHub/F-Droid    │    │ 上架: Play Store       │
└─────────────────┘    └───────────────────────┘    └──────────────────────┘
    ↑                     ↑                             ↑
  2 周可交付 PoC        4 周 MVP，可上架                  与桌面 Tuan-App 体验一致
```

**为什么这么排？**
- **阶段 1 是价值验证**：不写一行 Java/Kotlin/Rust，只调包配置和 Termux 适配脚本，2 周内验证"Tuan-CLI 真能在 Android 上跑起来"这个核心假设。
- **阶段 2 是产品化**：有了阶段 1 的成果，阶段 2 只是"给 Python 加个原生 UI 壳"，风险最低。
- **阶段 3 是体验统一**：Tauri 2 Android 稳定后可无缝替换阶段 2 的 UI 层，代码不用大改。

---

## 5. 阶段 1：Termux 原生 PoC（第 0-4 周）

### 5.1 交付物

- `tuan android setup` 子命令：一键在 Termux 上完成依赖安装与自检
- `install-termux.sh` 脚本：从 `pkg install python git` 到 `pip install tuan-cli` 全流程
- `docs/TERMUX.md`：面向 Termux 用户的完整手册
- `tests/android_termux/`：Termux 上的 CI 测试矩阵（GitHub Actions + Ubuntu 容器内 qemu-aarch64）

### 5.2 依赖改造清单

**必需改造**（不改无法工作）：

| 文件 | 改造内容 |
|---|---|
| `pyproject.toml` | 增加 `[project.optional-dependencies].termux` extra，列出 Termux 特化版本 |
| `tuan_cli/config/paths.py` | 增加 `is_termux()` 探测函数；`~/.tuan/` 在 Termux 下落到 `/data/data/com.termux/files/home/.tuan/` |
| `tuan_cli/ports/.../shell_tool.py` | 增加 Termux shell 探测（`/data/data/com.termux/files/usr/bin/bash` vs `/bin/sh`） |
| `tuan_cli/harden/blacklist.py` | Termux 特有命令特化规则（如 `termux-wake-lock`、`termux-battery-status`） |

**建议改造**（改造后体验更好）：

| 文件 | 改造内容 |
|---|---|
| `tuan_cli/models/local.py` | 新增 `TermuxMLCBackend`：调用 MLC LLM（Termux 上有 `mlc-llm` pip 包）加载 GGUF |
| `tuan_cli/cli/main.py` | 检测 Android 环境时跳过 `prompt_toolkit` 的交互式补全（触屏不友好），改为 `read()` 一行 |
| `install-termux.sh` | 新增：Termux bootstrap 脚本，检测架构、安装依赖、验证 |

### 5.3 关键难点与对策

**难点 1：pydantic-core 的 Android wheel**
- Pydantic 2.11+ 官方提供 `aarch64-linux-android` wheel。
- 对策：在 `install-termux.sh` 里 pin `pydantic>=2.11.0`，使用 `--only-binary=:all:`。
- 兜底：如果 wheel 不可用，切到 `pydantic 1.10`（无 Rust 扩展，但会失去 v2 的许多特性，需在 `pydantic` 兼容层做映射）。

**难点 2：cryptography 的 OpenSSL 依赖**
- Termux 自带 OpenSSL 3.x，`pkg install libcrypto` 即可。
- 对策：`install-termux.sh` 显式安装 `libcrypto libssl libssl-dev`。
- 兜底：Tuan-CLI 已内置纯 Python CTR+HMAC 回退（见 pyproject.toml 第 53 行注释），功能可用但非工业级。

**难点 3：SQLite FTS5**
- Android 的 system SQLite 通常不启用 FTS5。
- 对策：`pkg install sqlite`（Termux 自带独立 SQLite，含 FTS5 扩展），让 Python 优先链接 Termux 的 libsqlite3 而非 Android 系统版。

**难点 4：本地 LLM**
- **首选**：`mlc-llm`（Termux 支持，可加载 Qwen2.5-0.5B/1.5B 量化模型，约 300–800 MB）
- **备选**：`llama.cpp` C++ 版通过 `pkg install llama.cpp` 编译，Tuan-CLI 通过 subprocess 调用 `llama-cli`
- **不建议**：Ollama（无 Android 支持）

### 5.4 PoC 验收标准

- [ ] 一台干净的 Android 12 手机 + Termux → 20 分钟内 `tuan "hello"` 有响应
- [ ] `tuan safe bench` 在 Termux 上跑通，block recall ≥ 100%（安全语义等价）
- [ ] `tuan models local` 探测到 Termux MLC 或 llama.cpp 后端
- [ ] `tuan ecosystem link` 在 Termux 上启动 MCP server 供外部工具访问
- [ ] 完整 `/undo` 事务账本在 Termux 下正常落盘

### 5.5 时间估算

| 任务 | 人日 |
|---|---|
| Termux 环境搭建 + 依赖矩阵测试 | 2 |
| `is_termux()` 与路径适配 | 1 |
| 安全引擎 Termux 规则 | 1 |
| 本地 LLM 后端接入 | 3 |
| CI (qemu-aarch64) | 2 |
| 文档 + 分发脚本 | 2 |
| **合计** | **11 人日 / ~2.5 周** |

---

## 6. 阶段 2：混合应用（Kotlin UI + Python 侧车）（第 2-14 周）

### 6.1 交付物

- `Tuan-App/android/` 目录：原生 Android 工程（Kotlin + Jetpack Compose）
- `tuan_cli/ports/android_rpc/`：Python 侧 Unix socket RPC 服务
- `Tuan-App/engine/android-sidecar/`：Python 打包产物（Briefcase 或 chrysalis）
- `build-apk.sh`：一键构建 APK（含 Python sidecar）

### 6.2 架构

```
┌─────────────────────────────────────────────────────┐
│ Android OS (Linux 5.x kernel + ART)                  │
├─────────────────────────────────────────────────────┤
│ ┌─────────────────┐     ┌─────────────────────────┐ │
│ │ Kotlin UI 进程   │────▶│ Python 侧车进程           │ │
│ │ (Jetpack Compose)│ Unix│ (chrysalis/Briefcase)    │ │
│ │                 │ sock│                          │ │
│ │ - Chat 界面     │◀────│ - tuan_cli.core          │ │
│ │ - 工具执行展示   │ JSON│ - Loop (ReAct/Planner/Dev)│ │
│ │ - 文件选择器    │ RPC │ - Router + Models        │ │
│ │ - 安全事件流    │     │ - Security 引擎          │ │
│ └─────────────────┘     └─────────────────────────┘ │
│        │                            │                 │
│        ▼                            ▼                 │
│   Android SAF              Termux bash / toybox sh     │
│   (Storage Access FW)      (shell 工具执行)            │
└─────────────────────────────────────────────────────┘
```

### 6.3 关键技术选型

**Python 侧车打包**：
- **首选 chrysalis-python-for-android**：把整个 Python 环境（CPython + site-packages + 依赖）打包成 Android assets，运行时挂载到 `/data/data/<pkg>/files/python/`。优点：包体积可控（~80–150 MB）、依赖复用 Termux 验证过的 wheel。缺点：需要维护构建脚本。
- **备选 Briefcase**：BeeWare 出品，Android 支持较成熟，但打包产物偏大（~150–200 MB）。
- **不推荐 PyOxidizer + Nuitka**：编译链复杂，Android NDK 交叉编译容易踩坑。

**UI 层**：
- **Jetpack Compose**：现代 Android UI 框架，Kotlin DSL，与系统组件（权限对话框、文件选择器、通知栏）集成最好。
- **不选 Flutter**：增加一层引擎，包体积与内存占用偏高，且失去与 Kotlin 原生组件的集成优势。

**通信协议**：
- **Unix domain socket + JSON-RPC**：低延迟、无网络开销、Android 允许同 UID 进程间访问 socket。
- **消息格式**：复用 Tuan-CLI 现有的 `stream_json` 模块（已在仓库中），避免重新设计。

### 6.4 Python 侧改造

**新增模块 `tuan_cli/ports/android_rpc/`**：

```python
# 伪代码
class AndroidRPCServer:
    """在 Android 上启动 Unix socket server，接收 Kotlin UI 的 JSON-RPC 调用。"""
    
    async def start(self, socket_path: str):
        # 绑定到 Android 允许的 socket 路径
        # /data/data/<pkg>/cache/rpc.sock
        # 限制为当前 UID 可读
        ...
    
    def register_methods(self):
        self.route("agent.run", self._handle_agent_run)
        self.route("agent.undo", self._handle_undo)
        self.route("safe.score", self._handle_safe_score)
        self.route("models.list", self._handle_models_list)
        self.route("memory.search", self._handle_memory_search)
```

**关键点**：Python 侧车进程通过 Android 系统的 `/data/data/<pkg>/` 沙箱访问 Python 运行时和配置；文件读写工具（`read`/`write`/`edit`）通过 Kotlin UI 层转发 Android SAF URI，而不是直接访问文件系统。

### 6.5 安全模型在 Android 上的重新设计

原 CLI 的安全模型假设"用户在键盘前、能读终端输出"。在 Android 上这个假设不成立，需要重新映射：

| 原 CLI 机制 | Android 映射 | 说明 |
|---|---|---|
| `tuan safe bench` 危险命令拦截 | **系统层自动拦截 + 应用层白名单** | Android 沙箱天然阻止了 `rm -rf /` 这类动作（因为进程无 root）；应用层只需管住"应用自己发起的写操作" |
| YOLO / `--yolo` 跳过确认 | **保持语义等价** | 但"hard redline"名单在 Android 上大幅收缩——大部分红线已被系统层拦下 |
| `/undo` 事务账本 | **保留**，账本位置改到 `/data/data/<pkg>/tuan_ledger.db` | 语义不变 |
| 命令风险评分 | **特化规则集** | 增加 Android 特有命令（`am`、`adb`、`pm`、`monkey`）的风险评估；减少 shell 命令风险（大部分被沙箱兜住） |
| MCP/ACP 外部工具调用 | **Android 网络权限 + 端口限制** | Android 系统允许应用监听本地端口，但要走 `INTERNET` 权限 |

**新增的 Android 特有安全规则**（写入 `tuan_cli/harden/android_rules.py`）：

```python
# 新增红线：
# 1. 禁止通过 shell 执行 `am broadcast` 发送自定义 Intent（可能被恶意插件滥用）
# 2. 禁止 `adb shell` 调用（Android 上通常不可用，但侧车可能被劫持）
# 3. 禁止写入 `/data/local/tmp/`（非应用沙箱，风险高）
# 4. 禁止读取 `/data/data/com.android.shell/`（其他应用私有目录）
```

### 6.6 本地 LLM 方案

**首选：llama.cpp-Android**
- llama.cpp 官方支持 Android（有 `libllama.so` 的 JNI 桥接）
- 通过 Kotlin 侧调用 `llama-cli` 或 `llama-server`，Python 侧通过 RPC 获取结果
- 支持 GGUF 量化模型（Qwen2.5-0.5B/1.5B/3B，Llama 3.2 1B/3B）
- 内存需求：0.5B 模型 ~1 GB RAM，3B 模型 ~4 GB RAM（仅中高端手机可跑）

**备选：MLC LLM for Android**
- MLC 支持更全面的量化方案（包括 Q4/Q5/Q6/Q8）
- Termux 上有预编译包，但嵌入到混合应用需要额外编译

**模型分发策略**：
- 模型**不打包进 APK**（Play Store 限制 100 MB，模型动辄 500 MB–4 GB）
- 走"应用内下载"：用户在 UI 里选模型 → 后台下载到 `/data/data/<pkg>/models/`
- 或者指向用户自己的 HuggingFace / 网盘链接

### 6.7 存储与权限

**Android 11+ scoped storage 约束**：
- 应用默认只能访问自己的私有目录（`/data/data/<pkg>/`、`/storage/emulated/0/Android/data/<pkg>/`）
- 访问用户文档需要通过 SAF（Storage Access Framework）或请求 `MANAGE_EXTERNAL_STORAGE` 权限

**Tuan-CLI 的映射**：
- **配置文件**（`~/.tuan/config.yaml`）：映射到 `/data/data/<pkg>/tuan/config.yaml`
- **事务账本**：`/data/data/<pkg>/tuan_ledger.db`
- **用户代码文件**（Agent 主要操作对象）：通过 SAF 由用户在 UI 中授权具体目录，Python 侧接收 URI 后通过 ContentResolver 访问
- **技能与插件**：`/data/data/<pkg>/tuan/skills/`（APK 安装时解压）

**权限清单**（`AndroidManifest.xml`）：
```xml
<uses-permission android:name="android.permission.INTERNET"/>
<uses-permission android:name="android.permission.ACCESS_NETWORK_STATE"/>
<uses-permission android:name="android.permission.FOREGROUND_SERVICE"/>
<!-- 不申请 MANAGE_EXTERNAL_STORAGE，走 SAF -->
```

### 6.8 打包与分发

**APK 构建**：
- Gradle 构建 Kotlin UI（~20–30 MB）
- Python sidecar 打包为 assets（~80–150 MB）
- 总 APK ~100–180 MB
- 签名：阶段 2 用 debug keystore；上架 Play Store 前换 release keystore + Play App Signing

**分发渠道**：
- **阶段 2 早期**：GitHub Releases（sideload，用户需开启"未知来源"）
- **阶段 2 中期**：F-Droid（开源、无需 Google 账号、审核宽松）
- **阶段 2 后期**：Play Store（需合规文档、隐私政策、数据安全措施）

### 6.9 时间估算

| 任务 | 人日 |
|---|---|
| Android 工程脚手架（Gradle + Compose） | 3 |
| Python sidecar 打包（chrysalis 集成） | 5 |
| Unix socket RPC 协议 + 实现 | 5 |
| Kotlin UI（Chat + 工具执行展示 + 安全事件流） | 10 |
| 本地 LLM 集成（llama.cpp JNI） | 5 |
| SAF 文件访问 + 权限流程 | 5 |
| 安全模型 Android 特化 | 3 |
| CI/CD（GitHub Actions + Android NDK） | 3 |
| APK 签名 + F-Droid 打包 | 3 |
| **合计** | **42 人日 / ~8-10 周（2-3 人并行）** |

---

## 7. 阶段 3：Tauri 2 Android（第 10-32 周）

### 7.1 前置条件

- Tauri 2 Android 从 experimental → stable（当前 2.0.x 版本仍在稳定化，官方公告目标 2026 Q4 稳定）
- 桌面 Tuan-App 的 Rust 后端已在 CI 中通过 Android 交叉编译

### 7.2 迁移路径

阶段 3 **不是推倒重来**，而是在阶段 2 的 Python 侧车基础上，把 Kotlin UI 替换成 Tauri WebView：

```
阶段 2:                阶段 3:
┌──────────────┐      ┌──────────────┐
│ Kotlin UI    │  →   │ Tauri WebView │  ← 复用 Tuan-App 的 TS/React 前端
│ (Compose)    │      │ (Rust 后端)   │
├──────────────┤      ├──────────────┤
│ Python       │      │ Python        │  ← 复用阶段 2 的 sidecar 打包方案
│ sidecar      │      │ sidecar       │
└──────────────┘      └──────────────┘
```

**核心优势**：
- **前端代码复用**：桌面 Tuan-App 的 TypeScript/React 前端可以直接跑在 Android WebView 里，无需重写 UI
- **Rust 后端复用**：Tauri 的 Rust 命令（`#[tauri::command]`）可以直接暴露给前端
- **Python 侧车不变**：阶段 2 打好的 Python 打包方案继续用
- **桌面/Android 一份代码**：`tauri.conf.json` 的 `android` 段和 `windows/macos/linux` 段可以共存

### 7.3 关键难点

**难点 1：Tauri Android 的 sidecar 支持**
- Tauri 2 Android 目前对 sidecar（外挂二进制）的支持有限，需要确认 Python sidecar 是否可作为 `ExternalBin` 打包。
- 备选：把 Python 侧车进程作为 Android service 启动（独立进程，不通过 Tauri 管理），通过 Unix socket 通信（与阶段 2 相同）。

**难点 2：WebView 与 Termux shell 的交互**
- Tauri 的 WebView 无法直接启动 Termux 的 bash（Termux 是独立应用）。
- 对策：Python 侧车内部通过 `/data/data/com.termux/files/usr/bin/bash` 直接 spawn shell 命令，WebView 不感知 shell。

**难点 3：性能**
- WebView 比原生 UI 内存占用高（~100–200 MB 额外）。
- 对策：Tauri 2 使用系统 WebView（Android 12+ 是 Chromium），性能可接受。

### 7.4 时间估算

| 任务 | 人日 |
|---|---|
| Tauri 2 Android 稳定化跟踪 | 2（跨团队，非全职） |
| Rust 后端 Android 交叉编译 | 5 |
| 前端 WebView 适配（移动屏幕尺寸） | 5 |
| Sidecar 集成（若 Tauri 支持）或独立 service | 5 |
| APK 重打包 + 上架 | 5 |
| **合计** | **22 人日 / ~4-5 周（Tauri Android 稳定后）** |

---

## 8. 附录 A：本地 LLM 详细方案对比

| 方案 | 模型格式 | 内存需求 | Termux 支持 | APK 嵌入支持 | 推荐 |
|---|---|---|---|---|---|
| **MLC LLM** | ONNX + TFLite | 1–8 GB | ✅ `pkg install mlc-llm` | ✅ 需交叉编译 | ⭐⭐⭐⭐ |
| **llama.cpp** | GGUF | 1–8 GB | ✅ `pkg install llama.cpp` | ✅ 官方 JNI 桥接 | ⭐⭐⭐⭐⭐ |
| **MediaPipe LLM** | MediaPipe LLM 格式 | 1–4 GB | ⚠️ 社区包 | ✅ Google 官方 Android SDK | ⭐⭐⭐ |
| **Piper TTS** | ONNX | 100 MB–1 GB | ✅ | ✅ | ⭐⭐⭐ 语音合成，非 LLM |
| **Ollama** | GGUF | - | ❌ | ❌ | 不可用 |
| **Transformers (HF)** | 多种 | 2–16 GB | ✅ 但需 torch | ⚠️ 巨大 | 不推荐 |

**推荐组合**：
- 阶段 1（Termux）：`llama.cpp` + Qwen2.5-0.5B Q4（~300 MB 模型，1 GB RAM）
- 阶段 2（混合应用）：`llama.cpp-Android JNI` + Qwen2.5-1.5B Q4（~1 GB 模型，3 GB RAM）
- 阶段 3（Tauri Android）：同阶段 2

---

## 9. 附录 B：Android 上的安全模型差异

| 攻击面 | 桌面 CLI | Android | 差异说明 |
|---|---|---|---|
| 文件系统破坏（`rm -rf /`） | 需要用户输入密码 | 系统沙箱自动阻止 | Android 天然更安全 |
| 网络外泄 | 依赖防火墙 | Android 网络权限 + 后台限制 | Android 12+ 默认限制后台网络 |
| 命令注入 | 高风险（shell 直接执行） | 中风险（Termux shell 仍可用） | 需特化 Android 命令规则 |
| 插件滥用 | 高（可执行任意 Python） | 中（仍需 Python 运行时权限） | 需插件签名验证 |
| 凭据窃取 | 依赖环境变量 | Android Keystore 更强 | 建议把 API Key 存 Keystore |
| Agent 行为审计 | 用户能看终端输出 | UI 必须展示所有安全事件 | UI 层强制展示 |

**新增的 Android 特有红线**（在 `harden/android_rules.py` 中）：
1. 禁止写入 `/data/local/tmp/`（非应用沙箱）
2. 禁止执行 `am broadcast` 发送自定义 Intent
3. 禁止读取其他应用私有目录（`/data/data/<other_pkg>/`）
4. 禁止通过 shell 调用 `pm install`（安装应用需用户显式确认）
5. 禁止 `adb shell`（如果侧车被劫持）

---

## 10. 附录 C：分发与合规

### 10.1 Play Store 合规清单

- [ ] **隐私政策**：声明 API Key 存储位置、模型下载来源、数据是否上传第三方
- [ ] **数据安全表**（DST）：列出所有收集的数据类型
- [ ] **应用访问权限**：申请 `INTERNET`、`FOREGROUND_SERVICE`；**不申请** `MANAGE_EXTERNAL_STORAGE`
- [ ] **内容审核**：Agent 输出可能包含生成内容，需声明"应用内包含 AI 生成内容"
- [ ] **目标年龄**：13+（含 LLM 交互，无儿童隐私风险）
- [ ] **代码签名**：Play App Signing（Google 托管私钥）

### 10.2 F-Droid 合规清单

- [ ] 源码必须开源于 GitHub（✅ 项目已 MIT 开源）
- [ ] 所有依赖必须开源且可重现构建（⚠️ pydantic、cryptography 需要确认 F-Droid 构建器支持）
- [ ] APK 不能预装任何非 F-Droid 二进制
- [ ] 通过 F-Droid 构建器 CI 验证

### 10.3 直接 APK 分发（阶段 1）

- GitHub Releases（无审核，用户 sideload）
- 需要用户开启"未知来源"
- 提供 SHA256 校验和

---

## 11. 风险与应对

| 风险 | 概率 | 影响 | 应对 |
|---|---|---|---|
| Tauri 2 Android 持续不稳定 | 中 | 阶段 3 延期 | 阶段 2 已可独立交付，阶段 3 是"锦上添花" |
| pydantic-core Android wheel 不兼容 | 低 | 阶段 1 卡住 | 降级到 pydantic 1.10（有兼容层），或改用 pydantic-core 的 Rust 源交叉编译 |
| cryptography 在 Android 上性能差 | 中 | Agent 加密操作变慢 | 使用纯 Python CTR+HMAC 回退；或用 Android Keystore |
| Python sidecar 打包体积过大 | 中 | 应用上架受限 | 使用 chrysalis 精简依赖；模型走用户下载 |
| Android scoped storage 限制 Agent 文件访问 | 高 | 用户体验差 | 通过 SAF 让用户显式授权目录；提供"工作区"概念 |
| 本地 LLM 内存占用过大 | 高 | 低端手机不可用 | 提供 0.5B 量化模型（1 GB RAM）作为默认；3B+ 模型标注"需 6 GB+ RAM" |
| Play Store 审核被拒（Agent 行为不可预测） | 低 | 上架延期 | 提前准备 DST 和数据安全措施；阶段 2 早期走 GitHub/F-Droid |
| Termux 用户群体太小 | 高 | 阶段 1 商业价值低 | 阶段 1 是技术验证 + 极客用户运营；商业价值在阶段 2 |

---

## 12. 立即可做的 PoC 清单（本周内）

```bash
# Day 1: 环境验证
- [ ] 一台 Android 12 手机 + Termux
- [ ] pkg install python libcrypto sqlite git
- [ ] pip install pydantic==2.11.0 cryptography  # 验证 wheel 可用
- [ ] pip install tuan-cli  # 从 GitHub 主分支
- [ ] tuan --version  # 验证 CLI 启动

# Day 2-3: 核心依赖验证
- [ ] tuan models list  # 验证云端模型调用
- [ ] tuan safe bench --quick  # 验证安全引擎（子集）
- [ ] tuan memory search test  # 验证 SQLite FTS5
- [ ] tuan --yolo "写一个 hello.py 到 /tmp/"  # 验证工具链

# Day 4-5: 本地 LLM 验证
- [ ] pkg install llama.cpp
- [ ] 下载 Qwen2.5-0.5B Q4 GGUF (~300 MB)
- [ ] 通过 subprocess 调用 llama-cli，验证 Python 集成
- [ ] tuan models local  # 验证后端探测

# Day 6-7: 交付
- [ ] 写出 docs/TERMUX.md
- [ ] 写 install-termux.sh
- [ ] 提 PR 到 tuan_cli/config/paths.py 增加 is_termux()
```

**PoC 成功标准**：一台干净的 Android 12 手机，20 分钟内从安装 Termux 到跑通 `tuan "hello"`。

---

## 13. 总结

**推荐路径**：阶段 1（Termux，2-4 周）→ 阶段 2（混合应用，10 周）→ 阶段 3（Tauri Android，5 周 + 等 Tauri 稳定）。

**核心原则**：
1. **不重写 Python 核心**：Tuan-CLI 的 Agent 逻辑、安全引擎、Loop、Router 全部复用。
2. **Android 只做边界适配**：路径、shell、权限、UI、分发。
3. **分阶段交付**：每阶段独立可用，不阻塞后续阶段。
4. **本地 LLM 走用户下载**：不塞 APK，走模型商店或 HuggingFace。
5. **安全模型在 Android 上"系统层兜底 + 应用层特化"**：大部分红线由 Android 沙箱自然兜住，应用层专注 Agent 行为审计。

**下一步**：启动 PoC（Day 1 环境验证），验证 pydantic-core / cryptography 的 Android wheel 可用性。如果验证通过，进入阶段 1 正式开发。

---

*文档维护者：Tuan-CLI Android 工作流组*
*最后更新：2026-10-19*
*相关文档：[ARCHITECTURE.md](ARCHITECTURE.md) · [SECURITY.md](SECURITY.md) · [HARDENING.md](HARDENING.md)*
