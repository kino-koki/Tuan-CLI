//! 引擎桥接层：孵化内嵌 tuan_cli Web 工作台，把 SSE 事件流回传前端。
//!
//! 这是「与 TUI 功能对齐」的通道：引擎自带完整系统提示词（prompt_tier /
//! SOUL_FULL 分层）、工具调用、安全四道闸门、记忆与会话持久化——APP 不再
//! 直连模型 API 裸聊，而是让引擎跑真正的 Agent 循环。
//!
//! 协议（引擎 web/server.py）：
//!   POST /api/config/model {provider, model, api_key[, base_url, api_key_env]}
//!   POST /api/chat {message, session} -> SSE: session / delta / reason /
//!         tool / tool_result / error / done (+ `: hb` 心跳注释行)
//!   POST /api/stop   停止当前轮生成

use crate::engine::resolve_python;
use futures_util::StreamExt;
use serde::Serialize;
use std::io::Read;
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::OnceLock;
use std::time::{Duration, Instant};
use tauri::Manager;
#[cfg(windows)]
use std::os::windows::process::CommandExt;
#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x0800_0000;

const ENGINE_PORT: u16 = 8137;
const SPAWN_TIMEOUT: Duration = Duration::from_secs(30);
const READY_POLL: Duration = Duration::from_millis(250);
const CUSTOM_KEY_ENV: &str = "TUAN_APP_API_KEY";

/// 回传给前端的统一事件块（与 net.rs 的 Chunk 互补：多出 reason/tool 两类）。
#[derive(Debug, Serialize, Clone)]
pub struct Chunk {
    #[serde(rename = "type")]
    pub kind: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub text: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub name: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub args: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub out: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<String>,
}

fn chunk(kind: &str) -> Chunk {
    Chunk { kind: kind.into(), text: None, name: None, args: None, out: None, error: None }
}

fn text_chunk(t: String) -> Chunk {
    Chunk { kind: "text".into(), text: Some(t), name: None, args: None, out: None, error: None }
}

fn err_chunk(e: String) -> Chunk {
    Chunk { kind: "error".into(), text: None, name: None, args: None, out: None, error: Some(e) }
}

/// 从 stderr 里提取缺失的模块名（如 `ModuleNotFoundError: No module named 'rich'`）。
///
/// 目标机器若只装了 Python 却没跑过 `pip install -r requirements.txt`，
/// 引擎会在 import 阶段崩溃，用户看到一段看不懂的栈。这里把缺失的模块名
/// 抠出来，让错误提示直接指向可操作的安装命令，而不是让用户猜。
fn extract_missing_module(stderr: &str) -> Option<String> {
    let needle = "No module named '";
    let pos = stderr.find(needle)?;
    let rest = &stderr[pos + needle.len()..];
    let end = rest.find('\'')?;
    let name = rest[..end].trim();
    if name.is_empty() { None } else { Some(name.to_string()) }
}

/// 常驻引擎进程句柄（进程退出时自动回收子进程）。
struct EngineProc {
    child: Child,
}

impl Drop for EngineProc {
    fn drop(&mut self) {
        let _ = self.child.kill();
        let _ = self.child.wait();
    }
}

static ENGINE: OnceLock<tokio::sync::Mutex<Option<EngineProc>>> = OnceLock::new();

fn engine_lock() -> &'static tokio::sync::Mutex<Option<EngineProc>> {
    ENGINE.get_or_init(|| tokio::sync::Mutex::new(None))
}

fn base_url() -> String {
    format!("http://127.0.0.1:{ENGINE_PORT}")
}

