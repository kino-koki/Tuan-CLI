// 原生网络层：在 Rust 侧发起 HTTP，绕开 WebView 的跨域(CORS)限制，
// 通过 Tauri Channel 把 SSE 分片回传前端。Windows 与 Android 共用。
use futures_util::StreamExt;
use serde::{Deserialize, Serialize};
use std::time::Duration;

#[derive(Debug, Deserialize, Clone)]
pub struct Provider {
    #[serde(default)]
    pub id: String,
    #[serde(default)]
    pub name: String,
    pub baseUrl: String,
    #[serde(default)]
    pub format: String,
    #[serde(default)]
    pub apiKey: String,
}

#[derive(Debug, Deserialize, Clone)]
pub struct Msg {
    pub role: String,
    pub content: String,
}

#[derive(Debug, Serialize, Clone)]
pub struct Chunk {
    #[serde(rename = "type")]
    kind: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    text: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    error: Option<String>,
}

fn text(t: String) -> Chunk {
    Chunk { kind: "text".into(), text: Some(t), error: None }
}
fn done() -> Chunk {
    Chunk { kind: "done".into(), text: None, error: None }
}
fn err(e: String) -> Chunk {
    Chunk { kind: "error".into(), text: None, error: Some(e) }
}

fn clean_base(base: &str) -> String {
    base.trim_end_matches('/').to_string()
}

#[tauri::command]
pub async fn chat_stream(
    provider: Provider,
    model: String,
    history: Vec<Msg>,
    channel: tauri::ipc::Channel<Chunk>,
) -> Result<(), String> {
    let client = reqwest::Client::builder()
        // 整体超时放宽到 300s：长答案/慢模型不能在 120s 被误杀；连接仍单独 20s 超时
        .timeout(Duration::from_secs(300))
        .connect_timeout(Duration::from_secs(20))
        .build()
        .map_err(|e| format!("网络客户端初始化失败：{e}"))?;

    let base = clean_base(&provider.baseUrl);
    let is_anthropic = provider.format == "anthropic";

    let resp = if is_anthropic {
        let system = history
            .iter()
            .filter(|m| m.role == "system")
            .map(|m| m.content.clone())
            .collect::<Vec<_>>()
            .join("\n");
        let messages: Vec<serde_json::Value> = history
            .iter()
            .filter(|m| m.role != "system")
            .map(|m| {
                serde_json::json!({ "role": if m.role == "assistant" { "assistant" } else { "user" }, "content": m.content })
            })
            .collect();
        client
            .post(format!("{base}/v1/messages"))
            .header("Content-Type", "application/json")
            .header("x-api-key", &provider.apiKey)
            .header("anthropic-version", "2023-06-01")
            .json(&serde_json::json!({
                "model": model,
                "max_tokens": 4096,
                "system": if system.is_empty() { None } else { Some(system) },
                "messages": messages,
                "stream": true
            }))
            .send()
            .await
    } else {
        let messages: Vec<serde_json::Value> = history
            .iter()
            .map(|m| serde_json::json!({ "role": m.role, "content": m.content }))
            .collect();
        client
            .post(format!("{base}/chat/completions"))
            .header("Content-Type", "application/json")
            .header("Authorization", format!("Bearer {}", provider.apiKey))
            .json(&serde_json::json!({ "model": model, "messages": messages, "stream": true }))
            .send()
            .await
    };

    let resp = match resp {
        Ok(r) => r,
        Err(e) => {
            let _ = channel.send(err(format!("连接失败：{e}（请检查地址、网络与密钥）")));
            return Ok(());
        }
    };

    let status = resp.status();
    if !status.is_success() {
        let body = resp.text().await.unwrap_or_default();
        let _ = channel.send(err(format!("接口返回 {status}：{}", truncate(&body, 300))));
        return Ok(());
    }

    // 按字节缓存：TCP 分片可能切断一个 UTF-8 多字节字符，
    // 必须等整行（含换行）到达后再解码，否则会出现乱码/替换符。
    let mut buf: Vec<u8> = Vec::new();
    let mut stream = resp.bytes_stream();
    let mut send = |c: Chunk| -> bool { channel.send(c).is_ok() };
    while let Some(item) = stream.next().await {
        let chunk = match item {
            Ok(b) => b,
            Err(e) => {
                let _ = send(err(format!("读取流失败：{e}")));
                return Ok(());
            }
        };
        buf.extend_from_slice(&chunk);
        // 一块 SSE = 若干行 + 一个空行。跨 TCP 分片累积，块尾为空行才处理。
        while let Some(block) = take_block(&mut buf) {
            // 同一事件的 data 可跨多行，规范上用 \n 拼接。
            let mut data: Option<String> = None;
            for line in block.split(|&b| b == b'\n') {
                let line = line.strip_suffix(b"\r").unwrap_or(line);
                if line.starts_with(b"data:") {
                    let piece = String::from_utf8_lossy(&line[5..]).trim().to_string();
                    data = Some(match data.take() {
                        Some(prev) => format!("{prev}\n{piece}"),
                        None => piece,
                    });
                }
                // 其余字段（event: / id: / 心跳注释）在 OpenAI 兼容与 Anthropic
                // 的原生流里都不携带正文，直接忽略。
            }
            let Some(payload) = data else { continue };
            if payload == "[DONE]" {
                let _ = send(done());
                return Ok(());
            }
            if let Ok(v) = serde_json::from_str::<serde_json::Value>(&payload) {
                if is_anthropic {
                    if let Some(t) = v.pointer("/delta/text").and_then(|x| x.as_str()) {
                        let _ = send(text(t.to_string()));
                    }
                    if v.get("type").and_then(|x| x.as_str()) == Some("message_stop") {
                        let _ = send(done());
                        return Ok(());
                    }
                } else if let Some(t) = v.pointer("/choices/0/delta/content").and_then(|x| x.as_str()) {
                    let _ = send(text(t.to_string()));
                }
            }
        }
    }
    let _ = send(done());
    Ok(())
}