/// 定位引擎根目录（含 tuan_cli/ 包）：打包布局 exe/engine > resource_dir > app_data_dir > 环境变量。
///
/// 不做任何项目目录假设（不再回退到 CARGO_MANIFEST_DIR），开发/自定义部署
/// 通过 TUAN_ENGINE_ROOT 显式指定。错误信息列出所有探测过的候选路径，
/// 便于用户排查安装是否完整。
fn engine_root(app: &tauri::AppHandle) -> Result<PathBuf, String> {
    let mut candidates: Vec<PathBuf> = Vec::new();
    // 桌面端才从 exe 目录找引擎；Android 的 Wry 运行时没有 executable_dir，
    // 且安卓端不内置本地引擎（对话走前端直连协议），此处跳过。
    #[cfg(not(target_os = "android"))]
    if let Ok(exe) = app.path().executable_dir() {
        // NSIS 安装布局：exe 同目录的 engine/
        candidates.push(exe.join("engine"));
        // 便携布局：exe 上一层（少数打包器把 exe 放到子目录）
        if let Some(parent) = exe.parent() {
            candidates.push(parent.join("engine"));
        }
    }
    // Tauri 2 在部分打包目标（deb / appimage / portable）会把 resources 放到
    // 独立目录，用 resource_dir() 兜底，避免换台设备/换安装方式时引擎目录找不到。
    if let Ok(rd) = app.path().resource_dir() {
        candidates.push(rd.join("engine"));
    }
    // app_data_dir 下也尝试一次（便携式用户可能手动放置）
    if let Ok(data) = app.path().app_data_dir() {
        candidates.push(data.join("engine"));
    }
    // 环境变量兜底（开发/自定义部署时指定引擎目录）
    if let Ok(v) = std::env::var("TUAN_ENGINE_ROOT") {
        candidates.push(PathBuf::from(v));
    }
    for c in candidates {
        if c.join("tuan_cli").join("__init__.py").is_file() {
            return Ok(c);
        }
    }
    // 把探测过的路径列出来，用户才能判断"是包没解压"还是"装在别处"
    let tried: Vec<String> = candidates
        .iter()
        .map(|p| format!("  - {}", p.join("tuan_cli").join("__init__.py").display()))
        .collect();
    Err(format!(
        "未找到引擎目录（tuan_cli 包）。已尝试以下位置：\n{}\n\n\
         若为开发环境：请确认 engine/tuan_cli/__init__.py 存在，\n\
         \  可运行 `python ../scripts/sync_engine_bundle.py` 同步引擎副本。\n\
         若为已安装设备：NSIS 应已把 engine/ 解压到安装目录，若缺失说明安装包不完整；\n\
         \  或设置环境变量 TUAN_ENGINE_ROOT 指向引擎根目录（含 tuan_cli/ 子目录）。",
        tried.join("\n")
    ))
}

/// 确保引擎 Web 服务在跑：已在跑则复用，否则孵化并等就绪。
async fn ensure_server(app: &tauri::AppHandle) -> Result<(), String> {
    // 已在跑（旧进程残留或本进程已孵化）：直接复用
    if let Ok(resp) = reqwest::get(format!("{}/api/info", base_url())).await {
        if resp.status().is_success() {
            return Ok(());
        }
    }
    let mut guard = engine_lock().lock().await;
    // 双检：锁内再探一次，避免并发双孵化
    if let Ok(resp) = reqwest::get(format!("{}/api/info", base_url())).await {
        if resp.status().is_success() {
            return Ok(());
        }
    }
    let root = engine_root(app)?;
    let python = resolve_python(root.parent().unwrap_or(&root)).map_err(|e| e.to_string())?;
    let data = app.path().app_data_dir().map_err(|e| e.to_string())?;
    let home = data.join("tuan-home");
    let ws = data.join("tuan-workspace");
    std::fs::create_dir_all(&home).map_err(|e| e.to_string())?;
    std::fs::create_dir_all(&ws).map_err(|e| e.to_string())?;

    let mut cmd = Command::new(&python);
    // Windows Python Launcher 需要 -3 参数指定 Python 3.x
    #[cfg(windows)]
    if python.file_name().and_then(|s| s.to_str()).map(|s| s == "py" || s == "py.exe").unwrap_or(false) {
        cmd.arg("-3");
    }
    cmd.arg("-m")
        .arg("tuan_cli")
        .arg("web")
        .arg("--host")
        .arg("127.0.0.1")
        .arg("--port")
        .arg(ENGINE_PORT.to_string())
        .arg("--workspace")
        .arg(&ws)
        .current_dir(&root)
        .env("TUAN_HOME", &home)
        .stdout(Stdio::null())
        .stderr(Stdio::piped());
    #[cfg(windows)]
    cmd.creation_flags(CREATE_NO_WINDOW);
    let mut child = cmd.spawn().map_err(|e| format!("引擎进程启动失败: {e}"))?;

    let deadline = Instant::now() + SPAWN_TIMEOUT;
    loop {
        // 提前退出：立即把 stderr 读出来报错，而不是让调用方干等
        if let Some(status) = child.try_wait().map_err(|e| e.to_string())? {
            let mut err = String::new();
            if let Some(mut s) = child.stderr.take() {
                let _ = s.read_to_string(&mut err);
            }
            let err_trimmed = err.trim().to_string();
            // 缺失依赖时给出可操作的 pip 命令，而不是把裸栈抛给用户
            let hint = if let Some(missing) = extract_missing_module(&err_trimmed) {
                format!(
                    "\n\n（解释器已找到，但缺少 Python 依赖 \"{missing}\"。请在引擎目录运行：\n\
                     \  pip install \"{missing}\"\n\
                     \  或一次装齐全部依赖：\n\
                     \  pip install -r \"<安装目录>\\engine\\requirements.txt\"）"
                )
            } else {
                String::new()
            };
            return Err(format!(
                "引擎提前退出（状态 {status}）：{}{}",
                if err_trimmed.is_empty() { "无 stderr 输出" } else { err_trimmed },
                hint
            ));
        }
        if let Ok(resp) = reqwest::get(format!("{}/api/info", base_url())).await {
            if resp.status().is_success() {
                break;
            }
        }
        if Instant::now() > deadline {
            let _ = child.kill();
            let _ = child.wait();
            // 超时也可能有 stderr（引擎卡在启动阶段但没退出），一并读出来
            let mut err = String::new();
            if let Some(mut s) = child.stderr.take() {
                let _ = s.read_to_string(&mut err);
            }
            let err_trimmed = err.trim().to_string();
            let detail = if err_trimmed.is_empty() {
                "无 stderr 输出（引擎可能卡在启动阶段或端口被占用）".to_string()
            } else {
                format!("stderr 末尾：{err_trimmed}")
            };
            return Err(format!(
                "引擎就绪超时（30s），进程已终止。\n{detail}\n\n\
                 请检查：\n\
                 1. 端口 {ENGINE_PORT} 是否被其他程序占用：\n\
                 \  netstat -ano | findstr {ENGINE_PORT}\n\
                 2. Python 依赖是否齐全：\n\
                 \  pip install -r \"<安装目录>\\engine\\requirements.txt\""
            ));
        }
        tokio::time::sleep(READY_POLL).await;
    }
    *guard = Some(EngineProc { child });
    Ok(())
}

/// 把前端选中的供应商/模型/密钥推给引擎配置（目录内直接推；目录外自定义端点带 base_url 重推）。
async fn push_model(client: &reqwest::Client, provider: &crate::net::Provider, model: &str) -> Result<(), String> {
    let url = format!("{}/api/config/model", base_url());
    let mut body = serde_json::json!({
        "provider": provider.name,
        "model": model,
        "api_key": provider.apiKey,
    });
    let resp = client
        .post(&url)
        .json(&body)
        .send()
        .await
        .map_err(|e| format!("推送供应商配置失败: {e}"))?;
    let j: serde_json::Value = resp
        .json()
        .await
        .map_err(|e| format!("配置响应解析失败: {e}"))?;
    if j["ok"] == true {
        return Ok(());
    }
    // 未知供应商：按自定义 OpenAI 兼容端点重推（需显式 base_url）
    body["base_url"] = serde_json::json!(provider.baseUrl);
    body["api_key_env"] = serde_json::json!(CUSTOM_KEY_ENV);
    let resp2 = client
        .post(&url)
        .json(&body)
        .send()
        .await
        .map_err(|e| format!("推送自定义供应商配置失败: {e}"))?;
    let j2: serde_json::Value = resp2
        .json()
        .await
        .map_err(|e| format!("自定义配置响应解析失败: {e}"))?;
    if j2["ok"] == true {
        return Ok(());
    }
    Err(format!(
        "模型配置失败: {}",
        j2["error"].as_str().unwrap_or("未知错误")
    ))
}

/// 从字节缓冲里取出第一块完整 SSE 块，返回去掉块尾空行后的字节。
///
/// SSE 规范允许两种块尾：LF 流是 `\n\n`，CRLF 流是 `\r\n\r\n`（即 `\n\r\n`）。
/// 旧实现只找 `\n\n`，遇到 CRLF 端点（不少第三方中转与自建服务就是 CRLF）会
/// 永远等不到分块标记——表现为"模型明明在生成、页面却始终不动"或整条流被
/// 拼接成一坨再一起解析出的"大量乱码"。这里两种块尾都认，且要求块尾完整
/// 落进缓冲后才切块（避免把半个 `\r\n` 当成块尾截断）。
fn take_sse_block(buf: &mut Vec<u8>) -> Option<Vec<u8>> {
    let len = buf.len();
    if len < 2 {
        return None;
    }
    for i in 0..len - 1 {
        if buf[i] != b'\n' {
            continue;
        }
        let terminus = if buf[i + 1] == b'\n' {
            // LF：本行结尾 + 空行
            Some(2usize)
        } else if buf[i + 1] == b'\r' && i + 2 < len && buf[i + 2] == b'\n' {
            // CRLF：`\n` + `\r\n`
            Some(3)
        } else {
            None
        };
        let Some(n) = terminus else { continue };
        let block: Vec<u8> = buf.drain(..i + n).collect();
        // 去掉结尾的 \n\n / \n\r\n
        Some(block[..block.len() - n].to_vec())
    }
    None
}