/// 从字节缓冲中取出第一块完整 SSE 事件（若干行 + 一个空行），去掉块尾空行后返回。
///
/// 同时认 LF 块尾（`\n\n`）与 CRLF 块尾（`\r\n\r\n`）；块尾不完整时返回 None，
/// 等下一个分片再试——这保证单个 UTF-8 字符或半个 `\r\n` 不会把一行截断成乱码。
fn take_block(buf: &mut Vec<u8>) -> Option<Vec<u8>> {
    let len = buf.len();
    if len < 2 {
        return None;
    }
    for i in 0..len - 1 {
        if buf[i] != b'\n' {
            continue;
        }
        let terminus = if buf[i + 1] == b'\n' {
            Some(2usize)
        } else if buf[i + 1] == b'\r' && i + 2 < len && buf[i + 2] == b'\n' {
            Some(3)
        } else {
            None
        };
        let Some(n) = terminus else { continue };
        let block: Vec<u8> = buf.drain(..i + n).collect();
        Some(block[..block.len() - n].to_vec())
    }
    None
}

#[tauri::command]
pub async fn probe_models(provider: Provider) -> Vec<String> {
    if provider.format == "anthropic" {
        return Vec::new();
    }
    let Ok(client) = reqwest::Client::builder()
        .connect_timeout(Duration::from_secs(15))
        .build()
    else {
        return Vec::new();
    };
    let base = clean_base(&provider.baseUrl);
    let Ok(resp) = client
        .get(format!("{base}/models"))
        .header("Authorization", format!("Bearer {}", provider.apiKey))
        .send()
        .await
    else {
        return Vec::new();
    };
    if !resp.status().is_success() {
        return Vec::new();
    }
    let Ok(v) = resp.json::<serde_json::Value>().await else {
        return Vec::new();
    };
    v.pointer("/data")
        .and_then(|x| x.as_array())
        .map(|arr| {
            arr.iter()
                .filter_map(|m| m.get("id").and_then(|x| x.as_str()).map(String::from))
                .collect()
        })
        .unwrap_or_default()
}

/// 读取本地文本文件（用于把选中的文件内容附加到对话），限制 200KB。
#[tauri::command]
pub async fn read_text_file(path: String) -> Result<String, String> {
    tokio::task::spawn_blocking(move || {
        let meta = std::fs::metadata(&path).map_err(|e| format!("无法访问文件：{e}"))?;
        if meta.len() > 200_000 {
            return Err("文件过大（超过 200KB），仅支持读取较小的文本文件".to_string());
        }
        std::fs::read_to_string(&path).map_err(|e| format!("读取失败：{e}"))
    })
    .await
    .map_err(|e| format!("读取任务失败：{e}"))?
}

fn truncate(s: &str, n: usize) -> String {
    if s.chars().count() <= n {
        s.to_string()
    } else {
        s.chars().take(n).collect::<String>() + "…"
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn block_splitters_handle_lf_and_crlf() {
        let mut lf = b"data: {\"a\":1}\n\ndata: {\"b\":2}\n\n".to_vec();
        assert_eq!(
            String::from_utf8(take_block(&mut lf).unwrap()).unwrap(),
            "data: {\"a\":1}"
        );
        assert_eq!(
            String::from_utf8(take_block(&mut lf).unwrap()).unwrap(),
            "data: {\"b\":2}"
        );
        assert!(take_block(&mut lf).is_none());

        let mut crlf = b"data: {\"a\":1}\r\n\r\ndata: {\"b\":2}\r\n\r\n".to_vec();
        assert_eq!(
            String::from_utf8(take_block(&mut crlf).unwrap()).unwrap(),
            "data: {\"a\":1}"
        );
        assert_eq!(
            String::from_utf8(take_block(&mut crlf).unwrap()).unwrap(),
            "data: {\"b\":2}"
        );
    }

    #[test]
    fn block_splitters_keep_utf8_chars_intact() {
        // TCP 分片把"你"（E4 BD A0）切开，块尾不完整时不能解码，避免替换符。
        let mut buf = b"data: \"\xE4\xBD".to_vec();
        assert!(take_block(&mut buf).is_none(), "块尾未到达应等待");
        buf.extend_from_slice(b"A0\"\n\n");
        let block = take_block(&mut buf).expect("补全后可取");
        assert_eq!(String::from_utf8_lossy(&block), "data: \"你\"");
    }

    #[test]
    fn clean_base_strips_trailing_slash() {
        assert_eq!(clean_base("https://api.example.com/"), "https://api.example.com");
        assert_eq!(clean_base("https://api.example.com/v1///"), "https://api.example.com/v1");
        assert_eq!(clean_base("https://api.example.com"), "https://api.example.com");
    }
}