/// 解析 SSE 的 `data:` 负载。
///
/// 引擎发出的 data 一律是 JSON 编码的字符串（内层还有一层转义）：
/// 换行是 `\n`、引号是 `\"`、中文若未被 Rust 序列化器处理会是 `\uXXXX`。
/// 直接把原文当正文透传，会让用户看到 `\u4e2d\u6587` 这类"乱码参杂"。
/// 因此先尝试当作 JSON 字符串解析，成功则用解析结果；失败再退回原文
/// （兼容引擎降级为纯文本 delta 的情况）。
fn decode_sse_data(data: String) -> String {
    let trimmed = data.trim();
    if trimmed.is_empty() {
        return String::new();
    }
    // 纯文本 delta 不带引号，JSON 解析必然失败，直接返回
    if !trimmed.starts_with('"') {
        return data;
    }
    if let Ok(s) = serde_json::from_str::<String>(trimmed) {
        return s;
    }
    // 同一事件的多个 data 行会用真实换行拼接，若这段正文原本是 JSON 字符串里
    // 被转义成 \n 的换行，拼接后就变成了裸控制字符 —— JSON 字符串内不允许裸
    // 控制字符，解析必然失败。把裸换行重新转义后再试一次，避免正文被截断或
    // 带着未剥除的引号显示出来。
    let repaired = trimmed.replace('\n', "\\n").replace('\r', "\\r");
    serde_json::from_str::<String>(&repaired).unwrap_or(data)
}

/// 解析一块 SSE，映射为 Chunk；心跳注释行返回 None（跳过）。
fn parse_sse_block(block: &[u8]) -> Option<Chunk> {
    let mut event: Option<String> = None;
    let mut data: Option<String> = None;
    for line in block.split(|&b| b == b'\n') {
        // 容忍 \r\n：SSE 规范允许行尾 CRLF，不去会让 trim 之外的 \r 混进正文
        let line = line.strip_suffix(b"\r").unwrap_or(line);
        if line.starts_with(b"event:") {
            event = Some(String::from_utf8_lossy(&line[6..]).trim().to_string());
        } else if line.starts_with(b"data:") {
            // SSE 规范：同一事件可有多行 data，各行的值要用 \n 拼接。
            // 旧实现直接覆盖，遇到多行 data 只会留下最后一段——正文被截断
            // 成半句，或多段挤在一起看起来像乱码。
            let piece = String::from_utf8_lossy(&line[5..]).trim().to_string();
            data = Some(match data.take() {
                Some(prev) => format!("{prev}\n{piece}"),
                None => piece,
            });
        } else if line.starts_with(b":") {
            return None; // 心跳 `: hb`
        }
    }
    let ev = event?;
    let data = decode_sse_data(data.unwrap_or_default());
    match ev.as_str() {
        "session" => None, // 会话已建，前端不需要
        "delta" => Some(text_chunk(data)),
        "reason" => Some(Chunk {
            kind: "reason".into(),
            text: Some(data),
            name: None,
            args: None,
            out: None,
            error: None,
        }),
        "tool" => {
            let Ok(j) = serde_json::from_str::<serde_json::Value>(&data) else {
                return None;
            };
            Some(Chunk {
                kind: "tool".into(),
                text: None,
                name: j["name"].as_str().map(String::from),
                args: j["args"].as_str().map(String::from),
                out: None,
                error: None,
            })
        }
        "tool_result" => {
            let Ok(j) = serde_json::from_str::<serde_json::Value>(&data) else {
                return None;
            };
            Some(Chunk {
                kind: "tool_result".into(),
                text: None,
                name: j["name"].as_str().map(String::from),
                args: None,
                out: j["out"].as_str().map(String::from),
                error: None,
            })
        }
        "approval" => {
            // 危险工具调用触发了引擎安全闸门：引擎把审批请求推进 SSE 后**阻塞**
            // 等我们答复，300 秒内不答复就 fail-closed 拒绝（server.py 的
            // _ask_approval）。旧实现这里没有分支，事件被 parse_sse_block 静默
            // 丢弃，用户只能对着转圈空等五分钟然后莫名失败。
            // 字段复用现有结构：name=id（回传用）、text=prompt（给用户看）、
            // args=verdict 的 JSON（risk/reasons/blast_radius/suggestions）。
            let Ok(j) = serde_json::from_str::<serde_json::Value>(&data) else {
                return Some(text_chunk(data));
            };
            Some(Chunk {
                kind: "approval".into(),
                text: Some(j["prompt"].as_str().unwrap_or("").to_string()),
                name: j["id"].as_str().map(String::from),
                args: j.get("verdict").map(|v| v.to_string()),
                out: None,
                error: None,
            })
        }
        "error" => {
            let Ok(j) = serde_json::from_str::<serde_json::Value>(&data) else {
                return Some(err_chunk(data));
            };
            Some(err_chunk(
                j["message"].as_str().unwrap_or(&data).to_string(),
            ))
        }
        "done" => Some(chunk("done")),
        _ => None,
    }
}

/// 引擎聊天流：确保引擎服务 → 推供应商配置 → POST /api/chat → SSE 事件逐块回传。
#[tauri::command]
pub async fn engine_chat_stream(
    app: tauri::AppHandle,
    provider: crate::net::Provider,
    model: String,
    message: String,
    session: String,
    channel: tauri::ipc::Channel<Chunk>,
) -> Result<(), String> {
    // 安卓端不内置本地 Python 引擎，无法孵化引擎进程。
    // 前端已改走 chat_stream 直连协议，这里仅作兜底，避免误调用时白等引擎查找。
    #[cfg(target_os = "android")]
    {
        let _ = (app, provider, model, message, session, channel);
        return Err("Android 端未内置本地引擎，请使用直连协议通道".into());
    }

    #[cfg(not(target_os = "android"))]
    {
        engine_chat_stream_desktop(app, provider, model, message, session, channel).await
    }
}

#[cfg(not(target_os = "android"))]
async fn engine_chat_stream_desktop(
    app: tauri::AppHandle,
    provider: crate::net::Provider,
    model: String,
    message: String,
    session: String,
    channel: tauri::ipc::Channel<Chunk>,
) -> Result<(), String> {
    ensure_server(&app).await?;
    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(300))
        .build()
        .map_err(|e| format!("网络客户端初始化失败：{e}"))?;
    push_model(&client, &provider, &model).await?;

    let chat_body = serde_json::json!({ "message": message, "session": session });
    let resp = client
        .post(format!("{}/api/chat", base_url()))
        .json(&chat_body)
        .send()
        .await
        .map_err(|e| format!("聊天请求失败：{e}"))?;
    if !resp.status().is_success() {
        return Err(format!("聊天接口返回 {}", resp.status()));
    }
    let mut stream = resp.bytes_stream();
    let mut buf: Vec<u8> = Vec::new();
    while let Some(part) = stream.next().await {
        let part = part.map_err(|e| format!("读取事件流失败：{e}"))?;
        buf.extend_from_slice(&part);
        while let Some(block) = take_sse_block(&mut buf) {
            let Some(ck) = parse_sse_block(&block) else { continue };
            if channel.send(ck).is_err() {
                // 前端已断开（停止生成/关页面）：取消本轮，别让 agent 白跑
                let _ = client
                    .post(format!("{}/api/stop", base_url()))
                    .send()
                    .await;
                return Ok(());
            }
        }
    }
    Ok(())
}

/// 停止当前轮生成（对标 TUI 的 Ctrl+C / 停止按钮）。
#[tauri::command]
pub async fn engine_stop(app: tauri::AppHandle) -> Result<(), String> {
    // 安卓端无本地引擎：聊天走 chat_stream 直连协议，不存在引擎会话可停。
    // 直接返回，避免 ensure_server 白跑一遍引擎查找。
    #[cfg(target_os = "android")]
    {
        let _ = app;
        return Ok(());
    }

    #[cfg(not(target_os = "android"))]
    {
        let _ = ensure_server(&app).await; // 服务不在则不动作
        let _ = reqwest::Client::new()
            .post(format!("{}/api/stop", base_url()))
            .send()
            .await;
        Ok(())
    }
}

/// 危险操作审批回传。
///
/// 引擎在 `_ask_approval` 里阻塞等这个答复；不给答复它 300 秒后自动按拒绝处理。
/// `decision` 只认 `"allow"`，其余一律按 `"deny"` —— 缺省即拒绝，符合 fail-closed。
#[tauri::command]
pub async fn engine_approve(
    app: tauri::AppHandle,
    id: String,
    decision: String,
) -> Result<bool, String> {
    // 安卓端不内置本地引擎，不存在审批上下文可回传。
    #[cfg(target_os = "android")]
    {
        let _ = (app, id, decision);
        return Ok(false);
    }

    #[cfg(not(target_os = "android"))]
    {
        let _ = ensure_server(&app).await; // 服务不在则不动作
        let decision_norm = if decision.trim().eq_ignore_ascii_case("allow") {
            "allow"
        } else {
            "deny"
        };
        let client = reqwest::Client::new();
        let resp = client
            .post(format!("{}/api/approve", base_url()))
            .json(&serde_json::json!({ "id": id, "decision": decision_norm }))
            .send()
            .await
            .map_err(|e| format!("审批请求失败：{e}"))?;
        let j: serde_json::Value = resp
            .json()
            .await
            .map_err(|e| format!("审批响应解析失败：{e}"))?;
        Ok(j["ok"].as_bool().unwrap_or(false))
    }
}

/// 从引擎包目录读取真实版本号（`tuan_cli/version.py` 的 `__version__`）。
///
/// 之前这里返回 `env!("CARGO_PKG_VERSION")` —— 那是 Tauri 外壳的版本，
/// 却在界面上被当成"引擎版本"显示，用户会误以为引擎升级了。
/// 引擎版本必须从引擎自己的包定义里读，读不到时返回空串而非编造。
fn read_engine_version(root: &std::path::Path) -> String {
    let path = root.join("tuan_cli").join("version.py");
    let Ok(text) = std::fs::read_to_string(&path) else {
        return String::new();
    };
    for line in text.lines() {
        let line = line.trim();
        if let Some(rest) = line.strip_prefix("__version__") {
            let rest = rest.trim_start();
            let Some(eq) = rest.strip_prefix("=") else { continue };
            let value = eq.trim().trim_matches('"').trim_matches('\'').to_string();
            if !value.is_empty() {
                return value;
            }
        }
    }
    String::new()
}

/// 启动时引擎自检：定位引擎目录 + Python 解释器，返回可用性状态。
///
/// 前端在应用启动时调用，用于显示"引擎就绪/不可用"状态指示器，
/// 以及引擎不可用时自动降级到直连协议（纯对话模式）。
#[tauri::command]
pub async fn check_engine(app: tauri::AppHandle) -> Result<serde_json::Value, String> {
    #[cfg(target_os = "android")]
    {
        let _ = app;
        return Ok(serde_json::json!({
            "ok": false,
            "android": true,
            "app_version": env!("CARGO_PKG_VERSION"),
            "reason": "Android 端不内置本地引擎，聊天走直连协议通道",
        }));
    }

    #[cfg(not(target_os = "android"))]
    {
        let root = match engine_root(&app) {
            Ok(r) => r,
            Err(e) => {
                return Ok(serde_json::json!({
                    "ok": false,
                    "step": "engine_root",
                    "app_version": env!("CARGO_PKG_VERSION"),
                    "reason": e,
                }));
            }
        };
        let python = match crate::engine::resolve_python(root.parent().unwrap_or(&root)) {
            Ok(p) => p,
            Err(e) => {
                return Ok(serde_json::json!({
                    "ok": false,
                    "step": "python",
                    "app_version": env!("CARGO_PKG_VERSION"),
                    "engine_root": root.to_string_lossy().to_string(),
                    "reason": e.to_string(),
                }));
            }
        };
        Ok(serde_json::json!({
            "ok": true,
            "step": "ok",
            "app_version": env!("CARGO_PKG_VERSION"),
            "engine_version": read_engine_version(&root),
            "engine_root": root.to_string_lossy().to_string(),
            "python": python.to_string_lossy().to_string(),
        }))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn decode_unwraps_json_encoded_text() {
        // 引擎的 data 是 JSON 字符串，内层 \n 是转义的换行。
        // 原实现直接透传，用户会看到字面量的 \n 与 \" —— 即"乱码参杂"。
        let raw = r#""第一行\n第二行含\"引号\"""#.to_string();
        assert_eq!(decode_sse_data(raw), "第一行\n第二行含\"引号\"");
    }

    #[test]
    fn decode_passes_through_plain_text() {
        // 引擎降级为纯文本 delta 时（无引号），必须原样返回而不是解析失败
        let raw = "这是一段中文，可能带换行和 & < > 符号".to_string();
        assert_eq!(decode_sse_data(raw.clone()), raw);
        // 空串与首尾空白
        assert_eq!(decode_sse_data("   ".into()), "");
    }

    #[test]
    fn parse_delta_does_not_leak_escapes() {
        // 端到端：一整块 SSE
        let block = b"event: delta\ndata: \"\\u4f60\\u597d\\u4e16\\u754c\"\n" as &[u8];
        let c = parse_sse_block(block).expect("应解析出 delta");
        assert_eq!(c.kind, "text");
        assert_eq!(c.text.as_deref(), Some("你好世界"));
    }

    #[test]
    fn parse_handles_crlf_line_endings() {
        // SSE 规范允许 CRLF。行尾的 \r 若不去掉会混进正文末尾
        let block = b"event: delta\r\ndata: \"ok\"\r\n" as &[u8];
        let c = parse_sse_block(block).expect("应解析出 delta");
        assert_eq!(c.text.as_deref(), Some("ok"));
    }

    #[test]
    fn parse_skips_heartbeat_and_session() {
        assert!(parse_sse_block(b": hb\n\n".as_slice()).is_none());
        assert!(parse_sse_block(b"event: session\ndata: \"{}\"".as_slice()).is_none());
        assert!(parse_sse_block(b"event: unknown\ndata: x".as_slice()).is_none());
    }

    #[test]
    fn take_block_splits_on_double_newline() {
        let mut buf = b"event: a\ndata: 1\n\nevent: b\ndata: 2\n\n".to_vec();
        let b1 = take_sse_block(&mut buf).expect("第一块");
        assert_eq!(String::from_utf8(b1).unwrap(), "event: a\ndata: 1");
        let b2 = take_sse_block(&mut buf).expect("第二块");
        assert_eq!(String::from_utf8(b2).unwrap(), "event: b\ndata: 2");
        assert!(take_sse_block(&mut buf).is_none(), "应已取空");
    }

    #[test]
    fn take_block_accepts_crlf_terminator() {
        // CRLF 端点：块尾是 \r\n\r\n。旧实现只认 \n\n，会把整条流挂住。
        let mut buf = b"event: a\r\ndata: \"1\"\r\n\r\nevent: b\r\ndata: \"2\"\r\n\r\n".to_vec();
        let b1 = take_sse_block(&mut buf).expect("CRLF 第一块");
        assert_eq!(
            String::from_utf8(b1).unwrap(),
            "event: a\r\ndata: \"1\""
        );
        let b2 = take_sse_block(&mut buf).expect("CRLF 第二块");
        assert_eq!(String::from_utf8(b2).unwrap(), "event: b\r\ndata: \"2\"");
        assert!(take_sse_block(&mut buf).is_none());
    }

    #[test]
    fn take_block_waits_for_partial_crlf_terminator() {
        // 缓冲里只有半个块尾（\r\n），必须等下一个分片，不能误切。
        let mut buf = b"event: a\r\ndata: \"1\"\r\n".to_vec();
        assert!(take_sse_block(&mut buf).is_none(), "块尾不完整应等待");
        buf.extend_from_slice(b"\r\n");
        let b1 = take_sse_block(&mut buf).expect("补上块尾后应可取");
        assert_eq!(String::from_utf8(b1).unwrap(), "event: a\r\ndata: \"1\"");
    }

    #[test]
    fn parse_multiline_data_joins_with_newline() {
        // 同一事件的多个 data 行按规范用 \n 拼接；旧实现只留最后一行，正文被截断。
        let block = br#"event: delta
data: 第一段
data: 第二段"#;
        let c = parse_sse_block(block).expect("应解析出 delta");
        assert_eq!(c.kind, "text");
        assert_eq!(c.text.as_deref(), Some("第一段\n第二段"));
    }

    #[test]
    fn decode_repairs_newline_split_across_data_lines() {
        // JSON 字符串里的换行被 data 多行拼接还原成裸换行后，
        // JSON 解析会失败；还原转义后再解析应能得到完整正文。
        let raw = "\"第一段\n第二段\"".to_string();
        assert_eq!(decode_sse_data(raw), "第一段\n第二段");
    }

    #[test]
    fn decode_falls_back_to_raw_when_unrepairable() {
        // 无法修复时原样返回，不丢内容
        let raw = "\"这不是合法 JSON".to_string();
        assert_eq!(decode_sse_data(raw.clone()), raw);
    }

    #[test]
    fn tool_result_decodes_json_object() {
        // tool / tool_result 分支本就有 JSON 解析，锁住它不退化
        let block = br#"event: tool_result
data: {"name":"calc","out":"42"}
"#;
        let c = parse_sse_block(block).expect("应解析出 tool_result");
        assert_eq!(c.kind, "tool_result");
        assert_eq!(c.name.as_deref(), Some("calc"));
        assert_eq!(c.out.as_deref(), Some("42"));
    }

    #[test]
    fn approval_parses_prompt_id_and_verdict() {
        // 引擎安全闸门会阻塞等审批；事件被丢弃就等于用户对着转圈空等五分钟
        let block = br#"event: approval
data: {"id":"a1b2c3","prompt":"rm -rf ./out","verdict":{"risk":"high","reasons":["递归删除"],"blast_radius":"workspace","suggestions":["先确认目录"]}}
"#;
        let c = parse_sse_block(block).expect("应解析出 approval");
        assert_eq!(c.kind, "approval");
        assert_eq!(c.name.as_deref(), Some("a1b2c3"));
        assert_eq!(c.text.as_deref(), Some("rm -rf ./out"));
        let Some(args) = c.args.as_deref() else {
            panic!("verdict 应原样转发，供 UI 展示风险分析");
        };
        let v: serde_json::Value = serde_json::from_str(args).expect("verdict 应为 JSON");
        assert_eq!(v["risk"], "high");
        assert_eq!(v["suggestions"][0], "先确认目录");
        assert!(c.error.is_none(), "审批事件不是错误");
    }

    #[test]
    fn approval_missing_id_still_surfaces_prompt() {
        // id 缺失时仍要把 prompt 展示出来，只是无法回传答复
        let block = br#"event: approval
data: {"prompt":"rm -rf ./out"}
"#;
        let c = parse_sse_block(block).expect("应解析出 approval");
        assert_eq!(c.kind, "approval");
        assert!(c.name.is_none(), "缺 id 不应编造");
        assert_eq!(c.text.as_deref(), Some("rm -rf ./out"));
    }

    #[test]
    fn read_engine_version_picks_up_version_py() {
        // 引擎版本必须来自引擎自己的包定义，不能拿外壳版本号冒充
        let dir = std::env::temp_dir().join("tuan-test-version");
        let pkg = dir.join("tuan_cli");
        std::fs::create_dir_all(&pkg).unwrap();
        std::fs::write(
            pkg.join("version.py"),
            "# docstring\n__version__ = \"0.3.1\"\nOTHER = 1\n",
        ).unwrap();
        assert_eq!(read_engine_version(&dir), "0.3.1");
        std::fs::remove_dir_all(&dir).ok();
    }

    #[test]
    fn read_engine_version_empty_when_absent() {
        let dir = std::env::temp_dir().join("tuan-test-version-missing");
        std::fs::create_dir_all(&dir).unwrap();
        assert_eq!(read_engine_version(&dir), "");
        std::fs::remove_dir_all(&dir).ok();
    }

    #[test]
    fn extract_missing_module_picks_out_name() {
        // 真实 stderr 形如：
        //   ModuleNotFoundError: No module named 'rich'
        //   ModuleNotFoundError: No module named 'tuan_cli.deps'  （子模块）
        let s = "Traceback (most recent call last):\n  File ...\nModuleNotFoundError: No module named 'rich'";
        assert_eq!(extract_missing_module(s), Some("rich".into()));

        let s2 = "ModuleNotFoundError: No module named 'tuan_cli.deps.openai_client'";
        assert_eq!(extract_missing_module(s2), Some("tuan_cli.deps.openai_client".into()));
    }

    #[test]
    fn extract_missing_module_returns_none_when_absent() {
        assert_eq!(extract_missing_module(""), None);
        assert_eq!(extract_missing_module("引擎进程提前退出，无 stderr"), None);
        // 引号不完整时不硬抠
        assert_eq!(extract_missing_module("ModuleNotFoundError: No module named 'rich"), None);
    }
}
